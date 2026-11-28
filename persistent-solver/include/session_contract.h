#ifndef DEAGLE_PI_SESSION_CONTRACT_H
#define DEAGLE_PI_SESSION_CONTRACT_H

// Native PI-1 backend. Transactions own all local model data.
#include <cstdint>
#include <memory>
#include <mutex>
#include <ostream>
#include <string>
#include <utility>
#include <vector>

namespace deagle_pi
{
struct LocalVar { std::uint32_t id; };
struct GlobalVar { std::uint32_t id; };
struct VersionId { std::uint64_t id; };
struct QueryId { std::uint64_t id; };
struct EventId { std::uint32_t local; };

enum class LiteralKind { variable, constant_false, constant_true };
template<class Variable>
struct SignedLiteral
{
    LiteralKind kind;
    Variable variable; // Read only for kind == variable.
    bool negated;      // Sign of the variable literal. Constants have canonical sign false.
};

using LocalLit = SignedLiteral<LocalVar>;
using GlobalLit = SignedLiteral<GlobalVar>;
using Clause = std::vector<LocalLit>;
struct Selector { GlobalVar variable; }; // A dedicated positive variable, separate from program atoms.

enum class AtomRole { ordinary, rf, guard, race, co };
struct AtomDescription
{
    LocalVar variable;
    std::vector<AtomRole> roles; // A native variable may also carry multiple theory bindings.
    std::vector<std::string> identity_witnesses;
};

enum class InputScope { model, query };
struct InputOccurrence
{
    InputScope scope;
    Clause literals;
    std::uint64_t occurrence;
};

enum class Relation { po, apo, rf, race };
struct Edge
{
    Relation relation;
    EventId from, to;
    LocalLit condition; // constant_true for unconditional facts
};
struct Event
{
    std::string key, address_class;
    bool reads, writes, initial;
    std::int64_t location;
};
struct TheorySpec
{
    std::vector<Event> events; // EventId indexes this immutable transaction-local directory.
    std::vector<Edge> edges;
    std::vector<std::pair<EventId, LocalLit>> guards;
    std::vector<std::vector<EventId>> atomic_blocks;
    std::vector<std::pair<EventId, std::vector<EventId>>> candidate_writes;
    std::string rules_version;
};
struct QueryDescriptor
{
    QueryId id;
    std::uint32_t native_variable_count_at_boundary;
    std::vector<AtomDescription> new_query_atoms; // Includes allocations by later property queries.
    std::vector<std::string> properties, unwind_obligations;
    std::vector<LocalLit> goals, native_assumptions;
    std::vector<InputOccurrence> scoped_inputs; // Includes query-local blocking and delayed definitions.
};
struct ModelTransaction
{
    std::string complete_configuration; // Full canonical ABI/SC/encoding/options payload, compared by content.
    std::uint32_t native_variable_count;
    std::vector<AtomDescription> atoms;
    std::vector<InputOccurrence> inputs;
    TheorySpec graph;
    struct Match { LocalVar previous; LocalLit positive_image; std::string certificate; };
    // Receipts supplied by the authenticated model reader. Pair certificates name the actual predecessor.
    std::string model_receipt, predecessor_receipt;
    std::vector<Match> certified_matches; // Arrive with the new transaction only.
    std::vector<std::pair<EventId,EventId>> certified_events;
    QueryDescriptor first_query; // Sealed after eager conversion at the actual SAT boundary.
};

struct CanonicalConstraint
{
    InputScope scope;
    QueryId query_context; // Interpreted only in query scope. Full descriptor equality gates sharing.
    std::vector<GlobalLit> content;
    Selector selector; // Binding immutable for the lifetime of the session.
};
struct QueryResult
{
    enum class Status { sat, unsat, unknown, failed } status;
    enum class Value { false_value, true_value, unassigned };
    VersionId version;
    QueryId query;
    std::vector<Value> local_assignment;
    std::vector<LocalLit> failed_native_assumptions;
    std::vector<std::pair<std::string, int>> event_order;
    std::vector<std::pair<std::string, std::string>> property_results;
    std::string visible_witness;
};
enum class SessionState { idle, installing, ready, solving, aborted, failed };

class PersistentClosureSession
{
public:
    PersistentClosureSession();
    ~PersistentClosureSession();
    PersistentClosureSession(const PersistentClosureSession &) = delete;
    PersistentClosureSession &operator=(const PersistentClosureSession &) = delete;
    VersionId append_version(ModelTransaction transaction);
    QueryResult solve_query(VersionId version, QueryId query);
    QueryId append_query(VersionId version, QueryDescriptor descriptor);
    struct Statistics {
        std::uint64_t solver_construct_count = 0, old_learnt_export_count = 0, old_learnt_import_count = 0, per_clause_reproof_count = 0;
        std::uint64_t global_vars = 0, program_vars = 0, selectors = 0, co_vars = 0, reused = 0, fresh = 0, rejected_ports = 0;
        std::uint64_t occurrences = 0, unique_inputs = 0, skipped = 0, graph_generations = 0;
        double install_seconds = 0, assumption_build_seconds = 0;
        std::string receipt; // Per-query native counters and resident/hit populations (JSON).
    };
    SessionState state() const;
    Statistics statistics() const;
    void close();
    void probe_boundary(VersionId version, QueryId query); // No ordinary decisions or SAT result.
    void set_audit_output(std::ostream *owned_by_caller);
    void set_assumption_output(std::ostream *owned_by_caller);
    void first_restart_for_test(int conflicts);
    void collect_at_boundary();
    void interrupt_next_query();
    void clear_interrupt();
private:
    struct Backend; // Sole owner of one ClosureSolver. Owns a replaceable Closure runtime generation.
    std::unique_ptr<Backend> backend;
    Backend &live() const;
    mutable std::mutex access;
    Statistics final_statistics;
};
}
#endif
