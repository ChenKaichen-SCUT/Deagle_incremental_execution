static void record_request(int amount)
{
    if (amount > 0 && amount <= 3) {
        accepted += 1;
        units += amount;
    }
}
