"""Small native mixed proofs and independent finite-order semantics."""
import argparse
from collections import defaultdict
from itertools import permutations, product
from pathlib import Path
import json
import struct
import subprocess
import tarfile


def raw(v):
    return 2*abs(v)+(v<0)


def benchmark(tag, edges, guards=(), units=()):
    return dict(tag=tag,edges=list(edges),guards=dict(guards),
                assumptions=list(units), clauses=[(1,2,5),(1,-2,5),(3,4),(3,-4)])


W,R,U,V,X='x#1','x#2','x#3','x#4','x#5'
direct=benchmark('direct',[('rf',W,R,5),('po',R,W,0)])
block=benchmark('block',[('rf',W,R,5),('apo',U,R,0),('apo',W,V,0),('po',U,V,0)])
# RF(W,R,6), active W/X and W<X force R<X, preventing RF(X,R,5).
compete=benchmark('competition',[('rf',W,R,6),('rf',X,R,5),('po',W,X,0)],
                  [(W,0),(X,7)],(6,7))
# RF(W,R,6) and X<R force X<W when W/X are active.
ws=benchmark('ws',[('rf',W,R,6),('rf',W,X,5),('po',X,R,0)],
             [(W,0),(X,7)],(6,7))


def altered(spec, change):
    z={k:(v.copy() if isinstance(v,(list,dict)) else v) for k,v in spec.items()}
    if change in ('B','B+T'): z['clauses'].pop(0)
    if change in ('T','B+T'):z['edges']=[e for e in z['edges'] if e[0]!='po']
    if change=='split':z['edges'].remove(('apo',U,R,0))
    if change=='merge':z['edges'].append(('apo',R,W,0))
    if change=='guard':z['guards'][X]=-7
    if change=='add-write':z['edges'].append(('rf',V,R,8))
    if change=='unrelated':z['clauses'].append((8,))
    return z


def semantics(z):
    events=sorted({v for _,a,b,_ in z['edges'] for v in (a,b)}|set(z['guards']))
    writes={a for k,a,_,_ in z['edges'] if k=='rf'}|set(z['guards'])
    reads={b for k,_,b,_ in z['edges'] if k=='rf'}
    parent={i:i for i in events}
    def rep(i):
        while parent[i]!=i:i=parent[i]
        return i
    internal=set()
    po=set()
    for k,a,b,_ in z['edges']:
        if k=='apo':
            parent[rep(a)]=rep(b)
            internal.add((a,b))
        if k in ('apo','po'):po.add((a,b))
    for mid in events:
        internal|={(a,b) for a,c in internal for d,b in internal if c==mid==d and a!=b}
    blocks=defaultdict(set)
    for i in events:blocks[rep(i)].add(i)
    decl={(0,-1,-1,-1):('config','SC')}
    for i in events:
        decl[5,i,-1,-1]=('schema',i,i in reads,i in writes)
    for root,members in blocks.items():
        decl[7,root,-1,-1]=('block',tuple(sorted(members)),tuple(sorted((a,b) for a,b in internal if a in members)))
    for k,a,b,v in z['edges']:
        op={'po':1,'apo':2,'rf':3}[k]
        decl[op,a,b,-1 if not v else raw(v)]=(k,a,b,v)
    for u,g in z['guards'].items():
        decl[4,u,-1,-1 if not g else raw(g)]=('guard',u,g)
    # SameAddress is unordered. All fixture event names are writes/reads of x.
    for i in events:
        for j in events:
            decl[6,i,j,-1]=('address',*sorted((i,j)))
    domain={r:frozenset(a for k,a,b,v in z['edges'] if k=='rf' and b==r) for r in reads}
    return events,writes,reads,{i:rep(i) for i in events},internal,po,decl,domain


def make_inputs(root,case,p1,ns):
    d=root;events,writes,reads,rep,internal,_,decl,domain=semantics(case)
    peer=semantics(p1);peer_keys=set(peer[6].values())
    name={s:i for i,s,addr in ns}
    def local(x):return name[x] if isinstance(x,str) else x
    with (d/'decl').open('w') as f:
        for i,s,addr in ns:
            print('N',i,local(rep[s]),addr,int(s in reads),int(s in writes),file=f)
        for i,j in sorted(internal):
            print('I',local(j),local(i),file=f)
            print('O',local(i),local(j),file=f)
        for key,semantic_key in sorted(decl.items(),key=str):
            op,a,b,c=key
            if op==6 and local(a)>local(b):continue
            print('D',op,local(a),local(b),c,'M' if semantic_key in peer_keys else 'C',file=f)
    (d/'inputs').write_text(''.join(' '.join(map(str,['B',int(c not in p1['clauses']),*map(raw,c)]))+'\n' for c in case['clauses']))
    (d/'map').write_text(''.join(f'{i} {2*i}\n' for i in range(1,9)))
    return domain!=peer[7]


