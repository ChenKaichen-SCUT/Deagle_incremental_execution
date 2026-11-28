#include "ClosureSolver.h"
#include <cmath>
#include <cstring>
#include <iomanip>
#include <sstream>
#include <stdexcept>

namespace Minisat {
void RestartSample::timePrefix(int kind) {
    if (timing == kind) return;
    double now = epochClock();
    if (timing) intervals[timing] += now-since;
    since = now; timing = kind;
}

void PredicateTrace::open(const std::string &prefix, unsigned version) {
    if (prefix.empty()) return;
    out.open(prefix+"."+std::to_string(version)+".db", std::ios::binary | std::ios::app);
    out.exceptions(std::ios::badbit | std::ios::failbit);
}
void PredicateTrace::flush() {
    if (!count) return;
    out.write(reinterpret_cast<const char*>(&count), sizeof(count));
    out.write(reinterpret_cast<const char*>(&threshold), sizeof(threshold));
    out.write(reinterpret_cast<const char*>(first.data()), sizeof(int64_t)*first.size());
    out.write(reinterpret_cast<const char*>(step.data()), sizeof(int64_t)*step.size());
    count = 0;
}
void PredicateTrace::add(int learnts, int program, int selectors, int other, int assigned, uint64_t literals, double limit) {
    const Tuple row{{learnts,program,selectors,other,assigned,int64_t(literals)}};
    if (count && limit == threshold) {
        Tuple difference;
        for (size_t i=0;i<row.size();++i) difference[i]=row[i]-last[i];
        if (count==1 || step==difference) { step=difference; last=row; ++count; return; }
    }
    flush(); first=last=row; step.fill(0); threshold=limit; count=1;
}
void PredicateTrace::finish() {
    if (active()) { flush(); out.close(); }
}

void ClosureSolver::configureRestartStudy(const char *mode, const char *ledger, const char *db) {
    const std::string name=mode?mode:"R0";
    if (name!="R0" && name!="R1" && name!="R2") throw std::invalid_argument("PI1R_MODE");
    restartStudy.retain=name!="R0"; restartStudy.skipZero=name=="R2";
    if (ledger && std::string(ledger)!="off") throw std::invalid_argument("PI1R_LEDGER");
    restartStudy.ledger=!ledger;
    if (db) restartStudy.dbPath=db;
}

bool ClosureSolver::prefixSafe() const {
    const int a=assumptions.size(), depth=decisionLevel();
    return a>0 && restartStudy.sample.installed==a && depth>=a && work && workFloor<=a &&
        workDepth==depth && work->scopesAt(depth) && value(image->control)==l_True &&
        qhead==trail.size() && cursor==qhead && !initialCycle && temporary==CRef_Undef &&
        assigned_literals.empty() && literals_to_assign.empty() && queuedSite.empty() && work->triplets_to_check.empty();
}

double Solver::zeroTailProgress(int &visited) const {
    const double f=1.0/nVars();
    double sum=0;
    visited=0;
    for (int i=0; i<=decisionLevel(); ++i) {
        ++visited;
        const double weight=std::pow(f,i);
        if (weight==0 && f>0 && f<1) break;
        const int begin=i==0 ? 0 : trail_lim[i-1];
        const int end=i==decisionLevel() ? trail.size() : trail_lim[i];
        sum+=weight*(end-begin);
    }
    return sum/nVars();
}

double ClosureSolver::measuredProgress(bool exit) {
    auto &m=restartStudy.sample;
    int visits=decisionLevel()+1;
    const double start=epochClock();
    double result=restartStudy.skipZero ? zeroTailProgress(visits) : progressEstimate();
    m.progress[exit]+=epochClock()-start;
    ++m.calls[exit]; m.available[exit]+=decisionLevel()+1; m.visited[exit]+=visits;
    return result;
}

template<class V> static void numbers(std::ostream &o,const V &v) {
    o<<'['; bool first=true; for (auto x:v) { if(!first)o<<','; o<<x; first=false; } o<<']';
}
std::string ClosureSolver::restartReceipt() const {
    const auto &m=restartStudy.sample; std::ostringstream o; o<<std::setprecision(14);
    o<<"{\"mode\":\""<<(restartStudy.skipZero?"R2":restartStudy.retain?"R1":"R0")<<"\",\"ledger\":"<<(restartStudy.ledger?"true":"false")
     <<",\"first\":"<<m.first<<",\"reinstalled\":"<<m.repeated<<",\"ordinary\":"<<m.ordinary
     <<",\"kept\":"<<m.kept<<",\"incomplete\":"<<m.incomplete<<",\"unsafe\":"<<m.unsafe<<",\"budget_exit\":"<<m.budgets
     <<",\"query_switch_s\":"<<m.switchSeconds<<",\"end_level\":"<<decisionLevel()
     <<",\"end_graph\":"<<(work?1:0)<<",\"prefix_first_s\":"<<m.intervals[1]<<",\"prefix_repeat_s\":"<<m.intervals[2];
    o<<",\"jumps\":";numbers(o,m.jumps);o<<",\"prefix_jumps\":";numbers(o,m.prefixJumps);
    o<<",\"jump_removed\":";numbers(o,m.removed);o<<",\"progress_calls\":";numbers(o,m.calls);
    o<<",\"progress_available\":";numbers(o,m.available);o<<",\"progress_visits\":";numbers(o,m.visited);
    o<<",\"progress_seconds\":";numbers(o,m.progress);o<<",\"bcp_roles\":";numbers(o,m.dequeued);
    o<<",\"watcher_roles\":";numbers(o,m.watcher);o<<'}';return o.str();
}

void ClosureSolver::databaseSnapshot(const std::set<int> &off,unsigned active,unsigned total,const char *phase) {
    if (restartStudy.dbPath.empty()) return;
    std::map<std::pair<int,int>,std::array<unsigned,2>> hist;
    for (int i=0;i<learnts.size();++i) {
        const Clause &c=ca[learnts[i]]; int ns=0;bool dormant=false;
        for(int j=0;j<c.size();++j) {
            ns+=restartStudy.roles[var(c[j])]==Selector;
            dormant|=off.count(c[j].x)!=0;
        }
        ++hist[{c.size(),ns}][dormant];
    }
    if (piLedger) for (const auto &unit:piLedger->root_units) {
        Var v=unit.first; ++hist[{1,int(restartStudy.roles[v]==Selector)}][off.count(mkLit(v,value(v)==l_False).x)!=0];
    }
    uint64_t wused=0,wcap=0;
    for(int i=0;i<nVars()*2;++i) { auto &ws=watches[toLit(i)]; wused+=ws.size(); wcap+=ws.capacity(); }
    std::ofstream f(restartStudy.dbPath+".inventory",std::ios::app);
    f.exceptions(std::ios::badbit|std::ios::failbit);
    f<<"{\"version\":"<<epochVersion<<",\"phase\":\""<<phase<<"\",\"active_inputs\":"<<active<<",\"union_inputs\":"<<total
     <<",\"allocator_bytes\":"<<uint64_t(ca.size())*4<<",\"allocator_reserved\":"<<uint64_t(ca.reservedWords())*4
     <<",\"allocator_wasted\":"<<uint64_t(ca.wasted())*4<<",\"watcher_bytes\":"<<wused*sizeof(Watcher)
     <<",\"watcher_reserved\":"<<wcap*sizeof(Watcher)<<",\"native_learnts\":"<<learnts.size()
     <<",\"ledger_births\":"<<(piLedger?piLedger->births.size():0)<<",\"ledger_birth_capacity_bytes\":"
     <<(piLedger?piLedger->births.capacity()*sizeof(NativeBirth):0)<<",\"ledger_resident\":"<<(piLedger?piLedger->resident.size():0)
     <<",\"hist\":[";
    bool sep=false;for(const auto &x:hist) {if(sep)f<<',';sep=true;f<<'['<<x.first.first<<','<<x.first.second<<','<<x.second[0]<<','<<x.second[1]<<']';}
    f<<"]}\n";
}

void closure::auditScopes(std::ostream &o) const {
    auto limits=[&](const char *key,const vec<int>& v,int size){o<<' '<<key<<'=';for(int i=0;i<v.size();++i)o<<v[i]<<',';o<<size;};
    limits("edge",trail_edge_lim,trail_edge.size());limits("rf",trail_rf_lim,trail_rf.size());
    limits("vital",trail_vital_lim,trail_vital.size());limits("guard",trail_light_guard_lim,trail_light_guard.size());
    limits("triplet",trail_triplet_lim,trail_triplet.size());
    o<<" edges=";
    for(size_t i=0;i<nodes.size();++i) for(const auto &e:nodes[i].out) {
        o<<i<<'/'<<e.to; for(const auto p:e.reason)o<<'/'<<p.x; o<<',';
    }
    o<<" rfs=";for(size_t i=0;i<nodes.size();++i) for(const auto &e:nodes[i].out_rf)o<<i<<'/'<<e.to<<',';
    o<<" guards=";for(size_t i=0;i<nodes.size();++i) if(nodes[i].guard_lighted)o<<i<<'/'<<nodes[i].guard.x<<',';
    o<<" vitals=";for(size_t i=0;i<nodes.size();++i)for(int v:nodes[i].out_vital)o<<i<<'/'<<v<<',';
    o<<" triplets=";for(const auto &kv:rf_to_triplets)for(const auto &t:kv.second)o<<t.w1<<'/'<<t.w2<<'/'<<t.r<<'/'<<t.rf_lit.x<<'/'<<t.guard_lit.x<<',';
}
void ClosureSolver::restartAudit(const char *name,int target) {
    if(!reasonAudit) return;
    auto &o=*reasonAudit;
    o<<"STATE "<<name<<' '<<epochVersion<<' '<<target<<' '<<assumptions.size()<<' '<<meter.rebuilds<<' '<<workFloor
     <<' '<<workDepth<<' '<<qhead<<' '<<cursor<<' '<<restartStudy.sample.installed<<' '<<image->control.x<<" limits=";
    for(int i=0;i<trail_lim.size();++i)o<<trail_lim[i]<<',';
    o<<" trail=";for(int i=0;i<trail.size();++i) {
        const Var v=var(trail[i]);const CRef r=reason(v);
        o<<trail[i].x<<'/'<<level(v)<<'/'<<r;
        if(r!=CRef_Undef) for(int j=0;j<ca[r].size();++j)o<<'/'<<ca[r][j].x;
        o<<',';
    }
    o<<" pending="<<literals_to_assign.size()<<'/'<<assigned_literals.size()<<'/'<<queuedSite.size()<<'/'<<(work?work->triplets_to_check.size():0);
    if(work)work->auditScopes(o);
    o<<'\n';
}
}
