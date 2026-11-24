"""Executable transcriptions of TACAS Fig. 1 and FM Fig. 3(b)."""
from dataclasses import replace
from functools import lru_cache

from candidate import Branch, explain, saturate
from reference import Event, Graph, strict_models


def history(threads, reads, name):
    events, po = [], []
    for i, thread in enumerate(threads):
        for key in thread:
            events.append(Event(key,str(i),key[0].upper(),key[1]))
        po.extend(zip(thread,thread[1:]))
    return Graph(tuple(events),tuple(po),(),tuple(reads),name)


def examples():
    tacas = history([["wx1","wy1","rx3"],["wy2","ry3","wx2"]],
                     [("wx1","rx3"),("wy1","ry3")],"TACAS 2025 Fig. 1")
    fm = history([["rz3","wt2","rs3"],["rz4","ws2","rt3"],["wx1","wy1","wz1"],
                  ["wt1","ws1","wz2"],["rz5","wy2","rx3"],["rz6","wx2","ry3"]],
                 [("wz1","rz3"),("wz1","rz4"),("wz2","rz5"),("wz2","rz6"),
                  ("wx1","rx3"),("wy1","ry3"),("ws1","rs3"),("wt1","rt3")],
                 "FM 2026 Fig. 3(b)")
    return tacas,fm


def prefix_decide(graph):
    """Independent topological interleaving by thread PCs with last-write memory.

    Specialized to unconditional, fixed RF, no section or extra cross-thread PO.
    Memoization identifies prefixes with identical future transitions.
    """
    assert not graph.apo and all(e.guard=="1" for e in graph.events)
    threads = {}
    for e in graph.events:
        threads.setdefault(e.thread,[]).append(e)
    threads = list(threads.values())
    assert set(graph.po)=={(a.key,b.key) for t in threads for a,b in zip(t,t[1:])}
    want = {r:w for w,r in graph.rf}
    assert len(want)==len(graph.rf)
    addrs = sorted({e.addr for e in graph.events})
    @lru_cache(None)
    def walk(pcs,last):
        if all(pc==len(t) for pc,t in zip(pcs,threads)):
            return ()
        for i,(pc,t) in enumerate(zip(pcs,threads)):
            if pc==len(t):
                continue
            e = t[pc]
            j = addrs.index(e.addr)
            if e.op=="R" and last[j]!=want[e.key]:
                continue
            next_last = list(last)
            if e.op=="W":
                next_last[j]=e.key
            pos = list(pcs)
            pos[i]+=1
            suffix=walk(tuple(pos),tuple(next_last))
            if suffix is not None:
                return (e.key,)+suffix
        return None
    witness=walk((0,)*len(threads),tuple("init:"+a for a in addrs))
    return {"strict_order":witness,"distinct_prefix_states":walk.cache_info().currsize}


def native_input(graph):
    def symbol(k):
        return k[1]+"#"+k[2:]
    lines = ["write "+symbol(e.key) for e in graph.events if e.op=="W"]
    lines += ["po "+symbol(a)+" "+symbol(b) for a,b in graph.po]
    lines += ["rf "+symbol(a)+" "+symbol(b) for a,b in graph.rf]
    return "\n".join(lines)+"\n"


def check():
    tacas,fm = examples()
    tc,_=saturate(Branch(tacas,(),tacas.rf))
    exact=strict_models(tacas)
    assert exact and all(seq.index("rx3")<seq.index("wx2") for _,_,seq in exact)
    fm_facts,_=saturate(Branch(fm,(),fm.rf))
    assert not any(a==b for a,b in fm_facts)
    strict=prefix_decide(fm)
    assert strict["strict_order"] is None
    forced=[]
    for edge in (("wz1","wz2"),("wz2","wz1")):
        g=replace(fm,po=fm.po+(edge,))
        facts,_=saturate(Branch(g,(),g.rf),fm_facts)
        cycle=next(p for p in sorted(facts) if p[0]==p[1])
        forced.append({"extra_order":edge,"cycle_proof":explain(facts,cycle)})
    return {"tacas":{"input":tacas.document(),"required_order":["rx3","wx2"],
                     "paper_fig3_omits_order":True,"proof":explain(tc,("rx3","wx2")),
                     "strict_orders":len(exact),"example":min(exact)[2]},
            "fm":{"input":fm.document(),"positive_closure_pairs":len(fm_facts),
                  "positive_closure_contains_cycle":False,"strict":strict,"both_ws_choices":forced}}
