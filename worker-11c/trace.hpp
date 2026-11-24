#pragma once
// Per-query observer. No address or allocator offset is transported to a new query.
#include "minisat/core/ClosureSolver.h"
#include <algorithm>
#include <chrono>
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <vector>
namespace c11 {
using namespace Minisat;
using Key=std::vector<int>;
inline unsigned long long now(){return std::chrono::duration_cast<std::chrono::nanoseconds>(
    std::chrono::steady_clock::now().time_since_epoch()).count();}
template<class C> Key lits(const C &c){
    Key k;for(int i=0;i<int(c.size());++i)k.push_back(c[i].x);return k;
}
inline Key sorted(Key k){std::sort(k.begin(),k.end());return k;}
inline std::string field(const Key &xs){
    std::ostringstream out;for(size_t i=0;i<xs.size();++i){if(i)out<<',';out<<xs[i];}return out.str();
}
struct Entry {std::string tag;Key key;};
struct Rule {int type,w,r,v;};
struct State {
    bool collecting=false,chains=false,watching=false,running=false,posted=false;
    std::ofstream log,usage;
    std::map<CRef,Entry> known,imported;
    std::map<Key,int> pending;
    std::vector<Rule> rules;
    std::vector<size_t> marks;
    std::set<Key> prop_seen;
    size_t theory_id=0,learn_id=0,prevent_count=0,cycles=0,prevent_attempts=0,learned=0,pruned=0,collections=0;
    size_t full_cycles=0,analysis_limit=9000;
    int last_cycle=0,endpoint_a=-1,endpoint_b=-1,trigger=-1,trigger_target=-1;
    std::string cause;Key assumptions;
    std::map<std::pair<std::string,std::string>,size_t> hits;
    unsigned long long collection_ns=0,analysis_ns=0,persist_ns=0,install_ns=0;
    void open(const std::string &dir,bool capture,bool cdcl,bool observe){
        *this=State();collecting=capture;chains=cdcl;watching=observe;
        log.open(dir+"/proof.log");usage.open(dir+"/use.tsv");
    }
    void push(){if(collecting)marks.push_back(rules.size());}
    void pop(int n){if(collecting && size_t(n)<marks.size()){rules.resize(marks[n]);marks.resize(n);}}
    void infer(int kind,int w,int r,int v){if(collecting)rules.push_back({kind,w,r,v});}
    void snapshot(closure &g,int id,const char *origin,int a,int b,const Key &clause){
        auto t=now();
        log<<"E\t"<<id<<'\t'<<origin<<'\t'<<a<<'\t'<<b<<'\t'<<cause<<'\t'<<trigger<<'\t'<<trigger_target<<'\t'<<field(clause)<<"\n";
        for(int i=0;i<int(g.nodes.size());++i){
            auto &v=g.nodes[i];
            if(v.is_write && v.guard_lighted)log<<"G\t"<<id<<'\t'<<i<<'\t'<<v.guard.x<<"\n";
            for(auto &e:v.out_rf)log<<"R\t"<<id<<'\t'<<e.from<<'\t'<<e.to<<'\t'<<field(lits(e.reason))<<"\n";
        }
        for(auto &r:rules)log<<"I\t"<<id<<'\t'<<r.type<<'\t'<<r.w<<'\t'<<r.r<<'\t'<<r.v<<"\n";
        collection_ns+=now()-t;
    }
    void nodes(closure &g){
        if(!collecting)return;
        for(size_t i=0;i<g.nodes.size();++i)log<<"N\t"<<i<<'\t'<<g.nodes[i].name<<"\n";
    }
    void attempted(int a,int b){if(collecting){endpoint_a=a;endpoint_b=b;}}
    template<class SolverType> void conflict(closure &g,SolverType &s,CRef ref,const vec<Lit>& clause,int level){
        if(!collecting)return;
        ++cycles;last_cycle=0;
        if(full_cycles>=128){log<<"X\tcycle_budget\t"<<cycles<<'\t'<<g.conflict_origin<<"\n";return;}
        ++full_cycles;int id=++theory_id;last_cycle=id;auto key=lits(clause);
        snapshot(g,id,g.conflict_origin,endpoint_a,endpoint_b,key);
        log<<"V\t"<<id<<'\t'<<level<<'\t'<<field(assumptions);
        for(auto x:key){Lit l;l.x=x;log<<'\t'<<x<<','<<toInt(s.value(l))<<','<<s.order_literal_level(l);}
        log<<"\n";known[ref]={"t"+std::to_string(id),sorted(key)};
    }
    void prevent(closure &g,int r,int w,const literal_set &clause){
        if(!collecting || !chains)return;
        ++prevent_attempts;
        Key k;for(auto l:clause)k.push_back(l.x);k=sorted(k);
        if(prevent_count>=200 || !prop_seen.insert(k).second)return;
        ++prevent_count;int id=++theory_id;pending[k]=id;
        snapshot(g,id,"reverse_rf",r,w,k);
    }
    template<class SolverType> void propagated(SolverType &s,CRef ref,const vec<Lit>& clause,int level){
        if(!chains)return;
        Key k=sorted(lits(clause));auto it=pending.find(k);if(it==pending.end())return;
        known[ref]={"t"+std::to_string(it->second),k};
        log<<"P\t"<<it->second<<'\t'<<level<<'\t'<<field(assumptions);
        for(auto x:k){Lit p;p.x=x;log<<'\t'<<x<<','<<toInt(s.value(p))<<','<<s.order_literal_level(p);}
        log<<"\n";pending.erase(it);
    }
    std::string tag(CRef cr,const Clause &c){
        auto it=known.find(cr);
        if(it!=known.end() && it->second.key==sorted(lits(c)))return it->second.tag;
        return c.learnt()?"u":"b";
    }
    bool recording()const{return chains && learn_id<=analysis_limit;}
    void start(){if(collecting){++learn_id;++learned;}}
    void parent(CRef cr,const Clause &c,int pivot){
        if(!recording())return;
        log<<"A\t"<<learn_id<<'\t'<<pivot<<'\t'<<tag(cr,c)<<'\t'<<field(lits(c))<<"\n";
    }
    void raw(const vec<Lit> &c){if(recording())log<<"Q\t"<<learn_id<<'\t'<<field(lits(c))<<"\n";}
    void finish(const vec<Lit> &c){if(collecting)log<<"L\t"<<learn_id<<'\t'<<field(lits(c))<<"\n";}
    void learned_ref(CRef cr,const vec<Lit> &c){if(recording())known[cr]={"l"+std::to_string(learn_id),sorted(lits(c))};}
    void hit(CRef ref,const Clause &c,const char *why){
        if(!watching || !running)return;
        auto it=imported.find(ref);
        if(it!=imported.end() && it->second.key==sorted(lits(c)))++hits[{it->second.tag,why}];
    }
    void drop(CRef cr){if(collecting||watching){known.erase(cr);imported.erase(cr);++pruned;}}
    void gc(){if(collecting||watching){known.clear();imported.clear();++collections;}}
    void end(){
        auto a=now();log<<"Z\t"<<cycles<<'\t'<<full_cycles<<'\t'<<prevent_attempts<<'\t'<<prevent_count<<'\t'<<learned<<'\t'<<pruned<<'\t'<<collections<<"\n";
        for(auto &h:hits)usage<<"hit\t"<<h.first.first<<'\t'<<h.first.second<<'\t'<<h.second<<"\n";
        log.flush();usage.flush();persist_ns+=now()-a;
    }
};
inline State &state(){static State s;return s;}
}
