"""Create human-readable D4.1 measurement tables from all frozen process and replay receipts."""
import argparse
import csv
import json
from pathlib import Path
import struct
from audit_d4 import numbers, rows
from diff_d1 import digest
from run_d4 import property_contract
from run_stock import save


def table(path,records):
    fields=list(dict.fromkeys(k for r in records for k in r))
    with path.open("w",newline="") as f:
        w=csv.DictWriter(f,fields,delimiter="\t",lineterminator="\n");w.writeheader()
        for record in records:
            w.writerow({k:record[k] if record.get(k) is not None else "NA" for k in fields})


def layout(proof):
    with proof.open("rb") as f:
        tag=f.read(12);compact=tag[5:6]==b"C"
        sizes=[]
        for width in (16,4,8,16,12,8,12,4,4,4,4,4,20,1):
            n=struct.unpack("<I",f.read(4))[0];sizes.append(n);f.seek(n*width,1)
        f.seek(24,1);project=0
        if compact:
            n=struct.unpack("<I",f.read(4))[0];f.seek(n*4,1);project=struct.unpack("<Q",f.read(8))[0]
        stats=struct.unpack("<18Q",f.read(18*8));assert len(f.read())==8
    return dict(proof_bytes=proof.stat().st_size,nodes=sizes[0]-1,edges=sizes[2],input_records=sizes[3],
                births=sizes[4],theory_records=sizes[12],project_ms=project/1e6,
                reverse_ms=stats[14]/1e6,write_sections_ms=stats[15]/1e6,recorded_arena_capacity=stats[16],
                recorded_recorder_capacity=stats[17])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("matrix","audit","out"):p.add_argument(k,type=Path)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    read=lambda p:json.loads(p.read_text())
    matrix=read(a.matrix/"summary.json");audit=read(a.audit/"audit.json")
    measurements=[];selection=[];records=[];preparation=[];mapping=[];classes=[];props={}

    for case,arms in matrix.items():
        base=a.matrix/case;checks=audit[case];props[case]={}
        for label,sides in arms.items():
            for side,row in sides.items():
                n=base/label/side/"native";mode=base/label/side
                result=read(mode/"result.json")
                props[case][label+"/"+side]=property_contract(result)
                if (mode/"trace-comparison.json").exists():props[case][label+"/"+side]["trace_vs_stock"]=read(mode/"trace-comparison.json")
                counts=row["counts"]
                measurements.append(dict(case=case,arm=label,side=side,producer=row["producer"],wall_s=row["wall_s"],
                        search_s=row["search_s"],two_version_wall_s=row.get("cycle_s"),total_conflicts=row["total_conflicts"],
                        **counts,rss_kib=row["rss_kib"],**row["root"]))
                if (n/"proof.bin").exists():
                    records.append(dict(case=case,producer=label,wall_s=row["wall_s"],search_s=row["search_s"],
                              rss_kib=row["rss_kib"],model_bytes=(n/"model.tsv").stat().st_size,**layout(n/"proof.bin")))
                if side=="P1" and (n/"delta.json").exists():
                    t=row["preparation_ns"];s=row["selection"]
                    prep=dict(case=case,arm=label,model_and_diff_s=sum(t.values())/1e9,delta_output_bytes=sum(
                        f.stat().st_size for f in (n/"delta").rglob("*") if f.is_file()))
                    prep.update({k.removesuffix("_ns")+"_ms":v/1e6 for k,v in t.items()})
                    prep.update({k.removesuffix("_ns")+"_ms":s[k]/1e6 for k in ("archive_read_ns","validation_and_binding_ns","reverse_ns","selection_ns")})
                    preparation.append(prep)
                    byfam=row["families"]
                    sel=dict(case=case,arm=label,eligible=s["selected"],chosen=sum(r["selected"] for r in byfam.values()),
                        attached=sum(r.get("attached",0) for r in byfam.values()),hit_rows=sum(r["rows_used"] for r in byfam.values()),
                        policy_hash=digest(n/"eligible.tsv") if (n/"eligible.tsv").exists() else None)
                    if (n/"policy.json").exists():
                        receipt=read(n/"policy.json");assert (receipt["eligible"],receipt["chosen"])==(sel["eligible"],sel["chosen"])
                    for fam in ("B","M","T"):
                        for k in ("selected","attached","rows_used","watch_unit","watch_conflict","analyze","minimize"):
                            sel[fam+"_"+k]=byfam.get(fam,{}).get(k,0)
                    selection.append(sel)
        for mode,z in checks["mapping"].items():
            entry=dict(case=case,mapping=mode,vars=z["matched_variables"],old_vars=z["old_variables"],
                       audited_aux=z["gate_definitions_checked"],mappable_births=z["final_mapped"])
            for group,parts in z["premises"].items():
                entry.update({group+"_"+k:parts.get(k,0) for k in ("matched","unmapped","mapped_absent")})
            mapping.append(entry)
        for mode,z in checks["replay"].items():
            other=z["births"]-sum(z[k] for k in ("complete_permanent_boolean","complete_permanent_mixed",
                                                 "complete_permanent_theory_only","theory_any"))
            classes.append(dict(case=case,control=mode,births=z["births"],permanent_B=z["complete_permanent_boolean"],
                permanent_M=z["complete_permanent_mixed"],permanent_T=z["complete_permanent_theory_only"],
                unknown_theory=z["theory_any"],remaining_query_or_incomplete_without_unknown=other,
                complete_theory_reasons=z["complete_theory_reasons"],native_triplets=z.get("lemma_op_18",0),
                retained_mixed=z["complete_mixed_survives_mappable"],retained_eligible=z["survives_and_translates"],
                conclusions_mapped=z["all_mappable"],resident=z["resident_cdcl"]))
    for name,data in (("performance",measurements),("policies",selection),("recording",records),("delta-cost",preparation),
                      ("mapping",mapping),("classification",classes)):table(a.out/(name+".tsv"),data)
    save(a.out/"properties.json",props);save(a.out/"audit.json",audit)
    save(a.out/"matrix.json",matrix)
    print(len(measurements),"version runs;",len(selection),"live import receipts;",len(records),"native P0 proof archives")


if __name__=="__main__":main()
