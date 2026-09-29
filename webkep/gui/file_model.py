"""A fájllista táblázatmodellje (nagy listákhoz is gyors)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QFont

from ..core.models import JobResult, Status
from ..core.scanner import SourceItem, natural_key
from ..core.settings import OutputFormat
from ..i18n import fmt_bytes, fmt_percent, tr
from . import theme

SORT_ROLE = Qt.ItemDataRole.UserRole + 1

COL_NAME, COL_TYPE, COL_DIMS, COL_SIZE, COL_STATUS, COL_WEBP, COL_AVIF, COL_SAVING = range(8)
COLUMN_KEYS = ["col.name", "col.type", "col.dims", "col.size", "col.status", "col.webp", "col.avif", "col.saving"]


def path_key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


@dataclass
class FileRow:
    item: SourceItem
    checked: bool = True
    dims: tuple[int, int] | None = None
    status: Status = Status.PENDING
    result: JobResult | None = None

    @property
    def best_saving(self) -> float | None:
        if not self.result or not self.result.written or not self.item.size:
            return None
        return 1 - min(t.size for t in self.result.written) / self.item.size


class FileTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[FileRow] = []
        self._by_path: dict[str, int] | None = None
        self._bold = QFont()
        self._bold.setBold(True)

    # -- Qt API -------------------------------------------------------------
    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMN_KEYS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return tr(COLUMN_KEYS[section])
            if role == Qt.ItemDataRole.TextAlignmentRole and section in (COL_SIZE, COL_WEBP, COL_AVIF, COL_SAVING):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_NAME:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(row, col)
        if role == SORT_ROLE:
            return self._sort_value(row, col)
        if role == Qt.ItemDataRole.CheckStateRole and col == COL_NAME:
            return Qt.CheckState.Checked if row.checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ForegroundRole:
            if col == COL_STATUS:
                return QBrush(theme.status_color(row.status.value))
            if col == COL_SAVING and row.best_saving is not None:
                return QBrush(theme.status_color("done" if row.best_saving > 0 else "skipped"))
            if not row.checked:
                return QBrush(theme.status_color("cancelled"))
        if role == Qt.ItemDataRole.FontRole and col == COL_STATUS and row.status is Status.RUNNING:
            return self._bold
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (COL_SIZE, COL_WEBP, COL_AVIF, COL_SAVING):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(row, col)
        return None

    def setData(self, index: QModelIndex | QPersistentModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == COL_NAME:
            row = self.rows[index.row()]
            row.checked = Qt.CheckState(value) == Qt.CheckState.Checked
            self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), len(COLUMN_KEYS) - 1))
            return True
        return False

    # -- megjelenítés -----------------------------------------------------------
    def _display(self, row: FileRow, col: int) -> str:
        if col == COL_NAME:
            return str(row.item.rel_path)
        if col == COL_TYPE:
            return row.item.path.suffix.lstrip(".").upper()
        if col == COL_DIMS:
            return f"{row.dims[0]} × {row.dims[1]}" if row.dims else ""
        if col == COL_SIZE:
            return fmt_bytes(row.item.size)
        if col == COL_STATUS:
            return tr(f"status.{row.status.value}")
        if col in (COL_WEBP, COL_AVIF):
            fmt = OutputFormat.WEBP if col == COL_WEBP else OutputFormat.AVIF
            t = row.result.target(fmt) if row.result else None
            if t is None:
                return ""
            if t.status is Status.DONE:
                return fmt_bytes(t.size)
            return "—"
        if col == COL_SAVING:
            s = row.best_saving
            return fmt_percent(s, 1, signed=True) if s is not None else ""
        return ""

    def _sort_value(self, row: FileRow, col: int) -> Any:
        if col == COL_NAME:
            return natural_key(str(row.item.rel_path))
        if col == COL_TYPE:
            return row.item.path.suffix.lower()
        if col == COL_DIMS:
            return row.dims[0] * row.dims[1] if row.dims else -1
        if col == COL_SIZE:
            return row.item.size
        if col == COL_STATUS:
            return list(Status).index(row.status)
        if col in (COL_WEBP, COL_AVIF):
            fmt = OutputFormat.WEBP if col == COL_WEBP else OutputFormat.AVIF
            t = row.result.target(fmt) if row.result else None
            return t.size if t and t.status is Status.DONE else -1
        if col == COL_SAVING:
            s = row.best_saving
            return s if s is not None else -2.0
        return 0

    def _tooltip(self, row: FileRow, col: int) -> str | None:
        if col == COL_NAME:
            return str(row.item.path)
        r = row.result
        if r is None:
            return None
        lines: list[str] = []
        if r.error:
            lines.append(r.error)
        for t in r.targets:
            parts = [f"{t.fmt.value.upper()}: {tr('status.' + t.status.value)}"]
            if t.status is Status.DONE:
                parts.append(fmt_bytes(t.size))
                if t.quality is not None:
                    parts.append(tr("tip.quality", q=t.quality))
            if t.note:
                parts.append(t.note)
            lines.append(" · ".join(parts))
            if t.dest and t.status is Status.DONE:
                lines.append(f"   {t.dest}")
        lines.extend(f"⚠ {w}" for w in r.warnings)
        if r.output_dims and r.original_dims and r.output_dims != r.original_dims:
            lines.append(tr("tip.resized", a=f"{r.original_dims[0]}×{r.original_dims[1]}",
                            b=f"{r.output_dims[0]}×{r.output_dims[1]}"))
        return "\n".join(lines) or None

    # -- módosítás --------------------------------------------------------------
    def set_rows(self, rows: list[FileRow]) -> None:
        self.beginResetModel()
        self.rows = rows
        self._by_path = None
        self.endResetModel()

    def append_rows(self, rows: list[FileRow]) -> list[FileRow]:
        """Hozzáadja az új sorokat; a már listában lévő fájlokat kihagyja."""
        index = self._path_index()
        fresh = [r for r in rows if path_key(r.item.path) not in index]
        if not fresh:
            return []
        start = len(self.rows)
        self.beginInsertRows(QModelIndex(), start, start + len(fresh) - 1)
        self.rows.extend(fresh)
        self._by_path = None
        self.endInsertRows()
        return fresh

    def _path_index(self) -> dict[str, int]:
        if self._by_path is None:
            self._by_path = {path_key(r.item.path): i for i, r in enumerate(self.rows)}
        return self._by_path

    def row_for_path(self, path) -> int | None:
        return self._path_index().get(path_key(path))

    def clear(self) -> None:
        self.set_rows([])

    def remove_rows(self, indices: list[int]) -> None:
        for i in sorted(set(indices), reverse=True):
            if 0 <= i < len(self.rows):
                self.beginRemoveRows(QModelIndex(), i, i)
                del self.rows[i]
                self.endRemoveRows()
        self._by_path = None

    def _row_changed(self, i: int) -> None:
        self.dataChanged.emit(self.index(i, 0), self.index(i, len(COLUMN_KEYS) - 1))

    def set_status(self, i: int, status: Status) -> None:
        if 0 <= i < len(self.rows):
            self.rows[i].status = status
            self._row_changed(i)

    def set_result(self, i: int, result: JobResult) -> None:
        if 0 <= i < len(self.rows):
            row = self.rows[i]
            row.result = result
            row.status = result.status
            if result.original_dims and not row.dims:
                row.dims = result.original_dims
            self._row_changed(i)

    def set_dims(self, updates: list[tuple[str, tuple[int, int] | None]]) -> None:
        index = self._path_index()
        rows = []
        for path, dims in updates:
            i = index.get(path_key(path))
            if i is not None:
                self.rows[i].dims = dims
                rows.append(i)
        if rows:
            self.dataChanged.emit(self.index(min(rows), COL_DIMS), self.index(max(rows), COL_DIMS))

    def reset_results(self, indices: list[int] | None = None) -> None:
        targets = range(len(self.rows)) if indices is None else indices
        for i in targets:
            self.rows[i].status = Status.PENDING
            self.rows[i].result = None
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(COLUMN_KEYS) - 1))

    def set_checked(self, indices: list[int] | None, checked: bool) -> None:
        targets = range(len(self.rows)) if indices is None else indices
        for i in targets:
            self.rows[i].checked = checked
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(COLUMN_KEYS) - 1))

    def refresh_all(self) -> None:
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(COLUMN_KEYS) - 1))
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(COLUMN_KEYS) - 1)

    # -- lekérdezés -----------------------------------------------------------
    def checked_indices(self) -> list[int]:
        return [i for i, r in enumerate(self.rows) if r.checked]

    def totals(self) -> tuple[int, int, int, int]:
        """(összes db, összes bájt, kijelölt db, kijelölt bájt)"""
        n = len(self.rows)
        size = sum(r.item.size for r in self.rows)
        checked = [r for r in self.rows if r.checked]
        return n, size, len(checked), sum(r.item.size for r in checked)


class FileFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterKeyColumn(COL_NAME)
        self.status_filter: Status | None = None

    def set_status_filter(self, status: Status | None) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt 6.9+
            self.beginFilterChange()
            self.status_filter = status
            self.endFilterChange()
        else:  # pragma: no cover - régebbi Qt
            self.status_filter = status
            self.invalidateRowsFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex) -> bool:  # noqa: N802
        model: FileTableModel = self.sourceModel()  # type: ignore[assignment]
        if self.status_filter is not None and model.rows[source_row].status is not self.status_filter:
            return False
        return super().filterAcceptsRow(source_row, source_parent)

    def lessThan(self, left: QModelIndex | QPersistentModelIndex, right: QModelIndex | QPersistentModelIndex) -> bool:  # noqa: N802
        a = left.data(SORT_ROLE)
        b = right.data(SORT_ROLE)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)
