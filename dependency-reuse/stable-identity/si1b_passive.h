// Private audit overlays use this writer. The release binary never links it.
#pragma once
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
namespace si_tap {
inline FILE *log() {static FILE *f=std::fopen("tap.tsv","wb"); if(!f)std::abort(); return f;}
inline char &scope(){static char s='U';return s;}
struct Scope {char saved;explicit Scope(char next):saved(scope()){scope()=next;} ~Scope(){scope()=saved;}};
inline void graph(const char *tag,const std::vector<std::string> &xs) {
  std::fputs(tag,log());for(const auto &x:xs)std::fprintf(log(),"\t%s",x.c_str());std::fputc('\n',log());}
inline void gate(const char *op,int output,const std::vector<int> &xs) {
  std::fprintf(log(),"G\t%s\t%d",op,output);for(int x:xs)std::fprintf(log(),"\t%d",x);std::fputc('\n',log());}
inline void cache(char domain,const void *entry,bool miss,const std::string &op,unsigned n) {
  std::fprintf(log(),"K\t%c\t%p\t%d\t%s\t%u\n",domain,entry,miss,op.c_str(),n);}
}
