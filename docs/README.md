# AnyCall docs

Documentation that applies to every implementation (Java, Python). How to
use each library lives next to it, in `implementations/<language>/USAGE.md`.

| Topic | Read | Visual |
|---|---|---|
| What happens when a server dies mid-request: who notices, how long it takes, and what the caller gets | [reaping.md](reaping.md) | [reaping.html](visuals/reaping.html) |
| How a server takes a request without a crash ever losing it, and how it hears a new one arrived | [taking-requests.md](taking-requests.md) | [taking-requests.html](visuals/taking-requests.html) |
| How servers took requests before, with a blocking `BRPOP`, and why a crash lost the request | [taking-requests-legacy.md](taking-requests-legacy.md) | [taking-requests-legacy.html](visuals/taking-requests-legacy.html) |
