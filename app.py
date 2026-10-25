"""FastAPI bridge between the web player and welle-cli."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from spi_client import SPIClient
from metadata import dlplus_fields


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
VERSION_FILE = BASE_DIR / "VERSION"
APP_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.is_file() else "0.1.0"
DATA_DIR = Path(os.environ.get("DAB_DATA_DIR", str(BASE_DIR / "data")))
STATIONS_FILE = DATA_DIR / "stations.json"
LOG_FILE = DATA_DIR / "receiver.log"
TOKENS_FILE = BASE_DIR / "tokens.css"
RECEIVER_HOST = os.getenv("DAB_RECEIVER_HOST", "127.0.0.1")
RECEIVER_PORT = int(os.getenv("DAB_RECEIVER_PORT", "7979"))
RECEIVER_ROOT = f"http://{RECEIVER_HOST}:{RECEIVER_PORT}"
DEFAULT_CHANNEL = "12B"
SCAN_NO_SIGNAL_MIN_SECONDS = 3.0
SCAN_ACQUISITION_MIN_SECONDS = 8.0
SCAN_LABEL_STABLE_SECONDS = 3.0
SCAN_MAX_SECONDS = 15.0
SCAN_WEAK_MAX_SECONDS = 30.0
SCAN_POLL_SECONDS = 0.5
STREAM_QUEUE_DEPTH = 32
STREAM_CHUNK_SIZE = 4 * 1024
MAX_RECEIVER_LOG_BYTES = 2 * 1024 * 1024
RECEIVER_LOG_BACKUPS = 3

# ETSI Band III channel centres in MHz. 13D is the one non-uniform step.
CHANNEL_FREQUENCIES: dict[str, float] = {
    "5A": 174.928, "5B": 176.640, "5C": 178.352, "5D": 180.064,
    "6A": 181.936, "6B": 183.648, "6C": 185.360, "6D": 187.072,
    "7A": 188.928, "7B": 190.640, "7C": 192.352, "7D": 194.064,
    "8A": 195.936, "8B": 197.648, "8C": 199.360, "8D": 201.072,
    "9A": 202.928, "9B": 204.640, "9C": 206.352, "9D": 208.064,
    "10A": 209.936, "10B": 211.648, "10C": 213.360, "10D": 215.072,
    "11A": 216.928, "11B": 218.640, "11C": 220.352, "11D": 222.064,
    "12A": 223.936, "12B": 225.648, "12C": 227.360, "12D": 229.072,
    "13A": 230.784, "13B": 232.496, "13C": 234.208,
    "13D": 235.776, "13E": 237.488, "13F": 239.200,
}

logger = logging.getLogger("dab")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _configure_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)


def _read_cache() -> dict[str, Any]:
    try:
        value = json.loads(STATIONS_FILE.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("channels"), dict):
            value.setdefault("version", 1)
            value.setdefault("selected", {"channel": DEFAULT_CHANNEL, "service": None})
            return value
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("Unable to read station cache: %s", exc)
    return {"version": 1, "selected": {"channel": DEFAULT_CHANNEL, "service": None}, "channels": {}}


def _write_cache(cache: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATIONS_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(STATIONS_FILE)


def canonical_channel(value: str) -> str:
    channel = value.strip().upper()
    if channel not in CHANNEL_FREQUENCIES:
        raise HTTPException(status_code=422, detail="channel must be a valid DAB Band III channel (5A–13F)")
    return channel


def canonical_sid(value: str | int) -> str:
    try:
        if isinstance(value, bool):
            raise ValueError
        if isinstance(value, int):
            number = value
        else:
            text = value.strip().lower()
            if text.startswith("0x"):
                digits = text[2:]
                if not 1 <= len(digits) <= 8 or not re.fullmatch(r"[0-9a-f]+", digits):
                    raise ValueError
                number = int(digits, 16)
            elif re.fullmatch(r"[0-9a-f]{1,8}", text):
                number = int(text, 16)
            else:
                raise ValueError
        if not 0 < number <= 0xFFFFFFFF:
            raise ValueError
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="service must be a non-zero 32-bit hexadecimal DAB service ID")
    return f"0x{number:04x}"


def _raw_sid(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text.startswith("0x"):
        try:
            return f"0x{int(text, 16):04x}"
        except ValueError:
            return None
    try:
        return f"0x{int(text, 16):04x}"
    except ValueError:
        return None


def _audio_components(service: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for component in service.get("components", []) or []:
        if not isinstance(component, dict) or component.get("transportmode") != "audio":
            continue
        result.append(component)
    return result


def _station_from_service(service: dict[str, Any], channel: str, live: bool) -> dict[str, Any] | None:
    sid = _raw_sid(service.get("sid"))
    if sid is None:
        return None
    components = _audio_components(service)
    if not components:
        return None
    audio = next((c for c in components if (c.get("subchannel") or {}).get("bitrate")), components[0] if components else {})
    subchannel = audio.get("subchannel") or {}
    ascty = audio.get("ascty")
    raw_mode = service.get("mode")
    sample_rate = service.get("samplerate")
    if not isinstance(sample_rate, (int, float)) or sample_rate <= 0:
        sample_rate = None
    bitrate = subchannel.get("bitrate")
    if not isinstance(bitrate, (int, float)) or bitrate <= 0:
        bitrate = None
    label_info = service.get("label") if isinstance(service.get("label"), dict) else {}
    label = str(label_info.get("label") or "").strip()
    name = label or sid
    # welle-cli emits MP3 for its web stream. Keep the received DAB codec separately.
    source_codec = ascty if isinstance(ascty, str) else None
    dls = service.get("dls") if isinstance(service.get("dls"), dict) else {}
    return {
        "id": sid,
        "sid": sid,
        "name": name,
        "label": label or name,
        "short_label": str(label_info.get("shortlabel") or "").strip() or None,
        "channel": channel,
        "codec": "MP3" if service.get("url_mp3") or components else None,
        "source_codec": source_codec,
        "bitrate": int(bitrate) if bitrate is not None else None,
        "sample_rate": int(sample_rate) if sample_rate is not None else None,
        "mode": raw_mode if isinstance(raw_mode, str) and raw_mode.strip() else None,
        "language": service.get("languagestring") or None,
        "pty": service.get("ptystring") or None,
        "program_type": service.get("programType"),
        "dls": service.get("dls"),
        "radio_text": dls.get("label") or None,
        "mot": service.get("mot"),
        "components": service.get("components", []),
        "errors": service.get("errorcounters"),
        "stream_url": "/stream.mp3",
        "slide_url": "/api/slide",
        "live": live,
    }


class TuneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str = Field(min_length=2, max_length=3)
    service: str | int | None = None


@dataclass(eq=False)
class StreamSubscriber:
    queue: asyncio.Queue[bytes | None] = field(default_factory=lambda: asyncio.Queue(STREAM_QUEUE_DEPTH))
    closed: bool = False


class SharedAudioStream:
    """One welle audio connection fans out to bounded per-browser queues."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.subscribers: set[StreamSubscriber] = set()
        self.upstream_task: asyncio.Task[None] | None = None
        self.sid: str | None = None
        self.bytes_streamed = 0
        self.reconnects = 0
        self.errors = 0
        self.last_error: str | None = None
        self.slow_disconnects = 0

    async def subscribe(self, sid: str) -> StreamSubscriber:
        async with self.lock:
            if self.sid != sid and self.subscribers:
                old = list(self.subscribers)
                self.subscribers.clear()
                for subscriber in old:
                    self._finish(subscriber)
                task = self.upstream_task
                self.upstream_task = None
                if task:
                    task.cancel()
            subscriber = StreamSubscriber()
            self.subscribers.add(subscriber)
            self.sid = sid
            if self.upstream_task is None or self.upstream_task.done():
                self.upstream_task = asyncio.create_task(self._pump(sid), name=f"welle-stream-{sid}")
            return subscriber

    @staticmethod
    def _finish(subscriber: StreamSubscriber) -> None:
        if subscriber.closed:
            return
        subscriber.closed = True
        while not subscriber.queue.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                subscriber.queue.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            subscriber.queue.put_nowait(None)

    async def unsubscribe(self, subscriber: StreamSubscriber) -> None:
        task: asyncio.Task[None] | None = None
        async with self.lock:
            self.subscribers.discard(subscriber)
            self._finish(subscriber)
            if not self.subscribers and self.upstream_task:
                task = self.upstream_task
                self.upstream_task = None
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def stop_all(self) -> None:
        async with self.lock:
            subscribers = list(self.subscribers)
            self.subscribers.clear()
            task = self.upstream_task
            self.upstream_task = None
            for subscriber in subscribers:
                self._finish(subscriber)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _pump(self, sid: str) -> None:
        for attempt in range(5):
            try:
                async with receiver.http.stream("GET", f"{RECEIVER_ROOT}/stream/{sid}") as response:
                    if response.status_code != 200:
                        raise RuntimeError(f"welle audio endpoint returned HTTP {response.status_code}")
                    async for chunk in response.aiter_bytes(STREAM_CHUNK_SIZE):
                        if not chunk:
                            continue
                        self.bytes_streamed += len(chunk)
                        async with self.lock:
                            for subscriber in list(self.subscribers):
                                if subscriber.closed:
                                    continue
                                try:
                                    subscriber.queue.put_nowait(chunk)
                                except asyncio.QueueFull:
                                    self.slow_disconnects += 1
                                    self.subscribers.discard(subscriber)
                                    self._finish(subscriber)
                            if not self.subscribers:
                                return
                raise RuntimeError("welle audio connection ended")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # upstream/network failures are surfaced and retried a bounded number of times
                self.errors += 1
                self.last_error = str(exc)
                logger.warning("Audio upstream attempt %d failed: %s", attempt + 1, exc)
                if attempt >= 4:
                    break
                self.reconnects += 1
                await asyncio.sleep(min(0.5 * (2**attempt), 4.0))
        async with self.lock:
            for subscriber in list(self.subscribers):
                self._finish(subscriber)
            self.subscribers.clear()
            if self.upstream_task is asyncio.current_task():
                self.upstream_task = None


