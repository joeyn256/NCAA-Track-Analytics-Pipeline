"""Profile Milestone 3 canonical sources without creating a database.

This script:

1. Opens DuckDB entirely in memory.
2. Reads canonical source CSV files with explicit VARCHAR schemas.
3. Validates established Milestone 1 and Milestone 2 totals.
4. Profiles key and referential-integrity conditions.
5. Removes all temporary DuckDB spill files when finished.

It does not create or modify the production DuckDB database.
"""

from __future__ import annotations

import re
import shutil
import sys
import time
from pathlib import Path
from typing import Sequence

import duckdb


PROJECT_ROOT = Path(
    "/Users/joeyn256/Projects/NCAA Track Analytics Pipeline"
)

RAW_DIRECTORY = PROJECT_ROOT / "data" / "raw"

PERFORMANCE_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "performance_chunks"
)

STATUS_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "parser_checkpoints"
    / "chunk_status"
)

REPORT_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "database"
    / "preflight"
)

TEMP_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "database"
    / ".source_profile_tmp"
)

PRODUCTION_DATABASE = (
    PROJECT_ROOT
    / "data"
    / "database"
    / "ncaa_track_analytics.duckdb"
)

EXPECTED_DUCKDB_VERSION = "1.5.4"

EXPECTED_TOTALS = {
    "school_team_rows": 714,
    "season_files": 714,
    "unique_athletes": 193_961,
    "roster_records": 992_774,
    "athlete_parser_status_rows": 193_954,
    "athletes_with_performances": 172_204,
    "athletes_without_performances": 21_750,
    "performance_files": 194,
    "status_files": 194,
    "performance_records": 6_594_540,
}

SCHOOL_COLUMNS = [
    "school_id",
    "tfrrs_team_id",
    "school_name",
    "slug",
    "url",
    "division",
    "gender",
    "sport",
    "conference",
    "state",
]

ATHLETE_COLUMNS = [
    "athlete_id",
    "athlete_name",
    "school",
    "team_id",
    "athlete_url",
]

ROSTER_COLUMNS = [
    "athlete_id",
    "athlete_name",
    "year",
    "school",
    "team_id",
    "season",
    "config_hnd",
]

SEASON_COLUMNS = [
    "season_name",
    "config_hnd",
    "school_name",
    "tfrrs_team_id",
]

PERFORMANCE_COLUMNS = [
    "performance_id",
    "athlete_id",
    "athlete_name",
    "athlete_class",
    "school",
    "team_id",
    "season_year",
    "season_type",
    "season_label",
    "meet_id",
    "result_id",
    "meet_name",
    "meet_date_text",
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
    "source_file",
]

STATUS_COLUMNS = [
    "chunk_number",
    "athlete_id",
    "source_file",
    "status",
    "performance_rows",
    "error_type",
    "error_message",
]


def sql_string(value: str) -> str:
    """Return a safely quoted DuckDB string literal."""
    return "'" + value.replace("'", "''") + "'"


def sql_file_list(paths: Sequence[Path]) -> str:
    """Create a DuckDB list literal containing absolute paths."""
    values = ", ".join(
        sql_string(str(path.resolve()))
        for path in paths
    )
    return f"[{values}]"


def sql_column_struct(columns: Sequence[str]) -> str:
    """Create a DuckDB STRUCT literal mapping columns to VARCHAR."""
    values = ", ".join(
        f"{sql_string(column)}: 'VARCHAR'"
        for column in columns
    )
    return "{" + values + "}"


def create_csv_view(
    connection: duckdb.DuckDBPyConnection,
    view_name: str,
    paths: Sequence[Path],
    columns: Sequence[str],
) -> None:
    """Create a temporary view over one or more canonical CSV files."""
    if not paths:
        raise RuntimeError(
            f"No source files supplied for {view_name}."
        )

    connection.execute(
        f"""
        CREATE TEMP VIEW {view_name} AS
        SELECT *
        FROM read_csv(
            {sql_file_list(paths)},
            header = true,
            delim = ',',
            quote = '"',
            escape = '"',
            columns = {sql_column_struct(columns)},
            strict_mode = true,
            filename = true
        )
        """
    )


