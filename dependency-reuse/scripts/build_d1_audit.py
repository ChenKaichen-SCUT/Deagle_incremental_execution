"""Link two diagnostic object files before the original archives; never edit a built tree."""
import argparse
import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("tree", "build_log", "new_directory"):
        p.add_argument(arg, type=Path)
    args = p.parse_args()
    tree, out = args.tree.resolve(), args.new_directory.resolve()
    out.mkdir(parents=True, exist_ok=False)
    lines = args.build_log.read_text().splitlines()
    # One log per build. The compile/link recipes must be the native recipes.
    env = dict(os.environ, PATH="/usr/bin:/bin", LC_ALL="C")
    receipt = []
    func = r'''
#include <cstdio>
#include <cstdlib>
static FILE *d1_audit(const char *kind)
{
    std::string path = std::string("audit-") + kind;
    FILE *f = std::fopen(path.c_str(), "wbx");
    if(!f) std::abort();
    return f;
}
'''
    insertions = {
        "Solver": {
            "int v = nVars();": r'''static FILE *vars = d1_audit("vars");
    fprintf(vars, "%d %d %d\n", nVars(), toInt(upol), int(dvar));''',
            "bool Solver::addClause_(vec<Lit>& ps)\n{": r'''static FILE *clause_log = d1_audit("clauses");
    fprintf(clause_log, "%d", ps.size());
    for(int i = 0; i < ps.size(); ++i) fprintf(clause_log, " %d", ps[i].x);
    fputc('\n', clause_log);'''},
        "ClosureSolver": {
            "std::map<std::string, int>& _oc_result_order)\n{": r'''static FILE *edges = d1_audit("graph");
    for(const auto &e : _oc_edge_table)
        fprintf(edges, "E %s\t%s\t%s\t%d\n", e.first.first.c_str(), e.first.second.c_str(), e.second.second.c_str(), e.second.first.x);
    for(const auto &g : _oc_guard_map) fprintf(edges, "G %s\t%d\n", g.first.c_str(), g.second.x);
    for(const auto &l : _oc_location_map) fprintf(edges, "L %s\t%d\n", l.first.c_str(), l.second);
    for(const auto &r : _oc_result_order) fprintf(edges, "R %s\t%d\n", r.first.c_str(), r.second);''',
            "lbool ClosureSolver::solve_()\n{": r'''static FILE *init = d1_audit("init");
    fprintf(init, "I %a %a %a %a %d %d %d %d %d %d %a %a %a\n", var_decay, clause_decay,
        random_var_freq, random_seed, int(luby_restart), ccmin_mode, phase_saving, int(rnd_pol),
        int(rnd_init_act), restart_first, restart_inc, learntsize_factor, learntsize_inc);
    for(int i = 0; i < nVars(); ++i)
        fprintf(init, "V %d %d %d %d %d %a\n", i, int(polarity[i]), int(decision[i]), toInt(user_pol[i]), toInt(value(i)), activity[i]);
    for(int i = 0; i < order_heap.size(); ++i) fprintf(init, "H %d\n", order_heap[i]);
    for(int i = 0; i < trail.size(); ++i) fprintf(init, "T %d\n", trail[i].x);
    for(int i = 0; i < assumptions.size(); ++i) fprintf(init, "A %d\n", assumptions[i].x);'''}}
    objects = []
    for name, patches in insertions.items():
        part = Path("minisat-2.2.1/minisat/core") / (name + ".cc")
        source = (tree / part).read_text()
        for anchor, code in patches.items():
            if source.count(anchor) != 1:
                raise ValueError((name, anchor))
            source = source.replace(anchor, anchor + "\n    " + code)
        where = source.index("using namespace Minisat;")
        source = source[:where] + func + source[where:]
        copy = out / (name + ".cc")
        copy.write_text(source)
        obj = out / (name + ".o")
        objects.append(str(obj))
        cmd = shlex.split(next(l for l in lines if l.startswith("g++ -c ") and l.endswith("/" + str(part))))
        cmd[cmd.index("-o")+1:] = [str(obj), str(copy)]
        cmd.extend(["-I", str((tree / part).parent)])
        subprocess.run(cmd, cwd=tree/"src/solvers", check=True, env=env)
        receipt.append(cmd)
    link = shlex.split(next(l for l in lines if l.startswith("g++ ") and " -o deagle_exe " in l))
    link[link.index("-o")+1] = str(out/"deagle_exe")
    link[link.index("-Wl,--start-group"):link.index("-Wl,--start-group")] = objects
    subprocess.run(link, cwd=tree/"src/cbmc", check=True, env=env)
    receipt.append(link)
    (out/"recipes.json").write_text(json.dumps(dict(recipes=receipt, binary_sha256=hashlib.sha256(
        (out/"deagle_exe").read_bytes()).hexdigest()), indent=2))


if __name__ == "__main__":
    main()
