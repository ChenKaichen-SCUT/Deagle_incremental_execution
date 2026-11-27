// Native import ABI, root dispositions, database lifetime and malformed-batch tests.
#include "minisat/core/ClosureSolver.h"
#include <iostream>
#include <stdexcept>
using namespace Minisat;

namespace {
void require(bool ok,const char *msg) { if(!ok) throw std::runtime_error(msg); }
struct Fixture : ClosureSolver
{
    std::map<std::string,int> order;
    Fixture(int n)
    {
        newVar(l_Undef,false);
        for(int i=0;i<n;++i) newVar();
    }
    void install()
    {
        oc_edge_tablet e; oc_guard_mapt g; oc_location_mapt l;
        save_raw_graph(e,g,l,order);
    }
    void clause(std::initializer_list<int> xs)
    {
        vec<Lit> vs;
        for(int x:xs) vs.push(mkLit(std::abs(x),x<0));
        addClause_(vs);
    }
    void choose(int dimacs)
    {
        newDecisionLevel();
        uncheckedEnqueue(mkLit(std::abs(dimacs),dimacs<0));
        require(propagate()==CRef_Undef,"unexpected branch conflict");
    }
    void undo() {cancelUntil(0);}
    void shrink() {reduceDB();garbageCollect();}
    bool learnt(CRef ref) {return ca[ref].learnt();}
};
void add(ClauseImports &batch,unsigned id,std::initializer_list<int> xs)
{
    batch.rows.emplace_back(id,'B');
    for(int x:xs) batch.rows.back().translated.push_back(mkLit(std::abs(x),x<0).x);
}
template<class F> void rejected(F f)
{
    try {f();} catch(const std::exception &) {return;}
    throw std::runtime_error("invalid batch or boundary accepted");
}
void root()
{
    ClauseImports b;
    Fixture s(10);
    // Binary resolution on variable 10 entails (2 | 3), and on 9 entails 4.
    s.clause({1});s.clause({2,3,10});s.clause({2,3,-10});
    s.clause({4,9});s.clause({4,-9});s.clause({-4,5});s.clause({6,7});
    s.install();
    add(b,1,{1,8});add(b,2,{2,-2});add(b,3,{6,7});add(b,4,{-1,2,2,3});
    add(b,5,{3,-1,2});add(b,6,{4,-1});add(b,7,{5,8});
    const int originals=s.nClauses();
    s.importAtRoot(b,true);
    const char *expect[]={"root_satisfied","tautology","duplicate_resident","attached","duplicate_batch","root_unit","root_satisfied"};
    for(size_t i=0;i<b.rows.size();++i) require(b.rows[i].disposition==expect[i],"wrong root disposition");
    require(b.rows[3].installed==std::vector<int>({4,6}) && b.rows[3].removed_false==std::vector<int>({3}),"lost shortening witness");
    require(b.rows[5].installed==std::vector<int>({8}) && b.rows[6].root_witness==10,"unit propagation did not use new root");
    require(s.nClauses()==originals && s.learnt(b.rows[3].current_ref),"misclassified as original");
    rejected([&]{s.importAtRoot(b,true);});
    s.choose(-2);
    require(b.rows[3].hits[WatchUnit]==1,"expected imported watcher to imply 3");
    s.undo();
    require(s.solve(),"root fixture changed SAT");
    std::cout<<"root dispositions 7, root unit with implication, watcher propagation, fresh query SAT\n";
}
void collection()
{
    ClauseImports b;
    Fixture s(12);
    // All imported clauses follow from resolving two original clauses on variable 12.
    s.clause({1,2,12});s.clause({1,2,-12});add(b,10,{1,2});
    for(int i=3;i<=8;++i)
    {
        s.clause({1,i,11,12});s.clause({1,i,11,-12});add(b,10+i,{1,i,11});
    }
    s.install();s.importAtRoot(b,true);
    for(const auto &r:b.rows) require(r.disposition=="attached","expected ordinary attached clause");
    s.shrink();
    size_t deleted=0,moved=0;
    for(const auto &r:b.rows){deleted+=r.current_ref==CRef_Undef; moved+=r.moves!=0;}
    require(b.collections && moved && deleted && b.rows[0].current_ref!=CRef_Undef,"no imported relocation/deletion");
    s.choose(-1);
    require(b.rows[0].hits[WatchUnit]==1 && b.witnesses[0].ref==b.rows[0].current_ref,"hit attributed to stale CRef");
    s.undo();require(s.solve(),"GC fixture changed SAT");
    std::cout<<"reduceDB removals "<<deleted<<" relocated rows "<<moved<<" collection count "<<b.collections
             <<" propagated ID 10 at current reference "<<b.rows[0].current_ref<<"\n";
}
void invalid()
{
    ClauseImports wrong;Fixture s(4);
    add(wrong,9,{1,2});add(wrong,10,{5});
    rejected([&]{s.importAtRoot(wrong,true);});s.install();
    rejected([&]{s.importAtRoot(wrong,true);});
    require(!s.import_boundary_used && s.nLearnts()==0 && s.nAssigns()==0,"partially imported invalid batch");
    wrong.rows[1].translated.clear();wrong.rows[1].id=9;rejected([&]{s.importAtRoot(wrong,true);});
    wrong.rows[1].id=10;wrong.rows[1].family='Q';rejected([&]{s.importAtRoot(wrong,true);});
    ClauseImports empty;s.importAtRoot(empty,true);
    require(s.nLearnts()==0 && s.solve(),"empty batch changed result");
    ClauseImports conflict;Fixture unsat(3);
    for(auto a:{1,-1}) for(auto c:{2,-2}) unsat.clause({a,c});
    unsat.clause({3});unsat.install();add(conflict,20,{-3});add(conflict,21,{1,2});
    unsat.importAtRoot(conflict,true);
    require(!unsat.okay() && !unsat.solve() && conflict.rows[0].disposition=="root_conflict" &&
            conflict.rows[1].disposition=="already_inconsistent","root contradiction did not close query");
    std::cout<<"rejected missing graph, unbound literal, repeated ID, query family and repeated import; empty and root UNSAT verified\n";
}
}
int main()
{
    try {root();collection();invalid();}
    catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
