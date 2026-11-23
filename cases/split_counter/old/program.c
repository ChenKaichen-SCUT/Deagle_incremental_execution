static void record_one(void)
{
    int snapshot;
    pthread_mutex_lock(&counter_mutex);
    snapshot = counter;
    pthread_mutex_unlock(&counter_mutex);

    pthread_mutex_lock(&counter_mutex);
    counter = snapshot + 1;
    pthread_mutex_unlock(&counter_mutex);
}
