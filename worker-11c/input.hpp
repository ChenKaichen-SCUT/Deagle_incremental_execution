#pragma once
#include "minisat/core/ClosureSolver.h"
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace session10 {
using namespace Minisat;
using Key=std::vector<int>;
inline Lit literal(int raw){Lit p;p.x=raw;return p;}
inline void require(bool valid,const std::string &reason){if(!valid)throw std::runtime_error(reason);}
inline uint32_t word(std::istream &in){uint32_t x;if(!in.read(reinterpret_cast<char*>(&x),4))throw std::runtime_error("incomplete solver stream");return x;}
template<class C> Key key(const C &c){
  Key k;for(int i=0;i<int(c.size());++i)k.push_back(c[i].x);
  std::sort(k.begin(),k.end());return k;
}
struct Op {uint32_t tag;Key payload;};
enum : uint32_t { ClauseOp=0xfffffff0U,VarOp=0xfffffff1U,GraphOp=0xfffffff2U,GoalOp=0xfffffff3U,PolOp=0xfffffff4U };
struct Input {
  std::vector<Op> ops;
  oc_edge_tablet edges;oc_guard_mapt guards;oc_location_mapt locations;
  std::map<std::string,int> order;
  int variables=0,clauses=0;
  std::set<Key> submitted;
  explicit Input(const std::string &dir){
    std::ifstream graph(dir+"/s8-graph.tsv");
    require(graph.good(),"missing theory graph");
    for(std::string row;std::getline(graph,row);){
      std::stringstream st(row);std::vector<std::string> z;
      for(std::string f;std::getline(st,f,'\t');)z.push_back(f);
      if(z.size()==5 && z[0]=="edge")edges.push_back({{z[1],z[2]},{literal(std::stoi(z[4])),z[3]}});
      else if(z.size()==4 && z[0]=="guard"){guards[z[1]]=literal(std::stoi(z[2]));locations[z[1]]=std::stoi(z[3]);}
      else if(z.size()==3 && z[0]=="order")order[z[1]]=std::stoi(z[2]);
      else throw std::runtime_error("unknown graph record");
    }
    std::ifstream f(dir+"/s8-input.bin",std::ios::binary);require(f.good(),"missing native input");
    int graphs=0,goals=0;
    while(f.peek()!=std::char_traits<char>::eof()){
      require(!goals,"record after assumptions");
      Op op{word(f),{}};
      switch(op.tag){
      case VarOp: {
        int id=word(f),pol=word(f),decision=word(f);
        require(id==variables++ && pol>=0 && pol<=2 && (decision==0 || decision==1),"variable registration");
        op.payload={id,pol,decision};break;
      }
      case GraphOp:++graphs;break;
      case PolOp: {int v=word(f),pol=word(f);require(v>=0 && v<variables && pol>=0 && pol<=2,"invalid polarity");op.payload={v,pol};break;}
      case ClauseOp:case GoalOp:{
        uint32_t size=word(f);require(size<10000000,"unreasonable clause length");
        for(unsigned i=0;i<size;++i){int x=word(f);require(x>=0 && x/2<variables,"unallocated literal");op.payload.push_back(x);}
        if(op.tag==GoalOp)++goals;
        else{++clauses;}
        break;
      }
      default:throw std::runtime_error("unknown native stream event");
      }
      ops.push_back(std::move(op));
    }
    require(graphs==1 && goals==1,"expected one complete graph and solve");
  }
};
inline void write_answer(const std::string &dir,ClosureSolver &s,const Input &in,int rc){
  require(rc==0 || rc==1,"native result indefinite");
  std::ofstream out(dir+"/answer.txt");
  out<<rc<<" "<<in.variables<<"\n";
  if(rc==0){
    require(s.model.size()>=in.variables,"missing model bits");
    for(int i=0;i<in.variables;++i)out<<toInt(s.model[i])<<" ";
    out<<"\n"<<s.oc_result_order->size()<<"\n";
    for(const auto &n:*s.oc_result_order)out<<n.first<<" "<<n.second<<"\n";
    auto order=s.get_write_order();out<<order.size()<<"\n";for(const auto &n:order)out<<n<<"\n";
    for(const auto &op:in.ops){
      if(op.tag==ClauseOp){
        bool hit=false;for(int x:op.payload)if(s.modelValue(literal(x))==l_True){hit=true;break;}
        require(hit,"candidate model fails a submitted original clause");
      } else if(op.tag==GoalOp)for(int x:op.payload)require(s.modelValue(literal(x))==l_True,"candidate model fails assumption");
    }
  }
  require(out.good(),"native answer write");
}
}
