#include "../util/stage8_meter.h"
#include "theory_lemma.h"
#include <goto-symex/stage3_observer.h>
#include <util/json.h>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <stdexcept>
#ifdef __linux__
#include <sys/wait.h>
#include <unistd.h>
#endif

namespace
{
using clock_type = std::chrono::steady_clock;
json_numbert number(long long n) { return json_numbert(std::to_string(n)); }
long long elapsed(clock_type::time_point t)
{
  return std::chrono::duration_cast<std::chrono::nanoseconds>(clock_type::now()-t).count();
}
void write_json(const std::string &path, const jsont &doc)
{
  std::ofstream out(path);
  out << doc << '\n';
  out.close();
  if(!out) throw std::runtime_error("Cannot write theory evidence: "+path);
}

struct graph_atom
{
  Minisat::Lit literal;
  bool eligible;
};
struct import_row
{
  std::size_t id;
  bvt clause;
};

bool read_plan(const std::string &path, const std::vector<graph_atom> &slots,
               std::vector<import_row> &plan)
{
  std::ifstream in(path);
  std::string line;
  if(!in || !std::getline(in,line) || line!="stage5-local-bindings-v1") return false;
  while(std::getline(in,line))
  {
    std::istringstream row(line);
    import_row entry;
    std::size_t width;
    if(!(row>>entry.id>>width) || width<1 || width>slots.size() || entry.id!=plan.size()) return false;
    std::set<int> seen;
    for(std::size_t i=0;i<width;++i)
    {
      std::size_t index; int negative;
      if(!(row>>index>>negative) || index>=slots.size() || (negative!=0 && negative!=1)) return false;
      const auto &atom=slots[index];
      if(!atom.eligible || atom.literal.x<0) return false;
      auto lit=negative?~atom.literal:atom.literal;
      if(!seen.insert(Minisat::var(lit)).second) return false;
      entry.clause.emplace_back(Minisat::var(lit),Minisat::sign(lit));
    }
    std::string extra;
    if(row>>extra) return false;
    plan.push_back(std::move(entry));
  }
  return in.eof();
}

bool run_audit(const char *script, const std::string &directory)
{
  s8::Scope s8_timer(s8::lemma_worker);
#ifdef __linux__
  pid_t pid=fork();
  if(pid==0)
  {
    execl("/usr/bin/python3","python3","-B",script,"bind",directory.c_str(),static_cast<char *>(nullptr));
    std::_Exit(127);
  }
  int status=0;
  return pid>0 && waitpid(pid,&status,0)==pid && WIFEXITED(status) && WEXITSTATUS(status)==0;
#else
  (void)script; (void)directory;
  return false;
#endif
}

void submit(deagle_closure_solvert &adapter, const std::vector<import_row> &plan,
            const std::string &directory)
{
  s8::Scope s8_timer(s8::lemma_submit);
  auto start=clock_type::now();
  auto &solver=adapter.order_solver();
  json_arrayt rows;
  for(const auto &entry:plan)
  {
    json_objectt r;
    r["id"]=number(entry.id);
    r["clauses_before"]=number(solver.nClauses());
    r["assignments_before"]=number(solver.nAssigns());
    int before=solver.nClauses(), assigned=solver.nAssigns();
    bool okay=solver.okay();
    json_arrayt bound;
    for(const auto literal:entry.clause)
      bound.push_back(number(Minisat::mkLit(literal.var_no(),literal.sign()).x));
    r["candidate_literals"]=std::move(bound);
    if(okay) adapter.lcnf(entry.clause);
    std::string effect=!okay?"already_inconsistent":
      !solver.okay()?"contradiction":solver.nClauses()>before?"attached":
      solver.nAssigns()>assigned?"enqueued":"already_implied_at_root";
    r["effect"]=json_stringt(effect);
    r["clauses_after"]=number(solver.nClauses());
    r["assignments_after"]=number(solver.nAssigns());
    rows.push_back(std::move(r));
  }
  json_objectt output;
  output["site"]=json_stringt("ClosureSolver::solve_ before first search");
  output["api"]=json_stringt("satcheck_minisat2_baset::lcnf / Solver::addClause_");
  output["rows"]=std::move(rows); output["import_ns"]=number(elapsed(start));
  write_json(directory+"/native-import.json",output);
}
}

