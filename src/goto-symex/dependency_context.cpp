#include "dependency_context.h"
#include "goto_symex_state.h"
#include <goto-programs/goto_functions.h>
#include <util/std_expr.h>
#include <map>

namespace dependency_manifest
{
using instructiont = goto_programt::instructiont;
struct loopt
{
  unsigned first, last;
  irep_idt id;
  int site;
};
static std::map<const instructiont *, int> sites;
static std::map<irep_idt, std::vector<loopt>> loops;
static std::map<unsigned, int> births;
// A saved SSA source may have been copied across an atomic section or PC change.
static std::vector<std::pair<const instructiont *, unsigned>> origins;

std::string scalar_type(const typet &type)
{
  if(type.id() == ID_bool) return "bool";
  if(type.id() == ID_signedbv || type.id() == ID_unsignedbv || type.id() == ID_c_bool)
    return id2string(type.id()) + ":" + id2string(type.get(ID_width));
  return {};
}

std::string designator(const exprt &e)
{
  std::vector<std::string> parts{id2string(e.id())};
  if(e.id() == ID_symbol) parts.push_back(id2string(e.get(ID_identifier)));
  if(e.id() == ID_member) parts.push_back(id2string(e.get(ID_component_name)));
  if(e.id() == ID_constant)
  {
    parts.push_back(id2string(e.get(ID_value)));
    parts.push_back(scalar_type(e.type()));
  }
  for(const auto &child : e.operands()) parts.push_back(designator(child));
  return tuple(parts);
}

static std::string operation(const instructiont &ins)
{
  std::vector<std::string> parts{std::to_string(int(ins.type()))};
  if(ins.is_assign())
    parts.push_back(designator(ins.assign_lhs()));
  else if(ins.is_function_call())
  {
    parts.push_back(designator(ins.call_function()));
    for(const auto &arg : ins.call_arguments()) parts.push_back(designator(arg));
  }
  else if(ins.is_decl()) parts.push_back(designator(ins.decl_symbol()));
  else if(ins.is_dead()) parts.push_back(designator(ins.dead_symbol()));
  else if(ins.is_goto())
  {
    parts.push_back(ins.is_backwards_goto() ? "backedge" : "branch");
    // The loop predicate is version-specific. Multiple backedges are disambiguated
    // by the same local operation-neighbour check as other repeated sites.
  }
  else if(ins.is_assert()) parts.push_back(id2string(ins.source_location().get_property_id()));
  return tuple(parts);
}

void index_sites(const goto_functionst &functions)
{
  if(!sites.empty()) throw std::runtime_error("D1 expects one GOTO model per process");
  origins.emplace_back(nullptr, 0);
  for(const auto &f : functions.function_map)
  {
    const auto &body = f.second.body.instructions;
    std::vector<std::string> ops, keys;
    std::map<std::string, size_t> count, key_count;
    for(const auto &ins : body)
    {
      ops.push_back(operation(ins));
      ++count[ops.back()];
    }
    for(size_t i = 0; i < ops.size(); ++i)
    {
      std::vector<std::string> key{id2string(f.first), ops[i]};
      if(count[ops[i]] > 1)
      {
        key.push_back(i ? ops[i-1] : "BEGIN");
        key.push_back(i+1 < ops.size() ? ops[i+1] : "END");
      }
      keys.push_back(tuple(key));
      ++key_count[keys.back()];
    }
    size_t i = 0;
    for(const auto &ins : body)
    {
      int id = int(sites.size())+1;
      sites.emplace(&ins, id);
      row("S", {std::to_string(id), keys[i], key_count[keys[i]] == 1 ? "unique" : "ambiguous",
                id2string(f.first), id2string(ins.source_location().get_file()),
                id2string(ins.source_location().get_line())});
      if(ins.is_backwards_goto() && ins.targets.size() == 1)
        loops[f.first].push_back({ins.get_target()->location_number, ins.location_number,
                                  goto_programt::loop_id(f.first, ins), id});
      ++i;
    }
  }
}

int checked_context(const symex_targett::sourcet &source)
{
  const int id = source.d1_context;
  return id > 0 && origins.at(id) == std::make_pair(&*source.pc, source.thread_nr) ? id : -1;
}

void birth(unsigned child, const symex_targett::sourcet &parent)
{
  if(!births.emplace(child, checked_context(parent)).second)
    throw std::runtime_error("D1 cannot identify repeated symex thread creation");
}

void context(goto_symex_statet &state)
{
  auto &source = state.source;
  auto site = sites.find(&*source.pc);
  if(site == sites.end() || state.call_stack().empty())
  {
    source.d1_context = -1;
    return;
  }
  const auto &frame = state.call_stack().top();
  const auto thread = births.find(source.thread_nr);
  int spawned = source.thread_nr == 0 ? 0 : thread == births.end() ? -1 : thread->second;
  int caller = state.call_stack().size() == 1 ? 0 : checked_context(frame.calling_location);
  source.d1_context = int(origins.size());
  origins.emplace_back(&*source.pc, source.thread_nr);
  std::vector<std::string> fields{std::to_string(source.d1_context), std::to_string(site->second),
                                  std::to_string(spawned), std::to_string(caller)};
  const auto pos = source.pc->location_number;
  for(const auto &loop : loops[source.function_id])
    if(loop.first <= pos && pos <= loop.last)
    {
      auto it = frame.loop_iterations.find(loop.id);
      fields.push_back(std::to_string(loop.site));
      fields.push_back(std::to_string(it == frame.loop_iterations.end() ? 0 : it->second.count));
    }
  row("X", fields);
}
}
