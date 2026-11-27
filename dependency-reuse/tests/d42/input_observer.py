"""Diagnostic, externally linked observers for the original inputs and installed graph, also with recording off."""
import argparse,collections,hashlib,json,shlex,subprocess,sys
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    for n in ("tree","recipe","out"):p.add_argument(n,type=Path)
    p.add_argument("--side",choices=("old","new"),default="old")
    a=p.parse_args();tree=a.tree.resolve();out=a.out.resolve();out.mkdir();cmd0,link=json.loads(a.recipe.read_text())
    sources=tree/"minisat-2.2.1/minisat/core"
    for name in ("Solver","ClosureSolver"):
        src=sources/(name+".cc");s=src.read_text()
        if name=="Solver":
            where="    if (observe_input) observe_input(ps);"
            code=r'''    static FILE *capture=std::fopen("inputs.tsv","wb");std::fputs("C",capture);
    for(int k=0;k<ps.size();++k)std::fprintf(capture,"\t%d",ps[k].x);std::fputc('\n',capture);
'''
        else:
            where="    oc_edge_table = _oc_edge_table;"
            code=r'''    FILE *graph_file=std::fopen("raw-graph.tsv","wb");
    for(const auto &p:_oc_edge_table)std::fprintf(graph_file,"E\t%s\t%s\t%s\t%d\n",p.second.second.c_str(),p.first.first.c_str(),p.first.second.c_str(),p.second.first.x);
    for(const auto &p:_oc_guard_map)std::fprintf(graph_file,"H\t%s\t%d\n",p.first.c_str(),p.second.x);
    for(const auto &p:_oc_location_map)std::fprintf(graph_file,"L\t%s\t%d\n",p.first.c_str(),p.second);
    std::fclose(graph_file);
'''
            entry="    // Search:"
            assert s.count(entry)==1
            s=s.replace(entry,r'''    FILE *boundary42=std::fopen("query.tsv","ab");
    std::fprintf(boundary42,"%d",nVars());
    for(int k=0;k<assumptions.size();++k)std::fprintf(boundary42,"\t%d",assumptions[k].x);
    std::fputc('\n',boundary42);std::fclose(boundary42);
'''+entry)
            at="        ProofId cert=0;"
            assert s.count(at)==1
            s=s.replace(at,r'''        static unsigned observed=0;
        if(++observed==4300){std::fflush(nullptr);std::_Exit(73);}
'''+at)
        assert s.count(where)==(1 if name=="Solver" else 2);s=s.replace(where,code+where,1)
        copy=out/(name+".cc");copy.write_text(s)
        cmd=list(cmd0);cmd[cmd.index("-o")+1:]=[str(out/(name+".o")),str(copy),"-I",str(sources)]
        subprocess.run(cmd,cwd=tree/"src/solvers",check=True)
    link[link.index("-o")+1]=str(out/"deagle_exe")
    pos=link.index("-Wl,--start-group")-1
    link[pos:pos+1]=[str(out/"ClosureSolver.o"),str(out/"Solver.o")]
    subprocess.run(link,cwd=tree/"src/cbmc",check=True)
    hist=tree/"dependency-reuse/bench/fib-snapshot-11";options=json.loads((hist/"task.yaml").read_text())["argv"]
    for arm,flags in (("off",[]),("manifest",["--d1-manifest","metadata.tsv"]),("audit",["--d1-manifest","metadata.tsv","--d3-layouts","--d41-identities","--d3-proof","proof.bin","--d41-triplets"])):
        dest=out/arm;dest.mkdir();(dest/"program.i").write_bytes((hist/a.side/"program.i").read_bytes())
        with (dest/"stdout").open("w") as stdout,(dest/"stderr").open("w") as stderr:
            r=subprocess.run([out/"deagle_exe",*flags,*options],cwd=dest,stdout=stdout,stderr=stderr)
        assert r.returncode==73
    result={}
    for name in ("inputs.tsv","raw-graph.tsv","query.tsv"):
        base=(out/"off"/name).read_bytes().splitlines()
        for mode in ("manifest","audit"):
            actual=(out/mode/name).read_bytes().splitlines()
            old=collections.Counter(base);new=collections.Counter(actual)
            plus=list((new-old).elements());minus=list((old-new).elements())
            result[f"{name}/{mode}"]=dict(rows=[len(base),len(actual)],same_order=base==actual,same_multiset=old==new,
                first_diff=next(([i,x.decode(),y.decode()] for i,(x,y) in enumerate(zip(base,actual),1) if x!=y),None),
                added_count=len(plus),removed_count=len(minus),added=[x.decode() for x in plus[:5]],removed=[x.decode() for x in minus[:5]])
    (out/"comparison.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
if __name__=="__main__":main()
