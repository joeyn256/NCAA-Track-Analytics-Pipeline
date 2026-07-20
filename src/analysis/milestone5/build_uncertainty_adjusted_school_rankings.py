#!/usr/bin/env python3
"""
Milestone 5 Phase 5G — Uncertainty-Adjusted School Rankings

Builds the first official school-development rankings from the Phase 5F
multi-event-neutral athlete contributions.

Primary ranking model
---------------------
- One equal-weight athlete-school contribution per person and school.
- School raw score = mean athlete-school value added.
- Small-sample within-school variance is stabilized toward the pooled
  athlete-level variance using a 20-degree-of-freedom prior.
- True between-school variance is estimated by method of moments:
      tau^2 = max(0, variance(raw school means) - mean(sampling variance))
- Empirical-Bayes school score:
      global mean + shrinkage_weight * (raw score - global mean)
  where:
      shrinkage_weight = tau^2 / (tau^2 + stabilized_sampling_variance)

Publication policy
------------------
- Every school receives a posterior score and all-school diagnostic rank.
- Official overall rank requires at least 30 athlete-school units.
- Official men's/women's rank requires at least 20 athlete-school units.
- Official event-family rank requires at least 10 athlete-family units.
- Schools below a threshold remain visible as insufficient-data programs.
- Confidence intervals, evidence categories, sample size, and shrinkage are
  published with every score.

This phase produces official ranking candidates. A final sensitivity and
manual-review phase must pass before Milestone 5 publication is frozen.
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

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5g_uncertainty_adjusted_school_rankings"
)

OUTPUT_DB = OUTPUT_DIR / "school_development_rankings_v1.duckdb"

INPUT_DATASET_VERSION = "athlete_contributions_v1"
INPUT_AGGREGATION_POLICY = "equal_family_equal_athlete_v1"
DATASET_VERSION = "school_development_rankings_v1"
RANKING_POLICY_VERSION = "empirical_bayes_school_rankings_v1"

EXPECTED_ATHLETE_SCHOOL_ROWS = 80_077
EXPECTED_ATHLETE_FAMILY_ROWS = 98_888
EXPECTED_SCHOOLS = 361

VARIANCE_PRIOR_DF = 20.0
CI_Z = 1.96

OVERALL_MIN_SAMPLE = 30
GENDER_MIN_SAMPLE = 20
EVENT_FAMILY_MIN_SAMPLE = 10

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

    print("MILESTONE 5 PHASE 5G — UNCERTAINTY-ADJUSTED SCHOOL RANKINGS")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Ranking policy: {RANKING_POLICY_VERSION}")
    print(f"Input database: {INPUT_DB}")
    print(f"Output database: {OUTPUT_DB}")

    required_inputs = [INPUT_DB, PHASE_5F_CHECKS]
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
        print("PHASE GATE: FAIL — Required Phase 5F input missing.")
        return 1

    phase_5f_checks = read_csv(PHASE_5F_CHECKS)
    failed_phase_5f_checks = [
        row for row in phase_5f_checks
        if row.get("status") != "PASS"
    ]

    add_check(
        checks,
        "phase_5f_gate_passed",
        not failed_phase_5f_checks,
        [row.get("check_name") for row in failed_phase_5f_checks],
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
                AS contribution_source (READ_ONLY)
            """
        )

        metadata = {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM contribution_source.main.dataset_metadata
                """
            ).fetchall()
        }

        add_check(
            checks,
            "input_dataset_version_matches",
            metadata.get("dataset_version") == INPUT_DATASET_VERSION,
            metadata.get("dataset_version"),
            INPUT_DATASET_VERSION,
        )
        add_check(
            checks,
            "input_aggregation_policy_matches",
            metadata.get("aggregation_policy_version")
            == INPUT_AGGREGATION_POLICY,
            metadata.get("aggregation_policy_version"),
            INPUT_AGGREGATION_POLICY,
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
            CREATE TABLE athlete_family_snapshot AS
            SELECT *
            FROM contribution_source.main.athlete_event_family_value_added
            """
        )

        con.execute(
            """
            CREATE TABLE preliminary_school_snapshot AS
            SELECT *
            FROM contribution_source.main.preliminary_school_scores
            """
        )

        # ------------------------------------------------------------------
        # Overall school empirical-Bayes model
        # ------------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE overall_school_base AS
            SELECT
                resolved_school_id,
                COUNT(*) AS athlete_school_unit_count,
                COUNT(DISTINCT canonical_person_id)
                    AS distinct_athlete_count,
                COUNT(*) FILTER (
                    WHERE canonical_gender_code = 'm'
                ) AS male_athlete_unit_count,
                COUNT(*) FILTER (
                    WHERE canonical_gender_code = 'f'
                ) AS female_athlete_unit_count,
                AVG(primary_athlete_value_added)
                    AS raw_school_score,
                MEDIAN(primary_athlete_value_added)
                    AS median_athlete_value_added,
                VAR_SAMP(primary_athlete_value_added)
                    AS raw_within_school_variance,
                STDDEV_SAMP(primary_athlete_value_added)
                    AS raw_within_school_sd,
                AVG(
                    CAST(
                        primary_athlete_value_added > 0
                        AS DOUBLE
                    )
                ) AS above_expected_athlete_share,
                AVG(event_family_count)
                    AS mean_event_families_per_athlete,
                AVG(trajectory_count)
                    AS mean_trajectories_per_athlete,
                SUM(trajectory_count) AS trajectory_count,
                SUM(event_family_count) AS athlete_family_unit_count,
                AVG(winsorized_athlete_value_added)
                    AS winsorized_school_score,
                AVG(family_median_athlete_value_added)
                    AS family_median_school_score,
                MIN(minimum_training_support)
                    AS minimum_training_support
            FROM athlete_school_snapshot
            GROUP BY resolved_school_id
            """
        )

        con.execute(
            """
            CREATE TABLE overall_variance_prior AS
            SELECT
                AVG(primary_athlete_value_added)
                    AS global_athlete_mean,
                VAR_SAMP(primary_athlete_value_added)
                    AS global_athlete_variance,
                (
                    SELECT
                        SUM(
                            (athlete_school_unit_count - 1)
                            * COALESCE(raw_within_school_variance, 0)
                        )
                        / NULLIF(
                            SUM(athlete_school_unit_count - 1),
                            0
                        )
                    FROM overall_school_base
                ) AS pooled_within_school_variance,
                COUNT(*) AS total_athlete_school_units
            FROM athlete_school_snapshot
            """
        )

        con.execute(
            f"""
            CREATE TABLE overall_school_stabilized AS
            SELECT
                b.*,
                p.global_athlete_mean,
                p.global_athlete_variance,
                COALESCE(
                    p.pooled_within_school_variance,
                    p.global_athlete_variance
                ) AS pooled_within_school_variance,
                (
                    (
                        (b.athlete_school_unit_count - 1)
                        * COALESCE(
                            b.raw_within_school_variance,
                            COALESCE(
                                p.pooled_within_school_variance,
                                p.global_athlete_variance
                            )
                        )
                    )
                    + {VARIANCE_PRIOR_DF}
                        * COALESCE(
                            p.pooled_within_school_variance,
                            p.global_athlete_variance
                        )
                )
                / (
                    b.athlete_school_unit_count - 1
                    + {VARIANCE_PRIOR_DF}
                ) AS stabilized_within_school_variance,
                (
                    (
                        (
                            (b.athlete_school_unit_count - 1)
                            * COALESCE(
                                b.raw_within_school_variance,
                                COALESCE(
                                    p.pooled_within_school_variance,
                                    p.global_athlete_variance
                                )
                            )
                        )
                        + {VARIANCE_PRIOR_DF}
                            * COALESCE(
                                p.pooled_within_school_variance,
                                p.global_athlete_variance
                            )
                    )
                    / (
                        b.athlete_school_unit_count - 1
                        + {VARIANCE_PRIOR_DF}
                    )
                )
                / b.athlete_school_unit_count
                    AS stabilized_sampling_variance
            FROM overall_school_base b
            CROSS JOIN overall_variance_prior p
            """
        )

        con.execute(
            """
            CREATE TABLE overall_between_school_variance AS
            SELECT
                GREATEST(
                    0.0,
                    VAR_SAMP(raw_school_score)
                    - AVG(stabilized_sampling_variance)
                ) AS between_school_variance,
                VAR_SAMP(raw_school_score)
                    AS observed_school_mean_variance,
                AVG(stabilized_sampling_variance)
                    AS mean_sampling_variance,
                COUNT(*) AS school_count
            FROM overall_school_stabilized
            """
        )

        con.execute(
            f"""
            CREATE TABLE overall_school_posterior_base AS
            SELECT
                s.*,
                t.between_school_variance,
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
                s.athlete_school_unit_count
                    >= {OVERALL_MIN_SAMPLE}
                    AS official_rank_eligible,
                CASE
                    WHEN s.athlete_school_unit_count >= 300
                        THEN 'exceptional_sample'
                    WHEN s.athlete_school_unit_count >= 200
                        THEN 'high_reliability'
                    WHEN s.athlete_school_unit_count >= 100
                        THEN 'strong_reliability'
                    WHEN s.athlete_school_unit_count >= 50
                        THEN 'standard_reliability'
                    WHEN s.athlete_school_unit_count
                            >= {OVERALL_MIN_SAMPLE}
                        THEN 'provisional_reliability'
                    ELSE 'insufficient_data'
                END AS reliability_tier
            FROM overall_school_stabilized s
            CROSS JOIN overall_between_school_variance t
            """
        )

        con.execute(
            f"""
            CREATE TABLE overall_school_rankings AS
            WITH intervals AS (
                SELECT
                    *,
                    posterior_school_score
                        - {CI_Z} * posterior_standard_error
                        AS posterior_ci95_lower,
                    posterior_school_score
                        + {CI_Z} * posterior_standard_error
                        AS posterior_ci95_upper,
                    RANK() OVER (
                        ORDER BY posterior_school_score DESC
                    ) AS all_school_posterior_rank,
                    RANK() OVER (
                        ORDER BY raw_school_score DESC
                    ) AS raw_school_rank
                FROM overall_school_posterior_base
            ),
            official AS (
                SELECT
                    resolved_school_id,
                    RANK() OVER (
                        ORDER BY posterior_school_score DESC
                    ) AS official_overall_rank,
                    COUNT(*) OVER () AS official_ranked_school_count
                FROM intervals
                WHERE official_rank_eligible
            ),
            joined AS (
                SELECT
                    i.*,
                    o.official_overall_rank,
                    o.official_ranked_school_count
                FROM intervals i
                LEFT JOIN official o
                  USING (resolved_school_id)
            )
            SELECT
                *,
                CASE
                    WHEN NOT official_rank_eligible
                        THEN 'insufficient_data'
                    WHEN official_overall_rank::DOUBLE
                            / official_ranked_school_count <= 0.10
                        THEN 'top_10_percent'
                    WHEN official_overall_rank::DOUBLE
                            / official_ranked_school_count <= 0.25
                        THEN 'top_25_percent'
                    WHEN official_overall_rank::DOUBLE
                            / official_ranked_school_count <= 0.50
                        THEN 'top_half'
                    WHEN official_overall_rank::DOUBLE
                            / official_ranked_school_count <= 0.75
                        THEN 'lower_middle'
                    ELSE 'bottom_25_percent'
                END AS ranking_band,
                CASE
                    WHEN posterior_ci95_lower > 0
                        THEN 'credible_above_expected'
                    WHEN posterior_ci95_upper < 0
                        THEN 'credible_below_expected'
                    ELSE 'not_distinguishable_from_expected'
                END AS evidence_category,
                posterior_school_score - raw_school_score
                    AS shrinkage_adjustment,
                ABS(all_school_posterior_rank - raw_school_rank)
                    AS absolute_rank_change_from_raw,
                '{DATASET_VERSION}' AS dataset_version,
                '{RANKING_POLICY_VERSION}' AS ranking_policy_version
            FROM joined
            """
        )

        # ------------------------------------------------------------------
        # Gender-specific school empirical-Bayes models
        # ------------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE gender_school_base AS
            SELECT
                resolved_school_id,
                canonical_gender_code,
                COUNT(*) AS athlete_school_unit_count,
                COUNT(DISTINCT canonical_person_id)
                    AS distinct_athlete_count,
                AVG(primary_athlete_value_added)
                    AS raw_school_score,
                MEDIAN(primary_athlete_value_added)
                    AS median_athlete_value_added,
                VAR_SAMP(primary_athlete_value_added)
                    AS raw_within_school_variance,
                AVG(
                    CAST(
                        primary_athlete_value_added > 0
                        AS DOUBLE
                    )
                ) AS above_expected_athlete_share,
                SUM(trajectory_count) AS trajectory_count,
                SUM(event_family_count) AS athlete_family_unit_count,
                AVG(winsorized_athlete_value_added)
                    AS winsorized_school_score
            FROM athlete_school_snapshot
            GROUP BY
                resolved_school_id,
                canonical_gender_code
            """
        )

        con.execute(
            """
            CREATE TABLE gender_variance_prior AS
            WITH globals AS (
                SELECT
                    canonical_gender_code,
                    AVG(primary_athlete_value_added)
                        AS global_athlete_mean,
                    VAR_SAMP(primary_athlete_value_added)
                        AS global_athlete_variance
                FROM athlete_school_snapshot
                GROUP BY canonical_gender_code
            ),
            pooled AS (
                SELECT
                    canonical_gender_code,
                    SUM(
                        (athlete_school_unit_count - 1)
                        * COALESCE(raw_within_school_variance, 0)
                    )
                    / NULLIF(
                        SUM(athlete_school_unit_count - 1),
                        0
                    ) AS pooled_within_school_variance
                FROM gender_school_base
                GROUP BY canonical_gender_code
            )
            SELECT *
            FROM globals
            JOIN pooled
              USING (canonical_gender_code)
            """
        )

        con.execute(
            f"""
            CREATE TABLE gender_school_stabilized AS
            SELECT
                b.*,
                p.global_athlete_mean,
                p.global_athlete_variance,
                COALESCE(
                    p.pooled_within_school_variance,
                    p.global_athlete_variance
                ) AS pooled_within_school_variance,
                (
                    (
                        (b.athlete_school_unit_count - 1)
                        * COALESCE(
                            b.raw_within_school_variance,
                            COALESCE(
                                p.pooled_within_school_variance,
                                p.global_athlete_variance
                            )
                        )
                    )
                    + {VARIANCE_PRIOR_DF}
                        * COALESCE(
                            p.pooled_within_school_variance,
                            p.global_athlete_variance
                        )
                )
                / (
                    b.athlete_school_unit_count - 1
                    + {VARIANCE_PRIOR_DF}
                ) AS stabilized_within_school_variance,
                (
                    (
                        (
                            (b.athlete_school_unit_count - 1)
                            * COALESCE(
                                b.raw_within_school_variance,
                                COALESCE(
                                    p.pooled_within_school_variance,
                                    p.global_athlete_variance
                                )
                            )
                        )
                        + {VARIANCE_PRIOR_DF}
                            * COALESCE(
                                p.pooled_within_school_variance,
                                p.global_athlete_variance
                            )
                    )
                    / (
                        b.athlete_school_unit_count - 1
                        + {VARIANCE_PRIOR_DF}
                    )
                )
                / b.athlete_school_unit_count
                    AS stabilized_sampling_variance
            FROM gender_school_base b
            JOIN gender_variance_prior p
              USING (canonical_gender_code)
            """
        )

        con.execute(
            """
            CREATE TABLE gender_between_school_variance AS
            SELECT
                canonical_gender_code,
                GREATEST(
                    0.0,
                    VAR_SAMP(raw_school_score)
                    - AVG(stabilized_sampling_variance)
                ) AS between_school_variance,
                VAR_SAMP(raw_school_score)
                    AS observed_school_mean_variance,
                AVG(stabilized_sampling_variance)
                    AS mean_sampling_variance,
                COUNT(*) AS school_count
            FROM gender_school_stabilized
            GROUP BY canonical_gender_code
            """
        )

        con.execute(
            f"""
            CREATE TABLE gender_school_posterior_base AS
            SELECT
                s.*,
                t.between_school_variance,
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
                s.athlete_school_unit_count
                    >= {GENDER_MIN_SAMPLE}
                    AS official_rank_eligible,
                CASE
                    WHEN s.athlete_school_unit_count >= 150
                        THEN 'high_reliability'
                    WHEN s.athlete_school_unit_count >= 75
                        THEN 'strong_reliability'
                    WHEN s.athlete_school_unit_count >= 40
                        THEN 'standard_reliability'
                    WHEN s.athlete_school_unit_count
                            >= {GENDER_MIN_SAMPLE}
                        THEN 'provisional_reliability'
                    ELSE 'insufficient_data'
                END AS reliability_tier
            FROM gender_school_stabilized s
            JOIN gender_between_school_variance t
              USING (canonical_gender_code)
            """
        )

        con.execute(
            f"""
            CREATE TABLE gender_school_rankings AS
            WITH intervals AS (
                SELECT
                    *,
                    posterior_school_score
                        - {CI_Z} * posterior_standard_error
                        AS posterior_ci95_lower,
                    posterior_school_score
                        + {CI_Z} * posterior_standard_error
                        AS posterior_ci95_upper,
                    RANK() OVER (
                        PARTITION BY canonical_gender_code
                        ORDER BY posterior_school_score DESC
                    ) AS all_school_gender_rank,
                    RANK() OVER (
                        PARTITION BY canonical_gender_code
                        ORDER BY raw_school_score DESC
                    ) AS raw_gender_rank
                FROM gender_school_posterior_base
            ),
            official AS (
                SELECT
                    resolved_school_id,
                    canonical_gender_code,
                    RANK() OVER (
                        PARTITION BY canonical_gender_code
                        ORDER BY posterior_school_score DESC
                    ) AS official_gender_rank,
                    COUNT(*) OVER (
                        PARTITION BY canonical_gender_code
                    ) AS official_ranked_school_count
                FROM intervals
                WHERE official_rank_eligible
            )
            SELECT
                i.*,
                o.official_gender_rank,
                o.official_ranked_school_count,
                CASE
                    WHEN NOT i.official_rank_eligible
                        THEN 'insufficient_data'
                    WHEN o.official_gender_rank::DOUBLE
                            / o.official_ranked_school_count <= 0.10
                        THEN 'top_10_percent'
                    WHEN o.official_gender_rank::DOUBLE
                            / o.official_ranked_school_count <= 0.25
                        THEN 'top_25_percent'
                    WHEN o.official_gender_rank::DOUBLE
                            / o.official_ranked_school_count <= 0.50
                        THEN 'top_half'
                    WHEN o.official_gender_rank::DOUBLE
                            / o.official_ranked_school_count <= 0.75
                        THEN 'lower_middle'
                    ELSE 'bottom_25_percent'
                END AS ranking_band,
                CASE
                    WHEN i.posterior_ci95_lower > 0
                        THEN 'credible_above_expected'
                    WHEN i.posterior_ci95_upper < 0
                        THEN 'credible_below_expected'
                    ELSE 'not_distinguishable_from_expected'
                END AS evidence_category,
                i.posterior_school_score - i.raw_school_score
                    AS shrinkage_adjustment,
                ABS(i.all_school_gender_rank - i.raw_gender_rank)
                    AS absolute_rank_change_from_raw,
                '{DATASET_VERSION}' AS dataset_version,
                '{RANKING_POLICY_VERSION}' AS ranking_policy_version
            FROM intervals i
            LEFT JOIN official o
              USING (
                resolved_school_id,
                canonical_gender_code
              )
            """
        )

        # ------------------------------------------------------------------
        # Event-family empirical-Bayes rankings
        # ------------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE event_family_school_base AS
            SELECT
                resolved_school_id,
                canonical_gender_code,
                event_family,
                COUNT(*) AS athlete_family_unit_count,
                COUNT(DISTINCT canonical_person_id)
                    AS distinct_athlete_count,
                AVG(family_mean_value_added)
                    AS raw_school_score,
                MEDIAN(family_mean_value_added)
                    AS median_athlete_family_value_added,
                VAR_SAMP(family_mean_value_added)
                    AS raw_within_school_variance,
                AVG(
                    CAST(
                        family_mean_value_added > 0
                        AS DOUBLE
                    )
                ) AS above_expected_athlete_share,
                SUM(trajectory_count) AS trajectory_count,
                AVG(family_winsorized_mean_value_added)
                    AS winsorized_school_score
            FROM athlete_family_snapshot
            GROUP BY
                resolved_school_id,
                canonical_gender_code,
                event_family
            """
        )

        con.execute(
            """
            CREATE TABLE event_family_variance_prior AS
            WITH globals AS (
                SELECT
                    canonical_gender_code,
                    event_family,
                    AVG(family_mean_value_added)
                        AS global_athlete_mean,
                    VAR_SAMP(family_mean_value_added)
                        AS global_athlete_variance
                FROM athlete_family_snapshot
                GROUP BY
                    canonical_gender_code,
                    event_family
            ),
            pooled AS (
                SELECT
                    canonical_gender_code,
                    event_family,
                    SUM(
                        (athlete_family_unit_count - 1)
                        * COALESCE(raw_within_school_variance, 0)
                    )
                    / NULLIF(
                        SUM(athlete_family_unit_count - 1),
                        0
                    ) AS pooled_within_school_variance
                FROM event_family_school_base
                GROUP BY
                    canonical_gender_code,
                    event_family
            )
            SELECT *
            FROM globals
            JOIN pooled
              USING (
                canonical_gender_code,
                event_family
              )
            """
        )

        con.execute(
            f"""
            CREATE TABLE event_family_school_stabilized AS
            SELECT
                b.*,
                p.global_athlete_mean,
                p.global_athlete_variance,
                COALESCE(
                    p.pooled_within_school_variance,
                    p.global_athlete_variance
                ) AS pooled_within_school_variance,
                (
                    (
                        (b.athlete_family_unit_count - 1)
                        * COALESCE(
                            b.raw_within_school_variance,
                            COALESCE(
                                p.pooled_within_school_variance,
                                p.global_athlete_variance
                            )
                        )
                    )
                    + {VARIANCE_PRIOR_DF}
                        * COALESCE(
                            p.pooled_within_school_variance,
                            p.global_athlete_variance
                        )
                )
                / (
                    b.athlete_family_unit_count - 1
                    + {VARIANCE_PRIOR_DF}
                ) AS stabilized_within_school_variance,
                (
                    (
                        (
                            (b.athlete_family_unit_count - 1)
                            * COALESCE(
                                b.raw_within_school_variance,
                                COALESCE(
                                    p.pooled_within_school_variance,
                                    p.global_athlete_variance
                                )
                            )
                        )
                        + {VARIANCE_PRIOR_DF}
                            * COALESCE(
                                p.pooled_within_school_variance,
                                p.global_athlete_variance
                            )
                    )
                    / (
                        b.athlete_family_unit_count - 1
                        + {VARIANCE_PRIOR_DF}
                    )
                )
                / b.athlete_family_unit_count
                    AS stabilized_sampling_variance
            FROM event_family_school_base b
            JOIN event_family_variance_prior p
              USING (
                canonical_gender_code,
                event_family
              )
            """
        )

        con.execute(
            """
            CREATE TABLE event_family_between_school_variance AS
            SELECT
                canonical_gender_code,
                event_family,
                GREATEST(
                    0.0,
                    VAR_SAMP(raw_school_score)
                    - AVG(stabilized_sampling_variance)
                ) AS between_school_variance,
                VAR_SAMP(raw_school_score)
                    AS observed_school_mean_variance,
                AVG(stabilized_sampling_variance)
                    AS mean_sampling_variance,
                COUNT(*) AS school_count
            FROM event_family_school_stabilized
            GROUP BY
                canonical_gender_code,
                event_family
            """
        )

        con.execute(
            f"""
            CREATE TABLE event_family_school_posterior_base AS
            SELECT
                s.*,
                t.between_school_variance,
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
                s.athlete_family_unit_count
                    >= {EVENT_FAMILY_MIN_SAMPLE}
                    AS official_rank_eligible,
                CASE
                    WHEN s.athlete_family_unit_count >= 50
                        THEN 'high_reliability'
                    WHEN s.athlete_family_unit_count >= 25
                        THEN 'strong_reliability'
                    WHEN s.athlete_family_unit_count >= 15
                        THEN 'standard_reliability'
                    WHEN s.athlete_family_unit_count
                            >= {EVENT_FAMILY_MIN_SAMPLE}
                        THEN 'provisional_reliability'
                    ELSE 'insufficient_data'
                END AS reliability_tier
            FROM event_family_school_stabilized s
            JOIN event_family_between_school_variance t
              USING (
                canonical_gender_code,
                event_family
              )
            """
        )

        con.execute(
            f"""
            CREATE TABLE event_family_school_rankings AS
            WITH intervals AS (
                SELECT
                    *,
                    posterior_school_score
                        - {CI_Z} * posterior_standard_error
                        AS posterior_ci95_lower,
                    posterior_school_score
                        + {CI_Z} * posterior_standard_error
                        AS posterior_ci95_upper,
                    RANK() OVER (
                        PARTITION BY
                            canonical_gender_code,
                            event_family
                        ORDER BY posterior_school_score DESC
                    ) AS all_school_family_rank,
                    RANK() OVER (
                        PARTITION BY
                            canonical_gender_code,
                            event_family
                        ORDER BY raw_school_score DESC
                    ) AS raw_family_rank
                FROM event_family_school_posterior_base
            ),
            official AS (
                SELECT
                    resolved_school_id,
                    canonical_gender_code,
                    event_family,
                    RANK() OVER (
                        PARTITION BY
                            canonical_gender_code,
                            event_family
                        ORDER BY posterior_school_score DESC
                    ) AS official_event_family_rank,
                    COUNT(*) OVER (
                        PARTITION BY
                            canonical_gender_code,
                            event_family
                    ) AS official_ranked_school_count
                FROM intervals
                WHERE official_rank_eligible
            )
            SELECT
                i.*,
                o.official_event_family_rank,
                o.official_ranked_school_count,
                CASE
                    WHEN NOT i.official_rank_eligible
                        THEN 'insufficient_data'
                    WHEN o.official_event_family_rank::DOUBLE
                            / o.official_ranked_school_count <= 0.10
                        THEN 'top_10_percent'
                    WHEN o.official_event_family_rank::DOUBLE
                            / o.official_ranked_school_count <= 0.25
                        THEN 'top_25_percent'
                    WHEN o.official_event_family_rank::DOUBLE
                            / o.official_ranked_school_count <= 0.50
                        THEN 'top_half'
                    WHEN o.official_event_family_rank::DOUBLE
                            / o.official_ranked_school_count <= 0.75
                        THEN 'lower_middle'
                    ELSE 'bottom_25_percent'
                END AS ranking_band,
                CASE
                    WHEN i.posterior_ci95_lower > 0
                        THEN 'credible_above_expected'
                    WHEN i.posterior_ci95_upper < 0
                        THEN 'credible_below_expected'
                    ELSE 'not_distinguishable_from_expected'
                END AS evidence_category,
                i.posterior_school_score - i.raw_school_score
                    AS shrinkage_adjustment,
                ABS(i.all_school_family_rank - i.raw_family_rank)
                    AS absolute_rank_change_from_raw,
                '{DATASET_VERSION}' AS dataset_version,
                '{RANKING_POLICY_VERSION}' AS ranking_policy_version
            FROM intervals i
            LEFT JOIN official o
              USING (
                resolved_school_id,
                canonical_gender_code,
                event_family
              )
            """
        )

        # ------------------------------------------------------------------
        # Combined school score components
        # ------------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE school_score_components AS
            WITH gender_pivot AS (
                SELECT
                    resolved_school_id,
                    MAX(CASE
                        WHEN canonical_gender_code = 'm'
                        THEN posterior_school_score
                    END) AS mens_posterior_score,
                    MAX(CASE
                        WHEN canonical_gender_code = 'm'
                        THEN official_gender_rank
                    END) AS mens_official_rank,
                    MAX(CASE
                        WHEN canonical_gender_code = 'm'
                        THEN athlete_school_unit_count
                    END) AS mens_athlete_count,
                    MAX(CASE
                        WHEN canonical_gender_code = 'f'
                        THEN posterior_school_score
                    END) AS womens_posterior_score,
                    MAX(CASE
                        WHEN canonical_gender_code = 'f'
                        THEN official_gender_rank
                    END) AS womens_official_rank,
                    MAX(CASE
                        WHEN canonical_gender_code = 'f'
                        THEN athlete_school_unit_count
                    END) AS womens_athlete_count
                FROM gender_school_rankings
                GROUP BY resolved_school_id
            ),
            family_coverage AS (
                SELECT
                    resolved_school_id,
                    COUNT(*) AS represented_gender_family_groups,
                    COUNT(*) FILTER (
                        WHERE official_rank_eligible
                    ) AS officially_ranked_gender_family_groups,
                    COUNT(DISTINCT event_family)
                        AS represented_event_families,
                    AVG(posterior_school_score)
                        AS mean_event_family_posterior_score,
                    MIN(posterior_school_score)
                        AS minimum_event_family_posterior_score,
                    MAX(posterior_school_score)
                        AS maximum_event_family_posterior_score
                FROM event_family_school_rankings
                GROUP BY resolved_school_id
            )
            SELECT
                o.*,
                g.mens_posterior_score,
                g.mens_official_rank,
                g.mens_athlete_count,
                g.womens_posterior_score,
                g.womens_official_rank,
                g.womens_athlete_count,
                f.represented_gender_family_groups,
                f.officially_ranked_gender_family_groups,
                f.represented_event_families,
                f.mean_event_family_posterior_score,
                f.minimum_event_family_posterior_score,
                f.maximum_event_family_posterior_score
            FROM overall_school_rankings o
            LEFT JOIN gender_pivot g
              USING (resolved_school_id)
            LEFT JOIN family_coverage f
              USING (resolved_school_id)
            """
        )

        con.execute(
            f"""
            CREATE TABLE ranking_policy AS
            SELECT
                'overall_minimum_sample' AS policy_key,
                '{OVERALL_MIN_SAMPLE}' AS policy_value,
                'Minimum athlete-school units for an official overall rank.'
                    AS rationale
            UNION ALL
            SELECT
                'gender_minimum_sample',
                '{GENDER_MIN_SAMPLE}',
                'Minimum same-gender athlete-school units for an official '
                    || 'men''s or women''s rank.'
            UNION ALL
            SELECT
                'event_family_minimum_sample',
                '{EVENT_FAMILY_MIN_SAMPLE}',
                'Minimum athlete-family units for an official family rank.'
            UNION ALL
            SELECT
                'variance_prior_df',
                '{VARIANCE_PRIOR_DF}',
                'Stabilizes small-sample within-school variance estimates.'
            UNION ALL
            SELECT
                'confidence_interval',
                '95_percent_normal',
                'Posterior uncertainty interval using z=1.96.'
            UNION ALL
            SELECT
                'all_school_visibility',
                'true',
                'All schools retain posterior scores even when official '
                    || 'ranking eligibility is insufficient.'
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
                'ranking_policy_version',
                '{RANKING_POLICY_VERSION}'
            UNION ALL
            SELECT
                'input_dataset_version',
                '{INPUT_DATASET_VERSION}'
            UNION ALL
            SELECT
                'official_overall_minimum_sample',
                '{OVERALL_MIN_SAMPLE}'
            UNION ALL
            SELECT
                'official_gender_minimum_sample',
                '{GENDER_MIN_SAMPLE}'
            UNION ALL
            SELECT
                'official_event_family_minimum_sample',
                '{EVENT_FAMILY_MIN_SAMPLE}'
            UNION ALL
            SELECT
                'ranking_status',
                'official_candidate_pending_final_sensitivity'
            UNION ALL
            SELECT
                'created_at_utc',
                CURRENT_TIMESTAMP::VARCHAR
            """
        )

        # ------------------------------------------------------------------
        # Validation
        # ------------------------------------------------------------------
        counts = fetch_dicts(
            con,
            """
            SELECT
                (SELECT COUNT(*) FROM athlete_school_snapshot)
                    AS athlete_school_rows,
                (SELECT COUNT(*) FROM athlete_family_snapshot)
                    AS athlete_family_rows,
                (SELECT COUNT(*) FROM overall_school_rankings)
                    AS overall_school_rows,
                (SELECT COUNT(DISTINCT resolved_school_id)
                 FROM overall_school_rankings)
                    AS school_count,
                (SELECT COUNT(*)
                 FROM overall_school_rankings
                 WHERE official_rank_eligible)
                    AS official_overall_school_count,
                (SELECT COUNT(*)
                 FROM overall_school_rankings
                 WHERE NOT official_rank_eligible)
                    AS insufficient_overall_school_count,
                (SELECT COUNT(*) FROM gender_school_rankings)
                    AS gender_school_rows,
                (SELECT COUNT(*)
                 FROM gender_school_rankings
                 WHERE official_rank_eligible)
                    AS official_gender_school_rows,
                (SELECT COUNT(*) FROM event_family_school_rankings)
                    AS event_family_school_rows,
                (SELECT COUNT(*)
                 FROM event_family_school_rankings
                 WHERE official_rank_eligible)
                    AS official_event_family_rows
            """
        )[0]

        quality = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM overall_school_rankings
                 WHERE posterior_school_score IS NULL
                    OR posterior_standard_error IS NULL
                    OR posterior_ci95_lower IS NULL
                    OR posterior_ci95_upper IS NULL)
                    AS null_overall_scoring_rows,
                (SELECT COUNT(*)
                 FROM overall_school_rankings
                 WHERE shrinkage_weight < 0
                    OR shrinkage_weight > 1)
                    AS invalid_overall_weight_rows,
                (SELECT COUNT(*)
                 FROM overall_school_rankings
                 WHERE posterior_ci95_lower
                    > posterior_ci95_upper)
                    AS invalid_overall_interval_rows,
                (SELECT COUNT(*)
                 FROM overall_school_rankings
                 WHERE posterior_school_score
                    < LEAST(raw_school_score, global_athlete_mean)
                        - {FORMULA_TOLERANCE}
                    OR posterior_school_score
                    > GREATEST(raw_school_score, global_athlete_mean)
                        + {FORMULA_TOLERANCE})
                    AS nonconvex_overall_posterior_rows,
                (SELECT COUNT(*)
                 FROM overall_school_rankings
                 WHERE official_rank_eligible
                    <> (
                        athlete_school_unit_count
                        >= {OVERALL_MIN_SAMPLE}
                    ))
                    AS overall_eligibility_mismatch_rows,
                (SELECT COUNT(*)
                 FROM overall_school_rankings
                 WHERE official_rank_eligible
                   AND official_overall_rank IS NULL)
                    AS missing_official_overall_rank_rows,
                (SELECT COUNT(*)
                 FROM overall_school_rankings
                 WHERE NOT official_rank_eligible
                   AND official_overall_rank IS NOT NULL)
                    AS ineligible_overall_rank_rows,
                (SELECT COUNT(*)
                 FROM gender_school_rankings
                 WHERE posterior_school_score IS NULL
                    OR shrinkage_weight < 0
                    OR shrinkage_weight > 1
                    OR posterior_ci95_lower > posterior_ci95_upper)
                    AS invalid_gender_rows,
                (SELECT COUNT(*)
                 FROM gender_school_rankings
                 WHERE official_rank_eligible
                    <> (
                        athlete_school_unit_count
                        >= {GENDER_MIN_SAMPLE}
                    ))
                    AS gender_eligibility_mismatch_rows,
                (SELECT COUNT(*)
                 FROM event_family_school_rankings
                 WHERE posterior_school_score IS NULL
                    OR shrinkage_weight < 0
                    OR shrinkage_weight > 1
                    OR posterior_ci95_lower > posterior_ci95_upper)
                    AS invalid_event_family_rows,
                (SELECT COUNT(*)
                 FROM event_family_school_rankings
                 WHERE official_rank_eligible
                    <> (
                        athlete_family_unit_count
                        >= {EVENT_FAMILY_MIN_SAMPLE}
                    ))
                    AS family_eligibility_mismatch_rows,
                (SELECT COUNT(*)
                 FROM (
                    SELECT resolved_school_id, COUNT(*) AS row_count
                    FROM overall_school_rankings
                    GROUP BY resolved_school_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_overall_school_rows
            """
        )[0]

        overall_hyper = fetch_dicts(
            con,
            """
            SELECT
                p.global_athlete_mean,
                p.global_athlete_variance,
                p.pooled_within_school_variance,
                t.observed_school_mean_variance,
                t.mean_sampling_variance,
                t.between_school_variance,
                t.school_count
            FROM overall_variance_prior p
            CROSS JOIN overall_between_school_variance t
            """
        )[0]

        sensitivity = fetch_dicts(
            con,
            """
            SELECT
                CORR(
                    posterior_school_score,
                    raw_school_score
                ) AS posterior_raw_score_correlation,
                CORR(
                    all_school_posterior_rank,
                    raw_school_rank
                ) AS posterior_raw_rank_correlation,
                CORR(
                    posterior_school_score,
                    winsorized_school_score
                ) AS posterior_winsorized_score_correlation,
                AVG(ABS(
                    all_school_posterior_rank - raw_school_rank
                )) AS mean_abs_rank_change_from_raw,
                MAX(ABS(
                    all_school_posterior_rank - raw_school_rank
                )) AS max_abs_rank_change_from_raw,
                AVG(shrinkage_weight)
                    AS mean_shrinkage_weight,
                MIN(shrinkage_weight)
                    AS minimum_shrinkage_weight,
                MAX(shrinkage_weight)
                    AS maximum_shrinkage_weight
            FROM overall_school_rankings
            """
        )[0]

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
            "athlete_family_row_count",
            counts["athlete_family_rows"]
            == EXPECTED_ATHLETE_FAMILY_ROWS,
            counts["athlete_family_rows"],
            EXPECTED_ATHLETE_FAMILY_ROWS,
        )
        add_check(
            checks,
            "overall_school_row_count",
            counts["overall_school_rows"] == EXPECTED_SCHOOLS,
            counts["overall_school_rows"],
            EXPECTED_SCHOOLS,
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
            "overall_school_rows_unique",
            quality["duplicate_overall_school_rows"] == 0,
            quality["duplicate_overall_school_rows"],
            0,
        )
        add_check(
            checks,
            "no_null_overall_scores",
            quality["null_overall_scoring_rows"] == 0,
            quality["null_overall_scoring_rows"],
            0,
        )
        add_check(
            checks,
            "overall_shrinkage_weights_valid",
            quality["invalid_overall_weight_rows"] == 0,
            quality["invalid_overall_weight_rows"],
            0,
        )
        add_check(
            checks,
            "overall_intervals_valid",
            quality["invalid_overall_interval_rows"] == 0,
            quality["invalid_overall_interval_rows"],
            0,
        )
        add_check(
            checks,
            "overall_posterior_is_convex_combination",
            quality["nonconvex_overall_posterior_rows"] == 0,
            quality["nonconvex_overall_posterior_rows"],
            0,
        )
        add_check(
            checks,
            "overall_minimum_sample_policy_applied",
            quality["overall_eligibility_mismatch_rows"] == 0,
            quality["overall_eligibility_mismatch_rows"],
            0,
        )
        add_check(
            checks,
            "official_overall_ranks_complete",
            quality["missing_official_overall_rank_rows"] == 0,
            quality["missing_official_overall_rank_rows"],
            0,
        )
        add_check(
            checks,
            "insufficient_schools_not_officially_ranked",
            quality["ineligible_overall_rank_rows"] == 0,
            quality["ineligible_overall_rank_rows"],
            0,
        )
        add_check(
            checks,
            "gender_rankings_valid",
            quality["invalid_gender_rows"] == 0
            and quality["gender_eligibility_mismatch_rows"] == 0,
            {
                "invalid_rows": quality["invalid_gender_rows"],
                "eligibility_mismatches":
                    quality["gender_eligibility_mismatch_rows"],
            },
            {
                "invalid_rows": 0,
                "eligibility_mismatches": 0,
            },
        )
        add_check(
            checks,
            "event_family_rankings_valid",
            quality["invalid_event_family_rows"] == 0
            and quality["family_eligibility_mismatch_rows"] == 0,
            {
                "invalid_rows":
                    quality["invalid_event_family_rows"],
                "eligibility_mismatches":
                    quality["family_eligibility_mismatch_rows"],
            },
            {
                "invalid_rows": 0,
                "eligibility_mismatches": 0,
            },
        )
        add_check(
            checks,
            "between_school_variance_positive",
            float(overall_hyper["between_school_variance"]) > 0,
            overall_hyper["between_school_variance"],
            "greater than 0",
        )
        add_check(
            checks,
            "official_and_insufficient_populations_exist",
            counts["official_overall_school_count"] > 0
            and counts["insufficient_overall_school_count"] > 0,
            {
                "official": counts["official_overall_school_count"],
                "insufficient":
                    counts["insufficient_overall_school_count"],
            },
            "both greater than 0",
        )

        # ------------------------------------------------------------------
        # Exports
        # ------------------------------------------------------------------
        overall_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM overall_school_rankings
            ORDER BY
                official_rank_eligible DESC,
                official_overall_rank NULLS LAST,
                all_school_posterior_rank,
                resolved_school_id
            """
        )
        write_csv(
            OUTPUT_DIR / "overall_school_rankings.csv",
            overall_rows,
            list(overall_rows[0].keys()) if overall_rows else [],
        )

        mens_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM gender_school_rankings
            WHERE canonical_gender_code = 'm'
            ORDER BY
                official_rank_eligible DESC,
                official_gender_rank NULLS LAST,
                all_school_gender_rank,
                resolved_school_id
            """
        )
        write_csv(
            OUTPUT_DIR / "mens_school_rankings.csv",
            mens_rows,
            list(mens_rows[0].keys()) if mens_rows else [],
        )

        womens_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM gender_school_rankings
            WHERE canonical_gender_code = 'f'
            ORDER BY
                official_rank_eligible DESC,
                official_gender_rank NULLS LAST,
                all_school_gender_rank,
                resolved_school_id
            """
        )
        write_csv(
            OUTPUT_DIR / "womens_school_rankings.csv",
            womens_rows,
            list(womens_rows[0].keys()) if womens_rows else [],
        )

        family_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM event_family_school_rankings
            ORDER BY
                canonical_gender_code,
                event_family,
                official_rank_eligible DESC,
                official_event_family_rank NULLS LAST,
                all_school_family_rank,
                resolved_school_id
            """
        )
        write_csv(
            OUTPUT_DIR / "event_family_rankings.csv",
            family_rows,
            list(family_rows[0].keys()) if family_rows else [],
        )

        component_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM school_score_components
            ORDER BY
                official_rank_eligible DESC,
                official_overall_rank NULLS LAST,
                all_school_posterior_rank,
                resolved_school_id
            """
        )
        write_csv(
            OUTPUT_DIR / "school_score_components.csv",
            component_rows,
            list(component_rows[0].keys()) if component_rows else [],
        )

        uncertainty_rows = fetch_dicts(
            con,
            """
            SELECT
                resolved_school_id,
                athlete_school_unit_count,
                raw_school_score,
                global_athlete_mean,
                stabilized_within_school_variance,
                stabilized_sampling_variance,
                between_school_variance,
                shrinkage_weight,
                posterior_school_score,
                posterior_standard_error,
                posterior_ci95_lower,
                posterior_ci95_upper,
                official_rank_eligible,
                reliability_tier,
                evidence_category,
                all_school_posterior_rank,
                official_overall_rank
            FROM overall_school_rankings
            ORDER BY
                posterior_standard_error DESC,
                resolved_school_id
            """
        )
        write_csv(
            OUTPUT_DIR / "ranking_uncertainty.csv",
            uncertainty_rows,
            list(uncertainty_rows[0].keys())
                if uncertainty_rows else [],
        )

        hyperparameter_rows = [
            {
                "scope": "overall",
                **overall_hyper,
                "variance_prior_df": VARIANCE_PRIOR_DF,
                "minimum_sample": OVERALL_MIN_SAMPLE,
            }
        ]
        write_csv(
            OUTPUT_DIR / "ranking_hyperparameters.csv",
            hyperparameter_rows,
            list(hyperparameter_rows[0].keys()),
        )

        gender_hyper_rows = fetch_dicts(
            con,
            f"""
            SELECT
                'gender' AS scope,
                g.canonical_gender_code,
                NULL::VARCHAR AS event_family,
                p.global_athlete_mean,
                p.global_athlete_variance,
                p.pooled_within_school_variance,
                t.observed_school_mean_variance,
                t.mean_sampling_variance,
                t.between_school_variance,
                t.school_count,
                {VARIANCE_PRIOR_DF}
                    AS variance_prior_df,
                {GENDER_MIN_SAMPLE}
                    AS minimum_sample
            FROM gender_variance_prior p
            JOIN gender_between_school_variance t
              USING (canonical_gender_code)
            JOIN (
                SELECT DISTINCT canonical_gender_code
                FROM gender_school_rankings
            ) g USING (canonical_gender_code)
            ORDER BY canonical_gender_code
            """
        )
        write_csv(
            OUTPUT_DIR / "gender_ranking_hyperparameters.csv",
            gender_hyper_rows,
            list(gender_hyper_rows[0].keys())
                if gender_hyper_rows else [],
        )

        family_hyper_rows = fetch_dicts(
            con,
            f"""
            SELECT
                'event_family' AS scope,
                p.canonical_gender_code,
                p.event_family,
                p.global_athlete_mean,
                p.global_athlete_variance,
                p.pooled_within_school_variance,
                t.observed_school_mean_variance,
                t.mean_sampling_variance,
                t.between_school_variance,
                t.school_count,
                {VARIANCE_PRIOR_DF}
                    AS variance_prior_df,
                {EVENT_FAMILY_MIN_SAMPLE}
                    AS minimum_sample
            FROM event_family_variance_prior p
            JOIN event_family_between_school_variance t
              USING (
                canonical_gender_code,
                event_family
              )
            ORDER BY
                canonical_gender_code,
                event_family
            """
        )
        write_csv(
            OUTPUT_DIR / "event_family_ranking_hyperparameters.csv",
            family_hyper_rows,
            list(family_hyper_rows[0].keys())
                if family_hyper_rows else [],
        )

        policy_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM ranking_policy
            ORDER BY policy_key
            """
        )
        write_csv(
            OUTPUT_DIR / "ranking_policy.csv",
            policy_rows,
            list(policy_rows[0].keys()) if policy_rows else [],
        )

        sensitivity_rows = [
            {"metric": key, "value": value}
            for key, value in sensitivity.items()
        ]
        write_csv(
            OUTPUT_DIR / "ranking_sensitivity_summary.csv",
            sensitivity_rows,
            ["metric", "value"],
        )

        threshold_summary = fetch_dicts(
            con,
            """
            SELECT
                reliability_tier,
                official_rank_eligible,
                COUNT(*) AS school_count,
                MIN(athlete_school_unit_count)
                    AS minimum_athlete_count,
                MAX(athlete_school_unit_count)
                    AS maximum_athlete_count,
                AVG(shrinkage_weight)
                    AS mean_shrinkage_weight,
                AVG(posterior_standard_error)
                    AS mean_posterior_standard_error
            FROM overall_school_rankings
            GROUP BY
                reliability_tier,
                official_rank_eligible
            ORDER BY
                official_rank_eligible DESC,
                minimum_athlete_count DESC
            """
        )
        write_csv(
            OUTPUT_DIR / "sample_size_tier_summary.csv",
            threshold_summary,
            list(threshold_summary[0].keys())
                if threshold_summary else [],
        )

        review_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM overall_school_rankings
            ORDER BY
                absolute_rank_change_from_raw DESC,
                athlete_school_unit_count,
                resolved_school_id
            LIMIT 150
            """
        )
        write_csv(
            OUTPUT_DIR / "shrinkage_rank_change_review.csv",
            review_rows,
            list(review_rows[0].keys()) if review_rows else [],
        )

        summary_rows = [
            {
                "metric": "athlete_school_units",
                "value": counts["athlete_school_rows"],
            },
            {
                "metric": "schools",
                "value": counts["overall_school_rows"],
            },
            {
                "metric": "official_overall_ranked_schools",
                "value": counts["official_overall_school_count"],
            },
            {
                "metric": "insufficient_overall_schools",
                "value": counts["insufficient_overall_school_count"],
            },
            {
                "metric": "official_gender_ranking_rows",
                "value": counts["official_gender_school_rows"],
            },
            {
                "metric": "official_event_family_ranking_rows",
                "value": counts["official_event_family_rows"],
            },
            {
                "metric": "global_athlete_mean",
                "value": overall_hyper["global_athlete_mean"],
            },
            {
                "metric": "pooled_within_school_variance",
                "value":
                    overall_hyper["pooled_within_school_variance"],
            },
            {
                "metric": "between_school_variance",
                "value": overall_hyper["between_school_variance"],
            },
            {
                "metric": "posterior_raw_score_correlation",
                "value":
                    sensitivity["posterior_raw_score_correlation"],
            },
            {
                "metric": "posterior_raw_rank_correlation",
                "value":
                    sensitivity["posterior_raw_rank_correlation"],
            },
            {
                "metric": "mean_abs_rank_change_from_raw",
                "value":
                    sensitivity["mean_abs_rank_change_from_raw"],
            },
            {
                "metric": "max_abs_rank_change_from_raw",
                "value":
                    sensitivity["max_abs_rank_change_from_raw"],
            },
            {
                "metric": "mean_shrinkage_weight",
                "value": sensitivity["mean_shrinkage_weight"],
            },
        ]
        write_csv(
            OUTPUT_DIR / "phase_5g_summary.csv",
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
                "ranking_policy_version": RANKING_POLICY_VERSION,
            }
        ],
        [
            "output_name",
            "path",
            "size_bytes",
            "sha256",
            "dataset_version",
            "ranking_policy_version",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    top_official = fetch_dicts(
        duckdb.connect(str(OUTPUT_DB), read_only=True),
        """
        SELECT
            official_overall_rank,
            resolved_school_id,
            athlete_school_unit_count,
            raw_school_score,
            posterior_school_score,
            posterior_ci95_lower,
            posterior_ci95_upper,
            reliability_tier
        FROM overall_school_rankings
        WHERE official_rank_eligible
        ORDER BY official_overall_rank
        LIMIT 10
        """
    )

    report = [
        "MILESTONE 5 PHASE 5G — UNCERTAINTY-ADJUSTED SCHOOL RANKINGS",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "RANKING POLICY",
        "-" * 78,
        "Each athlete-school unit receives one equal vote.",
        "School means are adjusted with empirical-Bayes shrinkage.",
        f"Official overall minimum sample: {OVERALL_MIN_SAMPLE}",
        f"Official gender minimum sample: {GENDER_MIN_SAMPLE}",
        f"Official event-family minimum sample: {EVENT_FAMILY_MIN_SAMPLE}",
        "All schools remain visible even when insufficient for official rank.",
        "",
        "RESULTS",
        "-" * 78,
        f"Athlete-school units: "
        f"{int(counts['athlete_school_rows']):,}",
        f"Schools represented: "
        f"{int(counts['overall_school_rows']):,}",
        f"Officially ranked overall schools: "
        f"{int(counts['official_overall_school_count']):,}",
        f"Insufficient-data overall schools: "
        f"{int(counts['insufficient_overall_school_count']):,}",
        f"Between-school variance: "
        f"{float(overall_hyper['between_school_variance']):.6f}",
        f"Posterior/raw rank correlation: "
        f"{float(sensitivity['posterior_raw_rank_correlation']):.6f}",
        f"Mean absolute rank change from raw: "
        f"{float(sensitivity['mean_abs_rank_change_from_raw']):.3f}",
        "",
        "TOP TEN OFFICIAL OVERALL",
        "-" * 78,
    ]

    for row in top_official:
        report.append(
            f"{int(row['official_overall_rank']):>2}. "
            f"{row['resolved_school_id']} | "
            f"n={int(row['athlete_school_unit_count']):,} | "
            f"raw={float(row['raw_school_score']):.4f} | "
            f"posterior={float(row['posterior_school_score']):.4f} | "
            f"95% CI=[{float(row['posterior_ci95_lower']):.4f}, "
            f"{float(row['posterior_ci95_upper']):.4f}]"
        )

    report.extend(
        [
            "",
            "PHASE GATE",
            "-" * 78,
            (
                "PASS — Uncertainty-adjusted ranking candidates created."
                if not failed
                else "FAIL — Do not publish school rankings."
            ),
            "",
            "NEXT",
            "-" * 78,
            "Run final sensitivity, extreme-school, and coverage review.",
            "Then freeze ranking version 1 and complete documentation.",
        ]
    )

    (OUTPUT_DIR / "phase_5g_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Athlete-school units: "
        f"{int(counts['athlete_school_rows']):,}"
    )
    print(
        f"Schools represented: "
        f"{int(counts['overall_school_rows']):,}"
    )
    print(
        f"Official overall rankings: "
        f"{int(counts['official_overall_school_count']):,}"
    )
    print(
        f"Insufficient-data schools: "
        f"{int(counts['insufficient_overall_school_count']):,}"
    )
    print(
        f"Posterior/raw rank correlation: "
        f"{float(sensitivity['posterior_raw_rank_correlation']):.6f}"
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
    print("Next: final ranking sensitivity and publication audit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