class Receiver:
    def __init__(self) -> None:
        self.http: httpx.AsyncClient
        self.cache = _read_cache()
        selected = self.cache.get("selected") or {}
        channel = selected.get("channel", DEFAULT_CHANNEL)
        if channel not in CHANNEL_FREQUENCIES:
            channel = DEFAULT_CHANNEL
        self.selected: dict[str, Any] = {"channel": channel, "service": _raw_sid(selected.get("service"))}
        self.raw: dict[str, Any] | None = None
        self.current_channel: str | None = None
        self.status = "starting"
        self.last_error: str | None = None
        self.last_mux_at: str | None = None
        self.scan: dict[str, Any] = {
            "active": False, "channel": None, "completed": 0,
            "total": len(CHANNEL_FREQUENCIES), "started_at": None, "finished_at": None, "error": None,
        }
        self.manage = os.getenv("DAB_MANAGE_RECEIVER", "1").strip().lower() not in {"0", "false", "no", "off"}
        self.process: asyncio.subprocess.Process | None = None
        self.process_log_task: asyncio.Task[None] | None = None
        self.monitor_task: asyncio.Task[None] | None = None
        self.poll_task: asyncio.Task[None] | None = None
        self.scan_task: asyncio.Task[None] | None = None
        self.scan_cancel_requested = False
        self.operation_lock = asyncio.Lock()
        self.restart_attempts = 0
        self.poll_failures = 0
        self.null_device_polls = 0
        self.restart_requested = False
        self.last_poll_error_log = 0.0
        self.process_stopping = False
        self.audio = SharedAudioStream()
        self.spi = SPIClient(DATA_DIR / "spi-cache.json")

    async def start(self) -> None:
        _configure_logging()
        await self.spi.start()
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=2.0, read=12.0, write=5.0, pool=2.0),
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=10),
        )
        if self.manage:
            await self._launch_receiver()
            self.monitor_task = asyncio.create_task(self._monitor_process(), name="welle-supervisor")
        self.poll_task = asyncio.create_task(self._poll_loop(), name="welle-poller")

    async def close(self) -> None:
        self.process_stopping = True
        await self.spi.close()
        if self.scan_task and not self.scan_task.done():
            self.scan_task.cancel()
            await asyncio.gather(self.scan_task, return_exceptions=True)
        await self.audio.stop_all()
        for task in (self.poll_task, self.monitor_task):
            if task:
                task.cancel()
        await asyncio.gather(*(t for t in (self.poll_task, self.monitor_task) if t), return_exceptions=True)
        await self._stop_process()
        await self.http.aclose()

    async def _launch_receiver(self) -> None:
        binary = os.getenv("DAB_WELLE_CLI", "welle-cli")
        executable = shutil.which(binary) if os.sep not in binary else (binary if os.access(binary, os.X_OK) else None)
        if not executable:
            self.status = "error"
            self.last_error = f"welle-cli executable not found: {binary}"
            logger.error(self.last_error)
            return
        channel = self.selected["channel"] or DEFAULT_CHANNEL
        try:
            gain = float(os.getenv("DAB_GAIN", "-1"))
            if not math.isfinite(gain) or (gain != -1 and not 0 <= gain <= 100):
                raise ValueError("DAB_GAIN must be -1 (AGC) or a fixed gain from 0 to 100 dB")
        except ValueError as exc:
            self.status = "error"
            self.last_error = f"Invalid receiver gain: {exc}"
            logger.error(self.last_error)
            return
        command = [executable, "-c", channel, "-w", str(RECEIVER_PORT), "-F", "rtl_sdr", "-g", f"{gain:g}", "-O", "mp3"]
        try:
            self.process = await asyncio.create_subprocess_exec(
                *command, cwd=BASE_DIR, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            logger.info("Started receiver process pid=%s channel=%s", self.process.pid, channel)
            self.process_log_task = asyncio.create_task(self._drain_process_log(self.process), name="welle-log-drain")
            self.restart_requested = False
            self.status = "starting"
        except Exception as exc:
            self.status = "error"
            self.last_error = f"Could not start welle-cli: {exc}"
            logger.exception(self.last_error)

    async def _drain_process_log(self, process: asyncio.subprocess.Process) -> None:
        if process.stdout is None:
            return
        try:
            with LOG_FILE.open("ab", buffering=0) as log_file:
                while True:
                    chunk = await process.stdout.read(4096)
                    if not chunk:
                        break
                    if log_file.tell() + len(chunk) > MAX_RECEIVER_LOG_BYTES:
                        log_file.close()
                        for index in range(RECEIVER_LOG_BACKUPS, 0, -1):
                            source = LOG_FILE.with_name(f"{LOG_FILE.name}.{index}")
                            target = LOG_FILE.with_name(f"{LOG_FILE.name}.{index + 1}")
                            if source.exists():
                                if index == RECEIVER_LOG_BACKUPS:
                                    source.unlink(missing_ok=True)
                                else:
                                    source.replace(target)
                        if LOG_FILE.exists():
                            LOG_FILE.replace(LOG_FILE.with_name(f"{LOG_FILE.name}.1"))
                        log_file = LOG_FILE.open("ab", buffering=0)
                    log_file.write(chunk)
        except asyncio.CancelledError:
            raise
        except OSError as exc:
            logger.error("Could not write receiver log: %s", exc)

    async def _stop_process(self) -> None:
        process, self.process = self.process, None
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        if self.process_log_task:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.process_log_task, timeout=1.0)
            self.process_log_task = None

    async def _monitor_process(self) -> None:
        while not self.process_stopping:
            await asyncio.sleep(1.0)
            process = self.process
            if process is None or process.returncode is None:
                continue
            code = process.returncode
            self.process = None
            logger.error("welle-cli exited with status %s", code)
            if self.restart_attempts >= 3:
                self.status = "error"
                self.last_error = f"welle-cli exited with status {code}; restart limit reached"
                continue
            delay = min(2 ** self.restart_attempts, 8)
            self.restart_attempts += 1
            self.status = "restarting"
            self.last_error = f"welle-cli exited with status {code}; retry {self.restart_attempts}/3 in {delay}s"
            await asyncio.sleep(delay)
            if not self.process_stopping:
                await self._launch_receiver()

    def _request_receiver_restart(self, reason: str) -> None:
        process = self.process
        if (
            not self.manage or process is None or process.returncode is not None
            or self.restart_requested or self.restart_attempts >= 3
        ):
            return
        self.restart_requested = True
        self.status = "restarting"
        self.last_error = f"{reason}; restarting welle-cli"
        logger.error(self.last_error)
        with contextlib.suppress(ProcessLookupError):
            process.terminate()

    async def _poll_loop(self) -> None:
        while True:
            try:
                mux_response, channel_response = await asyncio.gather(
                    self.http.get(f"{RECEIVER_ROOT}/mux.json"),
                    self.http.get(f"{RECEIVER_ROOT}/channel"),
                )
                mux_response.raise_for_status()
                raw = mux_response.json()
                if not isinstance(raw, dict):
                    raise ValueError("welle /mux.json did not return a JSON object")
                self.raw = raw
                self.last_mux_at = utc_now()
                self.poll_failures = 0
                try:
                    channel_response.raise_for_status()
                    reported_channel = channel_response.text.strip().upper()
                    if reported_channel in CHANNEL_FREQUENCIES:
                        self.current_channel = reported_channel
                except httpx.HTTPError:
                    pass
                hardware = ((raw.get("receiver") or {}).get("hardware") or {})
                hardware_name = str(hardware.get("name") or "").strip()
                if hardware_name.casefold() in {"null device", "null"}:
                    self.null_device_polls += 1
                    self.status = "error"
                    self.last_error = "welle-cli reports Null device; the RTL-SDR is not available"
                    if self.null_device_polls >= 3:
                        self._request_receiver_restart("welle-cli repeatedly reports Null device")
                elif self.manage and self.process and self.process.returncode is not None:
                    self.null_device_polls = 0
                    self.status = "error"
                    self.last_error = f"welle-cli exited with status {self.process.returncode}"
                elif self.restart_requested:
                    self.null_device_polls = 0
                    self.status = "restarting"
                else:
                    self.null_device_polls = 0
                    self.status = "healthy"
                    self.last_error = None
                    self.restart_attempts = 0
                    if not self.scan.get("active") and self.selected.get("channel") == self.current_channel:
                        self.spi.select(self.current_channel, self.selected.get("service"), raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.poll_failures += 1
                self.status = "error" if self.poll_failures >= 3 else ("healthy" if self.raw is not None else "starting")
                self.last_error = f"Cannot read welle receiver: {exc}"
                if time.monotonic() - self.last_poll_error_log >= 10:
                    logger.warning(self.last_error)
                    self.last_poll_error_log = time.monotonic()
                if self.poll_failures >= 5:
                    self._request_receiver_restart("welle receiver polling failed repeatedly")
            await asyncio.sleep(1.0)

    async def _post_channel(self, channel: str) -> None:
        try:
            response = await self.http.post(f"{RECEIVER_ROOT}/channel", content=channel, headers={"Content-Type": "text/plain"})
            response.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise HTTPException(status_code=502, detail=f"welle-cli could not tune to {channel}: {exc}") from exc
        self.current_channel = channel

    def _service_in_channel(self, channel: str, sid: str) -> bool | None:
        cached = self.cache.get("channels", {}).get(channel)
        if isinstance(cached, dict):
            return any(_raw_sid(service.get("sid")) == sid for service in cached.get("services", []) if isinstance(service, dict))
        if channel == self.current_channel and isinstance(self.raw, dict):
            return any(_raw_sid(service.get("sid")) == sid for service in self.raw.get("services", []) if isinstance(service, dict))
        return None

    async def tune(self, request: TuneRequest) -> dict[str, Any]:
        channel = canonical_channel(request.channel)
        sid = canonical_sid(request.service) if request.service is not None else None
        async with self.operation_lock:
            if self.scan.get("active"):
                raise HTTPException(status_code=409, detail="tuning is unavailable while the band scan is active")
            if sid is not None and self._service_in_channel(channel, sid) is False:
                raise HTTPException(status_code=404, detail=f"service {sid} is not present on channel {channel}")
            await self.audio.stop_all()
            if channel != self.current_channel:
                await self._post_channel(channel)
            self.selected = {"channel": channel, "service": sid}
            self.cache["selected"] = dict(self.selected)
            await asyncio.to_thread(_write_cache, self.cache)
            return {"ok": True, "selected": dict(self.selected), "channel": channel}

    async def start_scan(self) -> dict[str, Any]:
        async with self.operation_lock:
            if self.scan.get("active"):
                raise HTTPException(status_code=409, detail="a Band III scan is already running")
            original_channel = self.current_channel or self.selected["channel"] or DEFAULT_CHANNEL
            original_service = self.selected.get("service")
            self.scan = {
                "active": True, "channel": None, "completed": 0,
                "total": len(CHANNEL_FREQUENCIES), "started_at": utc_now(),
                "finished_at": None, "error": None, "elapsed_seconds": None,
                "current_elapsed_seconds": 0.0, "cancelled": False,
                "original": {"channel": original_channel, "service": original_service},
            }
            self.scan_cancel_requested = False
            await self.audio.stop_all()
            self.scan_task = asyncio.create_task(self._scan_worker(original_channel, original_service), name="dab-band-iii-scan")
        return {"ok": True, "scan": {k: v for k, v in self.scan.items() if k != "original"}}

    async def cancel_scan(self) -> dict[str, Any]:
        async with self.operation_lock:
            if not self.scan.get("active") or not self.scan_task or self.scan_task.done():
                raise HTTPException(status_code=409, detail="no Band III scan is running")
            self.scan_cancel_requested = True
            self.scan_task.cancel()
        return {"ok": True, "scan": {k: v for k, v in self.scan.items() if k != "original"}}

    async def _acquire_mux(self, channel: str) -> tuple[dict[str, Any] | None, float]:
        started = time.monotonic()
        mux: dict[str, Any] | None = None
        labels_key = None
        stable_since = started
        detected = False
        weak = False
        labels_complete = False
        while True:
            elapsed = time.monotonic() - started
            self.scan["current_elapsed_seconds"] = round(elapsed, 1)
            try:
                response = await self.http.get(f"{RECEIVER_ROOT}/mux.json")
                response.raise_for_status()
                value = response.json()
                if isinstance(value, dict):
                    demod = value.get("demodulator") or {}
                    snr = demod.get("snr")
                    services = [s for s in value.get("services", []) if isinstance(s, dict)]
                    ensemble_id = (value.get("ensemble") or {}).get("id", "0x0000")
                    has_id = str(ensemble_id).lower() not in {"0", "0x0000", "0x0", "none", ""}
                    if services or has_id:
                        detected = True
                    if detected:
                        weak = not isinstance(snr, (float, int)) or snr < 10
                    if services:
                        # Keep the most complete FIC snapshot, not a later partial one.
                        if mux is None or len(services) >= len(mux.get("services", [])):
                            mux = value
                        def label(service):
                            raw_label = service.get("label")
                            return (raw_label.get("label") or raw_label.get("fig2label") or "").strip() if isinstance(raw_label, dict) else str(raw_label or "").strip()
                        key = tuple(sorted((str(x.get("sid")), label(x)) for x in services))
                        if key != labels_key:
                            labels_key, stable_since = key, time.monotonic()
                        labels_complete = all(name for _, name in key)
                        if not weak and labels_complete and elapsed >= SCAN_ACQUISITION_MIN_SECONDS and time.monotonic() - stable_since >= SCAN_LABEL_STABLE_SECONDS:
                            return mux, elapsed
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            limit = SCAN_WEAK_MAX_SECONDS if detected and weak else SCAN_MAX_SECONDS if detected else SCAN_NO_SIGNAL_MIN_SECONDS
            if elapsed >= limit:
                return mux, elapsed
            await asyncio.sleep(min(SCAN_POLL_SECONDS, limit - elapsed))

    async def _scan_worker(self, original_channel: str, original_service: str | None) -> None:
        failures: list[str] = []
        scan_started = time.monotonic()
        try:
            for index, channel in enumerate(CHANNEL_FREQUENCIES, start=1):
                self.scan["channel"] = channel
                self.scan["index"] = index
                try:
                    await self._post_channel(channel)
                except HTTPException as exc:
                    failures.append(f"{channel}: {exc.detail}")
                    previous = self.cache["channels"].get(channel, {})
                    self.cache["channels"][channel] = {**(previous if isinstance(previous, dict) else {}),
                        "frequency_mhz": CHANNEL_FREQUENCIES[channel], "scanned_at": utc_now(), "error": str(exc.detail), "stale": True}
                    self.scan["completed"] = index
                    await asyncio.to_thread(_write_cache, self.cache)
                    continue
                try:
                    mux, dwell = await self._acquire_mux(channel)
                    self.scan["current_elapsed_seconds"] = round(dwell, 1)
                    if mux is None:
                        previous = self.cache["channels"].get(channel, {})
                        self.cache["channels"][channel] = {**previous, "frequency_mhz": CHANNEL_FREQUENCIES[channel], "scanned_at": utc_now(), "error": None, "stale": bool(previous.get("services")), "received": False}
                        self.scan["completed"] = index
                        await asyncio.to_thread(_write_cache, self.cache)
                        continue
                    services = [s for s in mux.get("services", []) if isinstance(s, dict)]
                    self.cache["channels"][channel] = {
                        "frequency_mhz": CHANNEL_FREQUENCIES[channel], "services": services,
                        "scanned_at": utc_now(), "ensemble": mux.get("ensemble"),
                        "snr": (mux.get("demodulator") or {}).get("snr"), "error": None, "stale": False,
                    }
                except Exception as exc:
                    failures.append(f"{channel}: {exc}")
                    previous = self.cache["channels"].get(channel, {})
                    self.cache["channels"][channel] = {**(previous if isinstance(previous, dict) else {}),
                        "frequency_mhz": CHANNEL_FREQUENCIES[channel], "scanned_at": utc_now(), "error": str(exc), "stale": True}
                self.scan["completed"] = index
                await asyncio.to_thread(_write_cache, self.cache)
        except asyncio.CancelledError:
            self.scan["cancelled"] = self.scan_cancel_requested
        except Exception as exc:
            failures.append(str(exc))
            logger.exception("Band III scan failed")
        finally:
            with contextlib.suppress(Exception):
                await self._post_channel(original_channel)
            self.selected = {"channel": original_channel, "service": original_service}
            self.cache["selected"] = dict(self.selected)
            with contextlib.suppress(Exception):
                await asyncio.to_thread(_write_cache, self.cache)
            self.scan["active"] = False
            self.scan["channel"] = None
            self.scan["finished_at"] = utc_now()
            self.scan["error"] = "; ".join(failures[:5]) if failures else None
            self.scan["elapsed_seconds"] = round(time.monotonic() - scan_started, 1)
            self.scan["current_elapsed_seconds"] = 0.0

    def _live_services(self) -> list[dict[str, Any]]:
        if not isinstance(self.raw, dict):
            return []
        return [s for s in self.raw.get("services", []) if isinstance(s, dict)]

    def state_payload(self) -> dict[str, Any]:
        stations: dict[tuple[str, str], dict[str, Any]] = {}
        for channel, entry in self.cache.get("channels", {}).items():
            if channel not in CHANNEL_FREQUENCIES or not isinstance(entry, dict):
                continue
            for service in entry.get("services", []) or []:
                if isinstance(service, dict):
                    station = _station_from_service(service, channel, False)
                    if station:
                        stations[(channel, station["id"])] = station
        if self.current_channel:
            for service in self._live_services():
                station = _station_from_service(service, self.current_channel, True)
                if station:
                    stations[(self.current_channel, station["id"])] = station
        station_list = sorted(stations.values(), key=lambda s: (s["channel"], s["name"].casefold(), s["id"]))

        selected = dict(self.selected)
        metadata: dict[str, Any] | None = None
        is_live = False
        sid = selected.get("service")
        if sid:
            if selected.get("channel") == self.current_channel:
                match = next((s for s in self._live_services() if _raw_sid(s.get("sid")) == sid), None)
                if match:
                    metadata = dict(match)
                    is_live = True
            if metadata is None:
                entry = self.cache.get("channels", {}).get(selected.get("channel"), {})
                match = next((s for s in entry.get("services", []) if isinstance(s, dict) and _raw_sid(s.get("sid")) == sid), None)
                if match:
                    metadata = dict(match)
        if metadata is not None:
            metadata["live"] = is_live
            metadata.update(dlplus_fields(metadata.get("dlplus") or {}))
            metadata["spi"] = self.spi.result(selected.get("channel"), sid)
            current = metadata["spi"].get("current_programme") or {}
            if current:
                metadata.setdefault("programme", current.get("name"))
                metadata["programme_description"] = current.get("description")

        raw = self.raw or {}
        receiver_json = raw.get("receiver") if isinstance(raw.get("receiver"), dict) else {}
        hardware = receiver_json.get("hardware") if isinstance(receiver_json.get("hardware"), dict) else {}
        software = receiver_json.get("software") if isinstance(receiver_json.get("software"), dict) else {}
        demod = raw.get("demodulator") if isinstance(raw.get("demodulator"), dict) else {}
        stats: dict[str, Any] = {
            "stream_clients": len(self.audio.subscribers),
            "stream_bytes": self.audio.bytes_streamed,
            "stream_reconnects": self.audio.reconnects,
            "stream_errors": self.audio.errors,
            "stream_slow_disconnects": self.audio.slow_disconnects,
            "stream_last_error": self.audio.last_error,
        }
        for source, destination in (
            ("snr", "snr"), ("frequencycorrection", "frequency_correction"),
            ("time_last_fct0_frame", "time_last_fct0_frame"),
        ):
            if source in demod:
                stats[destination] = demod[source]
        fic = demod.get("fic") if isinstance(demod.get("fic"), dict) else {}
        if "numcrcerrors" in fic:
            stats["fic_crc_errors"] = fic["numcrcerrors"]

        channels = []
        for channel, frequency in CHANNEL_FREQUENCIES.items():
            entry = self.cache.get("channels", {}).get(channel, {})
            services = entry.get("services", []) if isinstance(entry, dict) else []
            channels.append({
                "channel": channel,
                "frequency_mhz": frequency,
                "services": len(services),
                "scanned_at": entry.get("scanned_at") if isinstance(entry, dict) else None,
                "snr": entry.get("snr") if isinstance(entry, dict) else None,
                "error": entry.get("error") if isinstance(entry, dict) else None,
                "stale": entry.get("stale", False) if isinstance(entry, dict) else False,
            })
        return {
            "receiver": {
                "status": self.status,
                "managed": self.manage,
                "running": bool(self.process and self.process.returncode is None) if self.manage else self.status == "healthy",
                "hardware": {"name": hardware.get("name"), "gain": hardware.get("gain")},
                "software": {"name": software.get("name"), "version": software.get("version")},
                "channel": self.current_channel,
                "last_update": self.last_mux_at,
                "error": self.last_error,
            },
            "selected": selected,
            "stations": station_list,
            "metadata": metadata,
            "stats": stats,
            "channels": channels,
            "scan": {k: v for k, v in self.scan.items() if k != "original"},
        }


receiver = Receiver()


from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_: FastAPI):
    await receiver.start()
    try:
        yield
    finally:
        await receiver.close()


