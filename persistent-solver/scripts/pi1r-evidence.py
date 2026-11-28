"""Lossless packaging and independent offline recomputation for PI-1R (no SAT executions)."""
import argparse
import gzip
import hashlib
import io
import json
import platform
from pathlib import Path
import runpy
import struct
import subprocess
import tarfile
import tempfile

from frozen import digest, require, save

here=Path(__file__).resolve().parent
control=runpy.run_path(str(here/"pi1r-run.py")); ROOT=control["ROOT"]; PLAN=control["PLAN"]; PI1=control["PI1"]
SOURCE="8e0c39f3934da0a1f28dacbea0a30c9a3e948f8a"
STAGES=("timed","database","ledger-off")
def read(p):return json.loads(p.read_bytes())


def sections(f,n):
    while True:
        block=f.read(n)
        if not block:return
        yield block


def pack(work,dest,binary):
    dest.mkdir(parents=True,exist_ok=True); objects=dest/"objects";objects.mkdir(exist_ok=True)
    files={}
    previous={v["sha256"]:v for v in control["INDEX"].values()}
    def remember(k,p):
        # Immutable old evidence can be addressed by SHA without copying it again.
        if p.name in ("assumptions.i32le","seals.json","stderr"):
            with p.open("rb") as f:
                h=hashlib.sha256()
                for b in sections(f,4<<20):h.update(b)
            key=h.hexdigest()
            if key in previous:
                files[k]={"sha256":key,"bytes":p.stat().st_size,"pi1":previous[key]["object"]};return
        h=hashlib.sha256();blocks=[]
        with p.open("rb") as f:
            for b in sections(f,4<<20):
                h.update(b);sh=digest(b);blocks.append(sh)
                target=objects/(sh+".gz")
                if not target.exists():target.write_bytes(gzip.compress(b,compresslevel=5,mtime=0))
        files[k]={"sha256":h.hexdigest(),"bytes":p.stat().st_size,"blocks":blocks}
    for phase in STAGES:
        for case,*modes in PLAN["ordered_timed_sessions"]:
            for m in (modes if phase!="ledger-off" else ["R2"]):
                r=work/"raw"/phase/case/m
                names=["rows.json","seals.json","assumptions.i32le","native.txt","stderr","run.json"]
                if phase=="database":names+=["reduce.1.db","reduce.2.db","reduce.inventory"]
                for name in names:remember("/".join((phase,case,m,name)),r/name)
    # Include actual native fixtures, transcripts and failed-input checks; omit the relinkable observer ELF.
    with (dest/"small.tar.gz").open("wb") as out,gzip.GzipFile(fileobj=out,filename="",mode="wb",mtime=0) as z,tarfile.open(fileobj=z,mode="w|") as tar:
        for p in sorted((work/"checks").rglob("*")):
            if not p.is_file() or p.name=="owner-probe":continue
            data=p.read_bytes();ti=tarfile.TarInfo(p.relative_to(work/"checks").as_posix());ti.size=len(data);ti.mode=0o644
            tar.addfile(ti,io.BytesIO(data))
    save(dest/"raw-index.json",files)
    build=read(PI1/"build.json")
    save(dest/"build.json",dict(source=SOURCE,baseline=PLAN["reviewed_baseline"],
         preregistration="6f8b1de4daaece2172e3bba3b0bd5210a034ede1",binary=digest(binary.read_bytes()),
         object_sha256={p.name:digest(p.read_bytes()) for p in sorted(binary.parent.glob("*.o"))},
         small_archive_sha256=digest((dest/"small.tar.gz").read_bytes()),build_log=(work/"build.log").read_text(),
         compiler=subprocess.check_output(["g++","--version"],text=True).splitlines()[0],system=platform.platform(),
         cpu=0,stock=build["stock"],stock_control=build["stock_control_sha256"],plan_sha256=digest((ROOT/"configs/pi1r-plan.json").read_bytes())))


class Archive:
    def __init__(self,root):self.root=root;self.index=read(root/"raw-index.json")
    def blocks(self,key):
        info=self.index[key];h=hashlib.sha256();size=0
        if "pi1" in info:
            with gzip.open(PI1/info["pi1"],"rb") as f:
                for b in sections(f,4<<20):
                    size+=len(b);h.update(b);yield b
        else:
            for sh in info["blocks"]:
                b=gzip.decompress((self.root/"objects"/(sh+".gz")).read_bytes())
                require(digest(b)==sh,"block seal");h.update(b);size+=len(b);yield b
        require(h.hexdigest()==info["sha256"] and size==info["bytes"],"raw seal "+key)
    def data(self,key):return b"".join(self.blocks(key))


