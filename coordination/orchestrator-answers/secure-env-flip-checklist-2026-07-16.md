# Secure-env flip checklist (Track D) — 2026-07-16

> **Решение этой полосы:** НЕ менять `AIOS_ENVIRONMENT` / `AIOS_AUTH_MODE` и НЕ делать `ALTER USER` сейчас.  
> Ниже — готовность к флипу и явные блокеры. Runbook: `coordination/secure-env-prep.md`.

## Текущее состояние (прод `/opt/cmr-erp`)

| Пункт | Статус |
|-------|--------|
| HEAD | `0c585d1` `main` |
| App env | `AIOS_ENVIRONMENT=dev`, `AIOS_AUTH_MODE=dev` |
| Keycloak realm/client/Audience/`director` | ✅ сделано |
| Стабильный `PUBLIC_KC_HOST` / `KC_HOSTNAME` | ❌ (ephemeral cloudflared или нет DNS) |
| Фронт Bearer / OIDC login | ❌ (только cookie `aios_role` → `X-User-Roles`) |
| DB password ≠ `aios` + override `KC_DB_PASSWORD` | ❌ отложено (нужно синхронно с app restart) |
| `AIOS_KEYCLOAK_ISSUER` / `AUDIENCE` в app env | пустые (ок для `dev`) |

## Плейсхолдеры (заполнить оператором перед флипом)

```
DB_PASS=__________
PUBLIC_KC_HOST=auth.belakb.by   # Caddy готов; DNS A→93.125.0.131 ещё нужен
ISSUER=https://auth.belakb.by/realms/aios
```

## Порядок флипа (когда A+B зелёные) — НЕ выполнять сейчас

1. Стабильный issuer (Caddy subdomain / named tunnel) + `KC_HOSTNAME` в untracked override.
2. Frontend пробрасывает `Authorization: Bearer` и умеет получить токен (минимум).
3. Сгенерировать `DB_PASS`, `ALTER USER`, override `KC_DB_PASSWORD`, restart keycloak.
4. Записать в `.env` блок prod/oidc/issuer/audience/DATABASE_URL (без коммита).
5. JWKS 200 из app-контейнера к `ISSUER`.
6. Только тогда: recreate **app** с новым env + смоук логина UI.
7. Откат: вернуть `.env` на dev + recreate app (см. runbook).

## Сознательно НЕ сделано в этой 8h-сессии

- ❌ `AIOS_ENVIRONMENT=prod`
- ❌ `AIOS_AUTH_MODE=oidc`
- ❌ смена пароля Postgres / `KC_DB_PASSWORD` (риск рассинхрона с живым app)
- ❌ смена Keycloak admin password (можно отдельно, не блокирует UI)

## DoD Track D

- [x] Чеклист и стопы зафиксированы
- [x] App остаётся `dev`/`dev`
- [ ] PUBLIC_KC_HOST заполнен (ждём Track A)
- [ ] Frontend Bearer (ждём Track B)
