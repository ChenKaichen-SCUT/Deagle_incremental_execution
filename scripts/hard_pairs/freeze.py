"""Freeze or replay both complete translation units using the original task obligations."""
import argparse
import difflib
import json
import shutil
from pathlib import Path
from prepare import DS,E,PROPERTY,REPO,ROOT,TAG,dump,h,job,schedule

# Final selection is passed explicitly, after independent all-property results.
PAIRS={
 'circular-buffer':('buffer','buffer-fix','trace_repair','轮询失败也推进了载荷编号。修复让七次轮询照常执行，生产和消费各在事务成功后推进序号。'),
 'rw-acquire':('rw0','rw1','residual_repair','冻结的第一轮修补修改读写协议，仍有调度能使原断言失败。'),
 'rw-release':('rw1','rw2','verified_repair','冻结的第二轮修补将读者释放操作合并为原子 RMW，保留原断言和四个线程。'),
 'unwind-limit':('unwind0','unwind1','verified_repair','冻结修补在生产端归一化请求，保留两个线程、读者循环和原断言，功能约束沿用预实验。'),
 'ldv-publication':('ldv-join','ldv-join-fix','trace_repair','发布设备状态与检查属于同一原子操作，仍允许工作线程更新设备且保留退出时的 join。'),
 'reorder-two':('reorder2','reorder2-fix','trace_repair','将两字段写入和相应读取各合并为一次原子操作，保留断言、线程及命令行参数。'),
 'reorder-five':('reorder5','reorder5-fix','trace_repair','将两字段写入和相应读取各合并为一次原子操作，保留断言、线程及命令行参数。'),
 'two-stage':('twostage','twostage-fix','trace_repair','数据发布和读取在相同锁顺序下取得两个字段的一致快照。'),
 'stack-occupancy':('stack2','stack1','published_variant_fix','公开对应变体在既有互斥区使用实际栈深度决定是否出栈，保留相同的下溢与上溢条件。'),
 'ticket-5-6':('ticket5','ticket6','scale_control','论文归档的公开版本增加一个工作线程，保留票号协议和 b 的可达性性质。'),
 'ticket-6-7':('ticket6','ticket7','scale_control','论文归档的七线程版本再增加一个工作线程，属于规模对照。'),
 'fib-strict-12':('fib-racy12-0','fib-racy12-1','upstream_sync_residual','采用竞态补丁之前和上游恢复严格小于性质之后的公开版本。两端均检查 i < correct && j < correct，读快照仍可能到达上界。'),
}
for n in (10,11,12):
    PAIRS[f'fib-snapshot-{n}']=(f'fib-history{n}-0',f'fib-history{n}-1','upstream_sync_fix',
        f'上游提交 5110fee 将原断言的两个共享读合并为一次原子快照。每个工作线程仍更新 {n} 次，两端保持同一数学上界。这是同一补丁的一个规模。')


def freeze(names):
    cases=json.loads((E/'inventory.json').read_bytes())
    for cid in names:
        a,b,kind,reason=PAIRS[cid];d=DS/cid
        d.mkdir(parents=True,exist_ok=True)
        sides={};buffers=[]
        for side,k in zip(('old','new'),(a,b)):
            data=cases[k];src=ROOT/data['file'];s=d/side;s.mkdir(exist_ok=True)
            name='program'+Path(data['original']).suffix
            blob=src.read_bytes();assert h(blob)==data['sha256']
            (s/name).write_bytes(blob);buffers.append(blob)
            spec=src.with_name('task.yml').read_bytes();assert h(spec)==data['yaml_sha256']
            (s/'upstream.yml').write_bytes(spec)
            sides[side]={**data,'local_file':side+'/'+name}
        assert sides['old']['model']==sides['new']['model'] and sides['old']['bound']==sides['new']['bound']
        patch=''.join(difflib.unified_diff(buffers[0].decode().splitlines(True),buffers[1].decode().splitlines(True),
                    fromfile=sides['old']['local_file'],tofile=sides['new']['local_file'])).encode()
        assert patch;(d/'patch.diff').write_bytes(patch)
        provenance=dict(case_id=cid,pair_kind=kind,sides=sides,patch_sha256=h(patch),svcomp26_commit=TAG,
            artifact_doi='10.5281/zenodo.18616443',repair_freeze='ff434538e5eaa78cf8c5e93eb3e41a7ccf06a5ff' if cid.startswith(('rw-','unwind')) else None,
            predecessor='ad51830bf5614c51f173527bcc534a6c7877b67a')
        dump(d/'provenance.json',provenance)
        opts=job(sides['old'],'placeholder',660,6)['argv']
        # JSON is also a valid YAML 1.2 document. Standard-library-only replay on Linux.
        dump(d/'task.yaml',dict(case_id=cid,description=reason,model=sides['old']['model'],property='unreach-call.prp',
                 property_sha256=PROPERTY,argv=opts,pair_kind=kind,sides={s:{'file':v['local_file'],'sha256':v['sha256']} for s,v in sides.items()},
                 limits={'memory_gib':7,'timeout_s':660},binding='all native properties including reach_error.assertion.1 and all unwinding assertions'))
        pp=(REPO/'cases/svcomp26/c/properties/unreach-call.prp').read_bytes()
        assert h(pp)==PROPERTY
        (d/'unreach-call.prp').write_bytes(pp)
        if cid.startswith('ticket'):
            shutil.copyfile(REPO/'reports/evidence/stage-11b/versions/LicenseRef-BSD-3-Clause-Attribution-Vandikas.txt',d/'LICENSE.txt')


def formal(names,phase):
    cases=json.loads((E/'inventory.json').read_bytes()); ordered=[]
    for key in names:
        for k in PAIRS[key][:2]:
            if k not in ordered:ordered.append(k)
    dump(ROOT/(phase+'.json'),[job(cases[k],phase,740,7,capture=True) for k in ordered])
    schedule([(phase,1)])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=('freeze','formal'));p.add_argument('names',nargs='+',choices=PAIRS)
    p.add_argument('--phase',default='formal');a=p.parse_args()
    if a.action=='freeze':freeze(a.names)
    else:formal(a.names,a.phase)
