"""Unit tests for AnyCallClient: calls, registered types, queue depth, and how
responses on the client's one queue reach the calls waiting for them."""

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional, Tuple

import pytest
import redis.exceptions

from .client import AnyCallClientImpl
from .exceptions import (
    AnyCallError,
    BrokerError,
    QueueFullError,
    SerializationError,
    ServerLostError,
    TimeoutError,
)


@dataclass
class MockResponse:
    """Test model for deserialization."""
    value: str


@dataclass
class AlternativeResponse:
    """Alternative test model."""
    count: int


class MockRedisAdapter:
    """Mock Redis adapter: nothing ever answers, so calls time out."""

    def __init__(self, queue_depth: int = 0):
        self.queue_depth = queue_depth
        self.responses: dict[str, list[str]] = {}
        self._responses_lock = threading.Lock()

    def push(self, queue_key: str, value: str) -> int:
        return 1

    def pop(self, queue_keys: List[str], timeout_seconds: float) -> Optional[Tuple[str, str]]:
        with self._responses_lock:
            waiting = self.responses.get(queue_keys[0])
            if waiting:
                return queue_keys[0], waiting.pop()
        time.sleep(0.005)  # a real BRPOP blocks; don't spin
        return None

    def respond(self, response_queue: str, value: str, ttl_seconds: int, processing_key: str = "", item: str = "") -> None:
        with self._responses_lock:
            self.responses.setdefault(response_queue, []).insert(0, value)

    def delete(self, key: str) -> int:
        return 0

    def length(self, queue_key: str) -> int:
        return self.queue_depth

    def alive_count(self, key: str, ttl_seconds: int) -> int:
        return 1

    def stale_members(self, key: str, ttl_seconds: int) -> set[str]:
        return set()

    def fail_back_next(self, alive_key, processing_key, server_id, response_ttl_seconds, tombstone_ttl_seconds, response_for) -> Optional[str]:
        return None

    def close(self) -> None:
        pass


class RespondingAdapter(MockRedisAdapter):
    """Answers every call on its client's queue with `response`, where
    REQUEST_ID stands for the call's requestId."""

    def __init__(self, response: str, delay: float = 0.0):
        super().__init__()
        self.response = response
        self.delay = delay

    def push(self, queue_key: str, value: str) -> int:
        request = json.loads(value)
        answer = self.response.replace("REQUEST_ID", request["requestId"])
        response_queue = f"anycall:responses:{request['clientId']}"
        if self.delay:
            threading.Timer(self.delay, self.respond, (response_queue, answer, 60)).start()
        else:
            self.respond(response_queue, answer, 60)
        return 1


class EchoAdapter(MockRedisAdapter):
    """Answers each call with its own request payload, held back so that
    responses come in the reverse order of the calls."""

    def __init__(self):
        super().__init__()
        self.held: list[tuple[str, str]] = []

    def push(self, queue_key: str, value: str) -> int:
        request = json.loads(value)
        answer = json.dumps({"requestId": request["requestId"], "payload": request["payload"], "error": None})
        self.held.append((f"anycall:responses:{request['clientId']}", answer))
        return 1

    def release_reversed(self) -> None:
        for response_queue, answer in reversed(self.held):
            self.respond(response_queue, answer, 60)


class DeadServerAdapter(MockRedisAdapter):
    """Every request pushed is taken by a server that then stops
    heartbeating, and nothing else is around to reap it."""

    def __init__(self, dead: bool = True):
        super().__init__()
        self.dead = dead
        self.processing: dict[str, list[str]] = {"dead-server": []}
        self.reap_steps = 0

    def push(self, queue_key: str, value: str) -> int:
        self.processing["dead-server"].append(value)
        return 1

    def stale_members(self, key: str, ttl_seconds: int) -> set[str]:
        return {server for server in self.processing if self.dead}

    def fail_back_next(self, alive_key, processing_key, server_id, response_ttl_seconds, tombstone_ttl_seconds, response_for):
        self.reap_steps += 1
        assert processing_key == f"anycall:processing:{server_id}"
        items = self.processing.get(server_id)
        if items is None:
            return None
        if not items:
            del self.processing[server_id]
            return None
        target = response_for(items.pop())
        if target is not None:
            self.respond(target[0], target[1], response_ttl_seconds)
        return "dropped" if target is None else "answered"


