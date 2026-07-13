"""Verify the Milestone 3 DuckDB environment without creating a database."""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(
    "/Users/joeyn256/Projects/NCAA Track Analytics Pipeline"
)

PRODUCTION_DATABASE = (
    PROJECT_ROOT
    / "data"
    / "database"
    / "ncaa_track_analytics.duckdb"
)

EXPECTED_DUCKDB_VERSION = "1.5.4"
EXPECTED_SCHEMAS = {
    "raw",
    "core",
    "analytics",
    "audit",
}


def main() -> None:
    """Run a completely in-memory DuckDB smoke test."""
    print("MILESTONE 3 DUCKDB ENVIRONMENT CHECK")
    print("=" * 72)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {platform.python_version()}")
    print(f"Platform: {platform.platform()}")
    print(f"Machine architecture: {platform.machine()}")
    print(f"DuckDB Python package: {duckdb.__version__}")
    print()

    if duckdb.__version__ != EXPECTED_DUCKDB_VERSION:
        raise RuntimeError(
            "Unexpected DuckDB version: "
            f"expected {EXPECTED_DUCKDB_VERSION}, "
            f"found {duckdb.__version__}"
        )

    print("Version pin: PASS")

    if PRODUCTION_DATABASE.exists():
        print(
            "Production database status: EXISTS "
            f"({PRODUCTION_DATABASE})"
        )
        print(
            "Warning: this verification script will not open or alter it."
        )
    else:
        print("Production database status: NOT CREATED")

    print()
    print("Opening temporary in-memory DuckDB connection...")

    connection = duckdb.connect(database=":memory:")

    try:
        engine_version = connection.execute(
            "SELECT version()"
        ).fetchone()[0]

        print(f"DuckDB engine version: {engine_version}")

        for schema_name in sorted(EXPECTED_SCHEMAS):
            connection.execute(
                f'CREATE SCHEMA "{schema_name}"'
            )

        schemas = {
            row[0]
            for row in connection.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                """
            ).fetchall()
        }

        missing_schemas = EXPECTED_SCHEMAS - schemas

        if missing_schemas:
            raise RuntimeError(
                "In-memory schema test failed. Missing: "
                + ", ".join(sorted(missing_schemas))
            )

        connection.execute(
            """
            CREATE TABLE audit.environment_smoke_test (
                test_id INTEGER,
                test_name VARCHAR,
                passed BOOLEAN
            )
            """
        )

        connection.execute(
            """
            INSERT INTO audit.environment_smoke_test
            VALUES (1, 'duckdb_in_memory_write', TRUE)
            """
        )

        result = connection.execute(
            """
            SELECT test_id, test_name, passed
            FROM audit.environment_smoke_test
            """
        ).fetchone()

        expected_result = (
            1,
            "duckdb_in_memory_write",
            True,
        )

        if result != expected_result:
            raise RuntimeError(
                "Unexpected smoke-test result: "
                f"{result!r}"
            )

        print("In-memory connection: PASS")
        print("Schema creation: PASS")
        print("Temporary table write/read: PASS")

    finally:
        connection.close()

    print()
    print("Connection closed.")
    print("No persistent DuckDB database was created.")
    print("No NCAA source data was loaded.")
    print()
    print("OVERALL RESULT: PASS")


if __name__ == "__main__":
    main()
