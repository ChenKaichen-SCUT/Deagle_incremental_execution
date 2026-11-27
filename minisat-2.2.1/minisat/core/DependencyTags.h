#ifndef MINISAT_DEPENDENCY_TAGS_H
#define MINISAT_DEPENDENCY_TAGS_H
#include "ProofStore.h"
#include <util/dependency_group_sources.h>
#include <algorithm>
#include <map>
#include <stdexcept>

namespace Minisat {
using DenseBits=std::array<uint64_t,16>;
enum DenseFlag : uint8_t { DenseB=1, DenseT=2, DenseQ=4, DenseUnknown=8 };
struct ClauseTag {
    DenseBits b{},t{};
    uint8_t flags=DenseUnknown;
    static ClauseTag neutral(){ClauseTag x;x.flags=0;return x;}
};

// Fixed-size value copied with native edges, deferred RF/guard triplets and reasons.
// bit contents need not be copied by off/Audit runs, where no dense payload exists.
struct TheoryTag {
    DenseBits t;
    uint32_t raw=0;
    uint8_t op=255;
    bool counted;
    static bool observing;
    static uint64_t live,peak;
    TheoryTag():counted(observing){if(counted){if(++live>peak)peak=live;}}
    TheoryTag(const TheoryTag &rhs):TheoryTag(){*this=rhs;}
    TheoryTag &operator=(const TheoryTag &rhs){
        if(!counted && observing){counted=true;if(++live>peak)peak=live;}
        raw=rhs.raw;op=rhs.op;if(op!=255)t=rhs.t;return *this;
    }
    ~TheoryTag(){if(counted)--live;}
};
struct TheorySupport {
    ProofId audit;
    TheoryTag tag;
    TheorySupport(ProofId id=0):audit(id){}
    explicit operator bool() const {return audit||tag.op!=255;}
};
struct GroupRegistry {
    static constexpr unsigned independent=1023;
    std::unordered_map<std::string,uint32_t> ids;
    std::vector<std::string> keys;
    uint32_t registerKey(const std::string &);
    static unsigned slot(uint32_t group){return std::min(group,uint32_t(independent));}
};

class DependencyTags {
    using Fact=std::array<int,4>;
    struct FactHash {size_t operator()(const Fact &f) const {
        uint64_t h=1;for(int v:f)h=(h^uint32_t(v))*UINT64_C(1099511628211);return size_t(h);
    }};
    std::unordered_map<Fact,uint32_t,FactHash> fact_ids;
    struct FactEntry {Fact key;uint32_t group;};
    std::vector<FactEntry> facts;
    GroupRegistry groups[2];
    std::vector<uint32_t> b_groups;
    std::vector<uint8_t> used[2];
    static constexpr uint32_t raw_bit=UINT32_C(1)<<31;
    static constexpr uint32_t query_group=UINT32_MAX,unknown_group=UINT32_MAX-1;
    const char *scope;
    dependency_manifest::group_owner_interfacet &source;
    std::vector<uint32_t> refs,free_slots;
    std::vector<ClauseTag> pool;
    struct Unit {int literal;ClauseTag support;};
    std::vector<uint32_t> unit_refs;
    std::vector<Unit> units;
    uint32_t pending_leaf=0;
    CRef transient=CRef_Undef;
    void dropTransient(){if(transient!=CRef_Undef){forget(transient);transient=CRef_Undef;}}
    ClauseTag pending,analysis,trial;
    std::vector<int> original;
    bool explicit_unit=false;
    std::string path;
    FILE *out=nullptr,*scoped=nullptr;
    uint64_t excluded_births=0;
    uint64_t ors=0,theory_ors=0,observe_calls[2]{},births=0,raw_live=0,raw_peak=0;
    uint64_t live_slots=0,peak_slots=0,peak_clause_tags=0,gc=0,recycled=0,root_conflicts=0;
    uint64_t trial_ok=0,trial_failed=0,boundaries[3]{},unknown_boundaries=0;
    uint64_t graph_edges=0,peak_graph_edges=0,peak_persistent_theory=0;
    void observe(unsigned,uint32_t);
    void merge(ClauseTag &,const ClauseTag &);
    void consume(uint32_t,ClauseTag &);
    void root(int,ClauseTag &);
    void reason(Solver &,CRef,int,ClauseTag &);
    void release(uint32_t);
    void update_peak();
    void writeBytes(const void *,size_t);
    template<class V> void put(const V &v){writeBytes(&v,sizeof(v));}
public:
    DependencyTags(const std::string &,const char *,dependency_manifest::group_owner_interfacet &);
    ProofStore *dual=nullptr;
    ~DependencyTags();
    TheorySupport declaration(TheoryOp,int,int,int);
    TheorySupport infer(TheoryOp,const TheorySupport *,size_t);
    void node(int id,const std::string &name){source.node(id,name);}
    void persistent(uint64_t other){peak_persistent_theory=std::max(peak_persistent_theory,2*graph_edges+other);}
    void edgeAdded(){++graph_edges;peak_graph_edges=std::max(peak_graph_edges,graph_edges);}
    void edgeRemoved(){if(!graph_edges)throw std::logic_error("Closure edge count");--graph_edges;}
    void boundary(ProofKind,const TheorySupport &);
    void opaque(){pending_leaf=0;pending=ClauseTag{};}
    void input(const vec<Lit> &);
    void acceptInput(Solver &,int size);
    void unit(){explicit_unit=true;}
    void bind(CRef);
    void bindTransient(CRef r){dropTransient();bind(r);transient=r;}
    void forget(CRef);
    void relocated(const ClauseAllocator &,uint32_t);
    void assignment(Solver &,Lit,CRef);
    void rootConflict(Solver &,CRef);
    void beginAnalysis(){analysis=ClauseTag::neutral();}
    void parent(Solver &s,CRef cr,Lit p){reason(s,cr,p==lit_Undef?0:1,analysis);}
    void beginTrial(){trial=ClauseTag::neutral();}
    void visit(Solver &,Var);
    void endTrial(bool);
    void basic(Solver &,Var);
    void learned(const vec<Lit> &);
    bool finish(int);
    uint8_t boundaryFlags() const {return pending.flags;}
};

class TheoryCapture {
public:
    ProofStore *audit=nullptr;
    DependencyTags *dense=nullptr;
    bool triplets=false,eager_triplets=false;
    TheorySupport decl(TheoryOp op,int a=-1,int b=-1,int c=-1);
    TheorySupport rule(TheoryOp op,int a,int b,int c,std::initializer_list<TheorySupport> xs);
    TheorySupport rule(TheoryOp op,int a,int b,int c,const std::vector<TheorySupport> &xs);
private:
    TheorySupport join(TheoryOp,int,int,int,const TheorySupport *,size_t);
};
}
#endif
