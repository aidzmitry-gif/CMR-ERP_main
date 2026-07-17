# OIDC flip readiness (2026-07-17)

> **Флип выполнен (auth only):** `AIOS_AUTH_MODE=oidc`, `AIOS_ENVIRONMENT=dev`.  
> `prod` — ещё нет.

## Уже зелёное

| Проверка | Результат |
|----------|-----------|
| Issuer | `https://auth.belakb.by/realms/aios` openid **200** |
| Token (password grant, user `dima`) | `iss`/`aud` (`aios-backend`) / roles ⊇ `director` |
| FE OIDC start / PKCE / refresh | OK |
| App | `AIOS_AUTH_MODE=oidc`, JWKS `http://keycloak:8080/.../certs` |
| Bearer-only `/sales/board` | **200**, 11 stages |
| `X-User-Roles` only | **403** (ожидаемо) |
| FE proxy cookie → board | **200** |
| FE | `NEXT_PUBLIC_AUTH_MODE=oidc` |

## Rollback

```bash
cd /opt/cmr-erp
# в .env: AIOS_AUTH_MODE=dev
docker compose up -d --force-recreate app
# FE drop-in NEXT_PUBLIC_AUTH_MODE=dev + rebuild
```

Бэкапы на сервере: `/tmp/cmr.env.bak.flip`, `/tmp/dc.override.bak.flip`.

## Остатки

- Ручной клик SSO за Caddy Basic Auth
- Сменить пароль Keycloak `dima`
- Когда готовы: `AIOS_ENVIRONMENT=prod` (см. `secure-env-prep.md`)
