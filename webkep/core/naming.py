"""Kimeneti fájlnevek és útvonalak megtervezése, ütközéskezeléssel."""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

from .formats import OUTPUT_EXTENSIONS
from .models import Job, SkipReason, Target
from .scanner import SourceItem
from .settings import ConflictPolicy, ConversionSettings, NamingOptions, OutputFormat, SourceOptions

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_NON_WEB = re.compile(r"[^a-z0-9._-]+")
_DASHES = re.compile(r"-{2,}")


def slugify(text: str) -> str:
    """Webbarát fájlnév: ékezetek nélkül, kisbetűvel, szóköz helyett kötőjel.

    >>> slugify("Nyári Fotó – Balaton (1)")
    'nyari-foto-balaton-1'
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in normalized if not unicodedata.combining(c))
    ascii_text = ascii_text.replace("ß", "ss").replace("ø", "o").replace("æ", "ae")
    slug = _NON_WEB.sub("-", ascii_text.lower())
    slug = _DASHES.sub("-", slug).strip("-._")
    return slug or "image"


def output_stem(source: Path, naming: NamingOptions) -> str:
    stem = f"{naming.prefix}{source.stem}{naming.suffix}"
    if naming.web_safe:
        stem = slugify(stem)
    elif naming.lowercase:
        stem = stem.lower()
    stem = _INVALID_CHARS.sub("_", stem).rstrip(" .")
    return stem or "image"


def output_name(source: Path, fmt: OutputFormat, naming: NamingOptions) -> str:
    return output_stem(source, naming) + OUTPUT_EXTENSIONS[fmt]


def output_dir_for(item: SourceItem, output_root: Path | None, src: SourceOptions) -> Path:
    if src.beside_source or output_root is None:
        return item.path.parent
    if src.keep_structure:
        return Path(output_root) / item.rel_dir
    return Path(output_root)


def _key(path: Path) -> str:
    # Kis/nagybetű-érzéketlen összehasonlítás (Windows/macOS fájlrendszerek).
    return os.path.normcase(os.path.abspath(path)).casefold()


def _numbered(path: Path, n: int) -> Path:
    return path.with_name(f"{path.stem}_{n}{path.suffix}")


def _next_free(path: Path, reserved: set[str], check_disk: bool) -> Path:
    n = 1
    while True:
        candidate = _numbered(path, n)
        if _key(candidate) not in reserved and not (check_disk and candidate.exists()):
            return candidate
        n += 1


def resolve_target(
    source: Path, dest: Path, policy: ConflictPolicy, reserved: set[str]
) -> tuple[Path, SkipReason | None, bool]:
    """Ütközések feloldása. Visszaad: (végső útvonal, kihagyás oka, átnevezve?)."""
    renamed = False
    # A forrásfájlt soha nem írjuk felül (pl. WebP -> WebP ugyanabba a mappába).
    if _key(dest) == _key(source):
        dest = _next_free(dest, reserved, check_disk=policy is not ConflictPolicy.OVERWRITE)
        renamed = True
    # Ugyanazon kötegen belüli névütközés (pl. kep.jpg + kep.png -> kep.webp).
    if _key(dest) in reserved:
        dest = _next_free(dest, reserved, check_disk=policy is not ConflictPolicy.OVERWRITE)
        renamed = True

    skip: SkipReason | None = None
    if dest.exists():
        if policy is ConflictPolicy.SKIP:
            skip = SkipReason.EXISTS
        elif policy is ConflictPolicy.RENAME:
            dest = _next_free(dest, reserved, check_disk=True)
            renamed = True
        elif policy is ConflictPolicy.UPDATE:
            try:
                if dest.stat().st_mtime >= source.stat().st_mtime:
                    skip = SkipReason.UP_TO_DATE
            except OSError:
                pass
    reserved.add(_key(dest))
    return dest, skip, renamed


def plan_jobs(
    items: list[SourceItem],
    settings: ConversionSettings,
    output_root: Path | None,
    src: SourceOptions,
    indices: list[int] | None = None,
) -> list[Job]:
    """Minden forráshoz megtervezi a kimeneti fájl(oka)t.

    Az ``indices`` a hívó saját sorszámait adja (pl. a GUI táblázat sorai)."""
    reserved: set[str] = set()
    jobs: list[Job] = []
    for pos, item in enumerate(items):
        out_dir = output_dir_for(item, output_root, src)
        targets: list[Target] = []
        for fmt in settings.formats:
            dest = out_dir / output_name(item.path, fmt, settings.naming)
            dest, skip, renamed = resolve_target(item.path, dest, settings.naming.conflict, reserved)
            targets.append(Target(fmt, dest, skip, renamed))
        index = indices[pos] if indices is not None else pos
        jobs.append(Job(index, item.path, item.size, targets))
    return jobs
