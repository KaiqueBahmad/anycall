# AnyCall Protocol — Contract 0.7

## 1. Conventions

- **MUST** / **MUST NOT**: required. An implementation that breaks it is wrong.
- **SHOULD** / **SHOULD NOT**: expected, unless there is a good reason not to.
- **MAY**: allowed, not required.

- **Client**: a process that calls methods.
- **Server**: a process that registers methods and answers calls. Each
  instance has a **server id**: a random lowercase UUID, made at creation and
  never reused.
- **Reaper**: whoever fails back a dead server's requests: any live server, or
  a waiting client.
- **Now**: Redis's `TIME`, as seconds with six decimals. No rule uses a
  host's clock.

Redis 5.0 or later is required. Implementations MAY use anything 5.0 has,
and a newer command only where they check for it and fall back. They MUST
talk RESP2: Redis 5.0 has no `HELLO`, so no RESP3.

## 2. Keys

| Key | Type | Written by | Read by | Expiry |
|---|---|---|---|---|
| `anycall:requests:<method>` | List | clients (`LPUSH`) | servers (`BLMOVE` or `BRPOPLPUSH`) | none |
| `anycall:processing:<server id>` | List | its server | its server, reapers | none |
| `anycall:responses:<request id>` | List | server or reaper (`LPUSH`) | the caller (`BRPOP`) | `RESPONSE_TTL`, set on every write |
| `anycall:servers:alive` | Sorted set: server id → now of its last heartbeat | servers | everyone | none |

Implementations MUST NOT write any other key under `anycall:`.

## 3. Messages

JSON objects, UTF-8, one List entry each.

**Request**

```json
{"requestId": "<uuid>", "methodName": "<method>", "payload": "<json text>"}
```

- `requestId` MUST be a fresh random UUID.
- `methodName` MUST match the queue it is pushed to.
- `payload` is the argument serialized to JSON, stored as a **string**.

**Response**

```json
{"requestId": "<uuid>", "payload": "<json text>" | null, "error": "<message>" | null}
{"requestId": "<uuid>", "payload": null, "error": "<message>", "lostServer": "<server id>"}
```

- Success: `payload` is the result as a JSON string, `error` is `null`. A
  method that returns null sends the string `"null"`, never a `null`
  payload.
- Remote error: `payload` is `null`, `error` is a message.
- Server lost (reapers only): a remote error plus `lostServer`. `error`
  SHOULD be `server <server id> stopped heartbeating while processing this request`.
- `payload` and `error` MUST always be present. `lostServer` MUST be omitted
  when unused, not `null`.

A message MUST NOT carry any other field, and a reader MUST reject one that
does. Adding a field is therefore a breaking change. Different contract
versions MUST NOT share a Redis.

## 4. Constants

Fixed by the contract; implementations MUST NOT make them configurable.

| Name | Value | Meaning |
|---|---|---|
| `HEARTBEAT_PERIOD` | 2s | how often a server heartbeats |
| `HEARTBEAT_TTL` | 8s | a server whose score is older than now − this is dead |
| `RESPONSE_TTL` | 60s | expiry of a response queue |
| `TAKE_BLOCK` | 2s | how long one take blocks |
| `WAIT_SLICE` | 10s | the longest a client blocks at once |

## 5. Scripts

### 5.1 HEARTBEAT

`KEYS[1]` = `anycall:servers:alive`; `ARGV` = server id, `HEARTBEAT_TTL`.
Returns `1` if the server had no entry before (first heartbeat, or it was
reaped) else `0`, followed by every dead server's id. Removes nothing.

```lua
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local added = redis.call('ZADD', KEYS[1], string.format('%.6f', now), ARGV[1])
local result = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', '(' .. string.format('%.6f', now - tonumber(ARGV[2])))
table.insert(result, 1, added)
return result
```

### 5.2 STALE

`KEYS[1]` = `anycall:servers:alive`; `ARGV` = `HEARTBEAT_TTL`. Returns every
dead server's id. The read-only half of HEARTBEAT, for clients.

