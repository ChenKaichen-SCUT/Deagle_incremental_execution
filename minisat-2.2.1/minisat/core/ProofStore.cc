#include "ProofStore.h"
#include "Solver.h"
#include <algorithm>
#include <cstring>
#include <chrono>
#include <limits>
#include <memory>
#include <stdexcept>

using namespace Minisat;
namespace
{
uint32_t narrow(size_t n)
{
    if(n >= UINT32_MAX) throw std::overflow_error("D2 proof section exceeds 32-bit index");
    return static_cast<uint32_t>(n);
}
uint32_t leafFlags(ProofKind k)
{
    if(k==Missing || k==UnknownInput) return Incomplete;
    if(k==QueryInput) return Query;
    if(k==TheoryDeclaration) return CertifiedTheory;
    if(k==TheoryReason || k==TheoryConflict || k==DynamicCO || k==TheoryEmpty) return Theory;
    return 0;
}
void uniqueInts(std::vector<int> &v)
{
    std::sort(v.begin(),v.end());
    v.erase(std::unique(v.begin(),v.end()),v.end());
}
}

ProofStore::ProofStore() : scope(nullptr)
{
    nodes.push_back({0,0,Missing,Incomplete});
}

ProofStore::ProofStore(const std::string &path, const char *origin) : ProofStore()
{
    scope=origin;
    output=std::fopen(path.c_str(),"wbx");
    if(!output) throw std::runtime_error("D2 requires a new writable proof file: "+path);
}

ProofStore::~ProofStore() { if(output) std::fclose(output); }

ProofId ProofStore::append(ProofKind kind, const int *c, size_t size, const std::vector<ProofEdge> &parents)
{
    ProofId id=narrow(nodes.size());
    uint32_t flags=leafFlags(kind);
    for(const auto &e:parents)
    {
        if(e.parent>=id) throw std::logic_error("forward D2 proof reference");
        flags |= nodes[e.parent].flags;
    }
    auto le=narrow(lits.size()+size), ee=narrow(edges.size()+parents.size());
    if(size) lits.insert(lits.end(),c,c+size);
    edges.insert(edges.end(),parents.begin(),parents.end());
    nodes.push_back({le,ee,kind,flags});
    return id;
}