def db_summary(arch,key,reader):
    with subprocess.Popen([reader],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=False) as proc:
        for b in arch.blocks(key):proc.stdin.write(b)
        proc.stdin.close();out=proc.stdout.read();require(proc.wait()==0,"invalid predicate trace "+key)
    return json.loads(out)


def work_signature(row,ledger):
    n=row["native"];s=n["restart_study"]
    native={k:v for k,v in n.items() if k not in ("activation","joint","rollback","boundary","restart_study","collections","reductions","families")}
    fields=("first","reinstalled","ordinary","kept","incomplete","unsafe","budget_exit","jumps","prefix_jumps","jump_removed",
            "bcp_roles","watcher_roles","end_level","end_graph")
    data=[row[k] for k in ("status","properties","order","assignment","native_vars","global_vars","program_vars","selectors","co_vars",
                            "fresh","reused","rejected_ports","occurrences","native_failed_assumptions")]
    return data+[native,[s[k] for k in fields],n["families"] if ledger else None]


def verify_small(dest, prefix=""):
    with tarfile.open(dest/"small.tar.gz") as t:
        def data(k):return t.extractfile(prefix+k).read()
        def tree(k):return json.loads(data(k))
        info={}
        native=runpy.run_path(str(here/"pi1r-controls.py"))
        # Re-parse archived allocator/trail records independently of the saved small-test JSON.
        def replay_projection(mode,name):
            raw=data(mode+"/target/"+name+"/native").decode().splitlines()
            signed=list(map(int,next(l for l in raw if l.startswith("ASSUME ")).split()[3:]))
            states=[native["state"](l) for l in raw if l.startswith("STATE ")]
            return [native["projection"](s,states[i+1],signed) for i,s in enumerate(states)
                    if s["kind"]=="restart" and s["target"]]

        for mode in ("R0","R1","R2"):
            small=tree(mode+"/small/small.json")
            for v in small.values():assert v["statuses"]==v["independent_stock"]
            ex=tree(mode+"/exhaustive/checks.json")
            assert all(v["expected"]==v["actual"]==v["stock"] for v in ex.values())
            target=tree(mode+"/target/checks.json")
            for name in ("rf_projection","restart_co","after_collection","triplet_pruned","triplet_retained"):
                assert json.loads(json.dumps(replay_projection(mode,name)))==target[name]["projections"]
            if mode!="R0":
                proj=target["rf_projection"]["projections"]
                assert any(x["kept_edges"] and x["removed_edges"] and x["dummy"] for x in proj)
                assert len(target["retained_theory_CRef"]["rejected_corruptions"])==3
            b=tree(mode+"/boundaries/checks.json")
            info[mode]=dict(sequences=len(small),versions=sum(len(x["statuses"]) for x in small.values()),
                            forced=sum(len(x["actual"]) for x in ex.values()),controls=list(target),transaction_rejections=len(b["rejections"]),
                            interrupted=b["statuses"],corruptions=b["allocator_faults_rejected"],projections=target["rf_projection"]["projections"])
        progress=[x.split() for x in data("progress.tsv").decode().splitlines()]
        assert len(progress)==216 and all(int(v)<=int(d)+1 for n,d,s,v,b in progress)
        assert any(int(v)<int(d)+1 for n,d,s,v,b in progress) and any(int(n)==0 for n,d,s,v,b in progress)
        owner=data("owner/owner.txt").decode();assert "OWNER closure=1 minisat=1 queries=2 same_this=1" in owner
        return {"arms":info,"progress_cases":len(progress),"constructor_probe":owner.strip().splitlines()[-1]}


