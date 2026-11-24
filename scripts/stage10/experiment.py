"""Run fresh and persistent native SC/Closure verification with independent full models in each phase."""
import argparse
import os
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.counterexample import normalize
from incdeagle.model.identity import file_sha,read,save
from incdeagle.model.repeat import phase_digest
from scripts.stage7.oracles import retained_projection
from scripts.stage10.bind import registry,decide

CASES=('batch_total','batch_retained','fib_updates_8')
FALLBACK='split_counter'
PHASES=('goto','raw_ssa','sc_input','full_model')
clock=time.monotonic_ns

def native_stats(p):
    rows=[list(map(int,l.split())) for l in p.read_text().splitlines()]
    keys='time object pid vars originals learnts assignments level ok arena_bytes starts decisions conflicts propagations theory_propagations theory_conflicts graph_nodes peak_rss_kib'.split()
    assert len(rows)==2 and all(len(r)==len(keys) for r in rows)
    return [dict(zip(keys,r)) for r in rows]

def signed_stats(p):
    out={}
    for r in p.read_text().splitlines():
        k,v=r.split('\t');out[k]=int(v) if v.isdecimal() else v
    return out

def ready_line(proc,deadline):
    with selectors.DefaultSelector() as poll:
        poll.register(proc.stdout,selectors.EVENT_READ)
        while True:
            left=deadline-time.monotonic()
            if left<=0 or not poll.select(left):raise TimeoutError('native worker deadline')
            line=proc.stdout.readline()
            if not line:raise RuntimeError('native solver worker exited')
            if line.startswith(b'STAGE10_DONE '):return line.decode().strip()
            # Python buffered reads may prefetch additional native lines. Worker emits its
            # protocol on a dedicated descriptor; normal solver stdout goes to a file.

def stop(proc):
    if proc is not None and proc.poll() is None:
        os.killpg(proc.pid,signal.SIGKILL);proc.wait()

