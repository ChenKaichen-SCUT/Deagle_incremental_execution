// Additional observations for the independent C audit. The production build compiles them out.
#ifndef MINISAT_BOUNDARY_AUDIT43_H
#define MINISAT_BOUNDARY_AUDIT43_H
#ifdef DEAGLE_D43C_AUDIT
#include "DependencyTags.h"
#include <map>
#include <memory>

namespace Minisat {
class BoundaryAudit43 {
public:
    enum Source : uint32_t { Other, ImmediateGuard, ImmediateRF, RecheckRF, RecheckGuard,
                             ReverseRF, Race, GraphConflict, Early, Dynamic };
    static BoundaryAudit43 *&active() { static BoundaryAudit43 *p=nullptr; return p; }
    Source site=Other;
private:
    FILE *file;
    uint32_t next_ticket=0, boundaries=0;
    std::map<int,uint32_t> pending;
    void bytes(const void *p,size_t n) {
        if(n && std::fwrite(p,1,n,file)!=n) throw std::runtime_error("C audit write");
    }
    void word(uint32_t x) { bytes(&x,sizeof(x)); }
public:
    explicit BoundaryAudit43(const std::string &path):file(std::fopen(path.c_str(),"wbx")) {
        if(!file || active()) throw std::runtime_error("need a fresh independent boundary audit");
        bytes("D43CBND1",8);active()=this;
    }
    ~BoundaryAudit43(){if(file)std::fclose(file);active()=nullptr;}
    template<class Set> void queued(Lit target,const Set &native,const TheorySupport &s) {
        uint32_t ticket=++next_ticket;
        if(!pending.emplace(target.x,ticket).second)throw std::logic_error("duplicate accepted target");
        word('Q');word(ticket);word(site);word(s.audit);word(target.x);
        word(1+native.size()-native.count(target));word(target.x);
        for(auto lit:native)if(lit!=target)word(lit.x);
        site=Other;
    }
    void duplicate(Lit target) {
        // Native clears its set with its queue. A duplicate cannot replace the first reason.
        word('D');word(pending.at(target.x));word(site);word(target.x);site=Other;
    }
    void clear() {
        if(!pending.empty()){word('X');word(pending.size());pending.clear();}
        site=Other;
    }
    void event(ProofKind kind,Source source,const vec<Lit> &clause,ProofId lemma,
               const TheorySupport &support,const DependencyTags &dense) {
        uint32_t ticket=0;
        if(kind==TheoryReason){
            ticket=pending.at(clause[0].x);pending.erase(clause[0].x);
        }
        const ClauseTag &sat=dense.boundaryTagForAudit();
        word('B');word(++boundaries);word(kind);word(source);word(lemma);word(support.audit);word(ticket);
        word(support.tag.op);word(sat.flags);word(clause.size());
        for(int i=0;i<clause.size();++i)word(clause[i].x);
        DenseBits none{};
        bytes(support.tag.op==255?none.data():support.tag.t.data(),sizeof(none));
        bytes(sat.t.data(),sizeof(sat.t));
    }
    bool finish() {
        clear();word('E');word(next_ticket);word(boundaries);bytes("ENDCBA01",8);
        bool ok=!std::ferror(file);ok=std::fclose(file)==0 && ok;file=nullptr;active()=nullptr;return ok;
    }
};
}
#define D43C_OBSERVE(action) do { if(auto *ob=Minisat::BoundaryAudit43::active()){ ob->action; } } while(0)
#else
#define D43C_OBSERVE(action) do {} while(0)
#endif
#endif
