from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class ForwardSignal:
    stock_id: str
    signal_date: date
    score: int
    label: str


class ForwardTracker:
    def __init__(self) -> None:
        self.signals: list[ForwardSignal] = []

    def add(self, signal: ForwardSignal) -> None:
        self.signals.append(signal)

    def pending(self) -> list[ForwardSignal]:
        return list(self.signals)