def exhaustive(z,kept):
    events,writes,reads,rep,_,po,_,_=semantics(z)
    orders=[]
    for order in permutations(events):
        pos={v:i for i,v in enumerate(order)}
        if not all(pos[a]<pos[b] for a,b in po):continue
        layers=[rep[v] for v in order]
        if any(max(j for j,x in enumerate(layers) if x==k)-layers.index(k)+1!=layers.count(k) for k in set(layers)):continue
        orders.append(pos)
    models=0
    for vals in product((False,True),repeat=8):
        val=lambda v: vals[abs(v)-1]!=(v<0)
        if not all(any(val(v) for v in c) for c in z['clauses']):continue
        active={w for w in writes if not z['guards'].get(w,0) or val(z['guards'][w])}
        selected=[(w,r) for k,w,r,v in z['edges'] if k=='rf' and val(v)]
        # An RF choice needs an executing source before the read, and no
        # intervening active competing write. No completeness axiom is assumed.
        if not any(all(w in active and pos[w]<pos[r] and
                       not any(pos[w]<pos[t]<pos[r] for t in active if t not in (w,r))
                       for w,r in selected) for pos in orders):continue
        models+=1
        assert all(any(vals[l//2-1]!=bool(l&1) for l in c) for c in kept)
    return models


def run(checker,solver,oracle,root):
    results={}
    plan=[(direct,['same','B','T','B+T','merge','unrelated','add-write']),
          (block,['same','split','merge','add-write']),(compete,['same','guard','add-write']),(ws,['same','guard'])]
    for case,changes in plan:
        tag=case['tag'];d=root/tag;d.mkdir()
        inp=d/'spec'
        rows=['8',*[' '.join(map(str,e)) for e in case['edges']],
              *[f'guard {w} {g}' for w,g in case['guards'].items()],
              *['B '+' '.join(map(str,c)) for c in case['clauses']]]
        rows.append('A '+' '.join(map(str,case['assumptions'])))
        inp.write_text('\n'.join(rows)+'\n')
        for mode,binary in [('D1',oracle),('D3',solver)]:
            wd=d/mode;wd.mkdir()
            with (wd/'stdout').open('w') as out,(wd/'stderr').open('w') as err:
                subprocess.run([binary,inp,wd/'proof.bin'],cwd=wd,stdout=out,stderr=err,check=True,timeout=25)
        assert (d/'D3/event-names.tsv').read_bytes()==(d/'D1/event-names.tsv').read_bytes()
        ns=[(int(i),s,int(a)) for i,s,a in (line.split() for line in (d/'D3/event-names.tsv').read_text().splitlines())]
        for change in changes:
            dest=d/change;dest.mkdir();p1=altered(case,change)
            domain_change=make_inputs(dest,case,p1,ns)
            subprocess.run([checker,d/'D3/proof.bin',dest/'inputs',dest/'map',d/'D1/native-learns.tsv',dest/'decl',dest],check=True)
            kept=[list(map(int,l.split()))[1:] for l in (dest/'survivors.tsv').read_text().splitlines()]
            m={k:int(v) for k,v in (l.split() for l in (dest/'metrics.tsv').read_text().splitlines())}
            m['enumerated_models']=exhaustive(p1,kept)
            m['complete_rf_domain_changed']=domain_change
            results[tag+'/'+change]=m
    return results


def corruption_tests(path,checker):
    """Mutate theory-only fields while preserving the Boolean graph and every actual native birth."""
    audit={}
    for label,case in [('inverted-binding','direct'),('reserved-triplet','direct'),('wrong-block','block')]:
        d=path/case
        out=d/label;out.mkdir()
        data=bytearray((d/'D3/proof.bin').read_bytes())
        assert data[:6]==b'DEAGD3'
        pos=12
        for stride in (16,4,8,16,12,8,12,4,4,4,4,4):
            n=struct.unpack_from('<I',data,pos)[0];pos+=4+n*stride
        count=struct.unpack_from('<I',data,pos)[0];pos+=4
        decl=(d/'same/decl').read_text()
        rep={int(a):int(b) for k,a,b,*_ in (l.split() for l in decl.splitlines()) if k=='N'}
        for j in range(count):
            at=pos+j*20
            node,op,x,y,z=struct.unpack_from('<IIiii',data,at)
            if label=='inverted-binding' and op==3:
                old=f'D 3 {x} {y} {z} M'
                assert old in decl and z>=0
                decl=decl.replace(old,f'D 3 {x} {y} {z^1} M')
                field,old_word,new_word=16,z,z^1
            elif label=='reserved-triplet' and op==17:
                field,old_word,new_word=4,17,18
            elif label=='wrong-block' and op==12:
                field,old_word,new_word=8,x,next(i for i in rep if rep[i]!=rep[x])
            else:continue
            struct.pack_into('<i',data,at+field,new_word)
            break
        else:raise AssertionError('fixture failed to exercise '+label)
        bad=out/'mutated.bin';bad.write_bytes(data)
        f=out/'decl';f.write_text(decl)
        r=subprocess.run([checker,bad,d/'same/inputs',d/'same/map',d/'D1/native-learns.tsv',f,out],
                         capture_output=True,text=True)
        assert r.returncode==1 and r.stderr.strip(),(label,r.returncode)
        audit[label]=dict(source=case,node=node,byte_offset=at+field,old_word=old_word,new_word=new_word,
                          rejection=r.stderr.strip())
    # Check the reader boundary with an actual frozen D2 proof, and independently
    # tamper with each of the two native receipt checks on an otherwise valid D3 run.
    d=path/'direct'
    good=(d/'D3/proof.bin').read_bytes()
    for label,expect in [('legacy-D2','completed D3 archive'),('wrong-graph','graph receipt mismatch'),
                         ('counter-mismatch','discharge counters')]:
        out=d/label;out.mkdir();data=bytearray(good);decl=(d/'same/decl').read_text()
        if label=='legacy-D2':
            package=Path(__file__).resolve().parents[2]/'reports/evidence/d2/micro/raw.tar.gz'
            with tarfile.open(package) as f:
                member=next(m for m in f.getmembers() if m.name.endswith('/cnf-on/proof.bin'))
                data=f.extractfile(member).read()
        elif label=='wrong-graph': decl+='G\tNODE\taltered\n'
        else:
            # D3 footer ends with three discharge counters, eighteen native
            # counters, the 32-bit status and four-byte closing marker.
            offset=len(data)-8-(18+1)*8
            v=struct.unpack_from('<Q',data,offset)[0];struct.pack_into('<Q',data,offset,v+1)
        bad=out/'mutated.bin';bad.write_bytes(data);f=out/'decl';f.write_text(decl)
        r=subprocess.run([checker,bad,d/'same/inputs',d/'same/map',d/'D1/native-learns.tsv',f,out],
                         capture_output=True,text=True)
        assert r.returncode==1 and expect in r.stderr,(label,r.stderr)
        audit[label]=dict(source='direct',rejection=r.stderr.strip())
    (path/'corruption-results.json').write_text(json.dumps(audit,indent=2)+'\n')


def assert_scenarios(r):
    for tag in ('direct','block'):
        m=r[tag+'/same']
        assert m['complete_permanent_mixed'] and m['complete_mixed_old_proof_survives']==m['complete_permanent_mixed']
    for change in ('B','T','B+T'):
        assert r['direct/'+change]['complete_mixed_old_proof_survives']==0
    for change in ('merge','split'):
        assert r['block/'+change]['complete_mixed_old_proof_survives']==0
    assert r['direct/unrelated']['complete_mixed_old_proof_survives']==r['direct/same']['complete_mixed_old_proof_survives']
    assert r['direct/merge']['complete_mixed_old_proof_survives']==r['direct/same']['complete_mixed_old_proof_survives']
    for tag in ('direct','block','competition'):
        assert r[tag+'/add-write']['complete_rf_domain_changed']
        assert r[tag+'/add-write']['old_proof_survives']==r[tag+'/same']['old_proof_survives']
    for tag,op in [('competition',15),('ws',14)]:
        assert r[tag+'/same']['op_'+str(op)]>0
        assert r[tag+'/guard']['theory_reasons_survive']<r[tag+'/same']['theory_reasons_survive']
    assert all(m['enumerated_models']>0 for m in r.values())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('checker','solver','oracle','new_dir'):p.add_argument(n,type=Path)
    a=p.parse_args();path=a.new_dir.resolve();path.mkdir(parents=True,exist_ok=False)
    r=run(a.checker.resolve(),a.solver.resolve(),a.oracle.resolve(),path)
    (path/'results.json').write_text(json.dumps(r,indent=2)+'\n')
    corruption_tests(path,a.checker.resolve())
    assert_scenarios(r)
    for k,x in r.items():print(k,x['births'],x['complete_permanent_boolean'],x['complete_permanent_mixed'],
        x['complete_mixed_old_proof_survives'],x['old_proof_survives'],x['enumerated_models'])
