#pragma once
// Included AFTER the native Closure interface. One worker, one solve at a time.
#include "closure_delta.hpp"
#include <fstream>
#include <sstream>
namespace oc11 {
using Arc=std::pair<int,int>;
struct Frame {
    std::vector<int> pred,succ;
    std::vector<Arc> absent,present;
    std::map<int,std::vector<Arc>> absent_by_row,present_by_row;
    void index(){
        for(auto p:absent)absent_by_row[p.first].push_back(p);
        for(auto p:present)present_by_row[p.first].push_back(p);
    }
};
struct Session {
    Closure root;
    std::map<std::string,int> symbols;
    std::map<std::string,std::string> names;
    std::map<int,int> block_of,native_of;
    std::map<Arc,Frame> old,current;
    bool enabled=false,incremental=false,static_po=false;
    std::string directory,reason;
    Tick graph_ns=0;
    size_t joins=0,accepted=0,rows_used=0,derived_used=0,pairs_saved=0,rf=0,guard=0,co=0,push=0,pop=0;
    std::set<Arc> consumed;
    int intern(const std::string &s){
        auto it=symbols.find(s);
        if(it!=symbols.end())return it->second;
        int n=int(symbols.size());symbols.emplace(s,n);return n;
    }
    void open(const std::string &dir,bool reuse){
        directory=dir;incremental=reuse;old.clear();
        if(reuse)old.swap(current);else root=Closure();
        current.clear();block_of.clear();native_of.clear();names.clear();consumed.clear();
        graph_ns=joins=accepted=rows_used=derived_used=pairs_saved=rf=guard=co=push=pop=0;
        std::ifstream f(dir+"/events.tsv");
        std::string endpoint,semantic;
        enabled=bool(f);static_po=false;reason=enabled?"admitted":"unverified_events";
        while(f>>endpoint>>semantic)if(!names.emplace(endpoint,semantic).second){enabled=false;reason="duplicate_event";}
    }
    template<class Table> void prepare(Minisat::closure &g,const Table &pos,const Table &apos,bool race){
        if(!enabled)return;
        auto start=clock_ns();
        if(race || g.nodes.size()>175){reason=race?"race_outside_root_calculus":"root_index_budget";enabled=false;return;}
        std::map<int,std::vector<std::string>> members,directions;
        std::set<std::string> unique;
        for(int i=0;i<int(g.nodes.size());++i){
            auto it=names.find(g.nodes[i].name);
            if(it==names.end() || !unique.insert(it->second).second){reason="unconfirmed_event_bijection";enabled=false;return;}
            members[g.union_find_parent(i)].push_back(it->second);
            if(!g.nodes[i].in_rf.empty() || !g.nodes[i].out_rf.empty()){reason="active_rf_before_static";enabled=false;return;}
        }
        for(const auto &p:apos){
            int u=g.get_node(p.first.first),v=g.get_node(p.first.second);
            if(g.union_find_parent(u)!=g.union_find_parent(v)){reason="inconsistent_apo_partition";enabled=false;return;}
            directions[g.union_find_parent(u)].push_back(names.at(p.first.first)+">"+names.at(p.first.second));
        }
        for(auto &m:members){
            auto &d=directions[m.first];std::sort(m.second.begin(),m.second.end());std::sort(d.begin(),d.end());
            std::string signature="members";for(auto &s:m.second)signature+=":"+s;
            signature+="|directed";for(auto &s:d)signature+=":"+s;
            int id=intern(signature);block_of[m.first]=id;native_of[id]=m.first;
        }
        std::set<Atom> base;
        for(const auto &p:pos){
            int a=block_of.at(g.union_find_parent(g.get_node(p.first.first)));
            int b=block_of.at(g.union_find_parent(g.get_node(p.first.second)));
            if(a!=b)base.insert({Path,a,b});
        }
        root.update(base);graph_ns=clock_ns()-start;
        for(auto a:root.facts)if(a[1]==a[2]){reason="static_cycle_native_cold";enabled=false;return;}
        std::ofstream out(directory+"/worker/closure.tsv");
        std::vector<std::string> labels(symbols.size());for(const auto &v:symbols)labels[v.second]=v.first;
        for(auto a:root.facts)out<<labels[a[1]]<<'\t'<<labels[a[2]]<<'\t'<<base.count(a)<<'\t'<<root.retained.count(a)<<'\n';
    }
    // Fast path runs inside native activate_directed_edge. Native calls and their order are unchanged.
    // All three reasons (predecessor, PO, successor) must be empty. A missing saved hit goes cold.
    template<class Has,class Apply> int join(Minisat::closure &g,int u,int v,Has has,Apply apply) {
        if(!enabled || !static_po)return -1;
        ++joins;Frame now;
        for(const auto &e:g.nodes[u].in){if(!e.reason.empty())return -1;now.pred.push_back(block_of.at(e.from));}
        for(const auto &e:g.nodes[v].out){if(!e.reason.empty())return -1;now.succ.push_back(block_of.at(e.to));}
        now.pred.push_back(block_of.at(u));now.succ.push_back(block_of.at(v));
        Arc key={block_of.at(u),block_of.at(v)};
        auto it=old.find(key);
        if(incremental && it!=old.end() && now.pred==it->second.pred && now.succ==it->second.succ){
            const auto &s=it->second;bool safe=true;
            for(auto p:s.present)if(!has(native_of.at(p.first),native_of.at(p.second))){safe=false;break;}
            for(auto p:s.absent)if(!root.retained.count({Path,p.first,p.second})){safe=false;break;}
            if(safe){
                ++accepted;pairs_saved+=now.pred.size()*now.succ.size();
                for(auto p:s.absent){
                    int a=native_of.at(p.first),b=native_of.at(p.second);
                    if(has(a,b)){now.present.push_back(p);continue;}
                    now.absent.push_back(p);consumed.insert(p);++derived_used;
                    if(apply(a,b))return 1;
                }
                now.present.insert(now.present.end(),s.present.begin(),s.present.end());now.index();current[key]=std::move(now);
                return 0;
            }
        }
        // A changed predecessor list need not invalidate every unchanged row of the product.
        // Row order follows P1. The old partition must cover exactly the complete current suffix.
        bool same_columns=incremental && it!=old.end() && it->second.succ==now.succ;
        for(int a:now.pred){
            if(same_columns){
                static const std::vector<Arc> none;
                const auto &s=it->second;
                auto hit=s.present_by_row.find(a),miss=s.absent_by_row.find(a);
                const auto &existing=hit==s.present_by_row.end()?none:hit->second;
                const auto &inserted=miss==s.absent_by_row.end()?none:miss->second;
                bool safe=!inserted.empty() && existing.size()+inserted.size()==now.succ.size();
                if(safe)for(auto p:existing)if(!has(native_of.at(a),native_of.at(p.second))){safe=false;break;}
                if(safe)for(auto p:inserted)if(!root.retained.count({Path,a,p.second})){safe=false;break;}
                if(safe){
                    ++rows_used;pairs_saved+=now.succ.size();
                    now.present.insert(now.present.end(),existing.begin(),existing.end());
                    for(auto p:inserted){
                        int x=native_of.at(a),y=native_of.at(p.second);
                        if(has(x,y)){now.present.push_back(p);continue;}
                        now.absent.push_back(p);consumed.insert(p);++derived_used;
                        if(apply(x,y))return 1;
                    }
                    continue;
                }
            }
            for(int b:now.succ){
                int x=native_of.at(a),y=native_of.at(b);
                if(has(x,y)){now.present.emplace_back(a,b);continue;}
                now.absent.emplace_back(a,b);
                if(apply(x,y))return 1;
            }
        }
        now.index();current[key]=std::move(now);return 0;
    }
    void report(){
        std::ofstream f(directory+"/worker/closure-stats.tsv");
        const auto &d=root.stats;
        f<<"reason\t"<<reason<<"\nroot_prepare_ns\t"<<graph_ns<<"\nretract_ns\t"<<d.retract_ns
         <<"\nderive_ns\t"<<d.derive_ns<<"\ndeleted\t"<<d.removed<<"\nadded\t"<<d.added<<"\nO\t"<<d.dirty
         <<"\nK_derived\t"<<d.clean_derived<<"\nrecovered\t"<<d.rederived<<"\naffected_instances\t"<<d.affected
         <<"\nboundary_checked\t"<<d.boundary<<"\nrule_checks\t"<<d.checked<<"\nfired_instances\t"<<root.instances()
         <<"\nnative_static_joins\t"<<joins<<"\ncached_joins\t"<<accepted<<"\ncached_rows\t"<<rows_used<<"\nused_derived\t"<<consumed.size()
         <<"\nretained_insertions\t"<<derived_used<<"\ncartesian_pairs_bypassed\t"<<pairs_saved
         <<"\nrf_activations\t"<<rf<<"\nguard_activations\t"<<guard<<"\ndynamic_co_pairs\t"<<co
         <<"\npush\t"<<push<<"\npop\t"<<pop<<"\n";
    }
};
inline Session &session(){static Session value;return value;}
}
