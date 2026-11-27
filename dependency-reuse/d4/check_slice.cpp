// Offline equality of the projected archive with the independently replayed full native DAG.
#include "minisat/core/ProofStore.h"
#include <iostream>
#include <set>
#include <stdexcept>
using namespace Minisat;
static void check(bool b,const char *m) {if(!b) throw std::runtime_error(m);}
int main(int argc,char **argv)
{
    if(argc!=3)return 2;
    try {
        ProofStore f,c;const int code=f.read(argv[1]);check(c.read(argv[2])==code,"status");
        check(!f.compact && c.compact && f.triplets==c.triplets && f.graph_receipt==c.graph_receipt,"formats or actual graph");
        check(c.origins.size()==c.nodes.size() && c.origins.at(0)==0,"origins directory");
        std::vector<uint8_t> keep(f.nodes.size()),has(f.nodes.size());
        std::vector<ProofId> stack;
        for(const auto &birth:f.learned) if(!(f.nodes.at(birth.id).flags&7)) stack.push_back(birth.id);
        while(!stack.empty()) {
            auto i=stack.back();stack.pop_back();if(keep.at(i))continue;keep[i]=1;
            for(auto j=f.edgeBegin(i);j<f.nodes[i].edge_end;++j) stack.push_back(f.edges[j].parent);
        }
        size_t k=1,full_theory=0,small_theory=0,n=0,retired=0,kept_edges=0;
        for(ProofId i=1;i<f.nodes.size();++i) {
            const auto &node=f.nodes[i];
            bool b=node.kind==BooleanInput || node.kind==QueryInput;
            for(auto j=f.edgeBegin(i);j<node.edge_end;++j)b|=bool(has[f.edges[j].parent]);
            has[i]=b;
            const TheoryRecord *r=nullptr;
            if(node.kind==TheoryDeclaration || node.kind==TheoryInference) r=&f.theory_records.at(full_theory++);
            if(!keep[i] && node.kind!=Learned)continue;
            check(c.origins.at(k)==i,"extra or missing ancestor");
            const auto &s=c.nodes[k];
            check(s.flags==node.flags && s.kind==(keep[i]?node.kind:uint32_t(RetiredBirth)),"node origin or kind");
            auto u=f.litBegin(i),v=c.litBegin(k);
            check(node.lit_end-u==s.lit_end-v,"literal count");
            for(;u<node.lit_end;++u,++v)check(f.lits[u]==c.lits[v],"literal polarity");
            u=f.edgeBegin(i);v=c.edgeBegin(k);
            if(keep[i]) {
                check(node.edge_end-u==s.edge_end-v,"lost rule/side condition");
                for(;u<node.edge_end;++u,++v) {
                    check(c.origins.at(c.edges[v].parent)==f.edges[u].parent && c.edges[v].pivot==f.edges[u].pivot,"direct dependency");
                    ++kept_edges;
                }
                if(r) {
                    const auto &t=c.theory_records.at(small_theory++);
                    check(r->id==i && t.id==k && t.op==r->op && t.a==r->a && t.b==r->b && t.c==r->c,"local rule payload");
                }
            } else {check(s.edge_end==v && (node.flags&7),"uncertified tombstone");++retired;}
            if(node.kind==Learned) {
                const auto &a=f.learned.at(n),&z=c.learned.at(n++);
                check(a.id==i && z.id==k && (keep[i]?(a.uip_edges==z.uip_edges && a.min_edges==z.min_edges):
                       (z.uip_edges==0 && z.min_edges==b)),"birth boundary");
            }
            ++k;
        }
        check(k==c.nodes.size() && n==c.learned.size() && n==f.learned.size() && small_theory==c.theory_records.size(),"section count");
        size_t leaves=0;
        for(size_t i=0;i<f.inputs.size();++i) if(keep[f.inputs[i].leaf]) {
            const auto &x=c.inputs.at(leaves++);check(size_t(x.witness)==i+1 && c.origins.at(x.leaf)==f.inputs[i].leaf,"input ordinal");
        }
        check(leaves==c.inputs.size(),"extra compact input");
        const auto offsets=c.offsets,children=c.children;c.buildReverse();
        check(offsets==c.offsets && children==c.children,"stored reverse index");
        std::cout<<"births\t"<<n<<"\nretired_tombstones\t"<<retired<<"\nfull_nodes\t"<<f.nodes.size()-1
                 <<"\nprojected_nodes\t"<<k-1<<"\nfull_edges\t"<<f.edges.size()<<"\nprojected_edges\t"<<kept_edges
                 <<"\nmatched_input_ordinals\t"<<leaves<<"\nlocal_theory_records\t"<<small_theory<<"\n";
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
