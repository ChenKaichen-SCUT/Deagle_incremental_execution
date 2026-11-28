"""Render the report tables from verified outputs."""
from pathlib import Path
import json
import sys

arms=("Fine-Persistent","Grouped-Persistent","Grouped-Reset-active")
cases={"fib_updates_8":"Fibonacci","circular-buffer":"circular-buffer","airline_reservations_6":"airline","fib-snapshot-11":"历史 Fibonacci"}
def num(x):return f"{x:,}"
def pair(*x):return " / ".join(num(y) for y in x)
def table(headers,rows):
    return "\n".join(["| "+" | ".join(headers)+" |","|"+"|".join("---" for _ in headers)+"|"]+
                     ["| "+" | ".join(map(str,r))+" |" for r in rows])


def tables(d):
    def read(name):return json.loads((d/(name+".json")).read_bytes())
    sc=read("scale");runs=read("runs");learn=read("learning");cmp=read("comparison");sh=read("shadow");out={}
    rows=[];reuse=[];size=[];work=[];mem=[];sem=[];time=[]
    for c,label in cases.items():
        a=sc[c];z=cmp[c];th=a["theory"]
        rows.append([label,pair(*a["unique_B"]),num(a["P0_groups"]),pair(a["full"],a["partial"],a["absent"]),
                     pair(a["fine_shared"],a["grouped_shared"]),num(a["partial_reinstalled"]),num(a["P1_new_groups"])])
        sem.append([label,pair(*a["unique_Q"]),pair(th["old_interfaces"],th["new_interfaces"]),num(th["accepted_interface_variables"]),
                    pair(th["accepted"],th["rejected_interfaces"]),"是" if th["shared_epoch"] else "否"])
        time.append([label,*[f"{z[k]:.3f}" for k in ("Fine_P1_s","Grouped_P1_s","Reset_active_P1_s","unguarded_P1_s","stock_full_P1_s")],
                     f"{z['grouped_savings_percent']:.1f}%",f"{z['persistent_savings_vs_reset_percent']:+.1f}%"])
        for mode,short in zip(arms,("Fine","Grouped","Reset")):
            fam=learn[c][mode][1]["families"]
            count=lambda k:sum(f[k] for f in fam)
            reuse.append([label,short,pair(count("physical"),count("dormant"),count("constraining")),
                          pair(count("distinct_used")-count("dormant_distinct_used"),count("dormant_distinct_used")),
                          pair(*(f["distinct_used"]-f["dormant_distinct_used"] for f in fam)),
                          pair(*(sum(f["hits"][i] for f in fam) for i in range(4)))])
            for j,side in enumerate(("P0","P1")):
                l=learn[c][mode][j];u=l["resident"];r=runs[c][mode][j];n=r["native"];rs=n["restart_study"];e=l["end"]
                size.append([label,short,side,pair(l["born"]["count"],u["count"]),num(u["literals"]),
                             pair(u["selector_literals"],u["program_and_other_literals"]),f"{u['mean_length']:.1f}",
                             pair(u["median_length"],u["p95_length"],u["max_length"]),
                             pair(u["median_selectors"],u["p95_selectors"],u["max_selectors"]),f"{100*u['selector_fraction']:.1f}%"])
                work.append([label,short,side,pair(r["selectors"],n["assumptions"],rs["reinstalled"]),n["rebuilds"],
                             pair(n["decisions"],n["conflicts"]),num(rs["bcp_roles"][0]),f"{n['boundary']:.3f}",f"{r['elapsed_backend_transaction_s']:.3f}"])
                mem.append([label,short,side,
                         f"{e['allocator_bytes']/1048576:.1f} / {e['allocator_reserved']/1048576:.1f}",
                         f"{e['watcher_bytes']/1048576:.1f} / {e['watcher_reserved']/1048576:.1f}",num(r["rss_kib"])])
    out["timing"]=table(["P1 病例","Fine s","Grouped s","Reset-active s","未守卫冷重放 s","stock 完整 s","Grouped 相对 Fine 节省","Grouped 相对 Reset 节省"],time)
    out["scale"]=table(["病例","P0 / P1 唯一 B","P0 组","完整 / 部分 / 全失配","Fine / Grouped 共享 B","部分失配重装 B","P1 新组"],rows)
    out["sem"]=table(["病例","P0 / P1 唯一 Q","旧 / 新理论接口变量","可认证共享接口","全部接受 / 接口拒绝的变量提案","共享 epoch"],sem)
    out["size"]=table(["病例","臂","版","出生 / 末驻留","末驻留总文字","selector / 非 selector 文字","平均长度","长度中位 / P95 / 最大","每条 selector 中位 / P95 / 最大","selector 占比"],size)
    out["work"]=table(["病例","臂","版","selector / assumptions / 重装","建图","决策 / 冲突","程序文字 BCP 出队","原生求解 s","后端事务 s"],work)
    out["mem"]=table(["病例","臂","版","原生分配器使用 / 容量 MiB","watcher 使用 / 容量 MiB","轻量峰值 RSS KiB"],mem)
    out["reuse"]=table(["P1 病例","臂","旧物理 / 休眠 / 活跃","命中过的活跃 / 休眠","活跃命中 B / M / T","全部传播 / 冲突 / 分析 / 成功最小化"],reuse)
    out["shadow"]=table(["病例","Fine 原本活跃","仅因同组受影响的 Fine 控制量","额外休眠旧学习","其中在 Fine 确有命中"],[
        [label,*[num(sh[c][k]) for k in ("fine_originally_active","affected_input_controls","extra_dormant","extra_dormant_with_real_fine_hit")]]
        for c,label in cases.items()])
    return out

if __name__=="__main__":
    for title,t in tables(Path(sys.argv[1])).items():print(title+"\n\n"+t+"\n")
