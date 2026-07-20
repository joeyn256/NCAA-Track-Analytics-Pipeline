#!/usr/bin/env python3
"""
Milestone 5 Phase 5H — Final Ranking Sensitivity and Publication Audit

Audits the Phase 5G uncertainty-adjusted school rankings under reasonable
alternative assumptions before the ranking is frozen for publication.

Sensitivity variants
--------------------
- primary_df20: official Phase 5G policy
- primary_df10: weaker within-school variance stabilization
- primary_df50: stronger within-school variance stabilization
- winsorized_df20: robust athlete-school values
- family_median_df20: median-within-family athlete values
- exclude_best_df20: remove each school's highest athlete contribution
- exclude_worst_df20: remove each school's lowest athlete contribution

The audit also evaluates:
- official minimum-sample thresholds of 20, 30, and 50 athletes;
- top-10 and top-25 overlap;
- rank and score correlations;
- roster-size and event-family-coverage relationships;
- evidence-category counts;
- schools most dependent on one exceptional or poor athlete;
- insufficient-data schools and extreme official rankings.

This phase does not rename school identifiers or update documentation. A final
publication-freeze phase follows only after this audit passes.
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
      "phase_5g_uncertainty_adjusted_school_rankings/"
      "school_development_rankings_v1.duckdb"
)

PHASE_5G_CHECKS = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5g_uncertainty_adjusted_school_rankings/"
      "hard_checks.csv"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5h_final_ranking_publication_audit"
)

OUTPUT_DB = OUTPUT_DIR / "ranking_publication_audit_v1.duckdb"

INPUT_DATASET_VERSION = "school_development_rankings_v1"
INPUT_POLICY_VERSION = "empirical_bayes_school_rankings_v1"
DATASET_VERSION = "ranking_publication_audit_v1_1"
AUDIT_POLICY_VERSION = "ranking_publication_audit_policy_v1_1"

EXPECTED_ATHLETE_SCHOOL_ROWS = 80_077
EXPECTED_SCHOOLS = 361
EXPECTED_OFFICIAL_SCHOOLS = 353
EXPECTED_VARIANTS = 7

PRIMARY_VARIANT = "primary_df20"
PRIMARY_MIN_SAMPLE = 30
CI_Z = 1.96

FORMULA_TOLERANCE = 1e-10

# Publication stability floors. These are deliberately broad enough to test
# reasonableness rather than force near-identical rankings.
MIN_VARIANT_RANK_CORRELATION = 0.90
MIN_TOP10_OVERLAP_SHARE = 0.50
MIN_TOP25_OVERLAP_SHARE = 0.60
MAX_MEDIAN_ABS_RANK_CHANGE = 25.0


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

    print("MILESTONE 5 PHASE 5H — FINAL RANKING PUBLICATION AUDIT")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Input database: {INPUT_DB}")
    print(f"Output database: {OUTPUT_DB}")

    required_inputs = [INPUT_DB, PHASE_5G_CHECKS]
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
        print("PHASE GATE: FAIL — Required Phase 5G input missing.")
        return 1

    phase_5g_checks = read_csv(PHASE_5G_CHECKS)
    failed_phase_5g_checks = [
        row for row in phase_5g_checks
        if row.get("status") != "PASS"
    ]

    add_check(
        checks,
        "phase_5g_gate_passed",
        not failed_phase_5g_checks,
        [row.get("check_name") for row in failed_phase_5g_checks],
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
                AS ranking_source (READ_ONLY)
            """
        )

        metadata = {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM ranking_source.main.dataset_metadata
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
            "input_ranking_policy_matches",
            metadata.get("ranking_policy_version")
            == INPUT_POLICY_VERSION,
            metadata.get("ranking_policy_version"),
            INPUT_POLICY_VERSION,
        )

        con.execute(
            """
            CREATE TABLE athlete_school_snapshot AS
            SELECT *
            FROM ranking_source.main.athlete_school_snapshot
            """
        )

        con.execute(
            """
            CREATE TABLE overall_ranking_snapshot AS
            SELECT *
            FROM ranking_source.main.overall_school_rankings
            """
        )

        con.execute(
            """
            CREATE TABLE gender_ranking_snapshot AS
            SELECT *
            FROM ranking_source.main.gender_school_rankings
            """
        )

        con.execute(
            """
            CREATE TABLE event_family_ranking_snapshot AS
            SELECT *
            FROM ranking_source.main.event_family_school_rankings
            """
        )

        con.execute(
            """
            CREATE TABLE school_score_component_snapshot AS
            SELECT *
            FROM ranking_source.main.school_score_components
            """
        )

        con.execute(
            """
            CREATE TABLE sensitivity_variant_config (
                variant_name VARCHAR,
                score_field VARCHAR,
                variance_prior_df DOUBLE,
                row_policy VARCHAR,
                variant_description VARCHAR
            )
            """
        )

        con.executemany(
            """
            INSERT INTO sensitivity_variant_config
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    "primary_df20",
                    "primary_athlete_value_added",
                    20.0,
                    "all_rows",
                    "Official Phase 5G primary policy.",
                ),
                (
                    "primary_df10",
                    "primary_athlete_value_added",
                    10.0,
                    "all_rows",
                    "Weaker within-school variance stabilization.",
                ),
                (
                    "primary_df50",
                    "primary_athlete_value_added",
                    50.0,
                    "all_rows",
                    "Stronger within-school variance stabilization.",
                ),
                (
                    "winsorized_df20",
                    "winsorized_athlete_value_added",
                    20.0,
                    "all_rows",
                    "Robust athlete values using event-family tail caps.",
                ),
                (
                    "family_median_df20",
                    "family_median_athlete_value_added",
                    20.0,
                    "all_rows",
                    "Median-within-family athlete sensitivity score.",
                ),
                (
                    "exclude_best_df20",
                    "primary_athlete_value_added",
                    20.0,
                    "exclude_school_best",
                    "Removes each school's highest athlete contribution.",
                ),
                (
                    "exclude_worst_df20",
                    "primary_athlete_value_added",
                    20.0,
                    "exclude_school_worst",
                    "Removes each school's lowest athlete contribution.",
                ),
            ],
        )

        con.execute(
            """
            CREATE TABLE ranked_athlete_school_rows AS
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY resolved_school_id
                    ORDER BY
                        primary_athlete_value_added DESC,
                        athlete_school_contribution_id
                ) AS descending_school_value_rank,
                ROW_NUMBER() OVER (
                    PARTITION BY resolved_school_id
                    ORDER BY
                        primary_athlete_value_added ASC,
                        athlete_school_contribution_id
                ) AS ascending_school_value_rank,
                COUNT(*) OVER (
                    PARTITION BY resolved_school_id
                ) AS school_athlete_count
            FROM athlete_school_snapshot
            """
        )

        con.execute(
            """
            CREATE TABLE variant_athlete_rows AS
            SELECT
                'primary_df20' AS variant_name,
                resolved_school_id,
                canonical_person_id,
                athlete_school_contribution_id,
                primary_athlete_value_added AS score_value
            FROM ranked_athlete_school_rows

            UNION ALL

            SELECT
                'primary_df10',
                resolved_school_id,
                canonical_person_id,
                athlete_school_contribution_id,
                primary_athlete_value_added
            FROM ranked_athlete_school_rows

            UNION ALL

            SELECT
                'primary_df50',
                resolved_school_id,
                canonical_person_id,
                athlete_school_contribution_id,
                primary_athlete_value_added
            FROM ranked_athlete_school_rows

            UNION ALL

            SELECT
                'winsorized_df20',
                resolved_school_id,
                canonical_person_id,
                athlete_school_contribution_id,
                winsorized_athlete_value_added
            FROM ranked_athlete_school_rows

            UNION ALL

            SELECT
                'family_median_df20',
                resolved_school_id,
                canonical_person_id,
                athlete_school_contribution_id,
                family_median_athlete_value_added
            FROM ranked_athlete_school_rows

            UNION ALL

            SELECT
                'exclude_best_df20',
                resolved_school_id,
                canonical_person_id,
                athlete_school_contribution_id,
                primary_athlete_value_added
            FROM ranked_athlete_school_rows
            WHERE descending_school_value_rank > 1
               OR school_athlete_count = 1

            UNION ALL

            SELECT
                'exclude_worst_df20',
                resolved_school_id,
                canonical_person_id,
                athlete_school_contribution_id,
                primary_athlete_value_added
            FROM ranked_athlete_school_rows
            WHERE ascending_school_value_rank > 1
               OR school_athlete_count = 1
            """
        )

        con.execute(
            """
            CREATE TABLE variant_school_base AS
            SELECT
                v.variant_name,
                c.variance_prior_df,
                c.row_policy,
                c.variant_description,
                v.resolved_school_id,
                COUNT(*) AS athlete_school_unit_count,
                AVG(v.score_value) AS raw_school_score,
                MEDIAN(v.score_value) AS median_school_score,
                VAR_SAMP(v.score_value) AS raw_within_school_variance,
                STDDEV_SAMP(v.score_value) AS raw_within_school_sd,
                AVG(CAST(v.score_value > 0 AS DOUBLE))
                    AS above_expected_athlete_share
            FROM variant_athlete_rows v
            JOIN sensitivity_variant_config c
              USING (variant_name)
            GROUP BY
                v.variant_name,
                c.variance_prior_df,
                c.row_policy,
                c.variant_description,
                v.resolved_school_id
            """
        )

        con.execute(
            """
            CREATE TABLE variant_global_prior AS
            WITH global_stats AS (
                SELECT
                    variant_name,
                    AVG(score_value) AS global_athlete_mean,
                    VAR_SAMP(score_value) AS global_athlete_variance,
                    COUNT(*) AS total_athlete_rows
                FROM variant_athlete_rows
                GROUP BY variant_name
            ),
            pooled AS (
                SELECT
                    variant_name,
                    SUM(
                        (athlete_school_unit_count - 1)
                        * COALESCE(raw_within_school_variance, 0)
                    )
                    / NULLIF(
                        SUM(athlete_school_unit_count - 1),
                        0
                    ) AS pooled_within_school_variance
                FROM variant_school_base
                GROUP BY variant_name
            )
            SELECT *
            FROM global_stats
            JOIN pooled
              USING (variant_name)
            """
        )

        con.execute(
            """
            CREATE TABLE variant_school_stabilized AS
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
                            p.pooled_within_school_variance,
                            p.global_athlete_variance
                        )
                    )
                    + b.variance_prior_df
                        * COALESCE(
                            p.pooled_within_school_variance,
                            p.global_athlete_variance
                        )
                )
                / (
                    b.athlete_school_unit_count - 1
                    + b.variance_prior_df
                ) AS stabilized_within_school_variance,
                (
                    (
                        (
                            (b.athlete_school_unit_count - 1)
                            * COALESCE(
                                b.raw_within_school_variance,
                                p.pooled_within_school_variance,
                                p.global_athlete_variance
                            )
                        )
                        + b.variance_prior_df
                            * COALESCE(
                                p.pooled_within_school_variance,
                                p.global_athlete_variance
                            )
                    )
                    / (
                        b.athlete_school_unit_count - 1
                        + b.variance_prior_df
                    )
                )
                / b.athlete_school_unit_count
                    AS stabilized_sampling_variance
            FROM variant_school_base b
            JOIN variant_global_prior p
              USING (variant_name)
            """
        )

        con.execute(
            """
            CREATE TABLE variant_between_school_variance AS
            SELECT
                variant_name,
                VAR_SAMP(raw_school_score)
                    AS observed_school_mean_variance,
                AVG(stabilized_sampling_variance)
                    AS mean_sampling_variance,
                GREATEST(
                    0.0,
                    VAR_SAMP(raw_school_score)
                    - AVG(stabilized_sampling_variance)
                ) AS between_school_variance,
                COUNT(*) AS school_count
            FROM variant_school_stabilized
            GROUP BY variant_name
            """
        )

        con.execute(
            f"""
            CREATE TABLE variant_school_posteriors AS
            SELECT
                s.*,
                t.observed_school_mean_variance,
                t.mean_sampling_variance,
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
                END AS posterior_standard_error
            FROM variant_school_stabilized s
            JOIN variant_between_school_variance t
              USING (variant_name)
            """
        )

        con.execute(
            f"""
            CREATE TABLE variant_school_rankings AS
            SELECT
                *,
                posterior_school_score
                    - {CI_Z} * posterior_standard_error
                    AS posterior_ci95_lower,
                posterior_school_score
                    + {CI_Z} * posterior_standard_error
                    AS posterior_ci95_upper,
                RANK() OVER (
                    PARTITION BY variant_name
                    ORDER BY posterior_school_score DESC
                ) AS all_school_variant_rank
            FROM variant_school_posteriors
            """
        )

        # Re-rank every variant using only schools eligible under the official
        # Phase 5G n>=30 publication population.
        con.execute(
            """
            CREATE TABLE official_population_variant_ranks AS
            SELECT
                v.*,
                b.official_overall_rank AS primary_official_rank,
                b.posterior_school_score
                    AS primary_posterior_school_score,
                b.raw_school_score AS primary_raw_school_score,
                RANK() OVER (
                    PARTITION BY v.variant_name
                    ORDER BY v.posterior_school_score DESC
                ) AS official_population_variant_rank
            FROM variant_school_rankings v
            JOIN overall_ranking_snapshot b
              USING (resolved_school_id)
            WHERE b.official_rank_eligible
            """
        )

        con.execute(
            f"""
            CREATE TABLE sensitivity_variant_metrics AS
            WITH comparisons AS (
                SELECT
                    variant_name,
                    COUNT(*) AS school_count,
                    CORR(
                        primary_posterior_school_score,
                        posterior_school_score
                    ) AS score_correlation,
                    CORR(
                        primary_official_rank,
                        official_population_variant_rank
                    ) AS rank_correlation,
                    AVG(ABS(
                        primary_official_rank
                        - official_population_variant_rank
                    )) AS mean_abs_rank_change,
                    MEDIAN(ABS(
                        primary_official_rank
                        - official_population_variant_rank
                    )) AS median_abs_rank_change,
                    MAX(ABS(
                        primary_official_rank
                        - official_population_variant_rank
                    )) AS max_abs_rank_change,
                    COUNT(*) FILTER (
                        WHERE primary_official_rank <= 10
                          AND official_population_variant_rank <= 10
                    ) AS top10_overlap,
                    COUNT(*) FILTER (
                        WHERE primary_official_rank <= 25
                          AND official_population_variant_rank <= 25
                    ) AS top25_overlap,
                    AVG(shrinkage_weight)
                        AS mean_shrinkage_weight,
                    MIN(shrinkage_weight)
                        AS minimum_shrinkage_weight,
                    MAX(shrinkage_weight)
                        AS maximum_shrinkage_weight
                FROM official_population_variant_ranks
                GROUP BY variant_name
            )
            SELECT
                c.*,
                m.variance_prior_df,
                m.row_policy,
                m.variant_description,
                c.top10_overlap / 10.0
                    AS top10_overlap_share,
                c.top25_overlap / 25.0
                    AS top25_overlap_share,
                c.rank_correlation
                    >= {MIN_VARIANT_RANK_CORRELATION}
                    AS rank_correlation_pass,
                c.top10_overlap / 10.0
                    >= {MIN_TOP10_OVERLAP_SHARE}
                    AS top10_overlap_pass,
                c.top25_overlap / 25.0
                    >= {MIN_TOP25_OVERLAP_SHARE}
                    AS top25_overlap_pass,
                c.median_abs_rank_change
                    <= {MAX_MEDIAN_ABS_RANK_CHANGE}
                    AS median_rank_change_pass
            FROM comparisons c
            JOIN sensitivity_variant_config m
              USING (variant_name)
            ORDER BY variant_name
            """
        )

        con.execute(
            """
            CREATE TABLE sample_threshold_sensitivity AS
            WITH thresholds(minimum_sample) AS (
                VALUES (20), (30), (50)
            ),
            ranked AS (
                SELECT
                    t.minimum_sample,
                    r.resolved_school_id,
                    r.athlete_school_unit_count,
                    r.posterior_school_score,
                    r.official_overall_rank AS primary_official_rank,
                    RANK() OVER (
                        PARTITION BY t.minimum_sample
                        ORDER BY r.posterior_school_score DESC
                    ) AS threshold_rank
                FROM overall_ranking_snapshot r
                CROSS JOIN thresholds t
                WHERE r.athlete_school_unit_count >= t.minimum_sample
            )
            SELECT
                minimum_sample,
                COUNT(*) AS eligible_school_count,
                COUNT(*) FILTER (
                    WHERE primary_official_rank <= 10
                      AND threshold_rank <= 10
                ) AS current_top10_overlap,
                COUNT(*) FILTER (
                    WHERE primary_official_rank <= 25
                      AND threshold_rank <= 25
                ) AS current_top25_overlap,
                CORR(primary_official_rank, threshold_rank)
                    AS current_rank_correlation,
                AVG(ABS(
                    primary_official_rank - threshold_rank
                )) AS mean_abs_rank_change_from_current
            FROM ranked
            GROUP BY minimum_sample
            ORDER BY minimum_sample
            """
        )

        con.execute(
            """
            CREATE TABLE school_bias_diagnostics AS
            SELECT
                CORR(
                    posterior_school_score,
                    athlete_school_unit_count
                ) AS score_sample_size_correlation,
                CORR(
                    posterior_school_score,
                    represented_event_families
                ) AS score_event_family_coverage_correlation,
                CORR(
                    posterior_school_score,
                    represented_gender_family_groups
                ) AS score_gender_family_coverage_correlation,
                CORR(
                    posterior_school_score,
                    mean_event_families_per_athlete
                ) AS score_athlete_breadth_correlation,
                CORR(
                    posterior_school_score,
                    male_athlete_unit_count::DOUBLE
                    / NULLIF(athlete_school_unit_count, 0)
                ) AS score_male_share_correlation,
                CORR(
                    posterior_school_score,
                    above_expected_athlete_share
                ) AS score_positive_share_correlation,
                CORR(
                    posterior_school_score,
                    minimum_training_support
                ) AS score_training_support_correlation
            FROM school_score_component_snapshot
            """
        )

        con.execute(
            """
            CREATE TABLE school_influence_review AS
            WITH pivoted AS (
                SELECT
                    resolved_school_id,
                    MAX(CASE
                        WHEN variant_name = 'primary_df20'
                        THEN posterior_school_score
                    END) AS primary_posterior_score,
                    MAX(CASE
                        WHEN variant_name = 'exclude_best_df20'
                        THEN posterior_school_score
                    END) AS exclude_best_posterior_score,
                    MAX(CASE
                        WHEN variant_name = 'exclude_worst_df20'
                        THEN posterior_school_score
                    END) AS exclude_worst_posterior_score,
                    MAX(CASE
                        WHEN variant_name = 'primary_df20'
                        THEN all_school_variant_rank
                    END) AS primary_all_school_rank,
                    MAX(CASE
                        WHEN variant_name = 'exclude_best_df20'
                        THEN all_school_variant_rank
                    END) AS exclude_best_all_school_rank,
                    MAX(CASE
                        WHEN variant_name = 'exclude_worst_df20'
                        THEN all_school_variant_rank
                    END) AS exclude_worst_all_school_rank
                FROM variant_school_rankings
                GROUP BY resolved_school_id
            ),
            athlete_extremes AS (
                SELECT
                    resolved_school_id,
                    COUNT(*) AS athlete_school_unit_count,
                    MAX(primary_athlete_value_added)
                        AS best_athlete_value_added,
                    MIN(primary_athlete_value_added)
                        AS worst_athlete_value_added,
                    APPROX_QUANTILE(
                        primary_athlete_value_added,
                        0.90
                    ) AS athlete_value_added_q90,
                    APPROX_QUANTILE(
                        primary_athlete_value_added,
                        0.10
                    ) AS athlete_value_added_q10,
                    AVG(primary_athlete_value_added)
                        AS raw_athlete_mean,
                    AVG(primary_athlete_value_added)
                        FILTER (
                            WHERE descending_school_value_rank > 1
                        ) AS raw_mean_excluding_best,
                    AVG(primary_athlete_value_added)
                        FILTER (
                            WHERE ascending_school_value_rank > 1
                        ) AS raw_mean_excluding_worst
                FROM ranked_athlete_school_rows
                GROUP BY resolved_school_id
            )
            SELECT
                p.*,
                e.* EXCLUDE (resolved_school_id),
                p.primary_posterior_score
                    - p.exclude_best_posterior_score
                    AS best_athlete_posterior_effect,
                p.exclude_worst_posterior_score
                    - p.primary_posterior_score
                    AS worst_athlete_posterior_effect,
                ABS(
                    p.primary_all_school_rank
                    - p.exclude_best_all_school_rank
                ) AS rank_change_excluding_best,
                ABS(
                    p.primary_all_school_rank
                    - p.exclude_worst_all_school_rank
                ) AS rank_change_excluding_worst
            FROM pivoted p
            JOIN athlete_extremes e
              USING (resolved_school_id)
            """
        )

        con.execute(
            """
            CREATE TABLE evidence_category_summary AS
            SELECT
                official_rank_eligible,
                reliability_tier,
                evidence_category,
                ranking_band,
                COUNT(*) AS school_count,
                MIN(athlete_school_unit_count)
                    AS minimum_athlete_count,
                MAX(athlete_school_unit_count)
                    AS maximum_athlete_count,
                AVG(posterior_school_score)
                    AS mean_posterior_score,
                AVG(posterior_standard_error)
                    AS mean_posterior_standard_error
            FROM overall_ranking_snapshot
            GROUP BY
                official_rank_eligible,
                reliability_tier,
                evidence_category,
                ranking_band
            ORDER BY
                official_rank_eligible DESC,
                reliability_tier,
                evidence_category,
                ranking_band
            """
        )

        con.execute(
            """
            CREATE TABLE extreme_school_review AS
            SELECT
                CASE
                    WHEN official_rank_eligible
                     AND official_overall_rank <= 25
                        THEN 'top_25_official'
                    WHEN official_rank_eligible
                     AND official_overall_rank
                        > official_ranked_school_count - 25
                        THEN 'bottom_25_official'
                    WHEN NOT official_rank_eligible
                        THEN 'insufficient_data'
                    WHEN absolute_rank_change_from_raw >= 20
                        THEN 'large_shrinkage_rank_change'
                    ELSE 'other_review'
                END AS review_category,
                *
            FROM overall_ranking_snapshot
            WHERE (
                    official_rank_eligible
                    AND (
                        official_overall_rank <= 25
                        OR official_overall_rank
                            > official_ranked_school_count - 25
                    )
                  )
               OR NOT official_rank_eligible
               OR absolute_rank_change_from_raw >= 20
            """
        )

        con.execute(
            """
            CREATE TABLE publication_readiness_summary AS
            SELECT
                (
                    SELECT COUNT(*)
                    FROM sensitivity_variant_metrics
                ) AS variant_count,
                (
                    SELECT MIN(rank_correlation)
                    FROM sensitivity_variant_metrics
                    WHERE variant_name <> 'primary_df20'
                ) AS minimum_alternative_rank_correlation,
                (
                    SELECT MIN(top10_overlap_share)
                    FROM sensitivity_variant_metrics
                    WHERE variant_name <> 'primary_df20'
                ) AS minimum_top10_overlap_share,
                (
                    SELECT MIN(top25_overlap_share)
                    FROM sensitivity_variant_metrics
                    WHERE variant_name <> 'primary_df20'
                ) AS minimum_top25_overlap_share,
                (
                    SELECT MAX(median_abs_rank_change)
                    FROM sensitivity_variant_metrics
                    WHERE variant_name <> 'primary_df20'
                ) AS maximum_median_abs_rank_change,
                (
                    SELECT COUNT(*)
                    FROM sensitivity_variant_metrics
                    WHERE NOT rank_correlation_pass
                       OR NOT top10_overlap_pass
                       OR NOT top25_overlap_pass
                       OR NOT median_rank_change_pass
                ) AS failed_variant_stability_rows,
                (
                    SELECT COUNT(*)
                    FROM overall_ranking_snapshot
                    WHERE official_rank_eligible
                ) AS official_school_count,
                (
                    SELECT COUNT(*)
                    FROM overall_ranking_snapshot
                    WHERE NOT official_rank_eligible
                ) AS insufficient_school_count,
                (
                    SELECT COUNT(*)
                    FROM overall_ranking_snapshot
                    WHERE evidence_category =
                        'credible_above_expected'
                ) AS credible_above_expected_school_count,
                (
                    SELECT COUNT(*)
                    FROM overall_ranking_snapshot
                    WHERE evidence_category =
                        'credible_below_expected'
                ) AS credible_below_expected_school_count,
                (
                    SELECT COUNT(*)
                    FROM overall_ranking_snapshot
                    WHERE evidence_category =
                        'not_distinguishable_from_expected'
                ) AS indistinguishable_school_count
            """
        )

        con.execute(
            f"""
            CREATE TABLE final_overall_rankings_candidate AS
            SELECT
                *,
                'publication_candidate_pending_name_enrichment'
                    AS publication_status,
                '{DATASET_VERSION}' AS audit_dataset_version,
                '{AUDIT_POLICY_VERSION}' AS audit_policy_version
            FROM overall_ranking_snapshot
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
                'audit_policy_version',
                '{AUDIT_POLICY_VERSION}'
            UNION ALL
            SELECT
                'input_ranking_dataset_version',
                '{INPUT_DATASET_VERSION}'
            UNION ALL
            SELECT
                'sensitivity_variant_count',
                '{EXPECTED_VARIANTS}'
            UNION ALL
            SELECT
                'publication_status',
                'candidate_pending_school_name_enrichment_and_docs'
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
                (SELECT COUNT(*) FROM athlete_school_snapshot)
                    AS athlete_school_rows,
                (SELECT COUNT(*) FROM overall_ranking_snapshot)
                    AS school_rows,
                (SELECT COUNT(*)
                 FROM overall_ranking_snapshot
                 WHERE official_rank_eligible)
                    AS official_school_rows,
                (SELECT COUNT(DISTINCT variant_name)
                 FROM sensitivity_variant_config)
                    AS variant_count,
                (SELECT COUNT(*)
                 FROM sensitivity_variant_metrics)
                    AS variant_metric_rows,
                (SELECT COUNT(*)
                 FROM official_population_variant_ranks
                 WHERE variant_name = 'primary_df20')
                    AS primary_official_comparison_rows,
                (SELECT COUNT(*)
                 FROM final_overall_rankings_candidate)
                    AS final_candidate_rows
            """
        )[0]

        quality = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM variant_school_rankings
                 WHERE posterior_school_score IS NULL
                    OR posterior_standard_error IS NULL
                    OR shrinkage_weight < 0
                    OR shrinkage_weight > 1
                    OR posterior_ci95_lower > posterior_ci95_upper)
                    AS invalid_variant_rows,
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        variant_name,
                        resolved_school_id,
                        COUNT(*) AS row_count
                    FROM variant_school_rankings
                    GROUP BY
                        variant_name,
                        resolved_school_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_variant_school_rows,
                (SELECT COUNT(*)
                 FROM sensitivity_variant_metrics
                 WHERE school_count <> {EXPECTED_OFFICIAL_SCHOOLS})
                    AS incomplete_variant_comparison_rows,
                (SELECT COUNT(*)
                 FROM overall_ranking_snapshot p
                 JOIN variant_school_rankings v
                   ON v.resolved_school_id = p.resolved_school_id
                  AND v.variant_name = 'primary_df20'
                 WHERE ABS(
                    p.posterior_school_score
                    - v.posterior_school_score
                 ) > {FORMULA_TOLERANCE})
                    AS primary_score_reproduction_mismatches,
                (SELECT COUNT(*)
                 FROM overall_ranking_snapshot p
                 JOIN variant_school_rankings v
                   ON v.resolved_school_id = p.resolved_school_id
                  AND v.variant_name = 'primary_df20'
                 WHERE p.all_school_posterior_rank
                    <> v.all_school_variant_rank)
                    AS primary_rank_reproduction_mismatches,
                (SELECT failed_variant_stability_rows
                 FROM publication_readiness_summary)
                    AS failed_variant_stability_rows,
                (SELECT COUNT(*)
                 FROM school_influence_review
                 WHERE primary_posterior_score IS NULL
                    OR exclude_best_posterior_score IS NULL
                    OR exclude_worst_posterior_score IS NULL)
                    AS null_school_influence_rows
            """
        )[0]

        readiness = fetch_dicts(
            con,
            """
            SELECT *
            FROM publication_readiness_summary
            """
        )[0]

        bias = fetch_dicts(
            con,
            """
            SELECT *
            FROM school_bias_diagnostics
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
            "school_row_count",
            counts["school_rows"] == EXPECTED_SCHOOLS,
            counts["school_rows"],
            EXPECTED_SCHOOLS,
        )
        add_check(
            checks,
            "official_school_count",
            counts["official_school_rows"]
            == EXPECTED_OFFICIAL_SCHOOLS,
            counts["official_school_rows"],
            EXPECTED_OFFICIAL_SCHOOLS,
        )
        add_check(
            checks,
            "sensitivity_variant_count",
            counts["variant_count"] == EXPECTED_VARIANTS,
            counts["variant_count"],
            EXPECTED_VARIANTS,
        )
        add_check(
            checks,
            "variant_metric_row_count",
            counts["variant_metric_rows"] == EXPECTED_VARIANTS,
            counts["variant_metric_rows"],
            EXPECTED_VARIANTS,
        )
        add_check(
            checks,
            "primary_official_comparison_complete",
            counts["primary_official_comparison_rows"]
            == EXPECTED_OFFICIAL_SCHOOLS,
            counts["primary_official_comparison_rows"],
            EXPECTED_OFFICIAL_SCHOOLS,
        )
        add_check(
            checks,
            "final_candidate_school_count",
            counts["final_candidate_rows"] == EXPECTED_SCHOOLS,
            counts["final_candidate_rows"],
            EXPECTED_SCHOOLS,
        )
        add_check(
            checks,
            "all_variant_rows_valid",
            quality["invalid_variant_rows"] == 0,
            quality["invalid_variant_rows"],
            0,
        )
        add_check(
            checks,
            "variant_school_grain_unique",
            quality["duplicate_variant_school_rows"] == 0,
            quality["duplicate_variant_school_rows"],
            0,
        )
        add_check(
            checks,
            "all_variant_comparisons_complete",
            quality["incomplete_variant_comparison_rows"] == 0,
            quality["incomplete_variant_comparison_rows"],
            0,
        )
        add_check(
            checks,
            "primary_posterior_scores_reproduce_phase_5g",
            quality["primary_score_reproduction_mismatches"] == 0,
            quality["primary_score_reproduction_mismatches"],
            0,
        )
        add_check(
            checks,
            "primary_ranks_reproduce_phase_5g",
            quality["primary_rank_reproduction_mismatches"] == 0,
            quality["primary_rank_reproduction_mismatches"],
            0,
        )
        add_check(
            checks,
            "alternative_rankings_meet_stability_floors",
            quality["failed_variant_stability_rows"] == 0,
            quality["failed_variant_stability_rows"],
            0,
            (
                f"Floors: rank correlation >= "
                f"{MIN_VARIANT_RANK_CORRELATION}, "
                f"top-10 overlap >= {MIN_TOP10_OVERLAP_SHARE:.0%}, "
                f"top-25 overlap >= {MIN_TOP25_OVERLAP_SHARE:.0%}, "
                f"median rank movement <= "
                f"{MAX_MEDIAN_ABS_RANK_CHANGE}."
            ),
        )
        add_check(
            checks,
            "school_influence_rows_complete",
            quality["null_school_influence_rows"] == 0,
            quality["null_school_influence_rows"],
            0,
        )
        add_check(
            checks,
            "official_and_insufficient_populations_preserved",
            readiness["official_school_count"]
            + readiness["insufficient_school_count"]
            == EXPECTED_SCHOOLS,
            readiness["official_school_count"]
            + readiness["insufficient_school_count"],
            EXPECTED_SCHOOLS,
        )
        add_check(
            checks,
            "evidence_categories_cover_all_schools",
            readiness["credible_above_expected_school_count"]
            + readiness["credible_below_expected_school_count"]
            + readiness["indistinguishable_school_count"]
            == EXPECTED_SCHOOLS,
            readiness["credible_above_expected_school_count"]
            + readiness["credible_below_expected_school_count"]
            + readiness["indistinguishable_school_count"],
            EXPECTED_SCHOOLS,
        )

        variant_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM sensitivity_variant_metrics
            ORDER BY variant_name
            """
        )
        write_csv(
            OUTPUT_DIR / "sensitivity_variant_metrics.csv",
            variant_rows,
            list(variant_rows[0].keys()) if variant_rows else [],
        )

        threshold_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM sample_threshold_sensitivity
            ORDER BY minimum_sample
            """
        )
        write_csv(
            OUTPUT_DIR / "sample_threshold_sensitivity.csv",
            threshold_rows,
            list(threshold_rows[0].keys()) if threshold_rows else [],
        )

        bias_rows = [
            {"metric": key, "value": value}
            for key, value in bias.items()
        ]
        write_csv(
            OUTPUT_DIR / "school_bias_diagnostics.csv",
            bias_rows,
            ["metric", "value"],
        )

        influence_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM school_influence_review
            ORDER BY
                rank_change_excluding_best DESC,
                best_athlete_posterior_effect DESC,
                resolved_school_id
            """
        )
        write_csv(
            OUTPUT_DIR / "school_influence_review.csv",
            influence_rows,
            list(influence_rows[0].keys()) if influence_rows else [],
        )

        evidence_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM evidence_category_summary
            ORDER BY
                official_rank_eligible DESC,
                reliability_tier,
                evidence_category,
                ranking_band
            """
        )
        write_csv(
            OUTPUT_DIR / "evidence_category_summary.csv",
            evidence_rows,
            list(evidence_rows[0].keys()) if evidence_rows else [],
        )

        extreme_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM extreme_school_review
            ORDER BY
                review_category,
                official_overall_rank NULLS LAST,
                all_school_posterior_rank,
                resolved_school_id
            """
        )
        write_csv(
            OUTPUT_DIR / "extreme_school_review.csv",
            extreme_rows,
            list(extreme_rows[0].keys()) if extreme_rows else [],
        )

        final_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM final_overall_rankings_candidate
            ORDER BY
                official_rank_eligible DESC,
                official_overall_rank NULLS LAST,
                all_school_posterior_rank,
                resolved_school_id
            """
        )
        write_csv(
            OUTPUT_DIR / "final_overall_rankings_candidate.csv",
            final_rows,
            list(final_rows[0].keys()) if final_rows else [],
        )

        readiness_rows = [
            {"metric": key, "value": value}
            for key, value in readiness.items()
        ]
        write_csv(
            OUTPUT_DIR / "publication_readiness_summary.csv",
            readiness_rows,
            ["metric", "value"],
        )

        manual_review_rows = fetch_dicts(
            con,
            """
            WITH combined AS (
                SELECT
                    resolved_school_id,
                    'largest_best_athlete_effect'
                        AS review_reason,
                    best_athlete_posterior_effect
                        AS review_value,
                    rank_change_excluding_best
                        AS associated_rank_change
                FROM school_influence_review
                QUALIFY ROW_NUMBER() OVER (
                    ORDER BY best_athlete_posterior_effect DESC
                ) <= 25

                UNION ALL

                SELECT
                    resolved_school_id,
                    'largest_worst_athlete_effect',
                    worst_athlete_posterior_effect,
                    rank_change_excluding_worst
                FROM school_influence_review
                QUALIFY ROW_NUMBER() OVER (
                    ORDER BY worst_athlete_posterior_effect DESC
                ) <= 25

                UNION ALL

                SELECT
                    resolved_school_id,
                    'largest_rank_change_excluding_best',
                    rank_change_excluding_best,
                    rank_change_excluding_best
                FROM school_influence_review
                QUALIFY ROW_NUMBER() OVER (
                    ORDER BY rank_change_excluding_best DESC
                ) <= 25

                UNION ALL

                SELECT
                    resolved_school_id,
                    'insufficient_data_program',
                    posterior_school_score,
                    all_school_posterior_rank
                FROM overall_ranking_snapshot
                WHERE NOT official_rank_eligible
            )
            SELECT
                c.*,
                r.athlete_school_unit_count,
                r.raw_school_score,
                r.posterior_school_score,
                r.posterior_ci95_lower,
                r.posterior_ci95_upper,
                r.official_rank_eligible,
                r.official_overall_rank,
                r.all_school_posterior_rank,
                r.reliability_tier,
                r.evidence_category
            FROM combined c
            JOIN overall_ranking_snapshot r
              USING (resolved_school_id)
            ORDER BY
                review_reason,
                review_value DESC,
                resolved_school_id
            """
        )
        write_csv(
            OUTPUT_DIR / "manual_school_review_queue.csv",
            manual_review_rows,
            list(manual_review_rows[0].keys())
                if manual_review_rows else [],
        )

        summary_rows = [
            {
                "metric": "athlete_school_units",
                "value": counts["athlete_school_rows"],
            },
            {
                "metric": "schools",
                "value": counts["school_rows"],
            },
            {
                "metric": "official_schools",
                "value": counts["official_school_rows"],
            },
            {
                "metric": "sensitivity_variants",
                "value": counts["variant_count"],
            },
            {
                "metric": "minimum_alternative_rank_correlation",
                "value":
                    readiness[
                        "minimum_alternative_rank_correlation"
                    ],
            },
            {
                "metric": "minimum_top10_overlap_share",
                "value":
                    readiness["minimum_top10_overlap_share"],
            },
            {
                "metric": "minimum_top25_overlap_share",
                "value":
                    readiness["minimum_top25_overlap_share"],
            },
            {
                "metric": "maximum_median_abs_rank_change",
                "value":
                    readiness["maximum_median_abs_rank_change"],
            },
            {
                "metric": "failed_variant_stability_rows",
                "value":
                    readiness["failed_variant_stability_rows"],
            },
            {
                "metric": "score_sample_size_correlation",
                "value":
                    bias["score_sample_size_correlation"],
            },
            {
                "metric":
                    "score_event_family_coverage_correlation",
                "value":
                    bias[
                        "score_event_family_coverage_correlation"
                    ],
            },
            {
                "metric": "credible_above_expected_schools",
                "value":
                    readiness[
                        "credible_above_expected_school_count"
                    ],
            },
            {
                "metric": "credible_below_expected_schools",
                "value":
                    readiness[
                        "credible_below_expected_school_count"
                    ],
            },
            {
                "metric": "indistinguishable_schools",
                "value":
                    readiness["indistinguishable_school_count"],
            },
        ]
        write_csv(
            OUTPUT_DIR / "phase_5h_summary.csv",
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
                "audit_policy_version": AUDIT_POLICY_VERSION,
            }
        ],
        [
            "output_name",
            "path",
            "size_bytes",
            "sha256",
            "dataset_version",
            "audit_policy_version",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 5 PHASE 5H — FINAL RANKING PUBLICATION AUDIT",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "AUDIT SCOPE",
        "-" * 78,
        "Seven ranking variants were compared on the same 353-school",
        "official publication population.",
        "Variants test shrinkage strength, robust athlete values, median",
        "aggregation, and exclusion of each school's best or worst athlete.",
        "Minimum-sample thresholds of 20, 30, and 50 were also profiled.",
        "",
        "STABILITY RESULTS",
        "-" * 78,
        "Minimum alternative rank correlation: "
        f"{float(readiness['minimum_alternative_rank_correlation']):.6f}",
        "Minimum top-10 overlap: "
        f"{float(readiness['minimum_top10_overlap_share']):.1%}",
        "Minimum top-25 overlap: "
        f"{float(readiness['minimum_top25_overlap_share']):.1%}",
        "Maximum median absolute rank movement: "
        f"{float(readiness['maximum_median_abs_rank_change']):.3f}",
        "Failed variant stability rows: "
        f"{int(readiness['failed_variant_stability_rows']):,}",
        "",
        "BIAS DIAGNOSTICS",
        "-" * 78,
        "Posterior score/sample-size correlation: "
        f"{float(bias['score_sample_size_correlation']):.6f}",
        "Posterior score/event-family-coverage correlation: "
        f"{float(bias['score_event_family_coverage_correlation']):.6f}",
        "Posterior score/gender-family-coverage correlation: "
        f"{float(bias['score_gender_family_coverage_correlation']):.6f}",
        "Posterior score/male-share correlation: "
        f"{float(bias['score_male_share_correlation']):.6f}",
        "",
        "EVIDENCE CATEGORIES",
        "-" * 78,
        "Credible above expected: "
        f"{int(readiness['credible_above_expected_school_count']):,}",
        "Credible below expected: "
        f"{int(readiness['credible_below_expected_school_count']):,}",
        "Not distinguishable from expected: "
        f"{int(readiness['indistinguishable_school_count']):,}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Ranking publication sensitivity audit passed."
            if not failed
            else "FAIL — Do not freeze or publish ranking version 1."
        ),
        "",
        "NEXT",
        "-" * 78,
        "Enrich school identifiers with readable school metadata.",
        "Freeze the final publication database and CSV package.",
        "Update the Milestone 5 methodology document and README.",
        "Commit, push, and verify a clean milestone-5 branch.",
    ]

    (OUTPUT_DIR / "phase_5h_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Official schools audited: "
        f"{int(counts['official_school_rows']):,}"
    )
    print(
        f"Sensitivity variants: {int(counts['variant_count']):,}"
    )
    print(
        "Minimum alternative rank correlation: "
        f"{float(readiness['minimum_alternative_rank_correlation']):.6f}"
    )
    print(
        "Minimum top-10 overlap: "
        f"{float(readiness['minimum_top10_overlap_share']):.1%}"
    )
    print(
        "Minimum top-25 overlap: "
        f"{float(readiness['minimum_top25_overlap_share']):.1%}"
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
    print("Next: enrich metadata and freeze publication version 1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
