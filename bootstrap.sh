#!/usr/bin/env bash
# Поднять супер-проект CMR-ERP_main после клона (--recurse-submodules).
#
# Стек: FastAPI/uvicorn + SQLAlchemy(async) + Alembic; инфраструктура в docker compose
# (postgres+pgvector, redis, keycloak, app). Контейнер `app` при старте сам применяет
# миграции (alembic upgrade head) и поднимает uvicorn на :8000.
# Фронтенд (frontend/) в compose не входит — запускается отдельно через npm.
set -euo pipefail

# 1) Подтянуть все домены-сабмодули
git submodule update --init --recursive

# 2) Инфраструктура + приложение в контейнерах (миграции применит app-entrypoint)
docker compose up -d --build

# 3) Зависимости фронтенда
if [ -d frontend ]; then ( cd frontend && npm install ); fi

echo
echo "Готово."
echo "  API:      http://localhost:8000"
echo "  Keycloak: http://localhost:8080  (admin/admin)"
echo "  Фронт:    cd frontend && npm run dev"
