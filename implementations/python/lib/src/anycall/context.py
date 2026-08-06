class AnycallContext:
    """Per-invocation context passed as the first parameter to every @supply method.

    Currently carries no data; reserved for future additions (e.g. auth, tracing,
    metadata) without requiring another change to the @supply method signature.
    """
    pass
