# AnyCall Client — call() vs call_raw() Design

## Overview

The AnyCall Python client provides two distinct call paths with **predictable, always-clear semantics**:

- **`call(op, req, Type?)`** — **Typed raia**: Always returns deserialized model object
- **`call_raw(op, req)`** — **Raw raia**: Always returns native dict

No method ever silently falls back or returns different types. The contract is explicit in the method name.

## Typed Raia: `call(operation, request, response_type?)`

### Two Overloads

1. **With explicit type**: `call("analyze-sentiment", req, Product)`
   - Deserializes response JSON to `Product` directly
   - Fast path; no registry lookup
   
2. **Without explicit type**: `call("analyze-sentiment", req)`
   - Looks up `"analyze-sentiment"` in local registry
   - If registered: deserializes to registered type
   - If NOT registered: **raises clear error** (see below)

### Error: Missing Type (Fail-Loud)

```python
client.call("unknown-op", req)  # No type, not in registry
# → AnyCallException:
#   "No response type registered for operation 'unknown-op'.
#    Either call with explicit type: call('unknown-op', req, YourType),
#    or register the type first: register_type('unknown-op', YourType)."
```

**Rationale**: Silent fallback to dict would hide bugs. If you want dict, use `call_raw()` explicitly.

### Returns

- **Always** a model object (never dict from this method)
- Type matches what was passed or registered

## Raw Raia: `call_raw(operation, request)`

### Behavior

- Never looks at registry
- Always deserializes response to native `dict`
- Explicit path for "I want data without a model"

```python
raw = client.call_raw("analyze-sentiment", req)
# → {'name': 'Keyboard', 'price_in_cents': 10000}

assert isinstance(raw, dict)
```

### Returns

- **Always** a dict (never a model from this method)
- No type system involved

## Registry: `register_type(operation, response_type)`

### Write-Once Semantics

The registry is **write-once, mostly-read**:

- **First registration**: succeeds
  ```python
  client.register_type("analyze-sentiment", Product)  # OK
  ```

- **Re-register with SAME type**: idempotent, no-op
  ```python
  client.register_type("analyze-sentiment", Product)  # OK (idempotent)
  ```

- **Re-register with DIFFERENT type**: **error**
  ```python
  client.register_type("analyze-sentiment", Product)
  client.register_type("analyze-sentiment", OrderResponse)
  # → AnyCallException:
  #   "Operation 'create-new-product' already registered with type Product,
  #    cannot register OrderResponse. Either register with same type (idempotent)
  #    or recreate client."
  ```

### Rationale

Duplicate registration with different type catches **bugs** in startup code:
- Typo in operation name (same op registered twice)
- Copy-paste error (forgot to change the response type)
- Test/prod mismatch (different types loaded)

Reconfigurating a live operation is dangerous; if you need a fresh config, recreate the client.

### Thread-Safety

The registry uses **no explicit locks** — just CPython's GIL and atomicity of dict operations:
- Write-once pattern (each op registered once, at startup)
- No RMW loops, no contention on same key
- Lookups are simple dict reads (concurrent-safe under GIL)

If using a thread-unsafe dict in other Pythons (e.g., PyPy), wrap in a simple lock around `register()`.

## Security: Type Source Always Local & Trusted

**Invariant**: The type for deserialization NEVER comes from the JSON payload or wire.

- `call(op, req, Type)` → Type comes from code
- `call_raw(op, req)` → No deserialization of model type
- `call(op, req)` → Type from registry, filled at startup by your own code

Rejected patterns:
- ❌ `@class` field in JSON payload
- ❌ `Class.forName` on wire data
- ❌ Default typing in Jackson
- ❌ Polymorphic types inferred from response shape

## Examples

See `example-consumer/src/consumer/examples.py` for:
1. Typed call with explicit type
2. Typed call with registry
3. Raw call
4. Error on missing type
5. Error on duplicate type (different)
6. Idempotent re-registration (same type)

## API Consistency Across Languages

This design is **intentionally identical** across Java, Python, Node.js, and Go:
- Same method names: `call`, `call_raw`, `register_type`
- Same semantics: explicit type + registry lookup, fail-loud on missing
- Same error messages: nominate operation, type names, and instructions
- Same security: type from local source, never from wire

Only the return type idiom changes:
- Python: dict (built-in)
- Java: Map<String,Object>
- Node.js: Object
- Go: map[string]interface{}
