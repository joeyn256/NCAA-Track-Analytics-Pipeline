"""Independently validate the published Milestone 3 DuckDB database.

This script opens the completed database in read-only mode and verifies:

1. The production file exists and can be opened.
2. All required schemas, tables, and raw views exist.
3. Core table counts match the accepted Milestone 3 totals.
4. The latest build run passed.
5. Every recorded hard audit passed.
6. Source-file metadata and hashes were recorded.
7. Performance identifiers remain complete and unique.
8. Core foreign-key relationships have no orphan records.
9. Historical-affiliation coverage reconciles to 6,594,540 records.
10. The persistent raw views can still read the canonical CSV sources.

The script cannot modify the database.
"""

from __future__ import annotations

import platform
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATABASE_PATH = (
    PROJECT_ROOT
    / "data"
    / "database"
    / "ncaa_track_analytics.duckdb"
)

STAGING_DATABASE = (
    PROJECT_ROOT
    / "data"
    / "database"
    / "ncaa_track_analytics.building.duckdb"
)

EXPECTED_DUCKDB_VERSION = "1.5.4"

EXPECTED_SCHEMAS = {
    "raw",
    "core",
    "analytics",
    "audit",
}

EXPECTED_CORE_TABLES = {
    "schools",
    "teams",
    "athletes",
    "seasons",
    "meets",
    "events",
    "athlete_affiliations",
    "performances",
}

EXPECTED_AUDIT_TABLES = {
    "schema_versions",
    "build_runs",
    "source_files",
    "table_counts",
    "integrity_checks",
    "roster_duplicate_groups",
    "affiliation_coverage",
    "dimension_conflicts",
}

EXPECTED_RAW_VIEWS = {
    "schools_source",
    "athletes_source",
    "rosters_source",
    "seasons_source",
    "performance_source",
    "chunk_status_source",
}

EXPECTED_CORE_COUNTS = {
    "schools": 554,
    "teams": 973,
    "athletes": 193_961,
    "meets": 32_416,
    "events": 378,
    "athlete_affiliations": 990_681,
    "performances": 6_594_540,
}

EXPECTED_RAW_COUNTS = {
    "schools_source": 714,
    "athletes_source": 193_961,
    "rosters_source": 992_774,
    "seasons_source": 34_332,
    "performance_source": 6_594_540,
    "chunk_status_source": 193_954,
}

EXPECTED_AFFILIATION_COVERAGE = {
    "matched": 5_916_703,
    "blank_team_id": 479,
    "performance_only_team": 32_776,
    "directory_team_without_roster_match": 644_582,
}

EXPECTED_PERFORMANCE_ROWS = 6_594_540
EXPECTED_SOURCE_FILES = 1_105
EXPECTED_ROSTER_DUPLICATE_EXCESS = 2_093


def heading(title: str) -> None:
    """Print a consistent report heading."""
    print()
    print(title)
    print("=" * 80)


def pass_message(message: str) -> None:
    """Print a passing check."""
    print(f"[PASS] {message}")


def check_equal(
    name: str,
    actual: object,
    expected: object,
) -> None:
    """Require two values to be equal."""
    if actual != expected:
        raise RuntimeError(
            f"{name} failed: "
            f"actual={actual!r}, expected={expected!r}"
        )

    pass_message(
        f"{name}: {actual}"
    )


def check_true(
    name: str,
    condition: bool,
    details: str,
) -> None:
    """Require a condition to be true."""
    if not condition:
        raise RuntimeError(
            f"{name} failed: {details}"
        )

    pass_message(f"{name}: {details}")


def scalar(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: list[object] | None = None,
) -> int:
    """Return one integer value from a query."""
    if parameters is None:
        result = connection.execute(query)
    else:
        result = connection.execute(
            query,
            parameters,
        )

    value = result.fetchone()[0]
    return int(value)


