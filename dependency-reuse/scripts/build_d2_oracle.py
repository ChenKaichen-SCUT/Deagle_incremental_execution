"""Link an observation-only ClosureSolver object into the pinned D1 build."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("d1_tree","build_log","new_dir"): p.add_argument(name,type=Path)
    args=p.parse_args()
    tree,log,out=args.d1_tree.resolve(),args.build_log.resolve(),args.new_dir.resolve()
    source=tree/"minisat-2.2.1/minisat/core/ClosureSolver.cc"
    if subprocess.check_output(["git","-C",str(tree),"diff","ed7679588106538c04dcb7dcc504b5ac682f010e","--",str(source)]):
        raise ValueError("oracle needs the reviewed D1 Closure solver")
    out.mkdir(parents=True,exist_ok=False)
    text=source.read_text()
    snapshot=r'''    for(int i=0;i<learnts.size();++i) d2_row('R',ca[learnts[i]]);
    for(int i=0;i<trail.size();++i)
        if(level(var(trail[i]))==0) std::fprintf(d2_oracle(),"U\t%d\n",trail[i].x);
    std::fprintf(d2_oracle(),"END\n");
'''
    patches={
        "using namespace Minisat;":r'''
static FILE *d2_oracle()
{
    static FILE *file=std::fopen("native-learns.tsv","wbx");
    if(!file) std::abort();
    return file;
}
template<class C> static void d2_row(char tag,const C &c)
{
    FILE *file=d2_oracle();
    std::fputc(tag,file);
    for(int i=0;i<c.size();++i) std::fprintf(file,"\t%d",c[i].x);
    std::fputc('\n',file);
}
''',
        "analyze(confl, learnt_clause, backtrack_level);":'\n            d2_row(\'L\',learnt_clause);',
        "    if (!ok) return l_False;":None,
        "    cancelUntil(0);\n    return status;":None}
    for anchor,code in patches.items():
        if text.count(anchor)!=1: raise ValueError(anchor)
        if code is None:
            replacement=("    if (!ok) {\n"+snapshot+"        return l_False;\n    }"
                         if "if (!ok)" in anchor else snapshot+anchor)
            text=text.replace(anchor,replacement)
        else: text=text.replace(anchor,anchor+code)
    copy=out/"ClosureSolver.cc"
    copy.write_text(text)
    lines=log.read_text().splitlines()
    cmd=shlex.split(next(l for l in lines if l.startswith("g++ -c ") and l.endswith("/minisat/core/ClosureSolver.cc")))
    obj=out/"ClosureSolver.o"
    cmd[cmd.index("-o")+1:]=[str(obj),str(copy),"-I",str(source.parent)]
    env=dict(os.environ,PATH="/usr/bin:/bin",LC_ALL="C")
    subprocess.run(cmd,cwd=tree/"src/solvers",env=env,check=True)
    link=shlex.split(next(l for l in lines if l.startswith("g++ ") and " -o deagle_exe " in l))
    link[link.index("-o")+1]=str(out/"deagle_exe")
    link.insert(link.index("-Wl,--start-group"),str(obj))
    subprocess.run(link,cwd=tree/"src/cbmc",env=env,check=True)
    (out/"recipes.json").write_text(json.dumps([cmd,link],indent=2)+"\n")


if __name__=="__main__": main()
