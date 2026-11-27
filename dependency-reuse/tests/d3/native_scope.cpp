#include "minisat/core/ClosureSolver.h"
#include <algorithm>
#include <fstream>
#include <stdexcept>

using namespace Minisat;
namespace
{
void require(bool test,const char *message)
{
    if(!test) throw std::runtime_error(message);
}

// Exercise the same decision, propagation and backtrack operations used in
// search, with prescribed choices so both branch orientations are covered.
struct ObservedSolver : ClosureSolver
{
    void branch(Lit p)
    {
        newDecisionLevel();
        proof->tag(0,Decision);
        uncheckedEnqueue(p);
        require(propagate()==CRef_Undef,"unexpected branch conflict");
    }
    void undo() { cancelUntil(0); }
};

std::vector<uint8_t> ancestry(const ProofStore &g,ProofId id)
{
    std::vector<uint8_t> used(g.nodes.size());
    used.at(id)=1;
    for(size_t i=id+1;i-->1;)
        if(used[i])
            for(auto j=g.edgeBegin(i);j<g.nodes[i].edge_end;++j) used.at(g.edges[j].parent)=1;
    return used;
}

void scope_fixture(const std::string &path)
{
    char scope='B';
    ProofStore g(path,&scope);
    g.d3=true;
    {
        ObservedSolver s;
        s.proof=&g;
        s.newVar(l_Undef,false);
        const Lit p=mkLit(s.newVar()),q=mkLit(s.newVar());
        oc_edge_tablet edges={{{"m#1","m#2"},{lit_Undef,"apo"}},{{"m#3","m#4"},{lit_Undef,"apo"}},
                              {{"m#1","m#3"},{p,"rf"}},{{"m#2","m#4"},{q,"rf"}}};
        oc_guard_mapt guards;
        oc_location_mapt locations;
        std::map<std::string,int> order;
        s.save_raw_graph(edges,guards,locations,order);
        const auto &nodes=s.declaration_graph().nodes;
        require(nodes.size()==4 && nodes[1].out.empty(),"unexpected initial graph");
        for(auto binding:{p,q})
        {
            s.branch(binding);
            require(nodes[1].out.size()==1 && nodes[1].out[0].to==3,"expected active block edge");
            auto id=nodes[1].out[0].proof.audit;
            require(id!=0,"branch edge has no proof");
            auto used=ancestry(g,id);
            unsigned bound=0;
            for(const auto &r:g.theory_records)
                if(used[r.id] && r.op==RFDecl)
                {
                    require(r.c==binding.x,"borrowed RF binding from another branch");
                    ++bound;
                }
            require(bound==1,"expected exactly one conditional RF binding");
            std::cout<<"scope edge "<<id<<" raw binding "<<binding.x<<"\n";
            s.undo();
            require(nodes[1].out.empty() && nodes[3].in.empty(),"branch edge survived rollback");
        }
        require(s.solve(),"scope fixture should admit a native model");
    }
    require(g.write(10),"write scope proof");
}

// The lower-level graph API can tag the RF target as a competing write as
// well. Native FR then produces a self-cycle. Certification is restricted to
// three distinct events, even when all static leaves match the new graph.
void aliased_competitor(const std::string &path)
{
    char scope='B';
    ProofStore g(path,&scope);
    g.d3=true;
    {
        ClosureSolver s;
        s.proof=&g;
        s.newVar(l_Undef,false);
        const Lit p=mkLit(s.newVar()), y=mkLit(s.newVar()), k=mkLit(s.newVar());
        oc_edge_tablet edges={{{"x#1","x#2"},{lit_Undef,"po"}},{{"x#1","x#2"},{p,"rf"}}};
        oc_guard_mapt guards={{"x#1",Lit{-1}},{"x#2",Lit{-1}}};
        oc_location_mapt locations;
        std::map<std::string,int> order;
        s.save_raw_graph(edges,guards,locations,order);
        const auto &target=s.declaration_graph().nodes.at(1);
        require(target.is_read && target.is_write,"expected a dual-role RF target");
        vec<Lit> assumptions;
        assumptions.push(p);
        require(!s.solve(assumptions),"native alias cycle was not detected");
        s.addClause(~y,p,k);
        s.addClause(~y,p,~k);
        assumptions.clear(); assumptions.push(y);
        require(!s.solve(assumptions),"missing indirect conflict");
        g.buildReverse();
        std::vector<uint8_t> declarations;
        for(const auto &r:g.theory_records)
        {
            if(g.nodes[r.id].kind==TheoryDeclaration) declarations.push_back(1);
            if(r.op==FRRule || r.op==WSRule)
                require(r.a!=r.b && r.a!=r.c && r.b!=r.c,"certified a repeated event");
        }
        auto dead=g.invalidatedInputs(std::vector<uint8_t>(g.inputs.size(),1),declarations);
        ProofId prior=0,child=0;
        for(const auto &birth:g.learned)
        {
            auto pos=g.litBegin(birth.id);
            if(g.nodes[birth.id].lit_end!=pos+1) continue;
            if(g.lits[pos]==(~p).x) prior=birth.id;
            if(g.lits[pos]==(~y).x) child=birth.id;
        }
        require(prior && child && ancestry(g,child).at(prior),"missing native indirect learning");
        auto support=ancestry(g,prior);
        bool opaque=false;
        for(size_t i=1;i<support.size();++i) opaque|=support[i] && g.nodes[i].kind==TheoryConflict;
        require(opaque && (g.nodes[prior].flags&Theory) && (g.nodes[child].flags&Theory) &&
                dead[prior] && dead[child],"aliased FR conflict or its descendant escaped invalidation");
        std::cout<<"dual-role target: native opaque conflict, retired CDCL IDs "<<prior<<" and "<<child<<'\n';
    }
    require(g.write(0),"write aliased-competitor proof");
}

void dynamic_fixture(const std::string &path)
{
    char scope='B';
    ProofStore g(path,&scope);
    g.d3=true;
    {
        ObservedSolver s;
        s.proof=&g;
        s.newVar(l_Undef,false);
        const Lit z=mkLit(s.newVar()), y=mkLit(s.newVar()), k=mkLit(s.newVar());
        oc_edge_tablet edges;
        oc_guard_mapt guards={{"m#1",Lit{-1}},{"m#2",Lit{-1}}}; // native Closure true
        oc_location_mapt locations;
        std::map<std::string,int> order;
        s.save_raw_graph(edges,guards,locations,order);
        const int first=s.nVars();
        s.addMissingCoClauses();
        require(s.nVars()==first+2,"native CO coverage clause was not generated");
        const Lit a=mkLit(first),b=mkLit(first+1);
        const auto &nodes=s.declaration_graph().nodes;
        for(auto orientation:{a,b})
        {
            s.branch(orientation==a ? ~b : ~a);
            int from=orientation==a ? 0 : 1;
            require(nodes[from].out.size()==1 && nodes[from].out.front().proof.audit==0,
                    "dynamic CO edge was certified");
            s.undo();
            require(nodes[0].out.empty() && nodes[1].out.empty(),"dynamic edge survived rollback");
        }
        s.addClause(~z,~a);
        s.addClause(~z,~b);
        vec<Lit> assum;
        assum.push(z);
        require(!s.solve(assum),"CO exclusion must rule out z");
        s.addClause(~y,z,k);
        s.addClause(~y,z,~k);
        assum.clear(); assum.push(y);
        require(!s.solve(assum),"prior learned unit must rule out y");
        ProofId prior=0, child=0;
        for(const auto &learn:g.learned)
        {
            auto pos=g.litBegin(learn.id);
            if(g.nodes[learn.id].lit_end!=pos+1) continue;
            if(g.lits[pos]==(~z).x) prior=learn.id;
            if(g.lits[pos]==(~y).x) child=learn.id;
        }
        require(prior && child && prior<child,"expected actual learned units ~z and ~y");
        auto used=ancestry(g,child);
        require(used[prior],"second native unit lacks the first learned ancestor");
        bool has_co=false;
        for(size_t i=0;i<used.size();++i) has_co|=used[i] && g.nodes[i].kind==DynamicCO;
        require(has_co,"native CO definition missing from ancestry");
        require((g.nodes[prior].flags&Theory) && (g.nodes[child].flags&Theory),"lost opaque provenance");
        g.buildReverse();
        std::vector<uint8_t> declarations;
        for(const auto &r:g.theory_records)
            if(g.nodes[r.id].kind==TheoryDeclaration) declarations.push_back(1);
        auto dead=g.invalidatedInputs(std::vector<uint8_t>(g.inputs.size(),1),declarations);
        require(dead[prior] && dead[child],"CO descendants survived joint invalidation");
        std::cout<<"dynamic CO learned "<<prior<<" and "<<child<<" retire after both CO variables resolve out\n";
    }
    require(g.write(0),"write dynamic proof");
}
}

int main(int argc,char **argv)
{
    if(argc!=4) return 2;
    try
    {
        scope_fixture(argv[1]); dynamic_fixture(argv[2]); aliased_competitor(argv[3]);
    }
    catch(const std::exception &e) { std::cerr<<e.what()<<'\n'; return 1; }
}