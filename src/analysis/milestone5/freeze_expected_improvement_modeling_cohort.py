#!/usr/bin/env python3
"""
Milestone 5 Phase 5C — Freeze Expected-Improvement Modeling Cohort

Freezes the reviewed Phase 5B trajectory disposition into a versioned,
auditable modeling cohort.

Frozen policy
-------------
- Include observed-development trajectories spanning 1–5 elapsed seasons.
- Park trajectories spanning 6+ seasons in an explicit exclusion registry.
- Statistical tail flags do not cause exclusion.
- Preserve the four approved two-meet event exceptions.
- Attach the Phase 5B recommended modeling resolution to every included row.
- Assign each school to exactly one deterministic cross-fitting fold so a
  school's held-out predictions are produced by models trained without that
  school.

This phase does not fit the expected-improvement model.
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
      "phase_5b_trajectory_modeling_audit/"
      "trajectory_modeling_audit_v1.duckdb"
)

PHASE_5B_CHECKS = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5b_trajectory_modeling_audit/"
      "hard_checks.csv"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5c_frozen_expected_improvement_cohort"
)

OUTPUT_DB = OUTPUT_DIR / "expected_improvement_cohort_v1.duckdb"

INPUT_DATASET_VERSION = "trajectory_modeling_audit_v1_1"
INPUT_TRAJECTORY_DATASET_VERSION = "observed_development_trajectories_v1"
COHORT_VERSION = "expected_improvement_cohort_v1"
COHORT_POLICY_VERSION = "expected_improvement_cohort_policy_v1"

EXPECTED_TOTAL_TRAJECTORIES = 189_839
EXPECTED_MODELING_ROWS = 189_703
EXPECTED_EXCLUSION_ROWS = 136
EXPECTED_SCHOOLS = 361

EXPECTED_EVENT_LEVEL_ROWS = 135_206
EXPECTED_EVENT_FAMILY_LEVEL_ROWS = 17_648
EXPECTED_GLOBAL_FALLBACK_ROWS = 36_849

PRIMARY_MIN_ELAPSED_SEASONS = 1
PRIMARY_MAX_ELAPSED_SEASONS = 5
CROSSFIT_FOLDS = 5


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

    print("MILESTONE 5 PHASE 5C — FREEZE MODELING COHORT")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Cohort version: {COHORT_VERSION}")
    print(f"Input database: {INPUT_DB}")
    print(f"Output database: {OUTPUT_DB}")
    print(f"Cross-fitting folds: {CROSSFIT_FOLDS}")

    required_inputs = [INPUT_DB, PHASE_5B_CHECKS]
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

    phase_5b_checks = read_csv(PHASE_5B_CHECKS)
    failed_phase_5b_checks = [
        row
        for row in phase_5b_checks
        if row.get("status") != "PASS"
    ]

    add_check(
        checks,
        "phase_5b_gate_passed",
        not failed_phase_5b_checks,
        [
            row.get("check_name")
            for row in failed_phase_5b_checks
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
                AS audit_source (READ_ONLY)
            """
        )

        metadata = {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM audit_source.main.dataset_metadata
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
            "input_trajectory_dataset_version_matches",
            metadata.get("input_dataset_version")
            == INPUT_TRAJECTORY_DATASET_VERSION,
            metadata.get("input_dataset_version"),
            INPUT_TRAJECTORY_DATASET_VERSION,
        )

        con.execute(
            f"""
            CREATE TABLE modeling_cohort_base AS
            SELECT
                a.*,
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
                ) AS baseline_level_band,
                (LEAST(
                    20,
                    GREATEST(
                        1,
                        CAST(
                            FLOOR(
                                baseline_stable_level / 5.0
                            ) AS INTEGER
                        ) + 1
                    )
                ) - 1) * 5 AS baseline_band_lower,
                LEAST(
                    100,
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
                    ) * 5
                ) AS baseline_band_upper,
                TRUE AS expected_improvement_model_eligible,
                'included_primary_1_to_5_seasons'
                    AS cohort_disposition,
                '{COHORT_VERSION}' AS cohort_version,
                '{COHORT_POLICY_VERSION}' AS cohort_policy_version
            FROM audit_source.main.trajectory_audit a
            WHERE primary_model_candidate
            """
        )

        con.execute(
            f"""
            CREATE TABLE modeling_exclusions AS
            SELECT
                a.*,
                FALSE AS expected_improvement_model_eligible,
                'excluded_long_duration_6_plus_seasons'
                    AS cohort_disposition,
                'Elapsed same-season-type trajectory exceeds the '
                    || '{PRIMARY_MAX_ELAPSED_SEASONS}'
                    || '-season primary modeling window.'
                    AS exclusion_reason,
                'retain_for_sensitivity_analysis'
                    AS exclusion_followup,
                '{COHORT_VERSION}' AS cohort_version,
                '{COHORT_POLICY_VERSION}' AS cohort_policy_version
            FROM audit_source.main.trajectory_audit a
            WHERE long_duration_review_flag
            """
        )

        con.execute(
            f"""
            CREATE TABLE school_crossfit_folds AS
            WITH school_sizes AS (
                SELECT
                    resolved_school_id,
                    COUNT(*) AS cohort_trajectory_count,
                    COUNT(DISTINCT canonical_person_id)
                        AS cohort_athlete_count,
                    COUNT(DISTINCT canonical_event_code)
                        AS cohort_event_count
                FROM modeling_cohort_base
                GROUP BY resolved_school_id
            ),
            assigned AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        ORDER BY
                            cohort_trajectory_count DESC,
                            CAST(resolved_school_id AS VARCHAR)
                    ) AS school_size_rank
                FROM school_sizes
            )
            SELECT
                resolved_school_id,
                cohort_trajectory_count,
                cohort_athlete_count,
                cohort_event_count,
                1 + MOD(
                    school_size_rank - 1,
                    {CROSSFIT_FOLDS}
                ) AS crossfit_fold,
                school_size_rank,
                'descending_school_size_round_robin'
                    AS fold_assignment_method,
                '{COHORT_VERSION}' AS cohort_version
            FROM assigned
            """
        )

        con.execute(
            """
            CREATE TABLE cell_resolution_policy AS
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                canonical_event_name,
                event_family,
                elapsed_seasons,
                baseline_level_band,
                baseline_band_lower,
                baseline_band_upper,
                trajectory_count AS cell_trajectory_count,
                school_count AS cell_school_count,
                event_cell_support_status,
                family_trajectory_count,
                family_school_count,
                family_cell_support_status,
                recommended_resolution
            FROM audit_source.main.recommended_modeling_resolution
            """
        )

        con.execute(
            """
            CREATE TABLE modeling_cohort AS
            SELECT
                b.*,
                f.crossfit_fold,
                f.cohort_trajectory_count
                    AS school_cohort_trajectory_count,
                f.cohort_athlete_count
                    AS school_cohort_athlete_count,
                f.cohort_event_count
                    AS school_cohort_event_count,
                f.fold_assignment_method,
                r.cell_trajectory_count,
                r.cell_school_count,
                r.event_cell_support_status,
                r.family_trajectory_count,
                r.family_school_count,
                r.family_cell_support_status,
                r.recommended_resolution
            FROM modeling_cohort_base b
            JOIN school_crossfit_folds f
              USING (resolved_school_id)
            LEFT JOIN cell_resolution_policy r
              USING (
                season_type,
                canonical_gender_code,
                canonical_event_code,
                event_family,
                elapsed_seasons,
                baseline_level_band
              )
            """
        )

        con.execute(
            """
            CREATE VIEW event_level_modeling_cohort AS
            SELECT *
            FROM modeling_cohort
            WHERE recommended_resolution = 'event_level'
            """
        )

        con.execute(
            """
            CREATE VIEW event_family_level_modeling_cohort AS
            SELECT *
            FROM modeling_cohort
            WHERE recommended_resolution = 'event_family_level'
            """
        )

        con.execute(
            """
            CREATE VIEW hierarchical_fallback_modeling_cohort AS
            SELECT *
            FROM modeling_cohort
            WHERE recommended_resolution =
                'hierarchical_global_fallback'
            """
        )

        con.execute(
            f"""
            CREATE TABLE dataset_metadata AS
            SELECT
                'dataset_version' AS metadata_key,
                '{COHORT_VERSION}' AS metadata_value
            UNION ALL
            SELECT
                'cohort_policy_version',
                '{COHORT_POLICY_VERSION}'
            UNION ALL
            SELECT
                'input_audit_version',
                '{INPUT_DATASET_VERSION}'
            UNION ALL
            SELECT
                'primary_elapsed_season_window',
                '{PRIMARY_MIN_ELAPSED_SEASONS}-'
                    || '{PRIMARY_MAX_ELAPSED_SEASONS}'
            UNION ALL
            SELECT
                'statistical_tails_excluded',
                'false'
            UNION ALL
            SELECT
                'school_grouped_crossfit_folds',
                '{CROSSFIT_FOLDS}'
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
                 FROM audit_source.main.trajectory_audit)
                    AS source_rows,
                (SELECT COUNT(*) FROM modeling_cohort)
                    AS modeling_rows,
                (SELECT COUNT(*) FROM modeling_exclusions)
                    AS exclusion_rows,
                (SELECT COUNT(DISTINCT canonical_person_id)
                 FROM modeling_cohort)
                    AS modeling_athletes,
                (SELECT COUNT(DISTINCT resolved_school_id)
                 FROM modeling_cohort)
                    AS modeling_schools,
                (SELECT COUNT(*)
                 FROM event_level_modeling_cohort)
                    AS event_level_rows,
                (SELECT COUNT(*)
                 FROM event_family_level_modeling_cohort)
                    AS event_family_level_rows,
                (SELECT COUNT(*)
                 FROM hierarchical_fallback_modeling_cohort)
                    AS global_fallback_rows,
                (SELECT COUNT(*)
                 FROM modeling_cohort
                 WHERE frozen_role =
                    'standalone_primary_two_meet_exception')
                    AS two_meet_exception_rows,
                (SELECT COUNT(*)
                 FROM modeling_cohort
                 WHERE event_low_improvement_tail_flag
                    OR event_high_improvement_tail_flag
                    OR event_low_annualized_tail_flag
                    OR event_high_annualized_tail_flag
                    OR event_low_baseline_tail_flag
                    OR event_high_baseline_tail_flag)
                    AS included_any_tail_rows
            """
        )[0]

        quality = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM modeling_cohort
                 WHERE elapsed_seasons
                    NOT BETWEEN {PRIMARY_MIN_ELAPSED_SEASONS}
                        AND {PRIMARY_MAX_ELAPSED_SEASONS})
                    AS invalid_modeling_duration_rows,
                (SELECT COUNT(*)
                 FROM modeling_exclusions
                 WHERE elapsed_seasons
                    <= {PRIMARY_MAX_ELAPSED_SEASONS})
                    AS invalid_exclusion_duration_rows,
                (SELECT COUNT(*)
                 FROM modeling_cohort
                 WHERE recommended_resolution IS NULL)
                    AS missing_resolution_rows,
                (SELECT COUNT(*)
                 FROM modeling_cohort
                 WHERE crossfit_fold NOT BETWEEN 1
                    AND {CROSSFIT_FOLDS})
                    AS invalid_fold_rows,
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        resolved_school_id,
                        COUNT(DISTINCT crossfit_fold)
                            AS fold_count
                    FROM modeling_cohort
                    GROUP BY resolved_school_id
                    HAVING COUNT(DISTINCT crossfit_fold) <> 1
                 ))
                    AS multi_fold_school_rows,
                (SELECT COUNT(*)
                 FROM (
                    SELECT trajectory_id, COUNT(*) AS row_count
                    FROM modeling_cohort
                    GROUP BY trajectory_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_modeling_ids,
                (SELECT COUNT(*)
                 FROM (
                    SELECT trajectory_id, COUNT(*) AS row_count
                    FROM modeling_exclusions
                    GROUP BY trajectory_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_exclusion_ids,
                (SELECT COUNT(*)
                 FROM modeling_cohort m
                 JOIN modeling_exclusions e
                   USING (trajectory_id))
                    AS cohort_exclusion_overlap
            """
        )[0]

        fold_summary = fetch_dicts(
            con,
            """
            SELECT
                crossfit_fold,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT canonical_person_id)
                    AS athlete_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                COUNT(DISTINCT canonical_event_code)
                    AS event_count,
                AVG(baseline_stable_level)
                    AS mean_baseline_level,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                MEDIAN(observed_improvement)
                    AS median_observed_improvement,
                AVG(elapsed_seasons)
                    AS mean_elapsed_seasons
            FROM modeling_cohort
            GROUP BY crossfit_fold
            ORDER BY crossfit_fold
            """
        )

        resolution_summary = fetch_dicts(
            con,
            """
            SELECT
                recommended_resolution,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT canonical_person_id)
                    AS athlete_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                COUNT(DISTINCT CONCAT_WS(
                    '|',
                    season_type,
                    canonical_gender_code,
                    canonical_event_code,
                    CAST(elapsed_seasons AS VARCHAR),
                    CAST(baseline_level_band AS VARCHAR)
                )) AS cell_count,
                AVG(baseline_stable_level)
                    AS mean_baseline_level,
                AVG(observed_improvement)
                    AS mean_observed_improvement
            FROM modeling_cohort
            GROUP BY recommended_resolution
            ORDER BY recommended_resolution
            """
        )

        tail_summary = fetch_dicts(
            con,
            """
            SELECT
                cohort_disposition,
                COUNT(*) AS trajectory_count,
                COUNT(*) FILTER (
                    WHERE event_low_improvement_tail_flag
                ) AS low_improvement_tail_rows,
                COUNT(*) FILTER (
                    WHERE event_high_improvement_tail_flag
                ) AS high_improvement_tail_rows,
                COUNT(*) FILTER (
                    WHERE event_low_annualized_tail_flag
                ) AS low_annualized_tail_rows,
                COUNT(*) FILTER (
                    WHERE event_high_annualized_tail_flag
                ) AS high_annualized_tail_rows,
                COUNT(*) FILTER (
                    WHERE event_low_baseline_tail_flag
                ) AS low_baseline_tail_rows,
                COUNT(*) FILTER (
                    WHERE event_high_baseline_tail_flag
                ) AS high_baseline_tail_rows
            FROM (
                SELECT
                    cohort_disposition,
                    event_low_improvement_tail_flag,
                    event_high_improvement_tail_flag,
                    event_low_annualized_tail_flag,
                    event_high_annualized_tail_flag,
                    event_low_baseline_tail_flag,
                    event_high_baseline_tail_flag
                FROM modeling_cohort

                UNION ALL

                SELECT
                    cohort_disposition,
                    event_low_improvement_tail_flag,
                    event_high_improvement_tail_flag,
                    event_low_annualized_tail_flag,
                    event_high_annualized_tail_flag,
                    event_low_baseline_tail_flag,
                    event_high_baseline_tail_flag
                FROM modeling_exclusions
            )
            GROUP BY cohort_disposition
            ORDER BY cohort_disposition
            """
        )

        fold_ids = {
            int(row["crossfit_fold"])
            for row in fold_summary
        }

        add_check(
            checks,
            "source_trajectory_row_count",
            counts["source_rows"]
            == EXPECTED_TOTAL_TRAJECTORIES,
            counts["source_rows"],
            EXPECTED_TOTAL_TRAJECTORIES,
        )
        add_check(
            checks,
            "modeling_cohort_row_count",
            counts["modeling_rows"]
            == EXPECTED_MODELING_ROWS,
            counts["modeling_rows"],
            EXPECTED_MODELING_ROWS,
        )
        add_check(
            checks,
            "modeling_exclusion_row_count",
            counts["exclusion_rows"]
            == EXPECTED_EXCLUSION_ROWS,
            counts["exclusion_rows"],
            EXPECTED_EXCLUSION_ROWS,
        )
        add_check(
            checks,
            "cohort_and_exclusions_reconcile",
            counts["modeling_rows"]
                + counts["exclusion_rows"]
                == counts["source_rows"],
            counts["modeling_rows"]
                + counts["exclusion_rows"],
            counts["source_rows"],
        )
        add_check(
            checks,
            "modeling_school_count",
            counts["modeling_schools"]
            == EXPECTED_SCHOOLS,
            counts["modeling_schools"],
            EXPECTED_SCHOOLS,
        )
        add_check(
            checks,
            "event_level_row_count",
            counts["event_level_rows"]
            == EXPECTED_EVENT_LEVEL_ROWS,
            counts["event_level_rows"],
            EXPECTED_EVENT_LEVEL_ROWS,
        )
        add_check(
            checks,
            "event_family_level_row_count",
            counts["event_family_level_rows"]
            == EXPECTED_EVENT_FAMILY_LEVEL_ROWS,
            counts["event_family_level_rows"],
            EXPECTED_EVENT_FAMILY_LEVEL_ROWS,
        )
        add_check(
            checks,
            "global_fallback_row_count",
            counts["global_fallback_rows"]
            == EXPECTED_GLOBAL_FALLBACK_ROWS,
            counts["global_fallback_rows"],
            EXPECTED_GLOBAL_FALLBACK_ROWS,
        )
        add_check(
            checks,
            "all_modeling_durations_in_window",
            quality["invalid_modeling_duration_rows"] == 0,
            quality["invalid_modeling_duration_rows"],
            0,
        )
        add_check(
            checks,
            "all_exclusions_are_long_duration",
            quality["invalid_exclusion_duration_rows"] == 0,
            quality["invalid_exclusion_duration_rows"],
            0,
        )
        add_check(
            checks,
            "all_modeling_rows_have_resolution",
            quality["missing_resolution_rows"] == 0,
            quality["missing_resolution_rows"],
            0,
        )
        add_check(
            checks,
            "all_crossfit_folds_present",
            fold_ids == set(range(1, CROSSFIT_FOLDS + 1)),
            sorted(fold_ids),
            list(range(1, CROSSFIT_FOLDS + 1)),
        )
        add_check(
            checks,
            "all_fold_values_valid",
            quality["invalid_fold_rows"] == 0,
            quality["invalid_fold_rows"],
            0,
        )
        add_check(
            checks,
            "each_school_in_exactly_one_fold",
            quality["multi_fold_school_rows"] == 0,
            quality["multi_fold_school_rows"],
            0,
        )
        add_check(
            checks,
            "modeling_trajectory_ids_unique",
            quality["duplicate_modeling_ids"] == 0,
            quality["duplicate_modeling_ids"],
            0,
        )
        add_check(
            checks,
            "exclusion_trajectory_ids_unique",
            quality["duplicate_exclusion_ids"] == 0,
            quality["duplicate_exclusion_ids"],
            0,
        )
        add_check(
            checks,
            "cohort_and_exclusions_disjoint",
            quality["cohort_exclusion_overlap"] == 0,
            quality["cohort_exclusion_overlap"],
            0,
        )
        add_check(
            checks,
            "statistical_tails_preserved_in_cohort",
            counts["included_any_tail_rows"] > 0,
            counts["included_any_tail_rows"],
            "greater than 0",
            "Tail flags remain diagnostics and do not cause exclusion.",
        )

        write_csv(
            OUTPUT_DIR / "crossfit_fold_summary.csv",
            fold_summary,
            [
                "crossfit_fold",
                "trajectory_count",
                "athlete_count",
                "school_count",
                "event_count",
                "mean_baseline_level",
                "mean_observed_improvement",
                "median_observed_improvement",
                "mean_elapsed_seasons",
            ],
        )

        write_csv(
            OUTPUT_DIR / "modeling_resolution_summary.csv",
            resolution_summary,
            [
                "recommended_resolution",
                "trajectory_count",
                "athlete_count",
                "school_count",
                "cell_count",
                "mean_baseline_level",
                "mean_observed_improvement",
            ],
        )

        write_csv(
            OUTPUT_DIR / "tail_flag_summary.csv",
            tail_summary,
            [
                "cohort_disposition",
                "trajectory_count",
                "low_improvement_tail_rows",
                "high_improvement_tail_rows",
                "low_annualized_tail_rows",
                "high_annualized_tail_rows",
                "low_baseline_tail_rows",
                "high_baseline_tail_rows",
            ],
        )

        exclusion_rows = fetch_dicts(
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
                baseline_stable_level,
                endpoint_stable_level,
                observed_improvement,
                annualized_observed_improvement,
                trajectory_reliability_tier,
                cohort_disposition,
                exclusion_reason,
                exclusion_followup,
                cohort_version,
                cohort_policy_version
            FROM modeling_exclusions
            ORDER BY
                elapsed_seasons DESC,
                ABS(observed_improvement) DESC,
                trajectory_id
            """
        )

        write_csv(
            OUTPUT_DIR / "modeling_exclusion_registry.csv",
            exclusion_rows,
            list(exclusion_rows[0].keys()) if exclusion_rows else [],
        )

        summary_rows = [
            {
                "metric": "source_trajectory_rows",
                "value": counts["source_rows"],
            },
            {
                "metric": "modeling_cohort_rows",
                "value": counts["modeling_rows"],
            },
            {
                "metric": "modeling_exclusion_rows",
                "value": counts["exclusion_rows"],
            },
            {
                "metric": "modeling_athletes",
                "value": counts["modeling_athletes"],
            },
            {
                "metric": "modeling_schools",
                "value": counts["modeling_schools"],
            },
            {
                "metric": "event_level_rows",
                "value": counts["event_level_rows"],
            },
            {
                "metric": "event_family_level_rows",
                "value": counts["event_family_level_rows"],
            },
            {
                "metric": "hierarchical_global_fallback_rows",
                "value": counts["global_fallback_rows"],
            },
            {
                "metric": "two_meet_exception_rows",
                "value": counts["two_meet_exception_rows"],
            },
            {
                "metric": "included_any_statistical_tail_rows",
                "value": counts["included_any_tail_rows"],
            },
            {
                "metric": "crossfit_folds",
                "value": CROSSFIT_FOLDS,
            },
        ]

        write_csv(
            OUTPUT_DIR / "phase_5c_summary.csv",
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
                "cohort_version": COHORT_VERSION,
                "cohort_policy_version": COHORT_POLICY_VERSION,
            }
        ],
        [
            "output_name",
            "path",
            "size_bytes",
            "sha256",
            "cohort_version",
            "cohort_policy_version",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 5 PHASE 5C — FROZEN EXPECTED-IMPROVEMENT COHORT",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Cohort version: {COHORT_VERSION}",
        "",
        "FROZEN POLICY",
        "-" * 78,
        "Primary expected-improvement cohort includes trajectories",
        "spanning 1–5 elapsed same-season-type seasons.",
        "Trajectories spanning 6+ seasons remain preserved in an",
        "explicit exclusion registry for sensitivity analysis.",
        "Statistical tails remain included unless independently invalid.",
        "Schools are assigned to one of five deterministic cross-fit folds.",
        "",
        "RESULTS",
        "-" * 78,
        f"Source trajectories: "
        f"{int(counts['source_rows']):,}",
        f"Modeling cohort rows: "
        f"{int(counts['modeling_rows']):,}",
        f"Long-duration exclusions: "
        f"{int(counts['exclusion_rows']):,}",
        f"Schools represented: "
        f"{int(counts['modeling_schools']):,}",
        f"Event-level rows: "
        f"{int(counts['event_level_rows']):,}",
        f"Event-family-level rows: "
        f"{int(counts['event_family_level_rows']):,}",
        f"Hierarchical global fallback rows: "
        f"{int(counts['global_fallback_rows']):,}",
        f"Statistical-tail rows retained: "
        f"{int(counts['included_any_tail_rows']):,}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Expected-improvement modeling cohort frozen."
            if not failed
            else "FAIL — Do not fit expected-improvement models."
        ),
        "",
        "NEXT",
        "-" * 78,
        "Fit cross-fitted expected-improvement benchmarks.",
        "Predictions for each school must come from models trained",
        "without that school's trajectories.",
    ]

    (OUTPUT_DIR / "phase_5c_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Source trajectories: {int(counts['source_rows']):,}"
    )
    print(
        f"Modeling cohort rows: {int(counts['modeling_rows']):,}"
    )
    print(
        f"Long-duration exclusions: {int(counts['exclusion_rows']):,}"
    )
    print(
        f"Schools represented: {int(counts['modeling_schools']):,}"
    )
    print(
        "Resolution rows — event: "
        f"{int(counts['event_level_rows']):,}, "
        "family: "
        f"{int(counts['event_family_level_rows']):,}, "
        "global: "
        f"{int(counts['global_fallback_rows']):,}"
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
    print("Next: fit cross-fitted expected-improvement benchmarks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
