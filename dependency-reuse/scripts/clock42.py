"""Additional stock observation-only timing. The unmodified executable supplies every stock wall."""
import argparse
from pathlib import Path
from cases42 import load
from d42_prepare import read,save
from diff_d1 import digest
from run_stock import BASE
from run_d42 import plain,snapshot,compare

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for n in ("observer","functional","out"):p.add_argument(n,type=Path)
    a=p.parse_args();binary,func,out=[v.resolve() for v in (a.observer,a.functional,a.out)]
    assert digest(binary)==read(BASE/"reports/D4-status.json")["stock_search_observer_sha256"]
    result={}
    for case,s in load().items():
        for side in ("P0","P1"):
            dest=out/case/side;plain(binary,s,case,side,dest)
            q=snapshot(dest);compare(func/case/"1/stock"/side,dest,True);result[f"{case}/{side}"]=q
    save(out/"timers.json",result)
