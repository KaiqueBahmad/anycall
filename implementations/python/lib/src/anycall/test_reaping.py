"""Unit tests for failing back a dead server's requests."""

import json

from .reaping import reap_dead_servers


class DeadServerLists:
    """One dead server's processing list, failed back one request at a time
    the way `RedisQueueAdapter.fail_back_next` does, from the tail."""

    def __init__(self, items: list[str]):
        self.items = list(items)
        self.alive = {"dead"}
        self.responses: dict[str, dict] = {}

    def fail_back_next(self, alive_key, processing_key, server_id, response_ttl_seconds, tombstone_ttl_seconds, response_for):
        if server_id not in self.alive:
            return None
        if not self.items:
            self.alive.discard(server_id)
            return None
        target = response_for(self.items.pop())
        if target is not None:
            self.responses[target[0]] = json.loads(target[1])
        return "dropped" if target is None else "answered"


def test_every_request_of_a_dead_server_gets_server_lost():
    items = [json.dumps({"requestId": f"r{i}", "clientId": f"c{i}", "methodName": "m", "payload": "{}"}) for i in range(3)]
    lists = DeadServerLists(items)

    reap_dead_servers(lists, ["dead"])

    # Each goes to its own client's queue, carrying its requestId.
    assert {queue: response["requestId"] for queue, response in lists.responses.items()} == {
        "anycall:responses:c0": "r0", "anycall:responses:c1": "r1", "anycall:responses:c2": "r2",
    }
    assert all(response["lostServer"] == "dead" for response in lists.responses.values())
    assert lists.items == [] and "dead" not in lists.alive


def test_request_with_unknown_field_still_gets_server_lost():
    item = json.dumps({"requestId": "r1", "clientId": "c1", "methodName": "echo", "payload": "{}", "extra": 1})
    lists = DeadServerLists([item])

    reap_dead_servers(lists, ["dead"])

    assert lists.responses["anycall:responses:c1"]["lostServer"] == "dead"


def test_request_with_no_readable_request_id_is_dropped():
    lists = DeadServerLists([
        "not json",
        json.dumps({"methodName": "echo"}),
        json.dumps({"requestId": "r1", "methodName": "echo", "payload": "{}"}),  # no clientId
    ])

    reap_dead_servers(lists, ["dead"])

    assert lists.responses == {}
    assert lists.items == []
