"""Прод-гард настроек (SECURITY.md P0-5/P1-1): прод не стартует на dev-дефолтах.

Компоуз больше НЕ хардкодит dev-режим (см. docker-compose.yml сервис app), поэтому
«тихий небезопасный старт» ловит этот валидатор: прод (environment≠dev) падает на
засвеченных dev-кредах БД и на доверии заголовку X-User-Roles (auth_mode≠oidc).
"""
import pytest
from pydantic import ValidationError

from config.settings import Settings

# Чистые прод-креды БД (без засвеченного aios:aios) и полный OIDC-набор.
PROD_DB = "postgresql+psycopg://real:s3cret@postgres:5432/prod"
OIDC = {"auth_mode": "oidc", "keycloak_issuer": "https://kc/realms/aios", "keycloak_audience": "app"}


def _settings(**kw) -> Settings:
    # _env_file=None — не читать локальный .env, чтобы тест был детерминирован.
    return Settings(_env_file=None, **kw)


def test_dev_environment_skips_all_guards():
    # dev-режим (локальная разработка): dev-креды БД и header-trust допустимы.
    s = _settings(environment="dev", database_url="postgresql+psycopg://aios:aios@localhost/aios")
    assert s.environment == "dev"


def test_prod_rejects_dev_db_creds():
    with pytest.raises(ValidationError, match="aios:aios"):
        _settings(
            environment="prod",
            database_url="postgresql+psycopg://aios:aios@postgres:5432/aios",
            **OIDC,
        )


def test_prod_rejects_header_trust_auth():
    # auth_mode=dev в проде = вход супер-юзером без пароля → старт запрещён.
    with pytest.raises(ValidationError, match="oidc"):
        _settings(environment="prod", database_url=PROD_DB, auth_mode="dev")


def test_prod_oidc_requires_issuer_and_audience():
    with pytest.raises(ValidationError, match="ISSUER|AUDIENCE|aud"):
        _settings(
            environment="prod",
            database_url=PROD_DB,
            auth_mode="oidc",
            keycloak_issuer="",
            keycloak_audience="",
        )


def test_prod_with_real_creds_and_oidc_boots():
    s = _settings(environment="prod", database_url=PROD_DB, **OIDC)
    assert s.environment == "prod"
    assert s.auth_mode == "oidc"
