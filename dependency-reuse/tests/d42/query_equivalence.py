"""Certify the observed query encoding as a bijective renaming. Offline only."""
from collections import Counter,defaultdict
import argparse,json
from itertools import zip_longest
from pathlib import Path


def verify(left,right,manifest):
    old=[];new=[];common=0;scopes=Counter();query_vars=set();fixed=set();q0=[];q1=[]
    def key(row):return tuple(sorted(map(int,row.split()[1:])))
    with left.open() as f,right.open() as h,manifest.open() as meta:
        scoped=(r for r in meta if r.startswith("C\t"))
        for seq,(a,b,m) in enumerate(zip_longest(f,h,scoped),1):
            if not a or not b or not m:raise ValueError("partial source of native inputs")
            _,t,*xs=m.split()
            if list(map(int,b.split()[1:]))!=list(map(int,xs)):raise ValueError("reference observed P0 differs from archive")
            scopes[t]+=1;u=key(a);v=key(b)
            if t=="Q":q0.append(u);q1.append(v)
            else:
                if u!=v:raise ValueError("changed non-query input")
                fixed.update(x//2 for x in u if x>=2)
            if a==b:common+=1
    # All permanent atoms and all theory ports stay fixed. For the remaining Q atoms,
    # bounded colour refinement only proposes a permutation. The final all-clause test certifies it.
    raw0=left.parent/"raw-graph.tsv";raw1=right.parent/"raw-graph.tsv"
    if raw0.read_bytes()!=raw1.read_bytes():raise ValueError("different installed graph")
    if (left.parent/"query.tsv").read_bytes()!=(right.parent/"query.tsv").read_bytes():raise ValueError("different live assumption boundary")
    for line in raw0.open():
        fields=line.split()
        if fields[0] in ("E","H") and int(fields[-1])>=2:fixed.add(int(fields[-1])//2)
    # A native assumption (if any) is an anchor at this query.
    for line in manifest.open():
        if line.startswith("N\t"):fixed.update(int(x)//2 for x in line.split()[2:] if int(x)>=2)
    groups=[]
    for items in (q0,q1):
        occur=defaultdict(list)
        for cl in items:
            for x in cl:occur[x//2].append((x&1,cl))
        groups.append(occur)
    labels=[{v:(-v if v in fixed else 1) for v in g} for g in groups]
    nrounds=0
    for _ in range(4):
        keys={};nexts=[{},{}]
        for i in (0,1):
            for v,entries in groups[i].items():
                if v in fixed:nexts[i][v]=-v;continue
                sig=(labels[i][v],tuple(sorted((sgn,tuple(sorted((labels[i][x//2],x&1) for x in c))) for sgn,c in entries)))
                nexts[i][v]=keys.setdefault(sig,len(keys)+1)
        nrounds+=1;labels=nexts
    buckets=[defaultdict(list),defaultdict(list)]
    for i in (0,1):
        for v,colour in labels[i].items():buckets[i][colour].append(v)
    if set(buckets[0])!=set(buckets[1]):raise ValueError("query colour domains differ")
    mapping={};symmetric=0
    for k,vs in buckets[0].items():
        peers=buckets[1][k]
        if len(vs)!=len(peers):raise ValueError("query colour multiplicity")
        if len(vs)>1:symmetric+=len(vs)
        mapping.update(zip(sorted(vs),sorted(peers)))
    def transport(c):return tuple(sorted(2*mapping[x//2]+(x&1) for x in c))
    if Counter(map(transport,q0))!=Counter(q1) or len(set(mapping.values()))!=len(mapping):raise ValueError("query clause multiset failed under proposed bijection")
    return dict(phase="offline encoding control",clauses=dict(scopes),identical_ordered_rows=common,unaltered_interface_rows=len(raw0.read_bytes().splitlines()),
                refinement_rounds=nrounds,symmetric_q_atoms=symmetric,permutation={v:w for v,w in mapping.items() if v!=w},exact_all_scopes=True)

if __name__=="__main__":
    import sys
    root=Path(sys.argv[1]);out=Path(sys.argv[2])
    out.write_text(json.dumps(verify(root/"off/inputs.tsv",root/"audit/inputs.tsv",root/"audit/metadata.tsv"),indent=2)+"\n")
