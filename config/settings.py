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


@lru_cache
def get_settings() -> Settings:
    """Закэшированный экземпляр настроек."""
    return Settings()
