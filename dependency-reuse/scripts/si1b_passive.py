"""Private compile-time taps for an exact comparison in the native no-manifest encoding."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import struct
from cases42 import load
from run_stock import BASE, ENV, run, save, sha
from si1b_catalog import check

UNITS=("goto-checker/bmc_util.cpp","goto-checker/goto_symex_property_decider.cpp","goto-symex/symex_target_equation.cpp",
       "solvers/sat/satcheck_minisat2.cpp","solvers/sat/cnf.cpp","solvers/prop/prop_conv_solver.cpp","solvers/flattening/boolbv.cpp")
def patch(name,t):
    if "dependency_manifest::scopet scope(" in t:t=t.replace("dependency_manifest::scopet scope(","si_tap::Scope scope(")
    if name.endswith("bmc_util.cpp"):
        first=t.index("else if(equation.use_deagle_closure)");end=t.index("else if(equation.use_deagle_icd)",first)
        block=t[first:end].replace("literalt guard = decision_procedure.convert(e_it->guard);",
        'std::fprintf(si_tap::log(),"[\\t%s\\n",name.c_str());\n        literalt guard = decision_procedure.convert(e_it->guard);\n        std::fputs("]\\n",si_tap::log());')
        t=t[:first]+block+t[end:]
    if name.endswith("cnf.cpp"):
        t=t.replace("if(dependency_manifest::stream)","if(true)").replace("dependency_manifest::gate(","si_tap::gate(")
        for sig,width in [("literalt cnft::new_variable()","1"),("bvt cnft::new_variables(std::size_t width)","width")]:
            mark=sig+"\n{";check(t.count(mark)==1,"allocation anchor")
            t=t.replace(mark,mark+'\n  std::fprintf(si_tap::log(),"NVAR\\t%zu\\t%zu\\n",size_t(_no_variables),size_t('+width+'));')
    if name.endswith(("prop_conv_solver.cpp","boolbv.cpp")):
        bv=name.endswith("boolbv.cpp");var="cache_result" if bv else "result"
        mark=f"auto &cache_entry = {var}.first->second;"
        check(t.count(mark)==1,"cache anchor")
        t=t.replace(mark,mark+"\n  si_tap::cache('"+("V" if bv else "B")+"',&cache_entry,"+var+".second,id2string(expr.id()),prop.no_variables());")
    if name.endswith("satcheck_minisat2.cpp"):
        anchor="if(!dependency_manifest::stream) return;\n  solver->observe_input"
        check(t.count(anchor)==1,"input anchor")
        t=t.replace('std::fprintf(f, "C\\t%c", dependency_manifest::scope);','std::fprintf(f, "C\\t%c", si_tap::scope());')
        t=t.replace(anchor,"solver->observe_input",1).replace("auto *f = dependency_manifest::stream;","auto *f = si_tap::log();",1)
        at="if(dependency_manifest::stream || (store && store->d3))"
        check(t.count(at)==1,"graph anchor");t=t.replace(at,"if(true)")
        t=t.replace("dependency_manifest::row(tag,fields);","si_tap::graph(tag,fields);")
        at="if(!dependency_manifest::d4_library.empty()) at_root_boundary();"
        t=t.replace(at,'std::fprintf(si_tap::log(),"QUERY\\t%zu",no_variables());\n'
                     '    for(const auto &a:assumptions) std::fprintf(si_tap::log(),"\\t%d",int(a.get()));\n'
                     '    std::fputc(\'\\n\',si_tap::log());std::fflush(nullptr);std::_Exit(75);\n    '+at)
    return '#include "si1b_passive.h"\n'+t

def build(tree,out):
    src=tree.resolve()/"src";out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    def unit(key):
        rel=Path(key);module=src/rel.parts[0];inp=rel.relative_to(rel.parts[0]);copy=out/rel
        copy.parent.mkdir(parents=True,exist_ok=True);copy.write_text(patch(key,(src/rel).read_text()))
        lines=subprocess.check_output(["make","-n","-W",str(inp),str(inp.with_suffix(".o"))],cwd=module,text=True)
        cmd,=[shlex.split(l) for l in lines.splitlines() if l.startswith("g++ ") and " -c " in l and shlex.split(l)[-1]==str(inp)]
        obj=copy.with_suffix(".o");cmd[cmd.index("-o")+1:]=[str(obj),str(copy),"-I",str((src/rel).parent),"-I",str(BASE/"stable-identity")]
        subprocess.run(cmd,cwd=module,check=True);return str(obj)
    with ThreadPoolExecutor(5) as pool:objects=list(pool.map(unit,UNITS))
    lines=subprocess.check_output(["make","-n","-W","cbmc_parse_options.o","deagle_exe"],cwd=src/"cbmc",text=True)
    cmd,=[shlex.split(l) for l in lines.splitlines() if l.startswith("g++ ")]
    cmd[cmd.index("-o")+1]=str(out/"deagle")
    for module in {Path(u).parts[0] for u in UNITS}:
        archive=src/module/(module+".a")
        members=subprocess.check_output(["ar","t",str(archive)],text=True).splitlines()
        replacements={(src/u).with_suffix(".o").resolve():o for u,o in zip(UNITS,objects) if Path(u).parts[0]==module}
        check(set(replacements)<={Path(m).resolve() for m in members},"missing archive member")
        private=out/(module+"-passive.a")
        if private.exists():private.unlink()
        subprocess.run(["ar","crsT",str(private),*[replacements.get(Path(m).resolve(),m) for m in members]],check=True)
        cmd[cmd.index("../"+module+"/"+module+".a")]=str(private)
    subprocess.run(cmd,cwd=src/"cbmc",check=True)
    save(out/"build.json",dict(parent=sha(src/"cbmc/deagle_exe"),observer=sha(out/"deagle"),
                                source={k:sha(out/k) for k in UNITS},header=sha(BASE/"stable-identity/si1b_passive.h")))

def digest(path):
    allocation=hashlib.sha256();scopes=defaultdict(hashlib.sha256);scope_counts=Counter()
    streams=defaultdict(hashlib.sha256);ordered=hashlib.sha256();counts=Counter();cache_ids={};guard=None;blocks={};seq=[]
    for row in path.open("rb"):
        t,*v=row.rstrip(b"\n").split(b"\t")
        if t==b"[":
            check(guard is None and v[0] not in blocks,"duplicate guard visit");guard=v[0];blocks[guard]=[];seq.append(guard);continue
        if t==b"]":
            check(guard is not None,"unexpected guard end");guard=None;continue
        if t==b"NVAR":allocation.update(struct.pack("<II",*map(int,v)))
        if t==b"C":scopes[v[0].decode()].update(row);scope_counts[v[0].decode()]+=1
        if t==b"K":
            kind,addr,miss,op,n=v;key=kind,addr
            if miss==b"1":
                check(key not in cache_ids,"cache address reused without clearing");cache_ids[key]=len(cache_ids)+1
            check(key in cache_ids,"cache hit before creation")
            row=b"\t".join([t,kind,str(cache_ids[key]).encode(),miss,op,n])+b"\n"
        counts[t.decode()]+=1;streams[t.decode()].update(row)
        if guard is not None:
            check(t==b"K" and v[2]==b"0","guard visit changed encoding state")
            blocks[guard].append(row)
        else:ordered.update(row)
    check(guard is None and counts["QUERY"]==1 and scope_counts["B"] and scope_counts["Q"],"first query or scopes incomplete")
    grouped=hashlib.sha256()
    for g in sorted(blocks):
        grouped.update(g+b"\n");grouped.update(b"".join(blocks[g]))
    return dict(allocation_ranges=allocation.hexdigest(),scope_counts=scope_counts,scope_streams={k:v.hexdigest() for k,v in scopes.items()},ordered_outside_guard=ordered.hexdigest(),guard_hits_by_named_event=grouped.hexdigest(),
                guard_visit_order=hashlib.sha256(b"\n".join(seq)).hexdigest(),guard_events=len(seq),
                guard_hits=sum(len(v) for v in blocks.values()),rows=counts,cache_instances=len(cache_ids),
                streams={t:h.hexdigest() for t,h in streams.items()})

def compare_taps(root,matrix,stock,enhanced):
    # Separate diagnostic observers from the CPU-0 cost arm.
    import run_stock
    run_stock.CPU=2
    for case,spec in load().items():
        for side in ("P0","P1"):
            result={}
            for label,binary in (("original",stock),("off",enhanced),("shadow",enhanced)):
                p=root/case/side/label
                for k in list(ENV):
                    if k.startswith("DEAGLE_SI1B"):del ENV[k]
                if label=="shadow":
                    ENV["DEAGLE_SI1B_CATALOG"]=str(p/"native.bin")
                    ENV["DEAGLE_SI1B_TOKENS"]=str(matrix/case/"source"/(side+".tokens"))
                if not (p/"run.json").exists():run(binary,spec,case,side,p,sha(binary))
                check(json.loads((p/"run.json").read_bytes())["exit_code"]==75,"unexpected passive exit")
                result[label]=digest(p/"work/tap.tsv")
            for label in ("off","shadow"):
                x,y=result["original"],result[label]
                check(all(x[k]==y[k] for k in ("ordered_outside_guard","guard_hits_by_named_event","guard_events","guard_hits","rows","cache_instances")),"native observation differs "+case+side+label)
                check(all(x["streams"][k]==v for k,v in y["streams"].items() if k!="K"),"ordered native/model stream differs")
            save(root/case/side/"receipt.json",result)
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest="action",required=True)
    x=sub.add_parser("build");x.add_argument("tree",type=Path);x.add_argument("output",type=Path)
    x=sub.add_parser("check")
    for k in ("root","matrix","original","enhanced"):x.add_argument(k,type=Path)
    a=p.parse_args()
    if a.action=="build":build(a.tree,a.output)
    else:compare_taps(*(p.resolve() for p in (a.root,a.matrix,a.original,a.enhanced)))
