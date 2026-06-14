"""Type registry for call-without-explicit-type resolution."""

from typing import Any, Dict, Type

from .exceptions import AnyCallError


class TypeRegistry:
    """Registry of response types for operations (write-once, mostly-read).

    Thread-safe under CPython GIL. Each operation is registered once (typically
    at startup) and then only read; no RMW loops, no contention on same key.
    """

    def __init__(self):
        self._types: Dict[str, Type] = {}

    def register(self, operation: str, response_type: Type) -> None:
        """Register a response type for an operation.

        Args:
            operation: Operation name
            response_type: Response type for deserialization

        Raises:
            AnyCallError: If operation already registered with different type
        """
        if operation in self._types:
            existing = self._types[operation]
            if existing is not response_type:
                raise AnyCallError(
                    "unknown",
                    f"Operation '{operation}' already registered with type "
                    f"{existing.__name__}, cannot register {response_type.__name__}. "
                    f"Either register with same type (idempotent) or recreate client."
                )
            return

        self._types[operation] = response_type

    def get(self, operation: str) -> Type | None:
        """Retrieve registered response type for operation.

        Args:
            operation: Operation name

        Returns:
            Response type if registered, None otherwise
        """
        return self._types.get(operation)

    def has(self, operation: str) -> bool:
        """Check if operation has registered type.

        Args:
            operation: Operation name

        Returns:
            True if registered, False otherwise
        """
        return operation in self._types
