static void reserve_seat(void)
{
    unsigned observed;
    pthread_mutex_lock(&bookings);
    observed = sold;
    pthread_mutex_unlock(&bookings);
    pthread_mutex_lock(&bookings);
    if (observed < capacity)
        sold = observed + 1u;
    pthread_mutex_unlock(&bookings);
}
