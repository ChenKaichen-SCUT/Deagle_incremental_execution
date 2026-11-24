#include "input.hpp"
#include <fstream>
using namespace Minisat;
using namespace session10;
extern std::vector<std::string> write_order;
static void graph(ClosureSolver &s,std::map<std::string,int>& ranks){
    oc_edge_tablet e;oc_guard_mapt g;oc_location_mapt loc;
    g["cell#1"]=lit_Error;g["cell#2"]=lit_Error;loc["cell#1"]=1;loc["cell#2"]=2;
    s.save_raw_graph(e,g,loc,ranks);
}
int main(int argc,char **argv){
    if(argc!=2)return 2;
    std::ofstream log(argv[1]);
    for(int moved=0;moved<=1;++moved)for(int direction=0;direction<3;++direction){
        ClosureSolver s;if(moved)s.newVar();std::map<std::string,int> rank;
        ::write_order.clear();graph(s,rank);int start=s.nVars();s.addMissingCoClauses();
        require(s.nVars()==start+2,"native solver failed to allocate both CO definitions");
        Lit ab=mkLit(start),ba=mkLit(start+1);vec<Lit> a;
        a.push(direction==1?~ab:ab);a.push(direction==0?~ba:ba);
        int rc=toInt(s.solveLimited(a));
        require(rc==(direction==2?1:0),"unexpected native CO result");
        if(rc==0)require((rank.at("cell#1")<rank.at("cell#2"))==(direction==0),"wrong native order");
        log<<moved<<' '<<direction<<' '<<ab.x<<' '<<ba.x<<' '<<rc<<' '<<rank.size()<<"\n";
    }
    for(int i=0;i<5;++i){
        int results[2];static ClosureSolver shared;static Lit sa,sx;
        if(!i){sa=mkLit(shared.newVar());sx=mkLit(shared.newVar());shared.addClause(~sa,sx);shared.addClause(~sa,~sx);}
        ClosureSolver fresh;auto a=mkLit(fresh.newVar()),x=mkLit(fresh.newVar());fresh.addClause(~a,x);fresh.addClause(~a,~x);
        for(int j=0;j<2;++j){vec<Lit> g;g.push(i%2?(j?~a:~sa):(j?a:sa));results[j]=toInt((j?fresh:shared).solveLimited(g));}
        require(results[0]==results[1] && results[0]==(i%2?0:1),"assumption leak");log<<"assume "<<i<<' '<<results[0]<<' '<<results[1]<<"\n";
    }
}
