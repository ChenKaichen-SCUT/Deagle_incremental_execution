#include <assert.h>
#include <pthread.h>

static int flag;

static void *worker(void *arg)
{
    (void)arg;
    flag = 1;
    assert(flag == 0);
    return 0;
}

int main(void)
{
    pthread_t tid;
    pthread_create(&tid, 0, worker, 0);
    pthread_join(tid, 0);
    return 0;
}
