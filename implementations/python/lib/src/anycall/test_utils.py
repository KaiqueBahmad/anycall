"""Unit tests for anycall.utils: a supplier's methods, without a server."""

import pytest

from . import utils
from .annotation import supply
from .context import AnycallContext
from .server import SupplyMethod


class Methods:
    @supply("slow", max_concurrency=4)
    def slow(self, ctx: AnycallContext, request: dict) -> dict:
        return request

    @supply("echo")
    def echo(self, ctx: AnycallContext, request: dict) -> dict:
        return request

    def not_supplied(self) -> None:
        pass


class Broken:
    @supply("broken")
    def broken(self, request: dict) -> dict:
        return request


def test_methods_lists_the_supply_methods_sorted():
    assert utils.methods(Methods()) == ["echo", "slow"]


def test_methods_of_an_object_with_none_is_empty():
    assert utils.methods(object()) == []


def test_method_reads_what_the_object_declares():
    assert utils.method(Methods(), "slow") == SupplyMethod("slow", 4, dict, dict)
    assert utils.method(Methods(), "echo").max_concurrency == 1


def test_method_without_a_return_annotation_has_no_response_type():
    class Bare:
        @supply("bare")
        def bare(self, ctx: AnycallContext, request: dict):
            return request

    assert utils.method(Bare(), "bare").response_type is None


def test_method_not_declared_fails():
    with pytest.raises(KeyError):
        utils.method(Methods(), "missing")
    with pytest.raises(KeyError):
        utils.method(Methods(), "not_supplied")


def test_an_invalid_supply_method_is_rejected_as_a_server_would():
    with pytest.raises(ValueError):
        utils.methods(Broken())