def main() -> None:
    """Run the complete independent production validation."""
    print("MILESTONE 3 PRODUCTION DATABASE VALIDATION")
    print("=" * 80)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Database: {DATABASE_PATH}")
    print(f"Python version: {platform.python_version()}")
    print(f"DuckDB package version: {duckdb.__version__}")
    print("Connection mode: read-only")

    check_true(
        "Production database exists",
        DATABASE_PATH.is_file(),
        str(DATABASE_PATH),
    )

    check_true(
        "Production database is nonempty",
        DATABASE_PATH.stat().st_size > 0,
        (
            f"{DATABASE_PATH.stat().st_size:,} bytes "
            f"({DATABASE_PATH.stat().st_size / (1024 ** 3):,.2f} GiB)"
        ),
    )

    check_true(
        "Staging database is absent",
        not STAGING_DATABASE.exists(),
        str(STAGING_DATABASE),
    )

    check_equal(
        "Pinned DuckDB package version",
        duckdb.__version__,
        EXPECTED_DUCKDB_VERSION,
    )

    connection = duckdb.connect(
        database=str(DATABASE_PATH),
        read_only=True,
    )

    try:
        heading("DATABASE ENGINE")

        engine_version = connection.execute(
            "SELECT version()"
        ).fetchone()[0]

        print(f"DuckDB engine version: {engine_version}")
        pass_message("Production database opened read-only")

        heading("SCHEMA AND OBJECT INVENTORY")

        actual_schemas = {
            row[0]
            for row in connection.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                """
            ).fetchall()
        }

        missing_schemas = EXPECTED_SCHEMAS - actual_schemas

        check_equal(
            "Missing required schemas",
            len(missing_schemas),
            0,
        )

        actual_core_tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'core'
                  AND table_type = 'BASE TABLE'
                """
            ).fetchall()
        }

        check_equal(
            "Core table inventory",
            actual_core_tables,
            EXPECTED_CORE_TABLES,
        )

        actual_audit_tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'audit'
                  AND table_type = 'BASE TABLE'
                """
            ).fetchall()
        }

        check_equal(
            "Audit table inventory",
            actual_audit_tables,
            EXPECTED_AUDIT_TABLES,
        )

        actual_raw_views = {
            row[0]
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'raw'
                  AND table_type = 'VIEW'
                """
            ).fetchall()
        }

        check_equal(
            "Raw view inventory",
            actual_raw_views,
            EXPECTED_RAW_VIEWS,
        )

        heading("LATEST BUILD RUN")

        build_row = connection.execute(
            """
            SELECT
                build_run_id,
                status,
                expected_performance_rows,
                actual_performance_rows,
                started_at,
                completed_at
            FROM audit.build_runs
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()

        if build_row is None:
            raise RuntimeError(
                "No build run was recorded."
            )

        (
            build_run_id,
            build_status,
            expected_performance_rows,
            actual_performance_rows,
            started_at,
            completed_at,
        ) = build_row

        print(f"Build run ID: {build_run_id}")
        print(f"Started: {started_at}")
        print(f"Completed: {completed_at}")

        check_equal(
            "Build status",
            build_status,
            "pass",
        )

        check_equal(
            "Recorded expected performance rows",
            expected_performance_rows,
            EXPECTED_PERFORMANCE_ROWS,
        )

        check_equal(
            "Recorded actual performance rows",
            actual_performance_rows,
            EXPECTED_PERFORMANCE_ROWS,
        )

        check_true(
            "Build completion timestamp",
            completed_at is not None,
            str(completed_at),
        )

        heading("CORE TABLE COUNTS")

        for table_name, expected_count in (
            EXPECTED_CORE_COUNTS.items()
        ):
            actual_count = scalar(
                connection,
                f"""
                SELECT COUNT(*)
                FROM core.{table_name}
                """,
            )

            check_equal(
                f"core.{table_name}",
                actual_count,
                expected_count,
            )

        season_count = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM core.seasons
            """,
        )

        check_true(
            "core.seasons contains records",
            season_count > 0,
            f"{season_count:,} rows",
        )

        heading("PERFORMANCE IDENTIFIER INTEGRITY")

        performance_metrics = connection.execute(
            """
            SELECT
                COUNT(*) AS total_rows,
                COUNT(
                    DISTINCT performance_id
                ) AS distinct_performance_ids,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(performance_id),
                        ''
                    ) IS NULL
                ) AS blank_performance_ids,
                COUNT(
                    DISTINCT athlete_id
                ) AS distinct_athletes,
                COUNT(*) FILTER (
                    WHERE team_id IS NULL
                ) AS blank_team_rows,
                COUNT(*) FILTER (
                    WHERE affiliation_id IS NOT NULL
                ) AS matched_affiliation_rows
            FROM core.performances
            """
        ).fetchone()

        (
            total_rows,
            distinct_performance_ids,
            blank_performance_ids,
            distinct_performance_athletes,
            blank_team_rows,
            matched_affiliation_rows,
        ) = performance_metrics

        check_equal(
            "Total performance rows",
            total_rows,
            EXPECTED_PERFORMANCE_ROWS,
        )

        check_equal(
            "Distinct performance IDs",
            distinct_performance_ids,
            EXPECTED_PERFORMANCE_ROWS,
        )

        check_equal(
            "Duplicate performance IDs",
            total_rows - distinct_performance_ids,
            0,
        )

        check_equal(
            "Blank performance IDs",
            blank_performance_ids,
            0,
        )

        check_equal(
            "Distinct performance athletes",
            distinct_performance_athletes,
            172_204,
        )

        check_equal(
            "Blank performance team rows",
            blank_team_rows,
            479,
        )

        check_equal(
            "Matched affiliation rows",
            matched_affiliation_rows,
            5_916_703,
        )

        heading("AFFILIATION INTEGRITY")

        duplicate_affiliation_keys = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    athlete_id,
                    team_id,
                    season_id,
                    COUNT(*) AS key_rows
                FROM core.athlete_affiliations
                GROUP BY
                    athlete_id,
                    team_id,
                    season_id
                HAVING COUNT(*) > 1
            )
            """,
        )

        check_equal(
            "Duplicate affiliation business keys",
            duplicate_affiliation_keys,
            0,
        )

        duplicate_excess = scalar(
            connection,
            """
            SELECT COALESCE(
                SUM(duplicate_excess_rows),
                0
            )
            FROM audit.roster_duplicate_groups
            WHERE build_run_id = ?
            """,
            [build_run_id],
        )

        check_equal(
            "Recorded roster duplicate excess",
            duplicate_excess,
            EXPECTED_ROSTER_DUPLICATE_EXCESS,
        )

        coverage_rows = connection.execute(
            """
            SELECT
                match_class,
                performance_rows
            FROM audit.affiliation_coverage
            WHERE build_run_id = ?
            """,
            [build_run_id],
        ).fetchall()

        actual_coverage = {
            str(match_class): int(performance_rows)
            for match_class, performance_rows
            in coverage_rows
        }

        check_equal(
            "Affiliation coverage categories",
            actual_coverage,
            EXPECTED_AFFILIATION_COVERAGE,
        )

        check_equal(
            "Affiliation coverage total",
            sum(actual_coverage.values()),
            EXPECTED_PERFORMANCE_ROWS,
        )

        heading("RELATIONAL ORPHAN CHECKS")

        orphan_queries = {
            "Performance athlete orphans": """
                SELECT COUNT(*)
                FROM core.performances AS performance
                LEFT JOIN core.athletes AS athlete
                    USING (athlete_id)
                WHERE athlete.athlete_id IS NULL
            """,
            "Performance team orphans": """
                SELECT COUNT(*)
                FROM core.performances AS performance
                LEFT JOIN core.teams AS team
                    USING (team_id)
                WHERE performance.team_id IS NOT NULL
                  AND team.team_id IS NULL
            """,
            "Performance season orphans": """
                SELECT COUNT(*)
                FROM core.performances AS performance
                LEFT JOIN core.seasons AS season
                    USING (season_id)
                WHERE season.season_id IS NULL
            """,
            "Performance meet orphans": """
                SELECT COUNT(*)
                FROM core.performances AS performance
                LEFT JOIN core.meets AS meet
                    USING (meet_id)
                WHERE meet.meet_id IS NULL
            """,
            "Performance event orphans": """
                SELECT COUNT(*)
                FROM core.performances AS performance
                LEFT JOIN core.events AS event
                    USING (event_id)
                WHERE event.event_id IS NULL
            """,
            "Affiliation athlete orphans": """
                SELECT COUNT(*)
                FROM core.athlete_affiliations
                    AS affiliation
                LEFT JOIN core.athletes AS athlete
                    USING (athlete_id)
                WHERE athlete.athlete_id IS NULL
            """,
            "Affiliation team orphans": """
                SELECT COUNT(*)
                FROM core.athlete_affiliations
                    AS affiliation
                LEFT JOIN core.teams AS team
                    USING (team_id)
                WHERE team.team_id IS NULL
            """,
            "Affiliation season orphans": """
                SELECT COUNT(*)
                FROM core.athlete_affiliations
                    AS affiliation
                LEFT JOIN core.seasons AS season
                    USING (season_id)
                WHERE season.season_id IS NULL
            """,
        }

        for check_name, query in orphan_queries.items():
            check_equal(
                check_name,
                scalar(connection, query),
                0,
            )

        heading("AUDIT RECORDS")

        hard_check_count = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM audit.integrity_checks
            WHERE build_run_id = ?
              AND severity = 'hard'
            """,
            [build_run_id],
        )

        failed_hard_checks = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM audit.integrity_checks
            WHERE build_run_id = ?
              AND severity = 'hard'
              AND NOT passed
            """,
            [build_run_id],
        )

        check_true(
            "Hard integrity checks were recorded",
            hard_check_count > 0,
            f"{hard_check_count:,} checks",
        )

        check_equal(
            "Failed hard integrity checks",
            failed_hard_checks,
            0,
        )

        source_file_records = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM audit.source_files
            WHERE build_run_id = ?
            """,
            [build_run_id],
        )

        check_equal(
            "Registered canonical source files",
            source_file_records,
            EXPECTED_SOURCE_FILES,
        )

        missing_hashes = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM audit.source_files
            WHERE build_run_id = ?
              AND NULLIF(TRIM(sha256), '') IS NULL
            """,
            [build_run_id],
        )

        check_equal(
            "Source files without SHA-256 hashes",
            missing_hashes,
            0,
        )

        failed_source_files = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM audit.source_files
            WHERE build_run_id = ?
              AND load_status = 'failed'
            """,
            [build_run_id],
        )

        check_equal(
            "Failed canonical source files",
            failed_source_files,
            0,
        )

        heading("PERSISTENT RAW VIEW COUNTS")

        print(
            "These checks reopen the canonical CSV files "
            "through the raw-schema views."
        )

        for view_name, expected_count in (
            EXPECTED_RAW_COUNTS.items()
        ):
            actual_count = scalar(
                connection,
                f"""
                SELECT COUNT(*)
                FROM raw.{view_name}
                """,
            )

            check_equal(
                f"raw.{view_name}",
                actual_count,
                expected_count,
            )

        heading("REPRESENTATIVE ANALYTICAL QUERY")

        top_events = connection.execute(
            """
            SELECT
                event_label,
                performance_count
            FROM core.events
            ORDER BY
                performance_count DESC,
                event_label
            LIMIT 10
            """
        ).fetchall()

        print("event_label | performance_count")
        print("-" * 80)

        for event_label, performance_count in top_events:
            print(
                f"{event_label} | "
                f"{performance_count:,}"
            )

        check_equal(
            "Representative query row count",
            len(top_events),
            10,
        )

    finally:
        connection.close()

    heading("FINAL VALIDATION RESULT")
    print("The database was opened in read-only mode.")
    print("No database records were created, changed, or deleted.")
    print("All independent production checks passed.")
    print()
    print("OVERALL RESULT: PASS")


if __name__ == "__main__":
    main()
