"""The payload types (see LIBRARY.md): what a request or response may be, as
JSON itself has it.

    T = boolean | integer | number | string
      | array of T | map of string to T | record of fields, each a T
      | T or null

In Python: bool, int, float, str, list[T], dict[str, T], a dataclass, and
`T | None`. Three checks, one per moment:

- `check_type`: a declared type, when it's declared (registering a method or
  a type, or calling with one). Raises TypeError.
- `to_json`: a value, as it's written. Raises PayloadError.
- `from_json`: JSON text, read into a declared type. Raises PayloadError.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import math
import threading
import types
import typing
from enum import Enum
from typing import Any, Union

# The integers every language reads exactly: a JSON number is a 64-bit float
# in some of them, and past this one a float can't tell neighbors apart.
MAX_INTEGER = 2**53 - 1

class PayloadError(ValueError):
    """A value that isn't a payload, or JSON that doesn't fit the type it's
    read into."""


def _name(tp: Any) -> str:
    return getattr(tp, "__name__", None) or repr(tp)


def _optional_of(tp: Any) -> Any:
    """`T` if `tp` is `T | None` (or Optional[T]), else None."""
    if typing.get_origin(tp) in (Union, types.UnionType):
        args = typing.get_args(tp)
        others = [a for a in args if a is not type(None)]
        if len(others) == 1 and len(args) == 2:
            return others[0]
    return None


def _type_name(tp: Any) -> str:
    """`tp` as it's written in code: `dict[str, Any]`, `int | None`."""
    origin, args = typing.get_origin(tp), typing.get_args(tp)
    if origin in (Union, types.UnionType):
        return " | ".join("None" if a is type(None) else _type_name(a) for a in args)
    if origin is not None and args:
        return f"{_name(origin)}[{', '.join(_type_name(a) for a in args)}]"
    if tp is Any:
        return "Any"
    return _name(tp)


def _not_a_payload_type(path: str, tp: Any, declared: Any) -> TypeError:
    if tp is declared:
        return TypeError(f"{path} is {_type_name(tp)}, not an AnyCall payload type")
    return TypeError(f"{path} is {_type_name(declared)}, and {_type_name(tp)} isn't an AnyCall payload type")


_checked: set = set()
_checked_lock = threading.Lock()


def check_type(tp: Any, where: str) -> None:
    """Check that `tp` is a payload type. `where` names it in the error,
    such as "method embed's request".

    Raises:
        TypeError: naming the field whose type isn't one
    """
    try:
        with _checked_lock:
            if tp in _checked:
                return
    except TypeError:  # unhashable: not a type at all
        raise TypeError(f"{where} is {tp!r}, not an AnyCall payload type") from None
    _check(tp, where, tp, set(), where)
    with _checked_lock:
        _checked.add(tp)


def _check(tp: Any, path: str, declared: Any, seen: set, where: str) -> None:
    """Check `tp`, found at `path` inside `declared`: the type as written
    there, which differs from it inside a list, a map or an optional. A
    field's path starts with `where`, what was declared, so its error says
    which method or call it came from."""
    inner = _optional_of(tp)
    if inner is not None:
        return _check(inner, path, declared, seen, where)
    if tp in (bool, int, float, str):
        return
    origin, args = typing.get_origin(tp), typing.get_args(tp)
    if origin is list and len(args) == 1:
        return _check(args[0], path, declared, seen, where)
    if origin is dict and len(args) == 2 and args[0] is str:
        return _check(args[1], path, declared, seen, where)
    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        if tp in seen:  # a type that refers to itself
            return
        seen.add(tp)
        hints = _field_types(tp)
        for field in _fields(tp):
            field_type = hints[field.name]
            _check(field_type, f"{where}: {tp.__name__}.{field.name}", field_type, seen, where)
        return
    raise _not_a_payload_type(path, tp, declared)


@functools.lru_cache(maxsize=None)
def _fields(cls: type) -> tuple:
    return tuple(f for f in dataclasses.fields(cls) if f.init)


@functools.lru_cache(maxsize=None)
def _field_types(cls: type) -> dict:
    """A dataclass's field types, forward references resolved. Cached: every
    request read into it needs them."""
    try:
        return typing.get_type_hints(cls)
    except Exception as e:
        raise TypeError(f"{cls.__name__} has a field type that can't be resolved: {e}") from e


# Writing


