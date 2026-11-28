// Link only in the independent PI-1G observer. Read resident clauses before P1 searches.
#ifdef DEAGLE_PI1G_OBSERVER
#include "ClosureSolver.h"
#include <cstring>
#include <fstream>
namespace Minisat {
void NativeLedger::measureBirth(CRef ref,ClauseFamily family,Var unit) {
    unsigned length=1,selectors=0;
    if(unit!=var_Undef)selectors=(*auditRoles)[unit]==Selector;
    else {
        const Clause& c=(*auditAllocator)[ref];length=c.size();
        for(int i=0;i<c.size();++i)selectors+=(*auditRoles)[var(c[i])]==Selector;
    }
    ++birthLengths[{{unsigned(family),length,selectors}}];
}
void ClosureSolver::observeGroupLearning(const char *phase) {
    if(!piLedger)return;
    std::ofstream out(restartStudy.inventoryPath+".learn",std::ios::app);
    out.exceptions(std::ios::badbit|std::ios::failbit);
    out<<"PHASE "<<epochVersion<<' '<<phase<<'\n';
    if(std::strcmp(phase,"entry")==0) {
        for(const auto &r:piLedger->resident) {
            const auto &b=piLedger->births[r.second];if(b.version>=epochVersion || b.dormant)continue;
            const Clause &c=ca[r.first];out<<"OLD "<<b.id<<' '<<unsigned(b.family)<<' '<<r.first;
            for(int i=0;i<c.size();++i)out<<' '<<c[i].x;
            out<<'\n';
        }
        for(const auto &r:piLedger->root_units) {
            const auto &b=piLedger->births[r.second];if(b.version>=epochVersion || b.dormant)continue;
            out<<"OLD "<<b.id<<' '<<unsigned(b.family)<<' '<<CRef_Undef<<' '<<mkLit(r.first,value(r.first)==l_False).x<<'\n';
        }
    } else {
        for(const auto &r:piLedger->birthLengths)out<<"BIN "<<r.first[0]<<' '<<r.first[1]<<' '<<r.first[2]<<' '<<r.second<<'\n';
        for(const auto &b:piLedger->births)if(b.version<epochVersion&&!b.dormant){
            bool used=false;for(auto x:b.hits)used|=x!=0;
            if(used){out<<"USE "<<b.id;for(auto x:b.hits)out<<' '<<x;out<<'\n';}
        }
    }
}
}
#endif
