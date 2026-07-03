"""sales: company_branding — лого продавца для печатных форм (счёт/договор).

Singleton-таблица (id=1): логотип хранится как data-URI (base64) в текстовой
колонке — без диска/S3/StaticFiles (в проекте нет установившегося паттерна
загрузки файлов, см. обсуждение); тот же подход, что у ContractTemplate.body
(текстовый контент печатной формы прямо в БД).

Revision ID: 0090
Revises: 0089
Create Date: 2026-07-03

Примечание: down_revision скорректирован вручную — локальный реестр резервов
(coordination/.migration-reservations.local) не знал про уже закоммиченный
0089 (Deal.next_step_at) и указал бы на 0088, что дало бы второй head.
Реальный head сверен командой `alembic heads` перед записью файла.
"""
import sqlalchemy as sa
from alembic import op

revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_branding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("logo_data_url", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        schema="sales",
    )


def downgrade() -> None:
    op.drop_table("company_branding", schema="sales")
