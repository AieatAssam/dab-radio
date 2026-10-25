# Third-party notices

DAB Radio includes and uses third-party software and typefaces. Their licenses apply to those components; they do not replace the project license in `LICENSE` or relicense independently authored project files.

## Project code and decoder boundary

The Python service and browser application are the project’s own work, copyright © 2026 Aieat Assam, and are offered under the MIT License in the repository’s `LICENSE`. The separately built `welle-cli` decoder is based on [welle.io](https://github.com/AlbrechtL/welle.io), whose source is supplied in `vendor/welle.io/` under GPL-2.0-or-later (`licenses/welle-io-COPYING`). This repository also applies `patches/welle-dlplus.patch` to that source; the patch remains part of the GPL-licensed decoder work and is not separately relicensed under the app’s MIT license. DABlin-derived PAD code and the DL+ extension are GPL-3.0-or-later; the combined patched decoder therefore retains GPLv3-or-later terms. It is not covered by the application’s MIT license. The Linux build links system FAAD2 and mpg123 libraries rather than compiling their bundled Android sources. Relevant texts and package copyright records are in `licenses/`.

The local Hallmark skill at `.agents/skills/hallmark/` corresponds to [Hallmark](https://github.com/Nutlope/hallmark), published under the MIT License; the included skill snapshot identifies version 1.1.0, and the upstream repository supplies its MIT license text. A copy is retained at [`licenses/hallmark-MIT.txt`](licenses/hallmark-MIT.txt). Hallmark provides anti-AI-slop design guidance and UI quality checks; it is development/design tooling, not a runtime UI library or generic design theme. Playwright, if installed or used for browser checks, is Apache-2.0 development tooling, not a runtime dependency.

Station logos, images, and broadcast text/content may be supplied by broadcasters or other rights holders. They are not relicensed by this project’s MIT license.

## Python dependencies

Versions below are the installed environment versions; runtime direct dependencies are declared in `requirements-runtime.txt`. Uvicorn’s `standard` extra brings optional server dependencies. Pytest and its dependencies are for tests/development. License texts for key dependencies are preserved under `licenses/python/`.

| Component | Version | License |
| --- | ---: | --- |
| FastAPI | 0.162.0 | MIT |
| Uvicorn | 0.54.0 | BSD-3-Clause |
| HTTPX | 0.28.1 | BSD-3-Clause |
| Pydantic | 2.14.1 | MIT |
| pydantic-core | 2.50.1 | MIT |
| Starlette | 1.10.0 | BSD-3-Clause |
| defusedxml | 0.7.1 | PSF License |
| dnspython | 2.9.0 | ISC |
| pytest | 9.1.1 | MIT |
| uvloop | 0.23.0 | MIT; Apache-2.0 alternative terms are also included upstream |
| httptools | 0.9.0 | MIT; includes separately licensed vendored http-parser and llhttp components |
| websockets | 17.3 | BSD-3-Clause |
| watchfiles | 1.3.0 | MIT |
| PyYAML | 6.0.3 | MIT |
| anyio | 4.15.1 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| certifi | 2026.10.23 | MPL-2.0 |
| iniconfig | 2.3.1 | MIT |
| packaging | 26.3 | Apache-2.0 or BSD-2-Clause |
| pluggy | 1.7.0 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |

This is the direct set and important transitive packages present in the project’s `.venv`; it is not an exhaustive inventory of every operating-system package or optional system library. Python license notices were copied from the installed distribution metadata where available. The `dnspython` installed distribution did not include a license text, so its declared upstream ISC license is identified above without an invented local license file.

## Decoder, native libraries, and system packages

The current Linux welle.io build uses system-provided FAAD2, mpg123, RTL-SDR, FFTW, libusb, LAME, and ALSA libraries; the installed `welle-cli` links to these system libraries. The welle.io CMake configuration compiles bundled FAAD2 and mpg123 source only in its Android branch. The source tree includes DABlin-derived decoder code by Stefan Pöschel under GPL-3.0-or-later, which is also the licensing basis for the DL+ patch in `patches/welle-dlplus.patch`. Debian copyright records below are retained as source-package notices and document mixed licensing where applicable.

| Component | License summary | Notice |
| --- | --- | --- |
| welle.io | GPL-2.0-or-later | [`licenses/welle-io-COPYING`](licenses/welle-io-COPYING) |
| DABlin-derived decoder code and DL+ patch | Stefan Pöschel, copyright 2015–2022; GPL-3.0-or-later | [DABlin source](https://github.com/Opendigitalradio/dablin), [`licenses/GPL-3.txt`](licenses/GPL-3.txt); original license notices appear in `vendor/welle.io/src/backend/` |
| FAAD2 | GPL-2.0-or-later; some frontend files GPL-3.0-or-later | [`licenses/faad2-copyright.txt`](licenses/faad2-copyright.txt), [`licenses/GPL-3.txt`](licenses/GPL-3.txt) |
| mpg123 | LGPL-2.1 | [`licenses/mpg123-LGPL-2.1.txt`](licenses/mpg123-LGPL-2.1.txt) |
| FFTW | GPL-2.0-or-later | [`licenses/fftw-copyright.txt`](licenses/fftw-copyright.txt) |
| RTL-SDR | GPL-2.0-or-later and GPL-3.0-or-later portions | [`licenses/rtl-sdr-copyright.txt`](licenses/rtl-sdr-copyright.txt) |
| libusb | LGPL-2.1-or-later | [`licenses/libusb-copyright.txt`](licenses/libusb-copyright.txt) |
| LAME | LGPL-2-or-later for most files; exceptions are recorded in its notice | [`licenses/lame-copyright.txt`](licenses/lame-copyright.txt) |
| ALSA | LGPL-2.1-or-later for the library | System package; license text is supplied by the operating system |

## Fonts

The bundled IBM Plex Sans, IBM Plex Mono, and Space Grotesk font files are under the SIL Open Font License 1.1. Their notices are retained beside the font assets in `web/fonts/`; copies are also in `licenses/fonts/`. The font files remain under OFL terms and are not relicensed under MIT.