def to_json(value: Any) -> str:
    """`value` as JSON text, checked as it's written.

    Raises:
        PayloadError: If it isn't made of payload types, has an integer out
            of range, a NaN or an infinity, or refers back to itself
    """
    return json.dumps(_write(value, "payload", set()), allow_nan=False)


def _write(value: Any, path: str, open_: set) -> Any:
    if value is None or isinstance(value, (bool, str)) and not isinstance(value, Enum):
        return value
    if isinstance(value, Enum):
        raise PayloadError(f"{path} is {type(value).__name__}, not an AnyCall payload type")
    if isinstance(value, int):
        if abs(value) > MAX_INTEGER:
            raise PayloadError(f"{path} is {value}, past ±(2^53 − 1)")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PayloadError(f"{path} is {value}; JSON has no NaN or infinity")
        return value
    is_record = dataclasses.is_dataclass(value) and not isinstance(value, type)
    if not isinstance(value, (list, dict)) and not is_record:
        raise PayloadError(f"{path} is {type(value).__name__}, not an AnyCall payload type")
    if id(value) in open_:
        raise PayloadError(f"{path} refers back to an object that contains it; a payload is a tree")
    open_.add(id(value))
    try:
        if isinstance(value, list):
            return [_write(item, f"{path}[{i}]", open_) for i, item in enumerate(value)]
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise PayloadError(f"{path} has the key {key!r}; map keys are str")
                out[key] = _write(item, f"{path}[{key!r}]", open_)
            return out
        name = type(value).__name__
        return {f.name: _write(getattr(value, f.name), f"{name}.{f.name}", open_) for f in _fields(type(value))}
    finally:
        open_.discard(id(value))


# Reading


def from_json(text: str, tp: Any) -> Any:
    """JSON text read into `tp`, a checked payload type. A whole payload of
    `null` is None whatever the type, as the protocol has a method that
    returns null send it.

    Raises:
        PayloadError: If it doesn't fit `tp`
        json.JSONDecodeError: If it isn't JSON
    """
    data = json.loads(text)
    if data is None:
        return None
    return _read(data, tp, "payload")


def _kind(data: Any) -> str:
    if data is None:
        return "null"
    if isinstance(data, bool):
        return "a boolean"
    if isinstance(data, (int, float)):
        return "a number"
    if isinstance(data, str):
        return "a string"
    if isinstance(data, list):
        return "an array"
    return "an object"


def _mismatch(path: str, tp: Any, data: Any) -> PayloadError:
    return PayloadError(f"{path} should be {_name(tp)}, got {_kind(data)}")


def _read(data: Any, tp: Any, path: str) -> Any:
    inner = _optional_of(tp)
    if inner is not None:
        return None if data is None else _read(data, inner, path)
    if tp is bool:
        if isinstance(data, bool):
            return data
        raise _mismatch(path, tp, data)
    if tp is int:
        if isinstance(data, int) and not isinstance(data, bool):
            if abs(data) > MAX_INTEGER:
                raise PayloadError(f"{path} is {data}, past ±(2^53 − 1)")
            return data
        raise _mismatch(path, tp, data)
    if tp is float:
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            return float(data)
        raise _mismatch(path, tp, data)
    if tp is str:
        if isinstance(data, str):
            return data
        raise _mismatch(path, tp, data)
    origin, args = typing.get_origin(tp), typing.get_args(tp)
    if origin is list:
        if not isinstance(data, list):
            raise _mismatch(path, tp, data)
        return [_read(item, args[0], f"{path}[{i}]") for i, item in enumerate(data)]
    if origin is dict:
        if not isinstance(data, dict):
            raise _mismatch(path, tp, data)
        return {key: _read(item, args[1], f"{path}[{key!r}]") for key, item in data.items()}
    # A dataclass, the only type left after check_type.
    if not isinstance(data, dict):
        raise _mismatch(path, tp, data)
    fields = _fields(tp)
    names = {f.name for f in fields}
    unknown = sorted(set(data) - names)
    if unknown:
        raise PayloadError(f"{tp.__name__} has no field {', '.join(unknown)}")
    missing = sorted(names - set(data))
    if missing:
        raise PayloadError(f"{tp.__name__} is missing {', '.join(missing)}")
    hints = _field_types(tp)
    return tp(**{f.name: _read(data[f.name], hints[f.name], f"{tp.__name__}.{f.name}") for f in fields})
