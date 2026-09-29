"""Az alkalmazásikon (assets/icon.ico és icon.png) előállítása Pillow-val.

Futtatás: python packaging/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SIZE = 1024


def _gradient(size: int) -> Image.Image:
    start, end = (79, 124, 255), (155, 92, 255)
    grad = Image.new("RGB", (size, size))
    px = grad.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(start, end))
    return grad


def make_master() -> Image.Image:
    s = SIZE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    mask = Image.new("L", (s, s), 0)
    pad = s * 2 // 64
    ImageDraw.Draw(mask).rounded_rectangle((pad, pad, s - pad, s - pad), radius=s * 14 // 64, fill=255)
    img.paste(_gradient(s), (0, 0), mask)

    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 242)
    u = s / 64
    # nap
    d.ellipse((17 * u, 17 * u, 29 * u, 29 * u), fill=white)
    # hegyek
    d.polygon([(10 * u, 50 * u), (26 * u, 32 * u), (36 * u, 42 * u), (44 * u, 34 * u), (54 * u, 50 * u)], fill=white)
    return img


def main() -> None:
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    master = make_master()
    master.resize((256, 256), Image.Resampling.LANCZOS).save(assets / "icon.png", optimize=True)
    sizes = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(assets / "icon.ico", sizes=sizes)
    print("assets/icon.png, assets/icon.ico elkészült")


if __name__ == "__main__":
    main()