app = FastAPI(title="DAB Radio", version=APP_VERSION, lifespan=lifespan)


@app.get("/api/state")
async def get_state() -> dict[str, Any]:
    return receiver.state_payload()


@app.get("/api/raw")
async def get_raw() -> JSONResponse:
    if receiver.raw is None:
        try:
            response = await receiver.http.get(f"{RECEIVER_ROOT}/mux.json")
            response.raise_for_status()
            raw = response.json()
            if not isinstance(raw, dict):
                raise ValueError("mux response was not an object")
            receiver.raw = raw
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"welle mux data unavailable: {exc}") from exc
    return JSONResponse(content=receiver.raw)


@app.get("/tokens.css", include_in_schema=False)
async def get_tokens_css() -> FileResponse:
    if not TOKENS_FILE.is_file():
        raise HTTPException(status_code=404, detail="tokens.css is not installed")
    return FileResponse(TOKENS_FILE, media_type="text/css")


@app.get("/api/health")
async def get_health() -> JSONResponse:
    healthy = receiver.status == "healthy"
    content = {
        "status": "healthy" if healthy else receiver.status,
        "managed": receiver.manage,
        "running": bool(receiver.process and receiver.process.returncode is None) if receiver.manage else receiver.status == "healthy",
        "hardware": ((receiver.raw or {}).get("receiver") or {}).get("hardware"),
        "channel": receiver.current_channel,
        "error": receiver.last_error,
    }
    return JSONResponse(content=content, status_code=200 if healthy else 503)