def full_run(d,case,version,exe,worker,old,mode,test,settings,phi,gamma,files):
    d.mkdir();(d/'worker').mkdir()
    work=d.parent/'source';work.mkdir(exist_ok=True)
    for item,name in [(version+'/program.c','program.c'),('harness.c','harness.c')]:
        shutil.copyfile(case/item,d/name)
        shutil.copyfile(d/name,work/name)
        assert file_sha(d/name)==files[item]
    s0,s1=socket.socketpair()
    env={k:os.environ[k] for k in ('PATH','LANG','HOME') if k in os.environ}
    env.update(LC_ALL='C',INCDEAGLE_OBSERVE_DIR=str(d),INCDEAGLE_JSON_OUTPUT=str(d/'result.json'),
               S8_OUT=str(d),S8_STREAM='1',S10_DIR=str(d))
    if worker:env['S10_BRIDGE_FD']=str(s1.fileno())
    cmd=[str(exe),*gamma['source_argv'],*gamma['verification_output'],'harness.c']
    end=time.monotonic()+gamma['limits']['timeout_seconds']
    save(d/'command.json',dict(argv=cmd,mode=mode,model_reuse='off',environment_keys=sorted(env),
          memory_bytes=gamma['limits']['memory_bytes'],affinity=sorted(os.sched_getaffinity(0))))
    reg=None;bind_ns=0;plan=None
    before=clock()
    with (d/'stdout').open('wb') as out,(d/'stderr').open('wb') as err:
        proc=subprocess.Popen(cmd,env=env,cwd=work,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                              pass_fds=(s1.fileno(),) if worker else (),start_new_session=True)
        s1.close()
        try:
            if worker:
                s0.settimeout(max(.01,end-time.monotonic()))
                if s0.recv(1)!=b'R':raise RuntimeError('model process exited before solve '+str(d))
                start=clock()
                try:
                    reg=registry(d,settings)
                    plan=decide(old,reg,test) if version=='candidate' and old and 'groups' in old else dict(
                      reason='old' if version=='old' else 'refuse_old_registry',pairs=[],confirmed=0)
                except (ValueError,KeyError,OSError,IndexError) as e:
                    reg={'error':str(e)};plan=dict(reason='old' if version=='old' else 'refuse_incomplete_registry',pairs=[],confirmed=0)
                ids=sorted(reg.get('groups',{})) if version=='old' else [a for a,b in plan['pairs']]
                (d/'plan.txt').write_text(plan['reason']+'\n'+' '.join(map(str,ids))+'\n')
                save(d/'admission.json',plan);save(d/'registry.json',reg)
                bind_ns=clock()-start
                worker.stdin.write((str(d)+'\n').encode());worker.stdin.flush()
                line=ready_line(worker,end)
                assert line=='STAGE10_DONE '+('0' if version=='old' else '1')
                s0.sendall(b'D')
            rc=proc.wait(timeout=max(.01,end-time.monotonic()))
        finally:
            stop(proc);s0.close()
    outer=clock()-before
    verdict,target=classify((d/'result.json').read_bytes(),rc,phi)
    if verdict['classification']=='VIOLATION':
        trace=normalize(target,phi,gamma,{'program.c':files[version+'/program.c'],'harness.c':files['harness.c']},'result.json',version=version)
        save(d/'counterexample.json',trace)
        if version=='candidate' and case.name=='batch_retained':assert retained_projection('batch_retained',trace)
    markers=dict((k,int(v)) for k,v in (l.split() for l in (d/'boundary.tsv').read_text().splitlines()))
    ops={v[0]:list(map(int,v[1:])) for v in (s.split() for s in (d/'s8-native.tsv').read_text().splitlines())}
    visits=read(d/'visits.json')
    assert ops['other_dispatch'][0]==len(visits)>0 and ops['sc'][0]>0 and ops['rf'][0]>0 and ops['po'][0]>0
    assert all(ops[name][0]==0 for name in ('prefix_dispatch','rebind','prefix_symbols','irep_read','rf_replay'))
    assert not (d/'native-import.json').exists() and not (d/'old_done.json').exists()
    ms=read(d/'metrics.json')['phase_nanoseconds']
    native=native_stats(d/('worker/native-state.tsv' if worker else 'native-state.tsv'))
    first,last=native
    stats=signed_stats(d/'worker/stats.tsv') if worker else {}
    assert first['pid']==last['pid'] and first['object']==last['object']
    for k in ('starts','decisions','conflicts','propagations','theory_propagations','theory_conflicts'):
        delta=last[k]-first[k]
        if worker:assert delta==stats[k],(d,k,delta,stats[k])
        stats[k]=delta
    init=markers['factory_end']-markers['factory_begin']
    search=ops['search']
    if worker:
        metered={z[0]:list(map(int,z[1:])) for z in (l.split() for l in (d/'worker/s8-native.tsv').read_text().splitlines())}
        search=metered['search']
    timing=dict(factory_ns=init,pure_search_ns=search[1],pure_search_cpu_ns=search[2],solve_ns=last['time']-first['time'],
        model_to_result_ns=markers['decider_return']-markers['model_ready']+init,
        capture_encode_graph_ns=ms['cnf_and_graph'],goal_encode_ns=ms['goal_conversion'],bind_ns=bind_ns,
        program_wall_ns=outer)
    s=dict(verdict=verdict,exit=rc,stats=stats,native=native,times=timing,
      phases={n:phase_digest(read(d/(n+'.json'))) for n in PHASES},model_process=proc.pid,
      full_dispatches=len(visits),sc_calls=ops['sc'][0],rf_calls=ops['rf'][0],po_calls=ops['po'][0],
      solver_input=file_sha(d/'s8-input.bin'),graph=file_sha(d/'s8-graph.tsv'))
    save(d/'receipt.json',s)
    return reg,s

