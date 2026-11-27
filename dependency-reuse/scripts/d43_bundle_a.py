"""Seal the preflight evidence and compare it with a replay from restored D4.2 objects."""
import argparse
import gzip
import json
import platform
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

from d43_project_support import BASE, PLAN, digest, save, check
from d43_review import write_tsv


def output(*command, cwd=None):
    return subprocess.check_output(command, cwd=cwd, text=True).strip()


def compare_tree(left,right):
    paths = {p.relative_to(left) for p in left.rglob("*") if p.is_file()}
    check(paths=={p.relative_to(right) for p in right.rglob("*") if p.is_file()},"replay file set")
    for rel in sorted(paths):
        check(digest(left/rel)==digest(right/rel),"replay byte mismatch: "+str(rel))
    return len(paths)


def specimen_sizes():
    # A host-layout measurement of the guide's example structs. Nothing is linked into Deagle.
    code = """
#include <array>
#include <cstdint>
#include <cstdio>
template<unsigned K> struct Theory {std::array<uint64_t,K/64> theory; uint8_t flags;};
template<unsigned K> struct Clause {std::array<uint64_t,K/64> boolean,theory; uint8_t flags;};
int main(){std::printf("%zu %zu %zu %zu", sizeof(Theory<256>),sizeof(Clause<256>),
                        sizeof(Theory<1024>),sizeof(Clause<1024>));}
"""
    with tempfile.TemporaryDirectory() as t:
        exe=Path(t)/"layout"
        subprocess.run(["g++","-std=c++17","-x","c++","-","-o",exe],input=code,text=True,check=True)
        ts,bs,tl,bl=map(int,output(exe).split())
    return dict(example_abi_bytes={"small":{"Closure":ts,"SAT":bs},"large":{"Closure":tl,"SAT":bl}},
                native_compact_objects_in_A=0,production_peak_observed=None)


def bundle(d42,scratch,out):
    # Accepted only after fresh, independent replay of the published owner stream.
    checked = {name:compare_tree(scratch/left,scratch/right) for name,left,right in
               (("projection","release","replayed"),("summaries","release-review","replayed-review"))}
    out.mkdir(parents=True,exist_ok=False)
    shutil.copytree(scratch/"release",out/"cases")
    shutil.copytree(scratch/"release-review",out/"summary")
    shutil.copytree(scratch/"raw",out/"raw")
    for name in ("restore","verify"):
        shutil.copy2(scratch/(name+".log"),out/(name+".txt"))
    raw=json.loads((out/"raw/files.json").read_bytes())["files"]
    costs=[]
    for case in PLAN["cases"]:
        prefix=scratch/"owners"/case
        for mode in ("off","on"):
            d=prefix/mode
            run=json.loads((d/"run.json").read_bytes())
            obs=json.loads((d/"observer.json").read_bytes())
            check(run["exit_code"] in (0,10) and not run["timed_out"],"failed P0 owner probe")
            costs.append([case,mode,run["exit_code"],run["wall_ns"],run["peak_rss_kib"],obs["scopes"],
                          obs["marker_bytes"],obs["canonical_sha256"],raw[f"owners/{case}/{mode}/model.tsv"]["sha256"]])
        row=json.loads((out/"cases"/case/"inputs.json").read_bytes())
        for u in ("audit","all"):
            with gzip.open(out/"cases"/case/f"directory-{u}.bin.gz","rb") as f:
                check(f.read(8)==b"D43DIR1\0","directory magic")
                n=sum(len(block) for block in iter(lambda:f.read(1<<20),b""))
            check(n==sum(row["directory_record_bytes"].get(u+d,0) for d in ("B","T")),"directory byte account")
    write_tsv(out/"owner-cost.tsv",["case","mode","exit","wall_ns","peak_RSS_KiB","scopes","marker_bytes",
                                   "canonical_model_SHA256","raw_model_SHA256"],costs)
    b=d42.parents[1]
    stock=b/"stock-build"; release=d42/"release"
    sources={}
    for label,tree,sha in (("stock",stock,PLAN["upstream"]),("D42_release",release,PLAN["implementation42"]),
                           ("base_review",b/"native",PLAN["review_base"])):
        actual=output("git","rev-parse","HEAD",cwd=tree)
        check(actual==sha,"wrong "+label)
        tracked=output("git","diff","--name-only","HEAD","--",cwd=tree)
        check(not tracked,"dirty tracked source in "+label)
        sources[label]=dict(path=str(tree),sha=actual,origin=output("git","remote","get-url","origin",cwd=tree))
    cpu=Path("/proc/cpuinfo").read_text()
    layout=specimen_sizes()
    environment=dict(kernel=platform.release(),machine=platform.machine(),python=platform.python_version(),
        compiler=output("g++","-dumpfullversion"),CPU=next(x.split(":",1)[1].strip() for x in cpu.splitlines()
            if x.startswith("model name")),logical_CPUs=cpu.count("processor\t:"),
        MemTotal=Path("/proc/meminfo").read_text().splitlines()[0],source=sources,stage_worktree=str(BASE.parent),
        stock_binary_sha256=digest(stock/"src/cbmc/deagle_exe"),D42_binary_sha256=digest(release/"src/cbmc/deagle_exe"),
        observer_build=json.loads((scratch/"observer/build.json").read_bytes()),projection_elf_sha256=digest(scratch/"project43"),
        input_index_sha256=PLAN["archive_index_sha256"],sizeof=layout,identical_restored_outputs=checked)
    check(environment["stock_binary_sha256"]==json.loads((BASE/"configs/build.json").read_bytes())["binary_sha256"] and
          environment["D42_binary_sha256"]==environment["observer_build"]["pinned_release_sha256"],"fixed binary differs")
    save(out/"environment.json",environment)
    entries={str(p.relative_to(out)):dict(bytes=p.stat().st_size,sha256=digest(p)) for p in sorted(out.rglob("*")) if p.is_file()}
    save(out/"files.json",dict(format="D4.3-A/preflight-v1",files=entries))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("d42",type=Path)
    p.add_argument("scratch",type=Path)
    p.add_argument("new_evidence_dir",type=Path)
    a=p.parse_args()
    bundle(a.d42.resolve(),a.scratch.resolve(),a.new_evidence_dir.resolve())
