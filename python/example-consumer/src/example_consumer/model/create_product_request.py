from dataclasses import dataclass


@dataclass
class CreateProductRequest:
    """Request to create a product."""
    name: str
    price_in_cents: int
