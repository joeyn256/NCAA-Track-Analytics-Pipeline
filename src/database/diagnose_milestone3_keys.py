"""Diagnose Milestone 3 relational keys without creating a database.

This script determines:

1. How the 714 directory team rows collapse into institutions.
2. Which roster key should define historical athlete affiliations.
3. How roster season/config values map to performance seasons.
4. Whether indoor seasons use their starting or ending year.
5. How performance-only historical teams should be represented.

The connection is completely in memory. No production database is created.
"""

from __future__ import annotations

import re
import shutil
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

TEMP_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "database"
    / ".key_diagnostic_tmp"
)

PRODUCTION_DATABASE = (
    PROJECT_ROOT
    / "data"
    / "database"
    / "ncaa_track_analytics.duckdb"
)

EXPECTED_DUCKDB_VERSION = "1.5.4"

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


def sql_string(value: str) -> str:
    """Return a safely quoted DuckDB string literal."""
    return "'" + value.replace("'", "''") + "'"


def sql_file_list(paths: Sequence[Path]) -> str:
    """Return a DuckDB list literal containing absolute file paths."""
    return (
        "["
        + ", ".join(
            sql_string(str(path.resolve()))
            for path in paths
        )
        + "]"
    )


def sql_column_struct(columns: Sequence[str]) -> str:
    """Return a DuckDB STRUCT literal mapping columns to VARCHAR."""
    return (
        "{"
        + ", ".join(
            f"{sql_string(column)}: 'VARCHAR'"
            for column in columns
        )
        + "}"
    )


