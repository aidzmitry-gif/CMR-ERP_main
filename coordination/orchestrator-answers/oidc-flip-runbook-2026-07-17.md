# OIDC flip runbook (auth only) — 2026-07-17

> Шаг 1: `AIOS_AUTH_MODE=oidc`, **оставить** `AIOS_ENVIRONMENT=dev`.  
> `prod` — отдельным шагом после смоука (DB уже без `aios:aios`).

## Preflight (уже проверено)

- FE PKCE + cookie → board, silent refresh
- Issuer/audience в `.env`
- JWKS с хоста 200; **из app-контейнера публичный HTTPS hairpin'ит** → нужен
  `AIOS_KEYCLOAK_JWKS_URI=http://keycloak:8080/realms/aios/protocol/openid-connect/certs`
  и/или `extra_hosts: auth.belakb.by:host-gateway`

## Flip

```bash
cd /opt/cmr-erp
# backup
cp -a .env /tmp/cmr.env.bak.$(date +%s)
cp -a docker-compose.override.yml /tmp/dc.override.bak.$(date +%s)

# .env: AUTH_MODE=oidc + JWKS internal (issuer остаётся публичным)
# override: app.extra_hosts auth.belakb.by:host-gateway

docker compose up -d --force-recreate app
curl -sS http://127.0.0.1:8000/health
# Bearer-only board → 200 (не Guest)
```

FE (опционально сразу):

```bash
# systemd drop-in NEXT_PUBLIC_AUTH_MODE=oidc + rebuild cmr-frontend
```

## Rollback

```bash
# restore AIOS_AUTH_MODE=dev in .env
docker compose up -d --force-recreate app
# FE: NEXT_PUBLIC_AUTH_MODE=dev + rebuild
```
