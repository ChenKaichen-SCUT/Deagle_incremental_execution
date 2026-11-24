"""Materialise explicit, checked public translation units and the initial screening plans."""
import csv
import hashlib
import json
import tarfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / 'runs/hard-pairs-admin/work'
SV = REPO / 'runs/svcomp26/discovery/bench/c'
FM = REPO / 'runs/stage-11b/artifact/files/workspace/benchmarks'
TAG = '7efe28dd29576b46927b7a34e8f742bd90966a75'
E = REPO / 'reports/evidence/stage-12'
DS = REPO / 'datasets/stage-12-hard-pairs'
PROPERTY = '0c6a90cfc3ad4545225a0537ddc37b8a11ea5a37b906c053bb298b748f810150'


def h(b):
    return hashlib.sha256(b).hexdigest()


def dump(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes((json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)+'\n').encode())


def job(c, phase, sec, mem, bound=None, capture=False):
    b = bound or c['bound']
    name = 'program' + Path(c['original']).suffix
    opts = ['--function','main','--deagle-closure','--mm','sc','--'+{'ILP32':'32','LP64':'64'}[c['model']],
            '--unwind',str(b),'--unwinding-assertions','--trace','--json-ui',name]
    return dict(out=phase+'/'+c['id']+'-b'+str(b), sample=c['id'], bound=b, phase=phase,
                timeout_s=sec,memory_gib=mem,capture=capture,argv=opts,
                files={name:dict(path=c['file'],sha256=c['sha256'])})


def pack(plans):
    admin=ROOT.parent
    with tarfile.open(admin/'input.tar.gz','w:gz') as tar:
        for f in sorted((ROOT/'inputs').rglob('*')):
            if f.is_file(): tar.add(f,arcname=f.relative_to(ROOT))
        for f in (Path(__file__).parent/n for n in ('run.py','dispatch.sh','status.py','export.py')):
            tar.add(f,arcname=f.name)
        for f in [ROOT/'order.txt',*(ROOT/(p+'.json') for p,_ in plans)]:
            tar.add(f,arcname=f.name)


def schedule(plans):
    (ROOT/'order.txt').write_bytes(''.join(f'{p} {n}\n' for p,n in plans).encode())
    pack(plans)


def prepare():
    ROOT.mkdir(parents=True,exist_ok=True)
    rows={r['task']:r for r in csv.DictReader((REPO/'reports/evidence/svcomp26/all-records.csv').open()) if r['category']=='C.unreach-call.Concurrency'}
    cases={}
    def add(key,task,bound,fm=False,override=None):
        base=FM if fm else SV
        y=base/(task+'.yml');spec=yaml.safe_load(y.read_bytes())
        target=next(p for p in spec['properties'] if p['property_file'].endswith('/unreach-call.prp'))
        prop=(y.parent/target['property_file']).resolve()
        if fm and not prop.exists():
            prop=REPO/'cases/svcomp26/c/properties/unreach-call.prp'
        assert h(prop.read_bytes())==PROPERTY
        original=y.parent/spec['input_files']
        local=override or original
        data=local.read_bytes()
        out=ROOT/'inputs'/key
        out.mkdir(parents=True,exist_ok=True)
        (out/local.suffix.lstrip('.')).write_bytes(data)
        (out/'task.yml').write_bytes(y.read_bytes())
        row=rows.get(task+'.yml') if not fm else None
        if row:
            assert row['yaml_sha256']==h(y.read_bytes()) and row['input_sha256']==h(original.read_bytes()),task
        cases[key]=dict(id=key,task=task+'.yml',source='FM26' if fm else 'SVCOMP26',original=original.name,
                        model=spec['options']['data_model'],expected_original=target['expected_verdict'],bound=bound,
                        sha256=h(data),yaml_sha256=h(y.read_bytes()),public_sha256=h(original.read_bytes()),
                        property_sha256=PROPERTY,official=row,file=(out/local.suffix.lstrip('.')).relative_to(ROOT).as_posix(),
                        override=override.relative_to(REPO).as_posix() if override else None)
    add('buffer','pthread-deagle/circular_buffer_bad',8)
    for family,task,b in [('pthread-atomic','read_write_lock-2',4),('pthread-theta','unwind1-1',4),('pthread-deagle','arithmetic_prog_bad',5)]:
        key={'read_write_lock-2':'rw','unwind1-1':'unwind','arithmetic_prog_bad':'arithmetic'}[task]
        add(key+'0',family+'/'+task,b)
        for v in (['P1','P2'] if key=='rw' else ['P1']):
            add(key+v[1],family+'/'+task,b,override=REPO/'cases/svcomp26/versions'/task/v/'program.i')
    for name,other in [('25_stack_longer-1','25_stack_longer-2'),('25_stack_longest-2','25_stack_longest-1'),('26_stack_cas_longer-1','26_stack_cas_longer-2')]:
        for x in (name,other):add(x,'pthread-ext/'+x,3)
    for prefix,a,b in [('counter-queue','bad-counter-queue','bad-counter-queue2'),('array-sum','more-array-sum','more-array-sum2'),
                        ('array-sum-alt','more-array-sum-alt','more-array-sum-alt2'),('buffer-mult','more-buffer-mult3','more-buffer-mult2'),
                        ('buffer-series','more-buffer-series3','more-buffer-series2'),('buffer-mult-alt','bad-buffer-mult-alt3','bad-buffer-mult-alt2')]:
        for num,x in enumerate((a,b)):add(prefix+str(num),'weaver/popl20-'+x+'.wvr',3)
    for n in (5,6,7):add('ticket'+str(n),'weaver/parallel-ticket-'+str(n)+'.wvr',2,True)
    for n in ('queue_longer','queue_longest','queue_ok_longer','queue_ok_longest','stack_longest-1'):add('fm-'+n,'pthread/'+n,2,True)
    for key,x in [('netbsd','43_NetBSD_sysmon_power_sliced'),('netbsd-pthread','43_NetBSD_sysmon_power_sliced-pthread')]:
        add(key,'pthread-ext/'+x,2,True)
    for n in (10,11):
        add('fib-safe'+str(n),'pthread/fib_safe-'+str(n),2*n+3)
    extra=[('reorder2','pthread/reorder_2',3),('reorder5','pthread/reorder_5',6),
           ('twostage','pthread/twostage_3',4),('ldv-join','ldv-races/race-1_2-join',4),
           ('stack2','pthread/stack-2',7),('stack1','pthread/stack-1',7),('steal','pthread-complex/workstealqueue_mutex-2',8)]
    for key,path,bound in extra:
        add(key,path,bound)
    dump(E/'inventory.json',cases)
    dump(ROOT/'quick.json',[job(c,'quick',22,3) for c in cases.values() if c['id'] not in {r[0] for r in extra}])
    extend=['ticket7','netbsd','netbsd-pthread','fib-safe10','fib-safe11',
            '25_stack_longest-2','26_stack_cas_longer-1','buffer']
    dump(ROOT/'extended.json',[job(cases[k],'extended',180,4) for k in extend]+
         [job(cases[k],'extended',160,4,8) for k in ('arithmetic0','arithmetic1')])
    schedule([('quick',8),('extended',8)])


if __name__=='__main__':
    prepare()
