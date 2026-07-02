"""M1: ЕГР-lookup — mock при пустом base_url, реальный HTTP-каркас при заданном (graceful)."""
from modules.integrations.registry import RegistryClient


async def test_mock_lookup_found_and_missing():
    client = RegistryClient()  # пустой base_url → mock
    found = await client.lookup("191234567")
    assert found is not None
    assert found["unp"] == "191234567"
    assert "name" in found and "address" in found and "status" in found
    assert await client.lookup("000000000") is None  # нет в mock
    assert await client.lookup("  ") is None  # пустой УНП


async def test_remote_lookup_graceful_on_unreachable():
    # заданный, но недостижимый base_url → None (не падаем), а не исключение
    client = RegistryClient("http://127.0.0.1:1/egr")
    assert await client.lookup("191234567") is None
