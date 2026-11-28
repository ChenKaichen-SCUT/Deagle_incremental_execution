"""Independent SI-1B audit. Historical maps, inputs and UsedLeaf enter only after the signed join."""
import argparse
from collections import Counter, defaultdict
import csv
import gc
import gzip
import hashlib
import json
from pathlib import Path
import struct
from cases42 import load
from compact43 import DenseLibrary
from package_d1 import metrics
from run_d42 import compare
from run_stock import BASE, save
from si1a_census import CATEGORIES, fingerprint, getmaps, rows, scan
from si1b_catalog import Wire, check, sha
from si1b_witness import verify
from summarize_stock import interpret

DISP=("same","added","lost","different","neither")
A=BASE/"reports/evidence/si1a"
def read(p):return json.loads(p.read_bytes())
def gzrows(path):
    with gzip.open(path,"rt") as f:yield from csv.DictReader(f,delimiter="\t")
def table(path,columns,data):
    with path.open("w") as f:
        writer=csv.writer(f,delimiter="\t",lineterminator="\n");writer.writerow(columns);writer.writerows(data)
def hashes(trace):
    n=hashlib.sha256();c=hashlib.sha256();counts=Counter()
    with gzip.open(trace,"rt") as f:
        for row in f:
            t,*parts=row.rstrip("\n").split("\t")
            if t=="R":n.update(struct.pack("<II",*map(int,parts[:2])));counts[t]+=1
            elif t in ("M","H"):
                domain,_,lo,hi,op=parts[:5]
                c.update(("%d %d %s %s %s\n"%(1 if domain=="BOOL" else 2,t=="H",op,lo,hi)).encode());counts[t]+=1
    return n.hexdigest(),c.hexdigest(),counts
def costs(folder):
    r=read(folder/"run.json")
    out={k:r[k] for k in ("wall_ns","peak_rss_kib","user_s","system_s","exit_code","binary_sha256")}
    if (folder/"seal.json").exists():
        out.update({f[0]:int(f[1]) for f in (l.split() for l in (folder/"native.bin.stats").read_text().splitlines())})
        out.update(read(folder/"seal-time.json"),catalog_bytes=(folder/"native.bin").stat().st_size)
    return out

def model_gates(case,side,folder,d,source,expected,tap):
    probe=A/"probe"/f"{case}-{side}.tsv.gz"
    check(sha(probe)==read(probe.with_name(f"{case}-{side}.json"))["trace_sha256"],"untrusted allocation trace")
    alloc,cache,counts=hashes(probe)
    audit=Wire(folder/"audit"/side,source);shadow=Wire(folder/"shadow"/side,source)
    check(audit.allocation_hash==alloc,"legacy manifest allocation changed")
    observed=read(tap/"receipt.json")
    check(observed["shadow"]["allocation_ranges"]==shadow.allocation_hash,"release allocation differs from passive observation")
    # The no-manifest and older manifest encodings of the historical query are distinct.
    # The passive same-configuration comparisons test every scoped input, gate, graph and cache access.
    same_catalog=(audit.rows==shadow.rows and audit.allocated==shadow.allocated and audit.strings==shadow.strings)
    check(audit.metrics["Y"]==counts["H"]+counts["M"],"incomplete legacy cache trace")
    af=folder/"audit"/side;meta=read(af/"run.json")
    fp=fingerprint(af/"model.tsv",meta["cwd"]);check(fp==expected,"ordered original model changed")
    off,sh=folder/"off"/side,folder/"shadow"/side
    pairs=dict(stock=compare(d/"stock"/side,sh,False),frozen_off=compare(d/"off"/side,off,False),stock_off_search=compare(d/"stock"/side,off,True),
               shadow_vs_off=compare(off,sh,True))
    restarts=lambda p:[int(l.split()[1]) for l in p.read_text().splitlines()]
    check(restarts(off/"search.tsv")==restarts(sh/"search.tsv"),"native restarts differ")
    q=metrics(interpret(read(sh/"run.json"),(sh/"stdout").read_text())[0])
    return dict(models=fp,full_manifest_sha256=sha(af/"model.tsv"),allocation_order_sha256=alloc,
                legacy_cache_order_sha256=cache,legacy_same_opcode_order=(audit.cache_hash==cache),observer_rows=counts,native_atoms=audit.n-1,
                same_configuration_passive=observed,manifest_and_default_shadow_catalog_byte_fields_equal=same_catalog,audit_raw_sha256=audit.seal["body"],
                audit_row_counts=audit.metrics,checks=pairs,native=q,restarts=restarts(sh/"search.tsv"),
                timing={mode:costs(folder/mode/side) for mode in ("off","shadow","audit")})

