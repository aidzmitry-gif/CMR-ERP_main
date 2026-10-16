#!/bin/sh
set -e

if [ "${AIOS_SKIP_AUTOMIGRATE:-0}" = "1" ]; then
    echo "Автоматическая миграция отключена для контролируемого запуска"
else
    echo "Применяю миграции (alembic upgrade head)..."
    alembic upgrade head
fi

echo "Запускаю API..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
