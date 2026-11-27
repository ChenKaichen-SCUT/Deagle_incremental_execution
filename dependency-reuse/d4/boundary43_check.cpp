// Offline D4.3-C checker. No solver, recorder or condition-cache implementation is linked.
#include "../d3/theory_check.h"
#include <cstdint>
#include <cstring>
#include <fstream>
using Mask=std::array<uint64_t,16>;
namespace {
struct Reader {
    std::ifstream f;
    explicit Reader(const char *p):f(p,std::ios::binary){require(bool(f),"missing observation file");}
    void bytes(void *p,size_t n){if(n)require(bool(f.read(static_cast<char*>(p),n)),"truncated observation");}
    uint32_t word(){uint32_t n;bytes(&n,4);return n;}
    void magic(const char *v){char s[8];bytes(s,8);require(!std::memcmp(s,v,8),"observation schema");}
    bool end(){return f.peek()==EOF;}
    std::vector<int> literals(){auto n=word();require(n<=4000000,"invalid literal count");std::vector<int> v(n);bytes(v.data(),4*v.size());return v;}
};
struct Queued {uint32_t site,rule;int target;std::vector<int> clause;};
const char *sources[]={"other","immediate_guard","immediate_RF","RF_recheck","guard_recheck",
                       "reverse_RF","race","graph_conflict","early_conflict","dynamic_CO"};
struct BoundaryCheck {
    ProofStore &g;
    TheoryAudit &audit;
    Reader trace,events;
    std::vector<Mask> masks;
    std::map<uint32_t,Queued> queue;
    std::map<int,uint32_t> targets;
    std::map<std::string,uint64_t> counts;
    uint32_t cursor=0,tickets=0,total=0;
    BoundaryCheck(ProofStore &g,TheoryAudit &audit,const char *slots,const char *old_trace,const char *observations):
        g(g),audit(audit),trace(old_trace),events(observations),masks(g.theory_records.size()){
        std::ifstream f(slots);Key key;unsigned slot,used;
        std::map<Key,std::pair<unsigned,bool>> directory;
        while(f>>key[0]>>key[1]>>key[2]>>key[3]>>slot>>used)
            require(slot<1024 && used<=1 && directory.emplace(key,std::make_pair(slot,used!=0)).second,"duplicate/invalid leaf slot");
        require(f.eof(),"invalid slot directory");
        for(size_t i=0;i<g.theory_records.size();++i){
            auto &r=g.theory_records[i];auto &bits=masks[i];
            if(g.nodes[r.id].kind==TheoryDeclaration){
                auto row=directory.at({{int(r.op),r.a,r.b,r.c}});slot=row.first;
                bits[slot/64]|=uint64_t(1)<<(slot%64);
            }else for(auto j=g.edgeBegin(r.id);j<g.nodes[r.id].edge_end;++j){
                auto &parent=masks.at(audit.index.at(g.edges.at(j).parent));
                for(size_t k=0;k<bits.size();++k)bits[k]|=parent[k];
            }
        }
    }
    bool nextTrace(uint32_t &kind,std::vector<int> &lits){
        while(!trace.end()){
            kind=trace.word();lits=trace.literals();if(kind!=Learned)return true;
        }
        return false;
    }
    ProofId nextLemma(){
        while(++cursor<g.nodes.size()){
            auto k=g.nodes[cursor].kind;if(k==TheoryLemma || theory(k))return cursor;
        }
        return 0;
    }
    void enqueue(){
        auto ticket=events.word(),site=events.word(),rule=events.word();int target=int(events.word());
        auto clause=events.literals();
        require(site<=6 && ticket==++tickets && !clause.empty() && target==clause.front()
                && targets.emplace(target,ticket).second,"queue acceptance/order");
        require(queue.emplace(ticket,Queued{site,rule,target,std::move(clause)}).second,"queue ticket reused");
        ++counts["queued"];
    }
    void duplicate(){
        auto ticket=events.word(),site=events.word();int target=events.word();
        require(site<=6 && targets.at(target)==ticket && queue.at(ticket).target==target,"duplicate replaced pending reason");
        ++counts["duplicates"];
    }
    void boundary(){
        uint32_t seq=events.word(),kind=events.word(),site=events.word(),lemma=events.word(),rule=events.word();
        uint32_t ticket=events.word(),op=events.word(),flags=events.word();
        auto native=events.literals();Mask edge{},sat{};events.bytes(&edge,sizeof(edge));events.bytes(&sat,sizeof(sat));
        uint32_t expected_kind;std::vector<int> previous;
        require(seq==++total && nextTrace(expected_kind,previous) && kind==expected_kind && previous==native,
                "independent native literal stream differs");
        require(lemma && nextLemma()==lemma,"boundary paired with a different Audit ProofID");
        auto k=g.nodes.at(lemma).kind;
        if(kind==TheoryReason){
            auto q=queue.at(ticket);
            require(site==0 && q.rule==rule && q.clause==native && targets.at(q.target)==ticket,"queued reason/ProofID/literal mismatch");
            queue.erase(ticket);targets.erase(q.target);site=q.site;
        }else require(!ticket && ((kind==TheoryConflict && site==7)||(kind==TheoryEmpty && site==8)||
                                   (kind==DynamicCO && site==9)),"nonqueued origin mismatch");
        require(k==TheoryEmpty || content(g,lemma)==native,"actual ordered Audit literals differ");
        ++counts[sources[site]];++counts["boundaries"];
        ++counts[kind==TheoryReason?"propagation":kind==DynamicCO?"co_definitions":"conflict"];
        if(kind==TheoryReason && native.size()==1){++counts["theory_units"];++counts[std::string("units_")+sources[site]];}
        if(k!=TheoryLemma){
            require(k==kind || (kind==TheoryEmpty && k==TheoryConflict),"opaque boundary kind");
            require(flags==8 && sat==Mask{},"uncertified reason admitted");
            if(!rule || kind==DynamicCO)require(op==255 && edge==Mask{},"missing raw source marked known");
            ++counts["unknown"];return;
        }
        require(rule && g.edges[g.edgeBegin(lemma)].parent==rule,"different source inference");
        const auto index=audit.index.at(rule);
        require(g.theory_records.at(index).op==op && flags==2,"known rule/scope mismatch");
        require(((site==7 || site==8) && op==CycleRule) || (site==5 && op==PreventRF) ||
                (site>=1 && site<=4 && op==TripletRule),"rule attributed to wrong native trigger");
        auto discharged=audit.facts.at(index).conditions;
        for(int &lit:discharged)lit^=1;
        require(normalized(discharged)==normalized(native),"independent conditional discharge mismatch");
        const Mask &need=masks.at(index);
        bool extra=false;
        for(size_t i=0;i<need.size();++i){
            require(!(need[i]&~edge[i]) && !(need[i]&~sat[i]),"missing projected theory premise");
            require(edge[i]==sat[i],"native reason tag differs from attached SAT tag");
            extra|=need[i]!=edge[i];
        }
        ++counts[extra?"proper_superset":"exact"];++counts["certified"];
    }
    void run(){
        events.magic("D43CBND1");
        for(;;){
            auto k=events.word();
            if(k=='Q')enqueue();
            else if(k=='D')duplicate();
            else if(k=='B')boundary();
            else if(k=='X'){
                require(!queue.empty() && events.word()==queue.size(),"discarded queue count");
                counts["discarded"]+=queue.size();queue.clear();targets.clear();
            }else{
                require(k=='E' && events.word()==tickets && events.word()==total,"boundary footer");
                events.magic("ENDCBA01");break;
            }
        }
        uint32_t k;std::vector<int> v;
        require(events.end() && !nextTrace(k,v) && !nextLemma() && queue.empty(),"extra or missing boundaries");
        require(tickets==counts["discarded"]+counts["propagation"],"unaccounted accepted reason");
    }
};
}
int main(int argc,char **argv){
    if(argc!=6)return 2;
    try{
        ProofStore g;int result=g.read(argv[1]);require(g.d3 && g.triplets && (result==0 || result==10),"full Audit required");
        GraphModel model(argv[2]);require(model.graph_receipt==g.graph_receipt,"wrong installed model");
        Analysis a(g);TheoryAudit audit(model,a);audit.replay();
        BoundaryCheck checker(g,audit,argv[3],argv[4],argv[5]);checker.run();
        for(auto &x:checker.counts)std::cout<<x.first<<'\t'<<x.second<<'\n';
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
