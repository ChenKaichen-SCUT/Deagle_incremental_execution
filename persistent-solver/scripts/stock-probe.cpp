// PI-0 diagnostic of the unchanged solver, on one Boolean formula and an empty graph.
#include <cstdlib>
#include <iostream>
#include <minisat/core/ClosureSolver.h>

using namespace Minisat;

struct NativeLayout : Solver
{
    static void print()
    {
        std::cout << "LAYOUT " << sizeof(Lit) << ' ' << sizeof(CRef) << ' '
                  << sizeof(Clause) << ' ' << sizeof(Watcher) << ' ' << sizeof(VarData)
                  << ' ' << sizeof(vec<Watcher>) << ' ' << sizeof(lbool) << ' '
                  << sizeof(double) << ' ' << sizeof(int) << '\n';
    }
};

int main()
{
    NativeLayout::print();
    ClosureSolver solver;
    oc_edge_tablet edges;
    oc_guard_mapt guards;
    oc_location_mapt locations;
    std::map<std::string, int> order;
    solver.save_raw_graph(edges, guards, locations, order);
    Lit x = mkLit(solver.newVar()), y = mkLit(solver.newVar());
    if (!solver.addClause(x, y))
        return EXIT_FAILURE;

    vec<Lit> assumptions;
    assumptions.push(~x);
    assumptions.push(~y);
    lbool status = solver.solveLimited(assumptions);
    bool core_x = false, core_y = false;
    for (int i = 0; i < solver.conflict.size(); ++i) {
        core_x |= solver.conflict[i] == x;
        core_y |= solver.conflict[i] == y;
    }
    std::cout << "ASSUMPTION_UNSAT " << (status == l_False) << ' ' << solver.okay()
              << ' ' << solver.conflict.size() << ' ' << core_x << ' ' << core_y << '\n';
    if (status != l_False || !solver.okay() || solver.conflict.size() != 2 || !core_x || !core_y)
        return EXIT_FAILURE;

    assumptions.pop();
    status = solver.solveLimited(assumptions);
    if (status != l_True || !solver.okay() || solver.modelValue(x) != l_False ||
        solver.modelValue(y) != l_True)
        return EXIT_FAILURE;
    std::cout << "NEXT_QUERY_SAT x=false y=true\n";

    vec<Lit> empty;
    if (solver.addClause_(empty) || solver.okay() || solver.solveLimited(empty) != l_False)
        return EXIT_FAILURE;
    std::cout << "PERMANENT_EMPTY_CLAUSE ok=false UNSAT\n";
}
