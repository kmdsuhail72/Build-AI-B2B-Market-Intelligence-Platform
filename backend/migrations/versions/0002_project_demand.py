"""Add transparent project demand assumptions to existing installations.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("projects")}
    if "doors_per_unit" not in columns:
        op.add_column("projects", sa.Column("doors_per_unit", sa.Float(), nullable=True))
    if "estimate_basis" not in columns:
        op.add_column("projects", sa.Column("estimate_basis", sa.String(length=300), nullable=True))
    if "demand_confidence" not in columns:
        op.add_column(
            "projects",
            sa.Column("demand_confidence", sa.String(length=20), nullable=False, server_default="unknown"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("projects")}
    for column in ("demand_confidence", "estimate_basis", "doors_per_unit"):
        if column in columns:
            op.drop_column("projects", column)
