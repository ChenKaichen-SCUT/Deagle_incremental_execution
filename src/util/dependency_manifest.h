// D1 side channel for the single-process native Closure verifier.
#ifndef CPROVER_UTIL_DEPENDENCY_MANIFEST_H
#define CPROVER_UTIL_DEPENDENCY_MANIFEST_H

#include <cstdio>
#include <initializer_list>
#include <string>
#include <vector>

namespace dependency_manifest
{
extern std::FILE *stream;
extern bool record_layouts;
extern bool triplets, compact_proof, identities41, eager_triplets, light42, quality42;
extern char scope;
extern std::string proof_path, dense_path, boundary_trace;
extern bool no_quality43, opaque43;
extern bool (*finish_dense)(int);
extern bool (*finish_boundaries)();
extern std::string d4_library, d4_out, d4_tools, d4_mode, search_log;
extern bool theory_proofs;
extern bool (*finish_proof)(int);
void open(const std::string &filename);
bool finish(int exit_code);
std::string escape(const std::string &field);
std::string tuple(const std::vector<std::string> &fields);
void row(const char *tag, const std::vector<std::string> &fields);
void gate(const char *op, int output, const std::vector<int> &inputs);

class scopet
{
  char previous;
public:
  explicit scopet(char value) : previous(scope) { if(stream || !proof_path.empty()) scope = value; }
  ~scopet() { if(stream || !proof_path.empty()) scope = previous; }
};
}
#endif
