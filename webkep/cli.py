"""Parancssoros felület – automatizáláshoz, szkriptekhez, szerverekhez.

Példa::

    webkep-cli ./kepek -o ./web --format webp avif --quality 80 --long-edge 1920
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .core.batch import BatchRunner, default_workers
from .core.formats import extensions_for_groups, library_versions, output_available
from .core.models import JobResult, Status
from .core.naming import plan_jobs
from .core.presets import builtin_presets, find_builtin
from .core.report import write_csv
from .core.scanner import collect_sources
from .core.settings import (
    AVIF_SUBSAMPLINGS,
    INPUT_GROUP_KEYS,
    ColorProfile,
    ConflictPolicy,
    ConversionSettings,
    OutputFormat,
    Resample,
    ResizeMode,
    SourceOptions,
)
from .i18n import fmt_bytes, fmt_duration, fmt_percent, set_language, tr


def _percent(value: str) -> int:
    v = int(value)
    if not 0 <= v <= 100:
        raise argparse.ArgumentTypeError("0-100")
    return v


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="webkep-cli",
        description=tr("cli.description"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=tr("cli.epilog"),
    )
    p.add_argument("inputs", nargs="*", type=Path, help=tr("cli.inputs"))
    p.add_argument("-o", "--output", type=Path, help=tr("cli.output"))
    p.add_argument("-V", "--version", action="version", version=f"{APP_NAME} {__version__}")
    p.add_argument("--lang", choices=["hu", "en"], help=tr("cli.lang"))
    p.add_argument("--list-presets", action="store_true", help=tr("cli.list_presets"))
    p.add_argument("--versions", action="store_true", help=tr("cli.versions"))

    g = p.add_argument_group(tr("cli.group.format"))
    g.add_argument("-p", "--preset", help=tr("cli.preset"))
    g.add_argument("-f", "--format", nargs="+", choices=["webp", "avif"], dest="formats", help=tr("cli.formats"))
    g.add_argument("-q", "--quality", type=_percent, help=tr("cli.quality"))
    g.add_argument("--webp-quality", type=_percent)
    g.add_argument("--avif-quality", type=_percent)
    g.add_argument("--lossless", action="store_true", help=tr("cli.lossless"))
    g.add_argument("--webp-method", type=int, choices=range(0, 7), metavar="0-6", help=tr("cli.webp_method"))
    g.add_argument("--webp-alpha-quality", type=_percent)
    g.add_argument("--avif-speed", type=int, choices=range(0, 11), metavar="0-10", help=tr("cli.avif_speed"))
    g.add_argument("--avif-subsampling", choices=AVIF_SUBSAMPLINGS)
    g.add_argument("--no-animation", action="store_true", help=tr("cli.no_animation"))
    g.add_argument("--target-kb", type=int, help=tr("cli.target_kb"))
    g.add_argument("--min-quality", type=_percent, help=tr("cli.min_quality"))
    g.add_argument("--skip-larger", action="store_true", help=tr("cli.skip_larger"))

    r = p.add_argument_group(tr("cli.group.resize"))
    r.add_argument("--percent", type=int, help=tr("cli.percent"))
    r.add_argument("--width", type=int, help=tr("cli.width"))
    r.add_argument("--height", type=int, help=tr("cli.height"))
    r.add_argument("--long-edge", type=int, help=tr("cli.long_edge"))
    r.add_argument("--fit", metavar="WxH", help=tr("cli.fit"))
    r.add_argument("--fill", metavar="WxH", help=tr("cli.fill"))
    r.add_argument("--upscale", action="store_true", help=tr("cli.upscale"))
    r.add_argument("--resample", choices=[m.value for m in Resample])
    r.add_argument("--sharpen", type=int, nargs="?", const=60, metavar="AMOUNT", help=tr("cli.sharpen"))

    m = p.add_argument_group(tr("cli.group.meta"))
    m.add_argument("--keep-exif", action="store_true", help=tr("cli.keep_exif"))
    m.add_argument("--keep-gps", action="store_true", help=tr("cli.keep_gps"))
    m.add_argument("--keep-xmp", action="store_true")
    m.add_argument("--color", choices=[c.value for c in ColorProfile], help=tr("cli.color"))
    m.add_argument("--no-auto-orient", action="store_true")
    m.add_argument("--no-timestamps", action="store_true", help=tr("cli.no_timestamps"))

    n = p.add_argument_group(tr("cli.group.naming"))
    n.add_argument("--prefix")
    n.add_argument("--suffix")
    n.add_argument("--web-safe", action="store_true", help=tr("cli.web_safe"))
    n.add_argument("--lowercase", action="store_true")
    n.add_argument("--on-conflict", choices=[c.value for c in ConflictPolicy], help=tr("cli.on_conflict"))
    n.add_argument("--no-recursive", action="store_true", help=tr("cli.no_recursive"))
    n.add_argument("--flat", action="store_true", help=tr("cli.flat"))
    n.add_argument("--beside-source", action="store_true", help=tr("cli.beside_source"))
    n.add_argument("--types", nargs="+", choices=INPUT_GROUP_KEYS, help=tr("cli.types"))

    x = p.add_argument_group(tr("cli.group.run"))
    x.add_argument("-j", "--workers", type=int, default=0, help=tr("cli.workers"))
    x.add_argument("--report", type=Path, help=tr("cli.report"))
    x.add_argument("-n", "--dry-run", action="store_true", help=tr("cli.dry_run"))
    x.add_argument("--quiet", action="store_true", help=tr("cli.quiet"))
    return p


def _parse_box(text: str) -> tuple[int, int]:
    try:
        w, h = text.lower().replace("×", "x").split("x")
        return max(1, int(w)), max(1, int(h))
    except ValueError:
        raise SystemExit(tr("cli.err.box", value=text)) from None


def settings_from_args(args: argparse.Namespace) -> tuple[ConversionSettings, SourceOptions]:
    if args.preset:
        preset = find_builtin(args.preset)
        if preset is None:
            raise SystemExit(tr("cli.err.preset", name=args.preset))
        s = preset.settings.copy()
    else:
        s = ConversionSettings()
    if args.formats:
        s.formats = [OutputFormat(f) for f in args.formats]
    if args.quality is not None:
        s.webp.quality = s.avif.quality = args.quality
    if args.webp_quality is not None:
        s.webp.quality = args.webp_quality
    if args.avif_quality is not None:
        s.avif.quality = args.avif_quality
    if args.lossless:
        s.webp.lossless = s.avif.lossless = True
    if args.webp_method is not None:
        s.webp.method = args.webp_method
    if args.webp_alpha_quality is not None:
        s.webp.alpha_quality = args.webp_alpha_quality
    if args.avif_speed is not None:
        s.avif.speed = args.avif_speed
    if args.avif_subsampling:
        s.avif.subsampling = args.avif_subsampling
    if args.no_animation:
        s.keep_animation = False
    if args.target_kb:
        s.target_size_enabled, s.target_size_kb = True, args.target_kb
    if args.min_quality is not None:
        s.target_min_quality = args.min_quality
    if args.skip_larger:
        s.skip_if_larger = True

    rz = s.resize
    if args.percent:
        rz.mode, rz.percent = ResizeMode.PERCENT, args.percent
    if args.width and args.height and not (args.fit or args.fill):
        rz.mode, rz.width, rz.height = ResizeMode.FIT, args.width, args.height
    elif args.width:
        rz.mode, rz.width = ResizeMode.WIDTH, args.width
    elif args.height:
        rz.mode, rz.height = ResizeMode.HEIGHT, args.height
    if args.long_edge:
        rz.mode, rz.long_edge = ResizeMode.LONG_EDGE, args.long_edge
    if args.fit:
        rz.mode = ResizeMode.FIT
        rz.width, rz.height = _parse_box(args.fit)
    if args.fill:
        rz.mode = ResizeMode.FILL
        rz.width, rz.height = _parse_box(args.fill)
    if args.upscale:
        rz.allow_upscale = True
    if args.resample:
        rz.resample = Resample(args.resample)
    if args.sharpen is not None:
        rz.sharpen, rz.sharpen_amount = True, args.sharpen

    md = s.metadata
    if args.keep_exif:
        md.keep_exif = True
    if args.keep_gps:
        md.strip_gps = False
    if args.keep_xmp:
        md.keep_xmp = True
    if args.color:
        md.color_profile = ColorProfile(args.color)
    if args.no_auto_orient:
        md.auto_orient = False
    if args.no_timestamps:
        md.preserve_timestamps = False

    nm = s.naming
    if args.prefix is not None:
        nm.prefix = args.prefix
    if args.suffix is not None:
        nm.suffix = args.suffix
    if args.web_safe:
        nm.web_safe = True
    if args.lowercase:
        nm.lowercase = True
    if args.on_conflict:
        nm.conflict = ConflictPolicy(args.on_conflict)

    src = SourceOptions(
        recursive=not args.no_recursive,
        keep_structure=not args.flat,
        beside_source=args.beside_source,
    )
    if args.types:
        src.groups = list(args.types)
    return s.validate(), src.validate()


def _result_line(res: JobResult, done: int, total: int) -> str:
    width = len(str(total))
    head = f"[{done:>{width}}/{total}] {res.source.name}"
    if res.status is Status.FAILED:
        return f"{head}  ✗ {res.error or '; '.join(t.note for t in res.targets if t.note)}"
    parts = []
    for t in res.targets:
        if t.status is Status.DONE:
            change = fmt_percent(1 - t.size / res.source_size, 0, signed=True) if res.source_size else ""
            parts.append(f"→ {t.dest.name if t.dest else ''} ({fmt_bytes(t.size)}, {change})")
        else:
            parts.append(f"{t.fmt.value}: {tr('status.' + t.status.value)}{' – ' + t.note if t.note else ''}")
    return f"{head}  " + "  ".join(parts)


def main(argv: list[str] | None = None) -> int:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang", choices=["hu", "en"])
    known, _ = pre.parse_known_args(argv)
    if known.lang:
        set_language(known.lang)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.versions:
        for k, v in library_versions().items():
            print(f"{k}: {v}")
        return 0
    if args.list_presets:
        for preset in builtin_presets():
            print(f"{preset.key:<18} {preset.name} – {preset.description}")
        return 0
    if not args.inputs:
        parser.print_usage(sys.stderr)
        print(tr("cli.err.no_input"), file=sys.stderr)
        return 2
    if not args.output and not args.beside_source:
        print(tr("cli.err.no_output"), file=sys.stderr)
        return 2

    settings, src = settings_from_args(args)
    for fmt in settings.formats:
        if not output_available(fmt):
            print(tr("err.format_unavailable", fmt=fmt.value.upper()), file=sys.stderr)
            return 2

    missing = [p for p in args.inputs if not p.exists()]
    if missing:
        print(tr("cli.err.missing", path=missing[0]), file=sys.stderr)
        return 2

    output = args.output.resolve() if args.output else None
    items = collect_sources(
        args.inputs,
        extensions_for_groups(src.groups),
        src.recursive,
        exclude_dirs=[output] if output else [],
    )
    if not items:
        print(tr("cli.no_files"))
        return 0

    jobs = plan_jobs(items, settings, output, src)
    total = len(jobs)
    workers = args.workers or default_workers()
    if not args.quiet:
        fmts = " + ".join(f.value.upper() for f in settings.formats)
        print(tr("cli.start", n=total, size=fmt_bytes(sum(i.size for i in items)), fmts=fmts, workers=workers))

    if args.dry_run:
        for job in jobs:
            for t in job.targets:
                flag = f"  [{tr('skip.' + t.skip.value)}]" if t.skip else ""
                print(f"{job.source}  →  {t.dest}{flag}")
        return 0

    done = 0

    def on_result(res: JobResult) -> None:
        nonlocal done
        done += 1
        if not args.quiet or res.status is Status.FAILED:
            print(_result_line(res, done, total), flush=True)

    runner = BatchRunner(jobs, settings, workers, on_result=on_result)
    previous = signal.getsignal(signal.SIGINT)

    def on_sigint(_sig, _frame):  # első Ctrl+C: szabályos leállítás
        print("\n" + tr("cli.cancelling"), file=sys.stderr, flush=True)
        runner.cancel()
        signal.signal(signal.SIGINT, previous)

    signal.signal(signal.SIGINT, on_sigint)
    try:
        summary = runner.run()
    finally:
        signal.signal(signal.SIGINT, previous)

    if args.report:
        write_csv(summary.results, args.report)

    print()
    print(
        tr(
            "cli.summary",
            done=summary.done,
            skipped=summary.skipped,
            failed=summary.failed,
            time=fmt_duration(summary.elapsed),
        )
    )
    for fmt, (src_bytes, out_bytes, count) in summary.per_format.items():
        saving = summary.format_saving(fmt) or 0.0
        print(
            f"  {fmt.value.upper()}: {count} × — {fmt_bytes(src_bytes)} → {fmt_bytes(out_bytes)} "
            f"({fmt_percent(saving, 1, signed=True)})"
        )
    if args.report:
        print(tr("cli.report_written", path=args.report))
    if summary.was_cancelled:
        return 130
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
