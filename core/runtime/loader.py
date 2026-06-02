"""Загрузчик модулей: по списку ENABLED_MODULES импортирует пакеты и вызывает register().

На старте — простой реестр в конфиге (соло-вариант). Контракт спроектирован так,
что позже загрузку можно перевести на Python entry points (`importlib.metadata`,
группа ``aios.modules``) без изменения самих модулей (см. §2.3 архитектуры).
"""
from __future__ import annotations

import importlib
import logging

from core.runtime.contract import ModuleContract
from core.runtime.core import Core

logger = logging.getLogger("aios.loader")


def _resolve_module(name: str) -> ModuleContract:
    """Импортировать ``modules.<name>.module`` и получить экземпляр модуля.

    Соглашение: пакет модуля экспонирует фабрику ``get_module() -> ModuleContract``.
    """
    pkg = importlib.import_module(f"modules.{name}.module")
    if not hasattr(pkg, "get_module"):
        raise RuntimeError(
            f"Модуль '{name}': в modules/{name}/module.py нет функции get_module()"
        )
    module = pkg.get_module()
    if not isinstance(module, ModuleContract):
        raise TypeError(
            f"Модуль '{name}': get_module() вернул не ModuleContract ({type(module)!r})"
        )
    return module


def load_modules(core: Core, enabled: list[str]) -> None:
    """Загрузить и зарегистрировать все включённые модули."""
    logger.info("Загрузка модулей: %s", ", ".join(enabled) or "(пусто)")
    for name in enabled:
        module = _resolve_module(name)
        core._begin(module.name)
        module.register(core)
        core._end(module.name)
        logger.info(
            "  + %s v%s  роуты:%d события:%d workflow:%d",
            module.name,
            module.version,
            sum(1 for r in core.routers if r.module == module.name),
            sum(1 for e in core.events if e.module == module.name),
            sum(1 for w in core.workflows if w.module == module.name),
        )
    logger.info("Готово: загружено модулей — %d", len(core.loaded_modules))
