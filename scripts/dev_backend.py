"""Dev-вход бэкенда: env-дефолты + uvicorn с --reload.

Отдельный файл, а не `python -c "..."`: реловодер uvicorn перезапускает процесс
по sys.argv, и с `-c` respawn ломается (порт так и не поднимается). Используется
launch.json (конфигурация backend) и scripts/dev-servers.ps1.
"""
import os
import sys

# Скрипт лежит в scripts/ → sys.path[0] указывает туда, и дочерний процесс
# реловодера не находит модуль `main`. Работаем из корня проекта явно.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

os.environ.setdefault("AIOS_DATABASE_URL", "sqlite+aiosqlite:///./dev.db")
os.environ.setdefault("AIOS_ENVIRONMENT", "dev")

import uvicorn  # noqa: E402  — после env-дефолтов

if __name__ == "__main__":
    uvicorn.run("main:app", port=8000, reload=True)
