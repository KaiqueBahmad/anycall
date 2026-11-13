"""Unit tests for reading the request and response envelopes."""

import pytest

from .model import AnyCallRequest, AnyCallResponse


def test_request_reads_camel_case_fields():
    request = AnyCallRequest.from_dict({"requestId": "r1", "clientId": "c1", "methodName": "m", "payload": "{}"})

    assert (request.request_id, request.client_id, request.method_name, request.payload) == ("r1", "c1", "m", "{}")


@pytest.mark.parametrize("data", [
    {"request_id": "r1", "clientId": "c1", "methodName": "m", "payload": "{}"},
    {"requestId": "r1", "client_id": "c1", "methodName": "m", "payload": "{}"},
    {"requestId": "r1", "clientId": "c1", "method_name": "m", "payload": "{}"},
    {"requestId": "r1", "clientId": "c1", "methodName": "m", "payload": "{}", "request_id": "r2"},
    {"requestId": "r1", "clientId": "c1", "methodName": "m"},
    {"requestId": "r1", "methodName": "m", "payload": "{}"},
])
def test_request_rejects_other_field_names_and_missing_fields(data):
    with pytest.raises(TypeError):
        AnyCallRequest.from_dict(data)


def test_response_reads_camel_case_fields():
    response = AnyCallResponse.from_dict(
        {"requestId": "r1", "payload": None, "error": "boom", "lostServer": "s1"}
    )

    assert (response.request_id, response.error_msg, response.lost_server) == ("r1", "boom", "s1")


@pytest.mark.parametrize("field", ["errorMsg", "error_msg", "request_id", "lost_server"])
def test_response_rejects_other_field_names(field):
    with pytest.raises(TypeError):
        AnyCallResponse.from_dict({"requestId": "r1", "payload": None, "error": None, field: "x"})
