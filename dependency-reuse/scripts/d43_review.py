"""Summarize all births and independently check selected supports directly against raw Audit pivots."""
import argparse
from array import array
from bisect import bisect_left
from collections import Counter, defaultdict
import csv
import gzip
import json
import math
import mmap
from pathlib import Path
import struct

from d43_project_support import (BASE, FACT, PAIR, PLAN, SOURCE, STATE, check, digest,
                                 frozen_read, save, tsv, zipped)
from run_d4 import property_contract
from run_d42 import compare

CLASSES = ("B","M","T","QUERY","UNKNOWN","QUERY+UNKNOWN")
LEVELS = ("exact","group","small","large")
UNIVERSES = ("audit","all")
FIELDS = ("b_leaves","t_leaves","q_leaves","u_leaves","b_groups","t_groups",
          "b_small","t_small","b_large","t_large")
ATTR = ("scope","conclusion","actual_leaf","same_group","slot_collision","eligible")


def family(flags,b):
    if flags&5:
        return "QUERY+UNKNOWN" if flags&2 else "UNKNOWN"
    if flags&2:
        return "QUERY"
    return ("M" if b else "T") if flags&8 else "B"


def decisions(mask,scope,mapped,universe):
    dirt = (mask>>(4+6*universe))&63
    first = "scope" if scope else "conclusion" if not mapped else "actual_leaf" if mask&15 else None
    group = first or ("same_group" if dirt&3 else None)
    return [first or "eligible", group or "eligible",
            group or ("slot_collision" if dirt&12 else "eligible"),
            group or ("slot_collision" if dirt&48 else "eligible")]


def quantiles(hist):
    n=sum(hist.values())
    ordered=sorted(hist.items())
    def rank(p):
        k=math.ceil(p*n)
        for x,c in ordered:
            k-=c
            if k<=0:
                return x
    return [n,ordered[0][0],rank(.5),rank(.9),rank(.95),rank(.99),ordered[-1][0]]


def write_tsv(path,header,rows):
    with path.open("w",newline="") as f:
        out=csv.writer(f,delimiter="\t",lineterminator="\n")
        out.writerow(header)
        out.writerows(rows)


