"""Offline verification of P0 inference snapshots, both proof DAGs, native use, full answers and SC schedules."""
import gzip,hashlib,json,sys,tempfile,zipfile
from pathlib import Path
from audit import read,save,digest,Graph,Formula,Proof,derive,verify,audit_theory,rebound,replay_dag,parse,norm,resolve
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE.parent/'stage11b'))
from raw_store import archive
from witness import result
from weak_controls import main as weak
def verify_original(e,rows):
    data=read(e/'original.json')
    assert data['binary_sha256']==read(ROOT/'configs/stage05.lock.json')['baseline_sha256']
    assert data['commit']==read(ROOT/'configs/stage05.lock.json')['baseline_commit']
    assert data['raw_sha256']==digest(e/'original-outputs.zip')
    stock={(p['case'],side):r for p in rows if p['mode']=='stock' for side,r in zip(('old','new'),p['sides'])}
    seen=set()
    with zipfile.ZipFile(e/'original-outputs.zip') as z:
        for h in z.namelist():assert hashlib.sha256(z.read(h)).hexdigest()==h
        for item in data['rows']:
            ref=stock[item['case'],item['side']]
            assert all(ref[k]==item[k] for k in ('source','argv','exit')) and item['wall_ns']>0
            parsed=[[r['property'],r['status']] for obj in json.loads(z.read(item['objects']['result.json'])) for r in obj.get('result',[])]
            assert parsed==item['properties']==[r[:2] for r in ref['properties']]
            assert all(h in z.NameToInfo for h in item['objects'].values())
            seen.add((item['case'],item['side'],item['trial']))
    assert seen=={(c,s,t) for c,s in stock for t in range(1,8)} and len(seen)==len(data['rows'])
    return len(seen)
def one_proof(old,new,lib,au):
    a,b=Graph(old),Graph(new);f0=Formula(old/'s8-input.bin');f1=Formula(new/'s8-input.bin')
    names,events,learnts,counts=parse(old/'worker/proof.log')
    assert lib['query']==[list(x) for x in f0.goals] and au['query']==[list(x) for x in f1.goals]
    assert lib['source']==au['source']==digest(old/'s8-input.bin') and lib['graph']==digest(old/'s8-graph.tsv')
    assert lib['capture']==digest(old/'worker/proof.log') and au['candidate']==digest(new/'s8-input.bin') and au['graph']==digest(new/'s8-graph.tsv')
    assert au['library']==digest(old/'library.json.gz') and au['approved_sha256']==digest(new/'approved.tsv')
    assert lib['counts']==counts
    sub={int(i):v for i,v in lib['theories'].items()}
    raw={i:c['old_clause'] for i,c in sub.items()}
    for i,c in sub.items():
        assert derive(a,events[i],names)==c['proof'] and tuple(c['old_clause'])==events[i]['clause']
        support=verify(a,c['old_clause'],c['proof'])
        assert {k:a.signature(k) for k in support}==c['support']
    replay_dag(lib['dag'],f0,raw)
    pf=Proof(f0,sub,learnts);mapping=dict(tuple(map(int,r.split())) for r in (new/'plan.txt').read_text().splitlines()[1:])
    for i,v in lib['mixed'].items():
        q=pf.uip(int(i));cone=pf.cone(q);types={pf.nodes[j][0] for j in cone}
        assert {'resolve','theory','input'}<=types
        assert pf.nodes[q][1]==lib['dag'][v['root']][1]==list(norm(v['old_clause']))
        assert sorted({pf.nodes[j][3] for j in cone if pf.nodes[j][0]=='theory'})==v['theories']
    roots={int(i):r for i,r in au['native_root_checks'].items()}
    if roots:
        native={int(l[0]):list(map(int,l[1:])) for r in (new/'native-contract.tsv').read_text().splitlines() if (l:=r.split())}
        assert roots==native
    new_t={}
    for j in au['extra_order']:
        new_t[j]=audit_theory(a,b,sub[j],mapping)
        assert roots[j][:2]==[1,0]
    def leaf(ref,used):
        if ref<len(f1.clauses):return f1.clauses[ref]
        t=au['extra_order'][ref-len(f1.clauses)];used.add(t);return new_t[t]
    for i,p in au['proofs'].items():
        used=set();c=leaf(p['conflict'],used)
        for lit,ref,expected in p['steps']:
            c=resolve(c,leaf(ref,used),lit);assert list(c)==expected
        target=rebound(lib['mixed'][i]['old_clause'],mapping)
        assert set(c)<=set(target) and tuple(p['clause'])==target and sorted(used)==p['used']
        assert p['mode']==('theory_RUP' if used else 'boolean_RUP')
    for tag,target in au['approved']:
        if tag[0]=='c':assert au['proofs'][tag[1:]]['mode']=='theory_RUP' and au['proofs'][tag[1:]]['clause']==target
        else:assert list(new_t[int(tag[1:])])==target and sub[int(tag[1:])]['origin']!='reverse_rf'
