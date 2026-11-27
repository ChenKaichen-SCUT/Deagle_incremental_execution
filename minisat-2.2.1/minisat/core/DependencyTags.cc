#include "DependencyTags.h"
#include "Solver.h"
#include <fstream>
#include <limits>
#include <stdexcept>
using namespace Minisat;
bool TheoryTag::observing=false;
uint64_t TheoryTag::live=0,TheoryTag::peak=0;
namespace {
uint32_t narrow(size_t n){
    if(n>=uint32_t(1)<<31)throw std::overflow_error("compact directory exhausted");
    return uint32_t(n);
}
void combine(DenseBits &dest,const DenseBits &src){for(unsigned w=0;w<16;++w)dest[w]|=src[w];}
void seed(DenseBits &dst,uint32_t group){
    auto s=GroupRegistry::slot(group);dst[s/64]|=UINT64_C(1)<<(s%64);
}
}
uint32_t GroupRegistry::registerKey(const std::string &key){
    auto i=ids.find(key);if(i!=ids.end())return i->second;
    auto id=narrow(keys.size());keys.push_back(key);ids.emplace(key,id);return id;
}
DependencyTags::DependencyTags(const std::string &file,const char *sc,dependency_manifest::group_owner_interfacet &src)
    :scope(sc),source(src),path(file){
    if(TheoryTag::observing)throw std::logic_error("one compact writer per model");
    out=std::fopen(path.c_str(),"wbx");
    if(!out)throw std::runtime_error("expected fresh compact archive: "+path);
    writeBytes("D43DNS2",8);put(uint32_t(0x01020304));put(uint32_t(1024));put(uint32_t(1023));
    TheoryTag::observing=true;TheoryTag::peak=TheoryTag::live;
}
DependencyTags::~DependencyTags(){if(out)std::fclose(out);if(scoped)std::fclose(scoped);TheoryTag::observing=false;}
void DependencyTags::writeBytes(const void *p,size_t n){
    if(n && std::fwrite(p,1,n,out)!=n)throw std::runtime_error("compact archive write failed");
}
void DependencyTags::observe(unsigned domain,uint32_t one_based){
    auto &bits=used[domain];uint32_t i=one_based-1;
    bits.at(i/8)|=uint8_t(1u<<(i%8));++observe_calls[domain];
}
TheorySupport DependencyTags::declaration(TheoryOp op,int a,int b,int c){
    Fact key{{int(op),a,b,c}};
    auto it=fact_ids.find(key);uint32_t index;
    if(it==fact_ids.end()){
        index=narrow(facts.size());auto g=groups[1].registerKey(source.theory(op,a,b));
        facts.push_back({key,g});fact_ids.emplace(key,index);
        if(index%8==0)used[1].push_back(0);
    }else index=it->second;
    TheorySupport s;s.tag.raw=index+1;s.tag.op=uint8_t(op);
    s.tag.t.fill(0);seed(s.tag.t,facts[index].group);return s;
}
TheorySupport DependencyTags::infer(TheoryOp op,const TheorySupport *ps,size_t n){
    TheorySupport out;
    bool complete=n!=0 && op>=POEdge && op<=TripletRule;
    out.tag.t.fill(0);
    for(size_t i=0;i<n;++i){
        auto &p=ps[i].tag;
        if(p.raw)observe(1,p.raw);
        if(p.op==255){complete=false;continue;}
        combine(out.tag.t,p.t);++theory_ors;
    }
    if(complete)out.tag.op=uint8_t(op);
    return out;
}
void DependencyTags::boundary(ProofKind k,const TheorySupport &s){
    ++boundaries[k==TheoryReason?0:k==TheoryConflict?1:2];
    opaque();
    if((k==TheoryConflict && s.tag.op==CycleRule) ||
       (k==TheoryReason && (s.tag.op==PreventRF || s.tag.op==TripletRule))){
        pending.flags=DenseT;pending.t=s.tag.t;
    }else ++unknown_boundaries;
}
void DependencyTags::input(const vec<Lit> &c){
    original.clear();for(int i=0;i<c.size();++i)original.push_back(c[i].x);
    uint32_t group=*scope=='B'?groups[0].registerKey(source.boolean(original.data(),original.size())):
                   *scope=='Q'?query_group:unknown_group;
    if(b_groups.size()%8==0)used[0].push_back(0);
    b_groups.push_back(group);pending_leaf=narrow(b_groups.size());
}
void DependencyTags::merge(ClauseTag &out,const ClauseTag &p){
    if(p.flags&DenseB)combine(out.b,p.b);
    if(p.flags&DenseT)combine(out.t,p.t);
    out.flags|=p.flags;++ors;
}
void DependencyTags::consume(uint32_t ref,ClauseTag &out){
    if(!(ref&raw_bit)){
        if(ref)merge(out,pool.at(ref-1));else out.flags|=DenseUnknown;
        return;
    }
    auto leaf=ref&~raw_bit;auto group=b_groups.at(leaf-1);
    if(group==query_group){out.flags|=DenseQ;return;}
    if(group==unknown_group){out.flags|=DenseUnknown;return;}
    observe(0,leaf);seed(out.b,group);out.flags|=DenseB;
}
void DependencyTags::root(int lit,ClauseTag &out){
    auto v=unsigned(lit)/2;auto id=v<unit_refs.size()?unit_refs[v]:0;
    if(!id || units.at(id-1).literal!=lit){out.flags|=DenseUnknown;return;}
    merge(out,units[id-1].support);
}
void DependencyTags::acceptInput(Solver &s,int size){
    pending=ClauseTag::neutral();
    for(int raw:original)if(s.value(Lit{raw})==l_False){
        if(pending_leaf){consume(raw_bit|pending_leaf,pending);pending_leaf=0;}
        root(raw^1,pending);
    }
    if(size<=1 && pending_leaf){consume(raw_bit|pending_leaf,pending);pending_leaf=0;}
}
void DependencyTags::update_peak(){
    peak_slots=std::max(peak_slots,live_slots);
    peak_clause_tags=std::max(peak_clause_tags,live_slots+units.size());
}
void DependencyTags::bind(CRef cr){
    if(cr>=refs.size())refs.resize(size_t(cr)+1,0);
    if(refs[cr])throw std::logic_error("occupied compact CRef");
    if(pending_leaf){
        refs[cr]=raw_bit|pending_leaf;raw_peak=std::max(raw_peak,++raw_live);
    }else{
        uint32_t id;
        if(free_slots.empty()){
            pool.push_back(pending);id=narrow(pool.size());
        }else{
            id=free_slots.back();free_slots.pop_back();pool[id-1]=pending;++recycled;
        }
        refs[cr]=id;++live_slots;update_peak();
    }
}
void DependencyTags::release(uint32_t id){
    if(id&raw_bit){--raw_live;return;}
    if(id){free_slots.push_back(id);--live_slots;}
}
void DependencyTags::forget(CRef cr){
    if(cr<refs.size()){release(refs[cr]);refs[cr]=0;}
}
void DependencyTags::relocated(const ClauseAllocator &ca,uint32_t length){
    std::vector<uint32_t> moved(length,0);
    for(size_t i=0;i<refs.size();++i)if(refs[i]){
        if(ca[i].reloced())moved.at(ca[i].relocation())=refs[i];else release(refs[i]);
    }
    refs.swap(moved);++gc;
}
void DependencyTags::assignment(Solver &s,Lit p,CRef cr){
    bool explicit_reason=explicit_unit;explicit_unit=false;
    if(s.decisionLevel()!=0)return;
    ClauseTag result=ClauseTag::neutral();
    if(cr!=CRef_Undef){
        consume(cr<refs.size()?refs[cr]:0,result);
        const Clause &c=s.ca[cr];
        for(int i=0;i<c.size();++i)if(c[i]!=p)root((~c[i]).x,result);
    }else if(explicit_reason){
        if(pending_leaf)consume(raw_bit|pending_leaf,result);
        else result=pending;
    }else result.flags=DenseUnknown;
    size_t v=var(p);if(v>=unit_refs.size())unit_refs.resize(v+1);
    if(unit_refs[v])units.at(unit_refs[v]-1)={p.x,result};
    else{units.push_back({p.x,result});unit_refs[v]=narrow(units.size());update_peak();}
}
void DependencyTags::rootConflict(Solver &s,CRef cr){
    if(cr==CRef_Undef)return;
    ClauseTag result=ClauseTag::neutral();reason(s,cr,0,result);++root_conflicts;dropTransient();
}
void DependencyTags::reason(Solver &s,CRef cr,int start,ClauseTag &acc){
    consume(cr<refs.size()?refs[cr]:0,acc);
    const Clause &c=s.ca[cr];
    for(int i=start;i<c.size();++i)if(s.level(var(c[i]))==0)root((~c[i]).x,acc);
}
void DependencyTags::visit(Solver &s,Var v){reason(s,s.reason(v),1,trial);}
void DependencyTags::endTrial(bool ok){
    if(ok){merge(analysis,trial);++trial_ok;}else ++trial_failed;
}
void DependencyTags::basic(Solver &s,Var v){reason(s,s.reason(v),1,analysis);}
void DependencyTags::learned(const vec<Lit> &c){
    dropTransient();pending_leaf=0;pending=analysis;++births;
    FILE *destination=out;
    if(pending.flags&(DenseQ|DenseUnknown)){
        put(uint8_t('S'));put(narrow(births));put(pending.flags);++excluded_births;
        if(!dual)return;
        if(!scoped){
            scoped=std::fopen((path+".scoped").c_str(),"wbx");
            if(!scoped || std::fwrite("D43SCP1",1,8,scoped)!=8)throw std::runtime_error("scoped Audit observation open");
        }
        destination=scoped;
    }
    auto bytes=[&](const void *p,size_t n){
        if(std::fwrite(p,1,n,destination)!=n)throw std::runtime_error("compact birth write failed");
    };
    uint8_t mark='L';uint32_t ordinal=narrow(births),length=c.size();
    bytes(&mark,1);bytes(&ordinal,4);bytes(&length,4);bytes(&pending.flags,1);
    static_assert(sizeof(Lit)==sizeof(int32_t),"incompatible literal format");
    if(length)bytes(&c[0],size_t(length)*sizeof(Lit));
    bytes(pending.b.data(),128);bytes(pending.t.data(),128);
}
bool DependencyTags::finish(int status){
    if(!out || (status!=0 && status!=10))return false;
    if(scoped){
        uint32_t count=narrow(excluded_births);
        bool written=std::fwrite("ENDSCOP1",1,8,scoped)==8 && std::fwrite(&count,4,1,scoped)==1;
        bool closed=std::fclose(scoped)==0;scoped=nullptr;
        if(!written || !closed)return false;
    }
    put(uint8_t('D'));
    for(const auto &domain:groups){
        put(narrow(domain.keys.size()));
        for(size_t i=0;i<domain.keys.size();++i){
            const auto &key=domain.keys[i];put(uint16_t(GroupRegistry::slot(uint32_t(i))));
            put(narrow(key.size()));writeBytes(key.data(),key.size());
        }
    }
    put(narrow(b_groups.size()));writeBytes(b_groups.data(),b_groups.size()*sizeof(uint32_t));
    put(narrow(facts.size()));for(auto &f:facts){put(f.key);put(f.group);}
    for(auto &bits:used){put(narrow(bits.size()));writeBytes(bits.data(),bits.size());}
    put(narrow(births));put(int32_t(status));writeBytes("ENDDENSE",8);
    bool ok=!std::ferror(out);ok=(std::fclose(out)==0)&&ok;out=nullptr;
    std::ofstream f(path+".stats");f.exceptions(std::ios::failbit|std::ios::badbit);
    auto stat=[&](const char *n,uint64_t v){f<<n<<'\t'<<v<<'\n';};
    stat("births",births);stat("original_occurrences",b_groups.size());stat("registered_theory",facts.size());
    stat("exportable_births",births-excluded_births);stat("scoped_dispositions",excluded_births);
    stat("legacy_recorders",dual!=nullptr);stat("SupportStore_instances",dual && dual->light());
    stat("proof_nodes",dual?dual->nodes.size()-1:0);stat("proof_parent_edges",dual?dual->edges.size():0);
    stat("duplicate_condition_nodes",dual?dual->conditionNodeCount():0);stat("legacy_quality_enabled",dual && dual->quality);
    stat("B_groups",groups[0].keys.size());stat("T_groups",groups[1].keys.size());
    stat("B_observations",observe_calls[0]);stat("T_observations",observe_calls[1]);
    stat("clause_ORs",ors);stat("theory_ORs",theory_ors);stat("peak_root_tags",units.size());
    stat("peak_raw_clause_refs",raw_peak);stat("peak_active_derived_clause_slots",peak_slots);
    stat("peak_active_clause_plus_root_tags",peak_clause_tags);stat("peak_theory_value_instances",TheoryTag::peak);
    stat("peak_native_graph_edges",peak_graph_edges);stat("peak_persistent_theory_slots",peak_persistent_theory);
    stat("sizeof_theory_tag",sizeof(TheoryTag));stat("sizeof_native_theory_support",sizeof(TheorySupport));
    stat("sizeof_clause_tag",sizeof(ClauseTag));stat("sizeof_root_entry",sizeof(Unit));
    stat("GC",gc);stat("recycled_clause_slots",recycled);stat("root_conflicts",root_conflicts);
    stat("min_success",trial_ok);stat("min_failure",trial_failed);
    stat("theory_reason_clauses",boundaries[0]);stat("theory_conflicts",boundaries[1]);
    stat("other_boundaries",boundaries[2]);stat("opaque_boundaries",unknown_boundaries);
    f.close();return ok;
}

TheorySupport TheoryCapture::decl(TheoryOp op,int a,int b,int c){
    TheorySupport result=dense?dense->declaration(op,a,b,c):TheorySupport{};
    if(audit)result.audit=audit->decl(op,a,b,c);
    return result;
}
TheorySupport TheoryCapture::join(TheoryOp op,int a,int b,int c,const TheorySupport *ps,size_t n){
    TheorySupport result=dense?dense->infer(op,ps,n):TheorySupport{};
    if(audit){
        // Legacy Audit/Light control only. No parent list exists in compact production.
        ProofId ids[8];
        if(n>8)throw std::logic_error("unexpected number of local Closure rule premises");
        for(size_t i=0;i<n;++i)ids[i]=ps[i].audit;
        result.audit=audit->localRule(op,a,b,c,ids,n);
    }
    return result;
}
TheorySupport TheoryCapture::rule(TheoryOp op,int a,int b,int c,std::initializer_list<TheorySupport> xs){
    return join(op,a,b,c,xs.begin(),xs.size());
}
TheorySupport TheoryCapture::rule(TheoryOp op,int a,int b,int c,const std::vector<TheorySupport> &xs){
    return join(op,a,b,c,xs.data(),xs.size());
}
