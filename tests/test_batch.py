import threading
from pathlib import Path

from webkep.core.batch import BatchRunner
from webkep.core.formats import extensions_for_groups
from webkep.core.models import Status
from webkep.core.naming import plan_jobs
from webkep.core.report import write_csv
from webkep.core.scanner import collect_sources
from webkep.core.settings import ConversionSettings, OutputFormat, SourceOptions

from .conftest import photo


def _tree(root: Path) -> None:
    for rel in ["a.jpg", "sub/b.png", "sub/deep/c.bmp", "sub/deep/d.gif", "skip.txt", ".hidden/e.jpg"]:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".txt"):
            p.write_text("x")
        else:
            photo((64, 48)).save(p)


def test_scan_recursive_and_excludes_output(tmp_path):
    src = tmp_path / "in"
    _tree(src)
    out = src / "web"  # a kimenet a bemeneten belül van – nem szabad újra beolvasni
    out.mkdir()
    photo((10, 10)).save(out / "old.png")
    exts = extensions_for_groups(SourceOptions().groups)
    items = collect_sources([src], exts, recursive=True, exclude_dirs=[out])
    rels = sorted(str(i.rel_path).replace("\\", "/") for i in items)
    assert rels == ["a.jpg", "sub/b.png", "sub/deep/c.bmp", "sub/deep/d.gif"]
    flat = collect_sources([src], exts, recursive=False)
    assert [i.path.name for i in flat] == ["a.jpg"]


def test_scan_single_files_and_dedupe(tmp_path):
    src = tmp_path / "in"
    _tree(src)
    exts = extensions_for_groups(["jpeg", "png"])
    items = collect_sources([src / "a.jpg", src / "a.jpg", src / "sub"], exts)
    assert [i.path.name for i in items] == ["a.jpg", "b.png"]
    assert items[0].rel_path == Path("a.jpg")


def test_batch_end_to_end(tmp_path):
    src = tmp_path / "in"
    out = tmp_path / "out"
    _tree(src)
    s = ConversionSettings(formats=[OutputFormat.WEBP, OutputFormat.AVIF])
    src_opts = SourceOptions()
    items = collect_sources([src], extensions_for_groups(src_opts.groups))
    jobs = plan_jobs(items, s, out, src_opts)
    started, finished = [], []
    runner = BatchRunner(jobs, s, workers=3, on_start=lambda j: started.append(j.index), on_result=finished.append)
    summary = runner.run()
    assert summary.total == 4 and summary.done == 4 and summary.failed == 0
    assert summary.files_written == 8
    assert sorted(started) == [0, 1, 2, 3]
    assert (out / "sub" / "deep" / "c.webp").exists()
    assert (out / "sub" / "deep" / "c.avif").exists()
    assert not list(out.rglob(".webkep-*"))  # nincs ottmaradt ideiglenes fájl
    assert set(summary.per_format) == {OutputFormat.WEBP, OutputFormat.AVIF}

    report = tmp_path / "riport.csv"
    rows = write_csv(summary.results, report)
    assert rows == 8
    text = report.read_text(encoding="utf-8-sig")
    assert text.splitlines()[0].startswith("Forrás;Formátum")


def test_batch_cancel(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    for i in range(12):
        photo((300, 200)).save(src / f"k{i}.png")
    s = ConversionSettings(formats=[OutputFormat.AVIF])
    s.avif.speed = 0  # lassú, hogy legyen idő megszakítani
    items = collect_sources([src], extensions_for_groups(["png"]))
    jobs = plan_jobs(items, s, tmp_path / "out", SourceOptions())
    runner = None

    def on_result(res):
        runner.cancel()

    runner = BatchRunner(jobs, s, workers=1, on_result=on_result)
    summary = runner.run()
    assert summary.was_cancelled
    assert summary.cancelled >= 10
    assert summary.done + summary.cancelled == 12


def test_batch_pause_resume(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    for i in range(3):
        photo((64, 64)).save(src / f"k{i}.png")
    s = ConversionSettings()
    items = collect_sources([src], extensions_for_groups(["png"]))
    jobs = plan_jobs(items, s, tmp_path / "out", SourceOptions())
    runner = BatchRunner(jobs, s, workers=2)
    runner.pause()
    assert runner.paused
    timer = threading.Timer(0.4, runner.resume)
    timer.start()
    summary = runner.run()
    assert summary.done == 3
    assert all(r.status is Status.DONE for r in summary.results)
