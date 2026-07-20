#!/usr/bin/env python3
"""
Milestone 5 Phase 4G — Calibrate Period Eligibility by Event Frequency

Purpose
-------
Evaluate whether the default requirement of three distinct meets per
athlete-event-season period is appropriate for every official event.

The Phase 4F coverage audit showed that a universal three-meet rule produces
excellent reliability for common events but nearly eliminates trajectories
for several rarely contested events. This phase compares one-, two-, and
three-meet period thresholds and produces a reviewable event-specific policy
recommendation.

Policy principles
-----------------
- Three distinct meets remains the default.
- Two distinct meets may be recommended only for sparse events when it
  restores a minimally usable standalone trajectory population.
- A single-meet period is never recommended for primary trajectory scoring.
- Events that remain too sparse at two meets are preserved for later
  event-family pooling or supporting analysis rather than forced into a
  standalone ranking.

This phase recommends policy; it does not yet construct development
trajectories or modify the Phase 4F database.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


ROOT = Path.cwd()

INPUT_DB = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4f_stable_athlete_event_period_levels/"
      "athlete_event_period_levels_v1.duckdb"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4g_event_period_threshold_calibration"
)

INPUT_DATASET_VERSION = "athlete_event_period_levels_v1_3"
CALIBRATION_VERSION = "event_period_threshold_calibration_v1"
EXPECTED_EVENT_COMBINATIONS = 82

DEFAULT_MIN_DISTINCT_MEETS = 3
EXCEPTION_MIN_DISTINCT_MEETS = 2

# A standalone event trajectory population should contain enough independent
# athlete-school-event segments and enough schools to avoid a handful of
# programs determining the result.
MIN_READY_SEGMENTS_FOR_STANDALONE = 100
MIN_READY_SCHOOLS_FOR_STANDALONE = 25


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


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 4G — EVENT PERIOD THRESHOLD CALIBRATION")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Calibration version: {CALIBRATION_VERSION}")
    print(f"Input database: {INPUT_DB}")
    print(f"Output directory: {OUTPUT_DIR}")

    add_check(
        checks,
        "input_database_exists",
        INPUT_DB.exists(),
        INPUT_DB.exists(),
        True,
    )

    if not INPUT_DB.exists():
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Input database missing.")
        return 1

    input_hash_before = sha256_file(INPUT_DB)

    con = duckdb.connect(":memory:")

    try:
        con.execute(
            f"""
            ATTACH '{sql_path(INPUT_DB)}'
                AS period_levels (READ_ONLY)
            """
        )

        metadata = {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM period_levels.main.dataset_metadata
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

        event_count = con.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT
                    season_type,
                    canonical_gender_code,
                    canonical_event_code
                FROM period_levels.main.athlete_event_period_levels
            )
            """
        ).fetchone()[0]

        add_check(
            checks,
            "official_event_combination_count",
            event_count == EXPECTED_EVENT_COMBINATIONS,
            event_count,
            EXPECTED_EVENT_COMBINATIONS,
        )

        con.execute(
            """
            CREATE TABLE threshold_scenarios AS
            WITH thresholds(min_distinct_meets) AS (
                VALUES (1), (2), (3)
            ),
            segment_thresholds AS (
                SELECT
                    t.min_distinct_meets,
                    p.season_type,
                    p.canonical_gender_code,
                    p.canonical_event_code,
                    ANY_VALUE(p.canonical_event_name)
                        AS canonical_event_name,
                    ANY_VALUE(p.event_family)
                        AS event_family,
                    p.canonical_person_id,
                    p.school_stint_id,
                    p.resolved_school_id,
                    COUNT(*) AS total_period_count,
                    COUNT(*) FILTER (
                        WHERE p.distinct_meet_count
                            >= t.min_distinct_meets
                    ) AS qualifying_period_count
                FROM
                    period_levels.main.athlete_event_period_levels p
                CROSS JOIN thresholds t
                GROUP BY
                    t.min_distinct_meets,
                    p.season_type,
                    p.canonical_gender_code,
                    p.canonical_event_code,
                    p.canonical_person_id,
                    p.school_stint_id,
                    p.resolved_school_id
            )
            SELECT
                min_distinct_meets,
                season_type,
                canonical_gender_code,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(event_family) AS event_family,
                COUNT(*) AS athlete_school_event_segments,
                COUNT(*) FILTER (
                    WHERE qualifying_period_count >= 1
                ) AS segments_with_one_qualifying_period,
                COUNT(*) FILTER (
                    WHERE qualifying_period_count >= 2
                ) AS trajectory_ready_segments,
                COUNT(DISTINCT canonical_person_id) FILTER (
                    WHERE qualifying_period_count >= 2
                ) AS trajectory_ready_athletes,
                COUNT(DISTINCT resolved_school_id) FILTER (
                    WHERE qualifying_period_count >= 2
                ) AS trajectory_ready_schools,
                AVG(qualifying_period_count)
                    AS mean_qualifying_period_count,
                MEDIAN(qualifying_period_count)
                    AS median_qualifying_period_count,
                COUNT(*) FILTER (
                    WHERE qualifying_period_count >= 2
                )::DOUBLE
                / NULLIF(COUNT(*), 0)
                    AS trajectory_ready_rate
            FROM segment_thresholds
            GROUP BY
                min_distinct_meets,
                season_type,
                canonical_gender_code,
                canonical_event_code
            ORDER BY
                season_type,
                canonical_gender_code,
                canonical_event_code,
                min_distinct_meets
            """
        )

        scenarios = fetch_dicts(
            con,
            """
            SELECT *
            FROM threshold_scenarios
            ORDER BY
                season_type,
                canonical_gender_code,
                canonical_event_code,
                min_distinct_meets
            """
        )

        write_csv(
            OUTPUT_DIR / "event_period_threshold_scenarios.csv",
            scenarios,
            [
                "min_distinct_meets",
                "season_type",
                "canonical_gender_code",
                "canonical_event_code",
                "canonical_event_name",
                "event_family",
                "athlete_school_event_segments",
                "segments_with_one_qualifying_period",
                "trajectory_ready_segments",
                "trajectory_ready_athletes",
                "trajectory_ready_schools",
                "mean_qualifying_period_count",
                "median_qualifying_period_count",
                "trajectory_ready_rate",
            ],
        )

        con.execute(
            f"""
            CREATE TABLE policy_recommendations AS
            WITH pivoted AS (
                SELECT
                    season_type,
                    canonical_gender_code,
                    canonical_event_code,
                    ANY_VALUE(canonical_event_name)
                        AS canonical_event_name,
                    ANY_VALUE(event_family)
                        AS event_family,
                    MAX(athlete_school_event_segments)
                        AS athlete_school_event_segments,

                    MAX(
                        CASE WHEN min_distinct_meets = 3
                        THEN trajectory_ready_segments END
                    ) AS ready_segments_at_3,
                    MAX(
                        CASE WHEN min_distinct_meets = 3
                        THEN trajectory_ready_athletes END
                    ) AS ready_athletes_at_3,
                    MAX(
                        CASE WHEN min_distinct_meets = 3
                        THEN trajectory_ready_schools END
                    ) AS ready_schools_at_3,
                    MAX(
                        CASE WHEN min_distinct_meets = 3
                        THEN trajectory_ready_rate END
                    ) AS ready_rate_at_3,

                    MAX(
                        CASE WHEN min_distinct_meets = 2
                        THEN trajectory_ready_segments END
                    ) AS ready_segments_at_2,
                    MAX(
                        CASE WHEN min_distinct_meets = 2
                        THEN trajectory_ready_athletes END
                    ) AS ready_athletes_at_2,
                    MAX(
                        CASE WHEN min_distinct_meets = 2
                        THEN trajectory_ready_schools END
                    ) AS ready_schools_at_2,
                    MAX(
                        CASE WHEN min_distinct_meets = 2
                        THEN trajectory_ready_rate END
                    ) AS ready_rate_at_2,

                    MAX(
                        CASE WHEN min_distinct_meets = 1
                        THEN trajectory_ready_segments END
                    ) AS ready_segments_at_1,
                    MAX(
                        CASE WHEN min_distinct_meets = 1
                        THEN trajectory_ready_schools END
                    ) AS ready_schools_at_1
                FROM threshold_scenarios
                GROUP BY
                    season_type,
                    canonical_gender_code,
                    canonical_event_code
            )
            SELECT
                *,
                ready_segments_at_2 - ready_segments_at_3
                    AS incremental_ready_segments_2_vs_3,
                ready_schools_at_2 - ready_schools_at_3
                    AS incremental_ready_schools_2_vs_3,

                CASE
                    WHEN ready_segments_at_3
                            >= {MIN_READY_SEGMENTS_FOR_STANDALONE}
                     AND ready_schools_at_3
                            >= {MIN_READY_SCHOOLS_FOR_STANDALONE}
                        THEN 3
                    WHEN ready_segments_at_2
                            >= {MIN_READY_SEGMENTS_FOR_STANDALONE}
                     AND ready_schools_at_2
                            >= {MIN_READY_SCHOOLS_FOR_STANDALONE}
                        THEN 2
                    ELSE NULL
                END AS recommended_min_distinct_meets,

                CASE
                    WHEN ready_segments_at_3
                            >= {MIN_READY_SEGMENTS_FOR_STANDALONE}
                     AND ready_schools_at_3
                            >= {MIN_READY_SCHOOLS_FOR_STANDALONE}
                        THEN 'standard_three_meet_primary'
                    WHEN ready_segments_at_2
                            >= {MIN_READY_SEGMENTS_FOR_STANDALONE}
                     AND ready_schools_at_2
                            >= {MIN_READY_SCHOOLS_FOR_STANDALONE}
                        THEN 'two_meet_exception_candidate'
                    ELSE 'supporting_only_family_pooling_candidate'
                END AS recommended_role,

                CASE
                    WHEN ready_segments_at_3
                            >= {MIN_READY_SEGMENTS_FOR_STANDALONE}
                     AND ready_schools_at_3
                            >= {MIN_READY_SCHOOLS_FOR_STANDALONE}
                        THEN
                            'Three-meet periods retain at least '
                            || '{MIN_READY_SEGMENTS_FOR_STANDALONE}'
                            || ' trajectories across at least '
                            || '{MIN_READY_SCHOOLS_FOR_STANDALONE}'
                            || ' schools.'
                    WHEN ready_segments_at_2
                            >= {MIN_READY_SEGMENTS_FOR_STANDALONE}
                     AND ready_schools_at_2
                            >= {MIN_READY_SCHOOLS_FOR_STANDALONE}
                        THEN
                            'Three-meet coverage is too sparse; '
                            || 'two-meet periods restore a minimally '
                            || 'usable standalone population.'
                    ELSE
                        'Even two-meet periods do not produce a '
                        || 'minimally broad standalone population; '
                        || 'preserve for event-family pooling or '
                        || 'supporting analysis.'
                END AS recommendation_reason,

                'review_required_not_frozen'
                    AS recommendation_status,
                '{CALIBRATION_VERSION}'
                    AS calibration_version
            FROM pivoted
            ORDER BY
                season_type,
                canonical_gender_code,
                canonical_event_code
            """
        )

        recommendations = fetch_dicts(
            con,
            """
            SELECT *
            FROM policy_recommendations
            ORDER BY
                CASE recommended_role
                    WHEN 'supporting_only_family_pooling_candidate'
                        THEN 1
                    WHEN 'two_meet_exception_candidate'
                        THEN 2
                    ELSE 3
                END,
                ready_segments_at_3,
                season_type,
                canonical_gender_code,
                canonical_event_code
            """
        )

        recommendation_fields = [
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "canonical_event_name",
            "event_family",
            "athlete_school_event_segments",
            "ready_segments_at_3",
            "ready_athletes_at_3",
            "ready_schools_at_3",
            "ready_rate_at_3",
            "ready_segments_at_2",
            "ready_athletes_at_2",
            "ready_schools_at_2",
            "ready_rate_at_2",
            "ready_segments_at_1",
            "ready_schools_at_1",
            "incremental_ready_segments_2_vs_3",
            "incremental_ready_schools_2_vs_3",
            "recommended_min_distinct_meets",
            "recommended_role",
            "recommendation_reason",
            "recommendation_status",
            "calibration_version",
        ]

        write_csv(
            OUTPUT_DIR
            / "event_period_eligibility_policy_recommendations.csv",
            recommendations,
            recommendation_fields,
        )

        exception_rows = [
            row
            for row in recommendations
            if row["recommended_role"]
            == "two_meet_exception_candidate"
        ]
        supporting_rows = [
            row
            for row in recommendations
            if row["recommended_role"]
            == "supporting_only_family_pooling_candidate"
        ]
        standard_rows = [
            row
            for row in recommendations
            if row["recommended_role"]
            == "standard_three_meet_primary"
        ]

        write_csv(
            OUTPUT_DIR / "two_meet_exception_candidates.csv",
            exception_rows,
            recommendation_fields,
        )
        write_csv(
            OUTPUT_DIR / "supporting_only_candidates.csv",
            supporting_rows,
            recommendation_fields,
        )

        scenario_count = len(scenarios)

        monotonic_issues = fetch_dicts(
            con,
            """
            WITH p AS (
                SELECT
                    season_type,
                    canonical_gender_code,
                    canonical_event_code,
                    MAX(CASE WHEN min_distinct_meets = 1
                        THEN trajectory_ready_segments END)
                        AS ready_1,
                    MAX(CASE WHEN min_distinct_meets = 2
                        THEN trajectory_ready_segments END)
                        AS ready_2,
                    MAX(CASE WHEN min_distinct_meets = 3
                        THEN trajectory_ready_segments END)
                        AS ready_3,
                    MAX(CASE WHEN min_distinct_meets = 1
                        THEN trajectory_ready_schools END)
                        AS schools_1,
                    MAX(CASE WHEN min_distinct_meets = 2
                        THEN trajectory_ready_schools END)
                        AS schools_2,
                    MAX(CASE WHEN min_distinct_meets = 3
                        THEN trajectory_ready_schools END)
                        AS schools_3
                FROM threshold_scenarios
                GROUP BY
                    season_type,
                    canonical_gender_code,
                    canonical_event_code
            )
            SELECT *
            FROM p
            WHERE NOT (
                ready_1 >= ready_2
                AND ready_2 >= ready_3
                AND schools_1 >= schools_2
                AND schools_2 >= schools_3
            )
            """
        )

        add_check(
            checks,
            "threshold_scenario_row_count",
            scenario_count
            == EXPECTED_EVENT_COMBINATIONS * 3,
            scenario_count,
            EXPECTED_EVENT_COMBINATIONS * 3,
        )
        add_check(
            checks,
            "recommendation_row_count",
            len(recommendations)
            == EXPECTED_EVENT_COMBINATIONS,
            len(recommendations),
            EXPECTED_EVENT_COMBINATIONS,
        )
        add_check(
            checks,
            "threshold_monotonicity",
            not monotonic_issues,
            len(monotonic_issues),
            0,
        )
        add_check(
            checks,
            "no_single_meet_primary_recommendations",
            all(
                row["recommended_min_distinct_meets"]
                not in (1, "1")
                for row in recommendations
            ),
            sum(
                row["recommended_min_distinct_meets"]
                in (1, "1")
                for row in recommendations
            ),
            0,
        )
        add_check(
            checks,
            "all_recommendations_have_valid_role",
            all(
                row["recommended_role"] in {
                    "standard_three_meet_primary",
                    "two_meet_exception_candidate",
                    "supporting_only_family_pooling_candidate",
                }
                for row in recommendations
            ),
            sum(
                row["recommended_role"] not in {
                    "standard_three_meet_primary",
                    "two_meet_exception_candidate",
                    "supporting_only_family_pooling_candidate",
                }
                for row in recommendations
            ),
            0,
        )
        add_check(
            checks,
            "standard_primary_population_exists",
            len(standard_rows) > 0,
            len(standard_rows),
            "greater than 0",
        )
        add_check(
            checks,
            "all_two_meet_exceptions_meet_population_floor",
            all(
                int(row["ready_segments_at_2"])
                >= MIN_READY_SEGMENTS_FOR_STANDALONE
                and int(row["ready_schools_at_2"])
                >= MIN_READY_SCHOOLS_FOR_STANDALONE
                for row in exception_rows
            ),
            sum(
                int(row["ready_segments_at_2"])
                < MIN_READY_SEGMENTS_FOR_STANDALONE
                or int(row["ready_schools_at_2"])
                < MIN_READY_SCHOOLS_FOR_STANDALONE
                for row in exception_rows
            ),
            0,
        )
        add_check(
            checks,
            "supporting_only_rows_fail_two_meet_floor",
            all(
                int(row["ready_segments_at_2"])
                < MIN_READY_SEGMENTS_FOR_STANDALONE
                or int(row["ready_schools_at_2"])
                < MIN_READY_SCHOOLS_FOR_STANDALONE
                for row in supporting_rows
            ),
            sum(
                int(row["ready_segments_at_2"])
                >= MIN_READY_SEGMENTS_FOR_STANDALONE
                and int(row["ready_schools_at_2"])
                >= MIN_READY_SCHOOLS_FOR_STANDALONE
                for row in supporting_rows
            ),
            0,
        )

        summary_rows = [
            {
                "metric": "event_combinations",
                "value": len(recommendations),
            },
            {
                "metric": "standard_three_meet_primary_events",
                "value": len(standard_rows),
            },
            {
                "metric": "two_meet_exception_candidates",
                "value": len(exception_rows),
            },
            {
                "metric": "supporting_only_candidates",
                "value": len(supporting_rows),
            },
            {
                "metric": "minimum_ready_segments_for_standalone",
                "value": MIN_READY_SEGMENTS_FOR_STANDALONE,
            },
            {
                "metric": "minimum_ready_schools_for_standalone",
                "value": MIN_READY_SCHOOLS_FOR_STANDALONE,
            },
            {
                "metric": "single_meet_primary_allowed",
                "value": False,
            },
        ]

        write_csv(
            OUTPUT_DIR / "phase_4g_summary.csv",
            summary_rows,
            ["metric", "value"],
        )

    finally:
        con.close()

    input_hash_after = sha256_file(INPUT_DB)

    add_check(
        checks,
        "input_database_unchanged",
        input_hash_before == input_hash_after,
        input_hash_after,
        input_hash_before,
    )

    write_csv(
        OUTPUT_DIR / "input_manifest.csv",
        [
            {
                "input_name": INPUT_DB.name,
                "path": str(INPUT_DB),
                "size_bytes": INPUT_DB.stat().st_size,
                "sha256_before": input_hash_before,
                "sha256_after": input_hash_after,
                "input_dataset_version": INPUT_DATASET_VERSION,
                "calibration_version": CALIBRATION_VERSION,
            }
        ],
        [
            "input_name",
            "path",
            "size_bytes",
            "sha256_before",
            "sha256_after",
            "input_dataset_version",
            "calibration_version",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 5 PHASE 4G — EVENT PERIOD THRESHOLD CALIBRATION",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Calibration version: {CALIBRATION_VERSION}",
        "",
        "POLICY PRINCIPLES",
        "-" * 78,
        "Three distinct meets remains the default period threshold.",
        "Two-meet exceptions are considered only for sparse events.",
        "Single-meet periods are never recommended for primary trajectories.",
        "Events still sparse at two meets remain available for later",
        "event-family pooling or supporting analysis.",
        "",
        "POPULATION FLOORS",
        "-" * 78,
        f"Minimum trajectory-ready segments: "
        f"{MIN_READY_SEGMENTS_FOR_STANDALONE}",
        f"Minimum trajectory-ready schools: "
        f"{MIN_READY_SCHOOLS_FOR_STANDALONE}",
        "",
        "RECOMMENDATIONS",
        "-" * 78,
        f"Standard three-meet primary events: {len(standard_rows)}",
        f"Two-meet exception candidates: {len(exception_rows)}",
        f"Supporting-only/family-pooling candidates: "
        f"{len(supporting_rows)}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Threshold scenarios and reviewable recommendations "
            "created."
            if not failed
            else "FAIL — Do not freeze event-specific thresholds."
        ),
        "",
        "NEXT",
        "-" * 78,
        "Review the exception and supporting-only candidate files.",
        "Then freeze the event-specific period eligibility policy.",
    ]

    (OUTPUT_DIR / "phase_4g_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Event combinations evaluated: {len(recommendations)}"
    )
    print(
        "Standard three-meet primary events: "
        f"{len(standard_rows)}"
    )
    print(
        "Two-meet exception candidates: "
        f"{len(exception_rows)}"
    )
    print(
        "Supporting-only candidates: "
        f"{len(supporting_rows)}"
    )
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
    print("Next: review and freeze event-specific period thresholds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
