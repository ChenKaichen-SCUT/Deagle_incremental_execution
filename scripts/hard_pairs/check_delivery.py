"""Validate the distributable package from Git contents, without contacting the server."""
import csv
import gzip
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from restore_evidence import ROOT,archive

def read(path):return json.loads(path.read_bytes())
def sha(data):return hashlib.sha256(data).hexdigest()
D=ROOT/'datasets/stage-12-hard-pairs';E=ROOT/'reports/evidence/stage-12'
def verify():
    manifest=read(D/'manifest.json')
    with (D/'dataset.csv').open(encoding='utf-8',newline='') as fp:rows=list(csv.DictReader(fp))
    assert len(rows)==len({r['case_id'] for r in rows})==len(manifest['accepted'])+len(manifest['screening'])
    raw=E/'raw';index=read(raw/'files.json')
    runs=json.loads(gzip.decompress((E/'all-runs.json.gz').read_bytes()))
    assert len(runs)==manifest['server_runs'] and len({r['out'] for r in runs})==len(runs)
    with archive(raw) as z:
        assert set(index.values())==set(z.namelist())
        for key in set(index.values()):
            if sha(z.read(key))!=key:raise ValueError('corrupt archive object '+key)
        for r in manifest['accepted']:
            cid=r['case_id'];folder=D/cid;src=read(folder/'provenance.json');task=read(folder/'task.yaml')
            assert r['P0_result'] in ('SAT','UNSAT') and r['P1_result'] in ('SAT','UNSAT')
            patch=(folder/'patch.diff').read_bytes();assert sha(patch)==src['patch_sha256']
            assert sha((folder/'unreach-call.prp').read_bytes())==manifest['property_sha256']==task['property_sha256']
            native=read(folder/'baseline.json')['results']
            with tempfile.TemporaryDirectory() as tmp:
                work=Path(tmp);name=Path(task['sides']['old']['file']).name
                (work/name).write_bytes((folder/'old'/name).read_bytes())
                (work/'.gitattributes').write_bytes(b'* -text\n')
                subprocess.run(['git','-c','core.eol=lf','-c','core.autocrlf=false','apply','--no-index','--whitespace=nowarn','-p1',str((folder/'patch.diff').resolve())],cwd=work,check=True,capture_output=True)
                assert (work/name).read_bytes()==(folder/'new'/name).read_bytes(),cid
            for side,q in native.items():
                source=(folder/task['sides'][side]['file']).read_bytes()
                assert sha(source)==task['sides'][side]['sha256']==src['sides'][side]['sha256']
                assert sha((folder/side/'upstream.yml').read_bytes())==src['sides'][side]['yaml_sha256']
                assert q['argv']==task['argv'] and all(v=='SUCCESS' for k,v in q['properties'] if 'unwind' in k)
                assert index['server/'+q['out']+'/'+q['argv'][-1]]==sha(source)
                for k in ('s8-input.bin','s8-graph.tsv','native-state.tsv','bits.tsv','goto.json','raw_ssa.json','sc_input.json','full_model.json','native-bindings.json','search.bin'):
                    assert index['server/'+q['out']+'/'+k]==q['raw_sha256'][k]
            delta=read(folder/'model-delta.json');b=delta['boolean'];mp=dict(b['semantic_mapping'])
            assert len(mp)==len({x//2 for x in mp.values()})==b['semantic_variables']
            for side,k in [('old','old'),('new','new')]:
                assert b[side]['clauses']==b['original_retained_confirmed']+b[k+'_mapped_only']+b[k+'_unknown']
            assert sha((folder/'semantic-diff.json.gz').read_bytes())==delta['semantic_diff_sha256']
    print('verified',manifest['formal_pairs'],'pairs,',len(rows),'CSV rows,',len(runs),'server attempts and',len(set(index.values())),'content-addressed objects')
if __name__=='__main__':verify()