namespace
{
// The table stores indices into the immutable records. Hash collisions always
// compare the opcode, endpoint payload and the complete ordered parent sequence.
uint64_t mixWord(uint64_t h,uint32_t word)
{
    h ^= word;
    h *= UINT64_C(1099511628211);
    return h ^ (h >> 32);
}
uint64_t payloadHash(TheoryOp op,int a,int b,int c)
{
    return mixWord(mixWord(mixWord(mixWord(UINT64_C(14695981039346656037),op),a),b),c);
}
}
void ProofStore::growTheoryIndex()
{
    std::vector<uint32_t> slots(theory_slots.empty()?64:2*theory_slots.size());
    const size_t mask=slots.size()-1;
    for(size_t i=0;i<theory_records.size();++i)
    {
        const auto &r=theory_records[i];
        uint64_t h=payloadHash(r.op,r.a,r.b,r.c);
        for(auto j=edgeBegin(r.id);j<nodes[r.id].edge_end;++j) h=mixWord(h,edges[j].parent);
        size_t pos=h&mask;
        while(slots[pos]) pos=(pos+1)&mask;
        slots[pos]=narrow(i+1);
    }
    theory_slots.swap(slots);
}
uint32_t ProofStore::internCondition(uint32_t a,uint32_t b)
{
    if(b!=UINT32_MAX)
    {
        if(!a || a==b) return b;
        if(!b) return a;
        if(a>b) std::swap(a,b);
    }
    auto hash=[](uint32_t x,uint32_t y){return mixWord(mixWord(UINT64_C(14695981039346656037),x),y);};
    if(conditions.size()>condition_slots.size()*3/4)
    {
        std::vector<uint32_t> slots(condition_slots.empty()?64:condition_slots.size()*2);
        for(size_t i=1;i<conditions.size();++i)
        {
            const auto &s=conditions[i];
            size_t pos=hash(s.a,s.b)&(slots.size()-1);
            while(slots[pos]) pos=(pos+1)&(slots.size()-1);
            slots[pos]=narrow(i);
        }
        condition_slots.swap(slots);
    }
    const size_t mask=condition_slots.size()-1;
    size_t pos=hash(a,b)&mask;
    while(uint32_t i=condition_slots[pos])
    {
        if(conditions[i].a==a && conditions[i].b==b) return i;
        pos=(pos+1)&mask;
    }
    auto id=narrow(conditions.size());
    conditions.push_back({a,b});
    return condition_slots[pos]=id;
}
ProofId ProofStore::internTheory(ProofKind kind,TheoryOp op,int a,int b,int c,const ProofId *parents,size_t count)
{
    if(theory_records.size()+1 > theory_slots.size()*3/4) growTheoryIndex();
    uint64_t h=payloadHash(op,a,b,c);
    if(kind==TheoryInference && (op<=BlockDecl || op>=TripletRule || !count)) return 0;
    for(size_t i=0;i<count;++i)
    {
        auto id=parents[i];
        if(!id || (nodes.at(id).flags & (Incomplete|Theory|Query))) return 0;
        h=mixWord(h,id);
    }
    const size_t mask=theory_slots.size()-1;
    size_t pos=h&mask;
    while(theory_slots[pos])
    {
        const auto &r=theory_records[theory_slots[pos]-1];
        if(r.op==op && r.a==a && r.b==b && r.c==c && nodes[r.id].kind==kind)
        {
            const auto j=edgeBegin(r.id);
            if(nodes[r.id].edge_end-j==count)
            {
                size_t i=0;
                while(i<count && parents[i]==edges[j+i].parent) ++i;
                if(i==count) return r.id;
            }
        }
        pos=(pos+1)&mask;
    }
    theory_parents.clear();
    for(size_t i=0;i<count;++i) theory_parents.push_back({parents[i],-1});
    const auto id=append(kind,nullptr,0,theory_parents);
    uint32_t condition=0;
    if((op==RFDecl || op==GuardDecl) && c>=0) condition=internCondition(uint32_t(c),UINT32_MAX);
    for(size_t i=0;i<count;++i) condition=internCondition(condition,condition_by_proof.at(parents[i]));
    condition_by_proof.resize(size_t(id)+1,0);
    condition_by_proof[id]=condition;
    theory_records.push_back({id,op,a,b,c});
    theory_slots[pos]=narrow(theory_records.size());
    return id;
}
ProofId ProofStore::decl(TheoryOp op,int a,int b,int c)
{
    if(op>BlockDecl) throw std::logic_error("not a theory declaration");
    return internTheory(TheoryDeclaration,op,a,b,c,nullptr,0);
}
ProofId ProofStore::rule(TheoryOp op,int a,int b,int c,const std::vector<ProofId> &parents)
{
    return internTheory(TheoryInference,op,a,b,c,parents.data(),parents.size());
}
ProofId ProofStore::rule(TheoryOp op,int a,int b,int c,std::initializer_list<ProofId> parents)
{
    return internTheory(TheoryInference,op,a,b,c,parents.begin(),parents.size());
}
size_t ProofStore::theoryIndex(ProofId id) const
{
    auto it=std::lower_bound(theory_records.begin(),theory_records.end(),id,
                             [](const TheoryRecord &r,ProofId key){return r.id<key;});
    if(it==theory_records.end() || it->id!=id)
        throw std::logic_error("missing theory payload");
    return size_t(it-theory_records.begin());
}
ProofId ProofStore::lemma(ProofKind boundary,const vec<Lit> &actual,ProofId reason)
{
    if(!reason || nodes.at(reason).kind!=TheoryInference)
    {
        ++discharge_stats[0];
        return opaque(boundary,actual);
    }
    const size_t index=theoryIndex(reason);
    const auto op=theory_records[index].op;
    if(!((op==CycleRule && boundary==TheoryConflict) ||
         (op==PreventRF && boundary==TheoryReason)))
    {
        ++discharge_stats[0];
        return opaque(boundary,actual);
    }
    const auto support=condition_by_proof.at(reason);
    discharge_cache.resize(conditions.size(),0);
    actual_condition.clear();
    for(int i=0;i<actual.size();++i) actual_condition.push_back(actual[i].x);
    uniqueInts(actual_condition);
    expected_condition.clear();
    if(ProofId cached=discharge_cache[support])
        expected_condition.assign(lits.begin()+litBegin(cached),lits.begin()+nodes[cached].lit_end);
    else
    {
        // Discharge branch premises exactly once for this immutable rule result.
        // Share the verified native clause as a cache. No ancestor list is retained.
        theory_marks.resize(conditions.size(),0);
        const auto stamp=narrow(nodes.size());
        condition_stack.assign(1,support);
        while(!condition_stack.empty())
        {
            auto id=condition_stack.back(); condition_stack.pop_back();
            if(!id || theory_marks[id]==stamp) continue;
            theory_marks[id]=stamp;
            const auto &s=conditions[id];
            if(s.b==UINT32_MAX) expected_condition.push_back(int(s.a)^1);
            else { condition_stack.push_back(s.a); condition_stack.push_back(s.b); }
        }
    }
    uniqueInts(expected_condition);
    if(expected_condition!=actual_condition)
    {
        ++discharge_stats[1];
        return opaque(boundary,actual);
    }
    ++discharge_stats[2];
    ProofId id=clause(TheoryLemma,actual,{{reason,-1}});
    discharge_cache[support]=id;
    return id;
}

