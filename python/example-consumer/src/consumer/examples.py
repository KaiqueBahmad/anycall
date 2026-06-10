"""Examples of call(), call_raw(), and register_type() usage."""

from dataclasses import dataclass

from anycall import AnyCall

from .model.create_product_request import CreateProductRequest
from .model.product import Product


@dataclass
class OrderResponse:
    """Example response type (different from Product)."""
    order_id: str
    total: int


def example_call_with_explicit_type():
    """Example 1: call() with explicit type (typed raia)."""
    print("\n=== Example 1: call() with explicit type ===")
    client = AnyCall.client("redis://localhost:6379")

    req = CreateProductRequest(name="Keyboard", price_in_cents=10000)
    product = client.call(
        "create-new-product",
        req,
        Product  # Explicit type → no registry needed
    )
    print(f"Product: {product}")
    assert isinstance(product, Product)
    assert product.name == "Keyboard"


def example_call_with_registry():
    """Example 2: call() with registry (typed raia, registry-resolved)."""
    print("\n=== Example 2: call() with registry ===")
    client = AnyCall.client("redis://localhost:6379")

    # Register the type once
    client.register_type("create-new-product", Product)

    # Now call without explicit type
    req = CreateProductRequest(name="Mouse", price_in_cents=5000)
    product = client.call("create-new-product", req)  # No Type arg
    print(f"Product from registry: {product}")
    assert isinstance(product, Product)
    assert product.name == "Mouse"


def example_call_raw():
    """Example 3: call_raw() always returns dict (raw raia)."""
    print("\n=== Example 3: call_raw() ===")
    client = AnyCall.client("redis://localhost:6379")

    req = CreateProductRequest(name="Monitor", price_in_cents=20000)
    raw_result = client.call_raw("create-new-product", req)
    print(f"Raw result: {raw_result}")
    assert isinstance(raw_result, dict)
    assert raw_result["name"] == "Monitor"
    assert raw_result["price_in_cents"] == 20000


def example_registry_absent_error():
    """Example 4: call() without type and without registry → error."""
    print("\n=== Example 4: Registry absent error ===")
    client = AnyCall.client("redis://localhost:6379")

    req = CreateProductRequest(name="Laptop", price_in_cents=300000)
    try:
        # No Type arg, no registry entry → must fail loudly
        product = client.call("create-new-product", req)
        print("ERROR: Should have raised AnyCallException!")
    except Exception as e:
        print(f"✓ Expected error: {e}")
        assert "create-new-product" in str(e)
        assert "register_type" in str(e) or "explicit type" in str(e)


def example_duplicate_type_error():
    """Example 5: Duplicate registration with different type → error."""
    print("\n=== Example 5: Duplicate type error ===")
    client = AnyCall.client("redis://localhost:6379")

    # Register with Product type
    client.register_type("create-new-product", Product)
    print("✓ Registered 'create-new-product' with Product")

    # Try to register same operation with different type
    try:
        client.register_type("create-new-product", OrderResponse)
        print("ERROR: Should have raised AnyCallException!")
    except Exception as e:
        print(f"✓ Expected error: {e}")
        assert "create-new-product" in str(e)
        assert "already registered" in str(e)


def example_duplicate_type_idempotent():
    """Example 6: Duplicate registration with SAME type → idempotent (no-op)."""
    print("\n=== Example 6: Duplicate type (same) = idempotent ===")
    client = AnyCall.client("redis://localhost:6379")

    # Register with Product type
    client.register_type("create-new-product", Product)
    print("✓ Registered 'create-new-product' with Product")

    # Register same operation with same type → no error
    client.register_type("create-new-product", Product)
    print("✓ Re-registered 'create-new-product' with Product (idempotent, no error)")


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
