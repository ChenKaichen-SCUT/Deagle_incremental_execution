#ifndef CPROVER_GOTO_SYMEX_STAGE3_OBSERVER_H
#define CPROVER_GOTO_SYMEX_STAGE3_OBSERVER_H

#include <chrono>
#include <cstddef>
#include <string>

class goto_functionst;
class goto_symex_statet;
class symex_target_equationt;
class SSA_stept;

namespace stage3
{
using clockt = std::chrono::steady_clock;
bool enabled();
void redirect(const std::string &path);
void timing(const std::string &name, clockt::time_point start, clockt::time_point end);
void goto_model(const goto_functionst &functions);
std::size_t visit(const goto_symex_statet &state);
void name_event(const SSA_stept &step, const std::string &name);
void equation(const char *name, const symex_target_equationt &model);
std::string declare_theory_snapshot();
const std::string &observation_directory();
void finish(int exit_code);
void gate(const char *state, const char *command);
}
#endif
