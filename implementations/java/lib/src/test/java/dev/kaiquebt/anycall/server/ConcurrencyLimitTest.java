package dev.kaiquebt.anycall.server;

import org.junit.jupiter.api.Test;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;

class ConcurrencyLimitTest {

    private static Thread acquireIn(ConcurrencyLimit limit, CountDownLatch acquired) {
        Thread t = new Thread(() -> {
            try {
                limit.acquire();
                acquired.countDown();
            } catch (InterruptedException ignored) {
            }
        });
        t.start();
        return t;
    }

    @Test
    void raisingTheCapLetsAWaiterIn() throws Exception {
        ConcurrencyLimit limit = new ConcurrencyLimit(1);
        limit.acquire();
        CountDownLatch acquired = new CountDownLatch(1);
        Thread waiter = acquireIn(limit, acquired);

        assertFalse(acquired.await(100, TimeUnit.MILLISECONDS));
        limit.setCapacity(2);
        assertTrue(acquired.await(1, TimeUnit.SECONDS));
        waiter.join();
    }

    @Test
    void loweringTheCapWaitsForRunningOnesToFinish() throws Exception {
        ConcurrencyLimit limit = new ConcurrencyLimit(3);
        limit.acquire();
        limit.acquire();
        limit.setCapacity(1);
        CountDownLatch acquired = new CountDownLatch(1);
        Thread waiter = acquireIn(limit, acquired);

        limit.release();
        assertFalse(acquired.await(100, TimeUnit.MILLISECONDS));
        limit.release();
        assertTrue(acquired.await(1, TimeUnit.SECONDS));
        waiter.join();
    }

    @Test
    void noCapNeverWaits() throws Exception {
        ConcurrencyLimit limit = new ConcurrencyLimit(null);
        for (int i = 0; i < 1000; i++) {
            limit.acquire();
        }
        assertNull(limit.capacity());
    }

    @Test
    void tryAcquireGivesUpAtTheCapAndGetsInOnceRaised() throws Exception {
        ConcurrencyLimit limit = new ConcurrencyLimit(1);
        assertTrue(limit.tryAcquire(0));
        assertFalse(limit.tryAcquire(50));

        limit.setCapacity(2);

        assertTrue(limit.tryAcquire(0));
    }
}
