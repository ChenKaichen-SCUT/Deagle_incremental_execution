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
extern char scope;
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
  explicit scopet(char value) : previous(scope) { if(stream) scope = value; }
  ~scopet() { if(stream) scope = previous; }
};
}
#endif
