"""Archive real receipts losslessly and recompute PI-1G metrics and the registered decision offline."""
import argparse
from collections import Counter,defaultdict
import gzip
import hashlib
import io
import json
import lzma
from pathlib import Path
import platform
import runpy
import shutil
import subprocess
import tarfile
import tempfile

here=Path(__file__).resolve().parent
g=runpy.run_path(str(here/"pi1g-audit.py"));scale=g["scale"];prev=scale["previous"];root=prev["ROOT"]
plan=scale["PLAN"];modes=plan["arms"];FINE,GP,RESET=modes
reviewed=runpy.run_path(str(here/"pi1r-evidence.py"))
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_text(json.dumps(v,indent=2,ensure_ascii=False)+"\n")
def sha(b):return hashlib.sha256(b).hexdigest()
def filehash(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda:f.read(4<<20),b""):h.update(block)
    return h.hexdigest()


def archive(work,dest):
    dest.mkdir(parents=True,exist_ok=True);objects=dest/"objects";objects.mkdir(exist_ok=True);index={}
    previous={v["sha256"]:v for v in prev["INDEX"].values()}
    def store(path,key):
        h=filehash(path);size=path.stat().st_size
        if h in previous:index[key]=dict(bytes=size,sha256=h,pi1=previous[h]["object"]);return
        parts=[];codec="xz" if path.name in ("activation.bin","inventory.jsonl","inventory.jsonl.learn") else "gz"
        with path.open("rb") as f:
            for raw in iter(lambda:f.read(4<<20),b""):
                name=sha(raw)+"."+codec;parts.append(name);target=objects/name
                if not target.exists():
                    temp=target.with_suffix(".packing")
                    temp.write_bytes(lzma.compress(raw,preset=1) if codec=="xz" else gzip.compress(raw,compresslevel=5,mtime=0))
                    temp.replace(target)
        index[key]=dict(bytes=size,sha256=h,parts=parts)
    for case,*order in plan["ordered_sessions"]:
        for phase in ("timed","audit"):
            for mode in order:
                prefix="/".join((phase,case,mode));folder=work/"raw"/prefix
                names=["run.json","rows.json","seals.json","native.txt","stderr","assumptions.i32le"]
                if phase=="audit":names+=["activation.bin","inventory.jsonl","inventory.jsonl.learn"]
                for name in names:store(folder/name,prefix+"/"+name)
        for side in ("P0","P1"):
            prefix="native-cold/"+case+"/"+side
            for name in ("receipt.json","rss","stdout","stderr"):store(work/"raw"/prefix/name,prefix+"/"+name)
    for name in ("scale.log","core.log","group1.log","group2.log","grouped-orders.log","runs.log","build.log","audit-build.log"):
        store(work/name,"stage/"+name)
    save(dest/"raw-index.json",index);shutil.copyfile(work/"scale.json",dest/"scale.json")
    with (dest/"small.tar.gz").open("wb") as raw,gzip.GzipFile(fileobj=raw,filename="",mode="wb",mtime=0) as z,tarfile.open(fileobj=z,mode="w|") as tar:
        for path in sorted((work/"checks").rglob("*")):
            if not path.is_file() or path.name=="owner-probe":continue
            data=path.read_bytes();h=tarfile.TarInfo(path.relative_to(work/"checks").as_posix());h.size=len(data);h.mode=0o644
            tar.addfile(h,io.BytesIO(data))
    timestamps={}
    for case,*order in plan["ordered_sessions"]:
        for arm in order:
            d=work/"raw/timed"/case/arm
            timestamps[case+"/"+arm]=[subprocess.check_output(["stat","-c","%w",d/"stderr"],text=True).strip(),
                                       subprocess.check_output(["stat","-c","%y",d/"rows.json"],text=True).strip()]
    save(dest/"build.json",dict(native_source="998c4f9a845d6f59bed5c3cfc96b5ee56181a0a1",observer_source="dbe6e1650fe2803349bfade2eefaaa46d9262506",
         preregistration="f1e3135e5566c5697a1b3c0fe88594c0b8b3257c",baseline=plan["baseline"],
         binary=filehash(work/"bin/pi1"),observer_binary=filehash(work/"audit-build/pi1"),cpu=0,
         compiler=subprocess.check_output(["g++","--version"],text=True).splitlines()[0],system=platform.platform(),
         stock_kernel=read(prev["PI1"]/"build.json")["stock"],cold_driver=read(prev["PI1"]/"build.json")["stock_control_sha256"],
         small_archive_sha256=filehash(dest/"small.tar.gz"),plan_sha256=filehash(root/"configs/pi1g-plan.json"),
         timing_windows=timestamps,observer_build_window=[subprocess.check_output(["stat","-c","%w",work/"audit-build"],text=True).strip(),
                        subprocess.check_output(["stat","-c","%y",work/"audit-build/pi1"],text=True).strip()]))


