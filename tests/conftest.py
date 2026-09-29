from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import ExifTags, Image, ImageDraw

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("WEBKEP_CONFIG_DIR", str(tmp_path_factory.mktemp("config")))
    from webkep.i18n import set_language

    set_language("hu")
    yield


def photo(size=(640, 480), mode="RGB") -> Image.Image:
    """Részletgazdag tesztkép (színátmenet + alakzatok), hogy a tömörítés mérhető legyen."""
    w, h = size
    img = Image.new("RGB", size)
    grad = Image.linear_gradient("L").resize(size)
    img = Image.merge("RGB", (grad, grad.transpose(Image.Transpose.FLIP_LEFT_RIGHT), grad.rotate(90).resize(size)))
    draw = ImageDraw.Draw(img)
    for i in range(0, w, 40):
        draw.ellipse((i, (i * 7) % h, i + 30, (i * 7) % h + 30), fill=((i * 3) % 256, 80, 200))
    draw.rectangle((w // 3, h // 3, w // 2, h // 2), fill=(250, 250, 20))
    return img.convert(mode) if mode != "RGB" else img


@pytest.fixture
def make_jpeg(tmp_path: Path):
    def _make(name="photo.jpg", size=(640, 480), orientation: int | None = None, gps=False, folder=None):
        folder = Path(folder or tmp_path)
        folder.mkdir(parents=True, exist_ok=True)
        img = photo(size)
        exif = Image.Exif()
        exif[ExifTags.Base.Make] = "TestCam"
        if orientation:
            exif[ExifTags.Base.Orientation] = orientation
        if gps:
            exif[ExifTags.Base.GPSInfo] = {ExifTags.GPS.GPSLatitudeRef: "N", ExifTags.GPS.GPSLatitude: (47.0, 30.0, 0.0)}
        path = folder / name
        img.save(path, "JPEG", quality=95, exif=exif.tobytes())
        return path

    return _make


@pytest.fixture
def make_png_alpha(tmp_path: Path):
    def _make(name="alpha.png", size=(200, 150), folder=None):
        folder = Path(folder or tmp_path)
        folder.mkdir(parents=True, exist_ok=True)
        img = photo(size).convert("RGBA")
        alpha = Image.new("L", size, 0)
        ImageDraw.Draw(alpha).ellipse((10, 10, size[0] - 10, size[1] - 10), fill=255)
        img.putalpha(alpha)
        path = folder / name
        img.save(path)
        return path

    return _make


@pytest.fixture
def make_gif(tmp_path: Path):
    def _make(name="anim.gif", frames=4, size=(120, 90)):
        imgs = []
        for i in range(frames):
            im = Image.new("P", size, 0)
            im.putpalette([0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255] + [0] * (256 * 3 - 12))
            ImageDraw.Draw(im).rectangle((i * 20, 10, i * 20 + 30, 60), fill=1 + (i % 3))
            imgs.append(im)
        path = tmp_path / name
        imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=[100, 150, 200, 250][:frames], loop=0)
        return path

    return _make
