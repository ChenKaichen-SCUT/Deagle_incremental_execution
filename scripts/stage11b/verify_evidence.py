"""Offline, byte-level release verification; use --seal once to write the publication manifest."""
from pathlib import Path
import argparse,collections,gzip,hashlib,json,tempfile
from raw_store import archive
from weak_controls import main as weak_check
from witness import result
from gates import decide,stock_fallback
ROOT=Path(__file__).resolve().parents[2]
E=ROOT/'reports/evidence/stage-11b'
def read(p):return json.loads(p.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()
def check():
    data=read(E/'trials.json');summary=read(E/'summary.json');idx=read(E/'raw/files.json')
    assert len(data)==105 and len(summary['cases'])==5
    assert set(summary['native_release'])=={'ACCEPT_NATIVE_RESTRICTED'} and summary['native_release']['ACCEPT_NATIVE_RESTRICTED']==200
    proofmeta=read(E/'proof-replay.json');blob=gzip.decompress((E/'proofs.json.gz').read_bytes())
    assert sha(blob)==proofmeta['proof_bytes_sha256'];proofs=json.loads(blob)
    for name,req in proofs.items():
        steps=req['proofs'];assert len(steps)==proofmeta['cases'][name]['consumed']
        assert len(steps)==summary['cases'][name]['modes']['GS']['median']['used_derived']
        old,new=[set(map(tuple,rows)) for rows in req['direct_PO_quotient']]
        for v in steps:
            a,b=v['pair'];assert (a,b) not in old
            for path,base in ((v['P0'],old),(v['P1'],new)):
                assert path[0]==a and path[-1]==b and all(x in base for x in zip(path,path[1:]))
    witnesses=read(E/'witnesses.json');checked=set();assignments=set()
    references={p['case']:p for p in data if p['mode']=='stock'}
    assert set(references)==set(proofs)==set(summary['cases']) and len(witnesses)==8
    sat_runs=0
    with archive(E/'raw') as z,tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp)
        for key in set(idx.values()):assert sha(z.read(key))==key
        weak_check(E/'panel',tmp/'weak.json')
        assert (tmp/'weak.json').read_bytes()==(E/'weak-sc.json').read_bytes()
        for case,req in proofs.items():
            labels=req['semantic_blocks']
            assert len(set(labels))==len(labels)
            steps={tuple(labels[i] for i in v['pair']) for v in req['proofs']}
            assert len(steps)==len(req['proofs'])
            for i,(side,info) in enumerate(zip(('old','new'),proofmeta['cases'][case]['replayed'])):
                prefix=f'formal/{case}/1/GS/{side}/'
                assert info['round1_answer']==idx[prefix+'answer.txt']
                assert all(idx[prefix+name]==h for name,h in info['hashes'].items())
                for ref in info['complete_answer_matches']:
                    other=f'formal/{case}/{ref}/'
                    assert idx[other+'answer.txt']==info['audit_answer']
                    assert all(idx[other+name]==h for name,h in info['hashes'].items())
                assert info['complete_answer_matches'] and info['equal_boolean_assignment'] and info['equal_rank_map']
                table=[line.split('\t') for line in z.read(idx[prefix+'worker/closure.tsv']).decode().splitlines()]
                direct={(a,b) for a,b,base,kept in table if base=='1'}
                assert direct=={(labels[a],labels[b]) for a,b in req['direct_PO_quotient'][i]}
                if i==1:assert steps<={(a,b) for a,b,base,kept in table if kept=='1'}
        for p in data:
            if p['mode']=='stock':continue
            for i,(side,r) in enumerate(zip(('old','new'),p['sides'])):
                w=r.get('witness')
                stock=references[p['case']]['sides'][i]
                prefix=f"formal/{p['case']}/{p['trial']}/{p['mode']}/{side}/"
                assert r['search_trace']==stock['search_trace']==idx[prefix+'worker/search.bin']
                assert stock['search_trace']==idx[f"formal/{p['case']}/0/stock/{side}/search.bin"]
                cert=witnesses[w] if w else {'status':'NO_SAT_MODEL'}
                for strict,k in ((False,'native'),(True,'strict_request')):
                    assert decide(r,stock,cert,strict)==r['admission'][k]
                if r['exit']==10:
                    sat_runs+=1
                    assert w and cert['status']=='EXPLICIT_SC_ORDER'
                    for status in ('UNCONFIRMED','NO_ORDER_FOR_RETURNED_ASSIGNMENT','NO_SAT_MODEL'):
                        assert decide(r,stock,{'status':status})['path']=='FULL_REBUILD'
                if w is None or w in checked:continue
                for n in ('full_model.json','native-bindings.json','bits.tsv','answer.txt'):
                    (tmp/n).write_bytes(z.read(idx[prefix+n]))
                observed=result(tmp);assert observed==witnesses[w] and observed['status']=='EXPLICIT_SC_ORDER'
                parts=(tmp/'answer.txt').read_bytes().split()
                assignments.add((w.split('-')[0],tuple(parts[:2+int(parts[1])])))
                checked.add(w)
        assert checked==set(witnesses) and len(assignments)==5 and sat_runs==120
        versions=[]
        for side in ('old','new'):
            d=tmp/'stock'/side;d.mkdir(parents=True)
            prefix='formal/lock12/0/stock/'+side+'/'
            (d/'receipt.json').write_bytes(z.read(idx[prefix+'receipt.json']))
            row=read(d/'receipt.json');files={}
            for k in row['source']:
                (d/k).write_bytes(z.read(idx[prefix+k]));files[k]=d/k
            versions.append(files)
        fallback=stock_fallback(tmp/'stock',versions,row['argv'],ValueError('unexplained deleted closure'))
        assert [fallback['versions'][s]['native_exit'] for s in ('old','new')]==[10,0]
        try:stock_fallback(tmp/'stock',versions,row['argv']+['--64'],ValueError('configuration mismatch'))
        except ValueError:pass
        else:raise AssertionError('unmatched reference accepted')
    for k,row in summary['cases'].items():
        assert all(t['repetitions']==5 for t in row['modes'].values())
    for ver in ('P0','P1'):
        ar=read(E/'multiquery'/ver/'receipt.json')
        assert ar['classification']=='INCOMPLETE_UNWINDING' and len(ar['stream']['queries'])==3
    assert read(E/'controls.json')['finite']['versions']==228
    assert read(ROOT/'project_state.json')['status']=='READY_FOR_REVIEW'
def manifest():
    roots=[E,ROOT/'scripts/stage11b']
    paths=[p for top in roots for p in top.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    paths.extend([ROOT/'reports/stage-11b.md',ROOT/'project_state.json'])
    return {p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in sorted(paths) if p!=E/'manifest.json'}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seal',action='store_true');a=p.parse_args()
    check();doc=dict(base='88ac77921fee14f84e721d85d91a4b7296fe4e23',sha256=manifest())
    if a.seal:(E/'manifest.json').write_bytes((json.dumps(doc,sort_keys=True,indent=2)+'\n').encode())
    assert read(E/'manifest.json')==doc
    print('Verified',len(doc['sha256']),'release files, all raw objects, 120 SAT results (8 source/answer records, 5 source/assignment combinations), both weak-SC controls and all retained-order proofs.')
