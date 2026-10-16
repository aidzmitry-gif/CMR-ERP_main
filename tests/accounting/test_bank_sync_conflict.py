from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from modules.finance import bank_ingest
from modules.finance.routes import bank_sync


@pytest.mark.parametrize("failure", ["ingest", "commit", "identity"])
async def test_sync_conflict_rolls_back_and_is_not_bank_outage(monkeypatch, failure):
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    sync = AsyncMock(return_value={"imported": 1})
    conflict = IntegrityError("synthetic", {}, ValueError("synthetic constraint"))
    if failure == "commit":
        session.commit.side_effect = conflict
    else:
        sync.side_effect = bank_ingest.BankSourceIdentityConflict("Existing source") if failure == "identity" else conflict
    monkeypatch.setattr(bank_ingest, "sync_incoming", sync)
    core = SimpleNamespace(services=SimpleNamespace(bank=None), event_bus=None)
    with pytest.raises(HTTPException) as raised:
        await bank_sync(core, session)
    assert raised.value.status_code == 409
    session.rollback.assert_awaited_once()
    if failure != "commit":
        session.commit.assert_not_awaited()
