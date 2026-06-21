"""Examples of call(), call_raw(), and register_type() usage."""

from dataclasses import dataclass

from anycall import AnyCall

from .model.text_request import TextRequest
from .model.sentiment import Sentiment


@dataclass
class OrderResponse:
    """Example response type (different from Product)."""
    order_id: str
    total: int


def example_call_with_explicit_type():
    """Example 1: call() with explicit type (typed raia)."""
    print("\n=== Example 1: call() with explicit type ===")
    client = AnyCall.client("redis://localhost:6379")

    req = TextRequest(text="This is great!")
    sentiment = client.call(
        "analyze-sentiment",
        req,
        Sentiment  # Explicit type → no registry needed
    )
    print(f"Sentiment: {sentiment}")
    assert isinstance(sentiment, Sentiment)
    assert sentiment.text == "This is great!"


def example_call_with_registry():
    """Example 2: call() with registry (typed raia, registry-resolved)."""
    print("\n=== Example 2: call() with registry ===")
    client = AnyCall.client("redis://localhost:6379")

    # Register the type once
    client.register_type("analyze-sentiment", Sentiment)

    # Now call without explicit type
    req = TextRequest(text="Absolutely wonderful!")
    sentiment = client.call("analyze-sentiment", req)  # No Type arg
    print(f"Sentiment from registry: {sentiment}")
    assert isinstance(sentiment, Sentiment)
    assert sentiment.text == "Absolutely wonderful!"


def example_call_raw():
    """Example 3: call_raw() always returns dict (raw raia)."""
    print("\n=== Example 3: call_raw() ===")
    client = AnyCall.client("redis://localhost:6379")

    req = TextRequest(text="Looking good!")
    raw_result = client.call_raw("analyze-sentiment", req)
    print(f"Raw result: {raw_result}")
    assert isinstance(raw_result, dict)
    assert raw_result["text"] == "Looking good!"
    assert raw_result["label"] == "positive"


def example_registry_absent_error():
    """Example 4: call() without type and without registry → error."""
    print("\n=== Example 4: Registry absent error ===")
    client = AnyCall.client("redis://localhost:6379")

    req = TextRequest(text="Unknown operation")
    try:
        # No Type arg, no registry entry → must fail loudly
        sentiment = client.call("unknown-operation", req)
        print("ERROR: Should have raised AnyCallException!")
    except Exception as e:
        print(f"✓ Expected error: {e}")
        assert "unknown-operation" in str(e)
        assert "register_type" in str(e) or "explicit type" in str(e)


def example_duplicate_type_error():
    """Example 5: Duplicate registration with different type → error."""
    print("\n=== Example 5: Duplicate type error ===")
    client = AnyCall.client("redis://localhost:6379")

    # Register with Sentiment type
    client.register_type("analyze-sentiment", Sentiment)
    print("✓ Registered 'analyze-sentiment' with Sentiment")

    # Try to register same operation with different type
    try:
        client.register_type("analyze-sentiment", OrderResponse)
        print("ERROR: Should have raised AnyCallException!")
    except Exception as e:
        print(f"✓ Expected error: {e}")
        assert "analyze-sentiment" in str(e)
        assert "already registered" in str(e)


def example_duplicate_type_idempotent():
    """Example 6: Duplicate registration with SAME type → idempotent (no-op)."""
    print("\n=== Example 6: Duplicate type (same) = idempotent ===")
    client = AnyCall.client("redis://localhost:6379")

    # Register with Sentiment type
    client.register_type("analyze-sentiment", Sentiment)
    print("✓ Registered 'analyze-sentiment' with Sentiment")

    # Register same operation with same type → no error
    client.register_type("analyze-sentiment", Sentiment)
    print("✓ Re-registered 'analyze-sentiment' with Sentiment (idempotent, no error)")


if __name__ == "__main__":
    print("=" * 60)
    print("AnyCall Client Examples: call, call_raw, register_type")
    print("=" * 60)

    try:
        example_call_with_explicit_type()
    except Exception as e:
        print(f"⚠ Skipped (no supplier): {e}")

    try:
        example_call_with_registry()
    except Exception as e:
        print(f"⚠ Skipped (no supplier): {e}")

    try:
        example_call_raw()
    except Exception as e:
        print(f"⚠ Skipped (no supplier): {e}")

    # These work without supplier (registry/error logic)
    example_registry_absent_error()
    example_duplicate_type_error()
    example_duplicate_type_idempotent()

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)
