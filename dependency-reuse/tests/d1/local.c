#include <assert.h>
#include <pthread.h>

extern unsigned nondet_uint(void);
static unsigned enabled, value, unrelated;

static void *store(void *unused)
{
  (void)unused;
  value = 7;
  return 0;
}

int main(void)
{
  pthread_t t;
  enabled = nondet_uint();
  unrelated = 1;
  pthread_create(&t, 0, store, 0);
  pthread_join(t, 0);
  assert(value == 7);
  return 0;
}
