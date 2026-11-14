from __future__ import annotations

from datetime import timedelta
from typing import Optional


class _Unset:
    """A setting the overrides leave to the client."""

    def __repr__(self) -> str:
        return "<client default>"


_UNSET = _Unset()


class CallOverrides:
    """Settings for one call that replace the client's, passed as the last
    argument of `call`, `raw_call` and their `aio` versions. A setting left
    out keeps the client's; `None` means no limit.

        urgent = CallOverrides(timeout=timedelta(seconds=5), max_queue_depth=None)
        client.call("analyze-sentiment", request, Sentiment, urgent)

    The same overrides can be reused across calls. Invalid values are
    rejected here, when the overrides are made.
    """

    __slots__ = ("_timeout", "_max_queue_depth")

    def __init__(
        self,
        *,
        timeout: Optional[timedelta] | _Unset = _UNSET,
        max_queue_depth: Optional[int] | _Unset = _UNSET,
    ):
        """
        Args:
            timeout: How long the call waits for its response; None waits with
                no limit. Must be positive.
            max_queue_depth: Reject the call with QueueFullError if the
                method's request queue already holds this many requests;
                None means no limit. Must be at least 1.

        Raises:
            ValueError: If a value is out of range
        """
        if isinstance(timeout, timedelta) and timeout <= timedelta(0):
            raise ValueError(f"timeout must be positive, or None for no limit; got {timeout}")
        if timeout is not None and not isinstance(timeout, (timedelta, _Unset)):
            raise TypeError(f"timeout must be a timedelta or None; got {type(timeout).__name__}")
        if isinstance(max_queue_depth, bool) or (
            max_queue_depth is not None and not isinstance(max_queue_depth, (int, _Unset))
        ):
            raise TypeError(f"max_queue_depth must be an int or None; got {type(max_queue_depth).__name__}")
        if isinstance(max_queue_depth, int) and max_queue_depth < 1:
            raise ValueError(f"max_queue_depth must be at least 1, or None for no limit; got {max_queue_depth}")
        self._timeout = timeout
        self._max_queue_depth = max_queue_depth

    def timeout_or(self, default: Optional[timedelta]) -> Optional[timedelta]:
        """The call's timeout: this override's, or `default` if left out."""
        return default if isinstance(self._timeout, _Unset) else self._timeout

    def max_queue_depth_or(self, default: Optional[int]) -> Optional[int]:
        """The call's queue limit: this override's, or `default` if left out."""
        return default if isinstance(self._max_queue_depth, _Unset) else self._max_queue_depth

    def __repr__(self) -> str:
        return f"CallOverrides(timeout={self._timeout!r}, max_queue_depth={self._max_queue_depth!r})"


NO_OVERRIDES = CallOverrides()
