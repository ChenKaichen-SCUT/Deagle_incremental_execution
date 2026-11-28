#pragma once

#include "session_contract.h"
#include "minisat/core/Solver.h"
#include <algorithm>
#include <fstream>
#include <stdexcept>
#include <unordered_map>

namespace deagle_pi {
struct VectorHash {
    size_t operator()(const std::vector<int>& v) const {
        size_t h=v.size();
        for(int n:v) h=(h^unsigned(n))*1099511628211ULL;
        return h;
    }
};

// Native little-endian int32 records: kind, payload length, payload. Only opened in audit runs.
class GroupJournal {
    std::ofstream out;
    void header(int kind,int words) {
        int h[]={kind,words};out.write(reinterpret_cast<const char*>(h),sizeof h);
    }
public:
    void open(const char *path) {
        if(path) {
            static_assert(sizeof(int)==4,"PI-1G journal ABI");
            out.exceptions(std::ios::badbit|std::ios::failbit);
            out.open(path,std::ios::binary|std::ios::app);
        }
    }
    bool enabled() const {return out.is_open();}
    void words(int kind,std::initializer_list<int> fields) {
        if(!enabled())return;
        header(kind,fields.size());out.write(reinterpret_cast<const char*>(fields.begin()),fields.size()*4);
    }
    void mapping(const std::vector<int>& mu) {
        if(!enabled())return;
        header(2,mu.size());out.write(reinterpret_cast<const char*>(mu.data()),mu.size()*4);
    }
    void clause(int member,int selector,int query,const Minisat::vec<Minisat::Lit>& actual) {
        if(!enabled())return;
        header(4,3+actual.size());int h[]={member,selector,query};out.write(reinterpret_cast<const char*>(h),sizeof h);
        static_assert(sizeof(Minisat::Lit)==sizeof(int),"native signed literal ABI");
        if(actual.size())out.write(reinterpret_cast<const char*>(&actual[0]),actual.size()*4);
    }
    void occurrence(int scope,uint64_t id,int member) {
        words(5,{scope,int(uint32_t(id)),int(uint32_t(id>>32)),member});
    }
};

struct OccurrenceBinding { uint64_t occurrence; int member; };
struct InputGroup {
    unsigned id,firstVersion;
    int selector,scope;
    std::vector<unsigned> members;
};
struct GroupPlan {
    std::vector<unsigned> retained;
    std::vector<std::vector<unsigned>> fresh;
    std::vector<unsigned> ordered, representative;
    std::vector<OccurrenceBinding> occurrences;
    unsigned skipped=0;
};

// Integer member IDs refer to complete, immutable canonical vectors. Hash collisions invoke vector equality.
class GroupRegistry {
    std::unordered_map<std::vector<int>,unsigned,VectorHash> dictionary;
    std::vector<const std::vector<int>*> payload;
public:
    static constexpr unsigned width=128;
    std::vector<InputGroup> permanent,queries;
    struct Sources {unsigned version;int scope;std::vector<OccurrenceBinding> occurrences;};
    std::vector<Sources> origins;
    unsigned intern(std::vector<int> c) {
        auto it=dictionary.emplace(std::move(c),payload.size());
        if(it.second)payload.push_back(&it.first->first);
        return it.first->second;
    }
    const std::vector<int>& at(unsigned member) const {return *payload.at(member);}

    template<class Normalize>
    GroupPlan collect(const std::vector<InputOccurrence>& input,Normalize normalize) {
        GroupPlan plan;plan.occurrences.reserve(input.size());
        plan.representative.assign(payload.size(),UINT32_MAX);
        for(unsigned i=0;i<input.size();++i) {
            std::vector<int> c;
            if(!normalize(input[i],c)) {plan.occurrences.push_back({input[i].occurrence,-1});++plan.skipped;continue;}
            unsigned id=intern(std::move(c));
            if(id==plan.representative.size())plan.representative.push_back(UINT32_MAX);
            if(plan.representative[id]==UINT32_MAX){plan.ordered.push_back(id);plan.representative[id]=i;}
            plan.occurrences.push_back({input[i].occurrence,int(id)});
        }
        return plan;
    }
    void partition(GroupPlan& plan) const {
        std::vector<bool> covered(plan.representative.size(),false);
        for(const auto &g:permanent) {
            if(!std::all_of(g.members.begin(),g.members.end(),[&](unsigned id){return plan.representative[id]!=UINT32_MAX;}))continue;
            plan.retained.push_back(g.id);
            for(unsigned id:g.members)covered[id]=true;
        }
        for(unsigned id:plan.ordered)if(!covered[id]){
            if(plan.fresh.empty()||plan.fresh.back().size()==width)plan.fresh.emplace_back();
            plan.fresh.back().push_back(id);
        }
    }
    // Translate the active partition via actual P1 input occurrences, before releasing the old solver.
    std::vector<std::vector<unsigned>> localLayout(const GroupPlan& plan) const {
        std::vector<std::vector<unsigned>> out;
        auto translate=[&](const std::vector<unsigned>& group){
            out.emplace_back();
            for(unsigned id:group)out.back().push_back(plan.representative.at(id));
        };
        for(unsigned g:plan.retained)translate(permanent.at(g).members);
        for(const auto &group:plan.fresh)translate(group);
        return out;
    }
};
}
