"""AI-gateway (LiteLLM): единый шлюз к моделям для AI-подмодулей (§2.5, §3.3).

AI-слой — Итерация 1, за feature-flag (``ai_enabled``). Шлюз стоит в ядре, чтобы
AI-подмодули всех модулей обращались к нему, а не к моделям напрямую: так
маршрутизация локал↔API и учёт токенов живут в одном месте.

В деве локальная модель (Qwen/Ollama) может быть не поднята — при пустом
``llm_base_url`` шлюз работает в mock-режиме только при ``environment=dev``.
Реальный LiteLLM (OpenAI-совместимый) подключается тем же контрактом ``complete``.
"""
from __future__ import annotations

import asyncio
import json

import httpx


class LLMGateway:
    """AI-шлюз: ``complete(prompt)`` поверх локальной/внешней модели или mock."""

    def __init__(self, settings=None) -> None:
        self.enabled = bool(getattr(settings, "ai_enabled", False))
        self.base_url = (getattr(settings, "llm_base_url", "") or "").strip()
        self.model = getattr(settings, "llm_model", "") or ""
        self.dev_mode = getattr(settings, "environment", "") == "dev"

    async def complete(self, prompt: str, system: str = "", kind: str = "") -> str:
        """Сгенерировать ответ модели. Требует включённого AI-слоя (feature-flag).

        ``kind`` — подсказка типа задачи для mock-режима (реальная модель её
        игнорирует, понимая задачу из ``system``/``prompt``).
        """
        if not self.enabled:
            raise RuntimeError("AI-слой выключен (feature-flag ai_enabled)")
        if self.base_url:
            return await self._call_model(prompt, system)
        if self.dev_mode:
            return self._mock(kind)
        raise RuntimeError("Некорректные настройки AI-шлюза")

    async def _call_model(self, prompt: str, system: str) -> str:
        try:
            url = httpx.URL(self.base_url)
            valid_url = (
                url.scheme in {"http", "https"} and url.host
                and not url.username and not url.password and not url.query and not url.fragment
                and "?" not in self.base_url and "#" not in self.base_url
            )
        except (httpx.InvalidURL, ValueError):
            valid_url = False
        if not valid_url or not self.model.strip():
            raise RuntimeError("Некорректные настройки AI-шлюза") from None

        suffix = "/v1/chat/completions" if url.path in {"", "/"} else "/chat/completions"
        endpoint = self.base_url.rstrip("/") + suffix
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})

        # A configured provider failure must never become a synthetic mock answer.
        # Disable redirects/proxy discovery so prompts go only to the configured endpoint.
        try:
            async with asyncio.timeout(30), httpx.AsyncClient(
                timeout=httpx.Timeout(30, connect=5), follow_redirects=False, trust_env=False,
            ) as client:
                async with client.stream(
                    "POST", endpoint,
                    json={"model": self.model, "messages": messages, "stream": False},
                    headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                ) as response:
                    if response.status_code != 200:
                        raise RuntimeError("AI-провайдер недоступен")
                    # Reject encoded bodies before HTTPX can decompress them without a bound.
                    if response.headers.get("content-encoding", "").strip().lower() not in {"", "identity"}:
                        raise RuntimeError("AI-провайдер вернул некорректный ответ")
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=16384):
                        if len(body) + len(chunk) > 1024 * 1024:
                            raise RuntimeError("AI-провайдер вернул некорректный ответ")
                        body.extend(chunk)
        except (httpx.HTTPError, TimeoutError):
            # Provider exceptions can contain URLs or response/prompt material.
            raise RuntimeError("AI-провайдер недоступен") from None

        try:
            data = json.loads(body)
        except ValueError:
            raise RuntimeError("AI-провайдер вернул некорректный ответ") from None
        choices = data.get("choices") if isinstance(data, dict) else None
        choice = choices[0] if isinstance(choices, list) and choices else None
        message = choice.get("message") if isinstance(choice, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if (
            not isinstance(content, str) or not content.strip()
            or message.get("role") != "assistant" or message.get("refusal")
            or message.get("tool_calls") or choice.get("finish_reason") != "stop"
        ):
            raise RuntimeError("AI-провайдер вернул некорректный ответ")
        return content

    # Детерминированные ответы без модели — чтобы AI-слой работал в деве (как 1С-mock).
    _MOCKS = {
        "draft": (
            "Здравствуйте! Благодарю за обращение. Уточнил информацию по вашему запросу — "
            "готовы предложить оптимальные условия и сроки поставки. Подготовлю детали "
            "и вернусь с коммерческим предложением. При необходимости согласуем созвон. "
            "С уважением, отдел продаж."
        ),
        "summary": (
            "Сделка в активной проработке: согласована номенклатура и цены, ведётся "
            "переписка с клиентом, оформляются документы. Риск — сроки поставки; цена в "
            "пределах истории по клиенту. Рекомендуется закрыть согласование договора."
        ),
        "next_step": (
            "Следующий шаг: согласовать договор с юристом и выставить счёт, затем "
            "подтвердить сроки отгрузки с клиентом. Ориентир — закрыть стадию за 3 дня."
        ),
        "insight": (
            "Здоровье бизнеса в норме: воронка наполнена, просроченных согласований нет. "
            "Точка роста — ускорить переход сделок со стадии КП; следить за планом отгрузки."
        ),
        "qualify": (
            "Оценка отражает заполненность профиля лида и качество канала обращения. "
            "Для целевого лида — быстро назначить менеджера по региону/продукту и выйти "
            "на первый контакт; для нецелевого — уточнить потребность до передачи в воронку."
        ),
        "call_script": (
            "Начните с уточнения потребности и сроков — это задаёт тон. Свяжите цену с "
            "наличием и сроком поставки, предложите конкретный следующий шаг по итогу звонка."
        ),
        "objection": (
            "Признайте сомнение клиента, отразите его своими словами и переведите разговор "
            "на ценность (наличие/сроки/гарантия). Закройте конкретным следующим шагом."
        ),
    }

    def _mock(self, kind: str) -> str:
        return self._MOCKS.get(kind, self._MOCKS["draft"])
