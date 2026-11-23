"""Measure the real frontend exit separately from Python's timeout polling, on frozen sources."""
import json
import os
import select
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.model.identity import file_sha,read,save
from incdeagle.model.repeat import phase_digest
from scripts.stage7.inputs import validate
from scripts.stage8.experiment import PRIORITY


def measure(archive,lock,out,case_name,variant,repeat,traced=False):
    item=read(ROOT/'reports/evidence/stage-07/matrix.json')[case_name]
    case=validate(archive,item)
    gamma=read(case/'gamma.json')
    d=out/case_name/str(repeat)/variant
    front=d/'frontend'
    if (d/'receipt.json').exists():return
    front.mkdir(parents=True,exist_ok=True)
    for src,dst in [('candidate/program.c','program.c'),('harness.c','harness.c')]:shutil.copyfile(case/src,front/dst)
    native=variant in ('timed-recorder','native-recorder','native-system')
    binary=Path(lock['development_binary']) if native else ROOT/'third_party/deagle-stage5/src/cbmc/deagle_exe'
    env=dict(os.environ,LC_ALL='C',INCDEAGLE_OBSERVE_DIR=str(front),INCDEAGLE_JSON_OUTPUT=str(front/'result.json'),
             INCDEAGLE_CPP_RECORD=str(front/'cpp.jsonl'),INCDEAGLE_S4_FRONTEND='1',INCDEAGLE_S4_ROOT=str(d))
    if native:env['S8_OUT']=str(front)
    if variant not in ('system-gcc','native-system'):
        dst=d/'tools/gcc';dst.parent.mkdir(exist_ok=True)
        timed=variant=='timed-recorder'
        shutil.copyfile(ROOT/('scripts/stage8/frontend_gcc_probe.py' if timed else 'scripts/stage3/record_gcc.py'),dst)
        dst.chmod(0o755)
        env['PATH']=str(dst.parent)+':'+env['PATH']
        if timed:env.update(S8_OUT=str(front),S8_GCC_ORIGINAL=str(ROOT/'scripts/stage3/record_gcc.py'))
    argv=[str(binary),*gamma['source_argv'],*gamma['verification_output'],'harness.c']
    before=time.monotonic_ns()
    with (d/'stdout.txt').open('wb') as so,(d/'stderr.txt').open('wb') as se:
        p=subprocess.Popen(argv,cwd=front,env=env,stdout=so,stderr=se,stdin=subprocess.DEVNULL)
        returned=time.monotonic_ns()
        ready=[]
        fd=os.pidfd_open(p.pid)
        poll=select.poll();poll.register(fd,select.POLLIN)
        def observe_exit():
            if poll.poll(300000):ready.append(time.monotonic_ns())
        watcher=threading.Thread(target=observe_exit)
        watcher.start()
        rc=p.wait(timeout=gamma['limits']['timeout_seconds'])
        reaped=time.monotonic_ns()
        watcher.join();os.close(fd)
    assert rc==0 and len(ready)==1
    expected=read(ROOT/'reports/evidence/stage-07/summary.json')['diagnostics'][case_name]['phases']['goto']
    assert phase_digest(read(front/'goto.json'))==expected and (front/'goto.irep').stat().st_size>0
    record={'variant':variant,'repeat':repeat,'case':case_name,'pid':p.pid,'traced':traced,
            'begin_ns':before,'popen_return_ns':returned,'pidfd_ready_ns':ready[0],'wait_return_ns':reaped,
            'child_lifetime_wall_ns':ready[0]-before,'wait_tail_ns':reaped-ready[0],
            'argv':argv,'binary_sha256':file_sha(binary),'goto_digest':expected,'irep_bytes':(front/'goto.irep').stat().st_size,
            'json_bytes':(front/'goto.json').stat().st_size,'candidate_sha256':file_sha(front/'program.c')}
    save(d/'receipt.json',record)


if __name__=='__main__':
    archive,out,build=map(lambda v:Path(v).resolve(),sys.argv[1:4]); lock=read(build)
    if len(sys.argv)>4:
        measure(archive,lock,out,'batch_total','recorder',0,True)
    else:
        variants=['recorder','system-gcc','native-recorder','native-system','timed-recorder']
        for i in range(5):
            for n in PRIORITY[i:]+PRIORITY[:i]:
                for v in variants[i:]+variants[:i]:
                    measure(archive,lock,out,n,v,i+1)
