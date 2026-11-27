// D1 links the original observation-only object; D3 links the native recorder.
#include "minisat/core/ClosureSolver.h"
#include <fstream>
#include <sstream>
#include <stdexcept>
using namespace Minisat;

static Lit literal(int dimacs)
{
    return mkLit(std::abs(dimacs),dimacs<0);
}

int main(int argc,char **argv)
{
    if(argc!=3) return 2;
    std::ifstream input(argv[1]);
    std::string line;
    int n, min_mode=2, stress=0;
    if(!std::getline(input,line)) return 2;
    std::istringstream header(line);
    if(!(header>>n)) return 2;
    if(header>>min_mode && !(header>>stress)) return 2;
    char scope='B';
#ifdef RECORD_PROOFS
    ProofStore store(argv[2],&scope);
    store.d3=true;
#ifdef D42_LIGHT
    store.quality=true;store.enableLight();
#endif
#ifdef D41_TRIPLETS
    store.triplets=true;
#endif
#endif
#ifdef IMPORT_PROOFS
    ClauseImports imported;
#endif
    int result;
    {
        ClosureSolver solver;
#ifdef RECORD_PROOFS
        solver.proof=&store;
#endif
        solver.ccmin_mode=min_mode;
        if(stress)
        {
            solver.garbage_frac=0;
            solver.learntsize_factor=0.01;
            solver.restart_first=8;
        }
        solver.newVar(l_Undef,false);
        for(int i=1;i<=n;++i) solver.newVar();
        vec<Lit> assumptions;
        oc_edge_tablet edges;
        oc_guard_mapt guards;
        oc_location_mapt locations;
        std::map<std::string,int> order;
        while(std::getline(input,line))
        {
            std::istringstream fields(line);std::string tag;
            if(!(fields>>tag)) continue;
            if(tag=="A")
            {
                int v;while(fields>>v)assumptions.push(literal(v));
            }
            else if(tag=="B" || tag=="Q" || tag=="U")
            {
                scope=tag[0];
                int v;vec<Lit> clause;
                while(fields>>v) clause.push(literal(v));
                solver.addClause_(clause);
            }
            else if(tag=="guard")
            {
                int v;std::string event;
                if(!(fields>>event>>v)) return 2;
                guards.emplace(event,v==0 ? Lit{-1} : literal(v)); // Closure constant true
            }
            else
            {
                int v;std::string u,w;
                if(!(fields>>u>>w>>v) || (tag!="po" && tag!="apo" && tag!="rf")) return 2;
                edges.push_back({{u,w},{v==0 ? lit_Undef : literal(v),tag}});
            }
        }
        solver.save_raw_graph(edges,guards,locations,order);
        const auto &g=solver.declaration_graph();
        std::ofstream names("event-names.tsv");
        for(size_t i=0;i<g.nodes.size();++i)
            names<<i<<'\t'<<g.nodes[i].name<<'\t'<<g.nodes[i].address<<'\n';
#ifdef IMPORT_PROOFS
        imported.read(argv[2],solver.nVars());
        solver.importAtRoot(imported,true);
#endif
        result=solver.solve(assumptions)?10:0;
    }
#ifdef RECORD_PROOFS
    if(!store.write(result)) return 3;
#endif
#ifdef IMPORT_PROOFS
    imported.write(".");
#endif
    std::cout<<"fixture result "<<result<<"\n";
    return 0;
}
