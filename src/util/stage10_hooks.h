#pragma once
#include <stdexcept>
#include "../../minisat-2.2.1/minisat/core/Solver.h"
namespace s10 {
using Take=Minisat::CRef(*)(Minisat::Solver*,const Minisat::vec<Minisat::Lit>&);
using Born=void(*)(Minisat::Solver*,const Minisat::vec<Minisat::Lit>&,Minisat::CRef);
extern Take take;
extern Born born;
}
