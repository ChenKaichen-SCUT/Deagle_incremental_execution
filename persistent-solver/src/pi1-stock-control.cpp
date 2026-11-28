// Compiled against the pristine PI-0 stock headers and object files.
#include "pi1-wire.h"
#include "minisat/core/ClosureSolver.h"

int main(int argc,char **argv) {
    try {
        require(argc==2,"usage: stock-control transaction");auto m=readTransaction(argv[1]);
        Minisat::ClosureSolver solver;
        using Minisat::lbool;
        for(unsigned i=0;i<m.native_variable_count;++i)solver.newVar();
        auto raw=[](LocalLit l){Minisat::Lit p={l.kind==LiteralKind::variable?int(2*l.variable.id+l.negated):
            l.kind==LiteralKind::constant_true?-1:-2};return p;};
        for(const auto *inputs:{&m.inputs,&m.first_query.scoped_inputs})for(const auto &c:*inputs) {
            Minisat::vec<Minisat::Lit> lits;bool taut=false;
            for(auto l:c.literals){auto p=raw(l);taut|=p.x==-1;if(p.x>=0)lits.push(p);}
            if(!taut)solver.addClause_(lits);
        }
        oc_edge_tablet edges;oc_guard_mapt guards;oc_location_mapt loc;std::map<std::string,int> output;
        for(auto &e:m.graph.events)loc[e.key]=e.location;
        for(auto &e:m.graph.edges) {
            const char *k[]={"po","apo","rf","race"};edges.push_back({{m.graph.events.at(e.from.local).key,m.graph.events.at(e.to.local).key},
                                                                      {raw(e.condition),k[int(e.relation)]}});
        }
        for(auto &g:m.graph.guards)guards[m.graph.events.at(g.first.local).key]=raw(g.second);
        solver.save_raw_graph(edges,guards,loc,output);
        Minisat::vec<Minisat::Lit> assumptions;
        for(auto l:m.first_query.native_assumptions){auto p=raw(l);
            if(p.x==-2){std::cout<<"STOCK UNSAT\n";return 0;}if(p.x>=0)assumptions.push(p);}
        auto status=solver.solveLimited(assumptions);
        std::cout<<"STOCK "<<(status==l_True?"SAT":status==l_False?"UNSAT":"UNKNOWN")<<'\n';
    }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}
