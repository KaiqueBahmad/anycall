# AnyCall Library

How a library implementing [the protocol](PROTOCOL.md) exposes it to the code
that uses it. Unlike the protocol, little here is required: a library that
differs still talks to every other. **MUST** marks only what a caller can't
do without; the rest is **SHOULD** or **MAY**, as defined in the protocol's
conventions, so implementations stay alike where their languages let them.

Every implementation SHOULD offer the operations below, with the defaults and
errors given. The names here describe the operations; each implementation's
usage guide gives its own, in its language's style. Where an operation needs
something a language may not have, such as reading types or annotations at
runtime, it says so and is a MAY.

**Creating**

| Operation | Takes (default) |
|---|---|
| client | Redis URL; call options, the defaults of every call (none: no limits); key prefix (`anycall`) |
| server | Redis URL; server options (none: no limits); key prefix (`anycall`) |

**Client**

| Operation | Behavior |
|---|---|
| call(method, request[, options]) | publishes the request, waits for its response and returns the payload converted as the caller asks |
| raw call(method, request[, options]) | returns the payload as the language's native map |
| queue depth(method) | `LLEN` of the method's queue |
| defaults | the client's call options, each setting set |
| update defaults(options) | for calls made after: what `options` set replaces the client's, what they leave out stays |
| close | stops the client at once; again is a no-op |

How a call converts the payload is an argument of the call, not an option, so
a typed language can make the call's result follow it: a type, a decoder, or
whatever the language uses. Where conversion is by type, an implementation
MAY also let a type be registered for a method once and used by calls that
give none; registering the same type again is a no-op, a different one fails,
and a call with neither fails.

**Call options.** A call's `timeout` and `max_queue_depth`, each of which can
be set to no limit. Given when creating the client, they're the defaults of
every call, and a setting left out has no limit; given to one call, they
replace the client's, and a setting left out keeps the client's. A timeout
SHOULD be positive and a `max_queue_depth` at least 1, rejected when the
options are made, and the options SHOULD tell a setting left out from one set
to no limit. Server options hold the server-wide `max_concurrency`, made the
same way: when creating the server, a setting left out has no limit; given to
update options, it stays as the server has it.

**Closing.** Close MUST fail every call still waiting, with
`ClientClosedError`, since nothing will ever answer them; every call made
after SHOULD fail the same way, before publishing anything. It SHOULD end the
reader at once, closing its connection under a blocked `BRPOP` rather than
waiting out the slice, and release every connection before it returns. A
request already published may still be processed; its response is dropped,
and `RESPONSE_TTL` removes the queue (see [PROTOCOL.md](PROTOCOL.md)). Where
the language closes a resource at the end of a block, the client SHOULD
support it.

**Asynchronous calls.** Where the language has a way for a caller not to
block (a future, a promise, a coroutine), call and raw call SHOULD also be
offered that way: same operations, conversions, options and errors, on the
same response queue.

**Server**

| Operation | Behavior |
|---|---|
| register | makes methods servable, each under a name, with a `max_concurrency` (default 1); registering a name again replaces it |
| register method(declaration, handler) | serves one function under the declaration's name, request type and `max_concurrency`, as register does |
| unregister | stops serving one method, by name |
| start, stop, is running | start heartbeats then takes; stop finishes what was taken |
| close | stops, then releases every connection; a closed server can't start again; again is a no-op |
| server id | the instance's id |
| options | the server's options, each setting set |
| update options(options) | while it runs: what `options` set replaces the server's, what they leave out stays; a lower `max_concurrency` lets what's running finish |
| methods | the names of every registered method, sorted |
| method(name) | a registered method's `max_concurrency` now, how many of its requests are running now, and its declaration; fails if none |
| set max concurrency(method, n) | while it runs, at least 1; a registered method only; lower lets what's running finish |

How methods are declared is the implementation's: marked methods of an
object, functions given a name, or anything else the language suits. A method
takes the context and the request, the request converted as it declares.

**Declarations.** A method's declaration is what it was registered with: its
name and `max_concurrency`, and, where the language can tell, its request and
response types. The response type is only informative: a server sends back
whatever the method returns. An implementation that finds methods on objects
MAY also describe an object without a server, accepting and rejecting the
same objects registering would: methods(object), the names of its methods,
sorted, and method(object, name), one method's declaration, failing if it has
none by that name.

