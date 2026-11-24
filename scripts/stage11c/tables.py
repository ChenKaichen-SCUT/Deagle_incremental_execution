"""Render paired results directly from the frozen trials and audited counters."""
import statistics,sys
from pathlib import Path
from audit import read
def render(e):
    summary=read(e/'summary.json');lc=read(e/'lifecycle.json')['rows']
    names={'fib_updates_8':'Fibonacci 8','lock12':'读写锁 P1→P2','ticket56-reviewed':'ticket 5→6'}
    modes=('F','B','T','C','TC')
    def rows():
        for case,name in names.items():
            for m in modes:yield case,name,m,summary[case]['modes'][m]
    lines=['# 原生求解、维护成本与配对结果','',
           '所有时间表均以毫秒计，保留两位小数。每个病例每种模式均有七轮。纯搜索使用原生 search 的 CPU 与单调墙钟。P1 求解器总时间从 model_ready（开始 CNF 和理论图编码）到 decider_return，覆盖编码、进程内外的绑定和证明审核、原生提交、搜索及桥接返回。两版周期从启动第一版到两版全部结束并通过独立输出审核，含 P0 的证明生成和持久化。带观测的固定程序单次独立运行、原始 F0 发布二进制七轮直接运行均另列。各表的中位数先在各自口径内计算。','']
    def table(headers,gen):
        lines.extend(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|'])
        for row in gen:lines.append('| '+' | '.join(str(x) for x in row)+' |')
        lines.append('')
    table(['程序','模式','P1 搜索墙钟','P1 搜索 CPU','P1 求解器总计','P1 程序总计','完整周期'],
          ([name,m,*[f"{v['median'][k]:,.2f}" for k in ('search_ms','search_cpu_ms','p1_solver_total_ms','p1_program_ms','cycle_ms')]] for _,name,m,v in rows()))
    table(['程序','阶段 10 直接原生 P0 完整墙钟','P1 完整墙钟','P1 纯搜索','P1 求解器总计'],
          ([name,*[f'{x:,.2f}' for x in (summary[c]['stock'][0]['program_ms'],summary[c]['stock'][1]['program_ms'],summary[c]['stock'][1]['search_ms'],summary[c]['stock'][1]['solver_total_ms'])]] for c,name in names.items()))
    original=read(e/'original.json')['rows']
    def original_times(case,side):
        vals=[r['wall_ns']/1e6 for r in original if r['case']==case and r['side']==side]
        return f'{statistics.median(vals):,.2f} [{min(vals):,.2f}, {max(vals):,.2f}]'
    table(['程序','原始 F0 的 P0 完整墙钟中位数与范围','原始 F0 的 P1 完整墙钟中位数与范围'],
          ([name,original_times(c,'old'),original_times(c,'new')] for c,name in names.items()))
    lines.extend(['## 配对差与波动','','每格依次为基线减测试模式的配对中位数、最小值至最大值和更快轮数。F 对照衡量总效果。C 对 B、TC 对 T 分别衡量单独或叠加混合学习信息的效果。',''])
    def differences():
        for c,name in names.items():
            for ref,m in [('F','B'),('F','T'),('F','C'),('F','TC'),('B','T'),('B','C'),('T','TC')]:
                metrics=summary[c]['modes'][m]['paired'][ref]
                def cell(k):
                    a=metrics[k];lo,hi=a['range'];return f"{a['median']:+,.2f} [{lo:+,.2f}, {hi:+,.2f}] {a['faster']}/7"
                yield [name,ref+'−'+m,*[cell(k) for k in ('search_ms','p1_solver_total_ms','cycle_ms')]]
    table(['程序','配对','纯搜索','P1 求解器总计','完整周期'],differences())
    lines.extend(['## 搜索与学习库','','search starts 包含首次进入，重启次数在本组单查询实验为该值减一。1-UIP、预防 Clause 分配、reduceDB 和回收数量取独立计数构建，须与相应七轮逐版原生搜索流及主要计数全部相同。',''])
    def work():
        for c,name,m,r in rows():
            v=r['median'];u=lc[c+'/'+m]['new']['counts']
            yield [name,m,*[f'{int(v[k]):,}' for k in ('decisions','conflicts','propagations','starts','theory_propagations','theory_conflicts')],
                   u['uip_count'],u['prop_clauses'],u['db_reduce'],u['removed_learnts'],u['gcs']]
    table(['程序','模式','决策','冲突','传播','starts','理论传播','理论冲突','1-UIP','预防 Clause','reduceDB','删除学习 Clause','GC'],work())
    lines.extend(['## 证书、维护和资源','','P0 应用覆盖原生实时采集，P0 建库在应用返回后计时。原生分析数值包含正常冲突分析及其观测。P0 增量总准备的开销可以通过相对 B 的配对差核查。P1 匹配与校验包含证据密封、完整图读取和 CNF 索引。理论审核还包含独立原生零决策反证。被拒绝的子句在审核端退役，进入原生库之前就已过滤。它们的审核计入相应阶段，原生没有为它们删除 Clause。P0 与 P1 的运行期库退役另计入 switch。原生提交含状态更新后的原始输入处理，所有小计不能直接相加重算总墙钟。',''])
    def cost():
        for c,name,m,r in rows():
            v=r['median']
            yield [name,m,*[f'{v.get(k,0):,.2f}' for k in ('p0_program_ms','p0_native_snapshot_ms','p0_instrumented_analysis_ms','p0_native_flush_ms','p0_read_context_ms','p0_theory_ms','p0_cdcl_ms','p0_persist_ms','p0_preparation_ms')]]
    table(['程序','模式','P0 应用','原生快照','带观测的 analyze','日志 flush','读上下文','理论构证','CDCL 构证','存储及封印','P0 总准备'],cost())
    def candidate():
        for c,name,m,r in rows():
            v=r['median']
            yield [name,m,*[f'{v.get(k,0):,.2f}' for k in ('p1_seal_mapping_ms','p1_theory_ms','p1_cdcl_ms','p1_persistence_ms','switch_ms','native_install_ms','submit_ms')],
                   f"{v['resident_Pss_kib']/1024:.1f}",f"{v['peak_rss_kib']/1024:.1f}",f"{v['controller_hwm_kib']/1024:.1f}",f"{v['child_cpu_s']:.2f}"]
    table(['程序','模式','匹配及封印','理论审核','CDCL 审核','清单持久化','原生切换','子句导入','原生提交','P1 PSS MiB','worker 峰值 MiB','控制器峰值 MiB','子进程 CPU 秒'],candidate())
    lines.extend(['## 单条实际使用','','下表以首轮 TC 为例。附着和单位化均取原生事件，命中为实际 watcher 单位传播、冲突、analyze 使用或根层传播。重复轮次没有累加为新的子句。各轮、各类拒绝与未命中的记录可在逐次数据与原始证书中核查。',''])
    details=[]
    for c,name in names.items():
        r=summary[c]['modes']['TC']['individual'][0]['reuse']
        for tag,action in r['imports'].items():
            u=r['hits'].get(tag,{});details.append((name,tag,action,*[u.get(k,0) for k in ('unit','conflict','analyze','root_propagation')]))
        if not r['imports']:details.append((name,'无','0',0,0,0,0))
    table(['程序','原生证明 ID','提交处置','单位传播','冲突','analyze 来源','根传播'],details)
    lines.append('[逐次配对](summary.json) · [完整测量](trials.json) · [学习库复播](lifecycle.json)')
    (e/'measurements.md').write_bytes(('\n'.join(lines)+'\n').encode())
if __name__=='__main__':render(Path(sys.argv[1]))
