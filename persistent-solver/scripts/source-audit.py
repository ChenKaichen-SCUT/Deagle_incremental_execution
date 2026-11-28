"""Index source seams and executable SAT sinks at the pinned revisions, with original line numbers."""
import re
import subprocess
import sys
from pathlib import Path

from frozen import RESEARCH, UPSTREAM, digest, require, save

CORE = "minisat-2.2.1/minisat/core/"
FILES = {
    CORE + "Solver.cc": r"^\w+ Solver::(newVar|addClause_|propagate|simplify|analyzeFinal|reduceDB|removeClause|relocAll|garbageCollect|solve_|litRedundant)\(|return ok =|ok = false",
    CORE + "Solver.h": r"struct (VarData|Watcher) | newDecisionLevel | propagate | simplify | addClause_ ",
    CORE + "ClosureSolver.h": r"closure graph;|solveLimited\(|oc_result_order;|newDecisionLevel\(|cancelUntil\(",
    CORE + "ClosureSolver.cc": r"^ClosureSolver::|^(void|lbool|CRef) ClosureSolver::|\b(ok\s*=\s*false|ca\.alloc|uncheckedEnqueue|newVar\(|return l_False|analyzeFinal\(|graph\.pop_scope|graph\.use_available_info|graph\.final_check|graph\.remove_rf|cancelUntil\(0\)|oc_result_order\s*=)",
    CORE + "Closure.cc": r"^(void|bool|int) closure::(init|add_guard_literal|check_guard_literal|activate_apo|union_join|refine_atomic_atoms|add_trinary_pattern|check_trinary_pattern|activate_edge|activate_directed_edge|light_guard|push_scope|pop_scope|use_available_info|remove_rf|final_check|get_co_pairs|init_race|init_reasonable_edge)\(|closure::find_incomplete_co_pairs\(|solver->assign_literal\(|conflict_lv\s*=|write_order\.|oc_result_order->|#define PROPAGATE_INTENSITY",
    CORE + "Closure.h": r"trail_\w+_lim|id_to_address|lit_to_edge|guard_lit_to_node|triplets_to_check|rf_to_triplets|guard_to_triplets|co_pairs|conflict_lv|inactive_",
    CORE + "GraphTypes.cc": r"get_address\(|str_to_kind\(",
    "src/goto-checker/solver_factory.cpp": r"solver_factoryt::(get_solver|get_default)\(|make_satcheck_prop<deagle_closure_solvert>|set_decision_procedure\(",
    "src/goto-checker/bmc_util.cpp": r"prepare_property_decider\(|convert_goals\(|deagle_closure_solver.save_raw_graph|run_property_decider\(|property_decider\.(solve|add_constraint_from_goals|update_properties_status_from_goals)\(|build_goto_trace\(",
    "src/goto-checker/goto_symex_property_decider.cpp": r"goto_symex_property_decidert::(convert_goals|add_constraint_from_goals|solve|update_properties_status_from_goals)\(",
    "src/solvers/sat/satcheck_minisat2.cpp": r"satcheck_minisat2_baset(\s*\(|<T>::(l_get|set_polarity|interrupt|clear_interrupt|lcnf|add_variables|do_prop_solve|is_in_conflict|set_assumptions|set_assignment)\()|solver\(util_make_unique|solver->(addClause_|newVar|solveLimited|save_raw_graph|okay)\(",
    "src/solvers/prop/prop_conv_solver.cpp": r"prop_conv_solvert::(dec_solve|push|pop)\(|finish_eager_conversion\(|post_processing_done|prop\.prop_solve\(",
    "src/solvers/flattening/bv_pointers.cpp": r"bv_pointerst::finish_eager_conversion\(|post_process",
    "src/solvers/flattening/arrays.h": r"finish_eager_conversion",
    "src/goto-symex/build_goto_trace.cpp": r"oc_result_order",
    "src/goto-symex/memory_model_sc.cpp": r"memory_model_sct::operator\(|program_order\(|read_from\(|oc_edges|oc_guard_map",
    "src/goto-symex/partial_order_concurrency.cpp": r"partial_order_concurrencyt::build_event_lists\(",
}


def entry(repo, rev, path, pattern):
    raw = subprocess.check_output(["git", "-C", str(repo), "cat-file", "blob", rev + ":" + path])
    # These fixed source files use C/C++ comments. Preserve line positions when removing them.
    code = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group().count("\n"), raw.decode().replace("\r\n", "\n"), flags=re.S)
    rows = []
    for n, line in enumerate(code.splitlines(), 1):
        statement = line.partition("//")[0].strip()
        if re.search(pattern, statement):
            rows.append([n, statement])
    require(rows, path)
    return dict(source_sha256=digest(raw), entries=rows)


if __name__ == "__main__":
    repo, output = map(Path, sys.argv[1:])
    files = {p: entry(repo, UPSTREAM, p, pattern) for p, pattern in FILES.items()}
    cs = files[CORE + "ClosureSolver.cc"]["entries"]
    cl = files[CORE + "Closure.cc"]["entries"]
    for token, expected, source in (
        ("ca.alloc", [249, 526, 730, 799], cs), ("ok = false", [99, 150, 384], cs),
        ("uncheckedEnqueue(", [247, 253, 320, 471, 725, 739], cs),
        ("newVar()", [787], cs), ("solver->assign_literal(", [308, 321, 369, 570, 636, 1034], cl),
        ("conflict_lv =", [505, 514, 560], cl)):
        require([n for n, s in source if token in s] == expected, "sink inventory differs: " + token)
    importer = entry(repo, RESEARCH, CORE + "ClosureSolver.cc", r"::importAtRoot\(|if\(!graph_ready \|\| solves \|\|")
    save(output, dict(upstream=UPSTREAM, files=files, old_reference=RESEARCH, old_importer=importer))
