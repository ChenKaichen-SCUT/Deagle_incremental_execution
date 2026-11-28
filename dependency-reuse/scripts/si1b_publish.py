"""Assemble reviewed SI-1B catalogs, controls, exact counts and integrity receipts."""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
from pathlib import Path
import shutil

from cases42 import load
from run_stock import BASE, save
from si1b_audit import DISP, read, rows, table
from si1b_catalog import check, sha

def pack(src,dst):
    dst.parent.mkdir(parents=True,exist_ok=True)
    with src.open("rb") as f,dst.open("wb") as raw,gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0,compresslevel=6) as g:
        shutil.copyfileobj(f,g,1<<20)
def raw_files(src,dst,include_binary=True):
    dst.mkdir(exist_ok=True,parents=True)
    for f in src.iterdir():
        if not f.is_file():continue
        if f.name in ("stdout","stderr","model.tsv","native.bin","phi.c"):
            if include_binary or f.name!="native.bin":pack(f,dst/(f.name+".gz"))
        elif f.name in ("run.json","seal.json","seal-time.json","native.bin.stats","search.tsv","search.tsv.root-clock"):
            shutil.copyfile(f,dst/f.name)
def gzjson(p):
    with gzip.open(p,"rt") as f:return json.load(f)
def witness_story(jdir,examples):
    keys=gzjson(jdir/"typed-keys.json.gz");irs=[gzjson(jdir/f"P{i}-ir.json.gz") for i in (0,1)]
    bysite=[{v:ir["source_sites"][k] for k,v in ir["sites"].items()} for ir in irs];out={}
    for name,item in examples.items():
        if not (name.startswith("used_union/") and name.endswith("/added")):continue
        key=item["witness"];row=keys[key];role=row;route=[]
        if row[0] in ("returned","lowering-role"):
            row=keys[row[1]]
            while row[0]=="operand":route.append(row[2]);row=keys[row[1]]
            owner=keys[row[1]];ctx=keys[owner[1]]
        elif row[0]=="outer":
            owner=keys[row[1]];ctx=keys[owner[1]]
        else:continue
        sites=[m.get(ctx[-1]) if ctx[0]=="occurrence" else None for m in bysite]
        out[name]=dict(item,port_role=role,operand_route=list(reversed(route)),owner=owner,occurrence=ctx,native_sites=sites)
    return out
def copy_controls(root,out):
    for name in ("P0","P1","same-cwd-control","native-cache/AB","native-cache/BA","single-phi/native"):
        raw_files(root/name,out/name)
    for name in ("source","native-cache/source","native-cache/direct","single-phi/source","lexical"):
        shutil.copytree(root/name,out/name,dirs_exist_ok=True)
    shutil.copyfile(root/"edit.patch",out/"edit.patch")

