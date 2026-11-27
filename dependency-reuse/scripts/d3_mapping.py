"""Compare the reviewed D1 mapping with D3 on all frozen inputs, including P0/P0."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from check_d1_delta import verify
from diff_d1 import digest
from package_d1 import metrics, packed
from prepare_d2 import prepare, metadata, occurrences
from recheck_d2 import restore
from run_d1 import CASES
from run_stock import BASE, run, save
from summarize_stock import interpret


def run_manifest(binary,case,side,enhanced,directory):
    spec=dict(json.loads((BASE/"bench/manifest.json").read_text())[case])
    path=directory/"native.tsv"
    spec["argv"]=["--d1-manifest",str(path),*(["--d3-layouts"] if enhanced else []),*spec["argv"]]
    run(binary,spec,case,side,directory,digest(binary))
    meta=json.loads((directory/"run.json").read_text())
    result,trace=interpret(meta,(directory/"stdout").read_text())
    with gzip.open(BASE/"reports/evidence/d1/runs/off"/case/side/"result.json.gz","rt") as f:
        reference,_=json.load(f)
    if meta["timed_out"] or metrics(result)!=metrics(reference):
        raise ValueError(f"native behavior differs for {case} {side}")
    save(directory/"result.json",result)
    return dict(wall_s=meta["wall_ns"]/1e9,rss_kib=meta["peak_rss_kib"],
                manifest_bytes=path.stat().st_size,sha256=digest(path))


def summarize(case,root,checker):
    ev=BASE/"reports/evidence/d2"
    oldpair=ev/"pairs"/case
    p0=root/"manifests"/case/"P0/after/native.tsv"
    prepared=root/"prepared"/case
    checked=root/"checked"/case
    checked.mkdir(parents=True)
    with tempfile.TemporaryDirectory(dir=root) as name:
        temp=Path(name)
        restore(ev,case,json.loads((oldpair/"runs.json").read_text())["proofs"][0],temp/"proof")
        with gzip.open(oldpair/"native-learns.tsv.gz","rb") as src,(temp/"oracle").open("wb") as dst:
            shutil.copyfileobj(src,dst)
        packed(p0,temp/"native.gz")
        prepare(case,prepared,root/"self",pair=root/"pairs"/case,native=temp/"native.gz")
        subprocess.run([checker,temp/"proof",prepared/"inputs.txt",prepared/"mapped.txt",temp/"oracle",checked],check=True)
    with gzip.open(oldpair/"used.tsv.gz","rt") as f:
        old={int(row[0]):int(row[3]) for row in map(str.split,f) if int(row[2])&2}
    with (checked/"used.tsv").open() as f:
        new={int(row[0]):int(row[3]) for row in map(str.split,f) if int(row[2])&2}
    if old.keys()!=new.keys(): raise ValueError("P0 used permanent Boolean inputs changed")
    changes=Counter((a,new[i]) for i,a in old.items())
    self_matched={i for i,scope,key,_ in occurrences(root/"self"/case) if i in old and key}
    previously_self_unknown={i for i in old if old[i]&64}
    old_input_effects=Counter()
    for i in previously_self_unknown:
        old_input_effects["now_self_resolved" if i in self_matched else "still_self_unknown"]+=1
        old_input_effects["now_matched" if new[i]==0 else "now_mapped_but_absent" if new[i]==1 else "cross_still_unknown"]+=1
    witnesses=[]
    probes=json.loads((ev/"proof-witnesses.json").read_text()).get(case,())
    original_map,_=metadata(BASE/"reports/evidence/d1/pairs"/case)
    improved_map,_=metadata(root/"pairs"/case)
    for proof in probes:
        for example in proof["examples"]:
            seq=example["source_occurrence"]
            if seq not in old:raise ValueError("stale witness occurrence")
            if old[seq]:
                witnesses.append(dict(learned_id=proof["learned_id"],occurrence=seq,old_cause=old[seq],
                    new_cause=new[seq],now_self_resolved=seq in self_matched,
                    variables=[dict(raw=l,old=original_map[l//2],new=improved_map[l//2])
                               for l in example["raw_literals"] if l>=2]))
    old_ids={int(row[0]) for row in map(str.split,gzip.open(oldpair/"survivors.tsv.gz","rt"))}
    new_ids={int(row[0]) for row in map(str.split,(checked/"survivors.tsv").open())}
    targets={}
    if case=="circular-buffer":
        ids=(1164359,1175295,1175622,1175652,1175741)
        with gzip.open(oldpair/"learned.tsv.gz","rt") as a,(checked/"learned.tsv").open() as b:
            for line1,line2 in zip(a,b):
                x,y=list(map(int,line1.split())),list(map(int,line2.split()))
                if x[0] in ids:
                    targets[x[0]]=dict(before=x[4],after=y[4],now_survives=bool(y[7]))
    return dict(used_permanent_input_count=len(old),matched_before=sum(c==0 for c in old.values()),
        matched_after=sum(c==0 for c in new.values()),used_transitions=[
          dict(before=a,after=b,count=n) for (a,b),n in sorted(changes.items())],
        used_previously_self_unknown=len(previously_self_unknown),outcomes_of_previously_self_unknown=old_input_effects,
        audited_D2_witnesses=witnesses,old_pure_survivors=len(old_ids),new_pure_survivors=len(new_ids),
        newly_surviving=sorted(new_ids-old_ids),previously_surviving_lost=sorted(old_ids-new_ids),
        five_aux_only_circular=targets)


def audit_gates(pair,p0,p1):
    def gates(path):
        result={}
        with path.open() as f:
            for line in f:
                if line.startswith("G\t"):
                    _,op,out,*literals=line.split()
                    raw=int(out)
                    entry=(op,raw&1,[int(l) for l in literals])
                    result[raw//2]=None if raw//2 in result else entry
        return result
    a,b=gates(p0),gates(p1)
    mapped={}
    aux=[]
    with gzip.open(pair/"variables.tsv.gz","rt") as f:
        for line in f:
            side,v,peer,role,_,_=line.split()
            if side!="0":break
            if int(peer)>=0:
                mapped[int(v)]=int(peer)
                if role=="Aux":aux.append(int(v))
    for v in aux:
        peer=mapped[v]
        op,sign,parents=a[v];new_op,new_sign,children=b[peer//2]
        translated=[(mapped[l//2]^(l&1)) if l>=0 else l for l in parents]
        if op!="ite":translated.sort();children=sorted(children)
        if op!=new_op or sign^(peer&1)!=new_sign or translated!=children:
            raise ValueError(f"gate definition fails signed comparison at {v}")
    return len(aux)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("binary","engine","d2_checker","new_directory"):p.add_argument(arg,type=Path)
    args=p.parse_args()
    binary,engine,checker,root=(path.resolve() for path in vars(args).values())
    root.mkdir(parents=True,exist_ok=False)
    schedule=[(case,side,mode) for i,case in enumerate(CASES) for j,side in enumerate(("P0","P1"))
              for mode in (("before","after") if (i+j)%2==0 else ("after","before"))]
    save(root/"plan.json",dict(schedule=schedule,binary_sha256=digest(binary),engine_sha256=digest(engine),
        checker_sha256=digest(checker),cpu=0,replicates_per_arm=1))
    cost={}
    for case,side,mode in schedule:
        cost.setdefault(case,{}).setdefault(side,{})[mode]=run_manifest(
            binary,case,side,mode=="after",root/"manifests"/case/side/mode)
    save(root/"native-cost.json",cost)
    report={}
    for case in CASES:
        snapshots={}
        for directory,p0mode,side,enhanced in (("baseline","before","P1",False),
                ("pairs","after","P1",True),("self","after","P0",True)):
            raw=root/"manifests"/case
            dest=root/directory/case
            subprocess.run([sys.executable,BASE/"scripts/diff_d1.py",raw/"P0"/p0mode/"native.tsv",
                raw/side/p0mode/"native.tsv",engine,dest,*(["--d3-mapping"] if enhanced else [])],check=True)
            snapshots[directory]=json.loads((dest/"summary.json").read_text())
        s=summarize(case,root,checker)
        raw=root/"manifests"/case
        p0,p1=(raw/k/"after/native.tsv" for k in ("P0","P1"))
        s["checked_Aux_functions"]=audit_gates(root/"pairs"/case,p0,p1)
        s["independent_clause_delta"]=verify(root/"pairs"/case,[p0,p1])
        locked=json.loads((BASE/"reports/evidence/d1/pairs"/case/"summary.json").read_text())
        for k in ("variables","clauses","theory"):
            if snapshots["baseline"][k]!=locked[k]:raise ValueError(f"{case} baseline {k} changed")
        for mode,z in snapshots.items():
            s[mode]=dict(matched_variables=z["variables"]["matched"],
              matched_aux=z["variables"]["exclusive_roles"][0].get("Aux",{}).get("matched",0),
              boolean_occurrences=z["clauses"]["occurrences"]["B"],
              analysis_s=z["analysis_wall_s"],compression_and_digest_s=z["evidence_compression_and_digest_wall_s"])
        old_self=json.loads((BASE/"reports/evidence/d2/self"/case/"summary.json").read_text())
        s["before_self"]=dict(matched_variables=old_self["variables"]["matched"],
                              boolean_occurrences=old_self["clauses"]["occurrences"]["B"])
        report[case]=s
    save(root/"summary.json",report)


if __name__=="__main__":main()
