// SI-1A observation only. Included in private copies of the frozen translation units.
#ifndef DEAGLE_SI1A_PROBE_H
#define DEAGLE_SI1A_PROBE_H
#include <cstdio>
#include <cstdlib>
#include <cstddef>
namespace si1a
{
struct state
{
  FILE *file = nullptr;
  const char *site = "unattributed";
  const char *op = "-";
  const char *phase = "-";
  int context = -1;
  state()
  {
    if(const char *path = std::getenv("DEAGLE_SI1A_TRACE"))
    {
      file = std::fopen(path, "wx");
      if(!file) std::abort();
    }
  }
};
inline state &trace() { static state data; return data; }
struct site_scope
{
  const char *old;
  explicit site_scope(const char *s) : old(trace().site) { trace().site = s; }
  ~site_scope() { trace().site = old; }
};
template<class P> auto one(P &p, const char *site) -> decltype(p.new_variable())
{
  site_scope scope(site);
  return p.new_variable();
}
template<class P, class W> auto many(P &p, const char *site, W width) -> decltype(p.new_variables(width))
{
  site_scope scope(site);
  return p.new_variables(width);
}
struct owner
{
  const char *old_phase;
  int old_context;
  owner(const char *phase, int context) : old_phase(trace().phase), old_context(trace().context)
  { trace().phase = phase; trace().context = context; }
  ~owner() { trace().phase = old_phase; trace().context = old_context; }
};
struct expr
{
  const char *old;
  explicit expr(const char *op) : old(trace().op) { trace().op = op; }
  ~expr() { trace().op = old; }
};
inline void alloc(std::size_t first, std::size_t width)
{
  const auto &s = trace();
  if(s.file) std::fprintf(s.file, "R\t%zu\t%zu\t%s\t%s\t%s\t%d\n", first, width, s.site, s.op, s.phase, s.context);
}
// Entry addresses are same-process cache correlation handles only. The published trace
// rewrites them to dense local ordinals, with separate BOOL and BV namespaces.
inline void cache(const char *event, const char *domain, const void *entry, std::size_t lo, std::size_t hi)
{
  const auto &s = trace();
  if(s.file) std::fprintf(s.file, "%s\t%s\t%p\t%zu\t%zu\t%s\t%s\t%d\n", event, domain, entry, lo, hi, s.op, s.phase, s.context);
}
inline void symbol(const char *name, const char *type, std::size_t width)
{
  if(trace().file) std::fprintf(trace().file, "Y\t%s\t%s\t%zu\n", name, type, width);
}
inline void boundary(std::size_t n)
{
  if(trace().file)
  {
    std::fprintf(trace().file, "N\t%zu\n", n);
    if(std::fflush(nullptr) != 0) std::abort();
    std::_Exit(77);
  }
}
}
#endif
