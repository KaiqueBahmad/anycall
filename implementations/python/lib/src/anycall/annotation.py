def supply(method_name: str, max_concurrency: int = 1):
    """Decorator to mark a method as a supply (RPC handler).

    Args:
        method_name: The name of the operation this method handles
        max_concurrency: How many requests for this operation a single server
            instance may process at the same time. Composes with scaling out
            via multiple server processes and with the server-wide cap
            (AnyCall.server(uri, metrics_enabled, max_concurrency)), if set.
            Defaults to 1 (one at a time per instance).
    """
    if max_concurrency < 1:
        raise ValueError(f"max_concurrency must be at least 1, got {max_concurrency}")

    def decorator(func):
        func._supply_method_name = method_name
        func._supply_max_concurrency = max_concurrency
        return func
    return decorator
