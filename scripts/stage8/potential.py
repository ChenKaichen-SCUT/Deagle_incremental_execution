"""Compute conditional engineering ceilings without assigning solver noise to model reuse."""
import csv
import statistics as st
import sys
from pathlib import Path
from tables import CASES,table,n,write

def render(dest):
    def rows(file):
        with (dest/file).open(encoding='utf8') as f:return list(csv.DictReader(f))
    raw=rows('ablation-results.csv')
    trial={(r['case'],r['mode'],int(r['rep']),r['detail']=='True'):r for r in raw}
    front={(r['case'],r['variant'],int(r['repeat'])):r for r in rows('frontend-results.csv')}
    spans={(r['case'],int(r['rep'])):float(r['wall_ms']) for r in rows('phase-times.csv') if r['mode']=='I3' and r['operation']=='binder.binding.binder'}
    def get(c,m,i,k,detail=False):return float(trial[c,m,i,detail][k])
    ranges=range(1,6)
    simulated=[];fallback=[]
    for c in CASES:
        gaps=[];ceilings=[];rest=[];helpers=[];other=[];ideal=[];shares=[]
        for i in ranges:
            gap=get(c,'I3',i,'wall_ms')-get(c,'F1',i,'wall_ms')
            gaps.append(gap)
            if (c,'recorder',i) in front:
                delta=float(front[c,'recorder',i]['outer_ms'])-float(front[c,'system-gcc',i]['child_lifetime_ms'])
                ceilings.append(delta);rest.append(gap-delta)
            helpers.append(get(c,'I3',i,'worker_ms',True)-spans[c,i])
            other.append(gap-(get(c,'I3',i,'solver_ms')-get(c,'F1',i,'solver_ms')))
            t=get(c,'F1',i,'wall_ms')
            saved=get(c,'F1',i,'prefix_wall_ms',True)+get(c,'F1',i,'region_gen_wall_ms',True)
            solver_delta=(get(c,'I3',i,'solver_ms')-get(c,'I2',i,'solver_ms')) if get(c,'I3',i,'imported') else 0.0
            ideal.append(t/(t-saved+solver_delta))
            shares.append(100*(get(c,'F1',i,'solver_ms')/t))
        med=lambda v:st.median(v) if v else None
        simulated.append([c,n(med(gaps),1),n(med(ceilings),1),n(med(rest),1),n(med(helpers),1),n(med(ideal),4)+'×',n(med(shares),1)+'%'])
        if trial[c,'I3',1,False]['path']=='full_fallback':
            fallback.append([c,n(med(gaps),1),n(med(other),1),trial[c,'I3',1,False]['reason']])
    write(dest/'engineering-potential.md',[
        '# 把实测模块成本换算成工程优化空间',
        '下表前两项来自正式运行和独立前端控制，后面各项是反事实估计。各差先按重复号形成，再取五次中位数。后续实现的速度和内存还须重新测量。',
        table(['版本对','I3−F1 候选 ms','前端工程空间¹ ms','若用尽前端空间后的差 ms','审核子进程外层余量² ms','理想零维护倍率³','F1 求解占比'],simulated),
        '¹ 仅五个直接测过的病例有此值。原记录器的外层墙钟减使用系统 GCC 的实际进程寿命，把所有额外依赖记录成本及带超时 wait 的退出尾部均视为可消除。正式实现仍要保证依赖身份完整，实际节省可能更小。正的剩余差表示在该假设下 I3 依然更慢。',
        '² 原生等待审核器的墙钟减去子进程内实测的整个 binder 函数墙钟。可定位于启动、导入模块、退出、IPC、额外诊断及调度。它给出在该实现中争取的量级，并不要求也不能删除证书检查。',
        '³ 假定前端等公共工作花费与 F1 相同，维护开销为零，当前命中的前缀和 SC 区域完全免费，仍支付完整编码和求解。对实际导入了子句的病例，另加同一重复号普通 I3−I2 的求解时差。此列将详细 CPU 探针范围的墙钟与普通组结合，是基于已有搜索轨迹的条件估计，不是对未来所有候选的数学上界。零导入时赋予引理的收益为零。只看建模部分的 Amdahl 上限见[病例账本](case-costs.md)。',
        '## 回退提前分流',
        table(['版本对','普通 I3−F1 ms','扣除两边求解差后的非求解差 ms','实际回退原因'],fallback),
        '这是在候选提交之后直接选择同一增强版全量路径可争取的量级。额外旧程序采集已经支付。分类器自身、新程序输入校验及必要结果解析也需要时间。这组数与前端流程收缩有重叠，不能相加。',
        '[正式样本](ablation-results.csv) · [独立前端对照](frontend-results.csv) · [审核器父子阶段](phase-times.csv)'])
if __name__=='__main__':render(Path(sys.argv[1]))
