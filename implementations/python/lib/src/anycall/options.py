from __future__ import annotations

from datetime import timedelta
from typing import Optional


class _Unset:
    """A setting the options leave out."""

    def __repr__(self) -> str:
        return "<unset>"


_UNSET = _Unset()


class CallOptions:
    """A call's settings: its timeout and its queue limit. `None` means no
    limit.

    Passed to `AnyCall.client`, they're the defaults of every call the client
    makes; a setting left out there means no limit. Passed as the last
    argument of `call`, `raw_call` and their `aio` versions, they apply to
    that one call; a setting left out there keeps the client's.

        client = AnyCall.client(uri, CallOptions(timeout=timedelta(seconds=30), max_queue_depth=100))
        client.call("analyze-sentiment", request, Sentiment, CallOptions(max_queue_depth=None))

    The same options can be reused. Invalid values are rejected here, when
    the options are made.
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
            TypeError: If a value has the wrong type
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

    def timeout_or(self, fallback: Optional[timedelta]) -> Optional[timedelta]:
        """The timeout these options set, or `fallback` if they leave it out."""
        return fallback if isinstance(self._timeout, _Unset) else self._timeout

    def max_queue_depth_or(self, fallback: Optional[int]) -> Optional[int]:
        """The queue limit these options set, or `fallback` if they leave it out."""
        return fallback if isinstance(self._max_queue_depth, _Unset) else self._max_queue_depth

    def __repr__(self) -> str:
        return f"CallOptions(timeout={self._timeout!r}, max_queue_depth={self._max_queue_depth!r})"


DEFAULT_CALL_OPTIONS = CallOptions()


class ServerOptions:
    """A server's settings. `None` means no limit.

    Passed to `AnyCall.server`, a setting left out means no limit. Passed to
    `server.update_options`, a setting left out stays as the server has it.

        server = AnyCall.server(uri, ServerOptions(max_concurrency=16))
        server.update_options(ServerOptions(max_concurrency=32))
    """

    __slots__ = ("_max_concurrency",)

    def __init__(self, *, max_concurrency: Optional[int] | _Unset = _UNSET):
        """
        Args:
            max_concurrency: Server-wide cap on requests processed at the same
                time, across every registered @supply method combined; each
                method's own max_concurrency still applies. None means no
                cap. Must be at least 1.

        Raises:
            ValueError: If max_concurrency is below 1
            TypeError: If max_concurrency isn't an int or None
        """
        if isinstance(max_concurrency, bool) or (
            max_concurrency is not None and not isinstance(max_concurrency, (int, _Unset))
        ):
            raise TypeError(f"max_concurrency must be an int or None; got {type(max_concurrency).__name__}")
        if isinstance(max_concurrency, int) and max_concurrency < 1:
            raise ValueError(f"max_concurrency must be at least 1, or None for no limit; got {max_concurrency}")
        self._max_concurrency = max_concurrency

    def max_concurrency_or(self, fallback: Optional[int]) -> Optional[int]:
        """The cap these options set, or `fallback` if they leave it out."""
        return fallback if isinstance(self._max_concurrency, _Unset) else self._max_concurrency

    def __repr__(self) -> str:
        return f"ServerOptions(max_concurrency={self._max_concurrency!r})"


DEFAULT_SERVER_OPTIONS = ServerOptions()
