from dataclasses import dataclass
from typing import Optional
import uuid


@dataclass
class AnyCallRequest:
    """RPC request envelope.

    Supports both camelCase (from Java) and snake_case field names during deserialization.
    """
    request_id: str
    method_name: str
    payload: str

    @staticmethod
    def create(method_name: str, payload: str) -> "AnyCallRequest":
        """Create a new request with a generated UUID."""
        return AnyCallRequest(
            request_id=str(uuid.uuid4()),
            method_name=method_name,
            payload=payload
        )

    @staticmethod
    def from_dict(data: dict) -> "AnyCallRequest":
        """Deserialize from dict, supporting both camelCase and snake_case keys."""
        # Normalize camelCase keys to snake_case
        normalized = {}
        for key, value in data.items():
            if key == "requestId":
                normalized["request_id"] = value
            elif key == "methodName":
                normalized["method_name"] = value
            else:
                normalized[key] = value

        return AnyCallRequest(**normalized)


@dataclass
class AnyCallResponse:
    """RPC response envelope."""
    request_id: str
    payload: Optional[str] = None
    error_msg: Optional[str] = None

    @staticmethod
    def success(request_id: str, payload: str) -> "AnyCallResponse":
        """Create a successful response."""
        return AnyCallResponse(request_id=request_id, payload=payload, error_msg=None)

    @staticmethod
    def error(request_id: str, error_message: str) -> "AnyCallResponse":
        """Create an error response."""
        return AnyCallResponse(request_id=request_id, payload=None, error_msg=error_message)

    def has_error(self) -> bool:
        """Check if this response contains an error."""
        return self.error_msg is not None
