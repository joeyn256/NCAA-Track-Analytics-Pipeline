"""Build the Milestone 3 NCAA Track Analytics DuckDB database.

The production build is atomic:

1. Validate the canonical input inventory.
2. Build a separate staging DuckDB database.
3. Register source-faithful raw views.
4. Construct the relational core tables.
5. Run all mandatory integrity audits.
6. Commit and checkpoint only if every hard check passes.
7. Rename the completed staging file to the production path.

The script refuses to overwrite an existing production database.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]

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

DATABASE_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "database"
)

PRODUCTION_DATABASE = (
    DATABASE_DIRECTORY
    / "ncaa_track_analytics.duckdb"
)

STAGING_DATABASE = (
    DATABASE_DIRECTORY
    / "ncaa_track_analytics.building.duckdb"
)

TEMP_DIRECTORY = (
    DATABASE_DIRECTORY
    / ".duckdb_build_tmp"
)

SCHEMA_FILE = (
    PROJECT_ROOT
    / "src"
    / "database"
    / "schema.sql"
)

EXPECTED_DUCKDB_VERSION = "1.5.4"

MINIMUM_FREE_GIB = 20.0

EXPECTED = {
    "directory_team_rows": 714,
    "directory_institutions": 363,
    "season_files": 714,
    "performance_files": 194,
    "status_files": 194,
    "athletes": 193_961,
    "roster_source_rows": 992_774,
    "affiliations": 990_681,
    "roster_duplicate_excess": 2_093,
    "parser_status_rows": 193_954,
    "athletes_with_performances": 172_204,
    "performance_rows": 6_594_540,
    "performance_teams": 962,
    "combined_teams": 973,
    "meets": 32_416,
    "events": 378,
    "blank_performance_team_rows": 479,
    "matched_affiliation_rows": 5_916_703,
    "unmatched_affiliation_rows": 677_837,
    "performance_only_team_rows": 32_776,
    "directory_team_unmatched_rows": 644_582,
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


@dataclass(frozen=True)
class SourceInventory:
    """Canonical files used by the Milestone 3 production build."""

    schools_file: Path
    athletes_file: Path
    rosters_file: Path
    season_files: tuple[Path, ...]
    performance_files: tuple[Path, ...]
    status_files: tuple[Path, ...]

    def grouped_files(
        self,
    ) -> tuple[tuple[str, tuple[Path, ...]], ...]:
        """Return source files grouped by their logical purpose."""
        return (
            ("schools", (self.schools_file,)),
            ("athletes", (self.athletes_file,)),
            ("rosters", (self.rosters_file,)),
            ("seasons", self.season_files),
            ("performances", self.performance_files),
            ("chunk_status", self.status_files),
        )

    def all_files(self) -> tuple[Path, ...]:
        """Return every canonical source file."""
        return tuple(
            path
            for _, paths in self.grouped_files()
            for path in paths
        )


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Build the Milestone 3 DuckDB analytical database."
        )
    )

    mode = parser.add_mutually_exclusive_group(
        required=True
    )

    mode.add_argument(
        "--preflight-only",
        action="store_true",
        help=(
            "Validate the environment and input inventory "
            "without creating a database."
        ),
    )

    mode.add_argument(
        "--build",
        action="store_true",
        help=(
            "Run the complete audited production database build."
        ),
    )

    return parser.parse_args()


def sql_string(value: str) -> str:
    """Return a safely quoted DuckDB string literal."""
    return "'" + value.replace("'", "''") + "'"


def sql_column_struct(columns: Sequence[str]) -> str:
    """Return a DuckDB STRUCT mapping all source columns to VARCHAR."""
    return (
        "{"
        + ", ".join(
            f"{sql_string(column)}: 'VARCHAR'"
            for column in columns
        )
        + "}"
    )


def numbered_files(
    directory: Path,
    glob_pattern: str,
    filename_pattern: str,
) -> tuple[tuple[Path, ...], list[int]]:
    """Return sequence-sorted files and their numeric suffixes."""
    expression = re.compile(filename_pattern)
    results: list[tuple[int, Path]] = []

    for path in directory.glob(glob_pattern):
        match = expression.fullmatch(path.name)

        if match is None:
            raise RuntimeError(
                f"Unexpected numbered filename: {path}"
            )

        results.append(
            (int(match.group(1)), path.resolve())
        )

    results.sort(key=lambda item: item[0])

    return (
        tuple(path for _, path in results),
        [number for number, _ in results],
    )


def collect_inventory() -> SourceInventory:
    """Validate and return the canonical production input inventory."""
    schools_file = (
        RAW_DIRECTORY / "schools.csv"
    ).resolve()

    athletes_file = (
        RAW_DIRECTORY / "unique_athletes.csv"
    ).resolve()

    rosters_file = (
        RAW_DIRECTORY / "all_roster_records.csv"
    ).resolve()

    for path in (
        schools_file,
        athletes_file,
        rosters_file,
        SCHEMA_FILE.resolve(),
    ):
        if not path.is_file():
            raise FileNotFoundError(
                f"Required file is missing: {path}"
            )

    season_files = tuple(
        sorted(
            path.resolve()
            for path in (
                RAW_DIRECTORY / "seasons"
            ).glob("*.csv")
        )
    )

    performance_files, performance_numbers = numbered_files(
        PERFORMANCE_DIRECTORY,
        "performances_*.csv",
        r"performances_(\d{5})\.csv",
    )

    status_files, status_numbers = numbered_files(
        STATUS_DIRECTORY,
        "status_*.csv",
        r"status_(\d{5})\.csv",
    )

    expected_sequence = list(
        range(
            1,
            EXPECTED["performance_files"] + 1,
        )
    )

    if len(season_files) != EXPECTED["season_files"]:
        raise RuntimeError(
            "Season file count mismatch: "
            f"expected {EXPECTED['season_files']}, "
            f"found {len(season_files)}"
        )

    if len(performance_files) != EXPECTED[
        "performance_files"
    ]:
        raise RuntimeError(
            "Performance file count mismatch: "
            f"expected {EXPECTED['performance_files']}, "
            f"found {len(performance_files)}"
        )

    if len(status_files) != EXPECTED["status_files"]:
        raise RuntimeError(
            "Status file count mismatch: "
            f"expected {EXPECTED['status_files']}, "
            f"found {len(status_files)}"
        )

    if performance_numbers != expected_sequence:
        raise RuntimeError(
            "Performance file sequence is incomplete."
        )

    if status_numbers != expected_sequence:
        raise RuntimeError(
            "Status file sequence is incomplete."
        )

    return SourceInventory(
        schools_file=schools_file,
        athletes_file=athletes_file,
        rosters_file=rosters_file,
        season_files=season_files,
        performance_files=performance_files,
        status_files=status_files,
    )


def free_space_gib(path: Path) -> float:
    """Return available filesystem space in GiB."""
    return shutil.disk_usage(path).free / (1024 ** 3)


def run_preflight(
    inventory: SourceInventory,
    *,
    allow_staging_cleanup: bool,
) -> None:
    """Run all checks required before a production build."""
    print("MILESTONE 3 PRODUCTION-BUILD PREFLIGHT")
    print("=" * 80)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {platform.python_version()}")
    print(f"DuckDB version: {duckdb.__version__}")
    print(f"Schema file: {SCHEMA_FILE}")
    print(f"Production database: {PRODUCTION_DATABASE}")
    print(f"Staging database: {STAGING_DATABASE}")
    print()

    if duckdb.__version__ != EXPECTED_DUCKDB_VERSION:
        raise RuntimeError(
            "DuckDB version mismatch: "
            f"expected {EXPECTED_DUCKDB_VERSION}, "
            f"found {duckdb.__version__}"
        )

    if PRODUCTION_DATABASE.exists():
        raise FileExistsError(
            "Production database already exists. "
            "The builder will not overwrite it:\n"
            f"{PRODUCTION_DATABASE}"
        )

    staging_related_files = (
        STAGING_DATABASE,
        Path(str(STAGING_DATABASE) + ".wal"),
    )

    existing_staging_files = [
        path
        for path in staging_related_files
        if path.exists()
    ]

    if existing_staging_files:
        if allow_staging_cleanup:
            for path in existing_staging_files:
                path.unlink()
        else:
            raise FileExistsError(
                "A previous staging database exists:\n"
                + "\n".join(
                    str(path)
                    for path in existing_staging_files
                )
            )

    available_gib = free_space_gib(PROJECT_ROOT)

    if available_gib < MINIMUM_FREE_GIB:
        raise RuntimeError(
            "Insufficient free disk space: "
            f"{available_gib:,.2f} GiB available; "
            f"{MINIMUM_FREE_GIB:,.2f} GiB required."
        )

    source_groups = inventory.grouped_files()
    total_files = len(inventory.all_files())
    total_bytes = sum(
        path.stat().st_size
        for path in inventory.all_files()
    )

    print("[PASS] DuckDB version pin")
    print("[PASS] Production database does not exist")
    print("[PASS] Numbered file sequences are complete")
    print(
        "[PASS] Free disk space: "
        f"{available_gib:,.2f} GiB"
    )
    print()
    print("CANONICAL SOURCE INVENTORY")
    print("-" * 80)

    for source_group, files in source_groups:
        group_bytes = sum(
            path.stat().st_size
            for path in files
        )

        print(
            f"{source_group}: "
            f"{len(files):,} files, "
            f"{group_bytes / (1024 ** 2):,.2f} MiB"
        )

    print("-" * 80)
    print(
        f"Total canonical files: {total_files:,}"
    )
    print(
        "Total canonical size: "
        f"{total_bytes / (1024 ** 3):,.2f} GiB"
    )
    print()
    print("PREFLIGHT RESULT: PASS")


def create_raw_view(
    connection: duckdb.DuckDBPyConnection,
    view_name: str,
    source_path: str,
    columns: Sequence[str],
) -> None:
    """Create a persistent, source-faithful CSV view."""
    connection.execute(
        f"""
        CREATE VIEW {view_name} AS
        SELECT *
        FROM read_csv(
            {sql_string(source_path)},
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


def timed_step(
    title: str,
    operation,
) -> None:
    """Run and report a build operation."""
    print()
    print(title)
    print("-" * 80)

    started = time.perf_counter()
    operation()
    elapsed = time.perf_counter() - started

    print(
        f"Completed in {elapsed:,.2f} seconds"
    )


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest for a source file."""
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while block := handle.read(4 * 1024 * 1024):
            digest.update(block)

    return digest.hexdigest()


def classify_season_type(label: str) -> str:
    """Classify a roster season label."""
    normalized = label.lower().replace("_", " ")

    if "cross" in normalized:
        return "cross_country"

    if "indoor" in normalized:
        return "indoor"

    if "outdoor" in normalized:
        return "outdoor"

    raise ValueError(
        f"Unrecognized season type: {label!r}"
    )


def parse_season_years(
    label: str,
) -> tuple[int, int]:
    """Parse start and end years from a roster season label."""
    normalized = label.replace("_", " ").replace("-", " ")

    full_years = [
        int(value)
        for value in re.findall(
            r"(?<!\d)(?:19|20)\d{2}(?!\d)",
            normalized,
        )
    ]

    if len(full_years) >= 2:
        return full_years[0], full_years[-1]

    if len(full_years) != 1:
        raise ValueError(
            f"Could not parse season year: {label!r}"
        )

    start_year = full_years[0]
    end_year = start_year

    short_year_match = re.search(
        r"((?:19|20)\d{2})\D+(\d{2})(?!\d)",
        label,
    )

    if short_year_match is not None:
        short_year = int(
            short_year_match.group(2)
        )
        century = (start_year // 100) * 100
        end_year = century + short_year

        if end_year < start_year:
            end_year += 100

    return start_year, end_year


def build_season_bridge(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Create the verified roster-season configuration bridge."""
    rows = connection.execute(
        """
        SELECT DISTINCT
            TRIM(config_hnd) AS config_hnd,
            TRIM(season_name) AS season_name
        FROM stg_seasons
        WHERE NULLIF(TRIM(config_hnd), '') IS NOT NULL
          AND NULLIF(TRIM(season_name), '') IS NOT NULL
        ORDER BY config_hnd, season_name
        """
    ).fetchall()

    labels_by_config: dict[str, set[str]] = {}

    for config_hnd, season_name in rows:
        labels_by_config.setdefault(
            str(config_hnd),
            set(),
        ).add(str(season_name))

    bridge_rows: list[
        tuple[str, str, int, int, str, str]
    ] = []

    for config_hnd, labels in labels_by_config.items():
        parsed = {
            (
                classify_season_type(label),
                *parse_season_years(label),
            )
            for label in labels
        }

        if len(parsed) != 1:
            raise RuntimeError(
                "Conflicting season definitions for "
                f"config_hnd={config_hnd}: {sorted(labels)}"
            )

        season_type, start_year, end_year = next(
            iter(parsed)
        )

        roster_label = sorted(labels)[0]
        season_id = f"{end_year}_{season_type}"

        bridge_rows.append(
            (
                config_hnd,
                roster_label,
                start_year,
                end_year,
                season_type,
                season_id,
            )
        )

    if len(bridge_rows) != 49:
        raise RuntimeError(
            "Expected 49 season configuration values, "
            f"found {len(bridge_rows)}."
        )

    connection.execute(
        """
        CREATE TEMP TABLE season_bridge (
            config_hnd VARCHAR,
            roster_season_label VARCHAR,
            roster_start_year INTEGER,
            roster_end_year INTEGER,
            season_type VARCHAR,
            season_id VARCHAR
        )
        """
    )

    connection.executemany(
        """
        INSERT INTO season_bridge
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        bridge_rows,
    )


def register_source_files(
    connection: duckdb.DuckDBPyConnection,
    inventory: SourceInventory,
    build_run_id: str,
) -> None:
    """Hash and register every canonical source file."""
    table_by_group = {
        "schools": "stg_schools",
        "athletes": "stg_athletes",
        "rosters": "stg_rosters",
        "seasons": "stg_seasons",
        "performances": "stg_performances",
        "chunk_status": "stg_chunk_status",
    }

    row_counts: dict[str, int] = {}

    for source_group, table_name in table_by_group.items():
        rows = connection.execute(
            f"""
            SELECT
                source_path,
                COUNT(*)::BIGINT AS row_count
            FROM {table_name}
            GROUP BY source_path
            """
        ).fetchall()

        for source_path, row_count in rows:
            row_counts[
                str(Path(source_path).resolve())
            ] = int(row_count)

    records = []
    files_processed = 0
    total_files = len(inventory.all_files())

    for source_group, paths in inventory.grouped_files():
        for path in paths:
            resolved_path = path.resolve()
            stat = resolved_path.stat()
            row_count = row_counts.get(
                str(resolved_path),
                0,
            )

            records.append(
                (
                    build_run_id,
                    source_group,
                    str(
                        resolved_path.relative_to(
                            PROJECT_ROOT
                        )
                    ),
                    resolved_path.name,
                    stat.st_size,
                    stat.st_mtime_ns,
                    sha256_file(resolved_path),
                    row_count,
                    row_count == 0,
                    (
                        "empty"
                        if row_count == 0
                        else "loaded"
                    ),
                    None,
                )
            )

            files_processed += 1

            if (
                files_processed % 100 == 0
                or files_processed == total_files
            ):
                print(
                    "Hashed source files: "
                    f"{files_processed:,}/{total_files:,}"
                )

    connection.executemany(
        """
        INSERT INTO audit.source_files (
            build_run_id,
            source_group,
            source_path,
            source_filename,
            file_size_bytes,
            modified_time_ns,
            sha256,
            row_count,
            is_empty,
            load_status,
            error_message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )


def scalar(
    connection: duckdb.DuckDBPyConnection,
    query: str,
) -> int:
    """Return a single integer query result."""
    value = connection.execute(query).fetchone()[0]
    return int(value)


def run_production_build(
    inventory: SourceInventory,
) -> None:
    """Build, audit, checkpoint, and publish the production database."""
    DATABASE_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    if TEMP_DIRECTORY.exists():
        shutil.rmtree(TEMP_DIRECTORY)

    TEMP_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    build_run_id = (
        datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        + "_"
        + uuid.uuid4().hex[:8]
    )

    schema_sql = SCHEMA_FILE.read_text(
        encoding="utf-8"
    )

    connection: duckdb.DuckDBPyConnection | None = None
    transaction_open = False
    build_committed = False

    started_at = datetime.now(timezone.utc)

    print()
    print("MILESTONE 3 PRODUCTION DATABASE BUILD")
    print("=" * 80)
    print(f"Build run ID: {build_run_id}")
    print(f"Staging database: {STAGING_DATABASE}")
    print(f"Final database: {PRODUCTION_DATABASE}")

    try:
        connection = duckdb.connect(
            database=str(STAGING_DATABASE)
        )

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

        connection.execute("BEGIN TRANSACTION")
        transaction_open = True

        timed_step(
            "Creating schemas and empty tables",
            lambda: connection.execute(schema_sql),
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
            VALUES (?, ?, 'running', ?, ?, ?, ?, ?)
            """,
            [
                build_run_id,
                started_at,
                str(PROJECT_ROOT),
                str(PRODUCTION_DATABASE),
                platform.python_version(),
                duckdb.__version__,
                EXPECTED["performance_rows"],
            ],
        )

        connection.execute(
            """
            INSERT INTO audit.schema_versions (
                version_id,
                milestone,
                description,
                duckdb_version
            )
            VALUES (
                'milestone_03_v1',
                3,
                'Initial relational analytical database',
                ?
            )
            """,
            [duckdb.__version__],
        )

        def create_raw_views() -> None:
            create_raw_view(
                connection,
                "raw.schools_source",
                str(inventory.schools_file),
                SCHOOL_COLUMNS,
            )
            create_raw_view(
                connection,
                "raw.athletes_source",
                str(inventory.athletes_file),
                ATHLETE_COLUMNS,
            )
            create_raw_view(
                connection,
                "raw.rosters_source",
                str(inventory.rosters_file),
                ROSTER_COLUMNS,
            )
            create_raw_view(
                connection,
                "raw.seasons_source",
                str(
                    (
                        RAW_DIRECTORY
                        / "seasons"
                        / "*.csv"
                    ).resolve()
                ),
                SEASON_COLUMNS,
            )
            create_raw_view(
                connection,
                "raw.performance_source",
                str(
                    (
                        PERFORMANCE_DIRECTORY
                        / "performances_*.csv"
                    ).resolve()
                ),
                PERFORMANCE_COLUMNS,
            )
            create_raw_view(
                connection,
                "raw.chunk_status_source",
                str(
                    (
                        STATUS_DIRECTORY
                        / "status_*.csv"
                    ).resolve()
                ),
                STATUS_COLUMNS,
            )

        timed_step(
            "Registering persistent raw-schema views",
            create_raw_views,
        )

        def stage_sources() -> None:
            connection.execute(
                """
                CREATE TEMP TABLE stg_schools AS
                SELECT
                    school_id,
                    tfrrs_team_id,
                    school_name,
                    slug,
                    url,
                    division,
                    gender,
                    sport,
                    conference,
                    state,
                    filename AS source_path
                FROM raw.schools_source
                """
            )

            connection.execute(
                """
                CREATE TEMP TABLE stg_athletes AS
                SELECT
                    athlete_id,
                    athlete_name,
                    school,
                    team_id,
                    athlete_url,
                    filename AS source_path
                FROM raw.athletes_source
                """
            )

            connection.execute(
                """
                CREATE TEMP TABLE stg_rosters AS
                SELECT
                    athlete_id,
                    athlete_name,
                    year,
                    school,
                    team_id,
                    season,
                    config_hnd,
                    filename AS source_path
                FROM raw.rosters_source
                """
            )

            connection.execute(
                """
                CREATE TEMP TABLE stg_seasons AS
                SELECT
                    season_name,
                    config_hnd,
                    school_name,
                    tfrrs_team_id,
                    filename AS source_path
                FROM raw.seasons_source
                """
            )

            connection.execute(
                """
                CREATE TEMP TABLE stg_performances AS
                SELECT
                    performance_id,
                    athlete_id,
                    athlete_name,
                    athlete_class,
                    school,
                    team_id,
                    season_year,
                    season_type,
                    season_label,
                    meet_id,
                    result_id,
                    meet_name,
                    meet_date_text,
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
                    source_file,
                    filename AS source_path
                FROM raw.performance_source
                """
            )

            connection.execute(
                """
                CREATE TEMP TABLE stg_chunk_status AS
                SELECT
                    chunk_number,
                    athlete_id,
                    source_file,
                    status,
                    performance_rows,
                    error_type,
                    error_message,
                    filename AS source_path
                FROM raw.chunk_status_source
                """
            )

        timed_step(
            "Materializing one consistent source snapshot",
            stage_sources,
        )

        timed_step(
            "Building the historical season bridge",
            lambda: build_season_bridge(connection),
        )

        timed_step(
            "Hashing and registering canonical source files",
            lambda: register_source_files(
                connection,
                inventory,
                build_run_id,
            ),
        )

        def build_teams() -> None:
            connection.execute(
                """
                CREATE TEMP TABLE
                    selected_performance_team_names
                AS
                WITH name_counts AS (
                    SELECT
                        NULLIF(TRIM(team_id), '')
                            AS team_id,
                        NULLIF(TRIM(school), '')
                            AS team_name,
                        COUNT(*)::BIGINT
                            AS source_rows
                    FROM stg_performances
                    WHERE NULLIF(
                        TRIM(team_id),
                        ''
                    ) IS NOT NULL
                    GROUP BY 1, 2
                ),
                ranked AS (
                    SELECT
                        *,
                        ROW_NUMBER() OVER (
                            PARTITION BY team_id
                            ORDER BY
                                CASE
                                    WHEN team_name IS NULL
                                    THEN 1
                                    ELSE 0
                                END,
                                source_rows DESC,
                                team_name
                        ) AS row_number
                    FROM name_counts
                )
                SELECT
                    team_id,
                    team_name
                FROM ranked
                WHERE row_number = 1
                """
            )

            connection.execute(
                """
                INSERT INTO core.teams
                WITH directory_teams AS (
                    SELECT
                        TRIM(tfrrs_team_id)
                            AS team_id,
                        REGEXP_REPLACE(
                            TRIM(tfrrs_team_id),
                            '_college_[mf]_',
                            '_college_'
                        ) AS school_id,
                        NULLIF(TRIM(school_id), '')
                            AS source_school_id,
                        COALESCE(
                            NULLIF(
                                TRIM(school_name),
                                ''
                            ),
                            TRIM(tfrrs_team_id)
                        ) AS team_name,
                        CASE
                            WHEN LOWER(
                                COALESCE(gender, '')
                            ) IN ('f', 'female', 'women')
                                THEN 'f'
                            WHEN LOWER(
                                COALESCE(gender, '')
                            ) IN ('m', 'male', 'men')
                                THEN 'm'
                            ELSE 'unknown'
                        END AS gender_code,
                        NULLIF(TRIM(division), '')
                            AS division,
                        NULLIF(TRIM(sport), '')
                            AS sport,
                        NULLIF(TRIM(conference), '')
                            AS conference,
                        NULLIF(TRIM(state), '')
                            AS state,
                        NULLIF(TRIM(slug), '')
                            AS slug,
                        NULLIF(TRIM(url), '')
                            AS team_url
                    FROM stg_schools
                ),
                roster_teams AS (
                    SELECT DISTINCT
                        TRIM(team_id) AS team_id
                    FROM stg_rosters
                    WHERE NULLIF(
                        TRIM(team_id),
                        ''
                    ) IS NOT NULL
                ),
                performance_teams AS (
                    SELECT
                        team_id,
                        team_name
                    FROM selected_performance_team_names
                )
                SELECT
                    directory.team_id,
                    directory.school_id,
                    directory.source_school_id,
                    directory.team_name,
                    directory.gender_code,
                    directory.division,
                    directory.sport,
                    directory.conference,
                    directory.state,
                    directory.slug,
                    directory.team_url,
                    TRUE,
                    roster.team_id IS NOT NULL,
                    performance.team_id IS NOT NULL
                FROM directory_teams AS directory
                LEFT JOIN roster_teams AS roster
                    USING (team_id)
                LEFT JOIN performance_teams AS performance
                    USING (team_id)

                UNION ALL

                SELECT
                    performance.team_id,
                    REGEXP_REPLACE(
                        performance.team_id,
                        '_college_[mf]_',
                        '_college_'
                    ),
                    NULL,
                    COALESCE(
                        performance.team_name,
                        performance.team_id
                    ),
                    CASE
                        WHEN performance.team_id
                            LIKE '%_college_f_%'
                            THEN 'f'
                        WHEN performance.team_id
                            LIKE '%_college_m_%'
                            THEN 'm'
                        ELSE 'unknown'
                    END,
                    NULL,
                    NULL,
                    NULL,
                    SPLIT_PART(
                        performance.team_id,
                        '_',
                        1
                    ),
                    NULL,
                    NULL,
                    FALSE,
                    FALSE,
                    TRUE
                FROM performance_teams AS performance
                LEFT JOIN directory_teams AS directory
                    USING (team_id)
                WHERE directory.team_id IS NULL
                """
            )

        timed_step(
            "Building the complete team dimension",
            build_teams,
        )

        def build_schools() -> None:
            connection.execute(
                """
                INSERT INTO core.schools
                WITH name_counts AS (
                    SELECT
                        school_id,
                        team_name AS school_name,
                        MAX(
                            CAST(
                                in_division_i_directory
                                AS INTEGER
                            )
                        ) AS directory_priority,
                        COUNT(*) AS team_rows
                    FROM core.teams
                    GROUP BY school_id, team_name
                ),
                ranked_names AS (
                    SELECT
                        *,
                        ROW_NUMBER() OVER (
                            PARTITION BY school_id
                            ORDER BY
                                directory_priority DESC,
                                team_rows DESC,
                                school_name
                        ) AS row_number
                    FROM name_counts
                ),
                selected_names AS (
                    SELECT
                        school_id,
                        school_name
                    FROM ranked_names
                    WHERE row_number = 1
                )
                SELECT
                    teams.school_id,
                    names.school_name,
                    COALESCE(
                        MIN(teams.state) FILTER (
                            WHERE
                                teams.in_division_i_directory
                                AND teams.state IS NOT NULL
                        ),
                        SPLIT_PART(
                            teams.school_id,
                            '_',
                            1
                        )
                    ) AS state,
                    COUNT(*) FILTER (
                        WHERE
                            teams.in_division_i_directory
                    )::INTEGER
                        AS directory_team_count,
                    COUNT(*)::INTEGER
                        AS total_team_count,
                    BOOL_OR(
                        teams.in_division_i_directory
                    ) AS is_directory_school,
                    CASE
                        WHEN BOOL_AND(
                            teams.in_division_i_directory
                        )
                            THEN 'directory'
                        WHEN BOOL_OR(
                            teams.in_division_i_directory
                        )
                            THEN 'mixed'
                        ELSE 'performance_only'
                    END AS source_method
                FROM core.teams AS teams
                INNER JOIN selected_names AS names
                    USING (school_id)
                GROUP BY
                    teams.school_id,
                    names.school_name
                """
            )

        timed_step(
            "Building the institution dimension",
            build_schools,
        )

        def build_athletes() -> None:
            connection.execute(
                """
                INSERT INTO core.athletes
                WITH parser_status AS (
                    SELECT
                        TRIM(athlete_id)
                            AS athlete_id,
                        MAX(
                            COALESCE(
                                TRY_CAST(
                                    performance_rows
                                    AS BIGINT
                                ),
                                0
                            )
                        ) AS performance_rows
                    FROM stg_chunk_status
                    GROUP BY TRIM(athlete_id)
                )
                SELECT
                    TRIM(athletes.athlete_id),
                    athletes.athlete_name,
                    athletes.school,
                    NULLIF(
                        TRIM(athletes.team_id),
                        ''
                    ),
                    athletes.athlete_url,
                    status.athlete_id IS NOT NULL,
                    COALESCE(
                        status.performance_rows,
                        0
                    ) > 0
                FROM stg_athletes AS athletes
                LEFT JOIN parser_status AS status
                    ON TRIM(athletes.athlete_id)
                        = status.athlete_id
                """
            )

        timed_step(
            "Building the athlete dimension",
            build_athletes,
        )

        def build_seasons() -> None:
            connection.execute(
                """
                CREATE TEMP TABLE
                    selected_performance_seasons
                AS
                WITH season_counts AS (
                    SELECT
                        TRY_CAST(
                            season_year AS INTEGER
                        ) AS season_year,
                        CASE
                            WHEN LOWER(season_type)
                                LIKE '%cross%'
                                THEN 'cross_country'
                            WHEN LOWER(season_type)
                                LIKE '%indoor%'
                                THEN 'indoor'
                            WHEN LOWER(season_type)
                                LIKE '%outdoor%'
                                THEN 'outdoor'
                            ELSE NULL
                        END AS season_type,
                        NULLIF(
                            TRIM(season_label),
                            ''
                        ) AS season_label,
                        COUNT(*)::BIGINT
                            AS performance_rows
                    FROM stg_performances
                    GROUP BY 1, 2, 3
                ),
                ranked AS (
                    SELECT
                        *,
                        ROW_NUMBER() OVER (
                            PARTITION BY
                                season_year,
                                season_type
                            ORDER BY
                                performance_rows DESC,
                                season_label
                        ) AS row_number
                    FROM season_counts
                )
                SELECT
                    season_year,
                    season_type,
                    season_label
                FROM ranked
                WHERE row_number = 1
                """
            )

            connection.execute(
                """
                INSERT INTO core.seasons
                WITH roster_seasons AS (
                    SELECT
                        roster_end_year
                            AS season_year,
                        season_type,
                        season_id,
                        roster_season_label,
                        config_hnd,
                        roster_start_year,
                        roster_end_year
                    FROM season_bridge
                ),
                season_keys AS (
                    SELECT
                        season_year,
                        season_type
                    FROM selected_performance_seasons

                    UNION

                    SELECT
                        season_year,
                        season_type
                    FROM roster_seasons
                )
                SELECT
                    CAST(keys.season_year AS VARCHAR)
                        || '_'
                        || keys.season_type,
                    keys.season_year,
                    keys.season_type,
                    performance.season_label,
                    roster.roster_season_label,
                    roster.config_hnd,
                    roster.roster_start_year,
                    roster.roster_end_year,
                    performance.season_year IS NOT NULL,
                    roster.season_year IS NOT NULL
                FROM season_keys AS keys
                LEFT JOIN selected_performance_seasons
                    AS performance
                    USING (
                        season_year,
                        season_type
                    )
                LEFT JOIN roster_seasons AS roster
                    USING (
                        season_year,
                        season_type
                    )
                """
            )

        timed_step(
            "Building the season dimension",
            build_seasons,
        )

        def build_meets() -> None:
            connection.execute(
                """
                INSERT INTO core.meets
                WITH base AS (
                    SELECT
                        TRIM(meet_id) AS meet_id,
                        NULLIF(TRIM(meet_name), '')
                            AS meet_name,
                        NULLIF(TRIM(meet_date_text), '')
                            AS meet_date_text,
                        NULLIF(TRIM(meet_url), '')
                            AS meet_url
                    FROM stg_performances
                ),
                meet_summary AS (
                    SELECT
                        meet_id,
                        COUNT(*)::BIGINT
                            AS performance_count,
                        COUNT(
                            DISTINCT meet_name
                        ) AS meet_name_variant_count,
                        COUNT(
                            DISTINCT meet_date_text
                        ) AS meet_date_variant_count,
                        COUNT(
                            DISTINCT meet_url
                        ) AS meet_url_variant_count
                    FROM base
                    GROUP BY meet_id
                ),
                name_counts AS (
                    SELECT
                        meet_id,
                        meet_name,
                        COUNT(*) AS source_rows
                    FROM base
                    WHERE meet_name IS NOT NULL
                    GROUP BY meet_id, meet_name
                ),
                selected_names AS (
                    SELECT meet_id, meet_name
                    FROM (
                        SELECT
                            *,
                            ROW_NUMBER() OVER (
                                PARTITION BY meet_id
                                ORDER BY
                                    source_rows DESC,
                                    meet_name
                            ) AS row_number
                        FROM name_counts
                    )
                    WHERE row_number = 1
                ),
                date_counts AS (
                    SELECT
                        meet_id,
                        meet_date_text,
                        COUNT(*) AS source_rows
                    FROM base
                    WHERE meet_date_text IS NOT NULL
                    GROUP BY meet_id, meet_date_text
                ),
                selected_dates AS (
                    SELECT meet_id, meet_date_text
                    FROM (
                        SELECT
                            *,
                            ROW_NUMBER() OVER (
                                PARTITION BY meet_id
                                ORDER BY
                                    source_rows DESC,
                                    meet_date_text
                            ) AS row_number
                        FROM date_counts
                    )
                    WHERE row_number = 1
                ),
                url_counts AS (
                    SELECT
                        meet_id,
                        meet_url,
                        COUNT(*) AS source_rows
                    FROM base
                    WHERE meet_url IS NOT NULL
                    GROUP BY meet_id, meet_url
                ),
                selected_urls AS (
                    SELECT meet_id, meet_url
                    FROM (
                        SELECT
                            *,
                            ROW_NUMBER() OVER (
                                PARTITION BY meet_id
                                ORDER BY
                                    source_rows DESC,
                                    meet_url
                            ) AS row_number
                        FROM url_counts
                    )
                    WHERE row_number = 1
                )
                SELECT
                    summary.meet_id,
                    names.meet_name,
                    dates.meet_date_text,
                    urls.meet_url,
                    summary.meet_name_variant_count,
                    summary.meet_date_variant_count,
                    summary.meet_url_variant_count,
                    summary.performance_count
                FROM meet_summary AS summary
                LEFT JOIN selected_names AS names
                    USING (meet_id)
                LEFT JOIN selected_dates AS dates
                    USING (meet_id)
                LEFT JOIN selected_urls AS urls
                    USING (meet_id)
                """
            )

        timed_step(
            "Building the meet dimension",
            build_meets,
        )

        def build_events() -> None:
            connection.execute(
                """
                INSERT INTO core.events
                WITH event_counts AS (
                    SELECT
                        event AS event_label,
                        COUNT(*)::BIGINT
                            AS performance_count
                    FROM stg_performances
                    GROUP BY event
                )
                SELECT
                    CAST(
                        ROW_NUMBER() OVER (
                            ORDER BY event_label
                        )
                        AS INTEGER
                    ) AS event_id,
                    event_label,
                    performance_count
                FROM event_counts
                """
            )

        timed_step(
            "Building the source-label event dimension",
            build_events,
        )

        def build_affiliations() -> None:
            connection.execute(
                """
                CREATE TEMP TABLE grouped_rosters AS
                SELECT
                    athlete_id,
                    athlete_name,
                    year,
                    school,
                    team_id,
                    season,
                    config_hnd,
                    COUNT(*)::INTEGER
                        AS source_occurrences
                FROM stg_rosters
                GROUP BY
                    athlete_id,
                    athlete_name,
                    year,
                    school,
                    team_id,
                    season,
                    config_hnd
                """
            )

            connection.execute(
                """
                INSERT INTO core.athlete_affiliations
                SELECT
                    ROW_NUMBER() OVER (
                        ORDER BY
                            TRIM(roster.athlete_id),
                            TRIM(roster.team_id),
                            TRIM(roster.config_hnd)
                    ) AS affiliation_id,
                    TRIM(roster.athlete_id),
                    TRIM(roster.team_id),
                    bridge.season_id,
                    TRIM(roster.config_hnd),
                    roster.season,
                    roster.year,
                    roster.athlete_name,
                    roster.school,
                    roster.source_occurrences,
                    roster.source_occurrences - 1
                FROM grouped_rosters AS roster
                INNER JOIN season_bridge AS bridge
                    ON TRIM(roster.config_hnd)
                        = bridge.config_hnd
                """
            )

            connection.execute(
                """
                INSERT INTO audit.roster_duplicate_groups
                SELECT
                    ?,
                    TRIM(athlete_id),
                    athlete_name,
                    year,
                    school,
                    TRIM(team_id),
                    season,
                    TRIM(config_hnd),
                    source_occurrences,
                    source_occurrences - 1
                FROM grouped_rosters
                WHERE source_occurrences > 1
                """,
                [build_run_id],
            )

        timed_step(
            "Building historical athlete affiliations",
            build_affiliations,
        )

        def build_performances() -> None:
            connection.execute(
                """
                CREATE TEMP VIEW typed_performances AS
                SELECT
                    *,
                    TRY_CAST(
                        season_year AS INTEGER
                    ) AS typed_season_year,
                    CASE
                        WHEN LOWER(season_type)
                            LIKE '%cross%'
                            THEN 'cross_country'
                        WHEN LOWER(season_type)
                            LIKE '%indoor%'
                            THEN 'indoor'
                        WHEN LOWER(season_type)
                            LIKE '%outdoor%'
                            THEN 'outdoor'
                        ELSE NULL
                    END AS typed_season_type,
                    CAST(
                        TRY_CAST(
                            season_year AS INTEGER
                        ) AS VARCHAR
                    )
                    || '_'
                    || CASE
                        WHEN LOWER(season_type)
                            LIKE '%cross%'
                            THEN 'cross_country'
                        WHEN LOWER(season_type)
                            LIKE '%indoor%'
                            THEN 'indoor'
                        WHEN LOWER(season_type)
                            LIKE '%outdoor%'
                            THEN 'outdoor'
                        ELSE NULL
                    END AS typed_season_id
                FROM stg_performances
                """
            )

            connection.execute(
                """
                INSERT INTO core.performances
                SELECT
                    performance.performance_id,
                    TRIM(performance.athlete_id),
                    performance.athlete_name,
                    performance.athlete_class,
                    performance.school,
                    NULLIF(
                        TRIM(performance.team_id),
                        ''
                    ),
                    performance.typed_season_id,
                    performance.typed_season_year,
                    performance.typed_season_type,
                    performance.season_label,
                    TRIM(performance.meet_id),
                    NULLIF(
                        TRIM(performance.result_id),
                        ''
                    ),
                    performance.meet_name,
                    performance.meet_date_text,
                    event.event_id,
                    performance.event,
                    performance.mark,
                    performance.secondary_mark,
                    performance.wind,
                    performance.place,
                    performance.competition_round,
                    performance.raw_place,
                    performance.meet_url,
                    performance.result_url,
                    performance.highlighted,
                    affiliation.affiliation_id,
                    performance.source_file,
                    REGEXP_EXTRACT(
                        performance.source_path,
                        '[^/]+$'
                    )
                FROM typed_performances AS performance
                INNER JOIN core.seasons AS season
                    ON performance.typed_season_id
                        = season.season_id
                INNER JOIN core.events AS event
                    ON performance.event
                        = event.event_label
                LEFT JOIN core.athlete_affiliations
                    AS affiliation
                    ON TRIM(performance.athlete_id)
                        = affiliation.athlete_id
                    AND NULLIF(
                        TRIM(performance.team_id),
                        ''
                    ) = affiliation.team_id
                    AND performance.typed_season_id
                        = affiliation.season_id
                """
            )

        timed_step(
            "Loading the performance fact table",
            build_performances,
        )

        def populate_dimension_conflicts() -> None:
            connection.execute(
                """
                INSERT INTO audit.dimension_conflicts (
                    build_run_id,
                    dimension_name,
                    business_key,
                    attribute_name,
                    distinct_value_count,
                    selected_value,
                    details
                )
                SELECT
                    ?,
                    'meets',
                    meet_id,
                    'meet_name',
                    meet_name_variant_count,
                    canonical_meet_name,
                    'Multiple source meet-name values'
                FROM core.meets
                WHERE meet_name_variant_count > 1

                UNION ALL

                SELECT
                    ?,
                    'meets',
                    meet_id,
                    'meet_date_text',
                    meet_date_variant_count,
                    canonical_meet_date_text,
                    'Multiple source meet-date values'
                FROM core.meets
                WHERE meet_date_variant_count > 1

                UNION ALL

                SELECT
                    ?,
                    'meets',
                    meet_id,
                    'meet_url',
                    meet_url_variant_count,
                    canonical_meet_url,
                    'Multiple source meet-URL values'
                FROM core.meets
                WHERE meet_url_variant_count > 1
                """,
                [
                    build_run_id,
                    build_run_id,
                    build_run_id,
                ],
            )

        timed_step(
            "Recording dimension conflicts",
            populate_dimension_conflicts,
        )

        hard_failures: list[str] = []

        def record_check(
            name: str,
            actual: int,
            expected: int,
            *,
            severity: str = "hard",
            details: str = "",
        ) -> None:
            passed = actual == expected

            connection.execute(
                """
                INSERT INTO audit.integrity_checks (
                    build_run_id,
                    check_name,
                    severity,
                    actual_value,
                    expected_value,
                    passed,
                    details
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    build_run_id,
                    name,
                    severity,
                    str(actual),
                    str(expected),
                    passed,
                    details,
                ],
            )

            status = "PASS" if passed else "FAIL"
            print(
                f"[{status}] {name}: "
                f"actual={actual:,}, "
                f"expected={expected:,}"
            )

            if severity == "hard" and not passed:
                hard_failures.append(
                    f"{name}: actual={actual}, "
                    f"expected={expected}"
                )

        print()
        print("MANDATORY BUILD AUDIT")
        print("-" * 80)

        core_counts = {
            "schools": scalar(
                connection,
                "SELECT COUNT(*) FROM core.schools",
            ),
            "teams": scalar(
                connection,
                "SELECT COUNT(*) FROM core.teams",
            ),
            "athletes": scalar(
                connection,
                "SELECT COUNT(*) FROM core.athletes",
            ),
            "seasons": scalar(
                connection,
                "SELECT COUNT(*) FROM core.seasons",
            ),
            "meets": scalar(
                connection,
                "SELECT COUNT(*) FROM core.meets",
            ),
            "events": scalar(
                connection,
                "SELECT COUNT(*) FROM core.events",
            ),
            "athlete_affiliations": scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM core.athlete_affiliations
                """,
            ),
            "performances": scalar(
                connection,
                "SELECT COUNT(*) FROM core.performances",
            ),
        }

        expected_table_counts = {
            "teams": EXPECTED["combined_teams"],
            "athletes": EXPECTED["athletes"],
            "meets": EXPECTED["meets"],
            "events": EXPECTED["events"],
            "athlete_affiliations": EXPECTED[
                "affiliations"
            ],
            "performances": EXPECTED[
                "performance_rows"
            ],
        }

        for table_name, actual_count in core_counts.items():
            expected_count = expected_table_counts.get(
                table_name
            )

            connection.execute(
                """
                INSERT INTO audit.table_counts (
                    build_run_id,
                    table_schema,
                    table_name,
                    actual_row_count,
                    expected_row_count,
                    passed
                )
                VALUES (?, 'core', ?, ?, ?, ?)
                """,
                [
                    build_run_id,
                    table_name,
                    actual_count,
                    expected_count,
                    (
                        True
                        if expected_count is None
                        else actual_count
                        == expected_count
                    ),
                ],
            )

        record_check(
            "directory team rows",
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM core.teams
                WHERE in_division_i_directory
                """,
            ),
            EXPECTED["directory_team_rows"],
        )

        record_check(
            "directory institutions",
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM core.schools
                WHERE is_division_i_directory_school
                """,
            ),
            EXPECTED["directory_institutions"],
        )

        record_check(
            "combined team domain",
            core_counts["teams"],
            EXPECTED["combined_teams"],
        )

        record_check(
            "performance team domain",
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM core.teams
                WHERE seen_in_performances
                """,
            ),
            EXPECTED["performance_teams"],
        )

        record_check(
            "athlete rows",
            core_counts["athletes"],
            EXPECTED["athletes"],
        )

        record_check(
            "roster source rows",
            scalar(
                connection,
                "SELECT COUNT(*) FROM stg_rosters",
            ),
            EXPECTED["roster_source_rows"],
        )

        record_check(
            "unique historical affiliations",
            core_counts["athlete_affiliations"],
            EXPECTED["affiliations"],
        )

        record_check(
            "roster duplicate excess rows",
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(duplicate_excess_rows),
                    0
                )
                FROM audit.roster_duplicate_groups
                """,
            ),
            EXPECTED["roster_duplicate_excess"],
        )

        record_check(
            "duplicate affiliation business keys",
            scalar(
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
            ),
            0,
        )

        record_check(
            "parser status rows",
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM stg_chunk_status
                """,
            ),
            EXPECTED["parser_status_rows"],
        )

        record_check(
            "parser status performance total",
            scalar(
                connection,
                """
                SELECT COALESCE(
                    SUM(
                        TRY_CAST(
                            performance_rows
                            AS BIGINT
                        )
                    ),
                    0
                )
                FROM stg_chunk_status
                """,
            ),
            EXPECTED["performance_rows"],
        )

        record_check(
            "parser failure rows",
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM stg_chunk_status
                WHERE
                    NULLIF(
                        TRIM(error_type),
                        ''
                    ) IS NOT NULL
                    OR NULLIF(
                        TRIM(error_message),
                        ''
                    ) IS NOT NULL
                    OR LOWER(
                        COALESCE(status, '')
                    ) LIKE '%fail%'
                    OR LOWER(
                        COALESCE(status, '')
                    ) LIKE '%error%'
                """,
            ),
            0,
        )

        record_check(
            "source performance rows",
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM stg_performances
                """,
            ),
            EXPECTED["performance_rows"],
        )

        record_check(
            "core performance rows",
            core_counts["performances"],
            EXPECTED["performance_rows"],
        )

        record_check(
            "distinct performance IDs",
            scalar(
                connection,
                """
                SELECT COUNT(
                    DISTINCT performance_id
                )
                FROM core.performances
                """,
            ),
            EXPECTED["performance_rows"],
        )

        record_check(
            "blank performance IDs",
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM core.performances
                WHERE NULLIF(
                    TRIM(performance_id),
                    ''
                ) IS NULL
                """,
            ),
            0,
        )

        record_check(
            "performance athletes",
            scalar(
                connection,
                """
                SELECT COUNT(
                    DISTINCT athlete_id
                )
                FROM core.performances
                """,
            ),
            EXPECTED["athletes_with_performances"],
        )

        record_check(
            "meet rows",
            core_counts["meets"],
            EXPECTED["meets"],
        )

        record_check(
            "event rows",
            core_counts["events"],
            EXPECTED["events"],
        )

        record_check(
            "blank performance team rows",
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM core.performances
                WHERE team_id IS NULL
                """,
            ),
            EXPECTED[
                "blank_performance_team_rows"
            ],
        )

        connection.execute(
            """
            INSERT INTO audit.affiliation_coverage (
                build_run_id,
                match_class,
                distinct_performance_keys,
                performance_rows
            )
            SELECT
                ?,
                match_class,
                COUNT(
                    DISTINCT (
                        athlete_id,
                        team_id,
                        season_id
                    )
                ),
                COUNT(*)
            FROM (
                SELECT
                    performance.*,
                    CASE
                        WHEN affiliation_id IS NOT NULL
                            THEN 'matched'
                        WHEN performance.team_id IS NULL
                            THEN 'blank_team_id'
                        WHEN NOT team.in_division_i_directory
                            THEN 'performance_only_team'
                        ELSE
                            'directory_team_without_roster_match'
                    END AS match_class
                FROM core.performances AS performance
                LEFT JOIN core.teams AS team
                    USING (team_id)
            )
            GROUP BY match_class
            """,
            [build_run_id],
        )

        coverage = {
            match_class: performance_rows
            for match_class, performance_rows
            in connection.execute(
                """
                SELECT
                    match_class,
                    performance_rows
                FROM audit.affiliation_coverage
                WHERE build_run_id = ?
                """,
                [build_run_id],
            ).fetchall()
        }

        record_check(
            "matched affiliation performance rows",
            int(coverage.get("matched", 0)),
            EXPECTED["matched_affiliation_rows"],
        )

        record_check(
            "blank-team affiliation rows",
            int(coverage.get("blank_team_id", 0)),
            EXPECTED[
                "blank_performance_team_rows"
            ],
        )

        record_check(
            "performance-only-team unmatched rows",
            int(
                coverage.get(
                    "performance_only_team",
                    0,
                )
            ),
            EXPECTED[
                "performance_only_team_rows"
            ],
        )

        record_check(
            "directory-team unmatched rows",
            int(
                coverage.get(
                    "directory_team_without_roster_match",
                    0,
                )
            ),
            EXPECTED[
                "directory_team_unmatched_rows"
            ],
        )

        record_check(
            "total unmatched affiliation rows",
            (
                int(
                    coverage.get(
                        "blank_team_id",
                        0,
                    )
                )
                + int(
                    coverage.get(
                        "performance_only_team",
                        0,
                    )
                )
                + int(
                    coverage.get(
                        "directory_team_without_roster_match",
                        0,
                    )
                )
            ),
            EXPECTED[
                "unmatched_affiliation_rows"
            ],
        )

        orphan_queries = {
            "performance athlete orphans": """
                SELECT COUNT(*)
                FROM core.performances AS performance
                LEFT JOIN core.athletes AS athlete
                    USING (athlete_id)
                WHERE athlete.athlete_id IS NULL
            """,
            "performance team orphans": """
                SELECT COUNT(*)
                FROM core.performances AS performance
                LEFT JOIN core.teams AS team
                    USING (team_id)
                WHERE performance.team_id IS NOT NULL
                  AND team.team_id IS NULL
            """,
            "performance season orphans": """
                SELECT COUNT(*)
                FROM core.performances AS performance
                LEFT JOIN core.seasons AS season
                    USING (season_id)
                WHERE season.season_id IS NULL
            """,
            "performance meet orphans": """
                SELECT COUNT(*)
                FROM core.performances AS performance
                LEFT JOIN core.meets AS meet
                    USING (meet_id)
                WHERE meet.meet_id IS NULL
            """,
            "performance event orphans": """
                SELECT COUNT(*)
                FROM core.performances AS performance
                LEFT JOIN core.events AS event
                    USING (event_id)
                WHERE event.event_id IS NULL
            """,
            "affiliation athlete orphans": """
                SELECT COUNT(*)
                FROM core.athlete_affiliations
                    AS affiliation
                LEFT JOIN core.athletes AS athlete
                    USING (athlete_id)
                WHERE athlete.athlete_id IS NULL
            """,
            "affiliation team orphans": """
                SELECT COUNT(*)
                FROM core.athlete_affiliations
                    AS affiliation
                LEFT JOIN core.teams AS team
                    USING (team_id)
                WHERE team.team_id IS NULL
            """,
            "affiliation season orphans": """
                SELECT COUNT(*)
                FROM core.athlete_affiliations
                    AS affiliation
                LEFT JOIN core.seasons AS season
                    USING (season_id)
                WHERE season.season_id IS NULL
            """,
        }

        for check_name, query in orphan_queries.items():
            record_check(
                check_name,
                scalar(connection, query),
                0,
            )

        record_check(
            "blank raw marks",
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM core.performances
                WHERE NULLIF(TRIM(mark), '') IS NULL
                """,
            ),
            0,
        )

        record_check(
            "blank raw meet dates",
            scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM core.performances
                WHERE NULLIF(
                    TRIM(meet_date_text),
                    ''
                ) IS NULL
                """,
            ),
            0,
        )

        if hard_failures:
            raise RuntimeError(
                "Mandatory build audit failed:\n"
                + "\n".join(
                    f"  - {failure}"
                    for failure in hard_failures
                )
            )

        completed_at = datetime.now(timezone.utc)

        connection.execute(
            """
            UPDATE audit.build_runs
            SET
                completed_at = ?,
                status = 'pass',
                actual_performance_rows = ?,
                notes = ?
            WHERE build_run_id = ?
            """,
            [
                completed_at,
                core_counts["performances"],
                (
                    "All Milestone 3 hard integrity "
                    "checks passed."
                ),
                build_run_id,
            ],
        )

        connection.execute("COMMIT")
        transaction_open = False
        build_committed = True

        print()
        print("Transaction committed.")

        connection.execute("CHECKPOINT")
        print("Staging database checkpoint completed.")

        connection.close()
        connection = None

        os.replace(
            STAGING_DATABASE,
            PRODUCTION_DATABASE,
        )

        build_size = PRODUCTION_DATABASE.stat().st_size

        print()
        print("PRODUCTION DATABASE PUBLISHED")
        print("=" * 80)
        print(f"Database: {PRODUCTION_DATABASE}")
        print(
            "Database size: "
            f"{build_size / (1024 ** 3):,.2f} GiB"
        )
        print(
            "Performance rows: "
            f"{core_counts['performances']:,}"
        )
        print(
            "Historical affiliations: "
            f"{core_counts['athlete_affiliations']:,}"
        )
        print(
            "Teams: "
            f"{core_counts['teams']:,}"
        )
        print(
            "Institutions: "
            f"{core_counts['schools']:,}"
        )
        print()
        print("OVERALL BUILD RESULT: PASS")

    except (Exception, KeyboardInterrupt):
        if connection is not None:
            if transaction_open:
                try:
                    connection.execute("ROLLBACK")
                except duckdb.Error:
                    pass

            connection.close()

        if not build_committed:
            for path in (
                STAGING_DATABASE,
                Path(str(STAGING_DATABASE) + ".wal"),
            ):
                if path.exists():
                    path.unlink()

        print()
        print("OVERALL BUILD RESULT: FAIL")
        print(
            "The production database was not published."
        )
        raise

    finally:
        shutil.rmtree(
            TEMP_DIRECTORY,
            ignore_errors=True,
        )


def main() -> None:
    """Run preflight mode or the complete production build."""
    arguments = parse_arguments()
    inventory = collect_inventory()

    run_preflight(
        inventory,
        allow_staging_cleanup=arguments.build,
    )

    if arguments.preflight_only:
        print()
        print("No database was created.")
        print("No source data was loaded.")
        return

    run_production_build(inventory)


if __name__ == "__main__":
    main()
