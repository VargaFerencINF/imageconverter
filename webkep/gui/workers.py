"""Háttérfolyamatok: mappabeolvasás, konvertálás, méretbecslés.

A Qt jelzések bármely szálból biztonságosan kibocsáthatók; a GUI szálban
lévő fogadók sorba állítva (queued) kapják meg őket."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from PIL import ExifTags, Image
from PySide6.QtCore import QObject, Signal

from ..core.batch import BatchRunner, BatchSummary, cpu_count
from ..core.converter import encode, prepare_image
from ..core.formats import register_optional_plugins
from ..core.models import Job, JobResult
from ..core.scanner import SourceItem, collect_sources
from ..core.settings import ConversionSettings, OutputFormat


def read_dims(path: Path) -> tuple[int, int] | None:
    """Képméret a fájl fejlécéből (az EXIF tájolást figyelembe véve)."""
    try:
        with Image.open(path) as im:
            w, h = im.size
            try:
                if int(im.getexif().get(ExifTags.Base.Orientation, 1) or 1) in (5, 6, 7, 8):
                    w, h = h, w
            except Exception:
                pass
            return w, h
    except Exception:
        return None


class ScanWorker(QObject):
    """Forrásfájlok felderítése, majd a képméretek beolvasása darabokban.

    Egy teljes újraolvasás (``replace=True``) érvényteleníti a korábbi
    beolvasásokat; a lista bővítései (``replace=False``) párhuzamosan
    futhatnak, így egy menet közbeni fogd-és-vidd sem vész el."""

    # "object" típus: a Python-objektumok változatlanul érkeznek meg
    # (list/dict típusnál a Qt QVariant-ná alakítaná őket).
    items_found = Signal(int, object, bool)  # generáció, list[SourceItem], replace
    dims_ready = Signal(int, object)  # generáció, list[(útvonal, dims)]
    progress = Signal(int, int, int)  # generáció, kész, összes
    finished = Signal(int, bool)  # generáció, replace

    def __init__(self) -> None:
        super().__init__()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.generation = 0

    def start(
        self,
        paths: list[Path],
        extensions: set[str],
        recursive: bool,
        exclude: list[Path],
        replace: bool = True,
    ) -> int:
        if replace:
            self.stop()
            self._stop = threading.Event()
            self.generation += 1
        gen = self.generation
        thread = threading.Thread(
            target=self._run, args=(gen, self._stop, paths, extensions, recursive, exclude, replace), daemon=True
        )
        self._threads = [t for t in self._threads if t.is_alive()] + [thread]
        thread.start()
        return gen

    def stop(self) -> None:
        """Minden futó beolvasás leállítása és érvénytelenítése."""
        self._stop.set()
        self.generation += 1

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def _run(self, gen, stop, paths, extensions, recursive, exclude, replace) -> None:
        try:
            register_optional_plugins()
            try:
                items: list[SourceItem] = collect_sources(paths, extensions, recursive, exclude, stop.is_set)
            except Exception:  # pragma: no cover - pl. elérhetetlen hálózati meghajtó
                items = []
            if stop.is_set():
                return
            self.items_found.emit(gen, items, replace)
            total = len(items)
            chunk: list = []
            for i, item in enumerate(items):
                if stop.is_set():
                    return
                chunk.append((str(item.path), read_dims(item.path)))
                if len(chunk) >= 48:
                    self.dims_ready.emit(gen, chunk)
                    self.progress.emit(gen, i + 1, total)
                    chunk = []
            if chunk:
                self.dims_ready.emit(gen, chunk)
            self.progress.emit(gen, total, total)
        finally:
            self.finished.emit(gen, replace)


class ConversionController(QObject):
    job_started = Signal(int)
    job_finished = Signal(object)  # JobResult
    all_finished = Signal(object)  # BatchSummary

    def __init__(self) -> None:
        super().__init__()
        self.runner: BatchRunner | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, jobs: list[Job], settings: ConversionSettings, workers: int) -> None:
        self.runner = BatchRunner(
            jobs,
            settings,
            workers,
            on_start=lambda job: self.job_started.emit(job.index),
            on_result=self._on_result,
        )
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _on_result(self, result: JobResult) -> None:
        self.job_finished.emit(result)

    def _run(self) -> None:
        assert self.runner is not None
        try:
            summary = self.runner.run()
        except Exception as exc:  # pragma: no cover - biztonsági háló
            summary = BatchSummary(total=len(self.runner.jobs), was_cancelled=True)
            summary.results = []
            summary.failed = summary.total
            self.job_finished.emit(JobResult(-1, Path(), 0, error=str(exc)))
        self.all_finished.emit(summary)

    def pause(self) -> None:
        if self.runner:
            self.runner.pause()

    def resume(self) -> None:
        if self.runner:
            self.runner.resume()

    def cancel(self) -> None:
        if self.runner:
            self.runner.cancel()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)


@dataclass
class EstimateResult:
    formats: dict  # OutputFormat -> {"ratio", "bytes", "samples"}
    total_bytes: int
    total_count: int
    sampled: int


class EstimateWorker(QObject):
    """Mintavételes méretbecslés: néhány képet memóriában konvertál, és az
    arányokból megbecsüli a teljes kimeneti méretet."""

    finished = Signal(object)  # EstimateResult
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, sample: list[SourceItem], settings: ConversionSettings, total_bytes: int, total_count: int) -> None:
        self._thread = threading.Thread(
            target=self._run, args=(sample, settings, total_bytes, total_count), daemon=True
        )
        self._thread.start()

    def _one(self, item: SourceItem, settings: ConversionSettings) -> dict[OutputFormat, int] | None:
        prepared = None
        try:
            prepared = prepare_image(item.path, settings)
            out = {}
            for fmt in settings.formats:
                try:
                    out[fmt] = len(encode(prepared, fmt, settings, avif_threads=1))
                except Exception:
                    pass
            return out
        except Exception:
            return None
        finally:
            if prepared is not None:
                prepared.close()

    def _run(self, sample, settings, total_bytes, total_count) -> None:
        try:
            workers = max(1, min(len(sample), cpu_count()))
            with ThreadPoolExecutor(workers) as pool:
                results = list(pool.map(lambda it: (it, self._one(it, settings)), sample))
            per_fmt: dict[OutputFormat, dict[str, int]] = {}
            for item, sizes in results:
                if not sizes:
                    continue
                for fmt, size in sizes.items():
                    agg = per_fmt.setdefault(fmt, {"in": 0, "out": 0, "n": 0})
                    agg["in"] += item.size
                    agg["out"] += size
                    agg["n"] += 1
            estimate = {}
            for fmt, agg in per_fmt.items():
                ratio = agg["out"] / agg["in"] if agg["in"] else 0
                estimate[fmt] = {"ratio": ratio, "bytes": int(total_bytes * ratio), "samples": agg["n"]}
            self.finished.emit(
                EstimateResult(formats=estimate, total_bytes=total_bytes, total_count=total_count, sampled=len(sample))
            )
        except Exception as exc:  # pragma: no cover
            self.failed.emit(str(exc))
