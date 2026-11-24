"""Publish independently measured versions, conservative model deltas and every screening outcome."""
import argparse
import csv
import gzip
import json
import shutil
import zipfile
from pathlib import Path
from prepare import REPO,ROOT,DS,E,PROPERTY,dump,h
from freeze import PAIRS
from delta import compare,load
from scripts.stage11b.raw_store import split,archive

RETURN=ROOT.parent/'returned'
FINAL=['circular-buffer','ldv-publication','unwind-limit','rw-acquire','rw-release','fib-snapshot-10','fib-snapshot-11','fib-snapshot-12','fib-strict-12','ticket-6-7']
FIELDS=['case_id','source','pair_kind','P0_result','P1_result','P0_search_time','P1_search_time','P0_learnt_count','P0_theory_conflicts',
        'B_delta','theory_delta','status','reason','P1_band','P0_program','P1_program','model_class']
FORMALS=('formal','formal-history','formal-strict')


def receipts(root):
    return [(p,load(p)) for p in sorted(root.glob('*/*/receipt.json'))]


def compact(r):
    keys=('out','identity','sample','result','properties','warnings','phases','counters','wall_s','user_s','sys_s','peak_rss_kib','exit','host',
          'capture','bound','binary','argv','timeout_s','memory_gib','core','files','raw_sha256')
    return {k:r[k] for k in keys}


def band(s):
    if s is None:return ''
    return '<10' if s<10 else '10-30' if s<=30 else '30-300' if s<=300 else '>300'


def formal_data(name,rows):
    found=[(p,a) for p,a in rows if a['phase'] in FORMALS and a['sample']==name]
    if len(found)!=1:raise ValueError('missing or ambiguous full run '+name)
    p,r=found[0];assert r['host']=='server-8core' and r['capture'] and r['result'] in ('SAT','UNSAT')
    where=p.parent/r['attempt']
    for name,digest in r['raw_sha256'].items():
        if h((where/name).read_bytes())!=digest:raise ValueError('broken native artifact '+name)
    phases={k:load(where/(k+'.json'))['phase'] for k in ('raw_ssa','sc_input','full_model')}
    assert len(phases)==3
    return where,r


def finalize_pair(cid,base,rows):
    old,new,kind,review=PAIRS[cid];d=base
    dp,dr=formal_data(old,rows);ep,er=formal_data(new,rows)
    task=load(d/'task.yaml')
    for k,v in [('old',dr),('new',er)]:
        assert v['argv']==task['argv'] and list(v['files'].values())[0]['sha256']==task['sides'][k]['sha256']
        assert all(s=='SUCCESS' for p,s in v['properties'] if 'unwind' in p)
    z=compare(dp,ep,dr,er,d/'semantic-diff.json.gz')
    z['semantic_diff_sha256']=h((d/'semantic-diff.json.gz').read_bytes())
    dump(d/'model-delta.json',z)
    times=[x['phases']['search']['wall_s'] for x in (dr,er)]
    osrc=load(d/'provenance.json')
    baseline=dict(case_id=cid,host='server-8core',profile='serial cold full model and fresh native Closure; one single-core job',
          repeats=1,results={k:compact(v) for k,v in [('old',dr),('new',er)]},
          prior_screenings={k:[dict(out=r['out'],native_search_s=r['phases'].get('search',{}).get('wall_s'),wall_s=r['wall_s'],result=r['result'])
                         for _,r in rows if r['sample']==q and r['phase'] not in FORMALS] for k,q in [('old',old),('new',new)]})
    dump(d/'baseline.json',baseline)
    t=z['theory'];b=z['boolean'];know=z['old_knowledge']
    p0,p1=dr['result'],er['result']
    if kind in ('trace_repair','verified_repair'):assert (p0,p1)==('SAT','UNSAT')
    if kind in ('residual_repair','upstream_sync_residual'):assert (p0,p1)==('SAT','SAT')
    if kind in ('scale_control','upstream_sync_fix'):assert (p0,p1)==('UNSAT','UNSAT')
    status='supplement' if kind=='scale_control' else 'core'
    proof_notes='原始宿主上的时间见 baseline.json，原始公式、图和轨迹见阶段证据索引。模型差分仅确认通过签名和语义身份核对的部分；未映射项单独计数。'
    if cid.startswith('fib-'):proof_notes+=' 父版本的断言读取与工作线程可并发，本表记录固定 Deagle 的 SC 编码；历史父版本不能据此获得 C11 无数据竞争保证。'
    if cid.startswith('rw-') or cid=='unwind-limit':proof_notes+=' 程序修补使用 SV-COMP AI 预实验的冻结字节。'
    readme=f'# {cid}\n\n{review}\n\n原性质由 YAML 的 unreach-call.prp 指定。两端均按 {task["model"]}、SC 和展开 {dr["bound"]} 从头建模，执行全部原生性质及展开检查。\n\n| 版本 | 结论 | 服务器纯搜索秒 | CDCL 冲突 | 理论冲突 |\n|---|---|---:|---:|---:|\n'
    for k,r in [('P0',dr),('P1',er)]:
        readme+=f'| {k} | {r["result"]} | {r["phases"]["search"]["wall_s"]:.6f} | {r["counters"]["conflicts"]} | {r["counters"]["theory_conflicts"]} |\n'
    readme+=f'\nP0 产生 {know["generated_uip"]} 条 CDCL 第一 UIP 学习记录。已确认 {b["semantic_variables"]} 个有符号变量对应和 {b["original_retained_confirmed"]} 条保留原始子句（按重数）。{proof_notes}\n\nWindows 工作区运行 '
    readme+=f'\u0060.\\deagle-local.cmd hard-pair {cid}\u0060。\n'
    (d/'README.md').write_bytes(readme.encode())
    return dict(case_id=cid,source=osrc['sides']['old']['source'],pair_kind=kind,P0_result=p0,P1_result=p1,
            P0_search_time=times[0],P1_search_time=times[1],P0_learnt_count=know['generated_uip'],P0_theory_conflicts=dr['counters']['theory_conflicts'],
            B_delta=f"{b['old']['clauses']} -> {b['new']['clauses']} / 确认保留 {b['original_retained_confirmed']}",
            theory_delta=' / '.join(f"{k} {v['old']}->{v['new']}" for k,v in t['edges'].items()),model_class=z['classification'],
            status=status,reason=review,P1_band=band(times[1]),P0_program=old,P1_program=new)


