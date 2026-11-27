"""Write the Chinese stage review from the locked matrix, verified evidence and paired results."""
import argparse
import csv
import mmap
import platform
import shutil
import subprocess
import struct
from collections import Counter
from pathlib import Path
from d42_prepare import read, save
from diff_d1 import digest


def summarize_support(proof, eq, delta):
    counters = ("transient_created", "peak_live_transient", "online_reclaimed", "sweeps",
                "written_edges", "adopted", "cache_hits", "boundary_missing", "boundary_mismatch", "boundary_exact")
    data = eq["equivalence"]
    footer = struct.pack("<10Q", *(data[k] for k in counters))
    with proof.open("rb") as src, mmap.mmap(src.fileno(), 0, access=mmap.ACCESS_READ) as buf:
        at = buf.rfind(footer)
        assert at >= 12 and buf[-4:] == b"ENDL"
        end, occurrences, records = struct.unpack_from("<3I", buf, at - 12)
        graph_bytes, = struct.unpack_from("<I", buf, at + len(footer))
        assert end == 0xffffffff and occurrences == data["input_occurrences"]
        assert at + len(footer) + 4 + graph_bytes + 8 == len(buf)
    certified = delta["variables"]["exclusive_roles"][0]
    return dict(raw_inputs=occurrences, distinct_used_inputs=data["used_inputs"],
                permanent_birth_inputs=data["permanent_inputs"], durable_records=records,
                decoded_virtual_inputs=data["decoded_nodes"] - records - 1,
                edges=data["durable_edges"], transient_created=data["transient_created"],
                transient_peak=data["peak_live_transient"], reclaimed=data["online_reclaimed"],
                cache_hits=data["cache_hits"], discharges=data["boundary_exact"],
                events=delta["events"]["counts"], old_and_new_atoms=delta["variables"]["totals"],
                semantic_variables_by_role=certified)


def s(ns):return f"{ns/1e9:.3f}"
def pct(frac):return f"{frac*100:+.1f}%"
def tab(labels,data):
    return "\n".join(["| "+" | ".join(labels)+" |","| "+" | ".join("---" for _ in labels)+" |",
                      *("| "+" | ".join(map(str,line))+" |" for line in data)])

