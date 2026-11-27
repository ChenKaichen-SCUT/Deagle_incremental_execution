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
struct BranchSources : Sources {
    std::string theory(int op,int a,int b) const override {
        return "[\"T\",\"test\","+std::to_string(op)+","+std::to_string(a)+","+std::to_string(b)+"]";
    }
};
struct BranchSolver : ClosureSolver {
    void choose(Lit literal) {
        newDecisionLevel();uncheckedEnqueue(literal);
        need(propagate()==CRef_Undef,"unexpected branch conflict");
    }
    void undo(){cancelUntil(0);}
};
bool intersects(const DenseBits &a,const DenseBits &b){
    for(size_t i=0;i<a.size();++i)if(a[i]&b[i])return true;
    return false;
}
void branches(const std::string &dir){
    BranchSources source;char scope='B';
    DependencyTags tags(dir+"/dense.bin",&scope,source);
    BranchSolver s;s.dense=&tags;s.newVar(l_Undef,false);
    Lit p=mkLit(s.newVar()),q=mkLit(s.newVar());
    oc_edge_tablet edges={{{"m#1","m#2"},{lit_Undef,"apo"}},{{"m#3","m#4"},{lit_Undef,"apo"}},
                          {{"m#1","m#3"},{p,"rf"}},{{"m#2","m#4"},{q,"rf"}}};
    oc_guard_mapt guards;oc_location_mapt locations;std::map<std::string,int> ordering;
    s.save_raw_graph(edges,guards,locations,ordering);
    const auto &nodes=s.declaration_graph().nodes;
    auto first=tags.declaration(RFDecl,0,2,p.x).tag;
    auto second=tags.declaration(RFDecl,1,3,q.x).tag;
    need(!intersects(first.t,second.t),"distinct RF slots");
    for(Lit binding:{p,q}){
        s.choose(binding);
        need(nodes.at(1).out.size()==1 && nodes[1].out[0].to==3,"missing conditional edge");
        const auto &tag=nodes[1].out[0].proof.tag;
        need(tag.op!=255 && intersects(tag.t,binding==p?first.t:second.t) &&
             !intersects(tag.t,binding==p?second.t:first.t),"RF tag borrowed from another decision branch");
        s.undo();need(nodes[1].out.empty() && nodes[3].in.empty(),"edge outlived branch");
    }
    need(s.solve() && tags.finish(10),"branch fixture");
}
void unknown_descendants(const std::string &dir){
    Sources source;char scope='B';
    ProofStore audit(dir+"/proof.bin",&scope);audit.d3=true;audit.triplets=true;
    DependencyTags tags(dir+"/dense.bin",&scope,source);tags.dual=&audit;
    ClosureSolver s;s.proof=&audit;s.dense=&tags;s.newVar(l_Undef,false);
    Lit z=mkLit(s.newVar()),y=mkLit(s.newVar()),k=mkLit(s.newVar());
    oc_edge_tablet edges;oc_guard_mapt guards={{"m#1",Lit{-1}},{"m#2",Lit{-1}}};
    oc_location_mapt locations;std::map<std::string,int> order;
    s.save_raw_graph(edges,guards,locations,order);
    auto first=s.nVars();s.addMissingCoClauses();need(s.nVars()==first+2,"missing CO definitions");
    s.addClause(~z,~mkLit(first));s.addClause(~z,~mkLit(first+1));
    vec<Lit> assumptions;assumptions.push(z);need(!s.solve(assumptions),"CO ancestor must conflict");
    s.addClause(~y,z,k);s.addClause(~y,z,~k);
    assumptions.clear();assumptions.push(y);need(!s.solve(assumptions),"indirect root unit must conflict");
    need(audit.write(0) && tags.finish(0),"unknown scope fixture");
    std::cout<<"expected opaque units "<<(~z).x<<" "<<(~y).x<<"\n";
}
int main(int argc,char **argv){
    if(argc!=3)return 2;
    const std::string mode=argv[1];
    if(mode=="observe")observation(argv[2]);
    else if(mode=="branches")branches(argv[2]);
    else if(mode=="unknown")unknown_descendants(argv[2]);
    else stress(argv[2],std::stoi(mode));
}
