"""CLI query-scope and archive rejection tests; run outside the timing matrix."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS=Path(__file__).resolve().parents[2]/"scripts"
sys.path.insert(0,str(SCRIPTS))
from d4_prepare import check_library, digest, save


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("native","stock","tools","new_directory"):p.add_argument(n,type=Path)
    a=p.parse_args();native,stock,tools,out=[x.resolve() for x in (a.native,a.stock,a.tools,a.new_directory)]
    out.mkdir(parents=True,exist_ok=False)
    # Two mutually exclusive violations require separate property queries in the same solver.
    program=(SCRIPTS.parent/"tests/d1/local.c").read_text().replace("assert(value == 7);",
        "assert(enabled == 0);\n  assert(enabled != 0);\n  assert(value == 7);")
    (out/"main.c").write_text(program)
    flags=["--function","main","--deagle-closure","--mm","sc","--unwind","3","--unwinding-assertions","--json-ui","main.c"]
    summary={}
    for name in ("stock","record","record-cold","reuse"):
        results=out/name;results.mkdir()
        cmd=[stock,*flags] if name=="stock" else [sys.executable,SCRIPTS/"d4.py",name,"--binary",native,"--tools",tools,
             "--out",results/"native",*([] if name=="record" else ["--library",out/"record/native"]),"--",*flags]
        with (results/"stdout").open("w") as stdout,(results/"stderr").open("w") as stderr:
            code=subprocess.run(cmd,cwd=out,stdout=stdout,stderr=stderr).returncode
        assert code==10,(name,code)
        text=(results/"stdout").read_text()
        from summarize_stock import ui_and_diagnostics
        entries,_=ui_and_diagnostics(text)
        props={p["property"]:p["status"] for m in entries for p in m.get("result",[])}
        assert len(props)==3 and sorted(props.values())==["FAILURE","FAILURE","SUCCESS"],props
        summary[name]=dict(properties=props)
    old=out/"record/native"
    source=(old/"model.tsv").read_text().splitlines()
    queries=sum(r.startswith("N\t") for r in source)
    assert queries>1,queries
    for mode in ("record-cold","reuse"):
        folder=out/mode/"native"
        prefix=(folder/"boundary.tsv").read_text().splitlines()
        assert prefix[-1]=="READY\tD4-P1-v1" and sum(r.startswith("N\t") for r in prefix)==1
        assert len((folder/"search.tsv").read_text().splitlines())>=1
    summary["P0_queries"]=queries
    # Self-consistent receipt checksum is insufficient for importing a wrong rule/ELF or truncated archive.
    rejected={}
    for label in ("receipt","producer","rules","truncated"):
        dest=out/("bad-"+label);shutil.copytree(old,dest)
        file=dest/"receipt.json";r=json.loads(file.read_text())
        if label=="receipt":(dest/"receipt.sha256").write_text("0"*64+"\n")
        else:
            if label=="producer":r["native_sha256"]="0"*64
            if label=="rules":r["rules"]="unsupported"
            if label=="truncated":
                f=dest/"proof.bin";f.write_bytes(f.read_bytes()[:-1]);r["library_sha256"]["proof.bin"]=digest(f)
            save(file,r);(dest/"receipt.sha256").write_text(digest(file)+"\n")
        try:check_library(dest,native,tools)
        except ValueError as error:rejected[label]=str(error)
        else:raise AssertionError("accepted "+label)
    summary["rejections"]=rejected
    save(out/"results.json",summary)
    print("P0 queries",queries,"all P1 properties matched; rejected",list(rejected))


if __name__=="__main__":main()
