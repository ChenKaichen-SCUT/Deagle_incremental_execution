"""Render timing boundaries from individual release receipts; all values are within-mode medians."""
import json,statistics,sys
from pathlib import Path
def report(root):
    raw=json.loads((root/'trials.json').read_bytes())
    groups={(p['case'],p['mode']) for p in raw if p['mode']!='stock'}
    names={'lock01':'读写锁 P0→P1','lock12':'读写锁 P1→P2','fib_updates_8':'八轮 Fibonacci','batch_retained':'batch_retained','ticket56-reviewed':'ticket 5→6'}
    def table(header,fields):
        lines=['| 病例 | 模式 | '+' | '.join(header)+' |','|---|---|'+'---:|'*len(header)]
        for name in names:
            for mode in ('F','G','S','GS'):
                if (name,mode) not in groups:continue
                samples=[p for p in raw if (p['case'],p['mode'])==(name,mode)]
                values=[statistics.median(fn(p,p['sides'][1]) for p in samples) for fn in fields]
                lines.append('| '+names[name]+' | '+mode+' | '+' | '.join(f'{x:,.2f}' for x in values)+' |')
        return '\n'.join(lines)
    def ms(k):return lambda p,r:r['timings'][k]/1e6
    def native(k):return lambda p,r:r['counters'][k]/1e6
    def oc(k):return lambda p,r:r['closure'][k]/1e6
    def model(k):return lambda p,r:r['model_phases_ns'][k]/1e6
    def pair(k):return lambda p,r:p[k]/1e6
    def val(k):return lambda p,r:r['counters'][k]
    timings=table(['到求解桥','源码/GOTO','符号执行','事件约束','CNF与图编码','事件/文字匹配与声明差分','worker 解析','原生提交','纯搜索'],[
        ms('pre_bridge_ns'),model('parse_goto'),model('symbolic_execution'),model('event_constraints'),ms('cnf_graph_ns'),ms('bind_delta_ns'),native('parse_ns'),native('submit_ns'),ms('search_ns')])
    costs=table(['商图维护总计','撤销','恢复/派生','SAT 创建或切换','RUP 审核','旧版应用','两版应用合计','两版含审查','子进程 CPU 秒','worker PSS MiB','worker HWM MiB'],[
        oc('root_prepare_ns'),oc('retract_ns'),oc('derive_ns'),native('init_switch_ns'),native('rup_ns'),
        lambda p,r:p['sides'][0]['timings']['program_ns']/1e6,pair('application_pair_ns'),pair('controller_with_gate_ns'),
        lambda p,r:p['children_user_s']+p['children_system_s'],lambda p,r:r['counters']['resident_Pss_kib']/1024,
        lambda p,r:r['counters']['peak_rss_kib']/1024])
    search=table(['决策','冲突','传播','search start','理论传播','理论冲突','RF 激活','Guard 激活','动态 CO 变量对','纯搜索 CPU 毫秒'],[
        val('decisions'),val('conflicts'),val('propagations'),val('starts'),val('theory_propagations'),val('theory_conflicts'),
        lambda p,r:r['closure']['rf_activations'],lambda p,r:r['closure']['guard_activations'],lambda p,r:r['closure']['dynamic_co_pairs'],ms('search_cpu_ns')])
    text='''# 计时、资源和搜索

每格为同一病例、模式的五轮中位数。时间以毫秒计，另有注明的列使用秒或 MiB。选中目标和所有展开设置在同版四模式及独立 stock 中一致。正式作业在同一台 8 vCPU Linux 主机顺序执行，亲和性 0–7，物理内存约 30 GiB。正式每个模型进程设 200 秒截止时间，各模式使用同一宿主内存环境。论文候选的探索性单次运行另设 60 秒与 4 GiB 上限。机器明细存于 raw 的 host/host.txt。

## 修改后前端和原生提交

到求解桥包括进程启动、完整建模、导出和编码。源码/GOTO、符号执行、事件约束、CNF 与图编码取自原生计时边界。匹配列还包括重新核对冻结证据和写入准入资料。worker 解析接收本版完整有序流。原生提交列包含初始化静态图、原始子句处理和 RUP 审核，所以下表中的细分不宜再与其相加。纯搜索取原生 search 边界。

'''+timings+'''

## 理论、SAT、周期和内存

两版应用合计为两个程序从启动至当前性质输出返回的墙钟之和。两版含审查还包括 worker 管理、当前图的独立 BFS、模型摘要和结果门控。独立 stock 用作事先获得的对照，其单次运行成本单列在 summary.json 内。两版应用的 CPU 包含两个前端与长驻 worker 的 user+system 时间，控制器 CPU 另记在 trials.json。PSS 是第二版求解后 /proc/self/smaps_rollup 的比例驻留集，HWM 是该 worker 截至此时的原生峰值；PSS 与峰值口径各异。驻留保持到版本对结束。

'''+costs+'''

## 搜索计数

search start 包含首次进入搜索，在本组单查询、无动态 CO 重启的记录中，后续搜索启动次数为该列减一。纯搜索 CPU 取原生进程时钟。每个版本、每轮另保留理论 push/pop、子句数、根赋值、学习库退役、实际 CRef 和模型字节哈希。

'''+search+'''

各表不能跨行相减代替配对分析。summary.json 保存每轮 F 减该模式的实际差，含中位数、范围和快于 F 的次数。[配对结果](summary.json) · [原始观测](trials.json)
'''
    (root/'timing.md').write_bytes(text.encode())
if __name__=='__main__':report(Path(sys.argv[1]))