def publish(z,out,development=False,passive=None):
    passive=passive or z/"passive"
    out.mkdir(exist_ok=True,parents=True);cohorts=[];clock=[];cache=[];scope_summary=[];used=Counter();origins=Counter();signed=Counter();refs={}
    for case in load():
        p=z/"release"/case;g=z/"verified"/case;j=z/"dr"/case;to=out/case;to.mkdir(exist_ok=True)
        shutil.copytree(p/"source",to/"source",dirs_exist_ok=True)
        shutil.copytree(g,to/"audit",dirs_exist_ok=True);shutil.copytree(j,to/"join",dirs_exist_ok=True)
        gates=read(g/"model-audit.json");info=read(j/"join.json");sample=witness_story(j,read(g/"examples.json"))
        save(to/"source-witnesses.json",sample)
        tallies=defaultdict(Counter)
        for row in rows(g/"coverage.tsv"):
            scope=row["scope"];cat=row["category"];side=row["side"];cohorts.append(row)
            tallies[(side,scope)].update({k:int(row[k]) for k in DISP})
            if side=="P0" and scope=="used_union":
                used.update({k:int(row[k]) for k in DISP});origins[cat,"old_gaps"]+=int(row["added"])+int(row["neither"])
                origins[cat,"recovered"]+=int(row["added"])
        for (side,scope),t in tallies.items():
            scope_summary.append([case,side,scope,*[t[k] for k in DISP],sum(t.values()),t["same"]+t["different"]+t["lost"],t["same"]+t["different"]+t["added"]])
        for i,side in enumerate(("P0","P1")):
            obs=passive/case/side
            for mode in ("off","shadow","audit"):raw_files(p/mode/side,to/"native"/side/mode)
            for mode in ("original","off","shadow"):
                folder=to/"passive"/side/mode;folder.mkdir(exist_ok=True,parents=True)
                shutil.copyfile(obs/mode/"run.json",folder/"run.json")
            shutil.copyfile(obs/"receipt.json",to/"passive"/side/"receipt.json")
            # Keep a queryable independent ordered trace, stripping process addresses.
            output=to/"passive"/side/"original.tsv.gz";handles={}
            with (obs/"original/work/tap.tsv").open("rb") as src,output.open("wb") as raw,gzip.GzipFile(fileobj=raw,filename="",mode="wb",mtime=0,compresslevel=4) as compressed:
                for line in src:
                    if line.startswith(b"K\t"):
                        f=line.split(b"\t");key=f[1],f[2];f[2]=str(handles.setdefault(key,len(handles)+1)).encode();line=b"\t".join(f)
                    compressed.write(line)
            for mode in ("original","off","shadow"):
                order=[ln.decode().rstrip().split("\t",1)[1] for ln in (obs/mode/"work/tap.tsv").open("rb") if ln.startswith(b"[\t")]
                save(to/"passive"/side/mode/"guard-order.json",order)
            light=gates[side]["timing"]["shadow"];off=gates[side]["timing"]["off"]
            def root_latency(mode):
                folder=p/mode/side
                stamp=int((folder/"search.tsv.root-clock").read_text().splitlines()[0])
                return stamp-read(folder/"run.json")["monotonic_start_ns"]
            clock.append(dict(case=case,side=side,off_to_root_ns=root_latency("off"),
                shadow_to_root_ns=root_latency("shadow"),off_wall_ns=off["wall_ns"],shadow_wall_ns=light["wall_ns"],off_rss_kib=off["peak_rss_kib"],
                shadow_rss_kib=light["peak_rss_kib"],source_pair_ns=read(p/"source/time.json")["scan_inheritance_ns"],
                native_register_ns=light["register_ns"],native_cache_ns=light["cache_role_ns"],serialize_ns=light["serialize_ns"],
                seal_ns=light["seal_ns"],native_bytes=light["catalog_bytes"],join_read_ns=info["timing"]["read_validate_ns"][i],
                ir_finalize_ns=info["timing"]["source_ir_finalize_ns"][i],port_index_ns=info["timing"]["port_template_read_index_ns"][i],
                pair_join_ns=info["timing"]["join_conflict_ns"],pair_to_outputs_ns=info["timing"]["process_to_outputs_ns"],
                pair_peak_rss_kib=info["timing"]["process_peak_RSS_KiB"]))
            cache.append(dict(case=case,side=side,**info["cache"][i],dedup_owner_root_attempts=light["owner_associations"]-info["cache"][i]["unique_native_owner_roots"],dedup_all_row_attempts=light["dedup_rows"]))
        signed[case]=info["join"]["accepted"]
    table(out/"scope-summary.tsv",["case","side","scope",*DISP,"total","old","direct"],scope_summary)
    for file,records in [("coverage",cohorts),("cost",clock),("cache",cache)]:
        keys=list(records[0]);table(out/(file+".tsv"),keys,([r[k] for k in keys] for r in records))
    check(sum(n for (c,t),n in origins.items() if t=="old_gaps")==58464 and origins["auxiliary","old_gaps"]==34754 and origins["pointer_aggregate","old_gaps"]==22732,"SI-1A denominator drift")
    save(out/"summary.json",dict(direct_per_case=signed,used=used,old_used_gaps={c:dict(old_gaps=origins[c,"old_gaps"],recovered=origins[c,"recovered"]) for c,t in origins if t=="old_gaps"}))
    copy_controls(z/"accepted-controls",out/"controls");shutil.copyfile(z/"extended-controls.json",out/"controls.json")
    shutil.copyfile(z/"native/si1b-build.json",out/"build.json")
    for tag in ("stock","si"):shutil.copyfile(z/("tap-"+tag)/"build.json",out/("passive-build-"+tag+".json"))
    if development:
        dev=out/"development";dev.mkdir(exist_ok=True)
        for tag,src in (("early-shadow-crash",z/"matrix/fib_updates_8/shadow/P0"),("pre-fix-off",z/"final-matrix/fib-snapshot-11/off/P0"),("pre-fix-shadow",z/"final-matrix/fib-snapshot-11/shadow/P0")):
            raw_files(src,dev/tag,False)
        shutil.copyfile(z/"stack",dev/"early-shadow-stack.txt")
    files={str(f.relative_to(out)):dict(bytes=f.stat().st_size,sha256=sha(f)) for f in sorted(out.rglob("*")) if f.is_file() and f not in (out/"files.json",out/"replay.json")}
    save(out/"files.json",files)
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("scratch",type=Path);p.add_argument("output",type=Path);p.add_argument("--development",action="store_true");p.add_argument("--passive-root",type=Path)
    a=p.parse_args();publish(a.scratch,a.output,a.development,a.passive_root)
