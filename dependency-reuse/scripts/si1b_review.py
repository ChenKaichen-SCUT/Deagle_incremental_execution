"""One finite offline SI-1B review. Inputs are the published archives, never a live solver."""
import argparse
from array import array
from collections import Counter, defaultdict
import gc
import gzip
import json
from pathlib import Path
import subprocess

from compact43 import DenseLibrary, OVERFLOW, QUERY, UNKNOWN
from d1_identity import Keys, Model, load_rows
from d41_identity import pair_sites
from d42_events import supplement, unchanged
from d43_project_support import check, digest, first_members
from diff_d1 import compare_theory
from prepare_d3 import facts
from si1a_census import fingerprint
from si1b_review_proof import Proof
from si1b_review_space import (BASE, CASES, EVIDENCE, MATRIX, authentic, build_maps, coordinates,
                               jsonlines, read, rows, save, sign_inverse, table)


def static_models(case, old, new, prod):
    keys = Keys()
    records = [load_rows(old, capture_graph=True),load_rows(new)]
    pairs = pair_sites(*records,keys)
    control = read(prod/"control43.json").get("source_patch")
    if control:
        root = BASE/"bench"/case
        left,right,diff = root/"old"/control["file"],root/"candidate"/control["file"],root/"patch.diff"
        check(digest(left)==read(old.parent/"library.json")["inputs"][control["file"]] and
              digest(right)==control["new_sha256"] and digest(diff)==control["patch_sha256"], "source patch binding")
        supplement(records,pairs,keys,control["file"],unchanged(left.read_bytes(),right.read_bytes(),diff.read_bytes()))
    return [Model(p,keys,True,live_boundary=bool(i),recorded_queries=not i,records=records[i],site_pairs=pairs[i])
            for i,p in enumerate((old,new))]


def certify(models, mu, old, dest):
    local = [{v:2*v for v in mu},sign_inverse(mu)]
    evidence = []
    compare_theory(models,local,dest,old_rows=evidence)
    cert = dest/"declarations.txt"
    facts(old,dest,cert,graph_lines=models[0].rows["_GRAPH"],declaration_rows=evidence)
    verdict = {}
    graph = bytearray()
    with cert.open("rb") as stream:
        for line in stream:
            if line.startswith(b"D "):
                _, *key,state = line.split()
                fact = tuple(map(int,key))
                check(fact not in verdict, "duplicate fact")
                verdict[fact] = state.decode()
            elif line.startswith(b"G\t"):
                graph.extend(line[2:])
    return verdict,graph


