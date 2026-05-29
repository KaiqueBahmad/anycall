from dataclasses import dataclass, field


@dataclass
class Supplier:
    id: str
    name: str
    group: str
    active: bool = False


@dataclass
class Consumer:
    id: str
    name: str
    language: str  # "java" | "python" | "go"
    method: str
    supplier_id: str


@dataclass
class ExecutionResult:
    consumer: Consumer
    supplier: Supplier
    duration_ms: int
    lines: list[str]
    success: bool = True


MOCK_SUPPLIERS = [
    Supplier("s1", "Java", "java-workers"),
    Supplier("s2", "Python", "python-workers"),
    Supplier("s3", "Go", "go-workers"),
]

MOCK_CONSUMERS = [
    Consumer("c1", "ProductConsumer", "java",   "createProduct", "s1"),
    Consumer("c2", "ProductConsumer", "python",  "createProduct", "s1"),
    Consumer("c3", "OrderConsumer",   "java",    "createOrder",   "s2"),
    Consumer("c4", "InventoryConsumer","go",     "checkStock",    "s3"),
]
