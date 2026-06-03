"""Реестр включённых модулей.

Простой список для соло-старта. Позже — Python entry points (``importlib.metadata``,
группа ``aios.modules``), чтобы модуль можно было ``pip install`` отдельным пакетом
(см. §2.3). Отключение модуля = убрать его из списка: его роуты, обработчики,
процессы и миграции просто не регистрируются, система спокойно стартует без него.
"""
ENABLED_MODULES: list[str] = [
    "sales",
    "integrations",
    "procurement",
    "production",
    "wms",
    "logistics",
    "finance",
    "marketing",
]