def translation(lits, mu):
    mapped = []
    for l in lits:
        if l in (-2,-1):
            mapped.append(l)
        elif l >= 2 and l//2 in mu:
            mapped.append(mu[l//2]^(l&1))
        else:
            return None
    return mapped


def leaf_state(case, old, new, lib, proof, maps, cert, prod, out, ref):
    pool = first_members(new)
    boolean, theory = set(), set()
    hit = {k:array("i") for k in MATRIX}
    members = {k:[defaultdict(list),defaultdict(list)] for k in MATRIX}
    tally = {k:dict(Boolean=Counter(),Theory=Counter(),export_B=Counter(),export_T=Counter()) for k in MATRIX}
    masks = bytearray()
    exact_b = {int(x["occurrence"]) for x in rows(ref/"inputs42.tsv") if int(x["use"])&2}
    exact_t = {tuple(int(x[k]) for k in ("op","a","b","c")) for x in rows(ref/"facts42.tsv") if int(x["use"])&2}
    aclaims = iter(rows(prod/"input-matches.tsv"))
    with old.open("rb") as f, table(out/"boolean-leaves.tsv.gz","occurrence group slot actual_used export_support A_P1 B_P1 C_P1") as put:
        for i,line in enumerate((x for x in f if x.startswith(b"C\t")),1):
            _,s,*ls = line.split()
            clause = tuple(map(int,ls))
            node = proof.input_ids[i-1]
            kind = proof.word(proof.nodes+16*node+8)
            check(s=={1:b"B",2:b"Q",3:b"U"}.get(kind) and proof.clause(node)==clause, "Audit input content/scope at "+str(i))
            group = lib.boolean[i-1]
            used = lib.observed(0,i-1)
            check((s==b"Q")==(group==QUERY) and (s==b"U")==(group==UNKNOWN), "scope mismatch")
            slot = lib.slots[0][group] if s==b"B" else -1
            if i in exact_b:
                check(used, "exportable Boolean support omitted from UsedLeaf")
            participate = used or slot==OVERFLOW
            if used:
                boolean.update(x//2 for x in clause if x>=2)
            values = []
            bits = 0
            for j,k in enumerate(MATRIX):
                dest = translation(clause,maps[k]) if participate else None
                member = -1 if dest is None else pool.get(tuple(sorted(set(dest))),0)
                hit[k].append(member)
                bits |= (member>0)<<j
                if participate:
                    state = "matched" if member>0 else "translated_absent" if member==0 else "unmapped"
                    if used:
                        tally[k]["Boolean"][state] += 1
                    if i in exact_b:
                        tally[k]["export_B"][state] += 1
                    if member<=0:
                        members[k][0][slot].append(i)
                values.append(member)
            if participate:
                gold = next(aclaims)
                check((i,values[0])==(int(gold["occurrence"]),int(gold["P1_permanent_occurrence"])), "frozen A input differs")
                put([i,group,slot,int(used),int(i in exact_b),*values])
            masks.append(bits)
    check(next(aclaims,None) is None and len(masks)==len(lib.boolean)==len(proof.input_ids), "occurrence count")
    # Also classify graph leaves used only by scoped records. They cannot qualify a permanent birth.
    tmasks = {}
    gold = {tuple(int(r[k]) for k in ("op","a","b","c")):r for r in rows(prod/"theory-matches.tsv")}
    with table(out/"theory-leaves.tsv.gz","op a b c group slot actual_used export_support A B C") as put:
        for fact,(i,g) in lib.theory.items():
            used,slot = lib.observed(1,i),lib.slots[1][g]
            states = [cert[k][fact] for k in MATRIX]
            if fact in exact_t:
                check(used,"exportable theory support omitted from UsedLeaf")
            if used and fact[0] in (3,4) and fact[3]>=2:
                theory.add(fact[3]//2)
            tmasks[fact] = sum((state=="M")<<j for j,state in enumerate(states))
            for k,state in zip(MATRIX,states):
                if used:
                    tally[k]["Theory"][state] += 1
                if fact in exact_t:
                    tally[k]["export_T"][state] += 1
                if (used or slot==OVERFLOW) and state!="M":
                    members[k][1][slot].append(fact)
                if state=="M" and fact[0] in (3,4) and fact[3]>=2:
                    check(fact[3]//2 in maps[k],"unbound interface declaration")
            if used or slot==OVERFLOW:
                row = gold.pop(fact)
                check(states[0]==row["state"] and slot==int(row["slot"]), "frozen A theory differs")
            put([*fact,g,slot,int(used),int(fact in exact_t),*states])
    check(not gold and set(proof.facts.values())<=lib.theory.keys(), "Audit declaration outside compact registry")
    return masks,tmasks,hit,members,tally,boolean,theory


def reference(arm,tmp,tool,proof,old,new,mu,sz):
    """Second implementation of exact graph invalidation. semantic consumes the supplied fixed map."""
    d = tmp/arm
    lookup = [mu,sign_inverse(mu)]
    with (d/"vars.tsv").open("w") as f:
        for side in (0,1):
            for v in range(1,sz[side]):
                print(side,v,lookup[side].get(v,-1),"Aux","fixed",0,sep="\t",file=f)
    with (d/"selector.log").open("w") as log:
        subprocess.run([tool,proof,old,new,d/"vars.tsv",d/"declarations.txt",d,*map(str,sz),"semantic"],
                       check=True,stdout=log)
    return {int(r["ordinal"]) for r in rows(d/"catalog42.tsv") if r["eligible"]=="1"}


def birth_review(proof, lib, maps, keys, valid, hit, members, cert, expected, ref, out, quarantine):
    counts = {k:defaultdict(Counter) for k in MATRIX}
    sets = {k:[set(),set()] for k in MATRIX}
    masks = {k:[sum(1<<s for s in dom) for dom in members[k]] for k in MATRIX}
    reasons = {k:Counter() for k in MATRIX}
    gain_count = Counter()
    total = permanent = 0
    prior = rows(ref/"actual-mu-births.tsv")
    native_ids = rows(ref/"catalog42.tsv")
    def variable_detail(v,k):
        return [v,maps["A"].get(v,-1),maps[k].get(v,-1),keys.get(v)]
    with table(out/"births.tsv.gz","ordinal Audit_id family scope A_mapped A_exact A_compact B_mapped B_exact B_compact C_mapped C_exact C_compact") as put, jsonlines(out/"gains.jsonl.gz") as record:
        for (i,flags,c,bt,tt),old in zip(lib.births(),prior,strict=True):
            total += 1
            node = proof.birth_ids[i-1]
            original = next(native_ids)
            check(i==int(old["ordinal"])==int(original["ordinal"]) and node==int(original["native_id"]),"birth alignment")
            scope = "unknown" if flags&8 else "query" if flags&4 else "permanent"
            family = ("scope_only","B","T","M")[flags&3] if flags&3 or flags&12 else "B"
            check(scope==old["scope"] and family==old["class"],"birth family/scope")
            permanent += c is not None
            if c is not None:
                check(proof.clause(node)==c and all(v//2 not in quarantine for v in c), "permanent conclusion alignment")
            outcomes = {}
            for j,k in enumerate(MATRIX):
                dest = None if c is None else translation(c,maps[k])
                mapped = dest is not None
                exact = mapped and bool(valid[node] & (1<<j))
                compact = mapped and not (bt&masks[k][0] or tt&masks[k][1])
                check(not compact or exact,"compact outside exact under "+k)
                if exact: sets[k][0].add(i)
                if compact: sets[k][1].add(i)
                ft = counts[k][family]
                ft["births"] += 1
                ft[scope] += 1
                if c is not None:
                    ft["mapped"] += mapped
                    ft["exact"] += exact
                    ft["compact"] += compact
                    if not exact:
                        reasons[k]["missing_conclusion" if not mapped else "failed_actual_support"] += 1
                    elif not compact:
                        reasons[k]["group_collateral"] += 1
                outcomes[k] = (int(mapped),int(exact),int(compact))
            check(tuple(map(int,(old["mapped"],old["exact"],old["compact"])))==outcomes["A"] if c is not None else
                  old["exact"]==old["compact"]=="0","frozen A birth membership")
            check(all(i in expected[k] if outcomes[k][1] else i not in expected[k] for k in MATRIX), "independent selector mismatch")
            put([i,node,family,scope,*[n for k in MATRIX for n in outcomes[k]]])
            gains = [k for k in ("B","C") if any(outcomes[k][j]>outcomes["A"][j] for j in (1,2))]
            if not gains:
                continue
            occ,facts,nodes,edges = proof.supports(node)
            support_vars = {x//2 for x in c}
            raw = {n:proof.clause(proof.input_ids[n-1]) for n in occ}
            support_vars.update(l//2 for clause in raw.values() for l in clause if l>=2)
            support_vars.update(f[3]//2 for f in facts if f[0] in (3,4) and f[3]>=2)
            for k in gains:
                exact_gain = outcomes[k][1]>outcomes["A"][1]
                compact_gain = outcomes[k][2]>outcomes["A"][2]
                gain_count[k+"_exact"] += exact_gain
                gain_count[k+"_compact"] += compact_gain
                check(all(hit[k][n-1]>0 for n in occ) and all(cert[k][f]=="M" for f in facts), "incomplete gain support")
                # Domain is explicit even where B and T happen to share a bit number.
                dirty = {arm:{domain:[[slot,len(leaves),leaves[0]] for slot,leaves in bank.items() if tag & (1<<slot)]
                             for domain,bank,tag in zip(("B","T"),members[arm],(bt,tt))} for arm in ("A",k)}
                record(dict(map=k,ordinal=i,Audit_id=node,family=family,old_literals=c,new_literals=translation(c,maps[k]),
                            A_mapped_exact_compact=outcomes["A"],new_mapped_exact_compact=outcomes[k],
                            exact_gain=exact_gain,compact_gain=compact_gain,visited_nodes=nodes,direct_edges=edges,
                            all_B_occurrence_and_P1=[[n,hit[k][n-1]] for n in occ],all_T_declarations=facts,
                            formerly_failed_A_B=[[n,hit["A"][n-1]] for n in occ if hit["A"][n-1]<=0],
                            formerly_failed_A_T=[[f,cert["A"][f]] for f in facts if cert["A"][f]!="M"],
                            formerly_untranslatable_conclusion=[l for l in c if l//2 not in maps["A"]],
                            new_bindings_on_conclusion_or_support=[variable_detail(v,k) for v in sorted(support_vars)
                                                                if maps[k].get(v)!=maps["A"].get(v)],
                            tagged_dirty_slots_with_counts_and_first_member=dirty))
    check(next(native_ids,None) is None and len(proof.birth_ids)==total and sets["A"][0]<=sets["C"][0] and sets["A"][1]<=sets["C"][1], "C lost A")
    return dict(births=total,permanent=permanent,classes=counts,retirements=reasons,gains=gain_count,
                pre_limit={k:{"exact":len(v[0]),"compact":len(v[1])} for k,v in sets.items()},
                lost_vs_A={k:{"exact":len(sets["A"][0]-v[0]),"compact":len(sets["A"][1]-v[1])} for k,v in sets.items()})


def run(case,droot,broot,out,tmp):
    out.mkdir(parents=True)
    tmp.mkdir(parents=True)
    si = EVIDENCE/"si1b"/case
    matrix = droot/"matrix"/case
    prod = matrix/"compact-reuse/P1/native"
    old = matrix/"compact/P0/native/model.tsv"
    new = prod/"boundary.tsv"
    audit = broot/case/"compact-audit/native"
    ref = droot/"exact"/case
    selector = droot/"offline-tools/select42"
    idx = read(EVIDENCE/"d43d/raw/files.json")["files"]
    for path in (old,new,old.parent/"dense.bin",old.parent/"library.json",prod/"control43.json",selector,
                 prod/"delta/variables.tsv",prod/"effective-map.tsv",prod/"theory-matches.tsv",prod/"input-matches.tsv",
                 ref/"inputs42.tsv",ref/"facts42.tsv",ref/"catalog42.tsv",ref/"actual-mu-births.tsv",old.parent.parent/"run.json",prod.parent/"run.json"):
        authentic(path,idx,str(path.relative_to(droot)))
    bi = read(EVIDENCE/"d43b/raw/files.json")["files"]
    for path in (audit/"proof.bin",audit/"dense.bin",audit/"model.tsv",audit.parent/"run.json"):
        authentic(path,bi,"accepted/"+str(path.relative_to(broot)))
    si_index = read(EVIDENCE/"si1b/files.json")
    for key in si_index:
        if key.startswith(case+"/") and any(f"/{x}/" in key for x in ("passive","join","audit","source","shadow")):
            authentic(EVIDENCE/"si1b"/key,si_index,key)
    erounds = read(EVIDENCE/"d43e/actual-maps.json")[case]
    for e in erounds.values():
        check(e["prep_sha256"]["effective-map.tsv"]==digest(prod/"effective-map.tsv") and e["dense_sha256"]==digest(audit/"dense.bin"),
              "E map or library changed")
    check(digest(audit/"dense.bin")==digest(old.parent/"dense.bin"), "dual and production tags differ")
    lib = DenseLibrary((old.parent/"dense.bin").read_bytes())
    proof = Proof(audit/"proof.bin")
    ms = static_models(case,old,new,prod)
    sz = [m.nvars for m in ms]
    lib.validate_payload(sz[0],lib.occurrence_flags())
    info,ports,qids = [],[],[]
    mreceipt = read(si/"audit/model-audit.json")
    for j,p in enumerate((old,new)):
        side = f"P{j}"
        ctx = read(p.parent.parent/"run.json")["cwd"]
        receipt = read(si/"passive"/side/"receipt.json")
        data,interface,quarantine = coordinates(case,side,si/"passive"/side/"original.tsv.gz",p,receipt,mreceipt[side],ctx)
        check(data["boundary"][0]==sz[j], "different allocation range")
        if not j:
            check(fingerprint(audit/"model.tsv",read(audit.parent/"run.json")["cwd"])==mreceipt[side]["models"], "full Audit semantic model mismatch")
        info.append(data);ports.append(interface);qids.append(quarantine)
    maps,keys,composition = build_maps(prod,si,tmp,out,sz,ports,qids)
    check(not (qids[0] & set(maps["C"])), "C accepted quarantined atom")
    cert,expected = {},{}
    for k in MATRIX:
        d = tmp/k
        d.mkdir()
        cert[k],g = certify(ms,maps[k],old,d)
        check(g==proof.graph, "installed theory graph is not the Audit receipt")
        expected[k] = reference(k,tmp,selector,audit/"proof.bin",old,new,maps[k],sz)
    masks,theory,hit,members,tallies,b,t = leaf_state(case,old,new,lib,proof,maps,cert,prod,out,ref)
    check(not qids[0] & (b|t), "query permutation intersects UsedLeaf")
    valid = proof.exact(masks,theory)
    results = birth_review(proof,lib,maps,keys,valid,hit,members,cert,expected,ref,out,qids[0])
    proof.close()
    result = dict(case=case,status="READY_FOR_REVIEW",native_space=info,coordinate_failures=0,composition=composition,
                  variables=sz,mapped={k:len(v) for k,v in maps.items()},registry_groups=list(map(len,lib.keys)),
                  used_atoms={k:dict(boolean=len(b & m.keys()),theory=len(t & m.keys()),union=len((b|t) & m.keys())) for k,m in maps.items()},
                  used_atom_denominators=dict(boolean=len(b),theory=len(t),union=len(b|t)),actual_and_export_support=tallies,
                  dirty_slots={k:[sorted(v) for v in members[k]] for k in MATRIX},results=results,
                  independently_compared_exact=True,SAT_RUP_Closure_calls=[0,0,0],
                  sources=dict(proof_sha256=digest(audit/"proof.bin"),dense_sha256=digest(old.parent/"dense.bin"),
                               real_E_map_sha256=digest(prod/"effective-map.tsv"),E_rounds=list(erounds),
                               B_map_sha256=digest(si/"join/direct-map.tsv.gz"),offline_selector_sha256=digest(selector)))
    save(out/"results.json",result)
    print(case,results["pre_limit"],flush=True)


if __name__=="__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("d43d_restored","d43b_accepted","output","scratch"):
        p.add_argument(name,type=Path)
    p.add_argument("--case",action="append",choices=CASES)
    opts = p.parse_args()
    for case in opts.case or CASES:
        run(case,opts.d43d_restored,opts.d43b_accepted,opts.output/case,opts.scratch/case)
        gc.collect()
