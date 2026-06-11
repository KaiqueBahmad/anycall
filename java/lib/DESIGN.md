# AnyCall Client — call() vs callRaw() Design

## Overview

The AnyCall Java client provides two distinct call paths with **predictable, always-clear semantics**:

- **`call(op, req, Class<T>)`** — **Typed raia (explicit)**: Deserialize to explicit type
- **`call(op, req)`** — **Typed raia (registry)**: Lookup type from registry or fail
- **`callRaw(op, req)`** — **Raw raia**: Always returns Map<String,Object>

No method ever silently falls back or returns different types. The contract is explicit in the method name and signature.

## Typed Raia: call(String operation, Object request, Class<T> responseType)

### Behavior

- Deserializes response JSON to `responseType` directly
- Type comes from **code** (trusted), never from wire
- Fast path; no registry lookup

```java
Product product = client.call("create-new-product", req, Product.class);
```

## Typed Raia (Registry): call(String operation, Object request)

### Behavior

1. Looks up `operation` in local registry
2. If registered: deserializes to registered type
3. If NOT registered: **raises clear error** (see below)

```java
client.registerType("create-new-product", Product.class);
Product product = client.call("create-new-product", req);
```

### Error: Missing Type (Fail-Loud)

```java
client.call("unknown-op", req);
// → AnyCallException:
//   "No response type registered for operation 'unknown-op'.
//    Either call with explicit type: call('unknown-op', req, YourType),
//    or register the type first: registerType('unknown-op', YourType)."
```

**Rationale**: Silent fallback to Map would hide bugs. If you want Map, use `callRaw()` explicitly.

## Raw Raia: callRaw(String operation, Object request)

### Behavior

- Never looks at registry
- Always deserializes response to native `Map<String,Object>`
- Explicit path for "I want data without a model"

```java
Map<String,Object> raw = client.callRaw("create-new-product", req);
// → {"name": "Keyboard", "priceInCents": 10000}

assertTrue(raw instanceof Map);
```

## Registry: registerType(String operation, Class<?> responseType)

### Write-Once Semantics (ConcurrentHashMap + putIfAbsent)

- **First registration**: succeeds
  ```java
  client.registerType("create-new-product", Product.class);  // OK
  ```

- **Re-register with SAME type**: idempotent, no-op
  ```java
  client.registerType("create-new-product", Product.class);  // OK (idempotent)
  ```

- **Re-register with DIFFERENT type**: **error**
  ```java
  client.registerType("create-new-product", Product.class);
  client.registerType("create-new-product", Order.class);
  // → AnyCallException:
  //   "Operation 'create-new-product' already registered with type Product,
  //    cannot register Order. Either register with same type (idempotent)
  //    or recreate client."
  ```

### Rationale

Duplicate registration with different type catches **bugs** in startup code:
- Typo in operation name (same op registered twice)
- Copy-paste error (forgot to change the response type)
- Test/prod mismatch (different types loaded)

Reconfiguring a live operation is dangerous; if you need a fresh config, recreate the client.

### Thread-Safety (ConcurrentHashMap + putIfAbsent)

```java
// ConcurrentHashMap.putIfAbsent is atomic:
// No explicit locks, no double-checked locking
Class<?> existing = types.putIfAbsent(operation, responseType);
if (existing != null && existing != responseType) {
    throw new AnyCallException(...);
}
```

- Write-once pattern (each op registered once, at startup)
- putIfAbsent handles insertion atomically
- No RMW loops, no contention on same key
- Lookups are simple Map.get() (concurrent-safe)

## Security: Type Source Always Local & Trusted

**Invariant**: The type for deserialization NEVER comes from the JSON payload or wire.

- `call(op, req, Class<T>)` → Type comes from code (trusted)
- `callRaw(op, req)` → No deserialization of model type
- `call(op, req)` → Type from registry, filled at startup by your own code

Rejected patterns:
- ❌ `@class` field in JSON payload
- ❌ `Class.forName` on wire data
- ❌ Jackson default typing (polymorphic)
- ❌ ObjectMapper with enableDefaultTyping

## Examples

See `src/test/java/.../CallExamplesTest.java` for:
1. Typed call with explicit type
2. Typed call with registry
3. Raw call
4. Error on missing type
5. Error on duplicate type (different)
6. Idempotent re-registration (same type)

## API Consistency Across Languages

This design is **intentionally identical** across Java, Python, Node.js, and Go:
- Same method names: `call`, `callRaw`, `registerType` (camelCase in Java)
- Same semantics: explicit type + registry lookup, fail-loud on missing
- Same error messages: nominate operation, type names, and instructions
- Same security: type from local source, never from wire

Only the return type idiom changes:
- Java: Map<String,Object>
- Python: dict
- Node.js: Object
- Go: map[string]interface{}
