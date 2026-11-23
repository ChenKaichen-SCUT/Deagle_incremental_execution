"""Serial, balanced same-binary ablations over the frozen Stage 7 program pairs."""
import argparse
import errno
import fcntl
import gzip
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.model.identity import file_sha,read,save
from incdeagle.model.repeat import phase_digest
from incdeagle.repair import apply_source_patch
from scripts.stage7.experiment import sample
from scripts.stage7.inputs import validate
from scripts.stage7.oracles import retained_projection

MODES=('F0','F1','F2','I1','I2','I3')
PRIORITY=('batch_total','threshold_guard','fib_updates_8','split_counter','airline_reservations_6')
OTHER=('partial_counter','batch_retained','fib_updates','airline_reservations')
PHASES=('goto','raw_ssa','sc_input','full_model')


def one(archive,lock,out,name,mode,repeat,detail,extra=None):
    parent=out/name/f'{repeat:02}'/('on' if detail else 'off')/mode
    if (parent/'complete.json').exists():
        return
    folder=parent
    while (folder/'settings.json').exists():
        folder=parent/('retry-'+str(time.monotonic_ns()))
    folder.mkdir(parents=True,exist_ok=True)
    unit='deagle8-'+uuid.uuid4().hex
    mat=read(ROOT/'reports/evidence/stage-07/matrix.json')
    item=mat[name]
    case=validate(archive,item)
    ref=read(ROOT/'reports/evidence/stage-07/summary.json')
    base=ref['cases'][name]
    bound=read(case/'gamma.json')['limits']
    stats=archive/'trials'/name/'1/incremental/pair/candidate/native-stats.json'
    regions=read(stats).get('sc_regions',[]) if stats.exists() else []
    known={k:'|'+'|'.join(v['name'] for v in regions if v['family']==k and v['reused'])+'|' for k in ('rf','po')}
    settings={'case':name,'mode':mode,'repeat':repeat,'detail':detail,'lock':str(lock),'prefix':base['reused_prefix_steps'],
        **known,'files':item['files'],'affinity':sorted(os.sched_getaffinity(0)),'reference_cex0':file_sha(archive/'fixed-traces'/(name+'.json')),
        'limits':bound,**(extra or {})}
    save(folder/'settings.json',settings)
    start=time.monotonic_ns()
    computed=apply_source_patch((case/'old/program.c').read_bytes(),(case/'patch.diff').read_bytes())
    assert computed==(case/'candidate/program.c').read_bytes()
    repair=time.monotonic_ns()-start
    command=['systemd-run','--quiet','--collect','--wait','--pipe','--unit',unit,'-p','MemoryMax='+str(bound['memory_bytes']),
             '-p','WorkingDirectory='+str(ROOT),'--setenv=LC_ALL=C','--','/usr/bin/timeout','--kill-after=5',
             str(bound['timeout_seconds']*2+30),sys.executable,'-B',str(ROOT/'scripts/stage8/worker.py'),str(case),str(folder)]
    group=None
    points=[]
    begin=time.monotonic_ns()
    with (folder/'service.stdout').open('wb') as so,(folder/'service.stderr').open('wb') as se:
        proc=subprocess.Popen(command,stdout=so,stderr=se,stdin=subprocess.DEVNULL)
        while proc.poll() is None:
            if group is None and (folder/'group.json').is_file():
                try:group=Path(read(folder/'group.json')['path'])
                except ValueError:pass
                if group is not None and group.name!=unit+'.service':raise RuntimeError('Unexpected cgroup')
            if group is not None:
                try:
                    p=sample(group)
                except OSError as exc:
                    if exc.errno not in (errno.ENODEV,errno.ENOENT,errno.ESRCH):
                        raise
                    # systemd can remove a finished cgroup between two reads.
                    p=None
                if p:points.append(p)
            time.sleep(.005)
    stop=time.monotonic_ns()
    with gzip.open(folder/'samples.json.gz','wt',encoding='utf8') as f:json.dump(points,f,separators=(',',':'))
    save(folder/'service.json',{'argv':command,'unit':unit,'launch':begin,'finish':stop,'rc':proc.returncode,'repair_ns':repair,
        'sample_columns':['monotonic_ns','rss_sum_kib','cgroup_current_kib','process_count']})
    if proc.returncode!=0:raise RuntimeError(str(folder)+': '+(folder/'service.stderr').read_text()[-1500:])
    m=read(folder/'measurement.json')
    dest=folder/('full' if mode in ('F0','F1') else 'pair/candidate')
    old=folder/('old_full' if mode in ('F0','F1') else 'pair/old')
    assert m['verdict']==read(archive/'trials'/name/'1/full/verify/verdict.json'),(mode,name,m['verdict'])
    assert m['old_verdict']==read(archive/'trials'/name/'1/old_full/verify/verdict.json')
    digests={}
    if (dest/'full_model.json').is_file():
        for phase in PHASES:
            digests[phase]=phase_digest(read(dest/(phase+'.json')))
        if digests!=ref['diagnostics'][name]['phases']:raise ValueError('Model mismatch '+str(dest))
    if mode not in ('F0','F1'):
        assert digests
        if mode=='F2':assert not m['native']['checkpoint_used'] and m['path']=='full_fallback'
        if mode=='I1':assert m['native'].get('sc_counters',{}).get('read_bundles_reused',0)==0 and m['native'].get('sc_counters',{}).get('thread_edges_reused',0)==0
        assert m['theory']['imported']==(base['lemmas_imported'] if mode=='I3' else 0)
        assert m['native']['reused_prefix_symex_steps']==(0 if mode=='F2' else base['reused_prefix_steps'])
    trace=dest/'cex1.json'
    if name in ('partial_counter','batch_retained'):assert retained_projection(name,read(trace))
    record={'verdict':m['verdict']['classification'],'candidate_sha256':file_sha(dest/'program.c'),
           'old_sha256':file_sha(old/'program.c'),'phase_digests':digests,'attempt':folder.relative_to(parent).as_posix(),
           'result_sha256':file_sha(dest/'result.json'),'old_result_sha256':file_sha(old/'result.json')}
    assert record['candidate_sha256']==item['files']['candidate/program.c'] and record['old_sha256']==item['files']['old/program.c']
    save(parent/'complete.json',record)
    print(name,repeat,mode,'detail' if detail else 'normal',record['verdict'],round((stop-begin)/1e9,3),flush=True)


