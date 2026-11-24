#pragma once
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <stdexcept>
#include <string>
#include <unistd.h>
#include <sys/resource.h>

namespace s10 {
inline uint64_t now() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
    std::chrono::steady_clock::now().time_since_epoch()).count();
}
inline std::string &where() { static std::string value; return value; }
inline std::string directory() {
  if(!where().empty()) return where();
  const char *p=std::getenv("S10_DIR"); return p?p:"";
}
inline void mark(const char *name) {
  auto dir=directory(); if(!dir.empty()) std::ofstream(dir+"/boundary.tsv",std::ios::app)<<name<<"\t"<<now()<<"\n";
}
inline FILE *&trace() { static FILE *value=nullptr; return value; }
inline void start_trace() {
  if(trace()) throw std::runtime_error("nested search trace");
  auto dir=directory(); if(!dir.empty()) {
    trace()=std::fopen((dir+"/search.bin").c_str(),"wb");
    if(!trace()) throw std::runtime_error("search trace open");
  }
}
inline void word(int32_t v) { if(trace() && std::fwrite(&v,4,1,trace())!=1) throw std::runtime_error("search trace write"); }
inline void choice(int level,int lit) {if(trace()){word(1);word(level);word(lit);}}
template<class C> inline void collision(int level,const C &c) {
  if(trace()){word(2);word(level);word(c.size());for(int i=0;i<c.size();++i)word(c[i].x);}
}
inline void close_trace(){if(trace()){if(std::fclose(trace()))throw std::runtime_error("search trace close");trace()=nullptr;}}
inline long rss_kib(){struct rusage u{};getrusage(RUSAGE_SELF,&u);return u.ru_maxrss;}
}
