// __SZH_ADD_BEGIN__

#ifndef CLOSURESOLVER_H
#define CLOSURESOLVER_H

#include <map>
#ifdef DEAGLE_PI1
#include <memory>
#endif


#include "../../minisat/mtl/Queue.h"
#include "../../minisat/core/Solver.h"

#include "ClosureTypes.h"
#include "Closure.h"



typedef std::vector<std::pair<std::pair<std::string, std::string>, std::pair<Minisat::Lit, std::string> > > oc_edge_tablet;
typedef std::map<std::string, Minisat::Lit> oc_guard_mapt;
typedef std::map<std::string, int> oc_location_mapt;

namespace Minisat
{

class ClosureSolver : public Solver
{
    closure graph;
#ifdef DEAGLE_PI1
    std::unique_ptr<closure> work;
    uint64_t instanceSerial = 0;
    EpochImage *image = nullptr;
    int barrier = 0, cursor = 0, workFloor = 0, workDepth = 0;
    bool initialCycle = false, probing = false;
    CRef temporary = CRef_Undef;
    std::map<int,int> queuedSite;
    int currentSite=0;
public:
    template<class Range> void assignGenerated(Lit p, Range &reason, int site) {
        if(image && assigned_literals.count(p)==0) queuedSite[p.x]=site;
        assign_literal(p,reason);
    }
private:
    EpochMeter meter;
    unsigned epochVersion = 0;
    bool prefixSafe() const;
    double measuredProgress(bool exit);
    void restartAudit(const char *name, int target);
public:
    void configureRestartStudy(const char *mode, const char *ledger, const char *db);
    void databaseSnapshot(const std::set<int>& off, unsigned active, unsigned total, const char *phase);
    std::string restartReceipt() const;
#ifdef DEAGLE_PI1G_OBSERVER
    void observeGroupLearning(const char *phase);
#endif
private:
    std::ostream *reasonAudit = nullptr;
    std::map<std::string,int> ownedOrder;
    std::vector<std::string> ownedWrites;
    CRef epochPropagate();
    CRef materialize(Lit conclusion, const literal_set& conditions, bool cycle);
    void releaseTemporary();
    void startGraph();
    void dropGraph();
    void installCo();
public:
    uint64_t nativeInstance() const { return instanceSerial; }
    void epochContext(EpochImage &spec, int barrierFrames, unsigned version, NativeLedger &ledger);
    lbool runEpoch(const vec<Lit> &args, bool probe);
    const EpochMeter& epochMetrics() const { return meter; }
    const std::map<std::string,int>& resultOrder() const { return ownedOrder; }
    std::vector<std::string> &sessionWrites(std::vector<std::string> &stock) { return image ? ownedWrites : stock; }
    void auditTo(std::ostream *stream) { reasonAudit = stream; }
    int currentLevel() const { return decisionLevel(); }
    void collectForTest() { reduceDB(); garbageCollect(); }
    void classifyResident(const std::set<int> &off);
    std::vector<Var> allocatedCO;
private:
#endif


    oc_edge_tablet oc_edge_table;
    oc_guard_mapt oc_guard_map;
    oc_location_mapt oc_location_map;

    std::vector<std::pair<Lit, literal_set>> literals_to_assign;
    std::set<Lit> assigned_literals;

    int conflict_cycle = 0;
    int theory_propagation = 0;

    int attempt_adding_co = 0;
    int added_co_clauses = 0;

protected:
    CRef propagate();
    void cancelUntil(int level);
    void newDecisionLevel();
    lbool search(int nof_conflicts);
    void analyze(CRef confl, vec<Lit>& out_learnt, int& out_btlevel);
public:
    ClosureSolver();
    void init();
    void save_raw_graph(oc_edge_tablet& _oc_edge_table, oc_guard_mapt& _oc_guard_map, oc_location_mapt& _oc_location_map, std::map<std::string, int>& _oc_result_order);
    void set_graph();

    lbool solve_();
    bool solve() { budgetOff(); assumptions.clear(); return solve_() == l_True; }
    inline bool solve(const vec<Lit>& assumps){ budgetOff(); assumps.copyTo(assumptions); return solve_() == l_True; }
    inline lbool solveLimited(const vec<Lit>& assumps){ assumps.copyTo(assumptions); return solve_(); }

    void show_rf();

    void assign_literal(Lit l, literal_set& lv);
    void assign_literal(Lit l, literal_vector& lv);

    void apply_literal_assignment();

    std::vector<std::string> get_write_order();

    //interface
    virtual void addOC(std::string from, std::string to, std::string type, Lit related_lit) override;
    virtual void addGuard(std::string node, Lit guard) override;
    void setRawGraph(oc_edge_tablet& _oc_edge_table, oc_guard_mapt& _oc_guard_map);

    std::map<std::string, int>* oc_result_order;

    void addMissingCoClauses();
};

}


#endif //CLOSURESOLVER_H

// __SZH_ADD_END__