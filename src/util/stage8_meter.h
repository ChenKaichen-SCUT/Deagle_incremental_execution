// Optional Linux-only measurement for the two fixed diagnostic worktrees.
#pragma once
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <fstream>
#include <string>
#include <unistd.h>
#include <cstdint>

namespace s8 {
inline uint64_t ns(clockid_t id) {
  timespec t{}; clock_gettime(id, &t);
  return uint64_t(t.tv_sec)*1000000000ULL+t.tv_nsec;
}
#define S8_ITEMS(X) X(front) X(preprocess) X(parse) X(typecheck) X(goto_convert) X(goto_process) X(goto_json) X(irep_write) X(irep_read) X(rebind) X(prefix_symbols) X(prefix_dispatch) X(other_dispatch) X(sc) X(event_list) X(rf) X(po) X(rf_selected) X(po_selected) X(rf_replay) X(sc_check) X(sc_thread) X(encode_graph) X(ssa_convert) X(graph_load) X(search) X(lemma_prepare) X(lemma_worker) X(lemma_submit) X(conflict_record) X(observer_equation)
#define S8_ID(k) k,
enum Key { S8_ITEMS(S8_ID) total_keys };
#undef S8_ID
struct Sample {uint64_t wall=0, cpu=0, calls=0;};
struct State {
  std::string out, mode, rf_keys, po_keys;
  bool detail=false, deep=false, searching=false;
  unsigned prefix=0, dispatch=0, first_decisions=0, first_conflicts=0;
  uint64_t born=0, cpu_born=0, inherited_cpu=0, clause_hash=14695981039346656037ULL, var_hash=14695981039346656037ULL;
  uint64_t clauses=0, vars=0;
  std::array<Sample,total_keys> sums{};
  FILE *sequence=nullptr;
  State() {
    const char *p=std::getenv("S8_OUT");
    if(p) out=p;
    detail=!out.empty(); deep=detail && std::getenv("S8_STREAM");
    p=std::getenv("S8_MODE"); if(p) mode=p;
    p=std::getenv("S8_PREFIX"); if(p) prefix=std::strtoul(p,nullptr,10);
    p=std::getenv("S8_RF"); if(p) rf_keys=p;
    p=std::getenv("S8_PO"); if(p) po_keys=p;
    if(detail) {born=ns(CLOCK_MONOTONIC); cpu_born=ns(CLOCK_PROCESS_CPUTIME_ID);}
  }
};
inline State &state() { static State instance; return instance; }
inline bool only(const char *mode) {return state().mode==mode;}
inline bool chosen(const std::string &keys,const std::string &k) {return keys.find("|"+k+"|")!=std::string::npos;}
struct Scope {
  Key key; bool active; uint64_t w=0,c=0;
  explicit Scope(Key k,bool enabled=true):key(k),active(enabled && state().detail) {
    if(active) {w=ns(CLOCK_MONOTONIC);c=ns(CLOCK_PROCESS_CPUTIME_ID);}
  }
  ~Scope(){ if(active){auto &s=state().sums[key];s.cpu+=ns(CLOCK_PROCESS_CPUTIME_ID)-c;s.wall+=ns(CLOCK_MONOTONIC)-w;++s.calls;} }
};
inline void reset_at_command(const std::string &dir) {
  if(!state().detail) return;
  State fresh; fresh.out=dir; state()=fresh;
}
inline void flush() {
  auto &s=state(); if(!s.detail) return;
  const uint64_t end=ns(CLOCK_MONOTONIC),cpu_end=ns(CLOCK_PROCESS_CPUTIME_ID);
  static const char *names[]={
#define S8_NAME(k) #k,
  S8_ITEMS(S8_NAME)
#undef S8_NAME
  };
  std::ofstream f(s.out+"/s8-native.tsv");
  f<<"span\t"<<s.born<<"\t"<<end<<"\t"<<s.inherited_cpu+cpu_end-s.cpu_born<<"\n";
  for(unsigned i=0;i<total_keys;++i) {auto &v=s.sums[i];f<<names[i]<<"\t"<<v.calls<<"\t"<<v.wall<<"\t"<<v.cpu<<"\n";}
  if(s.sequence) {std::fclose(s.sequence);s.sequence=nullptr;}
}
struct Finish {Finish(){(void)state();} ~Finish(){flush();}};
inline void word(uint64_t &h, uint32_t n) { h=(h ^ n)*1099511628211ULL; }
inline void raw(uint32_t n) {
  State &s=state(); if(!s.deep) return;
  if(!s.sequence) s.sequence=std::fopen((s.out+"/s8-input.bin").c_str(),"wb");
  if(s.sequence) std::fwrite(&n,sizeof(n),1,s.sequence);
}
template<class Literals> inline void clause(const Literals &l) {
  State &s=state(); if(!s.detail || s.searching) return;
  ++s.clauses; word(s.clause_hash,l.size()); raw(0xfffffff0U);raw(l.size());
  for(int i=0;i<l.size();++i){word(s.clause_hash,l[i].x);raw(l[i].x);}
}
inline void variable(int number,int polarity,bool decision) {
  State &s=state(); if(!s.detail || s.searching) return;
  ++s.vars; for(int x:{number,polarity,static_cast<int>(decision)})word(s.var_hash,x);
  raw(0xfffffff1U);raw(number);raw(polarity);raw(decision);
}
inline void first_search() {
  State &s=state(); if(!s.detail) return;
  s.searching=true;
  std::ofstream f(s.out+"/s8-sat.tsv");
  f<<s.vars<<"\t"<<s.clauses<<"\t"<<s.var_hash<<"\t"<<s.clause_hash<<"\n";
}
inline void decision(int level,int literal) {
  State &s=state(); if(!s.detail || s.first_decisions>=32)return;
  ++s.first_decisions;std::ofstream(s.out+"/s8-trace.tsv",std::ios::app)<<"decision\t"<<level<<"\t"<<literal<<"\n";
}
template<class Clause> inline void conflict(int level,const Clause &c) {
  State &s=state(); if(!s.detail || s.first_conflicts>=16)return;
  ++s.first_conflicts;std::ofstream f(s.out+"/s8-trace.tsv",std::ios::app);f<<"conflict\t"<<level;
  for(int i=0;i<c.size();++i)f<<"\t"<<c[i].x;
  f<<"\n";
}
}
