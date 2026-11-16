"""Unit tests for the payload types: which types can be declared, which values
can be written, and how JSON is read into a declared type. Then where a
client and a server check them."""

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Union, cast
from uuid import UUID

import pytest

from .annotation import supply
from .context import AnyCallContext
from .exceptions import SerializationError
from .payload import MAX_INTEGER, PayloadError, check_type, from_json, to_json
from .redis_adapter import RedisQueueAdapter
from .server import AnyCallServerImpl, SupplyMethod
from .test_client import MockRedisAdapter, RespondingAdapter, make_client, close_clients  # noqa: F401
from .test_server import FakeRedisAdapter


class Color(Enum):
    RED = "red"


@dataclass
class Point:
    x: float
    y: float


@dataclass
class Category:
    name: str
    children: list["Category"]


@dataclass
class Product:
    name: str
    stock: dict[str, int]
    tags: list[str]
    note: Optional[str]


@dataclass
class Event:
    name: str
    at: datetime


@dataclass
class WithDefault:
    name: str
    size: int = 1


# Declaring


@pytest.mark.parametrize("tp", [
    bool, int, float, str,
    list[int], dict[str, float], list[list[str]], dict[str, list[Point]],
    Point, Category, Product, Optional[Point], Point | None, list[Optional[int]],
])
def test_payload_types_are_accepted(tp):
    check_type(tp, "it")


@pytest.mark.parametrize("tp", [
    bytes,
    Color,
    datetime,
    UUID,
    Decimal,
    set[int],
    tuple[int, int],
    dict,
    list,
    dict[int, str],
    Union[int, str],
    Any,
    object,
])
def test_other_types_are_rejected(tp):
    with pytest.raises(TypeError, match="not an AnyCall payload type"):
        check_type(tp, "it")


def test_a_rejected_field_is_named():
    with pytest.raises(TypeError, match="method log's request: Event.at is datetime, not an AnyCall payload type"):
        check_type(list[Event], "method log's request")


# Writing


def test_values_are_written_as_json():
    product = Product("fone", {"sp": 12}, ["audio"], None)
    assert json.loads(to_json(product)) == {"name": "fone", "stock": {"sp": 12}, "tags": ["audio"], "note": None}


def test_a_list_of_dataclasses_is_written():
    assert json.loads(to_json([Point(1, 2), Point(3, 4)])) == [{"x": 1, "y": 2}, {"x": 3, "y": 4}]


@pytest.mark.parametrize("value", [MAX_INTEGER, -MAX_INTEGER])
def test_integers_up_to_the_limit_are_written(value):
    assert to_json(value) == str(value)


@pytest.mark.parametrize("value, error", [
    (MAX_INTEGER + 1, "2\\^53"),
    ({"id": -(MAX_INTEGER + 1)}, "2\\^53"),
    (float("nan"), "NaN"),
    ([float("inf")], "NaN or infinity"),
    (Color.RED, "Color, not an AnyCall payload type"),
    (b"abc", "bytes"),
    ((1, 2), "tuple"),
    ({1: "a"}, "keys are str"),
    (Event("x", datetime(2026, 1, 1)), "datetime"),
])
def test_values_outside_the_rules_are_not_written(value, error):
    with pytest.raises(PayloadError, match=error):
        to_json(value)


def test_cyclic_data_is_not_written():
    root: dict[str, Any] = {"name": "root"}
    root["self"] = root
    with pytest.raises(PayloadError, match="tree"):
        to_json(root)


def test_the_same_object_twice_is_written_twice():
    point = Point(1, 2)
    assert json.loads(to_json([point, point])) == [{"x": 1, "y": 2}, {"x": 1, "y": 2}]


# Reading


def test_json_is_read_into_the_declared_type():
    text = '{"name": "fone", "stock": {"sp": 12, "ba": 1}, "tags": [], "note": "x"}'
    assert from_json(text, Product) == Product("fone", {"sp": 12, "ba": 1}, [], "x")


def test_a_type_that_refers_to_itself_is_read():
    text = '{"name": "a", "children": [{"name": "b", "children": []}]}'
    assert from_json(text, Category) == Category("a", [Category("b", [])])


def test_a_list_of_dataclasses_is_read():
    assert from_json('[{"x": 1, "y": 2}]', list[Point]) == [Point(1.0, 2.0)]