def screening(rows):
    candidates=load(E/'inventory.json')
    all_rows=[{**compact(a),'phase':a['phase'],'attempt':a['attempt'],'receipt_path':p.relative_to(RETURN).as_posix()} for p,a in rows]
    (E/'all-runs.json.gz').write_bytes(gzip.compress((json.dumps(all_rows,ensure_ascii=False,separators=(',',':'))+'\n').encode(),mtime=0))
    qs={p.stem:load(p) for p in RETURN.glob('*-queue.json')}
    dump(E/'queues.json',qs)
    plans={name[:-len('-queue')]:load(RETURN/(name[:-len('-queue')]+'.json')) for name in sorted(qs)}
    orders={p.name:p.read_text(encoding='utf-8').splitlines() for p in sorted(RETURN.glob('order-*.txt'))}
    encoded=json.dumps({'plans':plans,'orders':orders},sort_keys=True,separators=(',',':')).encode()
    (E/'plans.json.gz').write_bytes(gzip.compress(encoded,mtime=0))
    hosts=E/'host';hosts.mkdir(exist_ok=True)
    for pat in ('order-*.host','order-*.log','order-*.complete'):
        for p in RETURN.glob(pat): shutil.copyfile(p,hosts/p.name)
    stages={k:[r for r in all_rows if r['sample']==k] for k in candidates}
    if any(not v for v in stages.values()):raise ValueError('unmeasured sample')
    return candidates,stages