class FailingRedisAdapter(MockRedisAdapter):
    """Raises a redis-py ConnectionError from the command named `fails`."""

    def __init__(self, fails: str):
        super().__init__()
        self.fails = fails

    def _maybe_fail(self, command: str) -> None:
        if command == self.fails:
            raise redis.exceptions.ConnectionError("Connection refused")

    def alive_count(self, key: str, ttl_seconds: int) -> int:
        self._maybe_fail("alive_count")
        return 1

    def length(self, queue_key: str) -> int:
        self._maybe_fail("length")
        return 0

    def push(self, queue_key: str, value: str) -> int:
        self._maybe_fail("push")
        return 1

    def pop(self, queue_keys: List[str], timeout_seconds: float) -> Optional[Tuple[str, str]]:
        self._maybe_fail("pop")
        return super().pop(queue_keys, timeout_seconds)


QUICK_TIMEOUT = timedelta(milliseconds=200)

_clients: list[AnyCallClientImpl] = []


def make_client(adapter, timeout: timedelta = QUICK_TIMEOUT, **kwargs) -> AnyCallClientImpl:
    client = AnyCallClientImpl(adapter, timeout, **kwargs)
    _clients.append(client)
    return client


@pytest.fixture(autouse=True)
def close_clients():
    """Stop every test client's reader thread once the test is done."""
    yield
    while _clients:
        _clients.pop().close()


@pytest.fixture
def client():
    """A test client with a mock adapter that never answers."""
    return make_client(MockRedisAdapter())


class TestRegisterType:
    """Tests for register_type() registry semantics."""

    def test_register_type_first_time(self, client):
        client.register_type("my-op", MockResponse)
        assert client._registry.has("my-op")
        assert client._registry.get("my-op") is MockResponse

    def test_register_type_same_type_idempotent(self, client):
        client.register_type("my-op", MockResponse)
        client.register_type("my-op", MockResponse)
        assert client._registry.get("my-op") is MockResponse

    def test_register_type_different_type_error(self, client):
        client.register_type("my-op", MockResponse)

        with pytest.raises(AnyCallError) as exc_info:
            client.register_type("my-op", AlternativeResponse)

        error_msg = str(exc_info.value)
        assert "my-op" in error_msg
        assert "already registered" in error_msg
        assert "MockResponse" in error_msg
        assert "AlternativeResponse" in error_msg

    def test_register_multiple_operations(self, client):
        client.register_type("op1", MockResponse)
        client.register_type("op2", AlternativeResponse)

        assert client._registry.get("op1") is MockResponse
        assert client._registry.get("op2") is AlternativeResponse


class TestCallWithRegistry:
    """Tests for call() with registry lookup."""

    def test_call_without_type_not_registered_error(self, client):
        with pytest.raises(AnyCallError) as exc_info:
            client.call("unknown-op", {})

        error_msg = str(exc_info.value)
        assert "unknown-op" in error_msg
        assert "register_type" in error_msg

    def test_call_without_type_registered_uses_registry(self):
        client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": "{\\"value\\": \\"ok\\"}", "error": null}'))
        client.register_type("my-op", MockResponse)

        assert client.call("my-op", {}) == MockResponse(value="ok")

    def test_call_with_explicit_type_ignores_registry(self):
        client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": "{\\"count\\": 3}", "error": null}'))
        client.register_type("my-op", MockResponse)

        assert client.call("my-op", {}, AlternativeResponse) == AlternativeResponse(count=3)


class TestRawCall:
    """Tests for raw_call() semantics."""

    def test_raw_call_ignores_registry(self):
        client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": "{\\"any\\": 1}", "error": null}'))
        client.register_type("my-op", MockResponse)

        assert client.raw_call("my-op", {}) == {"any": 1}


class TestErrorMessages:
    """Tests for error message quality."""

    def test_missing_type_error_suggests_both_paths(self, client):
        with pytest.raises(AnyCallError) as exc_info:
            client.call("my-operation", {})

        error_msg = str(exc_info.value)
        assert "my-operation" in error_msg
        assert "explicit type" in error_msg.lower()
        assert "register_type" in error_msg

    def test_duplicate_type_error_names_types(self, client):
        client.register_type("operation", MockResponse)

        with pytest.raises(AnyCallError) as exc_info:
            client.register_type("operation", AlternativeResponse)

        error_msg = str(exc_info.value)
        assert "MockResponse" in error_msg
        assert "AlternativeResponse" in error_msg
        assert "operation" in error_msg


