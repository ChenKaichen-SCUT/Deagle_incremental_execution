// Build once against the unmodified D1 observation object and once against D2.
#include "minisat/core/ClosureSolver.h"
#include <fstream>
#include <sstream>
#include <stdexcept>

using namespace Minisat;
int main(int argc,char **argv)
{
    if(argc!=3) return 2;
    std::ifstream f(argv[1]);
    std::string line;
    int n,min_mode,stress;
    if(!std::getline(f,line) || !(std::istringstream(line)>>n>>min_mode>>stress)) return 2;
    char scope='B';
#ifdef RECORD_PROOFS
    ProofStore store(argv[2],&scope);
#endif
    int result;
    {
        ClosureSolver s;
#ifdef RECORD_PROOFS
        s.proof=&store;
#endif
        s.ccmin_mode=min_mode;
        if(stress)
        {
            s.garbage_frac=0;
            s.learntsize_factor=0.01;
            s.restart_first=8;
        }
        oc_edge_tablet edges; oc_guard_mapt guards; oc_location_mapt locations;
        std::map<std::string,int> order;
        s.save_raw_graph(edges,guards,locations,order);
        s.newVar(l_Undef,false);
        for(int i=1;i<=n;++i)s.newVar();
        vec<Lit> assumptions;
        while(std::getline(f,line))
        {
            std::istringstream fields(line);
            char tag; int x; vec<Lit> c;
            if(!(fields>>tag)) continue;
            while(fields>>x) c.push(mkLit(std::abs(x),x<0));
            if(tag=='A') c.copyTo(assumptions);
            else if(tag=='T')
            {
                literal_set reason;
                for(int i=1;i<c.size();++i)reason.insert(c[i]);
                s.assign_literal(c[0],reason);
                s.apply_literal_assignment();
            }
            else
            {
                scope=tag;
                s.addClause_(c);
            }
        }
        result=s.solve(assumptions) ? 10 : 0; // Deagle convention: SAT reports a violation
    }
#ifdef RECORD_PROOFS
    if(!store.write(result))return 3;
#endif
    std::cout<<"CNF status "<<result<<"\n";
    return 0;
}