def get_numbered_files(
    directory: Path,
    glob_pattern: str,
    filename_pattern: str,
) -> tuple[list[Path], list[int]]:
    """Return sorted files and their parsed sequence numbers."""
    files = sorted(directory.glob(glob_pattern))
    expression = re.compile(filename_pattern)

    numbered_files: list[tuple[int, Path]] = []

    for path in files:
        match = expression.fullmatch(path.name)

        if match is None:
            raise RuntimeError(
                f"Unexpected numbered filename: {path}"
            )

        numbered_files.append(
            (int(match.group(1)), path)
        )

    numbered_files.sort(key=lambda item: item[0])

    return (
        [path for _, path in numbered_files],
        [number for number, _ in numbered_files],
    )


def print_heading(title: str) -> None:
    """Print a consistent report heading."""
    print()
    print(title)
    print("=" * 80)


def timed_one_row(
    connection: duckdb.DuckDBPyConnection,
    title: str,
    query: str,
) -> dict[str, object]:
    """Execute a query expected to return one row."""
    print_heading(title)
    started = time.perf_counter()

    result = connection.execute(query)
    column_names = [
        description[0]
        for description in result.description
    ]
    row = result.fetchone()

    if row is None:
        raise RuntimeError(
            f"{title} returned no row."
        )

    values = dict(zip(column_names, row, strict=True))

    for name, value in values.items():
        print(f"{name}: {value}")

    elapsed = time.perf_counter() - started
    print(f"Query elapsed seconds: {elapsed:,.2f}")

    return values


def timed_rows(
    connection: duckdb.DuckDBPyConnection,
    title: str,
    query: str,
) -> list[tuple[object, ...]]:
    """Execute and display a multi-row profile query."""
    print_heading(title)
    started = time.perf_counter()

    result = connection.execute(query)
    column_names = [
        description[0]
        for description in result.description
    ]
    rows = result.fetchall()

    print(" | ".join(column_names))
    print("-" * 80)

    if not rows:
        print("<no rows>")
    else:
        for row in rows:
            print(
                " | ".join(
                    str(value)
                    for value in row
                )
            )

    elapsed = time.perf_counter() - started
    print(f"Query elapsed seconds: {elapsed:,.2f}")

    return rows


