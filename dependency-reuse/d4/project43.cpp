// Offline only. Project actual Audit DAG supports in bounded blocks of 512 columns.
#include "transport_graph.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <map>
#include <sstream>
#include <unordered_map>
#include <omp.h>

using d42::Id;
using d42::need;
using d42::Fact;
using d42::Graph;
using std::uint32_t;
using std::uint64_t;
namespace {
constexpr unsigned metrics=10, words=8;
constexpr uint32_t absent=UINT32_MAX;
enum Domain { B, T };
enum Width { BooleanLeaves, TheoryLeaves, QueryLeaves, UnknownLeaves, BooleanGroups, TheoryGroups,
             BooleanSmall, TheorySmall, BooleanLarge, TheoryLarge };
using Widths=std::array<uint32_t,metrics>;

struct Leaf {
    uint32_t group;
    uint16_t slot;
    uint8_t state,use;
};
static_assert(sizeof(Leaf)==8, "incompatible leaf record");

template<class V> void read(std::istream &in,V &v){
    in.read(reinterpret_cast<char*>(&v),sizeof(v));
}
struct Directory {
    std::vector<Leaf> boolean,theory;
    std::map<Fact,Id> registry;
    explicit Directory(const std::string &path){
        std::ifstream in(path,std::ios::binary);
        in.exceptions(std::ios::badbit|std::ios::failbit);
        char magic[8];in.read(magic,8);
        need(std::memcmp(magic,"D43LEF1",8)==0,"leaf directory header");
        Id nb,nt;read(in,nb);read(in,nt);
        boolean.resize(size_t(nb)+1);theory.resize(size_t(nt)+1);
        in.read(reinterpret_cast<char*>(boolean.data()+1),sizeof(Leaf)*nb);
        for(Id i=1;i<=nt;++i){
            Fact f;read(in,f);read(in,theory[i]);
            need(registry.emplace(f,i).second,"duplicate theory declaration");
        }
        need(in.peek()==EOF,"trailing leaf data");
    }
};
struct Dirty{
    std::vector<uint8_t> group;
    std::array<bool,256> small{};
    std::array<bool,1024> large{};
    void seed(const Leaf &l){
        if(l.group>=group.size())group.resize(size_t(l.group)+1);
        group[l.group]=1;small.at(l.slot%256)=true;large.at(l.slot)=true;
    }
    uint32_t mask(const Leaf &l,unsigned u,Domain dom)const{
        const unsigned shift=4+6*u+dom;
        uint32_t m=0;
        if(l.group<group.size() && group[l.group])m|=1u<<shift;
        if(small.at(l.slot%256))m|=1u<<(shift+2);
        if(large.at(l.slot))m|=1u<<(shift+4);
        return m;
    }
};
struct Join {Id end,seed;};
struct Reduced {
    std::vector<Join> nodes{{0,absent}};
    std::vector<Id> edges,at_birth;
    std::vector<Widths> features;
    std::array<std::unordered_map<Id,Id>,metrics> cols;
    std::vector<uint32_t> masks;