@app.post("/api/tune")
async def post_tune(request: TuneRequest) -> dict[str, Any]:
    return await receiver.tune(request)


@app.post("/api/scan", status_code=202)
async def post_scan() -> dict[str, Any]:
    return await receiver.start_scan()


@app.post("/api/scan/cancel")
async def post_scan_cancel() -> dict[str, Any]:
    return await receiver.cancel_scan()


@app.get("/api/slide")
async def get_slide() -> Response:
    sid = receiver.selected.get("service")
    if not sid:
        raise HTTPException(status_code=404, detail="no DAB service is selected")
    try:
        async with receiver.http.stream("GET", f"{RECEIVER_ROOT}/slide/{sid}") as upstream:
            if upstream.status_code != 200:
                body = (await upstream.aread())[:4096]
                return Response(content=body, status_code=upstream.status_code, media_type=upstream.headers.get("content-type", "text/plain"))
            chunks = bytearray()
            async for chunk in upstream.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > 8 * 1024 * 1024:
                    raise HTTPException(status_code=502, detail="welle slide exceeds 8 MiB limit")
            return Response(
                content=bytes(chunks),
                media_type=upstream.headers.get("content-type", "application/octet-stream"),
                headers={"Cache-Control": "no-cache"},
            )
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"welle slide unavailable: {exc}") from exc


@app.get("/stream.mp3")
async def stream_mp3() -> StreamingResponse:
    if receiver.scan.get("active"):
        raise HTTPException(status_code=503, detail="audio is paused while the Band III scan is active")
    if receiver.status != "healthy":
        raise HTTPException(status_code=503, detail=receiver.last_error or "DAB receiver is not ready")
    sid = receiver.selected.get("service")
    if not sid:
        raise HTTPException(status_code=409, detail="select a DAB station before starting playback")
    known = receiver._service_in_channel(receiver.selected["channel"], sid)
    if known is False:
        raise HTTPException(status_code=404, detail=f"service {sid} is not present on channel {receiver.selected['channel']}")
    subscriber = await receiver.audio.subscribe(sid)

    async def chunks():
        try:
            while True:
                item = await subscriber.queue.get()
                if item is None:
                    break
                yield item
        finally:
            await receiver.audio.unsubscribe(subscriber)

    return StreamingResponse(
        chunks(), media_type="audio/mpeg",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
