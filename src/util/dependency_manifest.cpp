#include "dependency_manifest.h"
#include <stdexcept>

namespace dependency_manifest
{
std::FILE *stream = nullptr;
char scope = 'U';

void open(const std::string &filename)
{
  if(stream || !(stream = std::fopen(filename.c_str(), "wbx")))
    throw std::runtime_error("expected a new writable D1 manifest: " + filename);
  std::fputs("DEAGLE-D1\t1\n", stream);
}

bool finish(int exit_code)
{
  if(!stream) return true;
  std::fprintf(stream, "END\t%d\n", exit_code);
  bool ok = std::ferror(stream) == 0;
  ok = std::fclose(stream) == 0 && ok;
  stream = nullptr;
  return ok;
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
  std::fprintf(stream, "G\t%s\t%d", op, output);
  for(int l : inputs) std::fprintf(stream, "\t%d", l);
  std::fputc('\n', stream);
}
}