```lua
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
return redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', '(' .. string.format('%.6f', now - tonumber(ARGV[1])))
```

### 5.3 CLAIM

`KEYS` = `anycall:servers:alive`, `anycall:processing:<server id>`; `ARGV` =
server id, `HEARTBEAT_TTL`. If the server is still dead, removes it from the
live set, empties its processing list and returns what was on it; otherwise
returns nothing. Of all reapers claiming one server, exactly one gets its
requests.

```lua
local score = redis.call('ZSCORE', KEYS[1], ARGV[1])
if not score then return {} end
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
if tonumber(score) >= now - tonumber(ARGV[2]) then return {} end
redis.call('ZREM', KEYS[1], ARGV[1])
local items = redis.call('LRANGE', KEYS[2], 0, -1)
redis.call('DEL', KEYS[2])
return items
```

## 6. Server

See [docs/taking-requests.md](docs/taking-requests.md).

### 6.1 Liveness

- Before taking any request, a server MUST run HEARTBEAT once successfully.
  If it fails, starting MUST fail and the server MUST NOT take anything.
- While running, it MUST run HEARTBEAT every `HEARTBEAT_PERIOD` and reap every
  dead server it returns. Request processing MUST NOT delay it.
- If HEARTBEAT returns `1` after the first time, the server was reaped; it
  SHOULD log a warning and keeps running.

### 6.2 Taking

- Each method MUST have its own read loop, taking one request at a time with
  `BLMOVE anycall:requests:<method> anycall:processing:<server id> RIGHT LEFT TAKE_BLOCK`
  where Redis has it (6.2+), and otherwise with the equivalent
  `BRPOPLPUSH anycall:requests:<method> anycall:processing:<server id> TAKE_BLOCK`,
  which 6.2 deprecates. No other command.
