"""Cross matched complete inputs between original and enhanced Closure cores, five times."""
import re
import shutil
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.comparison import bounded
from incdeagle.model.identity import file_sha,read,save
from scripts.stage2.check_case import load_case
from scripts.stage7.inputs import validate


def run(source,build,out,trees):
    item=read(ROOT/'reports/evidence/stage-07/matrix.json')['airline_reservations_6']
    case=validate(source,item)
    _,gamma,phi=load_case(case)
    roles=('baseline','enhanced')
    for role,tree in zip(roles,trees):
        d=out/'captures'/role
        if (d/'receipt.json').exists():continue
        d.mkdir(parents=True,exist_ok=True)
        for a,b in [('old/program.c','program.c'),('harness.c','harness.c')]:shutil.copyfile(case/a,d/b)
        binary=tree/'src/cbmc/deagle_exe'
        command=[binary,*gamma['source_argv'],*gamma['verification_output'],'harness.c']
        service=bounded(command,d,d,gamma['limits'],env={'S8_OUT':d,'S8_STREAM':'1','INCDEAGLE_JSON_OUTPUT':d/'result.json'})
        verdict,target=classify((d/'result.json').read_bytes(),service['exit_code'],phi)
        assert verdict==read(source/'trials/airline_reservations_6/1/old_full/verify/verdict.json')
        save(d/'receipt.json',{'role':role,'source_sha256':file_sha(d/'program.c'),'binary_sha256':file_sha(binary),
             'verdict':verdict,'steps':len(target['trace']),'stream_sha256':file_sha(d/'s8-input.bin'),
             'graph_sha256':file_sha(d/'s8-graph.tsv'),'settings_sha256':file_sha(d/'s8-initial.tsv')})
    combos=[(r,s) for r in roles for s in roles]
    for n in range(1,6):
        for src,solver in (combos[n%4:]+combos[:n%4])[::1 if n%2 else -1]:
            d=out/'trials'/str(n)/(src+'-in-'+solver)
            if (d/'receipt.json').exists():continue
            d.mkdir(parents=True,exist_ok=True)
            reference=out/'captures'/src
            exe=build/('driver-'+solver)/'solver-replay'
            service=bounded([exe,reference],d,d,gamma['limits'],env={'S8_OUT':d})
            if service['exit_code']!=0:raise ValueError('Replay failed in '+str(d)+' '+str(service))
            m=re.search(rb'STAGE8_REPLAY\t(\d+)\t(\d+)\t(\d+)\t(\d+)\t(\d+)\t(\d+)',(d/'diagnostic.stdout').read_bytes())
            assert m
            status,elapsed,starts,conflicts,decisions,propagations=map(int,m.groups())
            artifacts=('s8-initial.tsv','s8-sat.tsv','s8-graph.tsv','s8-trace.tsv','s8-search.tsv')
            checks={f:(d/f).read_bytes()==(reference/f).read_bytes() for f in artifacts}
            receipt={'input':src,'solver':solver,'repeat':n,'status_sat':status==0,'solve_wall_ns':elapsed,
                'starts':starts,'conflicts':conflicts,'decisions':decisions,'propagations':propagations,
                'checks':checks,'exact_search_reproduction':all(checks.values()) and status==0,
                'executable_sha256':file_sha(exe)}
            save(d/'receipt.json',receipt)
            print(n,src,solver,receipt['exact_search_reproduction'],round(elapsed/1e9,3),flush=True)


if __name__=='__main__':
    a=list(map(lambda s:Path(s).resolve(),sys.argv[1:]))
    run(*a[:3],a[3:])
