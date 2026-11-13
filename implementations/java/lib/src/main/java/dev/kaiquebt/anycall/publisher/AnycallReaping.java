package dev.kaiquebt.anycall.publisher;

import dev.kaiquebt.anycall.model.AnyCallRequest;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import com.fasterxml.jackson.databind.ObjectMapper;
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

    // KEYS[1] = live servers sorted set, ARGV[1] = ttl seconds. Returns every member whose
    // heartbeat is older than the ttl: the read-only half of the heartbeat script, for
    // clients, which don't heartbeat.
    // Kept byte-for-byte identical to the Python client's copy.
    private static final String STALE_SCRIPT = """
        local t = redis.call('TIME')
        local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
        return redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', '(' .. string.format('%.6f', now - tonumber(ARGV[1])))
        """;

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    /** What {@link #failBackNext} did with the request it took. */
    /** What one step of reaping a dead server did (see {@link #failBackNext}). */
    private enum Step {
        /** Failed back one request to its client. */
        ANSWERED,
        /** Dropped one request whose requestId can't be read: it has no client to answer. */
        DROPPED,
        /** Nothing left: the server's list is a tombstone now. */
        DONE,
        /** Someone changed the list meanwhile: look again. */
        RETRY
    }

    // KEYS[1] = live servers sorted set, KEYS[2] = a dead server's processing list.
    // ARGV[1] = server id, ARGV[2] = tombstone ttl seconds. The last step of reaping a dead
    // server: if its list is still empty, removes it from the live set and, if it was still
    // there, turns the list into a tombstone string. Returns 0 if a request landed on the
    // list meanwhile (keep reaping), else 1. A server whose entry is already gone was reaped
    // before; its tombstone isn't recreated, in case the server came back and deleted it.
    // Kept byte-for-byte identical to the Python copy.
    private static final String TOMBSTONE_SCRIPT = """
        local kind = redis.call('TYPE', KEYS[2])['ok']
        if kind == 'list' then return 0 end
        if redis.call('ZREM', KEYS[1], ARGV[1]) == 1 and kind == 'none' then
          redis.call('SET', KEYS[2], 'drained', 'EX', ARGV[2])
        end
        return 1
        """;

    // KEYS[1] = a server's own processing list. Deletes it only if it's a tombstone: a
    // server that drained deletes its own once nothing can take onto that list anymore.
    // Kept byte-for-byte identical to the Python copy.
    private static final String DROP_TOMBSTONE_SCRIPT = """
        if redis.call('TYPE', KEYS[1])['ok'] == 'string' then return redis.call('DEL', KEYS[1]) end
        return 0
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
     * every request still on its processing list, so their clients stop waiting.
     * <p>
     * Each request is failed back in a transaction of its own (see {@link #failBackNext}): it
     * leaves the list only together with its response, so a reaper that dies halfway loses
     * nothing, and of several reapers on the same server, each request goes to exactly one.
     * A server declared dead never heartbeats again, so there's nothing to check first.
     * Failures only log.
     *
     * @param commands a connection nothing else uses meanwhile: {@code WATCH} and
     *                 {@code MULTI} belong to the connection, not the caller
     */
    public static void reapDeadServers(RedisCommands<String, String> commands, Collection<String> dead) {
        for (String serverId : dead) {
            int answered = 0;
            int dropped = 0;
            try {
                for (Step step = failBackNext(commands, serverId); step != Step.DONE;
                        step = failBackNext(commands, serverId)) {
                    if (step == Step.ANSWERED) {
                        answered++;
                    } else {
                        dropped++;
                    }
                }
            } catch (Exception e) {
                log.warn("Failed to reap dead server {}: {}", serverId, e.getMessage());
            }
            if (answered > 0) {
                log.warn("Failed back {} request(s) of dead server {} to their clients", answered, serverId);
            }
            if (dropped > 0) {
                log.warn("Dropped {} request(s) with no readable requestId or clientId of dead server {}",
                    dropped, serverId);
            }
        }
    }

    /**
     * Deletes a server's own tombstone (see {@link #DROP_TOMBSTONE_SCRIPT}); does nothing if
     * its processing key isn't one. For a server that drained, once nothing can take onto
     * its old list anymore.
     */
    public static void dropTombstone(RedisCommands<String, String> commands, String serverId) {
        commands.eval(DROP_TOMBSTONE_SCRIPT, ScriptOutputType.INTEGER,
            new String[] {AnycallQueues.PROCESSING_PREFIX + serverId});
    }

    /**
     * One step of reaping a dead server: fails back its next request, or, once its list is
     * empty, leaves a tombstone. Looks at the server's processing key and picks the case:
     * <ul>
     *   <li>a string: a tombstone, the server was reaped before;</li>
     *   <li>a list: there are requests left (see {@link #failBackLast});</li>
     *   <li>nothing: the list is empty (see {@link #tombstone}).</li>
     * </ul>
     * {@code WATCH} on the key makes any change by another reaper meanwhile restart the step.
     */
    private static Step failBackNext(RedisCommands<String, String> commands, String serverId)
            throws Exception {
        String processingKey = AnycallQueues.PROCESSING_PREFIX + serverId;
        while (true) {
            commands.watch(processingKey);
            Step step;
            try {
                step = switch (commands.type(processingKey)) {
                    case "string" -> Step.DONE;
                    case "list" -> failBackLast(commands, serverId, processingKey);
                    default -> tombstone(commands, serverId, processingKey);
                };
            } finally {
                commands.unwatch();  // a no-op after EXEC, which already dropped the WATCH
            }
            if (step != Step.RETRY) {
                return step;
            }
        }
    }

    /**
     * Fails back the last request on a dead server's list: removes it and writes its
     * server-lost response in one transaction, so it never leaves the list unanswered.
     * <p>
     * The request is read with a plain {@code LINDEX}, outside any script, so Redis is never
     * blocked copying it into Lua. The {@code WATCH} guarantees it's still the last one when
     * the transaction runs, so it's removed by position ({@code LTRIM}), with nothing to
     * compare or send back; if another reaper took it first, the transaction is discarded.
     */
    private static Step failBackLast(RedisCommands<String, String> commands, String serverId,
                                     String processingKey) throws Exception {
        String request = commands.lindex(processingKey, -1);
        if (request == null) {
            return Step.RETRY;  // emptied meanwhile: the next look tombstones it
        }
        // Only where it goes is needed, so a request the server couldn't have parsed (an
        // unknown field, say) still reaches its client.
        AnyCallRequest.ReplyAddress address = AnyCallRequest.readReplyAddress(request);
        String response = address == null ? null
            : OBJECT_MAPPER.writeValueAsString(AnyCallResponse.serverLost(address.requestId(), serverId));

        commands.multi();
        try {
            commands.ltrim(processingKey, 0, -2);
            if (address != null) {
                String responseQueue = AnycallQueues.responseQueue(address.clientId());
                commands.lpush(responseQueue, response);
                commands.expire(responseQueue, AnycallQueues.RESPONSE_TTL.getSeconds());
            }
        } catch (Exception e) {
            commands.discard();
            throw e;
        }
        if (commands.exec().wasDiscarded()) {
            return Step.RETRY;
        }
        return address == null ? Step.DROPPED : Step.ANSWERED;
    }

    /**
     * The last step of reaping a dead server, once its list is empty: {@link #TOMBSTONE_SCRIPT}
     * removes it from the live set and turns its processing key into a tombstone. If a
     * request landed on the list meanwhile, the script changes nothing, and reaping goes on.
     */
    private static Step tombstone(RedisCommands<String, String> commands, String serverId,
                                  String processingKey) {
        Long done = commands.eval(TOMBSTONE_SCRIPT, ScriptOutputType.INTEGER,
            new String[] {AnycallQueues.HEARTBEAT_KEY, processingKey},
            serverId, String.valueOf(AnycallQueues.TOMBSTONE_TTL.getSeconds()));
        return done == 1 ? Step.DONE : Step.RETRY;
    }
}
