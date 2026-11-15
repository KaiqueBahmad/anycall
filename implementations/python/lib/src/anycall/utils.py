"""Look at a supplier object without a server: which methods it would serve
and how. Checks the object the way `AnyCallServer.register` does, so what
this accepts a server registers, and what it rejects a server rejects too."""

from typing import Any

from .server import SupplyMethod, scan_supplier


def methods(supplier: Any) -> list[str]:
    """The names of the @supply methods `supplier` has, sorted.

    Raises:
        ValueError: If one of them isn't a valid supply method
    """
    return sorted({handler.method_name for handler in scan_supplier(supplier)})


def method(supplier: Any, method_name: str) -> SupplyMethod:
    """One @supply method of `supplier`, as declared.

    Raises:
        KeyError: If `supplier` has no @supply method under that name
        ValueError: If one of its methods isn't a valid supply method
    """
    found = [handler for handler in scan_supplier(supplier) if handler.method_name == method_name]
    if not found:
        raise KeyError(f"{type(supplier).__name__} has no @supply method {method_name!r}")
    return found[-1].declared
