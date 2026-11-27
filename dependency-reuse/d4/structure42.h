#ifndef DEAGLE_STRUCTURE42_H
#define DEAGLE_STRUCTURE42_H
#include "transport_graph.h"
#include <chrono>
#include <cstdlib>
#include <unordered_map>
#include <unordered_set>
namespace d42 {
using Literals=std::vector<int>;
struct Hash {size_t operator()(const Literals &key)const{uint64_t h=1;for(int k:key)h=(h^uint32_t(k))*UINT64_C(1099511628211);return h;}};
struct Flat {
    Literals data;std::vector<uint32_t> offsets{0},ordinals;
    void add(const Literals &c,unsigned seq){data.insert(data.end(),c.begin(),c.end());need(data.size()<UINT32_MAX,"CNF size");offsets.push_back(uint32_t(data.size()));ordinals.push_back(seq);}
    void get(size_t i,Literals &c)const{c.assign(data.begin()+offsets.at(i),data.begin()+offsets.at(i+1));}
};
inline void normalize(Literals &v){std::sort(v.begin(),v.end());v.erase(std::unique(v.begin(),v.end()),v.end());}
struct Atoms {
    Literals peer;std::vector<uint8_t> ordinary;
    explicit Atoms(int n):peer(n,-1),ordinary(n){}
    int translate(int raw)const{
        if(raw==-1||raw==-2)return raw;
        if(raw<2||size_t(raw/2)>=peer.size()||peer[raw/2]<0)return INT_MIN;
        return peer[raw/2]^(raw&1);
    }
    void theory(int raw){if(raw>=2 && size_t(raw/2)<ordinary.size())ordinary[raw/2]=0;}
};
struct Models {
    Flat old,now;Atoms a,b;std::vector<uint8_t> used;
    std::vector<unsigned> input_node;uint64_t p0_rows=0,p1_rows=0;
    Models(int n,int m,const Graph &g):a(n),b(m),used(g.reach()),input_node(size_t(g.occurrence_count)+1){
        for(Id i=1;i<g.nodes.size();++i)if(g.nodes[i].type==InputLeaf && used[i])
            input_node.at(g.nodes[i].payload)=i;
    }
    void map(const std::string &path){
        std::ifstream in(path);need(bool(in),"missing semantic map");int side,var,to;std::string role,reason,key;
        std::array<std::vector<uint8_t>,2> seen{{std::vector<uint8_t>(a.peer.size()),std::vector<uint8_t>(b.peer.size())}};
        while(in>>side>>var>>to>>role>>reason>>key){
            need(side==0||side==1,"map side");auto &m=side?b:a;
            need(var>0 && size_t(var)<m.peer.size(),"map variable");
            need(!seen[side][var] && to>=-1,"duplicate or malformed variable row");seen[side][var]=1;
            m.peer[var]=to;m.ordinary[var]=role=="Aux"||role=="Value";
        }
        need(in.eof(),"mapping input");validate();
    }
    void validate()const{
        for(int side=0;side<2;++side){const auto &x=side?b:a,&y=side?a:b;
            for(size_t v=1;v<x.peer.size();++v)if(x.peer[v]>=0){
                int t=x.peer[v];need(t>=2 && size_t(t/2)<y.peer.size() && y.peer[t/2]==int(2*v+(t&1)),"noninjective signed correspondence");
            }
        }
    }
    static void parse(const std::string &line,size_t start,Literals &out){
        out.clear();const char *p=line.c_str()+start;char *end;
        while(*p){auto v=std::strtol(p,&end,10);need(end!=p&&v>=INT_MIN&&v<=INT_MAX,"invalid native number");out.push_back(int(v));p=end;}
    }
    void read(const std::string &path,bool newer,const Graph &g){
        auto &side=newer?b:a;auto &flat=newer?now:old;
        std::ifstream in(path);need(bool(in),"model open");std::string l;Literals xs;unsigned seq=0;
        while(std::getline(in,l)){
            if(l.compare(0,2,"C\t")==0){
                ++seq;need(l.size()>=3,"bad CNF row");
                Id node=newer?0:input_node.at(seq);
                if(!newer && node){const auto flags=g.nodes[node].flags;need(l[2]==(flags==0?'B':flags==Query?'Q':'U'),"scope/ordinal mismatch");}
                if(l[2]!='B'||(!newer&&!node))continue;
                parse(l,3,xs);normalize(xs);flat.add(xs,seq);
            }else if(l.compare(0,6,"GUARD\t")==0){side.theory(std::stoi(l.substr(l.rfind('\t')+1)));}
            else if(l.compare(0,5,"EDGE\t")==0){
                auto p=l.find('\t',5);p=l.find('\t',p+1);p=l.find('\t',p+1);need(p!=std::string::npos,"edge schema");
                parse(l,p,xs);need(xs.size()==4,"edge fields");side.theory(xs[0]);side.theory(xs[3]);
            }else if(l.compare(0,3,"CO\t")==0){parse(l,3,xs);need(xs.size()==6,"CO fields");for(size_t j=2;j<xs.size();++j)side.theory(xs[j]);}
        }
        need(in.eof(),"CNF read failure");
        if(newer)p1_rows=seq;else{p0_rows=seq;need(seq==g.occurrence_count,"old model/occurrence mismatch");}
    }
};
struct Refinement {
    using Clock=std::chrono::steady_clock;
    unsigned rounds=0,added=0,ambiguous=0,collisions=0;uint64_t checks=0;std::string stop="fixed-point";
    // Each signature contains all known signed literals; exactly one ordinary atom remains.
    // Ambiguity on either side is rejected. Exact leaf membership is checked independently later.
    bool signature(const Literals &c,const Atoms &side,bool old,Literals &key,int &unknown){
        if(c.size()<2||c.size()>6)return false;
        key.clear();unknown=0;
        for(int l:c){
            if(l==-1||l==-2){key.push_back(l);continue;}
            if(l<2||size_t(l/2)>=side.peer.size())return false;
            if(side.peer[l/2]<0){
                if(unknown||!side.ordinary[l/2])return false;
                unknown=l;
            }else key.push_back(old?side.translate(l):l);
        }
        if(!unknown)return false;
        std::sort(key.begin(),key.end());return true;
    }
    void run(Models &m,std::ostream &proof){
        const auto end=Clock::now()+std::chrono::seconds(5);Literals c,key;
        for(unsigned round=1;round<=4;++round){
            struct Pair {int old=0,now=0;uint32_t first=0,second=0;};
            std::unordered_map<Literals,Pair,Hash> proposals;
            auto collect=[&](const Flat &f,bool left){
                for(size_t i=0;i<f.ordinals.size();++i){
                    if((i&1023)==0 && Clock::now()>=end){stop="time-budget";return false;}
                    if(left && !(m.used[m.input_node[f.ordinals[i]]]&2))continue;
                    f.get(i,c);int u;
                    if(!signature(c,left?m.a:m.b,left,key,u))continue;
                    if(checks==1000000){stop="candidate-budget";return false;}++checks;
                    if(left){auto &p=proposals[key];if(!p.old){p.old=u;p.first=f.ordinals[i];}else if(p.old!=u)p.old=-1;}
                    else{auto it=proposals.find(key);if(it==proposals.end())continue;auto &p=it->second;
                        if(!p.now){p.now=u;p.second=f.ordinals[i];}else if(p.now!=u)p.now=-1;}
                }return true;
            };
            if(!collect(m.old,true)||!collect(m.now,false))break;
            std::map<int,std::array<int,3>> forward;std::map<int,int> reverse;
            size_t visited=0;bool expired=false;
            for(const auto &kv:proposals){
                if((visited++ & 1023)==0 && Clock::now()>=end){expired=true;break;}
                const auto &p=kv.second;if(p.old<0||p.now<0){++ambiguous;continue;}if(!p.now)continue;
                const int v=p.old/2,w=p.now/2,to=p.now^(p.old&1);
                auto x=forward.emplace(v,std::array<int,3>{{to,int(p.first),int(p.second)}});
                if(!x.second && x.first->second[0]!=to)x.first->second[0]=-1;
                auto y=reverse.emplace(w,v);if(!y.second && y.first->second!=v)y.first->second=-1;
            }
            if(expired){stop="time-budget";break;}
            unsigned step=0;
            for(const auto &v:forward){
                if((visited++ & 1023)==0 && Clock::now()>=end){expired=true;break;}
                int i=v.first,t=v.second[0];
                if(t<0 || reverse.at(t/2)!=i){++collisions;continue;}
                need(m.a.peer[i]<0 && m.b.peer[t/2]<0 && m.a.ordinary[i] && m.b.ordinary[t/2],"anchor or theory collision");
                m.a.peer[i]=t;m.b.peer[t/2]=2*i+(t&1);++step;
                proof<<round<<'\t'<<i<<'\t'<<t<<'\t'<<v.second[1]<<'\t'<<v.second[2]<<'\n';
            }
            rounds=round;added+=step;
            if(expired){stop="time-budget";break;}
            if(!step)break;
            if(round==4)stop="round-limit";
        }
        m.validate();
    }
};
}
#endif
