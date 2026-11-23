static void record_split(void)
{
    int snapshot;
    pthread_mutex_lock(&counter_mutex);
    snapshot = counter;
    pthread_mutex_unlock(&counter_mutex);

    pthread_mutex_lock(&counter_mutex);
    counter = snapshot + 1;
    pthread_mutex_unlock(&counter_mutex);
}

static void record_left(void)
{
    pthread_mutex_lock(&counter_mutex);
    counter += 1;
    pthread_mutex_unlock(&counter_mutex);
}

static void record_right(void)
{
    record_split();
}
