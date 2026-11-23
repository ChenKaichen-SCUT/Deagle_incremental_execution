"""Small independent schedule enumerations for the published abstract atomic actions."""
import itertools
from functools import lru_cache
from math import comb


def fibonacci(n,bias):
    states={(0,0,1,1)}
    for _ in range(2*n):
        step=set()
        for l,r,x,y in states:
            if l<n:step.add((l+1,r,x+y+bias,y))
            if r<n:step.add((l,r+1,x,x+y))
        states=step
    return max(max(x,y) for _,_,x,y in states)


def sales(n,capacity,atomic):
    @lru_cache(None)
    def visit(waiting,reads,sold):
        if not waiting and not reads:return frozenset([sold])
        totals=set()
        if waiting:
            if atomic:totals.update(visit(waiting-1,(),min(capacity,sold+1)))
            else:totals.update(visit(waiting-1,tuple(sorted((*reads,sold))),sold))
        for i,observed in enumerate(reads):
            if i and reads[i-1]==observed:continue
            totals.update(visit(waiting,reads[:i]+reads[i+1:],observed+1 if observed<capacity else sold))
        return frozenset(totals)
    return sorted(visit(n,(),0))


def independent():
    out={}
    for name,n,limit in (("fib_updates",4,55),("fib_updates_8",8,2584)):
        old,new=fibonacci(n,1),fibonacci(n,0)
        assert old>limit and new==limit
        out[name]={"schedules":comb(2*n,n),"old_max_component":old,"candidate_max_component":new,"bound":limit}
    for name,n in (("airline_reservations",4),("airline_reservations_6",6)):
        a,b=sales(n,n-1,False),sales(n,n-1,True)
        assert min(a)<n-1 and b==[n-1]
        out[name]={"old_reachable_final_sold":a,"candidate_reachable_final_sold":b,"capacity":n-1}
    return out


def retained_projection(name,trace):
    steps=[s for s in trace["steps"] if s["type"]=="assignment" and s["source"].get("file")=="program.c"]
    if name=="batch_retained":
        values=[(s.get("thread"),s.get("value",{}).get("data")) for s in steps if s.get("lhs")=="shipped_units"]
        return values==[(1,"10")]
    if name!="partial_counter":return None
    sites={("record_left","counter","16"):"L",("record_split","snapshot","5"):"R",("record_split","counter","9"):"W"}
    observed=[]
    for s in steps:
        key=(s["source"].get("function"),s.get("lhs"),str(s["source"].get("line")))
        if key in sites:
            op=sites[key]
            observed.append((op,s["thread"],int(s["value"]["data"])))
    for order in itertools.permutations("LRW"):
        if order.index("R")>order.index("W"):continue
        counter=0
        result=[]
        for op in order:
            if op=="L":
                counter+=1
                result.append((op,1,counter))
            elif op=="R":
                snapshot=counter
                result.append((op,2,snapshot))
            else:
                counter=snapshot+1
                result.append((op,2,counter))
        if counter!=2 and observed==result:return True
    return False
