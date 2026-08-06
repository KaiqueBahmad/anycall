from dataclasses import dataclass


@dataclass
class AnycallContext:
    """Per-invocation context passed as the first parameter to every @supply method.

    Reserved for future additions (e.g. auth, tracing, metadata) without requiring
    another change to the @supply method signature.
    """
    request_id: str
    method_name: str
