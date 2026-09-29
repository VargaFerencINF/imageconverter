"""Konverziós riport exportálása CSV-be (Excel-barát: UTF-8 BOM, pontosvessző)."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from ..i18n import tr
from .models import JobResult


def _dims(d: tuple[int, int] | None) -> str:
    return f"{d[0]}x{d[1]}" if d else ""


def write_csv(results: Iterable[JobResult], path: Path | str) -> int:
    """A riport sorainak száma (formátumonként egy sor) a visszatérési érték."""
    headers = [
        tr("report.source"),
        tr("report.format"),
        tr("report.output"),
        tr("report.status"),
        tr("report.source_bytes"),
        tr("report.output_bytes"),
        tr("report.saving"),
        tr("report.source_dims"),
        tr("report.output_dims"),
        tr("report.quality"),
        tr("report.seconds"),
        tr("report.message"),
    ]
    rows = 0
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(headers)
        for r in results:
            messages = [m for m in [r.error, *r.warnings] if m]
            targets = r.targets or [None]
            for t in targets:
                saving = ""
                if t is not None and t.size and r.source_size:
                    saving = f"{(1 - t.size / r.source_size) * 100:.1f}".replace(".", tr("decimal_sep"))
                note = "; ".join([*(messages if t is targets[0] else []), *([t.note] if t and t.note else [])])
                writer.writerow(
                    [
                        str(r.source),
                        t.fmt.value.upper() if t else "",
                        str(t.dest) if t and t.dest else "",
                        tr(f"status.{(t.status if t else r.status).value}"),
                        r.source_size,
                        t.size if t and t.size else "",
                        saving,
                        _dims(r.original_dims),
                        _dims(r.output_dims),
                        t.quality if t and t.quality is not None else "",
                        f"{r.elapsed:.2f}".replace(".", tr("decimal_sep")),
                        note,
                    ]
                )
                rows += 1
    return rows
