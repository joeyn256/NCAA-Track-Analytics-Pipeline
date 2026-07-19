#!/usr/bin/env python3
"""
Milestone 5 Phase 2E-2 — Freeze Track Performance Foundation

Combines:
- parsed track marks;
- plausibility classifications;
- canonical gender and season metadata;
- final school-stint attribution.

Creates:
1. all indoor/outdoor track rows with explicit eligibility reasons;
2. the scoring-eligible track subset;
3. coverage and exclusion audits.

Cross-country rows are explicitly excluded from this track foundation and
remain available for the separate XC normalization/ranking branch.
"""

from __future__ import annotations

import csv
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


FOUNDATION_VERSION = "track_performance_foundation_v1"
EXPECTED_PARSED_ROWS = 4_953_801
EXPECTED_TRACK_ROWS = 4_953_753
EXPECTED_XC_ROWS_IN_TRACK_REGISTRY = 48

PARSED_DB = Path(
    "data/processed/milestone5/mark_parsing_v1/"
    "parsed_v1/parsed_performances_v1.duckdb"
)
VALIDITY_DB = Path(
    "data/processed/milestone5/mark_parsing_v1/"
    "plausibility_v1/performance_validity_v1.duckdb"
)
STINT_DB = Path(
    "data/processed/milestone4/final_school_stints_v1_1/"
    "final_school_stints_v1_1.duckdb"
)
OUTPUT_DIR = Path(
    "data/processed/milestone5/"
    "track_performance_foundation_v1/final_v1"
)
OUTPUT_DB = OUTPUT_DIR / "track_performance_foundation_v1.duckdb"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(block_size):
            digest.update(chunk)
    return digest.hexdigest()


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


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


def choose_column(
    columns: set[str],
    candidates: list[str],
) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def optional_select(
    alias: str,
    source_column: str | None,
    output_name: str,
    cast_type: str = "VARCHAR",
) -> str:
    if source_column is None:
        return f"NULL::{cast_type} AS {quoted(output_name)}"
    return (
        f"CAST({alias}.{quoted(source_column)} AS {cast_type}) "
        f"AS {quoted(output_name)}"
    )


def export_csv(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    path: Path,
) -> None:
    escaped = path.as_posix().replace("'", "''")
    con.execute(
        f"COPY ({sql}) TO '{escaped}' (HEADER, DELIMITER ',')"
    )


