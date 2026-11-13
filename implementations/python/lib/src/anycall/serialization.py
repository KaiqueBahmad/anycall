import json
from dataclasses import asdict, is_dataclass
from typing import Any, Type, TypeVar

import dacite
from .model import AnyCallRequest, AnyCallResponse

T = TypeVar("T")


def serialize(obj: Any) -> str:
    """Serialize an object to JSON string.

    Args:
        obj: Object to serialize (dataclass, dict, or JSON-serializable)

    Returns:
        JSON string representation
    """
    # Special handling for request/response to use camelCase for Java compatibility
    if isinstance(obj, (AnyCallRequest, AnyCallResponse)):
        return json.dumps(obj.to_dict())

    if is_dataclass(obj):
        return json.dumps(asdict(obj))
    return json.dumps(obj)


def deserialize(json_str: str, target_type: Type[T]) -> T:
    """Deserialize a JSON string to the target type.

    Args:
        json_str: JSON string to deserialize
        target_type: Target type class

    Returns:
        Deserialized object of target_type
    """
    data = json.loads(json_str)

    if is_dataclass(target_type):
        # The envelopes have camelCase wire names of their own.
        if target_type is AnyCallRequest:
            return AnyCallRequest.from_dict(data)
        if target_type is AnyCallResponse:
            return AnyCallResponse.from_dict(data)
        # JSON null is a null value of any type, as Jackson reads it.
        if data is None:
            return None
        return dacite.from_dict(target_type, data)

    return data
