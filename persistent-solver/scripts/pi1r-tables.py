"""Render the PI-1R report tables from independently recomputed JSON receipts."""
import json
from pathlib import Path
import sys

case_names={"fib_updates_8":"Fibonacci","circular-buffer":"circular-buffer","airline_reservations_6":"airline","fib-snapshot-11":"历史 Fibonacci"}
modes=["R0","R1","R2"]
def read(d,f):return json.loads((d/(f+".json")).read_text())
def table(headers,rows):
    return "\n".join(["| "+" | ".join(headers)+" |","|"+"|".join("---" for _ in headers)+"|"]+
                     ["| "+" | ".join(map(str,row))+" |" for row in rows])
def ratio(x):return f"{x:+.1f}%"
def sec(x):return f"{x:.3f}"
def ms(x):return f"{x*1000:.2f}"
def trip(values):return " / ".join(f"{v:,}" for v in values)

def sections(d):
    c=read(d,"comparison"); runs=read(d,"runs");db=read(d,"database");ledger=read(d,"ledger");res={}
    rows=[]
    for k,label in case_names.items():
        x=c[k];rows.append([label,*[sec(x[m]["P1_backend_s"]) for m in modes],
               ratio(x["R1"]["P1_percent_change_vs_R0"]),ratio(x["R2"]["P1_percent_change_vs_R0"]),
               sec(x["R0"]["stock_P1_full_s"])])
    res["backend"]=table(["病例","R0 后端 s","R1 后端 s","R2 后端 s","R1 相对 R0","R2 相对 R0","stock 完整 s"],rows)
    rows=[]
    for k,label in case_names.items():
        for side in ("P0","P1"):
            ns=[runs[k][m][side]["native"] for m in modes];s=[x["restart_study"] for x in ns]
            rows.append([label,side,f"{ns[0]['assumptions']:,}",trip([s[0]["ordinary"],s[1]["ordinary"]]),
                         f"{s[1]['kept']:,}",trip([s[0]["reinstalled"],s[1]["reinstalled"]]),
                         trip([ns[0]["rebuilds"],ns[1]["rebuilds"]]),trip(s[1]["prefix_jumps"]),
                         " / ".join(ms(z["prefix_repeat_s"]) for z in s[:2])])
    res["prefix"]=table(["病例","版本","A","普通重启 R0 / R1","R1 保留","实测重装 R0 / R1","建图 R0 / R1",
                        "R1 撤销前缀的 UIP / 延迟冲突 / 延迟单位","重装区间 ms R0 / R1"],rows)
    rows=[]
    for k,label in case_names.items():
        ns=[runs[k][m]["P1"]["native"]["restart_study"] for m in modes]
        rows.append([label,trip(z["progress_calls"][0] for z in ns),trip(z["progress_visits"][0] for z in ns),
                     " / ".join(ms(z["progress_seconds"][0]) for z in ns)])
    timing=[]
    for k,label in case_names.items():
        for side in ("P0","P1"):
            row=runs[k]["R2"][side]; n=row["native"]; s=n["restart_study"]
            timing.append([label,side,sec(row["install_seconds"]),sec(s["query_switch_s"]),sec(s["prefix_first_s"]),
                           sec(n["boundary"]),ms(n["rollback"]),sec(row["elapsed_backend_transaction_s"]),f"{row['rss_kib']:,}"])
    res["timing"]=table(["R2 病例","版本","输入安装 s","查询准备 s","首次安装区间 s",
                         "原生查询 s","退出回退 ms","完整后端事务 s","峰值 RSS KiB"],timing)
    res["progress"]=table(["P1 病例","调用 R0 / R1 / R2","实际遍历层数 R0 / R1 / R2","实测 ms R0 / R1 / R2"],rows)
    rows=[]
    for k,label in case_names.items():
        for m in ("R0","R2"):
            row=runs[k][m]["P1"];n=row["native"];s=n["restart_study"]
            rows.append([label,m,f"{n['decisions']:,}",f"{n['conflicts']:,}",trip([s["bcp_roles"][1],s["bcp_roles"][0]]),
                         f"{n['theory_props']:,}",f"{n['cycles']:,}",trip(f["distinct_used"] for f in n["families"]),
                         sec(n["boundary"]),f"{row['rss_kib']:,}"])
    res["work"]=table(["P1 病例","臂","决策","冲突","BCP 出队 selector / 程序","理论传播","理论冲突",
                       "旧学习实际命中 B / M / T","原生查询 s","峰值 RSS KiB"],rows)
    rows=[]
    for k,label in case_names.items():
        for side in ("P0","P1"):
            z=db[k]["R2"][side];p=z["predicate"];inv=z["inventory"][-1];hist=inv["hist"]
            population=sum(a+b for _,_,a,b in hist)
            mean=lambda col:sum(row[col]*(row[2]+row[3]) for row in hist)/max(population,1)
            rows.append([label,side,trip([inv["active_inputs"],inv["union_inputs"]]),f"{p['checks']:,}",
                         f"{p['native_true']:,}",f"{p['only_shadow_true']:,}",trip([population,sum(x[3] for x in hist)]),
                         f"{mean(0):.1f} / {mean(1):.1f}",f"{inv['allocator_reserved']/1048576:.1f} / {inv['watcher_reserved']/1048576:.1f}"])
    res["resident"]=table(["P1 R2 病例","旧物理驻留","被停用 selector 满足","仍可约束","不同旧条目回执","其中休眠回执"],[
        [label,f"{z['P1_old_physical']:,}",f"{z['P1_old_dormant']:,}",
         f"{z['P1_old_physical']-z['P1_old_dormant']:,}",f"{z['P1_old_distinct_used']:,}",f"{z['P1_old_dormant_distinct_used']:,}"]
        for k,label in case_names.items() for z in [c[k]["R2"]]])
    res["database"]=table(["R2 病例","版本","启用 / 联合基础输入","reduceDB 判断","实际触发","仅去掉 selector 扣减会触发",
                           "驻留 / 休眠","平均长度 / selector 个数","分配器 / watcher 容量 MiB"],rows)
    rows=[]
    for k,label in case_names.items():
        for side in ("P0","P1"):
            s=ledger[k][side]
            rows.append([label,side,sec(s["normal_backend_s"]),sec(s["without_backend_s"]),f"{s['backend_delta_s']:+.3f}",
                         f"{s['native_delta_s']:+.3f}",f"{s['delta_rss_kib']:+,}"])
    res["ledger"]=table(["病例","版本","启用账本事务 s","关闭账本事务 s","启用减关闭 s","原生查询差 s","RSS 差 KiB"],rows)
    return res

if __name__=="__main__":
    for name,out in sections(Path(sys.argv[1])).items():print(name+"\n\n"+out+"\n")