class Archive:
    def __init__(self,path):self.path=path;self.index=read(path/"raw-index.json")
    def blocks(self,key):
        row=self.index[key];h=hashlib.sha256();total=0
        if "pi1" in row:
            with gzip.open(prev["PI1"]/row["pi1"],"rb") as f:
                for b in iter(lambda:f.read(4<<20),b""):
                    h.update(b);total+=len(b);yield b
        else:
            for part in row["parts"]:
                p=self.path/"objects"/part;b=(lzma.decompress if p.suffix==".xz" else gzip.decompress)(p.read_bytes())
                assert sha(b)==p.stem;h.update(b);total+=len(b);yield b
        assert h.hexdigest()==row["sha256"] and total==row["bytes"],key
    def data(self,key):return b"".join(self.blocks(key))
    def json(self,key):return json.loads(self.data(key))
    def materialize(self,key,target):
        with target.open("wb") as f:
            for b in self.blocks(key):f.write(b)


def signature(r):
    n=r["native"];s=n["restart_study"]
    ignore=("boundary","rollback","activation","joint","restart_study","families","collections","reductions")
    return ([r[k] for k in ("version","query","status","properties","assignment","order","native_failed_assumptions","native_vars",
                            "global_vars","program_vars","selectors","co_vars","reused","fresh","rejected_ports","occurrences","unique_inputs","skipped")],
            {k:v for k,v in n.items() if k not in ignore},
            {k:v for k,v in s.items() if k not in ("ledger","query_switch_s","prefix_first_s","prefix_repeat_s","progress_seconds")})


def distribution(hist):
    # hist yields (length, selector count, multiplicity), including native root units.
    length=Counter();selector=Counter();lits=0;controls=0
    for l,s,n in hist:
        assert l>=s>=0 and n>=0
        length[l]+=n;selector[s]+=n;lits+=l*n;controls+=s*n
    total=sum(length.values())
    def quantile(bins,q):
        if not total:return None
        target=(q*total+99)//100;cum=0
        for k,n in sorted(bins.items()):
            cum+=n
            if cum>=target:return k
    return dict(count=total,literals=lits,selector_literals=controls,program_and_other_literals=lits-controls,
                mean_length=lits/total if total else None,median_length=quantile(length,50),p95_length=quantile(length,95),
                max_length=max(length) if total else None,mean_selectors=controls/total if total else None,
                median_selectors=quantile(selector,50),p95_selectors=quantile(selector,95),max_selectors=max(selector) if total else None,
                selector_fraction=controls/lits if lits else None,selector_distribution=sorted(selector.items()))


def observations(data):
    versions={}
    for line in data.splitlines():
        t,*w=line.split()
        if t==b"PHASE":
            v=int(w[0]);phase=w[1];z=versions.setdefault(v,dict(bins=[],old={},used={}))
        elif t==b"BIN":
            assert phase==b"exit";z["bins"].append(tuple(map(int,w)))
        elif t==b"OLD":
            i,f,ref,*lits=map(int,w);assert i not in z["old"] and phase==b"entry";z["old"][i]=(f,ref,lits)
        elif t==b"USE":
            i,*events=map(int,w);assert i in z["old"] and any(events);z["used"][i]=events
        else:raise ValueError(t)
    return versions