    void put(Widths &f,unsigned metric,Id key){
        auto &m=cols[metric];
        auto it=m.emplace(key,Id(m.size())).first;
        f[metric]=it->second;
    }
    Id leaf(Domain dom,Id local,const Leaf &l){
        Widths f;f.fill(absent);
        if(l.state==5||l.state==6){
            put(f,l.state==5?QueryLeaves:UnknownLeaves,local);
        }else{
            put(f,BooleanLeaves+dom,local);
            put(f,BooleanGroups+dom,l.group);
            put(f,BooleanSmall+dom,l.slot%256);
            put(f,BooleanLarge+dom,l.slot);
        }
        Id n=Id(nodes.size());
        nodes.push_back({Id(edges.size()),Id(features.size())});
        features.push_back(f);return n;
    }
    void build(const Graph &g,const Directory &d){
        const auto reached=g.reach();
        need(d.boolean.size()==size_t(g.occurrence_count)+1,"occurrence count");
        std::array<std::array<Dirty,2>,2> dirty;
        for(Domain dom:{B,T}){
            const auto &v=dom==B?d.boolean:d.theory;
            for(size_t i=1;i<v.size();++i){
                const auto &l=v[i];
                need(l.slot<1024 && (l.use==0||l.use==1||l.use==3),"invalid directory entry");
                need((dom==T?(l.state==0||l.state==3||l.state==4):
                      (l.state<=2||l.state==5||l.state==6)) && (l.group!=0)==(l.state<5),"domain");
                if(l.state>0 && l.state<5){
                    dirty[1][dom].seed(l);
                    if(l.use&2)dirty[0][dom].seed(l);
                }
            }
        }
        std::vector<uint8_t> breal(d.boolean.size()),treal(d.theory.size());
        std::vector<Id> ids(g.nodes.size()),ps;
        masks.resize(g.nodes.size());
        // One physical join per genuine fan-in. Aliasing a unary node preserves every support column.
        for(Id i=1;i<g.nodes.size();++i){
            const auto &n=g.nodes[i];
            if(n.type==d42::InputLeaf || n.type==d42::FactLeaf){
                Domain dom=n.type==d42::InputLeaf?B:T;
                Id local=dom==B?n.payload:d.registry.at(g.facts.at(n.payload));
                const Leaf &l=dom==B?d.boolean.at(local):d.theory.at(local);
                (dom==B?breal:treal).at(local)|=reached[i];
                if(dom==B)need(n.flags==(l.state==5?Minisat::Query:l.state==6?Minisat::Incomplete:0),"Boolean scope");
                ids[i]=leaf(dom,local,l);
                if(l.state<5){
                    for(unsigned u=0;u<2;++u)masks[i]|=dirty[u][dom].mask(l,u,dom);
                    if(l.state)masks[i]|=1u<<(l.state-1);
                }
            }else if(n.type==d42::MissingLeaf||n.type==d42::OpaqueLeaf){
                // Keep opaque sources distinct from raw unknown occurrences.
                ids[i]=leaf(B,Id(d.boolean.size())+i,Leaf{0,0,6,1});
            }else{
                ps.clear();
                for(Id e=g.begin(i);e<n.end;++e){
                    Id p=g.parents[e];masks[i]|=masks.at(p);
                    if(ids[p])ps.push_back(ids[p]);
                }
                std::sort(ps.begin(),ps.end());
                ps.erase(std::unique(ps.begin(),ps.end()),ps.end());
                if(ps.size()==1)ids[i]=ps[0];
                else if(!ps.empty()){
                    ids[i]=Id(nodes.size());edges.insert(edges.end(),ps.begin(),ps.end());
                    need(edges.size()<UINT32_MAX,"projection edge overflow");
                    nodes.push_back({Id(edges.size()),absent});
                }
            }
        }
        for(size_t i=1;i<breal.size();++i)need(breal[i]==d.boolean[i].use,"U_audit Boolean union");
        for(size_t i=1;i<treal.size();++i)need(treal[i]==d.theory[i].use,"U_audit theory union");
        for(const auto &b:g.births)at_birth.push_back(ids[b.node]);
    }

