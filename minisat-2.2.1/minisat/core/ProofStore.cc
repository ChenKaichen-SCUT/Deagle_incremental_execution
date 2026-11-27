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

std::vector<uint8_t> ProofStore::invalidatedInputs(const std::vector<uint8_t> &matched) const
{
    if(matched.size()!=inputs.size() || offsets.size()!=nodes.size()+1)
        throw std::invalid_argument("D2 invalidation requires the complete input delta and reverse index");
    std::vector<ProofId> seeds;
    for(ProofId id=0;id<nodes.size();++id)
        if(nodes[id].flags && edgeBegin(id)==nodes[id].edge_end)
            seeds.push_back(id); // query-local, opaque theory or missing provenance
    for(size_t i=0;i<inputs.size();++i)
        if(!matched[i] && nodes.at(inputs[i].leaf).kind==BooleanInput)
            seeds.push_back(inputs[i].leaf);
    return invalidate(seeds);
}

namespace
{
static_assert(sizeof(ProofNode)==16 && sizeof(ProofEdge)==8 && sizeof(InputRecord)==16 &&
              sizeof(LearnRecord)==12 && sizeof(int)==4,"unexpected proof layout");
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
    stats[RecorderBytes]=stats[ArenaBytes]+(refs.capacity()+units.capacity()+position.capacity()+
        roots.capacity()+minimized.capacity()+trial.capacity()+scratch.capacity())*sizeof(uint32_t)+
        chain.capacity()*sizeof(ProofEdge);
    uint32_t marker=0x01020304;
    bool ok=fwrite(magic,1,8,output)==8 && fwrite(&marker,4,1,output)==1 &&
        put(output,nodes) && put(output,lits) && put(output,edges) && put(output,inputs) &&
        put(output,learned) && put(output,evicted) && put(output,satisfied_removals) && put(output,residents) && put(output,root_units) && put(output,terminals) &&
        put(output,offsets) && put(output,children);
    stats[WriteSectionsNS]=std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now()-indexed).count();
    ok=ok && fwrite(stats,sizeof(stats),1,output)==1 &&
        fwrite(&exit_code,4,1,output)==1 && fwrite("END2",1,4,output)==4;
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
    if(fread(head,1,8,f)!=8 || memcmp(head,magic,8) || fread(&marker,4,1,f)!=1 || marker!=0x01020304)
        throw std::runtime_error("incompatible D2 archive");
    uint64_t left=uint64_t(size)-12;
    get(f,nodes,left); get(f,lits,left); get(f,edges,left); get(f,inputs,left); get(f,learned,left); get(f,evicted,left); get(f,satisfied_removals,left);
    get(f,residents,left); get(f,root_units,left); get(f,terminals,left); get(f,offsets,left); get(f,children,left);
    int code;
    if(left!=sizeof(stats)+8 || fread(stats,sizeof(stats),1,f)!=1 || fread(&code,4,1,f)!=1 ||
       fread(end,1,4,f)!=4 || memcmp(end,"END2",4)) throw std::runtime_error("incomplete D2 footer");
    return code;
}
