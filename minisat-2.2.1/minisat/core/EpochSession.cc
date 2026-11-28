#include "ClosureSolver.h"
#include <algorithm>
#include <stdexcept>
#include <sstream>

namespace Minisat {
void ClosureSolver::epochContext(EpochImage &spec, int frames, unsigned version, NativeLedger &ledger)
{
    if (decisionLevel() || work || temporary != CRef_Undef || !okay() || frames < 1)
        throw std::logic_error("unsafe epoch boundary");
    image = &spec;
    barrier = frames;
    piLedger = restartStudy.ledger ? &ledger : nullptr;
    epochVersion = version;
    ledger.version = version;
    for(auto &b:ledger.births)b.hits.fill(0);
    ownedOrder.clear();
    oc_result_order = &ownedOrder;
}

void ClosureSolver::dropGraph()
{
    work.reset();
    cursor = workDepth = workFloor = 0;
    initialCycle = false;
    queuedSite.clear();
    literals_to_assign.clear();
    assigned_literals.clear();
}

void ClosureSolver::startGraph()
{
    if (value(image->control) != l_True) throw std::logic_error("wrong epoch at barrier");
    for (int i=0; i<barrier; ++i)
        if (value(assumptions[i]) != l_True) throw std::logic_error("incomplete activation");
    const double begin = epochClock();
    work.reset(new closure);
    work->init(this);
    oc_edge_table.clear(); oc_guard_map.clear(); oc_location_map.clear();
    std::map<std::string,int> addresses;
    for (const auto &n : image->nodes) {
        int id = work->get_node(n.name);
        auto a = addresses.emplace(n.address, int(addresses.size()));
        auto &node = work->nodes.at(id);
        node.address = a.first->second;
        node.is_write = n.write; node.is_read = n.read; node.location = n.location;
    }
    for (const auto &edge : image->edges)
        oc_edge_table.push_back({{image->nodes[edge.from].name, image->nodes[edge.to].name}, {edge.port, edge.kind}});
    for (const auto &g : image->guards) oc_guard_map.emplace(image->nodes[g.first].name, g.second);
    workFloor = workDepth = decisionLevel();
    for (int i=0; i<workDepth; ++i) work->push_scope();
    meter.pushes += workDepth;
    set_graph();
    for (const auto &co : image->extensions) {
        work->init_reasonable_edge(co.from, co.to, OC_NA, co.forward);
        work->init_reasonable_edge(co.to, co.from, OC_NA, co.backward);
    }
    cursor = 0;
    ++meter.rebuilds; ++meter.replay; meter.replay_literals += trail.size();
    meter.activation += epochClock() - begin;
}

void ClosureSolver::releaseTemporary()
{
    if (temporary != CRef_Undef) { ca.free(temporary); temporary = CRef_Undef; }
}

// The incoming Closure payload already uses clause polarity. cycle has no conclusion.
// Read the SAT allocator after allocation for the audit, including the literal actually enqueued.
CRef ClosureSolver::materialize(Lit conclusion, const literal_set &conditions, bool cycle)
{
    bool realConclusion = !cycle && conclusion.x >= 0;
    if (!cycle && (conclusion.x == -1 || (realConclusion && value(conclusion) == l_True))) return CRef_Undef;
    vec<Lit> lits;
    if (realConclusion) lits.push(conclusion);
    literal_set body = conditions;
    if (!cycle) body.erase(conclusion);
    body.insert(~image->control);
    int supportLevel = 0, highest = -1;
    for (Lit l : body) {
        if (l.x == -2) continue;
        if (l.x < 0 || value(l) != l_False) {
            std::ostringstream msg;msg<<"non-false theory antecedent "<<l.x<<" conclusion "<<conclusion.x
              <<" native_site "<<currentSite<<" cycle "<<cycle<<" generation "<<meter.rebuilds<<" frame "<<decisionLevel()<<" raw";
            for(auto p:conditions)msg<<' '<<p.x<<'/'<<(p.x<0?-1:toInt(value(p)));
            throw std::logic_error(msg.str());
        }
        if (highest < 0 || level(var(l)) > supportLevel) { highest = lits.size(); supportLevel = level(var(l)); }
        lits.push(l);
    }
    if (highest < 0) throw std::logic_error("missing epoch literal");
    std::swap(lits[realConclusion ? 1 : 0], lits[highest]);
    const bool conflictNow = !realConclusion || value(conclusion) == l_False;
    CRef cr = ca.alloc(lits, true);
    if (reasonAudit) {
        auto &out = *reasonAudit;
        out << "REASON " << epochVersion << ' ' << meter.rebuilds << ' ' << (conflictNow ? 'C' : 'P')
            << ' ' << image->control.x << ' ' << (cycle ? -3 : conclusion.x) << ' ' << decisionLevel();
        const Clause &actual = ca[cr];
        for (int i=0; i<actual.size(); ++i)
            out << ' ' << actual[i].x << '/' << toInt(value(actual[i])) << '/' << level(var(actual[i]));
        out << " |";
        for (Lit l : conditions) out << ' ' << l.x;
        out << '\n';
    }
    if (conflictNow) {
        ++meter.cycles;
        temporary = cr; // Owned until UIP consumes it, or until the boundary probe rolls back.
        return cr;
    }
    if (supportLevel < decisionLevel()) {
        restartStudy.sample.timePrefix(0);
        restartStudy.sample.jump(decisionLevel(),supportLevel,2);
        restartAudit("support",supportLevel); cancelUntil(supportLevel);
        if (work) { meter.pops += workDepth; dropGraph(); }
    }
    learnts.push(cr); attachClause(cr); claBumpActivity(ca[cr]);
    if (piLedger) piLedger->born(cr, ClauseFamily::theory);
    uncheckedEnqueue(conclusion, cr);
    if (reasonAudit) {
        *reasonAudit<<"ENQUEUE "<<cr<<' '<<conclusion.x<<' '<<trail.size()-1;
        const Clause &actual=ca[reason(var(conclusion))];
        for(int j=1;j<actual.size();++j) {
            int position=0;while(position<trail.size() && trail[position]!=~actual[j])++position;
            if(position>=trail.size()-1)throw std::logic_error("non-causal theory reason");
            *reasonAudit<<' '<<actual[j].x<<'/'<<position;
        }
        *reasonAudit<<'\n';
    }
    ++meter.theory_props;
    return CRef_Undef;
}

CRef ClosureSolver::epochPropagate()
{
    for (;;) {
        ++meter.bcp;
        CRef c = Solver::propagate();
        if (c != CRef_Undef || decisionLevel() < barrier) return c;
        if (!work) startGraph();
        bool cycle = initialCycle;
        // Independent cursor, including the permanent root trail and assignments already processed by
        // non-virtual Solver::propagate during addClause_ or simplify.
        while (!cycle && cursor < trail.size()) {
            Lit p = trail[cursor++];
            auto e = work->get_decide_entry(p);
            if (e.first.first != -1) {
                literal_vector reason(1, p);
                cycle = work->activate_edge(e.first.first, e.first.second, e.second, reason);
            }
            if (!cycle) for (int node : work->check_guard_literal(p)) {
                if (work->light_guard(node)) { cycle = true; break; }
            }
        }
        if (cycle) {
            work->triplets_to_check.clear();
            literal_set reason;
            for (Lit p : work->conflict_lv) reason.insert(~p);
            return materialize(lit_Undef, reason, true);
        }
        if (literals_to_assign.empty()) return CRef_Undef;
        decltype(literals_to_assign) pending;
        literals_to_assign.swap(pending);
        assigned_literals.clear();
        std::map<int,int> sites;sites.swap(queuedSite);
        for (const auto &assignment : pending) {
            currentSite=sites.at(assignment.first.x);
            c = materialize(assignment.first, assignment.second, false);
            if (c != CRef_Undef) return c;
            if (!work) break; // The next generation reconstructs all unconsumed consequences.
        }
    }
}

void ClosureSolver::installCo()
{
    for (auto pair : work->find_incomplete_co_pairs()) {
        for (const auto &old : image->extensions)
            if (old.from == pair.first && old.to == pair.second)
                throw std::logic_error("existing CO binding failed completeness check");
        Lit a = mkLit(newVar()), b = mkLit(newVar());
        restartStudy.tag(var(a),DynamicCO); restartStudy.tag(var(b),DynamicCO);
        allocatedCO.push_back(var(a)); allocatedCO.push_back(var(b));
        vec<Lit> clause;
        clause.push(a); clause.push(b); clause.push(~image->control);
        for (int node : {pair.first, pair.second}) {
            Lit guard = work->nodes[node].guard;
            if (guard.x >= 0) clause.push(~guard);
            else if (guard.x != -1) throw std::logic_error("unlit CO guard");
        }
        CRef cr = ca.alloc(clause);
        clauses.push(cr); attachClause(cr); if (piLedger) piLedger->co_axioms.insert(cr);
        if (reasonAudit) {
            *reasonAudit << "CO " << epochVersion << ' ' << image->control.x;
            for (int j=0; j<ca[cr].size(); ++j) *reasonAudit << ' ' << ca[cr][j].x;
            *reasonAudit << '\n';
        }
        image->extensions.push_back({pair.first,pair.second,a,b});
        work->init_reasonable_edge(pair.first,pair.second,OC_NA,a);
        work->init_reasonable_edge(pair.second,pair.first,OC_NA,b);
        ++meter.co_pairs;
    }
}

void ClosureSolver::classifyResident(const std::set<int> &off)
{
    if (!piLedger) return;
    for (const auto &entry : piLedger->resident) {
        auto &birth = piLedger->births[entry.second];
        if (birth.version >= piLedger->version) continue;
        birth.dormant = false;
        const Clause &clause = ca[entry.first];
        for (int i=0; i<clause.size(); ++i)
            if (off.count(clause[i].x)) { birth.dormant = true; break; }
        if(reasonAudit) {
            *reasonAudit<<"OLDCLAUSE "<<epochVersion<<' '<<birth.id<<' '<<entry.first<<' '<<birth.dormant;
            for(int i=0;i<clause.size();++i)*reasonAudit<<' '<<clause[i].x;
            *reasonAudit<<'\n';
        }
    }
    for (const auto &u : piLedger->root_units)
        piLedger->births[u.second].dormant = off.count(mkLit(u.first, value(u.first) == l_False).x) != 0;
}

lbool ClosureSolver::runEpoch(const vec<Lit> &args, bool probe)
{
    args.copyTo(assumptions);
    meter = EpochMeter();
    auto &s=restartStudy;
    s.sample=RestartSample(); s.measuring=true; s.assigned.fill(0);
    for(int i=0;i<trail.size();++i) ++s.assigned[s.roles[var(trail[i])]];
    s.db.open(s.dbPath,epochVersion);
    meter.assumptions = args.size();
    for (int i=0; i<args.size(); ++i) (sign(args[i]) ? meter.negative : meter.positive)++;
    auto previousDecisions = decisions, previousConflicts = conflicts, previousProps = propagations;
    const double begin = epochClock();const uint64_t previousStarts=starts;
    lbool status = l_Undef;
    if (!probe) status = solve_();
    else {
        int next = 0;
        for (;;) {
            const double start = epochClock();
            CRef cr = epochPropagate();
            meter.joint += epochClock() - start;
            if (cr != CRef_Undef) { meter.diagnostic = "BOUNDARY_CONFLICT"; break; }
            if (!withinBudget()) { meter.diagnostic = "BOUNDARY_INTERRUPTED"; break; }
            next = decisionLevel();
            if (next == args.size()) { meter.diagnostic = "BOUNDARY_FIXPOINT"; break; }
            Lit p = args[next];
            ++meter.processed; meter.prefix = std::max(meter.prefix,uint64_t(next+1));
            if (value(p) == l_False) { meter.diagnostic = "BOUNDARY_FALSE_ASSUMPTION"; break; }
            newDecisionLevel();
            if (value(p) == l_True) ++meter.empty;
            else uncheckedEnqueue(p);
        }
        releaseTemporary();
        const double start = epochClock();
        cancelUntil(0);
        meter.rollback = epochClock() - start;
    }
    meter.boundary = epochClock() - begin;
    s.measuring=false; s.db.finish();
    meter.restarts = starts>previousStarts ? starts-previousStarts-1 : 0;
    meter.decisions = decisions - previousDecisions;
    meter.conflicts = conflicts - previousConflicts;
    meter.propagations = propagations - previousProps;
    if (decisionLevel() || work) throw std::logic_error("unfinished rollback");
    return status;
}
}
