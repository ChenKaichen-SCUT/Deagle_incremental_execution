// Audit instrumentation for the public D3 invalidation path.
#include "minisat/core/ProofStore.h"
#include <array>
#include <chrono>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
using namespace Minisat;
using Clock=std::chrono::steady_clock;
static void check(bool ok,const char *msg){if(!ok)throw std::runtime_error(msg);}
int main(int argc,char **argv)
{
    if(argc!=4)return 2;
    try {
        const auto start=Clock::now();
        ProofStore g;
        int rc=g.read(argv[1]);check(g.d3 && (rc==0 || rc==10),"incomplete P0");
        const auto loaded=Clock::now();
        std::ifstream in(argv[2]),facts(argv[3]);std::string line,graph;
        std::vector<uint8_t> matched, declarations;
        for(const auto &r:g.inputs)
        {
            check(bool(std::getline(in,line)),"missing Boolean input");
            std::istringstream s(line);
            char scope;unsigned why;check(bool(s>>scope>>why),"invalid Boolean row");
            const auto kind=g.nodes.at(r.leaf).kind;
            check((kind==BooleanInput && scope=='B') || (kind==QueryInput && scope=='Q') ||
                  (kind==UnknownInput && scope=='U'),"input scope mismatch");
            for(auto j=g.litBegin(r.leaf);j<g.nodes[r.leaf].lit_end;++j)
            {int lit;check(bool(s>>lit) && lit==g.lits[j],"Boolean input mismatch");}
            s>>std::ws;check(s.eof(),"extra input literal");
            matched.push_back(why==0);
        }
        check(!std::getline(in,line)&&in.eof(),"unexpected input tail");
        std::map<std::array<int,4>,char> entries;
        while(std::getline(facts,line))
        {
            if(line.compare(0,2,"G\t")==0){graph+=line.substr(2);graph+='\n';}
            else if(line.compare(0,2,"D ")==0)
            {
                std::istringstream s(line.substr(2));std::array<int,4> k;char status;
                check(bool(s>>k[0]>>k[1]>>k[2]>>k[3]>>status) && (status=='M'||status=='C'||status=='U')
                      && entries.emplace(k,status).second,"bad declaration");
            }
        }
        check(facts.eof() && !graph.empty() && graph.size()==g.graph_receipt.size() &&
              std::equal(graph.begin(),graph.end(),g.graph_receipt.begin()),"different native graph");
        for(const auto &r:g.theory_records)
            if(g.nodes.at(r.id).kind==TheoryDeclaration)
                declarations.push_back(entries.at({int(r.op),r.a,r.b,r.c})=='M');
        const auto bound=Clock::now();
        auto dead=g.invalidatedInputs(matched,declarations);
        const auto marked=Clock::now();
        for(const auto &r:g.learned)std::cout<<r.id<<'\t'<<(!dead.at(r.id))<<'\n';
        auto ns=[](Clock::duration d){return std::chrono::duration_cast<std::chrono::nanoseconds>(d).count();};
        std::cerr<<"archive_read_ns "<<ns(loaded-start)<<"\ninput_bind_ns "<<ns(bound-loaded)
                 <<"\njoint_reverse_ns "<<ns(marked-bound)<<"\n";
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