ProofId ProofStore::root(int assigned) const
{
    ProofId id=units.at(unsigned(assigned)/2);
    return id && nodes[id].lit_end==litBegin(id)+1 && lits[litBegin(id)]==assigned ? id : 0;
}

void ProofStore::input(const vec<Lit> &c)
{
    auto id=clause(*scope=='B' ? BooleanInput : *scope=='Q' ? QueryInput : UnknownInput,c,{});
    inputs.push_back({id,0,Accepted,-1});
}

void ProofStore::skipInput(InputAction action,int lit)
{
    auto &in=inputs.back();
    in.action=action;
    in.witness=lit;
    if(action==Satisfied) in.result=root(lit);
}

ProofId ProofStore::acceptInput(Solver &s,const vec<Lit> &c)
{
    auto &in=inputs.back();
    roots.clear();
    for(auto i=litBegin(in.leaf);i<nodes[in.leaf].lit_end;++i)
        if(s.value(Lit{lits[i]})==l_False) roots.push_back(lits[i]);
    in.result=in.leaf;
    if(!roots.empty())
    {
        chain.assign(1,{in.leaf,-1});
        appendRoots();
        in.result=clause(Shortened,c,chain);
    }
    if(c.size()==0) terminals.push_back(in.result);
    return in.result;
}

void ProofStore::bind(CRef cr,ProofId id)
{
    if(cr>=refs.size()) refs.resize(size_t(cr)+1,0);
    refs[cr]=id;
}

void ProofStore::removedSatisfied(Solver &s,CRef cr)
{
    const Clause &c=s.ca[cr];
    for(int i=0;i<c.size();++i)
        if(s.value(c[i])==l_True)
        {
            satisfied_removals.push_back({ref(cr),root(c[i].x),c[i].x});
            return;
        }
    throw std::logic_error("satisfied deletion lacks a true literal");
}

void ProofStore::forget(CRef cr)
{
    auto id=ref(cr);
    if(id && nodes[id].kind==Learned) evicted.push_back({id,narrow(nodes.size()-1)});
    if(cr<refs.size()) refs[cr]=0;
    ++stats[Removals];
}

