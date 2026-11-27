#include "minisat/core/SupportStore.h"
#include <stdexcept>
#include <iostream>
using namespace Minisat;
void require(bool b){if(!b)throw std::runtime_error("support lifetime invariant");}
int main(){
    FILE *f=std::tmpfile();require(f!=nullptr);
    SupportStore s(f);
    auto config=s.declaration(Config,-1,-1,-1,0);
    auto order=s.declaration(PODecl,1,2,-1,0);
    uint32_t p[]={config,order};
    auto merge=[](uint32_t a,uint32_t b){return a|b;};
    auto active=s.rule(POEdge,p,2,merge);
    uint32_t parents[]={active,config};
    auto survivor=s.rule(Transitive,parents,2,merge);
    uint32_t dropped=s.rule(APOEdge,p,2,merge);
    std::vector<uint32_t> live{survivor};s.collect(live);
    require(s.operation(active)==POEdge && s.operation(survivor)==Transitive);
    bool stale=false;try{s.operation(dropped);}catch(const std::logic_error&){stale=true;}require(stale);
    auto stable=s.adopt(survivor);require(!(stable&SupportFormat::Temp));
    live={survivor};s.collect(live);require(s.adopt(survivor)==stable);
    stale=false;try{s.operation(active);}catch(const std::logic_error&){stale=true;}require(stale);
    auto another=s.rule(POEdge,p,2,merge);require(another!=active && another!=dropped);
    uint64_t boundary[3]={};require(s.finish(10,{},boundary));std::fclose(f);
    std::cout<<"unadopted branch reclaimed; live ancestor survived; durable child survived parent collection; stale handle rejected; IDs not reused\n";
}
