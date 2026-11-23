"""Store auditable native records once per content hash, with bounded-size release archives."""
import argparse
import gzip
import hashlib
import json
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.model.identity import file_sha, read, save
from scripts.stage7.oracles import independent
from scripts.stage7.results import derive

SUFFIXES={".json",".jsonl",".stdout",".stderr",".diff",".yaml",".c",".txt",".irep"}


def fixed_traces(run):
    matrix=read(run/"matrix.json")
    folder=run/"fixed-traces"
    folder.mkdir(exist_ok=True)
    locations={}
    with tarfile.open(ROOT/"reports/evidence/stage-06/full-runs.tar.gz","r:gz") as archive:
        for name in read(run/"plan.json")["cases"]:
            item=matrix[name]
            dest=folder/(name+".json")
            if name in ("threshold_guard","split_counter"):
                origin="cases/"+name+"/evidence/old/cex0.json"
                shutil.copyfile(ROOT/origin,dest)
            elif item["stage6_run"]:
                ref="verification/"+item["stage6_run"]+"/repair/cex0.json"
                origin="stage6-archive/"+ref
                dest.write_bytes(archive.extractfile(ref).read())
            else:
                origin="diagnostics/"+name+"/repair/cex0.json"
                shutil.copyfile(run/origin,dest)
            trace=read(dest)
            if trace["p0_sha256"]!=item["files"]["old/program.c"] or trace["property"]!=read(run/item["case_dir"]/"phi.json")["id"]:
                raise ValueError("Reference old trace belongs to another experiment")
            locations[name]={"path":origin,"sha256":file_sha(dest),"steps":trace["step_count"]}
    save(folder/"index.json",locations)


def store(run,dest):
    roots=[run/s for s in ("diagnostics","trials","sources","fixed-traces")]
    paths=[p for root in roots for p in root.rglob("*") if p.is_file() and p.suffix in SUFFIXES and "tools" not in p.parts]
    paths.extend(run/s for s in ("matrix.json","plan.json","doctor.json"))
    paths.sort()
    logical={}
    object_pack={}
    z=None
    part=0
    packs={}
    try:
        for path in paths:
            name=path.relative_to(run).as_posix()
            if path.is_symlink():raise ValueError("Unexpected symlink "+name)
            data=path.read_bytes()
            sha=hashlib.sha256(data).hexdigest()
            logical[name]=sha
            if sha in object_pack:continue
            compressed=gzip.compress(data,compresslevel=6,mtime=0)
            if z is None or z.fp.tell()+len(compressed)+256>28*1024*1024:
                if z is not None:z.close()
                part+=1
                label="raw-"+str(part).zfill(2)+".zip"
                z=zipfile.ZipFile(dest/label,"w",compression=zipfile.ZIP_STORED)
                packs[label]=None
            info=zipfile.ZipInfo(sha+".gz",date_time=(1980,1,1,0,0,0))
            z.writestr(info,compressed)
            object_pack[sha]=label
    finally:
        if z is not None:z.close()
    for name in packs:
        packs[name]={"bytes":(dest/name).stat().st_size,"sha256":file_sha(dest/name)}
    return {"schema":1,"files":logical,"objects":object_pack,"archives":packs}


def pack(run,dest):
    dest.mkdir(exist_ok=True,parents=True)
    fixed_traces(run)
    rows,summary=derive(run)
    save(dest/"measurements.json",rows)
    save(dest/"summary.json",summary)
    save(dest/"schedule-oracles.json",independent())
    shutil.copyfile(run/"plan.json",dest/"plan.json")
    shutil.copyfile(run/"matrix.json",dest/"matrix.json")
    index=store(run,dest)
    save(dest/"archive.json",index)
    print("files",len(index["files"]),"distinct objects",len(index["objects"]),"archives",index["archives"],flush=True)
    print(json.dumps(summary["totals"],sort_keys=True))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--experiment",type=Path,required=True)
    p.add_argument("--dest",type=Path,required=True)
    a=p.parse_args()
    pack(a.experiment.resolve(),a.dest.resolve())
