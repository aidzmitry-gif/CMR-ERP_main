"""Настройки приложения (env-driven), Pydantic Settings.

Переменные читаются из окружения с префиксом ``AIOS_`` и/или из файла ``.env``.
Поля БД/Redis заполняются по мере подключения инфраструктуры (часть 1+).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AIOS_", extra="ignore")

    app_name: str = "AI-First Business OS"
    # Безопасные дефолты: прод не должен случайно унаследовать dev-режим.
    # Для локальной разработки выставить AIOS_ENVIRONMENT=dev и AIOS_DEBUG=true.
    environment: str = "prod"
    debug: bool = False

    # инфраструктура (наполняется в части 1+)
    database_url: str = "postgresql+psycopg://aios:aios@localhost:5432/aios"
    redis_url: str = "redis://localhost:6379/0"
    # базовый URL 1С (OData/REST); пусто — используется mock-источник
    onec_base_url: str = ""
    # HTTP Basic для OData (только чтение). Секреты — в env/сервере, не в git.
    onec_user: str = ""
    onec_password: str = ""
    # базовый URL сервиса ЕГР РБ (lookup реквизитов по УНП); пусто — mock-справочник
    egr_base_url: str = ""
    # Альфа-Банк (host-to-host): входящие зачисления клиентов для авто-проводки оплат.
    # Пусто → шлюз отдаёт [] (честная деградация, не выдумываем оплаты). Реальные вызовы —
    # слайс 3 (нужны договор + сертификат/токен от банка). Секреты — только через env/.env.
    alfa_base_url: str = ""
    alfa_token: str = ""
    alfa_account: str = ""

    # AuthN (SECURITY.md P1 — Keycloak/OIDC). ``auth_mode``:
    #   "dev"  — доверять заголовку X-User-Roles (текущее поведение dev и прода, пока realm
    #            Keycloak не заведён); "oidc" — принимать ТОЛЬКО проверенный Bearer-JWT Keycloak.
    # Дефолт "dev" — аддитивно для локали/тестов. ⚠️ Прод (environment≠dev) НЕ загрузится без
    # oidc + issuer + audience (см. валидатор ниже) — намеренный security-гейт: доверие заголовку
    # в публичном проде = вход суперпользователем без пароля.
    auth_mode: str = "dev"
    keycloak_issuer: str = ""    # https://<host>/realms/<realm>; пусто → oidc недоступен
    keycloak_audience: str = ""  # ожидаемый aud (client_id) в токене
    # Опционально: JWKS URL внутри Docker-сети (http://keycloak:8080/.../certs), если
    # публичный hostname hairpin'ит с контейнера (ECONNREFUSED на свой public IP).
    # iss/aud по-прежнему сверяются с keycloak_issuer / keycloak_audience.
    keycloak_jwks_uri: str = ""
    # Keycloak Admin API для приглашений сотрудников. Используется service account
    # отдельного confidential-client с realm-management правами; пароль bootstrap-admin
    # приложению не передаём. Пустой набор → endpoint приглашений честно отвечает 503.
    keycloak_admin_base_url: str = ""
    keycloak_admin_realm: str = "aios"
    keycloak_admin_client_id: str = ""
    keycloak_admin_client_secret: str = ""
    keycloak_invite_client_id: str = "aios-backend"
    keycloak_invite_redirect_uri: str = ""
    keycloak_invite_lifespan_seconds: int = 43_200

    # AI-слой (Итерация 1) — за feature-flag; в прототипе выключен
    ai_enabled: bool = False
    # шлюз LLM (LiteLLM/Ollama, OpenAI-совместимый); пусто — mock-режим без модели
    llm_base_url: str = ""
    llm_model: str = "qwen2.5"

    # Рассылка перевозчикам о тендере (Логистика). По умолчанию канал только логирует
    # (MVP); реальная доставка включается, когда заданы SMTP/Telegram (за конфигом).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@aios.local"
    smtp_tls: bool = True
    telegram_bot_token: str = ""
    # Telegram-webhook secret-token (SECURITY.md P0-6): задаётся в setWebhook, Telegram
    # шлёт его в заголовке ``X-Telegram-Bot-Api-Secret-Token`` в КАЖДОМ запросе. Если задан —
    # входящие без совпадающего заголовка отбиваются 401 (иначе любой подделает /approve).
    # Прод публичен (/telegram открыт в middleware) → задавать обязательно.
    telegram_webhook_secret: str = ""

    # Телефония (облачная АТС zruchna): входящий webhook + исходящий click-to-call.
    # Webhook аутентифицируется общим секретом ``?token=`` — если задан, входящие
    # без совпадающего токена отбиваются 403 (прод публичен → задавать обязательно).
    # ``originate_url`` — URL инициации звонка (client_call_gen.php), свой на инсталляцию;
    # пусто → исходящий звонок недоступен (503).
    telephony_webhook_token: str = ""
    telephony_originate_url: str = ""

    # Приём лидов с сайта (контакт-форма) и почты (вебхук форвардера): публичные коннекторы
    # integrations, аутентификация общим секретом ?token= — если задан, входящие без
    # совпадающего токена отбиваются 403 (прод публичен → задавать обязательно).
    intake_webhook_token: str = ""

    # Google Sheets — экспорт строк в таблицу через сервис-аккаунт. ``credentials_file`` —
    # путь к JSON-ключу сервис-аккаунта (Google Cloud, включён Sheets API, email аккаунта —
    # «Редактор» таблицы). Пусто → Services.gsheets = None (экспорт недоступен, честная
    # деградация). ``spreadsheet_id`` — таблица по умолчанию (ключ из URL .../d/<ID>/edit).
    gsheets_credentials_file: str = ""
    gsheets_spreadsheet_id: str = ""

    # SEO/GEO Growth Platform: входящий webhook от SEO-сервиса (HMAC в X-SEO-Signature).
    # Прод публичен → задавать обязательно (AIOS_SEO_WEBHOOK_SECRET).
    seo_webhook_secret: str = ""

    # Базовый URL SEO/GEO UI для deep-link из CRM (AIOS_SEO_UI_BASE_URL).
    seo_ui_base_url: str = "http://localhost:3000"

    # Реквизиты своей организации (продавец) для счетов/договоров SALES-53 — конфиг, не shared-схема
    # (ТЗ C.5). Переопределяются env AIOS_SELLER_*. Реквизиты покупателя берутся по УНП из ЕГР.
    seller_name: str = "ООО «Аккумуляторные решения»"
    seller_unp: str = "192766048"
    seller_address: str = "220035, г. Минск, ул. Тимирязева, д.65А, пом. №407"
    seller_director: str = ""
    seller_phone: str = "+375 29 635-00-95, +375 (17) 396-23-02"
    seller_email: str = ""
    # Банковские реквизиты продавца (строка «р/с … в банке … БИК …» в счёте — sales `_req_line`).
    # 🔴 Источник истины — бланк владельца (`sales-invoice-template.html`, блок `supplier`). НЕ
    # выдумывать: РБ с 04.07.2017 на IBAN+BIC, банк в платёжке опознаётся SWIFT'ом (`ALFABY2X`), а
    # НЕ числовым кодом. Числовой код тут уже был неверен — `153001270` принадлежит Беларусбанку
    # (см. справочник `scripts/seed.py::Bank`), у Альфа-Банка `153001963`; имя одного банка с кодом
    # другого на платёжном документе = деньги не придут (PLATFORM #1).
    seller_account: str = "BY15ALFA30122190570050270000"
    seller_bank: str = "ЗАО «АЛЬФА-БАНК», 220013, г. Минск, ул. Сурганова, 43-47"
    seller_bik: str = "ALFABY2X"

    @model_validator(mode="after")
    def _no_dev_defaults_in_prod(self) -> "Settings":
        """В прод-окружении запретить dev-дефолтные креды (SECURITY.md P0-5).

        Локальная разработка проходит при ``AIOS_ENVIRONMENT=dev``; прод-режим
        (значение по умолчанию) падает на старте, если БД/Telegram несут засвеченные
        dev-значения — это страховка от деплоя с ``aios:aios`` и т.п.
        """
        if self.environment.lower().startswith("dev"):
            return self
        if "aios:aios@" in self.database_url:
            raise ValueError(
                "Прод-режим с dev-дефолтом БД (aios:aios). Задайте AIOS_DATABASE_URL "
                "с реальными кредами или AIOS_ENVIRONMENT=dev для локальной разработки."
            )
        # AuthN (SEC-002): прод НЕ должен доверять заголовку X-User-Roles — на публичном
        # belakb.by это вход суперпользователем без пароля. Требуем проверенный Keycloak-JWT.
        if self.auth_mode != "oidc":
            raise ValueError(
                "Прод-режим требует AIOS_AUTH_MODE=oidc: доверие X-User-Roles в проде = вход "
                "без пароля. Заведите realm Keycloak или AIOS_ENVIRONMENT=dev для локали."
            )
        if not self.keycloak_issuer or not self.keycloak_audience:
            raise ValueError(
                "oidc-режим требует AIOS_KEYCLOAK_ISSUER и AIOS_KEYCLOAK_AUDIENCE "
                "(без проверки aud принимается любой токен realm'а — SEC-001)."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Закэшированный экземпляр настроек."""
    return Settings()