def pair(src,exe,driver,d,case_name,mode,test='normal'):
    if (d/'complete.json').exists():return
    if d.exists():d.rename(d.with_name(d.name+'-incomplete-'+str(clock())))
    d.mkdir(parents=True)
    all_cases=read(ROOT/'reports/evidence/stage-07/matrix.json');item=all_cases[case_name]
    case=src/item['case_dir'];files=item['files']
    assert all(file_sha(case/k)==v for k,v in files.items())
    phi=read(case/'phi.json');gamma=read(case/'gamma.json')
    for n in ('phi.json','gamma.json','patch.diff'):
        shutil.copyfile(case/n,d/n)
    setting=dict(backend='Minisat::ClosureSolver/SC',binary=file_sha(exe),gamma=gamma,phi=phi)
    worker=None;reg=None;phases=[]
    with (d/'worker.stdout').open('wb') as wout,(d/'worker.stderr').open('wb') as werr:
        try:
            if mode=='S':
                reader,writer=os.pipe()
                worker=subprocess.Popen([str(driver),test],stdin=subprocess.PIPE,stdout=wout,stderr=werr,
                    env=dict(os.environ,S10_PROTOCOL_FD=str(writer)),pass_fds=(writer,),start_new_session=True)
                os.close(writer);worker.stdout=os.fdopen(reader,'rb',buffering=0)
            for version in ('old','candidate'):
                reg,s=full_run(d/version,case,version,exe,worker,reg,mode,test,setting,phi,gamma,files)
                reference=read(src/'trials'/case_name/'1'/('old_full' if version=='old' else 'full')/'verify/verdict.json')
                assert s['verdict']==reference,(case_name,mode,version,s['verdict'],reference)
                phases.append(s)
            if worker:worker.stdin.close();assert worker.wait(timeout=10)==0;worker.stdout.close()
        finally:stop(worker)
    save(d/'complete.json',dict(case=case_name,mode=mode,test=test,versions=[s['verdict']['classification'] for s in phases],
         property=phi['id'],limits=gamma['limits']))
    print(case_name,mode,test,phases[1]['verdict']['classification'],phases[1]['stats'].get('admission','fresh'),
          phases[1]['stats'].get('actually_reattached',0),round(phases[1]['times']['model_to_result_ns']/1e6,2),flush=True)

def main(src,exe,driver,out,group):
    out.mkdir(parents=True,exist_ok=True)
    cg=Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().strip().split('::',1)[1].lstrip('/')
    assert int((cg/'memory.max').read_text())==21474836480 and sorted(os.sched_getaffinity(0))==list(range(8))
    save(out/'configuration.json',dict(cgroup=str(cg),memory_bytes=int((cg/'memory.max').read_text()),
         cpu=sorted(os.sched_getaffinity(0)),model_reuse='off',native_sha256=file_sha(exe),worker_sha256=file_sha(driver),
         theory_import=False,api_calls=0))
    if group=='pilot':
        for c in CASES:
            for mode in ('F','S'):pair(src,exe,driver,out/c/mode,c,mode)
    elif group=='controls':
        d=out/'assumptions';d.mkdir(exist_ok=True)
        with (d/'stdout').open('wb') as f:subprocess.run([driver,'--controls',d],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=60)
        fixed=out/'same-graph';fixed.mkdir(exist_ok=True)
        for name in [f'{v}-{i}' for v in ('shared','fresh') for i in range(7)]+['direction-0','direction-1']:
            (fixed/name).mkdir(exist_ok=True)
        with (fixed/'stdout').open('wb') as f:
            subprocess.run([driver,'--same-graph',out.parent/'pilot/batch_total/F/old',fixed],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=60)
        for c,test in [('batch_total','bad-map'),('fib_updates_8','damage-learning'),(FALLBACK,'normal')]:
            pair(src,exe,driver,out/(c+'-'+test)/'S',c,'S',test)
            pair(src,exe,driver,out/(c+'-'+test)/'F',c,'F')
    else:
        for i in range(8):
            cases=CASES[i%3:]+CASES[:i%3]
            for j,c in enumerate(cases):
                if i>=5 and c!='fib_updates_8':continue
                for mode in (('F','S') if (i+j)%2==0 else ('S','F')):
                    pair(src,exe,driver,out/c/f'{i+1:02}'/mode,c,mode)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('stage7','native','driver','output'):p.add_argument(k,type=Path)
    p.add_argument('group',choices=['pilot','formal','controls']);a=p.parse_args()
    main(*[getattr(a,k).resolve() for k in ('stage7','native','driver','output')],a.group)
