#ifndef CPROVER_GOTO_SYMEX_STAGE4_INCREMENTAL_H
#define CPROVER_GOTO_SYMEX_STAGE4_INCREMENTAL_H
#include <util/irep.h>
#include <chrono>
#include <string>

class goto_modelt;
class goto_symex_statet;
class symex_target_equationt;
class ui_message_handlert;
class optionst;
class SSA_stept;
class path_storaget;
namespace stage4
{
using clockt = std::chrono::steady_clock;
bool configured();
bool frontend(goto_modelt &, ui_message_handlert &, const optionst &);
void before_step(const goto_symex_statet &, symex_target_equationt &, const path_storaget &);
void finish(int);
clockt::time_point suffix_start(clockt::time_point full_start);
bool collecting();
bool restoring();
const std::string &root();
void save_irep(const std::string &, const irept &);
irept load_irep(const std::string &);
void save_cache();
irept &cache();
void count(const std::string &, std::size_t n=1);
void region(const std::string &family, const std::string &name, bool reused);
}
#endif