- The server MUST pick between the two once, on start, by asking Redis for
  the command (`COMMAND INFO BLMOVE` is `nil` when it doesn't exist), not by
  its version.
- A read loop MUST wait for a free slot of its method before each take.

### 6.3 Answering

- The server runs the method with a context (`requestId`, `methodName`) and
  writes a success or remote-error response. An exception MUST become a
  remote error.
- A response MUST be written in one round trip (a pipeline or a script), in
  this order:
  1. `LPUSH anycall:responses:<request id> <response>`
  2. `EXPIRE anycall:responses:<request id> RESPONSE_TTL`
  3. `LREM anycall:processing:<server id> 1 <request>`, with the request
     exactly as taken.
- A request that is invalid (not JSON, a missing or unknown field, a
  `payload` that doesn't fit the parameter) MUST get a remote error on its
  own response queue, as long as its `requestId` is readable: the entry is a
  JSON object whose `requestId` is a non-empty string. A server SHOULD read
  the `requestId` on its own only after the full read fails.
- A request whose `requestId` isn't readable MUST NOT be answered. The server
  MUST `LREM` it from its processing list and SHOULD log it.

### 6.4 Concurrency

- Each method has a `max_concurrency`, default `1`, at least `1`.
- A server MAY have a server-wide `max_concurrency`, at least `1`. It caps
  running requests, not taking: taking may exceed it by one request per
  method.

### 6.5 Stopping

- On stop or unregister, read loops MUST stop taking within `TAKE_BLOCK`.
  Requests already taken MUST still be run and answered.
- A server SHOULD NOT remove its own live-set entry; it ages out and is
  reaped with an empty list.

## 7. Reaping

See [docs/reaping.md](docs/reaping.md). For each server believed dead:

1. Run CLAIM. It checks again, so a server that heartbeated meanwhile is left
   alone.
2. For each returned request, read its `requestId` on its own, as above, and
   write a server-lost response with `LPUSH` + `EXPIRE`, without `LREM`. Drop
   a request whose `requestId` isn't readable.

A failure reaping one server MUST NOT stop the others, nor fail the call or
heartbeat that triggered it.

## 8. Client

### 8.1 Calling

1. **Liveness**: `TIME`, then `ZCOUNT anycall:servers:alive` from now −
   `HEARTBEAT_TTL`. If zero, fail with `NoServerAvailableError`.
2. **Queue depth**: if the call has a `max_queue_depth` (its own or the
   client's default) and `LLEN anycall:requests:<method>` is at least that,
   fail with `QueueFullError`.
3. **Publish**: `LPUSH anycall:requests:<method> <request>`.

Both checks are advisory.

### 8.2 Waiting

- `BRPOP anycall:responses:<request id>` in slices of at most `WAIT_SLICE`,
  until a response or the timeout.
- Each slice MUST be whole seconds, rounded up: Redis before 6.0 rejects a
  fractional timeout, and `0` would mean forever. A call may therefore time
  out up to 1s late.
- A timeout of zero means no limit, and is the default.
- After each empty slice, the client MUST run STALE and reap what it returns.
- The socket read timeout MUST be `WAIT_SLICE` plus a margin, whatever the
  call timeout: no command blocks longer than a slice, so one that outlasts it
  is stuck on a Redis that stopped answering.
- A command that fails while disconnected MUST fail at once, not wait for a
  reconnect.
- When the call ends, the client MUST `DEL` its response queue, unless it
  ended on a Redis failure.

### 8.3 Outcome

| Got | The call |
|---|---|
| nothing before the timeout | `TimeoutError` |
| `lostServer` set | `ServerLostError`, with the server id |
| non-null `error` | `RemoteException` |
| null `payload` and null `error`, or invalid JSON | `SerializationError` |
| a `payload` that doesn't fit the expected type | `SerializationError` |
| a Redis command failed (before the `LPUSH`, or from it on) | `BrokerError`, with `published` false, or true |
| otherwise | returns `payload` as the expected type; `"null"` is null for any type |

The client MUST NOT retry a lost request on its own: it may have partly run.

A crash is noticed 8–10s after the last heartbeat by a live server, or 8–18s
by the waiting client if none is alive.

## 9. Library API

Every implementation MUST offer the same operations, defaults and errors, in
its own language's style.

**Factory**

| Operation | Parameters (default) |
|---|---|
| client | Redis URI; timeout (zero); default `max_queue_depth` (none) |
| server | Redis URI; server-wide `max_concurrency` (none) |

**Client**

| Operation | Behavior |
|---|---|
| `call(method, request, type[, max_queue_depth])` | returns the payload as `type` |
| `call(method, request[, max_queue_depth])` | uses the type registered for `method`; fails if none |
| `raw_call(method, request[, max_queue_depth])` | returns the payload as a native map |
| `register_type(method, type)` | once; the same type again is a no-op, a different one fails |
| `get_queue_depth(method)` | `LLEN` of the method's queue |
| default `max_queue_depth` | get and set; a per-call value wins |

**Server**

| Operation | Behavior |
|---|---|
| register | one or more objects; each supply method is served under its name and `max_concurrency` |
| unregister | stops serving one method |
| start, stop, is running | start heartbeats then takes; stop finishes what was taken |
| server id | the instance's id |

A supply method takes the context and the request, deserialized to its
parameter's type.

**Errors**

| Error | Is a | When |
|---|---|---|
| `AnyCallError` | — | base of all; also a missing registered type |
| `PublishError` | `AnyCallError` | the call couldn't be delivered or answered |
| `NoServerAvailableError` | `PublishError` | no live server; carries the method |
| `QueueFullError` | `PublishError` | the queue is at its limit; carries method, depth, limit |
| `TimeoutError` | `PublishError` | no response before the timeout; carries the request id |
| `ServerLostError` | `PublishError` | the server died with the request; carries the request and server ids |
| `BrokerError` | `PublishError` | a Redis command failed during the call; carries the request id and whether it may have been published |
| `RemoteExecutionError` | `AnyCallError` | base of remote errors |
| `RemoteException` | `RemoteExecutionError` | the response has an `error` |
| `SerializationError` | `AnyCallError` | encoding or decoding failed |
