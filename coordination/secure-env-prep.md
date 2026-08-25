# Secure-env prep (только окружение)

> **Область:** `/opt/cmr-erp`, стек `aios`.  
> **Делать:** `.env` + untracked override для Keycloak DB-пароля + realm/client Keycloak + смена пароля Postgres.  
> **НЕ делать:** `git pull` / `checkout` / `push`, смена ветки `main`, `docker compose build` / `--build` app.  
> Деплой кода — **отдельным шагом** после пуша релиза в `main`.

Сверено с `config/settings.py` (`_no_dev_defaults_in_prod`), `docker-compose.yml` (substitution `${AIOS_…}`, **хардкод** `KC_DB_PASSWORD: aios`).

---

## Цель

При `AIOS_ENVIRONMENT=prod` app стартует только если:

| Переменная | Требование |
|------------|------------|
| `AIOS_AUTH_MODE` | `oidc` |
| `AIOS_DATABASE_URL` | **без** подстроки `aios:aios@` |
| `AIOS_KEYCLOAK_ISSUER` | непустой, = claim `iss` в токене |
| `AIOS_KEYCLOAK_AUDIENCE` | непустой, = `aud` в токене (= client_id + Audience mapper) |

Секреты только на сервере. `.env` в `.gitignore` (untracked).

---

## Предусловия

1. Сервер online (LAN/`tailscale status` → `localhost-0` active).
2. `cd /opt/cmr-erp && docker compose ps` — postgres, redis, keycloak, app UP.
3. Committed локальный `docker-compose.override.yml` (порты 5433/8001) на сервере **не использовать**. Если файл есть и ремапит порты — убрать/переименовать **или** заменить своим untracked override **без** порт-ремапа (см. Шаг 3).
4. Зафиксировать плейсхолдеры **до** команд:

```
DB_PASS=__________          # сильный пароль (один для ALTER USER и KC_DB_PASSWORD)
REALM=aios
CLIENT_ID=aios-backend      # → AIOS_KEYCLOAK_AUDIENCE
PUBLIC_KC_HOST=__________   # хост, под которым браузер/cloudflared видит Keycloak
ISSUER=https://<PUBLIC_KC_HOST>/realms/aios   # без хвостового /
```

### Уже сделано на сервере (2026-07-16, без флипа app→prod)

- Realm **`aios`** создан (Admin API).
- Client **`aios-backend`** (public) + protocol mapper **`aud-aios-backend`** (Audience → access token).
- Realm role **`director`**.
- OpenID discovery: `http://127.0.0.1:8080/realms/aios/.well-known/openid-configuration` → 200.
- Caddy: блок **`auth.belakb.by`** → `127.0.0.1:8080` (без Basic-Auth). Override: `KC_HOSTNAME=https://auth.belakb.by`.
- ✅ **DNS + TLS (2026-07-17):** `A auth.belakb.by → 93.125.0.131`; LE-сертификат получен; `https://auth.belakb.by/realms/aios/.well-known/openid-configuration` → **200**, `issuer=https://auth.belakb.by/realms/aios`.
- ⚠ App по-прежнему `AIOS_ENVIRONMENT=dev` / `AIOS_AUTH_MODE=dev` (фронт: Bearer-скелет есть, полного Keycloak login нет; флип = 401 на UI).
- Плейсхолдер: `PUBLIC_KC_HOST=auth.belakb.by`, `ISSUER=https://auth.belakb.by/realms/aios`.

---

## Шаг 0 — диагностика (read-only)

```bash
cd /opt/cmr-erp
echo "=== git (не менять) ===" && git rev-parse --abbrev-ref HEAD && git rev-parse --short HEAD
echo "=== compose AIOS lines ===" && grep -E 'AIOS_ENVIRONMENT|AIOS_AUTH_MODE|KC_DB_PASSWORD' docker-compose.yml
echo "=== override / .env ===" && ls -la .env docker-compose.override.yml 2>/dev/null || true
echo "=== runtime env app ===" && docker compose exec -T app printenv | grep -E 'AIOS_ENVIRONMENT|AIOS_AUTH_MODE|AIOS_KEYCLOAK|AIOS_DATABASE' || true
echo "=== ports ===" && docker compose config | grep -A2 'ports:'
```

