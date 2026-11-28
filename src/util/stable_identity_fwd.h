#ifndef CPROVER_UTIL_STABLE_IDENTITY_FWD_H
#define CPROVER_UTIL_STABLE_IDENTITY_FWD_H
namespace stable_identity
{
extern bool enabled;
extern unsigned current_origin;
void clear_cache(const void *converter, unsigned domain);
}
#endif
