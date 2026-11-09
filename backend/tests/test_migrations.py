from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool


def test_existing_mvp_database_receives_demand_migration():
    test_engine = create_engine("sqlite://", poolclass=StaticPool)
    with test_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE projects (id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, "
                "name VARCHAR(200) NOT NULL, location VARCHAR(200), status VARCHAR(80) NOT NULL, "
                "estimated_units INTEGER, estimated_doors INTEGER, demand_notes TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO projects (id, company_id, name, status, estimated_units) "
                "VALUES (9, 1, 'Legacy project', 'announced', 30)"
            )
        )
        migration_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        migration_config.attributes["connection"] = connection

        command.upgrade(migration_config, "head")

        project_columns = {item["name"] for item in inspect(connection).get_columns("projects")}
        source_columns = {item["name"] for item in inspect(connection).get_columns("sources")}
        project = connection.execute(
            text("SELECT id, name, estimated_units, demand_confidence FROM projects WHERE id=9")
        ).one()
        current_revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()

    assert {"doors_per_unit", "estimate_basis", "demand_confidence"}.issubset(project_columns)
    assert "content" in source_columns
    assert project == (9, "Legacy project", 30, "unknown")
    assert current_revision == "0003"
    test_engine.dispose()
