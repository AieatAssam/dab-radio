#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DECODER="${PROJECT_DIR}/build/welle/welle-cli"
REQ_FILE="${PROJECT_DIR}/requirements-runtime.txt"
VERSION_FILE="${PROJECT_DIR}/VERSION"
PACKAGE_VERSION="${1:-}"
REQUESTED_ARCH="${2:-}"

if [[ -z "${PACKAGE_VERSION}" ]]; then
    if [[ -f "${VERSION_FILE}" ]]; then
        PACKAGE_VERSION="$(<"${VERSION_FILE}")"
    else
        PACKAGE_VERSION=0.1.0
    fi
fi
if [[ ! "${PACKAGE_VERSION}" =~ ^[0-9][A-Za-z0-9.+:~-]*$ ]]; then
    echo "Invalid Debian package version: ${PACKAGE_VERSION}" >&2
    exit 2
fi

for command_name in dpkg-deb dpkg-query dpkg dpkg-shlibdeps readelf ldd readlink python3 tar; do
    command -v "${command_name}" >/dev/null || { echo "Missing build command: ${command_name}" >&2; exit 1; }
done
[[ -f "${REQ_FILE}" ]] || { echo "Missing ${REQ_FILE}; provide the runtime-only pip requirements." >&2; exit 1; }

if [[ ! -x "${DECODER}" ]]; then
    "${PROJECT_DIR}/scripts/build-decoder.sh"
fi
[[ -x "${DECODER}" ]] || { echo "Decoder build did not produce ${DECODER}" >&2; exit 1; }

native_arch="$(dpkg --print-architecture)"
package_arch="${REQUESTED_ARCH:-${native_arch}}"
case "${package_arch}" in
    arm64|amd64) ;;
    *) echo "Only native arm64 and amd64 builds are supported (host: ${package_arch})." >&2; exit 1 ;;
esac
if [[ "${package_arch}" != "${native_arch}" ]]; then
    echo "Refusing non-native build: requested ${package_arch}, host is ${native_arch}." >&2
    exit 1
fi
if [[ ! -r /etc/os-release ]] || ! . /etc/os-release || [[ "${ID:-}" != debian || "${VERSION_CODENAME:-}" != trixie ]]; then
    echo "Build packages on Debian 13 (Trixie) to match the declared runtime dependencies." >&2
    exit 1
fi
python_version="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
[[ "${python_version}" == 3.13 ]] || {
    echo "Runtime wheel staging requires Debian 13 system Python 3.13 (found ${python_version})." >&2
    exit 1
}
machine="$(readelf -h "${DECODER}" | awk -F: '/Machine:/ {gsub(/^[ \t]+/, "", $2); print $2}')"
case "${package_arch}:${machine}" in
    arm64:*AArch64*) ;;
    amd64:*X86-64*) ;;
    *) echo "Decoder architecture '${machine}' does not match native dpkg architecture '${package_arch}'." >&2; exit 1 ;;
esac

missing_libs="$(ldd "${DECODER}" | awk '/not found/ {print $1}')"
if [[ -n "${missing_libs}" ]]; then
    echo "Decoder has unresolved runtime libraries: ${missing_libs}" >&2
    exit 1
fi
while IFS= read -r library; do
    [[ -n "${library}" ]] || continue
    library_real="$(readlink -f "${library}")"
    dpkg-query -S "${library_real}" >/dev/null 2>&1 || {
        echo "No installed Debian package owns linked decoder library ${library}." >&2
        exit 1
    }
done < <(ldd "${DECODER}" | sed -nE 's/.*=> (\/[^ ]+).*/\1/p')

tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/dab-radio-package.XXXXXX")"
trap 'rm -rf "${tmp_root}"' EXIT
stage="${tmp_root}/root"
shlib_work="${tmp_root}/shlib-work"
mkdir -p "${stage}/opt/dab-radio" "${stage}/opt/dab-radio/bin" \
    "${stage}/opt/dab-radio/python" "${stage}/usr/share/doc/dab-radio" \
    "${stage}/DEBIAN" "${PROJECT_DIR}/dist" "${shlib_work}/debian"

cat > "${shlib_work}/debian/control" <<'EOF'
Source: dab-radio
Section: sound
Priority: optional
Maintainer: DAB Radio maintainers
Standards-Version: 4.7.0

Package: dab-radio
Architecture: any
Description: DAB/DAB+ network audio player for RTL-SDR
EOF
shlib_dependencies="$(cd "${shlib_work}" && dpkg-shlibdeps -O -e"${DECODER}" \
    | sed -n 's/^shlibs:Depends=//p')"
[[ -n "${shlib_dependencies}" ]] || { echo "dpkg-shlibdeps returned no decoder dependencies." >&2; exit 1; }

for app_file in app.py metadata.py spi_client.py tokens.css; do
    install -m 0644 "${PROJECT_DIR}/${app_file}" "${stage}/opt/dab-radio/${app_file}"
