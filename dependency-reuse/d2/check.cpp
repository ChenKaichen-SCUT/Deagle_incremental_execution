// Independent replay of the signed resolution chain. No solver or propagation oracle.
#include "minisat/core/ProofStore.h"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_set>

using namespace Minisat;
using ClauseData=std::vector<int>;
using Bag=std::map<ClauseData,unsigned>;
namespace
{
enum Cause { Changed=1, AuxGap=2, OtherGap=4, QueryScope=8, OpaqueTheory=16, MissingSource=32 };
void require(bool ok,const std::string &msg) { if(!ok) throw std::runtime_error(msg); }
ClauseData content(const ProofStore &g,ProofId id)
{
    return {g.lits.begin()+g.litBegin(id),g.lits.begin()+g.nodes.at(id).lit_end};
}
ClauseData normalized(ClauseData c)
{
    std::sort(c.begin(),c.end());
    c.erase(std::unique(c.begin(),c.end()),c.end());
    return c;
}
bool theory(uint32_t kind) { return kind==TheoryReason || kind==TheoryConflict || kind==DynamicCO || kind==TheoryEmpty; }
uint32_t origin(uint32_t kind)
{
    if(theory(kind)) return Theory;
    if(kind==QueryInput) return Query;
    return kind==Missing || kind==UnknownInput ? uint32_t(Incomplete) : 0u;
}
void verifyGraph(const ProofStore &g,std::map<std::string,uint64_t> &metrics)
{
    require(!g.nodes.empty() && g.nodes[0].kind==Missing && g.nodes[0].flags==Incomplete &&
            !g.nodes[0].edge_end && !g.nodes[0].lit_end,"invalid UNKNOWN sentinel");
    require(g.nodes.back().edge_end==g.edges.size() && g.nodes.back().lit_end==g.lits.size(),"section boundaries");
    require(g.offsets.size()==g.nodes.size()+1 && !g.offsets.front() &&
            g.offsets.back()==g.children.size() && g.children.size()==g.edges.size(),"reverse size");
    auto cursor=g.offsets;
    for(ProofId id=1;id<g.nodes.size();++id)
    {
        auto &n=g.nodes[id];
        auto begin=g.edgeBegin(id),first=g.litBegin(id);
        require(begin<=n.edge_end && n.edge_end<=g.edges.size() && first<=n.lit_end && n.lit_end<=g.lits.size() &&
                n.kind>Missing && n.kind<=TheoryEmpty,"invalid node "+std::to_string(id));
        bool derived=n.kind==RootUnit || n.kind==Learned || n.kind==Shortened || n.kind==RootConflict;
        require(derived==(begin<n.edge_end),"derivation arity");
        uint32_t flags=origin(n.kind);
        bool missing=false;
        for(auto j=begin;j<n.edge_end;++j)
        {
            auto e=g.edges[j];
            require(e.parent<id,"forward edge");
            require(g.children.at(cursor[e.parent]++)==id,"reverse consumer differs");
            require(j==begin ? e.pivot==-1 : e.pivot>=0,"pivot encoding");
            flags|=g.nodes[e.parent].flags;
            missing |= e.parent==0;
        }
        require(flags==n.flags,"provenance flags disagree at "+std::to_string(id));
        if(!derived) continue;
        if(missing) { ++metrics["uncheckable_local_steps"]; continue; }
        std::unordered_set<int> current;
        for(auto j=begin;j<n.edge_end;++j)
        {
            auto e=g.edges[j];
            const int p=e.pivot;
            if(j!=begin && !current.erase(p^1))
                throw std::runtime_error("resolvent missing pivot at "+std::to_string(id)+"/"+std::to_string(j-begin)+" pivot "+std::to_string(p));
            bool found=false;
            for(auto k=g.litBegin(e.parent);k<g.nodes[e.parent].lit_end;++k)
            {
                if(j!=begin && g.lits[k]==p) found=true;
                else current.insert(g.lits[k]);
            }
            if(j!=begin) require(found,"reason missing signed pivot at "+std::to_string(id));
        }
        for(auto k=first;k<n.lit_end;++k) require(current.count(g.lits[k])!=0,"extra conclusion literal at "+std::to_string(id));
        ClauseData expect=normalized(content(g,id));
        require(current.size()==expect.size(),"different conclusion at "+std::to_string(id)+" kind "+std::to_string(n.kind));
        ++metrics["checked_derivations"];
        metrics["checked_resolutions"]+=n.edge_end-begin-1;
    }
    for(size_t i=0;i<g.nodes.size();++i) require(cursor[i]==g.offsets[i+1],"reverse offsets");
    for(const auto &r:g.satisfied_removals)
    {
        auto c=content(g,r.clause);
        require(std::find(c.begin(),c.end(),r.literal)!=c.end() &&
                content(g,r.unit)==ClauseData{r.literal},"satisfied deletion lacks its unit justification");
    }
    metrics["satisfied_database_deletions"]=g.satisfied_removals.size();
    for(auto id:g.terminals) require(id && content(g,id).empty(),"nonempty terminal proof");
}

void checkNative(const ProofStore &g,const std::string &path)
{
    std::ifstream f(path);
    require(bool(f),"native oracle unavailable");
    std::string line;
    size_t born=0;
    bool ended=false;
    Bag resident;
    std::multiset<int> roots;
    for(auto id:g.residents) ++resident[normalized(content(g,id))];
    for(auto id:g.root_units)
    {
        auto c=content(g,id);
        require(c.size()==1,"root result is not a unit");
        roots.insert(c[0]);
    }
    while(std::getline(f,line))
    {
        require(!ended,"oracle trailing records");
        if(line=="END") { ended=true; continue; }
        std::istringstream fields(line);
        char kind; int lit; ClauseData c;
        fields>>kind;
        while(fields>>lit) c.push_back(lit);
        if(kind=='L')
        {
            require(born<g.learned.size() && c==content(g,g.learned[born].id),"actual native birth "+std::to_string(born+1));
            ++born;
        }
        else if(kind=='R')
        {
            auto i=resident.find(normalized(c));
            require(i!=resident.end() && i->second,"unaccounted native resident");
            if(!--i->second) resident.erase(i);
        }
        else if(kind=='U')
        {
            require(c.size()==1 && roots.count(c[0]),"unaccounted root assignment");
            roots.erase(roots.find(c[0]));
        }
        else throw std::runtime_error("unexpected native audit tag");
    }
    require(ended && born==g.learned.size() && resident.empty() && roots.empty(),"native snapshot incomplete");
}

struct Analysis
{
    ProofStore &g;
    std::vector<uint8_t> causes,reachable,resident,active_unit,input_matched;
    std::vector<ProofId> seeds;
    std::map<std::string,uint64_t> metrics;
    std::map<unsigned,int> mapped;
    explicit Analysis(ProofStore &store):g(store),causes(g.nodes.size()),reachable(g.nodes.size()),
        resident(g.nodes.size()),active_unit(g.nodes.size()) {}