def check(e):
    rows=read(e/'trials.json');idx=read(e/'raw/files.json');summary=read(e/'summary.json');wits=read(e/'witnesses.json')
    assert len(rows)==108 and len(summary)==3
    assert all(rec['repeats']==7 for case in summary.values() for rec in case['modes'].values())
    checked=set();proofkeys=set();sat=0;matched=0
    lifecycle=read(e/'lifecycle.json')['rows']
    with archive(e/'raw') as z,tempfile.TemporaryDirectory() as td:
        root=Path(td);old=root/'old';new=root/'new';old.mkdir();new.mkdir();(old/'worker').mkdir()
        for h in set(idx.values()):assert hashlib.sha256(z.read(h)).hexdigest()==h
        for case in summary:
            stock=next(p for p in rows if p['case']==case and p['mode']=='stock')
            for rep in range(1,8):
                prefix=f'formal/{case}/{rep}/'
                def inputs(mode,filename):
                    return z.read(idx[prefix+mode+'/new/'+filename])
                def approved(mode,kind):
                    return [tuple(int(p) for p in row[2:]) for line in inputs(mode,'approved.tsv').splitlines()
                            if (row:=line.split())[0].startswith(kind)]
                assert approved('T',b't')==approved('TC',b't')
                assert approved('C',b'c')==approved('TC',b'c')
                assert not approved('T',b'c') and not approved('C',b't')
                for n in ('s8-input.bin','s8-graph.tsv','plan.txt','events.tsv'):
                    assert all(inputs('T',n)==inputs(m,n) for m in ('B','C','TC'))
                matched+=1
            for p in [r for r in rows if r['case']==case and r['mode']!='stock']:
                prefix=f"formal/{case}/{p['trial']}/{p['mode']}/"
                def get(side,n):return z.read(idx[prefix+side+'/'+n])
                for i,(side,r) in enumerate(zip(('old','new'),p['sides'])):
                    s=stock['sides'][i];assert all(r[k]==s[k] for k in ('source','stream','phases','graph','argv','exit'))
                    assert [(x,y) for x,y,_ in r['properties']]==[(x,y) for x,y,_ in s['properties']]
                    assert r['gate']['native']['path']=='ACCEPT_NATIVE_RESTRICTED' and not r['model_reuse']
                    assert r['search_trace']==idx[prefix+side+'/worker/search.bin']==lifecycle[case+'/'+p['mode']][side]['search_sha256']
                    if p['trial']==1:
                        statpath='lifecycle/'+case+'/'+p['mode']+'/'+side+'/worker/stats.tsv'
                        counters=dict(row.split('\t') for row in z.read(idx[statpath]).decode().splitlines())
                        assert {k[3:]:int(v) for k,v in counters.items() if k.startswith('lc_')}==lifecycle[case+'/'+p['mode']][side]['counts']
                        assert all(int(counters[k])==r['counters'][k] for k in ('decisions','conflicts','propagations','theory_propagations','theory_conflicts'))
                    if r['exit']==10:
                        sat+=1;k=r['witness']
                        if k not in checked:
                            for n in ('full_model.json','native-bindings.json','bits.tsv','answer.txt'):(root/n).write_bytes(get(side,n))
                            assert result(root)==wits[k] and wits[k]['status']=='EXPLICIT_SC_ORDER';checked.add(k)
                if p['mode'] in ('F','B'):continue
                libkey=idx[prefix+'old/library.json.gz'];akey=idx[prefix+'new/audit.json.gz']
                au=json.loads(gzip.decompress(get('new','audit.json.gz')))
                uses=[r.split('\t') for r in get('new','worker/use.tsv').decode().splitlines()]
                admitted={k for k,_ in au['approved']};assert admitted=={u[1] for u in uses if u[0]=='import'}
                assert all(u[1] in admitted for u in uses)
                assert all(int(u[4])==int(u[3])+1 for u in uses if u[0]=='import' and u[2]=='attached')
                assert all(int(u[3])>0 for u in uses if u[0]=='hit')
                if (libkey,akey) in proofkeys:continue
                for side,d in [('old',old),('new',new)]:
                    for n in ('native-bindings.json','full_model.json','events.tsv','plan.txt','s8-graph.tsv','s8-input.bin'):
                        (d/n).write_bytes(get(side,n))
                for d,side,n in [(old,'old','worker/proof.log'),(old,'old','library.json.gz'),(new,'new','approved.tsv'),(new,'new','native-contract.tsv')]:
                    if prefix+side+'/'+n in idx:(d/n).write_bytes(get(side,n))
                one_proof(old,new,read(old/'library.json.gz'),au);proofkeys.add((libkey,akey))
        assert checked==set(wits)
        weak(ROOT/'reports/evidence/stage-11b/panel',root/'weak.json')
        assert read(root/'weak.json')==read(e/'weak-sc.json')
        for case,expected in [('batch_total',[10,0]),('batch_retained',[10,10])]:
            for trial,mode in [(0,'stock'),(1,'T')]:
                for side,code in zip(('old','new'),expected):
                    receipt=json.loads(z.read(idx[f'mechanism/{case}/{trial}/{mode}/{side}/receipt.json']))
                    assert receipt['exit']==code
    controls=read(e/'negative.json');assert set(range(1,17))=={int(d['test'][:2]) for d in controls}
    for d in controls:
        tag=d['test'][:2]
        if tag in ('12','13'):assert d['actual']==[r['code'] for r in d['cold']]==([1,0] if tag=='12' else [0,1])
        elif tag=='14':assert [line.split()[2:] for line in d['cold']]==[[str(1-i%2)]*2 for i in range(5)]
        elif d['test'].startswith('11a'):assert d['approved_proof'] and d['submitted']==0
        else:assert d['approved']==0 and d['reason'] and d['cold']
    assert all(v['classification']=='INCOMPLETE_UNWINDING' and len(v['stream']['queries'])==3 for v in read(e/'multiquery.json').values())
    return dict(pairs=len(rows),experimental_version_solves=210,stock_version_solves=6,F0_direct_version_runs=verify_original(e,rows),SAT=sat,distinct_source_answers=len(checked),
                matched_ordered_mode_inputs=matched,independent_proof_replays=len(proofkeys),negative_rows=len(controls),raw_paths=len(idx),unique_objects=len(set(idx.values())))
if __name__=='__main__':
    directory=Path(sys.argv[1]);out=check(directory)
    if '--record' in sys.argv[2:]:save(directory,'verification.json',out)
    print(json.dumps(out,sort_keys=True))
