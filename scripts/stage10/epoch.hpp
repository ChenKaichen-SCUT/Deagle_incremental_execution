#pragma once
#include "input.hpp"
#include "util/stage10_hooks.h"
#include "util/stage10_telemetry.h"
#include "util/stage8_meter.h"
#include <limits>
#include <new>

extern std::vector<std::string> write_order;

namespace Minisat {
class Stage10Epoch {
  using Key=session10::Key;
  ClosureSolver &s;
  const double initial_seed,initial_gc;
  std::set<int> eligible;
  std::map<CRef,Key> original;
  std::map<Key,std::vector<CRef>> available;
  std::vector<int> learnt_seal;
  static Stage10Epoch *&current(){static Stage10Epoch *value=nullptr;return value;}
  Key pending_key;
  bool certified(const Key &k) const {
    if(k.size()<2)return false;
    for(int x:k)if(!eligible.count(x/2))return false;
    return true;
  }
  static void record(Solver *owner,const vec<Lit>& ps,CRef ref){
    auto &e=*current();
    if(owner!=&e.s || e.pending_key.empty())return;
    auto actual=session10::key(ps);
    if(actual==e.pending_key)e.original[ref]=std::move(actual);
  }
  static CRef take(Solver *owner,const vec<Lit> &ps){
    auto &e=*current();
    if(owner!=&e.s || e.pending_key.empty())return CRef_Undef;
    Key k=session10::key(ps);
    if(k!=e.pending_key)return CRef_Undef;
    auto it=e.available.find(k);if(it==e.available.end() || it->second.empty())return CRef_Undef;
    CRef cr=it->second.back();it->second.pop_back();
    auto &physical=e.s.ca[cr];
    session10::require(!physical.mark() && !physical.learnt() && session10::key(physical)==k,"retained Clause differs before actual attach");
    e.used.emplace_back(cr,k);
    return cr;
  }
  std::vector<int> learning() const {
    std::vector<int> out;
    for(int j=0;j<s.learnts.size();++j){
      CRef cr=s.learnts[j];const Clause &c=s.ca[cr];
      out.push_back(cr);out.push_back(c.size());for(int i=0;i<c.size();++i)out.push_back(c[i].x);
    }
    return out;
  }
public:
  std::vector<std::pair<CRef,Key>> used;
  int old_learnts=0,old_roots=0,old_nodes=0,old_clauses=0,surviving=0;
  size_t seal_bytes=0;
  explicit Stage10Epoch(ClosureSolver &solver):s(solver),initial_seed(solver.random_seed),initial_gc(solver.garbage_frac){}
  ~Stage10Epoch(){close();}
  void close(){s10::born=nullptr;s10::take=nullptr;current()=nullptr;}
  void register_old(const std::set<int> &vars){
    eligible=vars;current()=this;s10::born=record;
    // Preserve provenance of offsets until the one handover. We still admit only live original objects.
    s.garbage_frac=std::numeric_limits<double>::max();s.remove_satisfied=false;
  }
  void submitting(const Key &lits){
    pending_key.clear();
    if(certified(lits)){pending_key=lits;std::sort(pending_key.begin(),pending_key.end());}
  }
  void seal(){
    close();learnt_seal=learning();old_learnts=s.nLearnts();old_roots=s.nAssigns();
    old_clauses=s.nClauses();old_nodes=s.graph.nodes.size();
    std::ofstream live(s10::directory()+"/original-resident.tsv");
    for(int i=0;i<s.clauses.size();++i){
      CRef cr=s.clauses[i];auto entry=original.find(cr);
      if(entry==original.end())continue;
      const Clause &c=s.ca[cr];
      session10::require(!c.mark() && !c.learnt() && session10::key(c)==entry->second,"old original contents changed");
      live<<cr;for(int x:entry->second)live<<"\t"<<x;live<<"\n";
    }
    std::ofstream learned(s10::directory()+"/learning.bin",std::ios::binary);
    if(!learnt_seal.empty())learned.write(reinterpret_cast<const char*>(learnt_seal.data()),learnt_seal.size()*sizeof(int));
    seal_bytes=learnt_seal.capacity()*sizeof(int);
    for(const auto &r:original)seal_bytes+=sizeof(r.first)+r.second.capacity()*sizeof(int);
  }
  bool intact() const {return learnt_seal==learning();}
  void corrupt_for_test(){
    if(!s.nLearnts())throw std::runtime_error("test needs non-empty native CDCL database");
    auto &c=s.ca[s.learnts[0]];c[0]=~c[0];
  }
  int cycles() const{return s.conflict_cycle;}
  int theory() const{return s.theory_propagation;}
  int nodes() const{return s.graph.nodes.size();}
  size_t arena_bytes() const{return size_t(s.ca.size())*sizeof(uint32_t);}
  void switch_version(const std::set<int> &confirmed,const session10::Input &next){
    session10::require(intact(),"damaged learnt seal");
    eligible=confirmed;
    std::set<Key> candidates;
    for(const auto &op:next.ops)if(op.tag==session10::ClauseOp && certified(op.payload)){
      auto k=op.payload;std::sort(k.begin(),k.end());candidates.insert(k);
    }
    for(int i=0;i<s.clauses.size();++i){
      CRef cr=s.clauses[i];auto it=original.find(cr);
      if(it==original.end() || !candidates.count(it->second))continue;
      const Clause &c=s.ca[cr];
      session10::require(!c.learnt() && !c.mark() && session10::key(c)==it->second,"original allocator provenance changed");
      available[it->second].push_back(cr);++surviving;
    }
    // No active references survive this boundary. Only admitted, unattached CRefs still have owners.
    s.watches.clear();s.clauses.clear();s.learnts.clear();s.trail.clear();s.trail_lim.clear();s.qhead=0;
    s.assigns.clear();s.vardata.clear();s.model.clear();s.conflict.clear();s.assumptions.clear();
    s.order_heap.clear(true);s.activity.clear();s.polarity.clear();s.user_pol.clear();s.decision.clear();
    s.seen.clear();s.analyze_stack.clear();s.analyze_toclear.clear();s.add_tmp.clear();
    s.var_inc=s.cla_inc=1;s.dec_vars=s.clauses_literals=s.learnts_literals=0;
    s.ok=true;s.simpDB_assigns=-1;s.simpDB_props=0;s.progress_estimate=0;s.clearInterrupt();s.budgetOff();
    s.graph.~closure();new(&s.graph) closure();
    s.oc_edge_table.clear();s.oc_guard_map.clear();s.oc_location_map.clear();s.oc_result_order=nullptr;
    s.literals_to_assign.clear();s.assigned_literals.clear();s.observe_order_conflict=nullptr;s.before_first_search=nullptr;
    ::write_order.clear();s.remove_satisfied=true;s.random_seed=initial_seed;s.garbage_frac=initial_gc;
    // Until all retained CRefs have been reattached no garbage collection may relocate them.
    // Normal native submission does not simplify/collect; the hooks release before search.
    current()=this;s10::take=take;
  }
};
}
