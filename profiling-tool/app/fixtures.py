"""Mock data for development and testing."""

from app.models import Supplier, Consumer

MOCK_SUPPLIERS = [
    Supplier("s1", "Java", "java-workers"),
]

MOCK_CONSUMERS = [
    Consumer("c1", "ProductConsumer", "java", "createProduct", "s1"),
]