def test_an_integer_is_read_as_a_float():
    point = from_json('{"x": 1, "y": 2.5}', Point)
    assert point == Point(1.0, 2.5) and isinstance(point.x, float)


def test_a_whole_null_payload_is_none_for_any_type():
    assert from_json("null", Point) is None


@pytest.mark.parametrize("text, tp, error", [
    ('{"x": 1, "y": 2, "z": 3}', Point, "no field z"),
    ('{"x": 1}', Point, "missing y"),
    ('{"name": "a"}', WithDefault, "missing size"),
    ('{"x": null, "y": 2}', Point, "Point.x should be float, got null"),
    ('1.5', int, "got a number"),
    ('true', int, "got a boolean"),
    ('1', bool, "got a number"),
    ('"1"', int, "got a string"),
    (str(MAX_INTEGER + 1), int, "2\\^53"),
    ('[1, "a"]', list[int], "payload\\[1\\]"),
    ('{"sp": "a"}', dict[str, int], "payload\\['sp'\\]"),
    ('[]', Point, "got an array"),
])
def test_json_that_doesnt_fit_is_rejected(text, tp, error):
    with pytest.raises(PayloadError, match=error):
        from_json(text, tp)


# Where a client checks


def test_register_type_rejects_a_type_that_isnt_a_payload_type():
    client = make_client(MockRedisAdapter())
    with pytest.raises(TypeError, match="the response type of log: Event.at is datetime"):
        client.register_type("log", Event)


def test_a_call_with_a_type_that_isnt_a_payload_type_publishes_nothing():
    adapter = MockRedisAdapter()
    pushed = []
    adapter.push = lambda queue_key, value: pushed.append(value) or 1
    with pytest.raises(TypeError, match="bytes"):
        make_client(adapter).call("embed", {"text": "hi"}, bytes)
    assert pushed == []


def test_a_request_out_of_the_rules_publishes_nothing():
    adapter = MockRedisAdapter()
    pushed = []
    adapter.push = lambda queue_key, value: pushed.append(value) or 1
    with pytest.raises(SerializationError, match="2\\^53"):
        make_client(adapter).raw_call("lookup", {"id": 2**60})
    assert pushed == []


def test_a_result_that_doesnt_fit_is_a_serialization_error():
    client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": "{\\"x\\": 1}", "error": null}'))
    with pytest.raises(SerializationError, match="missing y"):
        client.call("where", {}, Point)


def test_a_raw_call_reads_any_json():
    client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": "[1, \\"a\\"]", "error": null}'))
    assert client.raw_call("anything", {}) == [1, "a"]


# Where a server checks


class Logger:
    @supply("log")
    def log(self, ctx: AnyCallContext, event: Event) -> None:
        pass


def test_register_rejects_a_method_whose_types_arent_payload_types():
    server = AnyCallServerImpl(cast(RedisQueueAdapter, FakeRedisAdapter()))
    with pytest.raises(TypeError, match="method log's request: Event.at is datetime"):
        server.register(Logger())
    with pytest.raises(TypeError, match="method embed's response is bytes"):
        server.register_method(SupplyMethod("embed", 1, str, bytes), lambda ctx, text: b"")
    assert server.methods == []


def answer(handler_result: Any, payload: str = '"hi"') -> dict:
    adapter = FakeRedisAdapter()
    server = AnyCallServerImpl(cast(RedisQueueAdapter, adapter))
    server.register_method(SupplyMethod("m", 1, str, None), lambda ctx, text: handler_result)
    item = json.dumps({"requestId": "r1", "clientId": "c1", "methodName": "m", "payload": payload})
    server._process_request(server.method_handlers["m"], item, server._identity)
    return adapter.responses["anycall:responses:c1"]


def test_a_result_out_of_the_rules_is_answered_with_an_error():
    response = answer(float("nan"))
    assert response["payload"] is None
    assert "NaN" in response["error"]


def test_a_list_of_dataclasses_is_answered():
    assert json.loads(answer([Point(1, 2)])["payload"]) == [{"x": 1, "y": 2}]


def test_a_request_that_doesnt_fit_is_answered_with_an_error():
    response = answer("ok", payload="1")
    assert response["payload"] is None
    assert "should be str" in response["error"]
