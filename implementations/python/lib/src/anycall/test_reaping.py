"""Unit tests for failing back a dead server's requests."""

import json

from .reaping import reap_dead_servers


class ClaimingAdapter:
    """Hands over `items` as the dead server's processing list."""

    def __init__(self, items: list[str]):
        self.items = items
        self.responses: dict[str, dict] = {}

    def claim_dead(self, alive_key: str, processing_key: str, server_id: str, ttl_seconds: int) -> list[str]:
        items, self.items = self.items, []
        return items

    def respond(self, response_queue: str, value: str, ttl_seconds: int, processing_key: str = "", item: str = ""):
        self.responses[response_queue] = json.loads(value)


def test_request_with_unknown_field_still_gets_server_lost():
    item = json.dumps({"requestId": "r1", "methodName": "echo", "payload": "{}", "extra": 1})
    adapter = ClaimingAdapter([item])

    reap_dead_servers(adapter, ["dead"])

    assert adapter.responses["anycall:responses:r1"]["lostServer"] == "dead"


def test_request_with_no_readable_request_id_is_dropped():
    adapter = ClaimingAdapter(["not json", json.dumps({"methodName": "echo"})])

    reap_dead_servers(adapter, ["dead"])

    assert adapter.responses == {}
