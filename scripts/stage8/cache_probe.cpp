// Standalone cache microbenchmark using the release's actual IREP codec.
#include <util/irep_serialization.h>
#include <ctime>
#include <fstream>
#include <iostream>
#include <iterator>
#include <sstream>
#include <string>

static long long nanos(clockid_t clock) {
  timespec t{};
  clock_gettime(clock,&t);
  return t.tv_sec*1000000000LL+t.tv_nsec;
}
struct Clock {
  long long w=nanos(CLOCK_MONOTONIC), c=nanos(CLOCK_PROCESS_CPUTIME_ID);
  void finish(const char *name) {
    const auto wall=nanos(CLOCK_MONOTONIC), cpu=nanos(CLOCK_PROCESS_CPUTIME_ID);
    std::cout<<name<<'\t'<<wall-w<<'\t'<<cpu-c<<'\n';
  }
};
int main(int argc,char **argv) {
  if(argc!=3) return 1;
  Clock read;
  std::ifstream input(argv[1],std::ios::binary);
  if(!input) return 2;
  const std::string bytes((std::istreambuf_iterator<char>(input)),{});
  read.finish("read_file");
  Clock decode;
  std::istringstream in(bytes);
  irep_serializationt::ireps_containert ids;
  irep_serializationt reader(ids);
  const irept value=reader.reference_convert(in);
  if(in.peek()!=std::char_traits<char>::eof()) return 3;
  decode.finish("decode");
  Clock encode;
  std::ostringstream output;
  irep_serializationt::ireps_containert new_ids;
  irep_serializationt writer(new_ids);
  writer.reference_convert(value,output);
  const auto encoded=output.str();
  encode.finish("encode");
  Clock write;
  std::ofstream file(argv[2],std::ios::binary);
  file.write(encoded.data(),encoded.size());file.close();
  if(!file) return 4;
  write.finish("write_file");
  std::istringstream check(encoded);
  irep_serializationt::ireps_containert last_ids;
  irep_serializationt verify(last_ids);
  if(!value.full_eq(verify.reference_convert(check))) return 5;
  std::cout<<"bytes\t"<<bytes.size()<<'\t'<<encoded.size()<<'\n';
}
