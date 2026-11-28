#ifndef CPROVER_UTIL_STABLE_IDENTITY_H
#define CPROVER_UTIL_STABLE_IDENTITY_H
#include "stable_identity_fwd.h"
#include <cstdint>
#include <string>
#include <vector>

class exprt;
class typet;
class irept;
class source_locationt;
class symbolt;

namespace stable_identity
{
using Word = uint32_t;
using Words = std::vector<Word>;
Word text(const std::string &s);
Word type(const typet &t);
Word term(const exprt &e);
Word intern_row(char tag, const Words &body);
void row(char tag, const Words &body);
void declaration(const symbolt &s);
void site(unsigned local, unsigned origin, const std::string &function,
          const source_locationt &, const std::string &role);
void value(const std::string &symbol, const std::string &event, int context,
           const std::string &role, const std::string &object, const std::string &base,
           const typet &type, bool global);
class Lower
{
  unsigned previous;
public:
  Lower(const source_locationt &, const std::string &role);
  Lower(unsigned derived_from,const std::string &role);
  ~Lower();
};
unsigned copy_origin(unsigned original);
class Owner
{
  unsigned previous;
public:
  Owner(const char *phase, int context, unsigned kind, unsigned assignment, const std::string &lhs);
  ~Owner();
};
class Frame
{
  friend void role(const char *, Word, Word, Word);
  friend void allocation(Word, Word);
  friend void cnf_result(const char *, Word, const Words &);
  Frame *previous;
  unsigned saved_path=0;
  const exprt *expression;
  Word local=0;
  bool fresh=false;
  Word audit_domain=0, first_atom=0;
public:
  Frame(const void *converter, unsigned domain, const void *entry, const exprt &expr, bool hit);
  ~Frame();
  void finish(const Words &values);
  void scalar(Word lit) { if(enabled && fresh) finish({lit}); }
  template<class BV> void bits(const BV &bv)
  {
    if(enabled && fresh) { Words values; values.reserve(bv.size());
      for(const auto &l : bv) values.push_back(l.get());
      finish(values); }
  }
};
void role(const char *label, Word bit, Word flags, Word literal);
void cnf_result(const char *label, Word output, const Words &arguments);
class Path
{
  unsigned previous;
public:
  Path(const char *name, unsigned lane, unsigned option);
  ~Path();
};
void named(const std::string &, const typet &, const Words &values);
void named_bool(const std::string &, Word value);
template<class BV> void named_bits(const std::string &s, const typet &t, const BV &bv)
{
  Words data; data.reserve(bv.size());
  for(const auto &l : bv) data.push_back(l.get());
  named(s,t,data);
}
void allocation(Word begin, Word count);
void seal(Word n);
}
#endif