done
printf '%s\n' "${PACKAGE_VERSION}" > "${stage}/opt/dab-radio/VERSION"
chmod 0644 "${stage}/opt/dab-radio/VERSION"
cp -a "${PROJECT_DIR}/web" "${stage}/opt/dab-radio/web"
install -m 0755 "${DECODER}" "${stage}/opt/dab-radio/bin/welle-cli"
install -m 0644 "${PROJECT_DIR}/packaging/root/DEBIAN/control" "${stage}/DEBIAN/control"
sed -i "s/^Architecture: .*/Architecture: ${package_arch}/" "${stage}/DEBIAN/control"
sed -i "s/^Version: .*/Version: ${PACKAGE_VERSION}/" "${stage}/DEBIAN/control"
sed -i "/^Depends:/ s/$/, ${shlib_dependencies}/" "${stage}/DEBIAN/control"
for maint_script in postinst prerm conffiles; do
    install -m 0644 "${PROJECT_DIR}/packaging/root/DEBIAN/${maint_script}" "${stage}/DEBIAN/${maint_script}"
done
chmod 0755 "${stage}/DEBIAN/postinst" "${stage}/DEBIAN/prerm"
cp -a "${PROJECT_DIR}/packaging/root/etc" "${stage}/etc"
cp -a "${PROJECT_DIR}/packaging/root/usr/lib" "${stage}/usr/lib"
install -m 0644 "${PROJECT_DIR}/LICENSE" "${stage}/usr/share/doc/dab-radio/LICENSE"
install -m 0644 "${PROJECT_DIR}/README.md" "${stage}/usr/share/doc/dab-radio/README.md"
install -m 0644 "${PROJECT_DIR}/THIRD_PARTY_NOTICES.md" "${stage}/usr/share/doc/dab-radio/THIRD_PARTY_NOTICES.md"
cp -a "${PROJECT_DIR}/licenses" "${stage}/usr/share/doc/dab-radio/licenses"
cp -a "${PROJECT_DIR}/docs" "${stage}/usr/share/doc/dab-radio/docs"
mkdir -p "${stage}/usr/share/doc/dab-radio/patches"
install -m 0644 "${PROJECT_DIR}/patches/README.md" "${stage}/usr/share/doc/dab-radio/patches/README.md"
mkdir -p "${stage}/usr/share/doc/dab-radio/.agents/skills/playwright"
install -m 0644 "${PROJECT_DIR}/.agents/skills/playwright/NOTICE.txt" \
    "${stage}/usr/share/doc/dab-radio/.agents/skills/playwright/NOTICE.txt"
install -m 0644 "${PROJECT_DIR}/.agents/skills/playwright/LICENSE.txt" \
    "${stage}/usr/share/doc/dab-radio/.agents/skills/playwright/LICENSE.txt"
install -m 0644 "${PROJECT_DIR}/packaging/root/usr/share/doc/dab-radio/BUILDING-decoder.md" \
    "${stage}/usr/share/doc/dab-radio/BUILDING-decoder.md"

python3 -m pip install --target "${stage}/opt/dab-radio/python" \
    --only-binary=:all: --no-compile -r "${REQ_FILE}"

source_tmp="${tmp_root}/decoder-source"
mkdir -p "${source_tmp}"
tar -C "${PROJECT_DIR}/vendor" --exclude='.git' -cf - welle.io | tar -C "${source_tmp}" -xf -
mkdir -p "${source_tmp}/patches" "${source_tmp}/tests" "${source_tmp}/licenses"
install -m 0644 "${PROJECT_DIR}/patches/welle-dlplus.patch" "${source_tmp}/patches/welle-dlplus.patch"
install -m 0644 "${PROJECT_DIR}/tests/native_dlplus.cpp" "${source_tmp}/tests/native_dlplus.cpp"
install -m 0644 "${PROJECT_DIR}/licenses/welle-io-COPYING" "${source_tmp}/licenses/welle-io-COPYING"
install -m 0644 "${PROJECT_DIR}/licenses/GPL-3.txt" "${source_tmp}/licenses/GPL-3.txt"
install -m 0644 "${PROJECT_DIR}/packaging/root/usr/share/doc/dab-radio/BUILDING-decoder.md" "${source_tmp}/BUILDING.md"
source_epoch="${SOURCE_DATE_EPOCH:-$(git -C "${PROJECT_DIR}" log -1 --format=%ct 2>/dev/null || printf '0')}"
[[ "${source_epoch}" =~ ^[0-9]+$ ]] || { echo "Invalid SOURCE_DATE_EPOCH: ${source_epoch}" >&2; exit 1; }
tar -C "${source_tmp}" --sort=name --mtime="@${source_epoch}" --owner=0 --group=0 \
    --numeric-owner --format=gnu --exclude='.git' -cf - . \
    | gzip -n > "${PROJECT_DIR}/dist/dab-radio_${PACKAGE_VERSION}_decoder-source.tar.gz"

deb_path="${PROJECT_DIR}/dist/dab-radio_${PACKAGE_VERSION}_${package_arch}.deb"
dpkg-deb --build --root-owner-group -Zgzip "${stage}" "${deb_path}"
echo "Built ${deb_path}"
echo "Built ${PROJECT_DIR}/dist/dab-radio_${PACKAGE_VERSION}_decoder-source.tar.gz"
