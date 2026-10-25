from datetime import datetime, timezone

import pytest

from metadata import (MAX_XML_BYTES, MetadataCache, MetadataError, current_programme,
                      match_service, normalize_service_id, parse_spi_xml)


SPI = b'''<?xml version="1.0"?>
<serviceInformation xmlns="http://www.worlddab.org/schemas/epgSI/14"
 xmlns:epg="http://www.worlddab.org/schemas/epgDataTypes/14"
 originator="Example Radio" serviceProvider="Example Group">
 <ensemble id="e1.ce15"><service format="audio">
  <serviceID id="e1.ce15.c221.0"/><epg:shortName>EX</epg:shortName>
  <epg:mediumName>Example FM</epg:mediumName>
  <mediaDescription><epg:shortDescription>Music and news</epg:shortDescription></mediaDescription>
  <mediaDescription><epg:multimedia type="logo_colour_square" url="https://example.test/logo.png"/></mediaDescription>
 </service></ensemble>
 <schedule><scope><serviceScope id="dab:e1.ce15.c221.0"/></scope>
  <programme id="crid://example.test/show/one">
   <epg:mediumName>Morning Show</epg:mediumName>
   <location><time time="2025-01-01T08:00:00Z" duration="PT2H"/><bearer id="e1.ce15.c221.0"/></location>
   <mediaDescription><epg:shortDescription>Today's headlines</epg:shortDescription></mediaDescription>
  </programme>
 </schedule>
</serviceInformation>'''


def test_parses_namespaced_station_programme_and_bearer_matching():
    data = parse_spi_xml(SPI)
    station = match_service(data, "dab:e1.ce15.c221.0")
    assert station is not None
    assert station.name == "Example FM"
    assert station.short_name == "EX"
    assert station.description == "Music and news"
    assert station.logo_url == "https://example.test/logo.png"
    assert station.originator == "Example Radio"
    programme = current_programme(data, "e1.ce15.c221.0",
                                  datetime(2025, 1, 1, 9, tzinfo=timezone.utc))
    assert programme is not None
    assert programme.name == "Morning Show"
    assert programme.description == "Today's headlines"
    assert programme.crid == "crid://example.test/show/one"
    assert programme.end == datetime(2025, 1, 1, 10, tzinfo=timezone.utc)


def test_normalizes_dab_bearer_prefix():
    assert normalize_service_id("dab:E1.CE15.C221.0") == "e1.ce15.c221.0"


@pytest.mark.parametrize("xml", [
    b'<!DOCTYPE x [<!ENTITY e "boom">]><serviceInformation>&e;</serviceInformation>',
    b'<serviceInformation><x>',
])
def test_rejects_hostile_or_malformed_xml(xml):
    with pytest.raises(MetadataError):
        parse_spi_xml(xml)


def test_rejects_oversized_document():
    with pytest.raises(MetadataError, match="2 MiB"):
        parse_spi_xml(b" " * (MAX_XML_BYTES + 1))


def test_cache_ttl_and_capacity():
    cache = MetadataCache(max_entries=1, ttl_seconds=5)
    data = parse_spi_xml(SPI)
    cache.put("one", data, now=10)
    assert cache.get("one", now=14) is data
    cache.put("two", data, now=14)
    assert cache.get("one", now=14) is None
    assert cache.get("two", now=20) is None


def test_modern_spi_services_match_dab_bearers_without_service_id():
    xml = b'''<serviceInformation xmlns="http://www.worlddab.org/schemas/spi"><services><service><mediumName>Real Station</mediumName><bearer id="dab:ce1.ce15.c222.0"/><radiodns fqdn="radio.example.org" serviceIdentifier="station"/><mediaDescription><multimedia url="https://example.org/tiny.png" type="logo_unrestricted" width="32" height="32"/><multimedia url="https://example.org/full.png" type="logo_unrestricted" width="320" height="240"/></mediaDescription></service></services></serviceInformation>'''
    station = match_service(parse_spi_xml(xml), "dab:ce1.ce15.c222.0")
    assert station.name == "Real Station"
    assert station.logo_url == "https://example.org/full.png"
    assert station.radio_service_identifier == "station"


def test_dlplus_only_uses_transmitted_active_item_tags():
    from metadata import dlplus_fields
    tags = [{"name": "ITEM.ARTIST", "text": "Artist"}, {"name": "ITEM.TITLE", "text": "Track"}, {"name": "PROGRAMME.NOW", "text": "Show"}]
    assert dlplus_fields({"tags": tags, "item_running": True}) == {"artist": "Artist", "title": "Track", "programme": "Show"}
    assert dlplus_fields({"tags": tags, "item_running": False}) == {"programme": "Show"}
    assert dlplus_fields({}) == {}
