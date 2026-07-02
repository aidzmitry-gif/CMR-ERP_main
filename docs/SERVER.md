# Сервер (production / dev host)

> Доступ к серверу, где развёрнут этот проект. Используй эти данные, чтобы быстро подключаться.

## Подключение

- **Способ:** Tailscale SSH (tailscale установлен локально, v1.98.2).
- **Команда (нон-интерактивно):**
  ```powershell
  tailscale ssh root@100.70.224.109 "<команда>"
  ```
- **Хост в Tailscale:** `localhost-0` — owner `aidzmitry@`, Linux.
- **Tailscale IP:** `100.70.224.109`
- **Локальный IP (LAN):** `192.168.89.83/24` (интерфейс `enp12s0`)
- **Пользователь:** `root`
- Проверка связи: `tailscale status` → нода `localhost-0` должна быть онлайн.

## Хост

- **ОС:** Ubuntu 26.04 LTS, ядро `7.0.0-22-generic`, x86-64
- **Hostname:** `localhost.localdomain`
- **Ресурсы:** 61 GiB RAM, диск `/` 1.9 TB (≈6% занято), Docker 29.4.3
- **GitHub remote проекта:** `https://github.com/aidzmitry-gif/CMR-ERP_main.git` (ветка `main`)

## Расположение кода на сервере

- **Проект (стек `aios`):** `/opt/cmr-erp` — это и есть данный CRM/ERP проект (`docker-compose.yml`, ветка `main`).
- Приложение при старте само применяет миграции (`alembic upgrade head`).

## Docker-стеки и порты

| Контейнер | Образ | Порт (host→cont) | Назначение |
|-----------|-------|------------------|------------|
| `aios-app-1` | `aios-app` (build) | `8000→8000` | Backend приложения (FastAPI) |
| `aios-postgres-1` | `pgvector/pgvector:pg16` | `5432→5432` | PostgreSQL + pgvector (db/user/pass: `aios`/`aios`/`aios`) |
| `aios-redis-1` | `redis:7-alpine` | `6379→6379` | Redis |
| `aios-keycloak-1` | `quay.io/keycloak/keycloak:26.0` | `8080→8080` | Keycloak (start-dev, admin/admin) |
| `cloudflared` | `cloudflare/cloudflared:latest` | — | Cloudflare tunnel → `http://localhost:8080` (Keycloak) |
| `ollama` | `ollama/ollama` | `11435→11434` | Ollama LLM |
| `open-webui` | `ghcr.io/open-webui/open-webui:main` | `3000→8080` | Open WebUI |
| `big-bear-filebrowser` | `filebrowser/filebrowser` | `8081→80` | Filebrowser (CasaOS) |

> ⚠️ Дефолтные креды (`aios/aios`, Keycloak `admin/admin`) — это dev-окружение из `docker-compose.yml`. Не считать секретами для прод.

## Частые команды

```powershell
# Статус контейнеров проекта
tailscale ssh root@100.70.224.109 "cd /opt/cmr-erp && docker compose ps"
# Логи приложения
tailscale ssh root@100.70.224.109 "docker logs --tail 100 aios-app-1"
# Обновить и перезапустить стек
tailscale ssh root@100.70.224.109 "cd /opt/cmr-erp && git pull && docker compose up -d --build"
```
