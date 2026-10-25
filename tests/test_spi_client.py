import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from metadata import parse_spi_xml
from spi_client import SPIClient


def test_radio_dns_selection_and_cached_result_does_not_need_network(tmp_path):
    client = SPIClient(tmp_path / 'spi.json')
    client.select('12B', '0xc222', {'ensemble': {'id': '0xce15', 'ecc': '0xe1'}})
    assert client.selected[2:6] == ('ce1', 'ce15', 'c222', '0')
    assert client.result('12B', '0xc222')['status'] == 'loading'
    assert client.result('11D', '0xc222')['status'] == 'unavailable'


def test_spi_logo_still_available_when_programme_guide_unpublished(tmp_path):
    import httpx
    async def exercise():
        client = SPIClient(tmp_path / 'spi.json')
        client._discover = AsyncMock(return_value='https://example.org/radiodns/spi/3.1/')
        info = parse_spi_xml(b'<serviceInformation><service><mediumName>Station</mediumName><bearer id="dab:ce1.ce15.c222.0"/></service></serviceInformation>')
        client._document = AsyncMock(side_effect=[info, ValueError('not published')])
        result = await client._fetch(('12B', '0xc222', 'ce1', 'ce15', 'c222', '0', '20261025'))
        assert result['status'] == 'ready'
        assert result['guide_status'] == 'not_published'
        assert result['service']['name'] == 'Station'
    asyncio.run(exercise())


def test_spi_rejects_loopback_and_private_addresses(tmp_path):
    async def exercise():
        client = SPIClient(tmp_path / 'spi.json')
        for host in ['127.0.0.1', '192.168.1.1', '::1']:
            try:
                await client._public_host(host)
            except ValueError:
                continue
            raise AssertionError('private metadata endpoint accepted')
    asyncio.run(exercise())