def reject_rows(stages,accepted):
    check=[]
    def rejected(key,old,new,reason,kind='unresolved_pair',status='unresolved'):
        def choose(sample):
            if sample not in stages:return None
            return max(stages[sample],key=lambda r: (r['phase'] in FORMALS,r['phase']=='isolated',r['timeout_s'],r['memory_gib']))
        a,b=choose(old),choose(new)
        data=dict.fromkeys(FIELDS,'')
        for side,r in [('P0',a),('P1',b)]:
            if r:
                data[side+'_result']=r['result'] if r['result'] in ('SAT','UNSAT') else 'UNKNOWN'
                meter=r['phases'].get('search',{})
                data[side+'_search_time']=meter['wall_s'] if meter.get('calls') else ''
        data.update(case_id=key,source='SV-Benchmarks / FM26',pair_kind=kind,status=status,reason=reason,P0_program=old,P1_program=new,
                    P1_band=band(data['P1_search_time']) if isinstance(data['P1_search_time'],float) and data['P1_result'] in ('SAT','UNSAT') else '')
        check.append(data)
    for key in ('counter-queue','array-sum','array-sum-alt','buffer-mult','buffer-series','buffer-mult-alt'):
        rejected('public-'+key,key+'0',key+'1','公开逻辑修补保留断言，但数据依赖的循环存在失败的展开断言，不能冻结为通过。')
    for key,other in [('25_stack_longer-1','25_stack_longer-2'),('25_stack_longest-2','25_stack_longest-1'),('26_stack_cas_longer-1','26_stack_cas_longer-2')]:
        rejected('assertion-change-'+key,key,other,'公开对应文件反转了检查谓词；原版确有目标反例且无限创建线程导致展开失败。','changed_property','excluded')
    rejected('arithmetic','arithmetic0','arithmetic1','两个展开界限下均有失败的等待循环展开；目标真假和多次求解保留在逐次记录。')
    rejected('public-stack','stack2','stack1','公开版本锁内改用真实深度，错误条件等价；两端均在共享指针写入处安全拒绝。')
    for key in ('netbsd','netbsd-pthread'):
        rejected('fm-'+key,key,'','未获得所有展开义务均通过的相邻版本，长时限复核保留。','unpaired_candidate')
    for key in ('fib-safe10','fib-safe11'):
        rejected('official-'+key,'',key,'单独的公开安全版本。常见对应 unsafe 文件修改断言，另列有真实改动历史的版本对。','unpaired_candidate')
    used={s for r in accepted+check for s in (r['P0_program'],r['P1_program'])}
    for key in sorted(stages.keys()-used):
        reason='固定后端拒绝并发共享指针写入；安全配置下无法完成建模。' if any(r['result']=='UNSUPPORTED_POINTER' for r in stages[key]) else '未取得相同性质的完整可用版本对，逐次记录保留。'
        rejected('candidate-'+key,key,'',reason,'unpaired_candidate')
    rejected('fib-unsafe-intermediate','','','上游 11e0dee8 在同步修改中把严格小于放宽为小于等于，排除这一中间版本。','changed_property','excluded')
    for key,reason in [('reorder-c11','10/20/30 的 YAML 仅声明数据竞争；未借用注释中的可达性性质。'),
                        ('singleton','两个已发布的 .i 改变断言，不能作为同性质修复。'),
                        ('sssc12','公开变体的断言与行为或输入限制不同，且主线程无限创建工作线程。'),
                        ('triangular','safe/unsafe 候选改变边界判断，不能当作原性质修补。'),
                        ('cdac-datarace','演示程序在不同文件中检查 ==40 与 !=40；不能当作同性质修补。'),
                        ('circular-buffer-ok','公开 ok 源文件改动原检查，研究版本另用真实反例修补并保留原断言。')]:
        rejected('review-'+key,'','',reason,'source_review','excluded')
    panel=load(REPO/'reports/evidence/stage-11b/panel/selection.json')['rows']
    for r in panel:
        if not r['reach'] or r['kind']=='weak-control':
            why='FM YAML 没有 unreach-call，保留原始筛选记录。' if not r['reach'] else '阶段 11B 严格 SC 独立顺序检查与固定原生结论存在差异，继续隔离。'
            rejected('archived-'+r['task'],'','',why,'prior_source_review','excluded')
    previous=load(REPO/'reports/evidence/svcomp26/local-properties.json')
    for name in ('bounded_buffer','elimination_backoff_stack','safestack_relacy','workstealqueue_mutex-1'):
        rejected('prior-'+name,'','','预实验原始记录 '+previous[name]['P0']['classification']+'；本次未取得同性质的新版本对。','prior_source_review','unresolved')
    return check


