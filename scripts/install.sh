#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
UNIT_SOURCE="${PROJECT_DIR}/systemd/dab-radio.service"

if [[ "$(id -un)" != "aieat" ]]; then
    echo "Run this script as the aieat account, not with sudo." >&2
    exit 1
fi

for required_path in \
    "${PROJECT_DIR}/app.py" \
    "${PROJECT_DIR}/.venv/bin/uvicorn" \
    "${PROJECT_DIR}/build/welle/welle-cli" \
    "${UNIT_SOURCE}"; do
    if [[ ! -e "${required_path}" ]]; then
        echo "Required path is missing: ${required_path}" >&2
        exit 1
    fi
done

if [[ ! -x "${PROJECT_DIR}/.venv/bin/uvicorn" || ! -x "${PROJECT_DIR}/build/welle/welle-cli" ]]; then
    echo "uvicorn and welle-cli must be executable." >&2
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1 || ! command -v sudo >/dev/null 2>&1; then
    echo "systemctl and sudo are required to install the system service." >&2
    exit 1
fi

sudo install -m 0644 "${UNIT_SOURCE}" /etc/systemd/system/dab-radio.service
sudo systemctl daemon-reload
sudo systemctl enable dab-radio.service

echo "Installed and enabled dab-radio.service. Start it with ./scripts/start.sh."