void ProofStore::relocated(const ClauseAllocator &from,uint32_t new_size)
{
    std::vector<ProofId> moved(new_size);
    for(size_t i=0;i<refs.size();++i)
        if(refs[i] && from[i].reloced())
        {
            auto dest=from[i].relocation();
            moved.at(dest)=refs[i];
            if(dest!=i)
            {
                ++stats[ChangedRefs];
                stats[ChangedLearnRefs]+=nodes[refs[i]].kind==Learned;
            }
        }
    refs.swap(moved);
    ++stats[Collections];
}

void ProofStore::appendRoots()
{
    uniqueInts(roots);
    for(int false_lit:roots)
        chain.push_back({root(false_lit^1),false_lit^1});
}

void ProofStore::assignment(Solver &s,Lit p,CRef cr)
{
    ProofId explicit_id=next_unit;
    AssignmentSource source=cr==CRef_Undef ? next_source : ClauseReason;
    next_unit=0;
    next_source=Unexplained;
    position.at(var(p))=s.trail.size();
    ++stats[ByClause+source];
    if(s.decisionLevel()!=0) return;
    ProofId id=explicit_id;
    if(cr!=CRef_Undef)
    {
        const Clause &c=s.ca[cr];
        std::vector<ProofEdge> why{{ref(cr),-1}};
        for(int i=0;i<c.size();++i)
            if(c[i]!=p)
                why.push_back({root((~c[i]).x),(~c[i]).x});
        id=append(RootUnit,&p.x,1,why);
    }
    units[var(p)]=id;
}

void ProofStore::rootConflict(Solver &s,CRef cr)
{
    if(cr==CRef_Undef) return;
    const Clause &c=s.ca[cr];
    chain.assign(1,{ref(cr),-1});
    roots.clear();
    for(int i=0;i<c.size();++i) roots.push_back(c[i].x);
    appendRoots();
    terminals.push_back(append(RootConflict,nullptr,0,chain));
}

void ProofStore::theoryEmpty() { terminals.push_back(append(TheoryEmpty,nullptr,0,{})); }

void ProofStore::addReason(Solver &s,CRef cr,Lit pivot)
{
    chain.push_back({ref(cr),pivot==lit_Undef ? -1 : pivot.x});
    const Clause &c=s.ca[cr];
    for(int i=pivot==lit_Undef ? 0 : 1;i<c.size();++i)
        if(s.level(var(c[i]))==0) roots.push_back(c[i].x);
}

void ProofStore::endTrial(bool success)
{
    ++stats[success ? MinSuccess : MinFailure];
    if(success) minimized.insert(minimized.end(),trial.begin(),trial.end());
}

void ProofStore::finishAnalysis(Solver &s,const vec<Lit> &result)
{
    const uint32_t uip=narrow(chain.size());
    // Resolve later assignments first. Each successful DFS supplies its real visited
    // reasons; a shared visited node from a previous successful DFS is resolved once.
    std::sort(minimized.begin(),minimized.end(),[&](int a,int b){ return position[a]>position[b]; });
    minimized.erase(std::unique(minimized.begin(),minimized.end()),minimized.end());
    for(Var v:minimized) addReason(s,s.reason(v),s.trail[position[v]]);
    appendRoots();
    pending=clause(Learned,result,chain);
    learned.push_back({pending,uip,narrow(minimized.size())});
}

void ProofStore::snapshot(const vec<CRef> &db)
{
    residents.clear();
    for(int i=0;i<db.size();++i) residents.push_back(ref(db[i]));
    root_units.clear();
    for(ProofId id:units) if(id) root_units.push_back(id);
}

