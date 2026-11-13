from dataclasses import dataclass
from typing import Optional, Tuple
import json
import uuid


def _read_field(item: str, field: str) -> Optional[str]:
    """A string field of a JSON object, read on its own, or None if the entry
    isn't a JSON object or the field isn't a non-empty string."""
    try:
        data = json.loads(item)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get(field)
    if not isinstance(value, str) or not value:
        return None
    return value


def read_reply_address(item: str) -> Optional[Tuple[str, str]]:
    """The (`requestId`, `clientId`) of a request entry, read on their own, or
    None if either is missing: the entry isn't a JSON object, or one of them
    isn't a non-empty string.

    For entries the strict read rejects (an unknown or missing field), so
    their error can still reach the client waiting for them: the response
    goes to the client's queue, and the client hands it to the call by its
    requestId.
    """
    request_id = _read_field(item, "requestId")
    client_id = _read_field(item, "clientId")
    if request_id is None or client_id is None:
        return None
    return request_id, client_id


def read_response_request_id(item: str) -> Optional[str]:
    """The `requestId` of a response, read on its own, or None: what a client
    hands the response to its call by, before the strict read."""
    return _read_field(item, "requestId")


# Wire name -> dataclass field, for each envelope. Only these names are read:
# anything else is an unknown field, and the message is rejected.
_REQUEST_FIELDS = {
    "requestId": "request_id",
    "clientId": "client_id",
    "methodName": "method_name",
    "payload": "payload",
}
_RESPONSE_FIELDS = {
    "requestId": "request_id",
    "payload": "payload",
    "error": "error_msg",
    "lostServer": "lost_server",
}


def _from_wire(data: dict, fields: dict[str, str]) -> dict:
    unknown = [key for key in data if key not in fields]
    if unknown:
        raise TypeError(f"unknown field(s): {', '.join(unknown)}")
    return {fields[key]: value for key, value in data.items()}


@dataclass
class AnyCallRequest:
    """RPC request envelope. On the wire its fields are camelCase, as Java
    writes them: `requestId`, `clientId`, `methodName`, `payload`. `clientId`
    names the response queue the answer goes to (see `queues.response_queue`)."""
    request_id: str
    client_id: str
    method_name: str
    payload: str

    @staticmethod
    def create(method_name: str, payload: str, client_id: str) -> "AnyCallRequest":
        """Create a new request with a generated UUID."""
        return AnyCallRequest(
            request_id=str(uuid.uuid4()),
            client_id=client_id,
            method_name=method_name,
            payload=payload,
        )

    @staticmethod
    def from_dict(data: dict) -> "AnyCallRequest":
        """Deserialize from its wire dict. Raises TypeError on an unknown or
        missing field."""
        return AnyCallRequest(**_from_wire(data, _REQUEST_FIELDS))

    def to_dict(self) -> dict:
        """Serialize to dict using camelCase for Java compatibility."""
        return {
            "requestId": self.request_id,
            "clientId": self.client_id,
            "methodName": self.method_name,
            "payload": self.payload,
        }


@dataclass
class AnyCallResponse:
    """RPC response envelope.

    `lost_server` is set only on the error a reaping server writes for a
    request whose server stopped heartbeating; it holds that server's id.
    """
    request_id: str
    payload: Optional[str] = None
    error_msg: Optional[str] = None
    lost_server: Optional[str] = None

    @staticmethod
    def success(request_id: str, payload: str) -> "AnyCallResponse":
        """Create a successful response."""
        return AnyCallResponse(request_id=request_id, payload=payload, error_msg=None)

    @staticmethod
    def error(request_id: str, error_message: str) -> "AnyCallResponse":
        """Create an error response."""
        return AnyCallResponse(request_id=request_id, payload=None, error_msg=error_message)

    @staticmethod
    def server_lost(request_id: str, server_id: str) -> "AnyCallResponse":
        """Create the error response for a request whose server stopped heartbeating."""
        return AnyCallResponse(
            request_id=request_id,
            error_msg=f"server {server_id} stopped heartbeating while processing this request",
            lost_server=server_id,
        )

    def has_error(self) -> bool:
        """Check if this response contains an error."""
        return self.error_msg is not None

    @staticmethod
    def from_dict(data: dict) -> "AnyCallResponse":
        """Deserialize from its wire dict. Raises TypeError on an unknown
        field, or a missing `requestId`."""
        return AnyCallResponse(**_from_wire(data, _RESPONSE_FIELDS))

    def to_dict(self) -> dict:
        """Serialize to dict using camelCase for Java compatibility."""
        data = {
            "requestId": self.request_id,
            "payload": self.payload,
            "error": self.error_msg  # Java uses "error", not "error_msg"
        }
        # Only on reaped requests, so every other response stays readable by
        # clients that predate the field.
        if self.lost_server is not None:
            data["lostServer"] = self.lost_server
        return data
