"""Run a fresh full Deagle model for every side including the independent stock control."""
import argparse,collections,hashlib,json,os,resource,shutil,socket,subprocess,sys,time
from pathlib import Path
from bindings import ROOT,bind,read,file_sha,signed_map,write_plan
from scripts.stage10.experiment import ready_line,stop,signed_stats,PHASES
from incdeagle.model.repeat import phase_digest
from incdeagle.model.identity import save

CLOCK=time.monotonic_ns
EXE_SHA='b84a95d9d02e9fc48217373bf71564db1cb8ce4029644936a893aaaaef0a529e'
def check_root(d,names):
    """Independent complete BFS of the APO quotient. Compare every pair including omissions."""
    graph=read(d/'native-bindings.json'); adj={k:set() for k in names}
    for e in graph['edges']:
        if e['kind']=='apo':adj[e['from']].add(e['to']);adj[e['to']].add(e['from'])
    groups={};apodir=collections.defaultdict(list)
    for node in adj:
        if node in groups:continue
        stack=[node];members=set()
        while stack:
            n=stack.pop()
            if n in members:continue
            members.add(n);stack.extend(adj[n]-members)
        sig=tuple(sorted(names[m] for m in members))
        groups.update((m,sig) for m in members)
    for e in graph['edges']:
        if e['kind']=='apo':apodir[groups[e['from']]].append(names[e['from']]+'>'+names[e['to']])
    block={k:'members:'+':'.join(m)+'|directed'+''.join(':'+s for s in sorted(apodir[m])) for k,m in groups.items()}
    direct={(block[e['from']],block[e['to']]) for e in graph['edges'] if e['kind']=='po' and block[e['from']]!=block[e['to']]}
    succ=collections.defaultdict(set)
    for a,b in direct:succ[a].add(b)
    expected=set()
    for a in set(block.values()):
        work=list(succ[a]);seen=set()
        while work:
            b=work.pop()
            if b in seen:continue
            seen.add(b);work.extend(succ[b]-seen)
        expected.update((a,b) for b in seen)
    rows=[q.split('\t') for q in (d/'worker/closure.tsv').read_text().splitlines()]
    if expected!={(a,b) for a,b,_,_ in rows} or direct!={(a,b) for a,b,base,_ in rows if base=='1'}:
        raise ValueError('root closure disagrees with independent quotient search')
    return dict(facts=len(expected),bases=len(direct),digest=hashlib.sha256(json.dumps(sorted(expected)).encode()).hexdigest())

def pair_case(name,sources,fixtures):
    if name in ('ticket56','ticket56-reviewed'):
        v=ROOT/'reports/evidence/stage-11b/versions'
        return [{'program.c':v/('ticket-'+side+'.c')} for side in ('old','new')],['--function','main','--deagle-closure','--mm','sc','--32','--unwind','2','--unwinding-assertions','--property','reach_error.assertion.1','--trace','--json-ui','program.c']
    if name.startswith('lock'):
        v=fixtures/'cases/svcomp26/versions/read_write_lock-2'
        original=fixtures/'cases/svcomp26/c/pthread-atomic/read_write_lock-2.i'
        a,b=(v/'P1/program.i',v/'P2/program.i') if name=='lock12' else (original,v/'P1/program.i')
        return [{'program.i':p} for p in (a,b)],['--function','main','--deagle-closure','--mm','sc','--32','--unwind','4','--unwinding-assertions','--property','reach_error.assertion.1','--trace','--json-ui','program.i']
    case=sources/name
    if not (case/'gamma.json').exists():case=case/('batch_total' if name=='batch_retained' else name)
    gam=read(case/'gamma.json')
    return [dict({'harness.c':case/'harness.c','program.c':case/ver/'program.c'}) for ver in ('old','candidate')],gam['source_argv']+gam['verification_output']+['harness.c']

