"""Shared kernel — общие доменные ORM-сущности, доступные всем модулям."""
from core.domain.installation import PlatformInstallation
from core.domain.models import Contact, Counterparty, Sku, User

__all__ = ["Counterparty", "Contact", "Sku", "User", "PlatformInstallation"]
