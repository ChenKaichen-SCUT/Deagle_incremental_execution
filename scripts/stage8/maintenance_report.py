"""Detail required validation work, implementation costs and controller/resource boundaries."""
import csv
import json
import sys
from pathlib import Path
from statistics import median
from tables import CASES,table,n,write

def render(dest):
    def rows(name):
        with (dest/name).open(encoding='utf8') as f:return list(csv.DictReader(f))
    p=rows('phase-times.csv')
    profile={(r['case'],int(r['rep']),r['operation']):r for r in p if r['mode']=='I3' and r['detail']=='True'}
    full=rows('ablation-results.csv')
    rr={(r['case'],int(r['rep'])):r for r in full if r['mode']=='I3' and r['detail']=='True'}
    micro={(x['case'],int(x['repeat'])):x for x in rows('maintenance-micro.csv')}
    def total(c,names,field='exclusive_wall_ms'):
        return median(sum(float(profile.get((c,i,s),{}).get(field) or 0) for s in names) for i in range(1,6))
    def v(c,field):
        vals=[float(rr[c,i][field]) for i in range(1,6) if rr[c,i].get(field)]
        return median(vals) if vals else None
    def from_micro(c,field):
        xs=[float(micro[c,i][field]) for i in range(1,6) if micro[c,i].get(field)]
        return n(median(xs),3) if xs else '—'
    def b(c,what):return n(total(c,['binder.binding.'+what]),3)
    def fmtb(c,field):return n(v(c,field),3)
    write(dest/'maintenance.md',[
        '# 检查点、证书与控制器维护成本',
        '下表均为五次独立运行的中位数。除特别标注外单位为毫秒。原生文件、函数计时和实际求解调用构成直接测量，可信度高。跨函数取差得到的剩余只定位到一个时间边界。',
        '## 旧反例与候选引理',
        'I3 详细运行。旧快照列为生产接口的 fingerprint_ns，含规范化和指纹。旧证书构造为旧进程之后 Python derive 的独占墙钟。候选侧各函数的计时为审核器子进程内的独占墙钟。审核器之外的原生快照和审核器进程寿命分开。未调用的子函数记录为 0。',
        table(['版本对','旧冲突记录¹','旧快照','旧证书构造','原生准备减审核器²','审核器墙钟','候选上下文构造','候选证书核对','候选绑定','子进程内 JSON 读写','子进程内哈希'],
              [[c,n(total(c,['old.conflict_record'],'wall_ms'),3),fmtb(c,'old_snapshot_ms'),n(total(c,['controller.old.derive']),3),
                n(total(c,['candidate.lemma_prepare'],'wall_ms')-total(c,['candidate.lemma_worker'],'wall_ms'),3),fmtb(c,'worker_ms'),
                b(c,'context_build'),b(c,'cert_check'),b(c,'literal_bind'),n(total(c,['binder.binding.json_read','binder.binding.json_write']),3),b(c,'hash')] for c in CASES]),
        '¹ 冲突生成及搜索本身在旧求解器内。此列只计载明冲突的原生记录工作。² 两项中位数之差，包含快照采集、写出、读回计划及接口剩余，纯图计算无法单独分离。完整的候选计时还包含候选侧导入与后续搜索。[生产接口](../../../incdeagle/theory/cache.py) · [纯证书检查](../../../incdeagle/theory/certificate.py)',
        '## 变化分析与控制器',
        '独立微基准重跑阶段 7 相同的变化分析并逐字典断言结果一致。只把可分离的真正 diff、GOTO 索引、映射与同步扫描列在前五列。后面三列从正式 I3 控制器独占计时取得，覆盖已经挂钩的函数。',
        table(['版本对','源码 diff','源码/GOTO 索引','GOTO JSON 读','对应关系','同步资格','候选复制','候选哈希','候选 manifest'],
              [[c,*[from_micro(c,'diff_'+x+'_exclusive_ms') for x in ('source_diff','source_and_goto_index','decode_goto_json','map_correspondence','sync_and_eligibility')],
                *[n(total(c,['controller.candidate.'+x]),3) for x in ('copyfile','file_sha','manifest')]] for c in CASES]),
        '原生 rebind 还会检查符号、GOTO、指针、线程和 guard 的前置条件。其总时间和前缀符号扫描在[病例账本](case-costs.md)。原生代码没有将每次哈希查询和每次 guard 比较单独计时，因此无法继续分摊这部分。',
        '## 二进制 IREP 文件',
        '独立真实文件往返，按读文件 / 解码 / 编码 / 写文件给出墙钟毫秒。解码、编码调用项目实际 irep_serializationt 并校验完整恢复结果。实际更新使用的片段和镜像是两个文件。写返回指 OS 已接收数据，未要求 fsync。',
        table(['版本对','镜像 KiB','镜像 读 / 解 / 编 / 写','片段 KiB','片段 读 / 解 / 编 / 写'],
              [[c,n(v(c,'goto_image_bytes')/1024,1),' / '.join(from_micro(c,'image_'+x+'_ms') for x in ('read_file','decode','encode','write_file')),
                n(v(c,'fragment_bytes')/1024,1) if v(c,'fragment_bytes') is not None else '—',' / '.join(from_micro(c,'cache_'+x+'_ms') for x in ('read_file','decode','encode','write_file'))] for c in CASES]),
        '## 进程、等待与驻留内存',
        '每个正式服务完整保存 fork 墙钟、Popen 创建/返回、各次 wait 的开始/返回、原生进程 PID、cgroup CPU 和 I/O 计数。wait 包含子进程运行，在前端和理论审核器以外没有统一的 pidfd 退出探针，所以其余 wait 无法拆成纯 IPC 与系统调度。保留检查点在候选提交前读取 smaps_rollup，私有页及 PSS 见[资源表](ablation.md)。',
        table(['版本对','P0 采集后候选前端 ms','P1 变化检查 ms','P1 读取两种缓存 ms','P0 实际块设备读 / 写 KiB','P1 实际块设备读 / 写 KiB'],
              [[c,n(v(c,'frontend_ms'),1),n(v(c,'change_ms'),2),n(v(c,'restore_read_ms'),3),
                ' / '.join(n(v(c,'old_'+x+'_bytes')/1024,1) for x in ('read','write')),
                ' / '.join(n(v(c,x+'_bytes')/1024,1) for x in ('read','write'))] for c in CASES]),
        'cgroup io.stat 是块设备记账，页缓存命中不会形成等量块读取。逻辑文件大小与磁盘流量口径不同。各阶段 PSS、进程和 I/O 的时序样本与原始会话一同归档。[逐相包含与独占计时](phase-times.csv) · [微基准样本及 CPU](maintenance-micro.csv) · [正式墙钟及内存](ablation-results.csv)'])
if __name__=='__main__':
    render(Path(sys.argv[1]))
