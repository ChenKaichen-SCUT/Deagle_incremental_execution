#include "stable_identity.h"
#include "std_expr.h"
#include "symbol.h"
#include "config.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <set>
#include <stdexcept>
#include <tuple>
#include <unordered_map>

namespace stable_identity
{
bool enabled = std::getenv("DEAGLE_SI1B_CATALOG") != nullptr;
unsigned current_origin=0;
namespace
{
using Clock = std::chrono::steady_clock;
using Handle = std::tuple<const void *,unsigned,const void *>;
struct Store
{
  std::map<std::string,Word> strings;
  std::vector<std::string> dictionary{""};
  std::map<char,std::map<Words,Word>> intern;
  std::map<typet,Word> types;
  std::map<exprt,Word> terms;
  std::map<Handle,Word> handles;
  std::map<Word,Word> hit_counts;
  std::map<char,std::set<Words>> unique;
  Words stream;
  Word owner=0, path=0, next=0, next_atom=1;
  bool audit=std::getenv("DEAGLE_SI1B_AUDIT")!=nullptr;
  Frame *current=nullptr;
  std::array<uint64_t,12> counts{};
  std::array<uint64_t,3> ns{};
  int timing=-1;
  Clock::time_point start;
};
Store &db() { static Store d; return d; }
class Charge
{
  int old;
  void switch_to(int i)
  {
    auto &s=db(); const auto now=Clock::now();
    if(s.timing>=0) s.ns[s.timing]+=std::chrono::duration_cast<std::chrono::nanoseconds>(now-s.start).count();
    s.timing=i; s.start=now;
  }
public:
  explicit Charge(int i):old(db().timing) {switch_to(i);}
  ~Charge(){switch_to(old);}
};
Word number(const irep_idt &id)
{
  const auto &s=id2string(id);
  if(s.empty() || s.find_first_not_of("0123456789")!=std::string::npos) return 0;
  return Word(std::stoul(s));
}
using Tokens=std::map<std::pair<std::string,unsigned>,unsigned>;
Tokens load_tokens()
{
  const char *path=std::getenv("DEAGLE_SI1B_TOKENS");
  if(!path) throw std::runtime_error("missing SI-1B source catalog");
  std::ifstream in(path); std::string header,name;unsigned line,id;Tokens out;
  if(!std::getline(in,header) || header!="SI1TOK1") throw std::runtime_error("bad SI-1B token directory");
  while(in>>name>>line>>id)
    if(!line || !id || !out.emplace(std::make_pair(name,line),id).second)
      throw std::runtime_error("duplicate SI-1B source location");
  if(!in.eof()) throw std::runtime_error("truncated SI-1B token directory");
  return out;
}
Words loc(const source_locationt &l)
{
  static const auto tokens=load_tokens();
  const auto &file=id2string(l.get_file()); const auto line=number(l.get_line());
  const auto found=tokens.find({file,line});
  return {text(file),line,number(l.get_column()),text(id2string(l.get_function())),found==tokens.end()?0:found->second};
}
void distinct(char tag,const Words &v)
{
  if(db().unique[tag].insert(v).second) row(tag,v);
  else ++db().counts[0];
}
// Exact local type/attribute tree; omit debug locations and intern strings separately.
Word shape(const irept &x)
{
  Words b{text(id2string(x.id())),Word(x.get_sub().size())};
  for(const auto &s:x.get_sub()) b.push_back(shape(s));
  std::map<std::string,const irept *> named;
  for(const auto &s:x.get_named_sub())
    if(s.first!=ID_C_source_location) named.emplace(id2string(s.first),&s.second);
  for(const auto &s:named) {b.push_back(text(s.first));b.push_back(shape(*s.second));}
  return intern_row('J',b);
}
}
Word text(const std::string &s)
{
  if(s.empty()) return 0;
  auto &d=db();
  auto p=d.strings.emplace(s,d.dictionary.size());
  if(p.second) d.dictionary.push_back(s);
  return p.first->second;
}
void row(char tag,const Words &data)
{
  auto &buf=db().stream;
  buf.push_back(static_cast<unsigned char>(tag));
  buf.push_back(data.size());
  buf.insert(buf.end(),data.begin(),data.end());
}
Word intern_row(char tag,const Words &data)
{
  auto &table=db().intern[tag];
  auto p=table.emplace(data,table.size()+1);
  if(p.second)
  {
    Words values{p.first->second}; values.insert(values.end(),data.begin(),data.end()); row(tag,values);
  }
  return p.first->second;
}
Word type(const typet &t)
{
  auto &memo=db().types; auto p=memo.emplace(t,0);
  if(p.second) p.first->second=shape(t);
  return p.first->second;
}
Word term(const exprt &e)
{
  auto &memo=db().terms;
  auto p=memo.emplace(e,0);
  if(!p.second) return p.first->second;
  // Include semantic named attributes, without recursively expanding SSA definitions.
  Words attrs;
  std::map<std::string,const irept *> names;
  for(const auto &n:e.get_named_sub())
    if(n.first!=ID_type && n.first!=ID_C_source_location && n.first!=ID_identifier && n.first!=ID_value)
      names.emplace(id2string(n.first),&n.second);
  for(const auto &n:names) { attrs.push_back(text(n.first));attrs.push_back(shape(*n.second)); }
  Words body{text(id2string(e.id())),type(e.type()),text(id2string(e.get(ID_identifier))),
    text(id2string(e.get(ID_value))),intern_row('W',attrs)};
  for(const auto &c:e.operands()) body.push_back(term(c));
  return p.first->second=intern_row('E',body);
}
void declaration(const symbolt &s)
{
  Charge time(0);
  Words v=loc(s.location);
  v.insert(v.end(),{text(id2string(s.name)),text(id2string(s.base_name)),type(s.type),
                     Word(s.is_type),Word(s.is_macro),Word(s.is_parameter)});
  distinct('D',v);
}
Lower::Lower(const source_locationt &l,const std::string &role):previous(current_origin)
{
  if(!enabled) return;
  Charge time(0);
  Words v=loc(l); v.push_back(text(role));v.push_back(previous); current_origin=intern_row('O',v);
}
Lower::Lower(unsigned from,const std::string &role):previous(current_origin)
{
  if(enabled) { Charge time(0); current_origin=from ? intern_row('O',{0,0,0,0,0,text(role),from}) : 0; }
}
Lower::~Lower(){ current_origin=previous; }
unsigned copy_origin(unsigned orig)
{
  if(!enabled || !orig) return 0;
  Charge time(0);
  return intern_row('O',{0,0,0,0,0,text("goto.copy_from"),orig});
}
void site(unsigned local,unsigned orig,const std::string &fn,const source_locationt &l,const std::string &role)
{
  Charge time(0);
  Words v=loc(l); v.insert(v.end(),{local,orig,text(fn),text(role)}); row('I',v);
}
void value(const std::string &s,const std::string &event,int ctx,const std::string &role,
           const std::string &object,const std::string &base,const typet &t,bool global)
{
  Charge time(0);
  distinct('V',{text(s),text(event),Word(ctx),text(role),text(object),text(base),type(t),Word(global)});
}
Owner::Owner(const char *phase,int ctx,unsigned kind,unsigned assignment,const std::string &lhs):previous(0)
{
  if(!enabled) return;
  Charge time(0); previous=db().owner;
  db().owner=intern_row('U',{text(phase),Word(ctx),kind,assignment,text(lhs)});
}
Owner::~Owner(){if(enabled) db().owner=previous;}
void clear_cache(const void *converter,unsigned domain)
{
  if(!enabled) return;
  Charge time(1);
  auto &h=db().handles;
  for(auto it=h.begin();it!=h.end();)
    if(std::get<0>(it->first)==converter && std::get<1>(it->first)==domain) it=h.erase(it); else ++it;
  ++db().counts[9];
}
Frame::Frame(const void *converter,unsigned domain,const void *entry,const exprt &expr,bool hit):
  previous(nullptr),expression(&expr)
{
  if(!enabled) return;
  Charge time(1);auto &d=db(); previous=d.current; saved_path=d.path; d.path=0;
  const auto expr_id=term(expr);
  audit_domain=entry && d.audit ? domain : 0; first_atom=d.next_atom;
  if(hit && audit_domain) row('Y',{domain,1,text(id2string(expr.id())),0,0});
  const Handle handle{converter,domain,entry};
  if(hit)
  {
    ++d.counts[domain==1?1:3]; auto it=d.handles.find(handle);
    if(it!=d.handles.end()) {local=it->second;++d.hit_counts[local];}
    else ++d.counts[5];
  }
  else
  {
    if(entry) ++d.counts[domain==1?2:4];
    fresh=true;local=++d.next;
    if(entry) d.handles[handle]=local; // A native miss always starts a new lifetime.
    row('T',{local,domain,expr_id});
  }
  if(!previous)
  {
    if(d.owner && local) { ++d.counts[6];distinct('A',{d.owner,local}); }
  }
  else if(local && previous->local)
  {
    // Identify the operand by its real parent or one unique equal expression, never by execution order.
    const auto &pe=*previous->expression; Word edge=UINT32_MAX;
    if(&pe==&expr) edge=0;
    else
    {
      Word index=1, equal=0, candidate=0;
      for(const auto &op:pe.operands())
      {
        if(&op==&expr){edge=index;break;}
        if(op==expr){++equal;candidate=index;}
        ++index;
      }
      if(edge==UINT32_MAX && equal==1) edge=candidate;
    }
    if(edge==UINT32_MAX) ++d.counts[5];
    distinct('C',{previous->local,edge,domain,local});
  }
  d.current=this;
}
Frame::~Frame(){if(enabled) { db().current=previous; db().path=saved_path; }}
void Frame::finish(const Words &lits)
{
  Charge time(1);
  if(audit_domain) row('Y',{audit_domain,0,text(id2string(expression->id())),first_atom,db().next_atom});
  Words v{local};v.insert(v.end(),lits.begin(),lits.end());row('L',v);
}
Path::Path(const char *name,unsigned lane,unsigned option):previous(0)
{
  if(!enabled) return;
  Charge time(1); previous=db().path; db().path=intern_row('P',{previous,text(name),lane,option});
}
Path::~Path(){if(enabled) db().path=previous;}
void role(const char *name,Word bit,Word flags,Word lit)
{
  if(!enabled || !db().current || !db().current->local) return;
  Charge time(1);
  distinct('R',{db().current->local,db().path,text(name),bit,flags,lit});
}
void cnf_result(const char *label,Word output,const Words &args)
{
  if(!enabled || !db().current) return;
  // Native CNF helper returns are meaningful for a directly matching Boolean conversion.
  // BV helpers have separate named, lane-specific roles.
  const auto &expr=*db().current->expression;
  if(expr.type().id()!=ID_bool || id2string(expr.id())!=label) return;
  role("cnf-return",0,args.size(),output);
  if(expr.id()==ID_if)
    for(Word i=0;i<args.size();++i) role("ite-operand",i,args.size(),args[i]);
}
void named(const std::string &name,const typet &t,const Words &lits)
{
  Charge time(0); Words v{text(name),type(t)};
  v.insert(v.end(),lits.begin(),lits.end());distinct('B',v);
}
void named_bool(const std::string &s,Word v)
{
  Charge time(0);distinct('B',{text(s),0,v});
}
void allocation(Word begin,Word count)
{
  if(!enabled) return;
  Charge time(0);
  db().next_atom=begin+count;
  row('N',{begin,count,db().current ? db().current->local : 0});
}
void seal(Word n)
{
  if(!enabled) return;
  auto &d=db();
  const auto started=Clock::now();
  for(const auto &h:d.hit_counts) row('h',{h.first,h.second});
  row('Z',{n,Word(config.ansi_c.pointer_width),Word(config.bv_encoding.object_bits),
           Word(config.ansi_c.endianness),text(id2string(config.ansi_c.arch)),Word(config.ansi_c.alignment)});
  const std::string path=std::getenv("DEAGLE_SI1B_CATALOG");
  std::ofstream f(path,std::ios::binary|std::ios::trunc);f.exceptions(std::ios::badbit|std::ios::failbit);
  f.write("SI1BIN01",8);
  auto word=[&](Word x){f.write(reinterpret_cast<const char*>(&x),4);};
  word(0x01020304);word(d.dictionary.size());
  for(const auto &s:d.dictionary){word(s.size());f.write(s.data(),s.size());}
  word(d.stream.size());f.write(reinterpret_cast<const char*>(d.stream.data()),d.stream.size()*4);
  f.write("SI1END01",8);f.close();
  const auto serial=std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-started).count();
  std::ofstream meta(path+".stats");meta.exceptions(std::ios::badbit|std::ios::failbit);
  meta<<"register_ns "<<d.ns[0]<<"\ncache_role_ns "<<d.ns[1]<<"\nserialize_ns "<<serial<<"\n";
  const char *names[]={"dedup_rows","bool_hits","bool_misses","bv_hits","bv_misses","missing_child_or_template",
                       "owner_associations","reserved7","reserved8","cache_clears"};
  for(unsigned i=0;i<10;++i) meta<<names[i]<<" "<<d.counts[i]<<"\n";
  enabled=false;
  if(std::getenv("DEAGLE_SI1B_MODEL_ONLY")) { meta.close();std::fflush(nullptr);std::_Exit(77); }
}
}