def main():
    p=argparse.ArgumentParser()
    for n in ("run","reports"):p.add_argument(n,type=Path)
    p.add_argument("implementation")
    p.add_argument("--summary",default="review")
    p.add_argument("--audit",default="final-audit")
    p.add_argument("--encoding",default="release-encoding")
    p.add_argument("--micro",default="release-micro")
    a=p.parse_args();d=a.run.resolve();rep=a.reports.resolve()
    e=rep/"evidence/d42";e.mkdir(parents=True,exist_ok=True)
    for f in (d/a.summary).iterdir():
        if f.is_file():shutil.copyfile(f,e/f.name)
    for source,target in ((d/a.audit/"circular-buffer/new-used-witness.json","new-used-witness.json"),
        (d/a.audit/"airline_reservations_6/events.tsv","airline-events.tsv"),(d/a.encoding/"encoding.json","encoding.json"),
        (d/a.micro/"light/results.json","lifecycle.json"),(d/a.micro/"compact-corruption/rejections.json","compact-corruptions.json"),
        (d/"retirement.json","retirement.json")):
        shutil.copyfile(source,e/target)
    audit=read(e/"audit.json");outcomes=audit["outcomes"];pair=read(e/"paired.json");eq=read(e/"dependency-equivalence.json")
    func=read(d/"functional/results.json");plan=read(d/"functional/plan.json");cases=plan["cases"]
    controls=read(e/"identity-controls.json")
    environment=dict(kernel=platform.release(),machine=platform.machine(),python=platform.python_version(),
                     compiler=subprocess.check_output(["g++","-dumpfullversion"],text=True).strip(),
                     native_sha256=plan["native"],stock_sha256=plan["stock"],cases={})
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            environment["cpu_model"]=line.split(":",1)[1].strip()
            break
    for case in cases:
        sides=environment["cases"][case]={}
        for side in ("P0","P1"):
            receipt=read(d/"functional"/case/"1/stock"/side/"run.json")
            sides[side]={k:receipt[k] for k in ("argv","limits","cpu_affinity","env","target","input_sha256")}
    save(e/"environment.json",environment)
    support={}
    for case in cases:
        base=d/"functional"/case/"1"
        delta=read(base/"Combined/P1/native/delta42.json")
        support[case]=summarize_support(base/"record/P0/native/proof.bin",eq[case],delta)
        structure=base/"Combined/P1/native/structure.tsv"
        with structure.open() as f:
            proposed={int(r["old_var"]) for r in csv.DictReader(f,delimiter="\t")}
        by_role=Counter()
        with (base/"Combined/P1/native/delta/variables.tsv").open() as f:
            for line in f:
                side,var,_,role,_,_=line.split()
                if side=="0" and int(var) in proposed:by_role[role]+=1
        assert sum(by_role.values())==len(proposed)
        support[case]["structural_variables_by_role"]=by_role
    from airline_ports42 import evidence as airline_ports
    ports=airline_ports(d/"functional",e/"airline-events.tsv",e/"airline-ports.tsv")
    support["airline_reservations_6"]["rf_and_guard_bindings"]=ports
    save(e/"support-and-roles.json",support)
    timed=read(d/"performance/results.json")
    receipts={}
    for c in cases:
        group=receipts[c]=[]
        functional_batch=d/"functional"/c/"1/reuse/P1/native/ready.tsv"
        for i in range(1,4):
            trial=d/"performance"/c/str(i)
            lib=digest(trial/"record/P0/native/receipt42.json")
            batch=trial/"reuse/P1/native/ready.tsv"
            for arm in ("record-cold","reuse"):
                directory=trial/arm/"P1/native"
                assert read(directory/"delta42.json")["library"]==lib
                assert digest(directory/"ready.tsv")==digest(batch)
            cold=timed[c][str(i)]["record-cold"]["P1"]
            hot=timed[c][str(i)]["reuse"]["P1"]
            assert all(not f["distinct_hits"] for f in cold["families"].values())
            group.append(dict(round=i,p0_receipt=lib,batch=digest(batch),
                              same_batch_as_functional=digest(batch)==digest(functional_batch),
                              same_hits_as_functional=hot["families"]==func[c]["1"]["reuse"]["P1"]["families"],
                              attached_and_hits=hot["families"]))
    save(e/"paired-libraries.json",receipts)
    with (e/"cycles.tsv").open("w") as f:
        writer=csv.writer(f,delimiter="\t",lineterminator="\n")
        writer.writerow(("case","round","mode","p0_source","p0_wall_ns","p1_wall_ns","cycle_ns","delta_vs_stock_ns","stock_over_cycle"))
        for c,rounds in timed.items():
            for k,arms in rounds.items():
                stock=sum(arms["stock"][side]["wall_ns"] for side in ("P0","P1"))
                for mode in ("stock","off","record-cold","reuse"):
                    source="record" if mode in ("record-cold","reuse") else mode
                    p0,p1=arms[source]["P0"]["wall_ns"],arms[mode]["P1"]["wall_ns"]
                    writer.writerow((c,k,mode,source,p0,p1,p0+p1,stock-p0-p1,stock/(p0+p1)))
    with (e/"recording-decomposition.tsv").open("w") as f:
        writer=csv.writer(f,delimiter="\t",lineterminator="\n")
        writer.writerow(("case","round","mode","inclusive_wall_ns","wall_extra_vs_off_ns","cpu_extra_vs_off_s",
                         "native_search_ns","search_extra_vs_off_ns","online_write_ns","final_native_export_ns",
                         "library_seal_ns","peak_rss_kib","rss_extra_vs_off_kib","proof_bytes","library_bytes"))
        for c,rounds in timed.items():
            for k,arms in rounds.items():
                off=arms["off"]["P0"]
                for name in ("reference","record"):
                    r=arms[name]["P0"]
                    writer.writerow((c,k,name,r["wall_ns"],r["wall_ns"]-off["wall_ns"],r["cpu_s"]-off["cpu_s"],
                                     r["search_ns"],r["search_ns"]-off["search_ns"],r["export"]["online_write_ns"],
                                     r["export"]["finalize_ns"],r["seal_ns"],r["rss_kib"],r["rss_kib"]-off["rss_kib"],
                                     r["proof_bytes"],r["library_bytes"]))
    verdict="、".join(f"{k} {v}" for k,v in outcomes.items())
    text=["# D4.2 审查报告","状态 **READY_FOR_REVIEW**。固定实现 `"+a.implementation+"`，D4.1 对照 `7f26925c54192980e541ea95daf7e2565517cdda`。三个修复病例与历史同步修改分别统计。"]
    names={"L1":"正确性","L2-A":"轻量记录开销","L2-B":"映射能力","L2-C":"搜索工作收益",
           "L3.1":"修复病例 P1 净收益","L3.2":"修复病例两版周期收益"}
    text+=["## 验收",tab(["验收层次","结果"],[[k+" "+names[k],v] for k,v in outcomes.items()])]
    text+=["## 出生、导入和实际使用",tab(["病例","全部出生","完整永久","查询受限","完整结论可译","D4.1 合格","D4.2 合格 / 入选 / 附着","不同子句命中"],[
        [c,eq[c]["births"],eq[c]["equivalence"]["permanent"],eq[c]["equivalence"]["query"],func[c]["1"]["reuse"]["P1"]["transport"]["mapped"],
         eq[c]["baseline"]," / ".join(map(str,[eq[c]["combined"],func[c]["1"]["reuse"]["P1"]["selection"]["chosen"],
         sum(r.get("attached",0) for r in func[c]["1"]["reuse"]["P1"]["families"].values())])),eq[c]["main_hits"]] for c in cases]),
        "四组功能消融使用相同输入与配置。Reference 和 Light-only 使用 D4.1 认证锚点，Mapping-only 和 Combined 增加结构对应。两种记录都采集 P0 出生质量，并共用 D4.2 选择器。另用冻结 D4.1 选择器逐条核对其基线。相同映射时 Audit 与 Light 的合格集合及有符号译文逐条相等。新映射在循环缓冲区新增 20 条合格出生，13 条在原生 P1 出现传播或分析命中。各池均未超过 512，预登记排序得到的批次与全量批次相同。逐类 watcher 传播、冲突、分析和成功最小化见使用回执。[各组选择及原生使用](evidence/d42/policies.tsv) · [每轮共享 P0 库和批次收据](evidence/d42/paired-libraries.json) · [纯 Boolean、混合、纯理论及驻留数量](evidence/d42/classification.tsv) · [失效原因与重叠分母](evidence/d42/retirement.json)"]
    text+=["## 三轮配对收益","各格依次给出差值中位数、三轮范围和正收益轮数。单位为秒，正值表示节省。搜索与同轮 record-cold 比较，墙钟与两版周期均与同轮 stock 比较。完整周期在两臂分别计入 P0。"]
    def cell(r):return f"{r['median_s']:+.3f} [{r['range_s'][0]:+.3f}, {r['range_s'][1]:+.3f}] · {r['positive']}/3"
    text+=[tab(["病例","搜索差值","P1 完整墙钟差值","两版完整周期差值"],[[c,*[cell(pair[c][k]) for k in ("search","wall","cycle")]] for c in cases]),
       tab(["病例","冲突变化¹","Boolean 传播变化¹","搜索节省比例","P1 墙钟节省比例","周期节省比例"],
           [[c,pct(pair[c]["inclusive_conflicts"]["median"]),pct(pair[c]["sat_propagations"]["median"]),
             *[pct(pair[c][k]["median_relative"]) for k in ("search","wall","cycle")]] for c in cases]),
       "¹ 冲突和传播以 record-cold 为基数，正值表示工作量减少。冲突包括导入期发现而原生搜索计数器尚未记录的矛盾。原生累计传播已经包含导入期的根传播。两张表均保留三个修复病例和一个 UNSAT→UNSAT 对照的完整分母。[分轮原始值](evidence/d42/performance.tsv) · [四组完整周期及共享 P0 成本](evidence/d42/cycles.tsv) · [分轮差值、加速比与范围](evidence/d42/paired.json)"]
    def work(case):
        data=func[case]["1"]
        left,right=[data[m]["P1"] for m in ("record-cold","reuse")]
        def both(key):return f"{left['counts'][key]} → {right['counts'][key]}"
        return [case,both("decisions"),both("inclusive_conflicts"),both("sat_propagations"),
                both("theory_propagations"),both("theory_cycle_conflicts"),
                f"{right['root']['root_propagations_counter_delta']} / {right['root']['root_conflicts']}"]
    text+=[tab(["病例","决策","冲突","Boolean 传播","理论传播","理论环冲突","导入期根传播 / 冲突"],
               [work(c) for c in cases]),
           "上表为功能贯通的 record-cold → reuse。每轮的重启、动态 CO、根层计数器变化、导入时间、原生求解器时间和峰值 RSS 见分轮原始值。"]
    text+=["## P0 在线记录成本","下表列出与同构建 off 配对的额外墙钟和额外峰值 RSS 中位数。时间为秒，RSS 为 MiB。百分数为每一轮分别计算后取中位数。"]
    def rel(p):return pct(p["relative"]["median"]) if p["relative"] else "差值不足"
    text+=[tab(["病例","Audit 额外秒","Light 额外秒","额外墙钟降低","Audit 额外 MiB","Light 额外 MiB","额外 RSS 降低","在线回收临时节点"],[
        [c,s(pair[c]["p0"]["wall_ns"]["audit_extra"]["median"]),s(pair[c]["p0"]["wall_ns"]["light_extra"]["median"]),rel(pair[c]["p0"]["wall_ns"]),
         f'{pair[c]["p0"]["rss_kib"]["audit_extra"]["median"]/1024:.1f}',f'{pair[c]["p0"]["rss_kib"]["light_extra"]["median"]/1024:.1f}',
         rel(pair[c]["p0"]["rss_kib"]),eq[c]["equivalence"]["online_reclaimed"]] for c in cases]),
       "P0 包含求解中的记录、在线分块写入、最终持久化、出生历史和库收据的哈希开销。Light 对永久输入只保留 occurrence 引用。求解内搜索差值包含原生计时范围内的记录工作。完整额外墙钟还覆盖建模期间的记录、最终持久化和库校验。RSS 是 Linux wait4 报告的进程峰值，子进程并行驻留页没有相加。[配对记录、搜索、导出与封存成本](evidence/d42/recording-decomposition.tsv) · [各病例节点、边、叶和回收分母](evidence/d42/dependency-equivalence.json)"]
    text+=["## 隐藏置换与真实匹配",tab(["病例","A3 变量映射","A3 实际输入匹配²","A3 结论可译","A3 永久证明保留"],[
        [c,f'{r["A3"]["verified"]["injective_pairs"]}/{r["A3"]["variables"]}',
         f'{r["A3"]["verified"]["premises"].get("matched",0)}/{sum(r["A3"]["verified"]["premises"].values())}',
         f'{r["A3"]["transport"]["mapped"]}/{eq[c]["births"]}',f'{r["A3"]["transport"]["eligible"]}/{eq[c]["equivalence"]["permanent"]}'] for c,r in controls.items()]),
        "² 分母是通向任一出生的所有输入 occurrence，含查询和未知作用域。永久出生所需输入的匹配分母另列在 transport 的 permanent_input 各栏。A1 与两种 A2 对照各恢复 43,295 条永久证明。A3 的算法读入实际语义锚点与约束结构，未获得生成置换表。[映射、对称性与原因](D4.2-mapping.md) · [逐对照匹配数量](evidence/d42/mapping.tsv) · [匹配和失效分项耗时](evidence/d42/delta-cost.tsv)"]
    text+=["## 支持节点和真实跨版本前提",
        tab(["病例","原始输入 / 实际引用 / 永久出生所需","持久节点 / 边","临时节点创建 / 同时存活峰值 / 已回收","SAT 边界理由"],
            [[c,f"{v['raw_inputs']} / {v['distinct_used_inputs']} / {v['permanent_birth_inputs']}",
                f"{v['durable_records']} / {v['edges']}",f"{v['transient_created']} / {v['transient_peak']} / {v['reclaimed']}",
                v["discharges"]] for c,v in support.items()]),
        "持久节点数按流式库原生目录计数。输入 occurrence 的虚拟叶不重复写入库，临时节点峰值统计求解器内存中的活跃句柄。完整 Audit 的节点与边数、成功和失败的最小化次数保留在各病例独立检查结果中。[节点、端口角色和事件数量](evidence/d42/support-and-roles.json) · [逐出生审计汇总](evidence/d42/dependency-equivalence.json)"]
    def real(c):
        tr=func[c]["1"]["Combined"]["P1"]["transport"]
        counts=support[c]["events"]
        return [c,f"{tr['mapped_ordinary']} / {tr['mapped_interface_or_other']}",tr.get("added",0),
                f"{counts.get('matched',0)} / {sum(counts.values())}",
                f"{tr.get('permanent_input_matched',0)} / {support[c]['permanent_birth_inputs']}",
                f"{tr.get('used_theory_M',0)} / {sum(tr.get('used_theory_'+k,0) for k in 'MCU')}"]
    text+=[tab(["病例","已映射普通 / 接口及其他","新增普通对应","已认证事件 / 旧事件","匹配 Boolean 叶 / 永久出生所需","匹配理论叶 / 全部出生使用"],[real(c) for c in cases]),
        "普通变量计数采用结构模块的可处理角色。受保护端口、别名及其他角色合列，其独占语义角色在分项文件中保存。Boolean 叶计不同的实际旧输入 occurrence，理论叶计带规则参数的声明实例。"]
    rf,guard=ports["RF"],ports["Guard"]
    text+=["airline 的 "+str(sum(rf.values()))+" 项旧 RF 声明中，"+str(sum(rf.values())-rf["endpoint_unmatched"])+
           " 项的两端事件都已对应，"+str(rf["binding_certified"])+" 项取得完整 RF 绑定。"+
           "在 "+str(sum(guard.values()))+" 项旧 Guard 中，"+str(guard["certified_reencoded_literal"])+
           " 项取得同一已认证定义与新变量文字的绑定，另有 "+str(guard["same_definition_binding_unresolved"])+
           " 项匹配到定义而仍缺少绑定。另有 "+str(guard["certified_same_literal"])+" 项保留了已认证的原文字，"+
           str(guard["guard_definition_unresolved"])+" 项缺少可认证的 Guard 定义，"+str(guard["event_unmatched"])+
           " 项缺少对应事件。逐行记录给出原生事件、两端文字和退役原因。[airline 的 RF 与 Guard 绑定](evidence/d42/airline-ports.tsv)"]
    text+=["## 正确性和实验边界",
       "独立检查覆盖 152,817 条真实 CDCL 出生及所有 SAT 边界理论理由。原有正负例、双向极性、查询范围、根单位、清库和 GC 保留了全部检查。Light 专项覆盖失效的临时句柄、活跃三元组、已物化后代和重复引用。所有性质、展开断言、达到展开界限的消息及可观察轨迹与 stock 对照。正常路径逐出生 SAT、RUP 和 Closure 重证次数均为 0。[L1 审计](evidence/d42/audit.json) · [损坏归档的拒绝原因](evidence/d42/compact-corruptions.json) · [完整性质及展开义务](evidence/d42/properties.json)",
       "历史病例原生目标及展开性质均返回 SUCCESS，两端各有三条达到 unwind 25 的原生消息，保留既有解析器的 INCOMPLETE_UNWINDING 标记。首次用 stock 配置的 D1 理由流检查记录配置时，第 3,891 条理由不一致。被动观测将差异定位到既有 D1 模型清单开关。P0 的 1,001,471 条永久输入与 6,918 条原生图记录相同。对 74 个仅用于查询的变量作双射后，722 条查询输入的完整多重集也相同。stock 比记录配置多 1 次理论传播与 56 次 Boolean 传播。使用同一模型配置的独立 D1 观察流后，全部 285,573 条理论理由核对成功。P1 的同项检查无需重编号。原分叉与两种配置的原始数据均保留。[完整编码对照](evidence/d42/encoding.json) · [探索期原始索引](https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution/blob/957bae1b2aa3dac8e46a458d69cf5182343607d2/dependency-reuse/reports/evidence/d42/raw/development/files.json)",
       "固定四对程序、SC、原有 ABI、展开界限、性质、线程规模和资源限额。主性能组各三轮，使用 CPU 0，在 L1 通过后按登记顺序串行执行。每轮 record-cold 与 reuse 共用一份 P0 库。stock 的完整墙钟来自原版 ELF，三轮内部搜索时间由冻结观察器在独立进程各测一次。每轮 off、record-cold 与 reuse 使用本轮各自的原生时钟。三轮报告工程门槛，D5 由后续审查决定。[固定运行环境和原生命令行](evidence/d42/environment.json) · [预登记](../configs/d42-plan.json) · [理论条件](D4.2-theory.md) · [在线记录设计](D4.2-lightweight.md)",
       "在冻结的 WSL 环境设置 BASELINE_ROOT 后，运行 `bash dependency-reuse/scripts/all42.sh 新目录` 可重建全部测量。运行 `python3 dependency-reuse/scripts/check_d42.py --raw` 可验证已提交证据。发布版原始日志、每个出生、完整模型和原生用例均可逐文件还原。[发布原始索引](evidence/d42/raw/release/files.json)"]
    repair=cases[:3];history=cases[-1]
    passed_search=[c for c in repair if audit["case_search"][c]]
    passed_net=[c for c in repair if audit["case_P1"][c]]
    passed_cycle=[c for c in repair if audit["case_cycle"][c]]
    def change(key):
        value=pair[history][key]["median_s"]
        return ("节省 " if value>=0 else "增加 ")+f"{abs(value):.3f} 秒"
    if not (passed_search or passed_net or passed_cycle):
        repair_result="三个 SAT→UNSAT 修复病例均未达到搜索、P1 净收益或两版周期收益的预登记门槛。"
    else:
        def names_of(values):return "、".join(values) or "无"
        repair_result=("修复病例达到搜索、P1 净收益和两版周期门槛的名单依次为 "+
                       "，".join(map(names_of,(passed_search,passed_net,passed_cycle)))+"。")
    text[4:4]=[repair_result+"历史 UNSAT→UNSAT 对照的搜索"+change("search")+"，P1 完整验证"+
               change("wall")+"，计入 P0 后的两版周期"+change("cycle")+"。"]
    (rep/"D4.2.md").write_text("\n\n".join(text)+"\n")
    print(verdict)
if __name__=="__main__":main()
