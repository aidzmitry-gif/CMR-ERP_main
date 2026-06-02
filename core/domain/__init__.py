"""Shared kernel — общие доменные сущности, доступные всем модулям."""
from core.domain.models import Contact, Counterparty, Sku, User

__all__ = ["Counterparty", "Contact", "Sku", "User"]
