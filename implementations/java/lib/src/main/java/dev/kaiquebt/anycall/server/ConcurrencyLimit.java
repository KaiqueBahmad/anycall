package dev.kaiquebt.anycall.server;

/**
 * A cap on how many things run at once that can change while they run. Raising it lets
 * waiters in at once; lowering it lets what's running finish, and lets nothing new in until
 * the count is under the new cap.
 */
final class ConcurrencyLimit {

    // null means no cap.
    private Integer capacity;
    private int inUse;

    ConcurrencyLimit(Integer capacity) {
        this.capacity = capacity;
    }

    synchronized void acquire() throws InterruptedException {
        while (capacity != null && inUse >= capacity) {
            wait();
        }
        inUse++;
    }

    synchronized void release() {
        inUse--;
        notifyAll();
    }

    synchronized void setCapacity(Integer capacity) {
        this.capacity = capacity;
        notifyAll();
    }

    synchronized Integer capacity() {
        return capacity;
    }
}
