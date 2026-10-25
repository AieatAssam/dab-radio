# Building the bundled decoder from source

This archive contains the complete patched welle.io source used to build the
`welle-cli` binary shipped in the matching DAB Radio package. It targets
Debian 13 (Trixie) on the build machine's native architecture.

Install the native build tools and decoder development libraries:

```sh
sudo apt install build-essential cmake git pkg-config libasound2-dev \
  libfaad-dev libfftw3-dev libmpg123-dev libmp3lame-dev librtlsdr-dev \
  libusb-1.0-0-dev xxd
```

The source tree is already patched. From the directory containing `welle.io/`:

```sh
cmake -S welle.io -B build -DBUILD_WELLE_IO=OFF -DBUILD_WELLE_CLI=ON \
  -DRTLSDR=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
```

The resulting executable is `build/welle-cli`. Build on the same architecture
as the target package; cross compilation is not performed by the package
builder. `patches/welle-dlplus.patch` is supplied as the corresponding source
patch, and `tests/native_dlplus.cpp` is the project's native decoder fixture.
