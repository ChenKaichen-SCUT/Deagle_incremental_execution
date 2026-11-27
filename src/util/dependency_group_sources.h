#ifndef CPROVER_UTIL_DEPENDENCY_GROUP_SOURCES_H
#define CPROVER_UTIL_DEPENDENCY_GROUP_SOURCES_H
#include <cstdint>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace dependency_manifest {
// Canonical D4.3-A ownership, available before a raw input or declaration is consumed.
class group_owner_interfacet
{
public:
  virtual const std::string &boolean(const int *,size_t)=0;
  virtual void node(int,const std::string &)=0;
  virtual std::string theory(int,int,int) const=0;
  virtual ~group_owner_interfacet()=default;
};
class group_sourcest : public group_owner_interfacet
{
  std::map<int,std::pair<int,int>> contexts;
  std::map<std::string,std::string> events;
  std::vector<std::string> node_names;
  std::set<std::string> keys;
  std::vector<std::pair<uint32_t,const std::string *>> gates;
  uint32_t sequence=0;
  const std::string *intern(std::string key) { return &*keys.insert(std::move(key)).first; }
public:
  const std::string *owner=nullptr;
  const char *phase="outside";
  void row(const char *,const std::vector<std::string> &);
  void enter(const char *,int,unsigned);
  void gate(const char *,int);
  const std::string &boolean(const int *,size_t) override;
  void node(int,const std::string &) override;
  std::string theory(int op,int a,int b) const override;
};
extern group_sourcest *group_sources;
}
#endif
