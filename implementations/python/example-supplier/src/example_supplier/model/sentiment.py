from dataclasses import dataclass


@dataclass
class Sentiment:
    text: str
    label: str
