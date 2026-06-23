"""Настройки приложения (env-driven), Pydantic Settings.

Переменные читаются из окружения с префиксом ``AIOS_`` и/или из файла ``.env``.
Поля БД/Redis заполняются по мере подключения инфраструктуры (часть 1+).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AIOS_", extra="ignore")

    app_name: str = "AI-First Business OS"
    environment: str = "dev"
    debug: bool = True

    # инфраструктура (наполняется в части 1+)
    database_url: str = "postgresql+psycopg://aios:aios@localhost:5432/aios"
    redis_url: str = "redis://localhost:6379/0"
    # базовый URL 1С (OData/REST); пусто — используется mock-источник
    onec_base_url: str = ""

    # AI-слой (Итерация 1) — за feature-flag; в прототипе выключен
    ai_enabled: bool = False
    # шлюз LLM (LiteLLM/Ollama, OpenAI-совместимый); пусто — mock-режим без модели
    llm_base_url: str = ""
    llm_model: str = "qwen2.5"

    # Рассылка перевозчикам о тендере (Логистика). По умолчанию канал только логирует
    # (MVP); реальная доставка включается, когда заданы SMTP/Telegram (за конфигом).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@aios.local"
    smtp_tls: bool = True
    telegram_bot_token: str = ""

    # Телефония (облачная АТС zruchna): входящий webhook + исходящий click-to-call.
    # Webhook аутентифицируется общим секретом ``?token=`` — если задан, входящие
    # без совпадающего токена отбиваются 403 (прод публичен → задавать обязательно).
    # ``originate_url`` — URL инициации звонка (client_call_gen.php), свой на инсталляцию;
    # пусто → исходящий звонок недоступен (503).
    telephony_webhook_token: str = ""
    telephony_originate_url: str = ""


@lru_cache
def get_settings() -> Settings:
    """Закэшированный экземпляр настроек."""
    return Settings()
