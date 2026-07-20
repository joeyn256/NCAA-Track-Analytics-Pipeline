#!/usr/bin/env python3
"""
Milestone 5 Phase 4H — Freeze Event-Specific Period Eligibility Policy

Freezes the reviewed Phase 4G threshold recommendations and applies them to
the Phase 4F athlete-event-period dataset without modifying either input.

Frozen policy
-------------
- 72 event combinations: require at least 3 distinct meets per period.
- 4 sparse-but-usable event combinations: require at least 2 distinct meets.
- 6 ultra-sparse event combinations: excluded from standalone event
  trajectories and preserved for later event-family pooling/supporting analysis.
- Single-meet periods are never eligible for primary development trajectories.

The output database retains every Phase 4F period row and adds explicit policy
and eligibility fields. It also creates the population that Phase 5A will use
to construct observed athlete-development trajectories.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


ROOT = Path.cwd()

PERIOD_DB = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4f_stable_athlete_event_period_levels/"
      "athlete_event_period_levels_v1.duckdb"
)

RECOMMENDATIONS_CSV = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4g_event_period_threshold_calibration/"
      "event_period_eligibility_policy_recommendations.csv"
)

PHASE_4G_CHECKS = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4g_event_period_threshold_calibration/"
      "hard_checks.csv"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4h_frozen_event_period_policy"
)

OUTPUT_DB = OUTPUT_DIR / "event_period_policy_v1.duckdb"

INPUT_DATASET_VERSION = "athlete_event_period_levels_v1_3"
CALIBRATION_VERSION = "event_period_threshold_calibration_v1"
POLICY_VERSION = "event_period_eligibility_policy_v1"

EXPECTED_EVENT_COMBINATIONS = 82
EXPECTED_STANDARD_EVENTS = 72
EXPECTED_EXCEPTION_EVENTS = 4
EXPECTED_SUPPORTING_EVENTS = 6

EXPECTED_EXCEPTION_KEYS = {
    ("outdoor", "m", "3000M"),
    ("outdoor", "f", "3000M"),
    ("indoor", "m", "600M"),
    ("indoor", "f", "600M"),
}

EXPECTED_SUPPORTING_KEYS = {
    ("indoor", "f", "1500M"),
    ("indoor", "m", "1500M"),
    ("outdoor", "f", "MILE"),
    ("outdoor", "m", "MILE"),
    ("indoor", "f", "300M"),
    ("indoor", "m", "300M"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
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
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def fetch_dicts(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
) -> list[dict[str, Any]]:
    result = connection.execute(sql)
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


def key_tuple(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["season_type"]),
        str(row["canonical_gender_code"]),
        str(row["canonical_event_code"]),
    )


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    inputs = [
        PERIOD_DB,
        RECOMMENDATIONS_CSV,
        PHASE_4G_CHECKS,
    ]

    print("MILESTONE 5 PHASE 4H — FREEZE EVENT PERIOD POLICY")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Policy version: {POLICY_VERSION}")
    print(f"Period database: {PERIOD_DB}")
    print(f"Recommendations: {RECOMMENDATIONS_CSV}")
    print(f"Output database: {OUTPUT_DB}")

    missing = [str(path) for path in inputs if not path.exists()]
    add_check(
        checks,
        "all_required_inputs_exist",
        not missing,
        missing,
        [],
    )

    if missing:
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Required input missing.")
        return 1

    input_hashes_before = {
        str(path): sha256_file(path)
        for path in inputs
    }

    phase_4g_checks = read_csv(PHASE_4G_CHECKS)
    failed_phase_4g_checks = [
        row
        for row in phase_4g_checks
        if row.get("status") != "PASS"
    ]

    add_check(
        checks,
        "phase_4g_gate_passed",
        not failed_phase_4g_checks,
        [row.get("check_name") for row in failed_phase_4g_checks],
        [],
    )

    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()

    con = duckdb.connect(str(OUTPUT_DB))

    try:
        con.execute("PRAGMA threads=4")
        con.execute("PRAGMA enable_progress_bar=false")

        con.execute(
            f"""
            ATTACH '{sql_path(PERIOD_DB)}'
                AS period_source (READ_ONLY)
            """
        )

        metadata = {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM period_source.main.dataset_metadata
                """
            ).fetchall()
        }

        add_check(
            checks,
            "input_dataset_version_matches",
            metadata.get("dataset_version")
            == INPUT_DATASET_VERSION,
            metadata.get("dataset_version"),
            INPUT_DATASET_VERSION,
        )

        con.execute(
            f"""
            CREATE TABLE frozen_event_period_policy AS
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                canonical_event_name,
                event_family,
                CAST(athlete_school_event_segments AS BIGINT)
                    AS calibration_segments,
                CAST(ready_segments_at_3 AS BIGINT)
                    AS ready_segments_at_3,
                CAST(ready_schools_at_3 AS BIGINT)
                    AS ready_schools_at_3,
                CAST(ready_segments_at_2 AS BIGINT)
                    AS ready_segments_at_2,
                CAST(ready_schools_at_2 AS BIGINT)
                    AS ready_schools_at_2,
                CASE
                    WHEN recommended_role =
                        'standard_three_meet_primary'
                        THEN 3
                    WHEN recommended_role =
                        'two_meet_exception_candidate'
                        THEN 2
                    ELSE NULL
                END AS standalone_min_distinct_meets,
                CASE
                    WHEN recommended_role =
                        'supporting_only_family_pooling_candidate'
                        THEN 2
                    ELSE NULL
                END AS family_pool_min_distinct_meets,
                CASE
                    WHEN recommended_role =
                        'standard_three_meet_primary'
                        THEN 'standalone_primary_standard'
                    WHEN recommended_role =
                        'two_meet_exception_candidate'
                        THEN 'standalone_primary_two_meet_exception'
                    ELSE 'family_pooling_supporting_only'
                END AS frozen_role,
                recommendation_reason,
                'approved' AS policy_status,
                '{POLICY_VERSION}' AS policy_version,
                '{CALIBRATION_VERSION}' AS calibration_version
            FROM read_csv_auto(
                '{sql_path(RECOMMENDATIONS_CSV)}',
                HEADER = TRUE,
                ALL_VARCHAR = TRUE
            )
            """
        )

        policy_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM frozen_event_period_policy
            ORDER BY
                season_type,
                canonical_gender_code,
                canonical_event_code
            """
        )

        standard_rows = [
            row for row in policy_rows
            if row["frozen_role"]
            == "standalone_primary_standard"
        ]
        exception_rows = [
            row for row in policy_rows
            if row["frozen_role"]
            == "standalone_primary_two_meet_exception"
        ]
        supporting_rows = [
            row for row in policy_rows
            if row["frozen_role"]
            == "family_pooling_supporting_only"
        ]

        exception_keys = {key_tuple(row) for row in exception_rows}
        supporting_keys = {key_tuple(row) for row in supporting_rows}

        add_check(
            checks,
            "policy_event_combination_count",
            len(policy_rows) == EXPECTED_EVENT_COMBINATIONS,
            len(policy_rows),
            EXPECTED_EVENT_COMBINATIONS,
        )
        add_check(
            checks,
            "standard_event_count",
            len(standard_rows) == EXPECTED_STANDARD_EVENTS,
            len(standard_rows),
            EXPECTED_STANDARD_EVENTS,
        )
        add_check(
            checks,
            "two_meet_exception_event_count",
            len(exception_rows) == EXPECTED_EXCEPTION_EVENTS,
            len(exception_rows),
            EXPECTED_EXCEPTION_EVENTS,
        )
        add_check(
            checks,
            "supporting_only_event_count",
            len(supporting_rows) == EXPECTED_SUPPORTING_EVENTS,
            len(supporting_rows),
            EXPECTED_SUPPORTING_EVENTS,
        )
        add_check(
            checks,
            "two_meet_exception_set_matches_review",
            exception_keys == EXPECTED_EXCEPTION_KEYS,
            sorted(exception_keys),
            sorted(EXPECTED_EXCEPTION_KEYS),
        )
        add_check(
            checks,
            "supporting_only_set_matches_review",
            supporting_keys == EXPECTED_SUPPORTING_KEYS,
            sorted(supporting_keys),
            sorted(EXPECTED_SUPPORTING_KEYS),
        )
        add_check(
            checks,
            "no_single_meet_standalone_policy",
            all(
                row["standalone_min_distinct_meets"]
                in (2, 3, None)
                for row in policy_rows
            ),
            [
                key_tuple(row)
                for row in policy_rows
                if row["standalone_min_distinct_meets"]
                not in (2, 3, None)
            ],
            [],
        )

        con.execute(
            """
            CREATE TABLE policy_applied_period_levels AS
            SELECT
                p.*,
                f.standalone_min_distinct_meets,
                f.family_pool_min_distinct_meets,
                f.frozen_role,
                f.policy_status AS event_policy_status,
                f.policy_version AS event_policy_version,
                CASE
                    WHEN f.standalone_min_distinct_meets IS NOT NULL
                     AND p.distinct_meet_count
                            >= f.standalone_min_distinct_meets
                        THEN TRUE
                    ELSE FALSE
                END AS standalone_primary_eligible,
                CASE
                    WHEN f.family_pool_min_distinct_meets IS NOT NULL
                     AND p.distinct_meet_count
                            >= f.family_pool_min_distinct_meets
                        THEN TRUE
                    ELSE FALSE
                END AS family_pool_supporting_eligible,
                CASE
                    WHEN f.frozen_role =
                        'standalone_primary_standard'
                     AND p.distinct_meet_count >= 3
                        THEN 'three_meet_primary'
                    WHEN f.frozen_role =
                        'standalone_primary_two_meet_exception'
                     AND p.distinct_meet_count >= 3
                        THEN 'three_plus_meets_under_exception_policy'
                    WHEN f.frozen_role =
                        'standalone_primary_two_meet_exception'
                     AND p.distinct_meet_count = 2
                        THEN 'two_meet_exception_primary'
                    WHEN f.frozen_role =
                        'family_pooling_supporting_only'
                     AND p.distinct_meet_count >= 2
                        THEN 'family_pool_supporting'
                    ELSE 'not_primary_eligible'
                END AS frozen_eligibility_path
            FROM
                period_source.main.athlete_event_period_levels p
            JOIN frozen_event_period_policy f
              USING (
                season_type,
                canonical_gender_code,
                canonical_event_code
              )
            """
        )

        con.execute(
            """
            CREATE VIEW standalone_primary_period_levels AS
            SELECT *
            FROM policy_applied_period_levels
            WHERE standalone_primary_eligible
            """
        )

        con.execute(
            """
            CREATE VIEW family_pool_supporting_period_levels AS
            SELECT *
            FROM policy_applied_period_levels
            WHERE family_pool_supporting_eligible
            """
        )

        con.execute(
            """
            CREATE TABLE standalone_trajectory_readiness AS
            SELECT
                canonical_person_id,
                ANY_VALUE(athlete_id) AS athlete_id,
                ANY_VALUE(athlete_name) AS athlete_name,
                school_stint_id,
                resolved_school_id,
                canonical_gender_code,
                season_type,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(event_family) AS event_family,
                ANY_VALUE(frozen_role) AS frozen_role,
                ANY_VALUE(standalone_min_distinct_meets)
                    AS standalone_min_distinct_meets,
                COUNT(*) AS total_period_count,
                COUNT(*) FILTER (
                    WHERE standalone_primary_eligible
                ) AS qualifying_period_count,
                MIN(season_year) FILTER (
                    WHERE standalone_primary_eligible
                ) AS first_qualifying_season_year,
                MAX(season_year) FILTER (
                    WHERE standalone_primary_eligible
                ) AS last_qualifying_season_year,
                COUNT(*) FILTER (
                    WHERE standalone_primary_eligible
                ) >= 2 AS trajectory_ready
            FROM policy_applied_period_levels
            GROUP BY
                canonical_person_id,
                school_stint_id,
                resolved_school_id,
                canonical_gender_code,
                season_type,
                canonical_event_code
            """
        )

        con.execute(
            """
            CREATE TABLE dataset_metadata AS
            SELECT
                'dataset_version' AS metadata_key,
                'event_period_policy_v1' AS metadata_value
            UNION ALL
            SELECT
                'input_period_dataset_version',
                'athlete_event_period_levels_v1_3'
            UNION ALL
            SELECT
                'event_period_policy_version',
                'event_period_eligibility_policy_v1'
            UNION ALL
            SELECT
                'standard_min_distinct_meets',
                '3'
            UNION ALL
            SELECT
                'exception_min_distinct_meets',
                '2'
            UNION ALL
            SELECT
                'single_meet_primary_allowed',
                'false'
            UNION ALL
            SELECT
                'created_at_utc',
                CURRENT_TIMESTAMP::VARCHAR
            """
        )

        source_period_count = con.execute(
            """
            SELECT COUNT(*)
            FROM period_source.main.athlete_event_period_levels
            """
        ).fetchone()[0]

        applied_counts = fetch_dicts(
            con,
            """
            SELECT
                COUNT(*) AS total_period_rows,
                COUNT(*) FILTER (
                    WHERE standalone_primary_eligible
                ) AS standalone_primary_period_rows,
                COUNT(*) FILTER (
                    WHERE frozen_eligibility_path =
                        'two_meet_exception_primary'
                ) AS two_meet_exception_period_rows,
                COUNT(*) FILTER (
                    WHERE family_pool_supporting_eligible
                ) AS family_pool_supporting_period_rows,
                COUNT(*) FILTER (
                    WHERE distinct_meet_count = 1
                      AND standalone_primary_eligible
                ) AS single_meet_primary_rows,
                COUNT(*) FILTER (
                    WHERE frozen_role =
                        'family_pooling_supporting_only'
                      AND standalone_primary_eligible
                ) AS supporting_role_standalone_rows,
                COUNT(DISTINCT canonical_person_id)
                    FILTER (
                        WHERE standalone_primary_eligible
                    ) AS standalone_primary_athletes,
                COUNT(DISTINCT resolved_school_id)
                    FILTER (
                        WHERE standalone_primary_eligible
                    ) AS standalone_primary_schools
            FROM policy_applied_period_levels
            """
        )[0]

        readiness_counts = fetch_dicts(
            con,
            """
            SELECT
                COUNT(*) AS total_segments,
                COUNT(*) FILTER (
                    WHERE trajectory_ready
                ) AS trajectory_ready_segments,
                COUNT(DISTINCT canonical_person_id)
                    FILTER (
                        WHERE trajectory_ready
                    ) AS trajectory_ready_athletes,
                COUNT(DISTINCT resolved_school_id)
                    FILTER (
                        WHERE trajectory_ready
                    ) AS trajectory_ready_schools
            FROM standalone_trajectory_readiness
            """
        )[0]

        expected_ready_from_policy = sum(
            int(
                row["ready_segments_at_3"]
                if row["standalone_min_distinct_meets"] == 3
                else row["ready_segments_at_2"]
            )
            for row in policy_rows
            if row["standalone_min_distinct_meets"] in (2, 3)
        )

        duplicate_grain = fetch_dicts(
            con,
            """
            SELECT
                athlete_event_period_id,
                COUNT(*) AS row_count
            FROM policy_applied_period_levels
            GROUP BY athlete_event_period_id
            HAVING COUNT(*) > 1
            LIMIT 100
            """
        )

        missing_policy_matches = con.execute(
            """
            SELECT COUNT(*)
            FROM policy_applied_period_levels
            WHERE frozen_role IS NULL
            """
        ).fetchone()[0]

        add_check(
            checks,
            "period_row_count_preserved",
            applied_counts["total_period_rows"]
            == source_period_count,
            applied_counts["total_period_rows"],
            source_period_count,
        )
        add_check(
            checks,
            "all_periods_match_policy",
            missing_policy_matches == 0,
            missing_policy_matches,
            0,
        )
        add_check(
            checks,
            "policy_applied_period_ids_unique",
            not duplicate_grain,
            len(duplicate_grain),
            0,
        )
        add_check(
            checks,
            "no_single_meet_primary_rows",
            applied_counts["single_meet_primary_rows"] == 0,
            applied_counts["single_meet_primary_rows"],
            0,
        )
        add_check(
            checks,
            "supporting_events_not_standalone_primary",
            applied_counts["supporting_role_standalone_rows"] == 0,
            applied_counts["supporting_role_standalone_rows"],
            0,
        )
        add_check(
            checks,
            "trajectory_ready_count_matches_calibration",
            readiness_counts["trajectory_ready_segments"]
            == expected_ready_from_policy,
            readiness_counts["trajectory_ready_segments"],
            expected_ready_from_policy,
        )
        add_check(
            checks,
            "standalone_primary_population_exists",
            applied_counts["standalone_primary_period_rows"] > 0,
            applied_counts["standalone_primary_period_rows"],
            "greater than 0",
        )
        add_check(
            checks,
            "trajectory_ready_population_exists",
            readiness_counts["trajectory_ready_segments"] > 0,
            readiness_counts["trajectory_ready_segments"],
            "greater than 0",
        )

        write_csv(
            OUTPUT_DIR / "frozen_event_period_policy.csv",
            policy_rows,
            list(policy_rows[0].keys()) if policy_rows else [],
        )

        role_summary = fetch_dicts(
            con,
            """
            SELECT
                frozen_role,
                COUNT(DISTINCT CONCAT_WS(
                    '|',
                    season_type,
                    canonical_gender_code,
                    canonical_event_code
                )) AS event_combinations,
                COUNT(*) AS total_period_rows,
                COUNT(*) FILTER (
                    WHERE standalone_primary_eligible
                ) AS standalone_primary_period_rows,
                COUNT(*) FILTER (
                    WHERE family_pool_supporting_eligible
                ) AS family_pool_supporting_period_rows,
                COUNT(DISTINCT canonical_person_id)
                    FILTER (
                        WHERE standalone_primary_eligible
                    ) AS standalone_primary_athletes,
                COUNT(DISTINCT resolved_school_id)
                    FILTER (
                        WHERE standalone_primary_eligible
                    ) AS standalone_primary_schools
            FROM policy_applied_period_levels
            GROUP BY frozen_role
            ORDER BY frozen_role
            """
        )

        write_csv(
            OUTPUT_DIR / "policy_role_summary.csv",
            role_summary,
            [
                "frozen_role",
                "event_combinations",
                "total_period_rows",
                "standalone_primary_period_rows",
                "family_pool_supporting_period_rows",
                "standalone_primary_athletes",
                "standalone_primary_schools",
            ],
        )

        readiness_by_event = fetch_dicts(
            con,
            """
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(event_family) AS event_family,
                ANY_VALUE(frozen_role) AS frozen_role,
                ANY_VALUE(standalone_min_distinct_meets)
                    AS standalone_min_distinct_meets,
                COUNT(*) AS athlete_school_event_segments,
                COUNT(*) FILTER (
                    WHERE trajectory_ready
                ) AS trajectory_ready_segments,
                COUNT(DISTINCT canonical_person_id)
                    FILTER (
                        WHERE trajectory_ready
                    ) AS trajectory_ready_athletes,
                COUNT(DISTINCT resolved_school_id)
                    FILTER (
                        WHERE trajectory_ready
                    ) AS trajectory_ready_schools
            FROM standalone_trajectory_readiness
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

        write_csv(
            OUTPUT_DIR / "frozen_trajectory_readiness_by_event.csv",
            readiness_by_event,
            [
                "season_type",
                "canonical_gender_code",
                "canonical_event_code",
                "canonical_event_name",
                "event_family",
                "frozen_role",
                "standalone_min_distinct_meets",
                "athlete_school_event_segments",
                "trajectory_ready_segments",
                "trajectory_ready_athletes",
                "trajectory_ready_schools",
            ],
        )

        exception_impact = fetch_dicts(
            con,
            """
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                COUNT(*) AS total_period_rows,
                COUNT(*) FILTER (
                    WHERE distinct_meet_count >= 3
                ) AS three_meet_period_rows,
                COUNT(*) FILTER (
                    WHERE distinct_meet_count = 2
                ) AS added_two_meet_period_rows,
                COUNT(*) FILTER (
                    WHERE standalone_primary_eligible
                ) AS frozen_primary_period_rows
            FROM policy_applied_period_levels
            WHERE frozen_role =
                'standalone_primary_two_meet_exception'
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

        write_csv(
            OUTPUT_DIR / "two_meet_exception_impact.csv",
            exception_impact,
            [
                "season_type",
                "canonical_gender_code",
                "canonical_event_code",
                "canonical_event_name",
                "total_period_rows",
                "three_meet_period_rows",
                "added_two_meet_period_rows",
                "frozen_primary_period_rows",
            ],
        )

        summary_rows = [
            {
                "metric": "event_combinations",
                "value": len(policy_rows),
            },
            {
                "metric": "standard_three_meet_events",
                "value": len(standard_rows),
            },
            {
                "metric": "two_meet_exception_events",
                "value": len(exception_rows),
            },
            {
                "metric": "supporting_only_events",
                "value": len(supporting_rows),
            },
            {
                "metric": "source_period_rows",
                "value": source_period_count,
            },
            {
                "metric": "standalone_primary_period_rows",
                "value":
                    applied_counts["standalone_primary_period_rows"],
            },
            {
                "metric": "added_two_meet_exception_period_rows",
                "value":
                    applied_counts["two_meet_exception_period_rows"],
            },
            {
                "metric": "family_pool_supporting_period_rows",
                "value":
                    applied_counts["family_pool_supporting_period_rows"],
            },
            {
                "metric": "standalone_primary_athletes",
                "value":
                    applied_counts["standalone_primary_athletes"],
            },
            {
                "metric": "standalone_primary_schools",
                "value":
                    applied_counts["standalone_primary_schools"],
            },
            {
                "metric": "trajectory_ready_segments",
                "value":
                    readiness_counts["trajectory_ready_segments"],
            },
            {
                "metric": "trajectory_ready_athletes",
                "value":
                    readiness_counts["trajectory_ready_athletes"],
            },
            {
                "metric": "trajectory_ready_schools",
                "value":
                    readiness_counts["trajectory_ready_schools"],
            },
        ]

        write_csv(
            OUTPUT_DIR / "phase_4h_summary.csv",
            summary_rows,
            ["metric", "value"],
        )

    finally:
        con.close()

    input_hashes_after = {
        str(path): sha256_file(path)
        for path in inputs
    }

    add_check(
        checks,
        "all_inputs_unchanged",
        input_hashes_before == input_hashes_after,
        input_hashes_after,
        input_hashes_before,
    )

    output_hash = sha256_file(OUTPUT_DB)

    write_csv(
        OUTPUT_DIR / "input_manifest.csv",
        [
            {
                "input_name": path.name,
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256_before": input_hashes_before[str(path)],
                "sha256_after": input_hashes_after[str(path)],
            }
            for path in inputs
        ],
        [
            "input_name",
            "path",
            "size_bytes",
            "sha256_before",
            "sha256_after",
        ],
    )

    write_csv(
        OUTPUT_DIR / "output_manifest.csv",
        [
            {
                "output_name": OUTPUT_DB.name,
                "path": str(OUTPUT_DB),
                "size_bytes": OUTPUT_DB.stat().st_size,
                "sha256": output_hash,
                "policy_version": POLICY_VERSION,
                "input_dataset_version": INPUT_DATASET_VERSION,
            }
        ],
        [
            "output_name",
            "path",
            "size_bytes",
            "sha256",
            "policy_version",
            "input_dataset_version",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 5 PHASE 4H — FROZEN EVENT PERIOD POLICY",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Policy version: {POLICY_VERSION}",
        "",
        "FROZEN POLICY",
        "-" * 78,
        f"Standard three-meet event combinations: "
        f"{len(standard_rows)}",
        f"Two-meet exception event combinations: "
        f"{len(exception_rows)}",
        f"Family-pooling/supporting-only combinations: "
        f"{len(supporting_rows)}",
        "Single-meet periods are never primary eligible.",
        "",
        "TWO-MEET EXCEPTIONS",
        "-" * 78,
        "Outdoor men's 3000m",
        "Outdoor women's 3000m",
        "Indoor men's 600m",
        "Indoor women's 600m",
        "",
        "SUPPORTING/FAMILY-POOLING ONLY",
        "-" * 78,
        "Indoor men's and women's 1500m",
        "Outdoor men's and women's mile",
        "Indoor men's and women's 300m",
        "",
        "RESULTS",
        "-" * 78,
        f"Source period rows preserved: "
        f"{int(source_period_count):,}",
        f"Standalone-primary period rows: "
        f"{int(applied_counts['standalone_primary_period_rows']):,}",
        f"Added two-meet exception period rows: "
        f"{int(applied_counts['two_meet_exception_period_rows']):,}",
        f"Family-pool supporting period rows: "
        f"{int(applied_counts['family_pool_supporting_period_rows']):,}",
        f"Trajectory-ready segments: "
        f"{int(readiness_counts['trajectory_ready_segments']):,}",
        f"Trajectory-ready athletes: "
        f"{int(readiness_counts['trajectory_ready_athletes']):,}",
        f"Trajectory-ready schools: "
        f"{int(readiness_counts['trajectory_ready_schools']):,}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Event-specific period eligibility policy frozen."
            if not failed
            else "FAIL — Do not construct observed trajectories."
        ),
        "",
        "NEXT",
        "-" * 78,
        "Construct first-to-last observed development trajectories.",
        "Keep supporting-only events out of standalone event trajectories.",
    ]

    (OUTPUT_DIR / "phase_4h_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        "Standard three-meet events: "
        f"{len(standard_rows)}"
    )
    print(
        "Two-meet exception events: "
        f"{len(exception_rows)}"
    )
    print(
        "Supporting-only events: "
        f"{len(supporting_rows)}"
    )
    print(
        "Standalone-primary period rows: "
        f"{int(applied_counts['standalone_primary_period_rows']):,}"
    )
    print(
        "Trajectory-ready segments: "
        f"{int(readiness_counts['trajectory_ready_segments']):,}"
    )
    print(f"Output database: {OUTPUT_DB}")
    print()

    if failed:
        print("PHASE GATE: FAIL")
        for row in failed:
            print(
                f"  {row['check_name']}: "
                f"observed={row['observed']} "
                f"expected={row['expected']}"
            )
        return 1

    print("PHASE GATE: PASS")
    print("Next: build observed athlete-development trajectories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
