#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DECODER_REVISION=512558d1f8ac4c524d3c63e97510ea36c1bd7a70
DECODER_SOURCE="${PROJECT_DIR}/vendor/welle.io"
if [[ ! -d "${DECODER_SOURCE}/.git" ]]; then
    mkdir -p "${PROJECT_DIR}/vendor"
    git clone https://github.com/AlbrechtL/welle.io.git "${DECODER_SOURCE}"
    git -C "${DECODER_SOURCE}" checkout "${DECODER_REVISION}"
fi
if [[ "$(git -C "${DECODER_SOURCE}" rev-parse HEAD)" != "${DECODER_REVISION}" ]]; then
    echo 'Decoder checkout differs from the pinned revision; preserving it.' >&2
    exit 1
fi
if git -C "${DECODER_SOURCE}" apply --check "${PROJECT_DIR}/patches/welle-dlplus.patch" 2>/dev/null; then
    git -C "${DECODER_SOURCE}" apply "${PROJECT_DIR}/patches/welle-dlplus.patch"
elif ! git -C "${DECODER_SOURCE}" apply --reverse --check "${PROJECT_DIR}/patches/welle-dlplus.patch" 2>/dev/null; then
    echo 'Decoder patch conflicts with existing changes; preserving them.' >&2
    exit 1
fi
cmake -S "${DECODER_SOURCE}" -B "${PROJECT_DIR}/build/welle" -DBUILD_WELLE_IO=OFF -DBUILD_WELLE_CLI=ON -DRTLSDR=ON -DCMAKE_BUILD_TYPE=Release
nice -n 15 cmake --build "${PROJECT_DIR}/build/welle" --parallel "${DAB_BUILD_JOBS:-1}"
nice -n 15 g++ -std=c++14 -O1 -ffunction-sections -fdata-sections -I"${DECODER_SOURCE}/src/backend" "${PROJECT_DIR}/tests/native_dlplus.cpp" "${DECODER_SOURCE}/src/backend/pad_decoder.cpp" "${DECODER_SOURCE}/src/backend/tools.cpp" "${DECODER_SOURCE}/src/backend/charsets.cpp" -Wl,--gc-sections -o "${PROJECT_DIR}/build/test-dlplus"
"${PROJECT_DIR}/build/test-dlplus"
