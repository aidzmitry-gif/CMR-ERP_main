"""Точка входа приложения.

Запуск для разработки:  ``uvicorn main:app --reload``
"""
from core.runtime.app import create_app

app = create_app()
