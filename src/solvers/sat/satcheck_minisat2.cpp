/*******************************************************************\

Module:

Author: Daniel Kroening, kroening@kroening.com

\*******************************************************************/

#include "satcheck_minisat2.h"

#ifndef _WIN32
#  include <signal.h>
#  include <unistd.h>
#endif

#include <limits>

#include <util/invariant.h>
#include <util/dependency_manifest.h>
#include <util/run.h>
#include <sstream>
#include <util/make_unique.h>
#include <util/threeval.h>

#include <minisat/core/Solver.h>
#include <minisat/simp/SimpSolver.h>
#include "../minisat-2.2.1/minisat/core/ClosureSolver.h"
#include "../minisat-2.2.1/minisat/core/SegmentSolver.h"
#include "../minisat-2.2.1/minisat/core/MemoryModelSolver.h"

#ifndef HAVE_MINISAT2
#error "Expected HAVE_MINISAT2"
#endif

void convert(const bvt &bv, Minisat::vec<Minisat::Lit> &dest)
{
  PRECONDITION(
    bv.size() <= static_cast<std::size_t>(std::numeric_limits<int>::max()));
  dest.capacity(static_cast<int>(bv.size()));

  for(const auto &literal : bv)
  {
    if(!literal.is_false())
      dest.push(Minisat::mkLit(literal.var_no(), literal.sign()));
  }
}

template<typename T>
tvt satcheck_minisat2_baset<T>::l_get(literalt a) const
{
  if(a.is_true())
    return tvt(true);
  else if(a.is_false())
    return tvt(false);

  tvt result;

  if(a.var_no()>=(unsigned)solver->model.size())
    return tvt::unknown();

  using Minisat::lbool;

  if(solver->model[a.var_no()]==l_True)
    result=tvt(true);
  else if(solver->model[a.var_no()]==l_False)
    result=tvt(false);
  else
    return tvt::unknown();

  if(a.sign())
    result=!result;

  return result;
}

template<typename T>
void satcheck_minisat2_baset<T>::set_polarity(literalt a, bool value)
{
  PRECONDITION(!a.is_constant());

  using Minisat::lbool;

  try
  {
    add_variables();
    solver->setPolarity(a.var_no(), value ? l_True : l_False);
  }
  catch(Minisat::OutOfMemoryException)
  {
    log.error() << "SAT checker ran out of memory" << messaget::eom;
    status = statust::ERROR;
    throw std::bad_alloc();
  }
}

template<typename T>
void satcheck_minisat2_baset<T>::interrupt()
{
  solver->interrupt();
}

template<typename T>
void satcheck_minisat2_baset<T>::clear_interrupt()
{
  solver->clearInterrupt();
}

const std::string satcheck_minisat_no_simplifiert::solver_text()
{
  return "MiniSAT 2.2.1 without simplifier";
}

const std::string satcheck_minisat_simplifiert::solver_text()
{
  return "MiniSAT 2.2.1 with simplifier";
}