def verify(repo,fixtures,dest,output):
    arch=Archive(dest);build=read(dest/"build.json")
    require(digest((dest/"small.tar.gz").read_bytes())==build["small_archive_sha256"],"small archive")
    require(digest((ROOT/"configs/pi1r-plan.json").read_bytes())==build["plan_sha256"],"plan")
    source_props=read(PI1/"properties.json")
    witness=runpy.run_path(str(here/"pi1-witness.py"))["inspect"]
    results={};properties={};db={};ledger={};checks=verify_small(dest)
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        reader=Path(tmp)/"db"
        subprocess.run(["g++","-std=c++11","-O2",here/"pi1r-db.cpp","-o",reader],check=True)
        for case,*order in PLAN["ordered_timed_sessions"]:
            results[case]={};db[case]={};ledger[case]={};properties[case]={}
            seals=json.loads(control["original"](case+"/solve/seals.json"))
            for side in ("P0","P1"):control["prepare"](repo,fixtures/case,case,side)
            # Recreate the SAT witness's independent bit-layout and event catalogue from the sealed source.
            witness_root=Path(tmp)
            if any(p["status"]=="FAILURE" for p in source_props[case]["P0"]["properties"]):
                witness_seal=control["real"]["frozen"].prepare(repo,witness_root/"fixtures"/case,case,"P0")
                assert witness_seal==seals[0]
            base_control=control["original"](case+"/solve/assumptions.i32le")
            pi1_rows=json.loads(control["original"](case+"/solve/rows.json"))
            stock=[json.loads(control["original"](case+"/stock-"+side+"/receipt.json")) for side in ("P0","P1")]
            assert all(entry["cpu"]==0 and entry["binary"]==build["stock"] and
                       entry["argv"]==control["real"]["PLAN"]["cases"][case]["argv"] for entry in stock)
            for mode in order:
                fixed=None;old_reductions=0;timed_controls=None
                for phase in (STAGES if mode=="R2" else STAGES[:2]):
                    key="/".join((phase,case,mode))+"/"
                    rows=json.loads(arch.data(key+"rows.json"))
                    require(len(rows)==2 and json.loads(arch.data(key+"seals.json"))==seals,"transaction seals")
                    require(arch.data(key+"stderr")==b"","native error")
                    transcript=[json.loads(x[4:]) for x in arch.data(key+"native.txt").splitlines() if x.startswith(b"ROW ")]
                    run=json.loads(arch.data(key+"run.json"))
                    require(run["cpu"]==0 and run["binary_sha256"]==build["binary"] and run["limits"]==control["real"]["PLAN"]["cases"][case]["limits"],"run configuration")
                    signed=arch.data(key+"assumptions.i32le")
                    if phase=="timed":timed_controls=digest(signed)
                    assert digest(signed)==timed_controls
                    if mode=="R0":assert signed==base_control
                    offset=0
                    for i,r in enumerate(rows):
                        side=r["side"];n=r["native"];s=n["restart_study"];prior=pi1_rows[i]
                        assert all(r[k]==v for k,v in transcript[i].items())
                        version,query,A,controls=struct.unpack_from("<4I",signed,offset);offset+=16
                        words=memoryview(signed)[offset:offset+A*4].cast("I");offset+=A*4
                        assert version==i+1 and query==1 and A==n["assumptions"] and len(set(w//2 for w in words[:controls]))==controls
                        assert sum(w&1 for w in words)==n["negative"]
                        assert r["solver_construct_count"]==1 and r["old_learnt_export_count"]==r["old_learnt_import_count"]==r["per_clause_reproof_count"]==0
                        assert r["properties"]==stock[i]["properties"]==source_props[case][side]["persistent"]
                        assert set(r["properties"])==set(seals[i]["properties"])
                        assert r["status"]==prior["status"] and n["pushes"]==n["pops"]
                        assert s["end_level"]==s["end_graph"]==s["budget_exit"]==0
                        assert s["ordinary"]==n["restarts"]==s["progress_calls"][0]
                        assert sum(s["bcp_roles"])==n["propagations"] and s["first"]+s["reinstalled"]<=n["processed"]
                        if mode=="R0":
                            assert all(n[k]==prior["native"][k] for k in ("frames","processed","rebuilds","replay","empty","decisions","conflicts","propagations","families"))
                        if phase=="timed":
                            row={k:v for k,v in r.items() if k not in ("order","assignment")}
                            results[case].setdefault(mode,{})[side]=row
                            prop=dict(status=r["status"],properties=r["properties"],unwinding=source_props[case][side]["classification"],
                                      stock_full_seconds=stock[i]["wall"],stock_elf=stock[i]["binary"],signed_assumptions_sha256=timed_controls)
                            if r["status"]=="SAT":prop["witness"]=witness(repo,witness_root,case,r)
                            properties[case].setdefault(mode,{})[side]=prop
                        else:
                            assert work_signature(r,phase=="database")==work_signature(fixed[i],phase=="database"),(case,mode,side,phase)
                            matched=fixed[i]["native"]["restart_study"]
                            assert all(s[k]==matched[k] for k in ("progress_calls","progress_available","progress_visits"))
                        if phase=="database":
                            summ=db_summary(arch,key+"reduce."+str(i+1)+".db",reader);inv=[json.loads(line) for line in arch.data(key+"reduce.inventory").splitlines()]
                            assert summ["native_true"]==n["reductions"]-old_reductions
                            # With no dummy levels each predicate leads to a frame or the terminal SAT/false assumption.
                            if n["empty"]==0:assert summ["checks"]==n["frames"]+1
                            old_reductions=n["reductions"];snap=[v for v in inv if v["version"]==i+1]
                            assert [v["phase"] for v in snap]==["entry","exit"]
                            for v in snap:
                                assert 0<v["active_inputs"]<=v["union_inputs"] and v["watcher_bytes"]<=v["watcher_reserved"]
                                hist=v["hist"];assert sum(a+b for length,k,a,b in hist if length>1)==v["native_learnts"]
                            db[case].setdefault(mode,{})[side]={"predicate":summ,"inventory":snap}
                        if phase=="ledger-off":
                            assert not s["ledger"];norm=fixed[i]
                            ledger[case][side]={"normal_native_s":norm["native"]["boundary"],"without_native_s":n["boundary"],
                                "native_delta_s":norm["native"]["boundary"]-n["boundary"],
                                "normal_backend_s":norm["elapsed_backend_transaction_s"],"without_backend_s":r["elapsed_backend_transaction_s"],
                                "backend_delta_s":norm["elapsed_backend_transaction_s"]-r["elapsed_backend_transaction_s"],
                                "normal_rss_kib":norm["rss_kib"],"without_rss_kib":r["rss_kib"],
                                "delta_rss_kib":norm["rss_kib"]-r["rss_kib"],"equal_native_work_and_model":True}
                    assert offset==len(signed)
                    if phase=="timed":fixed=rows
            # Progress is statistics-only, hence the independent R1/R2 sessions have identical native work.
            r1=json.loads(arch.data("timed/"+case+"/R1/rows.json"));r2=json.loads(arch.data("timed/"+case+"/R2/rows.json"))
            assert all(work_signature(x,True)==work_signature(y,True) for x,y in zip(r1,r2))
    checks["signed_control_vectors_equal_across_modes"]={case:len({m["P1"]["signed_assumptions_sha256"] for m in p.values()})==1
                                                          for case,p in properties.items()}
    checks.update(timed_sessions=sum(map(len,results.values())), database_sessions=sum(map(len,db.values())),
                  ledger_off_sessions=len(ledger),
                  sat_native_witnesses=sum("witness" in side for modes in properties.values() for pair in modes.values() for side in pair.values()),
                  obligations_source="PI-1 fixed native stock full traces and sealed unchanged per-side query catalogue",
                  r0_equal_reviewed_trajectory=True,r1_r2_equal_work_and_model=True)
    comparison={}
    for case,modes in results.items():
        per_mode={}
        for mode,pair in modes.items():
            p0,p1=pair["P0"],pair["P1"];n=p1["native"];s=n["restart_study"]
            seconds=p1["elapsed_backend_transaction_s"];original=modes["R0"]["P1"]["elapsed_backend_transaction_s"]
            inv=db[case][mode]["P1"]["inventory"][-1]
            def distribution(index):
                bins={}
                for length,selectors,awake,dormant in inv["hist"]:
                    value=(length,selectors)[index];bins[value]=bins.get(value,0)+awake+dormant
                total=sum(bins.values());items=sorted(bins)
                def quantile(q):
                    rank=(q*total+99)//100;acc=0
                    for k in items:
                        acc+=bins[k]
                        if acc>=rank:return k
                return {"median":quantile(50),"p95":quantile(95),"max":max(items,default=0),
                        "mean":sum(k*v for k,v in bins.items())/max(1,total)}
            per_mode[mode]={"P0_backend_s":p0["elapsed_backend_transaction_s"],"P1_backend_s":seconds,
                "sum_backend_s":seconds+p0["elapsed_backend_transaction_s"],"P1_percent_change_vs_R0":100*(seconds/original-1),
                "stock_P1_full_s":properties[case][mode]["P1"]["stock_full_seconds"],
                "P1_retained_restarts":s["kept"],"P1_ordinary_restarts":s["ordinary"],
                "P1_old_physical":sum(f["physical"] for f in n["families"]),
                "P1_old_dormant":sum(f["dormant"] for f in n["families"]),
                "P1_old_distinct_used":sum(f["distinct_used"] for f in n["families"]),
                "P1_old_dormant_distinct_used":sum(f["dormant_distinct_used"] for f in n["families"]),
                "P1_end_awake":sum(x[2] for x in inv["hist"]),"P1_end_dormant":sum(x[3] for x in inv["hist"]),
                "P1_resident_length":distribution(0),"P1_resident_selectors":distribution(1)}
        comparison[case]=per_mode
    for name,content in (("comparison",comparison),("runs",results),("checks",checks),("ledger",ledger),("database",db),("properties",properties)):
        target=output/(name+".json")
        if name=="database":
            # Each native (length, selector count, awake, dormant) bin is already a numeric record.
            target.write_text(json.dumps(content,separators=(",",":"))+"\n")
        else:save(target,content)

if __name__=="__main__":
    a=argparse.ArgumentParser()
    s=a.add_subparsers(dest="command",required=True)
    p=s.add_parser("archive")
    for x in ("work","dest","binary"):p.add_argument(x,type=Path)
    p=s.add_parser("verify")
    for x in ("repo","fixtures","dest","output"):p.add_argument(x,type=Path)
    args=a.parse_args()
    if args.command=="archive":pack(args.work,args.dest,args.binary)
    else:verify(args.repo,args.fixtures,args.dest,args.output)