    std::vector<Widths> widths()const{
        using Bits=std::array<uint64_t,words>;
        struct Batch {unsigned metric;Id start;};
        std::vector<Batch> jobs;
        for(unsigned k=0;k<metrics;++k)
            for(Id start=0;start<cols[k].size();start+=64*words)jobs.push_back({k,start});
        std::vector<Widths> result(at_birth.size());
        #pragma omp parallel
        {
            std::vector<Bits> bits(nodes.size());
            std::vector<Widths> sums(at_birth.size());
            #pragma omp for schedule(dynamic,1)
            for(size_t j=0;j<jobs.size();++j){
                auto b=jobs[j];Id end=b.start+64*words;
                for(Id i=1;i<nodes.size();++i){
                    auto &v=bits[i];v.fill(0);
                    auto n=nodes[i];
                    if(n.seed!=absent){
                        Id c=features[n.seed][b.metric];
                        if(c>=b.start && c<end)v[(c-b.start)/64]|=UINT64_C(1)<<(c%64);
                    }else{
                        for(Id e=nodes[i-1].end;e<n.end;++e){
                            const auto &p=bits[edges[e]];
                            for(size_t w=0;w<words;++w)v[w]|=p[w];
                        }
                    }
                }
                for(size_t i=0;i<at_birth.size();++i)
                    for(uint64_t w:bits[at_birth[i]])sums[i][b.metric]+=__builtin_popcountll(w);
            }
            #pragma omp critical
            for(size_t i=0;i<result.size();++i)
                for(unsigned k=0;k<metrics;++k)result[i][k]+=sums[i][k];
        }
        return result;
    }
};

std::vector<int> mapping(const std::string &path){
    std::ifstream f(path,std::ios::binary|std::ios::ate);
    auto bytes=f.tellg();need(bytes>0 && bytes%4==0,"bad signed map");
    std::vector<int> mu(size_t(bytes)/4);f.seekg(0);
    f.read(reinterpret_cast<char*>(mu.data()),bytes);need(bool(f),"truncated map");return mu;
}

void report(const Graph &g,const Reduced &r,const std::vector<int> &mu,
            const std::string &catalog,const std::string &out){
    auto widths=r.widths();
    std::ifstream ref(catalog);std::string line;std::getline(ref,line);
    std::ofstream data(out+"/births.tsv");data.exceptions(std::ios::badbit|std::ios::failbit);
    data<<"ordinal\taudit_id\tflags\thas_b\tmapped\tmask\tb_leaves\tt_leaves\tq_leaves\tu_leaves"
          "\tb_groups\tt_groups\tb_small\tt_small\tb_large\tt_large\n";
    for(size_t i=0;i<g.births.size();++i){
        auto birth=g.births[i];auto n=g.nodes[birth.node];
        bool mapped=true;
        for(Id j=g.litBegin(i);j<birth.end;++j){
            int l=g.lits[j];
            if(l<2||size_t(l/2)>=mu.size()||mu[l/2]<2)mapped=false;
        }
        uint32_t m=r.masks[birth.node];
        bool alive=!(m&15) && !(n.flags&7);
        bool exact=alive && mapped;
        unsigned ordinal,id,flags,boolean,a,c,e;
        need(bool(std::getline(ref,line)),"missing reference birth");std::istringstream row(line);
        need(bool(row>>ordinal>>id>>flags>>boolean>>a>>c>>e) && ordinal==i+1 && id==birth.original &&
             flags==n.flags && boolean==n.has_b && a==alive && c==mapped && e==exact,"D4.2 birth disagreement");
        auto w=widths[i];
        for(unsigned domain:{0u,1u})
            need(w[domain]>=w[4+domain] && w[4+domain]>=w[8+domain] && w[8+domain]>=w[6+domain],
                 "support cardinalities are not nested");
        if(!(n.flags&7))need(bool(w[0])==bool(n.has_b) && bool(w[1])==bool(n.flags&8) && !w[2] && !w[3],
                              "permanent class disagrees with effective leaves");
        for(unsigned u=0;u<2;++u){
            unsigned h=(m>>(4+6*u))&63, group=h&3, small=(h>>2)&3, large=(h>>4)&3;
            need((group&~large)==0 && (large&~small)==0,"slot nesting");
            if(!(n.flags&7))need((!(m&3)||(group&1)) && (!(m&12)||(group&2)),"compact false acceptance");
        }
        need((((m>>4)&63)&~(m>>10))==0,"U bounds reversed");
        data<<ordinal<<'\t'<<id<<'\t'<<flags<<'\t'<<boolean<<'\t'<<mapped<<'\t'<<m;
        for(auto v:w)data<<'\t'<<v;
        data<<'\n';
    }
    need(!std::getline(ref,line) && ref.eof(),"extra catalogue births");
    std::ofstream stats(out+"/topology.tsv");
    stats<<"audit_reachable_nodes\taudit_parent_edges\twidth_nodes\twidth_edges\tbirths\n";
    stats<<g.nodes.size()-1<<'\t'<<g.parents.size()<<'\t'<<r.nodes.size()-1<<'\t'<<r.edges.size()
         <<'\t'<<g.births.size()<<'\n';
}
}
int main(int argc,char **argv){
    if(argc!=6){std::cerr<<"project43 proof.bin leaves.bin mu.bin catalog42.tsv out-dir\n";return 2;}
    try{
        Graph g(argv[1]);Directory d(argv[2]);Reduced r;r.build(g,d);
        report(g,r,mapping(argv[3]),argv[4],argv[5]);
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
