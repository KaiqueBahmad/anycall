from dataclasses import dataclass


@dataclass
class Product:
    """Product model."""
    name: str
    price_in_cents: int