def measured(d,inputs,argv,exe,worker,phase,old,review,cwd):
    d.mkdir(parents=True);(d/'worker').mkdir()
    cwd.mkdir(exist_ok=True,parents=True)
    for dest,src in inputs.items():
        shutil.copyfile(src,d/dest);shutil.copyfile(src,cwd/dest)
    env=dict(PATH=os.environ['PATH'],LC_ALL='C',INCDEAGLE_OBSERVE_DIR=str(d),INCDEAGLE_JSON_OUTPUT=str(d/'result.json'),S8_OUT=str(d),S8_STREAM='1',S10_DIR=str(d))
    a,b=socket.socketpair()
    if worker:env['S10_BRIDGE_FD']=str(b.fileno())
    settings={'argv':argv,'backend':'Minisat::ClosureSolver/fixed/native-restricted','binary':EXE_SHA}
    source={n:file_sha(d/n) for n in inputs};main=source.get('program.i',source.get('program.c'))
    before=CLOCK();deadline=time.monotonic()+200
    audit={};reg=None;names=None;diff={};fd=(b.fileno(),) if worker else ()
    with (d/'stdout').open('wb') as so,(d/'stderr').open('wb') as se:
        child=subprocess.Popen([str(exe),*argv],cwd=cwd,env=env,pass_fds=fd,stdout=so,stderr=se,start_new_session=True);b.close()
        try:
            if worker:
                a.settimeout(max(.01,deadline-time.monotonic()))
                if a.recv(1)!=b'R':raise ValueError('no first solve')
                ready=CLOCK()
                try:
                    names,groups,decl=bind(d,settings,main,review,cwd)
                    if cwd.name=='ticket56-reviewed':
                        from bindings import capture_identity
                        records=read(ROOT/'reports/evidence/stage-11b/versions/ticket-review.json')['versions']
                        cert=records[main]
                        if cert['argv']!=argv or any(capture_identity(k,(d/k).read_bytes(),cwd)!=h for k,h in cert['hashes'].items()):
                            raise ValueError('ticket static site certificate mismatch')
                        if not set(cert['roles'])<=set(names):raise ValueError('missing reviewed worker event')
                        names.update(cert['roles'])
                        if len(set(names.values()))!=len(names):raise ValueError('duplicate reviewed worker site')
                        # Literal groups stay under the ordinary full signed-alias policy.
                        decl.update(('reviewed_static_event',u) for u in cert['roles'].values())
                    reg=(groups,decl)
                    mapping=signed_map(old[0],groups) if old is not None else {v:2*v for v,sign in groups.values()}
                    reason='old' if not phase else ('keep' if old is not None and mapping else 'refuse_no_stable_aliases')
                    if old is not None:
                        diff={'added':sorted(decl-old[1]),'deleted':sorted(old[1]-decl)}
                except (ValueError,KeyError,IndexError,RecursionError,OSError) as ex:
                    reg=None;names=None;mapping={};reason='refuse_registry';audit['refusal']=str(ex)
                write_plan(d,names,mapping,reason)
                audit.update(events=len(names or {}),admission=reason,stable=len(mapping),renumbered=sum(x!=q//2 for x,q in mapping.items()),flipped=sum(q%2 for q in mapping.values()))
                bound=CLOCK()
                worker.stdin.write((str(d)+'\n').encode());worker.stdin.flush()
                if ready_line(worker,deadline)!='STAGE10_DONE '+str(phase):raise ValueError('solver phase')
                a.sendall(b'D');a.settimeout(max(.01,deadline-time.monotonic()))
                if a.recv(1):raise ValueError('additional solver request: full-run only')
            rc=child.wait(timeout=max(.01,deadline-time.monotonic()))
        finally:a.close();stop(child)
    elapsed=CLOCK()-before
    output=read(d/'result.json')
    props=[(p['property'],p['status'],len(p.get('trace',[]))) for row in output for p in row.get('result',[])]
    assert rc in (0,10) and props and (rc==10)==any(s=='FAILURE' for _,s,_ in props)
    sub=d/'worker' if worker else d
    def meter(p):return {x[0]:list(map(int,x[1:])) for x in (l.split() for l in p.read_text().splitlines())}
    front=meter(d/'s8-native.tsv');search=meter(sub/'s8-native.tsv')['search']
    assert front['other_dispatch'][0]==len(read(d/'visits.json')) and front['sc'][0]>0
    assert all(front[k][0]==0 for k in ('rf_replay','rebind','prefix_dispatch','prefix_symbols','irep_read'))
    obs=signed_stats(sub/'stats.tsv') if worker else {}
    closure=signed_stats(sub/'closure-stats.tsv') if worker else {}
    check=check_root(d,names) if names is not None and (sub/'closure.tsv').exists() else None
    marks=signed_stats(d/'boundary.tsv') if '\t' in (d/'boundary.tsv').read_text().splitlines()[0] else dict((k,int(v)) for k,v in (x.split() for x in (d/'boundary.tsv').read_text().splitlines()))
    ms=read(d/'metrics.json')['phase_nanoseconds']
    row=dict(phase=phase,source=source,argv=argv,properties=props,exit=rc,front_pid=child.pid,model_reuse=False,
        phases={k:phase_digest(read(d/(k+'.json'))) for k in PHASES},stream=file_sha(d/'s8-input.bin'),graph=file_sha(d/'s8-graph.tsv'),
        counters=obs,closure=closure,root_check=check,binding=audit,model_phases_ns=ms,search_trace=file_sha(sub/'search.bin'),
        timings=dict(program_ns=elapsed,pre_bridge_ns=ready-before if worker else None,bind_delta_ns=bound-ready if worker else None,
        search_ns=search[1],search_cpu_ns=search[2],cnf_graph_ns=ms['cnf_and_graph'],goal_ns=ms['goal_conversion']),
        full_dispatch=front['other_dispatch'][0],sc_calls=front['sc'][0],markers=marks)
    save(d/'diff.json',diff);save(d/'receipt.json',row)
    return reg,row

def run(args,name,trial,mode,versions,argv,review):
    d=args.out/name/str(trial)/mode
    if (d/'pair.json').exists():return
    if d.exists():d.rename(d.with_name(mode+'-failed-'+str(CLOCK())))
    d.mkdir(parents=True);rows=[];worker=None;prev=None
    with (d/'worker.stdout').open('wb') as out,(d/'worker.stderr').open('wb') as err:
        start=CLOCK();usage0=resource.getrusage(resource.RUSAGE_CHILDREN);cpu0=time.process_time_ns()
        try:
            if mode!='stock':
                r,w=os.pipe()
                worker=subprocess.Popen([str(args.worker),mode],stdin=subprocess.PIPE,stdout=out,stderr=err,env={'PATH':os.environ['PATH'],'LC_ALL':'C','S10_PROTOCOL_FD':str(w)},pass_fds=(w,),start_new_session=True)
                os.close(w);worker.stdout=os.fdopen(r,'rb',buffering=0)
            for i,files in enumerate(versions):
                prev,row=measured(d/('old','new')[i],files,argv,args.exe,worker,i,prev,review,args.out.parent/'work'/name);rows.append(row)
            if worker:
                worker.stdin.close();assert worker.wait(timeout=10)==0;worker.stdout.close()
        finally:stop(worker)
    cpu=resource.getrusage(resource.RUSAGE_CHILDREN)
    save(d/'pair.json',dict(case=name,trial=trial,mode=mode,controller_cycle_ns=CLOCK()-start,
         application_pair_ns=sum(r['timings']['program_ns'] for r in rows),children_highwater_kib=cpu.ru_maxrss,
         children_user_s=cpu.ru_utime-usage0.ru_utime,children_system_s=cpu.ru_stime-usage0.ru_stime,
         controller_cpu_ns=time.process_time_ns()-cpu0))
    print(name,trial,mode,[r['exit'] for r in rows],rows[1]['binding'],rows[1]['closure'].get('used_derived'),rows[1]['counters'].get('actually_reattached'),flush=True)

def main():
    parser=argparse.ArgumentParser()
    for arg in ('exe','worker','sources','fixtures','out'):parser.add_argument(arg,type=lambda s:Path(s).resolve())
    parser.add_argument('--cases',nargs='+',default=['lock12','fib_updates_8','lock01','batch_retained'])
    parser.add_argument('--repeats',type=int,default=5)
    args=parser.parse_args()
    assert file_sha(args.exe)==EXE_SHA
    review=read(ROOT/'reports/evidence/stage-11b/versions/lock-review.json')
    for j,name in enumerate(args.cases):
        versions,argv=pair_case(name,args.sources,args.fixtures)
        run(args,name,0,'stock',versions,argv,review)
        for i in range(1,args.repeats+1):
            modes=['F','G','S','GS']
            if i%2==0:modes.reverse()
            shift=(j+(i-1)//2)%4
            for m in modes[shift:]+modes[:shift]:
                try:
                    run(args,name,i,m,versions,argv,review)
                except (OSError,RuntimeError,ValueError,KeyError,IndexError,AssertionError,subprocess.SubprocessError) as exc:
                    from gates import stock_fallback
                    pair_dir=args.out/name/str(i)/m
                    fallback=stock_fallback(args.out/name/'0/stock',versions,argv,exc)
                    save(pair_dir/'fallback.json',fallback)
                    raise RuntimeError(f'{name}/{i}/{m}: candidate stopped; independent stock results recorded') from exc
                check_start=CLOCK()
                for side in ('old','new'):
                    base=args.out/name/'0/stock'/side;d=args.out/name/str(i)/m/side
                    r,o=read(d/'receipt.json'),read(base/'receipt.json')
                    from gates import verify
                    admission=verify(d,base)
                    if admission['native']['path']=='FULL_REBUILD':
                        save(d.parent/'fallback.json',admission)
                        raise RuntimeError(f'{name}/{i}/{m}/{side}: path stopped; current-version stock result recorded')
                pair_path=d.parent/'pair.json';doc=read(pair_path)
                if 'postcheck_ns' not in doc:
                    doc['postcheck_ns']=CLOCK()-check_start
                    doc['controller_with_gate_ns']=doc['controller_cycle_ns']+doc['postcheck_ns']
                    save(pair_path,doc)
if __name__=='__main__':main()
