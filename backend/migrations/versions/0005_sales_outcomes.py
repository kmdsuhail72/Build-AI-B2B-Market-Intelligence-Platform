"""Track structured sales outcomes on activity records.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


OUTCOME_CONSTRAINT = "ck_activities_sales_outcome"


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("activities")}
    if "sales_outcome" not in columns:
        with op.batch_alter_table("activities") as batch:
            batch.add_column(sa.Column("sales_outcome", sa.String(length=30), nullable=True))
            batch.create_check_constraint(
                OUTCOME_CONSTRAINT,
                "sales_outcome IS NULL OR sales_outcome IN "
                "('contacted', 'interested', 'qualified', 'proposal_sent', "
                "'won', 'lost', 'not_interested', 'no_response')",
            )


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("activities")}
    if "sales_outcome" in columns:
        with op.batch_alter_table("activities") as batch:
            batch.drop_constraint(OUTCOME_CONSTRAINT, type_="check")
            batch.drop_column("sales_outcome")
