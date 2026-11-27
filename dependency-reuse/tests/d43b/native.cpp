// Native P0 lifecycle controls. The synthetic group keys exercise slot allocation independently of the encoder.
#include "minisat/core/ClosureSolver.h"
#include <stdexcept>
#include <iostream>
using namespace Minisat;
struct Sources : dependency_manifest::group_owner_interfacet {
    std::string current="[\"B\",\"test\",0]";
    int theory_key=0;
    const std::string &boolean(const int *,size_t) override{return current;}
    void node(int,const std::string &) override{}
    std::string theory(int,int,int) const override{return "[\"T\",\"test\","+std::to_string(theory_key)+"]";}
    void b(int i){current="[\"B\",\"test\","+std::to_string(i)+"]";}
};
void need(bool b,const char *m){if(!b)throw std::runtime_error(m);}
void graph(ClosureSolver &s){
    oc_edge_tablet edges;oc_guard_mapt guards;oc_location_mapt locations;std::map<std::string,int> order;
    s.save_raw_graph(edges,guards,locations,order);
}
void observation(const std::string &dir){
    Sources source;char scope='B';DependencyTags tags(dir+"/dense.bin",&scope,source);
    ClosureSolver s;s.dense=&tags;s.newVar(l_Undef,false);
    auto a=mkLit(s.newVar()),b=mkLit(s.newVar()),c=mkLit(s.newVar()),d=mkLit(s.newVar());
    s.addClause(~a,b);s.addClause(a);s.addClause(c,d);
    // Already-satisfied input remains registered. The first two distinct raw
    // inputs were both consumed in deriving root b despite sharing a bit.
    for(int i=1;i<=1025;++i){source.b(i);s.addClause(a);}
    TheorySupport config=tags.declaration(Config,-1,-1,-1);
    TheorySupport order=tags.declaration(PODecl,0,1,-1);
    tags.declaration(APODecl,0,1,-1); // separate registration, same group, never read
    TheorySupport parents[]={config,order};auto proof=tags.infer(POEdge,parents,2);
    need(proof.tag.op==POEdge,"known order");
    for(int i=1;i<=1025;++i){
        source.theory_key=i;auto x=tags.declaration(SchemaDecl,i,-1,-1);
        if(i==1024)tags.infer(Lift,&x,1);
    }
    auto unsupported=tags.infer(static_cast<TheoryOp>(200),parents,2);
    need(unsupported.tag.op==255,"unknown future rule certified");
    need(tags.finish(10),"write observed snapshot");
}
void stress(const std::string &dir,int mode){
    Sources source;char scope='B';
    ProofStore audit(dir+"/proof.bin",&scope);audit.d3=true;audit.triplets=true;
    DependencyTags tags(dir+"/dense.bin",&scope,source);tags.dual=&audit;
    int status;
    {
        ClosureSolver s;s.proof=&audit;s.dense=&tags;
        s.ccmin_mode=mode;s.garbage_frac=0;s.learntsize_factor=.01;s.restart_first=8;
        s.newVar(l_Undef,false);for(int i=0;i<20;++i)s.newVar();graph(s);
        int id=0;
        for(int p=0;p<5;++p){
            vec<Lit> clause;for(int h=0;h<4;++h)clause.push(mkLit(1+4*p+h));
            source.b(++id);s.addClause_(clause);
        }
        for(int h=0;h<4;++h)for(int p=0;p<5;++p)for(int q=p+1;q<5;++q){
            source.b(++id);s.addClause(~mkLit(1+4*p+h),~mkLit(1+4*q+h));
        }
        status=s.solve()?10:0;
    }
    need(status==0 && audit.stats[Collections] && audit.stats[Reductions] && !audit.evicted.empty(),"GC/reduction fixture");
    need(audit.write(status) && tags.finish(status),"write stress fixture");
    std::cout<<"min_mode "<<mode<<" native_births "<<audit.learned.size()<<" GC "<<audit.stats[Collections]
             <<" reductions "<<audit.stats[Reductions]<<" evictions "<<audit.evicted.size()<<"\n";
}
int main(int argc,char **argv){
    if(argc!=3)return 2;
    if(std::string(argv[1])=="observe")observation(argv[2]);else stress(argv[2],std::stoi(argv[1]));
}
