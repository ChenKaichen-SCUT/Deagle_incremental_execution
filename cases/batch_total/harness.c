#include <assert.h>
#include <pthread.h>

static int shipped_units;

#include "program.c"

static void *pack(void *unused)
{
    (void)unused;
    record_batch(2);
    return 0;
}

int main(void)
{
    pthread_t worker;
    pthread_create(&worker, 0, pack, 0);
    pthread_join(worker, 0);
    /* Each of the two boxes contains three units. */
    assert(shipped_units == 6);
    return 0;
}