def check_small(dest):
    with tarfile.open(dest/"small.tar.gz") as t:
        def obj(k):return json.load(t.extractfile(k))
        checks=obj("group2/checks.json")
        assert len(checks["grouped-core"])==21
        assert len(checks[GP]["retire"]["faults"])==3
        old,hit=checks[GP]["survive"]["actual_hit"]
        lines=t.extractfile("group2/"+GP+"/survive/native.txt").read().decode().splitlines()
        assert " ".join(old) in lines and hit in lines and hit.split()[3]==old[2] and old[4]=="0"
        for name,record in checks[RESET].items():
            assert all(record["partition_matches_persistent"][i] for i,x in enumerate(record["inputs"]) if x["version"]<=2)
        gs=obj("grouped-orders/checks.json");assert all(x["actual"]==x["expected"]==x["stock"] for x in gs.values())
        for m in ("R0","R1","R2"):
            ex=obj("core/"+m+"/exhaustive/checks.json");assert all(x["actual"]==x["stock"]==x["expected"] for x in ex.values())
            ss=obj("core/"+m+"/small/small.json");assert all(x["statuses"]==x["independent_stock"] for x in ss.values())
        # Re-interpret the original allocator/trail controls and the deliberately damaged native group journals.
        restart_checks=reviewed["verify_small"](dest, "core/")
        control=runpy.run_path(str(here/"pi1g-small.py"))
        name="group2/"+GP+"/retire/"
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            for file in ("input.bin","args.bin","stdout","1.txn","2.txn","3.txn"):
                (d/file).write_bytes(t.extractfile(name+file).read())
            paths={v:{0:d/(str(v)+".txn"),1:d/(str(v)+".txn")} for v in (1,2,3)}
            rows=control["s"]["parse"]((d/"stdout").read_text())
            recovered=control["faults"](d,paths,GP,rows)
            assert recovered==checks[GP]["retire"]["faults"]
        return dict(restart_controls=restart_checks,grouped_cases_per_arm=len(checks[GP]),inherited_sequences=21,grouped_order_valuations=sum(len(x["actual"]) for x in gs.values()),
                    native_kept_hit=checks[GP]["survive"]["actual_hit"],rejected_faults=checks[GP]["retire"]["faults"],
                    persistent_reactivation=checks[GP]["retire"]["inputs"][-1])


