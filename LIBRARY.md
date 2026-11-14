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
| unregister | stops serving one method, by name |
| start, stop, is running | start heartbeats then takes; stop finishes what was taken |
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
