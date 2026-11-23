"""add user contact and password setup fields

Revision ID: 91f3d4c82a10
Revises: e6a1c9d2f804
Create Date: 2026-11-23 21:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "91f3d4c82a10"
down_revision = "e6a1c9d2f804"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("public_user_id", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("full_name", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("mobile_number", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("email", sa.String(length=254), nullable=True))
        batch_op.add_column(sa.Column("setup_token_nonce", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint("uq_user_public_user_id", ["public_user_id"])
        batch_op.create_unique_constraint("uq_user_mobile_number", ["mobile_number"])
        batch_op.create_unique_constraint("uq_user_email", ["email"])


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_constraint("uq_user_email", type_="unique")
        batch_op.drop_constraint("uq_user_mobile_number", type_="unique")
        batch_op.drop_constraint("uq_user_public_user_id", type_="unique")
        batch_op.drop_column("setup_token_nonce")
        batch_op.drop_column("email")
        batch_op.drop_column("mobile_number")
        batch_op.drop_column("full_name")
        batch_op.drop_column("public_user_id")
