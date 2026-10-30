"""Chat loading failures must remain distinct from a successfully empty list."""
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from modules.sales.models import Deal, Message


@pytest.mark.parametrize("entity", [Message, Deal], ids=["messages", "deals"])
@pytest.mark.parametrize("error_type", [OperationalError, ProgrammingError])
async def test_chat_database_failure_is_not_empty(session, api, monkeypatch, entity, error_type):
    execute = session.execute
    rollback = AsyncMock(wraps=session.rollback)
    failed_queries = []

    async def fail_chat_query(statement, *args, **kwargs):
        descriptions = getattr(statement, "column_descriptions", [])
        if any(column.get("entity") is entity for column in descriptions):
            failed_queries.append(statement)
            raise error_type("synthetic internal statement", {}, RuntimeError("internal-db-marker"))
        return await execute(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", fail_chat_query)
    monkeypatch.setattr(session, "rollback", rollback)
    response = await api.get("/sales/chats")

    assert failed_queries, "The intended endpoint database query must be reached."
    assert response.status_code == 503
    assert response.json() == {"detail": "Не удалось загрузить диалоги. Повторите позже."}
    assert "internal-db-marker" not in response.text
    assert "synthetic internal statement" not in response.text
    rollback.assert_awaited_once()


async def test_chat_successfully_empty_database_is_empty(api):
    response = await api.get("/sales/chats")
    assert response.status_code == 200
    assert response.json() == []
