"""Rebuild the frontend attribution from independent process and compiler observations."""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from statistics import median
from tables import table,n,write

PRIORITY=('batch_total','threshold_guard','fib_updates_8','split_counter','airline_reservations_6')

def report(raw, dest):
    result=json.loads((dest/'frontend.json').read_bytes())
    groups={(v['case'],v['variant']):v for v in result['groups']}
    matched={v['case']:v for v in result['matched']}
    formal=json.loads((dest/'summary.json').read_bytes())['groups']
    formal={(v['case'],v['mode'],v['detail']):v for v in formal}
    rows=list(csv.DictReader((dest/'frontend-results.csv').open(encoding='utf8')))
    def v(c,variant,field):return groups[c,variant][field]['median']
    def vs(c,variant,fields):return [n(v(c,variant,k),2) for k in fields]
    def scale(c):
        rr=[r for r in rows if r['case']==c]
        linked={(r['variant'],r['repeat']):r for r in rr}
        return median(float(linked['recorder',str(i)]['outer_ms'])-float(linked['system-gcc',str(i)]['child_lifetime_ms']) for i in range(1,6))
    counts=Counter()
    for line in (raw/'strace-frontend.txt').open(errors='replace'):
        m=re.match(r'\s*\d+\s+\d+\.\d+\s+([a-z_0-9]+)\(',line)
        if m:counts[m[1]]+=1
    base='batch_total'
    core=v(base,'native-system','front_ms')
    ext=v(base,'recorder','outer_ms')
    write(dest/'frontend-attribution.md',[
        '# 阶段 7 约 214 毫秒的候选前端',
        '五个重点病例各五次、五种前端配置，共 125 次。普通记录器和系统 GCC 使用原阶段 7 增强发布版。原生计时两组共用同一个增强诊断二进制。第五组在原记录器内部计量真实 GCC 子树和文件读取。125 次 GOTO 结构摘要逐一与独立冻结模型核对。pidfd 监视线程记录内核报告退出的时刻，原调用继续用带超时的 wait。两时刻的间隔含线程调度误差。',
        '## 外层、有效进程寿命与退出发现',
        '以下均为五次墙钟中位数，单位毫秒。首轮和后续列来自同一记录器配置。病例按轮换顺序执行，系统文件页缓存保持温热。第一轮属于本次实验的第一次，无法用于估计清空系统缓存后的冷启动。',
        table(['版本对','正式 I3 普通前端','记录器外层','进程实际寿命','wait 退出尾部','Popen 返回','首轮 / 后四次','系统 GCC 外层'],
              [[c,n(formal[c,'I3',False]['frontend_ms']['median'],1),*vs(c,'recorder',['outer_ms','child_lifetime_ms','wait_tail_ms','popen_ms']),
                 n(matched[c]['first_ms'],1)+' / '+n(matched[c]['subsequent_median_ms'],1),n(v(c,'system-gcc','outer_ms'),1)] for c in PRIORITY]),
        '## 子进程内部',
        '原生记录器配置保留原阶段 7 包装脚本。系统 GCC 配置仍构造同一 GOTO 并输出相同用途的文件。真正前端计算用系统 GCC 下的 get_goto_program 表示，包含实际预处理、解析、类型检查、GOTO 构建和内部库建模。总父阶段属于墙钟，专门记录 GCC 子树 CPU 的配置另列。',
        table(['版本对','原生记录器前端','系统 GCC 前端','系统预处理','解析 C','类型检查','goto_convert','GOTO JSON','IREP 写出','记录器增加的原生预处理¹'],
              [[c,n(v(c,'native-recorder','front_ms'),1),*vs(c,'native-system',['front_ms','preprocess_ms','parse_ms','typecheck_ms','goto_convert_ms','goto_json_ms','irep_write_ms']),
                n(matched[c]['recorder_native_cpp_extra_ms']['median'],2)] for c in PRIORITY]),
        '¹ 同病例、同重复、相同诊断二进制，分别在保留包装器及使用系统 GCC 时测量。原生预处理父阶段包括启动、管道处理、解释器、依赖记录等。子阶段不再与父阶段累加。',
        table(['版本对','有源文件的 GCC 调用','这些 GCC 子树墙钟 / CPU','记录器 Python CPU','文件读取 次 / ms','记录器脚本计时外的预处理¹','JSON / IREP KiB'],
              [[c,n(v(c,'timed-recorder','gcc_calls'),0),' / '.join(vs(c,'timed-recorder',['system_gcc_wall_ms','system_gcc_cpu_ms'])),
                n(v(c,'timed-recorder','recorder_cpu_ms'),2),n(v(c,'timed-recorder','dependency_file_reads'),0)+' / '+n(v(c,'timed-recorder','dependency_read_ms'),2),
                n(v(c,'timed-recorder','preprocess_outside_wrapper_ms'),2),' / '.join(vs(c,'timed-recorder',['json_kib','irep_kib']))] for c in PRIORITY]),
        '¹ 包含解释器进入脚本前的启动、启动 GCC 包装器的原生进程和管道、退出等未细分部分。脚本内 CPU 为 Python 自身，GCC 子树 CPU 独立取得。读取耗时为打开并读取被记录文件的合计，哈希、匹配行标记、路径解析及输出另占 Python 时间。',
        '## 重复工作的边界与可消除上限',
        f'{base} 的原记录器外层为 {ext:.1f} ms。去除记录器后的完整原生前端为 {core:.1f} ms，约占原外层的 {100*core/ext:.1f}%。这两个数来自独立配置。普通 F1 也必须做一次 C/GOTO 构建。可恢复的候选将这次工作放在前端子进程，随后从镜像恢复。回退流程会在资格判定后再次启动完整候选，从头进行预处理与 GOTO 构建。',
        '独立的 strace 还观察到两个通过标准输入探测 C 和 C++ 配置的 GCC 调用，分别带有 -E - -o - 和 -E -x c++ - -o - 参数。原记录器对它们直接 exec 系统 GCC，因此三条 cpp.jsonl 文件记录之外还有两次 Python 解释器启动。三份有源文件的输入分别为 harness.c 和两个不同的生成单元。五次调用共同解释了原生 C 预处理计时之外仍有包装器成本。回退时两个前端进程还会再次处理同一程序。',
        '为定位这两个调用的成本，另做 100 次独立对照。相同的极小分派脚本在四种配置下按标准输入或文件选择原记录器，其他调用交给系统 GCC。所有输出 GOTO 都与冻结摘要一致。表中均为配对进程寿命差，单位毫秒，未计入正式性能样本。',
        table(['版本对','仅两个 stdin 走记录器 − 全系统','仅三个文件走记录器 − 全系统','全部走记录器 − 仅文件','全部走记录器 − 全系统'],
              [[c,*[n(result['configuration_controls'][c][k]['median'],2) for k in ('stdin_minus_none','source_minus_none','both_minus_source','both_minus_none')]] for c in PRIORITY]),
        table(['版本对','记录器的进程寿命增量 ms¹','记录器外层减系统 GCC 实际寿命 ms²','F1 原生前端 ms','I3 候选普通墙钟 ms'],
              [[c,n(matched[c]['recorder_lifetime_extra_ms']['median'],1),n(scale(c),1),
                n(formal[c,'F1',True]['ledger_front_ms']['median'],1),n(formal[c,'I3',False]['wall_ms']['median'],1)] for c in PRIORITY]),
        '¹ 配对实测。² 同一重复号的两个独立配置相减，表示完全消除记录器额外寿命与退出发现等待时的乐观工程空间。保留依赖收集会占用其中一部分。对已经完整回退的程序，避免整个预检前端的另一上限是该次前端外层时长，两种上限重叠。这里没有实施前端复用。',
        '独立 strace 运行仅用于确认进程及等待路径。下列次数含 Python、前端和后代，不能当成一次编译器调用的独占时间。',
        table(['系统调用','该次跟踪次数'],[[k,counts[k]] for k in ('execve','clone','vfork','wait4','openat','clock_nanosleep')]),
        '[独立前端原始数据](frontend-results.csv) · [按组分布及配对差](frontend.json) · [控制器及 GCC 探针](../../../scripts/stage8/frontend_probe.py) · [阶段 4 正式前端入口](../../../scripts/stage4/session.py) · [阶段 3 依赖记录器](../../../scripts/stage3/record_gcc.py)'])
if __name__=='__main__':
    report(*map(Path,sys.argv[1:]))