def run(args):
    archive=args.source.resolve()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    assert read(archive/'matrix.json')==read(ROOT/'reports/evidence/stage-07/matrix.json')
    cases=list(args.cases or (*PRIORITY,*OTHER))
    modes=list(args.modes or MODES)
    schedule=[]
    for group in (list(filter(lambda c:c in PRIORITY,cases)),list(filter(lambda c:c in OTHER,cases))):
        for i in range(args.repeats):
            rotated=group[i%len(group):]+group[:i%len(group)] if group else []
            for j,c in enumerate(rotated):
                k=(i+cases.index(c))%len(modes)
                order=modes[k:]+modes[:k]
                if i%2:order=order[::-1]
                for m in order:
                    for detail in ([(i+j+modes.index(m))%2==0,(i+j+modes.index(m))%2!=0] if args.level=='both' else [args.level=='on']):
                        schedule.append([c,m,i+1,detail])
    plan={'schedule':schedule,'modes':modes,'cases':cases,'repeats':args.repeats,'level':args.level,
          'frozen_project':'247894bf77904bb34e547b5a636b8afe8527add4','warm_os_cache':True,'concurrent_verifications':1}
    if (out/'plan.json').is_file():assert plan==read(out/'plan.json')
    save(out/'plan.json',plan)
    for name,mode,r,detail in schedule:one(archive,args.lock.resolve(),out,name,mode,r,detail)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('source','lock','out'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--cases',nargs='+',choices=(*PRIORITY,*OTHER));p.add_argument('--modes',nargs='+',choices=MODES)
    p.add_argument('--repeats',type=int,default=5);p.add_argument('--level',choices=('off','on','both'),default='both')
    a=p.parse_args()
    with (a.lock.resolve().parent/'measurement.lock').open('a') as exclusive:
        fcntl.flock(exclusive,fcntl.LOCK_EX|fcntl.LOCK_NB)
        run(a)
