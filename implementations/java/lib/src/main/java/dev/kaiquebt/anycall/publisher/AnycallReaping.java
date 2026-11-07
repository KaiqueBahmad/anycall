package dev.kaiquebt.anycall.publisher;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.model.AnyCallRequest;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import io.lettuce.core.ScriptOutputType;
import io.lettuce.core.api.sync.RedisCommands;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Collection;
import java.util.List;

/**
 * Fails back the requests of servers that stopped heartbeating, so their clients get a
 * {@code ServerLostError} instead of waiting forever. Run by servers on every heartbeat
 * tick and by clients whenever a wait for a response ends empty: the same code either way.
 */
public final class AnycallReaping {

    private static final Logger log = LoggerFactory.getLogger(AnycallReaping.class);
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    // KEYS[1] = live servers sorted set, ARGV[1] = ttl seconds. Returns every member whose
    // heartbeat is older than the ttl: the read-only half of the heartbeat script, for
    // clients, which don't heartbeat.
    // Kept byte-for-byte identical to the Python client's copy.
    private static final String STALE_SCRIPT = """
        local t = redis.call('TIME')
        local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
        return redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', '(' .. string.format('%.6f', now - tonumber(ARGV[1])))
        """;

    // KEYS[1] = live servers sorted set, KEYS[2] = the server's processing list.
    // ARGV[1] = server id, ARGV[2] = ttl seconds. If the server's heartbeat is still older
    // than the ttl, removes it from the set, empties its processing list and returns what
    // was in it; otherwise returns {} and changes nothing. Atomic, so of everyone who finds
    // the same server dead, exactly one gets its requests.
    // Kept byte-for-byte identical to the Python copy.
    private static final String CLAIM_SCRIPT = """
        local score = redis.call('ZSCORE', KEYS[1], ARGV[1])
        if not score then return {} end
        local t = redis.call('TIME')
        local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
        if tonumber(score) >= now - tonumber(ARGV[2]) then return {} end
        redis.call('ZREM', KEYS[1], ARGV[1])
        local items = redis.call('LRANGE', KEYS[2], 0, -1)
        redis.call('DEL', KEYS[2])
        return items
        """;

    private AnycallReaping() {
    }

    /**
     * Every server in {@link AnycallQueues#HEARTBEAT_KEY} whose heartbeat is older than
     * {@link AnycallQueues#HEARTBEAT_TTL} by Redis's own clock: the dead servers not reaped
     * yet.
     */
    public static List<String> staleServers(RedisCommands<String, String> commands) {
        return commands.eval(STALE_SCRIPT, ScriptOutputType.MULTI,
            new String[] {AnycallQueues.HEARTBEAT_KEY}, String.valueOf(AnycallQueues.HEARTBEAT_TTL.getSeconds()));
    }

    /**
     * For each server in {@code dead}, pushes a server-lost error to the response queue of
     * every request still on its processing list.
     * <p>
     * Several servers and clients can find the same dead server at once; the claim script
     * hands its requests to exactly one of them, and only that one writes the errors, so a
     * client never gets two. {@code dead} is only a hint: the claim checks again,
     * atomically, so a server that heartbeated in between is left alone. Failures only log.
     */
    public static void reapDeadServers(RedisCommands<String, String> commands, Collection<String> dead) {
        for (String serverId : dead) {
            List<String> items;
            try {
                items = commands.eval(CLAIM_SCRIPT, ScriptOutputType.MULTI,
                    new String[] {AnycallQueues.HEARTBEAT_KEY, AnycallQueues.PROCESSING_PREFIX + serverId},
                    serverId, String.valueOf(AnycallQueues.HEARTBEAT_TTL.getSeconds()));
            } catch (Exception e) {
                log.warn("Failed to reap dead server {}: {}", serverId, e.getMessage());
                continue;
            }
            for (String item : items) {
                failBack(commands, item, serverId);
            }
        }
    }

    private static void failBack(RedisCommands<String, String> commands, String item, String serverId) {
        String requestId;
        try {
            requestId = OBJECT_MAPPER.readValue(item, AnyCallRequest.class).requestId();
        } catch (Exception e) {
            log.warn("Dropped an unparseable request of dead server {}", serverId);
            return;
        }
        try {
            AnycallResponses.push(commands, AnyCallResponse.serverLost(requestId, serverId));
            log.warn("Failed request {} back to its client: server {} is gone", requestId, serverId);
        } catch (Exception e) {
            log.warn("Failed to fail back request {} of dead server {}: {}", requestId, serverId, e.getMessage());
        }
    }
}
