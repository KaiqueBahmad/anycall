# AnyCall Visualizer

Read-only PyQt6 dashboard for observing AnyCall traffic on a Redis
instance: live servers, request queue backlogs, and a best-effort
activity log.

Request/response queues can be either a Redis List (Java, as of the
Streams-to-Lists migration) or a Redis Stream (Python, still pending that
migration) — the dashboard checks each queue's `TYPE` and reads it the
right way, so both kinds show up side by side, tagged `[list]`/`[stream]`
in the Methods panel.

It only ever issues non-destructive Redis commands (`SCAN`, `TYPE`, `LLEN`,
`LRANGE`, `XLEN`, `XRANGE`, `ZRANGEBYSCORE`, `INFO`) — it never pushes or
pops a queue entry, acknowledges/deletes messages, writes or prunes the
heartbeat set, or changes Redis config. It has no effect on real
client/server traffic and provides no actions of its own.

Works against any AnyCall implementation (Java, Python, ...) since they all
share the same Redis *key* protocol — though as of the Java migration to
Lists, the structure *behind* a given key can now differ by language (see
above); the dashboard handles that automatically.

## Run

```bash
./run.sh                                    # redis://localhost:16379
./run.sh --redis-uri redis://host:16379      # custom instance
./run.sh --interval 0.5                     # faster polling
```

Or set `ANYCALL_REDIS_URI` instead of `--redis-uri`.

## What it shows

- **Servers**: one row per server currently heartbeating into the
  `anycall:servers:alive` sorted set, with how long ago it last did so.
  Every AnyCall server `ZADD`s itself there every 2s under a fresh
  timestamp; the dashboard reads back the members scored within the 8s
  TTL, so a server that stops — cleanly (it `ZREM`s itself) or by
  crashing (it ages out) — drops off the list within a poll or two.
  Ages come from the server's own clock, so they're only as accurate as
  the clock agreement between that host and this one.
- **Methods**: one row per `anycall:requests:<method>` queue, tagged
  `[list]` or `[stream]`, with backlog (not-yet-popped requests). A
  request simply disappears from the backlog the instant a worker pops
  it, for both kinds.
- **Activity log**: servers coming and going, method discovery, backlog
  changes, and requests spotted entering a queue. Polling can't see
  everything that happens between two polls, so this is best-effort
  flavor, not a complete audit trail — the gauges above stay exact.

## Always on top

The button in the header pins the window above the others.

## Selection

Rows support Shift-click, Shift-Up/Down, and Ctrl-click for multi-select
(standard Qt tree/list-box behavior). Selection and expand/collapse state
survive each poll refresh.

Press **Ctrl-C** with row(s) selected to copy them to the clipboard as JSON
(a single object for one row, an array for multiple) — includes the row's
full underlying data, not just the visible columns.
