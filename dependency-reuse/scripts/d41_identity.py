"""Certify unresolved static sites in intervals bounded by common native instruction identities."""
from collections import Counter,defaultdict


def pair_sites(left,right,keys):
    def group(rows):
        shape=dict(rows["SITE41"]);functions=defaultdict(list)
        if len(shape)!=len(rows["S"]) or len(shape)!=len(rows["SITE41"]):raise ValueError("incomplete static instruction witness")
        for sid,key,status,fn,*_ in rows["S"]:functions[fn].append((sid,key,status,shape[sid]))
        return functions
    a,b=group(left),group(right)
    pairs=[{},{}]
    for fn in sorted(a.keys()&b.keys()):
        l,r=a[fn],b[fn]
        stable={v[1] for v in l if v[2]=="unique"} & {v[1] for v in r if v[2]=="unique"}
        ln=[(i,x[1]) for i,x in enumerate(l) if x[1] in stable]
        rn=[(i,x[1]) for i,x in enumerate(r) if x[1] in stable]
        if [k for _,k in ln]!=[k for _,k in rn]:continue
        bounds=[(-1,-1,"BEGIN"),*((i,j,k) for (i,k),(j,_) in zip(ln,rn)),(len(l),len(r),"END")]
        for (i,j,before),(ii,jj,after) in zip(bounds,bounds[1:]):
            old,new=l[i+1:ii],r[j+1:jj]
            x=[t[3] for t in old];y=[t[3] for t in new]
            if x==y:
                matches=[(u,v,("identical-interval",tuple(x),n)) for n,(u,v) in enumerate(zip(old,new))]
            else:
                lc,rc=Counter(x),Counter(y)
                unique={v[3]:v for v in new if rc[v[3]]==1}
                matches=[(u,unique[u[3]],("unique-in-interval",u[3])) for u in old if lc[u[3]]==1 and u[3] in unique]
            for u,v,proof in matches:
                k=keys.intern("native-site-interval",fn,before,after,*proof)
                pairs[0][u[0]]=k;pairs[1][v[0]]=k
    return pairs
