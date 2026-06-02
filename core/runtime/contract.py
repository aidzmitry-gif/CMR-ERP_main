"""Контракт модуля — единственный интерфейс между ядром и модулем-плагином.

Ядро не знает о внутренностях модуля: только про этот контракт. Любой модуль —
это Python-пакет с `module.py`, который реализует `ModuleContract` и через
`register(core)` отдаёт ядру свои возможности: API-роутер, обработчики событий,
процессы (Temporal), миграции, права (RBAC), Telegram-команды, виджеты панели
владельца и хуки жизненного цикла.

См. «Архитектура_и_план_AI-First_OS.md», §2.2–2.4.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from core.runtime.core import Core


@dataclass(frozen=True)
class Permission:
    """Разрешение RBAC, объявляемое модулем. Пример кода: ``sales.deal.read``."""

    code: str
    description: str = ""


@dataclass(frozen=True)
class Role:
    """Роль RBAC и набор её разрешений. Пример: «Менеджер»."""

    name: str
    permissions: tuple[str, ...] = ()


@dataclass(frozen=True)
class TelegramCommand:
    """Команда Telegram-бота, регистрируемая модулем (бот — часть 11)."""

    command: str
    description: str
    handler: Callable[..., object]


@dataclass(frozen=True)
class Widget:
    """Вклад модуля в панель владельца (AI Control Tower, часть 11)."""

    key: str
    title: str
    source: str = ""  # идентификатор источника данных, наполняется позже


class ModuleContract(ABC):
    """Базовый класс модуля-плагина.

    Подкласс объявляет метаданные (`name`, `version`, `api_prefix`) и реализует
    `register`, где регистрирует свои возможности в ядре. Имя `name` должно
    совпадать с именем пакета модуля в каталоге ``modules/``.
    """

    #: машинное имя модуля = имя пакета в modules/ ("sales")
    name: str
    #: версия модуля
    version: str = "0.1.0"
    #: префикс монтирования API-роутера ("/sales"); None — модуль без HTTP-API
    api_prefix: str | None = None

    @abstractmethod
    def register(self, core: "Core") -> None:
        """Зарегистрировать возможности модуля в ядре."""
        raise NotImplementedError
