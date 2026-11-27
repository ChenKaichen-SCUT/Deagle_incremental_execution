// Trusted native capture. Durable joins carry dependencies only. Transient Closure
// handles have a disjoint namespace and never enter a SAT reason or the archive.
#ifndef MINISAT_SUPPORT_STORE_H
#define MINISAT_SUPPORT_STORE_H
#include "ProofStore.h"
#include <algorithm>
#include <array>
#include <climits>
#include <chrono>
#include <map>
#include <stdexcept>
namespace Minisat {
struct SupportFormat {
    enum : uint32_t { IndexMask=(1u<<26)-1, FlagShift=26, Temp=1u<<30, Input=1u<<31, End=UINT32_MAX };
    enum Kind : uint32_t { Join=1, Declaration=2, Birth=3, Opaque=4 };
    static uint32_t flags(uint32_t id){return id?((id>>FlagShift)&15):uint32_t(Incomplete);}
    static uint32_t index(uint32_t id){return id&IndexMask;}
    static uint32_t number(size_t x){if(x>IndexMask)throw std::overflow_error("light ID range");return uint32_t(x);}
};
class SupportStore : public SupportFormat {
    struct Meta { uint32_t handle,durable,condition,op,begin,count; };
    struct Cache { uint64_t hash=0; uint32_t handle=0; };
    FILE *file;
    std::vector<uint32_t> buffer,arguments;
    std::map<std::array<int,4>,uint32_t> declarations;
    std::vector<Meta> old,young;
    std::vector<uint32_t> old_parents,young_parents;
    std::vector<Cache> cache;
    uint32_t issued=0,base=0,records=0;
    std::array<uint32_t,16> opaque_ids{};
    void flush(){
        auto start=std::chrono::steady_clock::now();
        if(!buffer.empty() && std::fwrite(buffer.data(),4,buffer.size(),file)!=buffer.size())
            throw std::runtime_error("light archive write");
        io_ns+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();
        buffer.clear();
    }
    Meta &get(uint32_t h){
        if((h&Temp)==0 || (h&Input))throw std::logic_error("invalid transient support");
        const uint32_t n=h^Temp;
        if(n>base)return young.at(size_t(n-base-1));
        auto it=std::lower_bound(old.begin(),old.end(),h,[](const Meta &v,uint32_t k){return v.handle<k;});
        if(it==old.end() || it->handle!=h)throw std::logic_error("stale Closure support handle");
        return *it;
    }
    const uint32_t *parents(const Meta &m) const {
        return (m.handle^Temp)>base?young_parents.data()+m.begin:old_parents.data()+m.begin;
    }
    uint32_t temp(uint32_t durable,uint32_t condition,TheoryOp op,const uint32_t *p,size_t n){
        if(issued==Temp-1)throw std::overflow_error("transient ID exhaustion");
        const uint32_t h=Temp|++issued;
        young.push_back({h,durable,condition,uint32_t(op),uint32_t(young_parents.size()),uint32_t(n)});
        if(n)young_parents.insert(young_parents.end(),p,p+n);
        peak=std::max(peak,uint64_t(old.size()+young.size()));
        return h;
    }
    uint32_t start(Kind kind,uint32_t flags,const uint32_t *p,size_t n){
        if(n>0xffffff)throw std::overflow_error("support node arity");
        if(buffer.size()>=(1u<<16))flush();
        buffer.push_back(uint32_t(n<<8)|(flags<<4)|kind);
        if(n)buffer.insert(buffer.end(),p,p+n);
        direct_edges+=n;
        return number(++records)|(flags<<FlagShift);
    }
public:
    uint32_t occurrences=0,pending_input=0;
    uint64_t io_ns=0;
    uint64_t peak=0,reclaimed=0,sweeps=0,direct_edges=0,cache_hits=0,materialized=0;
    std::vector<int> original;
    explicit SupportStore(FILE *f):file(f),cache(1u<<15){
        if(!f || std::fwrite("DEAGSL1",1,8,f)!=8)throw std::runtime_error("light header");
        buffer.reserve(1u<<16);
    }
    uint32_t input(const vec<Lit> &c,char scope){
        uint32_t flags=scope=='B'?0u:scope=='Q'?uint32_t(Query):uint32_t(Incomplete);
        original.clear();for(int i=0;i<c.size();++i)original.push_back(c[i].x);
        return pending_input=Input|number(++occurrences)|(flags<<FlagShift);
    }
    uint32_t join(const uint32_t *p,size_t n){
        if(!n)return 0;
        if(n==1)return p[0];
        uint32_t f=0;for(size_t j=0;j<n;++j){if(p[j]&Temp)throw std::logic_error("transient parent");f|=flags(p[j]);}
        return start(Join,f,p,n);
    }
    uint32_t capture(ProofKind kind,const int *c,size_t n,const std::vector<ProofEdge> &edges){
        if(kind==TheoryConflict || kind==TheoryReason || kind==TheoryEmpty || kind==DynamicCO){
            auto &id=opaque_ids.at(kind);
            if(!id){id=start(Opaque,Theory,nullptr,0);buffer.push_back(kind);}
            return id;
        }
        arguments.clear();uint32_t f=0;
        for(const auto &e:edges){arguments.push_back(e.parent);f|=flags(e.parent);}
        if(kind!=Learned)return join(arguments.data(),arguments.size());
        if(edges.empty())throw std::logic_error("native birth has no analysis parent");
        uint32_t id=start(Birth,f,arguments.data(),arguments.size());
        buffer.push_back(number(n));for(size_t i=0;i<n;++i)buffer.push_back(c[i]);
        return id;
    }
    uint32_t declaration(TheoryOp op,int a,int b,int c,uint32_t condition){
        const std::array<int,4> key{{int(op),a,b,c}};
        auto inserted=declarations.emplace(key,0);
        if(inserted.second){
            uint32_t d=start(Declaration,CertifiedTheory,nullptr,0);
            for(int v:key)buffer.push_back(uint32_t(v));
            inserted.first->second=temp(d,condition,op,nullptr,0);
        }
        return inserted.first->second;
    }
    template<class Combine> uint32_t rule(TheoryOp op,const uint32_t *p,size_t n,Combine combine){
        if(n==0 || n>6)throw std::logic_error("unsupported native arity");
        uint64_t hash=uint32_t(op);
        for(size_t j=0;j<n;++j){if(!p[j])return 0;hash=(hash^p[j])*UINT64_C(1099511628211);}
        auto &slot=cache[(hash^(hash>>32))&(cache.size()-1)];
        if(slot.handle && slot.hash==hash){
            auto &m=get(slot.handle);
            if(m.op==op && m.count==n && std::equal(p,p+n,parents(m))){++cache_hits;return m.handle;}
        }
        uint32_t cond=0;for(size_t i=0;i<n;++i)cond=combine(cond,get(p[i]).condition);
        uint32_t h=temp(0,cond,op,p,n);slot.hash=hash;slot.handle=h;return h;
    }
    TheoryOp operation(uint32_t h){return TheoryOp(get(h).op);}
    uint32_t condition(uint32_t h){return get(h).condition;}
    uint32_t adopt(uint32_t h){
        // Iterative postorder. Once the native clause discharges its conditions,
        // descendants refer to durable IDs and no longer need these scratch edges.
        std::vector<uint32_t> stack{h};
        while(!stack.empty()){
            Meta &m=get(stack.back());
            if(m.durable){stack.pop_back();continue;}
            const auto *p=parents(m);bool ready=true;
            for(size_t i=0;i<m.count;++i)if(!get(p[i]).durable){stack.push_back(p[i]);ready=false;break;}
            if(!ready)continue;
            arguments.clear();for(size_t i=0;i<m.count;++i)arguments.push_back(get(p[i]).durable);
            m.durable=join(arguments.data(),arguments.size());++materialized;stack.pop_back();
        }
        return get(h).durable;
    }
    bool due()const{return young.size()>=std::max(size_t(16384),old.size()/2);}
    void collect(std::vector<uint32_t> &roots){
        for(const auto &kv:declarations)roots.push_back(kv.second);
        std::sort(roots.begin(),roots.end());roots.erase(std::unique(roots.begin(),roots.end()),roots.end());
        std::vector<uint8_t> yo(young.size()),ol(old.size());
        while(!roots.empty()){
            uint32_t h=roots.back();roots.pop_back();if(!h)continue;
            auto &m=get(h);bool fresh=(h^Temp)>base;
            auto &mark=fresh?yo.at(&m-young.data()):ol.at(&m-old.data());
            if(mark)continue;
            mark=1;
            if(!m.durable && m.count){auto *p=parents(m);roots.insert(roots.end(),p,p+m.count);}
        }
        std::vector<Meta> keep;std::vector<uint32_t> links;
        auto copy=[&](const std::vector<Meta> &v,const std::vector<uint8_t> &mark){
            for(size_t i=0;i<v.size();++i)if(mark[i]){
                Meta m=v[i];auto at=links.size();
                if(m.durable)m.count=0;
                if(m.count){auto *p=parents(m);links.insert(links.end(),p,p+m.count);}
                m.begin=uint32_t(at);keep.push_back(m);
            }
        };
        copy(old,ol);copy(young,yo);reclaimed+=old.size()+young.size()-keep.size();++sweeps;
        old.swap(keep);old_parents.swap(links);young.clear();young_parents.clear();base=issued;
        std::fill(cache.begin(),cache.end(),Cache{});
    }
    bool finish(int result,const std::vector<char> &graph,const uint64_t *discharge){
        buffer.push_back(End);buffer.push_back(occurrences);buffer.push_back(records);flush();
        const uint64_t counters[]={issued,peak,reclaimed,sweeps,direct_edges,materialized,cache_hits,
                                   discharge[0],discharge[1],discharge[2]};
        uint32_t size=uint32_t(graph.size());
        return std::fwrite(counters,sizeof(counters),1,file)==1 && std::fwrite(&size,4,1,file)==1 &&
               (!size || std::fwrite(graph.data(),1,size,file)==size) &&
               std::fwrite(&result,4,1,file)==1 && std::fwrite("ENDL",1,4,file)==4;
    }
};
}
#endif
