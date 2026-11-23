"""Render the case-by-case cost ledgers and ablations from the published numerical files."""
import csv
import json
import sys
from pathlib import Path
from statistics import median

CASES=('batch_total','threshold_guard','split_counter','partial_counter','batch_retained','fib_updates',
       'airline_reservations','fib_updates_8','airline_reservations_6')
MODES=('F0','F1','F2','I1','I2','I3')
PAIRS=(('F0','F1'),('F1','F2'),('F2','I1'),('I1','I2'),('I2','I3'),('F1','I3'))

def table(headers,rows):
    return '\n'.join('| '+' | '.join(map(str,line))+' |' for line in [headers,['---']*len(headers),*rows])

def n(value,places=2):
    return '—' if value is None else f'{value:.{places}f}'

def write(path,paragraphs):
    path.write_bytes(('\n\n'.join(paragraphs)+'\n').encode())

def render(dest):
    s=json.loads((dest/'summary.json').read_bytes())
    g={(r['case'],r['mode'],r['detail']):r for r in s['groups']}
    diffs={(r['case'],r['left'],r['right'],r['detail']):r for r in s['contrasts']}
    def val(c,m,k,d=False,stat='median'):
        v=g[c,m,d].get(k)
        return v[stat] if v else None
    def contrast(c,a,b,key='wall_ms',detail=False):
        return diffs[c,a,b,detail][key]['median']
    l={r['case']:r for r in s['ledgers']}
    b={r['case']:r for r in s['bounds']}
    raw=list(csv.DictReader((dest/'ablation-results.csv').open(encoding='utf-8')))
    def cases(rows):
        return [[c,*rows(c)] for c in CASES]
    def ratio(c,m,a,d):
        vals=[100*float(r[a])/float(r['wall_ms']) for r in raw if r['case']==c and r['mode']==m and (r['detail']=='True')==d]
        return n(median(vals),1)
    def ranges(c,m):
        return ' / '.join(n(val(c,m,'wall_ms',False,k),1) for k in ('min','median','max'))
    write(dest/'ablation.md',[
        '# 六种验证模式的受控消融',
        '同一候选、目标性质和展开配置下，每个单元有五次普通运行及五次详细运行。下表为普通候选墙钟中位数，单位为毫秒。模式定义、使用的二进制和校验位置见[计时边界](timing-boundaries.md)。',
        table(['版本对',*MODES],cases(lambda c:[n(val(c,m,'wall_ms'),1) for m in MODES])),
        '## 配对的候选时间差',
        '单位为毫秒，每列先在同病例同重复号中取右侧减左侧，再取五次中位数。例如 F2−F1 为正表示 F2 较慢。第五列含导入后的求解搜索变化。F2 与 I1 的差也包含校验完毕后是否重启完整候选。',
        table(['版本对',*[b0+'−'+a for a,b0 in PAIRS]],cases(lambda c:[n(contrast(c,a,b0),1) for a,b0 in PAIRS])),
        '## 普通运行的波动与旧状态成本',
        '范围为五次最小值 / 中位数 / 最大值。旧程序及完整周期列为各自中位数。周期先在每次运行内相加，包含 P0、实际补丁重放和 P1。历史 AI 时间只在原阶段有可核实记录时另列原始 CSV。',
        table(['版本对','F1 候选范围','I3 候选范围','F1 旧','I3 旧','F1 周期','I3 周期','每次旧状态额外成本¹'],
              cases(lambda c:[ranges(c,'F1'),ranges(c,'I3'),*[n(val(c,m,k),1) for k in ('old_wall_ms','cycle_ms') for m in ('F1','I3')],n(b[c]['extra_warmup_normal_ms'],1)])),
        '¹ 同一增强版相同重复的旧程序时间差中位数。摊销阈值取额外 P0 成本除以单次净节省后向上取整。若候选净节省为零或负值，当前数据没有有限的摊销次数。[逐次结果](ablation-results.csv) · [四分位数、极值及按 1.5 IQR 标记的离群值](summary.json) · [条件上限与摊销阈值](bounds.csv)',
        '## 普通运行的资源',
        'CPU 是 cgroup 全进程 CPU 时间。RSS 是组内采样峰值进程 RSS 之和，PSS 是提交候选前一次读取驻留检查点的比例分摊内存。记账峰值和进程数均为组内采样最大值。内存为 MiB，CPU 为毫秒。',
        table(['版本对','F1 / I3 CPU','F1 / I3 RSS','F1 / I3 cgroup','I3 检查点 PSS','I3 私有页','F1 / I3 峰值进程数'],
              cases(lambda c:[' / '.join(n(val(c,m,k)/scale,1) for m in ('F1','I3')) for k,scale in [('cpu_ms',1),('rss_kib',1024),('cg_kib',1024)]]
                    +[n(val(c,'I3',k)/1024,1) if val(c,'I3',k) is not None else '—' for k in ('checkpoint_pss_kib','checkpoint_private_kib')]
                    +[' / '.join(n(val(c,m,'procs'),0) for m in ('F1','I3'))])),
        '普通与详细计时成对保留。F0 的正式普通组为原始发布二进制，另有五个重点病例在同一带探针 F0 上比较开关各五次。各模式的附加观测影响、极值和离群点可按病例单独查看。[诊断扰动](diagnostic-overhead.json) · [原始 I/O、旧程序 CPU 与采样数](ablation-results.csv)'])
    write(dest/'case-costs.md',[
        '# 九个病例的计算成本与额外开销',
        '## 完整候选与复用覆盖',
        '详细 F1 的中位数。CPU 为进程 CPU 毫秒，其余耗时为墙钟毫秒。求解占比逐次除以该次候选总墙钟再取中位数。SC 包含事件表、RF、PO/APO。编码含 SSA 位级转换及 Closure 图装载。',
        table(['版本对','完整分派 CPU','完整 SC CPU','编码及图','求解','求解占比','命中前缀 CPU','命中 SC 区域 CPU'],
              cases(lambda c:[n(val(c,'F1',k,True),3) for k in ('dispatch_cpu_ms','sc_cpu_ms','encode_ms','solver_ms')]
                    +[ratio(c,'F1','solver_ms',True)+'%',n(val(c,'F1','prefix_cpu_ms',True),3),n(val(c,'F1','region_gen_cpu_ms',True),3)])),
        '下表给出 I3 实际覆盖。事件沿用阶段 7 对共享读写、派生线程和屏障的口径。RF 值与读覆盖分别为 rf-val、rf-some。关系数以本阶段真实输出的完整有符号模型及图为分母。每格为已复用 / 仍执行或生成，最后一列为实际对新求解器生效的历史子句数。',
        table(['版本对','符号分派','事件','PO/APO 边','RF 边','RF 值及读覆盖公式','导入引理'],
              cases(lambda c:[f"{val(c,'I3',x,True):.0f} / {val(c,'I3',y,True):.0f}" for x,y in
                             [('skipped','new_dispatch'),('kept_events','rebuilt_events'),('reused_po','rebuilt_po_apo'),('reused_rf','rebuilt_rf_edges')]]
                    +[f"{val(c,'I3','reused_value',True)+val(c,'I3','reused_cover',True):.0f} / {val(c,'I3','rebuilt_rf_formulas',True):.0f}",n(val(c,'I3','imported',True),0)])),
        '## 候选增量时间账本',
        'I3 减 F1，每列为详细组五个配对差的算术平均，单位毫秒。总差等于九个独占阶段加剩余。理论列包括启动、等待子审核器及原生导入。观测列为候选主进程导出事件方程及 GOTO，前端子进程自己的导出已计在前端。正数为增量增加的时间。',
        table(['版本对','总差','前端','分派','SC','编码及图','求解','恢复','变化','理论','观测','剩余'],
              cases(lambda c:[n(l[c][k+'_ms'],2) for k in ['delta','front','dispatch','sc','encode','solver','restore','change','theory','observer','residual']])),
        '## 检查点、缓存与理论审核',
        'I3 详细组中位数，单位毫秒。fork 属于旧程序。读 IREP、重绑定、符号检查发生在可恢复的候选。外部审核器墙钟覆盖其内部工作。上下文构造、证书及 literal 绑定的独占计时与 Python 启动可以在分相明细复查。',
        table(['版本对','P0 fork','P0 写 IREP','P1 读 IREP','重绑定','符号核对','变化检查','审核器墙钟','证书流程¹','literal 绑定','原生导入'],
              cases(lambda c:[n(val(c,'I3',k,True),3) for k in ('fork_ms','old_irep_write_ms','restore_read_ms','rebind_ms','symbol_check_ms',
                                                                  'change_ms','worker_ms','audit_ms','bind_ms','import_ms')])),
        '¹ 生产接口的 audit_ns 含上下文处理，纯证书函数见 phase-times.csv 的 binder.binding.cert_check。空白表示该路径没有对应观测值。独立微基准对真实 GOTO 镜像和片段执行文件读取、原生解码、编码和写出，同时验证解码后完整结构相等。微基准测量与正式墙钟单列。[维护微基准](maintenance-micro.csv) · [原生及 Python 分项](phase-times.csv)',
        '## Amdahl 条件上限',
        '逐次取详细 F1 的 T，令 S 为匹配前缀及实际命中 SC 区域的原始生成墙钟。无维护、搜索相同且这两项可全部消除时的加速上限为 T/(T−S)。第二个宽松上限 T/(编码及图＋求解) 假定此前和此后的全部工作都可消除。引理改变搜索时，求解差由同输入的 I2/I3 对照另计。',
        table(['版本对','可消除墙钟 ms','占全量','仅当前建模上限','仅保留编码及求解时上限','普通候选净节省 ms','摊销候选数'],
              cases(lambda c:[n(b[c]['measured_targeted_wall_ms'],3),n(b[c]['targeted_share_pct'],3)+'%',n(b[c]['upper_existing_prefix_and_regions'],5)+'×',
                              n(b[c]['upper_if_only_encode_and_solve_remain'],3)+'×',n(b[c]['candidate_saving_normal_ms'],1),b[c]['break_even_uses'] or '无有限值'])),
        '分项中位数通常不能相加。原始 CPU 与墙钟、配对次序、上下文差异和进程采样都可以从归档恢复。[逐次数据](ablation-results.csv) · [独占差账本](case-ledgers.csv) · [上限原数值](bounds.csv)'])

if __name__=='__main__':
    render(Path(sys.argv[1]))
