def supply(method_name: str, max_concurrency: int = 1):
    """Marks a method as a supply (RPC handler).

    max_concurrency caps how many requests for this operation a single
    server instance processes at once; composes with the server-wide cap
    (AnyCall.server(..., max_concurrency=...)).
    """
    if max_concurrency < 1:
        raise ValueError(f"max_concurrency must be at least 1, got {max_concurrency}")

    def decorator(func):
        func._supply_method_name = method_name
        func._supply_max_concurrency = max_concurrency
        return func
    return decorator
