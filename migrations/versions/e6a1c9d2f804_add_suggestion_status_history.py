"""add suggestion status history

Revision ID: e6a1c9d2f804
Revises: d3f91a6b20ce
Create Date: 2026-11-22 22:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "e6a1c9d2f804"
down_revision = "d3f91a6b20ce"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "status_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("suggestion_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["changed_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["suggestion_id"], ["suggestion.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("status_history", schema=None) as batch_op:
        batch_op.create_index(
            "ix_status_history_suggestion_id",
            ["suggestion_id"],
            unique=False,
        )

    bind = op.get_bind()
    suggestions = bind.execute(
        sa.text(
            "SELECT id, status, officer_remark, created_at "
            "FROM suggestion"
        )
    ).mappings()
    for suggestion in suggestions:
        bind.execute(
            sa.text(
                "INSERT INTO status_history "
                "(suggestion_id, status, remark, changed_by, created_at) "
                "VALUES (:suggestion_id, :status, :remark, NULL, :created_at)"
            ),
            {
                "suggestion_id": suggestion["id"],
                "status": suggestion["status"],
                "remark": suggestion["officer_remark"],
                "created_at": suggestion["created_at"],
            },
        )


def downgrade():
    op.drop_index(
        "ix_status_history_suggestion_id",
        table_name="status_history",
    )
    op.drop_table("status_history")
