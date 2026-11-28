#include <pthread.h>
extern unsigned nondet_uint(void);
unsigned visible;
static void *worker(void *p) { return p; }
int main(void)
{
  pthread_t thread;
  pthread_create(&thread, 0, worker, 0);
  unsigned input = nondet_uint();
  unsigned choice;
  if(input & 1u)
    choice = input + 2u;
  else
    choice = input + 3u;
  visible = choice;
  pthread_join(thread, 0);
  __CPROVER_assert(visible != 0, "result");
}
