"""Explicit source adapter for legacy positive API examples (test-only)."""
from uuid import uuid4

import pytest_asyncio

from tests.test_logistics_invoice_binding import exact  # noqa: F401 - fixture registration


@pytest_asyncio.fixture
async def shipping_api(api, exact):  # noqa: F811
    original = api.post
    async def post(url, **kwargs):
        if url in {"/logistics/shipments", "/logistics/rfqs"}:
            data = dict(kwargs.get("json", {}))
            data.setdefault("invoice", exact)
            data.setdefault("source_key", uuid4().hex)
            if "deal_id" in data:
                data["deal_id"] = exact["document_id"]
            kwargs["json"] = data
        return await original(url, **kwargs)
    api.post = post
    yield api
    api.post = original
