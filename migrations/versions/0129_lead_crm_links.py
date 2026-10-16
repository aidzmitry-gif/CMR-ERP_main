"""Numeric CRM lead links and replay identity; no legacy name backfill.

Revision ID: 0129
Revises: 0128
"""
import sqlalchemy as sa
from alembic import op

revision = '0129'
down_revision = '0128'
branch_labels = None
depends_on = None


def upgrade():
    for name in ['owner_id', 'crm_client_id', 'crm_contact_id']:
        op.add_column('lead', sa.Column(name, sa.Integer(), nullable=True), schema='leads')
        op.create_index(f'ix_leads_lead_{name}', 'lead', [name], schema='leads')
    op.add_column('lead', sa.Column('request_key', sa.String(64), nullable=True), schema='leads')
    op.add_column('lead', sa.Column('request_hash', sa.String(64), nullable=True), schema='leads')
    op.create_unique_constraint('uq_lead_owner_request', 'lead', ['owner_id', 'request_key'], schema='leads')
    op.add_column('deal', sa.Column('crm_contact_id', sa.Integer(), nullable=True), schema='sales')


def downgrade():
    op.drop_column('deal', 'crm_contact_id', schema='sales')
    op.drop_constraint('uq_lead_owner_request', 'lead', schema='leads', type_='unique')
    for name in ['request_hash', 'request_key']:
        op.drop_column('lead', name, schema='leads')
    for name in ['crm_contact_id', 'crm_client_id', 'owner_id']:
        op.drop_index(f'ix_leads_lead_{name}', table_name='lead', schema='leads')
        op.drop_column('lead', name, schema='leads')
