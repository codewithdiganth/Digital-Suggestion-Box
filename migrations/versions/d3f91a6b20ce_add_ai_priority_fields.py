"""add AI priority fields

Revision ID: d3f91a6b20ce
Revises: c8e2a4f71b39
Create Date: 2026-11-21 21:52:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "d3f91a6b20ce"
down_revision = "c8e2a4f71b39"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("suggestion", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("ai_priority", sa.String(length=20), nullable=True)
        )
        batch_op.add_column(
            sa.Column("ai_priority_reason", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("ai_priority_provider", sa.String(length=30), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("suggestion", schema=None) as batch_op:
        batch_op.drop_column("ai_priority_provider")
        batch_op.drop_column("ai_priority_reason")
        batch_op.drop_column("ai_priority")
