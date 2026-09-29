# Harmadik féltől származó összetevők

A WebKép Konverter futtatható állományai az alábbi nyílt forrású könyvtárakat tartalmazzák.
Mindegyik a saját licence alatt áll; a licencszövegek a hivatkozott projektoldalakon érhetők el.

| Összetevő | Felhasználás | Licenc |
|---|---|---|
| [Python](https://www.python.org/) | futtatókörnyezet | PSF License |
| [Pillow](https://python-pillow.github.io/) | képbeolvasás és -feldolgozás | MIT-CMU (HPND) |
| [libwebp](https://chromium.googlesource.com/webm/libwebp) | WebP kódolás (a Pillow része) | BSD-3-Clause |
| [libavif](https://github.com/AOMediaCodec/libavif) | AVIF konténer (a Pillow része) | BSD-2-Clause |
| [libaom](https://aomedia.googlesource.com/aom/) | AV1/AVIF kódoló (a Pillow része) | BSD-2-Clause + AOM Patent License |
| [dav1d](https://code.videolan.org/videolan/dav1d) | AV1/AVIF dekódoló (a Pillow része) | BSD-2-Clause |
| [Little CMS](https://www.littlecms.com/) | színprofil-kezelés (a Pillow része) | MIT |
| libjpeg-turbo, libpng, zlib, libtiff, OpenJPEG, FreeType | formátumtámogatás (a Pillow része) | BSD-stílusú / IJG / zlib licencek |
| [Qt 6](https://www.qt.io/) és [PySide6](https://doc.qt.io/qtforpython/) | grafikus felület | LGPL-3.0 |
| [pi-heif](https://github.com/bigcat88/pillow_heif) | HEIC/HEIF beolvasás | BSD-3-Clause |
| [libheif](https://github.com/strukturag/libheif) | HEIF konténer (a pi-heif része) | LGPL-3.0 |
| [libde265](https://github.com/strukturag/libde265) | HEVC dekódoló (a pi-heif része) | LGPL-3.0 |

## LGPL megjegyzés

A Qt/PySide6, a libheif és a libde265 LGPL-3.0 licencű, dinamikusan betöltött könyvtárak.
A telepítős és a mappás (`WebKepKonverter\`) változatban ezek külön DLL-fájlként szerepelnek,
így a felhasználó lecserélheti őket egy kompatibilis, módosított változatra.
A programhoz tartozó forráskód és a build szkriptek ebben a repositoryban érhetők el, így
a hordozható (egyfájlos) változat is újraépíthető módosított könyvtárakkal.

A HEIC támogatáshoz szándékosan a csak dekódolásra képes `pi-heif` csomag szerepel
(a `pillow-heif` GPL licencű x265 kódolót is tartalmazna).
