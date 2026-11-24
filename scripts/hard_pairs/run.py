"""Resource-aware queue for independent cold runs of the pinned native Deagle."""
import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import time
from collections import Counter
from pathlib import Path

BINARY = 'b84a95d9d02e9fc48217373bf71564db1cb8ce4029644936a893aaaaef0a529e'
GIB = 1024 ** 3
STATE = 'ns object pid variables original_live learnt_live assigned level ok arena starts decisions conflicts propagations theory_propagations theory_conflicts graph_nodes rss_kib'.split()


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(2**20), b''):
            h.update(b)
    return h.hexdigest()


def write(path, obj):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, sort_keys=True, indent=2) + '\n')
    os.replace(tmp, path)


def available():
    mem = {p.split(':')[0]: int(p.split()[1])*1024 for p in Path('/proc/meminfo').read_text().splitlines() if ' kB' in p}
    cap = mem['MemAvailable']
    for row in Path('/proc/self/cgroup').read_text().splitlines():
        if not row.startswith('0::'):
            continue
        group = Path('/sys/fs/cgroup') / row[3:].lstrip('/')
        for d in (group, *group.parents):
            if not d.is_relative_to('/sys/fs/cgroup'):
                break
            try:
                limit = (d/'memory.max').read_text().strip()
                if limit != 'max':
                    cap = min(cap, int(limit)-int((d/'memory.current').read_text()))
            except OSError:
                pass
    return max(0, cap)


