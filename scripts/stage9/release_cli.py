"""Exercise the production CLI with locked release binaries and the actual frozen patches."""
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.model.identity import file_sha,read,save
from scripts.stage7.check_evidence import audit_theory

def main(stage7,out):
    out.mkdir(parents=True,exist_ok=True)
    matrix=read(ROOT/'reports/evidence/stage-07/matrix.json')
    for c,n in [('batch_total',1),('fib_updates_8',14)]:
        d=out/c
        if (d/'receipt.json').exists():continue
        case=stage7/matrix[c]['case_dir']
        d.mkdir()
        cmd=[sys.executable,'-B','-m','incdeagle.cli','run-case','--case',str(case/'task.yaml'),
             '--repair','manual','--patch',str(case/'patch.diff'),'--check-model','--out',str(d/'run')]
        with (d/'stdout').open('wb') as so,(d/'stderr').open('wb') as se:
            p=subprocess.run(cmd,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=so,stderr=se)
        result=read(d/'run/workflow.json')
        assert p.returncode==0 and result['status']=='COMPLETED' and result['model_match'] and result['agreement']=='DEFINITE_AGREEMENT',result
        assert result['repair_usage']['api_calls']==0
        pair=next((d/'run').rglob('pair/session.json')).parent
        session=read(pair/'session.json')
        theory=read(pair/'theory-summary.json')
        audit_theory(pair,matrix[c]['files'])
        assert theory['accepted']==theory['imported']==n
        save(d/'receipt.json',dict(case=c,exit=p.returncode,agreement=result['agreement'],model_match=result['model_match'],
             patch=file_sha(case/'patch.diff'),candidate=session['inputs_sha256']['program.c'],binary=session['tool'],
             imported=n,prefix=session['native']['reused_prefix_symex_steps'],api_calls=0))
        print('Release CLI',c,result['status'],n,flush=True)
if __name__=='__main__':main(*[Path(s).resolve() for s in sys.argv[1:]])
