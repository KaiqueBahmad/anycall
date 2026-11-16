import json
from typing import Type, TypeVar, Union

from .model import AnyCallRequest, AnyCallResponse

T = TypeVar("T", AnyCallRequest, AnyCallResponse)


def serialize(message: Union[AnyCallRequest, AnyCallResponse]) -> str:
    """A request or response message as JSON, with its camelCase wire names.
    Payloads are written by `payload.to_json`."""
    return json.dumps(message.to_dict())


def deserialize(json_str: str, message_type: Type[T]) -> T:
    """A request or response message read from JSON, strictly. Payloads are
    read by `payload.from_json`."""
    return message_type.from_dict(json.loads(json_str))