// __SZH_ADD_BEGIN__
deagle_closure_solvert::deagle_closure_solvert(message_handlert &handler)
  : satcheck_minisat2_baset<Minisat::ClosureSolver>(handler)
{
  solver->search_log=dependency_manifest::search_log;
  solver->opaque_theory43=dependency_manifest::opaque43;
  if(!dependency_manifest::boundary_trace.empty())
  {
    static FILE *trace=nullptr;
    if(trace || !(trace=std::fopen(dependency_manifest::boundary_trace.c_str(),"wbx")))
      throw std::runtime_error("expected a new writable boundary trace");
    solver->observe_boundary=[](unsigned k,const Minisat::vec<Minisat::Lit> &clause) {
      uint32_t n=clause.size();
      if(std::fwrite(&k,4,1,trace)!=1 || std::fwrite(&n,4,1,trace)!=1)
        throw std::runtime_error("boundary trace write failed");
      for(int i=0;i<clause.size();++i)if(std::fwrite(&clause[i].x,4,1,trace)!=1)
        throw std::runtime_error("boundary literal write failed");
    };
    dependency_manifest::finish_boundaries=[](){bool ok=std::fclose(trace)==0;trace=nullptr;return ok;};
  }
  if(!dependency_manifest::proof_path.empty())
  {
    static std::unique_ptr<Minisat::ProofStore> recording;
    if(recording || solver->nVars()!=0)
      throw std::runtime_error("D2 needs one fresh native Closure solver per archive");
    recording.reset(new Minisat::ProofStore(dependency_manifest::proof_path,&dependency_manifest::scope));
    recording->d3=dependency_manifest::theory_proofs;
    recording->triplets=dependency_manifest::triplets;
    recording->eager_triplets=dependency_manifest::eager_triplets;
    recording->compact=dependency_manifest::compact_proof;
    recording->quality=(dependency_manifest::quality42 || dependency_manifest::light42) && !dependency_manifest::no_quality43;
    if(dependency_manifest::light42)recording->enableLight();
    solver->proof=recording.get();
    dependency_manifest::finish_proof=[](int status) { return recording->write(status); };
  }
  if(!dependency_manifest::dense_path.empty())
  {
    static std::unique_ptr<Minisat::DependencyTags> recording;
    if(recording || solver->nVars()!=0)throw std::runtime_error("compact requires a fresh native solver");
    recording.reset(new Minisat::DependencyTags(dependency_manifest::dense_path,&dependency_manifest::scope,
                                                *dependency_manifest::group_sources));
    recording->dual=solver->proof;
    solver->dense=recording.get();
    dependency_manifest::finish_dense=[](int status){return recording->finish(status);};
  }
  if(!dependency_manifest::stream) return;
  solver->observe_input = [](const Minisat::vec<Minisat::Lit> &ps) {
    auto *f = dependency_manifest::stream;
    std::fprintf(f, "C\t%c", dependency_manifest::scope);
    for(int i = 0; i < ps.size(); ++i) std::fprintf(f, "\t%d", ps[i].x);
    std::fputc('\n', f);
  };
  solver->observe_co = [](int a, int b, Minisat::Lit x, Minisat::Lit y, Minisat::Lit g, Minisat::Lit h) {
    std::fprintf(dependency_manifest::stream, "CO\t%d\t%d\t%d\t%d\t%d\t%d\n", a,b,x.x,y.x,g.x,h.x);
  };
}

void deagle_closure_solvert::at_root_boundary()
{
  namespace dm=dependency_manifest;
  if(imported) return; // Later property queries keep the same permanent learnt DB.
  if(!dm::stream || !solver->graph_ready || solver->nVars()!=int(no_variables()))
    throw std::runtime_error("D4 requires the current solver's installed graph, variables and input stream");
  dm::row("READY",{"D4-P1-v1"});
  const bool write_ok=std::ferror(dm::stream)==0;
  const bool close_ok=std::fclose(dm::stream)==0;
  dm::stream=nullptr;
  if(!write_ok || !close_ok) throw std::runtime_error("D4 manifest write failed");
  solver->observe_input=nullptr;
  solver->observe_co=nullptr;
  const auto &dir=dm::d4_out;
  const std::string worker=dm::d4_tools+"/d4_prepare.py";
  if(run("python3",{"python3",worker,dm::d4_library,dir,dm::d4_tools},
         "",dir+"/prepare.stdout",dir+"/prepare.stderr")!=0)
    throw std::runtime_error("D4 live model preparation failed; see "+dir+"/prepare.stderr");

  imported.reset(new Minisat::ClauseImports);
  imported->read(dir+"/ready.tsv",solver->nVars());
  const int roots=solver->nAssigns();
  const bool was_ok=solver->okay();
  const auto before=solver->work();
  solver->importAtRoot(*imported,dm::d4_mode=="reuse");
  std::ofstream log(dir+"/import-time.tsv");
  log.exceptions(std::ios::failbit|std::ios::badbit);
  log<<"import_ns\t"<<imported->import_ns<<"\nroot_before\t"<<roots<<"\nroot_after\t"<<solver->nAssigns()<<"\n";
  log<<"root_conflicts\t"<<(was_ok && !solver->okay())<<"\n";
  const auto after=solver->work();
  const char *names[]={"conflicts","decisions","propagations","theory_propagations","theory_cycles"};
  for(size_t i=0;i<after.size();++i)
    log<<"root_"<<names[i]<<"_counter_delta\t"<<(after[i]-before[i])<<"\n";
  log.close();
}

