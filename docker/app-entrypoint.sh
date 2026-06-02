#!/bin/sh
set -e

echo "Применяю миграции (alembic upgrade head)..."
alembic upgrade head

echo "Запускаю API..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
