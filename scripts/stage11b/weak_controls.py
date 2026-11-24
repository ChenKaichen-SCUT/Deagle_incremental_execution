"""For these two source-audited litmus tests, enumerate all total write orders."""
import hashlib,itertools,json,re,tarfile
from pathlib import Path
from graphlib import TopologicalSorter,CycleError
def instructions(name,src):
    # Each shared location has a unique write of each nonzero value used in the bad outcome.
    if name=='butterfly':
        spec=[['Rw2','Wm1','Rx1'],['Rw1','Wn1','Ry2'],['Wx1','Ww1','Wy1','Rn2'],
              ['Wy2','Ww2','Wx2','Rm2'],['Wn2','Rw2'],['Wm2','Rw1']]
        expected=['rw == 2 && rx == 1','rw == 1 && ry == 2','rn == 2','rm == 2','rw == 2','rw == 1']
        assert '__VERIFIER_assert(success < 6);' in src and src.count('success++;')==6 and 'atomic_int success = 0;' in src
        for i,s in enumerate(spec):
            body=src.split(f'void *p{i}(void *arg) {{',1)[1].split('if (',1)
            actual=re.findall(r'int r\w+ = (\w);|([mnxyw]) = ([12]);',body[0])
            assert [v[1] for v in s]==[a or b for a,b,_ in actual]
            for op,(a,b,val) in zip(s,actual):
                assert (op[0]=='R')==bool(a) and (not val or val==op[2])
            assert body[1].startswith(expected[i]+')') and f'p{i},' in src
    else:
        spec=[['Rz2','Wy2','Rx1'],['Wx1','Wy1','Wz1'],['Wt1','Ws1','Wz2'],
              ['Rz2','Wx2','Ry1'],['Rz1','Wt2','Rs1'],['Rz1','Ws2','Rt1']]
        cond='z2 == 2 && x2 == 1 && z5 == 2 && y4 == 1 && z6 == 1 && s3 == 1 && z7 == 1 && tt3 == 1'
        active=re.sub(r'//[^\n]*','',src)
        assert 'assert(!('+cond+'));' in active
        expected=dict(re.findall(r'(\w+) == ([12])',cond))
        for i,ops in enumerate(spec):
            body=active.split(f'void *f{i}(void* arg) {{',1)[1].split('return 0;',1)[0]
            actual=re.findall(r'(\w+) = (\w+);',body)
            assert [('W'+l+r if r.isdecimal() else 'R'+r+expected[l]) for l,r in actual]==ops
    assert src.count('pthread_join(')==6 and len(spec)==6
    return spec
def check(spec):
    writes={};events={};po=set();reads=[]
    for t,ops in enumerate(spec):
        for i,op in enumerate(ops):
            e=f'T{t}.{i}';events[e]=op
            if i:po.add((f'T{t}.{i-1}',e))
            if op[0]=='W':
                assert (op[1],op[2]) not in writes
                writes[op[1],op[2]]=e
            else:reads.append((e,op[1],op[2]))
    loc=sorted({x for x,_ in writes})
    all_orders=[list(itertools.permutations(e for (v,_),e in writes.items() if v==x)) for x in loc]
    candidates=[]
    for orders in itertools.product(*all_orders):
        edges=set(po)
        for o in orders:edges.update(zip(o,o[1:]))
        for r,x,value in reads:
            w=writes[x,value];edges.add((w,r))
            order=orders[loc.index(x)];edges.update((r,later) for later in order[order.index(w)+1:])
        sorter=TopologicalSorter()
        for a,b in sorted(edges):sorter.add(b,a)
        try:schedule=list(sorter.static_order());cycle=None
        except CycleError as e:schedule=None;cycle=e.args[1]
        if cycle:assert all((a,b) in edges for a,b in zip(cycle,cycle[1:]))
        candidates.append(dict(ws=dict(zip(loc,orders)),cycle=cycle,execution=schedule))
    return dict(events=events,orders=candidates,strict_error_witnesses=sum(r['execution'] is not None for r in candidates))
def main(panel,out):
    cases={};q=json.loads((panel/'selection.json').read_bytes())['rows']
    with tarfile.open(panel/'inputs.tar.gz') as t:
        for r in q:
            if r['kind']!='weak-control':continue
            raw=t.extractfile(r['task']+'/'+r['unit']).read();source=hashlib.sha256(raw).hexdigest()
            assert source==r['source_sha256']
            kind='butterfly' if 'butterfly' in r['task'] else 'wsc'
            item=check(instructions(kind,raw.decode()));assert item['strict_error_witnesses']==0
            cases[kind]=dict(source_sha256=source,**item)
    out.parent.mkdir(exist_ok=True,parents=True)
    out.write_bytes((json.dumps(cases,sort_keys=True,indent=2)+'\n').encode())
if __name__=='__main__':
    import sys
    main(*map(Path,sys.argv[1:]))
