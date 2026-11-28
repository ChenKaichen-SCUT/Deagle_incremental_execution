#include <assert.h>
#include <pthread.h>
extern unsigned nondet_uint(void);
static unsigned a, b, sink;
struct pair { unsigned low; unsigned high; };
union word { unsigned complete; unsigned char bytes[4]; };
static union word saved;
static struct pair pair;
static unsigned *ptr;
static void repeated(void) { sink += 1; }
static void *worker(void *arg)
{
  unsigned first = a + b;
  unsigned second = a + b;
  for(unsigned i = 0; i < 2; ++i) {
    for(unsigned j = 0; j < 2; ++j) {
      if(first < second) sink = first + i;
      else sink = second + j;
    }
  }
  return arg;
}
int main(void)
{
  pthread_t t[2];
  a = nondet_uint();
  b = nondet_uint();
  repeated();
  sink = a;
  repeated();
  pair.low = a;
  saved.complete = b;
  ptr = &pair.low;
  for(unsigned k = 0; k < 2; ++k) pthread_create(&t[k], 0, worker, 0);
  pthread_join(t[0], 0);
  pthread_join(t[1], 0);
  assert(*ptr != saved.complete || sink == 0);
}
