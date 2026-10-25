"""Bounded parsing and caching helpers for ETSI DAB SPI XML.

This module handles XML payloads supplied by a caller. It does not discover
RadioDNS hosts, fetch documents/images, or decode the DAB MOT binary transport.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any
import re

from defusedxml import ElementTree as ET

MAX_XML_BYTES = 2 * 1024 * 1024
MAX_SERVICES = 1024
MAX_PROGRAMMES = 4096


class MetadataError(ValueError):
    """Invalid, unsafe, or oversized SPI XML."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1]


def _children(element: Any, name: str) -> list[Any]:
    return [child for child in element.iter() if child is not element and _local(child.tag) == name]


def _first_text(element: Any, names: tuple[str, ...]) -> str | None:
    for name in names:
        for child in _children(element, name):
            text = " ".join("".join(child.itertext()).split())
            if text:
                return text
    return None


def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_service_id(value: str | None) -> str | None:
    """Normalize common ETSI content IDs and DAB bearer URIs for matching."""
    if not value:
        return None
    value = value.strip()
    value = re.sub(r"^dab:", "", value, flags=re.I)
    value = value.lower()
    if not value:
        return None
    # DAB bearer: ensemble.ECC+ensemble-SId.service-SId.SCIdS
    parts = value.split(".")
    if len(parts) >= 3 and all(parts[:3]):
        return ".".join(parts[:4]) if len(parts) > 3 else value
    return value


@dataclass(frozen=True)
class Station:
    service_id: str
    name: str | None = None
    short_name: str | None = None
    description: str | None = None
    logo_url: str | None = None
    bearer_ids: tuple[str, ...] = ()
    originator: str | None = None
    radio_fqdn: str | None = None
    radio_service_identifier: str | None = None


@dataclass(frozen=True)
class Programme:
    crid: str | None = None
    name: str | None = None
    description: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    bearer_ids: tuple[str, ...] = ()
    service_ids: tuple[str, ...] = ()


@dataclass
class SPIData:
    stations: list[Station] = field(default_factory=list)
    programmes: list[Programme] = field(default_factory=list)
    originator: str | None = None
    service_provider: str | None = None
    binary_transport_supported: bool = False

    def station_for(self, service_id: str) -> Station | None:
        key = normalize_service_id(service_id)
        return next((s for s in self.stations if key == normalize_service_id(s.service_id)
                     or key in {normalize_service_id(x) for x in s.bearer_ids}), None)

    def programmes_for(self, service_id: str) -> list[Programme]:
        key = normalize_service_id(service_id)
        return [p for p in self.programmes
                if key in {normalize_service_id(x) for x in (*p.service_ids, *p.bearer_ids)}]


def parse_spi_xml(xml: bytes | str) -> SPIData:
    """Parse ServiceInformation and Schedule/ProgrammeInformation XML safely.

    Documents larger than 2 MiB and entity/DTD declarations are rejected before
    parsing. Matching is explicit through :func:`match_service`.
    """
    raw = xml.encode("utf-8") if isinstance(xml, str) else bytes(xml)
    if len(raw) > MAX_XML_BYTES:
        raise MetadataError("SPI XML exceeds 2 MiB")
    try:
        root = ET.fromstring(raw, forbid_dtd=True)
    except Exception as exc:
        raise MetadataError("invalid or unsafe SPI XML") from exc
    root_name = _local(root.tag)
    if root_name not in {"serviceInformation", "epg", "programmeInformation", "schedule"}:
        raise MetadataError(f"unsupported SPI document root: {root_name}")

    result = SPIData(originator=root.attrib.get("originator"),
                     service_provider=root.attrib.get("serviceProvider"))
    for node in [n for n in root.iter() if _local(n.tag) == "service"][:MAX_SERVICES]:
        sid_node = next(iter(_children(node, "serviceID")), None)
        sid = sid_node.attrib.get("id") if sid_node is not None else node.attrib.get("id")
        bearers = tuple(dict.fromkeys(b.attrib["id"] for b in _children(node, "bearer") if b.get("id")))
        sid = sid or next((b for b in bearers if b.lower().startswith("dab:")), next(iter(bearers), None))
        if not sid:
            continue
        logos = [m for m in _children(node, "multimedia") if m.get("url") and "logo" in m.get("type", "").lower()]
        def logo_score(m):
            try:
                w, h = int(m.get("width", "0")), int(m.get("height", "0"))
                return abs(w - 320) + abs(h - 240)
            except ValueError:
                return 100000
        logo = min(logos, key=logo_score).get("url") if logos else None
        radio = next(iter(_children(node, "radiodns")), None)
        result.stations.append(Station(
            service_id=sid,
            name=_first_text(node, ("mediumName", "longName", "shortName")),
            short_name=_first_text(node, ("shortName",)),
            description=_first_text(node, ("shortDescription", "longDescription")),
            logo_url=logo, bearer_ids=bearers, originator=result.originator,
            radio_fqdn=radio.get("fqdn") if radio is not None else None,
            radio_service_identifier=radio.get("serviceIdentifier") if radio is not None else None))

    programme_nodes = [n for n in root.iter() if _local(n.tag) in {"programme", "program"}]
    for node in programme_nodes[:MAX_PROGRAMMES]:
        times = _children(node, "time")
        start = next((_iso(t.get("time")) for t in times if _iso(t.get("time"))), None)
        end = None
        if start:
            duration = next((t.get("duration") for t in times if t.get("duration")), None)
            if duration:
                from datetime import timedelta
                match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?", duration)
                if match:
                    d, h, m, s = match.groups()
                    end = start + timedelta(days=int(d or 0), hours=int(h or 0), minutes=int(m or 0), seconds=float(s or 0))
        bearers = tuple(dict.fromkeys(b.get("id") for b in _children(node, "bearer") if b.get("id")))
        services = tuple(dict.fromkeys(s.get("id") for s in _children(node, "serviceScope") if s.get("id")))
        if not services:
            for schedule in (n for n in root.iter() if _local(n.tag) == "schedule"):
                if node in schedule.iter():
                    services = tuple(dict.fromkeys(
                        s.get("id") for s in _children(schedule, "serviceScope") if s.get("id")))
                    break
        result.programmes.append(Programme(
            crid=node.get("id") if node.get("id", "").startswith("crid:") else None,
            name=_first_text(node, ("mediumName", "longName", "shortName")),
            description=_first_text(node, ("shortDescription", "longDescription")),
            start=start, end=end, bearer_ids=bearers, service_ids=services))
    return result


