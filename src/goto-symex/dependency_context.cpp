#include <util/stable_identity.h>
#include "dependency_context.h"
#include "goto_symex_state.h"
#include <goto-programs/goto_functions.h>
#include <util/std_expr.h>
#include <algorithm>
#include <map>
#include <set>
#include <limits>
#include <util/arith_tools.h>
#include <util/c_types.h>
#include <util/bitvector_types.h>
#include <util/config.h>
#include <util/namespace.h>
#include <util/symbol.h>

namespace dependency_manifest
{
using instructiont = goto_programt::instructiont;
struct loopt
{
  unsigned first, last;
  irep_idt id;
  std::string observed_loop_name;
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

// The target ABI, ordered components and all reachable tag definitions participate
// in the key. Memoizing tag definitions separately handles recursive pointer types.
static std::map<typet, unsigned> layouts;
static std::string describe_type(const irept &node, std::set<std::string> &tags)
{
  if(node.id()==ID_struct_tag || node.id()==ID_union_tag || node.id()==ID_c_enum_tag)
    tags.insert(id2string(node.get(ID_identifier)));
  std::vector<std::string> children, fields;
  for(const auto &child : node.get_sub()) children.push_back(describe_type(child,tags));
  std::map<std::string,std::string> named;
  for(const auto &item : node.get_named_sub())
    if(item.first!=ID_C_source_location) // debug provenance includes the run's working directory
      named.emplace(id2string(item.first),describe_type(item.second,tags));
  for(const auto &item : named) fields.push_back(tuple({item.first,item.second}));
  return tuple({id2string(node.id()),tuple(children),tuple(fields)});
}

unsigned recorded_layout(const typet &type)
{
  auto p=layouts.find(type);
  return p==layouts.end() ? 0 : p->second;
}

// A stable storage layout alone cannot identify a pointer object number. Keep
// only a low integer prefix supported by every union view on little-endian targets.
static std::size_t integer_prefix(const typet &t,const namespacet &ns)
{
  if(t.id()==ID_signedbv || t.id()==ID_unsignedbv) return to_bitvector_type(t).get_width();
  if(t.id()==ID_struct_tag) return integer_prefix(ns.follow_tag(to_struct_tag_type(t)),ns);
  if(t.id()==ID_union_tag) return integer_prefix(ns.follow_tag(to_union_tag_type(t)),ns);
  if(t.id()==ID_struct || t.id()==ID_union)
  {
    const auto &members=to_struct_union_type(t).components();
    if(members.empty()) return 0;
    std::size_t prefix=std::numeric_limits<std::size_t>::max();
    for(const auto &member:members)
    {
      if(member.get_is_padding()) return 0;
      prefix=std::min(prefix,integer_prefix(member.type(),ns));
      if(t.id()==ID_struct || !prefix) break;
    }
    return prefix;
  }
  if(t.id()==ID_array)
  {
    const auto &array=to_array_type(t);
    const auto &element=array.element_type();
    if(element.id()!=ID_signedbv && element.id()!=ID_unsignedbv) return 0;
    const auto count=numeric_cast<std::size_t>(array.size());
    const auto width=to_bitvector_type(element).get_width();
    if(count.has_value() && width && *count<=std::numeric_limits<std::size_t>::max()/width) return *count*width;
  }
  return 0;
}

unsigned aggregate_layout(const typet &type,const namespacet &ns)
{
  if(type.id()!=ID_struct_tag && type.id()!=ID_union_tag && type.id()!=ID_struct && type.id()!=ID_union)
    return 0;
  const auto inserted=layouts.emplace(type,0);
  if(!inserted.second) return inserted.first->second;
  std::set<std::string> pending;
  std::map<std::string,std::string> tags;
  const auto root=describe_type(type,pending);
  while(!pending.empty())
  {
    auto name=*pending.begin();
    pending.erase(pending.begin());
    if(tags.count(name)) continue;
    const symbolt *sym=nullptr;
    if(ns.lookup(name,sym) || !sym->is_type || sym->type.is_nil()) return 0;
    tags.emplace(name,describe_type(sym->type,pending));
  }
  const auto &abi=config.ansi_c;
  std::vector<std::string> fields{id2string(abi.arch),std::to_string(int(abi.os)),
    std::to_string(int(abi.endianness)),std::to_string(abi.char_width),std::to_string(abi.pointer_width),
    std::to_string(abi.alignment),root};
  for(const auto &item:tags) fields.push_back(tuple({item.first,item.second}));
  unsigned id=layouts.size();
  inserted.first->second=id;
  const auto prefix=abi.endianness==configt::ansi_ct::endiannesst::IS_LITTLE_ENDIAN ? integer_prefix(type,ns) : 0;
  row("LAYOUT",{std::to_string(id),tuple(fields),std::to_string(prefix)});
  return id;
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
      if(stream) ++count[ops.back()];
    }
    for(size_t i = 0; stream && i < ops.size(); ++i)
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
      if(stable_identity::enabled)
        stable_identity::site(id,ins.stable_origin,id2string(f.first),ins.source_location(),ops[i]+(ins.is_goto() ? (ins.condition().is_true()?".unconditional":".conditional") : ""));
      if(stream) row("S", {std::to_string(id), keys[i], key_count[keys[i]] == 1 ? "unique" : "ambiguous",
                id2string(f.first), id2string(ins.source_location().get_file()),
                id2string(ins.source_location().get_line())});
      if(identities41)
      {
        std::set<std::string> tags;
        std::vector<std::string> targets;
        for(const auto &target:ins.targets) targets.push_back(operation(*target));
        row("SITE41",{std::to_string(id),tuple({ops[i],describe_type(ins.code(),tags),
          ins.has_condition()?describe_type(ins.condition(),tags):"",tuple(targets)})});
      }
      if(ins.is_backwards_goto() && ins.targets.size() == 1)
        loops[f.first].push_back({ins.get_target()->location_number, ins.location_number,
                                  stream ? goto_programt::loop_id(f.first, ins) : irep_idt(),
                                  id2string(f.first)+"."+std::to_string(ins.loop_number), id});
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
      // A shadow observation must never intern a future native loop identifier.
      auto it = stream ? frame.loop_iterations.find(loop.id) : std::find_if(
        frame.loop_iterations.begin(), frame.loop_iterations.end(),
        [&](const decltype(frame.loop_iterations)::value_type &item) {return id2string(item.first)==loop.observed_loop_name;});
      fields.push_back(std::to_string(loop.site));
      fields.push_back(std::to_string(it == frame.loop_iterations.end() ? 0 : it->second.count));
    }
  if(stable_identity::enabled)
  {
    stable_identity::Words numeric;
    for(const auto &s:fields) numeric.push_back(stable_identity::Word(std::stoi(s)));
    stable_identity::row('X',numeric);
  }
  if(stream) row("X", fields);
}
}
