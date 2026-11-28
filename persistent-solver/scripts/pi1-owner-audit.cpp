// Independent ELF link-time observation of the exact objects used by the session driver.
#include "minisat/core/ClosureSolver.h"
#include <cstdio>
#include <cstdlib>

namespace {
void *owner, *sat;
int closureCount, baseCount, calls;
uint64_t pushes, pops, unwound;
void finish() {
    std::fprintf(stderr, "OWNER closure=%d minisat=%d queries=%d same_this=%d\n",
                 closureCount, baseCount, calls, owner == sat);
    if (closureCount != 1 || baseCount != 1 || calls != 2 || owner != sat) std::abort();
}
}
extern "C" void __real__ZN7Minisat13ClosureSolverC1Ev(void *);
extern "C" void __real__ZN7Minisat6SolverC2Ev(void *);
extern "C" void __real__ZN7Minisat7closure10push_scopeEv(Minisat::closure *);
extern "C" void __real__ZN7Minisat7closure9pop_scopeEi(Minisat::closure *, int);
extern "C" void __wrap__ZN7Minisat7closure10push_scopeEv(Minisat::closure *g) {
    ++pushes;
    __real__ZN7Minisat7closure10push_scopeEv(g);
}
extern "C" void __wrap__ZN7Minisat7closure9pop_scopeEi(Minisat::closure *g, int target) {
    ++pops;
    unwound += g->get_decision_level() - target;
    __real__ZN7Minisat7closure9pop_scopeEi(g,target);
}
extern "C" Minisat::lbool __real__ZN7Minisat13ClosureSolver8runEpochERKNS_3vecINS_3LitEEEb(
    Minisat::ClosureSolver *, const Minisat::vec<Minisat::Lit> &, bool);

extern "C" void __wrap__ZN7Minisat13ClosureSolverC1Ev(void *p) {
    if (closureCount++ == 0) std::atexit(finish);
    owner = p;
    __real__ZN7Minisat13ClosureSolverC1Ev(p);
}
extern "C" void __wrap__ZN7Minisat6SolverC2Ev(void *p) {
    ++baseCount; sat = p;
    __real__ZN7Minisat6SolverC2Ev(p);
}
extern "C" Minisat::lbool __wrap__ZN7Minisat13ClosureSolver8runEpochERKNS_3vecINS_3LitEEEb(
    Minisat::ClosureSolver *p, const Minisat::vec<Minisat::Lit> &args, bool probe) {
    if (p != owner || p != sat) std::abort();
    ++calls;
    pushes = pops = unwound = 0;
    auto result = __real__ZN7Minisat13ClosureSolver8runEpochERKNS_3vecINS_3LitEEEb(p,args,probe);
    std::fprintf(stderr, "SCOPE version=%d push_calls=%llu pop_calls=%llu popped_frames=%llu destroyed_frames=%llu\n",
                 calls, (unsigned long long)pushes, (unsigned long long)pops,
                 (unsigned long long)unwound, (unsigned long long)(pushes-unwound));
    return result;
}
