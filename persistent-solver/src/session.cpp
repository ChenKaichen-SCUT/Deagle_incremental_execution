#include "session_contract.h"
#include "minisat/core/ClosureSolver.h"
#include <algorithm>
#include <climits>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

namespace deagle_pi {
using Minisat::Lit;
using Minisat::Var;
using Minisat::mkLit;
using Minisat::var;
using Minisat::sign;
using Minisat::epochClock;
using Minisat::EpochImage;
using Minisat::NativeUse;
using Minisat::NativeLedger;
using Minisat::ClauseFamily;
using Minisat::lbool;
using Minisat::CRef;
using Minisat::vec;
namespace {
void check(bool condition, const char *message) { if (!condition) throw std::invalid_argument(message); }
int wire(LocalLit l, unsigned limit) {
    if (l.kind == LiteralKind::variable) {
        check(l.variable.id < limit, "out-of-space local literal");
        return int(2*l.variable.id) + l.negated;
    }
    check(!l.negated && (l.kind == LiteralKind::constant_true || l.kind == LiteralKind::constant_false), "invalid constant");
    return l.kind == LiteralKind::constant_true ? -1 : -2;
}
Lit lit(int raw) { Lit l = {raw}; return l; }
int translate(int raw, const std::vector<int> &mu) { return raw < 0 ? raw : mu.at(raw/2) ^ (raw&1); }
void token(std::string &out, const std::string &s) { out += std::to_string(s.size()) + ":" + s; }
const char *relation(Relation r) {
    switch (r) { case Relation::po:return "po"; case Relation::apo:return "apo";
        case Relation::rf:return "rf"; case Relation::race:return "race"; }
    throw std::invalid_argument("unsupported theory relation");
}
struct Ports {
    // Entries are (role, endpoint identities, sign), including all aliases of a port.
    std::map<unsigned,std::vector<std::string>> positive, negative;
};
struct VectorHash {
    size_t operator()(const std::vector<int>& v) const {
        size_t h=v.size();
        for (int n:v) h=(h^unsigned(n))*1099511628211ULL;
        return h;
    }
};
struct Version {
    VersionId id;
    std::string config, receipt;
    std::vector<int> mu;
    TheorySpec graph;
    std::vector<std::string> event_ids;
    std::vector<unsigned> inputs;
    struct Query { QueryDescriptor desc; Var control; std::vector<unsigned> inputs; };
    std::map<uint64_t,Query> queries;
    unsigned epoch;
};
void validateQuery(const QueryDescriptor &q, unsigned n) {
    check(q.native_variable_count_at_boundary == n, "wrong query space");
    for (const auto &l:q.native_assumptions) wire(l,n);
    for (const auto &l:q.goals) wire(l,n);
    check(q.goals.empty() || q.goals.size()==q.properties.size(), "ambiguous goal projection");
    std::set<uint64_t> seen;
    for (const auto &c:q.scoped_inputs) {
        check(c.scope==InputScope::query && seen.insert(c.occurrence).second,"invalid query occurrence");
        for (auto l:c.literals) wire(l,n);
    }
}
void validateGraph(const TheorySpec &g, unsigned n) {
    check(!g.rules_version.empty(),"missing theory rules");
    std::set<std::string> names;
    for(const auto &e:g.events) check(!e.key.empty() && !e.address_class.empty() && names.insert(e.key).second
        && e.location>=INT_MIN && e.location<=INT_MAX,"invalid event");
    auto event=[&](EventId id){check(id.local<g.events.size(),"unknown event");};
    std::set<unsigned> guards,blocks,domains;
    std::set<int> rfPorts; std::set<std::pair<unsigned,unsigned>> rfPairs, racePairs;
    std::map<unsigned,std::set<unsigned>> writes;
    std::vector<unsigned> rep(g.events.size());
    for(unsigned i=0;i<rep.size();++i) rep[i]=i;
    auto root=[&](unsigned i){while(rep[i]!=i) i=rep[i];return i;};
    for(const auto &e:g.edges) {
        event(e.from); event(e.to); int p=wire(e.condition,n); relation(e.relation);
        auto a=e.from.local,b=e.to.local;
        if(e.relation==Relation::po || e.relation==Relation::apo) {
            check(p==-1,"conditional order unsupported");
            if(e.relation==Relation::apo) rep[root(a)]=root(b);
        } else {
            check(p>=0,"missing or constant choice port");
            if(e.relation==Relation::rf) {
                check(g.events[a].writes && g.events[b].reads && g.events[a].address_class==g.events[b].address_class,
                      "RF address or roles");
                check(rfPorts.insert(p).second && rfPairs.emplace(a,b).second,"ambiguous RF");
                writes[b].insert(a);
            } else check(racePairs.emplace(std::min(a,b),std::max(a,b)).second,"ambiguous race");
        }
    }
    for(const auto &q:g.guards) {
        event(q.first); wire(q.second,n);
        check(g.events[q.first.local].writes && guards.insert(q.first.local).second,"invalid guard binding");
    }
    std::map<unsigned,std::set<unsigned>> implied;
    for(unsigned i=0;i<rep.size();++i) implied[root(i)].insert(i);
    for(const auto &block:g.atomic_blocks) {
        check(!block.empty(),"empty atomic block"); std::set<unsigned> group;
        for(auto e:block) {event(e);check(blocks.insert(e.local).second,"overlapping atomic blocks");group.insert(e.local);}
        check(group==implied.at(root(block.front().local)),"atomic block inconsistent with APO");
    }
    check(blocks.size()==g.events.size(),"incomplete atomic directory");
    for(const auto &d:g.candidate_writes) {
        event(d.first);
        check(g.events[d.first.local].reads && domains.insert(d.first.local).second,"invalid RF domain");
        std::set<unsigned> candidates;
        for(auto w:d.second){event(w);check(candidates.insert(w.local).second,"duplicate RF candidate");}
        check(candidates==writes[d.first.local],"incomplete RF candidate domain");
    }
    for(unsigned i=0;i<rep.size();++i) if(g.events[i].reads) check(domains.count(i),"missing RF domain");
}
Ports ports(const TheorySpec &g,const std::vector<std::string>& ids,unsigned n) {
    Ports p;
    auto add=[&](int l,std::string key){
        if(l<0) return;
        (l&1 ? p.negative : p.positive)[l/2].push_back(key);
    };
    for(const auto &e:g.edges) {
        std::string key=relation(e.relation);
        token(key,ids[e.from.local]);token(key,ids[e.to.local]);add(wire(e.condition,n),key);
    }
    for(const auto &g0:g.guards){std::string k="guard";token(k,ids[g0.first.local]);add(wire(g0.second,n),k);}
    for(auto *m:{&p.negative,&p.positive}) for(auto &kv:*m) std::sort(kv.second.begin(),kv.second.end());
    return p;
}
const std::vector<std::string>& portList(const std::map<unsigned,std::vector<std::string>>& m,unsigned v) {
    static const std::vector<std::string> empty;
    auto it=m.find(v);return it==m.end()?empty:it->second;
}
}

struct PersistentClosureSession::Backend {
    Minisat::ClosureSolver solver;
    NativeLedger ledger;
    Statistics stats;
    SessionState state=SessionState::idle;
    std::unique_ptr<Version> current;
    std::vector<std::unique_ptr<EpochImage>> epochs;
    std::map<std::string,unsigned> epochKeys;
    std::vector<Var> queryControls, selectors;
    std::unordered_map<std::vector<int>,unsigned,VectorHash> registry;
    std::ostream *trace=nullptr, *assumptionOutput=nullptr;
    Var truth;
    uint64_t published=0;
    bool saved=true;
    Backend() {stats.solver_construct_count=1;solver.configureRestartStudy(std::getenv("PI1R_MODE"),std::getenv("PI1R_LEDGER"),std::getenv("PI1R_DATABASE"));
        truth=solver.newVar(l_Undef,false);solver.restartStudy.tag(truth,Minisat::Constant);check(solver.addClause(mkLit(truth)),"constant root");}
    void boundary() const {check(saved && solver.currentLevel()==0 && (state==SessionState::ready || state==SessionState::idle),"unsafe transaction boundary");}
    Var freshProgram() {++stats.program_vars;auto v=solver.newVar();solver.restartStudy.tag(v,Minisat::Program);return v;}
    Var control() {++stats.selectors;auto v=solver.newVar(l_Undef,false);solver.restartStudy.tag(v,Minisat::Selector);return v;}
    void remember(const InputOccurrence &c,Var query,std::vector<unsigned>& active,const std::vector<int>& mu) {
        ++stats.occurrences;
        std::vector<int> v;
        for(auto l:c.literals) {
            int p=translate(wire(l,mu.size()),mu);
            if(p==-1){++stats.skipped;return;}
            if(p>=0)v.push_back(p);
        }
        std::sort(v.begin(),v.end());v.erase(std::unique(v.begin(),v.end()),v.end());
        for(size_t i=1;i<v.size();++i) if((v[i-1]^1)==v[i]){++stats.skipped;return;}
        // Negative context codes cannot collide with any translated program literal.
        v.push_back(-2-query);
        auto inserted=registry.emplace(std::move(v),unsigned(selectors.size()));
        unsigned idx=inserted.first->second;
        if(inserted.second) {
            auto s=control();selectors.push_back(s);
            vec<Lit> guarded; guarded.push(~mkLit(s));
            if(query!=var_Undef)guarded.push(~mkLit(query));
            const auto &v0=inserted.first->first;
            for(size_t i=0;i+1<v0.size();++i) guarded.push(lit(v0[i]));
            check(solver.addClause_(guarded),"permanent guarded database became inconsistent");
            ++stats.unique_inputs;
        }
        active.push_back(idx);
        if(trace)*trace<<"OCC "<<published+1<<' '<<query<<' '<<c.occurrence<<' '<<selectors[idx]<<'\n';
    }
    void installQuery(Version &v,QueryDescriptor q) {
        Version::Query result;
        result.control=control();queryControls.push_back(result.control);
        for(const auto &c:q.scoped_inputs) remember(c,result.control,result.inputs,v.mu);
        q.scoped_inputs.clear(); result.desc=std::move(q);
        auto id=result.desc.id.id;
        v.queries.emplace(id,std::move(result));
    }
    unsigned installGraph(const Version &v) {
        std::string key; token(key,v.config);token(key,v.graph.rules_version);
        std::unique_ptr<EpochImage> spec(new EpochImage);
        for(unsigned i=0;i<v.graph.events.size();++i) {
            const auto &n=v.graph.events[i];token(key,"event");token(key,v.event_ids[i]);token(key,n.key);
            token(key,n.address_class);token(key,std::to_string(n.location));
            token(key,std::to_string(n.reads)+std::to_string(n.writes)+std::to_string(n.initial));
            spec->nodes.push_back({n.key,n.address_class,n.reads,n.writes,int(n.location)});
        }
        for(const auto &e:v.graph.edges) {
            int p=translate(wire(e.condition,v.mu.size()),v.mu);std::string k=relation(e.relation);
            token(key,k);token(key,std::to_string(e.from.local));token(key,std::to_string(e.to.local));token(key,std::to_string(p));
            spec->edges.push_back({int(e.from.local),int(e.to.local),k,lit(p)});
        }
        for(const auto &g:v.graph.guards) {
            int p=translate(wire(g.second,v.mu.size()),v.mu);
            token(key,"guard");token(key,std::to_string(g.first.local));token(key,std::to_string(p));
            spec->guards.emplace_back(g.first.local,lit(p));
        }
        for(auto &block:v.graph.atomic_blocks){token(key,"block");for(auto e:block)token(key,std::to_string(e.local));}
        for(auto &d:v.graph.candidate_writes){token(key,"domain");token(key,std::to_string(d.first.local));for(auto e:d.second)token(key,std::to_string(e.local));}
        auto it=epochKeys.emplace(std::move(key),epochs.size());
        if(it.second){spec->control=mkLit(control());epochs.push_back(std::move(spec));}
        return it.first->second;
    }
    void receipt(const std::vector<unsigned>& physical,const std::vector<unsigned>& inactive,
                 const std::vector<unsigned>& oldUnits) {
        const auto &m=solver.epochMetrics();
        std::ostringstream o; o.precision(12);
        o<<"{\"boundary_status\":\""<<m.diagnostic<<"\"";
#define FIELD(x) o<<",\"" #x "\":"<<m.x
        FIELD(assumptions);FIELD(processed);FIELD(prefix);FIELD(frames);FIELD(empty);FIELD(bcp);FIELD(pushes);FIELD(pops);
        FIELD(rebuilds);FIELD(replay);FIELD(replay_literals);FIELD(theory_props);FIELD(cycles);FIELD(co_pairs);
        FIELD(restarts);FIELD(discarded_queued);FIELD(delayed_conflicts);FIELD(positive);FIELD(negative);FIELD(max_level);FIELD(decisions);FIELD(conflicts);
        FIELD(propagations);FIELD(activation);FIELD(joint);FIELD(rollback);FIELD(boundary);
#undef FIELD
        o<<",\"restart_study\":"<<solver.restartReceipt();
        o<<",\"solver_instance\":"<<solver.nativeInstance();
        o<<",\"collections\":"<<ledger.collections<<",\"reductions\":"<<ledger.reductions<<",\"families\":[";
        for(unsigned f=0;f<3;++f){
            unsigned born=0,res=0,units=0,used=0,dormantUsed=0; std::array<uint64_t,4> h{},unitHits{},sleepHits{};unsigned unitUsed=0;
            for(const auto &b:ledger.births) if(unsigned(b.family)==f){
                if(b.version==published){++born;units+=b.unit;}
                if(b.version<published){
                    bool hit=false;for(unsigned i=0;i<4;++i){h[i]+=b.hits[i];if(b.unit)unitHits[i]+=b.hits[i];if(b.dormant)sleepHits[i]+=b.hits[i];hit|=b.hits[i]!=0;}
                    used+=hit;unitUsed+=hit&&b.unit;dormantUsed+=hit&&b.dormant;
                }
            }
            for(const auto &kv:ledger.resident) {auto &b=ledger.births[kv.second];res+=b.version==published&&unsigned(b.family)==f;}
            if(f)o<<',';
            o<<"{\"family\":\""<<("BMT"[f])<<"\",\"births\":"<<born<<",\"resident_end\":"<<res+units
             <<",\"unit_births\":"<<units<<",\"old_units\":"<<oldUnits[f]<<",\"physical\":"<<physical[f]
             <<",\"dormant\":"<<inactive[f]<<",\"constraining\":"<<physical[f]-inactive[f]
             <<",\"root_unit_used\":"<<unitUsed<<",\"root_unit_hits\":["<<unitHits[0]<<','<<unitHits[1]<<','<<unitHits[2]<<','<<unitHits[3]<<"]"
             <<",\"dormant_hits\":["<<sleepHits[0]<<','<<sleepHits[1]<<','<<sleepHits[2]<<','<<sleepHits[3]<<"]"<<",\"distinct_used\":"<<used<<",\"dormant_distinct_used\":"<<dormantUsed<<",\"hits\":["<<h[0]<<','<<h[1]<<','<<h[2]<<','<<h[3]<<"]}";
        }
        o<<"]}";stats.receipt=o.str();stats.global_vars=solver.nVars();stats.co_vars=solver.allocatedCO.size();
        stats.graph_generations+=m.rebuilds;
    }
    QueryResult run(VersionId version,QueryId id,bool probe) {
        check(current && version.id==published && (state==SessionState::ready || state==SessionState::idle),"invalid selected version");
        auto it=current->queries.find(id.id);check(it!=current->queries.end(),"unknown query");
        Version &v=*current;auto &q=it->second;
        QueryResult result{};result.version=version;result.query=id;
        double t=epochClock();
        vec<Lit> args;std::set<int> off;
        auto assume=[&](Lit control,bool on){args.push(on?control:~control);if(!on)off.insert((~control).x);};
        for(unsigned i=0;i<epochs.size();++i)assume(epochs[i]->control,i==v.epoch);
        for(auto c:queryControls)assume(mkLit(c),c==q.control);
        std::vector<unsigned char> enabled(selectors.size(),0);
        for(auto i:v.inputs)enabled[i]=1;
        for(auto i:q.inputs)enabled[i]=1;
        for(unsigned i=0;i<selectors.size();++i)assume(mkLit(selectors[i]),enabled[i]);
        for(auto a:q.desc.native_assumptions){
            int raw=translate(wire(a,v.mu.size()),v.mu);
            args.push(raw<0?mkLit(truth,raw==-2):lit(raw));
        }
        if(trace) {
            *trace<<"ASSUME "<<published<<' '<<id.id;
            for(int j=0;j<args.size();++j)*trace<<' '<<args[j].x;
            *trace<<'\n';
        }
        stats.assumption_build_seconds=epochClock()-t;
        if(assumptionOutput) {
            auto word=[&](uint32_t x){char bytes[4];for(unsigned j=0;j<4;++j)bytes[j]=char(x>>(j*8));assumptionOutput->write(bytes,4);};
            word(published);word(id.id);word(args.size());word(args.size()-q.desc.native_assumptions.size());
            for(int i=0;i<args.size();++i)word(args[i].x);
            check(assumptionOutput->good(),"assumption receipt failed");
        }
        solver.epochContext(*epochs[v.epoch],epochs.size(),published,ledger);
        solver.classifyResident(off);
        std::vector<unsigned> phys(3),inactive(3),oldUnits(3);
        auto count=[&](unsigned idx){const auto &b=ledger.births[idx];if(b.version<published){
            auto f=unsigned(b.family);++phys[f];inactive[f]+=b.dormant;oldUnits[f]+=b.unit;}};
        for(const auto &kv:ledger.resident)count(kv.second);
        for(const auto &kv:ledger.root_units)count(kv.second);
        unsigned active=0;
        if(!solver.restartStudy.dbPath.empty()) {
            active=std::count(enabled.begin(),enabled.end(),1);
            solver.databaseSnapshot(off,active,selectors.size(),"entry");
        }
        const double switchTime=epochClock()-t;
        state=SessionState::solving;
        try {
            lbool status=solver.runEpoch(args,probe);
            solver.restartStudy.sample.switchSeconds=switchTime;
            solver.databaseSnapshot(off,active,selectors.size(),"exit");
            if(status==l_True) {
                result.status=QueryResult::Status::sat;
                for(unsigned i=0;i<q.desc.native_variable_count_at_boundary;++i){auto value=solver.modelValue(lit(v.mu[i]));
                    result.local_assignment.push_back(value==l_True?QueryResult::Value::true_value:
                        value==l_False?QueryResult::Value::false_value:QueryResult::Value::unassigned);}
                result.event_order.assign(solver.resultOrder().begin(),solver.resultOrder().end());
                std::ostringstream out;
                for(auto &e:result.event_order)out<<e.first<<' '<<e.second<<'\n';
                result.visible_witness=out.str();
            } else result.status=status==l_False?QueryResult::Status::unsat:QueryResult::Status::unknown;
            if(status==l_False) for(auto a:q.desc.native_assumptions){
                int raw=translate(wire(a,v.mu.size()),v.mu);auto p=raw<0?mkLit(truth,raw==-2):lit(raw);
                for(int j=0;j<solver.conflict.size();++j)if(solver.conflict[j]==~p){result.failed_native_assumptions.push_back(a);break;}
            }
            if(!probe)for(unsigned i=0;i<q.desc.properties.size();++i) {
                std::string value="UNKNOWN";
                if(status==l_False)value="SUCCESS";
                if(status==l_True && !q.desc.goals.empty()) {
                    int p=translate(wire(q.desc.goals[i],v.mu.size()),v.mu);
                    if(p==-1 || (p>=0 && solver.modelValue(lit(p))==l_True))value="FAILURE";
                }
                if(status==l_True && q.desc.goals.empty() && q.desc.properties.size()==1)value="FAILURE";
                result.property_results.emplace_back(q.desc.properties[i],value);
            }
            receipt(phys,inactive,oldUnits);
            saved=true;state=SessionState::idle;
        } catch(...) {state=SessionState::failed;throw;}
        return result;
    }
};

PersistentClosureSession::PersistentClosureSession():backend(new Backend) {}
PersistentClosureSession::~PersistentClosureSession()=default;
PersistentClosureSession::Backend &PersistentClosureSession::live() const {
    if(!backend) throw std::logic_error("session is closed");
    return *backend;
}
VersionId PersistentClosureSession::append_version(ModelTransaction txn) {
    std::lock_guard<std::mutex> guard(access);
    auto &b=live();b.boundary();
    const double start=epochClock();
    const unsigned n=txn.native_variable_count;
    check(n>0&&n<unsigned(INT_MAX/8)&&!txn.complete_configuration.empty(),"invalid model header");
    validateQuery(txn.first_query,n);validateGraph(txn.graph,n);
    std::set<unsigned> atoms;
    for(const auto &a:txn.atoms)check(a.variable.id<n&&atoms.insert(a.variable.id).second,"duplicate/invalid atom");
    // Unlisted ordinary atoms are implicit. Extra interface roles require actual graph bindings.
    std::set<uint64_t> occurrences;
    for(const auto &c:txn.inputs){
        check(c.scope==InputScope::model && occurrences.insert(c.occurrence).second,"invalid model occurrence");
        for(auto l:c.literals)wire(l,n);
    }
    check(!b.current || b.current->config==txn.complete_configuration,"incompatible configuration");
    std::unique_ptr<Version> v(new Version);v->id={b.published+1};v->config=std::move(txn.complete_configuration);
    if(!txn.certified_matches.empty() || !txn.certified_events.empty() || !txn.predecessor_receipt.empty()) {
        check(b.current && !txn.model_receipt.empty() && !b.current->receipt.empty()
              && txn.predecessor_receipt==b.current->receipt,"certificate names a different predecessor model");
    }
    v->receipt=std::move(txn.model_receipt);
    v->graph=std::move(txn.graph);v->mu.assign(n,-1);
    for(unsigned i=0;i<v->graph.events.size();++i)v->event_ids.push_back(std::to_string(v->id.id)+"/"+std::to_string(i));
    std::set<unsigned> src,dst;
    for(const auto &e:txn.certified_events) {
        check(b.current && e.first.local<b.current->event_ids.size() && e.second.local<v->event_ids.size()
            && src.insert(e.first.local).second && dst.insert(e.second.local).second,"non-injective event certificate");
        auto &old=b.current->graph.events[e.first.local]; auto &now=v->graph.events[e.second.local];
        if(old.reads==now.reads && old.writes==now.writes && old.initial==now.initial && old.address_class==now.address_class)
            v->event_ids[e.second.local]=b.current->event_ids[e.first.local];
    }
    auto newPorts=ports(v->graph,v->event_ids,n);Ports oldPorts;
    if(b.current)oldPorts=ports(b.current->graph,b.current->event_ids,b.current->mu.size());
    std::set<std::pair<unsigned,AtomRole>> actualRoles;
    for(const auto &e:v->graph.edges)if(wire(e.condition,n)>=0)
        actualRoles.emplace(e.condition.variable.id,e.relation==Relation::rf?AtomRole::rf:AtomRole::race);
    for(const auto &g:v->graph.guards)if(wire(g.second,n)>=0)actualRoles.emplace(g.second.variable.id,AtomRole::guard);
    for(const auto &a:txn.atoms)for(auto r:a.roles)
        check(r==AtomRole::ordinary || actualRoles.count({a.variable.id,r}),"declared interface lacks actual binding");
    src.clear();dst.clear();
    uint64_t reused=0,rejected=0;
    for(const auto &m:txn.certified_matches){
        int p=wire(m.positive_image,n);unsigned x=m.previous.id;
        check(b.current && x<b.current->mu.size() && p>=0 && !m.certificate.empty() && src.insert(x).second
            && dst.insert(p/2).second,"invalid signed atom certificate");
        auto y=unsigned(p/2);bool inverse=p&1;
        if(portList(oldPorts.positive,x)!=portList(inverse?newPorts.negative:newPorts.positive,y) ||
           portList(oldPorts.negative,x)!=portList(inverse?newPorts.positive:newPorts.negative,y)){++rejected;continue;}
        v->mu[y]=b.current->mu[x]^int(inverse);++reused;
    }
    b.state=SessionState::installing;
    try {
        for(auto &a:v->mu)if(a<0)a=mkLit(b.freshProgram()).x;
        if (b.trace) { *b.trace<<"MU "<<v->id.id;for(int raw:v->mu)*b.trace<<' '<<raw;*b.trace<<'\n'; }
        v->epoch=b.installGraph(*v);
        for(const auto &c:txn.inputs)b.remember(c,var_Undef,v->inputs,v->mu);
        b.installQuery(*v,std::move(txn.first_query));
        b.published=v->id.id;b.current=std::move(v);b.saved=false;b.state=SessionState::ready;
        b.stats.reused=reused;b.stats.fresh=n-reused;b.stats.rejected_ports=rejected;b.stats.install_seconds=epochClock()-start;
    } catch(...) {b.state=SessionState::failed;throw;}
    return {b.published};
}
QueryId PersistentClosureSession::append_query(VersionId ver,QueryDescriptor q){
    std::lock_guard<std::mutex> guard(access);
    auto &b=live();b.boundary();check(b.current&&ver.id==b.published&&!b.current->queries.count(q.id.id),"invalid query transaction");
    auto &v=*b.current;unsigned prev=v.mu.size(), n=q.native_variable_count_at_boundary;
    check(n>=prev && n<unsigned(INT_MAX/8) && q.new_query_atoms.size()==n-prev,"unsealed query allocation");
    std::set<unsigned> ids;
    for(auto &a:q.new_query_atoms) {
        check(a.variable.id>=prev && a.variable.id<n && ids.insert(a.variable.id).second,"bad query allocation");
        for(auto r:a.roles)check(r==AtomRole::ordinary,"query-local theory binding unsupported");
    }
    validateQuery(q,n);auto id=q.id;
    try {
        while(v.mu.size()<n)v.mu.push_back(mkLit(b.freshProgram()).x);
        b.installQuery(v,std::move(q));b.saved=false;b.state=SessionState::ready;
    }catch(...){b.state=SessionState::failed;throw;}
    return id;
}
QueryResult PersistentClosureSession::solve_query(VersionId v,QueryId q){std::lock_guard<std::mutex> guard(access);return live().run(v,q,false);}
void PersistentClosureSession::probe_boundary(VersionId v,QueryId q){std::lock_guard<std::mutex> guard(access);live().run(v,q,true);}
SessionState PersistentClosureSession::state()const{std::lock_guard<std::mutex> guard(access);return backend?backend->state:SessionState::aborted;}
PersistentClosureSession::Statistics PersistentClosureSession::statistics()const{std::lock_guard<std::mutex> guard(access);return backend?backend->stats:final_statistics;}
void PersistentClosureSession::set_audit_output(std::ostream *s){std::lock_guard<std::mutex> guard(access);auto &b=live();b.solver.auditTo(s);b.trace=s;b.ledger.audit=s;}
void PersistentClosureSession::set_assumption_output(std::ostream *s){std::lock_guard<std::mutex> guard(access);live().assumptionOutput=s;}
void PersistentClosureSession::first_restart_for_test(int conflicts){std::lock_guard<std::mutex> guard(access);auto &b=live();b.boundary();check(conflicts>0,"restart interval");b.solver.restart_first=conflicts;}
void PersistentClosureSession::collect_at_boundary(){std::lock_guard<std::mutex> guard(access);auto &b=live();b.boundary();b.solver.collectForTest();}
void PersistentClosureSession::interrupt_next_query(){std::lock_guard<std::mutex> guard(access);live().solver.interrupt();}
void PersistentClosureSession::clear_interrupt(){std::lock_guard<std::mutex> guard(access);live().solver.clearInterrupt();}
void PersistentClosureSession::conflict_budget_for_test(int conflicts){
    std::lock_guard<std::mutex> guard(access);
    auto &b=live();b.boundary();
    if(conflicts<0)b.solver.budgetOff();else b.solver.setConfBudget(conflicts);
}
void PersistentClosureSession::close(){std::lock_guard<std::mutex> guard(access);if(backend){final_statistics=backend->stats;backend.reset();}}
}
