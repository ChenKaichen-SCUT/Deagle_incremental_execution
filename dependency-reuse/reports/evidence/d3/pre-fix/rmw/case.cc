#include "minisat/core/ClosureSolver.h"
#include <iostream>
using namespace Minisat;
int main(int argc, char **argv)
{
    if(argc!=2) return 2;
    char scope='B';
    ProofStore graph(argv[1],&scope);
    graph.d3=true;
    {
        ClosureSolver s;
        s.proof=&graph;
        s.newVar(l_Undef,false);
        Lit p=mkLit(s.newVar());
        oc_edge_tablet edges={{{"x#1","x#2"},{lit_Undef,"po"}},{{"x#1","x#2"},{p,"rf"}}};
        oc_guard_mapt guards={{"x#1",Lit{-1}},{"x#2",Lit{-1}}};
        oc_location_mapt locations;
        std::map<std::string,int> order;
        s.save_raw_graph(edges,guards,locations,order);
        const auto &target=s.declaration_graph().nodes.at(1);
        std::cout<<"target read="<<target.is_read<<" write="<<target.is_write<<"\n";
        vec<Lit> as;as.push(p);
        if(s.solve(as)) return 1;
        graph.buildReverse();
        std::vector<uint8_t> matched;
        for(const auto &r:graph.theory_records)
        {
            if(graph.nodes[r.id].kind==TheoryDeclaration) matched.push_back(1);
            if(r.op==FRRule || r.op==CycleRule)
                std::cout<<"rule "<<int(r.op)<<" "<<r.a<<" "<<r.b<<" "<<r.c<<" ID "<<r.id<<"\n";
        }
        auto dead=graph.invalidatedInputs({},matched);
        for(const auto &l:graph.learned)
            std::cout<<"birth "<<l.id<<" flags="<<graph.nodes[l.id].flags
                     <<" alive="<<!dead[l.id]<<" literal="<<graph.lits[graph.litBegin(l.id)]<<"\n";
    }
    return graph.write(0)?0:1;
}