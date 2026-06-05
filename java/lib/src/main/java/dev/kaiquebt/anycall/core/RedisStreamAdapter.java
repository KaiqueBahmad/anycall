package dev.kaiquebt.anycall.core;

import io.lettuce.core.RedisClient;
import io.lettuce.core.XReadArgs;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisStreamCommands;

import java.time.Duration;
import java.util.Collections;
import java.util.List;
import java.util.Map;

public class RedisStreamAdapter implements AutoCloseable {

    private final StatefulRedisConnection<String, String> connection;
    private final RedisStreamCommands<String, String> streamCommands;

    public RedisStreamAdapter(String redisUri) {
        RedisClient client = RedisClient.create(redisUri != null ? redisUri : "redis://localhost:6379");
        this.connection = client.connect();
        this.streamCommands = connection.sync();
    }

    public RedisStreamAdapter(StatefulRedisConnection<String, String> connection) {
        this.connection = connection;
        this.streamCommands = connection.sync();
    }

    public String add(String streamKey, Map<String, String> data) {
        return streamCommands.xadd(streamKey, data);
    }

    public List<Object> read(String streamKey, Duration timeout) {
        try {
            XReadArgs args = new XReadArgs();
            args.block(timeout);
            XReadArgs.StreamOffset<String> offset = XReadArgs.StreamOffset.from(streamKey, "0-0");
            List<io.lettuce.core.StreamMessage<String, String>> result = streamCommands.xread(args, offset);

            if (result != null && !result.isEmpty()) {
                io.lettuce.core.StreamMessage<String, String> msg = result.get(0);
                return List.of(msg.getId(), msg.getBody());
            }
            return null;
        } catch (Exception e) {
            return null;
        }
    }

    public List<Object> readGroup(String streamKey, String group, String consumer, Duration timeout) {
        try {
            io.lettuce.core.Consumer<String> consumerRef = io.lettuce.core.Consumer.from(group, consumer);
            XReadArgs args = new XReadArgs();
            args.block(timeout);
            XReadArgs.StreamOffset<String> offset = XReadArgs.StreamOffset.lastConsumed(streamKey);
            List<io.lettuce.core.StreamMessage<String, String>> result = streamCommands.xreadgroup(consumerRef, args, offset);

            if (result != null && !result.isEmpty()) {
                io.lettuce.core.StreamMessage<String, String> msg = result.get(0);
                return List.of(msg.getId(), msg.getBody());
            }
            return null;
        } catch (Exception e) {
            return null;
        }
    }

    public void createGroup(String streamKey, String group) {
        try {
            streamCommands.xgroupCreate(XReadArgs.StreamOffset.latest(streamKey), group);
        } catch (Exception e) {
            String msg = e.getMessage() != null ? e.getMessage() : "";
            if (!msg.contains("BUSYGROUP")) {
                try {
                    String id = streamCommands.xadd(streamKey, Collections.singletonMap("_init", "1"));
                    streamCommands.xdel(streamKey, id);
                    streamCommands.xgroupCreate(XReadArgs.StreamOffset.latest(streamKey), group);
                } catch (Exception ex) {
                    String exMsg = ex.getMessage() != null ? ex.getMessage() : "";
                    if (!exMsg.contains("BUSYGROUP")) {
                        throw ex;
                    }
                }
            }
        }
    }

    public void acknowledge(String streamKey, String group, String messageId) {
        streamCommands.xack(streamKey, group, messageId);
    }

    public void delete(String key) {
        connection.sync().del(key);
    }

    @Override
    public void close() {
        if (connection != null) {
            connection.close();
        }
    }
}