propt::resultt deagle_closure_solvert::do_prop_solve()
{
  auto result=satcheck_minisat2_baset<Minisat::ClosureSolver>::do_prop_solve();
  if(imported)
  {
    imported->write(dependency_manifest::d4_out);
    std::ofstream out(dependency_manifest::d4_out+"/cumulative-work.tsv",std::ios::app);
    out.exceptions(std::ios::failbit|std::ios::badbit);
    for(auto value:solver->work()) out<<value<<'\t';
    out<<solver->okay()<<'\n';
    out.close();
  }
  return result;
}

const std::string deagle_closure_solvert::solver_text()
{
  return "Deagle's Closure Solver";
}

const std::string deagle_icd_solvert::solver_text()
{
  return "Deagle's ICD Solver";
}

const std::string deagle_segment_solvert::solver_text()
{
  return "Deagle's Segment Solver";
}

const std::string memory_model_solvert::solver_text()
{
  return "Deagle's Memory Model Solver";
}
// __SZH_ADD_END__

template<typename T>
void satcheck_minisat2_baset<T>::add_variables()
{
  while((unsigned)solver->nVars()<no_variables())
    solver->newVar();
}

template<typename T>
void satcheck_minisat2_baset<T>::lcnf(const bvt &bv)
{
  try
  {
    add_variables();

    for(const auto &literal : bv)
    {
      if(literal.is_true())
        return;
      else if(!literal.is_false())
      {
        INVARIANT(
          literal.var_no() < (unsigned)solver->nVars(),
          "variable not added yet");
      }
    }

    Minisat::vec<Minisat::Lit> c;

    convert(bv, c);

    // Note the underscore.
    // Add a clause to the solver without making superflous internal copy.

    solver->addClause_(c);

    if(solver_hardness)
    {
      // To map clauses to lines of program code, track clause indices in the
      // dimacs cnf output. Dimacs output is generated after processing
      // clauses to remove duplicates and clauses that are trivially true.
      // Here, a clause is checked to see if it can be thus eliminated. If
      // not, add the clause index to list of clauses in
      // solver_hardnesst::register_clause().
      static size_t cnf_clause_index = 0;
      bvt cnf;
      bool clause_removed = process_clause(bv, cnf);

      if(!clause_removed)
        cnf_clause_index++;

      solver_hardness->register_clause(
        bv, cnf, cnf_clause_index, !clause_removed);
    }

    clause_counter++;
  }
  catch(const Minisat::OutOfMemoryException &)
  {
    log.error() << "SAT checker ran out of memory" << messaget::eom;
    status = statust::ERROR;
    throw std::bad_alloc();
  }
}

#ifndef _WIN32

static Minisat::Solver *solver_to_interrupt=nullptr;

static void interrupt_solver(int signum)
{
  (void)signum; // unused parameter -- just removing the name trips up cpplint
  solver_to_interrupt->interrupt();
}

#endif

