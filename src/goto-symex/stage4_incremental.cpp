#include "../util/stage8_meter.h"
#include "stage4_incremental.h"
#include "stage3_observer.h"
#include "goto_symex_state.h"
#include "path_storage.h"
#include "symex_target_equation.h"
#include <analyses/dirty.h>
#include <analyses/local_safe_pointers.h>
#include <goto-programs/goto_model.h>
#include <util/irep_serialization.h>
#include <util/json.h>
#include <util/options.h>
#include <util/std_expr.h>
#include <util/ui_message.h>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <set>
#include <stdexcept>
#ifdef __linux__
#include <sys/wait.h>
#include <unistd.h>
#endif

namespace stage4
{
namespace
{
const std::string base = std::getenv("INCDEAGLE_S4_ROOT") ? std::getenv("INCDEAGLE_S4_ROOT") : "";
goto_modelt *live = nullptr;
ui_message_handlert *ui = nullptr;
bool master = false, old = false, resumed = false, attempted = false;
std::string callee, refusal, change;
irept fragments("cache"), baseline_image;
std::size_t dispatched=0, prefix=0, prefix_rows=0, bound=0, mapped=0, symbols=0;
std::size_t prefix_symbols=0, threads=0, memory=0, fork_ns=0, prefix_events=0;
std::size_t budget=0;
clockt::time_point resume_time;
json_arrayt dispatch_trace, regions;
std::map<std::string,std::size_t> counts;

json_numbert num(std::size_t n) { return json_numbert(std::to_string(n)); }
void json_file(const std::string &name, const jsont &value)
{
  const auto tmp=name+".tmp";
  std::ofstream out(tmp);
  out << value << '\n';
  out.close();
  if(!out || std::rename(tmp.c_str(), name.c_str()))
    throw std::runtime_error("Cannot publish "+name);
}
void put(irept &a, const irept &b) { a.get_sub().push_back(b); }
void field(irept &a,const char *name,std::size_t n) { a.set(name,std::to_string(n)); }

irept symbol_image(const symbolt &s)
{
  irept v(s.name);
  v.set(ID_type,s.type); v.set(ID_value,s.value); v.set("location",s.location);
  v.set(ID_module,s.module); v.set(ID_mode,s.mode); v.set(ID_base_name,s.base_name);
  v.set(ID_pretty_name,s.pretty_name);
  std::string flags;
  for(bool bit : {s.is_type,s.is_macro,s.is_exported,s.is_input,s.is_output,s.is_state_var,s.is_property,
                  s.is_static_lifetime,s.is_thread_local,s.is_lvalue,s.is_file_local,s.is_extern,s.is_volatile,
                  s.is_parameter,s.is_auxiliary,s.is_weak})
    flags += bit?'1':'0';
  v.set("flags",flags);
  return v;
}

irept image(const goto_modelt &m)
{
  irept result("stage4-goto-v1");
  auto &syms=result.add("symbols");
  for(const auto &entry : m.symbol_table.symbols)
    syms.set(entry.first, symbol_image(entry.second));
  const dirtyt dirty(m.goto_functions);
  auto &dirty_set=result.add("dirty");
  for(const auto &id : dirty.get_dirty_ids()) dirty_set.set(id,"1");
  auto &fs=result.add("functions");
  for(const auto &entry : m.goto_functions.function_map)
  {
    auto &f=fs.add(entry.first);
    const auto &fn=entry.second;
    f.set("hidden",fn.is_hidden());
    for(const auto &p : fn.parameter_identifiers) put(f.add("params"),irept(p));
    local_safe_pointerst safe;
    safe(fn.body);
    f.set("safe",safe.stage4_dependencies());
    auto &body=f.add("instructions");
    for(const auto &i : fn.body.instructions)
    {
      irept row(i.to_string());
      row.set(ID_code,i.code()); if(i.has_condition()) row.set("guard",i.condition());
      row.set("location",i.source_location());
      field(row,"pc",i.location_number); field(row,"loop",i.loop_number); field(row,"target",i.target_number);
      for(const auto &l : i.labels) put(row.add("labels"),irept(l));
      for(const auto &t : i.targets) put(row.add("targets"),irept(std::to_string(t->location_number)));
      std::set<unsigned> incoming;
      for(const auto &n : i.incoming_edges) incoming.insert(n->location_number);
      for(auto n : incoming) put(row.add("incoming"),irept(std::to_string(n)));
      put(body,row);
    }
  }
  return result;
}

bool integer(const irept &v)
{
  return v.find(ID_type).id()==ID_signedbv || v.find(ID_type).id()==ID_unsignedbv;
}

bool pure_integer(const irept &v)
{
  if(!integer(v)) return false;
  if(v.id()==ID_constant || v.id()==ID_symbol) return true;
  if(v.id()!=ID_plus && v.id()!=ID_minus && v.id()!=ID_mult && v.id()!=ID_typecast) return false;
  for(const auto &part:v.get_sub()) if(!pure_integer(part)) return false;
  return true;
}

// Exactly one signed/unsigned integer literal on a pure scalar arithmetic RHS.
bool scalar_rhs(const irept &a,const irept &b,unsigned &changes)
{
  if(a.full_eq(b)) return true;
  if(a.id()!=b.id() || !integer(a) || !integer(b)) return false;
  irept x=a,y=b;
  if(a.id()==ID_constant)
  {
    x.remove(ID_value); y.remove(ID_value);
    if(!x.full_eq(y) || a.get(ID_value)==b.get(ID_value)) return false;
    return ++changes==1;
  }
  if(a.id()!=ID_plus && a.id()!=ID_minus && a.id()!=ID_mult && a.id()!=ID_typecast) return false;
  x.get_sub().clear(); y.get_sub().clear();
  if(!x.full_eq(y) || a.get_sub().size()!=b.get_sub().size()) return false;
  for(std::size_t j=0;j<a.get_sub().size();++j)
    if(!scalar_rhs(a.get_sub()[j],b.get_sub()[j],changes)) return false;
  return true;
}

bool scalar_guard(const irept &a,const irept &b,unsigned &changes)
{
  if(a.full_eq(b)) return true;
  if(a.id()!=b.id())
  {
    const bool pair=(a.id()==ID_lt && b.id()==ID_le) || (a.id()==ID_le && b.id()==ID_lt) ||
                    (a.id()==ID_gt && b.id()==ID_ge) || (a.id()==ID_ge && b.id()==ID_gt);
    if(!pair || a.get_sub().size()!=2 || !pure_integer(a.get_sub()[0]) || !pure_integer(a.get_sub()[1])) return false;
    irept y=b; y.id(a.id());
    return a.full_eq(y) && ++changes==1;
  }
  if(a.id()!=ID_not && a.id()!=ID_and && a.id()!=ID_or) return false;
  irept x=a,y=b; x.get_sub().clear(); y.get_sub().clear();
  if(!x.full_eq(y) || a.get_sub().size()!=b.get_sub().size()) return false;
  for(std::size_t i=0;i<a.get_sub().size();++i)
    if(!scalar_guard(a.get_sub()[i],b.get_sub()[i],changes)) return false;
  return true;
}

std::string first_difference(const irept &a,const irept &b,const std::string &path)
{
  if(a.id()!=b.id()) return path+" ["+id2string(a.id())+" -> "+id2string(b.id())+"]";
  if(a.get_sub().size()!=b.get_sub().size()) return path+".operand_count";
  for(std::size_t i=0;i<a.get_sub().size();++i)
    if(!a.get_sub()[i].full_eq(b.get_sub()[i])) return first_difference(a.get_sub()[i],b.get_sub()[i],path+"/"+std::to_string(i));
  for(const auto &p:a.get_named_sub())
    if(!p.second.full_eq(b.find(p.first))) return first_difference(p.second,b.find(p.first),path+"/"+id2string(p.first));
  for(const auto &p:b.get_named_sub())
    if(!p.second.full_eq(a.find(p.first))) return path+"/added:"+id2string(p.first);
  return path;
}

std::string rebind(const irept &next)
{
  s8::Scope s8_timer(s8::rebind);
  const auto &a=baseline_image, &b=next;
  if(a.id()!=b.id()) return "frontend_schema_changed";
  if(!a.find("dirty").full_eq(b.find("dirty"))) return "whole_program_dirty_set_changed";
  auto declarations=a.find("symbols");
  const auto &new_symbols=b.find("symbols");
  const auto &new_body=new_symbols.find(callee).find(ID_value);
  auto *function_symbol=live->symbol_table.get_writeable(callee);
  if(!function_symbol || !function_symbol->is_function() || new_body.id()!=ID_code)
    return "changed_function_body_unavailable";
  // The C front end retains an AST body on the function symbol as well as the
  // lowered CFG. All declarations, initializers and other functions still match.
  declarations.add(callee).set(ID_value,new_body);
  if(!declarations.full_eq(new_symbols))
    return "symbol_type_initializer_or_declaration_changed:"+first_difference(declarations,new_symbols,"symbols");
  const auto &af=a.find("functions").get_named_sub(), &bf=b.find("functions").get_named_sub();
  if(af.size()!=bf.size()) return "function_set_changed";
  goto_programt::instructiont *update=nullptr;
  irept replacement;
  for(const auto &pair : af)
  {
    auto it=bf.find(pair.first);
    if(it==bf.end()) return "function_set_changed";
    const auto &f=pair.second,&g=it->second;
    const auto &xs=f.find("instructions").get_sub(),&ys=g.find("instructions").get_sub();
    if(xs.size()!=ys.size()) return "instruction_topology_changed:"+id2string(pair.first);
    if(!f.find("safe").full_eq(g.find("safe"))) return "safe_pointer_summary_changed:"+id2string(pair.first);
    if(!f.find("params").full_eq(g.find("params")) || f.get("hidden")!=g.get("hidden")) return "function_abi_changed";
    auto pos=live->goto_functions.function_map.at(pair.first).body.instructions.begin();
    for(std::size_t i=0;i<xs.size();++i,++pos)
    {
      ++mapped;
      if(xs[i].full_eq(ys[i])) continue;
      if(id2string(pair.first)!=callee || update) return "outside_first_unentered_function_or_multiple_edits";
      irept u=xs[i],v=ys[i];
      u.remove(ID_code); v.remove(ID_code); u.remove("guard"); v.remove("guard");
      if(!u.full_eq(v)) return "control_flow_or_modelled_location_changed";
      unsigned edits=0;
      if(pos->is_assign() && xs[i].find("guard").full_eq(ys[i].find("guard")))
      {
        const auto &p=xs[i].find(ID_code),&q=ys[i].find(ID_code);
        irept x=p,y=q;
        if(x.get_sub().size()!=2 || y.get_sub().size()!=2) return "unsupported_assignment";
        x.get_sub().pop_back(); y.get_sub().pop_back();
        if(!x.full_eq(y) || !pure_integer(p.get_sub()[1]) || !pure_integer(q.get_sub()[1]) ||
           !scalar_rhs(p.get_sub()[1],q.get_sub()[1],edits) || edits!=1)
          return "non_scalar_or_address_sensitive_assignment";
        replacement=q; change="integer_rhs";
      }
      else if(pos->is_goto() && xs[i].find(ID_code).full_eq(ys[i].find(ID_code)) &&
              scalar_guard(xs[i].find("guard"),ys[i].find("guard"),edits) && edits==1)
      {
        replacement=ys[i].find("guard"); change="integer_guard";
      }
      else return "unsupported_guard_call_or_synchronization";
      update=&*pos;
    }
  }
  if(!update) return "no_supported_semantic_edit";
  // The candidate occupies the same audited node in this private, address-stable arena.
  // All other instruction, source, function and symbol records matched before mutation.
  if(change=="integer_rhs") update->code_nonconst()=static_cast<const goto_instruction_codet &>(replacement);
  else update->condition_nonconst()=static_cast<const exprt &>(replacement);
  function_symbol->value=static_cast<const exprt &>(new_body);
  if(!image(*live).full_eq(next)) return "installed_candidate_image_mismatch";
  return "";
}

std::string check_prefix_symbols(const goto_symex_statet &state,const symex_target_equationt &eq)
{
  s8::Scope s8_timer(s8::prefix_symbols);
  const namespacet ns(state.symbol_table,live->symbol_table);
  std::map<irep_idt,typet> named_ssa;
  for(const auto &s:eq.SSA_steps)
    if(s.ssa_lhs.is_not_nil())
    {
      named_ssa.emplace(s.ssa_lhs.get_identifier(),s.ssa_lhs.type());
      // symex_goto constructs this Boolean pseudo-symbol outside the program
      // symbol table. Require the actual GUARD definition in this checkpoint.
      if(s.is_assignment() && s.assignment_type==symex_targett::assignment_typet::GUARD &&
         s.ssa_lhs.get_original_name()==state.guard_identifier() && s.ssa_lhs.type().id()==ID_bool)
        named_ssa.emplace(state.guard_identifier(),s.ssa_lhs.type());
    }
  std::set<irep_idt> verified;
  std::function<std::string(const irept &)> check = [&](const irept &e)->std::string {
    if(e.id()==ID_symbol)
    {
      const auto name=e.get(ID_identifier);
      const auto &type=e.find(ID_type);
      const auto &original=e.find(ID_expression);
      const auto base_name=original.id()==ID_symbol ? original.get(ID_identifier) : name;
      const symbolt *symbol=nullptr;
      auto def=named_ssa.find(name);
      const bool in_equation=def!=named_ssa.end() && def->second==type;
      const bool in_namespace=!ns.lookup(base_name,symbol) && symbol->type==type;
      if(!in_namespace && !in_equation) return "unresolved_or_retyped_prefix_symbol:"+id2string(name);
      verified.insert(name);
    }
    for(const auto &x:e.get_sub()) { auto error=check(x);if(!error.empty()) return error; }
    for(const auto &p:e.get_named_sub())
    {
      if(p.first==ID_C_source_location || p.first==ID_C_end_location || p.first==ID_expression) continue;
      auto error=check(p.second);if(!error.empty()) return error;
    }
    return "";
  };
  for(const auto &s:eq.SSA_steps)
  {
    for(const exprt *e : std::initializer_list<const exprt *>{&s.guard,&s.cond_expr,&s.ssa_lhs,&s.ssa_rhs,
        &s.ssa_full_lhs,&s.original_full_lhs})
    { auto error=check(*e);if(!error.empty()) return error; }
    for(const auto &e:s.ssa_function_arguments) { auto error=check(e);if(!error.empty()) return error; }
    for(const auto &e:s.io_args) { auto error=check(e);if(!error.empty()) return error; }
  }
  bound=verified.size();
  return "";
}
void stats(const std::string &path,int code)
{
  json_objectt j;
  j["role"]=json_stringt(resumed?"candidate":"old");
  j["checkpoint_used"]=resumed?jsont(json_truet()):jsont(json_falset());
  j["exit_code"]=num(code); j["executed_symex_steps"]=num(dispatched);
  j["reused_prefix_symex_steps"]=num(resumed?prefix:0); j["checkpoint_dispatch"]=num(prefix);
  j["checkpoint_raw_ssa_rows"]=num(prefix_rows); j["checkpoint_symbol_table_entries"]=num(prefix_symbols);
  j["checkpoint_raw_events"]=num(prefix_events);
  j["checkpoint_threads"]=num(threads); j["checkpoint_virtual_bytes_upper_bound"]=num(memory);
  j["checkpoint_budget_bytes"]=num(budget);
  j["checkpoint_fork_ns"]=num(fork_ns); j["function"]=json_stringt(callee);
  j["changed_instruction_type"]=json_stringt(change); j["goto_nodes_checked"]=num(mapped);
  j["program_symbols_checked"]=num(symbols); j["prefix_symbol_references_resolved"]=num(bound);
  j["fallback_reason"]=json_stringt(refusal); j["executed_dispatches"]=dispatch_trace;
  json_objectt cs; for(const auto &p:counts) cs[p.first]=num(p.second);
  j["sc_counters"]=std::move(cs); j["sc_regions"]=regions;
  json_file(path,j);
}
}

const std::string &root() { return base; }
bool configured() { return !base.empty(); }
bool collecting() { return old; }
bool restoring() { return resumed; }
irept &cache() { return fragments; }
void count(const std::string &key,std::size_t n) { counts[key]+=n; }
void region(const std::string &family,const std::string &name,bool reused)
{
  json_objectt r; r["family"]=json_stringt(family);r["name"]=json_stringt(name);
  r["reused"]=reused?jsont(json_truet()):jsont(json_falset());regions.push_back(std::move(r));
}
void save_irep(const std::string &path,const irept &v)
{
  s8::Scope s8_timer(s8::irep_write);
  std::ofstream out(path,std::ios::binary);
  irep_serializationt::ireps_containert store; irep_serializationt io(store);
  io.reference_convert(v,out); out.close();
  if(!out) throw std::runtime_error("Cannot write "+path);
}
irept load_irep(const std::string &path)
{
  s8::Scope s8_timer(s8::irep_read);
  std::ifstream in(path,std::ios::binary);
  if(!in) throw std::runtime_error("Cannot read "+path);
  irep_serializationt::ireps_containert store; irep_serializationt io(store);
  irept v=io.reference_convert(in);
  if(!in || in.peek()!=std::char_traits<char>::eof()) throw std::runtime_error("Invalid image "+path);
  return v;
}
void save_cache() { if(old) save_irep(base+"/old/fragments.irep",fragments); }
clockt::time_point suffix_start(clockt::time_point start) { return resumed?resume_time:start; }

bool frontend(goto_modelt &model,ui_message_handlert &handler,const optionst &opt)
{
  if(!configured()) return false;
  if(std::getenv("INCDEAGLE_S4_FRONTEND"))
  {
    save_irep(base+"/frontend/goto.irep",image(model));
    return true;
  }
  const char *limit=std::getenv("INCDEAGLE_S4_BUDGET_BYTES");
  if(!limit) refusal="checkpoint_budget_missing";
  else budget=std::stoull(limit);
  if(!budget) refusal="checkpoint_disabled_by_budget";
  if(!opt.get_bool_option("deagle-closure") || opt.get_option("mm")!="sc" ||
     opt.get_bool_option("refined-pointer-analysis") || opt.get_bool_option("paths") ||
     opt.get_bool_option("concurrency-slice") || opt.get_bool_option("symex-driven-lazy-loading"))
    refusal="unsupported_verifier_configuration";
  live=&model; ui=&handler; master=true;
  return false;
}

void before_step(const goto_symex_statet &state,symex_target_equationt &eq,const path_storaget &storage)
{
  if(!master && !old && !resumed) return;
#ifdef __linux__
  const auto &pc=*state.source.pc;
  if(master && !attempted && refusal.empty() && pc.is_function_call() && pc.call_function().id()==ID_symbol)
  {
    const auto id=to_symbol_expr(pc.call_function()).get_identifier();
    const auto fn=live->goto_functions.function_map.find(id);
    bool user_fn=false;
    if(fn!=live->goto_functions.function_map.end())
      for(const auto &ins:fn->second.body.instructions)
        if(ins.source_location().get_file()=="program.c") { user_fn=true; break; }
    if(user_fn)
    {
      attempted=true; callee=id2string(id);
      const auto start=clockt::now();
      std::size_t pages=0; std::ifstream("/proc/self/statm")>>pages;
      memory=pages*static_cast<std::size_t>(sysconf(_SC_PAGESIZE));
      std::ifstream status("/proc/self/status");std::string line;unsigned tasks=0;
      while(std::getline(status,line)) if(line.compare(0,8,"Threads:")==0) tasks=std::stoul(line.substr(8));
      if(!memory || memory>budget || tasks!=1) refusal="checkpoint_budget_or_multithreaded_host";
      else if(!storage.empty() || storage.safe_pointers.count(id)) refusal="changed_function_previously_entered_or_pending_paths";
      else
      {
        baseline_image=image(*live); symbols=live->symbol_table.symbols.size();
        prefix=dispatched; prefix_rows=eq.SSA_steps.size(); threads=state.threads.size();
        prefix_symbols=state.symbol_table.symbols.size();
        std::size_t slot=0;
        for(auto &s:eq.SSA_steps)
        {
          s.stage4_prefix_slot=++slot;
          if(s.is_shared_read() || s.is_shared_write() || s.is_spawn() || s.is_memory_barrier()) ++prefix_events;
        }
        ui->flush(0); std::cout.flush(); std::cerr.flush();
        pages=0; std::ifstream("/proc/self/statm")>>pages;
        memory=pages*static_cast<std::size_t>(sysconf(_SC_PAGESIZE));
        const bool fits=memory>0 && memory<=budget;
        const uint64_t s8_parent=s8::state().detail ? s8::ns(CLOCK_PROCESS_CPUTIME_ID)-s8::state().cpu_born : 0;
        const pid_t child=fits?fork():-1;
        if(child==0 && s8::state().detail){s8::state().inherited_cpu=s8_parent;s8::state().cpu_born=0;}
        fork_ns=std::chrono::duration_cast<std::chrono::nanoseconds>(clockt::now()-start).count();
        if(child<0) refusal=fits?"fork_failed":"checkpoint_budget_after_capture";
        else if(child==0) { master=false; old=true; }
        else
        {
          int result=0; if(waitpid(child,&result,0)!=child || !WIFEXITED(result)) throw std::runtime_error("Old verifier failed");
          json_objectt ready; ready["old_exit"]=num(WEXITSTATUS(result)); ready["checkpoint_dispatch"]=num(prefix);
          ready["old_pid"]=num(child);ready["checkpoint_pid"]=num(getpid());json_file(base+"/old_done.json",ready);
          std::string request;
          bool s8_received=bool(std::getline(std::cin,request));
          s8::reset_at_command(base+"/candidate");
          s8::state().prefix=0;
          if(!s8_received) refusal="session_closed_before_update";
          else if(request.compare(0,5,"FULL ")==0) refusal=request.substr(5);
          else if(request!="APPLY") refusal="unknown_update_command";
          else
          {
            refusal=rebind(load_irep(base+"/frontend/goto.irep"));
            if(refusal.empty()) refusal=check_prefix_symbols(state,eq);
          }
          if(!refusal.empty()) { stats(base+"/decision.json",85); std::_Exit(85); }
          fragments=load_irep(base+"/old/fragments.irep");
          // Fresh physical output streams and fresh solver run. The checkpoint was taken
          // before any SAT conversion or SC postprocessing, while all state owners lived.
          ui->stage4_reopen_json(base+"/candidate/result.json");
          if(!freopen((base+"/candidate/diagnostic.stdout").c_str(),"w",stdout) ||
             !freopen((base+"/candidate/diagnostic.stderr").c_str(),"w",stderr)) throw std::runtime_error("Cannot switch diagnostics");
          stage3::redirect(base+"/candidate");
          master=false; resumed=true; dispatched=0;dispatch_trace=json_arrayt{};
          stage3::goto_model(live->goto_functions);
          resume_time=clockt::now();
        }
      }
    }
  }
#endif
  ++dispatched;
  json_objectt d;d["function"]=json_stringt(state.source.function_id);d["pc"]=num(state.source.pc->location_number);
  d["thread"]=num(state.source.thread_nr);dispatch_trace.push_back(std::move(d));
}
void finish(int code)
{
  if(!configured()) return;
  if(master && refusal.empty()) refusal="no_eligible_function_entry";
  stats(base+(resumed?"/candidate":"/old")+"/native-stats.json",code);
}
}
