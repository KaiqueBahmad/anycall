from dataclasses import dataclass


@dataclass
class Supplier:
    id: str
    name: str
    group: str
    active: bool = False
    loading: bool = False


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