template <typename T>
propt::resultt satcheck_minisat2_baset<T>::do_prop_solve()
{
  PRECONDITION(status != statust::ERROR);

  if(dependency_manifest::stream)
  {
    std::fprintf(dependency_manifest::stream, "N\t%zu", no_variables());
    for(const auto &a : assumptions) std::fprintf(dependency_manifest::stream, "\t%d", int(a.get()));
    std::fputc('\n', dependency_manifest::stream);
  }
  log.statistics() << (no_variables() - 1) << " variables, "
                   << solver->nClauses() << " clauses" << messaget::eom;

  try
  {
    add_variables();
    if(!dependency_manifest::d4_library.empty()) at_root_boundary();

    if(!solver->okay())
    {
      log.status() << "SAT checker inconsistent: instance is UNSATISFIABLE"
                   << messaget::eom;
      status = statust::UNSAT;
      return resultt::P_UNSATISFIABLE;
    }

    // if assumptions contains false, we need this to be UNSAT
    for(const auto &assumption : assumptions)
    {
      if(assumption.is_false())
      {
        log.status() << "got FALSE as assumption: instance is UNSATISFIABLE"
                     << messaget::eom;
        status = statust::UNSAT;
        return resultt::P_UNSATISFIABLE;
      }
    }

    Minisat::vec<Minisat::Lit> solver_assumptions;
    convert(assumptions, solver_assumptions);

    using Minisat::lbool;

#ifndef _WIN32

    void (*old_handler)(int) = SIG_ERR;

    if(time_limit_seconds != 0)
    {
      solver_to_interrupt = solver.get();
      old_handler = signal(SIGALRM, interrupt_solver);
      if(old_handler == SIG_ERR)
        log.warning() << "Failed to set solver time limit" << messaget::eom;
      else
        alarm(time_limit_seconds);
    }

    lbool solver_result = solver->solveLimited(solver_assumptions);

    if(old_handler != SIG_ERR)
    {
      alarm(0);
      signal(SIGALRM, old_handler);
      solver_to_interrupt = solver.get();
    }

#else // _WIN32

    if(time_limit_seconds != 0)
    {
      log.warning() << "Time limit ignored (not supported on Win32 yet)"
                    << messaget::eom;
    }

    lbool solver_result = solver->solve(solver_assumptions) ? l_True : l_False;

#endif

    if(solver_result == l_True)
    {
      log.status() << "SAT checker: instance is SATISFIABLE" << messaget::eom;
      CHECK_RETURN(solver->model.size() > 0);
      status = statust::SAT;
      return resultt::P_SATISFIABLE;
    }

    if(solver_result == l_False)
    {
      log.status() << "SAT checker: instance is UNSATISFIABLE" << messaget::eom;
      status = statust::UNSAT;
      return resultt::P_UNSATISFIABLE;
    }

    log.status() << "SAT checker: timed out or other error" << messaget::eom;
    status = statust::ERROR;
    return resultt::P_ERROR;
  }
  catch(const Minisat::OutOfMemoryException &)
  {
    log.error() << "SAT checker ran out of memory" << messaget::eom;
    status=statust::ERROR;
    return resultt::P_ERROR;
  }
}

template<typename T>
void satcheck_minisat2_baset<T>::set_assignment(literalt a, bool value)
{
  PRECONDITION(!a.is_constant());

  try
  {
    unsigned v = a.var_no();
    bool sign = a.sign();

    // MiniSat2 kills the model in case of UNSAT
    solver->model.growTo(v + 1);
    value ^= sign;
    solver->model[v] = Minisat::lbool(value);
  }
  catch(const Minisat::OutOfMemoryException &)
  {
    log.error() << "SAT checker ran out of memory" << messaget::eom;
    status = statust::ERROR;
    throw std::bad_alloc();
  }
}

template <typename T>
satcheck_minisat2_baset<T>::satcheck_minisat2_baset(
  message_handlert &message_handler)
  : cnf_solvert(message_handler),
    solver(util_make_unique<T>()),
    time_limit_seconds(0)
{
}

template <typename T>
satcheck_minisat2_baset<T>::~satcheck_minisat2_baset() = default;

template<typename T>
bool satcheck_minisat2_baset<T>::is_in_conflict(literalt a) const
{
  int v=a.var_no();

  for(int i=0; i<solver->conflict.size(); i++)
    if(var(solver->conflict[i])==v)
      return true;

  return false;
}

template<typename T>
void satcheck_minisat2_baset<T>::set_assumptions(const bvt &bv)
{
  // We filter out 'true' assumptions which cause an assertion violation
  // in Minisat2.
  assumptions.clear();
  for(const auto &assumption : bv)
  {
    if(!assumption.is_true())
    {
      assumptions.push_back(assumption);
    }
  }
}

template class satcheck_minisat2_baset<Minisat::Solver>;
template class satcheck_minisat2_baset<Minisat::SimpSolver>;
template class satcheck_minisat2_baset<Minisat::ClosureSolver>;
template class satcheck_minisat2_baset<Minisat::ICDSolver>;
template class satcheck_minisat2_baset<Minisat::SegmentSolver>;
template class satcheck_minisat2_baset<Minisat::MemoryModelSolver>;

