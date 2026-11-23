// Replay a complete, matched solver input stream, graph and assumptions in one fresh Closure instance.
#include "minisat/core/ClosureSolver.h"
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
using namespace Minisat;
static uint32_t word(std::istream &in) {
  uint32_t v=0;
  if(!in.read(reinterpret_cast<char*>(&v),sizeof(v))) throw std::runtime_error("Incomplete input record");
  return v;
}
static Lit literal(int v) { Lit lit;lit.x=v;return lit; }
static std::vector<std::string> split(const std::string &line) {
  std::vector<std::string> v;
  std::istringstream s(line);
  std::string token;
  while(std::getline(s,token,'\t'))v.push_back(token);
  return v;
}
int main(int argc,char **argv) {
  if(argc!=2)return 2;
  const std::string dir=argv[1];
  std::ifstream input(dir+"/s8-input.bin",std::ios::binary), graphfile(dir+"/s8-graph.tsv");
  if(!input || !graphfile)return 2;
  oc_edge_tablet edges;oc_guard_mapt guards;oc_location_mapt locations;
  std::map<std::string,int> result_order;
  for(std::string line;std::getline(graphfile,line);){
    auto s=split(line);
    if(s.at(0)=="edge")edges.push_back({{s.at(1),s.at(2)},{literal(std::stoi(s.at(4))),s.at(3)}});
    else if(s.at(0)=="guard"){guards[s.at(1)]=literal(std::stoi(s.at(2)));locations[s.at(1)]=std::stoi(s.at(3));}
    else if(s.at(0)=="order")result_order[s.at(1)]=std::stoi(s.at(2));
    else throw std::runtime_error("Unexpected graph record");
  }
  ClosureSolver solver;
  vec<Lit> clause,assumptions;
  unsigned graphs=0,goals=0;
  while(input.peek()!=std::char_traits<char>::eof()){
    uint32_t kind=word(input);
    if(kind==0xfffffff1U){
      auto id=word(input),polarity=word(input),decision=word(input);
      if(solver.newVar(lbool(static_cast<uint8_t>(polarity)),decision!=0)!=static_cast<int>(id))return 3;
    }else if(kind==0xfffffff0U){
      uint32_t n=word(input);
      clause.clear();
      for(uint32_t i=0;i<n;++i)clause.push(literal(word(input)));
      solver.addClause_(clause);
    }else if(kind==0xfffffff2U){
      if(++graphs!=1)return 4;
      solver.save_raw_graph(edges,guards,locations,result_order);
    }else if(kind==0xfffffff4U){
      auto id=word(input),polarity=word(input);
      solver.setPolarity(id,lbool(static_cast<uint8_t>(polarity)));
    }else if(kind==0xfffffff3U){
      if(++goals!=1)return 5;
      uint32_t n=word(input);
      for(uint32_t i=0;i<n;++i)assumptions.push(literal(word(input)));
      if(input.peek()!=std::char_traits<char>::eof())return 6;
    }else throw std::runtime_error("Unexpected solver stream marker");
  }
  if(graphs!=1 || goals!=1)return 7;
  auto before=std::chrono::steady_clock::now();
  lbool value=solver.solveLimited(assumptions);
  auto wall=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-before).count();
  std::cout<<"STAGE8_REPLAY\t"<<toInt(value)<<'\t'<<wall<<'\t'<<solver.starts<<'\t'<<solver.conflicts<<'\t'<<solver.decisions<<'\t'<<solver.propagations<<"\n";
}
