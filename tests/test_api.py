import asyncio

import httpx
import pytest

import app as backend


def request(method: str, path: str, **kwargs) -> httpx.Response:
    async def send() -> httpx.Response:
        # ASGITransport does not run the lifespan, so API tests cannot start SDR hardware.
        transport = httpx.ASGITransport(app=backend.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def test_tune_rejects_unknown_channel() -> None:
    response = request("POST", "/api/tune", json={"channel": "99Z"})

    assert response.status_code == 422
    assert "valid DAB Band III channel" in response.json()["detail"]


@pytest.mark.parametrize("service", [0, "0", "not-a-service"])
def test_tune_rejects_invalid_service_id(service: int | str) -> None:
    response = request("POST", "/api/tune", json={"channel": "12B", "service": service})

    assert response.status_code == 422
    assert "non-zero 32-bit hexadecimal" in response.json()["detail"]


def test_tune_rejects_unknown_request_fields() -> None:
    response = request("POST", "/api/tune", json={"channel": "12B", "volume": 0.5})

    assert response.status_code == 422


def test_state_keeps_unavailable_receiver_fields_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver = backend.Receiver()
    receiver.manage = False
    receiver.status = "starting"
    receiver.raw = None
    receiver.current_channel = None
    receiver.last_mux_at = None
    receiver.last_error = None
    receiver.selected = {"channel": "12B", "service": None}
    receiver.cache = {
        "version": 1,
        "selected": {"channel": "12B", "service": None},
        "channels": {},
    }
    monkeypatch.setattr(backend, "receiver", receiver)

    response = request("GET", "/api/state")

    assert response.status_code == 200
    state = response.json()
    assert state["selected"] == {"channel": "12B", "service": None}
    assert state["metadata"] is None
    assert state["receiver"]["channel"] is None
    assert state["receiver"]["last_update"] is None
    assert state["receiver"]["error"] is None
    assert state["receiver"]["hardware"] == {"name": None, "gain": None}
    assert state["receiver"]["software"] == {"name": None, "version": None}
    assert state["stats"]["stream_last_error"] is None
    assert all(channel["snr"] is None for channel in state["channels"])


def test_station_schema_separates_delivery_and_broadcast_codecs() -> None:
    service = {
        "sid": "0x1234",
        "components": [
            {
                "transportmode": "audio",
                "ascty": "DAB+",
                "subchannel": {"bitrate": 128},
            }
        ],
        "url_mp3": "/stream/0x1234",
    }

    station = backend._station_from_service(service, "12B", live=True)

    assert station is not None
    assert station["codec"] == "MP3"
    assert station["source_codec"] == "DAB+"
