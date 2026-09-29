from PIL import Image

from webkep.cli import main

from .conftest import photo


def test_cli_end_to_end(tmp_path, capsys):
    src = tmp_path / "Képek"
    (src / "nyár").mkdir(parents=True)
    photo((800, 600)).save(src / "nyár" / "Strand Fotó.jpg", quality=92)
    photo((300, 300)).save(src / "logo.png")
    out = tmp_path / "web"
    report = tmp_path / "r.csv"
    code = main(
        [str(src), "-o", str(out), "-f", "webp", "avif", "-q", "70", "--long-edge", "400",
         "--web-safe", "--report", str(report), "-j", "2"]
    )
    assert code == 0
    webp = out / "nyár" / "strand-foto.webp"
    assert webp.exists()
    assert (out / "logo.avif").exists()
    with Image.open(webp) as im:
        assert max(im.size) == 400
    assert report.exists()
    printed = capsys.readouterr().out
    assert "WEBP" in printed and "AVIF" in printed


def test_cli_dry_run_writes_nothing(tmp_path, capsys):
    src = tmp_path / "in"
    src.mkdir()
    photo((50, 50)).save(src / "a.png")
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--dry-run", "--lang", "en"]) == 0
    assert not out.exists()
    assert "a.webp" in capsys.readouterr().out


def test_cli_errors(tmp_path, capsys):
    assert main([]) == 2
    assert main([str(tmp_path)]) == 2  # nincs kimenet
    assert main([str(tmp_path / "nincs"), "-o", str(tmp_path / "o")]) == 2
    assert main(["--list-presets"]) == 0
    assert "balanced" in capsys.readouterr().out


def test_cli_preset_and_fill(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    photo((900, 600)).save(src / "a.jpg")
    out = tmp_path / "o"
    assert main([str(src), "-o", str(out), "--preset", "thumbnail", "--quiet"]) == 0
    with Image.open(out / "a-thumb.webp") as im:
        assert im.size == (400, 400)
