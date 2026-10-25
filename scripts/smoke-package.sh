#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
package_path="${1:-}"
if [[ -z "${package_path}" ]]; then
    shopt -s nullglob
    packages=("${PROJECT_DIR}"/dist/dab-radio_*_$(dpkg --print-architecture).deb)
    shopt -u nullglob
    if (( ${#packages[@]} != 1 )); then
        echo "Pass the package path, or leave exactly one native architecture package in dist/." >&2
        exit 2
    fi
    package_path="${packages[0]}"
fi
[[ -f "${package_path}" ]] || { echo "Package not found: ${package_path}" >&2; exit 1; }
package_arch="$(dpkg-deb --field "${package_path}" Architecture)"
native_arch="$(dpkg --print-architecture)"
[[ "${package_arch}" == "${native_arch}" ]] || {
    echo "Package architecture ${package_arch} does not match host ${native_arch}." >&2
    exit 1
}
package_version="$(dpkg-deb --field "${package_path}" Version)"

tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/dab-radio-smoke.XXXXXX")"
trap 'rm -rf "${tmp_root}"' EXIT
dpkg-deb --extract "${package_path}" "${tmp_root}/root"
pkgroot="${tmp_root}/root/opt/dab-radio"
data_root="${tmp_root}/data"
mkdir -p "${data_root}"

for required in app.py metadata.py spi_client.py tokens.css web/index.html python bin/welle-cli; do
    [[ -e "${pkgroot}/${required}" ]] || { echo "Package is missing ${required}" >&2; exit 1; }
done
[[ -x "${pkgroot}/bin/welle-cli" ]] || { echo 'Packaged decoder is not executable.' >&2; exit 1; }

env PYTHONPATH="${pkgroot}/python:${pkgroot}" DAB_DATA_DIR="${data_root}" \
    DAB_MANAGE_RECEIVER=0 DAB_WELLE_CLI="${pkgroot}/bin/welle-cli" \
    DAB_EXPECTED_VERSION="${package_version}" python3 - "${pkgroot}" "${data_root}" <<'PY'
import asyncio
import os
import sys
from pathlib import Path

root, expected_data = map(Path, sys.argv[1:])
sys.path.insert(0, str(root))
import app
import httpx

assert app.DATA_DIR == expected_data, (app.DATA_DIR, expected_data)
assert app.APP_VERSION == os.environ["DAB_EXPECTED_VERSION"]
assert (root / "VERSION").read_text(encoding="utf-8").strip() == app.APP_VERSION
assert Path(os.environ["DAB_WELLE_CLI"]).is_file()
paths = {route.path for route in app.app.routes}
assert "/api/health" in paths
assert "/api/state" in paths
assert "/stream.mp3" in paths

async def smoke():
    transport = httpx.ASGITransport(app=app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://package-smoke") as client:
        response = await client.get("/api/health")
        assert response.status_code in (200, 503), response.text
        assert response.json().get("status")
        assert (await client.get("/api/state")).status_code == 200
        root_page = await client.get("/")
        assert root_page.status_code == 200
        assert "DAB Radio" in root_page.text
        assert (await client.get("/app.js")).status_code == 200

asyncio.run(smoke())
print(f"Packaged imports and API routes OK; state path: {app.DATA_DIR}")
PY

echo "Package extraction smoke check passed: ${package_path}"
