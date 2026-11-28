#ifndef MINISAT_EPOCH_SESSION_H
#define MINISAT_EPOCH_SESSION_H

#include "SolverTypes.h"
#include "RestartStudy.h"
#include <array>
#include <chrono>
#include <cstdint>
#include <map>
#include <ostream>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

namespace Minisat {
inline double epochClock() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

enum class ClauseFamily { boolean, mixed, theory };
enum class NativeUse { watcher, conflict, analysis, minimization };
struct NativeBirth {
    unsigned version, id;
    ClauseFamily family;
    std::array<uint64_t,4> hits{};
    bool unit, dormant = false;
    NativeBirth(unsigned v, unsigned i, ClauseFamily f, bool u) : version(v), id(i), family(f), unit(u) {}
};

// Observation only. No parent edges or clause export. Keys follow the native allocator.
struct NativeLedger {
    std::ostream *audit = nullptr;
    unsigned version = 0;
    bool mixed = false;
    std::unordered_map<CRef,unsigned> resident;
    std::set<CRef> co_axioms;
    std::vector<NativeBirth> births;
    std::unordered_map<Var,unsigned> root_units;
    std::vector<unsigned char> root_theory;
    uint64_t collections = 0, reductions = 0;
    void born(CRef ref, ClauseFamily family, Var unit = var_Undef) {
        unsigned id = births.size();
        births.emplace_back(version, id, family, unit != var_Undef);
        if (audit) *audit<<"BIRTH "<<version<<' '<<id<<' '<<unsigned(family)<<' '<<ref<<' '<<unit<<'\n';
        if (unit != var_Undef) root_units[unit] = id;
        else resident[ref] = id;
    }
    void use(CRef ref, NativeUse kind) {
        auto it = resident.find(ref);
        if (it == resident.end()) {
            if(kind==NativeUse::analysis || kind==NativeUse::minimization) mixed |= co_axioms.count(ref)!=0;
            return;
        }
        auto &b = births[it->second];
        if (kind == NativeUse::analysis || kind == NativeUse::minimization)
            mixed |= b.family != ClauseFamily::boolean;
        if (b.version < version) {
            ++b.hits[unsigned(kind)];
            if (audit) *audit<<"USE "<<version<<' '<<b.version<<' '<<b.id<<' '<<unsigned(kind)<<' '<<ref<<'\n';
        }
    }
    void root(Var v, NativeUse kind) {
        if (unsigned(v) < root_theory.size()) mixed |= root_theory[v] != 0;
        auto it = root_units.find(v);
        if (it != root_units.end() && births[it->second].version < version)
            ++births[it->second].hits[unsigned(kind)];
    }
    void relocate(ClauseAllocator &old) {
        std::unordered_map<CRef,unsigned> moved;
        moved.reserve(resident.size());
        for (const auto &r : resident)
            if (old[r.first].reloced()) moved.emplace(old[r.first].relocation(), r.second);
        resident.swap(moved);
        std::set<CRef> ext;for(auto ref:co_axioms)if(old[ref].reloced())ext.insert(old[ref].relocation());
        co_axioms.swap(ext);
        ++collections;
    }
};

struct EpochNode {
    std::string name, address;
    bool read, write;
    int location;
};
struct EpochEdge { int from, to; std::string kind; Lit port; };
struct EpochImage {
    Lit control;
    std::vector<EpochNode> nodes;
    std::vector<EpochEdge> edges;
    std::vector<std::pair<int,Lit>> guards;
    struct CoBinding { int from, to; Lit forward, backward; };
    std::vector<CoBinding> extensions;
};
struct EpochMeter {
    uint64_t assumptions = 0, processed = 0, prefix = 0, frames = 0, empty = 0;
    uint64_t bcp = 0, pushes = 0, pops = 0, rebuilds = 0, replay = 0, replay_literals = 0;
    uint64_t theory_props = 0, cycles = 0, co_pairs = 0, delayed_conflicts = 0;
    uint64_t discarded_queued = 0, restarts = 0;
    uint64_t positive = 0, negative = 0, max_level = 0, decisions = 0, conflicts = 0, propagations = 0;
    double activation = 0, joint = 0, rollback = 0, boundary = 0;
    std::string diagnostic;
};
}
#endif
