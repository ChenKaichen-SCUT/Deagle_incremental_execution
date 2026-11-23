"""Render the observed paired ratios from the archived release measurements."""
import argparse
import json
from pathlib import Path
from statistics import median

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


def plot(source,out):
    rows=json.loads(source.read_bytes())
    names=list(dict.fromkeys(r["case_id"] for r in rows))
    colors={"both":"#206f66","prefix":"#465f95","rebuild":"#ab592d"}
    fig,ax=plt.subplots(figsize=(8.3,5.1),layout="constrained")
    for idx,name in enumerate(names):
        case=sorted((r for r in rows if r["case_id"]==name),key=lambda r:r["repeat"])
        xs=[r["speedup"] for r in case if r["speedup"] is not None]
        if not xs:continue
        color=colors["both" if case[0]["lemmas_imported"] else "prefix" if case[0]["reused_prefix_steps"] else "rebuild"]
        ax.plot([min(xs),max(xs)],[idx,idx],color=color,lw=1.1)
        offsets=[(i-(len(xs)-1)/2)*.16 for i in range(len(xs))]
        ax.scatter(xs,[idx+o for o in offsets],s=15,color="#71777b",zorder=3)
        mid=median(xs)
        ax.scatter(mid,idx,s=42,marker="D",color=color,zorder=4)
        near_reference=max(xs)>.85
        ax.text(min(xs)-.023 if near_reference else max(xs)+.023,idx,f"{mid:.3f}",va="center",
                ha="right" if near_reference else "left",fontsize=8,color="#252b30")
    ax.axvline(1,color="#44484b",linestyle="--",lw=1)
    ax.set(xlim=(0,1.09),ylim=(len(names)-.5,-.7),yticks=range(len(names)),yticklabels=names,
           xlabel="Full wall time / incremental wall time  (1 = equal)")
    ax.set_xticks([0,.2,.4,.6,.8,1])
    ax.set_axisbelow(True)
    ax.grid(axis="x",color="#dddddd",lw=.6)
    for edge in ("top","right","left"):ax.spines[edge].set_visible(False)
    ax.tick_params(axis="y",length=0,pad=8)
    ax.set_title("Post-change verification across three paired runs",loc="left",fontsize=13,pad=15)
    legend=[Line2D([0],[0],marker="D",linestyle="none",color=c,label=l,markersize=6) for c,l in
            ((colors["both"],"Prefix and lemma"),(colors["prefix"],"Prefix only"),(colors["rebuild"],"Full rebuild"))]
    legend.append(Line2D([0],[0],marker="o",linestyle="none",color="#71777b",label="Individual run",markersize=4))
    fig.legend(handles=legend,loc="outside lower center",ncol=4,frameon=False,fontsize=8)
    fig.savefig(out,dpi=165,facecolor="white")
    plt.close(fig)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("measurements",type=Path)
    p.add_argument("output",type=Path)
    a=p.parse_args()
    plot(a.measurements,a.output)
