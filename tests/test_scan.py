import asyncio
from types import SimpleNamespace

import pytest

import app as backend
from tests.test_api import request


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def raise_for_status(self):
        pass

    def json(self):
        return self.value


def test_adaptive_acquisition_waits_for_stable_service_labels(monkeypatch):
    receiver = backend.Receiver()
    clock = [0.0]

    async def sleep(seconds):
        clock[0] += seconds

    calls = [0]
    async def get(_url):
        calls[0] += 1
        label = "One" if calls[0] < 8 else "Stable"
        return FakeResponse({"services": [{"sid": "0x1234", "label": label}]})

    monkeypatch.setattr(backend.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(backend.asyncio, "sleep", sleep)
    receiver.http = SimpleNamespace(get=get)
    async def run():
        result, elapsed = await receiver._acquire_mux("12B")
        assert result["services"][0]["label"] == "Stable"
        assert elapsed >= backend.SCAN_ACQUISITION_MIN_SECONDS
    asyncio.run(run())


def test_failed_scan_preserves_cached_services_and_marks_stale(monkeypatch):
    receiver = backend.Receiver()
    receiver.current_channel = "12B"
    receiver.selected = {"channel": "12B", "service": None}
    prior = {"services": [{"sid": "0x1234", "label": "Cached"}], "scanned_at": "old"}
    receiver.cache = {"version": 1, "selected": dict(receiver.selected), "channels": {"5A": prior}}
    writes = []
    monkeypatch.setattr(backend, "_write_cache", lambda cache: writes.append(cache.copy()))

    async def post_channel(channel):
        receiver.current_channel = channel

    async def acquire(_channel):
        return None, 3.0

    async def run():
        receiver._post_channel = post_channel
        receiver._acquire_mux = acquire
        await receiver._scan_worker("12B", None)

    asyncio.run(run())
    entry = receiver.cache["channels"]["5A"]
    assert entry["services"] == prior["services"]
    assert entry["stale"] is True
    assert entry["scanned_at"] != "old"
    assert receiver.scan["elapsed_seconds"] is not None


def test_cancel_scan_http_endpoint(monkeypatch):
    receiver = backend.Receiver()
    async def cancel_scan():
        receiver.scan.update(active=False, cancelled=True)
        return {"ok": True}
    receiver.cancel_scan = cancel_scan
    monkeypatch.setattr(backend, "receiver", receiver)
    response = request("POST", "/api/scan/cancel")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.parametrize('value,expected', [
    ({'services': [], 'ensemble': {'id': '0x0000'}, 'demodulator': {'snr': 0}}, 3.0),
    ({'services': [], 'ensemble': {'id': '0xc183'}, 'demodulator': {'snr': 5}}, 30.0),
    ({'services': [{'sid': '0x1234', 'label': {'label': ''}}], 'ensemble': {'id': '0xc183'}, 'demodulator': {'snr': 20}}, 15.0),
    ({'services': [{'sid': '0x1234', 'label': {'label': 'Named'}}], 'ensemble': {'id': '0xc183'}, 'demodulator': {'snr': 20}}, 8.0),
])
def test_scan_waits_longer_for_weak_or_incomplete_ensembles(monkeypatch, value, expected):
    receiver = backend.Receiver()
    clock = [0.0]
    async def sleep(seconds):
        clock[0] += seconds
    async def get(_url):
        return FakeResponse(value)
    monkeypatch.setattr(backend.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(backend.asyncio, 'sleep', sleep)
    receiver.http = SimpleNamespace(get=get)
    async def run():
        _, elapsed = await receiver._acquire_mux('11C')
        assert elapsed == expected
    asyncio.run(run())
