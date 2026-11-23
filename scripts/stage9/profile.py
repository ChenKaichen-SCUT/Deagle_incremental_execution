"""Fifty separate instrumented frontend runs. Time real GCC, wrapper, collector and exit."""
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
from scripts.stage8.statistics8 import native
from scripts.stage9 import frontend
from scripts.stage9.run_matrix import FIRST


def measure(before,archive,lock,out,case,variant,i,meter):
    d=out/case/str(i)/variant
    if (d/'receipt.json').is_file():return
    d.mkdir(parents=True)
    front=d/'frontend';front.mkdir()
    tools=d/'tools';tools.mkdir()
    source=archive/read(ROOT/'reports/evidence/stage-07/matrix.json')[case]['case_dir']
    for a,b in [('candidate/program.c','program.c'),('harness.c','harness.c')]:
        shutil.copyfile(source/a,front/b)
    real=d/'real-gcc';os.link(meter,real)
    route=d/'outer';route.mkdir();os.link(meter,route/'gcc')
    inner=tools/'wrapped'
    text=(ROOT/'scripts/stage9/dispatch.sh' if variant=='after' else before/'scripts/stage3/record_gcc.py').read_text()
    if variant=='before':
        assert text.count('source = Path(')==1 and text.count('sys.stdout.buffer.write')==1
        text=text.replace('source = Path(', 'import time\nrecord_start=time.monotonic_ns()\nsource = Path(')
        text=text.replace('sys.stdout.buffer.write', "with open(os.environ['S9_REDUCE_LOG'],'a') as log: print(time.monotonic_ns()-record_start,file=log)\nsys.stdout.buffer.write")
    inner.write_text(text.replace('/usr/bin/gcc',str(real)));inner.chmod(0o755)
    env=dict(os.environ,LC_ALL='C',INCDEAGLE_OBSERVE_DIR=str(front),INCDEAGLE_JSON_OUTPUT=str(front/'result.json'),
             INCDEAGLE_CPP_RECORD=str(front/'cpp.jsonl'),INCDEAGLE_S4_FRONTEND='1',INCDEAGLE_S4_ROOT=str(d),S8_OUT=str(front),
             S9_PROFILE_WRAPPER=str(inner),S9_PROFILE_LOG=str(d/'gcc.tsv'),S9_REDUCE_LOG=str(d/'legacy-reducer.tsv'))
    gamma=read(source/'gamma.json')
    cmd=[lock['development_binary'],*gamma['source_argv'],*gamma['verification_output'],'harness.c']
    tc=frontend.Toolchain();tc.snapshot(env)  # same warm tool identities established during P0.
    rec=None;ready=[]
    with (front/'stdout').open('wb') as so,(front/'stderr').open('wb') as se:
        begin=time.monotonic_ns()
        if variant=='after':
            rec=frontend.Candidate(front,tools,env,tc)
            env.update(rec.env)
        env['PATH']=str(route)+':'+env['PATH']
        launch=time.monotonic_ns()
        p=subprocess.Popen(cmd,cwd=front,env=env,stdout=so,stderr=se,stdin=subprocess.DEVNULL,start_new_session=True)
        def observe():
            fd=os.pidfd_open(p.pid)
            try:
                poll=select.poll();poll.register(fd,select.POLLIN)
                if poll.poll(300000):ready.append(time.monotonic_ns())
            finally:os.close(fd)
        t=threading.Thread(target=observe);t.start()
        if rec:
            rc=rec.wait(p,lambda:max(.001,300-(time.monotonic_ns()-begin)/1e9))
            frontend.confirm_identity(front,env,tc)
        else:rc=p.wait(timeout=300)
        end=time.monotonic_ns()
        t.join()
        if rec:rec.close()
    assert rc==0 and len(ready)==1
    expected=read(ROOT/'reports/evidence/stage-07/summary.json')['diagnostics'][case]['phases']['goto']
    assert phase_digest(read(front/'goto.json'))==expected
    gcc={}
    for line in (d/'gcc.tsv').read_text().splitlines():
        role,kind,a,b,status=line.split('\t')
        assert status=='0'
        gcc.setdefault(role+'_'+kind,[]).append(int(b)-int(a))
    assert sorted(map(len,gcc.values()))==[2,2,3,3] and len(gcc)==4
    stats=native(front)
    g={k:sum(v) for k,v in gcc.items()}
    metrics=read(front/'frontend-metrics.json') if rec else {}
    whole=end-begin
    reduce_ns=metrics['reducer_ns'] if rec else sum(map(int,(d/'legacy-reducer.tsv').read_text().splitlines()))
    # The two config queries precede get_goto_program. File preprocessing is nested.
    calc=stats['front'][1]-g['wrapper_file']+g['gcc_file']
    save(d/'receipt.json',dict(case=case,repeat=i,variant=variant,goto=expected,binary_sha256=file_sha(Path(cmd[0])),
          begin_ns=begin,launch_ns=launch,end_ns=end,ready_ns=ready[0],wall_ns=whole,
          exit_tail_ns=metrics.get('exit_observed_ns',end)-ready[0],post_exit_to_end_ns=end-ready[0],
          prepare_ns=launch-begin,dependency_reduce_ns=reduce_ns,native_front_ns=stats['front'][1],
          native_preprocess_ns=stats['preprocess'][1],native_parse_ns=stats['parse'][1],
          native_typecheck_ns=stats['typecheck'][1],native_goto_ns=stats['goto_convert'][1],
          native_json_ns=stats['goto_json'][1],native_irep_ns=stats['irep_write'][1],
          adjusted_native_front_ns=calc,wrapper_minus_gcc_ns=g['wrapper_file']+g['wrapper_stdin']-g['gcc_file']-g['gcc_stdin'],**g))
    print(case,i,variant,round(whole/1e6,2),flush=True)

def main(before,archive,lock,out):
    out.mkdir(parents=True,exist_ok=True)
    meter=out/'clock-exec'
    cmd=['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',str(ROOT/'scripts/stage9/clock_exec.c'),'-o',str(meter)]
    subprocess.run(cmd,check=True)
    save(out/'build.json',dict(argv=cmd,source_sha256=file_sha(ROOT/'scripts/stage9/clock_exec.c'),binary_sha256=file_sha(meter)))
    lock=read(lock)
    for i in range(5):
        for j,case in enumerate(FIRST[i:]+FIRST[:i]):
            for v in (('before','after') if (i+j)%2==0 else ('after','before')):
                measure(before,archive,lock,out,case,v,i+1,meter)
if __name__=='__main__':main(*[Path(s).resolve() for s in sys.argv[1:]])
