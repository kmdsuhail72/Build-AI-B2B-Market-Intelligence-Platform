"""Store reviewed source excerpts for retrieval-augmented research.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("sources")}
    if "content" not in columns:
        op.add_column("sources", sa.Column("content", sa.Text(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("sources")}
    if "content" in columns:
        op.drop_column("sources", "content")
