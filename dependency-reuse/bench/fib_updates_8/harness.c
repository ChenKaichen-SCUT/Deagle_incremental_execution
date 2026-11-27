#include <assert.h>
#include <pthread.h>

void __CPROVER_atomic_begin(void);
void __CPROVER_atomic_end(void);
static unsigned left = 1, right = 1;

#include "program.c"

static void *left_worker(void *unused)
{
    (void)unused;
    for (unsigned k = 0; k < 8; ++k) {
        __CPROVER_atomic_begin();
        update_left();
        __CPROVER_atomic_end();
    }
    return 0;
}

static void *right_worker(void *unused)
{
    (void)unused;
    for (unsigned k = 0; k < 8; ++k) {
        __CPROVER_atomic_begin();
        right += left;
        __CPROVER_atomic_end();
    }
    return 0;
}

int main(void)
{
    pthread_t a, b;
    pthread_create(&a, 0, left_worker, 0);
    pthread_create(&b, 0, right_worker, 0);
    pthread_join(a, 0);
    pthread_join(b, 0);
    /* Sixteen atomic additions are bounded by F(18). */
    assert(left <= 2584u && right <= 2584u);
    return 0;
}
