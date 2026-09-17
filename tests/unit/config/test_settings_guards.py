import pytest

from config.settings import Settings


def test_dev_environment_allows_local_defaults():
    settings = Settings(environment="dev")
    assert settings.environment == "dev"


def test_prod_rejects_dev_database_defaults():
    with pytest.raises(ValueError, match="dev-дефолтом БД"):
        Settings(environment="prod")


def test_prod_requires_oidc_even_with_non_default_database():
    db = "postgresql+psycopg://test:test@db/app"
    with pytest.raises(ValueError, match="AIOS_AUTH_MODE=oidc"):
        Settings(environment="prod", database_url=db, auth_mode="dev")


def test_prod_oidc_requires_issuer_and_audience():
    db = "postgresql+psycopg://test:test@db/app"
    with pytest.raises(ValueError, match="ISSUER"):
        Settings(environment="prod", database_url=db, auth_mode="oidc")


def test_prod_oidc_with_explicit_issuer_and_audience_is_valid():
    settings = Settings(
        environment="prod",
        database_url="postgresql+psycopg://test:test@db/app",
        auth_mode="oidc",
        keycloak_issuer="https://sso.example/realms/aios",
        keycloak_audience="aios-backend",
    )
    assert settings.auth_mode == "oidc"
    assert settings.keycloak_audience == "aios-backend"
