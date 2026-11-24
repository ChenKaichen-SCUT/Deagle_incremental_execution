"""Prepare staged escalation, trace-derived patches, and isolated confirmation plans."""
import argparse
from itertools import combinations
import json
from pathlib import Path
from prepare import E, ROOT, REPO, dump, h, job, schedule

EXTRA='reorder2 reorder5 twostage ldv-join stack2 stack1 steal'.split()


def cited(case):
    dirs=sorted((ROOT.parent/'returned').glob('*/'+case+'-b*/receipt.json'))
    for p in dirs:
        a=json.loads(p.read_bytes())
        f=p.parent/a['attempt']/'result.json'
        if not f.is_file():continue
        trace=next((v.get('trace',[]) for m in json.loads(f.read_bytes()) for v in m.get('result',[])
                    if v['property']=='reach_error.assertion.1' and v['status']=='FAILURE'),[])
        if trace:
            return dict(receipt=a['identity'],result_sha256=h(f.read_bytes()),trace_steps=len(trace),
                        failure=trace[-1].get('sourceLocation'),job=a['out'])
    raise ValueError('no native target witness for '+case)


def patch(cases,key,changes):
    c=cases[key];proof=cited(key)
    old=(ROOT/c['file']).read_bytes();s=old
    for before,after,n in changes:
        assert s.count(before)==n,(key,before,s.count(before))
        s=s.replace(before,after)
    out=ROOT/'inputs'/(key+'-fix')/Path(c['file']).name
    out.parent.mkdir(exist_ok=True);out.write_bytes(s)
    (out.parent/'task.yml').write_bytes((ROOT/c['file']).with_name('task.yml').read_bytes())
    cases[key+'-fix']={**c,'id':key+'-fix','sha256':h(s),'file':out.relative_to(ROOT).as_posix(),
                        'override':'manual-from-native-witness','witness':proof}


def buffer_model():
    counts=[0,0];payloads=set();orig_bad=None
    for sender_slots in combinations(range(14),7):
        for fixed in (0,1):
            sent=0;received=0;fifo=[];poll=[0,0];bad=False
            for step in range(14):
                side=int(step not in sender_slots)
                if side==0 and sent==received:
                    fifo.append(sent if fixed else poll[0]);sent+=1
                elif side==1 and sent>received:
                    v=fifo.pop(0);expected=received if fixed else poll[1];received+=1
                    if v!=expected:bad=True
                poll[side]+=1
            assert sent-received==len(fifo)<=1 and sent<=7 and received<=7
            counts[fixed]+=bad
            if fixed:payloads.add(received)
            if not fixed and bad and orig_bad is None:orig_bad=sender_slots
    assert counts[0]>0 and counts[1]==0 and max(payloads)==7
    dump(E/'buffer-functional.json',dict(schedules=3432,original_bad_schedules=counts[0],fixed_bad_schedules=counts[1],
         complete_dequeue_counts=sorted(payloads),first_bad_sender_slots=orig_bad,
         basis='Every critical section takes the same mutex, so each source execution projects onto an order of seven producer and seven consumer polls. Successful transactions alternate. At most seven writes, before index wrap at 10. Each payload is the ordinal of its successful send and must equal the ordinal of its successful receive.'))


def main(which):
    cases=json.loads((E/'inventory.json').read_bytes())
    if which=='next':
        patch(cases,'buffer',[(b'int i;\n  for(i=0; i<7; i++)',b'int i = 0;\n  int attempt;\n  for(attempt=0; attempt<7; attempt++)',2),
            (b'insertLogElement(i);',b'insertLogElement(i);\n      i++;',1),(b'      receive=0;',b'      i++;\n      receive=0;',1)])
        buffer_model()
        dump(ROOT/'candidates.json',[job(cases[k],'candidates',60,4) for k in EXTRA+['buffer-fix']])
        dump(ROOT/'deep.json',[job(cases[k],'deep',660,7) for k in ('ticket7','netbsd')]+
             [job(cases[k],'deep',180,9) for k in ('25_stack_longest-2','26_stack_cas_longer-1')])
        schedule([('candidates',8),('deep',8)])
    elif which=='repairs':
        for key in ('ldv-join','reorder2','reorder5','twostage'):
            try:cited(key)
            except ValueError:continue
            if key=='ldv-join':
                patch(cases,key,[(b'      pdev = 2;\n      __VERIFIER_atomic_end();\n      __VERIFIER_atomic_begin();',
                                  b'      pdev = 2;',1)])
            elif key.startswith('reorder'):
                patch(cases,key,[(b'a = 1;\n    __VERIFIER_atomic_end();\n    __VERIFIER_atomic_begin();',b'a = 1;',1),
                                 (b'int la = a;\n    __VERIFIER_atomic_end();\n    __VERIFIER_atomic_begin();',b'int la = a;',1)])
            else:
                # Hold data1Lock throughout publication and through each reader snapshot. Both paths use data1 then data2.
                patch(cases,key,[(b'data1Value = 1;\n    pthread_mutex_unlock(data1Lock);\n    pthread_mutex_lock(data1Lock);',b'data1Value = 1;',1),
                  (b' = data1Value;\n    pthread_mutex_unlock(data1Lock);\n    pthread_mutex_lock(data2Lock);',b' = data1Value;\n    pthread_mutex_lock(data2Lock);',2),
                  (b'    pthread_mutex_unlock(data2Lock);',b'    pthread_mutex_unlock(data2Lock);\n    pthread_mutex_unlock(data1Lock);',2)])
        fixes=[k for k in cases if k.endswith('-fix') and k!='buffer-fix']
        dump(ROOT/'fixes.json',[job(cases[k],'fixes',180,4) for k in fixes])
        schedule([('fixes',8)])
    dump(E/'inventory.json',cases)


if __name__=='__main__':
    import sys
    main(sys.argv[1])
