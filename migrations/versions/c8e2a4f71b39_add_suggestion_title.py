"""add suggestion title

Revision ID: c8e2a4f71b39
Revises: b74f0d3c1a92
Create Date: 2026-11-21 21:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c8e2a4f71b39"
down_revision = "b74f0d3c1a92"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("suggestion", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("title", sa.String(length=150), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("suggestion", schema=None) as batch_op:
        batch_op.drop_column("title")
