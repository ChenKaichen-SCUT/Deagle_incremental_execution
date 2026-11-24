#pragma once
// Positive ground rules and two implicit binary transitivity families.
// A fired rule is indexed even when its head was already present.
#include <algorithm>
#include <array>
#include <chrono>
#include <deque>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

namespace oc11 {
using Tick = unsigned long long;
inline Tick clock_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}
using Atom = std::array<int,3>; // predicate, left argument, right argument
enum Predicate { Path=1, Order, On, ChooseRF, EligibleRF, RF, ChooseCO, EligibleCO,
                 WS, FR, Competes, Member, Different, Enabled, Contradiction, Static, IfOrder };
struct Rule {
    int name;
    Atom head;
    std::vector<Atom> body;
    bool operator<(const Rule &r) const {
        return std::tie(name,head,body)<std::tie(r.name,r.head,r.body);
    }
};
template<class T> std::set<T> minus_set(const std::set<T> &a,const std::set<T> &b) {
    std::set<T> out;
    std::set_difference(a.begin(),a.end(),b.begin(),b.end(),std::inserter(out,out.end()));
    return out;
}
struct Delta {
    size_t removed=0,added=0,dirty=0,clean_derived=0,affected=0,boundary=0,checked=0,new_fired=0,rederived=0;
    Tick retract_ns=0,derive_ns=0;
};
class Closure {
    using Rules=std::set<Rule>;
    using Facts=std::set<Atom>;
    using Slot=std::pair<int,int>;
    std::map<Slot,std::set<int>> outgoing,incoming;
    std::map<Atom,Rules> consumers,by_body,by_head;
    Rules fired,explicit_rules;
    Facts base;
    std::deque<Atom> agenda;
    static bool transitive(int p){return p==Path || p==Order;}
    static Rule trans(int p,int a,int b,int c) {
        return {p==Path ? 1 : 2,{p,a,c},{{p,a,b},{p,b,c}}};
    }
    void insert(Atom a) {
        if(!facts.insert(a).second)return;
        agenda.push_back(a);
        if(transitive(a[0])){outgoing[{a[0],a[1]}].insert(a[2]);incoming[{a[0],a[2]}].insert(a[1]);}
    }
    void consider(const Rule &r) {
        ++stats.checked;
        for(auto a:r.body)if(!facts.count(a))return;
        if(fired.insert(r).second){
            ++stats.new_fired;
            for(auto a:r.body)consumers[a].insert(r);
        }
        insert(r.head);
    }
    void forget(const Rule &r) {
        if(!fired.erase(r))return;
        for(auto a:r.body)consumers[a].erase(r);
    }
public:
    Facts facts,retained;
    Delta stats;
    size_t instances()const{return fired.size();}
    const Rules &supports()const{return fired;}
    void update(const Facts &next,const Rules &rules={}) {
        stats={}; auto start=clock_ns();
        auto deleted=minus_set(base,next), added=minus_set(next,base);
        auto gone=minus_set(explicit_rules,rules), born=minus_set(rules,explicit_rules);
        stats.removed=deleted.size();stats.added=added.size();
        Facts dirty=deleted;Rules affected;
        for(const auto &r:gone){
            if(fired.count(r)){dirty.insert(r.head);affected.insert(r);}
            for(auto a:r.body)by_body[a].erase(r);
            by_head[r.head].erase(r);
        }
        std::deque<Atom> queue(dirty.begin(),dirty.end());
        while(!queue.empty()){
            auto a=queue.front();queue.pop_front();
            for(const auto &r:consumers[a]){
                affected.insert(r);
                if(dirty.insert(r.head).second)queue.push_back(r.head);
            }
        }
        for(const auto &r:affected)forget(r);
        for(auto a:dirty){
            facts.erase(a);
            if(transitive(a[0])){outgoing[{a[0],a[1]}].erase(a[2]);incoming[{a[0],a[2]}].erase(a[1]);}
        }
        retained=minus_set(facts,base);
        stats.dirty=dirty.size();stats.clean_derived=retained.size();stats.affected=affected.size();
        auto middle=clock_ns();stats.retract_ns=middle-start;
        for(const auto &r:born){
            by_head[r.head].insert(r);for(auto a:r.body)by_body[a].insert(r);
        }
        for(auto a:added)insert(a);
        for(auto a:dirty)if(next.count(a))insert(a);
        for(const auto &r:born){++stats.boundary;consider(r);}
        for(auto h:dirty){
            for(const auto &r:by_head[h]){++stats.boundary;consider(r);}
            if(transitive(h[0])){
                auto mids=outgoing[{h[0],h[1]}];
                for(int m:mids)if(incoming[{h[0],h[2]}].count(m)){
                    ++stats.boundary;consider(trans(h[0],h[1],m,h[2]));
                }
            }
        }
        while(!agenda.empty()){
            auto a=agenda.front();agenda.pop_front();
            for(const auto &r:by_body[a])consider(r);
            if(!transitive(a[0]))continue;
            auto left=incoming[{a[0],a[1]}],right=outgoing[{a[0],a[2]}];
            for(int x:left)consider(trans(a[0],x,a[1],a[2]));
            for(int z:right)consider(trans(a[0],a[1],a[2],z));
        }
        for(auto a:dirty)if(facts.count(a))++stats.rederived;
        base=next;explicit_rules=rules;stats.derive_ns=clock_ns()-middle;
    }
};
}
