"""Render review tables from recomputed trial rows, independent frontend controls and native receipts."""
import csv
import json
import statistics as st
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.stage9.run_matrix import FIRST,OTHER
from scripts.stage9.evidence import locate

def md(path,sections):
    path.write_bytes(('\n\n'.join(sections)+'\n').encode())

def table(head,rows):
    return '\n'.join('| '+' | '.join(map(str,row))+' |' for row in [head,['---']*len(head),*rows])

def group(s,name,k,unit=1):
    return s['groups'][name][k]['median']/unit

def pair(a,b):
    return f'{a:.1f} / {b:.1f}'

def render(raw,dest):
    read=lambda p:json.loads(p.read_bytes())
    s=read(dest/'paired.json')
    v=read(dest/'verification.json')
    with (dest/'trials.csv').open(encoding='utf8') as f:trials=list(csv.DictReader(f))
    with (dest/'frontend-profile.csv').open(encoding='utf8') as f:profile=list(csv.DictReader(f))
    def pr(c,v,k):return st.median(float(r[k]) for r in profile if r['case']==c and r['variant']==v)
    performance=[];resources=[];outliers=[];costs=[];timing=[];old_stage=[]
    s8=read(ROOT/'reports/evidence/stage-08/summary.json')
    for c in FIRST:
        x=s[c];p=x['paired']
        a=lambda role,k,unit=1:group(x,role,k,unit)
        performance.append([c,pair(a('before_I3','front_ms'),a('after_I3','front_ms')),f"{p['front_saved']['median']:.1f}",
              pair(a('before_I3','p1_ms'),a('after_I3','p1_ms')),pair(a('before_F1','p1_ms'),a('after_F1','p1_ms')),
              pair(p['before_i3_minus_f1']['median'],p['after_i3_minus_f1']['median']),str(x['faster_repeats'])+'/5'])
        resources.append([c,pair(a('before_I3','old_ms'),a('after_I3','old_ms')),
            pair(a('before_F1','old_ms'),a('after_F1','old_ms')),pair(a('before_I3','cycle_ms'),a('after_I3','cycle_ms')),
            pair(a('before_F1','cycle_ms'),a('after_F1','cycle_ms')),f"{p['i3_cycle_saved']['median']:.1f}"])
        for mode in ('F1','I3'):
            b,e='before_'+mode,'after_'+mode
            costs.append([c,mode,pair(a(b,'old_cpu_ms'),a(e,'old_cpu_ms')),pair(a(b,'cpu_ms'),a(e,'cpu_ms')),
              pair(a(b,'old_rss_kib',1024),a(e,'old_rss_kib',1024)),pair(a(b,'rss_kib',1024),a(e,'rss_kib',1024)),
              pair(a(b,'old_cgroup_kib',1024),a(e,'old_cgroup_kib',1024)),pair(a(b,'cgroup_kib',1024),a(e,'cgroup_kib',1024)),
              pair(a(b,'max_procs'),a(e,'max_procs'))])
        for name in ('before_I3','after_I3','before_F1','after_F1'):
            t=x['groups'][name]['p1_ms']
            outliers.append([c,name,f"{t['min']:.1f} / {t['median']:.1f} / {t['max']:.1f}",f"{t['q1']:.1f}～{t['q3']:.1f}",
                       ', '.join(f'{m:.1f}' for m in t['outliers']) or '—'])
        for role in ('before','after'):
            k=lambda field:pr(c,role,field)
            timing.append([c,role,*[f'{z:.2f}' for z in (k('wall_ms'),k('adjusted_native_front_ms'),k('gcc_stdin_ms')+k('gcc_file_ms'),
                k('wrapper_minus_gcc_ms'),k('dependency_reduce_ms'),k('prepare_ms'),k('exit_tail_ms'),k('post_exit_to_end_ms'))]])
        historic=next(g for g in s8['groups'] if g['case']==c and g['mode']=='I3' and not g['detail'])
        old_stage.append([c,*[f'{n:.1f}' for n in (historic['frontend_ms']['median'],a('before_I3','front_ms'),a('after_I3','front_ms'),
              historic['wall_ms']['median'],a('before_I3','p1_ms'),a('after_I3','p1_ms'))]])
    md(dest/'performance.md',['# 候选、预热、周期与资源','正式组每个单元重复五次。成对数字依次为阶段 8 控制器重跑和阶段 9。墙钟和 CPU 单位均为 ms。每次先用相同重复号相减，再取配对中位数。',
       table(['病例','前端 前 / 后','前端配对节省','I3 候选 前 / 后','F1 候选 前 / 后','I3−F1 配对差 前 / 后','新版快于 F1'],performance),
       '## P0 与完整周期','周期由当次 P0、实际冻结补丁重放和 P1 相加。正的节省数表示新版周期较短。旧状态同时采集已见的编译器配置及依赖证据。',
       table(['病例','I3 P0 前 / 后','F1 P0 前 / 后','I3 周期 前 / 后','F1 周期 前 / 后','I3 周期配对节省'],resources),
       '## CPU、RSS 及 cgroup 内存','RSS 对组内进程取和，可能重复计入共享页。cgroup 含文件页。两者均为约 5 ms 采样所得的阶段峰值，表中为五次峰值的中位数，单位 MiB。进程数为候选阶段采样峰值。',
       table(['病例','模式','P0 CPU 前 / 后','P1 CPU 前 / 后','P0 RSS 前 / 后','P1 RSS 前 / 后','P0 cgroup 前 / 后','P1 cgroup 前 / 后','P1 进程数 前 / 后'],costs),
       '## 样本范围与异常值','Tukey 界限采用包含端点的四分位数和 1.5 IQR。全部样本均参与中位数。详细的前端范围、求解、绑定及逐次读数同时保存在 CSV 和 JSON。',
       table(['病例','组别','候选 min / median / max','Q1～Q3','界外样本 ms'],outliers),
       '## 与阶段 8 固定数据对照','历史行只用于查看同平台的跨时段波动。正式结论使用本阶段交替测得的两套控制器。',
       table(['病例','历史前端','重跑前端','新版前端','历史 I3','重跑 I3','新版 I3'],old_stage),
       '[逐次结果](trials.csv) · [逐例配对分布](paired.json)'])
    md(dest/'frontend-breakdown.md',['# 候选前端分相','下表是 50 次独立插桩运行各五次的墙钟中位数，单位 ms。两组使用同一原生增强版和相同的两层时钟探针。普通 F1/I3 运行没有这些探针。每个样本实测 2 个标准输入和 3 个文件调用，GOTO 均重算并匹配冻结模型。',
       table(['病例','版本','外层','原生 C/GOTO¹','实际 GCC 五次²','包装器减 GCC³','依赖记录','启动前准备','退出发现延迟⁴','退出至前端结束'],timing),
       '¹ 使用 get_goto_program 父阶段，扣除内部三次文件包装器寿命并加回三次真实 GCC 时间，估算剥离记录包装的原生前端。两次配置探测位于父阶段外。原生分项与 GOTO JSON/IREP 写耗时见逐次表。',
       '² 真实 GCC 子进程区间。表中为文件调用与标准输入调用各自中位数之和。³ 外层 GCC 分派器五个区间减内层 GCC 区间，含脚本进入、通知、输出转发、探针边界及分派进程等待。旧记录器的依赖计算嵌套在该区间，新记录器的文件计算发生于同步通知内，两个探测输出则在退出后处理。各列不可直接相加。',
       '⁴ 独立观察线程和被测控制器均使用单调时钟。独立线程观察 pidfd 的调度延迟可使数值略为负。新版前端总时钟还覆盖 GCC 身份确认、收集完成和状态写回。',
       '[分相逐次结果](frontend-profile.csv) · [测量实现](../../../scripts/stage9/profile.py)'])
    rows=[];streams=read(dest/'solver-inputs.json')
    for c in (*FIRST,*OTHER):
        p,_=locate(raw,'side','after',c,1,'I3')
        m=read(p/'measurement.json')
        sc=m['native']['sc_counters'];t=m['theory']
        rows.append([c,m['verdict']['classification'],m['path'],m['native']['reused_prefix_symex_steps'],m['native']['executed_symex_steps'],
                     sc.get('thread_edges_reused',0),sc.get('rf_edges_reused',0),t['accepted'],t['imported'],m['fallback_reason'] or '—'])
    md(dest/'regression.md',['# 九例独立全量与增量回归','阶段 9 每个病例均有带观察的独立 F1、实际 I3，另有相同条件下的阶段 8 对照。逐项重算 GOTO、原始 SSA、SC 输入及最终模型，将前缀分派与恢复后分派拼接后和独立全量访问顺序核对。每份理论证书重算上下文和有符号绑定，并读取原生导入回执。',
        table(['病例','P1','路径','跳过 / 步','执行 / 步','复用 PO/APO','复用 RF','审核通过','实际导入','回退原因'],rows),
        '所有旧程序都违反原目标。两类候选残错均从原生结果重建反例并核对保留的失败交错。具体次数见核验回执。',
        '[模型及证书核验计数](verification.json) · [各模式有序求解输入](solver-inputs.json) · [负向控制](negative-results.json)'])
    fib=[r for r in trials if r['case']=='fib_updates_8' and r['group']=='formal']
    rt=[]
    for i in range(1,6):
        def sample(v,m):return next(r for r in fib if r['variant']==v and r['mode']==m and int(r['rep'])==i)
        b,a=sample('before','I3'),sample('after','I3')
        rt.append([i,pair(float(b['p1_ms'])-float(sample('before','F1')['p1_ms']),float(a['p1_ms'])-float(sample('after','F1')['p1_ms'])),
                   pair(float(b['solver_ms']),float(a['solver_ms'])),b['decisions']+' / '+a['decisions'],b['conflicts']+' / '+a['conflicts'],
                   b['propagations']+' / '+a['propagations'],b['imported']+' / '+a['imported']])
    spec=streams['fib_updates_8']
    digs=[[mode,name,row['bytes'],row['before'],str(row['equal'])] for mode,files in spec.items() for name,row in files.items()]
    md(dest/'fibonacci.md',['# 八轮 Fibonacci 的配对结果与求解证据',
      table(['重复号','I3−F1 前 / 后 ms','I3 求解 前 / 后 ms','决策 前 / 后','冲突 前 / 后','传播 前 / 后','实际导入 前 / 后'],rt),
      '下表在额外的 F1 与 I3 对照中直接比较了每种模式优化前后的二进制输入流、理论图、带符号子句摘要、首次搜索记录和最终计数。',
      table(['模式','原生记录','字节','优化前 SHA-256','优化后相同'],digs),
      '[全部搜索记录哈希](solver-inputs.json) · [普通配对分布](paired.json)'])

if __name__=='__main__':render(*[Path(s).resolve() for s in sys.argv[1:]])
