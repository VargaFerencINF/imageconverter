"""Párhuzamos kötegelt feldolgozás szüneteltetéssel és megszakítással."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .converter import convert_job
from .models import Job, JobResult, Status, TargetResult
from .settings import ConversionSettings, OutputFormat


def cpu_count() -> int:
    return max(1, os.cpu_count() or 1)


def default_workers() -> int:
    return cpu_count()


@dataclass
class BatchSummary:
    total: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    cancelled: int = 0
    files_written: int = 0
    input_bytes: int = 0
    converted_input_bytes: int = 0
    output_bytes: int = 0
    elapsed: float = 0.0
    was_cancelled: bool = False
    results: list[JobResult] = field(default_factory=list)

    # formátumonként: [forrás bájtok, kimeneti bájtok, fájlok száma]
    per_format: dict[OutputFormat, list[int]] = field(default_factory=dict)

    def format_saving(self, fmt: OutputFormat) -> float | None:
        """Megtakarítás aránya az adott formátumban megírt képekre (0..1)."""
        src, out, _n = self.per_format.get(fmt, (0, 0, 0))
        if src <= 0:
            return None
        return 1.0 - out / src

    def add(self, r: JobResult) -> None:
        self.results.append(r)
        self.input_bytes += r.source_size
        if r.status is Status.DONE:
            self.done += 1
            self.converted_input_bytes += r.source_size
        elif r.status is Status.SKIPPED:
            self.skipped += 1
        elif r.status is Status.FAILED:
            self.failed += 1
        elif r.status is Status.CANCELLED:
            self.cancelled += 1
        written = r.written
        self.files_written += len(written)
        self.output_bytes += sum(t.size for t in written)
        for t in written:
            stats = self.per_format.setdefault(t.fmt, [0, 0, 0])
            stats[0] += r.source_size
            stats[1] += t.size
            stats[2] += 1


class BatchRunner:
    """Feladatok futtatása szálkészletben.

    A Pillow WebP és AVIF kódolója elengedi a GIL-t, így a szálak valóban
    párhuzamosan dolgoznak (nincs szükség külön folyamatokra, ami a
    fagyasztott .exe-ben is egyszerűbb és megbízhatóbb)."""

    def __init__(
        self,
        jobs: list[Job],
        settings: ConversionSettings,
        workers: int = 0,
        on_start: Callable[[Job], None] | None = None,
        on_result: Callable[[JobResult], None] | None = None,
    ) -> None:
        self.jobs = jobs
        self.settings = settings
        self.workers = max(1, workers or default_workers())
        self.on_start = on_start
        self.on_result = on_result
        self._cancel = threading.Event()
        self._resume = threading.Event()
        self._resume.set()

    # -- vezérlés ---------------------------------------------------------
    def cancel(self) -> None:
        self._cancel.set()
        self._resume.set()

    def pause(self) -> None:
        if not self._cancel.is_set():
            self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # -- futtatás ---------------------------------------------------------
    def _avif_threads(self) -> int:
        # Ne terheljük túl a processzort: a kódolók belső szálai és a
        # párhuzamos feladatok együtt se lépjék túl érdemben a magok számát.
        return max(1, cpu_count() // self.workers)

    def _run_one(self, job: Job, avif_threads: int) -> JobResult:
        while not self._resume.wait(0.2):
            if self._cancel.is_set():
                break
        if self._cancel.is_set():
            return _cancelled_result(job)
        if self.on_start is not None:
            try:
                self.on_start(job)
            except Exception:
                pass
        return convert_job(job, self.settings, self._cancel, avif_threads)

    def run(self) -> BatchSummary:
        summary = BatchSummary(total=len(self.jobs))
        started = time.perf_counter()
        avif_threads = self._avif_threads()
        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="webkep") as pool:
            futures = [pool.submit(self._run_one, job, avif_threads) for job in self.jobs]
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                except Exception as exc:  # pragma: no cover - convert_job maga kezeli
                    job = self.jobs[futures.index(fut)]
                    res = JobResult(job.index, job.source, job.source_size, Status.FAILED, error=str(exc))
                summary.add(res)
                if self.on_result is not None:
                    try:
                        self.on_result(res)
                    except Exception:
                        pass
        summary.results.sort(key=lambda r: r.index)
        summary.elapsed = time.perf_counter() - started
        summary.was_cancelled = self._cancel.is_set()
        return summary


def _cancelled_result(job: Job) -> JobResult:
    res = JobResult(job.index, job.source, job.source_size, Status.CANCELLED)
    res.targets = [TargetResult(t.fmt, t.dest, Status.CANCELLED) for t in job.targets]
    return res