void record_fresh_order_solver(deagle_closure_solvert &adapter)
{
  auto &s=adapter.order_solver();
  json_objectt row;
  row["site"]=json_stringt("new factory instance after generate_equation, before CNF");
  row["clauses"]=number(s.nClauses()); row["learnts"]=number(s.nLearnts());
  row["assignments"]=number(s.nAssigns()); row["variables"]=number(s.nVars());
  row["solves"]=number(s.solves);
#ifdef __linux__
  row["pid"]=number(getpid());
#endif
  write_json(stage3::observation_directory()+"/fresh-solver.json",row);
}

void prepare_order_lemma_cache(
  deagle_closure_solvert &adapter, const oc_edge_tablet &edges,
  const oc_guard_mapt &guards, const oc_location_mapt &locations)
{
  s8::Scope s8_timer(s8::lemma_prepare);
  const char *root=std::getenv("INCDEAGLE_S5_ROOT");
  const char *helper=std::getenv("INCDEAGLE_S5_HELPER");
  bool capture=std::getenv("S10_DIR")!=nullptr;
  if(!capture && (!root || !helper)) return;
  auto start=clock_type::now();
  const auto dir=stage3::declare_theory_snapshot();
  bool old=!capture && dir==std::string(root)+"/old";
  if(!capture && !old && dir!=std::string(root)+"/candidate") return;
  json_objectt graph, addresses;
  json_arrayt relations, conditions;
  std::vector<graph_atom> slots;
  for(const auto &edge:edges)
  {
    const auto &a=edge.first.first, &b=edge.first.second;
    json_objectt row;
    row["from"]=json_stringt(a); row["to"]=json_stringt(b);
    row["kind"]=json_stringt(edge.second.second); row["x"]=number(edge.second.first.x);
    row["slot"]=number(slots.size());
    slots.push_back({edge.second.first,edge.second.second=="rf"});
    addresses[a]=json_stringt(get_address(a)); addresses[b]=json_stringt(get_address(b));
    relations.push_back(std::move(row));
  }
  for(const auto &g:guards)
  {
    json_objectt row;
    row["event"]=json_stringt(g.first); row["x"]=number(g.second.x);
    row["line"]=number(locations.at(g.first)); row["slot"]=number(slots.size());
    slots.push_back({g.second,true}); addresses[g.first]=json_stringt(get_address(g.first));
    conditions.push_back(std::move(row));
  }
  graph["edges"]=std::move(relations); graph["guards"]=std::move(conditions);
  graph["addresses"]=std::move(addresses);
  graph["site"]=json_stringt("bmc_util before save_raw_graph/init");
  graph["snapshot_ns"]=number(elapsed(start));
  write_json(dir+"/native-bindings.json",graph);
  if(capture) return;
  auto &solver=adapter.order_solver();
  if(old)
  {
    const auto path=dir+"/native-conflicts.jsonl";
    std::ofstream(path,std::ios::trunc).close();
    solver.observe_order_conflict=[path,&solver](const char *origin,const Minisat::vec<Minisat::Lit> &clause) {
      s8::Scope s8_record(s8::conflict_record);
      json_objectt result; json_arrayt lits, levels;
      for(int i=0;i<clause.size();++i)
      {
        lits.push_back(number(clause[i].x));
        levels.push_back(number(clause[i].x<0?-1:solver.order_literal_level(clause[i])));
      }
      result["clause_x"]=std::move(lits); result["levels"]=std::move(levels);
      result["origin"]=json_stringt(origin);
      result["site"]=json_stringt("ClosureSolver::propagate/pre-analyze");
      // jsont pretty prints by default. Each record is a single compact JSON line.
      std::ostringstream record; record<<result;
      std::string compact=record.str();
      for(auto &ch:compact) if(ch=='\n' || ch=='\r') ch=' ';
      std::ofstream stream(path,std::ios::app); stream<<compact<<'\n'; stream.close();
      if(!stream) throw std::runtime_error("Cannot retain original OC conflict");
    };
    return;
  }
  std::vector<import_row> plan;
  bool valid=run_audit(helper,dir) && read_plan(dir+"/local-bindings.txt",slots,plan);
  json_objectt decision;
  decision["valid_plan"]=valid?jsont(json_truet()):jsont(json_falset());
  decision["planned"]=number(valid?plan.size():0);
  write_json(dir+"/native-plan.json",decision);
  if(!valid) plan.clear();
  if(s8::only("I1") || s8::only("I2") || s8::only("F2")) plan.clear();
  solver.before_first_search=[plan,dir,&adapter]() { submit(adapter,plan,dir); };
}
