"""Add normalized locations and professional contact relationships.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "locations" not in tables:
        op.create_table(
            "locations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("city", sa.String(length=100), nullable=False),
            sa.Column("state", sa.String(length=100), nullable=False),
            sa.Column("city_key", sa.String(length=100), nullable=False),
            sa.Column("state_key", sa.String(length=100), nullable=False),
            sa.UniqueConstraint("state_key", "city_key", name="uq_locations_state_city"),
            sa.CheckConstraint("length(trim(city)) > 0", name="ck_locations_city_nonempty"),
            sa.CheckConstraint("length(trim(state)) > 0", name="ck_locations_state_nonempty"),
        )
        op.create_index("ix_locations_state_city", "locations", ["state", "city"])

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "people" not in tables:
        op.create_table(
            "people",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("business_email", sa.String(length=255)),
            sa.Column("business_phone", sa.String(length=50)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("length(trim(name)) > 0", name="ck_people_name_nonempty"),
        )
        op.create_index("ix_people_name", "people", ["name"])
        op.create_index(
            "uq_people_business_email",
            "people",
            [sa.text("lower(business_email)")],
            unique=True,
        )

    if "company_people" not in tables:
        op.create_table(
            "company_people",
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("person_id", sa.Integer(), nullable=False),
            sa.Column("job_title", sa.String(length=120)),
            sa.Column("source_id", sa.Integer()),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("company_id", "person_id"),
            sa.CheckConstraint(
                "job_title IS NULL OR length(trim(job_title)) > 0",
                name="ck_company_people_job_title_nonempty",
            ),
        )
        op.create_index("ix_company_people_person_id", "company_people", ["person_id"])

    company_constraints = {
        item["name"]: item
        for item in sa.inspect(op.get_bind()).get_unique_constraints("companies")
    }
    if "uq_company_name_city" in company_constraints:
        with op.batch_alter_table("companies") as batch:
            batch.drop_constraint("uq_company_name_city", type_="unique")
            batch.create_unique_constraint(
                "uq_company_name_city_state", ["name", "city", "state"]
            )
    elif "uq_company_name_city_state" not in company_constraints:
        with op.batch_alter_table("companies") as batch:
            batch.create_unique_constraint(
                "uq_company_name_city_state", ["name", "city", "state"]
            )

    additions = {
        "companies": (
            sa.Column(
                "location_id",
                sa.Integer(),
                sa.ForeignKey(
                    "locations.id",
                    ondelete="RESTRICT",
                    name="fk_companies_location_id_locations",
                ),
            ),
        ),
        "projects": (
            sa.Column(
                "location_id",
                sa.Integer(),
                sa.ForeignKey(
                    "locations.id",
                    ondelete="RESTRICT",
                    name="fk_projects_location_id_locations",
                ),
            ),
        ),
        "activities": (
            sa.Column(
                "person_id",
                sa.Integer(),
                sa.ForeignKey(
                    "people.id",
                    ondelete="SET NULL",
                    name="fk_activities_person_id_people",
                ),
            ),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey(
                    "projects.id",
                    ondelete="SET NULL",
                    name="fk_activities_project_id_projects",
                ),
            ),
        ),
    }
    for table_name, columns in additions.items():
        existing = _columns(table_name)
        missing_columns = [column for column in columns if column.name not in existing]
        if missing_columns:
            with op.batch_alter_table(table_name) as batch:
                for column in missing_columns:
                    batch.add_column(column)

    existing_source_indexes = {
        item["name"] for item in sa.inspect(op.get_bind()).get_indexes("sources")
    }
    for table_name, column_name, index_name in (
        ("companies", "city", "ix_companies_state_city"),
        ("companies", "location_id", "ix_companies_location_id"),
        ("projects", "location_id", "ix_projects_location_id"),
        ("activities", "person_id", "ix_activities_person_id"),
        ("activities", "project_id", "ix_activities_project_id"),
        ("activities", "created_at", "ix_activities_company_created"),
        ("activities", "due_date", "ix_activities_due_date_completed"),
        ("projects", "status", "ix_projects_status_name"),
        ("sources", "verification_status", "ix_sources_verification_discovered"),
    ):
        existing_indexes = (
            existing_source_indexes
            if table_name == "sources"
            else {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table_name)}
        )
        if index_name not in existing_indexes:
            columns = (
                ["verification_status", "discovered_at"]
                if index_name == "ix_sources_verification_discovered"
                else ["state", "city"]
                if index_name == "ix_companies_state_city"
                else ["company_id", "created_at"]
                if index_name == "ix_activities_company_created"
                else ["due_date", "completed_at"]
                if index_name == "ix_activities_due_date_completed"
                else ["status", "name"]
                if index_name == "ix_projects_status_name"
                else [column_name]
            )
            op.create_index(index_name, table_name, columns)

    locations = sa.Table(
        "locations",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("city", sa.String(100)),
        sa.Column("state", sa.String(100)),
        sa.Column("city_key", sa.String(100)),
        sa.Column("state_key", sa.String(100)),
    )
    companies = sa.Table(
        "companies",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("city", sa.String(100)),
        sa.Column("state", sa.String(100)),
        sa.Column("location_id", sa.Integer()),
    )
    projects = sa.Table(
        "projects",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer()),
        sa.Column("location", sa.String(200)),
        sa.Column("location_id", sa.Integer()),
    )
    connection = op.get_bind()
    location_ids: dict[tuple[str, str], int] = {}

    def location_id(city: str | None, state: str | None) -> int | None:
        clean_city = " ".join((city or "").split())
        clean_state = " ".join((state or "").split())
        if not clean_city or not clean_state:
            return None
        city_key, state_key = clean_city.casefold(), clean_state.casefold()
        key = state_key, city_key
        if key in location_ids:
            return location_ids[key]
        existing_id = connection.execute(
            sa.select(locations.c.id).where(
                locations.c.state_key == state_key,
                locations.c.city_key == city_key,
            )
        ).scalar_one_or_none()
        if existing_id is None:
            existing_id = connection.execute(
                locations.insert().values(
                    city=clean_city,
                    state=clean_state,
                    city_key=city_key,
                    state_key=state_key,
                )
            ).inserted_primary_key[0]
        location_ids[key] = existing_id
        return existing_id

    for company in connection.execute(sa.select(companies)).mappings():
        if company["location_id"] is None:
            resolved_id = location_id(company["city"], company["state"])
            if resolved_id is not None:
                connection.execute(
                    companies.update()
                    .where(companies.c.id == company["id"])
                    .values(location_id=resolved_id)
                )
    company_geographies = {
        row["id"]: (
            row["location_id"],
            " ".join((row["city"] or "").split()).casefold(),
            row["state"],
        )
        for row in connection.execute(sa.select(companies)).mappings()
    }
    for project in connection.execute(sa.select(projects)).mappings():
        if project["location_id"] is None and project["location"]:
            company_geography = company_geographies.get(project["company_id"])
            if (
                company_geography
                and " ".join(project["location"].split()).casefold() == company_geography[1]
            ):
                resolved_id = company_geography[0]
            else:
                resolved_id = None
            if resolved_id is not None:
                connection.execute(
                    projects.update()
                    .where(projects.c.id == project["id"])
                    .values(location_id=resolved_id)
                )


def downgrade() -> None:
    connection = op.get_bind()
    collision = connection.execute(
        sa.text(
            "SELECT 1 FROM companies GROUP BY lower(name), lower(city) "
            "HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if collision:
        raise RuntimeError(
            "Cannot downgrade location-aware company identity: companies in different states "
            "share the same name and city."
        )

    indexes = (
        ("activities", "ix_activities_company_created"),
        ("activities", "ix_activities_due_date_completed"),
        ("activities", "ix_activities_person_id"),
        ("activities", "ix_activities_project_id"),
        ("companies", "ix_companies_location_id"),
        ("companies", "ix_companies_state_city"),
        ("locations", "ix_locations_state_city"),
        ("projects", "ix_projects_location_id"),
        ("projects", "ix_projects_status_name"),
        ("sources", "ix_sources_verification_discovered"),
    )
    tables = set(sa.inspect(connection).get_table_names())
    for table_name, index_name in indexes:
        if table_name in tables and index_name in {
            item["name"] for item in sa.inspect(connection).get_indexes(table_name)
        }:
            op.drop_index(index_name, table_name=table_name)

    company_constraints = {
        item["name"]: item
        for item in sa.inspect(connection).get_unique_constraints("companies")
    }
    if "uq_company_name_city_state" in company_constraints:
        with op.batch_alter_table("companies") as batch:
            batch.drop_constraint("uq_company_name_city_state", type_="unique")
            batch.create_unique_constraint("uq_company_name_city", ["name", "city"])

    for table_name, column_names in (
        ("activities", ("project_id", "person_id")),
        ("projects", ("location_id",)),
        ("companies", ("location_id",)),
    ):
        existing = _columns(table_name)
        missing = [column for column in column_names if column in existing]
        if missing:
            with op.batch_alter_table(table_name) as batch:
                for column_name in missing:
                    batch.drop_column(column_name)

    if "company_people" in tables:
        op.drop_table("company_people")
    if "people" in tables:
        op.drop_table("people")
    if "locations" in tables:
        op.drop_table("locations")