    void inputs(const std::string &path)
    {
        std::ifstream f(path); std::string line;
        for(const auto &record:g.inputs)
        {
            require(bool(std::getline(f,line)),"missing input");
            std::istringstream fields(line);
            char scope; unsigned change; int lit; ClauseData actual;
            require(bool(fields>>scope>>change) && change<=255 && !(change&56),"input delta record");
            while(fields>>lit) actual.push_back(lit);
            auto id=record.leaf;
            uint32_t kind=scope=='B' ? BooleanInput : scope=='Q' ? QueryInput : UnknownInput;
            require(g.nodes.at(id).kind==kind && content(g,id)==actual,"input occurrence/scope mismatch at node "+std::to_string(id));
            input_matched.push_back(change==0);
            causes[id]=uint8_t(change | (scope=='Q' ? QueryScope : scope=='B' ? 0 : MissingSource));
            if(record.action==Satisfied || record.action==Tautology)
            {
                auto contains=[&](int l){return std::find(actual.begin(),actual.end(),l)!=actual.end();};
                require(contains(record.witness),"discard witness not in input");
                if(record.action==Tautology) require(contains(record.witness^1),"false tautology");
                else require(record.result && content(g,record.result)==ClauseData{record.witness},"unproved satisfied input");
            }
            else if(record.action==Accepted)
                require(record.result==id || (g.nodes.at(record.result).kind==Shortened &&
                        g.edges.at(g.edgeBegin(record.result)).parent==id),"wrong shortened input");
            else require(record.action==AlreadyInconsistent && !record.result,"bad input action");
            ++metrics["input_action_"+std::to_string(record.action)];
        }
        require(!std::getline(f,line),"extra input occurrences");
    }
    void classify(const std::string &dir)
    {
        for(const char *name:{"births","resident_cdcl","unit_births","active_learned_units",
            "complete_permanent_boolean","boolean_including_query","theory_any","incomplete_any",
            "query_any","theory_direct","theory_indirect_only","uses_prior_learned_directly",
            "minimized_births","old_proof_survives","survives_and_translates","uncheckable_local_steps",
            "used_parent_edges_to_evicted_learned"})
            metrics.emplace(name,0);
        for(auto id:g.residents) { require(id && !resident.at(id),"duplicate resident"); resident[id]=1; }
        for(auto id:g.root_units) active_unit.at(id)=1;
        std::set<ProofId> deleted;
        for(auto e:g.evicted)
        {
            require(g.nodes.at(e.id).kind==Learned && e.last_node>=e.id && e.last_node<g.nodes.size() &&
                    !resident[e.id] && deleted.insert(e.id).second,"invalid eviction");
        }
        std::vector<uint8_t> through_learn(g.nodes.size());
        std::map<ProofId,ProofId> eviction_time;
        for(auto e:g.evicted) eviction_time[e.id]=e.last_node;
        std::vector<ProofId> oldest_eviction(g.evicted.empty()?0:g.nodes.size(),UINT32_MAX);
        for(ProofId id=0;id<g.nodes.size();++id)
        {
            if(theory(g.nodes[id].kind)) causes[id]|=OpaqueTheory;
            if(g.nodes[id].kind==Missing || g.nodes[id].kind==UnknownInput) causes[id]|=MissingSource;
            if(causes[id]) seeds.push_back(id);
            for(auto j=g.edgeBegin(id);j<g.nodes[id].edge_end;++j)
            {
                auto p=g.edges[j].parent;
                causes[id]|=causes[p];
                through_learn[id]|=through_learn[p] || (g.nodes[p].kind==Learned && (causes[p]&7));
                if(!oldest_eviction.empty())
                {
                    auto e=eviction_time.find(p);
                    oldest_eviction[id]=std::min(oldest_eviction[id],oldest_eviction[p]);
                    if(e!=eviction_time.end()) oldest_eviction[id]=std::min(oldest_eviction[id],e->second);
                }
            }
        }
        auto dead=g.invalidatedInputs(input_matched);
        for(size_t i=0;i<dead.size();++i) require(bool(dead[i])==bool(causes[i]),"reverse invalidation differs");
        std::ofstream catalog(dir+"/learned.tsv"),leaves(dir+"/used.tsv");
        catalog.exceptions(std::ios::badbit|std::ios::failbit);
        leaves.exceptions(std::ios::badbit|std::ios::failbit);
        std::ofstream survivors(dir+"/survivors.tsv");
        survivors.exceptions(std::ios::badbit|std::ios::failbit);
        std::vector<uint8_t> born(g.nodes.size());
        for(const auto &l:g.learned)
        {
            auto id=l.id; const auto &n=g.nodes.at(id);
            require(n.kind==Learned && !born[id] && l.uip_edges && l.uip_edges+l.min_edges<=n.edge_end-g.edgeBegin(id),"birth boundaries");
            born[id]=1;
            bool direct=false,has_prior=false,can_map=true;
            for(auto i=g.edgeBegin(id);i<n.edge_end;++i)
            {
                auto k=g.nodes[g.edges[i].parent].kind;
                direct |= theory(k); has_prior |= k==Learned;
            }
            for(auto i=g.litBegin(id);i<n.lit_end;++i) can_map &= mapped.count(unsigned(g.lits[i])/2)!=0;
            unsigned size=n.lit_end-g.litBegin(id);
            if(size!=1) require(bool(resident[id])!=bool(deleted.count(id)),"unaccounted learned clause");
            reachable[id]=1 | (n.flags==0 ? 2 : 0);
            catalog<<id<<'\t'<<size<<'\t'<<n.flags<<'\t'<<direct<<'\t'<<int(causes[id])<<'\t'<<int(resident[id])<<'\t'
                   <<int(active_unit[id])<<'\t'<<!dead[id]<<'\t'<<can_map<<'\t'<<l.uip_edges<<'\t'<<l.min_edges<<'\n';
            if(!dead[id] && can_map)
            {
                survivors<<id;
                for(auto i=g.litBegin(id);i<n.lit_end;++i)
                    survivors<<'\t'<<(mapped.at(unsigned(g.lits[i])/2)^(g.lits[i]&1));
                survivors<<'\n';
            }
            ++metrics["births"];
            metrics["resident_cdcl"]+=resident[id];
            metrics["unit_births"]+=size==1;
            metrics["active_learned_units"]+=active_unit[id];
            metrics["complete_permanent_boolean"]+=n.flags==0;
            metrics["boolean_including_query"]+=(n.flags & (Theory|Incomplete))==0;
            metrics["theory_any"]+=bool(n.flags&Theory);
            metrics["incomplete_any"]+=bool(n.flags&Incomplete);
            metrics["query_any"]+=bool(n.flags&Query);
            metrics["theory_direct"]+=direct;
            metrics["theory_indirect_only"]+=!direct && bool(n.flags&Theory);
            metrics["uses_prior_learned_directly"]+=has_prior;
            metrics["loss_through_prior_learned"]+=through_learn[id]!=0;
            metrics["born_after_ancestor_eviction"]+=!oldest_eviction.empty() && oldest_eviction[id]<id;
            metrics["minimized_births"]+=l.min_edges>0;
            metrics["old_proof_survives"]+=!dead[id];
            metrics["survives_and_translates"]+=!dead[id] && can_map;
            ++metrics["flags_"+std::to_string(n.flags)];
            ++metrics["cause_"+std::to_string(causes[id])];
        }
        for(size_t id=g.nodes.size();id-->1;)
        {
            require((g.nodes[id].kind==Learned)==bool(born[id]),"birth catalogue incomplete");
            for(auto j=g.edgeBegin(id);j<g.nodes[id].edge_end;++j)
            {
                auto p=g.edges[j].parent;
                if(reachable[id] && deleted.count(p)) ++metrics["used_parent_edges_to_evicted_learned"];
                reachable[p]|=reachable[id];
            }
        }
        for(size_t i=0;i<g.inputs.size();++i)
        {
            auto id=g.inputs[i].leaf;
            if(reachable[id])
            {
                unsigned all=0,pure=0;
                for(auto j=g.offsets[id];j<g.offsets[id+1];++j)
                {
                    auto mask=reachable[g.children[j]];
                    all+=bool(mask&1); pure+=bool(mask&2);
                }
                leaves<<i+1<<'\t'<<id<<'\t'<<int(reachable[id])<<'\t'<<int(causes[id])<<'\t'<<all<<'\t'<<pure<<'\n';
            }
        }
        for(ProofId id=1;id<g.nodes.size();++id) ++metrics["kind_"+std::to_string(g.nodes[id].kind)];
        metrics["nodes"]=g.nodes.size()-1; metrics["edges"]=g.edges.size(); metrics["literal_entries"]=g.lits.size();
        metrics["native_learnts_vector"]=g.residents.size(); metrics["evicted_cdcl"]=g.evicted.size();
        metrics["seed_count"]=seeds.size();
        metrics["invalidated_nodes"]=std::count(dead.begin(),dead.end(),uint8_t(1));
        const char *names[]={"gc","removed_clauses","reduce_db","min_success","min_failure","search_ns",
            "search_calls","assigned_by_clause","assigned_explicit_unit","decisions","assumptions","unexplained_assignments",
            "relocated_to_new_cref","relocated_cdcl_to_new_cref","reverse_ns","write_sections_ns",
            "persistent_arena_capacity_bytes","recorder_capacity_bytes"};
        static_assert(sizeof(names)/sizeof(*names)==StatCount,"stat layout");
        for(unsigned i=0;i<StatCount;++i) metrics[names[i]]=g.stats[i];
        std::ofstream out(dir+"/metrics.tsv"); out.exceptions(std::ios::badbit|std::ios::failbit);
        for(auto &m:metrics) out<<m.first<<'\t'<<m.second<<'\n';
    }
};
}

int main(int argc,char **argv)
{
    if(argc!=6) return 2;
    try
    {
        ProofStore g; int status=g.read(argv[1]);
        require(status==0 || status==10,"uncompleted verification");
        Analysis a(g);
        verifyGraph(g,a.metrics);
        checkNative(g,argv[4]);
        a.inputs(argv[2]);
        std::ifstream mapping(argv[3]); unsigned v;
        require(bool(mapping),"mapping unavailable");
        int peer;
        std::set<int> targets;
        while(mapping>>v>>peer)
            require(peer>=0 && a.mapped.emplace(v,peer).second && targets.insert(peer/2).second,"noninjective variable map");
        a.classify(argv[5]);
    }
    catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
