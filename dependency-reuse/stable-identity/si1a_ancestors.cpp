// Offline SI-1A census of archived reasons. Reads only the frozen audit DAG and D's leaf verdicts.
#include "../d4/transport_graph.h"
#include <fstream>
#include <iostream>
#include <map>
#include <string>

namespace
{
enum Loss : unsigned { BooleanUntranslated = 1, BooleanAbsent = 2, TheoryUnknown = 4,
                       TheoryChanged = 8, Scoped = 16 };

std::ifstream table(const char *name, const char *header)
{
  std::ifstream input(name);
  std::string line;
  d42::need(bool(std::getline(input, line)) && line == header, "table header");
  return input;
}

unsigned input_loss(const std::string &status)
{
  if(status == "matched") return 0;
  if(status == "unmapped") return BooleanUntranslated;
  if(status == "mapped_absent") return BooleanAbsent;
  d42::need(status == "scope", "unknown input status");
  return Scoped;
}

void count(char **argv)
{
  using namespace d42;
  Graph graph(argv[1]);
  auto inputs = table(argv[2], "occurrence\tuse\tstatus\tp1_permanent_occurrence");
  auto theories = table(argv[3], "op\ta\tb\tc\tuse\tstatus");
  auto catalog = table(argv[4], "ordinal\tnative_id\tflags\thas_b\tsupport_alive\tconclusion_mapped\teligible");
  std::map<unsigned,unsigned> b;
  std::map<Fact,unsigned> t;
  unsigned occ, use;
  int witness;
  std::string status;
  while(inputs >> occ >> use >> status >> witness)
    need(b.emplace(occ, input_loss(status)).second, "duplicate input receipt");
  Fact fact;
  while(theories >> fact[0] >> fact[1] >> fact[2] >> fact[3] >> use >> status)
  {
    need(status == "M" || status == "C" || status == "U", "unknown theory status");
    need(t.emplace(fact, status == "C" ? TheoryChanged : status == "U" ? TheoryUnknown : 0).second,
         "duplicate theory receipt");
  }
  need(inputs.eof() && theories.eof(), "malformed receipt");
  auto live = graph.reach();
  std::vector<unsigned char> loss(graph.nodes.size());
  loss[0] = Scoped;
  for(Id i=1; i<graph.nodes.size(); ++i)
  {
    if(!live[i]) continue;
    const Node &n = graph.nodes[i];
    if(n.type == InputLeaf) loss[i] = b.at(n.payload);
    else if(n.type == FactLeaf) loss[i] = t.at(graph.facts.at(n.payload));
    else if(n.type == OpaqueLeaf || n.type == MissingLeaf) loss[i] = Scoped;
    for(Id j=graph.begin(i); j<n.end; ++j) loss[i] |= loss.at(graph.parents[j]);
  }
  std::cout << "ordinal\tpermanent\tmapped\tmask\n";
  unsigned ordinal, original, flags, has_b, alive, mapped, eligible;
  for(unsigned i=0; i<graph.births.size(); ++i)
  {
    need(bool(catalog >> ordinal >> original >> flags >> has_b >> alive >> mapped >> eligible), "missing birth");
    const auto &birth = graph.births[i];
    const auto &node = graph.nodes[birth.node];
    const bool permanent = !(node.flags & 7);
    const auto mask = loss[birth.node];
    need(ordinal == i+1 && original == birth.original && flags == node.flags && has_b == node.has_b,
         "misaligned native birth");
    need(alive == (permanent && mask == 0) && eligible == (alive && mapped), "exact-support disagreement");
    std::cout << ordinal << '\t' << permanent << '\t' << mapped << '\t' << unsigned(mask) << '\n';
  }
  catalog >> std::ws;
  need(catalog.eof(), "extra native births");
}
}

int main(int argc, char **argv)
{
  if(argc != 5) return 2;
  try { count(argv); }
  catch(const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
