import json
from dataclasses import asdict, is_dataclass
from typing import Any, Type, TypeVar

import dacite

T = TypeVar("T")


def serialize(obj: Any) -> str:
    """Serialize an object to JSON string.

    Args:
        obj: Object to serialize (dataclass, dict, or JSON-serializable)

    Returns:
        JSON string representation
    """
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
        return dacite.from_dict(target_type, data)

    return data
