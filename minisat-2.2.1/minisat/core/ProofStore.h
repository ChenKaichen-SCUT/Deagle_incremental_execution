#ifndef MINISAT_PROOF_STORE_H
#define MINISAT_PROOF_STORE_H

#include "SolverTypes.h"
#include <cstdint>
#include <cstdio>
#include <string>
#include <initializer_list>
#include <vector>

namespace Minisat
{
class Solver;
using ProofId = uint32_t;
enum ProofKind : uint32_t
{
    Missing, BooleanInput, QueryInput, UnknownInput, Shortened, RootUnit, Learned,
    TheoryConflict, TheoryReason, DynamicCO, RootConflict, TheoryEmpty,
    TheoryDeclaration, TheoryInference, TheoryLemma, RetiredBirth
};
enum ProofFlag : uint32_t { Theory = 1, Query = 2, Incomplete = 4, CertifiedTheory = 8 };
enum TheoryOp : uint32_t
{
    Config, PODecl, APODecl, RFDecl, GuardDecl, SchemaDecl, AddressDecl, BlockDecl,
    POEdge, APOEdge, RFEdge, GuardOn, Lift, Transitive, WSRule, FRRule, CycleRule, PreventRF, TripletRule
};
struct TheoryRecord { ProofId id; TheoryOp op; int32_t a,b,c; };
enum InputAction : uint32_t { Accepted, Satisfied, Tautology, AlreadyInconsistent };
enum AssignmentSource : uint32_t { ClauseReason, ExplicitUnit, Decision, Assumption, Unexplained };
struct ProofNode { uint32_t lit_end, edge_end, kind, flags; };
struct ProofEdge { ProofId parent; int32_t pivot; }; // pivot occurs in parent, its complement in the running clause
struct InputRecord { ProofId leaf, result; uint32_t action; int32_t witness; };
struct SatisfiedRemoval { ProofId clause, unit; int32_t literal; };
struct EvictedLearn { ProofId id, last_node; };
struct LearnRecord { ProofId id; uint32_t uip_edges, min_edges; };
enum Stat { Collections, Removals, Reductions, MinSuccess, MinFailure, SearchNS, Queries,
            ByClause, ByUnit, ByDecision, ByAssumption, ByUnexplained,
            ChangedRefs, ChangedLearnRefs, ReverseNS, WriteSectionsNS, ArenaBytes, RecorderBytes, StatCount };

// Proofs are immutable. Only the current allocator references and scratch space follow the solver.
class ProofStore
{
    std::vector<ProofId> refs, units;
    std::vector<int> position;
    std::vector<ProofEdge> chain;
    std::vector<int> roots, minimized, trial;
    ProofId pending = 0, next_unit = 0;
    AssignmentSource next_source = Unexplained;
    FILE *output = nullptr;
    const char *scope;
    std::vector<uint32_t> theory_slots, condition_by_proof, condition_slots, theory_marks, discharge_cache;
    struct Condition { uint32_t a,b; }; // b==UINT32_MAX means one raw assumption literal
    std::vector<Condition> conditions{{0,0}};
    uint32_t internCondition(uint32_t a,uint32_t b);
    std::vector<int> expected_condition, actual_condition;
    std::vector<ProofId> condition_stack;
    std::vector<ProofEdge> theory_parents;
    size_t theoryIndex(ProofId) const;
    ProofId internTheory(ProofKind, TheoryOp, int, int, int, const ProofId *, size_t);
    void growTheoryIndex();

    void addReason(Solver &, CRef, Lit);
    void appendRoots();
    ProofId root(int assigned) const;
    ProofId append(ProofKind, const int *, size_t, const std::vector<ProofEdge> &);
    template<class C> ProofId clause(ProofKind k, const C &c, const std::vector<ProofEdge> &edges)
    {
        scratch.clear();
        for(int i=0;i<c.size();++i) scratch.push_back(c[i].x);
        return append(k,scratch.data(),scratch.size(),edges);
    }
    std::vector<int> scratch;
public:
    // The four contiguous sections below are also the offline checker interface.
    std::vector<ProofNode> nodes;
    std::vector<int32_t> lits;
    std::vector<ProofEdge> edges;
    std::vector<InputRecord> inputs;
    std::vector<LearnRecord> learned;
    std::vector<EvictedLearn> evicted;
    std::vector<SatisfiedRemoval> satisfied_removals;
    std::vector<ProofId> residents, root_units, terminals, offsets, children;
    bool d3 = false;
    bool triplets = false, compact = false, eager_triplets=false;
    std::vector<ProofId> origins; // compact ID to native P0 ID, including the sentinel
    uint64_t project_ns=0;
    void projectBirths();
    std::vector<char> graph_receipt; // one exact static declaration stream per native graph
    uint64_t discharge_stats[3] = {}; // missing certificate, condition mismatch, exact match
    std::vector<TheoryRecord> theory_records;
    ProofId decl(TheoryOp op,int a=-1,int b=-1,int c=-1);
    ProofId rule(TheoryOp op,int a,int b,int c,const std::vector<ProofId> &parents);
    ProofId rule(TheoryOp op,int a,int b,int c,std::initializer_list<ProofId> parents);
    ProofId lemma(ProofKind boundary,const vec<Lit> &actual,ProofId reason);
    uint64_t stats[StatCount] = {};
    ProofStore(); // in-memory graph or archive reader
    ProofStore(const std::string &path, const char *scope);
    ~ProofStore();
    ProofStore(const ProofStore &) = delete;
    ProofStore &operator=(const ProofStore &) = delete;
    bool write(int exit_code);
    int read(const std::string &path);
    void buildReverse();
    std::vector<uint8_t> invalidate(const std::vector<ProofId> &seeds) const;
    std::vector<uint8_t> invalidatedInputs(const std::vector<uint8_t> &matched,
                                          const std::vector<uint8_t> &declaration_matched={}) const;
    uint32_t litBegin(ProofId i) const { return i ? nodes[i-1].lit_end : 0; }
    uint32_t edgeBegin(ProofId i) const { return i ? nodes[i-1].edge_end : 0; }
    void input(const vec<Lit> &);
    void skipInput(InputAction, int lit = -1);
    ProofId acceptInput(Solver &, const vec<Lit> &);
    void bind(CRef, ProofId);
    ProofId ref(CRef r) const { return r<refs.size() ? refs[r] : 0; }
    void forget(CRef);
    void removedSatisfied(Solver &, CRef);
    void relocated(const ClauseAllocator &, uint32_t new_size);
    void newVariable() { position.push_back(-1); units.push_back(0); }
    void tag(ProofId id, AssignmentSource source) { next_unit=id; next_source=source; }
    void assignment(Solver &, Lit, CRef);
    void rootConflict(Solver &, CRef);
    void theoryEmpty();
    ProofId opaque(ProofKind kind, const vec<Lit> &c) { return clause(kind,c,{}); }
    void beginAnalysis() { chain.clear(); roots.clear(); minimized.clear(); }
    void analysisParent(Solver &s, CRef cr, Lit pivot) { addReason(s,cr,pivot); }
    void beginTrial() { trial.clear(); }
    void visitTrial(Var v) { trial.push_back(v); }
    void endTrial(bool success);
    void basicMin(Var v) { minimized.push_back(v); }
    void finishAnalysis(Solver &, const vec<Lit> &);
    ProofId lastLearned() const { return pending; }
    void snapshot(const vec<CRef> &db);
};
}
#endif
