#ifndef CPROVER_GOTO_SYMEX_STAGE4_SC_H
#define CPROVER_GOTO_SYMEX_STAGE4_SC_H
#include "memory_model.h"
#include <map>

// One ephemeral view per address or per thread. Cached records own only typed
// expressions, prefix slots and metadata. All iterators belong to the current run.
class stage4_sct
{
  using iterator = partial_order_concurrencyt::event_it;
  memory_model_baset &mm;
  symex_target_equationt &eq;
  bool active, eligible=true, hit=false;
  irept *record=nullptr;
  std::map<std::string,iterator> events;
  std::map<std::size_t,iterator> slots;
  std::size_t edge_start=0;
  iterator step_start;
  irept signature;
  void include(iterator);
  bool check(const std::string &,const std::string &);
  void replay_reads();
public:
  stage4_sct(memory_model_baset &,symex_target_equationt &);
  bool address(const std::string &,const std::vector<iterator> &,const std::vector<iterator> &);
  void begin_read();
  void end_read(iterator);
  bool thread(unsigned,const std::vector<iterator> &,const std::set<std::pair<std::string,std::string>> &);
  void end_thread();
};
#endif