def main() -> int:
    root = Path.cwd()
    parsed_path = root / PARSED_DB
    validity_path = root / VALIDITY_DB
    stint_path = root / STINT_DB
    output_dir = root / OUTPUT_DIR
    output_db = root / OUTPUT_DB
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = {
        "parsed_performance_database": parsed_path,
        "performance_validity_database": validity_path,
        "school_stint_database": stint_path,
    }
    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 2E-2 — FREEZE TRACK PERFORMANCE FOUNDATION")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Foundation version: {FOUNDATION_VERSION}")
    print(f"Output DB: {output_db}")

    manifest_before: list[dict[str, Any]] = []
    for name, path in inputs.items():
        exists = path.exists()
        add_check(
            checks,
            f"{name}_exists",
            exists,
            exists,
            True,
            str(path),
        )
        if exists:
            manifest_before.append(manifest_row(name, path, "before"))

    if any(not path.exists() for path in inputs.values()):
        write_csv(
            output_dir / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Required input database is missing.")
        return 1

    free_gib = shutil.disk_usage(root).free / (1024 ** 3)
    write_csv(
        output_dir / "disk_space.csv",
        [{"path": str(root), "free_gib": round(free_gib, 3)}],
        ["path", "free_gib"],
    )
    add_check(
        checks,
        "minimum_free_disk_space",
        free_gib >= 3.0,
        round(free_gib, 3),
        "at least 3.0 GiB",
    )

    if output_db.exists():
        output_db.unlink()

    con = duckdb.connect(str(output_db))
    try:
        con.execute("PRAGMA threads=4")
        con.execute("PRAGMA enable_progress_bar=false")
        con.execute(
            f"ATTACH '{sql_path(parsed_path)}' AS parsed_src (READ_ONLY)"
        )
        con.execute(
            f"ATTACH '{sql_path(validity_path)}' AS validity_src (READ_ONLY)"
        )
        con.execute(
            f"ATTACH '{sql_path(stint_path)}' AS stint_src (READ_ONLY)"
        )

        parsed_columns = {
            row[0]
            for row in con.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_catalog = 'parsed_src'
                  AND table_schema = 'main'
                  AND table_name = 'parsed_performances'
                """
            ).fetchall()
        }

        required = {
            "canonical_person_performance_id",
            "canonical_person_id",
            "canonical_gender_code",
            "season_type",
            "season_year",
            "season_id",
            "meet_id",
            "event_id",
            "canonical_event_code",
            "canonical_event_name",
            "mark_type",
            "performance_direction",
            "primary_parse_state",
            "primary_parsed_value",
            "normalized_unit",
            "d1_development_eligible",
            "school_stint_eligible",
            "canonical_school_id",
            "canonical_team_id",
        }
        missing = sorted(required - parsed_columns)
        add_check(
            checks,
            "required_parsed_metadata_present",
            not missing,
            ",".join(missing),
            "none missing",
        )
        if missing:
            write_csv(
                output_dir / "hard_checks.csv",
                checks,
                ["check_name", "status", "observed", "expected", "details"],
            )
            print(
                "PHASE GATE: FAIL — Missing parsed fields: "
                + ", ".join(missing)
            )
            return 1

        date_column = choose_column(
            parsed_columns,
            [
                "performance_date",
                "meet_date",
                "result_date",
                "date",
            ],
        )
        meet_name_column = choose_column(
            parsed_columns,
            ["meet_name", "competition_name"],
        )
        athlete_name_column = choose_column(
            parsed_columns,
            [
                "canonical_person_name",
                "athlete_name",
                "person_name",
                "name",
            ],
        )
        school_name_column = choose_column(
            parsed_columns,
            ["canonical_school_name", "school_name"],
        )

        parsed_count = con.execute(
            "SELECT COUNT(*) FROM parsed_src.main.parsed_performances"
        ).fetchone()[0]
        track_count = con.execute(
            """
            SELECT COUNT(*)
            FROM parsed_src.main.parsed_performances
            WHERE season_type IN ('indoor', 'outdoor')
            """
        ).fetchone()[0]
        xc_count = con.execute(
            """
            SELECT COUNT(*)
            FROM parsed_src.main.parsed_performances
            WHERE season_type = 'cross_country'
            """
        ).fetchone()[0]
        other_season_count = con.execute(
            """
            SELECT COUNT(*)
            FROM parsed_src.main.parsed_performances
            WHERE season_type IS NULL
               OR season_type NOT IN (
                    'indoor', 'outdoor', 'cross_country'
               )
            """
        ).fetchone()[0]

        add_check(
            checks,
            "parsed_source_row_count",
            parsed_count == EXPECTED_PARSED_ROWS,
            parsed_count,
            EXPECTED_PARSED_ROWS,
        )
        add_check(
            checks,
            "track_row_count",
            track_count == EXPECTED_TRACK_ROWS,
            track_count,
            EXPECTED_TRACK_ROWS,
        )
        add_check(
            checks,
            "cross_country_rows_explicitly_identified",
            xc_count == EXPECTED_XC_ROWS_IN_TRACK_REGISTRY,
            xc_count,
            EXPECTED_XC_ROWS_IN_TRACK_REGISTRY,
        )
        add_check(
            checks,
            "no_unknown_season_types",
            other_season_count == 0,
            other_season_count,
            0,
        )

        duplicate_map_rows = con.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT canonical_person_performance_id
                FROM stint_src.main.school_stint_performance_map
                GROUP BY 1
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
        add_check(
            checks,
            "school_stint_map_unique_by_performance",
            duplicate_map_rows == 0,
            duplicate_map_rows,
            0,
        )

        duplicate_stint_ids = con.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT school_stint_id
                FROM stint_src.main.analytical_school_stints
                GROUP BY 1
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
        add_check(
            checks,
            "analytical_school_stints_unique",
            duplicate_stint_ids == 0,
            duplicate_stint_ids,
            0,
        )

        date_select = optional_select(
            "p", date_column, "performance_date", "DATE"
        )
        meet_name_select = optional_select(
            "p", meet_name_column, "meet_name"
        )
        athlete_name_select = optional_select(
            "p", athlete_name_column, "athlete_name"
        )
        parsed_school_name_select = optional_select(
            "p", school_name_column, "parsed_school_name"
        )

        print("Creating track foundation...")

        con.execute(
            f"""
            CREATE TABLE main.track_performance_foundation AS
            SELECT
                '{FOUNDATION_VERSION}'::VARCHAR AS foundation_version,
                p.canonical_person_performance_id,
                p.canonical_person_id,
                {athlete_name_select},
                lower(p.canonical_gender_code)
                    AS canonical_gender_code,
                p.season_type,
                p.season_year,
                p.season_id,
                {date_select},
                p.meet_id,
                {meet_name_select},
                p.event_id,
                p.canonical_event_code,
                p.canonical_event_name,
                p.canonical_event_family,
                p.canonical_event_subfamily,
                p.mark_type,
                p.performance_direction,
                p.mark AS raw_mark,
                p.secondary_mark AS raw_secondary_mark,
                p.primary_parse_state,
                p.primary_status_code,
                p.primary_parser_class,
                p.primary_parsed_value,
                p.normalized_unit,
                v.validity_status,
                v.validity_reason,
                v.hard_validity_pass,
                v.distribution_flag,
                v.performance_tail_flag,
                v.valid_numeric_candidate,
                p.d1_development_eligible,
                p.school_stint_eligible,
                p.canonical_team_id AS parsed_team_id,
                p.canonical_school_id AS parsed_school_id,
                {parsed_school_name_select},
                sm.school_stint_id,
                sm.canonical_team_id AS stint_map_team_id,
                s.canonical_school_id AS stint_school_id,
                s.canonical_gender_code AS stint_gender_code,
                s.school_stint_version,
                s.stint_start_season_id,
                s.stint_end_season_id,

                coalesce(
                    s.canonical_school_id,
                    p.canonical_school_id
                ) AS resolved_school_id,

                coalesce(
                    sm.canonical_team_id,
                    p.canonical_team_id
                ) AS resolved_team_id,

                CASE
                    WHEN sm.school_stint_id IS NOT NULL
                        THEN 'school_stint_performance_map'
                    WHEN p.canonical_school_id IS NOT NULL
                        THEN 'parsed_performance_fallback'
                    ELSE 'unresolved'
                END AS school_resolution_method,

                CASE
                    WHEN lower(p.canonical_gender_code)
                        NOT IN ('m', 'f')
                        OR p.canonical_gender_code IS NULL
                        THEN 'exclude_missing_or_invalid_gender'
                    WHEN p.season_type NOT IN ('indoor', 'outdoor')
                        THEN 'exclude_non_track_season'
                    WHEN NOT coalesce(
                        p.d1_development_eligible,
                        FALSE
                    )
                        THEN 'exclude_not_d1_development_eligible'
                    WHEN NOT coalesce(p.school_stint_eligible, FALSE)
                        THEN 'exclude_not_school_stint_eligible'
                    WHEN NOT coalesce(
                        v.valid_numeric_candidate,
                        FALSE
                    )
                        THEN CASE
                            WHEN v.validity_status =
                                'not_numeric_status'
                                THEN 'exclude_non_numeric_status'
                            ELSE 'exclude_invalid_numeric_mark'
                        END
                    WHEN sm.school_stint_id IS NULL
                        THEN 'exclude_missing_school_stint_map'
                    WHEN s.school_stint_id IS NULL
                        THEN 'exclude_missing_analytical_school_stint'
                    WHEN s.canonical_school_id IS NULL
                        THEN 'exclude_missing_resolved_school'
                    WHEN lower(s.canonical_gender_code)
                        <> lower(p.canonical_gender_code)
                        THEN 'exclude_gender_conflict'
                    ELSE 'eligible'
                END AS scoring_eligibility_reason,

                CASE
                    WHEN lower(p.canonical_gender_code) IN ('m', 'f')
                     AND p.season_type IN ('indoor', 'outdoor')
                     AND coalesce(
                        p.d1_development_eligible,
                        FALSE
                     )
                     AND coalesce(p.school_stint_eligible, FALSE)
                     AND coalesce(
                        v.valid_numeric_candidate,
                        FALSE
                     )
                     AND sm.school_stint_id IS NOT NULL
                     AND s.school_stint_id IS NOT NULL
                     AND s.canonical_school_id IS NOT NULL
                     AND lower(s.canonical_gender_code)
                         = lower(p.canonical_gender_code)
                    THEN TRUE
                    ELSE FALSE
                END AS track_scoring_eligible

            FROM parsed_src.main.parsed_performances AS p
            JOIN validity_src.main.performance_validity AS v
              USING (canonical_person_performance_id)
            LEFT JOIN
                stint_src.main.school_stint_performance_map AS sm
              USING (canonical_person_performance_id)
            LEFT JOIN
                stint_src.main.analytical_school_stints AS s
              ON sm.school_stint_id = s.school_stint_id
            WHERE p.season_type IN ('indoor', 'outdoor')
            """
        )

        con.execute(
            """
            CREATE UNIQUE INDEX track_foundation_perf_uq
            ON main.track_performance_foundation(
                canonical_person_performance_id
            )
            """
        )
        con.execute(
            """
            CREATE INDEX track_foundation_scoring_idx
            ON main.track_performance_foundation(
                track_scoring_eligible,
                season_type,
                canonical_gender_code,
                canonical_event_code
            )
            """
        )
        con.execute(
            """
            CREATE INDEX track_foundation_person_stint_idx
            ON main.track_performance_foundation(
                canonical_person_id,
                school_stint_id,
                canonical_event_code,
                season_type
            )
            """
        )

        con.execute(
            """
            CREATE TABLE main.track_scoring_performances AS
            SELECT *
            FROM main.track_performance_foundation
            WHERE track_scoring_eligible
            """
        )

        con.execute(
            """
            CREATE TABLE main.track_exclusions AS
            SELECT *
            FROM main.track_performance_foundation
            WHERE NOT track_scoring_eligible
            """
        )

        con.execute(
            """
            CREATE TABLE main.track_foundation_summary AS
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                COUNT(*) AS total_rows,
                COUNT(*) FILTER (
                    WHERE track_scoring_eligible
                ) AS scoring_eligible_rows,
                COUNT(*) FILTER (
                    WHERE NOT track_scoring_eligible
                ) AS excluded_rows,
                COUNT(DISTINCT canonical_person_id)
                    FILTER (WHERE track_scoring_eligible)
                    AS scoring_eligible_people,
                COUNT(DISTINCT school_stint_id)
                    FILTER (WHERE track_scoring_eligible)
                    AS scoring_eligible_school_stints,
                COUNT(DISTINCT resolved_school_id)
                    FILTER (WHERE track_scoring_eligible)
                    AS scoring_eligible_schools
            FROM main.track_performance_foundation
            GROUP BY
                season_type,
                canonical_gender_code,
                canonical_event_code
            ORDER BY
                season_type,
                canonical_gender_code,
                canonical_event_code
            """
        )

        con.execute(
            """
            CREATE TABLE main.track_exclusion_summary AS
            SELECT
                scoring_eligibility_reason,
                season_type,
                canonical_gender_code,
                COUNT(*) AS row_count,
                COUNT(DISTINCT canonical_person_id)
                    AS person_count
            FROM main.track_performance_foundation
            WHERE NOT track_scoring_eligible
            GROUP BY
                scoring_eligibility_reason,
                season_type,
                canonical_gender_code
            ORDER BY
                row_count DESC,
                scoring_eligibility_reason
            """
        )

        overall = query_dicts(
            con,
            """
            SELECT
                COUNT(*) AS foundation_rows,
                COUNT(DISTINCT canonical_person_performance_id)
                    AS distinct_performance_ids,
                COUNT(*) FILTER (
                    WHERE track_scoring_eligible
                ) AS scoring_eligible_rows,
                COUNT(*) FILTER (
                    WHERE NOT track_scoring_eligible
                ) AS excluded_rows,
                COUNT(*) FILTER (
                    WHERE canonical_gender_code NOT IN ('m', 'f')
                       OR canonical_gender_code IS NULL
                ) AS invalid_gender_rows,
                COUNT(*) FILTER (
                    WHERE season_type NOT IN ('indoor', 'outdoor')
                ) AS non_track_rows,
                COUNT(*) FILTER (
                    WHERE track_scoring_eligible
                      AND school_stint_id IS NULL
                ) AS eligible_without_stint,
                COUNT(*) FILTER (
                    WHERE track_scoring_eligible
                      AND resolved_school_id IS NULL
                ) AS eligible_without_school,
                COUNT(*) FILTER (
                    WHERE track_scoring_eligible
                      AND NOT valid_numeric_candidate
                ) AS eligible_invalid_numeric,
                COUNT(*) FILTER (
                    WHERE track_scoring_eligible
                      AND NOT d1_development_eligible
                ) AS eligible_not_d1,
                COUNT(*) FILTER (
                    WHERE track_scoring_eligible
                      AND NOT school_stint_eligible
                ) AS eligible_not_stint_eligible,
                COUNT(*) FILTER (
                    WHERE track_scoring_eligible
                      AND lower(stint_gender_code)
                          <> lower(canonical_gender_code)
                ) AS eligible_gender_conflicts
            FROM main.track_performance_foundation
            """
        )[0]

        add_check(
            checks,
            "foundation_row_count",
            int(overall["foundation_rows"]) == EXPECTED_TRACK_ROWS,
            overall["foundation_rows"],
            EXPECTED_TRACK_ROWS,
        )
        add_check(
            checks,
            "foundation_performance_ids_unique",
            int(overall["distinct_performance_ids"])
            == int(overall["foundation_rows"]),
            (
                int(overall["foundation_rows"])
                - int(overall["distinct_performance_ids"])
            ),
            0,
        )
        add_check(
            checks,
            "all_track_rows_have_valid_gender",
            int(overall["invalid_gender_rows"]) == 0,
            overall["invalid_gender_rows"],
            0,
        )
        add_check(
            checks,
            "foundation_contains_track_seasons_only",
            int(overall["non_track_rows"]) == 0,
            overall["non_track_rows"],
            0,
        )
        add_check(
            checks,
            "eligible_rows_have_school_stint",
            int(overall["eligible_without_stint"]) == 0,
            overall["eligible_without_stint"],
            0,
        )
        add_check(
            checks,
            "eligible_rows_have_school",
            int(overall["eligible_without_school"]) == 0,
            overall["eligible_without_school"],
            0,
        )
        add_check(
            checks,
            "eligible_rows_are_valid_numeric",
            int(overall["eligible_invalid_numeric"]) == 0,
            overall["eligible_invalid_numeric"],
            0,
        )
        add_check(
            checks,
            "eligible_rows_are_d1",
            int(overall["eligible_not_d1"]) == 0,
            overall["eligible_not_d1"],
            0,
        )
        add_check(
            checks,
            "eligible_rows_are_school_stint_eligible",
            int(overall["eligible_not_stint_eligible"]) == 0,
            overall["eligible_not_stint_eligible"],
            0,
        )
        add_check(
            checks,
            "eligible_rows_have_no_gender_conflict",
            int(overall["eligible_gender_conflicts"]) == 0,
            overall["eligible_gender_conflicts"],
            0,
        )
        add_check(
            checks,
            "scoring_eligible_rows_exist",
            int(overall["scoring_eligible_rows"]) > 0,
            overall["scoring_eligible_rows"],
            "greater than 0",
        )

        season_gender_rows = query_dicts(
            con,
            """
            SELECT
                season_type,
                canonical_gender_code,
                COUNT(*) AS foundation_rows,
                COUNT(*) FILTER (
                    WHERE track_scoring_eligible
                ) AS scoring_eligible_rows,
                COUNT(*) FILTER (
                    WHERE NOT track_scoring_eligible
                ) AS excluded_rows,
                COUNT(DISTINCT canonical_person_id)
                    FILTER (WHERE track_scoring_eligible)
                    AS eligible_people,
                COUNT(DISTINCT resolved_school_id)
                    FILTER (WHERE track_scoring_eligible)
                    AS eligible_schools
            FROM main.track_performance_foundation
            GROUP BY
                season_type,
                canonical_gender_code
            ORDER BY
                season_type,
                canonical_gender_code
            """
        )

        export_csv(
            con,
            """
            SELECT *
            FROM main.track_foundation_summary
            ORDER BY
                season_type,
                canonical_gender_code,
                canonical_event_code
            """,
            output_dir / "track_foundation_summary.csv",
        )
        export_csv(
            con,
            """
            SELECT *
            FROM main.track_exclusion_summary
            ORDER BY
                row_count DESC,
                scoring_eligibility_reason
            """,
            output_dir / "track_exclusion_summary.csv",
        )
        write_csv(
            output_dir / "season_gender_summary.csv",
            season_gender_rows,
            list(season_gender_rows[0].keys()),
        )
        export_csv(
            con,
            """
            SELECT
                canonical_person_performance_id,
                canonical_person_id,
                canonical_gender_code,
                season_type,
                season_year,
                canonical_event_code,
                raw_mark,
                validity_status,
                d1_development_eligible,
                school_stint_eligible,
                school_stint_id,
                parsed_school_id,
                stint_school_id,
                scoring_eligibility_reason
            FROM main.track_exclusions
            ORDER BY
                scoring_eligibility_reason,
                season_type,
                canonical_gender_code,
                canonical_event_code
            LIMIT 1000
            """,
            output_dir / "track_exclusion_samples.csv",
        )

        manifest_after = [
            manifest_row(name, path, "after")
            for name, path in inputs.items()
        ]
        before_by_name = {
            row["input_name"]: row
            for row in manifest_before
        }
        for row in manifest_after:
            before = before_by_name[row["input_name"]]
            unchanged = (
                row["size_bytes"] == before["size_bytes"]
                and row["mtime_epoch_ns"] == before["mtime_epoch_ns"]
                and row["sha256"] == before["sha256"]
            )
            add_check(
                checks,
                f"{row['input_name']}_unchanged",
                unchanged,
                row["sha256"],
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
            row for row in checks
            if row["status"] == "FAIL"
        ]

        report_lines = [
            "MILESTONE 5 PHASE 2E-2 — TRACK PERFORMANCE FOUNDATION",
            "=" * 78,
            f"Finished UTC: {utc_now()}",
            f"Foundation version: {FOUNDATION_VERSION}",
            "",
            "SOURCE PARTITION",
            "-" * 78,
            f"All parsed rows: {parsed_count:,}",
            f"Indoor/outdoor track rows: {track_count:,}",
            f"Cross-country rows parked: {xc_count:,}",
            "",
            "TRACK FOUNDATION",
            "-" * 78,
            f"Foundation rows: {int(overall['foundation_rows']):,}",
            (
                "Scoring-eligible rows: "
                f"{int(overall['scoring_eligible_rows']):,}"
            ),
            f"Explicit exclusions: {int(overall['excluded_rows']):,}",
            "",
            "AUTHORITATIVE METADATA",
            "-" * 78,
            "gender: parsed canonical_gender_code",
            "season: parsed season_type and season_year",
            "meet: parsed meet_id",
            "school stint: final school_stint_performance_map",
            "school: analytical_school_stints.canonical_school_id",
            "",
            "SCORING ELIGIBILITY",
            "-" * 78,
            "valid numeric performance",
            "indoor or outdoor season",
            "canonical gender m/f",
            "D1 development eligible",
            "school-stint eligible",
            "mapped to a final analytical school stint",
            "school-stint gender agrees with performance gender",
            "",
            "CROSS-COUNTRY BOUNDARY",
            "-" * 78,
            "The 48 cross-country-season rows are excluded from track.",
            "XC remains parked for the separate distance-normalization branch.",
            "",
            "HARD CHECK SUMMARY",
            "-" * 78,
            f"PASS: {sum(row['status'] == 'PASS' for row in checks)}",
            f"FAIL: {len(failed)}",
            "",
            "PHASE GATE",
            "-" * 78,
            (
                "PASS — Track performance foundation is frozen for scoring."
                if not failed
                else "FAIL — Correct foundation coverage or join errors."
            ),
        ]
        (output_dir / "track_foundation_report.txt").write_text(
            "\n".join(report_lines) + "\n",
            encoding="utf-8",
        )

        print()
        print(f"Track foundation rows: {int(overall['foundation_rows']):,}")
        print(
            "Scoring-eligible rows: "
            f"{int(overall['scoring_eligible_rows']):,}"
        )
        print(f"Excluded rows: {int(overall['excluded_rows']):,}")
        print(f"Cross-country rows parked: {xc_count:,}")
        print()
        print("Created:")
        for filename in [
            "track_performance_foundation_v1.duckdb",
            "track_foundation_report.txt",
            "track_foundation_summary.csv",
            "track_exclusion_summary.csv",
            "season_gender_summary.csv",
            "track_exclusion_samples.csv",
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
        print("Next: build versioned collegiate-record anchors.")
        return 0

    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
