import logging
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any, Generic, Optional, Type, TypeVar

from . import queues
from .config import AnycallProperties
from .exceptions import AnyCallException
from .model import AnyCallRequest, AnyCallResponse
from .redis_adapter import RedisStreamAdapter
from .serialization import deserialize, serialize

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AnyCallClient(ABC):
    """Interface for RPC client."""

    @abstractmethod
    def call(self, method_name: str, request: Any, response_type: Type[T] | None = None) -> T | dict:
        """Call a remote method and wait for response.

        Args:
            method_name: Name of the method to invoke
            request: Request object (will be serialized to JSON)
            response_type: Expected response type (optional, returns dict if not provided)

        Returns:
            Deserialized response object or dict

        Raises:
            AnyCallException: On timeout or remote error
        """
        pass


class AnyCallClientImpl(AnyCallClient):
    """RPC client implementation."""

    def __init__(self, redis_adapter: RedisStreamAdapter, props: AnycallProperties):
        self.redis = redis_adapter
        self.props = props

    def call(self, method_name: str, request: Any, response_type: Type[T] | None = None) -> T | dict:
        """Call a remote method and wait for response.

        Args:
            method_name: Name of the method to invoke
            request: Request object (will be serialized to JSON)
            response_type: Expected response type (optional, returns dict if not provided)

        Returns:
            Deserialized response object or dict

        Raises:
            AnyCallException: On timeout or remote error
        """
        payload = serialize(request)
        rpc_request = AnyCallRequest.create(method_name, payload)

        request_stream = queues.request_queue(method_name)
        response_stream = queues.response_queue(rpc_request.request_id)

        try:
            request_json = serialize(rpc_request)
            self.redis.add(request_stream, {"data": request_json})

            timeout_ms = int(self.props.timeout.total_seconds() * 1000)
            result = self.redis.read(response_stream, timeout_ms)

            if result is None:
                raise AnyCallException(
                    f"Timeout waiting for response from method: {method_name}"
                )

            stream_name, messages = result[0]
            message_id, message_data = messages[0]
            response_json = message_data[b"data"].decode("utf-8")
            response = deserialize(response_json, AnyCallResponse)

            if response.has_error():
                raise AnyCallException(f"Error from remote method: {response.error_msg}")

            if response_type is None:
                return deserialize(response.payload, dict)
            return deserialize(response.payload, response_type)

        finally:
            self.redis.delete(response_stream)
