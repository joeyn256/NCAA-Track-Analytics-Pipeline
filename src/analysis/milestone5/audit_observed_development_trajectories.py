#!/usr/bin/env python3
"""
Milestone 5 Phase 5B — Trajectory Plausibility and Modeling-Cohort Audit

Audits the Phase 5A observed-development trajectories before expected-
improvement modeling.

This phase does not alter observed improvement and does not silently remove
extreme athlete results. It:

1. Verifies that the Phase 5A gate passed.
2. Separates ordinary 1–5 season trajectories from 6+ season duration reviews.
3. Flags event-specific extreme improvement, decline, annualized-change, and
   baseline-level tails for sensitivity analysis.
4. Profiles baseline-level × duration cell coverage to determine where the
   expected-improvement model can operate at event level and where it will
   require event-family pooling or hierarchical shrinkage.
5. Creates a reviewable candidate modeling cohort.

Extreme statistical tails remain model candidates unless another independent
data-quality issue is found. Long-duration trajectories are parked for review
rather than automatically included in the primary expected-improvement model.
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
      "phase_5a_observed_development_trajectories/"
      "observed_development_trajectories_v1.duckdb"
)

PHASE_5A_CHECKS = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5a_observed_development_trajectories/"
      "hard_checks.csv"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5b_trajectory_modeling_audit"
)

OUTPUT_DB = OUTPUT_DIR / "trajectory_modeling_audit_v1.duckdb"

INPUT_DATASET_VERSION = "observed_development_trajectories_v1"
INPUT_POLICY_VERSION = "observed_development_policy_v1"
AUDIT_VERSION = "trajectory_modeling_audit_v1_1"

EXPECTED_TRAJECTORY_ROWS = 189_839
EXPECTED_TRAJECTORY_ATHLETES = 79_551
EXPECTED_TRAJECTORY_SCHOOLS = 361
EXPECTED_LONG_DURATION_ROWS = 136
EXPECTED_EXTREME_LONG_DURATION_ROWS = 5
EXPECTED_PRIMARY_CANDIDATE_ROWS = (
    EXPECTED_TRAJECTORY_ROWS - EXPECTED_LONG_DURATION_ROWS
)

PRIMARY_MAX_ELAPSED_SEASONS = 5
EXTREME_LONG_DURATION_MIN = 8

TAIL_PROBABILITY = 0.001
MIN_EVENT_CELL_ROWS = 100
MIN_EVENT_CELL_SCHOOLS = 25
MIN_FAMILY_CELL_ROWS = 250
MIN_FAMILY_CELL_SCHOOLS = 50


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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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

    print("MILESTONE 5 PHASE 5B — TRAJECTORY MODELING AUDIT")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Audit version: {AUDIT_VERSION}")
    print(f"Input database: {INPUT_DB}")
    print(f"Output database: {OUTPUT_DB}")

    required_inputs = [INPUT_DB, PHASE_5A_CHECKS]
    missing = [str(path) for path in required_inputs if not path.exists()]

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
        print("PHASE GATE: FAIL — Required Phase 5A input missing.")
        return 1

    phase_5a_checks = read_csv(PHASE_5A_CHECKS)
    failed_phase_5a_checks = [
        row
        for row in phase_5a_checks
        if row.get("status") != "PASS"
    ]

    add_check(
        checks,
        "phase_5a_gate_passed",
        not failed_phase_5a_checks,
        [
            row.get("check_name")
            for row in failed_phase_5a_checks
        ],
        [],
    )

    input_hashes_before = {
        str(path): sha256_file(path)
        for path in required_inputs
    }

    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()

    con = duckdb.connect(str(OUTPUT_DB))

    try:
        con.execute("PRAGMA threads=4")
        con.execute("PRAGMA enable_progress_bar=false")

        con.execute(
            f"""
            ATTACH '{sql_path(INPUT_DB)}'
                AS trajectory_source (READ_ONLY)
            """
        )

        metadata = {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM trajectory_source.main.dataset_metadata
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
        add_check(
            checks,
            "input_policy_version_matches",
            metadata.get("trajectory_policy_version")
            == INPUT_POLICY_VERSION,
            metadata.get("trajectory_policy_version"),
            INPUT_POLICY_VERSION,
        )

        con.execute(
            f"""
            CREATE TABLE trajectory_audit AS
            WITH ranked AS (
                SELECT
                    t.*,
                    CUME_DIST() OVER (
                        PARTITION BY
                            season_type,
                            canonical_gender_code,
                            canonical_event_code
                        ORDER BY observed_improvement
                    ) AS observed_improvement_percentile,
                    CUME_DIST() OVER (
                        PARTITION BY
                            season_type,
                            canonical_gender_code,
                            canonical_event_code
                        ORDER BY annualized_observed_improvement
                    ) AS annualized_improvement_percentile,
                    CUME_DIST() OVER (
                        PARTITION BY
                            season_type,
                            canonical_gender_code,
                            canonical_event_code
                        ORDER BY baseline_stable_level
                    ) AS baseline_level_percentile
                FROM
                    trajectory_source.main.athlete_event_trajectories t
            )
            SELECT
                *,
                elapsed_seasons > {PRIMARY_MAX_ELAPSED_SEASONS}
                    AS long_duration_review_flag,
                elapsed_seasons >= {EXTREME_LONG_DURATION_MIN}
                    AS extreme_long_duration_flag,
                observed_improvement_percentile
                    <= {TAIL_PROBABILITY}
                    AS event_low_improvement_tail_flag,
                observed_improvement_percentile
                    >= {1.0 - TAIL_PROBABILITY}
                    AS event_high_improvement_tail_flag,
                annualized_improvement_percentile
                    <= {TAIL_PROBABILITY}
                    AS event_low_annualized_tail_flag,
                annualized_improvement_percentile
                    >= {1.0 - TAIL_PROBABILITY}
                    AS event_high_annualized_tail_flag,
                baseline_level_percentile
                    <= {TAIL_PROBABILITY}
                    AS event_low_baseline_tail_flag,
                baseline_level_percentile
                    >= {1.0 - TAIL_PROBABILITY}
                    AS event_high_baseline_tail_flag,
                frozen_role =
                    'standalone_primary_two_meet_exception'
                    AS two_meet_exception_flag,
                elapsed_seasons BETWEEN 1
                    AND {PRIMARY_MAX_ELAPSED_SEASONS}
                    AS primary_model_candidate,
                CASE
                    WHEN elapsed_seasons
                        > {PRIMARY_MAX_ELAPSED_SEASONS}
                        THEN 'long_duration_manual_review'
                    ELSE 'primary_model_candidate'
                END AS modeling_disposition,
                CASE
                    WHEN elapsed_seasons
                        > {PRIMARY_MAX_ELAPSED_SEASONS}
                        THEN
                            'Elapsed same-season-type span exceeds '
                            || '{PRIMARY_MAX_ELAPSED_SEASONS}'
                            || ' seasons.'
                    ELSE
                        'Within primary 1–'
                        || '{PRIMARY_MAX_ELAPSED_SEASONS}'
                        || ' season modeling window.'
                END AS modeling_disposition_reason,
                '{AUDIT_VERSION}' AS audit_version
            FROM ranked
            """
        )

        con.execute(
            """
            CREATE VIEW primary_modeling_candidate_trajectories AS
            SELECT *
            FROM trajectory_audit
            WHERE primary_model_candidate
            """
        )

        con.execute(
            """
            CREATE VIEW long_duration_review_trajectories AS
            SELECT *
            FROM trajectory_audit
            WHERE long_duration_review_flag
            """
        )

        con.execute(
            """
            CREATE VIEW extreme_statistical_tail_trajectories AS
            SELECT *
            FROM trajectory_audit
            WHERE event_low_improvement_tail_flag
               OR event_high_improvement_tail_flag
               OR event_low_annualized_tail_flag
               OR event_high_annualized_tail_flag
               OR event_low_baseline_tail_flag
               OR event_high_baseline_tail_flag
            """
        )

        con.execute(
            f"""
            CREATE TABLE event_baseline_duration_cells AS
            WITH prepared AS (
                SELECT
                    *,
                    LEAST(
                        20,
                        GREATEST(
                            1,
                            CAST(
                                FLOOR(
                                    baseline_stable_level / 5.0
                                ) AS INTEGER
                            ) + 1
                        )
                    ) AS baseline_level_band
                FROM primary_modeling_candidate_trajectories
            )
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(event_family) AS event_family,
                elapsed_seasons,
                baseline_level_band,
                (baseline_level_band - 1) * 5
                    AS baseline_band_lower,
                baseline_level_band * 5
                    AS baseline_band_upper,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT canonical_person_id)
                    AS athlete_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(baseline_stable_level)
                    AS mean_baseline_level,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                MEDIAN(observed_improvement)
                    AS median_observed_improvement,
                AVG(annualized_observed_improvement)
                    AS mean_annualized_improvement,
                STDDEV_SAMP(observed_improvement)
                    AS observed_improvement_sd,
                COUNT(*) FILTER (
                    WHERE observed_improvement > 0
                )::DOUBLE
                    / COUNT(*) AS improvement_rate,
                CASE
                    WHEN COUNT(*) >= {MIN_EVENT_CELL_ROWS}
                     AND COUNT(DISTINCT resolved_school_id)
                            >= {MIN_EVENT_CELL_SCHOOLS}
                        THEN 'event_cell_supported'
                    ELSE 'event_cell_sparse'
                END AS event_cell_support_status
            FROM prepared
            GROUP BY
                season_type,
                canonical_gender_code,
                canonical_event_code,
                elapsed_seasons,
                baseline_level_band
            """
        )

        con.execute(
            f"""
            CREATE TABLE family_baseline_duration_cells AS
            WITH prepared AS (
                SELECT
                    *,
                    LEAST(
                        20,
                        GREATEST(
                            1,
                            CAST(
                                FLOOR(
                                    baseline_stable_level / 5.0
                                ) AS INTEGER
                            ) + 1
                        )
                    ) AS baseline_level_band
                FROM primary_modeling_candidate_trajectories
            )
            SELECT
                season_type,
                canonical_gender_code,
                event_family,
                elapsed_seasons,
                baseline_level_band,
                (baseline_level_band - 1) * 5
                    AS baseline_band_lower,
                baseline_level_band * 5
                    AS baseline_band_upper,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT canonical_person_id)
                    AS athlete_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(baseline_stable_level)
                    AS mean_baseline_level,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                MEDIAN(observed_improvement)
                    AS median_observed_improvement,
                AVG(annualized_observed_improvement)
                    AS mean_annualized_improvement,
                STDDEV_SAMP(observed_improvement)
                    AS observed_improvement_sd,
                COUNT(*) FILTER (
                    WHERE observed_improvement > 0
                )::DOUBLE
                    / COUNT(*) AS improvement_rate,
                CASE
                    WHEN COUNT(*) >= {MIN_FAMILY_CELL_ROWS}
                     AND COUNT(DISTINCT resolved_school_id)
                            >= {MIN_FAMILY_CELL_SCHOOLS}
                        THEN 'family_cell_supported'
                    ELSE 'family_cell_sparse'
                END AS family_cell_support_status
            FROM prepared
            GROUP BY
                season_type,
                canonical_gender_code,
                event_family,
                elapsed_seasons,
                baseline_level_band
            """
        )

        con.execute(
            """
            CREATE TABLE recommended_modeling_resolution AS
            SELECT
                e.*,
                f.trajectory_count
                    AS family_trajectory_count,
                f.school_count AS family_school_count,
                f.family_cell_support_status,
                CASE
                    WHEN e.event_cell_support_status =
                        'event_cell_supported'
                        THEN 'event_level'
                    WHEN f.family_cell_support_status =
                        'family_cell_supported'
                        THEN 'event_family_level'
                    ELSE 'hierarchical_global_fallback'
                END AS recommended_resolution
            FROM event_baseline_duration_cells e
            LEFT JOIN family_baseline_duration_cells f
              USING (
                season_type,
                canonical_gender_code,
                event_family,
                elapsed_seasons,
                baseline_level_band
              )
            """
        )

        con.execute(
            f"""
            CREATE TABLE dataset_metadata AS
            SELECT
                'dataset_version' AS metadata_key,
                '{AUDIT_VERSION}' AS metadata_value
            UNION ALL
            SELECT
                'input_dataset_version',
                '{INPUT_DATASET_VERSION}'
            UNION ALL
            SELECT
                'input_trajectory_policy_version',
                '{INPUT_POLICY_VERSION}'
            UNION ALL
            SELECT
                'primary_max_elapsed_seasons',
                '{PRIMARY_MAX_ELAPSED_SEASONS}'
            UNION ALL
            SELECT
                'statistical_tail_probability',
                '{TAIL_PROBABILITY}'
            UNION ALL
            SELECT
                'created_at_utc',
                CURRENT_TIMESTAMP::VARCHAR
            """
        )

        counts = fetch_dicts(
            con,
            """
            SELECT
                COUNT(*) AS trajectory_rows,
                COUNT(DISTINCT canonical_person_id)
                    AS trajectory_athletes,
                COUNT(DISTINCT resolved_school_id)
                    AS trajectory_schools,
                COUNT(*) FILTER (
                    WHERE primary_model_candidate
                ) AS primary_candidate_rows,
                COUNT(*) FILTER (
                    WHERE long_duration_review_flag
                ) AS long_duration_rows,
                COUNT(*) FILTER (
                    WHERE extreme_long_duration_flag
                ) AS extreme_long_duration_rows,
                COUNT(*) FILTER (
                    WHERE two_meet_exception_flag
                ) AS two_meet_exception_rows,
                COUNT(*) FILTER (
                    WHERE event_low_improvement_tail_flag
                       OR event_high_improvement_tail_flag
                ) AS improvement_tail_rows,
                COUNT(*) FILTER (
                    WHERE event_low_annualized_tail_flag
                       OR event_high_annualized_tail_flag
                ) AS annualized_tail_rows,
                COUNT(*) FILTER (
                    WHERE event_low_baseline_tail_flag
                       OR event_high_baseline_tail_flag
                ) AS baseline_tail_rows,
                COUNT(*) FILTER (
                    WHERE primary_model_candidate
                      AND long_duration_review_flag
                ) AS candidate_review_overlap_rows,
                COUNT(*) FILTER (
                    WHERE NOT primary_model_candidate
                      AND NOT long_duration_review_flag
                ) AS unclassified_rows
            FROM trajectory_audit
            """
        )[0]

        structural = fetch_dicts(
            con,
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE elapsed_seasons <= 0
                ) AS invalid_elapsed_rows,
                COUNT(*) FILTER (
                    WHERE baseline_stable_level < 0
                       OR baseline_stable_level > 100
                       OR endpoint_stable_level < 0
                       OR endpoint_stable_level > 100
                ) AS invalid_score_rows,
                COUNT(*) FILTER (
                    WHERE trajectory_id IS NULL
                       OR canonical_person_id IS NULL
                       OR school_stint_id IS NULL
                       OR resolved_school_id IS NULL
                ) AS missing_identity_context_rows
            FROM trajectory_audit
            """
        )[0]

        duplicate_ids = fetch_dicts(
            con,
            """
            SELECT trajectory_id, COUNT(*) AS row_count
            FROM trajectory_audit
            GROUP BY trajectory_id
            HAVING COUNT(*) > 1
            LIMIT 100
            """
        )

        resolution_counts = fetch_dicts(
            con,
            """
            SELECT
                recommended_resolution,
                COUNT(*) AS cell_count,
                SUM(trajectory_count) AS summed_cell_rows
            FROM recommended_modeling_resolution
            GROUP BY recommended_resolution
            ORDER BY recommended_resolution
            """
        )

        add_check(
            checks,
            "trajectory_row_count",
            counts["trajectory_rows"]
            == EXPECTED_TRAJECTORY_ROWS,
            counts["trajectory_rows"],
            EXPECTED_TRAJECTORY_ROWS,
        )
        add_check(
            checks,
            "trajectory_athlete_count",
            counts["trajectory_athletes"]
            == EXPECTED_TRAJECTORY_ATHLETES,
            counts["trajectory_athletes"],
            EXPECTED_TRAJECTORY_ATHLETES,
        )
        add_check(
            checks,
            "trajectory_school_count",
            counts["trajectory_schools"]
            == EXPECTED_TRAJECTORY_SCHOOLS,
            counts["trajectory_schools"],
            EXPECTED_TRAJECTORY_SCHOOLS,
        )
        add_check(
            checks,
            "long_duration_row_count",
            counts["long_duration_rows"]
            == EXPECTED_LONG_DURATION_ROWS,
            counts["long_duration_rows"],
            EXPECTED_LONG_DURATION_ROWS,
        )
        add_check(
            checks,
            "extreme_long_duration_row_count",
            counts["extreme_long_duration_rows"]
            == EXPECTED_EXTREME_LONG_DURATION_ROWS,
            counts["extreme_long_duration_rows"],
            EXPECTED_EXTREME_LONG_DURATION_ROWS,
        )
        add_check(
            checks,
            "primary_candidate_row_count",
            counts["primary_candidate_rows"]
            == EXPECTED_PRIMARY_CANDIDATE_ROWS,
            counts["primary_candidate_rows"],
            EXPECTED_PRIMARY_CANDIDATE_ROWS,
        )
        add_check(
            checks,
            "modeling_dispositions_partition_rows",
            counts["candidate_review_overlap_rows"] == 0
            and counts["unclassified_rows"] == 0
            and counts["primary_candidate_rows"]
                + counts["long_duration_rows"]
                == counts["trajectory_rows"],
            {
                "candidate_review_overlap":
                    counts["candidate_review_overlap_rows"],
                "unclassified":
                    counts["unclassified_rows"],
                "candidate_plus_review":
                    counts["primary_candidate_rows"]
                    + counts["long_duration_rows"],
            },
            {
                "candidate_review_overlap": 0,
                "unclassified": 0,
                "candidate_plus_review":
                    counts["trajectory_rows"],
            },
        )
        add_check(
            checks,
            "trajectory_ids_unique",
            not duplicate_ids,
            len(duplicate_ids),
            0,
        )
        add_check(
            checks,
            "elapsed_seasons_positive",
            structural["invalid_elapsed_rows"] == 0,
            structural["invalid_elapsed_rows"],
            0,
        )
        add_check(
            checks,
            "scores_in_range",
            structural["invalid_score_rows"] == 0,
            structural["invalid_score_rows"],
            0,
        )
        add_check(
            checks,
            "identity_and_school_context_complete",
            structural["missing_identity_context_rows"] == 0,
            structural["missing_identity_context_rows"],
            0,
        )
        add_check(
            checks,
            "modeling_resolution_cells_exist",
            len(resolution_counts) > 0,
            len(resolution_counts),
            "greater than 0",
        )

        duration_rows = fetch_dicts(
            con,
            f"""
            SELECT
                elapsed_seasons,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT canonical_person_id)
                    AS athlete_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(baseline_stable_level)
                    AS mean_baseline_level,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                MEDIAN(observed_improvement)
                    AS median_observed_improvement,
                AVG(annualized_observed_improvement)
                    AS mean_annualized_improvement,
                COUNT(*) FILTER (
                    WHERE observed_improvement > 0
                )::DOUBLE
                    / COUNT(*) AS improvement_rate,
                CASE
                    WHEN elapsed_seasons
                        <= {PRIMARY_MAX_ELAPSED_SEASONS}
                        THEN 'primary_model_candidate'
                    ELSE 'long_duration_manual_review'
                END AS modeling_disposition
            FROM trajectory_audit
            GROUP BY elapsed_seasons
            ORDER BY elapsed_seasons
            """
        )

        write_csv(
            OUTPUT_DIR / "duration_audit.csv",
            duration_rows,
            [
                "elapsed_seasons",
                "trajectory_count",
                "athlete_count",
                "school_count",
                "mean_baseline_level",
                "mean_observed_improvement",
                "median_observed_improvement",
                "mean_annualized_improvement",
                "improvement_rate",
                "modeling_disposition",
            ],
        )

        long_duration_rows = fetch_dicts(
            con,
            """
            SELECT
                trajectory_id,
                canonical_person_id,
                athlete_name,
                resolved_school_id,
                school_stint_id,
                canonical_gender_code,
                season_type,
                canonical_event_code,
                canonical_event_name,
                event_family,
                baseline_season_year,
                endpoint_season_year,
                elapsed_seasons,
                qualifying_period_count,
                total_distinct_meets,
                baseline_stable_level,
                endpoint_stable_level,
                observed_improvement,
                annualized_observed_improvement,
                trajectory_reliability_tier,
                extreme_long_duration_flag,
                modeling_disposition_reason
            FROM long_duration_review_trajectories
            ORDER BY
                elapsed_seasons DESC,
                ABS(observed_improvement) DESC,
                trajectory_id
            """
        )

        write_csv(
            OUTPUT_DIR / "long_duration_trajectory_review.csv",
            long_duration_rows,
            [
                "trajectory_id",
                "canonical_person_id",
                "athlete_name",
                "resolved_school_id",
                "school_stint_id",
                "canonical_gender_code",
                "season_type",
                "canonical_event_code",
                "canonical_event_name",
                "event_family",
                "baseline_season_year",
                "endpoint_season_year",
                "elapsed_seasons",
                "qualifying_period_count",
                "total_distinct_meets",
                "baseline_stable_level",
                "endpoint_stable_level",
                "observed_improvement",
                "annualized_observed_improvement",
                "trajectory_reliability_tier",
                "extreme_long_duration_flag",
                "modeling_disposition_reason",
            ],
        )

        extreme_rows = fetch_dicts(
            con,
            """
            SELECT
                trajectory_id,
                canonical_person_id,
                athlete_name,
                resolved_school_id,
                school_stint_id,
                canonical_gender_code,
                season_type,
                canonical_event_code,
                canonical_event_name,
                event_family,
                elapsed_seasons,
                qualifying_period_count,
                baseline_stable_level,
                endpoint_stable_level,
                observed_improvement,
                annualized_observed_improvement,
                observed_improvement_percentile,
                annualized_improvement_percentile,
                baseline_level_percentile,
                event_low_improvement_tail_flag,
                event_high_improvement_tail_flag,
                event_low_annualized_tail_flag,
                event_high_annualized_tail_flag,
                event_low_baseline_tail_flag,
                event_high_baseline_tail_flag,
                long_duration_review_flag,
                primary_model_candidate
            FROM extreme_statistical_tail_trajectories
            ORDER BY
                long_duration_review_flag DESC,
                ABS(annualized_observed_improvement) DESC,
                ABS(observed_improvement) DESC,
                trajectory_id
            LIMIT 5000
            """
        )

        write_csv(
            OUTPUT_DIR / "extreme_statistical_tail_review.csv",
            extreme_rows,
            list(extreme_rows[0].keys()) if extreme_rows else [],
        )

        event_cells = fetch_dicts(
            con,
            """
            SELECT *
            FROM event_baseline_duration_cells
            ORDER BY
                event_cell_support_status,
                trajectory_count,
                season_type,
                canonical_gender_code,
                canonical_event_code,
                elapsed_seasons,
                baseline_level_band
            """
        )

        write_csv(
            OUTPUT_DIR / "event_baseline_duration_cell_coverage.csv",
            event_cells,
            list(event_cells[0].keys()) if event_cells else [],
        )

        family_cells = fetch_dicts(
            con,
            """
            SELECT *
            FROM family_baseline_duration_cells
            ORDER BY
                family_cell_support_status,
                trajectory_count,
                season_type,
                canonical_gender_code,
                event_family,
                elapsed_seasons,
                baseline_level_band
            """
        )

        write_csv(
            OUTPUT_DIR / "family_baseline_duration_cell_coverage.csv",
            family_cells,
            list(family_cells[0].keys()) if family_cells else [],
        )

        resolution_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM recommended_modeling_resolution
            ORDER BY
                recommended_resolution,
                trajectory_count,
                season_type,
                canonical_gender_code,
                canonical_event_code,
                elapsed_seasons,
                baseline_level_band
            """
        )

        write_csv(
            OUTPUT_DIR / "recommended_modeling_resolution.csv",
            resolution_rows,
            list(resolution_rows[0].keys()) if resolution_rows else [],
        )

        write_csv(
            OUTPUT_DIR / "modeling_resolution_summary.csv",
            resolution_counts,
            [
                "recommended_resolution",
                "cell_count",
                "summed_cell_rows",
            ],
        )

        summary_rows = [
            {
                "metric": "trajectory_rows",
                "value": counts["trajectory_rows"],
            },
            {
                "metric": "primary_model_candidate_rows",
                "value": counts["primary_candidate_rows"],
            },
            {
                "metric": "long_duration_review_rows",
                "value": counts["long_duration_rows"],
            },
            {
                "metric": "extreme_long_duration_rows",
                "value": counts["extreme_long_duration_rows"],
            },
            {
                "metric": "two_meet_exception_rows",
                "value": counts["two_meet_exception_rows"],
            },
            {
                "metric": "improvement_tail_rows",
                "value": counts["improvement_tail_rows"],
            },
            {
                "metric": "annualized_tail_rows",
                "value": counts["annualized_tail_rows"],
            },
            {
                "metric": "baseline_tail_rows",
                "value": counts["baseline_tail_rows"],
            },
            {
                "metric": "primary_max_elapsed_seasons",
                "value": PRIMARY_MAX_ELAPSED_SEASONS,
            },
            {
                "metric": "statistical_tail_probability",
                "value": TAIL_PROBABILITY,
            },
        ]

        write_csv(
            OUTPUT_DIR / "phase_5b_summary.csv",
            summary_rows,
            ["metric", "value"],
        )

    finally:
        con.close()

    input_hashes_after = {
        str(path): sha256_file(path)
        for path in required_inputs
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
            for path in required_inputs
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
                "audit_version": AUDIT_VERSION,
                "input_dataset_version": INPUT_DATASET_VERSION,
            }
        ],
        [
            "output_name",
            "path",
            "size_bytes",
            "sha256",
            "audit_version",
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
        "MILESTONE 5 PHASE 5B — TRAJECTORY MODELING AUDIT",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Audit version: {AUDIT_VERSION}",
        "",
        "PRIMARY MODELING DISPOSITION",
        "-" * 78,
        f"Primary candidate window: 1–"
        f"{PRIMARY_MAX_ELAPSED_SEASONS} elapsed seasons",
        "Trajectories longer than the primary window are parked for review.",
        "Statistical tail flags do not automatically exclude trajectories.",
        "",
        "RESULTS",
        "-" * 78,
        f"All observed trajectories: "
        f"{int(counts['trajectory_rows']):,}",
        f"Primary modeling candidates: "
        f"{int(counts['primary_candidate_rows']):,}",
        f"Long-duration review rows: "
        f"{int(counts['long_duration_rows']):,}",
        f"Extreme long-duration rows (8+ seasons): "
        f"{int(counts['extreme_long_duration_rows']):,}",
        f"Improvement-tail rows: "
        f"{int(counts['improvement_tail_rows']):,}",
        f"Annualized-change-tail rows: "
        f"{int(counts['annualized_tail_rows']):,}",
        f"Baseline-level-tail rows: "
        f"{int(counts['baseline_tail_rows']):,}",
        "",
        "MODEL RESOLUTION",
        "-" * 78,
    ]

    for row in resolution_counts:
        report.append(
            f"{row['recommended_resolution']}: "
            f"{int(row['cell_count']):,} cells"
        )

    report.extend(
        [
            "",
            "PHASE GATE",
            "-" * 78,
            (
                "PASS — Trajectory modeling audit and candidate cohort "
                "created."
                if not failed
                else "FAIL — Do not fit expected-improvement models."
            ),
            "",
            "NEXT",
            "-" * 78,
            "Review the 136 long-duration trajectories.",
            "Then freeze the primary expected-improvement modeling cohort",
            "and fit out-of-sample hierarchical benchmarks.",
        ]
    )

    (OUTPUT_DIR / "phase_5b_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"All trajectories: {int(counts['trajectory_rows']):,}"
    )
    print(
        "Primary modeling candidates: "
        f"{int(counts['primary_candidate_rows']):,}"
    )
    print(
        "Long-duration review rows: "
        f"{int(counts['long_duration_rows']):,}"
    )
    print(
        "Extreme long-duration rows: "
        f"{int(counts['extreme_long_duration_rows']):,}"
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
    print("Next: review long durations and freeze modeling cohort.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
