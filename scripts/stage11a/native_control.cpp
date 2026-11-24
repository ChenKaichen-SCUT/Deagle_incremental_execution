// Research driver. Link the fixed native archives without patching solver code.
#include "minisat/core/ClosureSolver.h"
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <string>

int main(int argc, char **argv)
{
  if(argc != 2)
    return 2;
  std::ifstream input(argv[1]);
  if(!input)
    return 2;
  Minisat::ClosureSolver solver;
  oc_edge_tablet edges;
  oc_guard_mapt guards;
  oc_location_mapt locations;
  std::map<std::string, int> order;
  Minisat::vec<Minisat::Lit> selected;
  Minisat::Lit always;
  always.x = -1; // save_raw_graph's encoding of an unconditional declaration.
  std::string line;
  int index = 0;
  while(std::getline(input, line))
  {
    std::istringstream row(line);
    std::string tag, a, b, extra;
    if(!(row >> tag >> a))
      return 2;
    if(tag == "write")
    {
      guards[a] = always;
      locations[a] = ++index;
    }
    else if((tag == "po" || tag == "apo" || tag == "rf") && row >> b)
    {
      auto literal = always;
      if(tag == "rf")
      {
        literal = Minisat::mkLit(solver.newVar());
        selected.push(literal);
      }
      edges.push_back({{a, b}, {literal, tag}});
    }
    else
      return 2;
    if(row >> extra)
      return 2;
  }
  solver.save_raw_graph(edges, guards, locations, order);
  const int result = Minisat::toInt(solver.solveLimited(selected));
  std::cout << "native_lbool " << result << "\n";
  return result == 0 || result == 1 ? 0 : 3;
}