class TestQueueDepth:
    """Tests for max_queue_depth / QueueFullError semantics."""

    def test_call_raises_when_queue_at_max_depth(self):
        client = make_client(MockRedisAdapter(queue_depth=5))

        with pytest.raises(QueueFullError) as exc_info:
            client.call("my-op", {}, MockResponse, max_queue_depth=5)

        assert exc_info.value.method_name == "my-op"
        assert exc_info.value.queue_depth == 5
        assert exc_info.value.max_queue_depth == 5

    def test_call_proceeds_when_queue_below_max_depth(self, client):
        with pytest.raises(TimeoutError):
            client.call("my-op", {}, MockResponse, max_queue_depth=5)

    def test_default_max_queue_depth_applies_without_override(self):
        client = make_client(MockRedisAdapter(queue_depth=3), default_max_queue_depth=3)

        with pytest.raises(QueueFullError):
            client.call("my-op", {}, MockResponse)

    def test_per_call_override_wins_over_default(self):
        client = make_client(MockRedisAdapter(queue_depth=3), default_max_queue_depth=1)

        with pytest.raises(TimeoutError):
            client.call("my-op", {}, MockResponse, max_queue_depth=10)

    def test_raw_call_respects_max_queue_depth(self):
        client = make_client(MockRedisAdapter(queue_depth=2))

        with pytest.raises(QueueFullError):
            client.raw_call("my-op", {}, max_queue_depth=2)

    def test_get_queue_depth_reads_through_adapter(self):
        assert make_client(MockRedisAdapter(queue_depth=7)).get_queue_depth("my-op") == 7

    def test_default_max_queue_depth_getter_and_setter(self, client):
        assert client.get_default_max_queue_depth() is None

        client.set_default_max_queue_depth(42)
        assert client.get_default_max_queue_depth() == 42

        client.set_default_max_queue_depth(None)
        assert client.get_default_max_queue_depth() is None


