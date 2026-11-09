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
                "CREATE TABLE companies (id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL, "
                "category VARCHAR(80) NOT NULL, city VARCHAR(100) NOT NULL, state VARCHAR(100) NOT NULL, "
                "website VARCHAR(500), public_phone VARCHAR(50), description TEXT, "
                "created_at DATETIME NOT NULL, CONSTRAINT uq_company_name_city UNIQUE (name, city))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO companies (id, name, category, city, state, created_at) "
                "VALUES (1, 'Legacy Builder', 'Builder', 'Varanasi', 'Uttar Pradesh', "
                "'2025-01-01 00:00:00')"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE projects (id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, "
                "name VARCHAR(200) NOT NULL, location VARCHAR(200), status VARCHAR(80) NOT NULL, "
                "estimated_units INTEGER, estimated_doors INTEGER, demand_notes TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO projects (id, company_id, name, location, status, estimated_units) "
                "VALUES (9, 1, 'Legacy project', 'Varanasi', 'announced', 30)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE activities (id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, "
                "activity_type VARCHAR(50) NOT NULL, notes TEXT NOT NULL, "
                "next_action VARCHAR(300), due_date DATE, completed_at DATETIME, "
                "created_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO activities (id, company_id, activity_type, notes, created_at) "
                "VALUES (7, 1, 'call', 'Legacy sales call', '2025-01-02 00:00:00')"
            )
        )
        migration_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        migration_config.attributes["connection"] = connection

        command.upgrade(migration_config, "head")

        project_columns = {item["name"] for item in inspect(connection).get_columns("projects")}
        source_columns = {item["name"] for item in inspect(connection).get_columns("sources")}
        company_columns = {item["name"] for item in inspect(connection).get_columns("companies")}
        activity_columns = {item["name"] for item in inspect(connection).get_columns("activities")}
        activity_outcome = connection.execute(
            text("SELECT sales_outcome FROM activities WHERE id=7")
        ).scalar_one()
        location = connection.execute(
            text(
                "SELECT locations.city, locations.state FROM companies "
                "JOIN locations ON companies.location_id = locations.id WHERE companies.id = 1"
            )
        ).one()
        project_location_id = connection.execute(
            text("SELECT location_id FROM projects WHERE id=9")
        ).scalar_one()
        company_location_id = connection.execute(
            text("SELECT location_id FROM companies WHERE id=1")
        ).scalar_one()
        project = connection.execute(
            text("SELECT id, name, estimated_units, demand_confidence FROM projects WHERE id=9")
        ).one()
        current_revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        command.downgrade(migration_config, "0003")
        downgraded_revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        downgraded_company_columns = {
            item["name"] for item in inspect(connection).get_columns("companies")
        }
        downgraded_activity_columns = {
            item["name"] for item in inspect(connection).get_columns("activities")
        }

    assert {"doors_per_unit", "estimate_basis", "demand_confidence"}.issubset(project_columns)
    assert "location_id" in company_columns
    assert "content" in source_columns
    assert "person_id" not in source_columns
    assert "sales_outcome" in activity_columns
    assert activity_outcome is None
    assert location == ("Varanasi", "Uttar Pradesh")
    assert project_location_id == company_location_id
    assert project == (9, "Legacy project", 30, "unknown")
    assert current_revision == "0005"
    assert downgraded_revision == "0003"
    assert "sales_outcome" not in downgraded_activity_columns
    assert "location_id" not in downgraded_company_columns
    assert not {"locations", "people", "company_people"}.issubset(
        inspect(test_engine).get_table_names()
    )
    test_engine.dispose()
