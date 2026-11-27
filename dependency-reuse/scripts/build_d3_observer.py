"""Compile a read-only boundary probe from the pinned D1 observation source."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("d1_tree","d2_oracle","new_dir"):
        p.add_argument(name,type=Path)
    a=p.parse_args()
    tree=a.d1_tree.resolve()
    oracle=a.d2_oracle.resolve()
    out=a.new_dir.resolve()
    out.mkdir(parents=True,exist_ok=False)
    source=(oracle/"ClosureSolver.cc").read_text()
    helper=r"""
template<class C> static void theory_observation(char tag,const C &clause)
{
    static FILE *file=std::fopen("native-theory.tsv","wbx");
    if(!file) std::abort();
    std::fputc(tag,file);
    for(int i=0;i<clause.size();++i) std::fprintf(file,"\t%d",clause[i].x);
    std::fputc('\n',file);
}
"""
    replacements=[
        ("using namespace Minisat;","using namespace Minisat;\n"+helper),
        ("confl = ca.alloc(minisat_lv, true);","confl = ca.alloc(minisat_lv, true);\n            theory_observation('C',minisat_lv);"),
        ("        if (learnt_clause.size() == 1)\n        {","        theory_observation('A',learnt_clause);\n        if (learnt_clause.size() == 1)\n        {")]
    for old,new in replacements:
        if source.count(old)!=1:raise ValueError(old)
        source=source.replace(old,new)
    file=out/"ClosureSolver.cc"
    file.write_text(source)
    compile_cmd,link=json.loads((oracle/"recipes.json").read_text())
    def relocate(command):
        return [word.replace(str(oracle)+"/",str(out)+"/") for word in command]
    env=dict(os.environ,PATH="/usr/bin:/bin",LC_ALL="C")
    subprocess.run(relocate(compile_cmd),cwd=tree/"src/solvers",env=env,check=True)
    subprocess.run(relocate(link),cwd=tree/"src/cbmc",env=env,check=True)
    (out/"recipes.json").write_text(json.dumps([relocate(compile_cmd),relocate(link)],indent=2)+"\n")


if __name__=="__main__":main()
