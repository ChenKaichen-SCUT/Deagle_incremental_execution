#ifndef DEAGLE_D1_BOOLEAN_DIFF_H
#define DEAGLE_D1_BOOLEAN_DIFF_H

#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace d1
{
using Key = std::vector<int>;
struct Hash
{
  size_t operator()(const Key &key) const
  {
    size_t h = 2166136261u;
    for(int number : key)
      h = (h ^ static_cast<unsigned>(number)) * 16777619u;
    return h;
  }
};

struct Variable
{
  int anchor = 0, orientation = 0, canonical = -1, peer = -1;
  std::string role = "Opaque", reason = "no_semantic_definition";
  int op = 0, output_sign = 0;
  Key inputs;
};

struct Model
{
  std::string path;
  std::vector<Variable> vars;
  std::vector<std::string> targets;
  Key assumptions;
  unsigned queries = 0;

  Model(const std::string &manifest, const std::string &anchors) : path(manifest)
  {
    static const std::map<std::string, int> ops =
      {{"and",1},{"or",2},{"xor",3},{"nand",4},{"nor",5},{"ite",6}};
    std::ifstream in(path), base(anchors);
    in.exceptions(std::ios::badbit);
    if(!in || !base) throw std::runtime_error("cannot read manifest/anchors");
    std::string line, op;
    size_t count = 0;
    while(std::getline(in, line))
    {
      if(line.compare(0, 2, "G\t") == 0)
      {
        std::istringstream fields(line.substr(2));
        int out, lit;
        if(!(fields >> op >> out) || out < 2) throw std::runtime_error("invalid gate");
        const int var = out / 2;
        if(vars.size() <= size_t(var)) vars.resize(var+1);
        auto &v = vars[var];
        v.op = v.op ? -1 : ops.at(op);
        v.role = "Aux";
        v.output_sign = out & 1;
        v.reason = v.op < 0 ? "multiple_gate_definitions" : "pending_gate";
        while(fields >> lit) v.inputs.push_back(lit);
      }
      else if(line.compare(0, 2, "N\t") == 0)
      {
        std::istringstream fields(line.substr(2));
        if(count || !(fields >> count) || !count) throw std::runtime_error("invalid solve boundary");
        int lit;
        while(fields >> lit) assumptions.push_back(lit);
      }
      else if(line == "QUERY") ++queries;
      else if(line.compare(0, 7, "TARGET\t") == 0) targets.push_back(line.substr(7));
      else if(line.compare(0, 3, "CO\t") == 0)
      {
        std::istringstream fields(line.substr(3));
        int a,b,x,y;
        if(!(fields >> a >> b >> x >> y) || std::min(x,y) < 0)
          throw std::runtime_error("invalid dynamic CO");
        size_t next = size_t(std::max(x,y)/2+1);
        if(vars.size() < next) vars.resize(next);
      }
    }
    if(!count) throw std::runtime_error("missing solve boundary");
    vars.resize(std::max(vars.size(), count));
    int var;
    while(base >> var)
    {
      auto &v = vars.at(var);
      base >> v.anchor >> v.orientation >> v.role >> v.reason;
      if(!base) throw std::runtime_error("malformed anchor");
    }
    std::sort(targets.begin(), targets.end());
  }

  // Local MiniSat literals use 2*var+sign. Canonical 0/1 denote false/true;
  // all nonconstant canonical literals use the P0 variable as their namespace.
  int canonical(int raw) const
  {
    if(raw == -1 || raw == -2) return raw + 2;
    if(raw < 2 || size_t(raw / 2) >= vars.size()) return -1;
    const int base = vars[raw / 2].canonical;
    return base < 0 ? -1 : base ^ (raw & 1);
  }
};

using Pair = std::array<std::vector<int>, 2>;
using Groups = std::unordered_map<Key, Pair, Hash>;

inline void pair_variables(Model &old, Model &now, int a, int b, int flip)
{
  auto &x = old.vars.at(a);
  auto &y = now.vars.at(b);
  if(x.peer >= 0 || y.peer >= 0) throw std::logic_error("mapping is not injective");
  x.peer = 2*b + flip;
  y.peer = 2*a + flip;
  x.canonical = 2*a;
  y.canonical = 2*a + flip;
  x.reason = y.reason = "matched";
}

inline void match(Model &old, Model &now)
{
  std::array<Model *, 2> sides{{&old, &now}};
  std::map<int, Pair> anchors;
  std::array<Key, 2> pending;
  for(int side = 0; side != 2; ++side)
    for(size_t i = 1; i < sides[side]->vars.size(); ++i)
    {
      auto &v = sides[side]->vars[i];
      if(v.anchor) anchors[v.anchor][side].push_back(int(i));
      else if(v.reason == "pending_gate") pending[side].push_back(int(i));
    }
  for(const auto &entry : anchors)
  {
    const auto &p = entry.second;
    if(p[0].size() == 1 && p[1].size() == 1)
    {
      int a = p[0][0], b = p[1][0];
      pair_variables(old, now, a, b, old.vars[a].orientation ^ now.vars[b].orientation);
    }
    else
      for(int side = 0; side != 2; ++side)
        for(int v : p[side])
          sides[side]->vars[v].reason = "different_or_ambiguous_complete_alias_class";
  }

  // Process both DAGs one dependency layer at a time. All candidates for a
  // definition appear in the same layer, even under a non-monotone renumbering.
  while(true)
  {
    Groups ready;
    for(int side = 0; side != 2; ++side)
    {
      auto &m = *sides[side];
      Key waiting;
      for(int index : pending[side])
      {
        const auto &v = m.vars[index];
        Key key{v.op};
        for(int l : v.inputs)
        {
          int translated = m.canonical(l);
          if(translated < 0) break;
          key.push_back(translated);
        }
        if(key.size() != v.inputs.size()+1)
        {
          waiting.push_back(index);
          continue;
        }
        if(v.op != 6) std::sort(key.begin()+1, key.end());
        ready[std::move(key)][side].push_back(index);
      }
      pending[side].swap(waiting);
    }
    if(ready.empty()) break;
    for(const auto &entry : ready)
    {
      const auto &p = entry.second;
      if(p[0].size() == 1 && p[1].size() == 1)
      {
        int a = p[0][0], b = p[1][0];
        pair_variables(old, now, a, b, old.vars[a].output_sign ^ now.vars[b].output_sign);
      }
      else
        for(int side = 0; side != 2; ++side)
          for(int v : p[side])
            sides[side]->vars[v].reason = p[0].size()>1 || p[1].size()>1
              ? "ambiguous_gate_definition" : "no_matching_resolved_gate";
    }
  }
  for(int side = 0; side != 2; ++side)
    for(int i : pending[side])
    {
      auto &m = *sides[side];
      auto &v = m.vars[i];
      for(int l : v.inputs)
        if(m.canonical(l) < 0)
        {
          v.reason = "unmapped_gate_input:" + std::to_string(l);
          break;
        }
    }
}
}
#endif