def match_service(data: SPIData, service_id: str) -> Station | None:
    """Return the station matching a DAB service ID or bearer identifier."""
    return data.station_for(service_id)


def current_programme(data: SPIData, service_id: str,
                      at: datetime | None = None) -> Programme | None:
    """Find the schedule entry covering ``at`` for a matching DAB service.

    Entries without an end time are treated as active until the next known
    programme start for that service, or indefinitely when no next entry exists.
    Naive and aware timestamps are not mixed; callers should pass timezone-aware
    datetimes for timezone-aware SPI feeds.
    """
    from datetime import timezone
    at = at or datetime.now(timezone.utc)
    candidates = data.programmes_for(service_id)
    candidates.sort(key=lambda p: p.start or datetime.min.replace(tzinfo=at.tzinfo))
    for index, programme in enumerate(candidates):
        if programme.start is None or programme.start > at:
            continue
        end = programme.end
        if end is None:
            end = next((p.start for p in candidates[index + 1:] if p.start), None)
        if end is None or at < end:
            return programme
    return None


class MetadataCache:
    """Small in-memory TTL cache suitable for an external bounded worker."""
    def __init__(self, max_entries: int = 32, ttl_seconds: float = 3600):
        from collections import OrderedDict
        self.max_entries = max(1, int(max_entries))
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._items: Any = OrderedDict()

    def get(self, key: str, *, now: float | None = None) -> SPIData | None:
        import time
        now = time.monotonic() if now is None else now
        item = self._items.get(key)
        if item is None:
            return None
        expires, value = item
        if expires <= now:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return value

    def put(self, key: str, value: SPIData, *, now: float | None = None) -> None:
        import time
        now = time.monotonic() if now is None else now
        self._items[key] = (now + self.ttl_seconds, value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)


def decode_binary_spi(_payload: bytes) -> SPIData:
    """Binary ETSI TS 102 371/MOT decoding is deliberately not implemented."""
    raise NotImplementedError("binary DAB SPI/MOT transport decoding is unsupported")


def dlplus_fields(value: dict) -> dict:
    """Use transmitted typed DL+ tags; never infer artist/title from plain DLS."""
    fields = {"ITEM.ARTIST": "artist", "ITEM.TITLE": "title", "ITEM.ALBUM": "album", "ITEM.COMPOSER": "composer", "ITEM.CONDUCTOR": "conductor", "PROGRAMME.NOW": "programme", "PROGRAMME.HOST": "presenter"}
    result = {}
    for tag in value.get("tags", [])[:64]:
        if not isinstance(tag, dict):
            continue
        name = tag.get("name")
        if name in fields and (not name.startswith("ITEM.") or value.get("item_running")):
            text = tag.get("text")
            if isinstance(text, str) and text.strip():
                result[fields[name]] = text.strip()[:256]
    return result
