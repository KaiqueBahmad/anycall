from dataclasses import dataclass
from datetime import timedelta


@dataclass
class AnycallProperties:
    """Configuration properties for AnyCall."""
    timeout: timedelta = timedelta(seconds=30)
    metrics_enabled: bool = False