void ProofStore::buildReverse()
{
    offsets.assign(nodes.size()+1,0);
    for(const auto &e:edges) ++offsets[e.parent+1];
    for(size_t i=1;i<offsets.size();++i) offsets[i]+=offsets[i-1];
    std::vector<uint32_t> cursor=offsets;
    children.resize(edges.size());
    for(ProofId id=1;id<nodes.size();++id)
        for(auto i=edgeBegin(id);i<nodes[id].edge_end;++i)
            children[cursor[edges[i].parent]++]=id;
}

std::vector<uint8_t> ProofStore::invalidate(const std::vector<ProofId> &seeds) const
{
    std::vector<uint8_t> dead(nodes.size());
    std::vector<ProofId> queue;
    for(auto id:seeds)
        if(!dead.at(id)) { dead[id]=1; queue.push_back(id); }
    for(size_t i=0;i<queue.size();++i)
        for(auto j=offsets.at(queue[i]);j<offsets.at(queue[i]+1);++j)
        {
            auto id=children[j];
            if(!dead[id]) { dead[id]=1; queue.push_back(id); }
        }
    return dead;
}

std::vector<uint8_t> ProofStore::invalidatedInputs(const std::vector<uint8_t> &matched,
                                                  const std::vector<uint8_t> &declaration_matched) const
{
    if(matched.size()!=inputs.size() || offsets.size()!=nodes.size()+1)
        throw std::invalid_argument("D2 invalidation requires the complete input delta and reverse index");
    std::vector<ProofId> seeds;
    for(ProofId id=0;id<nodes.size();++id)
        if((nodes[id].flags & (Theory|Query|Incomplete)) && edgeBegin(id)==nodes[id].edge_end)
            seeds.push_back(id); // query-local, opaque theory or missing provenance
    for(size_t i=0;i<inputs.size();++i)
        if(!matched[i] && nodes.at(inputs[i].leaf).kind==BooleanInput)
            seeds.push_back(inputs[i].leaf);
    size_t d=0;
    for(const auto &r:theory_records)
        if(nodes.at(r.id).kind==TheoryDeclaration && !declaration_matched.at(d++))
            seeds.push_back(r.id);
    if(d!=declaration_matched.size()) throw std::invalid_argument("D3 theory delta length");
    return invalidate(seeds);
}

namespace
{
static_assert(sizeof(ProofNode)==16 && sizeof(ProofEdge)==8 && sizeof(InputRecord)==16 &&
              sizeof(LearnRecord)==12 && sizeof(TheoryRecord)==20 && sizeof(int)==4,"unexpected proof layout");
const char magic[8]={'D','E','A','G','D','2',1,0};
template<typename T> bool put(FILE *f,const std::vector<T> &v)
{
    uint32_t n=narrow(v.size());
    return fwrite(&n,4,1,f)==1 && (!n || fwrite(v.data(),sizeof(T),n,f)==n);
}
template<typename T> void get(FILE *f,std::vector<T> &v,uint64_t &left)
{
    uint32_t n=0;
    if(left<4 || fread(&n,4,1,f)!=1 || uint64_t(n)*sizeof(T)>left-4)
        throw std::runtime_error("invalid D2 section length");
    left-=4+uint64_t(n)*sizeof(T);
    v.resize(n);
    if(n && fread(v.data(),sizeof(T),n,f)!=n) throw std::runtime_error("truncated D2 section");
}
}

