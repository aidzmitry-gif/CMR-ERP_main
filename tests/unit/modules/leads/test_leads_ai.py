from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.leads import ai


@pytest.mark.asyncio
async def test_qualify_lead_delegates_explanation_to_llm_with_localized_verdict():
    gateway = SimpleNamespace(complete=AsyncMock(return_value="Готово"))
    lead = SimpleNamespace(
        source="site",
        company="ООО Альфа",
        region="Минск",
        product="АКБ",
        message="Нужна партия",
    )
    result = await ai.qualify_lead(gateway, lead, 87, "target")
    assert result == "Готово"
    gateway.complete.assert_awaited_once()
    prompt, kwargs = gateway.complete.await_args.args, gateway.complete.await_args.kwargs
    assert "Оценка 87/100" in prompt[0]
    assert "вердикт: целевой" in prompt[0]
    assert kwargs == {"system": "Ты — AI-квалификатор лидов отдела продаж. Кратко поясни оценку на русском.", "kind": "qualify"}


@pytest.mark.asyncio
async def test_qualify_lead_uses_safe_dashes_for_empty_fields_and_non_target_verdict():
    gateway = SimpleNamespace(complete=AsyncMock(return_value="Не целевой"))
    lead = SimpleNamespace(source="phone", company="", region=None, product=None, message=None)
    await ai.qualify_lead(gateway, lead, 12, "reject")
    prompt = gateway.complete.await_args.args[0]
    assert "компания «—»" in prompt
    assert "вердикт: нецелевой" in prompt
