"""add suggestion photo

Revision ID: b74f0d3c1a92
Revises: a8764f2fa551
Create Date: 2026-11-20 22:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b74f0d3c1a92"
down_revision = "a8764f2fa551"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("suggestion", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("photo_filename", sa.String(length=255), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("suggestion", schema=None) as batch_op:
        batch_op.drop_column("photo_filename")
