#include "dependency_manifest.h"
#include "dependency_group_sources.h"
#include <stdexcept>

namespace dependency_manifest
{
std::FILE *stream = nullptr;
char scope = 'U';
bool record_layouts = false;
bool triplets=false, compact_proof=false, identities41=false, eager_triplets=false, light42=false, quality42=false;
std::string proof_path, dense_path, boundary_trace;
bool no_quality43=false, opaque43=false;
bool (*finish_dense)(int)=nullptr;
bool (*finish_boundaries)()=nullptr;
std::string d4_library, d4_out, d4_tools, d4_mode, search_log;
bool theory_proofs = false;
bool (*finish_proof)(int) = nullptr;

void open(const std::string &filename)
{
  if(stream || !(stream = std::fopen(filename.c_str(), "wbx")))
    throw std::runtime_error("expected a new writable D1 manifest: " + filename);
  std::fputs("DEAGLE-D1\t1\n", stream);
}

bool finish(int exit_code)
{
  bool proof_ok=proof_path.empty() || (finish_proof && finish_proof(exit_code));
  if(!dense_path.empty()) proof_ok=(finish_dense && finish_dense(exit_code)) && proof_ok;
  if(finish_boundaries) proof_ok=finish_boundaries() && proof_ok;
  if(!stream) return proof_ok;
  std::fprintf(stream, "END\t%d\n", exit_code);
  bool ok = std::ferror(stream) == 0;
  ok = std::fclose(stream) == 0 && ok;
  stream = nullptr;
  return ok && proof_ok;
}

std::string escape(const std::string &field)
{
  std::string out;
  static const char digits[] = "0123456789abcdef";
  for(unsigned char c : field)
  {
    if(c >= 32 && c != '%' && c != 127)
      out += char(c);
    else
    {
      out += '%';
      out += digits[c >> 4];
      out += digits[c & 15];
    }
  }
  return out;
}

std::string tuple(const std::vector<std::string> &fields)
{
  std::string out;
  for(const auto &s : fields)
    out += std::to_string(s.size()) + ":" + s;
  return out;
}

void row(const char *tag, const std::vector<std::string> &fields)
{
  if(group_sources) group_sources->row(tag,fields);
  std::fputs(tag, stream);
  for(const auto &s : fields)
  {
    std::fputc('\t', stream);
    std::fputs(escape(s).c_str(), stream);
  }
  std::fputc('\n', stream);
}

void gate(const char *op, int output, const std::vector<int> &inputs)
{
  if(group_sources) group_sources->gate(op,output);
  std::fprintf(stream, "G\t%s\t%d", op, output);
  for(int l : inputs) std::fprintf(stream, "\t%d", l);
  std::fputc('\n', stream);
}
}
