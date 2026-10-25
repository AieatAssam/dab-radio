"""Bounded, asynchronous RadioDNS SPI enrichment; never consumes SDR/audio data."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import time
from urllib.parse import quote, urljoin, urlsplit

import dns.asyncresolver
import httpx
from metadata import MAX_XML_BYTES, SPIData, parse_spi_xml, match_service, current_programme


class SPIClient:
    def __init__(self, cache_path: Path):
        self.path = cache_path
        self.cache: dict = {}
        try:
            saved = json.loads(cache_path.read_text())
            if isinstance(saved, dict):
                self.cache = dict(list(saved.items())[-32:])
        except (OSError, ValueError):
            pass
        self.documents: OrderedDict = OrderedDict()
        self.selected = None
        self.event = asyncio.Event()
        self.task = None
        self.http = None
        self.resolver = dns.asyncresolver.Resolver()
        self.resolver.lifetime = 3
        self.resolver.timeout = 2

    async def start(self):
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(8, connect=3), limits=httpx.Limits(max_connections=2), headers={"User-Agent": "DAB-Listening-Deck/1.1 RadioDNS-SPI", "Accept": "application/xml"})
        self.task = asyncio.create_task(self._worker(), name="low-priority-spi")

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.http:
            await self.http.aclose()

    def select(self, channel, sid, raw):
        if not sid or not raw:
            return
        ensemble = raw.get("ensemble") or {}
        try:
            eid = f"{int(ensemble.get('id', '0'), 16):04x}"
            service = f"{int(sid, 16):04x}"
            if eid == "0000" or len(service) != 4:
                return
            # ECC is optional on air. This installation's configured country is UK.
            ecc = int(ensemble.get("ecc", "0xe1"), 16) or 0xe1
            gcc = f"{int(service[0], 16):x}{ecc:02x}"
        except (ValueError, TypeError):
            return
        date = datetime.now(timezone.utc).strftime("%Y%m%d")
        selection = (channel, sid, gcc, eid, service, "0", date)
        key = "|".join(selection)
        if self.selected != selection or self.cache.get(key, {}).get("expires", 0) <= time.time():
            self.selected = selection
            self.event.set()

    def result(self, channel, sid):
        s = self.selected
        if not s or (channel, sid) != s[:2]:
            return {"status": "unavailable", "source": "RadioDNS (internet)"}
        result = dict(self.cache.get("|".join(s), {"status": "loading", "source": "RadioDNS (internet)"}))
        result.pop("expires", None)
        programmes = result.get("programmes", [])
        now = datetime.now(timezone.utc).isoformat()
        result["current_programme"] = next((p for p in programmes if p.get("start") and p.get("end") and p["start"] <= now < p["end"]), None)
        return result

    async def _public_host(self, host):
        if not host:
            raise ValueError("SPI URL has no host")
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            addresses = []
            for family in ("A", "AAAA"):
                try:
                    answers = await self.resolver.resolve(host, family)
                    addresses.extend(ipaddress.ip_address(str(r)) for r in answers)
                except dns.exception.DNSException:
                    pass
        if not addresses or any(not a.is_global for a in addresses):
            raise ValueError("SPI endpoint must use public network addresses")

    async def _document(self, url):
        cached = self.documents.get(url)
        if cached and cached[0] > time.time():
            return cached[1]
        original = url
        for _ in range(4):
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
                raise ValueError("unsupported SPI URL")
            await self._public_host(parsed.hostname)
            async with self.http.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_XML_BYTES:
                        raise ValueError("SPI document exceeds 2 MiB")
            parsed_data = await asyncio.to_thread(parse_spi_xml, bytes(data))
            self.documents[original] = (time.time() + 3600, parsed_data)
            while len(self.documents) > 12:
                self.documents.popitem(last=False)
            return parsed_data
        raise ValueError("too many SPI redirects")

    async def _discover(self, gcc, eid, sid, scids):
        fqdn = f"{scids}.{sid}.{eid}.{gcc}.dab.radiodns.org"
        answer = await self.resolver.resolve(fqdn, "CNAME")
        authority = str(answer[0].target).rstrip(".")
        for name, scheme in (("radiospi", "https"), ("radioepg", "http")):
            try:
                records = await self.resolver.resolve(f"_{name}._tcp.{authority}", "SRV")
            except dns.exception.DNSException:
                continue
            for record in sorted(records, key=lambda r: (r.priority, -r.weight))[:2]:
                host = str(record.target).rstrip(".")
                if host:
                    return f"{scheme}://{host}:{record.port}/radiodns/spi/3.1/"
        raise ValueError("station does not publish a RadioDNS SPI server")

    async def _fetch(self, selection):
        channel, sid, gcc, eid, service_id, scids, date = selection
        base = await self._discover(gcc, eid, service_id, scids)
        info = await self._document(base + "SI.xml")
        bearer = f"dab:{gcc}.{eid}.{service_id}.{scids}"
        station = match_service(info, bearer)
        if station is None:
            raise ValueError("station bearer not present in SPI service information")
        service = asdict(station)
        result = {"status": "ready", "source": "RadioDNS (internet)", "service": service, "programmes": [], "guide_status": "not_published", "updated_at": datetime.now(timezone.utc).isoformat()}
        paths = [f"dab/{gcc}/{eid}/{service_id}/{scids}/{date}_PI.xml"]
        if station.radio_fqdn and station.radio_service_identifier:
            paths.insert(0, f"id/{quote(station.radio_fqdn, safe='')}/{quote(station.radio_service_identifier, safe='')}/{date}_PI.xml")
        for path in paths:
            try:
                guide = await self._document(base + path)
                programmes = []
                seen = set()
                for candidate in (bearer, *station.bearer_ids):
                    for programme in guide.programmes_for(candidate):
                        identity = (programme.crid, programme.name, programme.start)
                        if identity not in seen:
                            seen.add(identity)
                            programmes.append(programme)
                # A PI document explicitly requested for this station may identify it
                # by RadioDNS id instead of its DAB bearer.
                if not programmes:
                    programmes = [p for p in guide.programmes if not p.bearer_ids and not p.service_ids]
                result["programmes"] = [{**asdict(p), "start": p.start.astimezone(timezone.utc).isoformat() if p.start and p.start.tzinfo else None, "end": p.end.astimezone(timezone.utc).isoformat() if p.end and p.end.tzinfo else None} for p in programmes[:128]]
                result["guide_status"] = "ready" if programmes else "empty"
                break
            except (httpx.HTTPError, ValueError, dns.exception.DNSException):
                continue
        return result

    async def _worker(self):
        while True:
            await self.event.wait()
            self.event.clear()
            selection = self.selected
            if selection is None:
                continue
            key = "|".join(selection)
            if self.cache.get(key, {}).get("expires", 0) > time.time():
                continue
            try:
                # Bounded metadata I/O cannot block or feed the audio stream.
                result = await asyncio.wait_for(self._fetch(selection), timeout=40)
                result["expires"] = time.time() + 3600
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                result = {"status": "unavailable", "source": "RadioDNS (internet)", "reason": str(exc)[:200], "expires": time.time() + 900}
            self.cache[key] = result
            self.cache = dict(list(self.cache.items())[-32:])
            try:
                await asyncio.to_thread(self._save)
            except OSError:
                pass

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.cache, ensure_ascii=False))
        temp.replace(self.path)
