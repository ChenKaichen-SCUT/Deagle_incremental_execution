#include "../util/stage8_meter.h"
#include "stage4_sc.h"
#include "stage4_incremental.h"
#include <util/replace_expr.h>
#include <util/std_expr.h>
#include <stdexcept>

stage4_sct::stage4_sct(memory_model_baset &m,symex_target_equationt &e)
  :mm(m),eq(e),active((stage4::collecting() || (stage4::restoring() && !s8::only("I1"))) && m.use_deagle &&
                      !m.enable_deadlock && !m.enable_datarace && m.assume_local_consistency)
{
}

void stage4_sct::include(iterator e)
{
  const auto slot=e->stage4_prefix_slot;
  if(!slot) { eligible=false; return; }
  const auto name=mm.get_name(e);
  if(!events.emplace(name,e).second || !slots.emplace(slot,e).second) { eligible=false; return; }
  irept row("event");
  row.set("slot",std::to_string(slot));row.set("order",std::to_string(mm.numbering.at(e)));
  row.set("kind",std::to_string(static_cast<unsigned>(e->type)));
  row.set("thread",std::to_string(e->source.thread_nr));row.set("fn",e->source.function_id);
  row.set("atomic",std::to_string(e->atomic_section_id));row.set("source",e->source.pc->source_location());
  row.set("lhs",e->ssa_lhs);row.set("guard",e->guard);
  signature.get_sub().push_back(row);
}

bool stage4_sct::check(const std::string &family,const std::string &name)
{
  s8::Scope s8_timer(s8::sc_check);
  if(!active) return false;
  auto &store=stage4::cache().add(family);
  if(eligible && stage4::collecting())
  {
    record=&store.add(name);record->set("signature",signature);
  }
  else if(eligible && stage4::restoring() && store.find(name).find("signature").full_eq(signature))
  {
    record=&store.add(name);hit=true;
  }
  stage4::region(family,name,hit);
  return hit;
}

bool stage4_sct::address(const std::string &name,const std::vector<iterator> &reads,
                         const std::vector<iterator> &writes)
{
  if(!active || reads.empty()) return false;
  for(auto e:reads) include(e);
  for(auto e:writes) include(e);
  if(!check("rf",name)) return false;
  replay_reads();
  return true;
}

void stage4_sct::begin_read()
{
  if(active) stage4::count("read_bundles_generated");
  if(record && !hit) { edge_start=eq.oc_edges.size(); step_start=std::prev(eq.SSA_steps.cend()); }
}

void stage4_sct::end_read(iterator read)
{
  if(!record || hit) return;
  irept bundle("read");bundle.set("read",std::to_string(read->stage4_prefix_slot));
  for(std::size_t j=edge_start;j<eq.oc_edges.size();++j)
  {
    const auto &e=eq.oc_edges[j];
    if(e.kind!="rf" || e.e2_str!=mm.get_name(read)) throw std::logic_error("Unexpected RF fragment");
    irept choice("choice"); choice.set("old_atom",e.expr);
    choice.set("write",std::to_string(events.at(e.e1_str)->stage4_prefix_slot));
    bundle.add("choices").get_sub().push_back(choice);
  }
  for(auto s=std::next(step_start);s!=eq.SSA_steps.cend();++s)
  {
    if(!s->is_constraint() || (s->comment!="rf-val" && s->comment!="rf-some"))
      throw std::logic_error("Unexpected read bundle formula");
    irept formula(s->comment);formula.set("value",s->cond_expr);
    bundle.add("formulas").get_sub().push_back(formula);
  }
  record->add("bundles").get_sub().push_back(bundle);
}

void stage4_sct::replay_reads()
{
  s8::Scope s8_timer(s8::rf_replay);
  for(const auto &bundle:record->find("bundles").get_sub())
  {
    auto r=slots.at(bundle.get_size_t("read"));
    replace_mapt rename;
    for(const auto &choice:bundle.find("choices").get_sub())
    {
      auto w=slots.at(choice.get_size_t("write"));
      auto atom=mm.nondet_bool_symbol("rf");
      rename.emplace(static_cast<const exprt &>(choice.find("old_atom")),atom);
      mm.choice_symbols.emplace(std::make_pair(r,w),atom);
      ++mm.total_rf_val_count;
      mm.add_oc_edge(eq,w,r,"rf",atom);
      stage4::count("rf_edges_reused");
    }
    for(const auto &f:bundle.find("formulas").get_sub())
    {
      exprt value=static_cast<const exprt &>(f.find("value"));
      replace_expr(rename,value);
      eq.constraint(value,id2string(f.id()),r->source);
      stage4::count(f.id()=="rf-some"?"coverage_formulas_reused":"value_formulas_reused");
    }
    stage4::count("read_bundles_reused");
  }
}

bool stage4_sct::thread(unsigned nr,const std::vector<iterator> &seq,
                        const std::set<std::pair<std::string,std::string>> &apo)
{
  s8::Scope s8_timer(s8::sc_thread);
  if(!active) return false;
  iterator previous=eq.SSA_steps.end();
  for(auto e:seq)
  {
    include(e);
    if(e->is_memory_barrier()) continue;
    if(previous!=eq.SSA_steps.end())
    {
      const auto pair=std::make_pair(id2string(previous->ssa_lhs.get_identifier()),id2string(e->ssa_lhs.get_identifier()));
      signature.add("external_apo_membership").get_sub().emplace_back(apo.count(pair)?"1":"0");
    }
    previous=e;
  }
  if(!check("po",std::to_string(nr))) { edge_start=eq.oc_edges.size();return false; }
  for(const auto &edge:record->find("edges").get_sub())
  {
    mm.add_oc_edge(eq,slots.at(edge.get_size_t("from")),slots.at(edge.get_size_t("to")),id2string(edge.id()),
                   static_cast<const exprt &>(edge.find("guard")));
    stage4::count("thread_edges_reused");
  }
  return true;
}

void stage4_sct::end_thread()
{
  if(!active) return;
  stage4::count("thread_edges_generated",eq.oc_edges.size()-edge_start);
  if(!record || hit) return;
  for(std::size_t i=edge_start;i<eq.oc_edges.size();++i)
  {
    const auto &e=eq.oc_edges[i];
    irept edge(e.kind);edge.set("guard",e.expr);
    edge.set("from",std::to_string(events.at(e.e1_str)->stage4_prefix_slot));
    edge.set("to",std::to_string(events.at(e.e2_str)->stage4_prefix_slot));
    record->add("edges").get_sub().push_back(edge);
  }
}