bool ProofStore::write(int exit_code)
{
    if(!output) return false;
    const auto start=std::chrono::steady_clock::now();
    buildReverse();
    const auto indexed=std::chrono::steady_clock::now();
    stats[ReverseNS]=std::chrono::duration_cast<std::chrono::nanoseconds>(indexed-start).count();
    stats[ArenaBytes]=nodes.capacity()*sizeof(ProofNode)+edges.capacity()*sizeof(ProofEdge)+
        inputs.capacity()*sizeof(InputRecord)+learned.capacity()*sizeof(LearnRecord)+
        evicted.capacity()*sizeof(EvictedLearn)+satisfied_removals.capacity()*sizeof(SatisfiedRemoval)+
        (lits.capacity()+residents.capacity()+root_units.capacity()+terminals.capacity()+
         offsets.capacity()+children.capacity())*sizeof(uint32_t);
    stats[ArenaBytes]+=theory_records.capacity()*sizeof(TheoryRecord)+graph_receipt.capacity();
    const auto theory_scratch=theory_slots.capacity()+condition_slots.capacity()+condition_by_proof.capacity()+
        2*conditions.capacity()+theory_marks.capacity()+discharge_cache.capacity()+
        expected_condition.capacity()+actual_condition.capacity()+condition_stack.capacity();
    stats[RecorderBytes]=stats[ArenaBytes]+(theory_scratch+refs.capacity()+units.capacity()+position.capacity()+
        roots.capacity()+minimized.capacity()+trial.capacity()+scratch.capacity())*sizeof(uint32_t)+
        (chain.capacity()+theory_parents.capacity())*sizeof(ProofEdge);
    uint32_t marker=0x01020304;
    char format[8]; std::memcpy(format,magic,8);
    if(d3) format[5]='3';
    bool ok=fwrite(format,1,8,output)==8 && fwrite(&marker,4,1,output)==1 &&
        put(output,nodes) && put(output,lits) && put(output,edges) && put(output,inputs) &&
        put(output,learned) && put(output,evicted) && put(output,satisfied_removals) && put(output,residents) && put(output,root_units) && put(output,terminals) &&
        put(output,offsets) && put(output,children);
    if(d3) ok=ok && put(output,theory_records) && put(output,graph_receipt) &&
                  fwrite(discharge_stats,sizeof(discharge_stats),1,output)==1;
    stats[WriteSectionsNS]=std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now()-indexed).count();
    ok=ok && fwrite(stats,sizeof(stats),1,output)==1 &&
        fwrite(&exit_code,4,1,output)==1 && fwrite(d3?"END3":"END2",1,4,output)==4;
    ok=std::fclose(output)==0 && ok;
    output=nullptr;
    return ok;
}

int ProofStore::read(const std::string &path)
{
    std::unique_ptr<FILE,decltype(&std::fclose)> owner(std::fopen(path.c_str(),"rb"),std::fclose);
    FILE *f=owner.get();
    if(!f || fseek(f,0,SEEK_END)!=0) throw std::runtime_error("cannot open D2 file");
    long size=ftell(f);
    if(size<20) throw std::runtime_error("incomplete D2 header");
    rewind(f);
    char head[8],end[4];
    uint32_t marker;
    if(fread(head,1,8,f)!=8) throw std::runtime_error("truncated archive header");
    d3=head[5]=='3';
    if(d3) head[5]='2';
    if(memcmp(head,magic,8) || fread(&marker,4,1,f)!=1 || marker!=0x01020304)
        throw std::runtime_error("incompatible D2 archive");
    uint64_t left=uint64_t(size)-12;
    get(f,nodes,left); get(f,lits,left); get(f,edges,left); get(f,inputs,left); get(f,learned,left); get(f,evicted,left); get(f,satisfied_removals,left);
    get(f,residents,left); get(f,root_units,left); get(f,terminals,left); get(f,offsets,left); get(f,children,left);
    if(d3)
    {
        get(f,theory_records,left);
        get(f,graph_receipt,left);
        if(left<sizeof(discharge_stats) || fread(discharge_stats,sizeof(discharge_stats),1,f)!=1)
            throw std::runtime_error("missing D3 discharge counters");
        left-=sizeof(discharge_stats);
    }
    int code;
    if(left!=sizeof(stats)+8 || fread(stats,sizeof(stats),1,f)!=1 || fread(&code,4,1,f)!=1 ||
       fread(end,1,4,f)!=4 || memcmp(end,d3?"END3":"END2",4)) throw std::runtime_error("incomplete proof footer");
    return code;
}
