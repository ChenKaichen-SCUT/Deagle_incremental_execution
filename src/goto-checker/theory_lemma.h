#ifndef CPROVER_GOTO_CHECKER_THEORY_LEMMA_H
#define CPROVER_GOTO_CHECKER_THEORY_LEMMA_H
#include <solvers/sat/satcheck_minisat2.h>

void record_fresh_order_solver(deagle_closure_solvert &);
void prepare_order_lemma_cache(
  deagle_closure_solvert &, const oc_edge_tablet &, const oc_guard_mapt &, const oc_location_mapt &);
#endif
