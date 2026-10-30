"""Installation identity is shared by every application worker."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class PlatformInstallation(Base):
    __tablename__ = "platform_installation"
    __table_args__ = (
        CheckConstraint("id = 1", name="platform_installation_singleton"),
        CheckConstraint("revision > 0", name="platform_installation_revision"),
        CheckConstraint("organization_id > 0", name="platform_installation_organization"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    # The core keeps a validated reference, without importing a module's ORM.
    organization_id: Mapped[int] = mapped_column(Integer)
    organization_unp: Mapped[str] = mapped_column(String(9))
    request_id: Mapped[str] = mapped_column(String(36))
    command_digest: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