def verify(repo,fixtures,dest,out):
    out.mkdir(exist_ok=True,parents=True);arch=Archive(dest);build=read(dest/"build.json");small=check_small(dest)
    reference=reviewed["Archive"](root/"reports/evidence/pi1r")
    for key in arch.index:
        if key.startswith("stage/"):arch.data(key)
    assert filehash(dest/"small.tar.gz")==build["small_archive_sha256"] and filehash(root/"configs/pi1g-plan.json")==build["plan_sha256"]
    frozen_props=read(prev["PI1"]/"properties.json");frozen_scale=read(dest/"scale.json")
    witness=runpy.run_path(str(here/"pi1-witness.py"))["inspect"]
    runs={};stats={};facts={};comparison={};activation={};shadow={};cold={}
    with tempfile.TemporaryDirectory() as tmp:
        temp=Path(tmp)
        for case,*order in plan["ordered_sessions"]:
            print("Verifying",case,flush=True)
            d=fixtures/case;seals=[prev["prepare"](repo,d,case,x) for x in ("P0","P1")]
            sc=scale["one"](fixtures,case);assert sc==frozen_scale[case]
            models={j:{0:d/(s+".txn"),1:d/(s+".txn")} for j,s in enumerate(("P0","P1"),1)}
            if case!="fib-snapshot-11":
                assert prev["real"]["frozen"].prepare(repo,temp/"fixtures"/case,case,"P0")==seals[0]
            active_layouts={};runs[case]={};stats[case]={};facts[case]={};activation[case]={};cold[case]={}
            for mode in order:
                runs[case][mode]=[];stats[case][mode]=[];facts[case][mode]=[]
                timed=None;base=None
                for phase in ("timed","audit"):
                    k="/".join((phase,case,mode))+"/"
                    rfile=arch.json(k+"run.json");assert rfile["cpu"]==0 and rfile["limits"]==prev["real"]["PLAN"]["cases"][case]["limits"]
                    assert rfile["binary"]==build["binary" if phase=="timed" else "observer_binary"] and arch.data(k+"stderr")==b""
                    assert arch.json(k+"seals.json")==seals
                    rows=arch.json(k+"rows.json");assert len(rows)==2
                    trace=[json.loads(x[4:]) for x in arch.data(k+"native.txt").splitlines() if x.startswith(b"ROW ")]
                    assert len(trace)==2 and all(all(r[k]==v for k,v in a.items()) for r,a in zip(rows,trace))
                    if phase=="timed":
                        timed=rows;base=arch.data(k+"assumptions.i32le")
                        if mode==FINE:
                            prior="ledger-off/"+case+"/R2/"
                            assert base==reference.data(prior+"assumptions.i32le")
                            for actual,old in zip(rows,json.loads(reference.data(prior+"rows.json"))):
                                native=dict(actual["native"])
                                for key in ("installed_guarded","guarded_input_fingerprint"):del native[key]
                                compare=reviewed["work_signature"]
                                assert compare(dict(actual,native=native),False)==compare(old,False),(case,"reviewed R2")
                    else:
                        assert arch.data(k+"assumptions.i32le")==base and all(signature(a)==signature(b) for a,b in zip(rows,timed)),(case,mode,"trajectory")
                        arch.materialize(k+"activation.bin",temp/"input.bin");(temp/"args.bin").write_bytes(base)
                        receipt,layouts=g["verify"](temp/"input.bin",temp/"args.bin",models,mode,rows)
                        if mode!=FINE:active_layouts[mode]=layouts
                        if mode!=RESET:assert (receipt[0]["epoch_variable"]==receipt[1]["epoch_variable"])==sc["theory"]["shared_epoch"]
                        risk=set(receipt[1].pop("partial_fine_negative_guards"));receipt[0].pop("partial_fine_negative_guards")
                        activation[case][mode]=receipt
                        inv=[json.loads(l) for l in arch.data(k+"inventory.jsonl").splitlines()]
                        obs=observations(arch.data(k+"inventory.jsonl.learn"))
                    for i,(side,row) in enumerate(zip(("P0","P1"),rows)):
                        n=row["native"];s=n["restart_study"]
                        assert row["properties"]==frozen_props[case][side]["persistent"] and set(row["properties"])==set(seals[i]["properties"])
                        assert row["status"]==("SAT" if "FAILURE" in row["properties"].values() else "UNSAT")
                        assert row["solver_construct_count"]==(2 if mode==RESET and i else 1)
                        assert (rows[0]["native"]["solver_instance"]!=n["solver_instance"])==(mode==RESET and i==1)
                        assert all(row[k]==0 for k in ("old_learnt_export_count","old_learnt_import_count","per_clause_reproof_count"))
                        assert s["mode"]=="R2" and s["ledger"]==(phase=="audit") and n["pushes"]==n["pops"] and s["end_level"]==s["end_graph"]==0
                        assert row["selectors"]==sc["arms"][mode]["selectors"][i] and n["assumptions"]==sc["arms"][mode]["assumptions"][i]
                        if i:
                            assert row["rejected_ports"]==sc["theory"]["rejected_interfaces"]
                            assert row["reused"]==(0 if mode==RESET else sc["theory"]["accepted"])
                        if mode==RESET and i:assert row["program_vars"]==row["native_vars"] and row["global_vars"]==row["program_vars"]+row["selectors"]+row["co_vars"]+1
                        if phase=="timed":
                            runs[case][mode].append({k:v for k,v in row.items() if k not in ("assignment","order")})
                            fact=dict(status=row["status"],properties=row["properties"],classification=frozen_props[case][side]["classification"],
                                      unfolding_ids=frozen_props[case][side]["unwinding_property_ids"],
                                      unfolding_messages=frozen_props[case][side]["unwinding_stop_or_warning"])
                            if row["status"]=="SAT":fact["witness"]=witness(repo,temp,case,row)
                            facts[case][mode].append(fact)
                            continue
                        assert receipt[i]["unique_B"]==sc["unique_B"][i] and receipt[i]["unique_Q"]==sc["unique_Q"][i]
                        if i and mode!=RESET:assert receipt[i]["shared_B"]==sc["fine_shared" if mode==FINE else "grouped_shared"]
                        entry,end=inv[2*i:2*i+2];assert entry["phase"]=="entry" and end["phase"]=="exit" and end["version"]==i+1
                        z=obs[i+1];born=distribution((l,s,num) for _,l,s,num in z["bins"])
                        resident=distribution((l,s,a+b) for l,s,a,b in end["hist"])
                        assert born["count"]==sum(f["births"] for f in n["families"])
                        assert resident["count"]==end["native_learnts"]+sum(a+b for l,s,a,b in end["hist"] if l==1)
                        family=n["families"];active=sum(f["constraining"] for f in family)
                        assert active==len(z["old"])
                        assert len(z["used"])==sum(f["distinct_used"]-f["dormant_distinct_used"] for f in family)
                        stats[case][mode].append(dict(side=side,born=born,resident=resident,families=family,
                          birth_family_counts=[sum(n for f,l,s,n in z["bins"] if f==k) for k in range(3)],
                          entry={k:v for k,v in entry.items() if k!="hist"},end={k:v for k,v in end.items() if k!="hist"},
                          resident_dormant=sum(b for l,s,a,b in end["hist"]),audit_backend_s=row["elapsed_backend_transaction_s"],audit_rss_kib=row["rss_kib"],
                          signature_equal=True))
                        if i and mode==FINE:
                            assert len(risk)==sc["partial_reinstalled"]
                            lost={k:{"family":"BMT"[f],"negative_guards":sorted(risk.intersection(lits)),"native_hits":z["used"].get(k,[0]*4)}
                                  for k,(f,ref,lits) in z["old"].items() if not risk.isdisjoint(lits)}
                            shadow[case]=dict(fine_originally_active=active,affected_input_controls=len(risk),extra_dormant=len(lost),
                                extra_dormant_with_real_fine_hit=sum(any(x["native_hits"]) for x in lost.values()),affected_births=lost)
            assert active_layouts[GP]==active_layouts[RESET],(case,"active group contents/order")
            for i,side in enumerate(("P0","P1")):
                p="native-cold/"+case+"/"+side+"/";r=arch.json(p+"receipt.json");assert arch.data(p+"stderr")==b""
                assert ("STOCK "+r["status"]).encode() in arch.data(p+"stdout") and int(arch.data(p+"rss"))==r["rss_kib"]
                assert r["model"]==seals[i]["transaction_sha256"] and r["status"]==facts[case][GP][i]["status"] and r["binary"]==build["cold_driver"]
                cold[case][side]=r
            f,p,r=(runs[case][m][1]["elapsed_backend_transaction_s"] for m in modes)
            sw=frozen_props[case]["P1"]["stock_wall_s"]
            comparison[case]=dict(Fine_P1_s=f,Grouped_P1_s=p,Reset_active_P1_s=r,stock_full_P1_s=sw,unguarded_P1_s=cold[case]["P1"]["backend_wall_s"],
              grouped_savings_s=f-p,grouped_savings_percent=100*(f-p)/f,persistent_savings_vs_reset_s=r-p,
              persistent_savings_vs_reset_percent=100*(r-p)/r,stock_minus_grouped_s=sw-p,
              diagnostic_signal=case!="fib-snapshot-11" and f-p>=0.2 and (f-p)/f>=.05 and p<sw)
    checks=dict(small=small,production_sessions=12,observer_sessions=12,unguarded_transactions=8,production_ledger=False,per_predicate_trace_count=0,
                exact_active_partitions_equal=True,production_and_observer_work_equal=True,fine_matches_reviewed_R2_all_eight_versions=True,stock_property_catalogues_equal=True,
                verified_SAT_witnesses=sum("witness" in s for x in facts.values() for y in x.values() for s in y),
                signals=[c for c,v in comparison.items() if v["diagnostic_signal"]])
    for name,obj in (("runs",runs),("learning",stats),("properties",facts),("comparison",comparison),("activation",activation),
                     ("shadow",shadow),("cold",cold),("checks",checks)):
        if name=="learning":(out/(name+".json")).write_text(json.dumps(obj,separators=(",",":"))+"\n")
        else:save(out/(name+".json"),obj)


if __name__=="__main__":
    p=argparse.ArgumentParser();s=p.add_subparsers(dest="cmd",required=True)
    a=s.add_parser("archive");v=s.add_parser("verify")
    for n in ("work","dest"):a.add_argument(n,type=Path)
    for n in ("repo","fixtures","dest","out"):v.add_argument(n,type=Path)
    retrieve=s.add_parser("extract",help="Restore one original file by its key in raw-index.json")
    retrieve.add_argument("dest",type=Path)
    retrieve.add_argument("key")
    retrieve.add_argument("output",type=Path)
    x=p.parse_args()
    if x.cmd=="archive":archive(x.work,x.dest)
    elif x.cmd=="extract":Archive(x.dest).materialize(x.key,x.output)
    else:verify(x.repo,x.fixtures,x.dest,x.out)
