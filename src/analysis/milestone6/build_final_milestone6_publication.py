#!/usr/bin/env python3
"""
Milestone 6 Phase 6G — Final Model Freeze and Publication

Official model hierarchy
------------------------
Primary:
    Enhanced Balanced Production
    - original athlete value-added signal
    - support reliability k = 191
    - 100,000 positive points per event
    - negative event pool capped at 100,000

Balanced-production companion:
    Original Balanced Production v4.1

Efficiency companion:
    Average Athlete Development from Phases 6A and 6B

This phase does not recalculate development. It validates, freezes, and
publishes the selected model and its companion views in one self-contained
DuckDB database and a final set of CSV publications.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


ROOT = Path.cwd()

PHASE_6A_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "seasonal_development_rankings_v1/"
      "phase_6a_seasonal_rankings"
)
PHASE_6A_DB = PHASE_6A_DIR / "seasonal_development_rankings_v1.duckdb"
PHASE_6A_CHECKS = PHASE_6A_DIR / "hard_checks.csv"

PHASE_6B_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "seasonal_elite_development_v1/"
      "phase_6b_seasonal_elite_rankings"
)
PHASE_6B_DB = (
    PHASE_6B_DIR / "seasonal_elite_development_rankings_v1.duckdb"
)
PHASE_6B_CHECKS = PHASE_6B_DIR / "hard_checks.csv"

PHASE_6E_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "development_model_variants_v1/"
      "phase_6e_model_variants"
)
PHASE_6E_DB = PHASE_6E_DIR / "development_model_variants_v1.duckdb"
PHASE_6E_CHECKS = PHASE_6E_DIR / "hard_checks.csv"

PHASE_6F_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "development_model_validation_v1/"
      "phase_6f_final_validation"
)
PHASE_6F_DB = (
    PHASE_6F_DIR / "development_model_validation_v1.duckdb"
)
PHASE_6F_CHECKS = PHASE_6F_DIR / "hard_checks.csv"

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "final_development_rankings_v1/"
      "phase_6g_final_publication"
)
OUTPUT_DB = OUTPUT_DIR / "final_development_rankings_v1.duckdb"

INPUT_6A_VERSION = "seasonal_development_rankings_v1_1"
INPUT_6B_VERSION = "seasonal_elite_development_rankings_v1_2"
INPUT_6E_VERSION = "development_model_variants_v1"
INPUT_6F_VERSION = "development_model_validation_v1_2"

DATASET_VERSION = "final_development_rankings_v1"
POLICY_VERSION = "enhanced_k191_cap1_frozen_v1"

PRIMARY_MODEL_KEY = "enhanced_balanced_production"
PRIMARY_MODEL_LABEL = "Enhanced Balanced Production"
LEGACY_MODEL_KEY = "original_balanced_production_v4_1"
LEGACY_MODEL_LABEL = "Original Balanced Production v4.1"
VALIDATION_REFERENCE_VARIANT = "support_k191_cap1"
VALIDATION_ORIGINAL_VARIANT = "original_v4_1_uncapped"

SUPPORT_K = 191.0
POSITIVE_EVENT_BUDGET = 100_000.0
NEGATIVE_EVENT_CAP = 100_000.0
POINT_TOLERANCE = 1e-6


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


def metadata_version(
    connection: duckdb.DuckDBPyConnection,
    attached_name: str,
) -> str | None:
    rows = connection.execute(
        f"""
        SELECT metadata_key, metadata_value
        FROM {attached_name}.main.dataset_metadata
        """
    ).fetchall()
    return dict(rows).get("dataset_version")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    print("MILESTONE 6 PHASE 6G — FINAL MODEL FREEZE AND PUBLICATION")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Official primary model: {PRIMARY_MODEL_LABEL}")
    print(f"Output database: {OUTPUT_DB}")

    required_inputs = (
        PHASE_6A_DB,
        PHASE_6A_CHECKS,
        PHASE_6B_DB,
        PHASE_6B_CHECKS,
        PHASE_6E_DB,
        PHASE_6E_CHECKS,
        PHASE_6F_DB,
        PHASE_6F_CHECKS,
    )

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
        print("PHASE GATE: FAIL — Required inputs are missing.")
        return 1

    upstream_gates = {
        "phase_6a_gate_passed": hard_checks_pass(PHASE_6A_CHECKS),
        "phase_6b_gate_passed": hard_checks_pass(PHASE_6B_CHECKS),
        "phase_6e_gate_passed": hard_checks_pass(PHASE_6E_CHECKS),
        "phase_6f_gate_passed": hard_checks_pass(PHASE_6F_CHECKS),
    }

    for name, passed in upstream_gates.items():
        add_check(checks, name, passed, passed, True)

    if not all(upstream_gates.values()):
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — An upstream phase did not pass.")
        return 1

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
            f"ATTACH '{sql_path(PHASE_6A_DB)}' AS p6a (READ_ONLY)"
        )
        con.execute(
            f"ATTACH '{sql_path(PHASE_6B_DB)}' AS p6b (READ_ONLY)"
        )
        con.execute(
            f"ATTACH '{sql_path(PHASE_6E_DB)}' AS p6e (READ_ONLY)"
        )
        con.execute(
            f"ATTACH '{sql_path(PHASE_6F_DB)}' AS p6f (READ_ONLY)"
        )

        versions = {
            "p6a": metadata_version(con, "p6a"),
            "p6b": metadata_version(con, "p6b"),
            "p6e": metadata_version(con, "p6e"),
            "p6f": metadata_version(con, "p6f"),
        }
        expected_versions = {
            "p6a": INPUT_6A_VERSION,
            "p6b": INPUT_6B_VERSION,
            "p6e": INPUT_6E_VERSION,
            "p6f": INPUT_6F_VERSION,
        }

        for attached_name, expected in expected_versions.items():
            add_check(
                checks,
                f"{attached_name}_version_matches",
                versions[attached_name] == expected,
                versions[attached_name],
                expected,
            )

        # --------------------------------------------------------------
        # Frozen model registry.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE final_model_registry AS
            SELECT
                1 AS display_order,
                '{PRIMARY_MODEL_KEY}' AS model_key,
                '{PRIMARY_MODEL_LABEL}' AS model_label,
                'official_primary' AS model_role,
                TRUE AS is_official_primary,
                TRUE AS uses_support_reliability,
                {SUPPORT_K}::DOUBLE AS support_k,
                TRUE AS caps_negative_event_pool,
                {NEGATIVE_EVENT_CAP}::DOUBLE
                    AS negative_event_cap,
                {POSITIVE_EVENT_BUDGET}::DOUBLE
                    AS positive_event_budget,
                (
                    'Total reliable athlete development production with '
                    'equal event budgets.'
                ) AS interpretation

            UNION ALL

            SELECT
                2,
                '{LEGACY_MODEL_KEY}',
                '{LEGACY_MODEL_LABEL}',
                'balanced_production_companion',
                FALSE,
                FALSE,
                0.0,
                FALSE,
                NULL::DOUBLE,
                {POSITIVE_EVENT_BUDGET}::DOUBLE,
                (
                    'Exact validated Phase 6D v4.1 athlete-production '
                    'formula.'
                )

            UNION ALL

            SELECT
                3,
                'average_athlete_development',
                'Average Athlete Development',
                'efficiency_companion',
                FALSE,
                TRUE,
                NULL::DOUBLE,
                FALSE,
                NULL::DOUBLE,
                NULL::DOUBLE,
                (
                    'School-average uncertainty-adjusted development; '
                    'answers how well the typical athlete developed.'
                )
            """
        )

        # --------------------------------------------------------------
        # Shared metadata and event registry.
        # --------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE school_metadata AS
            SELECT *
            FROM p6e.main.school_metadata
            """
        )
        con.execute(
            """
            CREATE TABLE balanced_event_registry AS
            SELECT *
            FROM p6e.main.balanced_event_registry
            """
        )

        # --------------------------------------------------------------
        # Balanced-production models.
        # Store both selected and legacy models in final tables.
        # --------------------------------------------------------------
        balanced_tables = (
            "athlete_model_points",
            "school_event_model_points",
            "event_budget_audit",
            "event_balanced_overall_gender",
            "event_balanced_overall_combined",
            "group_balanced_points_gender",
            "group_balanced_points_combined",
            "group_budget_audit",
            "group_balanced_overall_gender",
            "group_balanced_overall_combined",
        )

        for table_name in balanced_tables:
            con.execute(
                f"""
                CREATE TABLE {table_name} AS
                SELECT *
                FROM p6e.main.{table_name}
                WHERE model_key IN (
                    '{PRIMARY_MODEL_KEY}',
                    '{LEGACY_MODEL_KEY}'
                )
                """
            )

        # Convenience official-primary tables.
        con.execute(
            f"""
            CREATE VIEW official_athlete_points AS
            SELECT *
            FROM athlete_model_points
            WHERE model_key = '{PRIMARY_MODEL_KEY}'
            """
        )
        con.execute(
            f"""
            CREATE VIEW official_school_event_points AS
            SELECT *
            FROM school_event_model_points
            WHERE model_key = '{PRIMARY_MODEL_KEY}'
            """
        )
        con.execute(
            f"""
            CREATE VIEW official_overall_gender AS
            SELECT *
            FROM event_balanced_overall_gender
            WHERE model_key = '{PRIMARY_MODEL_KEY}'
            """
        )
        con.execute(
            f"""
            CREATE VIEW official_overall_combined AS
            SELECT *
            FROM event_balanced_overall_combined
            WHERE model_key = '{PRIMARY_MODEL_KEY}'
            """
        )
        con.execute(
            f"""
            CREATE VIEW official_group_points_gender AS
            SELECT *
            FROM group_balanced_points_gender
            WHERE model_key = '{PRIMARY_MODEL_KEY}'
            """
        )
        con.execute(
            f"""
            CREATE VIEW official_group_points_combined AS
            SELECT *
            FROM group_balanced_points_combined
            WHERE model_key = '{PRIMARY_MODEL_KEY}'
            """
        )
        con.execute(
            f"""
            CREATE VIEW official_group_overall_gender AS
            SELECT *
            FROM group_balanced_overall_gender
            WHERE model_key = '{PRIMARY_MODEL_KEY}'
            """
        )
        con.execute(
            f"""
            CREATE VIEW official_group_overall_combined AS
            SELECT *
            FROM group_balanced_overall_combined
            WHERE model_key = '{PRIMARY_MODEL_KEY}'
            """
        )

        # --------------------------------------------------------------
        # Average Athlete Development companion tables.
        # --------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE average_development_seasonal_rankings AS
            SELECT *
            FROM p6a.main.seasonal_rankings
            """
        )
        con.execute(
            """
            CREATE TABLE average_development_elite_rankings AS
            SELECT *
            FROM p6b.main.seasonal_elite_rankings
            """
        )

        # --------------------------------------------------------------
        # Final validation and diagnostic tables.
        # --------------------------------------------------------------
        phase_6e_diagnostic_tables = (
            "event_concentration_diagnostics",
            "roster_size_dependence",
            "elite_reward_audit",
            "elite_reward_monotonicity_summary",
            "model_rank_comparison_school",
            "model_rank_comparison_summary",
        )
        for table_name in phase_6e_diagnostic_tables:
            con.execute(
                f"""
                CREATE TABLE {table_name} AS
                SELECT *
                FROM p6e.main.{table_name}
                """
            )

        phase_6f_tables = (
            "validation_variant_registry",
            "validation_rank_stability_summary",
            "validation_concentration_summary",
            "validation_roster_summary",
            "elite_matched_slope_summary",
            "elite_matched_band_summary",
            "final_model_scorecard",
        )
        for table_name in phase_6f_tables:
            con.execute(
                f"""
                CREATE TABLE {table_name} AS
                SELECT *
                FROM p6f.main.{table_name}
                """
            )

        # --------------------------------------------------------------
        # Decision record.
        # --------------------------------------------------------------
        original_comparison = fetch_dicts(
            con,
            f"""
            SELECT *
            FROM final_model_scorecard
            WHERE variant_key = '{VALIDATION_ORIGINAL_VARIANT}'
            """
        )[0]

        selected_scorecard = fetch_dicts(
            con,
            f"""
            SELECT *
            FROM final_model_scorecard
            WHERE variant_key = '{VALIDATION_REFERENCE_VARIANT}'
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

        con.execute(
            f"""
            CREATE TABLE final_model_decision AS
            SELECT
                '{PRIMARY_MODEL_KEY}' AS selected_model_key,
                '{PRIMARY_MODEL_LABEL}' AS selected_model_label,
                {SUPPORT_K}::DOUBLE AS support_k,
                {POSITIVE_EVENT_BUDGET}::DOUBLE
                    AS positive_event_budget,
                {NEGATIVE_EVENT_CAP}::DOUBLE
                    AS negative_event_cap,
                {float(original_comparison['mean_rank_correlation'])}
                    AS rank_correlation_to_original_v4_1,
                {float(original_comparison['mean_top_10_overlap'])}
                    AS mean_top_10_overlap_to_original_v4_1,
                {float(original_comparison['mean_top_25_overlap'])}
                    AS mean_top_25_overlap_to_original_v4_1,
                {float(selected_scorecard['p95_largest_athlete_share'])}
                    AS p95_largest_athlete_share,
                {
                    float(
                        selected_scorecard[
                            'mean_effective_positive_athletes'
                        ]
                    )
                } AS mean_effective_positive_athletes,
                {
                    float(
                        selected_scorecard[
                            'mean_absolute_net_roster_correlation'
                        ]
                    )
                } AS mean_absolute_roster_correlation,
                {
                    float(
                        selected_scorecard[
                            'mean_positive_count_correlation'
                        ]
                    )
                } AS mean_positive_athlete_count_correlation,
                {
                    float(
                        elite_slope[
                            'nonnegative_enhanced_slope_share'
                        ]
                    )
                } AS nonnegative_elite_slope_share,
                {
                    float(
                        elite_band[
                            'enhanced_elite_advantage_share'
                        ]
                    )
                } AS elite_advantage_share,
                {
                    float(
                        elite_band[
                            'median_enhanced_elite_advantage'
                        ]
                    )
                } AS median_elite_advantage,
                FALSE AS extra_elite_multiplier_applied,
                (
                    'Selected after support, negative-cap, rank-stability, '
                    'concentration, roster-size, and matched elite audits.'
                ) AS decision_rationale,
                CURRENT_TIMESTAMP AS frozen_at_utc
            """
        )

        # --------------------------------------------------------------
        # Integrity checks.
        # --------------------------------------------------------------
        counts = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM final_model_registry)
                    AS final_model_registry_count,
                (SELECT COUNT(*)
                 FROM athlete_model_points
                 WHERE model_key = '{PRIMARY_MODEL_KEY}')
                    AS official_athlete_point_count,
                (SELECT COUNT(*)
                 FROM school_event_model_points
                 WHERE model_key = '{PRIMARY_MODEL_KEY}')
                    AS official_school_event_count,
                (SELECT COUNT(*)
                 FROM event_budget_audit
                 WHERE model_key = '{PRIMARY_MODEL_KEY}')
                    AS official_event_partition_count,
                (SELECT COUNT(*)
                 FROM event_balanced_overall_combined
                 WHERE model_key = '{PRIMARY_MODEL_KEY}'
                   AND time_scope = 'single_season')
                    AS official_seasonal_combined_rows,
                (SELECT COUNT(*)
                 FROM average_development_seasonal_rankings)
                    AS average_seasonal_rows,
                (SELECT COUNT(*)
                 FROM average_development_elite_rankings)
                    AS average_elite_rows,
                (SELECT COUNT(*)
                 FROM final_model_decision)
                    AS decision_row_count
            """
        )[0]

        quality = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM event_budget_audit
                 WHERE model_key = '{PRIMARY_MODEL_KEY}'
                   AND ABS(
                       distributed_positive_event_points
                       - {POSITIVE_EVENT_BUDGET}
                   ) > {POINT_TOLERANCE})
                    AS invalid_official_positive_event_budgets,
                (SELECT COUNT(*)
                 FROM event_budget_audit
                 WHERE model_key = '{PRIMARY_MODEL_KEY}'
                   AND negative_pool_magnitude
                        > {NEGATIVE_EVENT_CAP}
                            + {POINT_TOLERANCE})
                    AS official_negative_cap_violations,
                (SELECT COUNT(*)
                 FROM group_budget_audit
                 WHERE model_key = '{PRIMARY_MODEL_KEY}'
                   AND ABS(
                       distributed_positive_group_points
                       - {POSITIVE_EVENT_BUDGET}
                   ) > {POINT_TOLERANCE})
                    AS invalid_official_positive_group_budgets,
                (SELECT COUNT(*)
                 FROM final_model_registry
                 WHERE model_key = '{PRIMARY_MODEL_KEY}'
                   AND is_official_primary
                   AND support_k = {SUPPORT_K}
                   AND negative_event_cap
                        = {NEGATIVE_EVENT_CAP})
                    AS correct_primary_registry_rows,
                (SELECT COUNT(*)
                 FROM final_model_registry
                 WHERE model_key = '{LEGACY_MODEL_KEY}')
                    AS legacy_registry_rows,
                (SELECT COUNT(*)
                 FROM final_model_registry
                 WHERE model_key
                    = 'average_athlete_development')
                    AS average_registry_rows,
                (SELECT COUNT(*)
                 FROM final_model_decision
                 WHERE extra_elite_multiplier_applied)
                    AS unexpected_elite_multiplier_rows,
                (SELECT COUNT(*)
                 FROM final_model_decision
                 WHERE nonnegative_elite_slope_share < 0.60
                    OR elite_advantage_share < 0.60)
                    AS insufficient_elite_evidence_rows,
                (SELECT COUNT(*)
                 FROM final_model_decision
                 WHERE rank_correlation_to_original_v4_1 < 0.95
                    OR mean_top_25_overlap_to_original_v4_1 < 0.80)
                    AS unstable_model_decision_rows
            """
        )[0]

        add_check(
            checks,
            "final_model_registry_complete",
            counts["final_model_registry_count"] == 3,
            counts["final_model_registry_count"],
            3,
        )
        add_check(
            checks,
            "official_athlete_points_exist",
            counts["official_athlete_point_count"] > 0,
            counts["official_athlete_point_count"],
            "greater than 0",
        )
        add_check(
            checks,
            "official_school_event_points_exist",
            counts["official_school_event_count"] > 0,
            counts["official_school_event_count"],
            "greater than 0",
        )
        add_check(
            checks,
            "official_seasonal_rankings_exist",
            counts["official_seasonal_combined_rows"] > 0,
            counts["official_seasonal_combined_rows"],
            "greater than 0",
        )
        add_check(
            checks,
            "average_development_companion_exists",
            (
                counts["average_seasonal_rows"] > 0
                and counts["average_elite_rows"] > 0
            ),
            (
                counts["average_seasonal_rows"],
                counts["average_elite_rows"],
            ),
            "both greater than 0",
        )
        add_check(
            checks,
            "final_decision_row_exists",
            counts["decision_row_count"] == 1,
            counts["decision_row_count"],
            1,
        )
        add_check(
            checks,
            "all_official_positive_event_budgets_equal_100000",
            quality["invalid_official_positive_event_budgets"] == 0,
            quality["invalid_official_positive_event_budgets"],
            0,
        )
        add_check(
            checks,
            "all_official_positive_group_budgets_equal_100000",
            quality["invalid_official_positive_group_budgets"] == 0,
            quality["invalid_official_positive_group_budgets"],
            0,
        )
        add_check(
            checks,
            "official_negative_event_cap_respected",
            quality["official_negative_cap_violations"] == 0,
            quality["official_negative_cap_violations"],
            0,
        )
        add_check(
            checks,
            "official_primary_parameters_frozen",
            quality["correct_primary_registry_rows"] == 1,
            quality["correct_primary_registry_rows"],
            1,
        )
        add_check(
            checks,
            "original_v4_1_companion_preserved",
            quality["legacy_registry_rows"] == 1,
            quality["legacy_registry_rows"],
            1,
        )
        add_check(
            checks,
            "average_development_companion_registered",
            quality["average_registry_rows"] == 1,
            quality["average_registry_rows"],
            1,
        )
        add_check(
            checks,
            "no_extra_elite_multiplier",
            quality["unexpected_elite_multiplier_rows"] == 0,
            quality["unexpected_elite_multiplier_rows"],
            0,
        )
        add_check(
            checks,
            "matched_elite_evidence_supports_current_scale",
            quality["insufficient_elite_evidence_rows"] == 0,
            quality["insufficient_elite_evidence_rows"],
            0,
        )
        add_check(
            checks,
            "official_model_stability_thresholds_passed",
            quality["unstable_model_decision_rows"] == 0,
            quality["unstable_model_decision_rows"],
            0,
        )

        # --------------------------------------------------------------
        # Final metadata.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE dataset_metadata AS
            SELECT
                'dataset_version' AS metadata_key,
                '{DATASET_VERSION}' AS metadata_value
            UNION ALL
            SELECT 'policy_version', '{POLICY_VERSION}'
            UNION ALL
            SELECT 'official_primary_model',
                   '{PRIMARY_MODEL_KEY}'
            UNION ALL
            SELECT 'official_primary_label',
                   '{PRIMARY_MODEL_LABEL}'
            UNION ALL
            SELECT 'support_k', '{SUPPORT_K}'
            UNION ALL
            SELECT 'positive_event_budget',
                   '{POSITIVE_EVENT_BUDGET}'
            UNION ALL
            SELECT 'negative_event_cap',
                   '{NEGATIVE_EVENT_CAP}'
            UNION ALL
            SELECT 'balanced_companion_model',
                   '{LEGACY_MODEL_KEY}'
            UNION ALL
            SELECT 'efficiency_companion_model',
                   'average_athlete_development'
            UNION ALL
            SELECT 'elite_multiplier',
                   'none'
            UNION ALL
            SELECT 'phase_6a_input_version',
                   '{INPUT_6A_VERSION}'
            UNION ALL
            SELECT 'phase_6b_input_version',
                   '{INPUT_6B_VERSION}'
            UNION ALL
            SELECT 'phase_6e_input_version',
                   '{INPUT_6E_VERSION}'
            UNION ALL
            SELECT 'phase_6f_input_version',
                   '{INPUT_6F_VERSION}'
            UNION ALL
            SELECT 'frozen_at_utc',
                   CURRENT_TIMESTAMP::VARCHAR
            """
        )

        # --------------------------------------------------------------
        # Final exports. Names intentionally match explorer expectations.
        # --------------------------------------------------------------
        export_specs = (
            (
                "model_registry.csv",
                """
                SELECT
                    model_key,
                    model_label,
                    is_official_primary AS is_primary,
                    uses_support_reliability,
                    caps_negative_event_pool,
                    interpretation AS model_description,
                    model_role,
                    support_k,
                    negative_event_cap,
                    positive_event_budget
                FROM final_model_registry
                WHERE model_key IN (
                    'enhanced_balanced_production',
                    'original_balanced_production_v4_1'
                )
                ORDER BY display_order
                """,
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
                "SELECT * FROM event_concentration_diagnostics",
            ),
            (
                "roster_size_dependence.csv",
                "SELECT * FROM roster_size_dependence",
            ),
            (
                "elite_reward_audit.csv",
                "SELECT * FROM elite_reward_audit",
            ),
            (
                "elite_reward_monotonicity_summary.csv",
                "SELECT * FROM elite_reward_monotonicity_summary",
            ),
            (
                "model_rank_comparison_summary.csv",
                "SELECT * FROM model_rank_comparison_summary",
            ),
            (
                "model_rank_comparison_school.csv",
                "SELECT * FROM model_rank_comparison_school",
            ),
            (
                "final_model_decision.csv",
                "SELECT * FROM final_model_decision",
            ),
            (
                "final_model_scorecard.csv",
                "SELECT * FROM final_model_scorecard",
            ),
            (
                "average_development_seasonal_rankings.csv",
                "SELECT * FROM average_development_seasonal_rankings",
            ),
            (
                "average_development_elite_rankings.csv",
                "SELECT * FROM average_development_elite_rankings",
            ),
            (
                "official_season_overall_combined.csv",
                f"""
                SELECT *
                FROM official_overall_combined
                WHERE time_scope = 'single_season'
                ORDER BY
                    cohort_key,
                    season_year,
                    season_type,
                    event_balanced_rank
                """,
            ),
            (
                "official_season_overall_gender.csv",
                f"""
                SELECT *
                FROM official_overall_gender
                WHERE time_scope = 'single_season'
                ORDER BY
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    event_balanced_rank
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

        latest_leaders = fetch_dicts(
            con,
            f"""
            WITH latest AS (
                SELECT MAX(season_year) AS latest_year
                FROM official_overall_combined
                WHERE time_scope = 'single_season'
                  AND cohort_key = 'broad_all_athletes'
            )
            SELECT
                season_year,
                season_type,
                event_balanced_rank,
                school_name,
                total_positive_event_points,
                total_negative_event_points,
                total_event_balanced_points
            FROM official_overall_combined, latest
            WHERE time_scope = 'single_season'
              AND cohort_key = 'broad_all_athletes'
              AND season_year = latest.latest_year
              AND event_balanced_rank <= 3
            ORDER BY
                season_type,
                event_balanced_rank
            """
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
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 6 PHASE 6G — FINAL MODEL FREEZE AND PUBLICATION",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "OFFICIAL MODEL",
        "-" * 78,
        f"Primary: {PRIMARY_MODEL_LABEL}",
        f"Support reliability k: {SUPPORT_K:.0f}",
        f"Positive event budget: {POSITIVE_EVENT_BUDGET:,.0f}",
        f"Negative event cap: {NEGATIVE_EVENT_CAP:,.0f}",
        "Extra elite multiplier: none",
        "",
        "COMPANION VIEWS",
        "-" * 78,
        f"Balanced-production companion: {LEGACY_MODEL_LABEL}",
        "Efficiency companion: Average Athlete Development",
        "",
        "VALIDATION",
        "-" * 78,
        f"Rank correlation to Original v4.1: "
        f"{float(original_comparison['mean_rank_correlation']):.6f}",
        f"Mean top-10 overlap: "
        f"{float(original_comparison['mean_top_10_overlap']):.3f}",
        f"Mean top-25 overlap: "
        f"{float(original_comparison['mean_top_25_overlap']):.3f}",
        f"P95 largest athlete share: "
        f"{float(selected_scorecard['p95_largest_athlete_share']):.4f}",
        f"Mean effective positive athletes: "
        f"{float(selected_scorecard['mean_effective_positive_athletes']):.2f}",
        f"Mean absolute roster correlation: "
        f"{float(selected_scorecard['mean_absolute_net_roster_correlation']):.4f}",
        f"Mean positive-athlete-count correlation: "
        f"{float(selected_scorecard['mean_positive_count_correlation']):.4f}",
        f"Matched nonnegative elite slope share: "
        f"{float(elite_slope['nonnegative_enhanced_slope_share']):.3f}",
        f"Matched elite advantage share: "
        f"{float(elite_band['enhanced_elite_advantage_share']):.3f}",
        f"Median matched elite advantage: "
        f"{float(elite_band['median_enhanced_elite_advantage']):.4f}",
        "",
        "FINAL PUBLICATION COUNTS",
        "-" * 78,
        f"Official athlete-point rows: "
        f"{int(counts['official_athlete_point_count']):,}",
        f"Official school-event rows: "
        f"{int(counts['official_school_event_count']):,}",
        f"Official event partitions: "
        f"{int(counts['official_event_partition_count']):,}",
        f"Official single-season combined rows: "
        f"{int(counts['official_seasonal_combined_rows']):,}",
        "",
        "LATEST BROAD LEADERS",
        "-" * 78,
    ]

    for row in latest_leaders:
        report.append(
            f"{int(row['season_year'])} "
            f"{str(row['season_type']).title()} | "
            f"#{int(row['event_balanced_rank'])} "
            f"{row['school_name']} | "
            f"positive={float(row['total_positive_event_points']):,.2f} | "
            f"negative={float(row['total_negative_event_points']):,.2f} | "
            f"net={float(row['total_event_balanced_points']):,.2f}"
        )

    report.extend(
        [
            "",
            "PHASE GATE",
            "-" * 78,
            (
                "PASS — Milestone 6 final model frozen and published."
                if not failed
                else "FAIL — Review hard checks."
            ),
        ]
    )

    (OUTPUT_DIR / "phase_6g_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Official athlete-point rows: "
        f"{int(counts['official_athlete_point_count']):,}"
    )
    print(
        f"Official school-event rows: "
        f"{int(counts['official_school_event_count']):,}"
    )
    print(
        f"Official event partitions: "
        f"{int(counts['official_event_partition_count']):,}"
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
    print("Milestone 6 final model is frozen and published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
