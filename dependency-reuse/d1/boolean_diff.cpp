#include "boolean_diff.h"
#include <cstdlib>

namespace d1
{
struct Leaf
{
  unsigned id = 0;
  std::array<unsigned, 2> count{{0,0}};
};

bool same_query(const Model &old, const Model &now)
{
  if(old.queries != 1 || now.queries != 1 || old.targets.empty() || old.targets != now.targets)
    return false;
  std::array<Key, 2> assumptions;
  for(unsigned s = 0; s < 2; ++s)
  {
    const Model &m = s ? now : old;
    for(int l : m.assumptions)
    {
      int t = m.canonical(l);
      if(t < 0) return false;
      assumptions[s].push_back(t);
    }
    std::sort(assumptions[s].begin(), assumptions[s].end());
  }
  return assumptions[0] == assumptions[1];
}

void compare(const Model &old, const Model &now, const std::string &out)
{
  std::ofstream variables(out+"/variables.tsv"), occurrences(out+"/occurrences.tsv"),
    content(out+"/clause-keys.tsv"), counts(out+"/clause-counts.tsv");
  for(auto *f : {&variables, &occurrences, &content, &counts})
    f->exceptions(std::ios::badbit | std::ios::failbit);
  std::unordered_map<Key,Leaf,Hash> leaves;
  bool query_matches = same_query(old, now);
  for(int side = 0; side != 2; ++side)
  {
    const auto &m = side ? now : old;
    for(size_t i = 1; i < m.vars.size(); ++i)
    {
      const auto &v = m.vars[i];
      variables << side << '\t' << i << '\t' << v.peer << '\t' << v.role << '\t'
                << v.reason << '\t' << v.anchor << '\n';
    }
    std::ifstream file(m.path);
    file.exceptions(std::ios::badbit);
    std::string line;
    size_t seq = 0;
    while(std::getline(file,line))
    {
      if(line.compare(0,2,"C\t") != 0) continue;
      if(line.size()<3) throw std::runtime_error("malformed clause");
      ++seq;
      char scope = line[2];
      int missing = -1;
      Key key{int(scope)};
      const char *at = line.c_str()+3;
      while(*at)
      {
        char *next;
        long raw = std::strtol(at,&next,10);
        if(at == next) throw std::runtime_error("invalid clause literal");
        int normalized = m.canonical(int(raw));
        if(normalized < 0)
        {
          missing = int(raw);
          break;
        }
        key.push_back(normalized);
        at = next;
      }
      unsigned id = 0;
      occurrences << side << '\t' << seq << '\t' << scope << '\t';
      if(scope != 'B' && scope != 'Q') occurrences << "0\tunknown_origin";
      else if(scope == 'Q' && !query_matches) occurrences << "0\tquery_scope_changed_or_unknown";
      else if(missing != -1) occurrences << "0\tliteral:" << missing;
      else
      {
        std::sort(key.begin()+1,key.end());
        key.erase(std::unique(key.begin()+1,key.end()),key.end());
        auto inserted = leaves.emplace(key,Leaf{});
        auto &leaf = inserted.first->second;
        if(inserted.second)
        {
          leaf.id = unsigned(leaves.size());
          content << leaf.id << '\t' << scope;
          for(auto it = key.begin()+1; it != key.end(); ++it) content << '\t' << *it;
          content << '\n';
        }
        id = leaf.id;
        ++leaf.count[side];
        occurrences << id << "\t-";
      }
      occurrences << '\n';
    }
  }
  for(const auto &entry : leaves)
  {
    const auto &l = entry.second;
    counts << l.id << '\t' << char(entry.first.front()) << '\t' << l.count[0] << '\t'
           << l.count[1] << '\n';
  }
  for(auto *f : {&variables,&occurrences,&content,&counts}) f->close();
}
}

int main(int argc, char **argv)
{
  const bool refine=argc==7 && std::string(argv[6])=="--d3-mapping";
  if(argc!=6 && !refine) return 2;
  try
  {
    d1::Model old(argv[1],argv[3]), now(argv[2],argv[4]);
    d1::match(old,now);
    if(refine) d1::refine_duplicate_gates(old,now);
    d1::compare(old,now,argv[5]);
  }
  catch(const std::exception &e)
  {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
