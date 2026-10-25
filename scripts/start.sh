#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

if [[ "$(id -un)" != "aieat" ]]; then
    echo "Run this script as the aieat account, not with sudo." >&2
    exit 1
fi

if [[ ! -f "${PROJECT_DIR}/app.py" || ! -x "${PROJECT_DIR}/.venv/bin/uvicorn" ]]; then
    echo "app.py and the project's .venv/bin/uvicorn must exist before starting." >&2
    exit 1
fi

if sudo systemctl is-active --quiet dab-radio.service; then
    sudo systemctl --no-pager --full status dab-radio.service
    exit 0
fi

if command -v ss >/dev/null 2>&1; then
    for listener_port in 8090 7979; do
        port_listener="$(ss -H -ltn "sport = :${listener_port}")"
        if [[ -n "${port_listener}" ]]; then
            echo "Port ${listener_port} is already listening; leaving the existing process untouched." >&2
            echo "${port_listener}" >&2
            exit 1
        fi
    done
fi

sudo systemctl start dab-radio.service
sudo systemctl --no-pager --full status dab-radio.service
