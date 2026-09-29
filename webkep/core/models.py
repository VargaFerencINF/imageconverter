"""Feladat- és eredmény-adatszerkezetek."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .settings import OutputFormat


class Status(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SkipReason(str, Enum):
    EXISTS = "exists"
    UP_TO_DATE = "up_to_date"
    LARGER = "larger"


@dataclass
class Target:
    """Egy kimeneti fájl terve (formátum + útvonal)."""

    fmt: OutputFormat
    dest: Path
    skip: SkipReason | None = None
    renamed: bool = False


@dataclass
class Job:
    """Egy forráskép feldolgozása – egy vagy több kimeneti formátumba."""

    index: int
    source: Path
    source_size: int
    targets: list[Target]


@dataclass
class TargetResult:
    fmt: OutputFormat
    dest: Path | None
    status: Status
    size: int = 0
    quality: int | None = None
    skip: SkipReason | None = None
    note: str = ""


@dataclass
class JobResult:
    index: int
    source: Path
    source_size: int
    status: Status = Status.PENDING
    targets: list[TargetResult] = field(default_factory=list)
    original_dims: tuple[int, int] | None = None
    output_dims: tuple[int, int] | None = None
    frames: int = 1
    elapsed: float = 0.0
    error: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def written(self) -> list[TargetResult]:
        return [t for t in self.targets if t.status is Status.DONE]

    @property
    def output_bytes(self) -> int:
        return sum(t.size for t in self.written)

    def target(self, fmt: OutputFormat) -> TargetResult | None:
        for t in self.targets:
            if t.fmt is fmt:
                return t
        return None

    def finalize_status(self) -> None:
        if self.error:
            self.status = Status.FAILED
        elif any(t.status is Status.DONE for t in self.targets):
            self.status = Status.DONE
        elif any(t.status is Status.FAILED for t in self.targets):
            self.status = Status.FAILED
        elif any(t.status is Status.CANCELLED for t in self.targets):
            self.status = Status.CANCELLED
        else:
            self.status = Status.SKIPPED
