package dev.kaiquebt.anycall.publisher;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import io.lettuce.core.ScriptOutputType;
import io.lettuce.core.api.sync.RedisCommands;

/**
 * How a server writes a response: pushed onto its response queue together with the queue's
 * expiry and the removal of its request from the server's processing list, atomically and
 * in one round trip. A reaper writes its own in a transaction (see {@link AnycallReaping}).
 * <p>
 * A waiting client pops the response within milliseconds and deletes the queue; the
 * expiry only matters when nobody reads it (the client timed out or died, or a server
 * reaped as dead answered late), so it doesn't sit in Redis forever.
 */
public final class AnycallResponses {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    // KEYS[1] = response queue, KEYS[2] = processing list, ARGV[1] = response json,
    // ARGV[2] = ttl seconds, ARGV[3] = the request json exactly as it was taken.
    // The push goes first: if it never runs, neither does the LREM, and the request is
    // still on the list to be failed back.
    private static final String PUSH_AND_RELEASE_SCRIPT =
        "redis.call('LPUSH', KEYS[1], ARGV[1])\n"
        + "redis.call('EXPIRE', KEYS[1], ARGV[2])\n"
        + "redis.call('LREM', KEYS[2], 1, ARGV[3])\n"
        + "return 1";

    private AnycallResponses() {
    }

    /**
     * Writes a server's response and drops its request from the server's processing list.
     *
     * @param clientId the client that made the call, whose queue the response goes to
     * @param processingKey the processing list the request was taken onto
     * @param item the request json exactly as it was taken
     */
    public static void pushAndRelease(RedisCommands<String, String> commands, AnyCallResponse response,
                                      String clientId, String processingKey, String item)
            throws JsonProcessingException {
        commands.eval(PUSH_AND_RELEASE_SCRIPT, ScriptOutputType.INTEGER,
            new String[] {AnycallQueues.responseQueue(clientId), processingKey},
            OBJECT_MAPPER.writeValueAsString(response),
            String.valueOf(AnycallQueues.RESPONSE_TTL.getSeconds()), item);
    }
}
