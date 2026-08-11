# AnyCall Visualizer

Read-only Tkinter dashboard for observing AnyCall traffic on a Redis
instance: request queue backlogs, consumer groups/consumers, server
heartbeats, and a best-effort activity log.

It only ever issues non-destructive Redis commands (`SCAN`, `XLEN`,
`XRANGE`, `XINFO`, `GET`, `TTL`, `INFO`) — it never joins a consumer group,
acknowledges/deletes messages, or changes Redis config. It has no effect on
real client/server traffic and provides no actions of its own.

Works against any AnyCall implementation (Java, Python, ...) since they all
share the same Redis key protocol.

## Run

```bash
./run.sh                                    # redis://localhost:16379
./run.sh --redis-uri redis://host:16379      # custom instance
./run.sh --interval 0.5                     # faster polling
```

Or set `ANYCALL_REDIS_URI` instead of `--redis-uri`.

## What it shows

- **Methods**: one row per `anycall:requests:<method>` stream, with backlog
  (unclaimed requests), processing (pending/claimed-not-acked), and the
  consumer groups/consumers serving it. Expand a row for detail.
- **Servers**: one row per live `anycall:heartbeat:*` key, with time since
  last heartbeat and remaining TTL before it's considered offline.
- **Activity log**: method/server discovery, backlog changes, and requests
  spotted entering a stream. Polling can't see everything that happens
  between two polls, so this is best-effort flavor, not a complete audit
  trail — the gauges above stay exact.

## Selection

Rows support Shift-click, Shift-Up/Down, and Ctrl-click for multi-select
(standard list-box behavior, reimplemented for keyboard since `ttk.Treeview`
only supports it via mouse out of the box). Selection and expand/collapse
state survive each poll refresh.

Press **Ctrl-C** with row(s) selected to copy them to the clipboard as JSON
(a single object for one row, an array for multiple) — includes the row's
full underlying data, not just the visible columns.
