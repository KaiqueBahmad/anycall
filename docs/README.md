# AnyCall docs

Documentation that applies to every implementation (Java, Python). How to
use each library lives next to it, in `implementations/<language>/USAGE.md`.

| Topic | Read | Visual |
|---|---|---|
| What happens when a server dies mid-request: who notices, how long it takes, and what the caller gets | [reaping.md](reaping.md) | [reaping.html](visuals/reaping.html) (previous design: in-flight hash and the client's quiet timer, not updated yet) |
| How a server takes a request without a crash ever losing it, and why it holds one connection per method | [taking-requests.md](taking-requests.md) | [taking-requests.html](visuals/taking-requests.html) |