def airline(source,jdir):
    doc=read(source/"source-catalog.json");same=[]
    needle=["pthread_mutex_lock","(","&","bookings",")",";"]
    ir=[]
    for side in range(2):
        with gzip.open(jdir/f"P{side}-ir.json.gz","rt") as f:ir.append(json.load(f))
    for side,s in enumerate(doc["sides"]):
        locks=[]
        for line,r in s["program.c"]["lines"].items():
            if r["tokens"]==needle:
                sites=[(i,ir[side]["sites"].get(i)) for i,t in ir[side]["source_sites"].items()
                    if t[0]=="program.c" and t[1]==int(line) and "pthread_mutex_lock" in t[3]]
                locks.append(dict(line=int(line),anchor=r["id"],sites=sites))
        same.append(locks)
    a,b=same;check(len(a)==2 and len(b)==1 and a[0]["anchor"]==b[0]["anchor"]!=a[1]["anchor"],"airline lock token lineage")
    accepted={s for _,s in b[0]["sites"] if s}
    check(accepted and accepted & {s for _,s in a[0]["sites"]} and not accepted & {s for _,s in a[1]["sites"]},"airline lock GOTO lineage")
    return same

def one(case,matrix,joins,restored,taps,dest):
    dest.mkdir(exist_ok=True,parents=True);folder=matrix/case;jdir=joins/case
    source=folder/"source";d=restored/"matrix"/case
    signed={int(r["old_variable"]):(int(r["positive_image"]),int(r["witness_key"])) for r in gzrows(jdir/"direct-map.tsv.gz")}
    witness=verify(folder/"shadow",source,jdir)
    check(witness["accepted"]==len(signed),"wrong witness denominator")
    save(dest/"witness-audit.json",witness)
    new=[{v:p for v,(p,k) in signed.items()},{p//2:2*v+(p&1) for v,(p,k) in signed.items()}]
    mu,pre=getmaps(d/"compact-reuse/P1/native")
    lib=DenseLibrary((d/"compact/P0/native/dense.bin").read_bytes())
    exact={int(v["ordinal"]):v for v in rows(restored/"exact"/case/"actual-mu-births.tsv")}
    old_index=read(A/"source-sha256.json")[case]
    check(all(sha(restored/p)==h for p,h in old_index.items()),"SI-1A historical archive checksum")
    gold=read(A/"frozen-model-fingerprints.json")[case]
    output=[];why=[];gen=[];cache_rows=[];samples={};gates={};layout_summary=[]
    for i,side in enumerate(("P0","P1")):
        g=model_gates(case,side,folder,d,source,gold[side],taps/case/side);gates[side]=g
        oldmodel=d/("compact/P0/native/model.tsv" if not i else "compact-reuse/P1/native/boundary.tsv")
        detail={};scan(case,side,oldmodel,A/"probe"/f"{case}-{side}.tsv.gz",None if i else lib,mu[i],pre[i],exact,detail)
        states={int(r["variable"]):(r["state"],r["reason"],int(r["cached_direct_atom"]),int(r["missing_cache_role"]),int(r["cached_descendant_atom"]))
                for r in gzrows(jdir/f"P{i}-atoms.tsv.gz")}
        if case=="fib-snapshot-11":
            alpha=read(BASE/"reports/evidence/d42/encoding.json")[side]["alpha"]
            labels={int(v) for v in alpha["permutation"]}|set(alpha["permutation"].values())
            check(not labels.intersection(new[i]) and not any(mu[i][v]>=2 for v in labels),"old/default query coordinates affect actual mapped atoms")
            check(not labels.intersection(detail["scopes"].get("used_union",set()) | detail["scopes"].get("permanent_conclusion",set())),"query permutation reaches permanent supports")
            gates[side]["legacy_query_alignment"]=dict(certified_all_scopes=alpha["exact_all_scopes"],
                moved_query_atoms=len(labels),mapped_on_either_arm=0,used_or_permanent_atoms=0)
        subset=detail["scopes"];categories=detail["categories"];flags=detail["flags"];allocation=detail["allocation"]
        check(set(states)==set(categories)==set(mu[i]),"missing per-atom classification")
        check({v for v,t in states.items() if t[0]=="bound"}==new[i].keys(),"class/domain mismatch")
        scopes={"all":subset["all"],"theory_interface":flags["RF"]|flags["Guard"]}
        if not i:scopes.update(used_union=subset["used_union"],permanent_conclusion=subset["permanent_conclusion"])
        for scope,vs in scopes.items():
            breakdown=defaultdict(Counter);reasons=Counter();generated=Counter();cache_summary=Counter()
            for v in vs:
                cat=categories[v];old=mu[i][v];after=new[i].get(v,-1)
                disposition=("different" if old>=2 and after>=2 and old!=after else "same" if old>=2 and after>=2 else
                             "lost" if old>=2 else "added" if after>=2 else "neither")
                breakdown[cat][disposition]+=1
                st,reason,cached,missing,descendant=states[v];reasons[cat,st,reason]+=1
                if descendant and st!="bound":cache_summary["unmapped_including_nested_cache_atoms"]+=1
                if v in flags["later_cache_hit_other_owner_interval"] and st!="bound":cache_summary["unmapped_in_historical_other_owner_allocation_interval"]+=1
                if cached and st!="bound":cache_summary["unmatched_direct_values_of_reused_templates"]+=1
                if missing and st!="bound":cache_summary["unmatched_missing_direct_cache_origin"]+=1
                if not i and scope=="used_union" and old<2:
                    generated[cat,disposition,allocation[v][0],allocation[v][1]]+=1
                if cat=="pointer_aggregate" and st!="bound":
                    cause="LAYOUT_INCOMPATIBLE" if "LAYOUT_INCOMPATIBLE" in reason else "UNSUPPORTED_ORIGIN_OR_PEER" if st=="unsupported" else "CONFLICT"
                    cache_summary[cause]+=1
                if not i and disposition in ("added","different") and (scope,cat,disposition) not in samples:
                    samples[scope,cat,disposition]=dict(old_atom=v,old_image=old,new_positive_image=after,witness=signed[v][1],
                                                        allocation_site=allocation[v][0],operation=allocation[v][1])
            for cat in CATEGORIES:
                tally=breakdown[cat];output.append([case,side,scope,cat,*[tally[k] for k in DISP],sum(tally.values())])
            check(sum(sum(c.values()) for c in breakdown.values())==len(vs),"bad domain total")
            why.extend([case,side,scope,*key,n] for key,n in sorted(reasons.items()))
            gen.extend([case,*key,n] for key,n in sorted(generated.items()))
            cache_rows.extend([case,side,scope,k,v] for k,v in sorted(cache_summary.items()))
        del detail,states;gc.collect()
    if case=="airline_reservations_6":save(dest/"deleted-lock.json",airline(source,jdir))
    table(dest/"coverage.tsv",["case","side","scope","category",*DISP,"total"],output)
    table(dest/"causes.tsv",["case","side","scope","category","state","reason","atoms"],why)
    table(dest/"used-old-gaps.tsv",["case","category","disposition","native_allocation_site","opcode","atoms"],gen)
    table(dest/"cache-layout-limits.tsv",["case","side","scope","measure","atoms"],cache_rows)
    save(dest/"examples.json",{"/".join(k):v for k,v in samples.items()})
    save(dest/"model-audit.json",gates)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("case",choices=list(load()))
    for k in ("matrix","joins","restored","taps","dest"):p.add_argument(k,type=Path)
    a=p.parse_args();one(a.case,a.matrix,a.joins,a.restored,a.taps,a.dest)
