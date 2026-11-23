#include <assert.h>
#include <pthread.h>

static int accepted;
static int units;

#include "program.c"

static void *collect(void *unused)
{
    (void)unused;
    record_request(1);
    record_request(3);
    record_request(4);
    return 0;
}

int main(void)
{
    pthread_t worker;
    pthread_create(&worker, 0, collect, 0);
    pthread_join(worker, 0);
    /* Positive quantities up to and including three are accepted. */
    assert(accepted == 2 && units == 4);
    return 0;
}
