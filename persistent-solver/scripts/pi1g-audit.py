"""Check actual guarded inputs against the signed contents of sealed transactions and the applied controls."""
from array import array
from collections import defaultdict
import hashlib
import mmap
from pathlib import Path
import runpy
import struct

scale=runpy.run_path(str(Path(__file__).with_name("pi1g-scale.py")))
meta,entries,cert=(scale[k] for k in ("metadata","entries","certificate"))
WIDTH=scale["WIDTH"]
def must(value,why):
    if not value:raise ValueError(why)


def records(path):
    with path.open("rb") as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m:
        i=0
        while i<len(m):
            kind,n=struct.unpack_from("<ii",m,i);i+=8
            must(0<=n<=(len(m)-i)//4,"truncated activation journal")
            yield kind,struct.unpack_from("<"+"i"*n,m,i);i+=4*n


def signed(path):
    with path.open("rb") as f:
        while h:=f.read(16):
            v,q,n,k=struct.unpack("<4I",h);a=array("I");a.fromfile(f,n)
            yield v,q,k,a


def verify(journal,controls,models,mode,rows):
    grouped=mode!="Fine-Persistent"
    groups={};payload={};queries={};epochs=set()
    previous_meta=None;previous_mu=None;first_mu=True;idx=0;result=[];layouts=[]
    args=iter(signed(controls))
    for tag,f in records(journal):
        if tag==1:
            version,reset=f;must(reset==(mode=="Grouped-Reset-active" and version>1),"wrong lifetime")
            if reset:groups.clear();payload.clear();queries.clear();epochs.clear()
            bm=meta(models[version][0]);first_mu=True;bmembers={};bseq=None;qo={};qseq={};qmeta={}
        elif tag==2:
            mu=f;must(len(set(p//2 for p in mu))==len(mu) and all(x>=2 for x in mu),"invalid program projection")
            if first_mu:
                if previous_mu is not None:
                    mapping,_=cert(previous_meta,bm)
                    if not reset:
                        oldvars={p//2 for p in previous_mu}
                        for j,p in enumerate(mapping):
                            if p//2<len(previous_mu):must(mu[j]==previous_mu[p//2]^(p&1),"signed certificate drift")
                            else:must(mu[j]//2 not in oldvars,"unmatched variable reused")
                if reset:must(all(x==2*(i+1) for i,x in enumerate(mu)),"non-dense reset program space")
                previous_meta,previous_mu=bm,mu
                bseq=(x for x in entries(models[version][0],mu) if x[0]==b"B")
                first_mu=False
        elif tag==7:
            v,q,ctrl=f;must(v==version and ctrl not in queries,"query-control rebinding")
            desc=models[v][q];queries[ctrl]=q;qo[ctrl]={};qmeta[q]=meta(desc)
            qseq[ctrl]=(x for x in entries(desc,mu) if x[0]==b"Q")
        elif tag==3:
            gid,ctrl,birth,scope=f
            must(ctrl not in groups and birth==version and (scope<0 or scope in queries),"selector rebound or wrong scope")
            groups[ctrl]=(birth,scope,[])
        elif tag==4:
            cid,ctrl,scope,*actual=f
            must(ctrl in groups and groups[ctrl][:2]==(version,scope),"changed immutable payload")
            guard=[2*ctrl+1]+([2*scope+1] if scope>=0 and scope!=ctrl else [])
            must((not grouped or scope<0 or scope==ctrl) and actual[:len(guard)]==guard,"incorrect real guard")
            body=actual[len(guard):]
            must(body==sorted(set(body)) and not any((a^1)==b for a,b in zip(body,body[1:])),"noncanonical real clause")
            raw=struct.pack("<"+"i"*len(body),*body)
            if cid in payload:must(payload[cid]==raw,"mutated member")
            else:payload[cid]=raw
            groups[ctrl][2].append(cid)
        elif tag==5:
            scope,lo,hi,cid=f
            it=bseq if scope==-1 else qseq[scope]
            native=next(it,None);must(native is not None,"extra input occurrence")
            _,occ,raw=native
            must(occ==((hi&0xffffffff)<<32 | (lo&0xffffffff)),"changed occurrence order")
            if raw is None:must(cid==-1,"wrong constant or tautology");continue
            must(cid>=0 and payload.get(cid)==raw,"omitted or changed actual input")
            (bmembers if scope==-1 else qo[scope]).setdefault(raw,occ)
        elif tag==6:
            v,q,ctrl,epoch=f;row=rows[idx];idx+=1
            must(v==version and queries[ctrl]==q and (v,q)==(row["version"],row["query"]),"query boundary")
            must(next(bseq,None) is None and next(qseq[ctrl],None) is None,"missing input occurrences")
            av,aq,k,a=next(args);must((av,aq)==(v,q),"wrong control receipt")
            states={p//2:not(p&1) for p in a[:k]};epochs.add(epoch)
            must(len(states)==k and set(states)==set(groups)|set(queries)|epochs,"missing or extraneous control")
            must(all(states[e]==(e==epoch) for e in epochs) and all(states[j]==(j==ctrl) for j in queries),"wrong epoch/query")
            must(set(states).isdisjoint(p//2 for p in mu),"program/control alias")
            def project(p):return (0 if p==-1 else 1) if p<0 else mu[p//2]^(p&1)
            must(list(a[k:])==[project(int(x[0])) for x in qmeta[q]["ASSUME"]],"native query assumptions")
            cover=set();qcover=set();layout=array("I");existing=set();new_flat=[];sizes=[]
            for s,(born,scope,ids) in groups.items():
                if scope!=-1:
                    if s!=scope:must(states[s]==(scope==ctrl),"scoped fine selector")
                    if scope==ctrl and states[s]:qcover.update(payload[i] for i in ids)
                    continue
                bodies=[payload[i] for i in ids]
                must(bool(bodies) and len(bodies)<= (WIDTH if grouped else 1) and len(ids)==len(set(ids)),"invalid group cardinality")
                applies=all(b in bmembers for b in bodies)
                must(states[s]==applies,"wrong activation of partial or complete old group")
                if applies:
                    cover.update(bodies);layout.append(len(ids))
                    layout.extend(bmembers[b] for b in bodies)
                    if born<version:existing.update(bodies)
                    else:new_flat.extend(bodies);sizes.append(len(bodies))
            must(cover==set(bmembers) and qcover==set(qo[ctrl]),"active B/Q differs from actual transaction")
            if not reset:
                expected=[b for b in bmembers if b not in existing]
                must(new_flat==expected,"new groups changed native first-occurrence order")
                w=WIDTH if grouped else 1
                must(sizes==[min(w,len(expected)-i) for i in range(0,len(expected),w)],"wrong split")
            risk=[]
            if not grouped and version==2:
                old_selectors=[s for s,(born,scope,_) in groups.items() if born==1 and scope<0]
                for start in range(0,len(old_selectors),WIDTH):
                    block=old_selectors[start:start+WIDTH]
                    if not all(states[s] for s in block):
                        risk.extend(2*s+1 for s in block if states[s])
            packed=layout.tobytes();layouts.append(packed)
            result.append(dict(version=v,query=q,unique_B=len(cover),unique_Q=len(qcover),shared_B=len(existing),
                               active_partition_sha256=hashlib.sha256(packed).hexdigest(),signed_controls=k,
                               assumptions=len(a),epoch_variable=epoch,query_control=ctrl,fresh_solver=bool(reset),partial_fine_negative_guards=risk))
        else:raise ValueError("unknown activation record")
    must(idx==len(rows) and next(args,None) is None,"missing result")
    return result,layouts


def show_control(journal, controls, selector):
    """Stream one selector's immutable payload, actual installations, occurrences and query activations."""
    import json
    def emit(**fields):
        print(json.dumps(fields, separators=(",", ":")))
    assumptions=iter(signed(controls))
    registered=False
    members=set()
    for tag, row in records(journal):
        if tag==1:
            version, reset=row
            if reset:registered=False;members.clear()
        elif tag==3 and row[1]==selector:
            group, _, first, scope=row
            assert not registered
            registered=True
            emit(kind="group", version=version, id=group, selector=selector, first_version=first, scope=scope)
        elif tag==4 and row[1]==selector:
            member, _, scope, *native_clause=row
            members.add(member)
            emit(kind="installation", version=version, scope=scope, member=member, native_clause=native_clause)
        elif tag==5 and row[3] in members:
            scope, lo, hi, member=row
            emit(kind="occurrence", version=version, scope=scope, member=member,
                 occurrence=((hi&0xffffffff)<<32)|(lo&0xffffffff))
        elif tag==6:
            version, query, _, _=row
            v, q, k, words=next(assumptions)
            assert (v,q)==(version,query)
            if registered:
                applied=[p for p in words[:k] if p//2==selector]
                assert len(applied)==1
                emit(kind="activation", version=v, query=q, signed_control=applied[0], enabled=(applied[0]&1)==0)
    assert next(assumptions,None) is None


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description=show_control.__doc__)
    parser.add_argument("journal",type=Path)
    parser.add_argument("controls",type=Path)
    parser.add_argument("selector",type=int)
    args=parser.parse_args()
    show_control(args.journal,args.controls,args.selector)
