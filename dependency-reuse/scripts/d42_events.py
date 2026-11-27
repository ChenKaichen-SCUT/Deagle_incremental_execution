"""Supplement semantic sites only on unchanged lines witnessed by the authenticated source patch."""
from collections import Counter, defaultdict
import re


def unchanged(old,new,patch):
    old=old.splitlines(keepends=True)
    new=new.splitlines(keepends=True)
    if old==new:return dict(zip(range(1,len(old)+1),range(1,len(new)+1)))
    lines=patch.splitlines(keepends=True);i=j=0;matches={};hunks=0
    def same():
        nonlocal i,j
        if i>=len(old) or j>=len(new) or old[i]!=new[j]:raise ValueError("patch context")
        matches[i+1]=j+1;i+=1;j+=1
    pos=0
    while pos<len(lines):
        match=re.match(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@",lines[pos])
        pos+=1
        if not match:continue
        left,count,right,new_count=match.groups();left,right=int(left),int(right)
        count=int(count or 1);new_count=int(new_count or 1)
        while i<left-1:same()
        if i!=left-1 or j!=right-1:raise ValueError("patch locations")
        start_i,start_j=i,j;hunks+=1
        while i-start_i<count or j-start_j<new_count:
            line=lines[pos];pos+=1
            if line[:1]==b" " and old[i]==line[1:]:same()
            elif line[:1]==b"-" and old[i]==line[1:]:i+=1
            elif line[:1]==b"+" and new[j]==line[1:]:j+=1
            else:raise ValueError("patch bytes")
        if i-start_i!=count or j-start_j!=new_count:raise ValueError("patch lengths")
    while i<len(old):same()
    if j!=len(new) or not hunks:raise ValueError("incomplete source patch")
    return matches


def supplement(raw,pairs,keys,filename,lines):
    shapes=[dict(r["SITE41"]) for r in raw]
    stable=[{r[1] for r in side["S"] if r[2]=="unique"} for side in raw]
    common=stable[0]&stable[1]
    groups=[defaultdict(list),defaultdict(list)]
    for side in (0,1):
        for sid,key,status,fn,src,line,*_ in raw[side]["S"]:
            if src!=filename or not line.isdecimal():continue
            dest=lines.get(int(line)) if not side else int(line)
            if dest:groups[side][fn,dest,shapes[side][sid]].append((sid,key,status))
    evidence=[]
    for sig,old in groups[0].items():
        peer=groups[1].get(sig,[])
        if len(old)!=1 or len(peer)!=1:continue
        ids=[old[0][0],peer[0][0]]
        if any(ids[i] in pairs[i] for i in (0,1)):continue
        if any(row[2]=="unique" and row[1] in common for row in (old[0],peer[0])):continue
        ident=keys.intern("frozen-source-correspondence",filename,*sig)
        for side in (0,1):pairs[side][ids[side]]=ident
        evidence.append(dict(old_site=ids[0],new_site=ids[1],file=filename,line=sig[1],function=sig[0]))
    return evidence


def inventory(models):
    old,new=models
    sets=[]
    for m in models:
        sets.append({m.event(n):n for n in m.event_info if m.event(n)})
    counts=Counter();examples=defaultdict(list)
    for name,(role,_,_,_) in old.event_info.items():
        k=old.event(name)
        reason="matched" if k in sets[1] else old.event_reason.get(name,"no_peer_with_certified_context")
        counts[reason]+=1
        if len(examples[reason])<8:examples[reason].append([name,role,sets[1].get(k)])
    return dict(counts=counts,examples=examples)
