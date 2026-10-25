"""Packaging must keep writable state outside the installed, read-only app."""
import os
from pathlib import Path
import subprocess
import sys


def test_data_directory_environment_override_is_used(tmp_path):
    state = tmp_path / 'package-state'
    env = dict(os.environ, DAB_DATA_DIR=str(state), DAB_MANAGE_RECEIVER='0')
    result = subprocess.run(
        [sys.executable, '-c', 'import app; print(app.DATA_DIR); print(app.STATIONS_FILE); print(app.receiver.spi.path); print(app.APP_VERSION)'],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, check=True,
    )
    lines = result.stdout.strip().splitlines()
    assert lines[:3] == [str(state), str(state / 'stations.json'), str(state / 'spi-cache.json')]
    assert lines[3] == (Path(__file__).resolve().parents[1] / 'VERSION').read_text().strip()
