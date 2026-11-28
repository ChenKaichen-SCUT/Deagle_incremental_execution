"""Recalculate the paired decisions from the published clock tables alone, using exact rational arithmetic."""
import argparse
import csv
from fractions import Fraction
import json
from pathlib import Path
from statistics import median


def table(path):
    with path.open() as stream:
        return list(csv.DictReader(stream,delimiter="\t"))


def recalibrate(directory):
    measured={};paired={};funnel=table(directory/"funnel.tsv")
    for r in table(directory/"runs.tsv"):
        key=(r["case"],int(r["round"]),r["mode"],r["side"])
        assert key not in measured
        measured[key]=r
    for r in table(directory/"pairs.tsv"):
        key=(r["case"],int(r["round"]))
        assert key not in paired
        paired[key]=r
    gate=json.loads((directory/"gate.json").read_bytes())
    n=gate["rounds"];cases=list(dict.fromkeys(k[0] for k in measured))
    assert len(cases)==4 and n in (3,5) and len(measured)==4*n*9 and len(paired)==4*n
    summary={};trigger=False;success=[[],[]];record_pass=[[],[]];use={}
    for case in cases:
        off=[int(measured[case,i,"off","P0"]["wall_ns"]) for i in range(1,n+1)]
        floor=max(1,max(off)-min(off))
        fields={k:[] for k in ("quality_abs","no_quality_abs","quality_cost","P1_abs","cycle_abs",
                                "P1","cycle","search_abs","cold_reuse_abs","compact_extra","quality","no_quality")}
        for i in range(1,n+1):
            def value(arm,side,col="wall_ns"):
                return int(measured[case,i,arm,side][col])
            a,b=value("stock","P0"),value("stock","P1")
            c,d=value("compact","P0"),value("compact-reuse","P1")
            q,z=value("light-quality","P0"),value("light-no-quality","P0")
            row=paired[case,i]
            extra=c-off[i-1]
            p1=b-d;cycle=a+b-c-d
            expected={"P1_gain_ns":p1,"cycle_gain_ns":cycle,"extra_compact_vs_off_ns":extra,
                "extra_compact_vs_stock_ns":c-a,"quality_history_cost_ns":q-z,"extra_saved_vs_quality_ns":q-c,
                "extra_saved_vs_no_quality_ns":z-c,"denominator_noise_floor_ns":floor,
                "search_gain_ns":value("compact-cold","P1","search_ns")-value("compact-reuse","P1","search_ns"),
                "cold_minus_reuse_full_ns":value("compact-cold","P1")-d}
            assert all(int(row[k])==v for k,v in expected.items())
            for key,v in (("quality_abs",q-c),("no_quality_abs",z-c),("quality_cost",q-z),("P1_abs",p1),
                          ("cycle_abs",cycle),("P1",Fraction(p1,b)),("cycle",Fraction(cycle,a+b)),("compact_extra",extra),
                          ("search_abs",expected["search_gain_ns"]),("cold_reuse_abs",expected["cold_minus_reuse_full_ns"])):
                fields[key].append(v)
            for key,den in (("quality",q-off[i-1]),("no_quality",z-off[i-1])):
                fields[key].append(Fraction(den-extra,den) if den>floor else None)
        for j,k in enumerate(("P1","cycle")):
            v=fields[k]
            trigger |= median(v[:3])>=Fraction(1,20) and sum(x>0 for x in v[:3])>=2
            if case!="fib-snapshot-11" and n==5 and median(v)>=Fraction(1,20) and sum(x>0 for x in v)>=4:
                success[j].append(case)
        for j,k in enumerate(("quality","no_quality")):
            v=fields[k]
            for i,raw in enumerate(v,1):
                published=paired[case,i]["recording_reduction_vs_"+k]
                if None in v:
                    assert published==""
                else:
                    assert abs(float(published)-float(raw))<1e-12
            if None not in v and case in ("circular-buffer","airline_reservations_6","fib-snapshot-11"):
                if median(v)>=Fraction(1,2) and sum(x>0 for x in v)*3>=2*n:
                    record_pass[j].append(case)
        summary[case]={}
        for k,values in fields.items():
            summary[case][k]=None if None in values else dict(median=float(median(values)),minimum=float(min(values)),
                maximum=float(max(values)),positive=sum(v>0 for v in values),rounds=len(values))
        for i in range(1,n+1):
            arms=[r for r in funnel if r["case"]==case and int(r["round"])==i]
            assert len(arms)==4
            for field in ("attached","distinct_hits","watch_unit","watch_conflict","analyze","minimize"):
                assert sum(int(r[field]) for r in arms)==int(measured[case,i,"compact-reuse","P1"][field])
        use[case]=[(int(r["round"]),int(r["attached"]),int(r["distinct_hits"])) for r in funnel if r["case"]==case and r["family"]=="M"]
    assert trigger==gate["trigger"] and n==(5 if trigger else 3)
    for i,k in enumerate(("P1","cycle")):
        assert sorted(success[i])==sorted(gate["real_net_benefit_cases"][k])
    assert sorted(record_pass[0])==sorted(gate["L2_C_vs_original_Light_quality"])
    assert sorted(record_pass[1])==sorted(gate["controlled_L2_C_vs_Light_no_quality"])
    return dict(rounds=n,trigger=trigger,confirmed_real_P1=success[0],confirmed_real_cycle=success[1],
                recording_vs_quality=sorted(record_pass[0]),recording_vs_no_quality=sorted(record_pass[1]),
                mixed_attached_and_hit_by_round=use,paired_summary=summary)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("published_tables",type=Path)
    args=parser.parse_args()
    print(json.dumps(recalibrate(args.published_tables),indent=2))
