// Independent offline oracle. Operates on the original Audit DAG and never links a solver.
#include "transport_graph.h"
#include <map>
#include <iostream>
using namespace d42;
struct Leaf {Id group;uint16_t slot;uint8_t state,reach;};
struct Bits {std::array<uint64_t,16> b{},t{};};
template<class V> void read(std::istream &f,V &v){f.read(reinterpret_cast<char*>(&v),sizeof(v));}
template<class V> void put(std::ostream &f,const V &v){f.write(reinterpret_cast<const char*>(&v),sizeof(v));}
int main(int argc,char **argv){
    if(argc!=4)return 2;
    try{
        Graph g(argv[1]);std::ifstream f(argv[2],std::ios::binary);f.exceptions(std::ios::failbit|std::ios::badbit);
        char magic[8];f.read(magic,8);need(!memcmp(magic,"D43LEF1",8),"directory");
        Id nb,nt;read(f,nb);read(f,nt);need(nb==g.occurrence_count,"occurrences");
        std::vector<Leaf> b(nb+1);f.read(reinterpret_cast<char*>(&b[1]),nb*sizeof(Leaf));
        std::map<Fact,Leaf> t;for(Id i=0;i<nt;++i){Fact k;Leaf x;read(f,k);read(f,x);need(t.emplace(k,x).second,"duplicate fact");}
        need(f.peek()==EOF,"trailing directory");
        std::vector<Bits> masks(g.nodes.size());auto reach=g.reach();
        for(Id i=1;i<g.nodes.size();++i){
            auto &n=g.nodes[i];auto &out=masks[i];
            if(n.type==InputLeaf || n.type==FactLeaf){
                const bool is_b=n.type==InputLeaf;
                const Leaf &l=is_b?b.at(n.payload):t.at(g.facts.at(n.payload));
                need(l.reach==reach[i] && l.slot<1024,"support leaf");
                if(l.state<5)(is_b?out.b:out.t)[l.slot/64]|=UINT64_C(1)<<(l.slot%64);
            }else for(Id j=g.begin(i);j<n.end;++j){
                const Bits &p=masks[g.parents[j]];
                for(size_t w=0;w<16;++w){out.b[w]|=p.b[w];out.t[w]|=p.t[w];}
            }
        }
        std::ofstream out(argv[3],std::ios::binary);out.exceptions(std::ios::failbit|std::ios::badbit);
        out.write("D43REF1",8);put(out,Id(g.births.size()));
        for(size_t i=0;i<g.births.size();++i){
            auto &birth=g.births[i];auto &n=g.nodes[birth.node];
            put(out,Id(n.flags));put(out,birth.original);Id len=birth.end-g.litBegin(i);put(out,len);
            if(len)out.write(reinterpret_cast<const char*>(&g.lits[g.litBegin(i)]),4*len);
            put(out,masks[birth.node]);
        }
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
