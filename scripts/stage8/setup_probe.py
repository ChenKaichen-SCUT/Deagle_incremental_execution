"""Isolate the recorder cost on stdin GCC configuration probes and on real source units."""
import os
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.model.identity import read,file_sha,save
from incdeagle.model.repeat import phase_digest
from scripts.stage7.inputs import validate
from scripts.stage8.experiment import PRIORITY

# All four variants pay the same short dispatch shim. Unselected invocations
# go directly to system GCC. These standalone frontend probes never authorize reuse.
SHIM='''#!/bin/sh
last=''
for arg in "$@"; do last=$arg; done
category=stdin
if test -f "$last"; then category=source; fi
if test "$S8_CAPTURE" = both || test "$S8_CAPTURE" = "$category"; then
  exec "$S8_RECORDER" "$@"
fi
exec /usr/bin/gcc "$@"
'''

def run(source,out):
    release=ROOT/'third_party/deagle-stage5/src/cbmc/deagle_exe'
    matrix=read(ROOT/'reports/evidence/stage-07/matrix.json')
    ref=read(ROOT/'reports/evidence/stage-07/summary.json')['diagnostics']
    variants=('none','stdin','source','both')
    for i in range(5):
        for c in PRIORITY[i:]+PRIORITY[:i]:
            case=validate(source,matrix[c]); gamma=read(case/'gamma.json')
            for v in variants[i%4:]+variants[:i%4]:
                d=out/c/str(i+1)/v
                if (d/'receipt.json').exists():continue
                front=d/'frontend';bin_dir=d/'tools'
                front.mkdir(parents=True,exist_ok=True);bin_dir.mkdir(exist_ok=True)
                for name,dst in [('candidate/program.c','program.c'),('harness.c','harness.c')]:
                    shutil.copyfile(case/name,front/dst)
                tools=bin_dir/'gcc';tools.write_text(SHIM);tools.chmod(0o755)
                recorder=bin_dir/'record';shutil.copyfile(ROOT/'scripts/stage3/record_gcc.py',recorder);recorder.chmod(0o755)
                env=dict(os.environ,LC_ALL='C',PATH=str(bin_dir)+':'+os.environ['PATH'],S8_RECORDER=str(recorder),S8_CAPTURE=v,
                         INCDEAGLE_OBSERVE_DIR=str(front),INCDEAGLE_CPP_RECORD=str(front/'cpp.jsonl'),
                         INCDEAGLE_S4_FRONTEND='1',INCDEAGLE_S4_ROOT=str(d),INCDEAGLE_JSON_OUTPUT=str(front/'result.json'))
                argv=[str(release),*gamma['source_argv'],*gamma['verification_output'],'harness.c']
                with (d/'stdout.txt').open('wb') as so,(d/'stderr.txt').open('wb') as se:
                    before=time.monotonic_ns()
                    proc=subprocess.Popen(argv,cwd=front,env=env,stdin=subprocess.DEVNULL,stdout=so,stderr=se)
                    fd=os.pidfd_open(proc.pid)
                    try:
                        poll=select.poll();poll.register(fd,select.POLLIN)
                        if not poll.poll(gamma['limits']['timeout_seconds']*1000):
                            proc.kill();proc.wait();raise TimeoutError(str(d))
                        done=time.monotonic_ns()
                    finally:os.close(fd)
                    assert proc.wait()==0
                digest=phase_digest(read(front/'goto.json'))
                assert digest==ref[c]['phases']['goto']
                save(d/'receipt.json',dict(case=c,variant=v,repeat=i+1,child_wall_ns=done-before,goto_digest=digest,
                                           argv=argv,binary_sha256=file_sha(release),source_sha256=file_sha(front/'program.c')))
    print('100 standalone GCC dispatch controls completed',flush=True)

if __name__=='__main__':run(*map(lambda s:Path(s).resolve(),sys.argv[1:]))
