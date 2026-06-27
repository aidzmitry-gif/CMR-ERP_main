"""core: свободные «общие данные группы» (Производитель/коробка/габариты) — JSONB-наследование

``ref_nomenclature_category.attributes`` (JSONB) — словарь значений по умолчанию группы для
свободных полей карточки товара (Производитель/Марка/Импортёр, Кол-во в коробке, Габариты, Объём).
Товар без своего ключа в ``Sku.attributes`` наследует его вверх по дереву групп (parent_id) —
резолв в ``core.services.tnved.effective_group_attr``. Дополняет типизированные дефолты группы
(``vat_code/unit/country/tnved_code``, 0050/0054): «общие данные группы для товаров в ней».

На Postgres колонка — JSONB (тип ``JSON`` SQLAlchemy маппится в ``jsonb`` через диалект);
server_default ``'{}'`` совпадает с ``Sku.attributes``.

Revision ID: 0055
Revises: 0054
Create Date: 2026-06-27

Примечание: чейн линейный 0054 → 0055. Если параллельная сессия уже заняла 0055 —
перенумеровать (как было с 0034/0036).
"""
import sqlalchemy as sa
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ref_nomenclature_category",
        sa.Column(
            "attributes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),  # как Sku.attributes/provenance (0044/0047)
        ),
    )


def downgrade() -> None:
    op.drop_column("ref_nomenclature_category", "attributes")