def data_for(d, timed, rc, reason):
    doc = []
    try:
        doc = json.loads((d/'result.json').read_bytes())
    except (OSError, ValueError):
        pass
    props = [[p['property'], p['status']] for m in doc for p in m.get('result', [])]
    notes = [m.get('messageText','') for m in doc if m.get('messageType') in ('ERROR','WARNING')]
    stderr = (d/'stderr').read_bytes()[-4000:].decode(errors='replace')
    # Some native failures precede the final JSON document.
    with (d/'stdout').open('rb') as f:
        f.seek(max(0, (d/'stdout').stat().st_size-8192))
        stdout_tail=f.read().decode(errors='replace')
    messages = '\n'.join(notes + [stderr,stdout_tail])
    target = [(p,s) for p,s in props if p=='reach_error.assertion.1']
    unwinds = [(p,s) for p,s in props if 'unwind' in p]
    if timed:
        kind = 'TIMEOUT'
    elif reason:
        kind = reason
    elif 'pointer handling for concurrency is unsound' in messages:
        kind = 'UNSUPPORTED_POINTER'
    elif any('pthread_' in m and ('no body' in m.lower() or 'unsupported' in m.lower()) for m in notes):
        kind = 'UNSUPPORTED_PRIMITIVE'
    elif 'out of memory' in messages.lower() or 'bad_alloc' in messages:
        kind = 'MEMORY_LIMIT_OR_ALLOCATION_FAILURE'
    elif rc not in (0,10) or not props:
        kind = 'TOOL_FAILURE'
    elif not target:
        kind = 'TARGET_ABSENT'
    elif any(s != 'SUCCESS' for p,s in unwinds):
        kind = 'INCOMPLETE_UNWINDING'
    elif len(target)!=1 or target[0][1] not in ('FAILURE','SUCCESS'):
        kind = 'UNKNOWN'
    elif any(s!='SUCCESS' for p,s in props if p!=target[0][0]):
        kind = 'OTHER_PROPERTY_FAILURE'
    elif (rc,target[0][1]) not in ((10,'FAILURE'),(0,'SUCCESS')):
        kind = 'INCONSISTENT_EXIT'
    else:
        kind = 'SAT' if rc==10 else 'UNSAT'
    metrics = {}
    if (d/'s8-native.tsv').is_file():
        for line in (d/'s8-native.tsv').read_text().splitlines():
            k,*v = line.split('\t')
            if k in ('front','sc','ssa_convert','encode_graph','graph_load','search') and len(v)==3:
                metrics[k] = dict(calls=int(v[0]), wall_s=int(v[1])/1e9, cpu_s=int(v[2])/1e9)
    states=[]
    if (d/'native-state.tsv').is_file():
        for line in (d/'native-state.tsv').read_text().splitlines():
            fields=line.split()
            if len(fields)==len(STATE):
                states.append(dict(zip(STATE,map(int,fields))))
    counters = None
    native_last=None
    if (d/'s8-search.tsv').exists():
        raw=(d/'s8-search.tsv').read_text().split()
        if len(raw)==6:
            native_last=dict(zip(('starts','conflicts','decisions','propagations','theory_propagations','theory_conflicts'),map(int,raw)))
    if states and len(states)%2==0:
        counters={k:sum(states[i+1][k]-states[i][k] for i in range(0,len(states),2)) for k in
                  ('decisions','conflicts','propagations','theory_propagations','theory_conflicts')}
        counters.update(variables=states[0]['variables'],native_original_live=states[0]['original_live'],
                        learnt_live_end=states[-1]['learnt_live'], graph_nodes=states[-1]['graph_nodes'], queries=len(states)//2)
    return dict(result=kind, properties=props, warnings=notes, stderr_tail=stderr, phases=metrics, counters=counters,
                last_solve_cumulative=native_last)


def single(job, root, binary, cpu, host):
    rel=Path(job['out'])
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('invalid job directory')
    dest=root/rel
    dest.mkdir(parents=True,exist_ok=True)
    spec={**job,'binary':BINARY,'host':host}
    identity=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
    with (dest/'job.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        receipt=dest/'receipt.json'
        if receipt.exists():
            old=json.loads(receipt.read_bytes())
            if old['identity']!=identity:
                raise ValueError('changed configuration for existing job: '+str(rel))
            for k,v in old['raw_sha256'].items():
                if sha(dest/old['attempt']/k)!=v:
                    raise ValueError('damaged completed job: '+str(rel))
            return old['result']
        attempt=dest/('try-'+str(time.time_ns()))
        attempt.mkdir()
        for name,src in job['files'].items():
            if Path(name).name!=name:
                raise ValueError(name)
            p=(root/src['path']).resolve(strict=True)
            if not p.is_relative_to((root/'inputs').resolve(strict=True)):
                raise ValueError('source outside the staged inputs')
            if sha(p)!=src['sha256']:
                raise ValueError('input digest mismatch')
            (attempt/name).write_bytes(p.read_bytes())
        env=dict(PATH='/usr/bin:/bin',LC_ALL='C',TMPDIR=str(attempt),S8_OUT=str(attempt),
                 INCDEAGLE_JSON_OUTPUT=str(attempt/'result.json'))
        if job['capture']:
            env['S8_STREAM']='1'
            env['S10_DIR']=str(attempt)
            env['INCDEAGLE_OBSERVE_DIR']=str(attempt)
        limit=int(job['memory_gib']*GIB)
        # prlimit and taskset exec the actual verifier without a multithreaded Python preexec callback.
        argv=['/usr/bin/taskset','-c',str(cpu),'/usr/bin/prlimit','--as='+str(limit),'--',str(binary),*job['argv']]
        t=time.monotonic()
        timed=False
        with (attempt/'stdout').open('wb') as out,(attempt/'stderr').open('wb') as err:
            proc=subprocess.Popen(argv,cwd=attempt,env=env,stdout=out,stderr=err,start_new_session=True)
            try:
                while True:
                    pid,status,usage=os.wait4(proc.pid,os.WNOHANG)
                    if pid:
                        break
                    if time.monotonic()-t>=job['timeout_s']:
                        timed=True
                        os.killpg(proc.pid,signal.SIGKILL)
                        _,status,usage=os.wait4(proc.pid,0)
                        break
                    time.sleep(.08)
            finally:
                if 'status' not in locals() or (not timed and not pid):
                    try:os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
            proc.returncode=os.waitstatus_to_exitcode(status)
        elapsed=time.monotonic()-t
        details=data_for(attempt,timed,proc.returncode,None)
        hashes={f.name:sha(f) for f in sorted(attempt.iterdir()) if f.is_file()}
        write(receipt,dict(**spec,identity=identity,attempt=attempt.name,core=cpu,
              exit=proc.returncode,wall_s=elapsed,user_s=usage.ru_utime,sys_s=usage.ru_stime,
              peak_rss_kib=usage.ru_maxrss,raw_sha256=hashes,**details))
        return details['result']


def queue(root,binary,plan,host,maximum):
    root=root.resolve();binary=binary.resolve()
    if sha(binary)!=BINARY:
        raise ValueError('wrong verifier')
    jobs=json.loads(plan.read_bytes())
    cores=sorted(os.sched_getaffinity(0))[:min(8,maximum)]
    if not cores or len(set(j['out'] for j in jobs))!=len(jobs):
        raise ValueError('invalid queue')
    before=time.time()
    already_complete=sum((root/j['out']/'receipt.json').is_file() for j in jobs)
    pending=list(jobs);active={};unused=set(cores);peak=0;results=Counter();log=[]
    initial=available()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(cores)) as pool:
        while pending or active:
            # Reserve each job's entire address-space ceiling and leave memory for OS + controller.
            while pending and unused:
                current=available()
                remaining=min(initial-sum(v[1] for v in active.values()),current)-int(1.5*GIB)
                index=next((i for i,j in enumerate(pending) if j['memory_gib']*GIB<=remaining),None)
                if index is None:
                    if not active:raise RuntimeError('available memory below individual job reservation')
                    break
                j=pending.pop(index);core=min(unused);unused.remove(core)
                f=pool.submit(single,j,root,binary,core,host);active[f]=(core,int(j['memory_gib']*GIB),j['out'])
                peak=max(peak,len(active))
                log.append([round(time.time()-before,3),'dispatch',j['out'],core,len(active),current])
            if active:
                done,_=concurrent.futures.wait(active,timeout=1,return_when=concurrent.futures.FIRST_COMPLETED)
                for f in done:
                    core,cap,name=active.pop(f);unused.add(core);k=f.result();results[k]+=1
                    log.append([round(time.time()-before,3),k,name,core,len(active),available()])
                    print(name,k,flush=True)
    summary=root/(plan.stem+'-queue.json')
    if summary.exists():
        summary=root/(plan.stem+'-resume-'+str(time.time_ns())+'.json')
    write(summary,dict(host=host,start_epoch=before,elapsed_s=time.time()-before,validated_existing=already_complete,
          max_workers=len(cores),peak_concurrent=peak,initial_available_bytes=initial,results=results,events=log))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('root','binary','plan'): p.add_argument(name,type=Path)
    p.add_argument('--host',required=True);p.add_argument('--workers',type=int,default=8)
    args=p.parse_args()
    queue(args.root,args.binary,args.plan,args.host,args.workers)