Ожидание: в `docker-compose.yml` у app — `${AIOS_…}`; у keycloak — литерал `KC_DB_PASSWORD: aios` → пароль KC меняется **только через override**, не через host-`.env` alone.

---

## Шаг 1 — Keycloak: realm, client, Audience mapper

Админка: порт `8080` (или публичный URL), сейчас `admin`/`admin` → **сразу сменить пароль admin**.

1. **Realm** → Create realm → имя `aios` (или свой; войдёт в issuer).
2. **Client** → Create → Client ID = `aios-backend` (= будущий `AIOS_KEYCLOAK_AUDIENCE`).
   - Для SPA/фронта обычно public + Standard flow; confidential — если нужен client_secret.
3. **Audience mapper (обязательно):**  
   Client → Client scopes / Dedicated → Add mapper → **Audience**  
   - Included Client Audience = `aios-backend`  
   - Add to access token = ON  
   Без этого Keycloak **не кладёт** client_id в `aud` → app отбивает все JWT (SEC-001).
4. **Роль + пользователь:** realm role минимум `director`; user с паролем (temporary Off), назначить роль.
5. **Стабильный `iss`:** в env Keycloak (через тот же untracked override, Шаг 3) задать  
   `KC_HOSTNAME=<PUBLIC_KC_HOST>`  
   и/или Realm settings → Frontend URL = `https://<PUBLIC_KC_HOST>`.  
   Тогда `iss` = `https://<PUBLIC_KC_HOST>/realms/aios` независимо от входа через docker-имя.

Проверка токена (после логина): в access token есть `"aud": "aios-backend"` (или массив с этим значением) и `"iss": "<ISSUER>"` посимвольно.

> KC на Postgres (`KC_DB_URL …/keycloak`) — realm в БД переживает recreate контейнера. Том `pgdata` не сносить.

---

## Шаг 2 — файл `/opt/cmr-erp/.env` (untracked)

```env
AIOS_ENVIRONMENT=prod
AIOS_AUTH_MODE=oidc
AIOS_DATABASE_URL=postgresql+psycopg://aios:<DB_PASS>@postgres:5432/aios
AIOS_REDIS_URL=redis://redis:6379/0
AIOS_KEYCLOAK_ISSUER=https://<PUBLIC_KC_HOST>/realms/aios
AIOS_KEYCLOAK_AUDIENCE=aios-backend
# телефония/intake — пусто = graceful off
AIOS_TELEPHONY_WEBHOOK_TOKEN=
AIOS_TELEPHONY_ORIGINATE_URL=
```

Права: `chmod 600 .env`. В git не добавлять.

---

## Шаг 3 — untracked override: пароль БД для Keycloak (+ hostname)

`KC_DB_PASSWORD` в базовом compose **захардкожен** → host-`.env` его **не перебьёт**. Нужен файл рядом:

`/opt/cmr-erp/docker-compose.override.yml` (**untracked**, без ремапа портов 5433/8001):

```yaml
# Прод secure-env — НЕ коммитить. Порты не трогаем (остаются 8000/8080/5432 loopback из базы).
services:
  keycloak:
    environment:
      KC_DB_PASSWORD: "<DB_PASS>"
      KC_HOSTNAME: "<PUBLIC_KC_HOST>"
      # опционально, если нужен https в iss:
      # KC_HOSTNAME_STRICT: "false"
      # KC_PROXY_HEADERS: "xforwarded"
```

Если на сервере уже лежит **локальный** override с `5433`/`8001` — заменить этим содержимым или удалить старый (`mv docker-compose.override.yml docker-compose.override.yml.localbak`).

Проверка слияния (ещё **до** ALTER):

```bash
cd /opt/cmr-erp
docker compose config | grep -E 'KC_DB_PASSWORD|KC_HOSTNAME|AIOS_ENVIRONMENT|AIOS_AUTH_MODE|AIOS_DATABASE_URL|AIOS_KEYCLOAK'
```

В выводе: `KC_DB_PASSWORD` = новый пароль (не `aios`), AIOS_* из `.env`.

---

