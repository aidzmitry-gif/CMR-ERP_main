"""FastAPI-зависимости ядра."""
from __future__ import annotations

from fastapi import Request

from core.runtime.core import Core


def get_core(request: Request) -> Core:
    """Достать экземпляр ядра из состояния приложения."""
    return request.app.state.core
