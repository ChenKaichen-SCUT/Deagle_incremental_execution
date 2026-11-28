"""Independent fixed partition and signed-interface check on sealed PI-1 wire transactions."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import runpy
import struct

previous=runpy.run_path(str(Path(__file__).with_name("pi1r-run.py")))
ROOT=previous["ROOT"];PLAN=json.loads((ROOT/"configs/pi1g-plan.json").read_bytes())
WIDTH=PLAN["group_size"]


def seal(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(4<<20),b""):h.update(b)
    assert h.hexdigest()==Path(str(path)+".sha256").read_text().strip()
    return h.hexdigest()


def metadata(path):
    m=defaultdict(list)
    with path.open("rb") as f:
        for raw in f:
            if raw.startswith((b"B\t",b"Q\t",b"B\n",b"Q\n")):continue
            k,*args=raw.decode().rstrip("\n").split("\t");m[k].append(args)
    return m


def identity(m,version,old=None):
    ids=[(version,i) for i in range(len(m["NODE"]))]
    if old is not None:
        for x,y in ((int(a),int(b)) for a,b in m["EVENTMATCH"]):
            if old["NODE"][x][1:5]==m["NODE"][y][1:5]:ids[y]=(0,x)
    return ids


def mapped(l,mu):
    return l if l<0 else mu[l//2]^(l&1)


def ports(m,ids):
    d=defaultdict(list)
    for kind,a,b,l in m["EDGE"]:
        if int(l)>=0:d[int(l)].append((kind,ids[int(a)],ids[int(b)]))
    for a,l in m["GUARD"]:
        if int(l)>=0:d[int(l)].append(("guard",ids[int(a)]))
    return {k:sorted(v) for k,v in d.items()}


def certificate(m0,m1):
    n0,n1=(int(m["PI1.1"][0][0]) for m in (m0,m1))
    e0,e1=identity(m0,0),identity(m1,1,m0)
    p0,p1=ports(m0,e0),ports(m1,e1);mu=[None]*n1;orig=set();dst=set();rejected=0;interface=0
    for x,y,cert in m1["MATCH"]:
        a,b=int(x),int(y)
        assert cert and a not in orig and b//2 not in dst and 0<=a<n0 and 0<=b//2<n1
        orig.add(a);dst.add(b//2)
        if any(p0.get(2*a^s,[])!=p1.get(b^s,[]) for s in (0,1)):
            rejected+=1;continue
        mu[b//2]=2*a^(b&1);interface+=2*a in p0 or (2*a^1) in p0
    nxt=n0
    for i,v in enumerate(mu):
        if v is None:mu[i]=2*nxt;nxt+=1
    def graph(m,ids,mu):
        return (m["CONFIG"],m["PI1.1"][0][2],list(zip(ids,m["NODE"])),
                [(k,a,b,mapped(int(l),mu)) for k,a,b,l in m["EDGE"]],
                [(a,mapped(int(l),mu)) for a,l in m["GUARD"]],m["BLOCK"],m["DOMAIN"])
    mu0=range(0,2*n0,2)
    return mu,dict(proposed=len(orig),accepted=len(orig)-rejected,rejected_interfaces=rejected,
                   accepted_interface_variables=interface,
                   old_interfaces=len({k//2 for k in p0}),new_interfaces=len({k//2 for k in p1}),
                   shared_epoch=graph(m0,e0,mu0)==graph(m1,e1,mu))


def norm(raw,mu):
    if -1 in raw:return None
    a=sorted({mapped(x,mu) for x in raw if x>=0})
    if any((p^1)==q for p,q in zip(a,a[1:])):return None
    return struct.pack("<"+"i"*len(a),*a)


def entries(path,mu):
    occ=0
    with path.open("rb") as f:
        for line in f:
            if line[:2] not in (b"B\t",b"Q\t",b"B\n",b"Q\n"):continue
            fields=line.split();yield fields[0],occ,norm(list(map(int,fields[1:])),mu)
            occ+=1


def directory(path,mu):
    maps={b"B":{},b"Q":{}};counts=Counter()
    for k,_,clause in entries(path,mu):
        counts[k]+=1
        if clause is not None:maps[k][clause]=None
    return maps[b"B"],maps[b"Q"],[counts[b"B"],counts[b"Q"]]


def chunks(seq):
    seq=list(seq)
    return [seq[i:i+WIDTH] for i in range(0,len(seq),WIDTH)]


def one(root,case):
    d=root/case;f0=d/"P0.txn";f1=d/"P1.txn"
    h0=seal(f0);m0=metadata(f0)
    b0,q0,occ0=directory(f0,range(0,2*int(m0["PI1.1"][0][0]),2));old=chunks(b0)
    h1=seal(f1);m1=metadata(f1);assert m1["BASE"]==[[h0]]
    mu,cert=certificate(m0,m1);b1,q1,occ1=directory(f1,mu)
    hits=[sum(c in b1 for c in g) for g in old]
    full=[g for g,n in zip(old,hits) if len(g)==n];covered={c for g in full for c in g}
    new=chunks(c for c in b1 if c not in covered)
    shared=sum(c in b1 for c in b0);E=1 if cert["shared_epoch"] else 2
    arms={}
    for mode,s0,s1 in (("Fine-Persistent",len(b0)+len(q0)+2,len(b0)+len(b1)-shared+len(q0)+len(q1)+2+E),
                       ("Grouped-Persistent",len(old)+2,len(old)+len(new)+2+E),
                       ("Grouped-Reset-active",len(old)+2,len(full)+len(new)+2)):
        arms[mode]=dict(selectors=[s0,s1],assumptions=[s0+len(m0["ASSUME"]),s1+len(m1["ASSUME"])])
    return dict(seals=[h0,h1],unique_B=[len(b0),len(b1)],unique_Q=[len(q0),len(q1)],occurrences_B_Q=[occ0,occ1],
                P0_groups=len(old),full=len(full),partial=sum(0<n<len(g) for g,n in zip(old,hits)),absent=hits.count(0),
                fine_shared=shared,grouped_shared=len(covered),partial_reinstalled=shared-len(covered),
                uncovered=len(b1)-len(covered),P1_new_groups=len(new),theory=cert,arms=arms)


if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("fixtures",type=Path);a.add_argument("output",type=Path);v=a.parse_args()
    result={}
    for case,*_ in PLAN["ordered_sessions"]:
        result[case]=one(v.fixtures,case)
        print(case,result[case]["full"],result[case]["partial"],result[case]["partial_reinstalled"],flush=True)
    v.output.parent.mkdir(parents=True,exist_ok=True)
    v.output.write_text(json.dumps(result,indent=2)+"\n")
