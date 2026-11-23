"""Render solver input identity, candidate counters and old-program crossover results."""
import csv
import json
import statistics
import sys
from pathlib import Path
from tables import table,n,write

def render(dest):
    solver=json.loads((dest/'solver.json').read_bytes())
    summary=json.loads((dest/'summary.json').read_bytes())
    g={(s['case'],s['mode'],s['detail']):s for s in summary['groups']}
    pairs={(s['case'],s['left'],s['right'],s['detail']):s for s in summary['contrasts']}
    fib='fib_updates_8';air='airline_reservations_6'
    def num(c,m,k,d=True):
        x=g[c,m,d].get(k)
        return x['median'] if x else None
    def dist(x,places=2):
        return ' / '.join(n(x[k],places) for k in ('min','median','max'))
    def seq(s):
        x=s['cnf_and_variables'];v=x['first'];graph=s['graph_and_guard_order'];trace=s.get('early_search')
        rows=[
            ['记录流 SHA-256',*x['sha256']],
            ['记录流字节数',*x['bytes']],
            ['变量分配序列 SHA-256',*x['variable_stream_sha256']],
            ['原生变量分配记录',*[v.get('variable',0) for v in x['counts']]],
            ['向 addClause_ 提交的子句记录',*[v.get('clause',0) for v in x['counts']]],
            ['图、guard 及顺序记录行数',*graph['length']]]
        body=[table(['输入证据','左侧','右侧'],rows)]
        if v:
            body.append(f"从 0 编号，第 {v['record_index_zero_based']} 条输入记录开始不同。左侧为 {v['left']}，右侧为 {v['right']}。MiniSat literal 的低位表示符号，其余位为变量号。")
        else:body.append('两份完整捕获的搜索前输入流逐字节相同。')
        clauses=x['signed_clauses']
        if clauses['first']:
            k=clauses['first']
            body.append(f"单独剥离变量分配后，有 {clauses['different_sequence_positions']} 个子句位置不同。第一个位于 {k['index_zero_based']}（从 0 起），两边的带符号编码分别为 {k['left']} 与 {k['right']}。在两侧按子句内 literal 排序后再比较多重集合，未配对的子句分别有 {clauses['unmatched_clauses_each_side_ignoring_literal_order']} 个。")
        body.append('原始图和 guard 行的顺序'+('相同' if graph['same_order'] else '不同')+'，行的多重集合'+('相同' if graph['same_multiset'] else '不同')+'。'
                    +(f"前 32 个决策及前 16 个冲突的有限轨迹{'一致' if trace['same_order'] else '出现分歧'}。" if trace else '至少一侧未进入可记录的搜索。'))
        if trace and trace['first_index'] is not None:
            body.append(f"记录到的首个搜索差异位于轨迹第 {trace['first_index']} 行（从 0 起），两侧依次为 {trace['example']}。")
        return body
    ctrls=solver['original_old_controls']
    old={x['mode']:x for x in ctrls}
    cross=solver['cross_controls']
    eq=solver['printed_old_equation']
    first=eq['first']
    fibdelta=pairs[fib,'I2','I3',False]
    p=[
        '# Closure 求解时间与历史引理归因',
        '## 八轮 Fibonacci 候选',
        '同一增强二进制、同一冻结候选及待证性质。I2、I3 均先完成快照、证书和带符号 literal 绑定。I2 在审核结束后清空提交计划，I3 调用原有导入接口。按轮交替，每种配置分别有五次普通与五次详细结果。',
        table(['模式','普通求解 min / median / max (ms)','详细编码及图 ms','详细 SSA/CNF ms','图原生装载 ms','变量 / 子句','图边 / guard','审核通过 / 实导'],
              [[m,dist(g[fib,m,False]['solver_ms']),n(num(fib,m,'encode_ms')),n(num(fib,m,'ssa_cnf_ms')),n(num(fib,m,'graph_load_ms')),
                n(num(fib,m,'model_variables'),0)+' / '+n(num(fib,m,'model_clauses'),0),n(num(fib,m,'graph_edges'),0)+' / '+n(num(fib,m,'graph_guards'),0),
                n(num(fib,m,'accepted'),0)+' / '+n(num(fib,m,'imported'),0)] for m in ('F1','I1','I2','I3')]),
        table(['模式','决策','冲突','传播','理论传播','理论环','重启','搜索 CPU ms'],
              [[m,*[n(num(fib,m,k),0) for k in ('decisions','conflicts','propagations','theory_propagations','theory_cycles','restarts')],n(num(fib,m,'search_cpu_ms'),1)] for m in ('F1','I2','I3')]),
        f"普通组 I3−I2 的配对求解差为 {dist(fibdelta['solver_ms'],1)} ms（最小 / 中位 / 最大）。其候选端到端差为 {dist(fibdelta['wall_ms'],1)} ms。I3 详细组候选审核器墙钟 {num(fib,'I3','worker_ms'):.2f} ms，生产接口 audit_ns 为 {num(fib,'I3','audit_ms'):.2f} ms，literal 绑定为 {num(fib,'I3','bind_ms'):.3f} ms，原生导入为 {num(fib,'I3','import_ms'):.3f} ms。审核器墙钟包含内部计算和进程启动，几个数不能相加。",
        '以下左侧为 I2，右侧为 I3。捕获在第一次求解前结束，随后才调用已审计的引理提交回调。',
        *seq(solver['fibonacci_preimport']),
        'I2/I3 的基础输入可通过完整流、图和 target 独立复核。对这个候选，可以将稳定的搜索计数变化归于引理提交所引起的搜索轨迹变化。有效传播和启发式改变分别贡献了多少时间仍然无法识别。其他病例特别是没有命中引理的病例不据此外推。[候选明细](ablation-results.csv) · [输入及搜索轨迹比较](solver.json)',
        '## 六线程订票旧程序',
        '三组各独立运行五次，使用两个经过 SHA-256 复核的阶段 7 发布二进制。增强版两组均关闭跨版本缓存，第三组开启观察输出。以下均为求解器内部时间。每次均重新找到冻结目标性质的错误。',
        table(['发布配置','求解 min / median / max (ms)','变量 / 子句','决策','冲突','传播','理论传播','反例步数'],
              [[r['mode'],dist(r['solver_ms'],1),n(r['model_variables']['median'],0)+' / '+n(r['model_clauses']['median'],0),
                *[n(r[k]['median'],0) for k in ('decisions','conflicts','propagations','theory_propagations','trace_steps')]] for r in ctrls]),
        f"原始版减增强普通版的两组中位数之差为 {old['baseline']['solver_ms']['median']-old['development']['solver_ms']['median']:.1f} ms，增强观察版减增强普通版为 {old['development-observed']['solver_ms']['median']-old['development']['solver_ms']['median']:.1f} ms。",
        '以下左侧为原始诊断构建，右侧为增强诊断构建。变量分配记录包含分配号、初始极性和决策资格。相同的分配记录尚不能建立 C 对象到 SAT 变量的语义一一对应。实际有符号子句序列可以直接逐项比较。',
        *seq(solver['old_inputs']),
        f"原生打印的旧方程两侧分别有 {eq['blocks'][0]}、{eq['blocks'][1]} 个步骤，{eq['different_positions']} 个位置不同。整行块多重集合{'相同' if eq['row_multiset_identical'] else '不同'}。",
        ('第一个不同块在位置 '+str(first['position_zero_based'])+'，两段原始输出如下。\n\n```text\n'+first['original']+'\n---\n'+first['enhanced']+'\n```') if first else '两份打印方程的逐块次序也相同。',
        '两个固定原生版本的 symex_start_thread.cpp 具有相同 Git blob。它先遍历当前 L2 名称复制子线程栈帧的局部对象，再遍历符号表初始化线程局部对象。上例的首处分歧在栈帧复制。完整候选方程通过了带读写依赖检查的逐块比对。没有做只置换某一组初始化的对照，因而无法把所有搜索差异精确归到单一 SSA 行或首个不同子句。[源码指纹](native/native-provenance.json) · [完整候选证据](structural-checks.json)',
        '## 保持输入不变，交换求解核心',
        '单独捕获变量分配、带符号子句、图插入位置、显式极性和 assumptions。将原始与增强输入各自在两种真实 Closure 内核中重放五次。完整性判据同时检查 SAT、求解前根层状态与参数、输入序列摘要、图、前缀搜索轨迹及最终搜索计数。计时范围是独立驱动的 solveLimited 调用。']
    if cross:
        p.append(table(['捕获输入','求解核心','精确重现次数 / 5','求解 min / median / max (ms)','决策','冲突','传播'],
                       [[r['input'],r['solver'],r['matching_searches'],dist(r['solver_ms'],1),*[n(r[k]['median'],0) for k in ('decisions','conflicts','propagations')]] for r in cross]))
        if all(r['matching_searches']==5 for r in cross):
            q={(r['input'],r['solver']):r['solver_ms']['median'] for r in cross}
            p.append(f"20/20 次通过全部字节及计数检查。在原始核中仅交换输入相差 {q['baseline','baseline']-q['enhanced','baseline']:.1f} ms，在增强核中相差 {q['baseline','enhanced']-q['enhanced','enhanced']:.1f} ms。同一原始输入换核相差 {q['baseline','enhanced']-q['baseline','baseline']:+.1f} ms，同一增强输入换核相差 {q['enhanced','enhanced']-q['enhanced','baseline']:+.1f} ms。输入能够重现搜索轨迹的变化，剩余墙钟波动没有逐项归属。")
        else:p.append('有重放未通过完整性判据。归因只使用通过的检查项，不能从不匹配的重放估计内核与输入各自的贡献。')
    else:p.append('此处没有可核对的交换输入运行。无法拆出内核与输入各自的贡献。')
    p.extend(['两种实现来自同一固定的 Deagle/MiniSat 2.2.1 源系。记录了原生提交、补丁、构建配置 SHA 和实际可执行文件 SHA。编译产物不同，不能仅凭版本号排除二进制影响。上述旧程序差异独立于跨版本复用。同一输入上的时间差仍含机器状态、缓存和构建布局等因素。',
        '后续若继续排查最早编码差异，可按 SSA 行记录对应的首次 CNF 变量用途及首个变化子句，再只置换经证明独立的初始化次序做交叉重放。当前冻结结论只使用已捕获的完整输入与实际搜索。',
        '[原始发布版 15 次分次记录](old-search.csv) · [二进制锁](native-build.json) · [诊断源代码](../../../scripts/stage8/instrument.py) · [求解器交叉重放](../../../scripts/stage8/replay.py)'])
    write(dest/'solver-attribution.md',p)
if __name__=='__main__':
    render(Path(sys.argv[1]))