void satcheck_minisat_simplifiert::set_frozen(literalt a)
{
  try
  {
    if(!a.is_constant())
    {
      add_variables();
      solver->setFrozen(a.var_no(), true);
    }
  }
  catch(const Minisat::OutOfMemoryException &)
  {
    log.error() << "SAT checker ran out of memory" << messaget::eom;
    status = statust::ERROR;
    throw std::bad_alloc();
  }
}

bool satcheck_minisat_simplifiert::is_eliminated(literalt a) const
{
  PRECONDITION(!a.is_constant());

  return solver->isEliminated(a.var_no());
}

void deagle_closure_solvert::save_raw_graph(oc_edge_tablet& _oc_edge_table, oc_guard_mapt& _oc_guard_map, oc_location_mapt& _oc_location_map, std::map<std::string, int>& _oc_result_order)
{
  solver->save_raw_graph(_oc_edge_table, _oc_guard_map, _oc_location_map, _oc_result_order);
  auto *store=solver->proof;
  if(dependency_manifest::stream || (store && store->d3))
  {
    auto emit=[&](const char *tag,const std::vector<std::string> &fields) {
      if(!store || !store->d3)
      {
        dependency_manifest::row(tag,fields);
        return;
      }
      std::string line(tag);
      for(const auto &field:fields) { line+='\t'; line+=dependency_manifest::escape(field); }
      line+='\n';
      store->graph_receipt.insert(store->graph_receipt.end(),line.begin(),line.end());
      if(dependency_manifest::stream)
        std::fwrite(line.data(),1,line.size(),dependency_manifest::stream);
    };
    const auto &graph = solver->declaration_graph();
    std::map<std::string, int> node_ids;
    for(size_t i = 0; i < graph.nodes.size(); ++i)
    {
      const auto &n = graph.nodes[i];
      node_ids.emplace(n.name, int(i));
      if(n.atomic_parent == int(i))
        for(int item : n.atomic_items)
          emit("MEMBER", {std::to_string(i), std::to_string(item)});
      emit("NODE", {std::to_string(i), n.name, std::to_string(n.address),
        n.is_read ? "r" : "", n.is_write ? "w" : "", std::to_string(n.atomic_parent)});
      for(int j : n.atomic_in) emit("IN", {std::to_string(i), std::to_string(j)});
      for(int j : n.atomic_out) emit("OUT", {std::to_string(i), std::to_string(j)});
    }
    for(const auto &edge : _oc_edge_table)
    {
      auto binding = graph.observed_binding(edge.second.first);
      auto a = node_ids.find(edge.first.first), b = node_ids.find(edge.first.second);
      auto pair_lit = a == node_ids.end() || b == node_ids.end() ? Minisat::lit_Error :
        graph.observed_pair_binding(a->second, b->second);
      emit("EDGE", {edge.second.second, edge.first.first, edge.first.second,
        std::to_string(edge.second.first.x), std::to_string(binding.first.first), std::to_string(binding.first.second), std::to_string(pair_lit.x)});
    }
    for(const auto &g : _oc_guard_map)
      emit("GUARD", {g.first, std::to_string(g.second.x)});
  }
}

void deagle_icd_solvert::save_raw_graph(oc_edge_tablet& _oc_edge_table, std::map<std::string, int>& _oc_result_order)
{
  solver->save_raw_graph(_oc_edge_table, _oc_result_order);
}

void deagle_segment_solvert::save_raw_graph(oc_edge_tablet& _oc_edge_table, oc_guard_mapt& _oc_guard_map, oc_location_mapt& _oc_location_map, std::map<std::string, int>& _oc_result_order)
{
  solver->save_raw_graph(_oc_edge_table, _oc_guard_map, _oc_location_map, _oc_result_order);
}

void memory_model_solvert::save_raw_graph(oc_edge_tablet& _oc_edge_table, oc_label_tablet& _oc_label_table, cat_modulet& _cat_module)
{
  solver->save_raw_graph(_oc_edge_table, _oc_label_table, _cat_module);
}
