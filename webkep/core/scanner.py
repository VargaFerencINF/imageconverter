"""Forrásképek felderítése mappákból / egyedi fájlokból."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

SKIPPED_DIR_NAMES = {"$recycle.bin", "system volume information", "__macosx", "@eadir"}
TEMP_PREFIX = ".webkep-"


@dataclass(frozen=True)
class SourceItem:
    """Egy forrásfájl. A ``base`` az a mappa, amelyhez képest a relatív
    útvonalat (és így a kimeneti mappaszerkezetet) számoljuk."""

    path: Path
    base: Path
    size: int

    @property
    def rel_path(self) -> Path:
        try:
            return self.path.relative_to(self.base)
        except ValueError:
            return Path(self.path.name)

    @property
    def rel_dir(self) -> Path:
        return self.rel_path.parent


def natural_key(text: str) -> list:
    """"kep2" < "kep10" rendezés."""
    return [int(tok) if tok.isdigit() else tok.casefold() for tok in re.split(r"(\d+)", text)]


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def iter_folder(
    root: Path,
    extensions: set[str],
    recursive: bool = True,
    exclude_dirs: Iterable[Path] = (),
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[SourceItem]:
    root = Path(root)
    excluded = {_norm(p) for p in exclude_dirs if p}
    exts = {e.lower() for e in extensions}
    for dirpath, dirnames, filenames in os.walk(root):
        if should_stop and should_stop():
            return
        if recursive:
            dirnames[:] = sorted(
                (
                    d
                    for d in dirnames
                    if not d.startswith(".")
                    and d.casefold() not in SKIPPED_DIR_NAMES
                    and _norm(Path(dirpath, d)) not in excluded
                ),
                key=natural_key,
            )
        else:
            dirnames[:] = []
        for name in sorted(filenames, key=natural_key):
            if name.startswith(TEMP_PREFIX):
                continue
            if os.path.splitext(name)[1].lower() not in exts:
                continue
            full = Path(dirpath, name)
            try:
                size = full.stat().st_size
            except OSError:
                continue
            yield SourceItem(full, root, size)


def collect_sources(
    paths: Iterable[Path],
    extensions: set[str],
    recursive: bool = True,
    exclude_dirs: Iterable[Path] = (),
    should_stop: Callable[[], bool] | None = None,
) -> list[SourceItem]:
    """Mappák és fájlok vegyes listájából egyedi forráslistát készít."""
    exclude = list(exclude_dirs)
    seen: set[str] = set()
    items: list[SourceItem] = []
    exts = {e.lower() for e in extensions}

    def add(item: SourceItem) -> None:
        key = _norm(item.path)
        if key not in seen:
            seen.add(key)
            items.append(item)

    for p in paths:
        p = Path(p)
        if p.is_dir():
            for item in iter_folder(p, exts, recursive, exclude, should_stop):
                add(item)
        elif p.is_file() and p.suffix.lower() in exts:
            try:
                add(SourceItem(p, p.parent, p.stat().st_size))
            except OSError:
                continue
        if should_stop and should_stop():
            break
    return items
