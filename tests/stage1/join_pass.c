#include <assert.h>
#include <pthread.h>

static int value;

static void *store(void *arg)
{
    (void)arg;
    value = 7;
    return 0;
}

int main(void)
{
    pthread_t tid;
    pthread_create(&tid, 0, store, 0);
    pthread_join(tid, 0);
    assert(value == 7);
    return 0;
}
