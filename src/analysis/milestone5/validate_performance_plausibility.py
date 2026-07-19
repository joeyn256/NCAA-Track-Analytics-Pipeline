#!/usr/bin/env python3
"""
Milestone 5 Phase 2C — Performance Plausibility Validation

Validates the numeric marks created in Phase 2B.

Design:
- broad event-specific absolute bounds identify impossible/corrupt values;
- empirical distribution tails identify valid marks needing review;
- distribution extremes are NOT automatically excluded;
- status rows remain explicit and nonnumeric;
- no source database is modified.

Outputs a compact validity database keyed by canonical performance ID.
"""

from __future__ import annotations

import csv
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


VALIDITY_VERSION = "performance_validity_v1"
EXPECTED_ROWS = 4_953_801
EXPECTED_EVENTS = 33

PARSED_DB = Path(
    "data/processed/milestone5/mark_parsing_v1/"
    "parsed_v1/parsed_performances_v1.duckdb"
)
OUTPUT_DIR = Path(
    "data/processed/milestone5/mark_parsing_v1/"
    "plausibility_v1"
)
OUTPUT_DB = OUTPUT_DIR / "performance_validity_v1.duckdb"


# Broad physical/data-integrity limits. These are intentionally wider than
# normal NCAA ranges. Values inside these limits can still be flagged as
# distribution extremes without being excluded.
#
# code, hard_min, hard_max, unit, notes
ABSOLUTE_BOUNDS = [
    ("55M", 4.5, 30.0, "seconds", "Broad sprint integrity range."),
    ("60M", 5.0, 30.0, "seconds", "Broad sprint integrity range."),
    ("100M", 8.0, 60.0, "seconds", "Broad sprint integrity range."),
    ("200M", 16.0, 120.0, "seconds", "Broad sprint integrity range."),
    ("300M", 24.0, 180.0, "seconds", "Broad sprint integrity range."),
    ("400M", 32.0, 300.0, "seconds", "Broad one-lap integrity range."),
    ("500M", 40.0, 360.0, "seconds", "Broad long-sprint integrity range."),
    ("600M", 50.0, 420.0, "seconds", "Broad long-sprint integrity range."),
    ("800M", 75.0, 600.0, "seconds", "Broad middle-distance integrity range."),
    ("1000M", 95.0, 720.0, "seconds", "Broad middle-distance integrity range."),
    ("1500M", 150.0, 1200.0, "seconds", "Broad middle-distance integrity range."),
    ("MILE", 160.0, 1300.0, "seconds", "Broad mile integrity range."),
    ("3000M", 350.0, 2400.0, "seconds", "Broad distance integrity range."),
    ("5000M", 600.0, 4800.0, "seconds", "Broad distance integrity range."),
    ("10000M", 1200.0, 9600.0, "seconds", "Broad distance integrity range."),
    ("55H", 5.5, 40.0, "seconds", "Broad hurdles integrity range."),
    ("60H", 6.0, 40.0, "seconds", "Broad hurdles integrity range."),
    ("100H", 9.0, 60.0, "seconds", "Broad hurdles integrity range."),
    ("110H", 9.0, 60.0, "seconds", "Broad hurdles integrity range."),
    ("400H", 35.0, 300.0, "seconds", "Broad hurdles integrity range."),
    ("3000SC", 400.0, 3000.0, "seconds", "Broad steeplechase integrity range."),
    ("LJ", 0.5, 12.0, "meters", "Broad horizontal-jump integrity range."),
    ("TJ", 1.0, 25.0, "meters", "Broad horizontal-jump integrity range."),
    ("HJ", 0.5, 4.0, "meters", "Broad vertical-jump integrity range."),
    ("PV", 0.5, 10.0, "meters", "Broad pole-vault integrity range."),
    ("SP", 0.5, 40.0, "meters", "Broad throw integrity range."),
    ("DT", 0.5, 150.0, "meters", "Broad throw integrity range."),
    ("HT", 0.5, 150.0, "meters", "Broad throw integrity range."),
    ("WT", 0.5, 60.0, "meters", "Broad throw integrity range."),
    ("JT", 0.5, 150.0, "meters", "Broad throw integrity range."),
    ("PENT", 100.0, 10000.0, "points", "Broad combined-event integrity range."),
    ("HEP", 100.0, 15000.0, "points", "Broad combined-event integrity range."),
    ("DEC", 100.0, 20000.0, "points", "Broad combined-event integrity range."),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(block_size):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(
    path: Path,
    rows: Iterable[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def query_dicts(
    con: duckdb.DuckDBPyConnection,
    sql: str,
) -> list[dict[str, Any]]:
    result = con.execute(sql)
    columns = [item[0] for item in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def add_check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    observed: Any,
    expected: Any,
    details: str = "",
) -> None:
    checks.append(
        {
            "check_name": name,
            "status": "PASS" if passed else "FAIL",
            "observed": observed,
            "expected": expected,
            "details": details,
        }
    )


def manifest_row(name: str, path: Path, stage: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "input_name": name,
        "stage": stage,
        "path": str(path),
        "size_bytes": stat.st_size,
        "mtime_epoch_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def choose_column(
    columns: set[str],
    candidates: list[str],
) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def csv_export(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    path: Path,
) -> None:
    escaped_path = path.as_posix().replace("'", "''")
    con.execute(
        f"""
        COPY ({sql})
        TO '{escaped_path}'
        (HEADER, DELIMITER ',')
        """
    )


def main() -> int:
    root = Path.cwd()
    parsed_path = root / PARSED_DB
    output_dir = root / OUTPUT_DIR
    output_db = root / OUTPUT_DB
    output_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 2C — PERFORMANCE PLAUSIBILITY VALIDATION")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Validity version: {VALIDITY_VERSION}")
    print(f"Parsed DB: {parsed_path}")
    print(f"Output DB: {output_db}")

    exists = parsed_path.exists()
    add_check(
        checks,
        "parsed_performance_database_exists",
        exists,
        exists,
        True,
        str(parsed_path),
    )
    if not exists:
        write_csv(
            output_dir / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Parsed performance database is missing.")
        return 1

    manifest_before = [
        manifest_row("parsed_performance_database", parsed_path, "before")
    ]

    disk = shutil.disk_usage(root)
    free_gib = disk.free / (1024**3)
    write_csv(
        output_dir / "disk_space.csv",
        [
            {
                "path": str(root),
                "total_bytes": disk.total,
                "used_bytes": disk.used,
                "free_bytes": disk.free,
                "free_gib": round(free_gib, 3),
            }
        ],
        ["path", "total_bytes", "used_bytes", "free_bytes", "free_gib"],
    )
    add_check(
        checks,
        "minimum_free_disk_space",
        free_gib >= 2.0,
        round(free_gib, 3),
        "at least 2.0 GiB",
        "The validity database is compact and does not copy all source columns.",
    )

    if output_db.exists():
        output_db.unlink()

    con = duckdb.connect(str(output_db))
    try:
        con.execute("PRAGMA threads=4")
        con.execute("PRAGMA enable_progress_bar=false")
        con.execute(
            f"ATTACH '{sql_path(parsed_path)}' AS parsed_source (READ_ONLY)"
        )

        schema_rows = query_dicts(
            con,
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_catalog = 'parsed_source'
              AND table_schema = 'main'
              AND table_name = 'parsed_performances'
            ORDER BY ordinal_position
            """,
        )
        source_columns = {row["column_name"] for row in schema_rows}

        required_columns = {
            "canonical_person_performance_id",
            "canonical_person_id",
            "canonical_event_code",
            "canonical_event_name",
            "mark_type",
            "performance_direction",
            "mark",
            "secondary_mark",
            "primary_parse_state",
            "primary_status_code",
            "primary_parser_class",
            "primary_parsed_value",
            "normalized_unit",
        }
        missing_required = sorted(required_columns - source_columns)
        add_check(
            checks,
            "required_parsed_columns_present",
            not missing_required,
            ",".join(missing_required),
            "none missing",
        )
        if missing_required:
            write_csv(
                output_dir / "hard_checks.csv",
                checks,
                ["check_name", "status", "observed", "expected", "details"],
            )
            print(
                "PHASE GATE: FAIL — Required parsed columns are missing: "
                + ", ".join(missing_required)
            )
            return 1

        gender_column = choose_column(
            source_columns,
            ["gender", "gender_code", "sex", "athlete_gender"],
        )
        season_type_column = choose_column(
            source_columns,
            ["season_type", "season", "sport_season"],
        )
        season_year_column = choose_column(
            source_columns,
            ["season_year", "year", "academic_year"],
        )
        performance_id_column = choose_column(
            source_columns,
            ["performance_id", "source_performance_id"],
        )
        event_id_column = choose_column(
            source_columns,
            ["event_id"],
        )
        raw_event_column = choose_column(
            source_columns,
            ["event", "raw_event", "raw_event_label"],
        )

        def optional_expr(
            column: str | None,
            alias: str,
            cast_type: str,
        ) -> str:
            if column is None:
                return f"NULL::{cast_type} AS {quote_identifier(alias)}"
            return (
                f"CAST(p.{quote_identifier(column)} AS {cast_type}) "
                f"AS {quote_identifier(alias)}"
            )

        con.execute(
            """
            CREATE TABLE main.absolute_event_bounds (
                validity_version VARCHAR,
                canonical_event_code VARCHAR,
                hard_min_value DOUBLE,
                hard_max_value DOUBLE,
                normalized_unit VARCHAR,
                bound_notes VARCHAR
            )
            """
        )
        con.executemany(
            """
            INSERT INTO main.absolute_event_bounds
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    VALIDITY_VERSION,
                    code,
                    hard_min,
                    hard_max,
                    unit,
                    notes,
                )
                for code, hard_min, hard_max, unit, notes in ABSOLUTE_BOUNDS
            ],
        )
        con.execute(
            """
            CREATE UNIQUE INDEX absolute_event_bounds_code_uq
            ON main.absolute_event_bounds(canonical_event_code)
            """
        )

        source_event_count = con.execute(
            """
            SELECT COUNT(DISTINCT canonical_event_code)
            FROM parsed_source.main.parsed_performances
            """
        ).fetchone()[0]
        bounds_count = con.execute(
            "SELECT COUNT(*) FROM main.absolute_event_bounds"
        ).fetchone()[0]
        missing_bounds = query_dicts(
            con,
            """
            SELECT DISTINCT p.canonical_event_code
            FROM parsed_source.main.parsed_performances AS p
            LEFT JOIN main.absolute_event_bounds AS b
              USING (canonical_event_code)
            WHERE b.canonical_event_code IS NULL
            ORDER BY 1
            """,
        )

        add_check(
            checks,
            "source_event_count",
            source_event_count == EXPECTED_EVENTS,
            source_event_count,
            EXPECTED_EVENTS,
        )
        add_check(
            checks,
            "absolute_bounds_row_count",
            bounds_count == EXPECTED_EVENTS,
            bounds_count,
            EXPECTED_EVENTS,
        )
        add_check(
            checks,
            "every_source_event_has_absolute_bounds",
            len(missing_bounds) == 0,
            ",".join(
                row["canonical_event_code"]
                for row in missing_bounds
            ),
            "none missing",
        )

        print("Calculating event distributions...")

        con.execute(
            """
            CREATE TABLE main.event_distribution_reference AS
            SELECT
                p.canonical_event_code,
                ANY_VALUE(p.canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(p.mark_type) AS mark_type,
                ANY_VALUE(p.performance_direction)
                    AS performance_direction,
                ANY_VALUE(p.normalized_unit) AS normalized_unit,
                COUNT(*) AS parsed_count,
                MIN(p.primary_parsed_value) AS observed_min,
                quantile_cont(p.primary_parsed_value, 0.0001)
                    AS q0001,
                quantile_cont(p.primary_parsed_value, 0.001)
                    AS q001,
                quantile_cont(p.primary_parsed_value, 0.01)
                    AS q01,
                quantile_cont(p.primary_parsed_value, 0.50)
                    AS median,
                quantile_cont(p.primary_parsed_value, 0.99)
                    AS q99,
                quantile_cont(p.primary_parsed_value, 0.999)
                    AS q999,
                quantile_cont(p.primary_parsed_value, 0.9999)
                    AS q9999,
                MAX(p.primary_parsed_value) AS observed_max,
                AVG(p.primary_parsed_value) AS mean_value,
                STDDEV_SAMP(p.primary_parsed_value) AS stddev_value
            FROM parsed_source.main.parsed_performances AS p
            WHERE p.primary_parse_state = 'parsed'
            GROUP BY p.canonical_event_code
            ORDER BY p.canonical_event_code
            """
        )

        print("Classifying performance validity...")

        optional_selects = [
            optional_expr(
                performance_id_column,
                "performance_id",
                "VARCHAR",
            ),
            optional_expr(event_id_column, "event_id", "VARCHAR"),
            optional_expr(raw_event_column, "raw_event", "VARCHAR"),
            optional_expr(gender_column, "gender_code", "VARCHAR"),
            optional_expr(
                season_type_column,
                "season_type",
                "VARCHAR",
            ),
            optional_expr(
                season_year_column,
                "season_year",
                "VARCHAR",
            ),
        ]
        optional_sql = ",\n                ".join(optional_selects)

        con.execute(
            f"""
            CREATE TABLE main.performance_validity AS
            SELECT
                '{VALIDITY_VERSION}'::VARCHAR AS validity_version,
                p.canonical_person_performance_id,
                p.canonical_person_id,
                {optional_sql},
                p.canonical_event_code,
                p.canonical_event_name,
                p.mark_type,
                p.performance_direction,
                p.normalized_unit,
                p.mark AS raw_mark,
                p.secondary_mark AS raw_secondary_mark,
                p.primary_parse_state,
                p.primary_status_code,
                p.primary_parser_class,
                p.primary_parsed_value,
                b.hard_min_value,
                b.hard_max_value,
                d.q0001,
                d.q001,
                d.q01,
                d.median,
                d.q99,
                d.q999,
                d.q9999,

                CASE
                    WHEN p.primary_parse_state = 'status'
                        THEN 'not_numeric_status'
                    WHEN p.primary_parse_state = 'blank'
                        THEN 'invalid_blank'
                    WHEN p.primary_parse_state = 'unrecognized'
                        THEN 'invalid_unrecognized'
                    WHEN p.primary_parsed_value IS NULL
                        THEN 'invalid_missing_numeric_value'
                    WHEN p.primary_parsed_value <= 0
                        THEN 'invalid_nonpositive_value'
                    WHEN p.primary_parsed_value < b.hard_min_value
                        THEN 'invalid_below_absolute_bound'
                    WHEN p.primary_parsed_value > b.hard_max_value
                        THEN 'invalid_above_absolute_bound'
                    ELSE 'valid'
                END AS validity_status,

                CASE
                    WHEN p.primary_parse_state = 'status'
                        THEN 'source_status_' ||
                             lower(coalesce(p.primary_status_code, 'unknown'))
                    WHEN p.primary_parse_state = 'blank'
                        THEN 'blank_primary_mark'
                    WHEN p.primary_parse_state = 'unrecognized'
                        THEN 'unrecognized_primary_mark'
                    WHEN p.primary_parsed_value IS NULL
                        THEN 'missing_numeric_value_after_parse'
                    WHEN p.primary_parsed_value <= 0
                        THEN 'numeric_value_is_not_positive'
                    WHEN p.primary_parsed_value < b.hard_min_value
                        THEN 'value_below_broad_event_integrity_bound'
                    WHEN p.primary_parsed_value > b.hard_max_value
                        THEN 'value_above_broad_event_integrity_bound'
                    ELSE ''
                END AS validity_reason,

                CASE
                    WHEN p.primary_parse_state = 'parsed'
                     AND p.primary_parsed_value > 0
                     AND p.primary_parsed_value
                         BETWEEN b.hard_min_value AND b.hard_max_value
                    THEN TRUE
                    ELSE FALSE
                END AS hard_validity_pass,

                CASE
                    WHEN p.primary_parse_state <> 'parsed'
                        THEN 'not_applicable'
                    WHEN p.primary_parsed_value < b.hard_min_value
                      OR p.primary_parsed_value > b.hard_max_value
                        THEN 'hard_invalid'
                    WHEN p.primary_parsed_value < d.q0001
                        THEN 'distribution_extreme_low'
                    WHEN p.primary_parsed_value > d.q9999
                        THEN 'distribution_extreme_high'
                    ELSE 'not_extreme'
                END AS distribution_flag,

                CASE
                    WHEN p.primary_parse_state <> 'parsed'
                        THEN 'not_applicable'
                    WHEN p.primary_parsed_value < b.hard_min_value
                      OR p.primary_parsed_value > b.hard_max_value
                        THEN 'hard_invalid'
                    WHEN p.performance_direction = 'lower_is_better'
                     AND p.primary_parsed_value < d.q0001
                        THEN 'elite_tail_extreme'
                    WHEN p.performance_direction = 'lower_is_better'
                     AND p.primary_parsed_value > d.q9999
                        THEN 'lower_performance_tail_extreme'
                    WHEN p.performance_direction = 'higher_is_better'
                     AND p.primary_parsed_value > d.q9999
                        THEN 'elite_tail_extreme'
                    WHEN p.performance_direction = 'higher_is_better'
                     AND p.primary_parsed_value < d.q0001
                        THEN 'lower_performance_tail_extreme'
                    ELSE 'not_extreme'
                END AS performance_tail_flag,

                CASE
                    WHEN p.primary_parse_state = 'parsed'
                     AND p.primary_parsed_value > 0
                     AND p.primary_parsed_value
                         BETWEEN b.hard_min_value AND b.hard_max_value
                    THEN TRUE
                    ELSE FALSE
                END AS valid_numeric_candidate
            FROM parsed_source.main.parsed_performances AS p
            JOIN main.absolute_event_bounds AS b
              USING (canonical_event_code)
            JOIN main.event_distribution_reference AS d
              USING (canonical_event_code)
            """
        )

        con.execute(
            """
            CREATE UNIQUE INDEX performance_validity_id_uq
            ON main.performance_validity(
                canonical_person_performance_id
            )
            """
        )
        con.execute(
            """
            CREATE INDEX performance_validity_event_idx
            ON main.performance_validity(
                canonical_event_code,
                validity_status
            )
            """
        )
        con.execute(
            """
            CREATE INDEX performance_validity_person_idx
            ON main.performance_validity(
                canonical_person_id,
                canonical_event_code
            )
            """
        )

        con.execute(
            """
            CREATE TABLE main.event_validity_summary AS
            SELECT
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(mark_type) AS mark_type,
                ANY_VALUE(performance_direction)
                    AS performance_direction,
                ANY_VALUE(normalized_unit) AS normalized_unit,
                COUNT(*) AS total_rows,
                COUNT(*) FILTER (
                    WHERE primary_parse_state = 'parsed'
                ) AS parsed_rows,
                COUNT(*) FILTER (
                    WHERE validity_status = 'not_numeric_status'
                ) AS status_rows,
                COUNT(*) FILTER (
                    WHERE validity_status LIKE 'invalid_%'
                ) AS hard_invalid_rows,
                COUNT(*) FILTER (
                    WHERE valid_numeric_candidate
                ) AS valid_numeric_rows,
                COUNT(*) FILTER (
                    WHERE distribution_flag =
                        'distribution_extreme_low'
                ) AS distribution_extreme_low_rows,
                COUNT(*) FILTER (
                    WHERE distribution_flag =
                        'distribution_extreme_high'
                ) AS distribution_extreme_high_rows,
                COUNT(*) FILTER (
                    WHERE performance_tail_flag =
                        'elite_tail_extreme'
                ) AS elite_tail_extreme_rows,
                COUNT(*) FILTER (
                    WHERE performance_tail_flag =
                        'lower_performance_tail_extreme'
                ) AS lower_performance_tail_extreme_rows,
                MIN(primary_parsed_value) FILTER (
                    WHERE valid_numeric_candidate
                ) AS valid_min_value,
                MAX(primary_parsed_value) FILTER (
                    WHERE valid_numeric_candidate
                ) AS valid_max_value
            FROM main.performance_validity
            GROUP BY canonical_event_code
            ORDER BY canonical_event_code
            """
        )

        con.execute(
            """
            CREATE TABLE main.hard_invalid_performances AS
            SELECT *
            FROM main.performance_validity
            WHERE validity_status LIKE 'invalid_%'
            ORDER BY
                canonical_event_code,
                validity_status,
                primary_parsed_value
            """
        )

        con.execute(
            """
            CREATE TABLE main.distribution_extremes AS
            SELECT *
            FROM main.performance_validity
            WHERE distribution_flag IN (
                'distribution_extreme_low',
                'distribution_extreme_high'
            )
              AND hard_validity_pass
            ORDER BY
                canonical_event_code,
                distribution_flag,
                primary_parsed_value
            """
        )

        overall = query_dicts(
            con,
            """
            SELECT
                COUNT(*) AS row_count,
                COUNT(DISTINCT canonical_event_code) AS event_count,
                COUNT(DISTINCT canonical_person_performance_id)
                    AS distinct_performance_ids,
                COUNT(*) FILTER (
                    WHERE validity_status = 'not_numeric_status'
                ) AS status_rows,
                COUNT(*) FILTER (
                    WHERE validity_status LIKE 'invalid_%'
                ) AS hard_invalid_rows,
                COUNT(*) FILTER (
                    WHERE valid_numeric_candidate
                ) AS valid_numeric_rows,
                COUNT(*) FILTER (
                    WHERE distribution_flag IN (
                        'distribution_extreme_low',
                        'distribution_extreme_high'
                    )
                    AND hard_validity_pass
                ) AS distribution_extreme_rows,
                COUNT(*) FILTER (
                    WHERE validity_status IS NULL
                ) AS rows_without_validity_status,
                COUNT(*) FILTER (
                    WHERE valid_numeric_candidate
                      AND primary_parse_state <> 'parsed'
                ) AS nonparsed_marked_valid,
                COUNT(*) FILTER (
                    WHERE valid_numeric_candidate
                      AND (
                        primary_parsed_value IS NULL
                        OR primary_parsed_value <= 0
                        OR primary_parsed_value < hard_min_value
                        OR primary_parsed_value > hard_max_value
                      )
                ) AS impossible_marked_valid
            FROM main.performance_validity
            """,
        )[0]

        source_count = con.execute(
            """
            SELECT COUNT(*)
            FROM parsed_source.main.parsed_performances
            """
        ).fetchone()[0]

        add_check(
            checks,
            "validity_row_count_matches_source",
            int(overall["row_count"]) == source_count == EXPECTED_ROWS,
            overall["row_count"],
            EXPECTED_ROWS,
            f"source_count={source_count}",
        )
        add_check(
            checks,
            "validity_event_count",
            int(overall["event_count"]) == EXPECTED_EVENTS,
            overall["event_count"],
            EXPECTED_EVENTS,
        )
        add_check(
            checks,
            "validity_ids_unique",
            int(overall["distinct_performance_ids"])
            == int(overall["row_count"]),
            (
                int(overall["row_count"])
                - int(overall["distinct_performance_ids"])
            ),
            0,
        )
        add_check(
            checks,
            "every_row_has_validity_status",
            int(overall["rows_without_validity_status"]) == 0,
            overall["rows_without_validity_status"],
            0,
        )
        add_check(
            checks,
            "only_parsed_rows_can_be_valid_numeric_candidates",
            int(overall["nonparsed_marked_valid"]) == 0,
            overall["nonparsed_marked_valid"],
            0,
        )
        add_check(
            checks,
            "no_impossible_value_marked_valid",
            int(overall["impossible_marked_valid"]) == 0,
            overall["impossible_marked_valid"],
            0,
        )

        event_summary_count = con.execute(
            "SELECT COUNT(*) FROM main.event_validity_summary"
        ).fetchone()[0]
        add_check(
            checks,
            "event_validity_summary_row_count",
            event_summary_count == EXPECTED_EVENTS,
            event_summary_count,
            EXPECTED_EVENTS,
        )

        # Export production and audit summaries.
        csv_export(
            con,
            """
            SELECT *
            FROM main.absolute_event_bounds
            ORDER BY canonical_event_code
            """,
            output_dir / "absolute_event_bounds.csv",
        )
        csv_export(
            con,
            """
            SELECT *
            FROM main.event_distribution_reference
            ORDER BY canonical_event_code
            """,
            output_dir / "event_distribution_reference.csv",
        )
        csv_export(
            con,
            """
            SELECT *
            FROM main.event_validity_summary
            ORDER BY canonical_event_code
            """,
            output_dir / "event_validity_summary.csv",
        )
        csv_export(
            con,
            """
            SELECT
                canonical_person_performance_id,
                canonical_person_id,
                performance_id,
                event_id,
                raw_event,
                gender_code,
                season_type,
                season_year,
                canonical_event_code,
                canonical_event_name,
                mark_type,
                raw_mark,
                raw_secondary_mark,
                primary_parser_class,
                primary_parsed_value,
                normalized_unit,
                hard_min_value,
                hard_max_value,
                validity_status,
                validity_reason
            FROM main.hard_invalid_performances
            ORDER BY
                canonical_event_code,
                validity_status,
                primary_parsed_value
            LIMIT 1000
            """,
            output_dir / "hard_invalid_samples.csv",
        )
        csv_export(
            con,
            """
            WITH ranked AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            canonical_event_code,
                            performance_tail_flag
                        ORDER BY
                            CASE
                                WHEN performance_tail_flag =
                                    'elite_tail_extreme'
                                AND performance_direction =
                                    'lower_is_better'
                                THEN primary_parsed_value
                                WHEN performance_tail_flag =
                                    'lower_performance_tail_extreme'
                                AND performance_direction =
                                    'higher_is_better'
                                THEN primary_parsed_value
                                ELSE -primary_parsed_value
                            END
                    ) AS sample_rank
                FROM main.distribution_extremes
            )
            SELECT
                canonical_person_performance_id,
                canonical_person_id,
                gender_code,
                season_type,
                season_year,
                canonical_event_code,
                canonical_event_name,
                performance_direction,
                raw_mark,
                primary_parsed_value,
                normalized_unit,
                q0001,
                q9999,
                distribution_flag,
                performance_tail_flag
            FROM ranked
            WHERE sample_rank <= 25
            ORDER BY
                canonical_event_code,
                performance_tail_flag,
                sample_rank
            """,
            output_dir / "distribution_extreme_samples.csv",
        )

        manifest_after = [
            manifest_row("parsed_performance_database", parsed_path, "after")
        ]
        before = manifest_before[0]
        after = manifest_after[0]
        unchanged = (
            before["size_bytes"] == after["size_bytes"]
            and before["mtime_epoch_ns"] == after["mtime_epoch_ns"]
            and before["sha256"] == after["sha256"]
        )
        add_check(
            checks,
            "parsed_performance_database_unchanged",
            unchanged,
            after["sha256"],
            before["sha256"],
        )

        write_csv(
            output_dir / "input_manifest.csv",
            manifest_before + manifest_after,
            [
                "input_name",
                "stage",
                "path",
                "size_bytes",
                "mtime_epoch_ns",
                "sha256",
            ],
        )
        write_csv(
            output_dir / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )

        failed = [
            check for check in checks
            if check["status"] == "FAIL"
        ]

        report_lines = [
            "MILESTONE 5 PHASE 2C — PERFORMANCE PLAUSIBILITY VALIDATION",
            "=" * 78,
            f"Finished UTC: {utc_now()}",
            f"Validity version: {VALIDITY_VERSION}",
            "",
            "SCALE",
            "-" * 78,
            f"Validity rows: {int(overall['row_count']):,}",
            f"Canonical events: {int(overall['event_count']):,}",
            f"Status rows: {int(overall['status_rows']):,}",
            f"Valid numeric candidates: {int(overall['valid_numeric_rows']):,}",
            f"Hard-invalid numeric rows: {int(overall['hard_invalid_rows']):,}",
            (
                "Valid distribution-tail review rows: "
                f"{int(overall['distribution_extreme_rows']):,}"
            ),
            "",
            "POLICY",
            "-" * 78,
            "Absolute bounds are broad integrity checks, not scoring ceilings.",
            "Values outside absolute bounds are hard-invalid candidates.",
            "Values beyond empirical 0.01% tails remain valid but are flagged.",
            "Elite-tail marks are preserved for later NCAA-record comparison.",
            "No distribution extreme is automatically deleted.",
            "",
            "OUTPUT DATABASE",
            "-" * 78,
            "main.performance_validity",
            "main.absolute_event_bounds",
            "main.event_distribution_reference",
            "main.event_validity_summary",
            "main.hard_invalid_performances",
            "main.distribution_extremes",
            "",
            "HARD CHECK SUMMARY",
            "-" * 78,
            f"PASS: {sum(c['status'] == 'PASS' for c in checks)}",
            f"FAIL: {len(failed)}",
            "",
            "PHASE GATE",
            "-" * 78,
            (
                "PASS — Plausibility classifications are ready for review."
                if not failed
                else "FAIL — Correct validity accounting or input errors."
            ),
        ]

        (output_dir / "plausibility_report.txt").write_text(
            "\n".join(report_lines) + "\n",
            encoding="utf-8",
        )

        print()
        print(f"Validity rows: {int(overall['row_count']):,}")
        print(f"Valid numeric candidates: {int(overall['valid_numeric_rows']):,}")
        print(f"Hard-invalid numeric rows: {int(overall['hard_invalid_rows']):,}")
        print(
            "Valid distribution-tail review rows: "
            f"{int(overall['distribution_extreme_rows']):,}"
        )
        print()
        print("Created:")
        for filename in [
            "performance_validity_v1.duckdb",
            "plausibility_report.txt",
            "absolute_event_bounds.csv",
            "event_distribution_reference.csv",
            "event_validity_summary.csv",
            "hard_invalid_samples.csv",
            "distribution_extreme_samples.csv",
            "input_manifest.csv",
            "disk_space.csv",
            "hard_checks.csv",
        ]:
            print(f"  {output_dir / filename}")

        if failed:
            print()
            print("PHASE GATE: FAIL")
            for check in failed:
                print(
                    f"  {check['check_name']}: "
                    f"observed={check['observed']} "
                    f"expected={check['expected']}"
                )
            return 1

        print()
        print("PHASE GATE: PASS")
        print("Stop here and inspect hard-invalid and extreme samples.")
        return 0

    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
