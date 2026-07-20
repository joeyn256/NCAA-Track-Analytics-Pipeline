#!/usr/bin/env python3
"""
Milestone 6 Phase 6F — Final Model Validation and Selection

This phase does not replace any published model. It stress-tests the
development-ranking choices created in Phase 6E.

Validation families
-------------------
1. Support-reliability sensitivity
   Tests k = 0, 50, 100, 191, 300, and 500 in:

       reliability = sqrt(n / (n + k))

2. Negative-pool sensitivity
   Tests caps of 0.5x, 1.0x, 1.5x the positive event budget, plus uncapped.

3. Elite matched-improvement audit
   Compares athlete value added at different baseline levels while matching
   approximately on gender, event, and observed-improvement decile.

4. Concentration and roster-size audits
   Measures dependence on one athlete, one school, and program size.

The current enhanced model remains the reference:
    support k = 191
    negative cap = 1.0 x 100,000

The exact Original Balanced Production v4.1 model is also retained as a
comparison variant.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


ROOT = Path.cwd()

INPUT_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "development_model_variants_v1/"
      "phase_6e_model_variants"
)
INPUT_DB = INPUT_DIR / "development_model_variants_v1.duckdb"
INPUT_CHECKS = INPUT_DIR / "hard_checks.csv"

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "development_model_validation_v1/"
      "phase_6f_final_validation"
)
OUTPUT_DB = OUTPUT_DIR / "development_model_validation_v1.duckdb"

INPUT_VERSION = "development_model_variants_v1"
DATASET_VERSION = "development_model_validation_v1_2"
POLICY_VERSION = "support_cap_elite_and_concentration_audit_v1_2"

POSITIVE_EVENT_BUDGET = 100_000.0
POINT_TOLERANCE = 1e-6
SIGNAL_TOLERANCE = 1e-12

REFERENCE_VARIANT = "support_k191_cap1"
ORIGINAL_VARIANT = "original_v4_1_uncapped"

VARIANTS = (
    (
        ORIGINAL_VARIANT,
        "Original v4.1 — Uncapped",
        0.0,
        False,
        None,
        "legacy",
    ),
    (
        "support_k0_cap1",
        "No support adjustment — Cap 1.0",
        0.0,
        True,
        1.0,
        "support",
    ),
    (
        "support_k50_cap1",
        "Support k=50 — Cap 1.0",
        50.0,
        True,
        1.0,
        "support",
    ),
    (
        "support_k100_cap1",
        "Support k=100 — Cap 1.0",
        100.0,
        True,
        1.0,
        "support",
    ),
    (
        REFERENCE_VARIANT,
        "Support k=191 — Cap 1.0",
        191.0,
        True,
        1.0,
        "reference",
    ),
    (
        "support_k300_cap1",
        "Support k=300 — Cap 1.0",
        300.0,
        True,
        1.0,
        "support",
    ),
    (
        "support_k500_cap1",
        "Support k=500 — Cap 1.0",
        500.0,
        True,
        1.0,
        "support",
    ),
    (
        "support_k191_cap0_5",
        "Support k=191 — Cap 0.5",
        191.0,
        True,
        0.5,
        "negative_cap",
    ),
    (
        "support_k191_cap1_5",
        "Support k=191 — Cap 1.5",
        191.0,
        True,
        1.5,
        "negative_cap",
    ),
    (
        "support_k191_uncapped",
        "Support k=191 — Uncapped",
        191.0,
        False,
        None,
        "negative_cap",
    ),
)


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


def hard_checks_pass(path: Path) -> bool:
    rows = read_csv(path)
    return bool(rows) and all(row.get("status") == "PASS" for row in rows)


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


def export_query(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    path: Path,
) -> int:
    rows = fetch_dicts(connection, sql)
    fieldnames = list(rows[0].keys()) if rows else []
    write_csv(path, rows, fieldnames)
    return len(rows)


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

    print("MILESTONE 6 PHASE 6F — FINAL MODEL VALIDATION")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Output database: {OUTPUT_DB}")

    missing = [
        str(path)
        for path in (INPUT_DB, INPUT_CHECKS)
        if not path.exists()
    ]
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
        print("PHASE GATE: FAIL — Phase 6E inputs are missing.")
        return 1

    input_gate = hard_checks_pass(INPUT_CHECKS)
    add_check(
        checks,
        "phase_6e_gate_passed",
        input_gate,
        input_gate,
        True,
    )
    if not input_gate:
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Phase 6E did not pass.")
        return 1

    input_hashes_before = {
        str(INPUT_DB): sha256_file(INPUT_DB),
        str(INPUT_CHECKS): sha256_file(INPUT_CHECKS),
    }

    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()

    con = duckdb.connect(str(OUTPUT_DB))

    try:
        con.execute("PRAGMA threads=4")
        con.execute("PRAGMA enable_progress_bar=false")
        con.execute(
            f"ATTACH '{sql_path(INPUT_DB)}' AS src (READ_ONLY)"
        )

        input_version = dict(
            con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM src.main.dataset_metadata
                """
            ).fetchall()
        ).get("dataset_version")

        add_check(
            checks,
            "input_dataset_version_matches",
            input_version == INPUT_VERSION,
            input_version,
            INPUT_VERSION,
        )

        con.execute(
            """
            CREATE TABLE validation_variant_registry (
                variant_key VARCHAR,
                variant_label VARCHAR,
                support_k DOUBLE,
                negative_cap_enabled BOOLEAN,
                negative_cap_ratio DOUBLE,
                variant_family VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO validation_variant_registry VALUES (?, ?, ?, ?, ?, ?)",
            VARIANTS,
        )

        con.execute(
            """
            CREATE TABLE source_athlete_units AS
            SELECT *
            FROM src.main.source_athlete_units
            """
        )

        event_partition = """
            variant_key,
            cohort_key,
            time_scope,
            season_year,
            season_type,
            gender_scope,
            canonical_event_code
        """

        con.execute(
            f"""
            CREATE TABLE validation_athlete_points AS
            WITH signals AS (
                SELECT
                    v.variant_key,
                    v.variant_label,
                    v.support_k,
                    v.negative_cap_enabled,
                    v.negative_cap_ratio,
                    v.variant_family,
                    u.*,
                    CASE
                        WHEN v.support_k <= 0
                            THEN 1.0
                        ELSE SQRT(
                            GREATEST(
                                COALESCE(
                                    u.minimum_training_support,
                                    1
                                ),
                                1
                            )::DOUBLE
                            / (
                                GREATEST(
                                    COALESCE(
                                        u.minimum_training_support,
                                        1
                                    ),
                                    1
                                )::DOUBLE
                                + v.support_k
                            )
                        )
                    END AS reliability_factor,
                    u.athlete_development_signal
                        * reliability_factor
                        AS validation_signal
                FROM source_athlete_units u
                CROSS JOIN validation_variant_registry v
            ),
            signal_parts AS (
                SELECT
                    *,
                    GREATEST(validation_signal, 0.0)
                        AS positive_signal,
                    LEAST(validation_signal, 0.0)
                        AS negative_signal
                FROM signals
            ),
            partition_totals AS (
                SELECT
                    *,
                    SUM(positive_signal) OVER (
                        PARTITION BY {event_partition}
                    ) AS total_positive_signal,
                    SUM(negative_signal) OVER (
                        PARTITION BY {event_partition}
                    ) AS total_negative_signal,
                    COUNT(*) OVER (
                        PARTITION BY {event_partition}
                    ) AS event_athlete_unit_count
                FROM signal_parts
            ),
            scales AS (
                SELECT
                    *,
                    {POSITIVE_EVENT_BUDGET}
                        / NULLIF(total_positive_signal, 0)
                        AS positive_points_per_signal,
                    ABS(total_negative_signal)
                        / NULLIF(total_positive_signal, 0)
                        AS raw_negative_positive_ratio,
                    CASE
                        WHEN negative_cap_enabled
                            THEN {POSITIVE_EVENT_BUDGET}
                                * LEAST(
                                    ABS(total_negative_signal)
                                    / NULLIF(
                                        total_positive_signal,
                                        0
                                    ),
                                    negative_cap_ratio
                                )
                        ELSE {POSITIVE_EVENT_BUDGET}
                            * ABS(total_negative_signal)
                            / NULLIF(
                                total_positive_signal,
                                0
                            )
                    END AS negative_pool_magnitude
                FROM partition_totals
                WHERE total_positive_signal
                    > {SIGNAL_TOLERANCE}
            )
            SELECT
                *,
                CASE
                    WHEN ABS(total_negative_signal)
                            > {SIGNAL_TOLERANCE}
                        THEN negative_pool_magnitude
                            / ABS(total_negative_signal)
                    ELSE 0.0
                END AS negative_points_per_signal,
                positive_signal
                    * positive_points_per_signal
                    AS athlete_positive_points,
                negative_signal
                    * negative_points_per_signal
                    AS athlete_negative_points,
                athlete_positive_points
                    + athlete_negative_points
                    AS athlete_net_points,
                positive_signal
                    / NULLIF(total_positive_signal, 0)
                    AS positive_point_share,
                CASE
                    WHEN negative_cap_enabled
                     AND raw_negative_positive_ratio
                            > negative_cap_ratio
                        THEN TRUE
                    ELSE FALSE
                END AS negative_pool_was_capped
            FROM scales
            """
        )

        # --------------------------------------------------------------
        # School-period rankings for every validation variant.
        # --------------------------------------------------------------
        overall_partition = """
            variant_key,
            cohort_key,
            time_scope,
            season_year,
            season_type
        """

        con.execute(
            f"""
            CREATE TABLE validation_school_rankings AS
            WITH school_totals AS (
                SELECT
                    {overall_partition},
                    ANY_VALUE(variant_label) AS variant_label,
                    ANY_VALUE(variant_family) AS variant_family,
                    ANY_VALUE(cohort_label) AS cohort_label,
                    resolved_school_id,
                    ANY_VALUE(school_name) AS school_name,
                    SUM(athlete_positive_points)
                        AS total_positive_points,
                    SUM(athlete_negative_points)
                        AS total_negative_points,
                    SUM(athlete_net_points)
                        AS total_net_points,
                    COUNT(*) AS athlete_event_unit_count,
                    COUNT(*) FILTER (
                        WHERE validation_signal > 0
                    ) AS positive_athlete_event_count,
                    COUNT(DISTINCT
                        gender_scope || '|'
                        || canonical_event_code
                    ) AS represented_event_count
                FROM validation_athlete_points
                GROUP BY
                    {overall_partition},
                    resolved_school_id
            )
            SELECT
                *,
                RANK() OVER (
                    PARTITION BY {overall_partition}
                    ORDER BY
                        total_net_points DESC,
                        total_positive_points DESC,
                        represented_event_count DESC
                ) AS school_rank,
                total_net_points
                    / NULLIF(athlete_event_unit_count, 0)
                    AS net_points_per_athlete_event
            FROM school_totals
            """
        )

        # --------------------------------------------------------------
        # Rank stability against the Phase 6E reference model.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE validation_rank_comparison AS
            SELECT
                a.variant_key,
                ANY_VALUE(a.variant_label) AS variant_label,
                ANY_VALUE(a.variant_family) AS variant_family,
                a.cohort_key,
                ANY_VALUE(a.cohort_label) AS cohort_label,
                a.time_scope,
                a.season_year,
                a.season_type,
                COUNT(*) AS shared_school_count,
                CORR(a.school_rank, r.school_rank)
                    AS rank_correlation_to_reference,
                CORR(a.total_net_points, r.total_net_points)
                    AS score_correlation_to_reference,
                AVG(ABS(a.school_rank - r.school_rank))
                    AS mean_absolute_rank_shift,
                MEDIAN(ABS(a.school_rank - r.school_rank))
                    AS median_absolute_rank_shift,
                MAX(ABS(a.school_rank - r.school_rank))
                    AS maximum_absolute_rank_shift,
                COUNT(*) FILTER (
                    WHERE a.school_rank <= 10
                      AND r.school_rank <= 10
                )::DOUBLE
                    / NULLIF(
                        COUNT(*) FILTER (
                            WHERE r.school_rank <= 10
                        ),
                        0
                    ) AS top_10_overlap_share,
                COUNT(*) FILTER (
                    WHERE a.school_rank <= 25
                      AND r.school_rank <= 25
                )::DOUBLE
                    / NULLIF(
                        COUNT(*) FILTER (
                            WHERE r.school_rank <= 25
                        ),
                        0
                    ) AS top_25_overlap_share
            FROM validation_school_rankings a
            JOIN validation_school_rankings r
              ON a.cohort_key = r.cohort_key
             AND a.time_scope = r.time_scope
             AND a.season_year
                    IS NOT DISTINCT FROM r.season_year
             AND a.season_type = r.season_type
             AND a.resolved_school_id
                    = r.resolved_school_id
             AND r.variant_key = '{REFERENCE_VARIANT}'
            GROUP BY
                a.variant_key,
                a.cohort_key,
                a.time_scope,
                a.season_year,
                a.season_type
            """
        )

        con.execute(
            """
            CREATE TABLE validation_rank_stability_summary AS
            SELECT
                variant_key,
                ANY_VALUE(variant_label) AS variant_label,
                ANY_VALUE(variant_family) AS variant_family,
                COUNT(*) AS compared_partition_count,
                AVG(rank_correlation_to_reference)
                    AS mean_rank_correlation,
                MIN(rank_correlation_to_reference)
                    AS minimum_rank_correlation,
                AVG(mean_absolute_rank_shift)
                    AS mean_partition_rank_shift,
                MAX(maximum_absolute_rank_shift)
                    AS maximum_observed_rank_shift,
                AVG(top_10_overlap_share)
                    AS mean_top_10_overlap,
                MIN(top_10_overlap_share)
                    AS minimum_top_10_overlap,
                AVG(top_25_overlap_share)
                    AS mean_top_25_overlap,
                MIN(top_25_overlap_share)
                    AS minimum_top_25_overlap
            FROM validation_rank_comparison
            GROUP BY variant_key
            """
        )

        # --------------------------------------------------------------
        # Concentration sensitivity.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE validation_event_concentration AS
            SELECT
                {event_partition},
                ANY_VALUE(variant_label) AS variant_label,
                ANY_VALUE(variant_family) AS variant_family,
                ANY_VALUE(cohort_label) AS cohort_label,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                COUNT(*) FILTER (
                    WHERE athlete_positive_points > 0
                ) AS positive_athlete_count,
                MAX(positive_point_share)
                    AS largest_athlete_positive_share,
                SUM(
                    positive_point_share
                    * positive_point_share
                ) AS athlete_positive_hhi,
                1.0 / NULLIF(
                    SUM(
                        positive_point_share
                        * positive_point_share
                    ),
                    0
                ) AS effective_positive_athlete_count,
                MAX(raw_negative_positive_ratio)
                    AS raw_negative_positive_ratio,
                BOOL_OR(negative_cap_enabled)
                    AS negative_cap_enabled,
                MAX(negative_cap_ratio)
                    AS negative_cap_ratio,
                MAX(negative_pool_magnitude)
                    / {POSITIVE_EVENT_BUDGET}
                    AS applied_negative_pool_ratio,
                BOOL_OR(negative_pool_was_capped)
                    AS negative_pool_was_capped
            FROM validation_athlete_points
            GROUP BY {event_partition}
            """
        )

        con.execute(
            """
            CREATE TABLE validation_concentration_summary AS
            SELECT
                variant_key,
                ANY_VALUE(variant_label) AS variant_label,
                ANY_VALUE(variant_family) AS variant_family,
                COUNT(*) AS event_partition_count,
                AVG(largest_athlete_positive_share)
                    AS mean_largest_athlete_share,
                QUANTILE_CONT(
                    largest_athlete_positive_share,
                    0.95
                ) AS p95_largest_athlete_share,
                MAX(largest_athlete_positive_share)
                    AS maximum_largest_athlete_share,
                AVG(effective_positive_athlete_count)
                    AS mean_effective_positive_athletes,
                QUANTILE_CONT(
                    effective_positive_athlete_count,
                    0.05
                ) AS p05_effective_positive_athletes,
                COUNT(*) FILTER (
                    WHERE negative_pool_was_capped
                ) AS capped_event_partition_count,
                AVG(applied_negative_pool_ratio)
                    AS mean_applied_negative_ratio,
                MAX(applied_negative_pool_ratio)
                    AS maximum_applied_negative_ratio
            FROM validation_event_concentration
            GROUP BY variant_key
            """
        )

        # --------------------------------------------------------------
        # Roster-size dependence by school-period partition.
        # --------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE validation_roster_dependence AS
            SELECT
                variant_key,
                ANY_VALUE(variant_label) AS variant_label,
                ANY_VALUE(variant_family) AS variant_family,
                cohort_key,
                ANY_VALUE(cohort_label) AS cohort_label,
                time_scope,
                season_year,
                season_type,
                COUNT(*) AS ranked_school_count,
                CORR(
                    total_net_points,
                    athlete_event_unit_count
                ) AS net_points_roster_correlation,
                CORR(
                    total_positive_points,
                    athlete_event_unit_count
                ) AS positive_points_roster_correlation,
                CORR(
                    total_net_points,
                    positive_athlete_event_count
                ) AS net_points_positive_count_correlation,
                CORR(
                    total_net_points,
                    net_points_per_athlete_event
                ) AS net_points_efficiency_correlation
            FROM validation_school_rankings
            GROUP BY
                variant_key,
                cohort_key,
                time_scope,
                season_year,
                season_type
            """
        )

        con.execute(
            """
            CREATE TABLE validation_roster_summary AS
            SELECT
                variant_key,
                ANY_VALUE(variant_label) AS variant_label,
                ANY_VALUE(variant_family) AS variant_family,
                COUNT(*) AS partition_count,
                COUNT(*) FILTER (
                    WHERE ISFINITE(net_points_roster_correlation)
                ) AS finite_roster_correlation_partitions,
                COUNT(*) FILTER (
                    WHERE ISFINITE(
                        net_points_positive_count_correlation
                    )
                ) AS finite_positive_count_correlation_partitions,
                COUNT(*) FILTER (
                    WHERE ISFINITE(
                        net_points_efficiency_correlation
                    )
                ) AS finite_efficiency_correlation_partitions,
                AVG(
                    CASE
                        WHEN ISFINITE(net_points_roster_correlation)
                            THEN net_points_roster_correlation
                    END
                ) AS mean_net_roster_correlation,
                AVG(
                    CASE
                        WHEN ISFINITE(net_points_roster_correlation)
                            THEN ABS(net_points_roster_correlation)
                    END
                ) AS mean_absolute_net_roster_correlation,
                MAX(
                    CASE
                        WHEN ISFINITE(net_points_roster_correlation)
                            THEN ABS(net_points_roster_correlation)
                    END
                ) AS maximum_absolute_net_roster_correlation,
                AVG(
                    CASE
                        WHEN ISFINITE(
                            net_points_positive_count_correlation
                        )
                            THEN net_points_positive_count_correlation
                    END
                ) AS mean_positive_count_correlation,
                AVG(
                    CASE
                        WHEN ISFINITE(
                            net_points_efficiency_correlation
                        )
                            THEN net_points_efficiency_correlation
                    END
                ) AS mean_efficiency_correlation
            FROM validation_roster_dependence
            GROUP BY variant_key
            """
        )

        # --------------------------------------------------------------
        # Matched elite-baseline audit.
        #
        # Observed improvement is divided into deciles within gender/event.
        # Baseline slopes are then estimated within those cells.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE elite_matched_cells AS
            WITH base AS (
                SELECT
                    canonical_person_id,
                    resolved_school_id,
                    gender_scope,
                    canonical_event_code,
                    canonical_event_name,
                    mean_baseline_level,
                    mean_observed_improvement,
                    athlete_development_signal
                        AS original_development_signal,
                    athlete_development_signal
                        * SQRT(
                            GREATEST(
                                COALESCE(
                                    minimum_training_support,
                                    1
                                ),
                                1
                            )::DOUBLE
                            / (
                                GREATEST(
                                    COALESCE(
                                        minimum_training_support,
                                        1
                                    ),
                                    1
                                )::DOUBLE
                                + 191.0
                            )
                        ) AS enhanced_development_signal,
                    NTILE(10) OVER (
                        PARTITION BY
                            gender_scope,
                            canonical_event_code
                        ORDER BY mean_observed_improvement
                    ) AS observed_improvement_decile
                FROM source_athlete_units
                WHERE cohort_key = 'broad_all_athletes'
                  AND time_scope = 'all_time'
                  AND mean_observed_improvement > 0
                  AND mean_baseline_level IS NOT NULL
                  AND athlete_development_signal IS NOT NULL
            )
            SELECT
                gender_scope,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                observed_improvement_decile,
                COUNT(*) AS athlete_unit_count,
                MIN(mean_baseline_level)
                    AS minimum_baseline_level,
                MAX(mean_baseline_level)
                    AS maximum_baseline_level,
                AVG(mean_observed_improvement)
                    AS mean_observed_improvement,
                REGR_SLOPE(
                    original_development_signal,
                    mean_baseline_level
                ) AS original_signal_baseline_slope,
                REGR_SLOPE(
                    enhanced_development_signal,
                    mean_baseline_level
                ) AS enhanced_signal_baseline_slope,
                CORR(
                    original_development_signal,
                    mean_baseline_level
                ) AS original_signal_baseline_correlation,
                CORR(
                    enhanced_development_signal,
                    mean_baseline_level
                ) AS enhanced_signal_baseline_correlation
            FROM base
            GROUP BY
                gender_scope,
                canonical_event_code,
                observed_improvement_decile
            HAVING COUNT(*) >= 30
               AND MAX(mean_baseline_level)
                    - MIN(mean_baseline_level) >= 10
            """
        )

        con.execute(
            """
            CREATE TABLE elite_matched_slope_summary AS
            SELECT
                COUNT(*) AS matched_cell_count,
                COUNT(*) FILTER (
                    WHERE original_signal_baseline_slope > 0
                ) AS positive_original_slope_cells,
                COUNT(*) FILTER (
                    WHERE enhanced_signal_baseline_slope > 0
                ) AS positive_enhanced_slope_cells,
                COUNT(*) FILTER (
                    WHERE original_signal_baseline_slope >= 0
                )::DOUBLE / COUNT(*)
                    AS nonnegative_original_slope_share,
                COUNT(*) FILTER (
                    WHERE enhanced_signal_baseline_slope >= 0
                )::DOUBLE / COUNT(*)
                    AS nonnegative_enhanced_slope_share,
                AVG(original_signal_baseline_slope)
                    AS mean_original_baseline_slope,
                MEDIAN(original_signal_baseline_slope)
                    AS median_original_baseline_slope,
                AVG(enhanced_signal_baseline_slope)
                    AS mean_enhanced_baseline_slope,
                MEDIAN(enhanced_signal_baseline_slope)
                    AS median_enhanced_baseline_slope
            FROM elite_matched_cells
            """
        )

        # Direct matched-band comparison: 90+ versus 70–79.99 inside the
        # same gender/event/improvement-decile cell.
        con.execute(
            """
            CREATE TABLE elite_matched_band_results AS
            WITH base AS (
                SELECT
                    gender_scope,
                    canonical_event_code,
                    canonical_event_name,
                    mean_baseline_level,
                    mean_observed_improvement,
                    athlete_development_signal
                        AS original_development_signal,
                    athlete_development_signal
                        * SQRT(
                            GREATEST(
                                COALESCE(
                                    minimum_training_support,
                                    1
                                ),
                                1
                            )::DOUBLE
                            / (
                                GREATEST(
                                    COALESCE(
                                        minimum_training_support,
                                        1
                                    ),
                                    1
                                )::DOUBLE
                                + 191.0
                            )
                        ) AS enhanced_development_signal,
                    NTILE(10) OVER (
                        PARTITION BY
                            gender_scope,
                            canonical_event_code
                        ORDER BY mean_observed_improvement
                    ) AS observed_improvement_decile,
                    CASE
                        WHEN mean_baseline_level >= 90
                            THEN 'elite_90_plus'
                        WHEN mean_baseline_level >= 70
                         AND mean_baseline_level < 80
                            THEN 'reference_70_to_79'
                        ELSE 'other'
                    END AS comparison_band
                FROM source_athlete_units
                WHERE cohort_key = 'broad_all_athletes'
                  AND time_scope = 'all_time'
                  AND mean_observed_improvement > 0
                  AND mean_baseline_level IS NOT NULL
            ),
            grouped AS (
                SELECT
                    gender_scope,
                    canonical_event_code,
                    ANY_VALUE(canonical_event_name)
                        AS canonical_event_name,
                    observed_improvement_decile,
                    comparison_band,
                    COUNT(*) AS athlete_unit_count,
                    AVG(mean_observed_improvement)
                        AS mean_observed_improvement,
                    AVG(original_development_signal)
                        AS mean_original_signal,
                    AVG(enhanced_development_signal)
                        AS mean_enhanced_signal
                FROM base
                WHERE comparison_band <> 'other'
                GROUP BY
                    gender_scope,
                    canonical_event_code,
                    observed_improvement_decile,
                    comparison_band
                HAVING COUNT(*) >= 5
            )
            SELECT
                e.gender_scope,
                e.canonical_event_code,
                e.canonical_event_name,
                e.observed_improvement_decile,
                e.athlete_unit_count AS elite_athlete_count,
                r.athlete_unit_count AS reference_athlete_count,
                e.mean_observed_improvement
                    AS elite_mean_observed_improvement,
                r.mean_observed_improvement
                    AS reference_mean_observed_improvement,
                e.mean_original_signal
                    AS elite_mean_original_signal,
                r.mean_original_signal
                    AS reference_mean_original_signal,
                e.mean_original_signal
                    - r.mean_original_signal
                    AS original_elite_signal_advantage,
                e.mean_enhanced_signal
                    AS elite_mean_enhanced_signal,
                r.mean_enhanced_signal
                    AS reference_mean_enhanced_signal,
                e.mean_enhanced_signal
                    - r.mean_enhanced_signal
                    AS enhanced_elite_signal_advantage
            FROM grouped e
            JOIN grouped r
              ON e.gender_scope = r.gender_scope
             AND e.canonical_event_code
                    = r.canonical_event_code
             AND e.observed_improvement_decile
                    = r.observed_improvement_decile
            WHERE e.comparison_band = 'elite_90_plus'
              AND r.comparison_band = 'reference_70_to_79'
            """
        )

        con.execute(
            """
            CREATE TABLE elite_matched_band_summary AS
            SELECT
                COUNT(*) AS matched_band_cell_count,
                COUNT(*) FILTER (
                    WHERE original_elite_signal_advantage > 0
                )::DOUBLE / COUNT(*)
                    AS original_elite_advantage_share,
                COUNT(*) FILTER (
                    WHERE enhanced_elite_signal_advantage > 0
                )::DOUBLE / COUNT(*)
                    AS enhanced_elite_advantage_share,
                AVG(original_elite_signal_advantage)
                    AS mean_original_elite_advantage,
                MEDIAN(original_elite_signal_advantage)
                    AS median_original_elite_advantage,
                AVG(enhanced_elite_signal_advantage)
                    AS mean_enhanced_elite_advantage,
                MEDIAN(enhanced_elite_signal_advantage)
                    AS median_enhanced_elite_advantage
            FROM elite_matched_band_results
            """
        )

        # --------------------------------------------------------------
        # Consolidated scorecard.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE final_model_scorecard AS
            SELECT
                s.variant_key,
                s.variant_label,
                s.variant_family,
                s.mean_rank_correlation,
                s.minimum_rank_correlation,
                s.mean_partition_rank_shift,
                s.mean_top_10_overlap,
                s.mean_top_25_overlap,
                c.p95_largest_athlete_share,
                c.mean_effective_positive_athletes,
                c.capped_event_partition_count,
                c.maximum_applied_negative_ratio,
                r.finite_roster_correlation_partitions,
                r.finite_positive_count_correlation_partitions,
                r.finite_efficiency_correlation_partitions,
                r.mean_absolute_net_roster_correlation,
                r.mean_positive_count_correlation,
                r.mean_efficiency_correlation,
                CASE
                    WHEN s.mean_rank_correlation >= 0.98
                     AND s.mean_top_25_overlap >= 0.90
                        THEN 'high_stability'
                    WHEN s.mean_rank_correlation >= 0.95
                     AND s.mean_top_25_overlap >= 0.80
                        THEN 'moderate_stability'
                    ELSE 'material_change'
                END AS stability_category,
                CASE
                    WHEN c.maximum_applied_negative_ratio <= 1.0
                        THEN 'bounded_to_positive_pool'
                    WHEN c.maximum_applied_negative_ratio <= 1.5
                        THEN 'moderately_unbounded'
                    ELSE 'strongly_unbounded'
                END AS negative_balance_category,
                CASE
                    WHEN c.p95_largest_athlete_share <= 0.20
                        THEN 'distributed'
                    WHEN c.p95_largest_athlete_share <= 0.35
                        THEN 'moderately_concentrated'
                    ELSE 'highly_concentrated'
                END AS concentration_category
            FROM validation_rank_stability_summary s
            JOIN validation_concentration_summary c
              USING (variant_key)
            JOIN validation_roster_summary r
              USING (variant_key)
            """
        )

        # --------------------------------------------------------------
        # Integrity validation.
        # --------------------------------------------------------------
        counts = fetch_dicts(
            con,
            """
            SELECT
                (SELECT COUNT(*)
                 FROM validation_variant_registry)
                    AS variant_count,
                (SELECT COUNT(*)
                 FROM source_athlete_units)
                    AS source_athlete_unit_count,
                (SELECT COUNT(*)
                 FROM validation_athlete_points)
                    AS validation_athlete_point_count,
                (SELECT COUNT(*)
                 FROM validation_rank_stability_summary)
                    AS rank_summary_count,
                (SELECT COUNT(*)
                 FROM validation_concentration_summary)
                    AS concentration_summary_count,
                (SELECT COUNT(*)
                 FROM validation_roster_summary)
                    AS roster_summary_count,
                (SELECT COUNT(*)
                 FROM elite_matched_cells)
                    AS elite_matched_cell_count,
                (SELECT COUNT(*)
                 FROM elite_matched_band_results)
                    AS elite_band_cell_count,
                (SELECT COUNT(*)
                 FROM final_model_scorecard)
                    AS final_scorecard_row_count,
                (SELECT COUNT(*)
                 FROM final_model_scorecard
                 WHERE finite_positive_count_correlation_partitions > 0
                   AND mean_positive_count_correlation IS NOT NULL
                   AND ISFINITE(mean_positive_count_correlation))
                    AS valid_final_scorecard_roster_rows
            """
        )[0]

        quality = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        {event_partition},
                        SUM(athlete_positive_points)
                            AS positive_points
                    FROM validation_athlete_points
                    GROUP BY {event_partition}
                 )
                 WHERE ABS(
                    positive_points
                    - {POSITIVE_EVENT_BUDGET}
                 ) > {POINT_TOLERANCE})
                    AS invalid_positive_event_budgets,
                (SELECT COUNT(*)
                 FROM validation_athlete_points
                 WHERE reliability_factor <= 0
                    OR reliability_factor > 1)
                    AS invalid_reliability_factors,
                (SELECT COUNT(*)
                 FROM validation_athlete_points
                 WHERE athlete_positive_points < -{POINT_TOLERANCE})
                    AS invalid_positive_points,
                (SELECT COUNT(*)
                 FROM validation_athlete_points
                 WHERE athlete_negative_points > {POINT_TOLERANCE})
                    AS invalid_negative_points,
                (SELECT COUNT(*)
                 FROM validation_event_concentration
                 WHERE negative_cap_enabled
                   AND applied_negative_pool_ratio
                        > negative_cap_ratio
                            + {POINT_TOLERANCE})
                    AS negative_cap_violations,
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        variant_key,
                        cohort_key,
                        time_scope,
                        season_year,
                        season_type,
                        gender_scope,
                        canonical_event_code,
                        canonical_person_id,
                        resolved_school_id,
                        COUNT(*) AS row_count
                    FROM validation_athlete_points
                    GROUP BY
                        variant_key,
                        cohort_key,
                        time_scope,
                        season_year,
                        season_type,
                        gender_scope,
                        canonical_event_code,
                        canonical_person_id,
                        resolved_school_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_validation_keys,
                (SELECT COUNT(*)
                 FROM validation_roster_summary
                 WHERE mean_positive_count_correlation IS NULL
                    OR NOT ISFINITE(
                        mean_positive_count_correlation
                    ))
                    AS invalid_positive_count_summary_rows,
                (SELECT COUNT(*)
                 FROM validation_roster_summary
                 WHERE finite_positive_count_correlation_partitions = 0)
                    AS variants_without_finite_positive_count_correlations
            """
        )[0]

        add_check(
            checks,
            "validation_variant_count",
            counts["variant_count"] == len(VARIANTS),
            counts["variant_count"],
            len(VARIANTS),
        )
        add_check(
            checks,
            "all_source_units_represented_in_all_variants",
            counts["validation_athlete_point_count"]
                == counts["source_athlete_unit_count"]
                    * counts["variant_count"],
            counts["validation_athlete_point_count"],
            counts["source_athlete_unit_count"]
                * counts["variant_count"],
        )
        add_check(
            checks,
            "all_positive_event_budgets_equal_100000",
            quality["invalid_positive_event_budgets"] == 0,
            quality["invalid_positive_event_budgets"],
            0,
        )
        add_check(
            checks,
            "all_reliability_factors_valid",
            quality["invalid_reliability_factors"] == 0,
            quality["invalid_reliability_factors"],
            0,
        )
        add_check(
            checks,
            "positive_points_nonnegative",
            quality["invalid_positive_points"] == 0,
            quality["invalid_positive_points"],
            0,
        )
        add_check(
            checks,
            "negative_points_nonpositive",
            quality["invalid_negative_points"] == 0,
            quality["invalid_negative_points"],
            0,
        )
        add_check(
            checks,
            "all_enabled_negative_caps_respected",
            quality["negative_cap_violations"] == 0,
            quality["negative_cap_violations"],
            0,
        )
        add_check(
            checks,
            "validation_keys_unique",
            quality["duplicate_validation_keys"] == 0,
            quality["duplicate_validation_keys"],
            0,
        )
        add_check(
            checks,
            "rank_stability_outputs_exist",
            counts["rank_summary_count"] == len(VARIANTS),
            counts["rank_summary_count"],
            len(VARIANTS),
        )
        add_check(
            checks,
            "concentration_outputs_exist",
            counts["concentration_summary_count"]
                == len(VARIANTS),
            counts["concentration_summary_count"],
            len(VARIANTS),
        )
        add_check(
            checks,
            "roster_outputs_exist",
            counts["roster_summary_count"] == len(VARIANTS),
            counts["roster_summary_count"],
            len(VARIANTS),
        )
        add_check(
            checks,
            "roster_positive_count_correlations_are_finite",
            quality["invalid_positive_count_summary_rows"] == 0,
            quality["invalid_positive_count_summary_rows"],
            0,
        )
        add_check(
            checks,
            "every_variant_has_finite_positive_count_correlations",
            quality[
                "variants_without_finite_positive_count_correlations"
            ] == 0,
            quality[
                "variants_without_finite_positive_count_correlations"
            ],
            0,
        )
        add_check(
            checks,
            "final_scorecard_contains_all_variants",
            counts["final_scorecard_row_count"] == len(VARIANTS),
            counts["final_scorecard_row_count"],
            len(VARIANTS),
        )
        add_check(
            checks,
            "final_scorecard_roster_fields_valid",
            counts["valid_final_scorecard_roster_rows"]
                == len(VARIANTS),
            counts["valid_final_scorecard_roster_rows"],
            len(VARIANTS),
        )
        add_check(
            checks,
            "elite_matched_cells_exist",
            counts["elite_matched_cell_count"] > 0,
            counts["elite_matched_cell_count"],
            "greater than 0",
        )

        # --------------------------------------------------------------
        # Exports.
        # --------------------------------------------------------------
        export_specs = (
            (
                "validation_variant_registry.csv",
                """
                SELECT *
                FROM validation_variant_registry
                ORDER BY variant_family, support_k, negative_cap_ratio
                """,
            ),
            (
                "validation_rank_comparison.csv",
                """
                SELECT *
                FROM validation_rank_comparison
                ORDER BY
                    variant_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type
                """,
            ),
            (
                "validation_rank_stability_summary.csv",
                """
                SELECT *
                FROM validation_rank_stability_summary
                ORDER BY variant_family, variant_key
                """,
            ),
            (
                "validation_event_concentration.csv",
                """
                SELECT *
                FROM validation_event_concentration
                ORDER BY
                    variant_key,
                    largest_athlete_positive_share DESC
                """,
            ),
            (
                "validation_concentration_summary.csv",
                """
                SELECT *
                FROM validation_concentration_summary
                ORDER BY variant_family, variant_key
                """,
            ),
            (
                "validation_roster_dependence.csv",
                """
                SELECT *
                FROM validation_roster_dependence
                ORDER BY
                    variant_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type
                """,
            ),
            (
                "validation_roster_summary.csv",
                """
                SELECT *
                FROM validation_roster_summary
                ORDER BY variant_family, variant_key
                """,
            ),
            (
                "elite_matched_cells.csv",
                """
                SELECT *
                FROM elite_matched_cells
                ORDER BY
                    canonical_event_name,
                    gender_scope,
                    observed_improvement_decile
                """,
            ),
            (
                "elite_matched_slope_summary.csv",
                "SELECT * FROM elite_matched_slope_summary",
            ),
            (
                "elite_matched_band_results.csv",
                """
                SELECT *
                FROM elite_matched_band_results
                ORDER BY
                    canonical_event_name,
                    gender_scope,
                    observed_improvement_decile
                """,
            ),
            (
                "elite_matched_band_summary.csv",
                "SELECT * FROM elite_matched_band_summary",
            ),
            (
                "final_model_scorecard.csv",
                """
                SELECT *
                FROM final_model_scorecard
                ORDER BY variant_family, variant_key
                """,
            ),
        )

        output_counts = {}
        for filename, sql in export_specs:
            output_counts[filename] = export_query(
                con,
                sql,
                OUTPUT_DIR / filename,
            )

        con.execute(
            f"""
            CREATE TABLE dataset_metadata AS
            SELECT
                'dataset_version' AS metadata_key,
                '{DATASET_VERSION}' AS metadata_value
            UNION ALL
            SELECT 'policy_version', '{POLICY_VERSION}'
            UNION ALL
            SELECT 'input_version', '{INPUT_VERSION}'
            UNION ALL
            SELECT 'reference_variant', '{REFERENCE_VARIANT}'
            UNION ALL
            SELECT 'positive_event_budget',
                   '{POSITIVE_EVENT_BUDGET}'
            UNION ALL
            SELECT
                'roster_correlation_nan_policy',
                'exclude non-finite partition correlations from summaries'
            UNION ALL
            SELECT
                'scorecard_roster_handoff_patch',
                'carry finite correlation counts into final model scorecard'
            UNION ALL
            SELECT 'created_at_utc', CURRENT_TIMESTAMP::VARCHAR
            """
        )

        reference_score = fetch_dicts(
            con,
            f"""
            SELECT *
            FROM final_model_scorecard
            WHERE variant_key = '{REFERENCE_VARIANT}'
            """
        )[0]

        original_score = fetch_dicts(
            con,
            f"""
            SELECT *
            FROM final_model_scorecard
            WHERE variant_key = '{ORIGINAL_VARIANT}'
            """
        )[0]

        elite_slope = fetch_dicts(
            con,
            "SELECT * FROM elite_matched_slope_summary",
        )[0]

        elite_band = fetch_dicts(
            con,
            "SELECT * FROM elite_matched_band_summary",
        )[0]

    finally:
        con.close()

    input_hashes_after = {
        str(INPUT_DB): sha256_file(INPUT_DB),
        str(INPUT_CHECKS): sha256_file(INPUT_CHECKS),
    }
    add_check(
        checks,
        "all_inputs_unchanged",
        input_hashes_before == input_hashes_after,
        input_hashes_after,
        input_hashes_before,
    )

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
            for path in (INPUT_DB, INPUT_CHECKS)
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
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    elite_evidence_present = (
        float(
            elite_slope["nonnegative_enhanced_slope_share"]
            or 0
        ) >= 0.60
        and float(
            elite_band["enhanced_elite_advantage_share"]
            or 0
        ) >= 0.60
    )

    reference_is_stable = (
        float(
            original_score["mean_rank_correlation"]
            or 0
        ) >= 0.95
        and float(
            original_score["mean_top_25_overlap"]
            or 0
        ) >= 0.80
    )

    recommendation = (
        "Retain Enhanced Balanced Production as primary and preserve "
        "Original v4.1 plus Average Development as companion views."
        if reference_is_stable
        else (
            "Do not finalize the enhanced model yet; the change from "
            "Original v4.1 is materially larger than the stability target."
        )
    )

    elite_recommendation = (
        "Matched evidence supports greater credit at higher baselines; "
        "do not add another elite multiplier."
        if elite_evidence_present
        else (
            "Elite reward is not consistently monotonic in matched cells. "
            "Do not add an arbitrary bonus; revisit the performance-level "
            "or expected-improvement calibration in a separate phase."
        )
    )

    report = [
        "MILESTONE 6 PHASE 6F — FINAL MODEL VALIDATION",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "REFERENCE MODEL",
        "-" * 78,
        "Enhanced Balanced Production",
        "Support k: 191",
        "Negative cap: 1.0 × positive event budget",
        "",
        "REFERENCE VERSUS ORIGINAL V4.1",
        "-" * 78,
        f"Mean rank correlation: "
        f"{float(original_score['mean_rank_correlation']):.6f}",
        f"Mean partition rank shift: "
        f"{float(original_score['mean_partition_rank_shift']):.3f}",
        f"Mean top-10 overlap: "
        f"{float(original_score['mean_top_10_overlap']):.3f}",
        f"Mean top-25 overlap: "
        f"{float(original_score['mean_top_25_overlap']):.3f}",
        "",
        "CONCENTRATION",
        "-" * 78,
        f"Reference p95 largest athlete share: "
        f"{float(reference_score['p95_largest_athlete_share']):.4f}",
        f"Reference mean effective positive athletes: "
        f"{float(reference_score['mean_effective_positive_athletes']):.2f}",
        f"Reference concentration category: "
        f"{reference_score['concentration_category']}",
        "",
        "ROSTER DEPENDENCE",
        "-" * 78,
        f"Reference mean absolute roster correlation: "
        f"{float(reference_score['mean_absolute_net_roster_correlation']):.4f}",
        f"Reference mean positive-athlete-count correlation: "
        f"{float(reference_score['mean_positive_count_correlation']):.4f}",
        f"Reference finite positive-count partitions: "
        f"{int(reference_score['finite_positive_count_correlation_partitions']):,}",
        "",
        "MATCHED ELITE REWARD",
        "-" * 78,
        f"Matched slope cells: "
        f"{int(elite_slope['matched_cell_count']):,}",
        f"Nonnegative enhanced baseline-slope share: "
        f"{float(elite_slope['nonnegative_enhanced_slope_share']):.3f}",
        f"Matched 90+ versus 70–79 cell count: "
        f"{int(elite_band['matched_band_cell_count'] or 0):,}",
        f"Enhanced elite-advantage share: "
        f"{float(elite_band['enhanced_elite_advantage_share'] or 0):.3f}",
        f"Median enhanced elite advantage: "
        f"{float(elite_band['median_enhanced_elite_advantage'] or 0):.4f}",
        "",
        "RECOMMENDATION",
        "-" * 78,
        recommendation,
        elite_recommendation,
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Final validation outputs published."
            if not failed
            else "FAIL — Review hard checks."
        ),
    ]

    (OUTPUT_DIR / "phase_6f_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Validation variants: "
        f"{int(counts['variant_count']):,}"
    )
    print(
        f"Validation athlete-point rows: "
        f"{int(counts['validation_athlete_point_count']):,}"
    )
    print(
        f"Matched elite slope cells: "
        f"{int(counts['elite_matched_cell_count']):,}"
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
    print("Next: select the frozen primary model and finalize Milestone 6.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
