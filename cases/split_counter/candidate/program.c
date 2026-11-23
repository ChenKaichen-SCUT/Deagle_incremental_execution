static void record_one(void)
{
    pthread_mutex_lock(&counter_mutex);
    counter = counter + 1;
    pthread_mutex_unlock(&counter_mutex);
}
