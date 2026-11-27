"""Explain the frozen historical query's allocator-sensitive native encoding using independent sources."""
import argparse,sys,subprocess
from pathlib import Path
from cases42 import load
from d42_prepare import read,save
from diff_d1 import digest
from run_stock import BASE,run
from summarize_stock import interpret

def main():
    p=argparse.ArgumentParser()
    for n in ("tree","observer","out"):p.add_argument(n,type=Path)
    a=p.parse_args();tree,observer,out=[v.resolve() for v in (a.tree,a.observer,a.out)]
    fixture=tree/"dependency-reuse/tests/d42";sys.path.insert(0,str(fixture))
    from query_equivalence import verify
    case="fib-snapshot-11";spec=load()[case];result={};out.mkdir()
    for side,src in (("P0","old"),("P1","new")):
        sub=out/side;sub.mkdir()
        inp=sub/"passive"
        subprocess.run([sys.executable,fixture/"input_observer.py",tree,observer/"recipes.json",inp,"--side",src],check=True)
        r=result[side]={"source_sha256":spec["files_sha256"][src+"/program.i"],"observer":digest(observer/"deagle_exe")}
        for arm in ("stock","manifest"):
            dest=sub/arm;cmd=observer/"deagle_exe";flag=["--d1-manifest",str(dest/"model.tsv")] if arm=="manifest" else []
            run(cmd,{**spec,"argv":[*flag,*spec["argv"]]},case,side,dest,digest(cmd))
            meta=read(dest/"run.json");assert meta["exit_code"]==0
            props,_=interpret(meta,(dest/"stdout").read_text());r[arm]=[q["native_cumulative"] for q in props["queries"]]
            save(dest/"result.json",props)
        r["alpha"]=verify(inp/"off/inputs.tsv",inp/"audit/inputs.tsv",inp/"audit/metadata.tsv")
        # Bind the full D1 manifest to the passive audit capture, including clause submission order.
        stream=lambda p:(l for l in p.open("rb") if l.startswith(b"C\t"))
        from itertools import zip_longest
        assert all(x==y for x,y in zip_longest(stream(sub/"manifest/model.tsv"),stream(inp/"audit/metadata.tsv")))
        save(out/"encoding.json",result)
if __name__=="__main__":main()