def create_csv_view(
    connection: duckdb.DuckDBPyConnection,
    view_name: str,
    paths: Sequence[Path],
    columns: Sequence[str],
) -> None:
    """Create a temporary view over explicitly typed CSV files."""
    if not paths:
        raise RuntimeError(
            f"No source files found for {view_name}."
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


def heading(title: str) -> None:
    """Print a report heading."""
    print()
    print(title)
    print("=" * 88)


def query_one(
    connection: duckdb.DuckDBPyConnection,
    title: str,
    sql: str,
) -> dict[str, object]:
    """Run and display a one-row query."""
    heading(title)
    started = time.perf_counter()

    result = connection.execute(sql)
    names = [
        description[0]
        for description in result.description
    ]
    row = result.fetchone()

    if row is None:
        raise RuntimeError(
            f"{title} returned no row."
        )

    values = dict(zip(names, row, strict=True))

    for name, value in values.items():
        print(f"{name}: {value}")

    print(
        "Query elapsed seconds: "
        f"{time.perf_counter() - started:,.2f}"
    )

    return values


def query_rows(
    connection: duckdb.DuckDBPyConnection,
    title: str,
    sql: str,
) -> list[tuple[object, ...]]:
    """Run and display a multi-row query."""
    heading(title)
    started = time.perf_counter()

    result = connection.execute(sql)
    names = [
        description[0]
        for description in result.description
    ]
    rows = result.fetchall()

    print(" | ".join(names))
    print("-" * 88)

    if not rows:
        print("<no rows>")
    else:
        for row in rows:
            print(
                " | ".join(
                    "<null>" if value is None else str(value)
                    for value in row
                )
            )

    print(
        "Query elapsed seconds: "
        f"{time.perf_counter() - started:,.2f}"
    )

    return rows


def classify_season_type(label: str) -> str:
    """Classify a source season label."""
    normalized = label.lower().replace("_", " ")

    if "cross" in normalized:
        return "cross_country"

    if "indoor" in normalized:
        return "indoor"

    if "outdoor" in normalized:
        return "outdoor"

    return "unknown"


def parse_season_years(
    label: str,
) -> tuple[int | None, int | None]:
    """Extract starting and ending years from a season label."""
    normalized = label.replace("_", " ").replace("-", " ")

    four_digit_years = [
        int(value)
        for value in re.findall(
            r"(?<!\d)(?:19|20)\d{2}(?!\d)",
            normalized,
        )
    ]

    if len(four_digit_years) >= 2:
        return (
            four_digit_years[0],
            four_digit_years[-1],
        )

    if len(four_digit_years) == 1:
        start_year = four_digit_years[0]
        end_year = start_year

        short_year_match = re.search(
            r"((?:19|20)\d{2})\D+(\d{2})(?!\d)",
            label,
        )

        if short_year_match is not None:
            short_year = int(short_year_match.group(2))
            century = (start_year // 100) * 100
            candidate_end_year = century + short_year

            if candidate_end_year < start_year:
                candidate_end_year += 100

            end_year = candidate_end_year

        return start_year, end_year

    return None, None


def normalize_performance_type(value: str | None) -> str:
    """Normalize a performance season-type value."""
    if value is None:
        return "unknown"

    normalized = value.lower().replace("_", " ")

    if "cross" in normalized:
        return "cross_country"

    if "indoor" in normalized:
        return "indoor"

    if "outdoor" in normalized:
        return "outdoor"

    return "unknown"


def main() -> None:
    """Run the complete in-memory diagnostic."""
    print("MILESTONE 3 RELATIONAL-KEY DIAGNOSTIC")
    print("=" * 88)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"DuckDB version: {duckdb.__version__}")
    print("Connection: in-memory")
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
            "The production database already exists. "
            "This diagnostic will not open or modify it."
        )

    schools_file = RAW_DIRECTORY / "schools.csv"
    roster_file = RAW_DIRECTORY / "all_roster_records.csv"

    season_files = sorted(
        (RAW_DIRECTORY / "seasons").glob("*.csv")
    )

    performance_files = sorted(
        PERFORMANCE_DIRECTORY.glob(
            "performances_*.csv"
        )
    )

    if len(season_files) != 714:
        raise RuntimeError(
            "Expected 714 season files, found "
            f"{len(season_files)}."
        )

    if len(performance_files) != 194:
        raise RuntimeError(
            "Expected 194 performance chunks, found "
            f"{len(performance_files)}."
        )

    if TEMP_DIRECTORY.exists():
        shutil.rmtree(TEMP_DIRECTORY)

    TEMP_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

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

        heading("REGISTERING SOURCES")

        create_csv_view(
            connection,
            "schools_source",
            [schools_file],
            SCHOOL_COLUMNS,
        )
        print("schools_source: READY")

        create_csv_view(
            connection,
            "rosters_source",
            [roster_file],
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

        heading("MATERIALIZING DIAGNOSTIC SUMMARIES")
        started = time.perf_counter()

        connection.execute(
            """
            CREATE TEMP TABLE performance_affiliation_keys AS
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
                TRY_CAST(
                    season_year AS INTEGER
                ) AS season_year,
                CASE
                    WHEN LOWER(
                        COALESCE(season_type, '')
                    ) LIKE '%cross%'
                        THEN 'cross_country'
                    WHEN LOWER(
                        COALESCE(season_type, '')
                    ) LIKE '%indoor%'
                        THEN 'indoor'
                    WHEN LOWER(
                        COALESCE(season_type, '')
                    ) LIKE '%outdoor%'
                        THEN 'outdoor'
                    ELSE 'unknown'
                END AS season_type,
                NULLIF(
                    TRIM(season_label),
                    ''
                ) AS season_label,
                COUNT(*)::BIGINT AS performance_rows
            FROM performance_source
            GROUP BY 1, 2, 3, 4, 5, 6
            """
        )

        print(
            "performance_affiliation_keys: READY "
            f"({time.perf_counter() - started:,.2f} seconds)"
        )

        query_one(
            connection,
            "DIRECTORY INSTITUTION-KEY PROFILE",
            """
            WITH directory_rows AS (
                SELECT
                    school_id,
                    tfrrs_team_id,
                    school_name,
                    gender,
                    state,
                    REGEXP_REPLACE(
                        tfrrs_team_id,
                        '_college_[mf]_',
                        '_college_'
                    ) AS proposed_institution_key
                FROM schools_source
            ),
            institution_groups AS (
                SELECT
                    proposed_institution_key,
                    COUNT(*) AS team_rows,
                    COUNT(
                        DISTINCT school_name
                    ) AS distinct_school_names,
                    COUNT(
                        DISTINCT state
                    ) AS distinct_states,
                    COUNT(
                        DISTINCT gender
                    ) AS distinct_genders
                FROM directory_rows
                GROUP BY proposed_institution_key
            )
            SELECT
                (
                    SELECT COUNT(*)
                    FROM directory_rows
                ) AS source_team_rows,
                (
                    SELECT COUNT(
                        DISTINCT school_id
                    )
                    FROM directory_rows
                ) AS distinct_source_school_ids,
                COUNT(*) AS proposed_institutions,
                COUNT(*) FILTER (
                    WHERE team_rows = 2
                ) AS two_team_institutions,
                COUNT(*) FILTER (
                    WHERE team_rows = 1
                ) AS single_team_institutions,
                COUNT(*) FILTER (
                    WHERE team_rows > 2
                ) AS keys_with_more_than_two_teams,
                COUNT(*) FILTER (
                    WHERE distinct_school_names > 1
                ) AS keys_with_multiple_school_names
            FROM institution_groups
            """,
        )

        query_rows(
            connection,
            "DIRECTORY INSTITUTION-KEY EXCEPTIONS",
            """
            WITH directory_rows AS (
                SELECT
                    school_id,
                    tfrrs_team_id,
                    school_name,
                    gender,
                    state,
                    REGEXP_REPLACE(
                        tfrrs_team_id,
                        '_college_[mf]_',
                        '_college_'
                    ) AS proposed_institution_key
                FROM schools_source
            ),
            grouped AS (
                SELECT
                    proposed_institution_key,
                    COUNT(*) AS team_rows,
                    COUNT(
                        DISTINCT school_name
                    ) AS distinct_school_names,
                    STRING_AGG(
                        tfrrs_team_id,
                        ' | '
                        ORDER BY tfrrs_team_id
                    ) AS team_ids,
                    STRING_AGG(
                        school_name,
                        ' | '
                        ORDER BY school_name
                    ) AS school_names
                FROM directory_rows
                GROUP BY proposed_institution_key
            )
            SELECT *
            FROM grouped
            WHERE
                team_rows <> 2
                OR distinct_school_names <> 1
            ORDER BY
                team_rows DESC,
                proposed_institution_key
            """,
        )

        query_one(
            connection,
            "ROSTER KEY-CANDIDATE COUNTS",
            """
            SELECT
                (
                    SELECT COUNT(*)
                    FROM rosters_source
                ) AS source_rows,

                (
                    SELECT COUNT(*)
                    FROM (
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
                ) AS distinct_full_rows,

                (
                    SELECT COUNT(*)
                    FROM (
                        SELECT DISTINCT
                            athlete_id,
                            team_id,
                            season,
                            config_hnd
                        FROM rosters_source
                    )
                ) AS distinct_athlete_team_season_config,

                (
                    SELECT COUNT(*)
                    FROM (
                        SELECT DISTINCT
                            athlete_id,
                            team_id,
                            config_hnd
                        FROM rosters_source
                    )
                ) AS distinct_athlete_team_config,

                (
                    SELECT COUNT(*)
                    FROM (
                        SELECT DISTINCT
                            athlete_id,
                            team_id,
                            season
                        FROM rosters_source
                    )
                ) AS distinct_athlete_team_season
            """,
        )

        query_rows(
            connection,
            "TOP EXACT-DUPLICATE ROSTER GROUPS",
            """
            SELECT
                athlete_id,
                athlete_name,
                year,
                school,
                team_id,
                season,
                config_hnd,
                COUNT(*) AS source_occurrences
            FROM rosters_source
            GROUP BY
                athlete_id,
                athlete_name,
                year,
                school,
                team_id,
                season,
                config_hnd
            HAVING COUNT(*) > 1
            ORDER BY
                source_occurrences DESC,
                athlete_id,
                team_id,
                config_hnd
            LIMIT 30
            """,
        )

        query_one(
            connection,
            "ROSTER AFFILIATION-KEY CONFLICT PROFILE",
            """
            WITH grouped AS (
                SELECT
                    athlete_id,
                    team_id,
                    config_hnd,
                    COUNT(
                        DISTINCT season
                    ) AS season_values,
                    COUNT(
                        DISTINCT year
                    ) AS class_year_values,
                    COUNT(
                        DISTINCT school
                    ) AS school_values,
                    COUNT(
                        DISTINCT athlete_name
                    ) AS athlete_name_values
                FROM rosters_source
                GROUP BY
                    athlete_id,
                    team_id,
                    config_hnd
            )
            SELECT
                COUNT(*) AS candidate_affiliation_keys,
                COUNT(*) FILTER (
                    WHERE season_values > 1
                ) AS keys_with_multiple_seasons,
                COUNT(*) FILTER (
                    WHERE class_year_values > 1
                ) AS keys_with_multiple_class_years,
                COUNT(*) FILTER (
                    WHERE school_values > 1
                ) AS keys_with_multiple_school_names,
                COUNT(*) FILTER (
                    WHERE athlete_name_values > 1
                ) AS keys_with_multiple_athlete_names
            FROM grouped
            """,
        )

        query_one(
            connection,
            "ROSTER-TO-SEASON-CONFIG COVERAGE",
            """
            WITH season_keys AS (
                SELECT DISTINCT
                    NULLIF(
                        TRIM(tfrrs_team_id),
                        ''
                    ) AS team_id,
                    NULLIF(
                        TRIM(config_hnd),
                        ''
                    ) AS config_hnd
                FROM seasons_source
            )
            SELECT
                COUNT(*) AS roster_rows,
                COUNT(*) FILTER (
                    WHERE s.team_id IS NOT NULL
                ) AS matched_roster_rows,
                COUNT(*) FILTER (
                    WHERE s.team_id IS NULL
                ) AS unmatched_roster_rows
            FROM rosters_source r
            LEFT JOIN season_keys s
                ON NULLIF(
                    TRIM(r.team_id),
                    ''
                ) = s.team_id
                AND NULLIF(
                    TRIM(r.config_hnd),
                    ''
                ) = s.config_hnd
            """,
        )

        season_name_rows = connection.execute(
            """
            SELECT DISTINCT
                NULLIF(
                    TRIM(config_hnd),
                    ''
                ) AS config_hnd,
                NULLIF(
                    TRIM(season_name),
                    ''
                ) AS season_name
            FROM seasons_source
            WHERE
                NULLIF(
                    TRIM(config_hnd),
                    ''
                ) IS NOT NULL
                AND NULLIF(
                    TRIM(season_name),
                    ''
                ) IS NOT NULL
            ORDER BY config_hnd, season_name
            """
        ).fetchall()

        season_labels_by_config: dict[str, set[str]] = {}

        for config_hnd, season_name in season_name_rows:
            season_labels_by_config.setdefault(
                str(config_hnd),
                set(),
            ).add(str(season_name))

        season_bridge_rows = []

        heading("PARSED SEASON-CONFIG MAP")
        print(
            "config_hnd | type | start_year | end_year | "
            "source_labels"
        )
        print("-" * 88)

        for config_hnd in sorted(
            season_labels_by_config,
            key=lambda value: (
                int(value)
                if value.isdigit()
                else value
            ),
        ):
            labels = sorted(
                season_labels_by_config[config_hnd]
            )

            parsed_values = {
                (
                    classify_season_type(label),
                    *parse_season_years(label),
                )
                for label in labels
            }

            if len(parsed_values) != 1:
                season_type = "conflict"
                start_year = None
                end_year = None
            else:
                (
                    season_type,
                    start_year,
                    end_year,
                ) = next(iter(parsed_values))

            source_labels = " | ".join(labels)

            season_bridge_rows.append(
                (
                    config_hnd,
                    start_year,
                    end_year,
                    season_type,
                    source_labels,
                )
            )

            print(
                f"{config_hnd} | "
                f"{season_type} | "
                f"{start_year} | "
                f"{end_year} | "
                f"{source_labels}"
            )

        connection.execute(
            """
            CREATE TEMP TABLE season_bridge (
                config_hnd VARCHAR,
                start_year INTEGER,
                end_year INTEGER,
                season_type VARCHAR,
                source_labels VARCHAR
            )
            """
        )

        connection.executemany(
            """
            INSERT INTO season_bridge
            VALUES (?, ?, ?, ?, ?)
            """,
            season_bridge_rows,
        )

        query_one(
            connection,
            "SEASON-BRIDGE PARSE QUALITY",
            """
            SELECT
                COUNT(*) AS config_values,
                COUNT(*) FILTER (
                    WHERE season_type = 'unknown'
                ) AS unknown_type_values,
                COUNT(*) FILTER (
                    WHERE season_type = 'conflict'
                ) AS conflicting_config_values,
                COUNT(*) FILTER (
                    WHERE start_year IS NULL
                       OR end_year IS NULL
                ) AS unparsed_year_values,
                COUNT(
                    DISTINCT (
                        end_year,
                        season_type
                    )
                ) AS distinct_end_year_type_keys,
                COUNT(
                    DISTINCT (
                        start_year,
                        season_type
                    )
                ) AS distinct_start_year_type_keys
            FROM season_bridge
            """,
        )

        query_rows(
            connection,
            "PERFORMANCE SEASON VALUES",
            """
            SELECT
                season_year,
                season_type,
                season_label,
                COUNT(*) AS distinct_affiliation_keys,
                SUM(
                    performance_rows
                ) AS performance_rows
            FROM performance_affiliation_keys
            GROUP BY
                season_year,
                season_type,
                season_label
            ORDER BY
                season_year,
                season_type,
                season_label
            """,
        )

        query_one(
            connection,
            "TEAM-DOMAIN UNION PROFILE",
            """
            WITH directory_teams AS (
                SELECT DISTINCT
                    NULLIF(
                        TRIM(tfrrs_team_id),
                        ''
                    ) AS team_id
                FROM schools_source
            ),
            performance_teams AS (
                SELECT DISTINCT team_id
                FROM performance_affiliation_keys
                WHERE team_id IS NOT NULL
            )
            SELECT
                (
                    SELECT COUNT(*)
                    FROM directory_teams
                ) AS directory_team_ids,

                (
                    SELECT COUNT(*)
                    FROM performance_teams
                ) AS performance_team_ids,

                (
                    SELECT COUNT(*)
                    FROM performance_teams p
                    INNER JOIN directory_teams d
                        USING (team_id)
                ) AS shared_team_ids,

                (
                    SELECT COUNT(*)
                    FROM performance_teams p
                    LEFT JOIN directory_teams d
                        USING (team_id)
                    WHERE d.team_id IS NULL
                ) AS performance_only_team_ids,

                (
                    SELECT COUNT(*)
                    FROM (
                        SELECT team_id
                        FROM directory_teams

                        UNION

                        SELECT team_id
                        FROM performance_teams
                    )
                ) AS combined_team_domain
            """,
        )

        query_rows(
            connection,
            "TOP PERFORMANCE-ONLY HISTORICAL TEAMS",
            """
            WITH directory_teams AS (
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
            LEFT JOIN directory_teams d
                USING (team_id)
            WHERE
                p.team_id IS NOT NULL
                AND d.team_id IS NULL
            GROUP BY p.team_id
            ORDER BY
                performance_rows DESC,
                p.team_id
            LIMIT 40
            """,
        )

        query_one(
            connection,
            "BLANK PERFORMANCE TEAM-ID PROFILE",
            """
            SELECT
                SUM(
                    performance_rows
                ) AS blank_team_performance_rows,
                COUNT(
                    DISTINCT athlete_id
                ) AS affected_athletes,
                COUNT(*) AS distinct_affiliation_keys
            FROM performance_affiliation_keys
            WHERE team_id IS NULL
            """,
        )

        def affiliation_coverage(
            year_column: str,
            title: str,
        ) -> dict[str, object]:
            return query_one(
                connection,
                title,
                f"""
                WITH roster_affiliations AS (
                    SELECT DISTINCT
                        NULLIF(
                            TRIM(r.athlete_id),
                            ''
                        ) AS athlete_id,
                        NULLIF(
                            TRIM(r.team_id),
                            ''
                        ) AS team_id,
                        b.{year_column} AS season_year,
                        b.season_type
                    FROM rosters_source r
                    INNER JOIN season_bridge b
                        ON NULLIF(
                            TRIM(r.config_hnd),
                            ''
                        ) = b.config_hnd
                    WHERE
                        b.{year_column} IS NOT NULL
                        AND b.season_type NOT IN (
                            'unknown',
                            'conflict'
                        )
                )
                SELECT
                    COALESCE(
                        SUM(p.performance_rows),
                        0
                    ) AS total_performance_rows,

                    COALESCE(
                        SUM(
                            CASE
                                WHEN r.athlete_id IS NOT NULL
                                THEN p.performance_rows
                                ELSE 0
                            END
                        ),
                        0
                    ) AS matched_performance_rows,

                    COALESCE(
                        SUM(
                            CASE
                                WHEN r.athlete_id IS NULL
                                THEN p.performance_rows
                                ELSE 0
                            END
                        ),
                        0
                    ) AS unmatched_performance_rows,

                    COUNT(*) AS distinct_performance_keys,

                    COUNT(*) FILTER (
                        WHERE r.athlete_id IS NOT NULL
                    ) AS matched_distinct_keys,

                    COUNT(*) FILTER (
                        WHERE r.athlete_id IS NULL
                    ) AS unmatched_distinct_keys
                FROM performance_affiliation_keys p
                LEFT JOIN roster_affiliations r
                    ON p.athlete_id = r.athlete_id
                    AND p.team_id = r.team_id
                    AND p.season_year = r.season_year
                    AND p.season_type = r.season_type
                """,
            )

        end_year_metrics = affiliation_coverage(
            "end_year",
            "AFFILIATION COVERAGE USING INDOOR END YEAR",
        )

        start_year_metrics = affiliation_coverage(
            "start_year",
            "AFFILIATION COVERAGE USING INDOOR START YEAR",
        )

        if (
            int(
                end_year_metrics[
                    "matched_performance_rows"
                ]
            )
            >= int(
                start_year_metrics[
                    "matched_performance_rows"
                ]
            )
        ):
            selected_year_column = "end_year"
            selected_strategy = "end year"
        else:
            selected_year_column = "start_year"
            selected_strategy = "start year"

        heading("SELECTED SEASON-YEAR STRATEGY")
        print(
            "Selected indoor season convention: "
            f"{selected_strategy}"
        )
        print(
            "Selected bridge column: "
            f"{selected_year_column}"
        )

        query_one(
            connection,
            "UNMATCHED AFFILIATION BREAKDOWN",
            f"""
            WITH directory_teams AS (
                SELECT DISTINCT
                    NULLIF(
                        TRIM(tfrrs_team_id),
                        ''
                    ) AS team_id
                FROM schools_source
            ),
            roster_affiliations AS (
                SELECT DISTINCT
                    NULLIF(
                        TRIM(r.athlete_id),
                        ''
                    ) AS athlete_id,
                    NULLIF(
                        TRIM(r.team_id),
                        ''
                    ) AS team_id,
                    b.{selected_year_column}
                        AS season_year,
                    b.season_type
                FROM rosters_source r
                INNER JOIN season_bridge b
                    ON NULLIF(
                        TRIM(r.config_hnd),
                        ''
                    ) = b.config_hnd
                WHERE
                    b.{selected_year_column}
                        IS NOT NULL
            ),
            classified AS (
                SELECT
                    p.*,
                    CASE
                        WHEN r.athlete_id IS NOT NULL
                            THEN 'matched'
                        WHEN p.team_id IS NULL
                            THEN 'blank_team_id'
                        WHEN d.team_id IS NULL
                            THEN 'performance_only_team'
                        ELSE 'directory_team_without_roster_match'
                    END AS match_class
                FROM performance_affiliation_keys p
                LEFT JOIN roster_affiliations r
                    ON p.athlete_id = r.athlete_id
                    AND p.team_id = r.team_id
                    AND p.season_year = r.season_year
                    AND p.season_type = r.season_type
                LEFT JOIN directory_teams d
                    ON p.team_id = d.team_id
            )
            SELECT
                COALESCE(
                    SUM(
                        CASE
                            WHEN match_class = 'matched'
                            THEN performance_rows
                            ELSE 0
                        END
                    ),
                    0
                ) AS matched_rows,

                COALESCE(
                    SUM(
                        CASE
                            WHEN match_class =
                                'blank_team_id'
                            THEN performance_rows
                            ELSE 0
                        END
                    ),
                    0
                ) AS blank_team_rows,

                COALESCE(
                    SUM(
                        CASE
                            WHEN match_class =
                                'performance_only_team'
                            THEN performance_rows
                            ELSE 0
                        END
                    ),
                    0
                ) AS performance_only_team_rows,

                COALESCE(
                    SUM(
                        CASE
                            WHEN match_class =
                                'directory_team_without_roster_match'
                            THEN performance_rows
                            ELSE 0
                        END
                    ),
                    0
                ) AS directory_team_unmatched_rows,

                COALESCE(
                    SUM(performance_rows),
                    0
                ) AS total_rows
            FROM classified
            """,
        )

        query_rows(
            connection,
            "TOP DIRECTORY-SEASON GROUPS WITHOUT ROSTER MATCH",
            f"""
            WITH directory_teams AS (
                SELECT DISTINCT
                    NULLIF(
                        TRIM(tfrrs_team_id),
                        ''
                    ) AS team_id
                FROM schools_source
            ),
            roster_affiliations AS (
                SELECT DISTINCT
                    NULLIF(
                        TRIM(r.athlete_id),
                        ''
                    ) AS athlete_id,
                    NULLIF(
                        TRIM(r.team_id),
                        ''
                    ) AS team_id,
                    b.{selected_year_column}
                        AS season_year,
                    b.season_type
                FROM rosters_source r
                INNER JOIN season_bridge b
                    ON NULLIF(
                        TRIM(r.config_hnd),
                        ''
                    ) = b.config_hnd
            )
            SELECT
                p.season_year,
                p.season_type,
                p.season_label,
                COUNT(*) AS distinct_affiliation_keys,
                SUM(
                    p.performance_rows
                ) AS performance_rows
            FROM performance_affiliation_keys p
            INNER JOIN directory_teams d
                ON p.team_id = d.team_id
            LEFT JOIN roster_affiliations r
                ON p.athlete_id = r.athlete_id
                AND p.team_id = r.team_id
                AND p.season_year = r.season_year
                AND p.season_type = r.season_type
            WHERE r.athlete_id IS NULL
            GROUP BY
                p.season_year,
                p.season_type,
                p.season_label
            ORDER BY
                performance_rows DESC,
                p.season_year,
                p.season_type
            LIMIT 40
            """,
        )

    finally:
        connection.close()
        shutil.rmtree(
            TEMP_DIRECTORY,
            ignore_errors=True,
        )

    heading("DIAGNOSTIC COMPLETION")
    print("Temporary DuckDB files were removed.")
    print("The production DuckDB database was not created.")
    print("No source files were modified.")
    print()
    print("OVERALL DIAGNOSTIC RESULT: COMPLETE")


if __name__ == "__main__":
    main()
