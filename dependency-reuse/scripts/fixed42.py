"""Recreate the historical pair reference without changing its native flags or original sources."""
import argparse,sys
from pathlib import Path
from cases42 import load
from diff_d1 import digest
from run_stock import BASE,run,save
from d42_prepare import read
from summarize_stock import interpret


def main():
    p=argparse.ArgumentParser()
    for n in ("d41","tools","out"):p.add_argument(n,type=Path)
    a=p.parse_args();tree,tools,out=[v.resolve() for v in (a.d41,a.tools,a.out)]
    case="fib-snapshot-11";s=load()[case];exe=tree/"src/cbmc/deagle_exe"
    assert digest(exe)==read(BASE/"reports/D4.1-status.json")["native_elf_sha256"]
    stockinfo=read(BASE/"configs/build.json");stock=Path(stockinfo["binary_path"]);assert digest(stock)==stockinfo["binary_sha256"]
    for arm in ("stock","D41"):
        for side in ("P0","P1"):
            dest=out/case/arm/side;cmd=stock;flags=[]
            if arm=="D41":
                cmd=Path(sys.executable).resolve()
                flags=[tree/"dependency-reuse/scripts/d4.py","record" if side=="P0" else "reuse","--binary",exe,"--tools",tools,"--out",dest/"native"]
                flags+=["--triplets","--identities"] if side=="P0" else ["--mapping","d41","--policy","all","--library",out/case/arm/"P0/native"]
                flags+=["--source","program.i","--"]
            run(cmd,{**s,"argv":[*map(str,flags),*s["argv"]]},case,side,dest,digest(cmd))
            m=read(dest/"run.json");assert m["exit_code"]==0
            save(dest/"result.json",interpret(m,(dest/"stdout").read_text())[0])
if __name__=="__main__":main()
