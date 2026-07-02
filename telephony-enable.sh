#!/bin/bash
# Включает телефонию zruchna на сервере belakb.by.
# Запуск (после bash deploy-belakb.sh, на сервере с правами root):
#   ZRUCHNA_URL='https://your-pbx.zruchna.com/client_call_gen.php' bash telephony-enable.sh
# Можно без ZRUCHNA_URL — тогда originate останется placeholder.
#
# Что делает:
#   1) Подставляет ваш ZRUCHNA_URL в /opt/cmr-erp/.env (если задан).
#   2) Перезапускает app-контейнер (подхватит новый URL).
#   3) Вставляет блок в /etc/caddy/Caddyfile (пропуск /integrations/telephony/*
#      из Basic-Auth + flush для SSE), если он ещё не там.
#   4) Перезагружает Caddy.
#   5) Печатает webhook URL для регистрации в кабинете zruchna.
# Idempotent. Не трогает уже корректные блоки.
set -e
HOST_CFG=/opt/cmr-erp/.env
CADDYFILE=/etc/caddy/Caddyfile

if [ ! -f "$HOST_CFG" ]; then
  echo "FAIL: $HOST_CFG не найден. Сперва запустите bash deploy-belakb.sh." >&2
  exit 1
fi

echo "=== [1/5] zruchna URL → $HOST_CFG ==="
if [ -n "${ZRUCHNA_URL:-}" ]; then
  if grep -qE '^AIOS_TELEPHONY_ORIGINATE_URL=' "$HOST_CFG"; then
    sed -i "s|^AIOS_TELEPHONY_ORIGINATE_URL=.*|AIOS_TELEPHONY_ORIGINATE_URL=$ZRUCHNA_URL|" "$HOST_CFG"
    echo "  AIOS_TELEPHONY_ORIGINATE_URL обновлён."
  else
    echo "AIOS_TELEPHONY_ORIGINATE_URL=$ZRUCHNA_URL" >> "$HOST_CFG"
    echo "  AIOS_TELEPHONY_ORIGINATE_URL добавлен."
  fi
else
  CUR=$(grep -E '^AIOS_TELEPHONY_ORIGINATE_URL=' "$HOST_CFG" | head -1 | cut -d= -f2-)
  if echo "$CUR" | grep -q CHANGE-ME; then
    echo "  ⚠️ originate URL = placeholder ($CUR). Передайте ZRUCHNA_URL='https://...' этому скрипту."
  else
    echo "  originate URL уже задан: $CUR"
  fi
fi

echo "=== [2/5] перезапуск app-контейнера ==="
cd /opt/cmr-erp && docker compose up -d

echo "=== [3/5] патч /etc/caddy/Caddyfile ==="
if [ ! -f "$CADDYFILE" ]; then
  echo "  ⚠️ $CADDYFILE не найден. Caddy не установлен или путь иной."
  echo "  Найдите Caddyfile: find /etc /opt -name Caddyfile 2>/dev/null"
  echo "  И вставьте блок из coordination/caddy-telephony-snippet.md вручную."
elif grep -q 'integrations/telephony' "$CADDYFILE"; then
  echo "  Caddyfile уже содержит блок integrations/telephony — пропускаю."
else
  # Простейшая стратегия: дописать блок в КОНЕЦ файла. Если у вас один сайт-блок belakb.by
  # и matcher @telephony внутри него, разделяемый со skipped Basic-Auth — иначе скрипт
  # выйдет и попросит вставить вручную (предупреждение ниже).
  cp "$CADDYFILE" "$CADDYFILE.bak-$(date +%s)"
  echo "  Бэкап: $CADDYFILE.bak-*"
  cat >> "$CADDYFILE" <<'CADDY_EOF'

# === Телефония (добавлено telephony-enable.sh) ===
# ВНИМАНИЕ: если ваш сайт-блок belakb.by уже использует basicauth глобально,
# эти matcher'ы должны быть ВНУТРИ него и ПЕРЕД директивой basicauth.
# Тогда переместите блок и удалите этот хвост.
(telephony_bypass) {
    @telephony path /integrations/telephony/*
    handle @telephony {
        reverse_proxy 127.0.0.1:8000
    }
    @calls_sse path /sales/calls/stream*
    handle @calls_sse {
        reverse_proxy 127.0.0.1:8000 {
            flush_interval -1
        }
    }
}
CADDY_EOF
  echo "  Блок добавлен в конец Caddyfile (snippet 'telephony_bypass')."
  echo "  ⚠️ Snippet нужно ИМПОРТИРОВАТЬ внутри вашего сайт-блока belakb.by"
  echo "     ДО директивы basicauth. Например, добавьте 'import telephony_bypass'"
  echo "     в начало блока belakb.by { ... } и перезагрузите."
fi

echo "=== [4/5] reload Caddy ==="
if systemctl is-active --quiet caddy; then
  systemctl reload caddy && echo "  caddy reload OK"
else
  echo "  ⚠️ caddy systemd-unit не активен. Запустите 'systemctl status caddy' и проверьте."
fi

echo "=== [5/5] webhook URL для регистрации в zruchna ==="
TOKEN=$(grep -E '^AIOS_TELEPHONY_WEBHOOK_TOKEN=' "$HOST_CFG" | head -1 | cut -d= -f2-)
if [ -n "$TOKEN" ]; then
  echo
  echo "  В кабинете zruchna зарегистрируйте webhook:"
  echo "    https://belakb.by/integrations/telephony/zruchna?token=$TOKEN"
  echo
  echo "  zruchna должен слать события на каждый этап (in/dial→answer→hangup)"
  echo "  с одним uniqueid; формат — GET-query или x-www-form-urlencoded/JSON."
  echo "  ⚠️ НЕ multipart/form-data — поля придут пустыми."
else
  echo "  ⚠️ AIOS_TELEPHONY_WEBHOOK_TOKEN не найден. Запустите deploy-belakb.sh."
fi

echo
echo "=== Тест входящего вебхука (после регистрации) ==="
echo "curl -i 'https://belakb.by/integrations/telephony/zruchna?token=$TOKEN&type=in&direct=in&uniqueid=TEST1&phone=375291234567&did=375171234567'"
echo "  Ожидаемо: {\"ok\":true,\"event\":\"telephony.call.incoming\",\"call_id\":\"TEST1\"}"
echo
echo "=== Тест исходящего (originate) ==="
echo "curl -X POST 'https://belakb.by/integrations/telephony/originate' \\"
echo "  -H 'X-User-Roles: director' -H 'Content-Type: application/json' \\"
echo "  -d '{\"vnut\":\"<внутр.номер_сотрудника>\",\"number\":\"375291234567\"}'"
echo "  503 = ORIGINATE_URL не задан. 502 = zruchna не отвечает (проверьте URL)."
