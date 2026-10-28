"""app/core/turn_stats.py — per-turn counters, written to the log only (nothing is stored).

`chat_service` starts a TurnStats for each chat request; the LLM retry helper and the
vector search add to it. One summary log line per turn comes out at the end, so we can
see how many model calls a turn made and where the time went.
"""

import time
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class TurnStats:
    started: float = field(default_factory=time.perf_counter)
    llm_calls: list[tuple[str, float]] = field(default_factory=list)   # (label, seconds)
    embed_calls: int = 0

    def add_llm(self, label: str, seconds: float) -> None:
        self.llm_calls.append((label, seconds))

    @property
    def total_seconds(self) -> float:
        return time.perf_counter() - self.started

    @property
    def llm_seconds(self) -> float:
        return sum(s for _, s in self.llm_calls)

    def llm_summary(self) -> str:
        return ",".join(f"{label}:{seconds:.1f}s" for label, seconds in self.llm_calls) or "-"


_current: ContextVar[TurnStats | None] = ContextVar("turn_stats", default=None)


def start_turn() -> TurnStats:
    stats = TurnStats()
    _current.set(stats)
    return stats


def current() -> TurnStats | None:
    return _current.get()
