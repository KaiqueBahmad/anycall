package dev.kaiquebt.anycall.publisher;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import io.lettuce.core.ScriptOutputType;
import io.lettuce.core.api.sync.RedisCommands;

/**
 * The one way a response is written, by a server answering a request or by a reaper
 * failing one back: pushed onto its response queue together with the queue's expiry,
 * atomically and in one round trip.
 * <p>
 * A waiting client pops the response within milliseconds and deletes the queue; the
 * expiry only matters when nobody reads it (the client timed out or died, or a server
 * pruned as dead answered late), so it doesn't sit in Redis forever.
 */
public final class AnycallResponses {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    // KEYS[1] = response queue, ARGV[1] = response json, ARGV[2] = ttl seconds.
    private static final String PUSH_SCRIPT =
        "redis.call('LPUSH', KEYS[1], ARGV[1])\n"
        + "redis.call('EXPIRE', KEYS[1], ARGV[2])\n"
        + "return 1";

    private AnycallResponses() {
    }

    public static void push(RedisCommands<String, String> commands, AnyCallResponse response)
            throws JsonProcessingException {
        String responseQueue = AnycallQueues.RESPONSE_QUEUE_PREFIX + response.requestId();
        commands.eval(PUSH_SCRIPT, ScriptOutputType.INTEGER, new String[] {responseQueue},
            OBJECT_MAPPER.writeValueAsString(response),
            String.valueOf(AnycallQueues.RESPONSE_TTL.getSeconds()));
    }
}