def raw_public(roots):
    raw=E/'raw';raw.mkdir(exist_ok=True)
    zip_path=ROOT.parent/'release-objects.zip';files={};seen=set()
    with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5,allowZip64=True) as z:
        def put(name,file):
            blob=file.read_bytes();key=h(blob);files[name]=key
            if key not in seen:
                info=zipfile.ZipInfo(key,(1980,1,1,0,0,0));info.create_system=3;info.external_attr=0o100644<<16
                z.writestr(info,blob,compress_type=zipfile.ZIP_DEFLATED,compresslevel=5);seen.add(key)
        for base,root in roots:
            for p,a in receipts(root):
                dest=p.parent/a['attempt'];prefix=base+'/'+p.relative_to(root).parent.as_posix()
                put(prefix+'/receipt.json',p)
                for name,want in sorted(a['raw_sha256'].items()):
                    path=dest/name
                    if not path.is_file():continue
                    if h(path.read_bytes())!=want:raise ValueError('raw SHA mismatch '+str(path))
                    put(prefix+'/'+name,path)
            for pattern in ('*-queue.json','order-*.host','order-*.log','order-*.complete'):
                for p in sorted(root.glob(pattern)):put(base+'/'+p.name,p)
        for p in sorted((ROOT/'inputs').rglob('*')):
            if p.is_file():put(p.relative_to(ROOT).as_posix(),p)
    split(zip_path,raw)
    dump(raw/'files.json',files)
    with archive(raw) as z:
        if z.testzip():raise ValueError('bad public ZIP')
        assert set(z.namelist())==set(files.values())
    return dict(zip_bytes=zip_path.stat().st_size,original_paths=len(files),unique_objects=len(seen),sha256=load(raw/'parts.json')['sha256'])


def generate(final,cal,raw=False):
    rows=receipts(RETURN);table=[]
    for cid in final:table.append(finalize_pair(cid,DS/cid,rows))
    for cid in cal:
        summary=finalize_pair(cid,E/'calibration'/cid,rows);dump(E/'calibration'/(cid+'.json'),summary)
    candidates,stages=screening(rows)
    rest=reject_rows(stages,table+[load(E/'calibration'/(cid+'.json')) for cid in cal])
    for cid in cal:
        s=load(E/'calibration'/(cid+'.json'));s.update(status='calibration',reason='已在阶段 11B 发布的规模对照，本次保留独立核对。');rest.append(s)
    with (DS/'dataset.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,lineterminator='\n');w.writeheader();w.writerows(table+rest)
    local={}
    for cid,fold in [('circular-buffer','local-buffer'),('fib-snapshot-11','local-fib11'),('ldv-publication','local-ldv')]:
        root=ROOT.parent/fold
        if not (root/'local').is_dir():continue
        vals={}
        for p,r in receipts(root):
            old=load(DS/cid/'baseline.json')['results'][r['sample']]
            flags=r['argv']==old['argv'];props=r['properties']==old['properties'];rc=r['exit']==old['exit']
            shas={k:r['raw_sha256'][k]==old['raw_sha256'][k] for k in ('s8-input.bin','s8-graph.tsv','search.bin')}
            assert flags and props and rc and all(shas.values()) and r['binary']==old['binary']
            vals[r['sample']]=dict(checks=shas,argv_equal=flags,properties_equal=props,result=r['result'],sha256=next(iter(r['files'].values()))['sha256'],
                                    search_s=r['phases']['search']['wall_s'],wall_s=r['wall_s'],host='wsl-local',receipt_identity=r['identity'])
        assert len(vals)==2;local[cid]=vals
    dump(E/'local-verification.json',local)
    stats=dict(status='READY_FOR_REVIEW',formal_pairs=len(table),real_pairs=sum(r['pair_kind']!='scale_control' for r in table),
            native_input_versions=len(candidates),unique_native_source_hashes=len({c['sha256'] for c in candidates.values()}),
            distinct_published_task_paths=len({c['task'] for c in candidates.values()}),server_runs=len(rows),local_pairs=sorted(local),
            official26_unreach_rows=725,official25_overlap=len(load(E/'svcomp25/overlap.json')),fm_panel=13,
            accepted=table,screening=rest,local_performance_separate=True,property_sha256=PROPERTY)
    if raw:stats['public_raw']=raw_public([('server',RETURN),*[(name,ROOT.parent/name) for name in ('local-buffer','local-fib11','local-ldv') if (ROOT.parent/name).exists()]])
    elif (E/'raw/parts.json').exists():
        parts=load(E/'raw/parts.json');files=load(E/'raw/files.json')
        stats['public_raw']=dict(zip_bytes=sum(p['bytes'] for p in parts['parts']),original_paths=len(files),
                                 unique_objects=len(set(files.values())),sha256=parts['sha256'])
    dump(DS/'manifest.json',stats)
    return table


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--raw',action='store_true')
    p.add_argument('--individual',nargs='*')
    a=p.parse_args()
    if a.individual:
        rows=receipts(RETURN)
        for cid in a.individual:
            print(finalize_pair(cid,DS/cid,rows)['case_id'])
    else:generate(FINAL,['ticket-5-6'],a.raw)
