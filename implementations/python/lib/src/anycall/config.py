from dataclasses import dataclass
from datetime import timedelta


@dataclass
class AnycallProperties:
    """Configuration properties for AnyCall."""
    timeout: timedelta = timedelta(0)  # no limit
    metrics_enabled: bool = False
