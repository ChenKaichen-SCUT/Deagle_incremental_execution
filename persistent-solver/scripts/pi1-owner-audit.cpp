// Independent ELF link-time observation of the exact objects used by the session driver.
#include "minisat/core/ClosureSolver.h"
#include <cstdio>
#include <cstdlib>

namespace {
void *owner, *sat;
int closureCount, baseCount, calls;
void finish() {
    std::fprintf(stderr, "OWNER closure=%d minisat=%d queries=%d same_this=%d\n",
                 closureCount, baseCount, calls, owner == sat);
    if (closureCount != 1 || baseCount != 1 || calls != 2 || owner != sat) std::abort();
}
}
extern "C" void __real__ZN7Minisat13ClosureSolverC1Ev(void *);
extern "C" void __real__ZN7Minisat6SolverC2Ev(void *);
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
    return __real__ZN7Minisat13ClosureSolver8runEpochERKNS_3vecINS_3LitEEEb(p,args,probe);
}
