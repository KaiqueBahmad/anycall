package dev.kaiquebt.anycall.spring;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

/**
 * AnyCall's settings, under {@code anycall.*}:
 *
 * <pre>{@code
 * anycall:
 *   redis-url: redis://localhost:6379
 *   prefix: billing
 *   client:
 *     timeout: 30s
 *     max-queue-depth: 100
 *   server:
 *     max-concurrency: 16
 * }</pre>
 */
@ConfigurationProperties("anycall")
public class AnyCallProperties {

    /** Redis the client and server connect to. */
    private String redisUrl = "redis://localhost:6379";

    /** The first part of every key; a client and a server see each other only under the same one. */
    private String prefix = "anycall";

    private final Client client = new Client();

    private final Server server = new Server();

    public String getRedisUrl() {
        return redisUrl;
    }

    public void setRedisUrl(String redisUrl) {
        this.redisUrl = redisUrl;
    }

    public String getPrefix() {
        return prefix;
    }

    public void setPrefix(String prefix) {
        this.prefix = prefix;
    }

    public Client getClient() {
        return client;
    }

    public Server getServer() {
        return server;
    }

    public static class Client {

        /** Whether to create the client bean. */
        private boolean enabled = true;

        /** How long a call waits for its response; left out, with no limit. */
        private Duration timeout;

        /** Reject a call if its method's queue already holds this many requests; left out, no limit. */
        private Long maxQueueDepth;

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public Duration getTimeout() {
            return timeout;
        }

        public void setTimeout(Duration timeout) {
            this.timeout = timeout;
        }

        public Long getMaxQueueDepth() {
            return maxQueueDepth;
        }

        public void setMaxQueueDepth(Long maxQueueDepth) {
            this.maxQueueDepth = maxQueueDepth;
        }
    }

    public static class Server {

        /** Whether to serve the context's {@code @AnyCallSupplier} beans. */
        private boolean enabled = true;

        /** Server-wide cap on requests processed at once, across every method; left out, none. */
        private Integer maxConcurrency;

        /**
         * How long the context's close waits for the requests already taken to finish; past
         * it, they're given up on. Must be positive.
         */
        private Duration shutdownTimeout = Duration.ofSeconds(30);

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public Integer getMaxConcurrency() {
            return maxConcurrency;
        }

        public void setMaxConcurrency(Integer maxConcurrency) {
            this.maxConcurrency = maxConcurrency;
        }

        public Duration getShutdownTimeout() {
            return shutdownTimeout;
        }

        public void setShutdownTimeout(Duration shutdownTimeout) {
            if (shutdownTimeout == null || shutdownTimeout.isZero() || shutdownTimeout.isNegative()) {
                throw new IllegalArgumentException("anycall.server.shutdown-timeout must be positive; got "
                    + shutdownTimeout);
            }
            this.shutdownTimeout = shutdownTimeout;
        }
    }
}
