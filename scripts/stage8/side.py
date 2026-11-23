"""Separate full-model observers, deep solver inputs and same-binary diagnostic controls."""
import os
import shutil
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.comparison import bounded
from incdeagle.model.identity import file_sha,read,save
from scripts.stage2.check_case import load_case
from scripts.stage7.inputs import validate
from scripts.stage7.results import runtime_messages
from scripts.stage8.experiment import one,PRIORITY,OTHER
from scripts.stage8.frontend_probe import measure


def direct(archive,build,out,name,version,role,detail,stream,repeat):
    d=out/name/version/str(repeat)/(role+'-'+('on' if detail else 'off'))
    if (d/'receipt.json').exists():return
    d.mkdir(parents=True,exist_ok=True)
    case=validate(archive,read(ROOT/'reports/evidence/stage-07/matrix.json')[name])
    _,gamma,phi=load_case(case)
    binary=Path(build[role+'_binary'])
    for src,target in [(version+'/program.c','program.c'),('harness.c','harness.c')]:shutil.copyfile(case/src,d/target)
    env={'INCDEAGLE_JSON_OUTPUT':str(d/'result.json')}
    if detail:env.update(S8_OUT=str(d))
    if stream:env.update(S8_STREAM='1')
    cmd=[binary,*gamma['source_argv'],*gamma['verification_output'],'harness.c']
    rc=bounded(cmd,d,d,gamma['limits'],env=env)
    verdict,target=classify((d/'result.json').read_bytes(),rc['exit_code'],phi)
    old=version=='old'
    known=read(archive/'trials'/name/'1'/('old_full' if old else 'full')/'verify/verdict.json')
    assert verdict==known
    save(d/'receipt.json',{'case':name,'mode':role,'version':version,'repeat':repeat,'detail':detail,
         'source_sha256':file_sha(d/'program.c'),'binary_sha256':file_sha(binary),'result':verdict,
         'steps':len(target['trace']) if verdict['classification']=='VIOLATION' else 0,
         'wall_ns':rc['wall_ns'],'solver':runtime_messages(d/'result.json'),'deep_stream':stream})


def main(source,lock,out):
    build=read(lock)
    for c in (*PRIORITY,*OTHER):
        one(source,lock,out/'models',c,'F1',1,True,{'observe':True})
    for role in ('baseline','development'):
        direct(source,build,out/'ordered','airline_reservations_6','old',role,True,True,1)
    for mode in ('I2','I3'):
        one(source,lock,out/'ordered-fib','fib_updates_8',mode,1,True,{'stream':True})
    # Separate same diagnostic baseline, with and without its timers, matched by repeat.
    for i in range(5):
        for c in PRIORITY:
            for detailed in ([True,False] if (i+PRIORITY.index(c))%2 else [False,True]):
                direct(source,build,out/'baseline-meter',c,'candidate','baseline',detailed,False,i+1)
    print('Separate observer, input sequence and overhead controls complete.',flush=True)


if __name__=='__main__':
    source,lock,out=map(lambda s:Path(s).resolve(),sys.argv[1:])
    main(source,lock,out)