def main() -> None:
    """Run the complete read-only source profile."""
    failures: list[str] = []

    def check_equal(
        name: str,
        actual: object,
        expected: object,
    ) -> None:
        passed = actual == expected
        status = "PASS" if passed else "FAIL"

        print(
            f"[{status}] {name}: "
            f"actual={actual}, expected={expected}"
        )

        if not passed:
            failures.append(
                f"{name}: actual={actual}, "
                f"expected={expected}"
            )

    def check_true(
        name: str,
        condition: bool,
        details: str,
    ) -> None:
        status = "PASS" if condition else "FAIL"
        print(f"[{status}] {name}: {details}")

        if not condition:
            failures.append(
                f"{name}: {details}"
            )

    print("MILESTONE 3 CANONICAL-SOURCE PROFILE")
    print("=" * 80)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"DuckDB Python package: {duckdb.__version__}")
    print("Connection type: in-memory")
    print(f"Temporary directory: {TEMP_DIRECTORY}")
    print(f"Production database: {PRODUCTION_DATABASE}")
    print()

    if duckdb.__version__ != EXPECTED_DUCKDB_VERSION:
        raise RuntimeError(
            "Unexpected DuckDB version: "
            f"expected {EXPECTED_DUCKDB_VERSION}, "
            f"found {duckdb.__version__}"
        )

    if PRODUCTION_DATABASE.exists():
        raise RuntimeError(
            "Production database already exists. "
            "This pre-load profile will not continue until "
            "that file is reviewed."
        )

    schools_file = RAW_DIRECTORY / "schools.csv"
    athletes_file = RAW_DIRECTORY / "unique_athletes.csv"
    rosters_file = RAW_DIRECTORY / "all_roster_records.csv"

    season_files = sorted(
        (RAW_DIRECTORY / "seasons").glob("*.csv")
    )

    performance_files, performance_numbers = (
        get_numbered_files(
            PERFORMANCE_DIRECTORY,
            "performances_*.csv",
            r"performances_(\d{5})\.csv",
        )
    )

    status_files, status_numbers = get_numbered_files(
        STATUS_DIRECTORY,
        "status_*.csv",
        r"status_(\d{5})\.csv",
    )

    print_heading("FILE INVENTORY CHECKS")

    for required_file in (
        schools_file,
        athletes_file,
        rosters_file,
    ):
        check_true(
            f"Required file exists: {required_file.name}",
            required_file.is_file(),
            str(required_file),
        )

    check_equal(
        "Season file count",
        len(season_files),
        EXPECTED_TOTALS["season_files"],
    )

    check_equal(
        "Performance file count",
        len(performance_files),
        EXPECTED_TOTALS["performance_files"],
    )

    check_equal(
        "Status file count",
        len(status_files),
        EXPECTED_TOTALS["status_files"],
    )

    expected_sequence = list(
        range(
            1,
            EXPECTED_TOTALS["performance_files"] + 1,
        )
    )

    check_equal(
        "Performance file sequence",
        performance_numbers,
        expected_sequence,
    )

    check_equal(
        "Status file sequence",
        status_numbers,
        expected_sequence,
    )

    free_bytes = shutil.disk_usage(PROJECT_ROOT).free
    free_gib = free_bytes / (1024 ** 3)

    check_true(
        "Disk-space safety threshold",
        free_gib >= 20,
        f"{free_gib:,.2f} GiB free; minimum 20 GiB",
    )

    if failures:
        print()
        print("File inventory checks failed.")
        print("No source scan was started.")

        for failure in failures:
            print(f"  - {failure}")

        raise SystemExit(1)

    if TEMP_DIRECTORY.exists():
        shutil.rmtree(TEMP_DIRECTORY)

    TEMP_DIRECTORY.mkdir(parents=True, exist_ok=True)
    REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(database=":memory:")

    try:
        connection.execute(
            f"""
            SET temp_directory =
                {sql_string(str(TEMP_DIRECTORY.resolve()))}
            """
        )
        connection.execute(
            "SET max_temp_directory_size = '12GB'"
        )
        connection.execute(
            "SET memory_limit = '4GB'"
        )
        connection.execute(
            "SET threads = 4"
        )
        connection.execute(
            "SET preserve_insertion_order = false"
        )

        settings = timed_one_row(
            connection,
            "DUCKDB SESSION SETTINGS",
            """
            SELECT
                current_setting('memory_limit')
                    AS memory_limit,
                current_setting('threads')
                    AS threads,
                current_setting('temp_directory')
                    AS temp_directory,
                current_setting(
                    'max_temp_directory_size'
                ) AS max_temp_directory_size,
                current_setting(
                    'preserve_insertion_order'
                ) AS preserve_insertion_order
            """,
        )

        del settings

        print_heading("REGISTERING CANONICAL CSV SOURCES")

        create_csv_view(
            connection,
            "schools_source",
            [schools_file],
            SCHOOL_COLUMNS,
        )
        print("schools_source: READY")

        create_csv_view(
            connection,
            "athletes_source",
            [athletes_file],
            ATHLETE_COLUMNS,
        )
        print("athletes_source: READY")

        create_csv_view(
            connection,
            "rosters_source",
            [rosters_file],
            ROSTER_COLUMNS,
        )
        print("rosters_source: READY")

        create_csv_view(
            connection,
            "seasons_source",
            season_files,
            SEASON_COLUMNS,
        )
        print("seasons_source: READY")

        create_csv_view(
            connection,
            "performance_source",
            performance_files,
            PERFORMANCE_COLUMNS,
        )
        print("performance_source: READY")

        create_csv_view(
            connection,
            "chunk_status_source",
            status_files,
            STATUS_COLUMNS,
        )
        print("chunk_status_source: READY")

        school_metrics = timed_one_row(
            connection,
            "SCHOOL AND TEAM SOURCE METRICS",
            """
            SELECT
                COUNT(*) AS total_rows,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(school_id),
                        ''
                    )
                ) AS distinct_school_ids,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(tfrrs_team_id),
                        ''
                    )
                ) AS distinct_team_ids,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(school_id),
                        ''
                    ) IS NULL
                ) AS blank_school_ids,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(tfrrs_team_id),
                        ''
                    ) IS NULL
                ) AS blank_team_ids
            FROM schools_source
            """,
        )

        check_equal(
            "School/team source row count",
            school_metrics["total_rows"],
            EXPECTED_TOTALS["school_team_rows"],
        )

        check_equal(
            "Distinct TFRRS team IDs",
            school_metrics["distinct_team_ids"],
            EXPECTED_TOTALS["school_team_rows"],
        )

        check_equal(
            "Blank TFRRS team IDs",
            school_metrics["blank_team_ids"],
            0,
        )

        athlete_metrics = timed_one_row(
            connection,
            "ATHLETE SOURCE METRICS",
            """
            SELECT
                COUNT(*) AS total_rows,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(athlete_id),
                        ''
                    )
                ) AS distinct_athlete_ids,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(athlete_id),
                        ''
                    ) IS NULL
                ) AS blank_athlete_ids,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(team_id),
                        ''
                    )
                ) AS distinct_current_team_ids,
                COUNT(
                    DISTINCT filename
                ) AS source_files
            FROM athletes_source
            """,
        )

        check_equal(
            "Unique-athlete row count",
            athlete_metrics["total_rows"],
            EXPECTED_TOTALS["unique_athletes"],
        )

        check_equal(
            "Distinct athlete IDs",
            athlete_metrics["distinct_athlete_ids"],
            EXPECTED_TOTALS["unique_athletes"],
        )

        check_equal(
            "Blank athlete IDs",
            athlete_metrics["blank_athlete_ids"],
            0,
        )

        roster_metrics = timed_one_row(
            connection,
            "HISTORICAL ROSTER SOURCE METRICS",
            """
            SELECT
                COUNT(*) AS total_rows,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(athlete_id),
                        ''
                    )
                ) AS distinct_athlete_ids,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(team_id),
                        ''
                    )
                ) AS distinct_team_ids,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(config_hnd),
                        ''
                    )
                ) AS distinct_config_hnd_values,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(athlete_id),
                        ''
                    ) IS NULL
                ) AS blank_athlete_ids,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(team_id),
                        ''
                    ) IS NULL
                ) AS blank_team_ids,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(season),
                        ''
                    ) IS NULL
                ) AS blank_seasons,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(config_hnd),
                        ''
                    ) IS NULL
                ) AS blank_config_hnd_values
            FROM rosters_source
            """,
        )

        check_equal(
            "Historical roster row count",
            roster_metrics["total_rows"],
            EXPECTED_TOTALS["roster_records"],
        )

        check_equal(
            "Roster blank athlete IDs",
            roster_metrics["blank_athlete_ids"],
            0,
        )

        check_equal(
            "Roster blank team IDs",
            roster_metrics["blank_team_ids"],
            0,
        )

        roster_duplicate_metrics = timed_one_row(
            connection,
            "HISTORICAL ROSTER EXACT-DUPLICATE PROFILE",
            """
            WITH distinct_roster_rows AS (
                SELECT DISTINCT
                    athlete_id,
                    athlete_name,
                    year,
                    school,
                    team_id,
                    season,
                    config_hnd
                FROM rosters_source
            )
            SELECT
                (
                    SELECT COUNT(*)
                    FROM rosters_source
                ) AS source_rows,
                (
                    SELECT COUNT(*)
                    FROM distinct_roster_rows
                ) AS distinct_full_rows,
                (
                    SELECT COUNT(*)
                    FROM rosters_source
                ) - (
                    SELECT COUNT(*)
                    FROM distinct_roster_rows
                ) AS duplicate_full_rows
            """,
        )

        check_equal(
            "Exact duplicate roster rows",
            roster_duplicate_metrics[
                "duplicate_full_rows"
            ],
            0,
        )

        season_metrics = timed_one_row(
            connection,
            "SEASON SOURCE METRICS",
            """
            SELECT
                COUNT(*) AS total_rows,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(config_hnd),
                        ''
                    )
                ) AS distinct_config_hnd_values,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(tfrrs_team_id),
                        ''
                    )
                ) AS distinct_team_ids,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(config_hnd),
                        ''
                    ) IS NULL
                ) AS blank_config_hnd_values,
                COUNT(
                    DISTINCT filename
                ) AS source_files
            FROM seasons_source
            """,
        )

        check_equal(
            "Season source files read",
            season_metrics["source_files"],
            EXPECTED_TOTALS["season_files"],
        )

        status_metrics = timed_one_row(
            connection,
            "PARSER STATUS RECONCILIATION",
            """
            SELECT
                COUNT(*) AS total_status_rows,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(athlete_id),
                        ''
                    )
                ) AS distinct_athlete_ids,
                COUNT(
                    DISTINCT filename
                ) AS source_status_files,
                COALESCE(
                    SUM(
                        TRY_CAST(
                            performance_rows
                            AS BIGINT
                        )
                    ),
                    0
                ) AS summed_performance_rows,
                COUNT(*) FILTER (
                    WHERE TRY_CAST(
                        performance_rows
                        AS BIGINT
                    ) > 0
                ) AS athletes_with_performances,
                COUNT(*) FILTER (
                    WHERE COALESCE(
                        TRY_CAST(
                            performance_rows
                            AS BIGINT
                        ),
                        0
                    ) = 0
                ) AS athletes_without_performances,
                COUNT(*) FILTER (
                    WHERE
                        NULLIF(
                            TRIM(error_type),
                            ''
                        ) IS NOT NULL
                        OR NULLIF(
                            TRIM(error_message),
                            ''
                        ) IS NOT NULL
                ) AS rows_with_error_details,
                COUNT(*) FILTER (
                    WHERE
                        LOWER(
                            COALESCE(status, '')
                        ) LIKE '%fail%'
                        OR LOWER(
                            COALESCE(status, '')
                        ) LIKE '%error%'
                ) AS failure_status_rows
            FROM chunk_status_source
            """,
        )

        check_equal(
            "Parser status row count",
            status_metrics["total_status_rows"],
            EXPECTED_TOTALS[
                "athlete_parser_status_rows"
            ],
        )

        check_equal(
            "Distinct parser-status athletes",
            status_metrics["distinct_athlete_ids"],
            EXPECTED_TOTALS[
                "athlete_parser_status_rows"
            ],
        )

        check_equal(
            "Status files read",
            status_metrics["source_status_files"],
            EXPECTED_TOTALS["status_files"],
        )

        check_equal(
            "Status performance-row sum",
            status_metrics["summed_performance_rows"],
            EXPECTED_TOTALS["performance_records"],
        )

        check_equal(
            "Athletes with performances",
            status_metrics[
                "athletes_with_performances"
            ],
            EXPECTED_TOTALS[
                "athletes_with_performances"
            ],
        )

        check_equal(
            "Athletes without performances",
            status_metrics[
                "athletes_without_performances"
            ],
            EXPECTED_TOTALS[
                "athletes_without_performances"
            ],
        )

        check_equal(
            "Status rows with error details",
            status_metrics["rows_with_error_details"],
            0,
        )

        check_equal(
            "Failure status rows",
            status_metrics["failure_status_rows"],
            0,
        )

        timed_rows(
            connection,
            "PARSER STATUS DISTRIBUTION",
            """
            SELECT
                COALESCE(
                    NULLIF(TRIM(status), ''),
                    '<blank>'
                ) AS status,
                COUNT(*) AS athlete_rows,
                COALESCE(
                    SUM(
                        TRY_CAST(
                            performance_rows
                            AS BIGINT
                        )
                    ),
                    0
                ) AS performance_rows
            FROM chunk_status_source
            GROUP BY 1
            ORDER BY athlete_rows DESC, status
            """,
        )

        performance_metrics = timed_one_row(
            connection,
            "PERFORMANCE SOURCE INTEGRITY",
            """
            SELECT
                COUNT(*) AS total_rows,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(performance_id),
                        ''
                    )
                ) AS distinct_performance_ids,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(athlete_id),
                        ''
                    )
                ) AS distinct_athlete_ids,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(team_id),
                        ''
                    )
                ) AS distinct_team_ids,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(meet_id),
                        ''
                    )
                ) AS distinct_meet_ids,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(result_id),
                        ''
                    )
                ) AS distinct_result_ids,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(event),
                        ''
                    )
                ) AS distinct_event_labels,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(source_file),
                        ''
                    )
                ) AS distinct_parser_source_files,
                COUNT(
                    DISTINCT filename
                ) AS source_chunk_files,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(performance_id),
                        ''
                    ) IS NULL
                ) AS blank_performance_ids,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(athlete_id),
                        ''
                    ) IS NULL
                ) AS blank_athlete_ids,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(team_id),
                        ''
                    ) IS NULL
                ) AS blank_team_ids,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(meet_id),
                        ''
                    ) IS NULL
                ) AS blank_meet_ids,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(event),
                        ''
                    ) IS NULL
                ) AS blank_event_labels,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(mark),
                        ''
                    ) IS NULL
                ) AS blank_marks,
                COUNT(*) FILTER (
                    WHERE NULLIF(
                        TRIM(meet_date_text),
                        ''
                    ) IS NULL
                ) AS blank_meet_dates,
                COUNT(*) FILTER (
                    WHERE
                        NULLIF(
                            TRIM(season_year),
                            ''
                        ) IS NOT NULL
                        AND TRY_CAST(
                            season_year AS INTEGER
                        ) IS NULL
                ) AS invalid_numeric_season_years
            FROM performance_source
            """,
        )

        check_equal(
            "Performance row count",
            performance_metrics["total_rows"],
            EXPECTED_TOTALS["performance_records"],
        )

        check_equal(
            "Distinct performance IDs",
            performance_metrics[
                "distinct_performance_ids"
            ],
            EXPECTED_TOTALS["performance_records"],
        )

        check_equal(
            "Duplicate performance IDs",
            performance_metrics["total_rows"]
            - performance_metrics[
                "distinct_performance_ids"
            ],
            0,
        )

        check_equal(
            "Blank performance IDs",
            performance_metrics[
                "blank_performance_ids"
            ],
            0,
        )

        check_equal(
            "Distinct performance athletes",
            performance_metrics[
                "distinct_athlete_ids"
            ],
            EXPECTED_TOTALS[
                "athletes_with_performances"
            ],
        )

        check_equal(
            "Performance chunk files read",
            performance_metrics["source_chunk_files"],
            EXPECTED_TOTALS["performance_files"],
        )

        check_equal(
            "Invalid numeric season years",
            performance_metrics[
                "invalid_numeric_season_years"
            ],
            0,
        )

        timed_rows(
            connection,
            "PERFORMANCE SEASON-TYPE DISTRIBUTION",
            """
            SELECT
                COALESCE(
                    NULLIF(TRIM(season_type), ''),
                    '<blank>'
                ) AS season_type,
                MIN(
                    TRY_CAST(
                        season_year AS INTEGER
                    )
                ) AS minimum_season_year,
                MAX(
                    TRY_CAST(
                        season_year AS INTEGER
                    )
                ) AS maximum_season_year,
                COUNT(*) AS performance_rows,
                COUNT(
                    DISTINCT NULLIF(
                        TRIM(season_label),
                        ''
                    )
                ) AS distinct_season_labels
            FROM performance_source
            GROUP BY 1
            ORDER BY performance_rows DESC
            """,
        )

        print_heading(
            "BUILDING TEMPORARY DISTINCT AFFILIATION KEYS"
        )
        started = time.perf_counter()

        connection.execute(
            """
            CREATE TEMP TABLE
                performance_affiliation_keys
            AS
            SELECT
                NULLIF(
                    TRIM(athlete_id),
                    ''
                ) AS athlete_id,
                NULLIF(
                    TRIM(team_id),
                    ''
                ) AS team_id,
                NULLIF(
                    TRIM(school),
                    ''
                ) AS school,
                NULLIF(
                    TRIM(season_label),
                    ''
                ) AS season_label,
                COUNT(*)::BIGINT AS performance_rows
            FROM performance_source
            GROUP BY 1, 2, 3, 4
            """
        )

        connection.execute(
            """
            CREATE TEMP TABLE
                roster_affiliation_keys
            AS
            SELECT DISTINCT
                NULLIF(
                    TRIM(athlete_id),
                    ''
                ) AS athlete_id,
                NULLIF(
                    TRIM(team_id),
                    ''
                ) AS team_id,
                NULLIF(
                    TRIM(season),
                    ''
                ) AS season_label
            FROM rosters_source
            WHERE
                NULLIF(
                    TRIM(athlete_id),
                    ''
                ) IS NOT NULL
                AND NULLIF(
                    TRIM(team_id),
                    ''
                ) IS NOT NULL
                AND NULLIF(
                    TRIM(season),
                    ''
                ) IS NOT NULL
            """
        )

        elapsed = time.perf_counter() - started
        print(
            "Temporary aggregate key tables: READY"
        )
        print(f"Build elapsed seconds: {elapsed:,.2f}")

        reference_metrics = timed_one_row(
            connection,
            "SOURCE REFERENTIAL-COVERAGE PROFILE",
            """
            WITH
            known_athletes AS (
                SELECT DISTINCT
                    NULLIF(
                        TRIM(athlete_id),
                        ''
                    ) AS athlete_id
                FROM athletes_source
            ),
            known_teams AS (
                SELECT DISTINCT
                    NULLIF(
                        TRIM(tfrrs_team_id),
                        ''
                    ) AS team_id
                FROM schools_source
            ),
            performance_athletes AS (
                SELECT DISTINCT athlete_id
                FROM performance_affiliation_keys
                WHERE athlete_id IS NOT NULL
            ),
            performance_teams AS (
                SELECT DISTINCT team_id
                FROM performance_affiliation_keys
                WHERE team_id IS NOT NULL
            ),
            roster_athletes AS (
                SELECT DISTINCT athlete_id
                FROM roster_affiliation_keys
            ),
            roster_teams AS (
                SELECT DISTINCT team_id
                FROM roster_affiliation_keys
            )
            SELECT
                (
                    SELECT COUNT(*)
                    FROM performance_athletes p
                    LEFT JOIN known_athletes a
                        USING (athlete_id)
                    WHERE a.athlete_id IS NULL
                ) AS performance_athletes_not_in_master,
                (
                    SELECT COUNT(*)
                    FROM performance_teams p
                    LEFT JOIN known_teams t
                        USING (team_id)
                    WHERE t.team_id IS NULL
                ) AS performance_teams_not_in_directory,
                (
                    SELECT COUNT(*)
                    FROM roster_athletes r
                    LEFT JOIN known_athletes a
                        USING (athlete_id)
                    WHERE a.athlete_id IS NULL
                ) AS roster_athletes_not_in_master,
                (
                    SELECT COUNT(*)
                    FROM roster_teams r
                    LEFT JOIN known_teams t
                        USING (team_id)
                    WHERE t.team_id IS NULL
                ) AS roster_teams_not_in_directory
            """,
        )

        check_equal(
            "Performance athletes absent from master",
            reference_metrics[
                "performance_athletes_not_in_master"
            ],
            0,
        )

        check_equal(
            "Roster athletes absent from master",
            reference_metrics[
                "roster_athletes_not_in_master"
            ],
            0,
        )

        check_equal(
            "Roster teams absent from directory",
            reference_metrics[
                "roster_teams_not_in_directory"
            ],
            0,
        )

        affiliation_metrics = timed_one_row(
            connection,
            "EXACT HISTORICAL-AFFILIATION COVERAGE",
            """
            SELECT
                COUNT(*) AS distinct_performance_keys,
                COUNT(*) FILTER (
                    WHERE r.athlete_id IS NOT NULL
                ) AS matched_distinct_keys,
                COUNT(*) FILTER (
                    WHERE r.athlete_id IS NULL
                ) AS unmatched_distinct_keys,
                COALESCE(
                    SUM(p.performance_rows),
                    0
                ) AS total_performance_rows,
                COALESCE(
                    SUM(p.performance_rows)
                    FILTER (
                        WHERE r.athlete_id IS NOT NULL
                    ),
                    0
                ) AS matched_performance_rows,
                COALESCE(
                    SUM(p.performance_rows)
                    FILTER (
                        WHERE r.athlete_id IS NULL
                    ),
                    0
                ) AS unmatched_performance_rows
            FROM performance_affiliation_keys p
            LEFT JOIN roster_affiliation_keys r
                ON p.athlete_id = r.athlete_id
                AND p.team_id = r.team_id
                AND p.season_label = r.season_label
            """,
        )

        check_equal(
            "Affiliation profile performance total",
            affiliation_metrics[
                "total_performance_rows"
            ],
            EXPECTED_TOTALS["performance_records"],
        )

        timed_rows(
            connection,
            "TOP PERFORMANCE TEAMS OUTSIDE 714-TEAM DIRECTORY",
            """
            WITH known_teams AS (
                SELECT DISTINCT
                    NULLIF(
                        TRIM(tfrrs_team_id),
                        ''
                    ) AS team_id
                FROM schools_source
            )
            SELECT
                p.team_id,
                MIN(p.school) AS example_school,
                COUNT(
                    DISTINCT p.athlete_id
                ) AS distinct_athletes,
                SUM(
                    p.performance_rows
                ) AS performance_rows
            FROM performance_affiliation_keys p
            LEFT JOIN known_teams t
                USING (team_id)
            WHERE
                p.team_id IS NOT NULL
                AND t.team_id IS NULL
            GROUP BY p.team_id
            ORDER BY
                performance_rows DESC,
                p.team_id
            LIMIT 30
            """,
        )

    finally:
        connection.close()
        shutil.rmtree(
            TEMP_DIRECTORY,
            ignore_errors=True,
        )

    print_heading("FINAL HARD-CHECK SUMMARY")

    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")

        print()
        print("OVERALL RESULT: FAIL")
        print(
            "The production database was not created."
        )
        raise SystemExit(1)

    print("All established source-total checks passed.")
    print("All required identifier checks passed.")
    print("Parser status and performance totals reconcile.")
    print("Temporary DuckDB files were removed.")
    print("The production database was not created.")
    print()
    print("OVERALL RESULT: PASS")


if __name__ == "__main__":
    main()
