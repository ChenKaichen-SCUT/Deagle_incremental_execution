#include <assert.h>
#include <pthread.h>

static int counter;
static pthread_mutex_t counter_mutex = PTHREAD_MUTEX_INITIALIZER;

#include "program.c"

static void *left(void *unused)
{
    (void)unused;
    record_left();
    return 0;
}

static void *right(void *unused)
{
    (void)unused;
    record_right();
    return 0;
}

int main(void)
{
    pthread_t left_worker, right_worker;
    pthread_create(&left_worker, 0, left, 0);
    pthread_create(&right_worker, 0, right, 0);
    pthread_join(left_worker, 0);
    pthread_join(right_worker, 0);
    /* Both workers must contribute exactly one, in either order. */
    assert(counter == 2);
    return 0;
}
