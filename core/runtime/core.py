"""Ядро-реестр: объект `Core`, в который модули регистрируют свои возможности.

`Core` — это одновременно:
- **реестр** того, что подключено (роуты, события, процессы, права, виджеты);
- **фасад** к общим сервисам (БД, шина событий, Temporal, auth, LiteLLM).

Модули получают `Core` в `register(core)` и работают только через этот фасад,
не обращаясь к внутренностям друг друга (правило границ, §2.4).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from fastapi import APIRouter

from core.runtime.contract import Permission, Reference, Role, TelegramCommand, Widget
from core.services import Services

logger = logging.getLogger("aios.core")


@dataclass
class RegisteredRouter:
    module: str
    prefix: str
    router: APIRouter


@dataclass
class RegisteredWorkflow:
    module: str
    name: str
    workflow: type


@dataclass
class RegisteredEvent:
    module: str
    event_type: str
    handler: Callable


@dataclass
class RegisteredReference:
    module: str
    reference: Reference


class Core:
    """Реестр возможностей модулей и фасад к общим сервисам."""

    def __init__(self, services: Services) -> None:
        self.services = services
        self.config = services.config
        self.event_bus = services.event_bus

        self.routers: list[RegisteredRouter] = []
        self.workflows: list[RegisteredWorkflow] = []
        self.events: list[RegisteredEvent] = []
        self.permissions: list[Permission] = []
        self.roles: list[Role] = []
        self.telegram_commands: list[TelegramCommand] = []
        self.widgets: list[Widget] = []
        self.references: list[RegisteredReference] = []
        self.startup_hooks: list[Callable[[], Awaitable | None]] = []
        self.shutdown_hooks: list[Callable[[], Awaitable | None]] = []
        self.loaded_modules: list[str] = []

        # имя регистрирующегося сейчас модуля — выставляется загрузчиком,
        # чтобы регистрации автоматически атрибутировались модулю.
        self._current: str | None = None

    # --- служебное: контекст текущего модуля (используется загрузчиком) ---
    def _begin(self, name: str) -> None:
        self._current = name

    def _end(self, name: str) -> None:
        if name not in self.loaded_modules:
            self.loaded_modules.append(name)
        self._current = None

    @property
    def _module(self) -> str:
        return self._current or "<unknown>"

    # --- API регистрации (вызывается модулями внутри register()) ---
    def include_router(self, router: APIRouter, *, prefix: str | None = None) -> None:
        """Подключить FastAPI-роутер модуля под префиксом."""
        self.routers.append(RegisteredRouter(self._module, prefix or "", router))

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Подписать обработчик на событие шины."""
        self.event_bus.subscribe(event_type, handler)
        self.events.append(RegisteredEvent(self._module, event_type, handler))

    def register_workflow(self, name: str, workflow: type) -> None:
        """Зарегистрировать процесс (Temporal workflow); реальный воркер — часть 4."""
        self.workflows.append(RegisteredWorkflow(self._module, name, workflow))

    def declare_permissions(self, permissions: list[Permission]) -> None:
        """Объявить разрешения RBAC модуля."""
        self.permissions.extend(permissions)

    def declare_role(self, role: Role) -> None:
        """Объявить роль RBAC модуля."""
        self.roles.append(role)

    def register_telegram(self, command: TelegramCommand) -> None:
        """Зарегистрировать Telegram-команду модуля."""
        self.telegram_commands.append(command)

    def register_widget(self, widget: Widget) -> None:
        """Зарегистрировать виджет панели владельца."""
        self.widgets.append(widget)

    def register_reference(self, reference: Reference) -> None:
        """Зарегистрировать справочник в реестре-витрине «Справочники».

        Данные остаются у владельца; реестр хранит только метаданные — для UI,
        прав (RBAC) и каталога AI. Атрибутируется текущему модулю автоматически
        (``self._module``), как и остальные регистрации.
        """
        self.references.append(RegisteredReference(self._module, reference))

    def on_startup(self, hook: Callable) -> None:
        """Хук, вызываемый при старте приложения."""
        self.startup_hooks.append(hook)

    def on_shutdown(self, hook: Callable) -> None:
        """Хук, вызываемый при остановке приложения."""
        self.shutdown_hooks.append(hook)
