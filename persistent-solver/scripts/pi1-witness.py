"""Check the actual persistent local assignment and event order against the sealed model and program."""
import collections
import gzip
import io
import json
import re
import sys
from pathlib import Path
from frozen import blob, require, save


def inspect(repo,work,case,row):
    directory=work/"fixtures"/case
    model=directory/"P0.txn"
    meta=json.loads((directory/"P0-directory.json").read_text())
    assignment=row["assignment"];order=row["order"]
    def val(p):
        p=int(p)
        if p<0:return p==-1
        require(assignment[p//2] in "01","undefined interface")
        return (assignment[p//2]=="1") != bool(p&1)
    words={}
    for name,kind,bit,literal in meta["assignment_bits"]:
        words[name]=words.get(name,0)|(int(val(literal))<<int(bit))
    names=[];guards={};edges=[];blocks=[];checked=0;info={}
    for line in model.open():
        f=line.rstrip("\n").split("\t")
        if f[0] in ("B","Q"):
            require(any(val(p) for p in f[1:]),"falsified original input")
            checked+=1
        elif f[0]=="ASSUME":require(val(f[1]),"failed query assumption")
        elif f[0]=="NODE":names.append(f[1]);info[f[1]]=f[2:]
        elif f[0]=="GUARD":guards[names[int(f[1])]]=val(f[2])
        elif f[0]=="BLOCK":blocks.append([names[int(x)] for x in f[1:]])
        elif f[0]=="EDGE":edges.append((f[1],names[int(f[2])],names[int(f[3])],int(f[4])))
    require(set(order)==set(names),"order directory")
    require(len({order[g[0]] for g in blocks})==len(blocks) and
            all(len({order[n] for n in g})==1 for g in blocks),"atomic block rank")
    adj=collections.defaultdict(set)
    for k,a,b,l in edges:
        if k in ("apo","po") or k=="rf" and val(l):
            require(order[a]<=order[b],"native event order reversed")
            if order[a]==order[b]:adj[b].add(a)
    linear=[]
    for g in sorted(blocks,key=lambda g:order[g[0]]):
        left=set(g)
        while left:
            available=sorted((n for n in left if not (adj[n]&left)),key=lambda n:(meta["locations"][n],n))
            require(available,"intra-block cycle");n=available[0];linear.append(n);left.remove(n)
    rank={n:i for i,n in enumerate(linear)}
    active_writes=collections.defaultdict(list)
    for n in linear:
        if guards.get(n,False):active_writes[info[n][0]].append(n)
    rf=[]
    for k,a,b,l in edges:
        if k=="rf" and val(l):
            require(rank[a]<rank[b] and guards.get(a,False),"chosen RF has no preceding active write")
            require(not any(rank[a]<rank[w]<rank[b] for w in active_writes[info[a][0]]),"chosen RF skips an intervening write")
            if a in words and b in words:require(words[a]==words[b],"chosen RF value mismatch")
            rf.append((a,b))
    archive=f"reports/evidence/si1b/{case}/native/P0/audit/model.tsv.gz"
    contexts={};events={};sites={}
    for line in gzip.GzipFile(fileobj=io.BytesIO(blob(repo,archive))):
        if not line.startswith((b"E\t",b"X\t",b"S\t")):continue
        f=line.decode().rstrip("\n").split("\t")
        if f[0]=="S":sites[f[1]]=f[-3:]
        elif f[0]=="X":contexts[f[1]]=f[2:]
        else:events[f[1]]=(f[2],f[3])
    def ctx(n):return contexts.get(events[n][0],[])
    def iteration(n,function):
        c=ctx(n)
        while c:
            if sites[c[0]][0]==function and len(c)>=5:return int(c[-1])
            c=contexts.get(c[2],[])
        raise ValueError("missing loop instance "+n)
    if case=="fib_updates_8":
        left=right=1;actions=[]
        for n in linear:
            if not guards.get(n,False) or n in ("left#1","right#1"):continue
            if n.startswith("left#"):
                left+=right+1;require(left==words[n],"left Fibonacci update");actions.append(["L",left,n])
            if n.startswith("right#"):
                right+=left;require(right==words[n],"right Fibonacci update");actions.append(["R",right,n])
        require(collections.Counter(a[0] for a in actions)=={"L":8,"R":8} and max(left,right)>2584,"Fibonacci violation")
        visible=dict(actions=actions,final_left=left,final_right=right,bound=2584)
    elif case=="airline_reservations_6":
        actions=[];observed={};written=set();sold=0
        selected_reads={b for _,b in rf}
        for n in linear:
            c=ctx(n)
            if not n.startswith("sold#") or not c or sites[c[0]][0]!="reserve_seat":continue
            thread=c[1]
            if n in selected_reads:
                require(thread not in observed and words[n]==sold,"booking read");observed[thread]=sold;actions.append([thread,"read",sold,n])
            elif guards.get(n,False):
                require(thread not in written and thread in observed and observed[thread]<5,"booking guard")
                sold=observed[thread]+1;require(sold==words[n],"booking write");written.add(thread);actions.append([thread,"write",sold,n])
        require(len(observed)==6 and written=={t for t,v in observed.items() if v<5} and sold!=5,"booking violation")
        visible=dict(actions=actions,final_sold=sold,capacity=5,thread_id_kind="native spawn context")
    else:
        actions=[];buffer=[0]*10;first=0;bad=[]
        for n in linear:
            if not guards.get(n,False):continue
            match=re.fullmatch(r"buffer#\d+\[\[(\d+)\]\]",n)
            if match and meta["locations"][n]==709:
                idx=int(match[1]);i=iteration(n,"t1");require(words[n]==i,"producer iteration")
                buffer[idx]=i;actions.append(["insert",i,idx,n])
            if n.startswith("first#") and meta["locations"][n]==697:
                i=iteration(n,"t2");v=buffer[first];first+=1
                require(words[n]==first,"removed buffer index")
                returns=[words[k] for k in words if re.fullmatch(r"t2::\$tmp::return_value_removeLogElement!\d+@"+str(i+1)+r"#2",k)]
                require(returns==[v],"caller return value")
                actions.append(["remove",i,v,n])
                if v!=i:bad.append((i,v))
        require(bad,"circular-buffer violation")
        visible=dict(actions=actions,failed_consumer_iteration=bad[0][0],returned=bad[0][1])
    return dict(original_clauses=checked,selected_rf=len(rf),ordered_events=len(linear),visible=visible)


if __name__=="__main__":
    repo,root,case=sys.argv[1:];work=Path(root);folder=work/"raw"/case/"solve"
    rows=json.loads((folder/"rows.json").read_text())
    if rows[0]["status"]=="SAT":save(folder/"witness.json",inspect(repo,work,case,rows[0]))
