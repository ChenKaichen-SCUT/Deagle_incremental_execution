#include <assert.h>
#include <pthread.h>

enum { workers = 6, capacity = 5 };
static unsigned sold;
static pthread_mutex_t bookings = PTHREAD_MUTEX_INITIALIZER;

#include "program.c"

static void *agent(void *unused)
{
    (void)unused;
    reserve_seat();
    return 0;
}

int main(void)
{
    pthread_t agents[workers];
    for (unsigned i = 0; i < workers; ++i)
        pthread_create(&agents[i], 0, agent, 0);
    for (unsigned i = 0; i < workers; ++i)
        pthread_join(agents[i], 0);
    assert(sold == capacity);
    return 0;
}
