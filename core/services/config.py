"""Сервис конфигурации — тонкая обёртка над настройками из ``config/settings.py``."""
from __future__ import annotations

from config.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
