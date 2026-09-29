"""Névjegy, összegzés és méretbecslés párbeszédablakok."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, REPO_URL, __version__
from ..core.batch import BatchSummary
from ..core.formats import library_versions
from ..core.models import Status
from ..core.settings import OutputFormat
from ..i18n import fmt_bytes, fmt_duration, fmt_percent, tr
from . import theme
from .widgets import Card
from .workers import EstimateResult


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("about.title"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 16)
        lay.setSpacing(14)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(64))
        head.addWidget(logo)
        col = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("AppTitle")
        ver = QLabel(tr("about.version", v=__version__))
        ver.setObjectName("Muted")
        col.addWidget(title)
        col.addWidget(ver)
        head.addLayout(col, 1)
        lay.addLayout(head)

        desc = QLabel(tr("about.description"))
        desc.setWordWrap(True)
        lay.addWidget(desc)

        card = Card(tr("about.libraries"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        for i, (k, v) in enumerate(library_versions().items()):
            key = QLabel(k)
            key.setObjectName("Muted")
            val = QLabel(str(v))
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            val.setWordWrap(True)
            grid.addWidget(key, i, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(val, i, 1)
        card.body().addLayout(grid)
        lay.addWidget(card)

        shortcuts = Card(tr("about.shortcuts"))
        sc = QLabel(tr("about.shortcuts_text"))
        sc.setTextFormat(Qt.TextFormat.RichText)
        shortcuts.body().addWidget(sc)
        lay.addWidget(shortcuts)

        link = QLabel(f"<a href='{REPO_URL}'>{REPO_URL}</a>")
        link.setOpenExternalLinks(True)
        lay.addWidget(link)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("common.close"))
        lay.addWidget(buttons)


def _stat(grid: QGridLayout, col: int, value: str, label: str, name: str = "BigStat") -> None:
    v = QLabel(value)
    v.setObjectName(name)
    v.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl = QLabel(label)
    lbl.setObjectName("Muted")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    grid.addWidget(v, 0, col)
    grid.addWidget(lbl, 1, col)


class SummaryDialog(QDialog):
    def __init__(self, summary: BatchSummary, output_dir: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.summary = summary
        self.output_dir = output_dir
        self.export_requested = False
        self.setWindowTitle(tr("sum.title"))
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(14)

        if summary.was_cancelled:
            head_text, head_name = tr("sum.cancelled"), "Warning"
        elif summary.failed:
            head_text, head_name = tr("sum.with_errors"), "Warning"
        else:
            head_text, head_name = tr("sum.success"), "Success"
        head = QLabel(head_text)
        head.setObjectName(head_name)
        head.setStyleSheet("font-size: 15pt;")
        lay.addWidget(head)
        sub = QLabel(tr("sum.subtitle", n=summary.total, time=fmt_duration(summary.elapsed)))
        sub.setObjectName("Muted")
        lay.addWidget(sub)

        card = Card()
        grid = QGridLayout()
        _stat(grid, 0, str(summary.done), tr("sum.done"), "BigStat")
        _stat(grid, 1, str(summary.skipped), tr("sum.skipped"))
        _stat(grid, 2, str(summary.failed), tr("sum.failed"))
        _stat(grid, 3, str(summary.files_written), tr("sum.files"))
        card.body().addLayout(grid)
        lay.addWidget(card)

        if summary.per_format:
            card = Card(tr("sum.sizes"))
            g = QGridLayout()
            g.setHorizontalSpacing(18)
            for i, fmt in enumerate(OutputFormat):
                if fmt not in summary.per_format:
                    continue
                src, out, n = summary.per_format[fmt]
                saving = summary.format_saving(fmt) or 0
                name = QLabel(f"<b>{fmt.value.upper()}</b>")
                detail = QLabel(tr("sum.format_line", n=n, src=fmt_bytes(src), out=fmt_bytes(out)))
                pct = QLabel(fmt_percent(saving, 1, signed=True))
                pct.setObjectName("Success" if saving > 0 else "Danger")
                g.addWidget(name, i, 0)
                g.addWidget(detail, i, 1)
                g.addWidget(pct, i, 2, Qt.AlignmentFlag.AlignRight)
            card.body().addLayout(g)
            lay.addWidget(card)

        problems = [r for r in summary.results if r.status is Status.FAILED]
        if problems:
            box = QPlainTextEdit()
            box.setObjectName("Log")
            box.setReadOnly(True)
            lines = []
            for r in problems[:200]:
                reason = r.error or "; ".join(t.note for t in r.targets if t.note)
                lines.append(f"{r.source.name}: {reason}")
            if len(problems) > 200:
                lines.append(tr("sum.more", n=len(problems) - 200))
            box.setPlainText("\n".join(lines))
            box.setMaximumHeight(150)
            lay.addWidget(QLabel(tr("sum.errors")))
            lay.addWidget(box)

        row = QHBoxLayout()
        open_btn = QPushButton(tr("btn.open_output"))
        open_btn.setIcon(theme.icon("external"))
        open_btn.clicked.connect(self._open_output)
        open_btn.setEnabled(bool(output_dir))
        export_btn = QPushButton(tr("btn.export"))
        export_btn.setIcon(theme.icon("download"))
        export_btn.clicked.connect(self._export)
        close_btn = QPushButton(tr("common.close"))
        close_btn.setObjectName("Primary")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        row.addWidget(open_btn)
        row.addWidget(export_btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        lay.addLayout(row)

    def _open_output(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir))

    def _export(self) -> None:
        self.export_requested = True
        self.accept()


class EstimateDialog(QDialog):
    def __init__(self, result: EstimateResult, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("est.title"))
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)
        intro = QLabel(
            tr("est.intro", sampled=result.sampled, n=result.total_count, size=fmt_bytes(result.total_bytes))
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)
        card = Card()
        g = QGridLayout()
        g.setHorizontalSpacing(18)
        formats = result.formats
        if not formats:
            g.addWidget(QLabel(tr("est.none")), 0, 0)
        for i, fmt in enumerate(OutputFormat):
            info = formats.get(fmt)
            if not info:
                continue
            saving = 1 - info["ratio"]
            g.addWidget(QLabel(f"<b>{fmt.value.upper()}</b>"), i, 0)
            g.addWidget(QLabel(tr("est.line", out=fmt_bytes(info["bytes"]))), i, 1)
            pct = QLabel(fmt_percent(saving, 0, signed=True))
            pct.setObjectName("Success" if saving > 0 else "Danger")
            g.addWidget(pct, i, 2, Qt.AlignmentFlag.AlignRight)
        card.body().addLayout(g)
        lay.addWidget(card)
        note = QLabel(tr("est.note"))
        note.setObjectName("Hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("common.close"))
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
