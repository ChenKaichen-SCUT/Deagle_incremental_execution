// Exact structural equality of support expressions implies equality of all base
// supports at every birth. Interning compares full keys even on hash collision.
#include "transport_graph.h"
#include <iostream>
#include <unordered_map>
using namespace d42;
struct ExpressionHash {size_t operator()(const std::vector<Id>&v)const{size_t h=1;for(Id k:v)h=(h^k)*UINT64_C(1099511628211);return h;}};
struct Expressions {
    std::unordered_map<std::vector<Id>,Id,ExpressionHash> keys;
    std::vector<Id> run(const Graph &g){
        std::vector<Id> index(g.nodes.size());std::vector<Id> key;
        auto reach=g.reach();
        for(Id i=0;i<g.nodes.size();++i){
            if(i && !reach[i])continue;
            const auto &n=g.nodes[i];key.clear();
            if(n.type==InputLeaf)key={InputLeaf,n.payload,n.flags};
            else if(n.type==FactLeaf){key={FactLeaf};for(int w:g.facts[n.payload])key.push_back(w);}
            else if(n.type==OpaqueLeaf || n.type==MissingLeaf)key={n.type,n.payload};
            else{
                for(auto j=g.begin(i);j<n.end;++j)key.push_back(index.at(g.parents[j]));
                std::sort(key.begin(),key.end());key.erase(std::unique(key.begin(),key.end()),key.end());
                if(key.size()==1){index[i]=key[0];continue;}
                key.insert(key.begin(),Group);
            }
            index[i]=keys.emplace(key,Id(keys.size()+1)).first->second;
        }
        std::vector<Id> result;for(const auto &b:g.births)result.push_back(index.at(b.node));return result;
    }
};
int main(int argc,char **argv){
    if(argc!=3)return 2;
    try{
        Graph audit(argv[1]),light(argv[2]);need(audit.receipt==light.receipt && audit.status==light.status && audit.occurrence_count==light.occurrence_count,"different native models");
        need(audit.lits==light.lits && audit.births.size()==light.births.size(),"different native conclusions");
        Expressions table;auto expected=table.run(audit),actual=table.run(light);
        uint64_t permanent=0,query=0,unknown=0;
        for(size_t i=0;i<actual.size();++i){
            const auto &x=audit.births[i],&y=light.births[i];
            need(x.end==y.end,"birth length");
            const auto &n=audit.nodes[x.node],&m=light.nodes[y.node];
            if(n.flags!=m.flags || n.has_b!=m.has_b || expected[i]!=actual[i])throw std::runtime_error("different support at native birth "+std::to_string(i+1));
            permanent+=!(n.flags&7);query+=bool(n.flags&Query);unknown+=bool(n.flags&(Theory|Incomplete));
        }
        for(int i=7;i<10;++i)need(audit.stats[i]==light.stats[i],"native discharge boundary");
        auto used=light.reach();size_t inputs=0,final_inputs=0;
        for(size_t i=0;i<used.size();++i)if(light.nodes[i].type==InputLeaf){inputs+=bool(used[i]);final_inputs+=bool(used[i]&2);}
        std::cout<<"births\t"<<actual.size()<<"\npermanent\t"<<permanent<<"\nquery\t"<<query<<"\nunknown\t"<<unknown
            <<"\ncanonical_expressions\t"<<table.keys.size()<<"\ninput_occurrences\t"<<light.occurrence_count<<"\nused_inputs\t"<<inputs
            <<"\npermanent_inputs\t"<<final_inputs<<"\ndecoded_nodes\t"<<light.nodes.size()<<"\ndurable_edges\t"<<light.parents.size()<<'\n';
        const char *names[]={"transient_created","peak_live_transient","online_reclaimed","sweeps","written_edges","adopted","cache_hits","boundary_missing","boundary_mismatch","boundary_exact"};
        for(size_t i=0;i<10;++i)std::cout<<names[i]<<'\t'<<light.stats[i]<<'\n';
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
