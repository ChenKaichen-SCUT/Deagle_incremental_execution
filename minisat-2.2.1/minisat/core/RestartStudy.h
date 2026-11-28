#ifndef MINISAT_RESTART_STUDY_H
#define MINISAT_RESTART_STUDY_H

#include <array>
#include <cstdint>
#include <fstream>
#include <string>
#include <vector>

namespace Minisat {
enum VarRole { Program, Selector, DynamicCO, Constant, RoleCount };

struct RestartSample {
    int installed = 0, high = 0, timing = 0;
    uint64_t first = 0, repeated = 0, ordinary = 0, kept = 0, incomplete = 0, unsafe = 0, budgets = 0;
    uint64_t jumps[3]{}, prefixJumps[3]{}, removed[3]{};
    uint64_t calls[2]{}, available[2]{}, visited[2]{}, dequeued[RoleCount]{}, watcher[RoleCount]{};
    double progress[2]{}, intervals[3]{}, since = 0, switchSeconds = 0;
    void timePrefix(int kind);
    void installedFrame() {
        if (installed < high) ++repeated; else { ++high; ++first; }
        ++installed;
    }
    void jump(int oldLevel, int target, int kind) {
        if (target < oldLevel) {
            ++jumps[kind];
            if (target < installed) { ++prefixJumps[kind]; removed[kind] += installed-target; }
        }
    }
};

// Each binary segment expands to a sequence of exact native predicate tuples.
// start + i*step (0 <= i < count), with max_learnts constant over the segment.
class PredicateTrace {
    using Tuple = std::array<int64_t,6>;
    std::ofstream out;
    Tuple first{}, last{}, step{};
    uint64_t count = 0;
    double threshold = 0;
    void flush();
public:
    bool active() const { return out.is_open(); }
    void open(const std::string &prefix, unsigned version);
    void add(int learnts, int program, int selectors, int other, int assigned, uint64_t literals, double limit);
    void finish();
};

struct RestartStudy {
    bool retain = false, skipZero = false, ledger = true, measuring = false;
    std::string dbPath;
    PredicateTrace db;
    RestartSample sample;
    std::vector<unsigned char> roles;
    std::array<int,RoleCount> assigned{};
    void tag(int v, VarRole r) {
        if (size_t(v) >= roles.size()) roles.resize(size_t(v)+1, Program);
        roles[v] = r;
    }
};
}
#endif
