from anycall import supply

from .model.create_product_request import CreateProductRequest
from .model.product import Product


class ProductSupplier:
    """Supplier for product creation operations."""

    @supply("create-new-product")
    def create_new_product(self, req: CreateProductRequest) -> Product:
        """Create a new product.

        Args:
            req: Product creation request

        Returns:
            Created product
        """
        return Product(name=req.name, price_in_cents=req.price_in_cents)
