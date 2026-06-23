# DEPLOY — перенос CRM/ERP на сервер

Стек: **backend** (FastAPI + Postgres 16/pgvector; миграции применяются на старте — `alembic upgrade head`),
**frontend** (Next.js). Прод-режим включается `AIOS_ENVIRONMENT=production` — при нём запрещены
dev-дефолтные креды БД (страховка от деплоя с `aios:aios`).

## 0. Предусловия
- Сервер Linux с Docker + Docker Compose (либо Postgres 16 + Python 3.12 + Node 20 напрямую).
- Домен + TLS через reverse proxy (nginx / Caddy / Traefik) перед backend (`:8000`) и frontend (`:3000`).

## 1. Секреты — `.env` в корне проекта
Скопируйте `.env.example` → `.env` и замените на прод-значения:
```env
AIOS_ENVIRONMENT=production
AIOS_DEBUG=false
AIOS_DATABASE_URL=postgresql+psycopg://<user>:<СИЛЬНЫЙ_ПАРОЛЬ>@postgres:5432/<db>
AIOS_REDIS_URL=redis://redis:6379/0
AIOS_TELEPHONY_WEBHOOK_TOKEN=<длинный-случайный-секрет>   # вебхук АТС
AIOS_INTAKE_WEBHOOK_TOKEN=<длинный-случайный-секрет>      # сайт/почта → лиды
# SMTP / Telegram — по необходимости (см. .env.example)
```
⚠️ НЕ используйте `aios:aios` в проде — прод-гард уронит старт приложения (это и есть страховка).

## 2. База данных + backend
```bash
docker compose up -d postgres redis
docker compose up -d --build app        # uvicorn :8000; миграции применяются автоматически на старте
# (опционально) демо-данные — на чистый прод НЕ нужно:
# docker compose exec app python scripts/seed.py
```
Проверка: `curl https://<домен-backend>/health` → `200`.

## 3. Frontend (Next.js)
```bash
cd frontend
npm ci
BACKEND_URL=http://app:8000 npm run build   # BACKEND_URL — внутренний адрес backend
BACKEND_URL=http://app:8000 npm start        # Next :3000
```
`BACKEND_URL` читается прокси `/api/[...path]` и SSR-фетчами. Можно завернуть фронт в свой Dockerfile —
ключевая прод-переменная одна: `BACKEND_URL`.

## 4. Каналы → лиды → сделка (сквозной поток)
- **Сайт:** контакт-форма шлёт `POST https://<backend>/integrations/web/lead?token=<INTAKE_TOKEN>`
  с полями (JSON или form): `name, company, phone, email, region, product, message`.
- **Почта:** форвардер/вебхук входящих писем → `POST https://<backend>/integrations/email/inbound?token=<INTAKE_TOKEN>`
  с `from, subject, text`.
- **Телефония:** вебхук АТС zruchna → `/integrations/telephony/zruchna?token=<TELEPHONY_TOKEN>`.

Дальше: заявка → **лид** (приём CRM, `/crm/leads`) → квалификация → распределение → конвертация в
**сделку** → продавец ведёт сделку (карточка `/crm/deals/{id}`: документы с записью в 1С, счёт+резерв,
звонки/окно входящего, контакты, AI-ассистент).

## 5. Чеклист готовности
- [x] backend-тесты: `pytest -m "not integration"` — **454 passed**
- [x] frontend прод-сборка: `npm run build` — **80/80 страниц**
- [ ] `.env` заполнен прод-секретами (не dev-дефолты)
- [ ] миграции применены (`alembic upgrade head` — авто на старте `app`)
- [ ] reverse proxy + TLS перед `:8000` и `:3000`
- [ ] вебхуки сайта/почты/АТС настроены с токенами
- [ ] (рекомендуется) реальная аутентификация Keycloak вместо dev-логина

## Известные ограничения (dev-заглушки — заменить в проде)
- **Логин** — dev-переключатель ролей (cookie `aios_user`/`aios_role`). Прод: Keycloak OIDC (заложен в compose).
- **7 экранов Сделок 2.0** (каталог-подбор, реестр/архив документов, постоянные клиенты, статус отгрузки,
  валовая прибыль, конструктор плана) — на demo-данных, ждут подключения backend по каждому.
- **1С / склад / ЕГР** — mock-шлюзы (контракты заложены, подключаются реальными коннекторами).
