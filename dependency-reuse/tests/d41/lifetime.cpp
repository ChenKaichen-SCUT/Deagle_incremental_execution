// Native SAT-boundary lifetime and inclusive import-work probes.
#include "minisat/core/ClosureSolver.h"
#include <iostream>
#ifdef D43C_FIXTURE
#include "../d43c/fixture_capture.h"
#endif
#include <stdexcept>
using namespace Minisat;

static void check(bool condition,const char *message)
{
    if(!condition) throw std::runtime_error(message);
}

struct Native : ClosureSolver
{
    std::map<std::string,int> order;
    explicit Native(ProofStore *store=nullptr)
    {
        proof=store;
        newVar(l_Undef,false);
        for(int i=1;i<=8;++i)newVar();
    }
    void install()
    {
        oc_edge_tablet edges={{{"x#1","x#2"},{mkLit(5),"rf"}},{{"x#1","x#5"},{lit_Undef,"po"}},
                              {{"x#5","x#2"},{lit_Undef,"po"}}};
        oc_guard_mapt guards={{"x#1",Lit{-1}},{"x#5",mkLit(7)}};
        oc_location_mapt locations;save_raw_graph(edges,guards,locations,order);
    }
    void branch(int var)
    {
        newDecisionLevel();
        proof->tag(0,Decision);
        uncheckedEnqueue(mkLit(var));
        check(propagate()==CRef_Undef,"unexpected branch conflict");
    }
    void undo(){cancelUntil(0);}
    void clause(int a,int b)
    {
        addClause(mkLit(std::abs(a),a<0),mkLit(std::abs(b),b<0));
    }
};

static void lifetime()
{
    char scope='B';ProofStore store("lifetime.bin",&scope);store.d3=true;store.triplets=true;
    {
        Native s(&store);
#ifdef D43C_FIXTURE
        FixtureOwners43 owners;DependencyTags tags("dense.bin",&scope,owners);tags.dual=&store;
        FixtureTrace43 recorder(".");s.dense=&tags;recorder.attach(s);
#endif
        s.install();
        s.branch(5);
        check(s.value(7)==l_False,"RF recheck did not imply guard");
        bool found=false;
        for(const auto &r:store.theory_records)found|=r.op==TripletRule;
        check(found,"branch did not emit a conditional triplet certificate");
        s.undo();
        check(s.value(5)==l_Undef && s.value(7)==l_Undef,"branch left a root fact");
        s.branch(7);
        check(s.value(5)==l_False,"opposite branch did not exclude RF");
        s.undo();
        check(s.solve(),"backtrack did not preserve a native model");
#ifdef D43C_FIXTURE
        check(tags.finish(10),"lifetime labels");recorder.finish();s.dense=nullptr;
#endif
    }
    check(store.write(10),"write lifetime archive");
    std::cout<<"branch RF excludes guard, undo clears both, guard branch excludes RF, native SAT\n";
}

static void import_work(bool conflict)
{
    Native s;
    // g is entailed by resolving (g or a) and (g or not a). If requested,
    // RF is independently forced by another pair, making the SC problem UNSAT.
    s.clause(7,1);s.clause(7,-1);
    if(conflict){s.clause(5,2);s.clause(5,-2);}
    s.install();
    ClauseImports batch;batch.rows.emplace_back(10,'B');batch.rows.back().translated={mkLit(7).x};
    auto before=s.work();bool was_ok=s.okay();s.importAtRoot(batch,true);auto after=s.work();
    check(batch.rows[0].disposition=="root_unit","expected entailed imported root unit");
    check(after[2]>before[2] && after[3]>before[3],"missing native import BCP or theory work");
    check(s.okay()!=conflict && s.solve()!=conflict,"wrong P1 verdict");
    const uint64_t recorded=uint64_t(was_ok && !s.okay());
    check(recorded==conflict,"lost import-time contradiction");
    std::cout<<"root_import\t"<<conflict<<"\tBCP\t"<<after[2]-before[2]<<"\ttheory\t"<<after[3]-before[3]
             <<"\troot_conflicts\t"<<recorded<<"\tnative_conflict_delta\t"<<after[0]-before[0]<<'\n';
}

int main()
{
    try{lifetime();import_work(false);import_work(true);}
    catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
