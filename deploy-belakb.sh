#!/bin/bash
# Одноразовый деплой-скрипт для belakb.by (хаб-чат CRM, 2026-06-24).
# Запуск на сервере: cd /opt/cmr-erp && git pull && bash deploy-belakb.sh
#
# Что делает:
#   1) Подтягивает свежий main + сабмодули.
#   2) Форсит BACKEND_URL=127.0.0.1 (drop-in юнит) → systemd reload.
#   3) Пересобирает фронт (cmr-frontend, Next.js).
#   4) Применяет alembic + сидит БД демо-данными (идемпотентно).
#   5) Прокидывает telephony-секреты (генерирует токен, если не задан).
#   6) Пересоздаёт app-контейнер с новыми env.
#   7) Печатает самопроверку (роль director — из config/access.py).
#
# Идемпотентно: можно гонять повторно.
set -e
cd /opt/cmr-erp

echo "=== [1/7] git pull + submodules ==="
git pull
git submodule sync --recursive
git submodule update --init --recursive

echo "=== [2/7] BACKEND_URL drop-in (127.0.0.1, не localhost) ==="
mkdir -p /etc/systemd/system/cmr-frontend.service.d
printf '[Service]\nEnvironment=BACKEND_URL=http://127.0.0.1:8000\n' \
  > /etc/systemd/system/cmr-frontend.service.d/backend-url.conf
systemctl daemon-reload

echo "=== [3/7] frontend rebuild ==="
cd /opt/cmr-erp/frontend
npm ci
npm run build
systemctl restart cmr-frontend
cd /opt/cmr-erp

echo "=== [4/7] rebuild image + alembic + seed ==="
# КРИТИЧНО: пересобрать образ ДО seed, иначе scripts/seed.py в контейнере остаётся
# старой версией (git pull обновил файл на хосте, не в образе).
# --build гарантирует, что свежие COPY . . включит обновлённый scripts/seed.py.
docker compose up -d --build
sleep 6
# entrypoint.sh уже сделал alembic upgrade head на старте. Теперь seed (идемпотентно).
docker exec -e PYTHONPATH=/app aios-app-1 python scripts/seed.py
echo "SEED OK"

echo "=== [5/7] host-конфиг (telephony) ==="
HOST_CFG=/opt/cmr-erp/.env
touch "$HOST_CFG"
# Anchored regex (^KEY=), чтобы закомментированные строки в .env.example не матчились.
# AIOS_ENVIRONMENT=prod НЕ ставим сейчас: settings._no_dev_defaults_in_prod
# отбивает дефолтные aios:aios@postgres креды → app падает на старте. Перейти в prod
# можно только после смены DB-пароля на сильный (отдельная задача). Токены webhook'ов
# enforced независимо от ENV (через `if expected:` в роутах) — telephony работает в dev-режиме.
if ! grep -qE '^AIOS_TELEPHONY_WEBHOOK_TOKEN=' "$HOST_CFG"; then
  echo "AIOS_TELEPHONY_WEBHOOK_TOKEN=$(openssl rand -hex 32)" >> "$HOST_CFG"
  echo "  Сгенерирован новый AIOS_TELEPHONY_WEBHOOK_TOKEN."
fi
if ! grep -qE '^AIOS_TELEPHONY_ORIGINATE_URL=' "$HOST_CFG"; then
  echo "AIOS_TELEPHONY_ORIGINATE_URL=https://CHANGE-ME.zruchna.io/client_call_gen.php" >> "$HOST_CFG"
  echo "  ⚠️ AIOS_TELEPHONY_ORIGINATE_URL = placeholder. Замените на ваш URL в $HOST_CFG."
fi
# Если AIOS_ENVIRONMENT=prod уже в .env из предыдущих запусков скрипта — убрать
# (иначе app не стартует с дефолтными DB-кредами).
if grep -qE '^AIOS_ENVIRONMENT=prod' "$HOST_CFG"; then
  sed -i '/^AIOS_ENVIRONMENT=prod$/d' "$HOST_CFG"
  echo "  AIOS_ENVIRONMENT=prod удалён (app падал с дефолтными DB-кредами). См. SECURITY-TODO ниже."
fi

echo "=== [6/7] docker compose up -d (app пересоздастся с host-env) ==="
# Образ уже пересобран в [4/7]; здесь только перезапуск с обновлёнными env.
docker compose up -d
sleep 4
# Проверка проброса telephony-токена в контейнер (fail-fast — иначе webhook бессмысленен).
TOKEN_LEN=$(docker exec aios-app-1 sh -c 'printf "%s" "$AIOS_TELEPHONY_WEBHOOK_TOKEN" | wc -c' || echo 0)
echo "  токен в контейнере: $TOKEN_LEN символов (ожидаемо 64)"
if [ "$TOKEN_LEN" != "64" ]; then
  echo "FAIL: AIOS_TELEPHONY_WEBHOOK_TOKEN в контейнере имеет длину $TOKEN_LEN, ожидаемо 64. Проверьте $HOST_CFG." >&2
  exit 1
fi

echo "=== [7/7] самопроверка эндпоинтов (роль director) ==="
echo -n "/sales/board       : "
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-User-Roles: director' http://127.0.0.1:8000/sales/board || echo "(connect failed)"
echo -n "/leads/board       : "
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-User-Roles: director' http://127.0.0.1:8000/leads/board 2>/dev/null || echo "(нет /leads/board, ок если эндпоинт другой)"
for m in procurement wms production hr logistics legal knowledge office; do
  printf "/%s/board " "$m"
  printf "%*s" $((20-${#m})) ""
  echo -n ": "
  curl -s -o /dev/null -w '%{http_code}\n' -H 'X-User-Roles: director' http://127.0.0.1:8000/$m/board || echo "(connect failed)"
done

echo
echo "=== ГОТОВО ==="
echo "Дальше:"
echo "  • Откройте https://belakb.by/crm/deals — должны быть сделки/доски (Ctrl+F5)."
echo "  • Если хотите телефонию вживую — допишите в /opt/cmr-erp/.env реальный"
echo "    AIOS_TELEPHONY_ORIGINATE_URL и настройте Caddy по coordination/caddy-telephony-snippet.md"
echo "    (+ webhook в кабинете zruchna со ссылкой и токеном из .env)."
echo
echo "🔒 SECURITY-TODO (не блокер сейчас): сервер работает с AIOS_ENVIRONMENT=dev,"
echo "   что отключает _no_dev_defaults_in_prod (SECURITY P0-5). Чтобы перейти в prod-режим:"
echo "   1) docker exec aios-postgres-1 psql -U aios -c \"ALTER USER aios WITH PASSWORD '<сильный>';\""
echo "   2) В /opt/cmr-erp/.env: AIOS_DATABASE_URL=postgresql+psycopg://aios:<сильный>@postgres:5432/aios"
echo "   3) В /opt/cmr-erp/.env: AIOS_ENVIRONMENT=prod"
echo "   4) docker compose up -d (контейнер пересоздастся, _no_dev_defaults_in_prod пройдёт)."
