"""Trace unresolved operands on actual failed conclusions, plus the competing bookings#9 SSA definitions."""
import argparse
from collections import defaultdict
from pathlib import Path
from d1_identity import load_rows

from run_stock import save


def contexts(model,symbol,kind="V"):
    ctx={r[0]:r[1:] for r in model["X"]}
    sites={r[0]:dict(function=r[3],source=r[4],line=r[5],status=r[2]) for r in model["S"]}
    def frame(i):
        if i not in ctx:return dict(context=i)
        site,birth,caller,*loops=ctx[i]
        return dict(context=i,site=sites[site],thread_origin=birth,call_origin=caller,
                    iterations=[(sites[s],n) for s,n in zip(loops[::2],loops[1::2])])
    result=[]
    for name,i,role,obj,typ,storage in model[kind]:
        if name!=symbol:continue
        trail=[];at=i
        while at in ctx:
            trail.append(frame(at));at=ctx[at][2]
        result.append(dict(symbol=name,role=role,object=obj,type=typ,storage=storage,frames=trail))
    return result


def explain(native,pair,sample):
    model=load_rows(native);gates=defaultdict(list);atoms=defaultdict(list);bindings=defaultdict(list)
    var={}
    with (pair/"delta/variables.tsv").open() as f:
        for row in f:
            side,v,to,role,why,_=row.split()
            if side!="0":break
            var[int(v)]=(int(to),role,why)
    with native.open() as f:
        for row in f:
            if row.startswith("G\t"):
                _,op,target,*xs=row.split();gates[int(target)//2].append((op,int(target),list(map(int,xs))))
    for sym,t,bit,lit in model["A"]:atoms[int(lit)//2].append([sym,t,bit,lit])
    for event,raw in model["GUARD"]:bindings[int(raw)//2].append(["guard",event,raw])
    for tag,a,b,lit,*_ in model["EDGE"]:
        if tag.lower()=="rf":bindings[int(lit)//2].append(["rf",a,b,lit])
    def trace(v,seen):
        if v in seen:return dict(variable=v,repeat=True)
        seen.add(v);peer,role,reason=var[v];entry=dict(variable=v,peer=peer,role=role,reason=reason)
        if peer>=0:return entry
        if gates[v]:
            entry["definitions"]=gates[v]
            bad=[n//2 for op,t,xs in gates[v] for n in xs if n>=2 and var[n//2][0]<0]
            if bad:entry["first_unmatched_operand"]=trace(bad[0],seen)
        if atoms[v]:
            entry["atoms"]=atoms[v][:3]
            entry["definitions_at_execution"]=[r for sym,*_ in atoms[v][:2] for r in contexts(model,sym)][:4]
        if bindings[v]:
            entry["event_bindings"]=bindings[v][:3]
            entry["event_origins"]=[r for row in bindings[v][:2] for e in row[1:-1] for r in contexts(model,e,"E")][:4]
        return entry
    return {role:dict(birth_ordinal=r["birth_ordinal"],clause=r["signed_clause"],
                      dependency=trace(r["variable"],set())) for role,r in sample.items()}


def main():
    import json
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("matrix","audit","out"):p.add_argument(n,type=Path)
    a=p.parse_args();report={}
    for c,r in json.loads((a.audit/"audit.json").read_text()).items():
        base=a.matrix/c;old=base/"AB/P0/native/model.tsv";new=base/"AB/P1/native"
        report[c]=explain(old,new,r["mapping"]["cross-d41"]["first_failed_conclusions"])
        if c=="airline_reservations_6":
            report[c]["same_spelling_bookings_9"]={k:contexts(load_rows(path),"bookings#9")
                                                for k,path in (("P0",old),("P1",new/"boundary.tsv"))}
    save(a.out,report)


if __name__=="__main__":main()
