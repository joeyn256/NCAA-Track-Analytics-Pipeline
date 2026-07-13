"""Validate the Milestone 3 DuckDB schema entirely in memory.

This script:

1. Reads src/database/schema.sql.
2. Executes it inside an in-memory DuckDB transaction.
3. Confirms every required schema, table, and performance column.
4. Confirms the large fact and affiliation tables have no physical
   PRIMARY KEY or UNIQUE indexes.
5. Inserts synthetic test records.
6. Rolls the transaction back.
7. Confirms no production database was created.

No NCAA source data is read or loaded.
"""

from __future__ import annotations

import platform
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_FILE = (
    PROJECT_ROOT
    / "src"
    / "database"
    / "schema.sql"
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

EXPECTED_TABLES = {
    ("audit", "schema_versions"),
    ("audit", "build_runs"),
    ("audit", "source_files"),
    ("audit", "table_counts"),
    ("audit", "integrity_checks"),
    ("audit", "roster_duplicate_groups"),
    ("audit", "affiliation_coverage"),
    ("audit", "dimension_conflicts"),
    ("core", "schools"),
    ("core", "teams"),
    ("core", "athletes"),
    ("core", "seasons"),
    ("core", "meets"),
    ("core", "events"),
    ("core", "athlete_affiliations"),
    ("core", "performances"),
}

EXPECTED_PERFORMANCE_COLUMNS = [
    "performance_id",
    "athlete_id",
    "athlete_name",
    "athlete_class",
    "school",
    "team_id",
    "season_id",
    "season_year",
    "season_type",
    "season_label",
    "meet_id",
    "result_id",
    "meet_name",
    "meet_date_text",
    "event_id",
    "event",
    "mark",
    "secondary_mark",
    "wind",
    "place",
    "competition_round",
    "raw_place",
    "meet_url",
    "result_url",
    "highlighted",
    "affiliation_id",
    "source_file",
    "source_chunk_file",
]


def print_pass(message: str) -> None:
    """Print a standardized passing result."""
    print(f"[PASS] {message}")


def main() -> None:
    """Run the in-memory schema validation."""
    print("MILESTONE 3 SCHEMA VALIDATION")
    print("=" * 80)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Schema file: {SCHEMA_FILE}")
    print(f"Production database: {PRODUCTION_DATABASE}")
    print(f"Python version: {platform.python_version()}")
    print(f"DuckDB version: {duckdb.__version__}")
    print("Validation connection: in-memory")
    print()

    if duckdb.__version__ != EXPECTED_DUCKDB_VERSION:
        raise RuntimeError(
            "Unexpected DuckDB version: "
            f"expected {EXPECTED_DUCKDB_VERSION}, "
            f"found {duckdb.__version__}"
        )

    print_pass("DuckDB version matches the pinned dependency")

    if not SCHEMA_FILE.is_file():
        raise FileNotFoundError(
            f"Schema file not found: {SCHEMA_FILE}"
        )

    print_pass("Schema file exists")

    if PRODUCTION_DATABASE.exists():
        raise RuntimeError(
            "Production database already exists. "
            "The schema validator will not open or modify it."
        )

    print_pass("Production database does not exist")

    schema_sql = SCHEMA_FILE.read_text(
        encoding="utf-8"
    )

    if not schema_sql.strip():
        raise RuntimeError(
            "Schema SQL file is empty."
        )

    connection = duckdb.connect(database=":memory:")
    transaction_started = False

    try:
        connection.execute("BEGIN TRANSACTION")
        transaction_started = True

        connection.execute(schema_sql)

        print_pass(
            "Schema SQL executed successfully in memory"
        )

        actual_schemas = {
            row[0]
            for row in connection.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                """
            ).fetchall()
        }

        missing_schemas = (
            EXPECTED_SCHEMAS - actual_schemas
        )

        if missing_schemas:
            raise RuntimeError(
                "Missing required schemas: "
                + ", ".join(
                    sorted(missing_schemas)
                )
            )

        print_pass(
            "raw, core, analytics, and audit schemas exist"
        )

        actual_tables = {
            (row[0], row[1])
            for row in connection.execute(
                """
                SELECT
                    table_schema,
                    table_name
                FROM information_schema.tables
                WHERE table_type = 'BASE TABLE'
                  AND table_schema IN (
                      'core',
                      'audit'
                  )
                """
            ).fetchall()
        }

        missing_tables = (
            EXPECTED_TABLES - actual_tables
        )

        unexpected_tables = (
            actual_tables - EXPECTED_TABLES
        )

        if missing_tables or unexpected_tables:
            messages = []

            if missing_tables:
                messages.append(
                    "Missing tables: "
                    + ", ".join(
                        f"{schema}.{table}"
                        for schema, table
                        in sorted(missing_tables)
                    )
                )

            if unexpected_tables:
                messages.append(
                    "Unexpected tables: "
                    + ", ".join(
                        f"{schema}.{table}"
                        for schema, table
                        in sorted(unexpected_tables)
                    )
                )

            raise RuntimeError(
                "; ".join(messages)
            )

        print_pass(
            f"All {len(EXPECTED_TABLES)} required tables exist"
        )

        actual_performance_columns = [
            row[0]
            for row in connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'core'
                  AND table_name = 'performances'
                ORDER BY ordinal_position
                """
            ).fetchall()
        ]

        if (
            actual_performance_columns
            != EXPECTED_PERFORMANCE_COLUMNS
        ):
            raise RuntimeError(
                "core.performances column order mismatch.\n"
                f"Expected: {EXPECTED_PERFORMANCE_COLUMNS}\n"
                f"Actual:   {actual_performance_columns}"
            )

        print_pass(
            "core.performances has the expected 28 columns"
        )

        large_table_index_constraints = (
            connection.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.table_constraints
                WHERE table_schema = 'core'
                  AND table_name IN (
                      'athlete_affiliations',
                      'performances'
                  )
                  AND constraint_type IN (
                      'PRIMARY KEY',
                      'UNIQUE'
                  )
                """
            ).fetchone()[0]
        )

        if large_table_index_constraints != 0:
            raise RuntimeError(
                "A PRIMARY KEY or UNIQUE constraint was "
                "unexpectedly created on a large table."
            )

        print_pass(
            "Large core tables have no physical "
            "PRIMARY KEY or UNIQUE indexes"
        )

        connection.execute(
            """
            INSERT INTO audit.build_runs (
                build_run_id,
                started_at,
                status,
                project_root,
                database_path,
                python_version,
                duckdb_version,
                expected_performance_rows
            )
            VALUES (
                'schema_validation_test',
                CURRENT_TIMESTAMP,
                'running',
                '/temporary/project',
                '/temporary/database.duckdb',
                '3.12.13',
                '1.5.4',
                6594540
            )
            """
        )

        connection.execute(
            """
            INSERT INTO core.schools
            VALUES (
                'TEST_college_Example',
                'Example University',
                'TS',
                2,
                2,
                TRUE,
                'directory'
            )
            """
        )

        connection.execute(
            """
            INSERT INTO core.teams
            VALUES (
                'TEST_college_f_Example',
                'TEST_college_Example',
                'source_school_1',
                'Example University',
                'f',
                '1',
                'Track & Field',
                NULL,
                'TS',
                'Example_University',
                'https://example.com/team',
                TRUE,
                TRUE,
                TRUE
            )
            """
        )

        connection.execute(
            """
            INSERT INTO core.athletes
            VALUES (
                '1',
                'Runner, Test',
                'Example University',
                'TEST_college_f_Example',
                'https://example.com/athlete/1',
                TRUE,
                TRUE
            )
            """
        )

        connection.execute(
            """
            INSERT INTO core.seasons
            VALUES (
                '2026_outdoor',
                2026,
                'outdoor',
                '2026 Outdoors',
                '2026 Outdoor',
                '432',
                2026,
                2026,
                TRUE,
                TRUE
            )
            """
        )

        connection.execute(
            """
            INSERT INTO core.meets
            VALUES (
                'meet_1',
                'Test Meet',
                'May 1, 2026',
                'https://example.com/meet',
                1,
                1,
                1,
                2
            )
            """
        )

        connection.execute(
            """
            INSERT INTO core.events
            VALUES (
                1,
                '100 Meters',
                2
            )
            """
        )

        connection.execute(
            """
            INSERT INTO core.athlete_affiliations
            VALUES (
                1,
                '1',
                'TEST_college_f_Example',
                '2026_outdoor',
                '432',
                '2026 Outdoor',
                'SR-4',
                'Runner, Test',
                'Example University',
                1,
                0
            )
            """
        )

        connection.execute(
            """
            INSERT INTO core.performances (
                performance_id,
                athlete_id,
                athlete_name,
                athlete_class,
                school,
                team_id,
                season_id,
                season_year,
                season_type,
                season_label,
                meet_id,
                result_id,
                meet_name,
                meet_date_text,
                event_id,
                event,
                mark,
                secondary_mark,
                wind,
                place,
                competition_round,
                raw_place,
                meet_url,
                result_url,
                highlighted,
                affiliation_id,
                source_file,
                source_chunk_file
            )
            VALUES
            (
                'performance_1',
                '1',
                'Runner, Test',
                'SR-4',
                'Example University',
                'TEST_college_f_Example',
                '2026_outdoor',
                2026,
                'outdoor',
                '2026 Outdoors',
                'meet_1',
                'result_1',
                'Test Meet',
                'May 1, 2026',
                1,
                '100 Meters',
                '12.34',
                NULL,
                NULL,
                '1',
                NULL,
                '1',
                'https://example.com/meet',
                'https://example.com/result/1',
                'False',
                1,
                '1.html',
                'performances_00001.csv'
            ),
            (
                'performance_2',
                '1',
                'Runner, Test',
                'SR-4',
                'Unattached',
                NULL,
                '2026_outdoor',
                2026,
                'outdoor',
                '2026 Outdoors',
                'meet_1',
                'result_2',
                'Test Meet',
                'May 1, 2026',
                1,
                '100 Meters',
                '12.50',
                NULL,
                NULL,
                '2',
                NULL,
                '2',
                'https://example.com/meet',
                'https://example.com/result/2',
                'False',
                NULL,
                '1.html',
                'performances_00001.csv'
            )
            """
        )

        smoke_result = connection.execute(
            """
            SELECT
                COUNT(*) AS total_rows,

                COUNT(*) FILTER (
                    WHERE team_id IS NULL
                ) AS nullable_team_rows,

                COUNT(*) FILTER (
                    WHERE affiliation_id IS NOT NULL
                ) AS matched_affiliation_rows
            FROM core.performances
            """
        ).fetchone()

        expected_smoke_result = (
            2,
            1,
            1,
        )

        if smoke_result != expected_smoke_result:
            raise RuntimeError(
                "Unexpected fact-table smoke-test result: "
                f"{smoke_result!r}"
            )

        print_pass(
            "Performance table accepts both matched and "
            "unmatched affiliation records"
        )

        joined_rows = connection.execute(
            """
            SELECT COUNT(*)
            FROM core.performances AS performances
            INNER JOIN core.athlete_affiliations
                AS affiliations
                ON performances.affiliation_id
                    = affiliations.affiliation_id
            """
        ).fetchone()[0]

        if joined_rows != 1:
            raise RuntimeError(
                "Expected one matched synthetic affiliation, "
                f"found {joined_rows}."
            )

        print_pass(
            "Synthetic relational join succeeds"
        )

        connection.execute("ROLLBACK")
        transaction_started = False

        print_pass(
            "Validation transaction rolled back"
        )

    except Exception:
        if transaction_started:
            try:
                connection.execute("ROLLBACK")
            except duckdb.Error:
                pass

        raise

    finally:
        connection.close()

    print_pass(
        "In-memory DuckDB connection closed"
    )

    if PRODUCTION_DATABASE.exists():
        raise RuntimeError(
            "The production database was unexpectedly created."
        )

    print_pass(
        "No persistent DuckDB database was created"
    )

    print()
    print("No NCAA source files were read.")
    print("No NCAA source data was loaded.")
    print()
    print("OVERALL RESULT: PASS")


if __name__ == "__main__":
    main()
