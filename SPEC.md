# AnyCall Protocol — Contract 0.8

## 1. Conventions

- **MUST** / **MUST NOT**: required. An implementation that breaks it is wrong.
- **SHOULD** / **SHOULD NOT**: expected, unless there is a good reason not to.
- **MAY**: allowed, not required.

- **Client**: a process that calls methods. Each client instance has a
  **client id**: a random lowercase UUID, made when it's created and never
  reused. Every response to its calls goes to its own response queue.
- **Server**: a process that registers methods and answers calls. Each
  instance has a **server id**: a random lowercase UUID, made on every start
  and whenever the server is declared dead, and never reused.
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
| `anycall:processing:<server id>` | List; a string once reaped (a tombstone) | its server; reapers | its server, reapers | none; a tombstone `TOMBSTONE_TTL` |
| `anycall:responses:<client id>` | List: every response to that client's calls | server or reaper (`LPUSH`) | the client (`BRPOP`) | `RESPONSE_TTL`, set on every write |
| `anycall:servers:alive` | Sorted set: server id → now of its last heartbeat | servers | everyone | none |

Implementations MUST NOT write any other key under `anycall:`.

## 3. Messages

JSON objects, UTF-8, one List entry each.

**Request**

```json
{"requestId": "<uuid>", "clientId": "<client id>", "methodName": "<method>", "payload": "<json text>"}
```

- `requestId` MUST be a fresh random UUID.
- `clientId` MUST be the calling client's id: the response goes to
  `anycall:responses:<clientId>`.
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
| `TOMBSTONE_TTL` | 30 days | expiry of a dead server's tombstone |

## 5. Scripts

### 5.1 HEARTBEAT

`KEYS[1]` = `anycall:servers:alive`; `ARGV` = server id, `HEARTBEAT_TTL`,
`1` on the server id's first heartbeat (else `0`). Past its first heartbeat,
a server whose entry is gone or older than `HEARTBEAT_TTL` was declared dead:
it gets `{-1}` and nothing is written, so a dead server never comes back.
Otherwise refreshes its entry and returns `0`, followed by every dead server's
id. Removes nothing.

```lua
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local stale = string.format('%.6f', now - tonumber(ARGV[2]))
if ARGV[3] ~= '1' then
  local score = redis.call('ZSCORE', KEYS[1], ARGV[1])
  if not score or tonumber(score) < tonumber(stale) then return {-1} end
end
redis.call('ZADD', KEYS[1], string.format('%.6f', now), ARGV[1])
local result = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', '(' .. stale)
table.insert(result, 1, 0)
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

### 5.3 TOMBSTONE

`KEYS` = `anycall:servers:alive`, `anycall:processing:<server id>`; `ARGV` =
server id, `TOMBSTONE_TTL` in seconds. The last step of reaping a dead
server: if its list is still empty, removes it from the live set and, if it
was still there, turns its processing key into a tombstone string. Returns
`0` if a request landed on the list meanwhile, else `1`. A server whose
entry is already gone was reaped before; its tombstone isn't recreated, in
case the server came back and deleted it.

```lua
local kind = redis.call('TYPE', KEYS[2])['ok']
if kind == 'list' then return 0 end
if redis.call('ZREM', KEYS[1], ARGV[1]) == 1 and kind == 'none' then
  redis.call('SET', KEYS[2], 'drained', 'EX', ARGV[2])
