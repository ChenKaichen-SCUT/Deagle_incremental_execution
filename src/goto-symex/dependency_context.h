#ifndef CPROVER_GOTO_SYMEX_DEPENDENCY_CONTEXT_H
#define CPROVER_GOTO_SYMEX_DEPENDENCY_CONTEXT_H

#include "symex_target.h"
#include <util/dependency_manifest.h>

class goto_functionst;
class namespacet;
class goto_symex_statet;
namespace dependency_manifest
{
void index_sites(const goto_functionst &functions);
void context(goto_symex_statet &state);
void birth(unsigned child, const symex_targett::sourcet &parent);
int checked_context(const symex_targett::sourcet &source);
std::string designator(const exprt &expression);
std::string scalar_type(const typet &type);
unsigned aggregate_layout(const typet &, const namespacet &);
unsigned recorded_layout(const typet &);
}
#endif