def incidence(out):
    with gzip.open(out/"leaves.bin.gz","rb") as f:
        data=f.read()
    check(data[:8]==b"D43LEF1\0","registry header")
    nb,nt=struct.unpack_from("<II",data,8)
    off=16+PAIR.size*nb
    check(len(data)==off+(16+PAIR.size)*nt,"registry size")
    slots={}
    with gzip.open(out/"groups.tsv.gz","rt") as f:
        for row in csv.DictReader(f,delimiter="\t"):
            gid=int(row["id"])
            key=json.loads(row["canonical_key"])
            slots[gid]=(int(row["large"]),key[1]=="fallback",key[0])
    domains={}
    winners={}
    fact_idx={}
    for u in UNIVERSES:
        with gzip.open(out/f"used-{u}.bin.gz","rb") as f:
            bits=f.read()
        check(bits[:8]==b"D43USE1\0" and struct.unpack_from("<II",bits,8)==(nb,nt) and
              len(bits)==16+(nb+7)//8+(nt+7)//8,"U bitmap shape")
        for dom,n,base,step,bits_at in (("B",nb,16,8,16),("T",nt,off,24,16+(nb+7)//8)):
            groups=Counter()
            dirty=set()
            reg=0
            for i in range(n):
                pos=base+step*i
                if dom=="T":
                    fact=FACT.unpack_from(data,pos)
                    fact_idx[fact]=i+1
                    pos+=16
                group,slot,status,use=PAIR.unpack_from(data,pos)
                is_used=status<5 and (u=="all" or use&2!=0)
                check(bool(is_used)==bool(bits[bits_at+i//8]&(1<<(i%8))),"U bit content")
                if not is_used:
                    continue
                check(slots[group][0]==slot and slots[group][2]==dom,"group domain/slot")
                reg+=1;groups[group]+=1
                if status:
                    dirty.add(group)
                    for level,anchor in (("group",group),("small",slot%256),("large",slot)):
                        winners.setdefault((u,dom,level,anchor),(i+1,group,status))
            stats={"leaves":reg,"groups":len(groups),"dirty_groups":len(dirty),
                   "fallback_groups":sum(slots[g][1] for g in groups),
                   "fallback_leaves":sum(v for g,v in groups.items() if slots[g][1])}
            for level,cap in (("small",256),("large",1024)):
                counts=Counter(slots[g][0]%cap for g in groups)
                stats[level]=dict(occupied=len(counts),collision_slots=sum(v>1 for v in counts.values()),
                    groups_in_collisions=sum(v for v in counts.values() if v>1),extra_groups=len(groups)-len(counts),
                    max_groups=max(counts.values(),default=0),dirty_slots=len({slots[g][0]%cap for g in dirty}))
            domains[u,dom]=stats
    def leaf(dom,i):
        pos=16+8*(i-1) if dom=="B" else off+24*(i-1)+16
        return PAIR.unpack_from(data,pos)
    return domains,winners,leaf,fact_idx


def independent(proof,samples,leaf,fact_idx,winners,extra_dirty):
    """Separate raw binary walk, materializing distinct leaves for one diagnostic birth at a time."""
    result=[]
    with proof.open("rb") as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
        check(data[:8]==b"DEAGD3\x02\0","independent Audit format")
        at=12;sections=[]
        for size in (16,4,8,16,12,8,12,4,4,4,4,4,20):
            n,=struct.unpack_from("<I",data,at);sections.append((at+4,n));at+=4+n*size
        node,_,edge,raw=sections[:4]
        input_nodes=array("I",(r[0] for r in struct.iter_unpack("<4I",data[raw[0]:raw[0]+16*raw[1]])))
        start,count=sections[12]
        facts={r[0]:fact_idx[tuple(r[1:])] for r in struct.iter_unpack("<IIiii",data[start:start+count*20]) if r[1]<=7}
        for ordinal,(r,tags) in sorted(samples.items()):
            seen=bytearray(node[1])
            stack=[r["audit_id"]];seen[stack[0]]=1
            true={"B":set(),"T":set()};q=set();unknown=set()
            while stack:
                i=stack.pop()
                _,end,kind,_=struct.unpack_from("<4I",data,node[0]+16*i)
                if kind in (1,2,3):
                    j=bisect_left(input_nodes,i)
                    check(input_nodes[j]==i,"direct walk input directory")
                    if kind==1:true["B"].add(j+1)
                    elif kind==2:q.add(i)
                    else:unknown.add(i)
                elif kind==12:true["T"].add(facts[i])
                elif kind in (0,7,8,9,11):unknown.add(i)
                begin=struct.unpack_from("<I",data,node[0]+16*(i-1)+4)[0] if i else 0
                for e in range(begin,end):
                    p,=struct.unpack_from("<I",data,edge[0]+8*e)
                    check(p<i,"non-topological Audit edge")
                    if not seen[p]:
                        stack.append(p);seen[p]=1
            widths=[len(true["B"]),len(true["T"]),len(q),len(unknown)]
            vals={d:[(idx,*leaf(d,idx)) for idx in sorted(ids)] for d,ids in true.items()}
            for level in ("group","small","large"):
                for d in ("B","T"):
                    widths.append(len({(g if level=="group" else s%256 if level=="small" else s)
                                       for _,g,s,_,_ in vals[d]}))
            check(widths==[r[k] for k in FIELDS],"direct-walk distinct widths")
            mask=0;witness={}
            for d,rows in vals.items():
                di=int(d=="T")
                for idx,g,s,state,use in rows:
                    if state:mask|=1<<(state-1)
                    if not r["flags"]&7:check(use&2,"actual leaf missing from U_audit")
                    for ui,u in enumerate(UNIVERSES):
                        for li,(label,x) in enumerate((("group",g),("small",s%256),("large",s))):
                            bad=winners.get((u,d,label,x))
                            if bad:
                                mask|=1<<(4+6*ui+2*li+di)
                                if not r["mask"]&15 and (label=="group" or bad[1]!=g):
                                    witness.setdefault(u+"_"+d+"_"+label,dict(actual_leaf=idx,actual_group=g,
                                      dirty_leaf=bad[0],dirty_group=bad[1],dirty_state=STATE[bad[2]],bucket_or_group=x))
            check(mask==r["mask"],"direct-walk bad supports")
            overlap=sorted(extra_dirty.intersection(v[2] for v in vals["T"]))
            result.append(dict(ordinal=ordinal,audit_id=r["audit_id"],sample_roles=tags,widths=widths,
                               verified_mask=mask,unrelated_leaf_examples=witness,
                               additional_dirty_T_slots_if_entire_static_catalogue_registered=overlap))
    return result


def report(d42,root,out,do_walk=True):
    idx=json.loads(SOURCE.read_bytes())["files"]
    rows=[];groups=[];widths=[];dist=[];classes=[];causes=[];joint=[];samples_out={}
    properties={};extra_files={};checks={};width_hist={};candidate_rows=[]
    for case in PLAN["cases"]:
        folder=root/case
        doms,winners,leaf,facts=incidence(folder)
        for (u,dom),v in doms.items():
            for level in ("small","large"):
                values=v[level]
                groups.append([case,u,dom,level,*[v[k] for k in ("leaves","groups","dirty_groups","fallback_groups","fallback_leaves")],
                               *[values[k] for k in ("occupied","collision_slots","groups_in_collisions","extra_groups","max_groups","dirty_slots")]])
        run=d42/"functional"/case/"1"
        def verified(path):
            return frozen_read(path,d42,idx,extra_files)
        src=folder/"births.tsv.gz"
        all_class=Counter();counts=Counter();multi=Counter();sample_roles={}
        summary_hits=Counter()
        # First decide every birth from pure projection; the subsequent join reads P1 hit receipts.
        masks=[]
        guaranteed=[]
        with gzip.open(src,"rt") as f:
            for raw in csv.DictReader(f,delimiter="\t"):
                r={k:int(v) for k,v in raw.items()}
                fam=family(r["flags"],r["has_b"])
                scope=r["flags"]&7
                ordinal=r["ordinal"]
                mask=r["mask"]
                check(ordinal==len(masks)+1,"birth ordinal")
                all_class[fam,"births"]+=1
                if r["mapped"]:all_class[fam,"translated"]+=1
                data=[r[k] for k in FIELDS]
                for label,val in zip((*FIELDS,"leaf_total","group_total","small_total","large_total"),
                                     (*data,sum(data[:4]),sum(data[4:6]),sum(data[6:8]),sum(data[8:10]))):
                    for cl in (fam,"ALL"):
                        width_hist.setdefault((case,cl,label),Counter())[val]+=1
                selected=defaultdict(list)
                for ui,u in enumerate(UNIVERSES):
                    dec=decisions(mask,scope,r["mapped"],ui)
                    for lvl,reason in zip(LEVELS,dec):
                        counts[u,lvl,fam,reason]+=1
                        if reason=="eligible":selected[u].append(lvl)
                    for label,flag in (("query",r["flags"]&2),("unknown",r["flags"]&5),("unmapped_conclusion",not r["mapped"]),
                        ("actual_B_unmapped",mask&1),("actual_B_absent",mask&2),("actual_T_changed",mask&4),("actual_T_unknown",mask&8)):
                        if flag:multi[u,label]+=1
                    for li,lvl in enumerate(LEVELS[1:]):
                        for di,d in enumerate(("B","T")):
                            if mask&(1<<(4+6*ui+2*li+di)):multi[u,lvl+"_intersects_"+d]+=1
                    for role in (fam, u+"_"+dec[1], u+"_"+dec[2], u+"_"+dec[3]):
                        sample_roles.setdefault(role,r)
                    if fam=="M" and u=="all" and dec[3]=="eligible":
                        guaranteed.append(r)
                if ordinal==1:sample_roles["first"]=r
                sample_roles["last"]=r
                masks.append((fam,selected))
        source=run/"reuse/P1/native"
        imports={int(r["id"]):r for r in tsv(verified(source/"imports.tsv"))}
        hits={int(r["id"]) for r in tsv(verified(source/"hits.tsv"))}
        expected_hits={i for i,r in imports.items() if any(int(r[k]) for k in ("watch_unit","watch_conflict","analyze","minimize"))}
        check(hits==expected_hits,"D4.2 hit receipts disagree")
        exact={i for i,(_,s) in enumerate(masks,1) if "exact" in s["audit"]}
        check(exact==imports.keys() and len(exact)<=512,"original candidate ordinals")
        for i in sorted(exact):
            fam,selected=masks[i-1]
            imp=imports[i]
            candidate_rows.append([case,i,fam,int(i in hits),*[imp[k] for k in
                ("watch_unit","watch_conflict","analyze","minimize")],
                *[int(level in selected[u]) for u in UNIVERSES for level in LEVELS[1:]]])
        for i in hits:
            fam,selected=masks[i-1]
            check(fam==imports[i]["family"],"family differs from native import receipt")
            for u,levels in selected.items():
                for level in levels:summary_hits[u,level,fam]+=1
        for u in UNIVERSES:
            for lvl in LEVELS:
                rows.append([case,u,lvl,len(masks),*[counts[u,lvl,cl,"eligible"] for cl in ("B","M","T")],
                             *[summary_hits[u,lvl,cl] for cl in ("B","M","T")]])
                for reason in ATTR:
                    causes.append([case,u,lvl,reason,*[counts[u,lvl,cl,reason] for cl in CLASSES]])
                check(sum(counts[u,lvl,cl,a] for cl in CLASSES for a in ATTR)==len(masks),"retirement denominator")
            for (uu,label),c in sorted(multi.items()):
                if uu==u:joint.append([case,u,label,c])
        for cl in CLASSES:
            classes.append([case,cl,all_class[cl,"births"],all_class[cl,"translated"]])
        sample={}
        for role,r in sample_roles.items():
            sample.setdefault(r["ordinal"],(r,[]))[1].append(role)
        for r in guaranteed:
            sample.setdefault(r["ordinal"],(r,[]))[1].append("all_large_mixed")
        extra_dirty=set(json.loads((folder/"inputs.json").read_bytes())["unregistered_dirty_large_slots"])
        if do_walk:samples_out[case]=independent(run/"reference/P0/native/proof.bin",sample,leaf,facts,winners,extra_dirty)
        props={}
        for side,reference in (("P0","reference"),("P1","reuse")):
            archived=run/"stock"/side
            observed=run/reference/side
            for d in (archived,observed):
                for fn in ("run.json","stdout","result.json"):verified(d/fn)
            cmp=compare(archived,observed,False)
            native=json.loads((archived/"result.json").read_bytes())
            spec=json.loads((archived/"run.json").read_bytes())
            props[side]=dict(argv=spec["argv"][1:],target=spec["target"],inputs=spec["input_sha256"],limits=spec["limits"],
                             stock=property_contract(native),trace_comparison=cmp["traces"],
                             reference_arm=reference)
        properties[case]=props
        checks[case]=dict(birth_catalogue_agreements=len(masks),exact_candidates=len(exact),distinct_D42_hits=len(hits),
                          signed_subset_violations=0,universe_order_violations=0,
                          direct_walk_samples=len(sample) if do_walk else 0)
    for (case,cl,metric),hist in width_hist.items():
        widths.append([case,cl,metric,*quantiles(hist)])
        for x,c in sorted(hist.items()):dist.append([case,cl,metric,x,c])
    write_tsv(out/"retention.tsv",["case","U","level","all_births","B","M","T","hit_B","hit_M","hit_T"],rows)
    write_tsv(out/"candidates.tsv",["case","ordinal","class","previous_hit","D42_unit","D42_conflict","D42_analyze",
        "D42_minimize",*[u+"_"+l for u in UNIVERSES for l in LEVELS[1:]]],candidate_rows)
    write_tsv(out/"groups.tsv",["case","U","domain","capacity","leaves","groups","dirty_groups","fallback_groups","fallback_leaves",
        "occupied_slots","collision_slots","groups_in_collisions","extra_groups","max_groups_per_slot","dirty_slots"],groups)
    write_tsv(out/"widths.tsv",["case","class","metric","n","min","p50","p90","p95","p99","max"],widths)
    with zipped(out/"width-histogram.tsv.gz") as f:
        f.write(b"case\tclass\tmetric\twidth\tfrequency\n")
        for item in dist:f.write(("\t".join(map(str,item))+"\n").encode())
    write_tsv(out/"classes.tsv",["case","class","births","translated"],classes)
    write_tsv(out/"retirements.tsv",["case","U","level","exclusive_reason",*CLASSES],causes)
    write_tsv(out/"overlaps.tsv",["case","U","nonexclusive_indicator","births"],joint)
    save(out/"independent-samples.json",samples_out)
    save(out/"properties.json",properties)
    save(out/"checks.json",checks)
    save(out/"reference-files.json",extra_files)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--d42",type=Path,required=True)
    p.add_argument("--projection",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    report(a.d42,a.projection,a.out)
