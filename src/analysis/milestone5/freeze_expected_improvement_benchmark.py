#!/usr/bin/env python3
"""
Milestone 5 Phase 5E — Freeze Expected-Improvement Benchmark

Freezes the Phase 5D cross-fitted benchmark recommendation and creates the
first official athlete trajectory value-added dataset.

Frozen benchmark
----------------
resolution_raw_mean

For every trajectory:
athlete value added = observed improvement - expected improvement

All expected-improvement predictions remain school-held-out because the Phase
5D candidate predictions were generated from training folds that excluded the
trajectory's school fold.

This phase does not yet aggregate trajectories into athlete or school ranks.
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
      "phase_5d_expected_improvement_benchmark_comparison/"
      "expected_improvement_benchmarks_v1.duckdb"
)

PHASE_5D_CHECKS = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5d_expected_improvement_benchmark_comparison/"
      "hard_checks.csv"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5e_frozen_expected_improvement_benchmark"
)

OUTPUT_DB = OUTPUT_DIR / "expected_improvement_policy_v1.duckdb"

INPUT_DATASET_VERSION = "expected_improvement_benchmarks_v1_2"
INPUT_BENCHMARK_POLICY_VERSION = (
    "expected_improvement_benchmark_comparison_v1_2"
)
DATASET_VERSION = "expected_improvement_policy_v1_1"
POLICY_VERSION = "expected_improvement_policy_v1_1"

SELECTED_CANDIDATE = "resolution_raw_mean"

EXPECTED_TRAJECTORY_ROWS = 189_703
EXPECTED_SCHOOLS = 361
EXPECTED_FOLDS = 5

MAX_ABS_OVERALL_BIAS = 0.10
MIN_CALIBRATION_SLOPE = 0.90
MAX_CALIBRATION_SLOPE = 1.10
MAX_ABS_FOLD_BIAS = 0.10
MAX_ABS_DURATION_BIAS = 0.20
MAX_ABS_RESOLUTION_BIAS = 0.35


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

    print("MILESTONE 5 PHASE 5E — FREEZE EXPECTED-IMPROVEMENT BENCHMARK")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Selected candidate: {SELECTED_CANDIDATE}")
    print(f"Input database: {INPUT_DB}")
    print(f"Output database: {OUTPUT_DB}")

    required_inputs = [INPUT_DB, PHASE_5D_CHECKS]
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
        print("PHASE GATE: FAIL — Required Phase 5D input missing.")
        return 1

    phase_5d_checks = read_csv(PHASE_5D_CHECKS)
    failed_phase_5d_checks = [
        row
        for row in phase_5d_checks
        if row.get("status") != "PASS"
    ]

    add_check(
        checks,
        "phase_5d_gate_passed",
        not failed_phase_5d_checks,
        [
            row.get("check_name")
            for row in failed_phase_5d_checks
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
                AS benchmark_source (READ_ONLY)
            """
        )

        metadata = {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM benchmark_source.main.dataset_metadata
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
            "input_benchmark_policy_version_matches",
            metadata.get("benchmark_policy_version")
            == INPUT_BENCHMARK_POLICY_VERSION,
            metadata.get("benchmark_policy_version"),
            INPUT_BENCHMARK_POLICY_VERSION,
        )

        con.execute(
            f"""
            CREATE TABLE frozen_benchmark_policy AS
            SELECT
                candidate_name,
                prediction_count,
                mae,
                rmse,
                median_absolute_error,
                mean_bias,
                prediction_correlation,
                calibration_slope,
                calibration_intercept,
                r_squared,
                mae_rank,
                rmse_rank,
                naive_mae,
                naive_rmse,
                mae_improvement_vs_naive,
                rmse_improvement_vs_naive,
                recommended_for_freeze,
                recommendation_reason,
                'approved' AS policy_status,
                '{POLICY_VERSION}' AS policy_version,
                CURRENT_TIMESTAMP::VARCHAR AS frozen_at_utc
            FROM benchmark_source.main.candidate_recommendation
            WHERE recommended_for_freeze
            """
        )

        selected_policy = fetch_dicts(
            con,
            """
            SELECT *
            FROM frozen_benchmark_policy
            """
        )

        selected_name = (
            selected_policy[0]["candidate_name"]
            if len(selected_policy) == 1
            else None
        )

        add_check(
            checks,
            "exactly_one_recommended_candidate",
            len(selected_policy) == 1,
            len(selected_policy),
            1,
        )
        add_check(
            checks,
            "recommended_candidate_matches_review",
            selected_name == SELECTED_CANDIDATE,
            selected_name,
            SELECTED_CANDIDATE,
        )

        con.execute(
            f"""
            CREATE TABLE expected_improvement_scored_trajectories AS
            SELECT
                m.*,
                p.expected_improvement,
                p.residual_value_added AS athlete_value_added,
                p.observed_improvement
                    - p.expected_improvement
                    AS value_added_formula_check,
                p.training_support_n,
                p.candidate_name AS expected_improvement_model,
                CASE
                    WHEN m.elapsed_seasons > 0
                    THEN p.expected_improvement
                        / m.elapsed_seasons
                    ELSE NULL
                END AS annualized_expected_improvement,
                CASE
                    WHEN m.elapsed_seasons > 0
                    THEN p.residual_value_added
                        / m.elapsed_seasons
                    ELSE NULL
                END AS annualized_athlete_value_added,
                ABS(p.residual_value_added)
                    AS absolute_value_added,
                CASE
                    WHEN p.residual_value_added > 1e-12
                        THEN 'above_expected'
                    WHEN p.residual_value_added < -1e-12
                        THEN 'below_expected'
                    ELSE 'at_expected'
                END AS value_added_direction,
                '{DATASET_VERSION}' AS value_added_dataset_version,
                '{POLICY_VERSION}' AS expected_improvement_policy_version
            FROM
                benchmark_source.main.modeling_cohort_snapshot m
            JOIN benchmark_source.main.candidate_predictions p
              USING (trajectory_id)
            WHERE p.candidate_name = '{SELECTED_CANDIDATE}'
            """
        )

        con.execute(
            """
            CREATE VIEW above_expected_trajectories AS
            SELECT *
            FROM expected_improvement_scored_trajectories
            WHERE athlete_value_added > 0
            """
        )

        con.execute(
            """
            CREATE VIEW below_expected_trajectories AS
            SELECT *
            FROM expected_improvement_scored_trajectories
            WHERE athlete_value_added < 0
            """
        )

        con.execute(
            """
            CREATE TABLE benchmark_fold_calibration AS
            SELECT
                crossfit_fold,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                AVG(expected_improvement)
                    AS mean_expected_improvement,
                AVG(athlete_value_added)
                    AS mean_value_added,
                MEDIAN(athlete_value_added)
                    AS median_value_added,
                AVG(ABS(athlete_value_added))
                    AS mae,
                SQRT(AVG(POWER(athlete_value_added, 2)))
                    AS rmse
            FROM expected_improvement_scored_trajectories
            GROUP BY crossfit_fold
            ORDER BY crossfit_fold
            """
        )

        con.execute(
            """
            CREATE TABLE benchmark_duration_calibration AS
            SELECT
                elapsed_seasons,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                AVG(expected_improvement)
                    AS mean_expected_improvement,
                AVG(athlete_value_added)
                    AS mean_value_added,
                MEDIAN(athlete_value_added)
                    AS median_value_added,
                AVG(ABS(athlete_value_added))
                    AS mae,
                SQRT(AVG(POWER(athlete_value_added, 2)))
                    AS rmse
            FROM expected_improvement_scored_trajectories
            GROUP BY elapsed_seasons
            ORDER BY elapsed_seasons
            """
        )

        con.execute(
            """
            CREATE TABLE benchmark_resolution_calibration AS
            SELECT
                recommended_resolution,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                AVG(expected_improvement)
                    AS mean_expected_improvement,
                AVG(athlete_value_added)
                    AS mean_value_added,
                MEDIAN(athlete_value_added)
                    AS median_value_added,
                AVG(ABS(athlete_value_added))
                    AS mae,
                SQRT(AVG(POWER(athlete_value_added, 2)))
                    AS rmse,
                MIN(training_support_n)
                    AS minimum_training_support,
                MEDIAN(training_support_n)
                    AS median_training_support
            FROM expected_improvement_scored_trajectories
            GROUP BY recommended_resolution
            ORDER BY recommended_resolution
            """
        )

        con.execute(
            """
            CREATE TABLE benchmark_baseline_calibration AS
            SELECT
                canonical_gender_code,
                season_type,
                baseline_level_band,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(baseline_stable_level)
                    AS mean_baseline_level,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                AVG(expected_improvement)
                    AS mean_expected_improvement,
                AVG(athlete_value_added)
                    AS mean_value_added,
                MEDIAN(athlete_value_added)
                    AS median_value_added,
                AVG(ABS(athlete_value_added))
                    AS mae
            FROM expected_improvement_scored_trajectories
            GROUP BY
                canonical_gender_code,
                season_type,
                baseline_level_band
            ORDER BY
                canonical_gender_code,
                season_type,
                baseline_level_band
            """
        )

        con.execute(
            """
            CREATE TABLE benchmark_event_family_calibration AS
            SELECT
                canonical_gender_code,
                season_type,
                event_family,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                AVG(expected_improvement)
                    AS mean_expected_improvement,
                AVG(athlete_value_added)
                    AS mean_value_added,
                MEDIAN(athlete_value_added)
                    AS median_value_added,
                AVG(ABS(athlete_value_added))
                    AS mae,
                SQRT(AVG(POWER(athlete_value_added, 2)))
                    AS rmse
            FROM expected_improvement_scored_trajectories
            GROUP BY
                canonical_gender_code,
                season_type,
                event_family
            ORDER BY
                canonical_gender_code,
                season_type,
                event_family
            """
        )

        con.execute(
            """
            CREATE TABLE benchmark_support_calibration AS
            WITH bucketed AS (
                SELECT
                    *,
                    CASE
                        WHEN training_support_n < 25
                            THEN '001_under_25'
                        WHEN training_support_n < 50
                            THEN '002_25_to_49'
                        WHEN training_support_n < 100
                            THEN '003_50_to_99'
                        WHEN training_support_n < 250
                            THEN '004_100_to_249'
                        WHEN training_support_n < 500
                            THEN '005_250_to_499'
                        WHEN training_support_n < 1000
                            THEN '006_500_to_999'
                        ELSE '007_1000_plus'
                    END AS support_bucket
                FROM expected_improvement_scored_trajectories
            )
            SELECT
                support_bucket,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                MIN(training_support_n)
                    AS minimum_training_support,
                MAX(training_support_n)
                    AS maximum_training_support,
                AVG(athlete_value_added)
                    AS mean_value_added,
                MEDIAN(athlete_value_added)
                    AS median_value_added,
                AVG(ABS(athlete_value_added))
                    AS mae,
                SQRT(AVG(POWER(athlete_value_added, 2)))
                    AS rmse
            FROM bucketed
            GROUP BY support_bucket
            ORDER BY support_bucket
            """
        )

        con.execute(
            f"""
            CREATE TABLE school_candidate_sensitivity AS
            WITH school_candidate AS (
                SELECT
                    resolved_school_id,
                    candidate_name,
                    COUNT(*) AS trajectory_count,
                    AVG(residual_value_added)
                        AS mean_residual_value_added
                FROM benchmark_source.main.candidate_predictions
                WHERE candidate_name IN (
                    '{SELECTED_CANDIDATE}',
                    'hierarchical_winsorized_moderate',
                    'hierarchical_mean_moderate'
                )
                GROUP BY resolved_school_id, candidate_name
            ),
            pivoted AS (
                SELECT
                    resolved_school_id,
                    MAX(trajectory_count)
                        AS trajectory_count,
                    MAX(CASE
                        WHEN candidate_name =
                            '{SELECTED_CANDIDATE}'
                        THEN mean_residual_value_added
                    END) AS selected_mean_value_added,
                    MAX(CASE
                        WHEN candidate_name =
                            'hierarchical_winsorized_moderate'
                        THEN mean_residual_value_added
                    END) AS winsorized_hierarchical_mean_value_added,
                    MAX(CASE
                        WHEN candidate_name =
                            'hierarchical_mean_moderate'
                        THEN mean_residual_value_added
                    END) AS hierarchical_mean_value_added
                FROM school_candidate
                GROUP BY resolved_school_id
            )
            SELECT
                *,
                selected_mean_value_added
                    - winsorized_hierarchical_mean_value_added
                    AS selected_minus_winsorized,
                selected_mean_value_added
                    - hierarchical_mean_value_added
                    AS selected_minus_hierarchical,
                RANK() OVER (
                    ORDER BY selected_mean_value_added DESC
                ) AS selected_rank,
                RANK() OVER (
                    ORDER BY
                        winsorized_hierarchical_mean_value_added DESC
                ) AS winsorized_hierarchical_rank,
                RANK() OVER (
                    ORDER BY hierarchical_mean_value_added DESC
                ) AS hierarchical_rank
            FROM pivoted
            """
        )

        con.execute(
            f"""
            CREATE TABLE dataset_metadata AS
            SELECT
                'dataset_version' AS metadata_key,
                '{DATASET_VERSION}' AS metadata_value
            UNION ALL
            SELECT
                'expected_improvement_policy_version',
                '{POLICY_VERSION}'
            UNION ALL
            SELECT
                'selected_candidate',
                '{SELECTED_CANDIDATE}'
            UNION ALL
            SELECT
                'input_benchmark_dataset_version',
                '{INPUT_DATASET_VERSION}'
            UNION ALL
            SELECT
                'value_added_formula',
                'observed_improvement_minus_expected_improvement'
            UNION ALL
            SELECT
                'school_held_out_predictions',
                'true'
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
                    AS athlete_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                COUNT(DISTINCT crossfit_fold)
                    AS fold_count,
                COUNT(*) FILTER (
                    WHERE athlete_value_added > 0
                ) AS above_expected_rows,
                COUNT(*) FILTER (
                    WHERE athlete_value_added < 0
                ) AS below_expected_rows,
                COUNT(*) FILTER (
                    WHERE ABS(athlete_value_added) <= 1e-12
                ) AS at_expected_rows,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                AVG(expected_improvement)
                    AS mean_expected_improvement,
                AVG(athlete_value_added)
                    AS mean_value_added,
                MEDIAN(athlete_value_added)
                    AS median_value_added,
                AVG(ABS(athlete_value_added))
                    AS mae,
                SQRT(AVG(POWER(athlete_value_added, 2)))
                    AS rmse,
                CORR(
                    observed_improvement,
                    expected_improvement
                ) AS prediction_correlation,
                REGR_SLOPE(
                    observed_improvement,
                    expected_improvement
                ) AS calibration_slope,
                REGR_INTERCEPT(
                    observed_improvement,
                    expected_improvement
                ) AS calibration_intercept
            FROM expected_improvement_scored_trajectories
            """
        )[0]

        quality = fetch_dicts(
            con,
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE expected_improvement IS NULL
                       OR athlete_value_added IS NULL
                ) AS null_scoring_rows,
                COUNT(*) FILTER (
                    WHERE training_support_n IS NULL
                       OR training_support_n <= 0
                ) AS invalid_support_rows,
                COUNT(*) FILTER (
                    WHERE ABS(
                        athlete_value_added
                        - (
                            observed_improvement
                            - expected_improvement
                        )
                    ) > 1e-10
                ) AS value_added_formula_mismatch_rows,
                COUNT(*) FILTER (
                    WHERE ABS(
                        annualized_athlete_value_added
                        - athlete_value_added / elapsed_seasons
                    ) > 1e-10
                ) AS annualized_formula_mismatch_rows,
                COUNT(*) FILTER (
                    WHERE expected_improvement_model
                        <> 'resolution_raw_mean'
                ) AS wrong_model_rows
            FROM expected_improvement_scored_trajectories
            """
        )[0]

        duplicate_ids = fetch_dicts(
            con,
            """
            SELECT trajectory_id, COUNT(*) AS row_count
            FROM expected_improvement_scored_trajectories
            GROUP BY trajectory_id
            HAVING COUNT(*) > 1
            LIMIT 100
            """
        )

        calibration_maxima = fetch_dicts(
            con,
            """
            SELECT
                (
                    SELECT MAX(ABS(mean_value_added))
                    FROM benchmark_fold_calibration
                ) AS max_abs_fold_bias,
                (
                    SELECT MAX(ABS(mean_value_added))
                    FROM benchmark_duration_calibration
                ) AS max_abs_duration_bias,
                (
                    SELECT MAX(ABS(mean_value_added))
                    FROM benchmark_resolution_calibration
                ) AS max_abs_resolution_bias
            """
        )[0]

        sensitivity = fetch_dicts(
            con,
            """
            SELECT
                CORR(
                    selected_mean_value_added,
                    winsorized_hierarchical_mean_value_added
                ) AS selected_winsorized_school_correlation,
                CORR(
                    selected_mean_value_added,
                    hierarchical_mean_value_added
                ) AS selected_hierarchical_school_correlation,
                AVG(ABS(selected_rank
                    - winsorized_hierarchical_rank))
                    AS mean_abs_rank_difference_winsorized,
                AVG(ABS(selected_rank
                    - hierarchical_rank))
                    AS mean_abs_rank_difference_hierarchical,
                MAX(ABS(selected_rank
                    - winsorized_hierarchical_rank))
                    AS max_abs_rank_difference_winsorized,
                MAX(ABS(selected_rank
                    - hierarchical_rank))
                    AS max_abs_rank_difference_hierarchical
            FROM school_candidate_sensitivity
            """
        )[0]

        selected_metrics = selected_policy[0] if selected_policy else {}

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
            "school_count",
            counts["school_count"] == EXPECTED_SCHOOLS,
            counts["school_count"],
            EXPECTED_SCHOOLS,
        )
        add_check(
            checks,
            "fold_count",
            counts["fold_count"] == EXPECTED_FOLDS,
            counts["fold_count"],
            EXPECTED_FOLDS,
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
            "no_null_scoring_rows",
            quality["null_scoring_rows"] == 0,
            quality["null_scoring_rows"],
            0,
        )
        add_check(
            checks,
            "all_rows_have_training_support",
            quality["invalid_support_rows"] == 0,
            quality["invalid_support_rows"],
            0,
        )
        add_check(
            checks,
            "value_added_formula",
            quality["value_added_formula_mismatch_rows"] == 0,
            quality["value_added_formula_mismatch_rows"],
            0,
        )
        add_check(
            checks,
            "annualized_value_added_formula",
            quality["annualized_formula_mismatch_rows"] == 0,
            quality["annualized_formula_mismatch_rows"],
            0,
        )
        add_check(
            checks,
            "all_rows_use_frozen_model",
            quality["wrong_model_rows"] == 0,
            quality["wrong_model_rows"],
            0,
        )
        add_check(
            checks,
            "mae_matches_phase_5d",
            abs(
                float(counts["mae"])
                - float(selected_metrics.get("mae", float("nan")))
            ) <= 1e-10,
            counts["mae"],
            selected_metrics.get("mae"),
        )
        add_check(
            checks,
            "rmse_matches_phase_5d",
            abs(
                float(counts["rmse"])
                - float(selected_metrics.get("rmse", float("nan")))
            ) <= 1e-10,
            counts["rmse"],
            selected_metrics.get("rmse"),
        )
        add_check(
            checks,
            "overall_bias_within_limit",
            abs(float(counts["mean_value_added"]))
                <= MAX_ABS_OVERALL_BIAS,
            counts["mean_value_added"],
            f"absolute value at most {MAX_ABS_OVERALL_BIAS}",
        )
        add_check(
            checks,
            "calibration_slope_within_range",
            MIN_CALIBRATION_SLOPE
                <= float(counts["calibration_slope"])
                <= MAX_CALIBRATION_SLOPE,
            counts["calibration_slope"],
            (
                f"between {MIN_CALIBRATION_SLOPE} "
                f"and {MAX_CALIBRATION_SLOPE}"
            ),
        )
        add_check(
            checks,
            "fold_bias_within_limit",
            float(calibration_maxima["max_abs_fold_bias"])
                <= MAX_ABS_FOLD_BIAS,
            calibration_maxima["max_abs_fold_bias"],
            f"at most {MAX_ABS_FOLD_BIAS}",
        )
        add_check(
            checks,
            "duration_bias_within_limit",
            float(calibration_maxima["max_abs_duration_bias"])
                <= MAX_ABS_DURATION_BIAS,
            calibration_maxima["max_abs_duration_bias"],
            f"at most {MAX_ABS_DURATION_BIAS}",
        )
        add_check(
            checks,
            "resolution_bias_within_limit",
            float(calibration_maxima["max_abs_resolution_bias"])
                <= MAX_ABS_RESOLUTION_BIAS,
            calibration_maxima["max_abs_resolution_bias"],
            f"at most {MAX_ABS_RESOLUTION_BIAS}",
        )
        add_check(
            checks,
            "frozen_model_beats_naive_mae",
            float(selected_metrics.get("mae"))
                < float(selected_metrics.get("naive_mae")),
            selected_metrics.get("mae"),
            f"less than {selected_metrics.get('naive_mae')}",
        )
        add_check(
            checks,
            "frozen_model_beats_naive_rmse",
            float(selected_metrics.get("rmse"))
                < float(selected_metrics.get("naive_rmse")),
            selected_metrics.get("rmse"),
            f"less than {selected_metrics.get('naive_rmse')}",
        )

        fold_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM benchmark_fold_calibration
            ORDER BY crossfit_fold
            """
        )
        duration_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM benchmark_duration_calibration
            ORDER BY elapsed_seasons
            """
        )
        resolution_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM benchmark_resolution_calibration
            ORDER BY recommended_resolution
            """
        )
        baseline_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM benchmark_baseline_calibration
            ORDER BY
                canonical_gender_code,
                season_type,
                baseline_level_band
            """
        )
        family_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM benchmark_event_family_calibration
            ORDER BY
                canonical_gender_code,
                season_type,
                event_family
            """
        )
        support_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM benchmark_support_calibration
            ORDER BY support_bucket
            """
        )
        sensitivity_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM school_candidate_sensitivity
            ORDER BY selected_rank, resolved_school_id
            """
        )

        write_csv(
            OUTPUT_DIR / "benchmark_fold_calibration.csv",
            fold_rows,
            list(fold_rows[0].keys()) if fold_rows else [],
        )
        write_csv(
            OUTPUT_DIR / "benchmark_duration_calibration.csv",
            duration_rows,
            list(duration_rows[0].keys()) if duration_rows else [],
        )
        write_csv(
            OUTPUT_DIR / "benchmark_resolution_calibration.csv",
            resolution_rows,
            list(resolution_rows[0].keys()) if resolution_rows else [],
        )
        write_csv(
            OUTPUT_DIR / "benchmark_baseline_calibration.csv",
            baseline_rows,
            list(baseline_rows[0].keys()) if baseline_rows else [],
        )
        write_csv(
            OUTPUT_DIR / "benchmark_event_family_calibration.csv",
            family_rows,
            list(family_rows[0].keys()) if family_rows else [],
        )
        write_csv(
            OUTPUT_DIR / "benchmark_support_calibration.csv",
            support_rows,
            list(support_rows[0].keys()) if support_rows else [],
        )
        write_csv(
            OUTPUT_DIR / "school_candidate_sensitivity.csv",
            sensitivity_rows,
            list(sensitivity_rows[0].keys()) if sensitivity_rows else [],
        )

        policy_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM frozen_benchmark_policy
            """
        )
        write_csv(
            OUTPUT_DIR / "frozen_benchmark_policy.csv",
            policy_rows,
            list(policy_rows[0].keys()) if policy_rows else [],
        )

        extreme_value_added = fetch_dicts(
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
                baseline_stable_level,
                endpoint_stable_level,
                observed_improvement,
                expected_improvement,
                athlete_value_added,
                annualized_athlete_value_added,
                training_support_n,
                recommended_resolution,
                trajectory_reliability_tier,
                crossfit_fold
            FROM expected_improvement_scored_trajectories
            ORDER BY
                ABS(athlete_value_added) DESC,
                trajectory_id
            LIMIT 500
            """
        )

        write_csv(
            OUTPUT_DIR / "extreme_value_added_review.csv",
            extreme_value_added,
            list(extreme_value_added[0].keys())
                if extreme_value_added else [],
        )

        summary_rows = [
            {
                "metric": "selected_candidate",
                "value": SELECTED_CANDIDATE,
            },
            {
                "metric": "trajectory_rows",
                "value": counts["trajectory_rows"],
            },
            {
                "metric": "athlete_count",
                "value": counts["athlete_count"],
            },
            {
                "metric": "school_count",
                "value": counts["school_count"],
            },
            {
                "metric": "above_expected_rows",
                "value": counts["above_expected_rows"],
            },
            {
                "metric": "below_expected_rows",
                "value": counts["below_expected_rows"],
            },
            {
                "metric": "mean_observed_improvement",
                "value": counts["mean_observed_improvement"],
            },
            {
                "metric": "mean_expected_improvement",
                "value": counts["mean_expected_improvement"],
            },
            {
                "metric": "mean_value_added",
                "value": counts["mean_value_added"],
            },
            {
                "metric": "median_value_added",
                "value": counts["median_value_added"],
            },
            {
                "metric": "mae",
                "value": counts["mae"],
            },
            {
                "metric": "rmse",
                "value": counts["rmse"],
            },
            {
                "metric": "prediction_correlation",
                "value": counts["prediction_correlation"],
            },
            {
                "metric": "calibration_slope",
                "value": counts["calibration_slope"],
            },
            {
                "metric": "calibration_intercept",
                "value": counts["calibration_intercept"],
            },
            {
                "metric": "max_abs_fold_bias",
                "value": calibration_maxima["max_abs_fold_bias"],
            },
            {
                "metric": "max_abs_duration_bias",
                "value": calibration_maxima["max_abs_duration_bias"],
            },
            {
                "metric": "max_abs_resolution_bias",
                "value": calibration_maxima["max_abs_resolution_bias"],
            },
            {
                "metric":
                    "selected_winsorized_school_correlation",
                "value":
                    sensitivity[
                        "selected_winsorized_school_correlation"
                    ],
            },
            {
                "metric":
                    "selected_hierarchical_school_correlation",
                "value":
                    sensitivity[
                        "selected_hierarchical_school_correlation"
                    ],
            },
            {
                "metric":
                    "mean_abs_rank_difference_winsorized",
                "value":
                    sensitivity[
                        "mean_abs_rank_difference_winsorized"
                    ],
            },
            {
                "metric":
                    "mean_abs_rank_difference_hierarchical",
                "value":
                    sensitivity[
                        "mean_abs_rank_difference_hierarchical"
                    ],
            },
        ]

        write_csv(
            OUTPUT_DIR / "phase_5e_summary.csv",
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
                "dataset_version": DATASET_VERSION,
                "policy_version": POLICY_VERSION,
                "selected_candidate": SELECTED_CANDIDATE,
            }
        ],
        [
            "output_name",
            "path",
            "size_bytes",
            "sha256",
            "dataset_version",
            "policy_version",
            "selected_candidate",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 5 PHASE 5E — FROZEN EXPECTED-IMPROVEMENT BENCHMARK",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "FROZEN POLICY",
        "-" * 78,
        f"Selected benchmark: {SELECTED_CANDIDATE}",
        "Expected improvement is generated from school-held-out",
        "cross-fitted training statistics.",
        "Athlete value added equals observed improvement minus",
        "expected improvement.",
        "",
        "RESULTS",
        "-" * 78,
        f"Scored trajectories: {int(counts['trajectory_rows']):,}",
        f"Unique athletes: {int(counts['athlete_count']):,}",
        f"Schools represented: {int(counts['school_count']):,}",
        f"Above-expected trajectories: "
        f"{int(counts['above_expected_rows']):,}",
        f"Below-expected trajectories: "
        f"{int(counts['below_expected_rows']):,}",
        f"Mean value added: "
        f"{float(counts['mean_value_added']):.6f}",
        f"MAE: {float(counts['mae']):.6f}",
        f"RMSE: {float(counts['rmse']):.6f}",
        f"Calibration slope: "
        f"{float(counts['calibration_slope']):.6f}",
        f"Maximum absolute fold bias: "
        f"{float(calibration_maxima['max_abs_fold_bias']):.6f}",
        f"Maximum absolute duration bias: "
        f"{float(calibration_maxima['max_abs_duration_bias']):.6f}",
        f"Maximum absolute resolution bias: "
        f"{float(calibration_maxima['max_abs_resolution_bias']):.6f}",
        "",
        "SENSITIVITY",
        "-" * 78,
        "Selected vs winsorized hierarchical school correlation: "
        f"{float(sensitivity['selected_winsorized_school_correlation']):.6f}",
        "Selected vs hierarchical school correlation: "
        f"{float(sensitivity['selected_hierarchical_school_correlation']):.6f}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Expected-improvement benchmark frozen."
            if not failed
            else "FAIL — Do not aggregate value added into rankings."
        ),
        "",
        "NEXT",
        "-" * 78,
        "Deduplicate multi-event athlete contributions and aggregate",
        "trajectory value added to athlete, event-family, and school levels.",
    ]

    (OUTPUT_DIR / "phase_5e_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Selected benchmark: {SELECTED_CANDIDATE}")
    print(
        f"Scored trajectories: {int(counts['trajectory_rows']):,}"
    )
    print(
        f"Unique athletes: {int(counts['athlete_count']):,}"
    )
    print(
        f"Schools represented: {int(counts['school_count']):,}"
    )
    print(
        f"Mean value added: "
        f"{float(counts['mean_value_added']):.6f}"
    )
    print(
        f"Calibration slope: "
        f"{float(counts['calibration_slope']):.6f}"
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
    print("Next: aggregate athlete value added into school rankings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
