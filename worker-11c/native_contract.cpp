// Additional native-contract check for an independently replayed OC proof. No program CNF or query assumptions.
#include "input.hpp"
#include <fstream>
using namespace Minisat;
using namespace session10;
int main(int argc,char **argv){
    if(argc!=3)return 2;
    Input model(argv[1]);std::ofstream out(argv[2]);
    int id,n;
    while(std::cin>>id>>n){
        if(n<1 || n>128)return 2;
        ClosureSolver s;
        for(int i=0;i<model.variables;++i)s.newVar();
        std::map<std::string,int> order;
        s.save_raw_graph(model.edges,model.guards,model.locations,order);
        for(int k=0;k<n;++k){int x;if(!(std::cin>>x) || x<0 || x/2>=model.variables)return 2;s.addClause(~literal(x));}
        s.setConfBudget(0);
        vec<Lit> empty;auto rc=s.solveLimited(empty);
        out<<id<<' '<<toInt(rc)<<' '<<s.decisions<<' '<<s.conflicts<<' '<<s.propagations<<"\n";
    }
    return out.good()?0:2;
}
