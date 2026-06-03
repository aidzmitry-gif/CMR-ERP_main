"""AI-gateway (LiteLLM): единый шлюз к моделям для AI-подмодулей (§2.5, §3.3).

AI-слой — Итерация 1, за feature-flag (``ai_enabled``). Шлюз стоит в ядре, чтобы
AI-подмодули всех модулей обращались к нему, а не к моделям напрямую: так
маршрутизация локал↔API и учёт токенов живут в одном месте.

В деве локальная модель (Qwen/Ollama) может быть не поднята — при пустом
``llm_base_url`` шлюз работает в детерминированном mock-режиме (как 1С-mock).
Реальный LiteLLM (OpenAI-совместимый) подключается тем же контрактом ``complete``.
"""
from __future__ import annotations


class LLMGateway:
    """AI-шлюз: ``complete(prompt)`` поверх локальной/внешней модели или mock."""

    def __init__(self, settings=None) -> None:
        self.enabled = bool(getattr(settings, "ai_enabled", False))
        self.base_url = getattr(settings, "llm_base_url", "") or ""
        self.model = getattr(settings, "llm_model", "") or ""

    async def complete(self, prompt: str, system: str = "") -> str:
        """Сгенерировать ответ модели. Требует включённого AI-слоя (feature-flag)."""
        if not self.enabled:
            raise RuntimeError("AI-слой выключен (feature-flag ai_enabled)")
        if self.base_url:
            # TODO(ai): реальный OpenAI-совместимый запрос к LiteLLM/Ollama
            return await self._call_model(prompt, system)
        return self._mock(prompt, system)

    async def _call_model(self, prompt: str, system: str) -> str:  # pragma: no cover
        raise NotImplementedError("Реальный LiteLLM подключается на этапе AI-слоя")

    def _mock(self, prompt: str, system: str) -> str:
        """Детерминированный ответ без модели — чтобы AI-слой работал в деве."""
        return (
            "Здравствуйте! Благодарю за обращение. Уточнил информацию по вашему запросу — "
            "готовы предложить оптимальные условия и сроки поставки. Подготовлю детали "
            "и вернусь с коммерческим предложением. При необходимости согласуем созвон. "
            "С уважением, отдел продаж."
        )