## Шаг 4 — смена пароля Postgres + рестарт только Keycloak

`POSTGRES_PASSWORD` в env на уже созданный том **не влияет**. Меняем роль:

```bash
cd /opt/cmr-erp
# 1) пароль пользователя aios (им ходят и app, и keycloak)
docker compose exec -T postgres psql -U aios -d aios -c "ALTER USER aios WITH PASSWORD '<DB_PASS>';"

# 2) Keycloak подхватит новый KC_DB_PASSWORD из override
docker compose up -d keycloak

# 3) Keycloak жив и логинится в БД
docker compose ps keycloak
docker compose logs --tail 40 keycloak
```

**Не** делать `docker compose up -d --build` и **не** рестартовать app на этом шаге (код/образ — позже).  
Учти: пока app не перезапущен с новым `AIOS_DATABASE_URL`, при обрыве пула коннектов app может начать падать на auth к БД — окно до выката держать коротким или сразу планировать деплой.

---

## Шаг 5 — JWKS / OpenID discovery из app-контейнера

Issuer должен открываться **из сети app** (не только с ноутбука):

```bash
cd /opt/cmr-erp
ISSUER='https://<PUBLIC_KC_HOST>/realms/aios'   # тот же, что в .env

docker compose exec -T app python -c "
import urllib.request, sys
u = sys.argv[1].rstrip('/') + '/.well-known/openid-configuration'
print('GET', u)
r = urllib.request.urlopen(u, timeout=15)
print('status', r.status)
body = r.read(200)
print(body[:200])
" "$ISSUER"

docker compose exec -T app python -c "
import urllib.request, sys
u = sys.argv[1].rstrip('/') + '/protocol/openid-connect/certs'
print('GET', u)
print('status', urllib.request.urlopen(u, timeout=15).status)
" "$ISSUER"
```

Ожидание: оба `status 200`. Если нет — чинить DNS/egress/`KC_HOSTNAME`/прокси, иначе после флипа в oidc app не проверит JWT.

---

## Шаг 6 — итоговая проверка env (без рестарта app) и СТОП

```bash
cd /opt/cmr-erp
echo "=== compose config (подстановка) ==="
docker compose config | grep -E 'AIOS_ENVIRONMENT|AIOS_DATABASE_URL|AIOS_AUTH_MODE|AIOS_KEYCLOAK|KC_DB_PASSWORD'

echo "=== git не трогали ==="
git status --short
git rev-parse --abbrev-ref HEAD
```

### DoD этого этапа

- [ ] `AIOS_ENVIRONMENT=prod`
- [ ] `AIOS_AUTH_MODE=oidc`
- [ ] `AIOS_DATABASE_URL` без `aios:aios@`
- [ ] `AIOS_KEYCLOAK_ISSUER` и `AIOS_KEYCLOAK_AUDIENCE` заполнены
- [ ] `KC_DB_PASSWORD` в `compose config` = новый (не литерал `aios` из базы)
- [ ] openid-configuration + certs = 200 из app
- [ ] Audience mapper включён
- [ ] `git status` без неожиданных tracked-изменений кода; ветка та же (`main` не переключали)
- [ ] app **не** пересобирали

**Остановиться.** Прислать координатору: вывод Шага 6 + статусы JWKS (Шаг 5).

---

## Что сознательно НЕ в этом runbook

| Действие | Когда |
|----------|--------|
| `git pull` / смена `main` | После пуша релиза координатором |
| `docker compose up -d --build` app | Вместе с выкатом кода (`RELEASE.md` §4–5) |
| Смоук логина OIDC в UI | После рестарта app с новым env |
| Перевод Keycloak с `start-dev` на `start` | Отдельный hardening |

---

## Откат env (если что-то пошло не так до выката)

```bash
# вернуть пароль aios (если ещё помните/есть бэкап) или оставить новый и поправить файлы
mv .env .env.bad
mv docker-compose.override.yml docker-compose.override.yml.bad
# при необходимости: ALTER USER aios PASSWORD 'aios';
docker compose up -d keycloak
```

App при `environment=dev` (дефолт compose без `.env`) снова поднимется в header-trust — **только** как аварийный откат, не оставлять на публичном хосте.
