def supply(method_name: str):
    """Decorator to mark a method as a supply (RPC handler).

    Args:
        method_name: The name of the operation this method handles
    """
    def decorator(func):
        func._supply_method_name = method_name
        return func
    return decorator
