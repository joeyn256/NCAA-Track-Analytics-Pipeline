#!/usr/bin/env python3
"""
Milestone 6 Phase 6E — Development Model Variants and Fairness Audits

This phase preserves the validated Phase 6D v4.1 athlete-level model and
adds an enhanced primary variant.

MODEL 1 — Enhanced Balanced Production
--------------------------------------
Original athlete development signal:
    observed improvement - cross-fitted expected improvement

Reliability adjustment:
    support reliability
    = sqrt(n / (n + k))

where:
- n is the athlete-event unit's minimum training support;
- k is the empirical median support in the broad all-time population.

Positive event pool:
    exactly 100,000 points per publishable event.

Negative event pool:
    follows the same positive conversion while total negative signal is no
    larger than total positive signal, then caps at -100,000 points.

Equivalently:
    negative pool magnitude
    = 100,000 * min(abs(total negative signal) / total positive signal, 1)

This prevents an event with extensive regression from regaining more total
influence than another event through an unbounded negative tail.

MODEL 2 — Original Balanced Production v4.1
-------------------------------------------
Reproduces the already validated Phase 6D v4.1 formula exactly:
- no support adjustment;
- exactly 100,000 positive points per event;
- negative signals use the same uncapped linear conversion.

The previous Average Athlete Development rankings remain separate Phase 6A
and Phase 6B explorer views because they answer development efficiency rather
than total development production.

Additional diagnostics:
- event concentration;
- negative-pool behavior;
- roster-size dependence;
- elite-baseline reward patterns;
- enhanced-versus-v4.1 rank stability.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


ROOT = Path.cwd()

SOURCE_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "event_balanced_development_points_v1/"
      "phase_6d_event_balanced_points"
)
SOURCE_DB = SOURCE_DIR / "event_balanced_development_points_v1.duckdb"
SOURCE_CHECKS = SOURCE_DIR / "hard_checks.csv"

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "development_model_variants_v1/"
      "phase_6e_model_variants"
)
OUTPUT_DB = OUTPUT_DIR / "development_model_variants_v1.duckdb"

INPUT_VERSION = "event_balanced_development_points_v4_1"
DATASET_VERSION = "development_model_variants_v1"
POLICY_VERSION = "reliability_bounded_negative_and_legacy_v1"

POSITIVE_EVENT_BUDGET = 100_000.0
POSITIVE_GROUP_BUDGET = 100_000.0
NEGATIVE_EVENT_CAP = 100_000.0

POINT_TOLERANCE = 1e-6
SIGNAL_TOLERANCE = 1e-12

PRIMARY_MODEL_KEY = "enhanced_balanced_production"
LEGACY_MODEL_KEY = "original_balanced_production_v4_1"

MODEL_ROWS = (
    (
        PRIMARY_MODEL_KEY,
        "Enhanced Balanced Production",
        True,
        True,
        True,
        (
            "Original athlete value added with support reliability and "
            "a negative event-pool cap."
        ),
    ),
    (
        LEGACY_MODEL_KEY,
        "Original Balanced Production v4.1",
        False,
        False,
        False,
        (
            "Exact reproduction of the validated Phase 6D v4.1 "
            "athlete-level allocation."
        ),
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

    print("MILESTONE 6 PHASE 6E — DEVELOPMENT MODEL VARIANTS")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Output database: {OUTPUT_DB}")

    missing = [
        str(path)
        for path in (SOURCE_DB, SOURCE_CHECKS)
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
        print("PHASE GATE: FAIL — Phase 6D v4.1 inputs are missing.")
        return 1

    source_gate = hard_checks_pass(SOURCE_CHECKS)
    add_check(
        checks,
        "phase_6d_v4_1_gate_passed",
        source_gate,
        source_gate,
        True,
    )
    if not source_gate:
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Phase 6D v4.1 hard checks failed.")
        return 1

    input_hashes_before = {
        str(SOURCE_DB): sha256_file(SOURCE_DB),
        str(SOURCE_CHECKS): sha256_file(SOURCE_CHECKS),
    }

    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()

    con = duckdb.connect(str(OUTPUT_DB))

    try:
        con.execute("PRAGMA threads=4")
        con.execute("PRAGMA enable_progress_bar=false")
        con.execute(
            f"ATTACH '{sql_path(SOURCE_DB)}' AS src (READ_ONLY)"
        )

        source_metadata = dict(
            con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM src.main.dataset_metadata
                """
            ).fetchall()
        )
        source_version = source_metadata.get("dataset_version")
        add_check(
            checks,
            "source_dataset_version_matches",
            source_version == INPUT_VERSION,
            source_version,
            INPUT_VERSION,
        )

        con.execute(
            """
            CREATE TABLE model_registry (
                model_key VARCHAR,
                model_label VARCHAR,
                is_primary BOOLEAN,
                uses_support_reliability BOOLEAN,
                caps_negative_event_pool BOOLEAN,
                model_description VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO model_registry VALUES (?, ?, ?, ?, ?, ?)",
            MODEL_ROWS,
        )

        con.execute(
            """
            CREATE TABLE school_metadata AS
            SELECT *
            FROM src.main.school_metadata
            """
        )
        con.execute(
            """
            CREATE TABLE balanced_event_registry AS
            SELECT *
            FROM src.main.balanced_event_registry
            """
        )
        con.execute(
            """
            CREATE TABLE source_athlete_units AS
            SELECT *
            FROM src.main.athlete_event_development_units
            """
        )

        support_prior_strength = float(
            con.execute(
                """
                SELECT GREATEST(
                    1.0,
                    MEDIAN(minimum_training_support::DOUBLE)
                )
                FROM source_athlete_units
                WHERE cohort_key = 'broad_all_athletes'
                  AND time_scope = 'all_time'
                """
            ).fetchone()[0]
        )

        print(
            "Empirical support prior strength: "
            f"{support_prior_strength:.3f}"
        )

        # --------------------------------------------------------------
        # Build both model signals from the same original athlete units.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE athlete_model_signals AS
            SELECT
                m.model_key,
                m.model_label,
                m.is_primary,
                m.uses_support_reliability,
                m.caps_negative_event_pool,
                u.*,
                GREATEST(
                    COALESCE(u.minimum_training_support, 1),
                    1
                )::DOUBLE AS evidence_support_n,
                CASE
                    WHEN m.uses_support_reliability
                        THEN SQRT(
                            evidence_support_n
                            / (
                                evidence_support_n
                                + {support_prior_strength}
                            )
                        )
                    ELSE 1.0
                END AS reliability_factor,
                u.athlete_development_signal
                    AS original_development_signal,
                u.athlete_development_signal
                    * reliability_factor
                    AS model_development_signal
            FROM source_athlete_units u
            CROSS JOIN model_registry m
            """
        )

        event_partition = """
            model_key,
            cohort_key,
            time_scope,
            season_year,
            season_type,
            gender_scope,
            canonical_event_code
        """

        con.execute(
            f"""
            CREATE TABLE athlete_model_points AS
            WITH signal_parts AS (
                SELECT
                    *,
                    GREATEST(
                        model_development_signal,
                        0.0
                    ) AS positive_model_signal,
                    LEAST(
                        model_development_signal,
                        0.0
                    ) AS negative_model_signal
                FROM athlete_model_signals
            ),
            partition_totals AS (
                SELECT
                    *,
                    SUM(positive_model_signal) OVER (
                        PARTITION BY {event_partition}
                    ) AS total_positive_model_signal,
                    SUM(negative_model_signal) OVER (
                        PARTITION BY {event_partition}
                    ) AS total_negative_model_signal,
                    COUNT(*) OVER (
                        PARTITION BY {event_partition}
                    ) AS event_athlete_unit_count,
                    COUNT(DISTINCT resolved_school_id) OVER (
                        PARTITION BY {event_partition}
                    ) AS event_school_count
                FROM signal_parts
            ),
            pool_policy AS (
                SELECT
                    *,
                    {POSITIVE_EVENT_BUDGET}
                        / NULLIF(
                            total_positive_model_signal,
                            0
                        ) AS positive_points_per_signal_unit,
                    ABS(total_negative_model_signal)
                        / NULLIF(
                            total_positive_model_signal,
                            0
                        ) AS raw_negative_to_positive_ratio,
                    CASE
                        WHEN caps_negative_event_pool
                            THEN {NEGATIVE_EVENT_CAP}
                                * LEAST(
                                    ABS(total_negative_model_signal)
                                    / NULLIF(
                                        total_positive_model_signal,
                                        0
                                    ),
                                    1.0
                                )
                        ELSE {POSITIVE_EVENT_BUDGET}
                            * ABS(total_negative_model_signal)
                            / NULLIF(
                                total_positive_model_signal,
                                0
                            )
                    END AS negative_pool_magnitude
                FROM partition_totals
                WHERE total_positive_model_signal
                        > {SIGNAL_TOLERANCE}
            )
            SELECT
                *,
                CASE
                    WHEN ABS(total_negative_model_signal)
                            > {SIGNAL_TOLERANCE}
                        THEN negative_pool_magnitude
                            / ABS(total_negative_model_signal)
                    ELSE 0.0
                END AS negative_points_per_signal_unit,
                positive_model_signal
                    * positive_points_per_signal_unit
                    AS athlete_positive_points,
                negative_model_signal
                    * negative_points_per_signal_unit
                    AS athlete_negative_points,
                athlete_positive_points
                    + athlete_negative_points
                    AS athlete_net_points,
                positive_model_signal
                    / NULLIF(
                        total_positive_model_signal,
                        0
                    ) AS positive_event_point_share,
                athlete_net_points
                    / {POSITIVE_EVENT_BUDGET}
                    AS net_event_point_share,
                CASE
                    WHEN original_development_signal
                            > {SIGNAL_TOLERANCE}
                        THEN 'positive_development'
                    WHEN original_development_signal
                            < -{SIGNAL_TOLERANCE}
                        THEN 'negative_regression'
                    ELSE 'neutral_development'
                END AS development_direction,
                CASE
                    WHEN caps_negative_event_pool
                     AND raw_negative_to_positive_ratio > 1.0
                        THEN TRUE
                    ELSE FALSE
                END AS negative_pool_was_capped,
                {POSITIVE_EVENT_BUDGET}::DOUBLE
                    AS positive_event_budget,
                '{DATASET_VERSION}' AS dataset_version,
                '{POLICY_VERSION}' AS policy_version
            FROM pool_policy
            """
        )

        # --------------------------------------------------------------
        # School event results.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE school_event_model_points AS
            WITH school_totals AS (
                SELECT
                    {event_partition},
                    ANY_VALUE(model_label) AS model_label,
                    BOOL_OR(is_primary) AS is_primary,
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(publication_tier)
                        AS publication_tier,
                    ANY_VALUE(season_key) AS season_key,
                    ANY_VALUE(season_label) AS season_label,
                    ANY_VALUE(canonical_event_name)
                        AS canonical_event_name,
                    ANY_VALUE(balanced_group_key)
                        AS balanced_group_key,
                    ANY_VALUE(balanced_group_label)
                        AS balanced_group_label,
                    resolved_school_id,
                    ANY_VALUE(school_name) AS school_name,
                    COUNT(*) AS athlete_unit_count,
                    COUNT(*) FILTER (
                        WHERE development_direction
                            = 'positive_development'
                    ) AS positive_athlete_count,
                    COUNT(*) FILTER (
                        WHERE development_direction
                            = 'negative_regression'
                    ) AS negative_athlete_count,
                    COUNT(*) FILTER (
                        WHERE development_direction
                            = 'neutral_development'
                    ) AS neutral_athlete_count,
                    SUM(trajectory_count) AS trajectory_count,
                    AVG(mean_baseline_level)
                        AS mean_baseline_level,
                    AVG(mean_endpoint_level)
                        AS mean_endpoint_level,
                    AVG(mean_observed_improvement)
                        AS mean_observed_improvement,
                    AVG(mean_expected_improvement)
                        AS mean_expected_improvement,
                    AVG(original_development_signal)
                        AS school_mean_original_signal,
                    AVG(model_development_signal)
                        AS school_mean_model_signal,
                    SUM(original_development_signal)
                        AS school_total_original_signal,
                    SUM(model_development_signal)
                        AS school_total_model_signal,
                    SUM(positive_model_signal)
                        AS school_positive_model_signal,
                    SUM(negative_model_signal)
                        AS school_negative_model_signal,
                    SUM(athlete_positive_points)
                        AS positive_event_points,
                    SUM(athlete_negative_points)
                        AS negative_event_points,
                    SUM(athlete_net_points)
                        AS net_event_points,
                    AVG(reliability_factor)
                        AS mean_reliability_factor,
                    MIN(evidence_support_n)
                        AS minimum_evidence_support,
                    MAX(event_athlete_unit_count)
                        AS event_athlete_unit_count,
                    MAX(event_school_count)
                        AS event_school_count,
                    MAX(raw_negative_to_positive_ratio)
                        AS raw_negative_to_positive_ratio,
                    BOOL_OR(negative_pool_was_capped)
                        AS negative_pool_was_capped
                FROM athlete_model_points
                GROUP BY
                    {event_partition},
                    resolved_school_id
            ),
            ranked AS (
                SELECT
                    *,
                    RANK() OVER (
                        PARTITION BY {event_partition}
                        ORDER BY
                            net_event_points DESC,
                            positive_event_points DESC,
                            athlete_unit_count DESC
                    ) AS source_rank,
                    COUNT(*) OVER (
                        PARTITION BY {event_partition}
                    ) AS ranked_school_count
                FROM school_totals
            )
            SELECT
                *,
                net_event_points AS event_balanced_points,
                positive_event_points
                    / {POSITIVE_EVENT_BUDGET}
                    AS positive_event_point_share,
                net_event_points
                    / {POSITIVE_EVENT_BUDGET}
                    AS event_point_share,
                school_mean_model_signal
                    AS posterior_school_score,
                school_positive_model_signal
                    AS relative_development_strength,
                CASE
                    WHEN athlete_unit_count >= 8
                        THEN 'strong_sample'
                    WHEN athlete_unit_count >= 5
                        THEN 'moderate_sample'
                    WHEN athlete_unit_count >= 3
                        THEN 'limited_sample'
                    ELSE 'single_or_small_sample'
                END AS evidence_category,
                CASE
                    WHEN athlete_unit_count >= 8
                        THEN 'high'
                    WHEN athlete_unit_count >= 5
                        THEN 'medium'
                    ELSE 'low'
                END AS reliability_tier,
                CASE
                    WHEN positive_event_points > 0
                        THEN 'positive_formula_share'
                    WHEN negative_event_points < 0
                        THEN 'negative_regression_only'
                    ELSE 'neutral'
                END AS scoring_status,
                {POSITIVE_EVENT_BUDGET}::DOUBLE
                    AS event_budget,
                '{DATASET_VERSION}' AS dataset_version
            FROM ranked
            """
        )

        # --------------------------------------------------------------
        # Event budget and negative-pool audit.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE event_budget_audit AS
            SELECT
                {event_partition},
                ANY_VALUE(model_label) AS model_label,
                ANY_VALUE(cohort_label) AS cohort_label,
                ANY_VALUE(season_key) AS season_key,
                ANY_VALUE(season_label) AS season_label,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(balanced_group_key)
                    AS balanced_group_key,
                ANY_VALUE(balanced_group_label)
                    AS balanced_group_label,
                COUNT(*) AS ranked_school_count,
                SUM(athlete_unit_count)
                    AS athlete_unit_count,
                SUM(positive_event_points)
                    AS distributed_positive_event_points,
                SUM(negative_event_points)
                    AS distributed_negative_event_points,
                SUM(net_event_points)
                    AS distributed_net_event_points,
                {POSITIVE_EVENT_BUDGET}::DOUBLE
                    AS required_positive_event_points,
                SUM(positive_event_points)
                    - {POSITIVE_EVENT_BUDGET}
                    AS positive_budget_difference,
                MAX(raw_negative_to_positive_ratio)
                    AS raw_negative_to_positive_ratio,
                BOOL_OR(negative_pool_was_capped)
                    AS negative_pool_was_capped,
                ABS(SUM(negative_event_points))
                    AS negative_pool_magnitude,
                ABS(SUM(negative_event_points))
                    / {POSITIVE_EVENT_BUDGET}
                    AS negative_pool_to_positive_budget_ratio
            FROM school_event_model_points
            GROUP BY {event_partition}
            """
        )

        # --------------------------------------------------------------
        # Overall rankings.
        # --------------------------------------------------------------
        overall_gender_partition = """
            model_key,
            cohort_key,
            time_scope,
            season_year,
            season_type,
            gender_scope
        """

        con.execute(
            f"""
            CREATE TABLE event_balanced_overall_gender AS
            WITH partition_events AS (
                SELECT
                    {overall_gender_partition},
                    COUNT(DISTINCT canonical_event_code)
                        AS publishable_event_count
                FROM school_event_model_points
                GROUP BY {overall_gender_partition}
            ),
            school_totals AS (
                SELECT
                    {overall_gender_partition},
                    ANY_VALUE(model_label) AS model_label,
                    BOOL_OR(is_primary) AS is_primary,
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(publication_tier)
                        AS publication_tier,
                    ANY_VALUE(season_key) AS season_key,
                    ANY_VALUE(season_label) AS season_label,
                    resolved_school_id,
                    ANY_VALUE(school_name) AS school_name,
                    SUM(positive_event_points)
                        AS total_positive_event_points,
                    SUM(negative_event_points)
                        AS total_negative_event_points,
                    SUM(net_event_points)
                        AS total_event_balanced_points,
                    SUM(athlete_unit_count)
                        AS athlete_event_unit_count,
                    SUM(positive_athlete_count)
                        AS positive_athlete_count,
                    SUM(negative_athlete_count)
                        AS negative_athlete_count,
                    COUNT(DISTINCT canonical_event_code) FILTER (
                        WHERE positive_event_points > 0
                    ) AS scoring_event_count,
                    COUNT(DISTINCT canonical_event_code)
                        AS represented_event_count
                FROM school_event_model_points
                GROUP BY
                    {overall_gender_partition},
                    resolved_school_id
            )
            SELECT
                s.*,
                p.publishable_event_count,
                p.publishable_event_count
                    * {POSITIVE_EVENT_BUDGET}
                    AS available_event_points,
                s.total_positive_event_points
                    / NULLIF(
                        p.publishable_event_count
                            * {POSITIVE_EVENT_BUDGET},
                        0
                    ) AS positive_share_of_available_points,
                s.total_event_balanced_points
                    / NULLIF(
                        p.publishable_event_count
                            * {POSITIVE_EVENT_BUDGET},
                        0
                    ) AS percent_of_available_points,
                s.total_event_balanced_points
                    / NULLIF(s.athlete_event_unit_count, 0)
                    AS net_points_per_athlete_event_unit,
                RANK() OVER (
                    PARTITION BY {overall_gender_partition}
                    ORDER BY
                        s.total_event_balanced_points DESC,
                        s.total_positive_event_points DESC,
                        s.scoring_event_count DESC
                ) AS event_balanced_rank,
                '{DATASET_VERSION}' AS dataset_version
            FROM school_totals s
            JOIN partition_events p
              USING (
                model_key,
                cohort_key,
                time_scope,
                season_year,
                season_type,
                gender_scope
              )
            """
        )

        combined_partition = """
            model_key,
            cohort_key,
            time_scope,
            season_year,
            season_type
        """

        con.execute(
            f"""
            CREATE TABLE event_balanced_overall_combined AS
            WITH partition_events AS (
                SELECT
                    {combined_partition},
                    COUNT(DISTINCT
                        gender_scope || '|'
                        || canonical_event_code
                    ) AS publishable_event_count
                FROM school_event_model_points
                GROUP BY {combined_partition}
            ),
            school_totals AS (
                SELECT
                    {combined_partition},
                    ANY_VALUE(model_label) AS model_label,
                    BOOL_OR(is_primary) AS is_primary,
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(publication_tier)
                        AS publication_tier,
                    ANY_VALUE(season_key) AS season_key,
                    ANY_VALUE(season_label) AS season_label,
                    resolved_school_id,
                    ANY_VALUE(school_name) AS school_name,
                    SUM(positive_event_points)
                        AS total_positive_event_points,
                    SUM(negative_event_points)
                        AS total_negative_event_points,
                    SUM(net_event_points)
                        AS total_event_balanced_points,
                    SUM(positive_event_points) FILTER (
                        WHERE gender_scope = 'm'
                    ) AS men_positive_event_points,
                    SUM(negative_event_points) FILTER (
                        WHERE gender_scope = 'm'
                    ) AS men_negative_event_points,
                    SUM(net_event_points) FILTER (
                        WHERE gender_scope = 'm'
                    ) AS men_event_balanced_points,
                    SUM(positive_event_points) FILTER (
                        WHERE gender_scope = 'f'
                    ) AS women_positive_event_points,
                    SUM(negative_event_points) FILTER (
                        WHERE gender_scope = 'f'
                    ) AS women_negative_event_points,
                    SUM(net_event_points) FILTER (
                        WHERE gender_scope = 'f'
                    ) AS women_event_balanced_points,
                    SUM(athlete_unit_count)
                        AS athlete_event_unit_count,
                    SUM(positive_athlete_count)
                        AS positive_athlete_count,
                    SUM(negative_athlete_count)
                        AS negative_athlete_count,
                    COUNT(DISTINCT
                        gender_scope || '|'
                        || canonical_event_code
                    ) FILTER (
                        WHERE positive_event_points > 0
                    ) AS scoring_event_count,
                    COUNT(DISTINCT
                        gender_scope || '|'
                        || canonical_event_code
                    ) AS represented_event_count
                FROM school_event_model_points
                GROUP BY
                    {combined_partition},
                    resolved_school_id
            )
            SELECT
                s.*,
                p.publishable_event_count,
                p.publishable_event_count
                    * {POSITIVE_EVENT_BUDGET}
                    AS available_event_points,
                s.total_positive_event_points
                    / NULLIF(
                        p.publishable_event_count
                            * {POSITIVE_EVENT_BUDGET},
                        0
                    ) AS positive_share_of_available_points,
                s.total_event_balanced_points
                    / NULLIF(
                        p.publishable_event_count
                            * {POSITIVE_EVENT_BUDGET},
                        0
                    ) AS percent_of_available_points,
                s.total_event_balanced_points
                    / NULLIF(s.athlete_event_unit_count, 0)
                    AS net_points_per_athlete_event_unit,
                RANK() OVER (
                    PARTITION BY {combined_partition}
                    ORDER BY
                        s.total_event_balanced_points DESC,
                        s.total_positive_event_points DESC,
                        s.scoring_event_count DESC
                ) AS event_balanced_rank,
                '{DATASET_VERSION}' AS dataset_version
            FROM school_totals s
            JOIN partition_events p
              USING (
                model_key,
                cohort_key,
                time_scope,
                season_year,
                season_type
              )
            """
        )

        # --------------------------------------------------------------
        # Group points and group-balanced overall rankings.
        # --------------------------------------------------------------
        group_gender_partition = """
            model_key,
            cohort_key,
            time_scope,
            season_year,
            season_type,
            gender_scope,
            balanced_group_key
        """

        con.execute(
            f"""
            CREATE TABLE group_balanced_points_gender AS
            WITH group_events AS (
                SELECT
                    {group_gender_partition},
                    ANY_VALUE(balanced_group_label)
                        AS balanced_group_label,
                    COUNT(DISTINCT canonical_event_code)
                        AS group_event_count
                FROM school_event_model_points
                GROUP BY {group_gender_partition}
            ),
            school_group_totals AS (
                SELECT
                    {group_gender_partition},
                    ANY_VALUE(model_label) AS model_label,
                    BOOL_OR(is_primary) AS is_primary,
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(publication_tier)
                        AS publication_tier,
                    ANY_VALUE(season_key) AS season_key,
                    ANY_VALUE(season_label) AS season_label,
                    ANY_VALUE(balanced_group_label)
                        AS balanced_group_label,
                    resolved_school_id,
                    ANY_VALUE(school_name) AS school_name,
                    SUM(positive_event_points)
                        AS raw_positive_group_points,
                    SUM(negative_event_points)
                        AS raw_negative_group_points,
                    SUM(net_event_points)
                        AS raw_net_group_points,
                    SUM(athlete_unit_count)
                        AS athlete_event_unit_count,
                    SUM(positive_athlete_count)
                        AS positive_athlete_count,
                    SUM(negative_athlete_count)
                        AS negative_athlete_count,
                    COUNT(DISTINCT canonical_event_code) FILTER (
                        WHERE positive_event_points > 0
                    ) AS group_scoring_event_count,
                    COUNT(DISTINCT canonical_event_code)
                        AS group_represented_event_count
                FROM school_event_model_points
                GROUP BY
                    {group_gender_partition},
                    resolved_school_id
            ),
            normalized AS (
                SELECT
                    s.*,
                    g.group_event_count,
                    s.raw_positive_group_points
                        / g.group_event_count
                        AS positive_group_points,
                    s.raw_negative_group_points
                        / g.group_event_count
                        AS negative_group_points,
                    s.raw_net_group_points
                        / g.group_event_count
                        AS group_balanced_points
                FROM school_group_totals s
                JOIN group_events g
                  USING (
                    model_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    gender_scope,
                    balanced_group_key
                  )
            )
            SELECT
                *,
                positive_group_points
                    / {POSITIVE_GROUP_BUDGET}
                    AS positive_group_point_share,
                group_balanced_points
                    / {POSITIVE_GROUP_BUDGET}
                    AS group_point_share,
                group_balanced_points
                    / {POSITIVE_GROUP_BUDGET}
                    AS group_strength_share,
                RANK() OVER (
                    PARTITION BY {group_gender_partition}
                    ORDER BY
                        group_balanced_points DESC,
                        positive_group_points DESC
                ) AS group_source_rank,
                COUNT(*) OVER (
                    PARTITION BY {group_gender_partition}
                ) AS group_ranked_school_count,
                {POSITIVE_GROUP_BUDGET}::DOUBLE
                    AS group_budget,
                CASE
                    WHEN positive_group_points > 0
                        THEN 'positive_formula_share'
                    WHEN negative_group_points < 0
                        THEN 'negative_regression_only'
                    ELSE 'neutral'
                END AS scoring_status,
                '{DATASET_VERSION}' AS dataset_version
            FROM normalized
            """
        )

        con.execute(
            """
            CREATE TABLE group_balanced_points_combined AS
            WITH partition_availability AS (
                SELECT
                    model_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    balanced_group_key,
                    ANY_VALUE(balanced_group_label)
                        AS balanced_group_label,
                    COUNT(DISTINCT gender_scope)
                        AS available_gender_count
                FROM group_balanced_points_gender
                GROUP BY
                    model_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    balanced_group_key
            ),
            school_values AS (
                SELECT
                    model_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    balanced_group_key,
                    resolved_school_id,
                    ANY_VALUE(model_label) AS model_label,
                    BOOL_OR(is_primary) AS is_primary,
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(publication_tier)
                        AS publication_tier,
                    ANY_VALUE(season_key) AS season_key,
                    ANY_VALUE(season_label) AS season_label,
                    ANY_VALUE(school_name) AS school_name,
                    SUM(positive_group_points)
                        AS summed_positive_group_points,
                    SUM(negative_group_points)
                        AS summed_negative_group_points,
                    SUM(group_balanced_points)
                        AS summed_net_group_points,
                    SUM(athlete_event_unit_count)
                        AS athlete_event_unit_count,
                    SUM(positive_athlete_count)
                        AS positive_athlete_count,
                    SUM(negative_athlete_count)
                        AS negative_athlete_count,
                    SUM(group_scoring_event_count)
                        AS group_scoring_event_count,
                    SUM(group_represented_event_count)
                        AS group_represented_event_count,
                    MAX(positive_group_points) FILTER (
                        WHERE gender_scope = 'm'
                    ) AS men_positive_group_points,
                    MAX(negative_group_points) FILTER (
                        WHERE gender_scope = 'm'
                    ) AS men_negative_group_points,
                    MAX(group_balanced_points) FILTER (
                        WHERE gender_scope = 'm'
                    ) AS men_group_points,
                    MAX(positive_group_points) FILTER (
                        WHERE gender_scope = 'f'
                    ) AS women_positive_group_points,
                    MAX(negative_group_points) FILTER (
                        WHERE gender_scope = 'f'
                    ) AS women_negative_group_points,
                    MAX(group_balanced_points) FILTER (
                        WHERE gender_scope = 'f'
                    ) AS women_group_points
                FROM group_balanced_points_gender
                GROUP BY
                    model_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    balanced_group_key,
                    resolved_school_id
            ),
            normalized AS (
                SELECT
                    s.*,
                    p.balanced_group_label,
                    p.available_gender_count,
                    s.summed_positive_group_points
                        / p.available_gender_count
                        AS positive_group_points,
                    s.summed_negative_group_points
                        / p.available_gender_count
                        AS negative_group_points,
                    s.summed_net_group_points
                        / p.available_gender_count
                        AS group_balanced_points
                FROM school_values s
                JOIN partition_availability p
                  USING (
                    model_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    balanced_group_key
                  )
            )
            SELECT
                *,
                positive_group_points / 100000.0
                    AS positive_group_point_share,
                group_balanced_points / 100000.0
                    AS group_point_share,
                group_balanced_points / 100000.0
                    AS combined_group_strength_share,
                RANK() OVER (
                    PARTITION BY
                        model_key,
                        cohort_key,
                        time_scope,
                        season_year,
                        season_type,
                        balanced_group_key
                    ORDER BY
                        group_balanced_points DESC,
                        positive_group_points DESC
                ) AS group_source_rank,
                COUNT(*) OVER (
                    PARTITION BY
                        model_key,
                        cohort_key,
                        time_scope,
                        season_year,
                        season_type,
                        balanced_group_key
                ) AS group_ranked_school_count,
                100000.0 AS group_budget,
                CASE
                    WHEN positive_group_points > 0
                        THEN 'positive_formula_share'
                    WHEN negative_group_points < 0
                        THEN 'negative_regression_only'
                    ELSE 'neutral'
                END AS scoring_status,
                '{DATASET_VERSION}' AS dataset_version
            FROM normalized
            """
        )

        con.execute(
            f"""
            CREATE TABLE group_budget_audit AS
            SELECT
                model_key,
                ANY_VALUE(model_label) AS model_label,
                cohort_key,
                ANY_VALUE(cohort_label) AS cohort_label,
                time_scope,
                season_year,
                season_type,
                gender_scope,
                balanced_group_key,
                ANY_VALUE(balanced_group_label)
                    AS balanced_group_label,
                COUNT(*) AS ranked_school_count,
                SUM(positive_group_points)
                    AS distributed_positive_group_points,
                SUM(negative_group_points)
                    AS distributed_negative_group_points,
                SUM(group_balanced_points)
                    AS distributed_net_group_points,
                {POSITIVE_GROUP_BUDGET}::DOUBLE
                    AS required_positive_group_points,
                SUM(positive_group_points)
                    - {POSITIVE_GROUP_BUDGET}
                    AS positive_budget_difference
            FROM group_balanced_points_gender
            GROUP BY
                model_key,
                cohort_key,
                time_scope,
                season_year,
                season_type,
                gender_scope,
                balanced_group_key

            UNION ALL

            SELECT
                model_key,
                ANY_VALUE(model_label),
                cohort_key,
                ANY_VALUE(cohort_label),
                time_scope,
                season_year,
                season_type,
                'all',
                balanced_group_key,
                ANY_VALUE(balanced_group_label),
                COUNT(*),
                SUM(positive_group_points),
                SUM(negative_group_points),
                SUM(group_balanced_points),
                {POSITIVE_GROUP_BUDGET}::DOUBLE,
                SUM(positive_group_points)
                    - {POSITIVE_GROUP_BUDGET}
            FROM group_balanced_points_combined
            GROUP BY
                model_key,
                cohort_key,
                time_scope,
                season_year,
                season_type,
                balanced_group_key
            """
        )

        con.execute(
            f"""
            CREATE TABLE group_balanced_overall_gender AS
            WITH partition_groups AS (
                SELECT
                    model_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    gender_scope,
                    COUNT(DISTINCT balanced_group_key)
                        AS publishable_group_count
                FROM group_balanced_points_gender
                GROUP BY
                    model_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    gender_scope
            ),
            school_totals AS (
                SELECT
                    model_key,
                    ANY_VALUE(model_label) AS model_label,
                    BOOL_OR(is_primary) AS is_primary,
                    cohort_key,
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(publication_tier)
                        AS publication_tier,
                    time_scope,
                    season_year,
                    season_type,
                    ANY_VALUE(season_key) AS season_key,
                    ANY_VALUE(season_label) AS season_label,
                    gender_scope,
                    resolved_school_id,
                    ANY_VALUE(school_name) AS school_name,
                    SUM(positive_group_points)
                        AS total_positive_group_points,
                    SUM(negative_group_points)
                        AS total_negative_group_points,
                    SUM(group_balanced_points)
                        AS total_group_balanced_points,
                    SUM(athlete_event_unit_count)
                        AS athlete_event_unit_count,
                    SUM(positive_athlete_count)
                        AS positive_athlete_count,
                    SUM(negative_athlete_count)
                        AS negative_athlete_count,
                    COUNT(DISTINCT balanced_group_key) FILTER (
                        WHERE positive_group_points > 0
                    ) AS scoring_group_count,
                    COUNT(DISTINCT balanced_group_key)
                        AS represented_group_count
                FROM group_balanced_points_gender
                GROUP BY
                    model_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    gender_scope,
                    resolved_school_id
            )
            SELECT
                s.*,
                p.publishable_group_count,
                p.publishable_group_count
                    * {POSITIVE_GROUP_BUDGET}
                    AS available_group_points,
                s.total_positive_group_points
                    / NULLIF(
                        p.publishable_group_count
                            * {POSITIVE_GROUP_BUDGET},
                        0
                    ) AS positive_share_of_available_group_points,
                s.total_group_balanced_points
                    / NULLIF(
                        p.publishable_group_count
                            * {POSITIVE_GROUP_BUDGET},
                        0
                    ) AS percent_of_available_group_points,
                RANK() OVER (
                    PARTITION BY
                        s.model_key,
                        s.cohort_key,
                        s.time_scope,
                        s.season_year,
                        s.season_type,
                        s.gender_scope
                    ORDER BY
                        s.total_group_balanced_points DESC,
                        s.total_positive_group_points DESC
                ) AS group_balanced_rank,
                '{DATASET_VERSION}' AS dataset_version
            FROM school_totals s
            JOIN partition_groups p
              USING (
                model_key,
                cohort_key,
                time_scope,
                season_year,
                season_type,
                gender_scope
              )
            """
        )

        con.execute(
            f"""
            CREATE TABLE group_balanced_overall_combined AS
            WITH partition_groups AS (
                SELECT
                    model_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    COUNT(DISTINCT balanced_group_key)
                        AS publishable_group_count
                FROM group_balanced_points_combined
                GROUP BY
                    model_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type
            ),
            school_totals AS (
                SELECT
                    model_key,
                    ANY_VALUE(model_label) AS model_label,
                    BOOL_OR(is_primary) AS is_primary,
                    cohort_key,
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(publication_tier)
                        AS publication_tier,
                    time_scope,
                    season_year,
                    season_type,
                    ANY_VALUE(season_key) AS season_key,
                    ANY_VALUE(season_label) AS season_label,
                    resolved_school_id,
                    ANY_VALUE(school_name) AS school_name,
                    SUM(positive_group_points)
                        AS total_positive_group_points,
                    SUM(negative_group_points)
                        AS total_negative_group_points,
                    SUM(group_balanced_points)
                        AS total_group_balanced_points,
                    SUM(athlete_event_unit_count)
                        AS athlete_event_unit_count,
                    SUM(positive_athlete_count)
                        AS positive_athlete_count,
                    SUM(negative_athlete_count)
                        AS negative_athlete_count,
                    COUNT(DISTINCT balanced_group_key) FILTER (
                        WHERE positive_group_points > 0
                    ) AS scoring_group_count,
                    COUNT(DISTINCT balanced_group_key)
                        AS represented_group_count
                FROM group_balanced_points_combined
                GROUP BY
                    model_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    resolved_school_id
            )
            SELECT
                s.*,
                p.publishable_group_count,
                p.publishable_group_count
                    * {POSITIVE_GROUP_BUDGET}
                    AS available_group_points,
                s.total_positive_group_points
                    / NULLIF(
                        p.publishable_group_count
                            * {POSITIVE_GROUP_BUDGET},
                        0
                    ) AS positive_share_of_available_group_points,
                s.total_group_balanced_points
                    / NULLIF(
                        p.publishable_group_count
                            * {POSITIVE_GROUP_BUDGET},
                        0
                    ) AS percent_of_available_group_points,
                RANK() OVER (
                    PARTITION BY
                        s.model_key,
                        s.cohort_key,
                        s.time_scope,
                        s.season_year,
                        s.season_type
                    ORDER BY
                        s.total_group_balanced_points DESC,
                        s.total_positive_group_points DESC
                ) AS group_balanced_rank,
                '{DATASET_VERSION}' AS dataset_version
            FROM school_totals s
            JOIN partition_groups p
              USING (
                model_key,
                cohort_key,
                time_scope,
                season_year,
                season_type
              )
            """
        )

        # --------------------------------------------------------------
        # Concentration diagnostics.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE event_concentration_diagnostics AS
            WITH positive_athletes AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY {event_partition}
                        ORDER BY athlete_positive_points DESC
                    ) AS positive_athlete_order
                FROM athlete_model_points
                WHERE athlete_positive_points > 0
            ),
            athlete_concentration AS (
                SELECT
                    {event_partition},
                    ANY_VALUE(model_label) AS model_label,
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(season_label) AS season_label,
                    ANY_VALUE(canonical_event_name)
                        AS canonical_event_name,
                    COUNT(*) AS positive_athlete_count,
                    MAX(positive_event_point_share)
                        AS largest_athlete_positive_share,
                    SUM(positive_event_point_share) FILTER (
                        WHERE positive_athlete_order <= 5
                    ) AS top_five_athlete_positive_share,
                    SUM(
                        positive_event_point_share
                        * positive_event_point_share
                    ) AS athlete_positive_hhi,
                    1.0 / NULLIF(
                        SUM(
                            positive_event_point_share
                            * positive_event_point_share
                        ),
                        0
                    ) AS effective_positive_athlete_count
                FROM positive_athletes
                GROUP BY {event_partition}
            ),
            positive_schools AS (
                SELECT
                    *,
                    positive_event_points
                        / {POSITIVE_EVENT_BUDGET}
                        AS school_positive_share
                FROM school_event_model_points
                WHERE positive_event_points > 0
            ),
            school_concentration AS (
                SELECT
                    {event_partition},
                    COUNT(*) AS positive_school_count,
                    MAX(school_positive_share)
                        AS largest_school_positive_share,
                    SUM(
                        school_positive_share
                        * school_positive_share
                    ) AS school_positive_hhi,
                    1.0 / NULLIF(
                        SUM(
                            school_positive_share
                            * school_positive_share
                        ),
                        0
                    ) AS effective_positive_school_count
                FROM positive_schools
                GROUP BY {event_partition}
            )
            SELECT
                a.*,
                s.positive_school_count,
                s.largest_school_positive_share,
                s.school_positive_hhi,
                s.effective_positive_school_count,
                CASE
                    WHEN a.largest_athlete_positive_share > 0.25
                      OR a.effective_positive_athlete_count < 5
                        THEN 'high_athlete_concentration'
                    WHEN a.largest_athlete_positive_share > 0.15
                      OR a.effective_positive_athlete_count < 10
                        THEN 'moderate_athlete_concentration'
                    ELSE 'distributed_athlete_contributions'
                END AS athlete_concentration_flag,
                CASE
                    WHEN s.largest_school_positive_share > 0.40
                      OR s.effective_positive_school_count < 4
                        THEN 'high_school_concentration'
                    WHEN s.largest_school_positive_share > 0.25
                      OR s.effective_positive_school_count < 8
                        THEN 'moderate_school_concentration'
                    ELSE 'distributed_school_contributions'
                END AS school_concentration_flag
            FROM athlete_concentration a
            JOIN school_concentration s
              USING (
                model_key,
                cohort_key,
                time_scope,
                season_year,
                season_type,
                gender_scope,
                canonical_event_code
              )
            """
        )

        # --------------------------------------------------------------
        # Roster-size dependence.
        # --------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE roster_size_dependence AS
            SELECT
                model_key,
                ANY_VALUE(model_label) AS model_label,
                cohort_key,
                ANY_VALUE(cohort_label) AS cohort_label,
                time_scope,
                season_year,
                season_type,
                COUNT(*) AS ranked_school_count,
                CORR(
                    total_event_balanced_points,
                    athlete_event_unit_count
                ) AS net_points_roster_size_correlation,
                CORR(
                    total_positive_event_points,
                    athlete_event_unit_count
                ) AS positive_points_roster_size_correlation,
                CORR(
                    total_event_balanced_points,
                    positive_athlete_count
                ) AS net_points_positive_athlete_correlation,
                CORR(
                    total_event_balanced_points,
                    net_points_per_athlete_event_unit
                ) AS net_points_efficiency_correlation,
                AVG(athlete_event_unit_count)
                    AS mean_athlete_event_unit_count,
                MEDIAN(athlete_event_unit_count)
                    AS median_athlete_event_unit_count
            FROM event_balanced_overall_combined
            GROUP BY
                model_key,
                cohort_key,
                time_scope,
                season_year,
                season_type
            """
        )

        # --------------------------------------------------------------
        # Elite reward audit.
        # This is diagnostic rather than a hard gate because actual athlete
        # data mixes different event conditions and improvement magnitudes.
        # --------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE elite_reward_audit AS
            WITH positive_improvement AS (
                SELECT
                    *,
                    CASE
                        WHEN mean_baseline_level < 70
                            THEN 'below_70'
                        WHEN mean_baseline_level < 80
                            THEN '70_to_79_99'
                        WHEN mean_baseline_level < 90
                            THEN '80_to_89_99'
                        WHEN mean_baseline_level < 95
                            THEN '90_to_94_99'
                        ELSE '95_plus'
                    END AS baseline_band,
                    CASE
                        WHEN mean_baseline_level < 70 THEN 1
                        WHEN mean_baseline_level < 80 THEN 2
                        WHEN mean_baseline_level < 90 THEN 3
                        WHEN mean_baseline_level < 95 THEN 4
                        ELSE 5
                    END AS baseline_band_order
                FROM athlete_model_points
                WHERE cohort_key = 'broad_all_athletes'
                  AND time_scope = 'all_time'
                  AND mean_observed_improvement > 0
            )
            SELECT
                model_key,
                ANY_VALUE(model_label) AS model_label,
                baseline_band,
                baseline_band_order,
                COUNT(*) AS athlete_unit_count,
                AVG(mean_baseline_level)
                    AS mean_baseline_level,
                AVG(mean_observed_improvement)
                    AS mean_observed_improvement,
                AVG(original_development_signal)
                    AS mean_original_development_signal,
                AVG(model_development_signal)
                    AS mean_model_development_signal,
                MEDIAN(original_development_signal)
                    AS median_original_development_signal,
                MEDIAN(model_development_signal)
                    AS median_model_development_signal,
                AVG(
                    original_development_signal
                    / NULLIF(mean_observed_improvement, 0)
                ) AS mean_original_signal_per_observed_unit,
                AVG(
                    model_development_signal
                    / NULLIF(mean_observed_improvement, 0)
                ) AS mean_model_signal_per_observed_unit,
                AVG(athlete_positive_points) FILTER (
                    WHERE athlete_positive_points > 0
                ) AS mean_positive_points_per_positive_athlete
            FROM positive_improvement
            GROUP BY
                model_key,
                baseline_band,
                baseline_band_order
            ORDER BY
                model_key,
                baseline_band_order
            """
        )

        con.execute(
            """
            CREATE TABLE elite_reward_monotonicity_summary AS
            WITH ordered AS (
                SELECT
                    *,
                    LAG(mean_original_signal_per_observed_unit) OVER (
                        PARTITION BY model_key
                        ORDER BY baseline_band_order
                    ) AS prior_original_rate,
                    LAG(mean_model_signal_per_observed_unit) OVER (
                        PARTITION BY model_key
                        ORDER BY baseline_band_order
                    ) AS prior_model_rate
                FROM elite_reward_audit
            )
            SELECT
                model_key,
                ANY_VALUE(model_label) AS model_label,
                COUNT(*) AS baseline_band_count,
                COUNT(*) FILTER (
                    WHERE prior_original_rate IS NOT NULL
                      AND mean_original_signal_per_observed_unit
                            >= prior_original_rate
                ) AS nondecreasing_original_transitions,
                COUNT(*) FILTER (
                    WHERE prior_model_rate IS NOT NULL
                      AND mean_model_signal_per_observed_unit
                            >= prior_model_rate
                ) AS nondecreasing_model_transitions,
                MAX(mean_original_signal_per_observed_unit) FILTER (
                    WHERE baseline_band = '95_plus'
                ) AS elite_95_original_rate,
                MAX(mean_original_signal_per_observed_unit) FILTER (
                    WHERE baseline_band = '70_to_79_99'
                ) AS baseline_70_original_rate,
                MAX(mean_model_signal_per_observed_unit) FILTER (
                    WHERE baseline_band = '95_plus'
                ) AS elite_95_model_rate,
                MAX(mean_model_signal_per_observed_unit) FILTER (
                    WHERE baseline_band = '70_to_79_99'
                ) AS baseline_70_model_rate
            FROM ordered
            GROUP BY model_key
            """
        )

        # --------------------------------------------------------------
        # Enhanced versus original v4.1 model comparison.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE model_rank_comparison_school AS
            SELECT
                a.cohort_key,
                a.cohort_label,
                a.time_scope,
                a.season_year,
                a.season_type,
                a.resolved_school_id,
                a.school_name,
                a.event_balanced_rank AS enhanced_rank,
                b.event_balanced_rank AS original_v4_1_rank,
                a.total_event_balanced_points
                    AS enhanced_net_points,
                b.total_event_balanced_points
                    AS original_v4_1_net_points,
                a.event_balanced_rank
                    - b.event_balanced_rank
                    AS rank_shift,
                ABS(
                    a.event_balanced_rank
                    - b.event_balanced_rank
                ) AS absolute_rank_shift
            FROM event_balanced_overall_combined a
            JOIN event_balanced_overall_combined b
              ON a.cohort_key = b.cohort_key
             AND a.time_scope = b.time_scope
             AND a.season_year IS NOT DISTINCT FROM b.season_year
             AND a.season_type = b.season_type
             AND a.resolved_school_id = b.resolved_school_id
            WHERE a.model_key = '{PRIMARY_MODEL_KEY}'
              AND b.model_key = '{LEGACY_MODEL_KEY}'
            """
        )

        con.execute(
            """
            CREATE TABLE model_rank_comparison_summary AS
            SELECT
                cohort_key,
                ANY_VALUE(cohort_label) AS cohort_label,
                time_scope,
                season_year,
                season_type,
                COUNT(*) AS shared_school_count,
                CORR(enhanced_rank, original_v4_1_rank)
                    AS rank_correlation,
                CORR(
                    enhanced_net_points,
                    original_v4_1_net_points
                ) AS score_correlation,
                AVG(absolute_rank_shift)
                    AS mean_absolute_rank_shift,
                MEDIAN(absolute_rank_shift)
                    AS median_absolute_rank_shift,
                MAX(absolute_rank_shift)
                    AS maximum_absolute_rank_shift,
                COUNT(*) FILTER (
                    WHERE enhanced_rank <= 10
                      AND original_v4_1_rank <= 10
                )::DOUBLE
                    / NULLIF(
                        COUNT(*) FILTER (
                            WHERE original_v4_1_rank <= 10
                        ),
                        0
                    ) AS top_10_overlap_share,
                COUNT(*) FILTER (
                    WHERE enhanced_rank <= 25
                      AND original_v4_1_rank <= 25
                )::DOUBLE
                    / NULLIF(
                        COUNT(*) FILTER (
                            WHERE original_v4_1_rank <= 25
                        ),
                        0
                    ) AS top_25_overlap_share,
                COUNT(*) FILTER (
                    WHERE enhanced_rank <= 50
                      AND original_v4_1_rank <= 50
                )::DOUBLE
                    / NULLIF(
                        COUNT(*) FILTER (
                            WHERE original_v4_1_rank <= 50
                        ),
                        0
                    ) AS top_50_overlap_share
            FROM model_rank_comparison_school
            GROUP BY
                cohort_key,
                time_scope,
                season_year,
                season_type
            """
        )

        # --------------------------------------------------------------
        # Validation.
        # --------------------------------------------------------------
        counts = fetch_dicts(
            con,
            """
            SELECT
                (SELECT COUNT(*) FROM model_registry)
                    AS model_count,
                (SELECT COUNT(*) FROM source_athlete_units)
                    AS source_athlete_unit_count,
                (SELECT COUNT(*) FROM athlete_model_points)
                    AS athlete_model_point_count,
                (SELECT COUNT(*) FROM school_event_model_points)
                    AS school_event_model_count,
                (SELECT COUNT(*) FROM event_budget_audit)
                    AS event_budget_partition_count,
                (SELECT COUNT(*) FROM group_budget_audit)
                    AS group_budget_partition_count,
                (SELECT COUNT(*) FROM event_concentration_diagnostics)
                    AS concentration_row_count,
                (SELECT COUNT(*) FROM roster_size_dependence)
                    AS roster_audit_row_count,
                (SELECT COUNT(*) FROM elite_reward_audit)
                    AS elite_reward_row_count,
                (SELECT COUNT(*) FROM model_rank_comparison_summary)
                    AS comparison_summary_row_count
            """
        )[0]

        quality = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM event_budget_audit
                 WHERE ABS(positive_budget_difference)
                    > {POINT_TOLERANCE})
                    AS invalid_positive_event_budgets,
                (SELECT COUNT(*)
                 FROM group_budget_audit
                 WHERE ABS(positive_budget_difference)
                    > {POINT_TOLERANCE})
                    AS invalid_positive_group_budgets,
                (SELECT COUNT(*)
                 FROM event_budget_audit
                 WHERE model_key = '{PRIMARY_MODEL_KEY}'
                   AND negative_pool_magnitude
                        > {NEGATIVE_EVENT_CAP}
                            + {POINT_TOLERANCE})
                    AS enhanced_negative_caps_exceeded,
                (SELECT COUNT(*)
                 FROM athlete_model_points
                 WHERE athlete_positive_points < -{POINT_TOLERANCE})
                    AS invalid_positive_athlete_points,
                (SELECT COUNT(*)
                 FROM athlete_model_points
                 WHERE athlete_negative_points > {POINT_TOLERANCE})
                    AS invalid_negative_athlete_points,
                (SELECT COUNT(*)
                 FROM athlete_model_points
                 WHERE reliability_factor <= 0
                    OR reliability_factor > 1)
                    AS invalid_reliability_factors,
                (SELECT MAX(ABS(
                    new.athlete_positive_points
                    - old.athlete_positive_points
                 ))
                 FROM athlete_model_points new
                 JOIN src.main.athlete_event_development_points old
                   ON new.cohort_key = old.cohort_key
                  AND new.time_scope = old.time_scope
                  AND new.season_year
                        IS NOT DISTINCT FROM old.season_year
                  AND new.season_type = old.season_type
                  AND new.gender_scope = old.gender_scope
                  AND new.canonical_event_code
                        = old.canonical_event_code
                  AND new.canonical_person_id
                        = old.canonical_person_id
                  AND new.resolved_school_id
                        = old.resolved_school_id
                 WHERE new.model_key = '{LEGACY_MODEL_KEY}')
                    AS legacy_positive_point_error,
                (SELECT MAX(ABS(
                    new.athlete_negative_points
                    - old.athlete_negative_points
                 ))
                 FROM athlete_model_points new
                 JOIN src.main.athlete_event_development_points old
                   ON new.cohort_key = old.cohort_key
                  AND new.time_scope = old.time_scope
                  AND new.season_year
                        IS NOT DISTINCT FROM old.season_year
                  AND new.season_type = old.season_type
                  AND new.gender_scope = old.gender_scope
                  AND new.canonical_event_code
                        = old.canonical_event_code
                  AND new.canonical_person_id
                        = old.canonical_person_id
                  AND new.resolved_school_id
                        = old.resolved_school_id
                 WHERE new.model_key = '{LEGACY_MODEL_KEY}')
                    AS legacy_negative_point_error,
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        model_key,
                        cohort_key,
                        time_scope,
                        season_year,
                        season_type,
                        gender_scope,
                        canonical_event_code,
                        canonical_person_id,
                        resolved_school_id,
                        COUNT(*) AS row_count
                    FROM athlete_model_points
                    GROUP BY
                        model_key,
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
                    AS duplicate_athlete_model_keys
            """
        )[0]

        add_check(
            checks,
            "model_count",
            counts["model_count"] == 2,
            counts["model_count"],
            2,
        )
        add_check(
            checks,
            "all_source_units_exist_in_both_models",
            counts["athlete_model_point_count"]
                == counts["source_athlete_unit_count"] * 2,
            counts["athlete_model_point_count"],
            counts["source_athlete_unit_count"] * 2,
        )
        add_check(
            checks,
            "all_positive_event_pools_equal_100000",
            quality["invalid_positive_event_budgets"] == 0,
            quality["invalid_positive_event_budgets"],
            0,
        )
        add_check(
            checks,
            "all_positive_group_pools_equal_100000",
            quality["invalid_positive_group_budgets"] == 0,
            quality["invalid_positive_group_budgets"],
            0,
        )
        add_check(
            checks,
            "enhanced_negative_event_pools_bounded",
            quality["enhanced_negative_caps_exceeded"] == 0,
            quality["enhanced_negative_caps_exceeded"],
            0,
        )
        add_check(
            checks,
            "positive_athlete_points_nonnegative",
            quality["invalid_positive_athlete_points"] == 0,
            quality["invalid_positive_athlete_points"],
            0,
        )
        add_check(
            checks,
            "negative_athlete_points_nonpositive",
            quality["invalid_negative_athlete_points"] == 0,
            quality["invalid_negative_athlete_points"],
            0,
        )
        add_check(
            checks,
            "reliability_factors_valid",
            quality["invalid_reliability_factors"] == 0,
            quality["invalid_reliability_factors"],
            0,
        )
        add_check(
            checks,
            "legacy_positive_points_reproduce_v4_1",
            float(quality["legacy_positive_point_error"])
                <= POINT_TOLERANCE,
            quality["legacy_positive_point_error"],
            f"<= {POINT_TOLERANCE}",
        )
        add_check(
            checks,
            "legacy_negative_points_reproduce_v4_1",
            float(quality["legacy_negative_point_error"])
                <= POINT_TOLERANCE,
            quality["legacy_negative_point_error"],
            f"<= {POINT_TOLERANCE}",
        )
        add_check(
            checks,
            "athlete_model_keys_unique",
            quality["duplicate_athlete_model_keys"] == 0,
            quality["duplicate_athlete_model_keys"],
            0,
        )
        add_check(
            checks,
            "concentration_diagnostics_exist",
            counts["concentration_row_count"] > 0,
            counts["concentration_row_count"],
            "greater than 0",
        )
        add_check(
            checks,
            "roster_size_audit_exists",
            counts["roster_audit_row_count"] > 0,
            counts["roster_audit_row_count"],
            "greater than 0",
        )
        add_check(
            checks,
            "elite_reward_audit_exists",
            counts["elite_reward_row_count"] > 0,
            counts["elite_reward_row_count"],
            "greater than 0",
        )
        add_check(
            checks,
            "model_comparison_exists",
            counts["comparison_summary_row_count"] > 0,
            counts["comparison_summary_row_count"],
            "greater than 0",
        )

        # --------------------------------------------------------------
        # Exports.
        # --------------------------------------------------------------
        export_specs = (
            (
                "model_registry.csv",
                "SELECT * FROM model_registry ORDER BY is_primary DESC",
            ),
            (
                "athlete_model_points.csv",
                """
                SELECT *
                FROM athlete_model_points
                ORDER BY
                    model_key,
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    canonical_event_name,
                    athlete_net_points DESC
                """,
            ),
            (
                "event_balanced_point_rows.csv",
                """
                SELECT *
                FROM school_event_model_points
                ORDER BY
                    model_key,
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    canonical_event_name,
                    source_rank
                """,
            ),
            (
                "event_budget_audit.csv",
                """
                SELECT *
                FROM event_budget_audit
                ORDER BY
                    model_key,
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    canonical_event_name
                """,
            ),
            (
                "event_balanced_overall_gender.csv",
                """
                SELECT *
                FROM event_balanced_overall_gender
                ORDER BY
                    model_key,
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    event_balanced_rank
                """,
            ),
            (
                "event_balanced_overall_combined.csv",
                """
                SELECT *
                FROM event_balanced_overall_combined
                ORDER BY
                    model_key,
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    event_balanced_rank
                """,
            ),
            (
                "group_balanced_points_gender.csv",
                """
                SELECT *
                FROM group_balanced_points_gender
                ORDER BY
                    model_key,
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    balanced_group_label,
                    group_source_rank
                """,
            ),
            (
                "group_balanced_points_combined.csv",
                """
                SELECT *
                FROM group_balanced_points_combined
                ORDER BY
                    model_key,
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    balanced_group_label,
                    group_source_rank
                """,
            ),
            (
                "group_budget_audit.csv",
                """
                SELECT *
                FROM group_budget_audit
                ORDER BY
                    model_key,
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    balanced_group_label
                """,
            ),
            (
                "group_balanced_overall_gender.csv",
                """
                SELECT *
                FROM group_balanced_overall_gender
                ORDER BY
                    model_key,
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    group_balanced_rank
                """,
            ),
            (
                "group_balanced_overall_combined.csv",
                """
                SELECT *
                FROM group_balanced_overall_combined
                ORDER BY
                    model_key,
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    group_balanced_rank
                """,
            ),
            (
                "event_concentration_diagnostics.csv",
                """
                SELECT *
                FROM event_concentration_diagnostics
                ORDER BY
                    model_key,
                    largest_athlete_positive_share DESC
                """,
            ),
            (
                "roster_size_dependence.csv",
                """
                SELECT *
                FROM roster_size_dependence
                ORDER BY
                    model_key,
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type
                """,
            ),
            (
                "elite_reward_audit.csv",
                """
                SELECT *
                FROM elite_reward_audit
                ORDER BY model_key, baseline_band_order
                """,
            ),
            (
                "elite_reward_monotonicity_summary.csv",
                """
                SELECT *
                FROM elite_reward_monotonicity_summary
                ORDER BY model_key
                """,
            ),
            (
                "model_rank_comparison_school.csv",
                """
                SELECT *
                FROM model_rank_comparison_school
                ORDER BY
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    enhanced_rank
                """,
            ),
            (
                "model_rank_comparison_summary.csv",
                """
                SELECT *
                FROM model_rank_comparison_summary
                ORDER BY
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type
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
            SELECT 'positive_event_budget',
                   '{POSITIVE_EVENT_BUDGET}'
            UNION ALL
            SELECT 'positive_group_budget',
                   '{POSITIVE_GROUP_BUDGET}'
            UNION ALL
            SELECT 'enhanced_negative_event_cap',
                   '{NEGATIVE_EVENT_CAP}'
            UNION ALL
            SELECT 'support_prior_strength',
                   '{support_prior_strength}'
            UNION ALL
            SELECT
                'support_reliability_formula',
                'sqrt(n / (n + empirical_median_support))'
            UNION ALL
            SELECT
                'elite_multiplier',
                'none; elite difficulty remains in original nonlinear level and expected-improvement model'
            UNION ALL
            SELECT 'created_at_utc', CURRENT_TIMESTAMP::VARCHAR
            """
        )

        comparison_overall = fetch_dicts(
            con,
            """
            SELECT
                AVG(rank_correlation) AS mean_rank_correlation,
                AVG(mean_absolute_rank_shift)
                    AS mean_of_partition_mean_absolute_shifts,
                MIN(top_25_overlap_share)
                    AS minimum_top_25_overlap_share
            FROM model_rank_comparison_summary
            """
        )[0]

        negative_summary = fetch_dicts(
            con,
            f"""
            SELECT
                COUNT(*) FILTER (
                    WHERE model_key = '{PRIMARY_MODEL_KEY}'
                      AND negative_pool_was_capped
                ) AS capped_enhanced_event_partitions,
                MAX(negative_pool_to_positive_budget_ratio) FILTER (
                    WHERE model_key = '{PRIMARY_MODEL_KEY}'
                ) AS maximum_enhanced_negative_ratio,
                MAX(negative_pool_to_positive_budget_ratio) FILTER (
                    WHERE model_key = '{LEGACY_MODEL_KEY}'
                ) AS maximum_legacy_negative_ratio
            FROM event_budget_audit
            """
        )[0]

    finally:
        con.close()

    input_hashes_after = {
        str(SOURCE_DB): sha256_file(SOURCE_DB),
        str(SOURCE_CHECKS): sha256_file(SOURCE_CHECKS),
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
            for path in (SOURCE_DB, SOURCE_CHECKS)
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

    report = [
        "MILESTONE 6 PHASE 6E — DEVELOPMENT MODEL VARIANTS",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "MODELS",
        "-" * 78,
        "Primary: Enhanced Balanced Production",
        "  - original athlete development signal",
        "  - empirical support reliability",
        "  - exactly 100,000 positive points per event",
        "  - negative event pool capped at 100,000",
        "",
        "Legacy: Original Balanced Production v4.1",
        "  - exact validated Phase 6D v4.1 reproduction",
        "  - no support reliability",
        "  - uncapped linear negative points",
        "",
        "Average Athlete Development remains available in the explorer as "
        "the separate efficiency-oriented ranking.",
        "",
        "PARAMETERS",
        "-" * 78,
        f"Empirical support prior strength: "
        f"{support_prior_strength:.3f}",
        f"Positive event budget: {POSITIVE_EVENT_BUDGET:,.0f}",
        f"Enhanced negative event cap: {NEGATIVE_EVENT_CAP:,.0f}",
        "",
        "MODEL COMPARISON",
        "-" * 78,
        f"Mean partition rank correlation: "
        f"{float(comparison_overall['mean_rank_correlation']):.6f}",
        f"Mean of partition mean absolute rank shifts: "
        f"{float(comparison_overall['mean_of_partition_mean_absolute_shifts']):.3f}",
        f"Minimum top-25 overlap share: "
        f"{float(comparison_overall['minimum_top_25_overlap_share']):.3f}",
        "",
        "NEGATIVE-POOL AUDIT",
        "-" * 78,
        f"Enhanced event partitions capped: "
        f"{int(negative_summary['capped_enhanced_event_partitions']):,}",
        f"Maximum enhanced negative/positive ratio: "
        f"{float(negative_summary['maximum_enhanced_negative_ratio']):.3f}",
        f"Maximum legacy negative/positive ratio: "
        f"{float(negative_summary['maximum_legacy_negative_ratio']):.3f}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Enhanced and original balanced models published."
            if not failed
            else "FAIL — Review hard checks."
        ),
    ]

    (OUTPUT_DIR / "phase_6e_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Athlete model-point rows: "
        f"{int(counts['athlete_model_point_count']):,}"
    )
    print(
        f"Event budget partitions: "
        f"{int(counts['event_budget_partition_count']):,}"
    )
    print(
        f"Enhanced capped negative partitions: "
        f"{int(negative_summary['capped_enhanced_event_partitions']):,}"
    )
    print(
        f"Mean enhanced/original rank correlation: "
        f"{float(comparison_overall['mean_rank_correlation']):.6f}"
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
    print("Next: compare models and inspect fairness diagnostics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