end
return 1
```

### 5.4 DROP_TOMBSTONE

`KEYS` = `anycall:processing:<server id>`. Deletes the key only if it's a
tombstone.

```lua
if redis.call('TYPE', KEYS[1])['ok'] == 'string' then return redis.call('DEL', KEYS[1]) end
return 0
```

## 6. Server

See [docs/taking-requests.md](docs/taking-requests.md).

### 6.1 Liveness

- Before taking any request, a server MUST run HEARTBEAT once successfully.
  If it fails, starting MUST fail and the server MUST NOT take anything.
- While running, it MUST run HEARTBEAT every `HEARTBEAT_PERIOD` and reap every
  dead server it returns. Request processing MUST NOT delay it.
- A server whose heartbeat is older than `HEARTBEAT_TTL` is dead, for good:
  HEARTBEAT refuses its id from then on.

### 6.2 Draining

A server that gets `-1` from HEARTBEAT was declared dead while still running
(a long GC pause, a frozen VM, Redis unreachable). It MUST NOT stop or fail:
its old server id **drains**, and it carries on under a new one. It SHOULD
log a warning.

- It heartbeats under the new id at once, as a first heartbeat. Read loops
  MUST NOT take under the new id before that heartbeat went through, and
  never again under the draining one.
- Requests taken under the draining id that are still running finish, but
  their results MUST be discarded: reapers fail them back, and the draining
  id's processing list belongs to them.
- They keep their concurrency slots until they finish, as if nothing had
  changed: the new id only takes what the slots left allow. A method with
  `max_concurrency` 3 and 2 requests still draining takes 1 more until they
  finish.
- A take that fails with `WRONGTYPE` hit the draining id's tombstone: the id
  was reaped, so it's dead. The request stays in its queue; the server MUST
  drain at once, without waiting for HEARTBEAT to be refused.
- Once no take started under the draining id is still running, nothing can
  land on its list anymore. The server MUST then reap that id (in case no
  one did) and delete its own tombstone with DROP_TOMBSTONE. A server that
  dies before that leaves its tombstone to expire.

A server frozen longer than `TOMBSTONE_TTL` that then resumes as if nothing
happened may lose a request taken in the moment before it notices it's
dead. That's the only bound draining relies on, and it's measured by Redis's
clock.

### 6.3 Taking

- Each method MUST have its own read loop, taking one request at a time with
  `BLMOVE anycall:requests:<method> anycall:processing:<server id> RIGHT LEFT TAKE_BLOCK`
  where Redis has it (6.2+), and otherwise with the equivalent
  `BRPOPLPUSH anycall:requests:<method> anycall:processing:<server id> TAKE_BLOCK`,
  which 6.2 deprecates. No other command.
- The server MUST pick between the two once, on start, by asking Redis for
  the command (`COMMAND INFO BLMOVE` is `nil` when it doesn't exist), not by
  its version.
- A read loop MUST wait for a free slot of its method before each take.
- A dead server's processing key is a tombstone once reaped: a take onto it
  fails with `WRONGTYPE`, and Redis leaves the request in its queue.

### 6.4 Answering

- The server runs the method with a context (`requestId`, `methodName`) and
  writes a success or remote-error response. An exception MUST become a
  remote error.
- A response MUST be written in one round trip (a pipeline or a script), in
  this order:
  1. `LPUSH anycall:responses:<client id> <response>`
  2. `EXPIRE anycall:responses:<client id> RESPONSE_TTL`
  3. `LREM anycall:processing:<server id> 1 <request>`, with the request
     exactly as taken.
- A request that is invalid (not JSON, a missing or unknown field, a
  `payload` that doesn't fit the parameter) MUST get a remote error on its
  client's response queue, as long as its `requestId` and `clientId` are
  readable: the entry is a JSON object in which both are non-empty strings. A
  server SHOULD read them on their own only after the full read fails.
- A request whose `requestId` or `clientId` isn't readable MUST NOT be
  answered. The server MUST `LREM` it from its processing list and SHOULD log
  it.

### 6.5 Concurrency

- Each method has a `max_concurrency`, default `1`, at least `1`.
- A server MAY have a server-wide `max_concurrency`, at least `1`. It caps
  running requests, not taking: taking may exceed it by one request per
  method.

### 6.6 Stopping

- On stop or unregister, read loops MUST stop taking within `TAKE_BLOCK`.
  Requests already taken MUST still be run and answered.
- A server SHOULD NOT remove its own live-set entry; it ages out and is
  reaped with an empty list.

## 7. Reaping

See [docs/reaping.md](docs/reaping.md). A dead server's requests are failed
back one at a time, each in a transaction of its own, until none is left:

1. `WATCH anycall:processing:<server id>`, then `TYPE` of it:
   - a string: it's a tombstone, the server was reaped before. Stop.
   - none: the list is empty. Run TOMBSTONE; if it returns `0`, start again
     from step 1, else stop.
2. `LINDEX anycall:processing:<server id> -1`, and read its `requestId` and
   `clientId` the way a server does. Requests MUST NOT be read inside a
   script.
3. `MULTI`, `LTRIM anycall:processing:<server id> 0 -2`, which drops the
   request read in step 2 (the `WATCH` guarantees it's still the last), and,
   if both are readable, a server-lost response to the client's queue with
   `LPUSH` + `EXPIRE`, as a server writes a response. A request without them
   is dropped.
4. `EXEC`. If it was discarded, start again from step 1.

A dead server never heartbeats again, so nothing about it needs checking
first. A request leaves the list only in the `EXEC` that writes its response,
so a reaper that dies at any point loses nothing. `WATCH` and `MULTI` belong to a
connection: a reaper MUST NOT share its connection with anything else while
reaping.

A failure reaping one server MUST NOT stop the others, nor fail the call or
heartbeat that triggered it.

## 8. Client

### 8.1 Calling

1. **Liveness**: `TIME`, then `ZCOUNT anycall:servers:alive` from now −
   `HEARTBEAT_TTL`. If zero, fail with `NoServerAvailableError`.
2. **Queue depth**: if the call has a `max_queue_depth` (its own or the
   client's default) and `LLEN anycall:requests:<method>` is at least that,
   fail with `QueueFullError`.
3. **Publish**: `LPUSH anycall:requests:<method> <request>`. The call MUST be
   waiting for its response (see Waiting) before the `LPUSH`, so a fast
   response always finds it.

Both checks are advisory.

### 8.2 Waiting

A client reads its own response queue with a single **reader** and hands each
response to the call waiting for it, so any number of calls can wait at once.

- The reader runs `BRPOP anycall:responses:<client id>` in slices of
  `WAIT_SLICE`, whole seconds.
- It reads each response's `requestId` on its own, like a server reads a
  request's, and hands the response to the call waiting for that id. A
  response with no readable `requestId`, or for a call no longer waiting (it
  timed out), is dropped.
- After each empty slice while calls are waiting, it MUST run STALE and reap
  every dead server it returns.
- Each call's timeout is measured by the client, on the call; zero means no
  limit, and is the default. A call that times out stops waiting.
- If a Redis command under the reader fails, every waiting call MUST fail
  with `BrokerError` (`published` true), and the reader starts over.
- The socket read timeout MUST be `WAIT_SLICE` plus a margin: no command
  blocks longer than a slice, so one that outlasts it is stuck on a Redis
  that stopped answering.
- A command that fails while disconnected MUST fail at once, not wait for a
  reconnect.
- A client never deletes its response queue: it's empty, and so gone, while
  nothing waits in it, and `RESPONSE_TTL` removes it once the client is gone.

### 8.3 Outcome

| Got | The call |
|---|---|
| nothing before the timeout | `TimeoutError` |
| `lostServer` set | `ServerLostError`, with the server id |
| non-null `error` | `RemoteException` |
| null `payload` and null `error`, or an otherwise invalid response | `SerializationError` |
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

**Asynchronous calls.** `call` and `raw_call` MUST also be offered without
blocking, returning the language's future or awaitable instead of the
result: Java's `client.async()`, whose methods return a `CompletableFuture`,
and Python's `client.aio`, whose methods are awaited. Same operations,
registered types, timeout and errors, on the same response queue.

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
