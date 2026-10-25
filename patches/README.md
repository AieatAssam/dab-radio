# Native DL+ decoder extension

`welle-dlplus.patch` applies to welle.io commit `512558d1f8ac4c524d3c63e97510ea36c1bd7a70`.

The DL+ decoder/reassembler is adapted from [Opendigitalradio/DABlin](https://github.com/Opendigitalradio/dablin), `src/pad_decoder.{h,cpp}`, copyright 2015–2022 Stefan Pöschel, under GPL v3 or later as stated in those source files. Existing license notices remain in the patch/source. UTF-8 substring extraction uses the existing welle charset converter, with extra bounds checks on truncated commands. The patch exposes decoded typed tags through `/mux.json` without changing the audio decoder or MP3 encoder.

Build from the repository root using `./scripts/build-decoder.sh`. It checks the pinned revision, preserves unrelated local changes, applies the patch idempotently, builds at low priority with one job by default, and runs native DL+ tests. The systemd service uses the resulting `build/welle/welle-cli`; the original `/usr/local/bin/welle-cli` is untouched.

`tests/native_dlplus.cpp` checks valid CRC-tagged commands, title/artist extraction, Unicode character offsets, invalid CRCs, truncated tag commands, and label removal.
