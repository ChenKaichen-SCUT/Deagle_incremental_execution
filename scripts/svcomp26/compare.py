"""Adapt only the stage-10 controller to a single official preprocessed translation unit."""
import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from config import DEAGLE,WORKER,ROOT,folder
from oracle import interpret,metadata,options,read,save,sha
sys.path.insert(0,str(ROOT))
from incdeagle.model.repeat import phase_digest
from scripts.stage10.bind import registry,decide
from scripts.stage10.experiment import PHASES,native_stats,signed_stats,ready_line,stop
from scripts.stage10.evidence import read_stream
from stream import inspect,states

def measure(d,work,src,exe,worker,previous,phase,task):
    d.mkdir();(d/'worker').mkdir();work.mkdir(parents=True,exist_ok=True)
    unit=work/'program.i';shutil.copyfile(src,unit)
    m=metadata(task)
    argv=[str(exe),*options(m),'--property','reach_error.assertion.1','--trace','--json-ui','program.i']
    env=dict(PATH=os.environ['PATH'],LC_ALL='C',S8_OUT=str(d),S8_STREAM='1',S10_DIR=str(d),
             INCDEAGLE_OBSERVE_DIR=str(d),INCDEAGLE_JSON_OUTPUT=str(d/'result.json'))
    s0,s1=socket.socketpair()
    if worker:env['S10_BRIDGE_FD']=str(s1.fileno())
    settings=dict(backend='Minisat::ClosureSolver/SC',native=DEAGLE,worker=WORKER,options=argv[1:],yaml=m['yaml_sha256'],property=m['property_sha256'])
    start=time.monotonic_ns();deadline=time.monotonic()+180;reg=None;bind=0
    cg=Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().strip().split('::',1)[1].lstrip('/')
    save(d/'command.json',dict(argv=argv,input_sha256=sha(unit),model_reuse=False,environment_keys=sorted(env),
        limits=dict(timeout_s=180,memory_bytes=(cg/'memory.max').read_text().strip(),affinity=sorted(os.sched_getaffinity(0))),settings=settings))
    with (d/'stdout').open('wb') as so,(d/'stderr').open('wb') as se:
        child=subprocess.Popen(argv,cwd=work,env=env,stdout=so,stderr=se,stdin=subprocess.DEVNULL,start_new_session=True,
            pass_fds=(s1.fileno(),) if worker else ())
        s1.close()
        try:
            if worker:
                s0.settimeout(max(.01,deadline-time.monotonic()))
                if s0.recv(1)!=b'R':raise RuntimeError('frontend exited before first solve')
                mark=time.monotonic_ns()
                try:
                    reg=registry(d,settings)
                except (ValueError,KeyError,OSError,IndexError,RecursionError) as ex:
                    reg={'error':type(ex).__name__+': '+str(ex)}
                plan=dict(reason='old' if phase==0 else 'refuse_incomplete_registry',pairs=[],confirmed=0)
                if phase and 'groups' in reg and previous and 'groups' in previous:plan=decide(previous,reg)
                ids=sorted(reg.get('groups',{})) if phase==0 else [a for a,b in plan['pairs']]
                (d/'plan.txt').write_text(plan['reason']+'\n'+' '.join(map(str,ids))+'\n')
                save(d/'registry.json',reg);save(d/'admission.json',plan)
                bind=time.monotonic_ns()-mark
                worker.stdin.write((str(d)+'\n').encode());worker.stdin.flush()
                if ready_line(worker,deadline)!='STAGE10_DONE '+str(phase):raise ValueError('native phase mismatch')
                s0.sendall(b'D')
                s0.settimeout(max(.01,deadline-time.monotonic()))
                extra=s0.recv(1)
                if extra:
                    save(d/'extra-bridge-request.json',dict(byte=extra.hex(),phase=phase))
                    raise RuntimeError('refuse_additional_solver_query')
            rc=child.wait(timeout=max(.01,deadline-time.monotonic()))
        finally:stop(child);s0.close()
    wall=time.monotonic_ns()-start
    result,witness=interpret(read(d/'result.json'),rc)
    assert result['target']=='reach_error.assertion.1' and result['classification'] in ('VIOLATION','BOUNDED_PASS','INCOMPLETE_UNWINDING')
    ops=lambda path:{k:list(map(int,v)) for k,*v in (l.split() for l in path.read_text().splitlines())}
    metrics=ops(d/'s8-native.tsv');visits=read(d/'visits.json')
    assert metrics['other_dispatch'][0]==len(visits)>0 and all(metrics[k][0]>0 for k in ('front','sc','rf','po','ssa_convert'))
    assert all(metrics[k][0]==0 for k in ('prefix_dispatch','rebind','prefix_symbols','irep_read','rf_replay'))
    assert not (d/'old_done.json').exists() and not (d/'native-import.json').exists()
    loc=d/'worker' if worker else d
    native=states(loc/'native-state.tsv');first,last=native[0],native[-1]
    assert first['pid']==last['pid'] and first['object']==last['object']
    born=signed_stats(loc/'stats.tsv') if worker else {}
    counts={}
    for k in ('starts','decisions','conflicts','propagations','theory_propagations','theory_conflicts'):
        counts[k]=sum(y[k]-x[k] for x,y in zip(native[::2],native[1::2]))
        assert not worker or born[k]==counts[k]
    search=ops(loc/'s8-native.tsv')['search']
    b={k:int(v) for k,v in (z.split() for z in (d/'boundary.tsv').read_text().splitlines())}
    timing=dict(program_wall_ns=wall,pure_search_ns=search[1],search_cpu_ns=search[2],
        solve_ns=sum(y['time']-x['time'] for x,y in zip(native[::2],native[1::2])),model_to_result_ns=b['factory_end']-b['factory_begin']+b['decider_return']-b['model_ready'],bind_ns=bind)
    stream,_=inspect(d/'s8-input.bin');n=stream['variables']
    assert len(stream['queries'])==len(native)//2
    if worker:
        _,cnf,goals=read_stream(d/'s8-input.bin')
        assert born['input_variables']==n and born['input_clauses']==len(cnf)
        fields=(d/'answer.txt').read_text().split()
        ans=list(map(int,fields[:2]))
        assert ans[0]==(0 if rc==10 else 1) and ans[1]==n
        if ans[0]==0:
            bits=list(map(int,fields[2:2+n]));assert len(bits)==n
            holds=lambda x:bits[x//2]==(x&1)
            assert all(any(holds(x) for x in c) for c in cnf) and all(holds(x) for x in goals)
    receipt=dict(source_sha256=sha(unit),target_result=result['classification'],target=result['target'],properties=result['property_rows'],exit=rc,
        model_pid=child.pid,native=native,counters=counts,driver=born,timing=timing,variables=n,clauses=stream['clauses'],stream=stream,
        phases={k:phase_digest(read(d/(k+'.json'))) for k in PHASES},dispatch=len(visits),sc=metrics['sc'][0],
        cnf_sha256=sha(d/'s8-input.bin'),graph_sha256=sha(d/'s8-graph.tsv'),search_sha256=sha(loc/'search.bin'))
    save(d/'receipt.json',receipt)
    return reg,receipt

def run_pair(base,root,task,roundno,exe,driver,mode,sources):
    base.mkdir(parents=True,exist_ok=False);worker=None;prev=None;rows=[];start=time.monotonic_ns()
    with (base/'worker.stdout').open('wb') as out,(base/'worker.stderr').open('wb') as err:
        try:
            if mode=='S':
                r,w=os.pipe()
                worker=subprocess.Popen([str(driver),'normal'],stdin=subprocess.PIPE,stdout=out,stderr=err,
                    env=dict(PATH=os.environ['PATH'],LC_ALL='C',S10_PROTOCOL_FD=str(w)),pass_fds=(w,),start_new_session=True)
                os.close(w);worker.stdout=os.fdopen(r,'rb',buffering=0)
            for phase,src in enumerate(sources):
                prev,row=measure(base/('old','candidate')[phase],root/'work'/task,src,exe,worker,prev,phase,task)
                rows.append(row)
            if worker:
                worker.stdin.close();assert worker.wait(timeout=10)==0;worker.stdout.close()
            assert rows[0]['model_pid']!=rows[1]['model_pid']
            if not worker:assert rows[0]['native'][0]['pid']!=rows[1]['native'][0]['pid']
            save(base/'complete.json',dict(mode=mode,round=roundno,wall_ns=time.monotonic_ns()-start))
            return rows
        finally:stop(worker)
def main(root,exe,driver,task,roundno,repeats):
    assert sha(exe)==DEAGLE and sha(driver)==WORKER
    old=folder(task)/metadata(task)['input'] if roundno==1 else root/'rounds'/task/f'P{roundno-1}/candidate.i'
    new=root/'rounds'/task/f'P{roundno}/candidate.i'
    assert sha(new)==read(new.parent/'model.json')['candidate_sha256']
    for trial in range(1,repeats+1):
        d=root/'pairs'/task/f'P{roundno-1}-P{roundno}'/str(trial);groups={}
        for mode in (('F','S') if trial%2 else ('S','F')):
            base=d/mode
            if (base/'complete.json').exists():groups[mode]=[read(base/k/'receipt.json') for k in ('old','candidate')];continue
            if base.exists():raise ValueError('incomplete run already exists: '+str(base))
            dispatch=mode;refusal=None
            if mode=='S':
                reference=d.parent/'1/F'
                refs=[read(reference/k/'receipt.json') for k in ('old','candidate')]
                goal_counts=[len(v['stream']['queries']) for v in refs]
                if goal_counts!=[1,1]:dispatch='fresh-on-refusal';refusal=dict(reason='refuse_multi_query_stream',native_queries=goal_counts,source='first independent F receipts',scope='frozen task/versions/options')
                elif any(len(v['properties'])>1 for v in refs):
                    dispatch='fresh-on-refusal'
                    refusal=dict(reason='refuse_unresolved_followup_goals',native_queries=goal_counts,property_counts=[len(v['properties']) for v in refs],
                                 source='frozen worker accepts one solve per version; property driver may request a follow-up after a SAT witness')
            try:
                groups[mode]=run_pair(base,root,task,roundno,exe,driver,dispatch,[old,new])
                if refusal:save(base/'refusal.json',refusal)
            except (RuntimeError,ValueError,AssertionError,TimeoutError,OSError,subprocess.TimeoutExpired) as ex:
                save(base/'failure.json',dict(reason=type(ex).__name__+': '+str(ex),mode=mode))
                if mode=='S':
                    groups['emergency']=run_pair(d/'emergency-fresh',root,task,roundno,exe,driver,'F',[old,new])
                else:raise
        if 'S' in groups:
            for f,s in zip(groups['F'],groups['S']):
                for k in ('target_result','phases','dispatch','cnf_sha256','graph_sha256','variables','clauses','source_sha256'):assert f[k]==s[k],k
        print(task,roundno,trial,{k:[r['target_result'] for r in v] for k,v in groups.items()},flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for x in ('root','exe','driver'):p.add_argument(x,type=Path)
    p.add_argument('task');p.add_argument('round',type=int,choices=[1,2]);p.add_argument('--repeats',type=int,default=3)
    a=p.parse_args();main(a.root.resolve(),a.exe.resolve(),a.driver.resolve(),a.task,a.round,a.repeats)
