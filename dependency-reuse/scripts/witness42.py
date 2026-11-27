"""Offline evidence for event correspondence and a genuinely used newly transportable birth."""
import csv,mmap,struct
from collections import Counter,defaultdict
from pathlib import Path
from d1_identity import Keys,Model,load_rows
from d41_identity import pair_sites
from d42_events import supplement,unchanged
from diff_d1 import digest

def rows(p):
    with p.open() as f:yield from csv.DictReader(f,delimiter="\t")

def example(old,arm,ordinal):
    birth=next(r for r in rows(arm/"catalog42.tsv") if int(r["ordinal"])==ordinal)
    target=int(birth["native_id"]);visited=set();stack=[target];input_ids=set();facts=set()
    with (old/"proof.bin").open("rb") as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
        at=12;sect=[]
        for w in (16,4,8,16,12,8,12,4,4,4,4,4,20):
            n=struct.unpack_from("<I",data,at)[0];sect.append((at+4,n,w));at+=4+n*w
        node=sect[0][0];edges=sect[2][0]
        while stack:
            v=stack.pop()
            if v in visited:continue
            visited.add(v);lo=struct.unpack_from("<I",data,node+16*(v-1)+4)[0]
            _,hi,kind,flags=struct.unpack_from("<4I",data,node+16*v);assert not flags&7
            if kind==1:input_ids.add(v)
            if kind==12:facts.add(v)
            stack.extend(struct.unpack_from("<I",data,edges+j*8)[0] for j in range(lo,hi))
        bases={i+1 for i in range(sect[3][1]) if struct.unpack_from("<I",data,sect[3][0]+i*16)[0] in input_ids}
        declared=[list(r[1:]) for r in (struct.unpack_from("<IIiii",data,sect[12][0]+20*i) for i in range(sect[12][1])) if r[0] in facts]
    used_inputs={int(r["occurrence"]):int(r["p1_permanent_occurrence"]) for r in rows(arm/"inputs42.tsv") if int(r["occurrence"]) in bases}
    assert all(used_inputs.values()) and set(used_inputs)==bases
    inputs={};seq=0
    with (old/"model.tsv").open() as f:
        for l in f:
            if l.startswith("C\t"):
                seq+=1
                if seq in bases:inputs[seq]=list(map(int,l.split()[2:]))
    proposals={int(r["old_var"]):r for r in rows(arm/"structure.tsv")}
    used={v//2 for lits in inputs.values() for v in lits}
    return dict(ordinal=ordinal,audit_id=target,proof_sha256=digest(old/"proof.bin"),visited_nodes=len(visited),
        matched_premises=used_inputs,facts=declared,signed_structural_witnesses={v:proposals[v] for v in sorted(proposals.keys()&used)},
        boundary_hash=digest(arm/"boundary.tsv"),import_row=next(r for r in rows(arm/"imports.tsv") if int(r["id"])==ordinal),
        uses=[r for r in rows(arm/"hits.tsv") if int(r["id"])==ordinal])

def airline(old,arm,src,dst):
    keys=Keys();raw=[load_rows(old/"model.tsv"),load_rows(arm/"boundary.tsv")];pairs=pair_sites(*raw,keys)
    z=src/"old/program.c";w=src/"candidate/program.c"
    lines=unchanged(z.read_bytes(),w.read_bytes(),(src/"patch.diff").read_bytes())
    supplement(raw,pairs,keys,"program.c",lines)
    ms=[Model(p,keys,True,recorded_queries=not s,live_boundary=bool(s),records=raw[s],site_pairs=pairs[s])
        for s,p in enumerate((old/"model.tsv",arm/"boundary.tsv"))]
    def lineage(m,ctx):
        chain=[];todo=[ctx];seen=set();sites={r[0]:r[3:6] for r in m.rows["S"]}
        contexts={r[0]:r[1:4] for r in m.rows["X"]}
        while todo:
            q=todo.pop()
            if q in seen or q not in contexts:continue
            seen.add(q);sid,birth,call=contexts[q];chain.append([q,sid,*sites[sid]]);todo.extend([birth,call])
        return chain
    peer={ms[1].event(n):n for n in ms[1].event_info if ms[1].event(n)}
    removed=set(range(1,len(z.read_text().splitlines())+1))-lines.keys();summary=Counter()
    with (dst/"events.tsv").open("w") as f:
        writer=csv.writer(f,delimiter="\t");writer.writerow(["old_event","peer","role","old_context","state","source_and_call_chain"])
        for n,ctx,role,*_ in ms[0].rows["E"]:
            identity=ms[0].event(n);p=peer.get(identity,"");chain=lineage(ms[0],ctx)
            deleted=any(src=="program.c" and ln.isdigit() and int(ln) in removed for _,_,fn,src,ln in chain)
            if deleted and p:raise ValueError(("deleted invocation transported",n,p,chain))
            why="removed_invocation_in_patch" if deleted else "matched" if p else ms[0].event_reason.get(n,"no_peer_with_certified_context")
            summary[why]+=1;writer.writerow([n,p,role,ctx,why,chain])
    literal={int(r["variable"]):int(r["peer"]) for r in rows(arm/"effective-map.tsv") if r["side"]=="0"}
    roles={int(v):role for side,v,_,role,_,_ in (l.split() for l in (arm/"delta/variables.tsv").open()) if side=="0"}
    return dict(events=summary,deleted_lines=sorted(removed),unmapped_by_role=Counter(roles[v] for v,p in literal.items() if p<0))
