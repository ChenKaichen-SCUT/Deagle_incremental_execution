"""Link a clock-only observer against the frozen stock object files in a separate directory."""
import argparse
import os
import shlex
import subprocess
from pathlib import Path
import json

from diff_d1 import digest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("output",type=Path)
    args=p.parse_args()
    out=args.output.resolve()
    info=json.loads((Path(__file__).resolve().parents[1]/"configs/build.json").read_text())
    stock=Path(info["binary_path"])
    tree=stock.parents[2]
    src=tree/info["members"]["ClosureSolver"]["source"]
    if digest(stock)!=info["binary_sha256"] or digest(src)!=info["members"]["ClosureSolver"]["source_sha256"]:
        raise ValueError("stock source or ELF differs from D0")
    out.mkdir(parents=True,exist_ok=False)
    original=src.read_text()
    text=original
    for old,new in (
        ('#include "ClosureSolver.h"','#include "ClosureSolver.h"\n#include <chrono>\n#include <cstdio>'),
        ('    int curr_restarts = 0;', '    const auto start=std::chrono::steady_clock::now();\n    int curr_restarts = 0;'),
        ('        curr_restarts++;\n    }', '''        curr_restarts++;
    }
    const auto ns=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();
    FILE *clock_output=std::fopen("stock-search.tsv","ab");
    if(!clock_output || std::fprintf(clock_output,"%lld\\t%d\\n",(long long)ns,curr_restarts)<0 ||
       std::fclose(clock_output)!=0) std::abort();''')):
        if text.count(old)!=1:raise ValueError("ambiguous stock timer location: "+old)
        text=text.replace(old,new)
    copy=out/"ClosureSolver.cc";copy.write_text(text)
    obj=out/"ClosureSolver.o"
    cc=shlex.split(info["closure_compile"])
    cc[cc.index("-o")+1:]=[str(obj),str(copy),"-I",str(src.parent)]
    link=shlex.split(info["final_link"])
    link[link.index("-o")+1]=str(out/"deagle_exe")
    link.insert(link.index("-Wl,--start-group"),str(obj))
    env=dict(os.environ,LC_ALL="C",PATH="/usr/bin:/bin")
    subprocess.run(cc,cwd=tree/"src/solvers",env=env,check=True)
    subprocess.run(link,cwd=tree/"src/cbmc",env=env,check=True)
    (out/"receipt.json").write_text(json.dumps(dict(stock=digest(stock),source=digest(src),clock_source=digest(copy),
        clock_elf=digest(out/"deagle_exe"),compile=cc,link=link),indent=2)+"\n")


if __name__=="__main__":main()
