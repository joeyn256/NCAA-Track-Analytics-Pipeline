#!/usr/bin/env python3
"""
Milestone 5 Phase 5D — Cross-Fitted Expected-Improvement Benchmarks

Fits and compares interpretable expected-improvement benchmarks using the
frozen Phase 5C cohort.

Every prediction is cross-fitted by school:
- each school belongs to exactly one fold;
- a trajectory is predicted only from summary statistics built without its
  school's fold.

Candidate benchmarks
--------------------
1. naive_fold_mean
2. resolution_raw_mean
3. hierarchical_mean_moderate
4. hierarchical_mean_strong
5. hierarchical_winsorized_moderate

The hierarchy is:
overall training mean
→ gender × season type × elapsed seasons
→ baseline-level band
→ event family
→ event

The Phase 5C recommended resolution determines whether the final prediction
uses the event, event-family, or broader baseline-duration estimate.

This phase compares candidates and recommends a winner. It does not yet freeze
the expected-improvement policy or create athlete value-added scores.
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
      "phase_5c_frozen_expected_improvement_cohort/"
      "expected_improvement_cohort_v1.duckdb"
)

PHASE_5C_CHECKS = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5c_frozen_expected_improvement_cohort/"
      "hard_checks.csv"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5d_expected_improvement_benchmark_comparison"
)

OUTPUT_DB = OUTPUT_DIR / "expected_improvement_benchmarks_v1.duckdb"

INPUT_DATASET_VERSION = "expected_improvement_cohort_v1"
INPUT_POLICY_VERSION = "expected_improvement_cohort_policy_v1"
DATASET_VERSION = "expected_improvement_benchmarks_v1_2"
BENCHMARK_POLICY_VERSION = "expected_improvement_benchmark_comparison_v1_2"

EXPECTED_COHORT_ROWS = 189_703
EXPECTED_SCHOOLS = 361
EXPECTED_FOLDS = 5
EXPECTED_CANDIDATES = 5
EXPECTED_PREDICTION_ROWS = EXPECTED_COHORT_ROWS * EXPECTED_CANDIDATES

WINSOR_LOWER = 0.005
WINSOR_UPPER = 0.995

# Moderate shrinkage strengths.
MODERATE_COARSE_PRIOR = 250.0
MODERATE_GLOBAL_PRIOR = 100.0
MODERATE_FAMILY_PRIOR = 75.0
MODERATE_EVENT_PRIOR = 50.0

# Strong shrinkage strengths.
STRONG_COARSE_PRIOR = 1000.0
STRONG_GLOBAL_PRIOR = 500.0
STRONG_FAMILY_PRIOR = 250.0
STRONG_EVENT_PRIOR = 100.0


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

    print("MILESTONE 5 PHASE 5D — EXPECTED-IMPROVEMENT BENCHMARKS")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Input database: {INPUT_DB}")
    print(f"Output database: {OUTPUT_DB}")
    print(f"Candidate models: {EXPECTED_CANDIDATES}")

    required_inputs = [INPUT_DB, PHASE_5C_CHECKS]
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
        print("PHASE GATE: FAIL — Required input missing.")
        return 1

    phase_5c_checks = read_csv(PHASE_5C_CHECKS)
    failed_phase_5c_checks = [
        row
        for row in phase_5c_checks
        if row.get("status") != "PASS"
    ]

    add_check(
        checks,
        "phase_5c_gate_passed",
        not failed_phase_5c_checks,
        [
            row.get("check_name")
            for row in failed_phase_5c_checks
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
                AS cohort_source (READ_ONLY)
            """
        )

        metadata = {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM cohort_source.main.dataset_metadata
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
            metadata.get("cohort_policy_version")
            == INPUT_POLICY_VERSION,
            metadata.get("cohort_policy_version"),
            INPUT_POLICY_VERSION,
        )

        con.execute(
            """
            CREATE TABLE modeling_cohort_snapshot AS
            SELECT *
            FROM cohort_source.main.modeling_cohort
            """
        )

        # Build training rows for every held-out fold. A source row appears in
        # the four folds in which it is eligible for training.
        con.execute(
            f"""
            CREATE TABLE crossfit_training_rows AS
            WITH folds(holdout_fold) AS (
                VALUES (1), (2), (3), (4), (5)
            ),
            event_caps AS (
                SELECT
                    f.holdout_fold,
                    c.season_type,
                    c.canonical_gender_code,
                    c.canonical_event_code,
                    QUANTILE_CONT(
                        c.observed_improvement,
                        {WINSOR_LOWER}
                    ) AS lower_cap,
                    QUANTILE_CONT(
                        c.observed_improvement,
                        {WINSOR_UPPER}
                    ) AS upper_cap
                FROM modeling_cohort_snapshot c
                CROSS JOIN folds f
                WHERE c.crossfit_fold <> f.holdout_fold
                GROUP BY
                    f.holdout_fold,
                    c.season_type,
                    c.canonical_gender_code,
                    c.canonical_event_code
            )
            SELECT
                f.holdout_fold,
                c.crossfit_fold AS source_fold,
                c.trajectory_id,
                c.resolved_school_id,
                c.canonical_person_id,
                c.season_type,
                c.canonical_gender_code,
                c.canonical_event_code,
                c.event_family,
                c.elapsed_seasons,
                c.baseline_level_band,
                c.baseline_stable_level,
                c.observed_improvement,
                LEAST(
                    caps.upper_cap,
                    GREATEST(
                        caps.lower_cap,
                        c.observed_improvement
                    )
                ) AS winsorized_observed_improvement
            FROM modeling_cohort_snapshot c
            CROSS JOIN folds f
            JOIN event_caps caps
              ON caps.holdout_fold = f.holdout_fold
             AND caps.season_type = c.season_type
             AND caps.canonical_gender_code =
                    c.canonical_gender_code
             AND caps.canonical_event_code =
                    c.canonical_event_code
            WHERE c.crossfit_fold <> f.holdout_fold
            """
        )

        con.execute(
            """
            CREATE TABLE crossfit_overall_stats AS
            SELECT
                holdout_fold,
                COUNT(*) AS overall_n,
                AVG(observed_improvement) AS overall_mean,
                MEDIAN(observed_improvement) AS overall_median,
                AVG(winsorized_observed_improvement)
                    AS overall_winsorized_mean,
                STDDEV_SAMP(observed_improvement) AS overall_sd
            FROM crossfit_training_rows
            GROUP BY holdout_fold
            """
        )

        con.execute(
            """
            CREATE TABLE crossfit_coarse_stats AS
            SELECT
                holdout_fold,
                season_type,
                canonical_gender_code,
                elapsed_seasons,
                COUNT(*) AS coarse_n,
                AVG(observed_improvement) AS coarse_mean,
                MEDIAN(observed_improvement) AS coarse_median,
                AVG(winsorized_observed_improvement)
                    AS coarse_winsorized_mean,
                STDDEV_SAMP(observed_improvement) AS coarse_sd
            FROM crossfit_training_rows
            GROUP BY
                holdout_fold,
                season_type,
                canonical_gender_code,
                elapsed_seasons
            """
        )

        con.execute(
            """
            CREATE TABLE crossfit_global_cell_stats AS
            SELECT
                holdout_fold,
                season_type,
                canonical_gender_code,
                elapsed_seasons,
                baseline_level_band,
                COUNT(*) AS global_n,
                AVG(observed_improvement) AS global_mean,
                MEDIAN(observed_improvement) AS global_median,
                AVG(winsorized_observed_improvement)
                    AS global_winsorized_mean,
                STDDEV_SAMP(observed_improvement) AS global_sd
            FROM crossfit_training_rows
            GROUP BY
                holdout_fold,
                season_type,
                canonical_gender_code,
                elapsed_seasons,
                baseline_level_band
            """
        )

        con.execute(
            """
            CREATE TABLE crossfit_family_cell_stats AS
            SELECT
                holdout_fold,
                season_type,
                canonical_gender_code,
                event_family,
                elapsed_seasons,
                baseline_level_band,
                COUNT(*) AS family_n,
                AVG(observed_improvement) AS family_mean,
                MEDIAN(observed_improvement) AS family_median,
                AVG(winsorized_observed_improvement)
                    AS family_winsorized_mean,
                STDDEV_SAMP(observed_improvement) AS family_sd
            FROM crossfit_training_rows
            GROUP BY
                holdout_fold,
                season_type,
                canonical_gender_code,
                event_family,
                elapsed_seasons,
                baseline_level_band
            """
        )

        con.execute(
            """
            CREATE TABLE crossfit_event_cell_stats AS
            SELECT
                holdout_fold,
                season_type,
                canonical_gender_code,
                canonical_event_code,
                elapsed_seasons,
                baseline_level_band,
                COUNT(*) AS event_n,
                AVG(observed_improvement) AS event_mean,
                MEDIAN(observed_improvement) AS event_median,
                AVG(winsorized_observed_improvement)
                    AS event_winsorized_mean,
                STDDEV_SAMP(observed_improvement) AS event_sd
            FROM crossfit_training_rows
            GROUP BY
                holdout_fold,
                season_type,
                canonical_gender_code,
                canonical_event_code,
                elapsed_seasons,
                baseline_level_band
            """
        )

        con.execute(
            f"""
            CREATE TABLE prediction_components AS
            WITH joined AS (
                SELECT
                    c.*,
                    o.overall_n,
                    o.overall_mean,
                    o.overall_median,
                    o.overall_winsorized_mean,
                    o.overall_sd,
                    cr.coarse_n,
                    cr.coarse_mean,
                    cr.coarse_median,
                    cr.coarse_winsorized_mean,
                    cr.coarse_sd,
                    g.global_n,
                    g.global_mean,
                    g.global_median,
                    g.global_winsorized_mean,
                    g.global_sd,
                    fam.family_n,
                    fam.family_mean,
                    fam.family_median,
                    fam.family_winsorized_mean,
                    fam.family_sd,
                    ev.event_n,
                    ev.event_mean,
                    ev.event_median,
                    ev.event_winsorized_mean,
                    ev.event_sd
                FROM modeling_cohort_snapshot c
                JOIN crossfit_overall_stats o
                  ON o.holdout_fold = c.crossfit_fold
                LEFT JOIN crossfit_coarse_stats cr
                  ON cr.holdout_fold = c.crossfit_fold
                 AND cr.season_type = c.season_type
                 AND cr.canonical_gender_code =
                        c.canonical_gender_code
                 AND cr.elapsed_seasons = c.elapsed_seasons
                LEFT JOIN crossfit_global_cell_stats g
                  ON g.holdout_fold = c.crossfit_fold
                 AND g.season_type = c.season_type
                 AND g.canonical_gender_code =
                        c.canonical_gender_code
                 AND g.elapsed_seasons = c.elapsed_seasons
                 AND g.baseline_level_band =
                        c.baseline_level_band
                LEFT JOIN crossfit_family_cell_stats fam
                  ON fam.holdout_fold = c.crossfit_fold
                 AND fam.season_type = c.season_type
                 AND fam.canonical_gender_code =
                        c.canonical_gender_code
                 AND fam.event_family = c.event_family
                 AND fam.elapsed_seasons = c.elapsed_seasons
                 AND fam.baseline_level_band =
                        c.baseline_level_band
                LEFT JOIN crossfit_event_cell_stats ev
                  ON ev.holdout_fold = c.crossfit_fold
                 AND ev.season_type = c.season_type
                 AND ev.canonical_gender_code =
                        c.canonical_gender_code
                 AND ev.canonical_event_code =
                        c.canonical_event_code
                 AND ev.elapsed_seasons = c.elapsed_seasons
                 AND ev.baseline_level_band =
                        c.baseline_level_band
            ),
            moderate AS (
                SELECT
                    *,
                    (
                        COALESCE(coarse_n, 0) *
                            COALESCE(coarse_mean, overall_mean)
                        + {MODERATE_COARSE_PRIOR} * overall_mean
                    )
                    / (
                        COALESCE(coarse_n, 0)
                        + {MODERATE_COARSE_PRIOR}
                    ) AS moderate_coarse_mean,

                    (
                        COALESCE(coarse_n, 0) *
                            COALESCE(
                                coarse_winsorized_mean,
                                overall_winsorized_mean
                            )
                        + {MODERATE_COARSE_PRIOR}
                            * overall_winsorized_mean
                    )
                    / (
                        COALESCE(coarse_n, 0)
                        + {MODERATE_COARSE_PRIOR}
                    ) AS moderate_coarse_winsorized_mean
                FROM joined
            ),
            moderate_global AS (
                SELECT
                    *,
                    (
                        COALESCE(global_n, 0) *
                            COALESCE(
                                global_mean,
                                moderate_coarse_mean
                            )
                        + {MODERATE_GLOBAL_PRIOR}
                            * moderate_coarse_mean
                    )
                    / (
                        COALESCE(global_n, 0)
                        + {MODERATE_GLOBAL_PRIOR}
                    ) AS moderate_global_mean,

                    (
                        COALESCE(global_n, 0) *
                            COALESCE(
                                global_winsorized_mean,
                                moderate_coarse_winsorized_mean
                            )
                        + {MODERATE_GLOBAL_PRIOR}
                            * moderate_coarse_winsorized_mean
                    )
                    / (
                        COALESCE(global_n, 0)
                        + {MODERATE_GLOBAL_PRIOR}
                    ) AS moderate_global_winsorized_mean
                FROM moderate
            ),
            moderate_family AS (
                SELECT
                    *,
                    (
                        COALESCE(family_n, 0) *
                            COALESCE(
                                family_mean,
                                moderate_global_mean
                            )
                        + {MODERATE_FAMILY_PRIOR}
                            * moderate_global_mean
                    )
                    / (
                        COALESCE(family_n, 0)
                        + {MODERATE_FAMILY_PRIOR}
                    ) AS moderate_family_mean,

                    (
                        COALESCE(family_n, 0) *
                            COALESCE(
                                family_winsorized_mean,
                                moderate_global_winsorized_mean
                            )
                        + {MODERATE_FAMILY_PRIOR}
                            * moderate_global_winsorized_mean
                    )
                    / (
                        COALESCE(family_n, 0)
                        + {MODERATE_FAMILY_PRIOR}
                    ) AS moderate_family_winsorized_mean
                FROM moderate_global
            ),
            moderate_event AS (
                SELECT
                    *,
                    (
                        COALESCE(event_n, 0) *
                            COALESCE(
                                event_mean,
                                moderate_family_mean
                            )
                        + {MODERATE_EVENT_PRIOR}
                            * moderate_family_mean
                    )
                    / (
                        COALESCE(event_n, 0)
                        + {MODERATE_EVENT_PRIOR}
                    ) AS moderate_event_mean,

                    (
                        COALESCE(event_n, 0) *
                            COALESCE(
                                event_winsorized_mean,
                                moderate_family_winsorized_mean
                            )
                        + {MODERATE_EVENT_PRIOR}
                            * moderate_family_winsorized_mean
                    )
                    / (
                        COALESCE(event_n, 0)
                        + {MODERATE_EVENT_PRIOR}
                    ) AS moderate_event_winsorized_mean
                FROM moderate_family
            ),
            strong AS (
                SELECT
                    *,
                    (
                        COALESCE(coarse_n, 0) *
                            COALESCE(coarse_mean, overall_mean)
                        + {STRONG_COARSE_PRIOR} * overall_mean
                    )
                    / (
                        COALESCE(coarse_n, 0)
                        + {STRONG_COARSE_PRIOR}
                    ) AS strong_coarse_mean
                FROM moderate_event
            ),
            strong_global AS (
                SELECT
                    *,
                    (
                        COALESCE(global_n, 0) *
                            COALESCE(
                                global_mean,
                                strong_coarse_mean
                            )
                        + {STRONG_GLOBAL_PRIOR}
                            * strong_coarse_mean
                    )
                    / (
                        COALESCE(global_n, 0)
                        + {STRONG_GLOBAL_PRIOR}
                    ) AS strong_global_mean
                FROM strong
            ),
            strong_family AS (
                SELECT
                    *,
                    (
                        COALESCE(family_n, 0) *
                            COALESCE(
                                family_mean,
                                strong_global_mean
                            )
                        + {STRONG_FAMILY_PRIOR}
                            * strong_global_mean
                    )
                    / (
                        COALESCE(family_n, 0)
                        + {STRONG_FAMILY_PRIOR}
                    ) AS strong_family_mean
                FROM strong_global
            )
            SELECT
                *,
                (
                    COALESCE(event_n, 0) *
                        COALESCE(
                            event_mean,
                            strong_family_mean
                        )
                    + {STRONG_EVENT_PRIOR}
                        * strong_family_mean
                )
                / (
                    COALESCE(event_n, 0)
                    + {STRONG_EVENT_PRIOR}
                ) AS strong_event_mean
            FROM strong_family
            """
        )

        con.execute(
            """
            CREATE TABLE candidate_predictions_wide AS
            SELECT
                *,
                overall_mean AS pred_naive_fold_mean,

                CASE recommended_resolution
                    WHEN 'event_level'
                        THEN COALESCE(
                            event_mean,
                            family_mean,
                            global_mean,
                            coarse_mean,
                            overall_mean
                        )
                    WHEN 'event_family_level'
                        THEN COALESCE(
                            family_mean,
                            global_mean,
                            coarse_mean,
                            overall_mean
                        )
                    ELSE COALESCE(
                        global_mean,
                        coarse_mean,
                        overall_mean
                    )
                END AS pred_resolution_raw_mean,

                CASE recommended_resolution
                    WHEN 'event_level'
                        THEN moderate_event_mean
                    WHEN 'event_family_level'
                        THEN moderate_family_mean
                    ELSE moderate_global_mean
                END AS pred_hierarchical_mean_moderate,

                CASE recommended_resolution
                    WHEN 'event_level'
                        THEN strong_event_mean
                    WHEN 'event_family_level'
                        THEN strong_family_mean
                    ELSE strong_global_mean
                END AS pred_hierarchical_mean_strong,

                CASE recommended_resolution
                    WHEN 'event_level'
                        THEN moderate_event_winsorized_mean
                    WHEN 'event_family_level'
                        THEN moderate_family_winsorized_mean
                    ELSE moderate_global_winsorized_mean
                END AS pred_hierarchical_winsorized_moderate
            FROM prediction_components
            """
        )

        con.execute(
            f"""
            CREATE TABLE candidate_predictions AS
            SELECT
                trajectory_id,
                resolved_school_id,
                canonical_person_id,
                athlete_name,
                school_stint_id,
                canonical_gender_code,
                season_type,
                canonical_event_code,
                canonical_event_name,
                event_family,
                baseline_stable_level,
                baseline_level_band,
                elapsed_seasons,
                qualifying_period_count,
                observed_improvement,
                crossfit_fold,
                recommended_resolution,
                'naive_fold_mean' AS candidate_name,
                pred_naive_fold_mean AS expected_improvement,
                observed_improvement - pred_naive_fold_mean
                    AS residual_value_added,
                overall_n AS training_support_n,
                '{DATASET_VERSION}' AS dataset_version
            FROM candidate_predictions_wide

            UNION ALL

            SELECT
                trajectory_id,
                resolved_school_id,
                canonical_person_id,
                athlete_name,
                school_stint_id,
                canonical_gender_code,
                season_type,
                canonical_event_code,
                canonical_event_name,
                event_family,
                baseline_stable_level,
                baseline_level_band,
                elapsed_seasons,
                qualifying_period_count,
                observed_improvement,
                crossfit_fold,
                recommended_resolution,
                'resolution_raw_mean',
                pred_resolution_raw_mean,
                observed_improvement - pred_resolution_raw_mean,
                CASE recommended_resolution
                    WHEN 'event_level'
                        THEN COALESCE(
                            event_n,
                            family_n,
                            global_n,
                            coarse_n,
                            overall_n
                        )
                    WHEN 'event_family_level'
                        THEN COALESCE(
                            family_n,
                            global_n,
                            coarse_n,
                            overall_n
                        )
                    ELSE COALESCE(
                        global_n,
                        coarse_n,
                        overall_n
                    )
                END,
                '{DATASET_VERSION}'
            FROM candidate_predictions_wide

            UNION ALL

            SELECT
                trajectory_id,
                resolved_school_id,
                canonical_person_id,
                athlete_name,
                school_stint_id,
                canonical_gender_code,
                season_type,
                canonical_event_code,
                canonical_event_name,
                event_family,
                baseline_stable_level,
                baseline_level_band,
                elapsed_seasons,
                qualifying_period_count,
                observed_improvement,
                crossfit_fold,
                recommended_resolution,
                'hierarchical_mean_moderate',
                pred_hierarchical_mean_moderate,
                observed_improvement
                    - pred_hierarchical_mean_moderate,
                CASE recommended_resolution
                    WHEN 'event_level'
                        THEN COALESCE(
                            event_n,
                            family_n,
                            global_n,
                            coarse_n,
                            overall_n
                        )
                    WHEN 'event_family_level'
                        THEN COALESCE(
                            family_n,
                            global_n,
                            coarse_n,
                            overall_n
                        )
                    ELSE COALESCE(
                        global_n,
                        coarse_n,
                        overall_n
                    )
                END,
                '{DATASET_VERSION}'
            FROM candidate_predictions_wide

            UNION ALL

            SELECT
                trajectory_id,
                resolved_school_id,
                canonical_person_id,
                athlete_name,
                school_stint_id,
                canonical_gender_code,
                season_type,
                canonical_event_code,
                canonical_event_name,
                event_family,
                baseline_stable_level,
                baseline_level_band,
                elapsed_seasons,
                qualifying_period_count,
                observed_improvement,
                crossfit_fold,
                recommended_resolution,
                'hierarchical_mean_strong',
                pred_hierarchical_mean_strong,
                observed_improvement
                    - pred_hierarchical_mean_strong,
                CASE recommended_resolution
                    WHEN 'event_level'
                        THEN COALESCE(
                            event_n,
                            family_n,
                            global_n,
                            coarse_n,
                            overall_n
                        )
                    WHEN 'event_family_level'
                        THEN COALESCE(
                            family_n,
                            global_n,
                            coarse_n,
                            overall_n
                        )
                    ELSE COALESCE(
                        global_n,
                        coarse_n,
                        overall_n
                    )
                END,
                '{DATASET_VERSION}'
            FROM candidate_predictions_wide

            UNION ALL

            SELECT
                trajectory_id,
                resolved_school_id,
                canonical_person_id,
                athlete_name,
                school_stint_id,
                canonical_gender_code,
                season_type,
                canonical_event_code,
                canonical_event_name,
                event_family,
                baseline_stable_level,
                baseline_level_band,
                elapsed_seasons,
                qualifying_period_count,
                observed_improvement,
                crossfit_fold,
                recommended_resolution,
                'hierarchical_winsorized_moderate',
                pred_hierarchical_winsorized_moderate,
                observed_improvement
                    - pred_hierarchical_winsorized_moderate,
                CASE recommended_resolution
                    WHEN 'event_level'
                        THEN COALESCE(
                            event_n,
                            family_n,
                            global_n,
                            coarse_n,
                            overall_n
                        )
                    WHEN 'event_family_level'
                        THEN COALESCE(
                            family_n,
                            global_n,
                            coarse_n,
                            overall_n
                        )
                    ELSE COALESCE(
                        global_n,
                        coarse_n,
                        overall_n
                    )
                END,
                '{DATASET_VERSION}'
            FROM candidate_predictions_wide
            """
        )

        con.execute(
            """
            CREATE TABLE candidate_overall_metrics AS
            WITH base AS (
                SELECT
                    candidate_name,
                    COUNT(*) AS prediction_count,
                    AVG(ABS(residual_value_added)) AS mae,
                    SQRT(AVG(POWER(residual_value_added, 2)))
                        AS rmse,
                    MEDIAN(ABS(residual_value_added))
                        AS median_absolute_error,
                    AVG(residual_value_added) AS mean_bias,
                    MEDIAN(residual_value_added) AS median_bias,
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
                    ) AS calibration_intercept,
                    1
                    - SUM(POWER(residual_value_added, 2))
                      / NULLIF(
                            SUM(
                                POWER(
                                    observed_improvement
                                    - (
                                        SELECT AVG(observed_improvement)
                                        FROM modeling_cohort_snapshot
                                    ),
                                    2
                                )
                            ),
                            0
                        ) AS r_squared
                FROM candidate_predictions
                GROUP BY candidate_name
            )
            SELECT
                *,
                DENSE_RANK() OVER (
                    ORDER BY mae, rmse
                ) AS mae_rank,
                DENSE_RANK() OVER (
                    ORDER BY rmse, mae
                ) AS rmse_rank
            FROM base
            ORDER BY mae_rank, rmse_rank, candidate_name
            """
        )

        con.execute(
            """
            CREATE TABLE candidate_fold_metrics AS
            SELECT
                candidate_name,
                crossfit_fold,
                COUNT(*) AS prediction_count,
                AVG(ABS(residual_value_added)) AS mae,
                SQRT(AVG(POWER(residual_value_added, 2)))
                    AS rmse,
                MEDIAN(ABS(residual_value_added))
                    AS median_absolute_error,
                AVG(residual_value_added) AS mean_bias,
                CORR(
                    observed_improvement,
                    expected_improvement
                ) AS prediction_correlation
            FROM candidate_predictions
            GROUP BY candidate_name, crossfit_fold
            ORDER BY candidate_name, crossfit_fold
            """
        )

        con.execute(
            """
            CREATE TABLE candidate_resolution_metrics AS
            SELECT
                candidate_name,
                recommended_resolution,
                COUNT(*) AS prediction_count,
                AVG(ABS(residual_value_added)) AS mae,
                SQRT(AVG(POWER(residual_value_added, 2)))
                    AS rmse,
                MEDIAN(ABS(residual_value_added))
                    AS median_absolute_error,
                AVG(residual_value_added) AS mean_bias
            FROM candidate_predictions
            GROUP BY candidate_name, recommended_resolution
            ORDER BY candidate_name, recommended_resolution
            """
        )

        con.execute(
            """
            CREATE TABLE candidate_baseline_calibration AS
            SELECT
                candidate_name,
                canonical_gender_code,
                season_type,
                baseline_level_band,
                COUNT(*) AS prediction_count,
                AVG(baseline_stable_level)
                    AS mean_baseline_level,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                AVG(expected_improvement)
                    AS mean_expected_improvement,
                AVG(residual_value_added)
                    AS mean_residual_value_added,
                AVG(ABS(residual_value_added)) AS mae
            FROM candidate_predictions
            GROUP BY
                candidate_name,
                canonical_gender_code,
                season_type,
                baseline_level_band
            ORDER BY
                candidate_name,
                canonical_gender_code,
                season_type,
                baseline_level_band
            """
        )

        con.execute(
            """
            CREATE TABLE candidate_duration_calibration AS
            SELECT
                candidate_name,
                elapsed_seasons,
                COUNT(*) AS prediction_count,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                AVG(expected_improvement)
                    AS mean_expected_improvement,
                AVG(residual_value_added)
                    AS mean_residual_value_added,
                AVG(ABS(residual_value_added)) AS mae,
                SQRT(AVG(POWER(residual_value_added, 2)))
                    AS rmse
            FROM candidate_predictions
            GROUP BY candidate_name, elapsed_seasons
            ORDER BY candidate_name, elapsed_seasons
            """
        )

        con.execute(
            """
            CREATE TABLE candidate_event_family_calibration AS
            SELECT
                candidate_name,
                canonical_gender_code,
                season_type,
                event_family,
                COUNT(*) AS prediction_count,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                AVG(expected_improvement)
                    AS mean_expected_improvement,
                AVG(residual_value_added)
                    AS mean_residual_value_added,
                AVG(ABS(residual_value_added)) AS mae,
                SQRT(AVG(POWER(residual_value_added, 2)))
                    AS rmse
            FROM candidate_predictions
            GROUP BY
                candidate_name,
                canonical_gender_code,
                season_type,
                event_family
            ORDER BY
                candidate_name,
                canonical_gender_code,
                season_type,
                event_family
            """
        )

        con.execute(
            """
            CREATE TABLE candidate_recommendation AS
            WITH ranked AS (
                SELECT
                    *,
                    FIRST_VALUE(mae) OVER (
                        ORDER BY mae, rmse
                    ) AS best_mae,
                    FIRST_VALUE(candidate_name) OVER (
                        ORDER BY mae, rmse
                    ) AS recommended_candidate
                FROM candidate_overall_metrics
            ),
            naive AS (
                SELECT
                    mae AS naive_mae,
                    rmse AS naive_rmse
                FROM candidate_overall_metrics
                WHERE candidate_name = 'naive_fold_mean'
            )
            SELECT
                r.candidate_name,
                r.prediction_count,
                r.mae,
                r.rmse,
                r.median_absolute_error,
                r.mean_bias,
                r.prediction_correlation,
                r.calibration_slope,
                r.calibration_intercept,
                r.r_squared,
                r.mae_rank,
                r.rmse_rank,
                n.naive_mae,
                n.naive_rmse,
                n.naive_mae - r.mae AS mae_improvement_vs_naive,
                n.naive_rmse - r.rmse AS rmse_improvement_vs_naive,
                r.candidate_name = r.recommended_candidate
                    AS recommended_for_freeze,
                CASE
                    WHEN r.candidate_name =
                        r.recommended_candidate
                        THEN
                            'Lowest cross-fitted MAE with RMSE '
                            || 'as the tie-breaker.'
                    ELSE
                        'Comparison candidate.'
                END AS recommendation_reason
            FROM ranked r
            CROSS JOIN naive n
            ORDER BY r.mae_rank, r.rmse_rank, r.candidate_name
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
                'benchmark_policy_version',
                '{BENCHMARK_POLICY_VERSION}'
            UNION ALL
            SELECT
                'input_cohort_version',
                '{INPUT_DATASET_VERSION}'
            UNION ALL
            SELECT
                'candidate_count',
                '{EXPECTED_CANDIDATES}'
            UNION ALL
            SELECT
                'school_grouped_crossfit_folds',
                '{EXPECTED_FOLDS}'
            UNION ALL
            SELECT
                'winsor_limits',
                '{WINSOR_LOWER}-{WINSOR_UPPER}'
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
                (SELECT COUNT(*)
                 FROM modeling_cohort_snapshot)
                    AS cohort_rows,
                (SELECT COUNT(DISTINCT resolved_school_id)
                 FROM modeling_cohort_snapshot)
                    AS school_count,
                (SELECT COUNT(DISTINCT crossfit_fold)
                 FROM modeling_cohort_snapshot)
                    AS fold_count,
                (SELECT COUNT(*)
                 FROM crossfit_training_rows)
                    AS training_rows,
                (SELECT COUNT(*)
                 FROM candidate_predictions)
                    AS prediction_rows,
                (SELECT COUNT(DISTINCT candidate_name)
                 FROM candidate_predictions)
                    AS candidate_count,
                (SELECT COUNT(*)
                 FROM candidate_predictions
                 WHERE expected_improvement IS NULL
                    OR residual_value_added IS NULL)
                    AS null_prediction_rows,
                (SELECT COUNT(*)
                 FROM candidate_predictions
                 WHERE training_support_n IS NULL
                    OR training_support_n <= 0)
                    AS invalid_support_rows
            """
        )[0]

        quality = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM crossfit_training_rows
                 WHERE source_fold = holdout_fold)
                    AS same_fold_training_rows,
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        trajectory_id,
                        candidate_name,
                        COUNT(*) AS row_count
                    FROM candidate_predictions
                    GROUP BY trajectory_id, candidate_name
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_trajectory_candidate_rows,
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        trajectory_id,
                        COUNT(DISTINCT candidate_name)
                            AS candidate_count
                    FROM candidate_predictions
                    GROUP BY trajectory_id
                    HAVING COUNT(DISTINCT candidate_name)
                        <> {EXPECTED_CANDIDATES}
                 ))
                    AS incomplete_candidate_sets,
                (SELECT COUNT(*)
                 FROM candidate_overall_metrics)
                    AS overall_metric_rows,
                (SELECT COUNT(*)
                 FROM candidate_fold_metrics)
                    AS fold_metric_rows,
                (SELECT COUNT(*)
                 FROM candidate_recommendation
                 WHERE recommended_for_freeze)
                    AS recommended_candidate_rows
            """
        )[0]

        naive_metrics = con.execute(
            """
            SELECT mae, rmse
            FROM candidate_overall_metrics
            WHERE candidate_name = 'naive_fold_mean'
            """
        ).fetchone()

        best_structured_metrics = con.execute(
            """
            SELECT MIN(mae), MIN(rmse)
            FROM candidate_overall_metrics
            WHERE candidate_name <> 'naive_fold_mean'
            """
        ).fetchone()

        selected = fetch_dicts(
            con,
            """
            SELECT *
            FROM candidate_recommendation
            WHERE recommended_for_freeze
            """
        )

        fold_training_reconciliation = fetch_dicts(
            con,
            """
            WITH cohort AS (
                SELECT
                    crossfit_fold,
                    COUNT(*) AS holdout_rows
                FROM modeling_cohort_snapshot
                GROUP BY crossfit_fold
            ),
            training AS (
                SELECT
                    holdout_fold,
                    COUNT(*) AS training_rows
                FROM crossfit_training_rows
                GROUP BY holdout_fold
            ),
            total AS (
                SELECT COUNT(*) AS total_rows
                FROM modeling_cohort_snapshot
            )
            SELECT
                c.crossfit_fold,
                c.holdout_rows,
                t.training_rows,
                total.total_rows - c.holdout_rows
                    AS expected_training_rows,
                t.training_rows
                    = total.total_rows - c.holdout_rows
                    AS reconciles
            FROM cohort c
            JOIN training t
              ON t.holdout_fold = c.crossfit_fold
            CROSS JOIN total
            ORDER BY c.crossfit_fold
            """
        )

        add_check(
            checks,
            "cohort_row_count",
            counts["cohort_rows"] == EXPECTED_COHORT_ROWS,
            counts["cohort_rows"],
            EXPECTED_COHORT_ROWS,
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
            "candidate_count",
            counts["candidate_count"]
            == EXPECTED_CANDIDATES,
            counts["candidate_count"],
            EXPECTED_CANDIDATES,
        )
        add_check(
            checks,
            "prediction_row_count",
            counts["prediction_rows"]
            == EXPECTED_PREDICTION_ROWS,
            counts["prediction_rows"],
            EXPECTED_PREDICTION_ROWS,
        )
        add_check(
            checks,
            "no_same_fold_training_rows",
            quality["same_fold_training_rows"] == 0,
            quality["same_fold_training_rows"],
            0,
        )
        add_check(
            checks,
            "fold_training_counts_reconcile",
            all(row["reconciles"] for row in fold_training_reconciliation),
            [
                row
                for row in fold_training_reconciliation
                if not row["reconciles"]
            ],
            [],
        )
        add_check(
            checks,
            "no_null_predictions",
            counts["null_prediction_rows"] == 0,
            counts["null_prediction_rows"],
            0,
        )
        add_check(
            checks,
            "all_predictions_have_training_support",
            counts["invalid_support_rows"] == 0,
            counts["invalid_support_rows"],
            0,
        )
        add_check(
            checks,
            "trajectory_candidate_pairs_unique",
            quality["duplicate_trajectory_candidate_rows"] == 0,
            quality["duplicate_trajectory_candidate_rows"],
            0,
        )
        add_check(
            checks,
            "every_trajectory_has_all_candidates",
            quality["incomplete_candidate_sets"] == 0,
            quality["incomplete_candidate_sets"],
            0,
        )
        add_check(
            checks,
            "overall_metric_row_count",
            quality["overall_metric_rows"]
            == EXPECTED_CANDIDATES,
            quality["overall_metric_rows"],
            EXPECTED_CANDIDATES,
        )
        add_check(
            checks,
            "fold_metric_row_count",
            quality["fold_metric_rows"]
            == EXPECTED_CANDIDATES * EXPECTED_FOLDS,
            quality["fold_metric_rows"],
            EXPECTED_CANDIDATES * EXPECTED_FOLDS,
        )
        add_check(
            checks,
            "exactly_one_candidate_recommended",
            quality["recommended_candidate_rows"] == 1,
            quality["recommended_candidate_rows"],
            1,
        )
        add_check(
            checks,
            "structured_model_beats_naive_mae",
            best_structured_metrics[0] < naive_metrics[0],
            best_structured_metrics[0],
            f"less than naive MAE {naive_metrics[0]}",
        )
        add_check(
            checks,
            "structured_model_beats_naive_rmse",
            best_structured_metrics[1] < naive_metrics[1],
            best_structured_metrics[1],
            f"less than naive RMSE {naive_metrics[1]}",
        )

        overall_metrics = fetch_dicts(
            con,
            """
            SELECT *
            FROM candidate_overall_metrics
            ORDER BY mae_rank, rmse_rank, candidate_name
            """
        )

        fold_metrics = fetch_dicts(
            con,
            """
            SELECT *
            FROM candidate_fold_metrics
            ORDER BY candidate_name, crossfit_fold
            """
        )

        resolution_metrics = fetch_dicts(
            con,
            """
            SELECT *
            FROM candidate_resolution_metrics
            ORDER BY candidate_name, recommended_resolution
            """
        )

        baseline_calibration = fetch_dicts(
            con,
            """
            SELECT *
            FROM candidate_baseline_calibration
            ORDER BY
                candidate_name,
                canonical_gender_code,
                season_type,
                baseline_level_band
            """
        )

        duration_calibration = fetch_dicts(
            con,
            """
            SELECT *
            FROM candidate_duration_calibration
            ORDER BY candidate_name, elapsed_seasons
            """
        )

        family_calibration = fetch_dicts(
            con,
            """
            SELECT *
            FROM candidate_event_family_calibration
            ORDER BY
                candidate_name,
                canonical_gender_code,
                season_type,
                event_family
            """
        )

        recommendation_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM candidate_recommendation
            ORDER BY mae_rank, rmse_rank, candidate_name
            """
        )

        write_csv(
            OUTPUT_DIR / "candidate_overall_metrics.csv",
            overall_metrics,
            list(overall_metrics[0].keys()) if overall_metrics else [],
        )
        write_csv(
            OUTPUT_DIR / "candidate_fold_metrics.csv",
            fold_metrics,
            list(fold_metrics[0].keys()) if fold_metrics else [],
        )
        write_csv(
            OUTPUT_DIR / "candidate_resolution_metrics.csv",
            resolution_metrics,
            list(resolution_metrics[0].keys())
                if resolution_metrics else [],
        )
        write_csv(
            OUTPUT_DIR / "candidate_baseline_calibration.csv",
            baseline_calibration,
            list(baseline_calibration[0].keys())
                if baseline_calibration else [],
        )
        write_csv(
            OUTPUT_DIR / "candidate_duration_calibration.csv",
            duration_calibration,
            list(duration_calibration[0].keys())
                if duration_calibration else [],
        )
        write_csv(
            OUTPUT_DIR / "candidate_event_family_calibration.csv",
            family_calibration,
            list(family_calibration[0].keys())
                if family_calibration else [],
        )
        write_csv(
            OUTPUT_DIR / "candidate_recommendation.csv",
            recommendation_rows,
            list(recommendation_rows[0].keys())
                if recommendation_rows else [],
        )
        write_csv(
            OUTPUT_DIR / "fold_training_reconciliation.csv",
            fold_training_reconciliation,
            list(fold_training_reconciliation[0].keys())
                if fold_training_reconciliation else [],
        )

        sample_predictions = fetch_dicts(
            con,
            """
            SELECT *
            FROM candidate_predictions
            WHERE candidate_name = (
                SELECT candidate_name
                FROM candidate_recommendation
                WHERE recommended_for_freeze
            )
            ORDER BY
                ABS(residual_value_added) DESC,
                trajectory_id
            LIMIT 500
            """
        )

        write_csv(
            OUTPUT_DIR / "recommended_candidate_prediction_samples.csv",
            sample_predictions,
            list(sample_predictions[0].keys())
                if sample_predictions else [],
        )

        summary_rows = [
            {
                "metric": "cohort_rows",
                "value": counts["cohort_rows"],
            },
            {
                "metric": "school_count",
                "value": counts["school_count"],
            },
            {
                "metric": "crossfit_folds",
                "value": counts["fold_count"],
            },
            {
                "metric": "candidate_models",
                "value": counts["candidate_count"],
            },
            {
                "metric": "candidate_prediction_rows",
                "value": counts["prediction_rows"],
            },
            {
                "metric": "recommended_candidate",
                "value":
                    selected[0]["candidate_name"] if selected else "",
            },
            {
                "metric": "recommended_candidate_mae",
                "value": selected[0]["mae"] if selected else "",
            },
            {
                "metric": "recommended_candidate_rmse",
                "value": selected[0]["rmse"] if selected else "",
            },
            {
                "metric": "recommended_candidate_bias",
                "value": selected[0]["mean_bias"] if selected else "",
            },
            {
                "metric": "naive_mae",
                "value": naive_metrics[0],
            },
            {
                "metric": "naive_rmse",
                "value": naive_metrics[1],
            },
        ]

        write_csv(
            OUTPUT_DIR / "phase_5d_summary.csv",
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
                "benchmark_policy_version":
                    BENCHMARK_POLICY_VERSION,
            }
        ],
        [
            "output_name",
            "path",
            "size_bytes",
            "sha256",
            "dataset_version",
            "benchmark_policy_version",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    selected_name = (
        selected[0]["candidate_name"]
        if selected else "none"
    )
    selected_mae = (
        float(selected[0]["mae"])
        if selected else float("nan")
    )
    selected_rmse = (
        float(selected[0]["rmse"])
        if selected else float("nan")
    )

    report = [
        "MILESTONE 5 PHASE 5D — EXPECTED-IMPROVEMENT BENCHMARKS",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "CROSS-FITTING POLICY",
        "-" * 78,
        "Every school is predicted from training statistics built without",
        "that school's assigned fold.",
        "Five benchmark candidates were evaluated on identical held-out rows.",
        "",
        "CANDIDATE RESULTS",
        "-" * 78,
    ]

    for row in overall_metrics:
        report.append(
            f"{row['candidate_name']}: "
            f"MAE={float(row['mae']):.6f}, "
            f"RMSE={float(row['rmse']):.6f}, "
            f"bias={float(row['mean_bias']):.6f}, "
            f"R2={float(row['r_squared']):.6f}"
        )

    report.extend(
        [
            "",
            "RECOMMENDATION",
            "-" * 78,
            f"Recommended candidate: {selected_name}",
            f"Cross-fitted MAE: {selected_mae:.6f}",
            f"Cross-fitted RMSE: {selected_rmse:.6f}",
            "The recommendation is not frozen until calibration and",
            "sensitivity outputs are reviewed.",
            "",
            "PHASE GATE",
            "-" * 78,
            (
                "PASS — Cross-fitted benchmark candidates compared."
                if not failed
                else "FAIL — Do not freeze an expected-improvement model."
            ),
            "",
            "NEXT",
            "-" * 78,
            "Review candidate performance by fold, resolution, baseline",
            "level, duration, gender, and event family.",
            "Then freeze the selected expected-improvement benchmark.",
        ]
    )

    (OUTPUT_DIR / "phase_5d_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Cohort trajectories: {int(counts['cohort_rows']):,}"
    )
    print(
        f"Candidate prediction rows: "
        f"{int(counts['prediction_rows']):,}"
    )
    print(f"Recommended candidate: {selected_name}")
    print(f"Recommended MAE: {selected_mae:.6f}")
    print(f"Recommended RMSE: {selected_rmse:.6f}")
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
    print("Next: review calibration and freeze the benchmark.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
