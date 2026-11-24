#include "../util/stage8_meter.h"
#include "stage3_observer.h"

#include <goto-programs/goto_functions.h>
#include <util/config.h>
#include <util/json.h>
#include "goto_symex_state.h"
#include "symex_target_equation.h"

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <unordered_map>

namespace stage3
{
namespace
{
std::string directory = std::getenv("INCDEAGLE_OBSERVE_DIR") ? std::getenv("INCDEAGLE_OBSERVE_DIR") : "";
json_arrayt visits;
std::map<const SSA_stept *, std::string> event_names;
std::map<std::string, long long> times;

json_numbert number(std::size_t value)
{
  return json_numbert(std::to_string(value));
}

jsont boolean(bool value)
{
  if(value)
    return json_truet();
  return json_falset();
}

void save(const std::string &name, const jsont &value)
{
  const std::string path = std::string(directory) + "/" + name + ".json";
  const std::string temporary = path + ".tmp";
  std::ofstream out(temporary);
  out << value << '\n';
  out.close();
  if(!out || std::rename(temporary.c_str(), path.c_str()) != 0)
    throw std::runtime_error("Cannot publish diagnostic " + name);
}

// All integer links in a pool are local to a single document.
// Type, operators and operands are retained. Source locations are separate.
class irep_poolt
{
  std::unordered_map<irept, std::size_t, irep_full_hash, irep_full_eq> ids;
public:
  json_arrayt rows;
  jsont ref(const irept &value)
  {
    if(value.is_nil())
      return json_nullt();
    const auto found = ids.find(value);
    if(found != ids.end())
      return number(found->second);
    json_objectt node;
    node["id"] = json_stringt(value.id());
    json_arrayt operands;
    for(const auto &operand : value.get_sub())
      operands.push_back(ref(operand));
    if(!operands.empty())
      node["sub"] = std::move(operands);
    json_objectt named;
    for(const auto &item : value.get_named_sub())
      named[id2string(item.first)] = ref(item.second);
    if(named.size() != 0)
      node["named"] = std::move(named);
    const std::size_t index = rows.size();
    ids.emplace(value, index);
    rows.push_back(std::move(node));
    return number(index);
  }
};

json_objectt place(const symex_targett::sourcet &source)
{
  json_objectt loc;
  loc["function"] = json_stringt(source.function_id);
  loc["pc"] = number(source.pc->location_number);
  return loc;
}

const char *step_kind(goto_trace_stept::typet type)
{
  using T = goto_trace_stept::typet;
  switch(type)
  {
  case T::NONE: return "none";
  case T::ASSIGNMENT: return "assignment";
  case T::ASSUME: return "assume";
  case T::ASSERT: return "assert";
  case T::GOTO: return "goto";
  case T::LOCATION: return "location";
  case T::INPUT: return "input";
  case T::OUTPUT: return "output";
  case T::DECL: return "decl";
  case T::DEAD: return "dead";
  case T::FUNCTION_CALL: return "function_call";
  case T::FUNCTION_RETURN: return "function_return";
  case T::CONSTRAINT: return "constraint";
  case T::SHARED_READ: return "read";
  case T::SHARED_WRITE: return "write";
  case T::SPAWN: return "spawn";
  case T::MEMORY_BARRIER: return "fence";
  case T::ATOMIC_BEGIN: return "atomic_begin";
  case T::ATOMIC_END: return "atomic_end";
  }
  throw std::logic_error("Unrecognized SSA step");
}
}

bool enabled()
{
  return !directory.empty();
}

void redirect(const std::string &path)
{
  directory=path;
  times.clear();
}

void timing(const std::string &name, clockt::time_point start, clockt::time_point end)
{
  if(enabled())
    times[name] += std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
}

void goto_model(const goto_functionst &functions)
{
  s8::Scope s8_timer(s8::goto_json);
  irep_poolt pool;
  json_arrayt rows;
  for(const auto &fn : functions.function_map)
    for(const auto &ins : fn.second.body.instructions)
    {
      const auto &loc = ins.source_location();
      json_objectt row;
      row["function"] = json_stringt(fn.first);
      row["pc"] = number(ins.location_number);
      row["kind"] = json_stringt(ins.to_string());
      row["file"] = json_stringt(loc.get_file());
      row["line"] = json_stringt(loc.get_line());
      row["column"] = json_stringt(loc.get_column());
      row["property"] = json_stringt(loc.get_property_id());
      if(ins.is_backwards_goto())
        row["local_loop"] = json_stringt(goto_programt::loop_id(fn.first, ins));
      row["code"] = pool.ref(ins.code());
      if(ins.has_condition())
        row["condition"] = pool.ref(ins.condition());
      json_arrayt targets;
      for(const auto &target : ins.targets)
        targets.push_back(number(target->location_number));
      row["targets"] = std::move(targets);
      rows.push_back(std::move(row));
    }
  const auto &c = config.ansi_c;
  json_objectt layout;
  layout["char_bits"] = number(c.char_width);
  layout["short_bits"] = number(c.short_int_width);
  layout["int_bits"] = number(c.int_width);
  layout["long_bits"] = number(c.long_int_width);
  layout["long_long_bits"] = number(c.long_long_int_width);
  layout["pointer_bits"] = number(c.pointer_width);
  layout["wchar_bits"] = number(c.wchar_t_width);
  layout["char_unsigned"] = boolean(c.char_is_unsigned);
  layout["alignment_bytes"] = number(c.alignment);
  layout["endian_code"] = number(static_cast<unsigned>(c.endianness));
  json_objectt out;
  out["schema"] = number(1);
  out["layout"] = std::move(layout);
  out["instructions"] = std::move(rows);
  out["ireps"] = std::move(pool.rows);
  save("goto", out);
}

std::size_t visit(const goto_symex_statet &state)
{
  json_objectt row = place(state.source);
  row["thread"] = number(state.source.thread_nr);
  row["reachable_at_dispatch"] = boolean(state.reachable);
  json_arrayt frames;
  for(const auto &frame : state.call_stack())
  {
    json_objectt f;
    f["function"] = json_stringt(frame.function_identifier);
    // The root's saved calling PC is an end iterator. The creator of a child
    // thread is exported from the native witness_spawn_events separately.
    if(!frames.empty())
      f["caller"] = place(frame.calling_location);
    json_objectt loops;
    for(const auto &loop : frame.loop_iterations)
      if(loop.second.count && !loop.second.is_recursion)
        loops[id2string(loop.first)] = number(loop.second.count);
    f["loops"] = std::move(loops);
    frames.push_back(std::move(f));
  }
  row["frames"] = std::move(frames);
  visits.push_back(std::move(row));
  return visits.size(); // zero means no symex dispatch (e.g. memory-model rows)
}

void name_event(const SSA_stept &step, const std::string &name)
{
  if(enabled())
    event_names[&step] = name;
}

void equation(const char *name, const symex_target_equationt &model)
{
  s8::Scope s8_timer(s8::observer_equation);
  const auto before = clockt::now();
  irep_poolt pool;
  json_arrayt rows;
  const SSA_stept *previous = nullptr;
  std::size_t source_group = 0;
  for(const auto &s : model.SSA_steps)
  {
    json_objectt row = place(s.source);
    // Mirror the pinned SC same_source predicate. Only group membership among
    // shared accesses is exported as a cross-version semantic dependency.
    if(previous == nullptr || previous->source.function_id != s.source.function_id ||
       previous->source.thread_nr != s.source.thread_nr ||
       previous->source.pc->source_location() != s.source.pc->source_location())
      ++source_group;
    previous = &s;
    row["local_source_group"] = number(source_group);
    row["kind"] = json_stringt(step_kind(s.type));
    row["thread"] = number(s.source.thread_nr);
    row["visit"] = number(s.observer_visit);
    row["atomic_section"] = number(s.atomic_section_id);
    row["guard"] = pool.ref(s.guard);
    row["condition"] = pool.ref(s.cond_expr);
    row["lhs"] = pool.ref(s.ssa_lhs);
    row["rhs"] = pool.ref(s.ssa_rhs);
    row["full_lhs"] = pool.ref(s.ssa_full_lhs);
    row["original_lhs"] = pool.ref(s.original_full_lhs);
    row["assignment_type"] = number(static_cast<unsigned>(s.assignment_type));
    row["hidden"] = boolean(s.hidden);
    row["ignored"] = boolean(s.ignore);
    if(!s.comment.empty())
      row["comment"] = json_stringt(s.comment);
    if(s.is_assert())
      row["property"] = json_stringt(s.get_property_id());
    if(!s.called_function.empty())
      row["called"] = json_stringt(s.called_function);
    if(!s.ssa_function_arguments.empty())
    {
      json_arrayt args;
      for(const auto &arg : s.ssa_function_arguments)
        args.push_back(pool.ref(arg));
      row["arguments"] = std::move(args);
    }
    if(s.type == goto_trace_stept::typet::INPUT || s.is_output())
    {
      json_arrayt args;
      for(const auto &arg : s.io_args)
        args.push_back(pool.ref(arg));
      row["io_args"] = std::move(args);
      row["io_id"] = json_stringt(s.io_id);
      row["format"] = json_stringt(s.format_string);
    }
    if(s.ssa_lhs.is_not_nil())
    {
      row["local_symbol"] = json_stringt(s.ssa_lhs.get_identifier());
      row["object"] = json_stringt(s.ssa_lhs.get_original_name());
      row["address_l1"] = json_stringt(s.ssa_lhs.get_l1_object_identifier());
    }
    const auto found = event_names.find(&s);
    if(found != event_names.end())
      row["oc_name"] = json_stringt(found->second);
    rows.push_back(std::move(row));
  }
  json_arrayt edges, births, guards;
  for(const auto &edge : model.oc_edges)
  {
    json_objectt row;
    row["kind"] = json_stringt(edge.kind);
    row["from"] = json_stringt(edge.e1_str);
    row["to"] = json_stringt(edge.e2_str);
    row["guard"] = pool.ref(edge.expr);
    edges.push_back(std::move(row));
  }
  for(const auto &b : model.witness_spawn_events)
  {
    auto row = place(b.call_site);
    row["parent"] = number(b.creator_thread);
    row["child"] = number(b.child_thread);
    row["guard"] = pool.ref(b.guard);
    births.push_back(std::move(row));
  }
  for(const auto &it : model.oc_guard_map)
  {
    json_objectt row;
    row["local_symbol"] = json_stringt(it->ssa_lhs.get_identifier());
    row["guard"] = pool.ref(it->guard);
    row["solver_line"] = json_stringt(it->source.pc->source_location().get_line());
    guards.push_back(std::move(row));
  }
  json_objectt out;
  out["schema"] = number(1);
  out["phase"] = json_stringt(name);
  out["steps"] = std::move(rows);
  out["oc_edges"] = std::move(edges);
  out["oc_guards"] = std::move(guards);
  out["thread_births"] = std::move(births);
  out["ireps"] = std::move(pool.rows);
  save(name, out);
  timing("equation_export", before, clockt::now());
}

std::string declare_theory_snapshot()
{
  save("visits",visits);
  return directory;
}

const std::string &observation_directory() { return directory; }

void finish(int exit_code)
{
  save("visits", visits);
  json_objectt t;
  for(const auto &entry : times)
    t[entry.first] = json_numbert(std::to_string(entry.second));
  json_objectt out;
  out["schema"] = number(1);
  out["phase_nanoseconds"] = std::move(t);
  out["symbolic_instruction_dispatches"] = number(visits.size());
  out["exit_code"] = number(exit_code);
  save("metrics", out);
}

void gate(const char *state, const char *command)
{
  if(!std::getenv("INCDEAGLE_STAGE3_SESSION"))
    return;
  json_objectt status;
  status["state"] = json_stringt(state);
  save(state, status);
  std::string request;
  if(!std::getline(std::cin, request) || request != command)
    throw std::runtime_error("Native session closed or received an unexpected command");
}
}
