def supply(method_name: str, max_concurrency: int = 1):
    """Marks a method as a supply (RPC handler).

    max_concurrency caps how many requests for this operation a single
    server instance processes at once, when it's registered; composes with
    the server-wide cap (ServerOptions(max_concurrency=...)).

    Both can change while the server runs: this one with
    `server.set_max_concurrency`, the server-wide one with
    `server.update_options`. Registering the method again starts it over
    from this value.
    """
    if max_concurrency < 1:
        raise ValueError(f"max_concurrency must be at least 1, got {max_concurrency}")

    def decorator(func):
        func._supply_method_name = method_name
        func._supply_max_concurrency = max_concurrency
        return func
    return decorator