class TestOneResponseQueue:
    """Every response goes to the client's one queue, and reaches its call by requestId."""

    def test_requests_name_the_clients_queue(self):
        adapter = MockRedisAdapter()
        pushed: list[dict] = []
        adapter.push = lambda queue_key, value: pushed.append(json.loads(value)) or 1
        client = make_client(adapter)

        with pytest.raises(TimeoutError):
            client.raw_call("my-op", {})

        assert pushed[0]["clientId"] == client.client_id

    def test_concurrent_calls_get_their_own_responses_in_any_order(self):
        adapter = EchoAdapter()
        client = make_client(adapter, timeout=timedelta(seconds=5))
        results: dict[int, dict] = {}

        def call(i: int) -> None:
            results[i] = client.raw_call("echo", {"i": i})

        threads = [threading.Thread(target=call, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        deadline = time.monotonic() + 2
        while len(adapter.held) < 5 and time.monotonic() < deadline:
            time.sleep(0.01)
        adapter.release_reversed()
        for t in threads:
            t.join()

        assert results == {i: {"i": i} for i in range(5)}

    def test_late_response_is_dropped(self):
        client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": "1", "error": null}', delay=0.5))

        with pytest.raises(TimeoutError):
            client.raw_call("my-op", {})
        time.sleep(0.6)  # the late answer arrives, with no call waiting for it

        assert client._pending == {}

    def test_response_with_no_readable_request_id_is_dropped(self):
        client = make_client(RespondingAdapter("not json"))

        with pytest.raises(TimeoutError):
            client.raw_call("my-op", {})


class TestWaiterDrivenReaping:
    """While calls wait, a read slice that ends empty reaps dead servers."""

    def test_call_reaps_its_dead_server_and_raises_server_lost(self):
        adapter = DeadServerAdapter()
        client = make_client(adapter, timeout=timedelta(seconds=5))

        with pytest.raises(ServerLostError) as exc_info:
            client.raw_call("my-op", {})

        assert exc_info.value.server_id == "dead-server"
        assert "dead-server" not in adapter.processing

    def test_no_reaping_while_every_server_is_alive(self):
        adapter = DeadServerAdapter(dead=False)
        client = make_client(adapter)

        with pytest.raises(TimeoutError):
            client.raw_call("my-op", {})

        assert adapter.reap_steps == 0
        assert len(adapter.processing["dead-server"]) == 1


class TestResponseFields:
    """Responses are read by their camelCase wire names only."""

    def test_camel_case_response_is_read(self):
        client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": "{\\"value\\": \\"ok\\"}", "error": null}'))

        assert client.call("my-op", {}, MockResponse) == MockResponse(value="ok")

    def test_response_with_other_field_name_is_a_serialization_error(self):
        client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": null, "errorMsg": "boom"}'))

        with pytest.raises(SerializationError):
            client.raw_call("my-op", {})


class TestNullPayload:
    """A null result travels as the payload "null"; a null payload is a broken response."""

    def test_null_result_is_none_for_typed_call(self):
        client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": "null", "error": null}'))

        assert client.call("my-op", {}, MockResponse) is None

    def test_null_result_is_none_for_raw_call(self):
        client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": "null", "error": null}'))

        assert client.raw_call("my-op", {}) is None

    def test_response_with_neither_payload_nor_error_is_a_serialization_error(self):
        client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": null, "error": null}'))

        with pytest.raises(SerializationError, match="neither a payload nor an error"):
            client.call("my-op", {}, MockResponse)

    def test_payload_that_does_not_fit_the_type_is_a_serialization_error(self):
        client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": "{\\"other\\": 1}", "error": null}'))

        with pytest.raises(SerializationError):
            client.call("my-op", {}, MockResponse)


class TestInvalidJson:
    """An invalid payload in a readable response is a plain SerializationError."""

    def test_invalid_payload_json_is_a_serialization_error(self):
        client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": "not json", "error": null}'))

        with pytest.raises(SerializationError) as exc_info:
            client.raw_call("my-op", {})

        assert type(exc_info.value) is SerializationError


class TestBrokerError:
    """A Redis failure during a call is a BrokerError saying whether the request may have left."""

    @pytest.mark.parametrize("fails", ["alive_count", "length"])
    def test_failure_before_publishing_is_not_published(self, fails):
        client = make_client(FailingRedisAdapter(fails), default_max_queue_depth=10)

        with pytest.raises(BrokerError) as exc_info:
            client.raw_call("my-op", {})

        assert exc_info.value.published is False
        assert isinstance(exc_info.value.__cause__, redis.exceptions.ConnectionError)

    def test_failure_publishing_may_be_published(self):
        client = make_client(FailingRedisAdapter("push"))

        with pytest.raises(BrokerError) as exc_info:
            client.raw_call("my-op", {})

        assert exc_info.value.published is True
        assert exc_info.value.get_id()
        assert client._pending == {}

    def test_failure_reading_responses_fails_every_waiting_call(self):
        client = make_client(FailingRedisAdapter("pop"), timeout=timedelta(seconds=5))

        with pytest.raises(BrokerError) as exc_info:
            client.raw_call("my-op", {})

        assert exc_info.value.published is True
        assert isinstance(exc_info.value.__cause__, redis.exceptions.ConnectionError)


class TestAsyncCalls:
    """client.aio: the same calls, to await."""

    def test_awaited_call_returns_its_result(self):
        client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": "{\\"value\\": \\"ok\\"}", "error": null}'))

        assert asyncio.run(client.aio.call("my-op", {}, MockResponse)) == MockResponse(value="ok")

    def test_awaited_calls_run_together(self):
        adapter = EchoAdapter()
        client = make_client(adapter, timeout=timedelta(seconds=5))

        async def main():
            calls = asyncio.gather(*(client.aio.raw_call("echo", {"i": i}) for i in range(5)))
            while len(adapter.held) < 5:
                await asyncio.sleep(0.01)
            adapter.release_reversed()
            return await calls

        assert asyncio.run(main()) == [{"i": i} for i in range(5)]

    def test_awaited_call_uses_the_registered_type(self):
        client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": "{\\"value\\": \\"ok\\"}", "error": null}'))
        client.register_type("my-op", MockResponse)

        assert asyncio.run(client.aio.call("my-op", {})) == MockResponse(value="ok")

    def test_awaited_call_times_out_with_anycalls_error(self, client):
        with pytest.raises(TimeoutError):
            asyncio.run(client.aio.raw_call("my-op", {}))

        assert client._pending == {}

    def test_awaited_call_raises_remote_errors(self):
        client = make_client(RespondingAdapter('{"requestId": "REQUEST_ID", "payload": null, "error": "boom", "lostServer": "s1"}'))

        with pytest.raises(ServerLostError):
            asyncio.run(client.aio.raw_call("my-op", {}))