**Errors**

Each error MUST be told apart from the others, or a caller can't react to
what went wrong. Where the language has a hierarchy of errors,
implementations SHOULD keep the one below, so a caller can handle, say, every
publish error at once.

| Error | Kind of | When |
|---|---|---|
| `AnyCallError` | — | base of all; also a call with no conversion given or registered |
| `PublishError` | `AnyCallError` | the call couldn't be delivered or answered |
| `QueueFullError` | `PublishError` | the queue is at its limit; carries method, depth, limit |
| `TimeoutError` | `PublishError` | no response before the timeout; carries the request id |
| `ServerLostError` | `PublishError` | the server died with the request; carries the request and server ids |
| `BrokerError` | `PublishError` | a Redis command failed during the call; carries the request id and whether it may have been published |
| `RemoteExecutionError` | `AnyCallError` | base of remote errors |
| `RemoteException` | `RemoteExecutionError` | the response has an `error` |
| `SerializationError` | `AnyCallError` | encoding or decoding failed |
| `ClientClosedError` | `AnyCallError` | the client was closed: a call made after, or one still waiting |

## Payload types

A method's request and response, and the type a call reads its result into,
are limited on purpose to what JSON itself has, so a type means the same in
every language. Every implementation MUST accept these and only these. A
type has to be a `T`:

```
T = boolean
  | integer
  | number
  | string
  | array of T
  | map of string to T
  | record of fields, each a T
  | T or null
```

- An integer is between −(2^53 − 1) and 2^53 − 1, the range a 64-bit float
  holds exactly: some languages read every JSON number as one, and a larger
  integer would arrive rounded. A larger value goes as a string. A number is
  a 64-bit float.
- A map's keys are data: any string. A record's fields are part of the type:
  each named, each with its own `T`. Both are a JSON object on the wire; the
  type declared on the reading side says which, at every level, never the
  wire.
- A type MAY refer to itself, as a category with an array of categories.

Anything else is not a payload type: bytes, enums, dates and durations,
UUIDs, arbitrary-precision numbers, sets, tuples, maps keyed by anything but
a string, unions other than `T or null`. Their meaning differs between
languages, so the code using the library converts them to a string or a
number of its own choosing. Where the language's JSON library would convert
one of them on its own, the implementation MUST still reject it, or it would
work in one language only.

**Checking.** Where the language can read types at runtime, a declared type
MUST be checked when it's given, not when the first request arrives:
registering a method checks its request and response types, and registering
a type for a method or calling with one checks that type. A type that isn't
a payload type fails with the language's usual error for a bad argument,
naming the field and its type. A value is also checked as it's written, by
the same rules, and fails with `SerializationError`; a call whose request
fails this way publishes nothing.

**Writing.**
- Every field of a record MUST be written, `null` ones included.
- An integer out of range MUST NOT be written: a call whose request has one
  publishes nothing, and a server whose method returns one answers with a
  remote error instead.
- `NaN` and the infinities MUST NOT be written; JSON has no such numbers.
- A payload is a tree. Cyclic data MUST fail. The same object reached twice
  is written twice and read back as two.

**Reading**, into the declared type:
- A record with a field it doesn't declare, or missing one it does, MUST be
  rejected.
- `null` is read only where the type is `T or null`, except as the whole
  payload: a method that returns null sends `null` whatever its type (see
  [PROTOCOL.md](PROTOCOL.md)).
- An integer MAY be read where a number is declared: JSON doesn't tell `1`
  from `1.0`, and languages write either. A number with a fraction, or an
  integer out of range or that doesn't fit the declared one, MUST be
  rejected where an integer is declared.
- A boolean is never read as a number, nor a number as a boolean.
- A server answers a request that doesn't fit its method's request type
  with a remote error (see [PROTOCOL.md](PROTOCOL.md)); a call whose result
  doesn't fit fails with `SerializationError`.

A raw call reads with no declared type: an object as the language's native
map, an array as its native list, and the rest as its own boolean, integer,
number, string and null.

Each implementation's usage guide MUST give its mapping both ways: which of
its types each `T` is written from, and which it can be read into.
