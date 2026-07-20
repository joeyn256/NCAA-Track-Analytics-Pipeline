#!/usr/bin/env python3
"""
Milestone 5 Phase 5K — Supplemental Development Rankings

Creates eight admissions-ready analytical products from the frozen Milestone 5
value-added system without new scraping or new expected-improvement modeling.

Products
--------
1. Development Consistency
   Combines the school median athlete value added and a beta-binomial
   stabilized share of athletes above expected.

2. Elite / Frontier Development
   Ranks schools for trajectories beginning at performance level >= 70.

3. Baseline-Tier Development
   Developing: < 50
   Competitive: 50 to < 65
   Advanced: 65 to < 80
   Elite: >= 80

4. Breakout Rate
   A breakout athlete has athlete-school value added >= 5 points.

5. Balanced Program
   Uses gender-specific posterior scores across six core groups:
   sprints, middle distance, distance, hurdles, jumps, and throws.
   Requires at least eight of twelve gender-group cells, including both
   genders. The index rewards mean strength and penalizes group dispersion,
   gender imbalance, and missing coverage.

6. Development Efficiency
   Ranks annualized athlete-school value added.

7. Ranking Robustness
   Uses all seven approved Phase 5H variants. Programs are ordered by their
   worst approved rank, then average rank and rank spread.

8. Inbound Transfer Development
   Identifies destination schools whose first observed school season occurs
   after the athlete's first observed school season, then ranks destination
   value added with empirical-Bayes shrinkage.

All school-mean rankings use the Phase 5G empirical-Bayes structure with a
20-degree-of-freedom stabilized within-school variance prior.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


ROOT = Path.cwd()

TRAJECTORY_DB = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5e_frozen_expected_improvement_benchmark/"
      "expected_improvement_policy_v1.duckdb"
)
PHASE_5E_CHECKS = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5e_frozen_expected_improvement_benchmark/"
      "hard_checks.csv"
)

CONTRIBUTION_DB = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5f_multi_event_neutral_athlete_contributions/"
      "athlete_contributions_v1.duckdb"
)
PHASE_5F_CHECKS = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5f_multi_event_neutral_athlete_contributions/"
      "hard_checks.csv"
)

AUDIT_DB = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5h_final_ranking_publication_audit/"
      "ranking_publication_audit_v1.duckdb"
)
PHASE_5H_CHECKS = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5h_final_ranking_publication_audit/"
      "hard_checks.csv"
)

PUBLICATION_DB = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5i_publication_freeze/"
      "ncaa_d1_athlete_development_rankings_v1.duckdb"
)
PHASE_5I_CHECKS = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5i_publication_freeze/"
      "hard_checks.csv"
)

EVENT_DB = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5j_event_and_group_rankings/"
      "ncaa_d1_event_development_rankings_v1.duckdb"
)
PHASE_5J_CHECKS = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5j_event_and_group_rankings/"
      "hard_checks.csv"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5k_supplemental_development_rankings"
)
OUTPUT_DB = OUTPUT_DIR / "supplemental_development_rankings_v1.duckdb"

INPUT_TRAJECTORY_VERSION = "expected_improvement_policy_v1_1"
INPUT_CONTRIBUTION_VERSION = "athlete_contributions_v1"
INPUT_AUDIT_VERSION = "ranking_publication_audit_v1_1"
INPUT_PUBLICATION_VERSION = "ncaa_d1_athlete_development_rankings_v1"
INPUT_EVENT_VERSION = "ncaa_d1_event_development_rankings_v1_1"

DATASET_VERSION = "supplemental_development_rankings_v1"
POLICY_VERSION = "supplemental_development_rankings_policy_v1"

EXPECTED_TRAJECTORY_ROWS = 189_703
EXPECTED_ATHLETE_SCHOOL_ROWS = 80_077
EXPECTED_SCHOOLS = 361
EXPECTED_OFFICIAL_ROBUSTNESS_SCHOOLS = 353
EXPECTED_SENSITIVITY_VARIANTS = 7

VARIANCE_PRIOR_DF = 20.0
CI_Z = 1.96

SCHOOL_MIN_SAMPLE = 30
SEGMENT_MIN_SAMPLE = 20
TRANSFER_MIN_SAMPLE = 15
BREAKOUT_THRESHOLD = 5.0
RATE_PRIOR_STRENGTH = 20.0

ELITE_FRONTIER_MINIMUM = 70.0

BALANCE_CORE_GROUPS = (
    "sprints",
    "middle_distance",
    "distance",
    "hurdles",
    "jumps",
    "throws",
)
BALANCE_EXPECTED_CELLS = 12
BALANCE_MINIMUM_CELLS = 8
BALANCE_MINIMUM_CELLS_PER_GENDER = 3
BALANCE_VARIATION_PENALTY = 0.25
BALANCE_GENDER_GAP_PENALTY = 0.25
BALANCE_COVERAGE_PENALTY = 0.50

FORMULA_TOLERANCE = 1e-10


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


def failed_checks(path: Path) -> list[str]:
    return [
        row.get("check_name", "")
        for row in read_csv(path)
        if row.get("status") != "PASS"
    ]


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 5K — SUPPLEMENTAL DEVELOPMENT RANKINGS")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Output database: {OUTPUT_DB}")

    required_inputs = [
        TRAJECTORY_DB,
        PHASE_5E_CHECKS,
        CONTRIBUTION_DB,
        PHASE_5F_CHECKS,
        AUDIT_DB,
        PHASE_5H_CHECKS,
        PUBLICATION_DB,
        PHASE_5I_CHECKS,
        EVENT_DB,
        PHASE_5J_CHECKS,
    ]
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

    for phase_name, check_path in [
        ("phase_5e", PHASE_5E_CHECKS),
        ("phase_5f", PHASE_5F_CHECKS),
        ("phase_5h", PHASE_5H_CHECKS),
        ("phase_5i", PHASE_5I_CHECKS),
        ("phase_5j", PHASE_5J_CHECKS),
    ]:
        failures = failed_checks(check_path)
        add_check(
            checks,
            f"{phase_name}_gate_passed",
            not failures,
            failures,
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

        for alias, path in [
            ("trajectory_source", TRAJECTORY_DB),
            ("contribution_source", CONTRIBUTION_DB),
            ("audit_source", AUDIT_DB),
            ("publication_source", PUBLICATION_DB),
            ("event_source", EVENT_DB),
        ]:
            con.execute(
                f"""
                ATTACH '{sql_path(path)}'
                    AS {alias} (READ_ONLY)
                """
            )

        trajectory_metadata = dict(
            con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM trajectory_source.main.dataset_metadata
                """
            ).fetchall()
        )
        contribution_metadata = dict(
            con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM contribution_source.main.dataset_metadata
                """
            ).fetchall()
        )
        audit_metadata = dict(
            con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM audit_source.main.dataset_metadata
                """
            ).fetchall()
        )
        publication_metadata = dict(
            con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM publication_source.main.dataset_metadata
                """
            ).fetchall()
        )
        event_metadata = dict(
            con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM event_source.main.dataset_metadata
                """
            ).fetchall()
        )

        version_checks = [
            (
                "trajectory_version_matches",
                trajectory_metadata.get("dataset_version"),
                INPUT_TRAJECTORY_VERSION,
            ),
            (
                "contribution_version_matches",
                contribution_metadata.get("dataset_version"),
                INPUT_CONTRIBUTION_VERSION,
            ),
            (
                "audit_version_matches",
                audit_metadata.get("dataset_version"),
                INPUT_AUDIT_VERSION,
            ),
            (
                "publication_version_matches",
                publication_metadata.get("dataset_version"),
                INPUT_PUBLICATION_VERSION,
            ),
            (
                "event_version_matches",
                event_metadata.get("dataset_version"),
                INPUT_EVENT_VERSION,
            ),
        ]

        for name, observed, expected in version_checks:
            add_check(
                checks,
                name,
                observed == expected,
                observed,
                expected,
            )

        con.execute(
            """
            CREATE TABLE trajectory_snapshot AS
            SELECT *
            FROM
                trajectory_source.main.expected_improvement_scored_trajectories
            """
        )
        con.execute(
            """
            CREATE TABLE athlete_school_snapshot AS
            SELECT *
            FROM contribution_source.main.athlete_school_value_added
            """
        )
        con.execute(
            """
            CREATE TABLE school_metadata AS
            SELECT *
            FROM publication_source.main.ranking_school_metadata
            """
        )
        con.execute(
            """
            CREATE TABLE official_overall_snapshot AS
            SELECT *
            FROM audit_source.main.overall_ranking_snapshot
            """
        )
        con.execute(
            """
            CREATE TABLE approved_variant_ranks AS
            SELECT *
            FROM audit_source.main.official_population_variant_ranks
            """
        )
        con.execute(
            """
            CREATE TABLE event_group_ranking_snapshot AS
            SELECT *
            FROM event_source.main.event_and_group_rankings
            """
        )

        # ------------------------------------------------------------------
        # 1. Consistency ranking
        # ------------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE consistency_school_base AS
            SELECT
                resolved_school_id,
                COUNT(*) AS athlete_school_unit_count,
                MEDIAN(primary_athlete_value_added)
                    AS median_athlete_value_added,
                QUANTILE_CONT(primary_athlete_value_added, 0.25)
                    AS athlete_value_added_q25,
                AVG(primary_athlete_value_added)
                    AS mean_athlete_value_added,
                COUNT(*) FILTER (
                    WHERE primary_athlete_value_added > 0
                ) AS above_expected_athlete_count,
                COUNT(*) FILTER (
                    WHERE primary_athlete_value_added >= {BREAKOUT_THRESHOLD}
                ) AS breakout_athlete_count,
                STDDEV_SAMP(primary_athlete_value_added)
                    AS athlete_value_added_sd
            FROM athlete_school_snapshot
            GROUP BY resolved_school_id
            """
        )

        con.execute(
            f"""
            CREATE TABLE consistency_rate_prior AS
            SELECT
                AVG(
                    CAST(
                        primary_athlete_value_added > 0
                        AS DOUBLE
                    )
                ) AS global_positive_rate,
                {RATE_PRIOR_STRENGTH}
                    AS prior_strength
            FROM athlete_school_snapshot
            """
        )

        con.execute(
            f"""
            CREATE TABLE consistency_rankings AS
            WITH posterior AS (
                SELECT
                    b.*,
                    p.global_positive_rate,
                    p.prior_strength,
                    (
                        b.above_expected_athlete_count
                        + p.global_positive_rate * p.prior_strength
                    )
                    / (
                        b.athlete_school_unit_count
                        + p.prior_strength
                    ) AS stabilized_above_expected_share,
                    SQRT(
                        (
                            (
                                b.above_expected_athlete_count
                                + p.global_positive_rate
                                    * p.prior_strength
                            )
                            * (
                                b.athlete_school_unit_count
                                - b.above_expected_athlete_count
                                + (1.0 - p.global_positive_rate)
                                    * p.prior_strength
                            )
                        )
                        / (
                            POWER(
                                b.athlete_school_unit_count
                                + p.prior_strength,
                                2
                            )
                            * (
                                b.athlete_school_unit_count
                                + p.prior_strength + 1
                            )
                        )
                    ) AS stabilized_share_standard_error
                FROM consistency_school_base b
                CROSS JOIN consistency_rate_prior p
            ),
            eligible_percentiles AS (
                SELECT
                    resolved_school_id,
                    PERCENT_RANK() OVER (
                        ORDER BY median_athlete_value_added
                    ) AS median_percentile,
                    PERCENT_RANK() OVER (
                        ORDER BY stabilized_above_expected_share
                    ) AS positive_share_percentile
                FROM posterior
                WHERE athlete_school_unit_count
                    >= {SCHOOL_MIN_SAMPLE}
            ),
            indexed AS (
                SELECT
                    p.*,
                    e.median_percentile,
                    e.positive_share_percentile,
                    p.athlete_school_unit_count
                        >= {SCHOOL_MIN_SAMPLE}
                        AS official_rank_eligible,
                    CASE
                        WHEN e.resolved_school_id IS NOT NULL
                        THEN 100.0
                            * (
                                0.5 * e.median_percentile
                                + 0.5
                                    * e.positive_share_percentile
                            )
                        ELSE NULL
                    END AS consistency_index,
                    GREATEST(
                        0.0,
                        p.stabilized_above_expected_share
                        - {CI_Z}
                            * p.stabilized_share_standard_error
                    ) AS stabilized_share_ci95_lower,
                    LEAST(
                        1.0,
                        p.stabilized_above_expected_share
                        + {CI_Z}
                            * p.stabilized_share_standard_error
                    ) AS stabilized_share_ci95_upper
                FROM posterior p
                LEFT JOIN eligible_percentiles e
                  USING (resolved_school_id)
            ),
            official AS (
                SELECT
                    resolved_school_id,
                    RANK() OVER (
                        ORDER BY consistency_index DESC
                    ) AS official_consistency_rank,
                    COUNT(*) OVER () AS official_ranked_school_count
                FROM indexed
                WHERE official_rank_eligible
            )
            SELECT
                i.*,
                o.official_consistency_rank,
                o.official_ranked_school_count,
                m.school_name,
                m.state_code,
                m.conference_name,
                '{DATASET_VERSION}' AS dataset_version
            FROM indexed i
            JOIN school_metadata m
              USING (resolved_school_id)
            LEFT JOIN official o
              USING (resolved_school_id)
            """
        )

        # ------------------------------------------------------------------
        # 2-3. Elite/frontier and baseline-tier contribution units
        # ------------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE baseline_segment_trajectory_rows AS
            SELECT
                'elite_frontier' AS segment_type,
                'baseline_70_plus' AS segment_key,
                'Elite / Frontier (70+)' AS segment_label,
                {ELITE_FRONTIER_MINIMUM}
                    AS segment_lower_bound,
                NULL::DOUBLE AS segment_upper_bound,
                t.*
            FROM trajectory_snapshot t
            WHERE t.baseline_stable_level
                >= {ELITE_FRONTIER_MINIMUM}

            UNION ALL

            SELECT
                'baseline_tier',
                'developing',
                'Developing (<50)',
                NULL,
                50.0,
                t.*
            FROM trajectory_snapshot t
            WHERE t.baseline_stable_level < 50.0

            UNION ALL

            SELECT
                'baseline_tier',
                'competitive',
                'Competitive (50–<65)',
                50.0,
                65.0,
                t.*
            FROM trajectory_snapshot t
            WHERE t.baseline_stable_level >= 50.0
              AND t.baseline_stable_level < 65.0

            UNION ALL

            SELECT
                'baseline_tier',
                'advanced',
                'Advanced (65–<80)',
                65.0,
                80.0,
                t.*
            FROM trajectory_snapshot t
            WHERE t.baseline_stable_level >= 65.0
              AND t.baseline_stable_level < 80.0

            UNION ALL

            SELECT
                'baseline_tier',
                'elite',
                'Elite (80+)',
                80.0,
                NULL,
                t.*
            FROM trajectory_snapshot t
            WHERE t.baseline_stable_level >= 80.0
            """
        )

        con.execute(
            """
            CREATE TABLE athlete_segment_family_contributions AS
            SELECT
                segment_type,
                segment_key,
                ANY_VALUE(segment_label) AS segment_label,
                ANY_VALUE(segment_lower_bound)
                    AS segment_lower_bound,
                ANY_VALUE(segment_upper_bound)
                    AS segment_upper_bound,
                canonical_person_id,
                ANY_VALUE(athlete_id) AS athlete_id,
                ANY_VALUE(athlete_name) AS athlete_name,
                resolved_school_id,
                canonical_gender_code,
                event_family,
                COUNT(*) AS trajectory_count,
                AVG(baseline_stable_level)
                    AS mean_baseline_level,
                AVG(athlete_value_added)
                    AS family_mean_value_added,
                AVG(annualized_athlete_value_added)
                    AS family_mean_annualized_value_added,
                MIN(training_support_n)
                    AS minimum_training_support
            FROM baseline_segment_trajectory_rows
            GROUP BY
                segment_type,
                segment_key,
                canonical_person_id,
                resolved_school_id,
                canonical_gender_code,
                event_family
            """
        )

        con.execute(
            f"""
            CREATE TABLE athlete_segment_contributions AS
            SELECT
                'aseg_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        segment_type,
                        segment_key,
                        canonical_person_id,
                        resolved_school_id,
                        canonical_gender_code
                    )
                ) AS athlete_segment_contribution_id,
                segment_type,
                segment_key,
                ANY_VALUE(segment_label) AS segment_label,
                ANY_VALUE(segment_lower_bound)
                    AS segment_lower_bound,
                ANY_VALUE(segment_upper_bound)
                    AS segment_upper_bound,
                canonical_person_id,
                ANY_VALUE(athlete_id) AS athlete_id,
                ANY_VALUE(athlete_name) AS athlete_name,
                resolved_school_id,
                canonical_gender_code,
                COUNT(*) AS event_family_count,
                SUM(trajectory_count) AS trajectory_count,
                AVG(mean_baseline_level)
                    AS equal_family_mean_baseline_level,
                AVG(family_mean_value_added)
                    AS segment_athlete_value_added,
                AVG(family_mean_annualized_value_added)
                    AS segment_annualized_value_added,
                MIN(minimum_training_support)
                    AS minimum_training_support,
                '{DATASET_VERSION}' AS dataset_version
            FROM athlete_segment_family_contributions
            GROUP BY
                segment_type,
                segment_key,
                canonical_person_id,
                resolved_school_id,
                canonical_gender_code
            """
        )

        # ------------------------------------------------------------------
        # 6. Efficiency input and 8. inbound transfer registry
        # ------------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE person_school_timing AS
            SELECT
                canonical_person_id,
                resolved_school_id,
                MIN(baseline_season_year)
                    AS first_school_baseline_year,
                MAX(endpoint_season_year)
                    AS last_school_endpoint_year,
                COUNT(DISTINCT school_stint_id)
                    AS analytical_stint_count
            FROM trajectory_snapshot
            GROUP BY
                canonical_person_id,
                resolved_school_id
            """
        )

        con.execute(
            """
            CREATE TABLE person_career_timing AS
            SELECT
                canonical_person_id,
                MIN(first_school_baseline_year)
                    AS first_observed_school_year,
                COUNT(DISTINCT resolved_school_id)
                    AS observed_school_count
            FROM person_school_timing
            GROUP BY canonical_person_id
            """
        )

        con.execute(
            f"""
            CREATE TABLE transfer_destination_contributions AS
            SELECT
                a.*,
                t.first_school_baseline_year,
                t.last_school_endpoint_year,
                c.first_observed_school_year,
                c.observed_school_count,
                t.first_school_baseline_year
                    - c.first_observed_school_year
                    AS years_after_first_observed_school,
                '{DATASET_VERSION}' AS supplemental_dataset_version
            FROM athlete_school_snapshot a
            JOIN person_school_timing t
              USING (
                canonical_person_id,
                resolved_school_id
              )
            JOIN person_career_timing c
              USING (canonical_person_id)
            WHERE c.observed_school_count > 1
              AND t.first_school_baseline_year
                    > c.first_observed_school_year
            """
        )

        # ------------------------------------------------------------------
        # Unified empirical-Bayes mean ranking engine
        # ------------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE mean_ranking_input_units AS
            SELECT
                CASE
                    WHEN segment_type = 'elite_frontier'
                        THEN 'elite_development'
                    ELSE 'baseline_tier'
                END AS ranking_type,
                segment_key AS ranking_key,
                segment_label AS ranking_label,
                {SEGMENT_MIN_SAMPLE} AS minimum_sample,
                resolved_school_id,
                canonical_person_id,
                athlete_segment_contribution_id
                    AS contribution_id,
                segment_athlete_value_added AS score_value,
                minimum_training_support
            FROM athlete_segment_contributions

            UNION ALL

            SELECT
                'development_efficiency',
                'annualized_value_added',
                'Annualized Development Efficiency',
                {SCHOOL_MIN_SAMPLE},
                resolved_school_id,
                canonical_person_id,
                athlete_school_contribution_id,
                family_equal_mean_annualized_value_added,
                minimum_training_support
            FROM athlete_school_snapshot
            WHERE family_equal_mean_annualized_value_added
                IS NOT NULL

            UNION ALL

            SELECT
                'transfer_development',
                'inbound_transfer',
                'Inbound Transfer Development',
                {TRANSFER_MIN_SAMPLE},
                resolved_school_id,
                canonical_person_id,
                athlete_school_contribution_id,
                primary_athlete_value_added,
                minimum_training_support
            FROM transfer_destination_contributions
            """
        )

        con.execute(
            """
            CREATE TABLE mean_ranking_school_base AS
            SELECT
                ranking_type,
                ranking_key,
                ANY_VALUE(ranking_label) AS ranking_label,
                ANY_VALUE(minimum_sample) AS minimum_sample,
                resolved_school_id,
                COUNT(*) AS athlete_unit_count,
                COUNT(DISTINCT canonical_person_id)
                    AS distinct_athlete_count,
                AVG(score_value) AS raw_school_score,
                MEDIAN(score_value) AS median_athlete_score,
                VAR_SAMP(score_value) AS raw_within_school_variance,
                STDDEV_SAMP(score_value) AS raw_within_school_sd,
                AVG(CAST(score_value > 0 AS DOUBLE))
                    AS above_expected_athlete_share,
                MIN(minimum_training_support)
                    AS minimum_training_support
            FROM mean_ranking_input_units
            GROUP BY
                ranking_type,
                ranking_key,
                resolved_school_id
            """
        )

        con.execute(
            """
            CREATE TABLE mean_ranking_global_prior AS
            WITH globals AS (
                SELECT
                    ranking_type,
                    ranking_key,
                    AVG(score_value) AS global_athlete_mean,
                    VAR_SAMP(score_value) AS global_athlete_variance,
                    COUNT(*) AS total_athlete_units
                FROM mean_ranking_input_units
                GROUP BY ranking_type, ranking_key
            ),
            pooled AS (
                SELECT
                    ranking_type,
                    ranking_key,
                    SUM(
                        (athlete_unit_count - 1)
                        * COALESCE(raw_within_school_variance, 0)
                    )
                    / NULLIF(
                        SUM(athlete_unit_count - 1),
                        0
                    ) AS pooled_within_school_variance
                FROM mean_ranking_school_base
                GROUP BY ranking_type, ranking_key
            )
            SELECT *
            FROM globals
            JOIN pooled
              USING (ranking_type, ranking_key)
            """
        )

        con.execute(
            f"""
            CREATE TABLE mean_ranking_school_stabilized AS
            SELECT
                b.*,
                p.global_athlete_mean,
                p.global_athlete_variance,
                COALESCE(
                    p.pooled_within_school_variance,
                    p.global_athlete_variance,
                    0.0
                ) AS pooled_within_school_variance,
                (
                    (
                        (b.athlete_unit_count - 1)
                        * COALESCE(
                            b.raw_within_school_variance,
                            p.pooled_within_school_variance,
                            p.global_athlete_variance,
                            0.0
                        )
                    )
                    + {VARIANCE_PRIOR_DF}
                        * COALESCE(
                            p.pooled_within_school_variance,
                            p.global_athlete_variance,
                            0.0
                        )
                )
                / (
                    b.athlete_unit_count - 1
                    + {VARIANCE_PRIOR_DF}
                ) AS stabilized_within_school_variance,
                (
                    (
                        (
                            (b.athlete_unit_count - 1)
                            * COALESCE(
                                b.raw_within_school_variance,
                                p.pooled_within_school_variance,
                                p.global_athlete_variance,
                                0.0
                            )
                        )
                        + {VARIANCE_PRIOR_DF}
                            * COALESCE(
                                p.pooled_within_school_variance,
                                p.global_athlete_variance,
                                0.0
                            )
                    )
                    / (
                        b.athlete_unit_count - 1
                        + {VARIANCE_PRIOR_DF}
                    )
                )
                / b.athlete_unit_count
                    AS stabilized_sampling_variance
            FROM mean_ranking_school_base b
            JOIN mean_ranking_global_prior p
              USING (ranking_type, ranking_key)
            """
        )

        con.execute(
            """
            CREATE TABLE mean_ranking_between_school_variance AS
            SELECT
                ranking_type,
                ranking_key,
                GREATEST(
                    0.0,
                    VAR_SAMP(raw_school_score)
                    - AVG(stabilized_sampling_variance)
                ) AS between_school_variance,
                VAR_SAMP(raw_school_score)
                    AS observed_school_mean_variance,
                AVG(stabilized_sampling_variance)
                    AS mean_sampling_variance,
                COUNT(*) AS represented_school_count
            FROM mean_ranking_school_stabilized
            GROUP BY ranking_type, ranking_key
            """
        )

        con.execute(
            f"""
            CREATE TABLE mean_development_rankings AS
            WITH posterior AS (
                SELECT
                    s.*,
                    t.between_school_variance,
                    t.represented_school_count,
                    CASE
                        WHEN t.between_school_variance <= 0
                            THEN 0.0
                        ELSE
                            t.between_school_variance
                            / (
                                t.between_school_variance
                                + s.stabilized_sampling_variance
                            )
                    END AS shrinkage_weight,
                    s.global_athlete_mean
                        + (
                            CASE
                                WHEN t.between_school_variance <= 0
                                    THEN 0.0
                                ELSE
                                    t.between_school_variance
                                    / (
                                        t.between_school_variance
                                        + s.stabilized_sampling_variance
                                    )
                            END
                        )
                        * (
                            s.raw_school_score
                            - s.global_athlete_mean
                        ) AS posterior_school_score,
                    CASE
                        WHEN t.between_school_variance <= 0
                            THEN SQRT(s.stabilized_sampling_variance)
                        ELSE SQRT(
                            t.between_school_variance
                            * s.stabilized_sampling_variance
                            / (
                                t.between_school_variance
                                + s.stabilized_sampling_variance
                            )
                        )
                    END AS posterior_standard_error,
                    s.athlete_unit_count >= s.minimum_sample
                        AS official_rank_eligible
                FROM mean_ranking_school_stabilized s
                JOIN mean_ranking_between_school_variance t
                  USING (ranking_type, ranking_key)
            ),
            intervals AS (
                SELECT
                    *,
                    posterior_school_score
                        - {CI_Z} * posterior_standard_error
                        AS posterior_ci95_lower,
                    posterior_school_score
                        + {CI_Z} * posterior_standard_error
                        AS posterior_ci95_upper,
                    RANK() OVER (
                        PARTITION BY ranking_type, ranking_key
                        ORDER BY posterior_school_score DESC
                    ) AS all_school_rank
                FROM posterior
            ),
            official AS (
                SELECT
                    ranking_type,
                    ranking_key,
                    resolved_school_id,
                    RANK() OVER (
                        PARTITION BY ranking_type, ranking_key
                        ORDER BY posterior_school_score DESC
                    ) AS official_rank,
                    COUNT(*) OVER (
                        PARTITION BY ranking_type, ranking_key
                    ) AS official_ranked_school_count
                FROM intervals
                WHERE official_rank_eligible
            )
            SELECT
                i.*,
                o.official_rank,
                o.official_ranked_school_count,
                m.school_name,
                m.state_code,
                m.conference_name,
                CASE
                    WHEN i.posterior_ci95_lower > 0
                        THEN 'credible_above_expected'
                    WHEN i.posterior_ci95_upper < 0
                        THEN 'credible_below_expected'
                    ELSE 'not_distinguishable_from_expected'
                END AS evidence_category,
                '{DATASET_VERSION}' AS dataset_version
            FROM intervals i
            JOIN school_metadata m
              USING (resolved_school_id)
            LEFT JOIN official o
              USING (
                ranking_type,
                ranking_key,
                resolved_school_id
              )
            """
        )

        # ------------------------------------------------------------------
        # 4. Breakout rate
        # ------------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE breakout_school_base AS
            SELECT
                resolved_school_id,
                COUNT(*) AS athlete_school_unit_count,
                COUNT(*) FILTER (
                    WHERE primary_athlete_value_added
                        >= {BREAKOUT_THRESHOLD}
                ) AS breakout_athlete_count,
                AVG(
                    CAST(
                        primary_athlete_value_added
                            >= {BREAKOUT_THRESHOLD}
                        AS DOUBLE
                    )
                ) AS raw_breakout_rate,
                AVG(primary_athlete_value_added)
                    FILTER (
                        WHERE primary_athlete_value_added
                            >= {BREAKOUT_THRESHOLD}
                    ) AS mean_breakout_value_added
            FROM athlete_school_snapshot
            GROUP BY resolved_school_id
            """
        )

        con.execute(
            f"""
            CREATE TABLE breakout_rate_prior AS
            SELECT
                AVG(
                    CAST(
                        primary_athlete_value_added
                            >= {BREAKOUT_THRESHOLD}
                        AS DOUBLE
                    )
                ) AS global_breakout_rate,
                {RATE_PRIOR_STRENGTH} AS prior_strength
            FROM athlete_school_snapshot
            """
        )

        con.execute(
            f"""
            CREATE TABLE breakout_rate_rankings AS
            WITH posterior AS (
                SELECT
                    b.*,
                    p.global_breakout_rate,
                    p.prior_strength,
                    (
                        b.breakout_athlete_count
                        + p.global_breakout_rate
                            * p.prior_strength
                    )
                    / (
                        b.athlete_school_unit_count
                        + p.prior_strength
                    ) AS posterior_breakout_rate,
                    SQRT(
                        (
                            (
                                b.breakout_athlete_count
                                + p.global_breakout_rate
                                    * p.prior_strength
                            )
                            * (
                                b.athlete_school_unit_count
                                - b.breakout_athlete_count
                                + (1.0 - p.global_breakout_rate)
                                    * p.prior_strength
                            )
                        )
                        / (
                            POWER(
                                b.athlete_school_unit_count
                                + p.prior_strength,
                                2
                            )
                            * (
                                b.athlete_school_unit_count
                                + p.prior_strength + 1
                            )
                        )
                    ) AS posterior_standard_error,
                    b.athlete_school_unit_count
                        >= {SCHOOL_MIN_SAMPLE}
                        AS official_rank_eligible
                FROM breakout_school_base b
                CROSS JOIN breakout_rate_prior p
            ),
            intervals AS (
                SELECT
                    *,
                    GREATEST(
                        0.0,
                        posterior_breakout_rate
                        - {CI_Z} * posterior_standard_error
                    ) AS posterior_ci95_lower,
                    LEAST(
                        1.0,
                        posterior_breakout_rate
                        + {CI_Z} * posterior_standard_error
                    ) AS posterior_ci95_upper
                FROM posterior
            ),
            official AS (
                SELECT
                    resolved_school_id,
                    RANK() OVER (
                        ORDER BY posterior_breakout_rate DESC
                    ) AS official_breakout_rank,
                    COUNT(*) OVER () AS official_ranked_school_count
                FROM intervals
                WHERE official_rank_eligible
            )
            SELECT
                i.*,
                o.official_breakout_rank,
                o.official_ranked_school_count,
                m.school_name,
                m.state_code,
                m.conference_name,
                {BREAKOUT_THRESHOLD} AS breakout_threshold,
                '{DATASET_VERSION}' AS dataset_version
            FROM intervals i
            JOIN school_metadata m
              USING (resolved_school_id)
            LEFT JOIN official o
              USING (resolved_school_id)
            """
        )

        # ------------------------------------------------------------------
        # 5. Balanced program ranking
        # ------------------------------------------------------------------
        core_group_sql = ", ".join(
            f"'{value}'" for value in BALANCE_CORE_GROUPS
        )

        con.execute(
            f"""
            CREATE TABLE balance_component_scores AS
            SELECT
                resolved_school_id,
                gender_scope,
                ranking_key AS event_group,
                ranking_label AS event_group_label,
                athlete_unit_count,
                posterior_school_score,
                posterior_standard_error,
                official_rank_eligible
            FROM event_group_ranking_snapshot
            WHERE ranking_scope = 'gender_group'
              AND ranking_key IN ({core_group_sql})
              AND official_rank_eligible
            """
        )

        con.execute(
            f"""
            CREATE TABLE balanced_program_rankings AS
            WITH aggregated AS (
                SELECT
                    resolved_school_id,
                    COUNT(*) AS eligible_gender_group_cells,
                    COUNT(*) FILTER (
                        WHERE gender_scope = 'm'
                    ) AS eligible_mens_cells,
                    COUNT(*) FILTER (
                        WHERE gender_scope = 'f'
                    ) AS eligible_womens_cells,
                    COUNT(DISTINCT event_group)
                        AS represented_event_groups,
                    AVG(posterior_school_score)
                        AS mean_group_posterior_score,
                    STDDEV_SAMP(posterior_school_score)
                        AS group_score_sd,
                    MIN(posterior_school_score)
                        AS minimum_group_posterior_score,
                    MAX(posterior_school_score)
                        AS maximum_group_posterior_score,
                    AVG(posterior_school_score)
                        FILTER (
                            WHERE gender_scope = 'm'
                        ) AS mens_mean_group_score,
                    AVG(posterior_school_score)
                        FILTER (
                            WHERE gender_scope = 'f'
                        ) AS womens_mean_group_score,
                    SUM(athlete_unit_count)
                        AS summed_group_athlete_units
                FROM balance_component_scores
                GROUP BY resolved_school_id
            ),
            scored AS (
                SELECT
                    *,
                    eligible_gender_group_cells::DOUBLE
                        / {BALANCE_EXPECTED_CELLS}
                        AS coverage_share,
                    ABS(
                        mens_mean_group_score
                        - womens_mean_group_score
                    ) AS gender_score_gap,
                    mean_group_posterior_score
                        - {BALANCE_VARIATION_PENALTY}
                            * COALESCE(group_score_sd, 0)
                        - {BALANCE_GENDER_GAP_PENALTY}
                            * ABS(
                                mens_mean_group_score
                                - womens_mean_group_score
                            )
                        - {BALANCE_COVERAGE_PENALTY}
                            * (
                                1.0
                                - eligible_gender_group_cells::DOUBLE
                                    / {BALANCE_EXPECTED_CELLS}
                            ) AS balanced_program_index,
                    (
                        eligible_gender_group_cells
                            >= {BALANCE_MINIMUM_CELLS}
                        AND eligible_mens_cells
                            >= {BALANCE_MINIMUM_CELLS_PER_GENDER}
                        AND eligible_womens_cells
                            >= {BALANCE_MINIMUM_CELLS_PER_GENDER}
                    ) AS official_rank_eligible
                FROM aggregated
            ),
            official AS (
                SELECT
                    resolved_school_id,
                    RANK() OVER (
                        ORDER BY balanced_program_index DESC
                    ) AS official_balanced_program_rank,
                    COUNT(*) OVER () AS official_ranked_school_count
                FROM scored
                WHERE official_rank_eligible
            )
            SELECT
                s.*,
                o.official_balanced_program_rank,
                o.official_ranked_school_count,
                m.school_name,
                m.state_code,
                m.conference_name,
                '{DATASET_VERSION}' AS dataset_version
            FROM scored s
            JOIN school_metadata m
              USING (resolved_school_id)
            LEFT JOIN official o
              USING (resolved_school_id)
            """
        )

        # ------------------------------------------------------------------
        # 7. Robustness ranking
        # ------------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE ranking_robustness_rankings AS
            WITH aggregated AS (
                SELECT
                    resolved_school_id,
                    COUNT(DISTINCT variant_name)
                        AS approved_variant_count,
                    MIN(official_population_variant_rank)
                        AS best_approved_rank,
                    MAX(official_population_variant_rank)
                        AS worst_approved_rank,
                    AVG(official_population_variant_rank)
                        AS mean_approved_rank,
                    MEDIAN(official_population_variant_rank)
                        AS median_approved_rank,
                    MAX(official_population_variant_rank)
                        - MIN(official_population_variant_rank)
                        AS approved_rank_spread,
                    COUNT(*) FILTER (
                        WHERE official_population_variant_rank <= 10
                    ) AS top10_variant_count,
                    COUNT(*) FILTER (
                        WHERE official_population_variant_rank <= 25
                    ) AS top25_variant_count,
                    AVG(posterior_school_score)
                        AS mean_variant_posterior_score,
                    MIN(posterior_school_score)
                        AS minimum_variant_posterior_score,
                    MAX(posterior_school_score)
                        AS maximum_variant_posterior_score
                FROM approved_variant_ranks
                GROUP BY resolved_school_id
            ),
            ranked AS (
                SELECT
                    *,
                    RANK() OVER (
                        ORDER BY
                            worst_approved_rank ASC,
                            mean_approved_rank ASC,
                            approved_rank_spread ASC
                    ) AS robustness_rank,
                    100.0
                        * (
                            1.0
                            - (
                                worst_approved_rank - 1.0
                            )
                            / (
                                {EXPECTED_OFFICIAL_ROBUSTNESS_SCHOOLS}
                                - 1.0
                            )
                        ) AS worst_case_rank_percentile
                FROM aggregated
            )
            SELECT
                r.*,
                m.school_name,
                m.state_code,
                m.conference_name,
                o.official_overall_rank,
                o.posterior_school_score
                    AS primary_posterior_school_score,
                o.athlete_school_unit_count,
                '{DATASET_VERSION}' AS dataset_version
            FROM ranked r
            JOIN school_metadata m
              USING (resolved_school_id)
            JOIN official_overall_snapshot o
              USING (resolved_school_id)
            WHERE o.official_rank_eligible
            """
        )

        # ------------------------------------------------------------------
        # Transfer comparison table
        # ------------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE transfer_school_comparison AS
            WITH transfer_stats AS (
                SELECT
                    resolved_school_id,
                    COUNT(*) AS inbound_transfer_athlete_count,
                    AVG(primary_athlete_value_added)
                        AS inbound_transfer_mean_value_added,
                    MEDIAN(primary_athlete_value_added)
                        AS inbound_transfer_median_value_added,
                    AVG(
                        CAST(
                            primary_athlete_value_added > 0
                            AS DOUBLE
                        )
                    ) AS inbound_transfer_above_expected_share
                FROM transfer_destination_contributions
                GROUP BY resolved_school_id
            ),
            nontransfer_stats AS (
                SELECT
                    a.resolved_school_id,
                    COUNT(*) AS nontransfer_athlete_count,
                    AVG(a.primary_athlete_value_added)
                        AS nontransfer_mean_value_added
                FROM athlete_school_snapshot a
                LEFT JOIN transfer_destination_contributions t
                  ON t.athlete_school_contribution_id
                     = a.athlete_school_contribution_id
                WHERE t.athlete_school_contribution_id IS NULL
                GROUP BY a.resolved_school_id
            )
            SELECT
                t.*,
                n.nontransfer_athlete_count,
                n.nontransfer_mean_value_added,
                t.inbound_transfer_mean_value_added
                    - n.nontransfer_mean_value_added
                    AS transfer_minus_nontransfer_gap,
                m.school_name,
                m.state_code,
                m.conference_name
            FROM transfer_stats t
            LEFT JOIN nontransfer_stats n
              USING (resolved_school_id)
            JOIN school_metadata m
              USING (resolved_school_id)
            """
        )

        # ------------------------------------------------------------------
        # Validation
        # ------------------------------------------------------------------
        counts = fetch_dicts(
            con,
            """
            SELECT
                (SELECT COUNT(*) FROM trajectory_snapshot)
                    AS trajectory_rows,
                (SELECT COUNT(*) FROM athlete_school_snapshot)
                    AS athlete_school_rows,
                (SELECT COUNT(*) FROM school_metadata)
                    AS school_metadata_rows,
                (SELECT COUNT(*) FROM consistency_rankings)
                    AS consistency_school_rows,
                (SELECT COUNT(*) FROM breakout_rate_rankings)
                    AS breakout_school_rows,
                (SELECT COUNT(*) FROM athlete_segment_contributions)
                    AS athlete_segment_rows,
                (SELECT COUNT(DISTINCT ranking_key)
                 FROM mean_development_rankings
                 WHERE ranking_type = 'baseline_tier')
                    AS baseline_tier_count,
                (SELECT COUNT(*)
                 FROM mean_development_rankings
                 WHERE ranking_type = 'elite_development')
                    AS elite_school_rows,
                (SELECT COUNT(*)
                 FROM mean_development_rankings
                 WHERE ranking_type = 'development_efficiency')
                    AS efficiency_school_rows,
                (SELECT COUNT(*)
                 FROM transfer_destination_contributions)
                    AS transfer_destination_rows,
                (SELECT COUNT(*)
                 FROM mean_development_rankings
                 WHERE ranking_type = 'transfer_development')
                    AS transfer_school_rows,
                (SELECT COUNT(*) FROM balanced_program_rankings)
                    AS balance_school_rows,
                (SELECT COUNT(*)
                 FROM balanced_program_rankings
                 WHERE official_rank_eligible)
                    AS official_balance_school_rows,
                (SELECT COUNT(*) FROM ranking_robustness_rankings)
                    AS robustness_school_rows,
                (SELECT COUNT(DISTINCT variant_name)
                 FROM approved_variant_ranks)
                    AS approved_variant_count
            """
        )[0]

        quality = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM school_metadata
                 WHERE metadata_match_status <> 'matched')
                    AS unmatched_school_metadata_rows,
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        athlete_segment_contribution_id,
                        COUNT(*) AS row_count
                    FROM athlete_segment_contributions
                    GROUP BY athlete_segment_contribution_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_segment_ids,
                (SELECT COUNT(*)
                 FROM mean_development_rankings
                 WHERE posterior_school_score IS NULL
                    OR posterior_standard_error IS NULL
                    OR posterior_ci95_lower > posterior_ci95_upper
                    OR shrinkage_weight < 0
                    OR shrinkage_weight > 1)
                    AS invalid_mean_ranking_rows,
                (SELECT COUNT(*)
                 FROM mean_development_rankings
                 WHERE posterior_school_score
                    < LEAST(raw_school_score, global_athlete_mean)
                        - {FORMULA_TOLERANCE}
                    OR posterior_school_score
                    > GREATEST(raw_school_score, global_athlete_mean)
                        + {FORMULA_TOLERANCE})
                    AS nonconvex_mean_ranking_rows,
                (SELECT COUNT(*)
                 FROM consistency_rankings
                 WHERE consistency_index < 0
                    OR consistency_index > 100
                    OR stabilized_above_expected_share < 0
                    OR stabilized_above_expected_share > 1)
                    AS invalid_consistency_rows,
                (SELECT COUNT(*)
                 FROM breakout_rate_rankings
                 WHERE posterior_breakout_rate < 0
                    OR posterior_breakout_rate > 1
                    OR posterior_ci95_lower > posterior_ci95_upper)
                    AS invalid_breakout_rows,
                (SELECT COUNT(*)
                 FROM ranking_robustness_rankings
                 WHERE approved_variant_count
                    <> {EXPECTED_SENSITIVITY_VARIANTS})
                    AS incomplete_robustness_rows,
                (SELECT COUNT(*)
                 FROM balanced_program_rankings
                 WHERE official_rank_eligible
                   AND (
                        eligible_gender_group_cells
                            < {BALANCE_MINIMUM_CELLS}
                        OR eligible_mens_cells
                            < {BALANCE_MINIMUM_CELLS_PER_GENDER}
                        OR eligible_womens_cells
                            < {BALANCE_MINIMUM_CELLS_PER_GENDER}
                   ))
                    AS balance_eligibility_mismatch_rows
            """
        )[0]

        add_check(
            checks,
            "trajectory_row_count",
            counts["trajectory_rows"] == EXPECTED_TRAJECTORY_ROWS,
            counts["trajectory_rows"],
            EXPECTED_TRAJECTORY_ROWS,
        )
        add_check(
            checks,
            "athlete_school_row_count",
            counts["athlete_school_rows"]
            == EXPECTED_ATHLETE_SCHOOL_ROWS,
            counts["athlete_school_rows"],
            EXPECTED_ATHLETE_SCHOOL_ROWS,
        )
        add_check(
            checks,
            "school_metadata_row_count",
            counts["school_metadata_rows"] == EXPECTED_SCHOOLS,
            counts["school_metadata_rows"],
            EXPECTED_SCHOOLS,
        )
        add_check(
            checks,
            "all_school_metadata_matched",
            quality["unmatched_school_metadata_rows"] == 0,
            quality["unmatched_school_metadata_rows"],
            0,
        )
        add_check(
            checks,
            "consistency_covers_all_schools",
            counts["consistency_school_rows"] == EXPECTED_SCHOOLS,
            counts["consistency_school_rows"],
            EXPECTED_SCHOOLS,
        )
        add_check(
            checks,
            "breakout_covers_all_schools",
            counts["breakout_school_rows"] == EXPECTED_SCHOOLS,
            counts["breakout_school_rows"],
            EXPECTED_SCHOOLS,
        )
        add_check(
            checks,
            "all_four_baseline_tiers_exist",
            counts["baseline_tier_count"] == 4,
            counts["baseline_tier_count"],
            4,
        )
        add_check(
            checks,
            "elite_ranking_exists",
            counts["elite_school_rows"] > 0,
            counts["elite_school_rows"],
            "greater than 0",
        )
        add_check(
            checks,
            "efficiency_ranking_exists",
            counts["efficiency_school_rows"] > 0,
            counts["efficiency_school_rows"],
            "greater than 0",
        )
        add_check(
            checks,
            "transfer_population_exists",
            counts["transfer_destination_rows"] > 0
            and counts["transfer_school_rows"] > 0,
            {
                "destination_rows":
                    counts["transfer_destination_rows"],
                "school_rows": counts["transfer_school_rows"],
            },
            "both greater than 0",
        )
        add_check(
            checks,
            "balanced_program_population_exists",
            counts["balance_school_rows"] > 0
            and counts["official_balance_school_rows"] > 0,
            {
                "represented": counts["balance_school_rows"],
                "official": counts["official_balance_school_rows"],
            },
            "both greater than 0",
        )
        add_check(
            checks,
            "robustness_school_count",
            counts["robustness_school_rows"]
            == EXPECTED_OFFICIAL_ROBUSTNESS_SCHOOLS,
            counts["robustness_school_rows"],
            EXPECTED_OFFICIAL_ROBUSTNESS_SCHOOLS,
        )
        add_check(
            checks,
            "approved_variant_count",
            counts["approved_variant_count"]
            == EXPECTED_SENSITIVITY_VARIANTS,
            counts["approved_variant_count"],
            EXPECTED_SENSITIVITY_VARIANTS,
        )
        add_check(
            checks,
            "segment_contribution_ids_unique",
            quality["duplicate_segment_ids"] == 0,
            quality["duplicate_segment_ids"],
            0,
        )
        add_check(
            checks,
            "mean_rankings_valid",
            quality["invalid_mean_ranking_rows"] == 0,
            quality["invalid_mean_ranking_rows"],
            0,
        )
        add_check(
            checks,
            "mean_posterior_scores_are_convex",
            quality["nonconvex_mean_ranking_rows"] == 0,
            quality["nonconvex_mean_ranking_rows"],
            0,
        )
        add_check(
            checks,
            "consistency_rows_valid",
            quality["invalid_consistency_rows"] == 0,
            quality["invalid_consistency_rows"],
            0,
        )
        add_check(
            checks,
            "breakout_rows_valid",
            quality["invalid_breakout_rows"] == 0,
            quality["invalid_breakout_rows"],
            0,
        )
        add_check(
            checks,
            "robustness_variants_complete",
            quality["incomplete_robustness_rows"] == 0,
            quality["incomplete_robustness_rows"],
            0,
        )
        add_check(
            checks,
            "balance_eligibility_reconciles",
            quality["balance_eligibility_mismatch_rows"] == 0,
            quality["balance_eligibility_mismatch_rows"],
            0,
        )

        # ------------------------------------------------------------------
        # Exports
        # ------------------------------------------------------------------
        export_query(
            con,
            """
            SELECT *
            FROM consistency_rankings
            ORDER BY
                official_rank_eligible DESC,
                official_consistency_rank NULLS LAST,
                consistency_index DESC,
                school_name
            """,
            OUTPUT_DIR / "development_consistency_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM mean_development_rankings
            WHERE ranking_type = 'elite_development'
            ORDER BY
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "elite_development_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM mean_development_rankings
            WHERE ranking_type = 'baseline_tier'
            ORDER BY
                ranking_key,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "baseline_tier_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM breakout_rate_rankings
            ORDER BY
                official_rank_eligible DESC,
                official_breakout_rank NULLS LAST,
                posterior_breakout_rate DESC,
                school_name
            """,
            OUTPUT_DIR / "breakout_rate_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM balanced_program_rankings
            ORDER BY
                official_rank_eligible DESC,
                official_balanced_program_rank NULLS LAST,
                balanced_program_index DESC,
                school_name
            """,
            OUTPUT_DIR / "balanced_program_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM mean_development_rankings
            WHERE ranking_type = 'development_efficiency'
            ORDER BY
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "development_efficiency_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM ranking_robustness_rankings
            ORDER BY robustness_rank, school_name
            """,
            OUTPUT_DIR / "ranking_robustness_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM mean_development_rankings
            WHERE ranking_type = 'transfer_development'
            ORDER BY
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "transfer_development_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM transfer_school_comparison
            ORDER BY
                inbound_transfer_athlete_count DESC,
                school_name
            """,
            OUTPUT_DIR / "transfer_school_comparison.csv",
        )

        export_query(
            con,
            """
            SELECT
                ranking_type,
                ranking_key,
                ANY_VALUE(ranking_label) AS ranking_label,
                ANY_VALUE(minimum_sample) AS minimum_sample,
                COUNT(*) AS represented_school_count,
                COUNT(*) FILTER (
                    WHERE official_rank_eligible
                ) AS official_school_count,
                SUM(athlete_unit_count) AS athlete_unit_count,
                MIN(athlete_unit_count) AS minimum_school_sample,
                MAX(athlete_unit_count) AS maximum_school_sample,
                AVG(posterior_school_score)
                    AS mean_posterior_school_score
            FROM mean_development_rankings
            GROUP BY ranking_type, ranking_key
            ORDER BY ranking_type, ranking_key
            """,
            OUTPUT_DIR / "supplemental_ranking_scope_summary.csv",
        )

        leader_rows = fetch_dicts(
            con,
            """
            SELECT
                'consistency' AS ranking_product,
                school_name,
                official_consistency_rank AS rank,
                consistency_index AS score,
                athlete_school_unit_count AS sample_size
            FROM consistency_rankings
            WHERE official_consistency_rank = 1

            UNION ALL

            SELECT
                ranking_type || ':' || ranking_key,
                school_name,
                official_rank,
                posterior_school_score,
                athlete_unit_count
            FROM mean_development_rankings
            WHERE official_rank = 1

            UNION ALL

            SELECT
                'breakout_rate',
                school_name,
                official_breakout_rank,
                posterior_breakout_rate,
                athlete_school_unit_count
            FROM breakout_rate_rankings
            WHERE official_breakout_rank = 1

            UNION ALL

            SELECT
                'balanced_program',
                school_name,
                official_balanced_program_rank,
                balanced_program_index,
                summed_group_athlete_units
            FROM balanced_program_rankings
            WHERE official_balanced_program_rank = 1

            UNION ALL

            SELECT
                'ranking_robustness',
                school_name,
                robustness_rank,
                worst_case_rank_percentile,
                athlete_school_unit_count
            FROM ranking_robustness_rankings
            WHERE robustness_rank = 1
            ORDER BY ranking_product
            """
        )
        write_csv(
            OUTPUT_DIR / "supplemental_ranking_leaders.csv",
            leader_rows,
            list(leader_rows[0].keys()) if leader_rows else [],
        )

        methodology_rows = [
            {
                "ranking_product": "Development Consistency",
                "primary_metric":
                    "50% median percentile + 50% stabilized positive-share percentile",
                "minimum_sample": SCHOOL_MIN_SAMPLE,
                "interpretation":
                    "Rewards broad, repeatable development rather than only a few extreme athletes.",
            },
            {
                "ranking_product": "Elite / Frontier Development",
                "primary_metric":
                    f"posterior mean value added for baseline >= {ELITE_FRONTIER_MINIMUM:g}",
                "minimum_sample": SEGMENT_MIN_SAMPLE,
                "interpretation":
                    "Measures improvement among athletes already near the performance frontier.",
            },
            {
                "ranking_product": "Baseline Tiers",
                "primary_metric":
                    "posterior mean value added within four baseline bands",
                "minimum_sample": SEGMENT_MIN_SAMPLE,
                "interpretation":
                    "Shows which schools best develop athletes from different starting levels.",
            },
            {
                "ranking_product": "Breakout Rate",
                "primary_metric":
                    f"beta-binomial stabilized share with value added >= {BREAKOUT_THRESHOLD:g}",
                "minimum_sample": SCHOOL_MIN_SAMPLE,
                "interpretation":
                    "Measures the probability of producing a materially above-expected athlete.",
            },
            {
                "ranking_product": "Balanced Program",
                "primary_metric":
                    "mean group score minus variation, gender-gap, and coverage penalties",
                "minimum_sample": BALANCE_MINIMUM_CELLS,
                "interpretation":
                    "Rewards strength across both genders and six core event groups.",
            },
            {
                "ranking_product": "Development Efficiency",
                "primary_metric":
                    "posterior mean annualized athlete value added",
                "minimum_sample": SCHOOL_MIN_SAMPLE,
                "interpretation":
                    "Measures how quickly athletes improve per elapsed season.",
            },
            {
                "ranking_product": "Ranking Robustness",
                "primary_metric":
                    "worst approved sensitivity rank, then average rank",
                "minimum_sample": EXPECTED_SENSITIVITY_VARIANTS,
                "interpretation":
                    "Rewards conclusions that survive every approved ranking variant.",
            },
            {
                "ranking_product": "Inbound Transfer Development",
                "primary_metric":
                    "posterior mean value added at observed destination schools",
                "minimum_sample": TRANSFER_MIN_SAMPLE,
                "interpretation":
                    "Measures development after an athlete moves beyond the first observed school.",
            },
        ]
        write_csv(
            OUTPUT_DIR / "supplemental_ranking_methodology.csv",
            methodology_rows,
            [
                "ranking_product",
                "primary_metric",
                "minimum_sample",
                "interpretation",
            ],
        )

        summary_rows = [
            {
                "metric": "trajectory_rows",
                "value": counts["trajectory_rows"],
            },
            {
                "metric": "athlete_school_rows",
                "value": counts["athlete_school_rows"],
            },
            {
                "metric": "athlete_segment_rows",
                "value": counts["athlete_segment_rows"],
            },
            {
                "metric": "baseline_tiers",
                "value": counts["baseline_tier_count"],
            },
            {
                "metric": "transfer_destination_rows",
                "value": counts["transfer_destination_rows"],
            },
            {
                "metric": "official_balanced_programs",
                "value": counts["official_balance_school_rows"],
            },
            {
                "metric": "robustness_schools",
                "value": counts["robustness_school_rows"],
            },
            {
                "metric": "approved_sensitivity_variants",
                "value": counts["approved_variant_count"],
            },
        ]
        write_csv(
            OUTPUT_DIR / "phase_5k_summary.csv",
            summary_rows,
            ["metric", "value"],
        )

        con.execute(
            f"""
            CREATE TABLE dataset_metadata AS
            SELECT
                'dataset_version' AS metadata_key,
                '{DATASET_VERSION}' AS metadata_value
            UNION ALL
            SELECT
                'policy_version',
                '{POLICY_VERSION}'
            UNION ALL
            SELECT
                'ranking_product_count',
                '8'
            UNION ALL
            SELECT
                'breakout_threshold',
                '{BREAKOUT_THRESHOLD}'
            UNION ALL
            SELECT
                'elite_frontier_threshold',
                '{ELITE_FRONTIER_MINIMUM}'
            UNION ALL
            SELECT
                'publication_status',
                'supplemental_rankings_frozen'
            UNION ALL
            SELECT
                'created_at_utc',
                CURRENT_TIMESTAMP::VARCHAR
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

    output_files = sorted(
        path
        for path in OUTPUT_DIR.iterdir()
        if path.is_file()
        and path.name not in {
            "output_manifest.csv",
            "hard_checks.csv",
            "terminal_output.txt",
        }
    )

    write_csv(
        OUTPUT_DIR / "output_manifest.csv",
        [
            {
                "output_name": path.name,
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "dataset_version": DATASET_VERSION,
                "policy_version": POLICY_VERSION,
            }
            for path in output_files
        ],
        [
            "output_name",
            "path",
            "size_bytes",
            "sha256",
            "dataset_version",
            "policy_version",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 5 PHASE 5K — SUPPLEMENTAL DEVELOPMENT RANKINGS",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "PRODUCTS",
        "-" * 78,
        "Development Consistency",
        "Elite / Frontier Development",
        "Four Baseline-Tier Rankings",
        "Breakout Rate",
        "Balanced Program",
        "Development Efficiency",
        "Ranking Robustness",
        "Inbound Transfer Development",
        "",
        "RESULTS",
        "-" * 78,
        f"Source trajectories: {int(counts['trajectory_rows']):,}",
        f"Athlete-school units: {int(counts['athlete_school_rows']):,}",
        f"Athlete-segment units: {int(counts['athlete_segment_rows']):,}",
        f"Inbound transfer destination units: "
        f"{int(counts['transfer_destination_rows']):,}",
        f"Official balanced programs: "
        f"{int(counts['official_balance_school_rows']):,}",
        f"Robustness schools: "
        f"{int(counts['robustness_school_rows']):,}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — All supplemental ranking products frozen."
            if not failed
            else "FAIL — Review supplemental ranking validation."
        ),
        "",
        "NEXT",
        "-" * 78,
        "Review leaders and transfer-definition caveats.",
        "Update the Milestone 5 methodology document and README.",
        "Then stage, commit, push, and verify the milestone-5 branch.",
    ]

    (OUTPUT_DIR / "phase_5k_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Athlete-segment units: "
        f"{int(counts['athlete_segment_rows']):,}"
    )
    print(
        f"Inbound transfer destination units: "
        f"{int(counts['transfer_destination_rows']):,}"
    )
    print(
        f"Official balanced programs: "
        f"{int(counts['official_balance_school_rows']):,}"
    )
    print(
        f"Robustness schools: "
        f"{int(counts['robustness_school_rows']):,}"
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
    print("Next: finalize Milestone 5 documentation and Git.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
