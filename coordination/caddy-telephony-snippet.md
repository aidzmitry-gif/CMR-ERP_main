# Caddy snippet для телефонии (belakb.by)

> Вставить ВНУТРЬ существующего сайт-блока `belakb.by { … }` в `/etc/caddy/Caddyfile`,
> **перед** общими `basicauth` и `reverse_proxy`. Затем `caddy reload` (или `systemctl reload caddy`).
> Без этого: (а) zruchna получит 401 на webhook (за Basic-Auth), (б) SSE окно звонка не всплывёт (буферизация).

```caddyfile
# === Телефония: webhook zruchna + originate (без Basic-Auth, обрабатывают app:8000) ===
@telephony path /integrations/telephony/*
handle @telephony {
    reverse_proxy 127.0.0.1:8000
}

# === SSE окна звонка: отключить буферизацию (иначе карточка не всплывёт) ===
@calls_sse path /sales/calls/stream*
handle @calls_sse {
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
        transport http {
            response_header_timeout 0s
        }
    }
}
```

## Проверка после reload

```bash
# 1) Webhook доступен без Basic-Auth (без токена → 401/403, но НЕ HTML логин-формы):
curl -i 'https://belakb.by/integrations/telephony/zruchna' | head -5

# 2) С токеном (после задания AIOS_TELEPHONY_WEBHOOK_TOKEN в .env и docker compose up -d):
TOKEN="<ваш-секрет-из-host-env>"
curl -i "https://belakb.by/integrations/telephony/zruchna?token=${TOKEN}&type=in&direct=in&uniqueid=TEST1&phone=375291234567&did=375171234567"
# Ожидаемо: {"ok":true,"event":"telephony.call.incoming","call_id":"TEST1"}

# 3) Журнал звонков (через Basic-Auth + роль sales):
curl -u "dima:<ваш-пароль>" -H "X-User-Roles: director" https://belakb.by/api/sales/calls | head -c 500
```
