import os
import time
from pathlib import Path

from webkep.core.models import SkipReason
from webkep.core.naming import output_name, plan_jobs, slugify
from webkep.core.scanner import SourceItem
from webkep.core.settings import ConflictPolicy, ConversionSettings, NamingOptions, OutputFormat, SourceOptions


def test_slugify_hungarian():
    assert slugify("Árvíztűrő Tükörfúrógép") == "arvizturo-tukorfurogep"
    assert slugify("Nyári Fotó – Balaton (1)") == "nyari-foto-balaton-1"
    assert slugify("  ___ ") == "image"


def test_output_name_prefix_suffix_websafe():
    naming = NamingOptions(prefix="Web ", suffix="-min", web_safe=True)
    assert output_name(Path("Őszi Kép.JPG"), OutputFormat.WEBP, naming) == "web-oszi-kep-min.webp"
    naming = NamingOptions(lowercase=True)
    assert output_name(Path("IMG_01.PNG"), OutputFormat.AVIF, naming) == "img_01.avif"


def _items(root: Path, *names: str) -> list[SourceItem]:
    items = []
    for n in names:
        p = root / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        items.append(SourceItem(p, root, 1))
    return items


def test_keep_structure_and_flat(tmp_path):
    src = tmp_path / "in"
    out = tmp_path / "out"
    items = _items(src, "a/b/kep.jpg", "c.png")
    s = ConversionSettings(formats=[OutputFormat.WEBP, OutputFormat.AVIF])
    jobs = plan_jobs(items, s, out, SourceOptions(keep_structure=True))
    assert jobs[0].targets[0].dest == out / "a" / "b" / "kep.webp"
    assert jobs[0].targets[1].dest == out / "a" / "b" / "kep.avif"
    jobs = plan_jobs(items, s, out, SourceOptions(keep_structure=False))
    assert jobs[0].targets[0].dest == out / "kep.webp"


def test_intra_batch_collision_is_disambiguated(tmp_path):
    items = _items(tmp_path / "in", "kep.jpg", "kep.png", "KEP.bmp")
    jobs = plan_jobs(items, ConversionSettings(), tmp_path / "out", SourceOptions())
    names = [j.targets[0].dest.name for j in jobs]
    assert names == ["kep.webp", "kep_1.webp", "KEP_2.webp"]
    assert jobs[1].targets[0].renamed


def test_never_overwrites_source(tmp_path):
    items = _items(tmp_path, "kep.webp")
    jobs = plan_jobs(items, ConversionSettings(), None, SourceOptions(beside_source=True))
    assert jobs[0].targets[0].dest == tmp_path / "kep_1.webp"


def test_conflict_policies(tmp_path):
    items = _items(tmp_path / "in", "kep.jpg")
    out = tmp_path / "out"
    out.mkdir()
    (out / "kep.webp").write_bytes(b"old")

    def plan(policy):
        s = ConversionSettings(naming=NamingOptions(conflict=policy))
        return plan_jobs(items, s, out, SourceOptions())[0].targets[0]

    assert plan(ConflictPolicy.OVERWRITE).dest == out / "kep.webp"
    assert plan(ConflictPolicy.OVERWRITE).skip is None
    assert plan(ConflictPolicy.SKIP).skip is SkipReason.EXISTS
    assert plan(ConflictPolicy.RENAME).dest == out / "kep_1.webp"

    # UPDATE: a kimenet újabb, mint a forrás -> kihagyás; régebbi -> újrakészítés
    now = time.time()
    os.utime(items[0].path, (now - 100, now - 100))
    os.utime(out / "kep.webp", (now, now))
    assert plan(ConflictPolicy.UPDATE).skip is SkipReason.UP_TO_DATE
    os.utime(out / "kep.webp", (now - 200, now - 200))
    assert plan(ConflictPolicy.UPDATE).skip is None
