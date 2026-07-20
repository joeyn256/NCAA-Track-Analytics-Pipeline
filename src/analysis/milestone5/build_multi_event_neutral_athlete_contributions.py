#!/usr/bin/env python3
"""
Milestone 5 Phase 5F — Multi-Event-Neutral Athlete Contributions

Converts the frozen trajectory-level athlete value-added dataset into
event-family and athlete-school contribution units.

Primary aggregation policy
--------------------------
1. Every scored trajectory belongs to one athlete, school, gender, and
   event family.
2. Trajectories are weighted equally within an athlete-school event family.
3. Event families are weighted equally within an athlete-school unit.
4. Each athlete therefore contributes total weight 1.0 to each school,
   regardless of how many events or season types were observed.
5. A transfer athlete may contribute once to each distinct school.
6. Multiple analytical stints at the same school are consolidated into one
   athlete-school contribution.
7. Statistical tails remain included. Winsorized and median alternatives are
   retained only as sensitivity measures.

This phase creates preliminary unshrunk school summaries. It does not yet
freeze the official school ranking, apply empirical-Bayes shrinkage, or add
uncertainty-based ranking tiers.
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

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5f_multi_event_neutral_athlete_contributions"
)

OUTPUT_DB = OUTPUT_DIR / "athlete_contributions_v1.duckdb"

INPUT_DATASET_VERSION = "expected_improvement_policy_v1_1"
INPUT_POLICY_VERSION = "expected_improvement_policy_v1_1"
DATASET_VERSION = "athlete_contributions_v1"
AGGREGATION_POLICY_VERSION = "equal_family_equal_athlete_v1"

EXPECTED_TRAJECTORY_ROWS = 189_703
EXPECTED_SCHOOLS = 361

WINSOR_LOWER = 0.005
WINSOR_UPPER = 0.995
WEIGHT_TOLERANCE = 1e-10
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

    print("MILESTONE 5 PHASE 5F — MULTI-EVENT-NEUTRAL CONTRIBUTIONS")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Aggregation policy: {AGGREGATION_POLICY_VERSION}")
    print(f"Input database: {INPUT_DB}")
    print(f"Output database: {OUTPUT_DB}")

    required_inputs = [INPUT_DB, PHASE_5E_CHECKS]
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
        print("PHASE GATE: FAIL — Required Phase 5E input missing.")
        return 1

    phase_5e_checks = read_csv(PHASE_5E_CHECKS)
    failed_phase_5e_checks = [
        row
        for row in phase_5e_checks
        if row.get("status") != "PASS"
    ]

    add_check(
        checks,
        "phase_5e_gate_passed",
        not failed_phase_5e_checks,
        [
            row.get("check_name")
            for row in failed_phase_5e_checks
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
                AS value_source (READ_ONLY)
            """
        )

        metadata = {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM value_source.main.dataset_metadata
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
            metadata.get("expected_improvement_policy_version")
            == INPUT_POLICY_VERSION,
            metadata.get("expected_improvement_policy_version"),
            INPUT_POLICY_VERSION,
        )

        con.execute(
            f"""
            CREATE TABLE trajectory_value_added_snapshot AS
            SELECT *
            FROM
                value_source.main.expected_improvement_scored_trajectories
            """
        )

        con.execute(
            f"""
            CREATE TABLE event_family_tail_caps AS
            SELECT
                canonical_gender_code,
                event_family,
                QUANTILE_CONT(
                    athlete_value_added,
                    {WINSOR_LOWER}
                ) AS lower_value_added_cap,
                QUANTILE_CONT(
                    athlete_value_added,
                    {WINSOR_UPPER}
                ) AS upper_value_added_cap,
                COUNT(*) AS calibration_trajectory_count
            FROM trajectory_value_added_snapshot
            GROUP BY
                canonical_gender_code,
                event_family
            """
        )

        con.execute(
            """
            CREATE TABLE trajectory_contribution_weights AS
            WITH enriched AS (
                SELECT
                    t.*,
                    COUNT(*) OVER (
                        PARTITION BY
                            canonical_person_id,
                            resolved_school_id,
                            canonical_gender_code,
                            event_family
                    ) AS athlete_school_family_trajectory_count,
                    COUNT(DISTINCT event_family) OVER (
                        PARTITION BY
                            canonical_person_id,
                            resolved_school_id,
                            canonical_gender_code
                    ) AS athlete_school_family_count,
                    COUNT(*) OVER (
                        PARTITION BY
                            canonical_person_id,
                            resolved_school_id,
                            canonical_gender_code
                    ) AS athlete_school_trajectory_count,
                    COUNT(DISTINCT school_stint_id) OVER (
                        PARTITION BY
                            canonical_person_id,
                            resolved_school_id,
                            canonical_gender_code
                    ) AS athlete_school_stint_count,
                    COUNT(DISTINCT canonical_event_code) OVER (
                        PARTITION BY
                            canonical_person_id,
                            resolved_school_id,
                            canonical_gender_code
                    ) AS athlete_school_event_count,
                    COUNT(DISTINCT season_type) OVER (
                        PARTITION BY
                            canonical_person_id,
                            resolved_school_id,
                            canonical_gender_code
                    ) AS athlete_school_season_type_count
                FROM trajectory_value_added_snapshot t
            )
            SELECT
                e.*,
                caps.lower_value_added_cap,
                caps.upper_value_added_cap,
                LEAST(
                    caps.upper_value_added_cap,
                    GREATEST(
                        caps.lower_value_added_cap,
                        e.athlete_value_added
                    )
                ) AS winsorized_athlete_value_added,
                1.0
                    / e.athlete_school_family_trajectory_count
                    AS within_family_trajectory_weight,
                1.0
                    / e.athlete_school_family_count
                    AS event_family_weight,
                1.0
                    / (
                        e.athlete_school_family_trajectory_count
                        * e.athlete_school_family_count
                    ) AS primary_trajectory_contribution_weight,
                e.athlete_value_added
                    / (
                        e.athlete_school_family_trajectory_count
                        * e.athlete_school_family_count
                    ) AS weighted_primary_value_added_contribution,
                LEAST(
                    caps.upper_value_added_cap,
                    GREATEST(
                        caps.lower_value_added_cap,
                        e.athlete_value_added
                    )
                )
                    / (
                        e.athlete_school_family_trajectory_count
                        * e.athlete_school_family_count
                    ) AS weighted_winsorized_value_added_contribution,
                '{AGGREGATION_POLICY_VERSION}'
                    AS aggregation_policy_version
            FROM enriched e
            JOIN event_family_tail_caps caps
              USING (
                canonical_gender_code,
                event_family
              )
            """
        )

        con.execute(
            f"""
            CREATE TABLE athlete_event_family_value_added AS
            SELECT
                'afam_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        canonical_person_id,
                        resolved_school_id,
                        canonical_gender_code,
                        event_family
                    )
                ) AS athlete_family_contribution_id,
                canonical_person_id,
                ANY_VALUE(athlete_id) AS athlete_id,
                ANY_VALUE(athlete_name) AS athlete_name,
                resolved_school_id,
                canonical_gender_code,
                event_family,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT canonical_event_code)
                    AS event_count,
                COUNT(DISTINCT season_type)
                    AS season_type_count,
                COUNT(DISTINCT school_stint_id)
                    AS school_stint_count,
                MIN(baseline_season_year)
                    AS first_baseline_season_year,
                MAX(endpoint_season_year)
                    AS last_endpoint_season_year,
                MIN(baseline_stable_level)
                    AS minimum_baseline_level,
                MAX(baseline_stable_level)
                    AS maximum_baseline_level,
                AVG(baseline_stable_level)
                    AS mean_baseline_level,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                AVG(expected_improvement)
                    AS mean_expected_improvement,
                AVG(athlete_value_added)
                    AS family_mean_value_added,
                MEDIAN(athlete_value_added)
                    AS family_median_value_added,
                AVG(winsorized_athlete_value_added)
                    AS family_winsorized_mean_value_added,
                STDDEV_SAMP(athlete_value_added)
                    AS family_value_added_sd,
                AVG(annualized_athlete_value_added)
                    AS mean_annualized_value_added,
                SUM(total_distinct_meets)
                    AS total_distinct_meets,
                SUM(qualifying_period_count)
                    AS total_qualifying_periods,
                MIN(training_support_n)
                    AS minimum_training_support,
                MEDIAN(training_support_n)
                    AS median_training_support,
                COUNT(*) FILTER (
                    WHERE athlete_value_added > 0
                ) AS above_expected_trajectory_count,
                COUNT(*) FILTER (
                    WHERE athlete_value_added < 0
                ) AS below_expected_trajectory_count,
                COUNT(*) FILTER (
                    WHERE frozen_role =
                        'standalone_primary_two_meet_exception'
                ) AS two_meet_exception_trajectory_count,
                '{DATASET_VERSION}' AS dataset_version,
                '{AGGREGATION_POLICY_VERSION}'
                    AS aggregation_policy_version
            FROM trajectory_contribution_weights
            GROUP BY
                canonical_person_id,
                resolved_school_id,
                canonical_gender_code,
                event_family
            """
        )

        con.execute(
            f"""
            CREATE TABLE athlete_school_value_added AS
            WITH family_aggregated AS (
                SELECT
                    canonical_person_id,
                    ANY_VALUE(athlete_id) AS athlete_id,
                    ANY_VALUE(athlete_name) AS athlete_name,
                    resolved_school_id,
                    canonical_gender_code,
                    COUNT(*) AS event_family_count,
                    SUM(trajectory_count)
                        AS trajectory_count,
                    SUM(event_count)
                        AS family_summed_event_count,
                    MAX(school_stint_count)
                        AS family_max_school_stint_count,
                    SUM(season_type_count)
                        AS family_summed_season_type_count,
                    MIN(first_baseline_season_year)
                        AS first_baseline_season_year,
                    MAX(last_endpoint_season_year)
                        AS last_endpoint_season_year,
                    AVG(family_mean_value_added)
                        AS primary_athlete_value_added,
                    AVG(family_median_value_added)
                        AS family_median_athlete_value_added,
                    AVG(family_winsorized_mean_value_added)
                        AS winsorized_athlete_value_added,
                    AVG(mean_observed_improvement)
                        AS family_equal_mean_observed_improvement,
                    AVG(mean_expected_improvement)
                        AS family_equal_mean_expected_improvement,
                    AVG(mean_annualized_value_added)
                        AS family_equal_mean_annualized_value_added,
                    SUM(total_distinct_meets)
                        AS total_distinct_meets,
                    SUM(total_qualifying_periods)
                        AS total_qualifying_periods,
                    MIN(minimum_training_support)
                        AS minimum_training_support,
                    MEDIAN(median_training_support)
                        AS median_training_support,
                    SUM(above_expected_trajectory_count)
                        AS above_expected_trajectory_count,
                    SUM(below_expected_trajectory_count)
                        AS below_expected_trajectory_count,
                    SUM(two_meet_exception_trajectory_count)
                        AS two_meet_exception_trajectory_count
                FROM athlete_event_family_value_added
                GROUP BY
                    canonical_person_id,
                    resolved_school_id,
                    canonical_gender_code
            ),
            trajectory_alternatives AS (
                SELECT
                    canonical_person_id,
                    resolved_school_id,
                    canonical_gender_code,
                    AVG(athlete_value_added)
                        AS raw_trajectory_mean_value_added,
                    MEDIAN(athlete_value_added)
                        AS raw_trajectory_median_value_added,
                    SUM(
                        weighted_primary_value_added_contribution
                    ) AS weighted_formula_primary_value_added,
                    SUM(
                        weighted_winsorized_value_added_contribution
                    ) AS weighted_formula_winsorized_value_added,
                    COUNT(DISTINCT canonical_event_code)
                        AS distinct_event_count,
                    COUNT(DISTINCT season_type)
                        AS distinct_season_type_count,
                    COUNT(DISTINCT school_stint_id)
                        AS actual_school_stint_count
                FROM trajectory_contribution_weights
                GROUP BY
                    canonical_person_id,
                    resolved_school_id,
                    canonical_gender_code
            )
            SELECT
                'asch_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        f.canonical_person_id,
                        f.resolved_school_id,
                        f.canonical_gender_code
                    )
                ) AS athlete_school_contribution_id,
                f.* EXCLUDE (family_max_school_stint_count),
                t.actual_school_stint_count AS school_stint_count,
                t.distinct_event_count,
                t.distinct_season_type_count,
                t.raw_trajectory_mean_value_added,
                t.raw_trajectory_median_value_added,
                t.weighted_formula_primary_value_added,
                t.weighted_formula_winsorized_value_added,
                CASE
                    WHEN f.primary_athlete_value_added > 1e-12
                        THEN 'above_expected'
                    WHEN f.primary_athlete_value_added < -1e-12
                        THEN 'below_expected'
                    ELSE 'at_expected'
                END AS primary_value_added_direction,
                CASE
                    WHEN f.event_family_count = 1
                     AND f.trajectory_count = 1
                        THEN 'single_trajectory'
                    WHEN f.event_family_count = 1
                        THEN 'multi_trajectory_single_family'
                    ELSE 'multi_family'
                END AS contribution_complexity,
                1.0 AS total_school_voting_weight,
                '{DATASET_VERSION}' AS dataset_version,
                '{AGGREGATION_POLICY_VERSION}'
                    AS aggregation_policy_version
            FROM family_aggregated f
            JOIN trajectory_alternatives t
              USING (
                canonical_person_id,
                resolved_school_id,
                canonical_gender_code
              )
            """
        )

        con.execute(
            """
            CREATE TABLE preliminary_school_scores AS
            WITH raw_trajectory AS (
                SELECT
                    resolved_school_id,
                    AVG(athlete_value_added)
                        AS raw_trajectory_weighted_school_score,
                    COUNT(*) AS raw_trajectory_count
                FROM trajectory_value_added_snapshot
                GROUP BY resolved_school_id
            ),
            athlete_scores AS (
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
                    SUM(trajectory_count)
                        AS trajectory_count,
                    SUM(event_family_count)
                        AS athlete_family_unit_count,
                    AVG(event_family_count)
                        AS mean_event_families_per_athlete,
                    AVG(trajectory_count)
                        AS mean_trajectories_per_athlete,
                    AVG(primary_athlete_value_added)
                        AS preliminary_primary_school_score,
                    MEDIAN(primary_athlete_value_added)
                        AS median_primary_athlete_value_added,
                    STDDEV_SAMP(primary_athlete_value_added)
                        AS athlete_value_added_sd,
                    STDDEV_SAMP(primary_athlete_value_added)
                        / SQRT(COUNT(*))
                        AS unshrunk_standard_error,
                    AVG(raw_trajectory_mean_value_added)
                        AS equal_athlete_raw_trajectory_score,
                    AVG(family_median_athlete_value_added)
                        AS family_median_school_score,
                    AVG(winsorized_athlete_value_added)
                        AS winsorized_family_school_score,
                    AVG(primary_athlete_value_added)
                        FILTER (
                            WHERE canonical_gender_code = 'm'
                        ) AS male_primary_school_score,
                    AVG(primary_athlete_value_added)
                        FILTER (
                            WHERE canonical_gender_code = 'f'
                        ) AS female_primary_school_score,
                    COUNT(*) FILTER (
                        WHERE primary_athlete_value_added > 0
                    ) AS above_expected_athlete_count,
                    COUNT(*) FILTER (
                        WHERE primary_athlete_value_added < 0
                    ) AS below_expected_athlete_count,
                    COUNT(*) FILTER (
                        WHERE event_family_count > 1
                    ) AS multi_family_athlete_count,
                    COUNT(*) FILTER (
                        WHERE trajectory_count > 1
                    ) AS multi_trajectory_athlete_count,
                    AVG(
                        CAST(
                            primary_athlete_value_added > 0
                            AS DOUBLE
                        )
                    ) AS above_expected_athlete_share,
                    AVG(
                        CAST(
                            event_family_count > 1
                            AS DOUBLE
                        )
                    ) AS multi_family_athlete_share,
                    MIN(minimum_training_support)
                        AS minimum_training_support
                FROM athlete_school_value_added
                GROUP BY resolved_school_id
            )
            SELECT
                a.*,
                r.raw_trajectory_weighted_school_score,
                r.raw_trajectory_count,
                a.preliminary_primary_school_score
                    - r.raw_trajectory_weighted_school_score
                    AS primary_minus_raw_trajectory_score,
                a.preliminary_primary_school_score
                    - a.equal_athlete_raw_trajectory_score
                    AS family_neutralization_effect,
                a.preliminary_primary_school_score
                    - a.winsorized_family_school_score
                    AS tail_sensitivity_effect,
                a.preliminary_primary_school_score
                    - 1.96 * a.unshrunk_standard_error
                    AS unshrunk_ci95_lower,
                a.preliminary_primary_school_score
                    + 1.96 * a.unshrunk_standard_error
                    AS unshrunk_ci95_upper,
                RANK() OVER (
                    ORDER BY
                        a.preliminary_primary_school_score DESC
                ) AS preliminary_primary_rank,
                RANK() OVER (
                    ORDER BY
                        r.raw_trajectory_weighted_school_score DESC
                ) AS raw_trajectory_rank,
                RANK() OVER (
                    ORDER BY
                        a.equal_athlete_raw_trajectory_score DESC
                ) AS equal_athlete_raw_rank,
                RANK() OVER (
                    ORDER BY
                        a.family_median_school_score DESC
                ) AS family_median_rank,
                RANK() OVER (
                    ORDER BY
                        a.winsorized_family_school_score DESC
                ) AS winsorized_family_rank,
                '{DATASET_VERSION}' AS dataset_version,
                '{AGGREGATION_POLICY_VERSION}'
                    AS aggregation_policy_version
            FROM athlete_scores a
            JOIN raw_trajectory r
              USING (resolved_school_id)
            """
        )

        con.execute(
            """
            CREATE TABLE aggregation_policy AS
            SELECT
                'trajectory_to_family' AS policy_level,
                'equal_weight_within_athlete_school_event_family'
                    AS policy_rule,
                'Prevents multiple events or indoor/outdoor variants '
                    || 'inside one family from multiplying athlete weight.'
                    AS rationale
            UNION ALL
            SELECT
                'family_to_athlete_school',
                'equal_weight_across_event_families',
                'Preserves multi-disciplinary breadth while each athlete '
                    || 'retains total school voting weight 1.0.'
            UNION ALL
            SELECT
                'same_person_same_school',
                'consolidate_across_school_stints',
                'Prevents repeat or fragmented stints at one school from '
                    || 'creating multiple athlete votes.'
            UNION ALL
            SELECT
                'transfers',
                'one_contribution_per_distinct_school',
                'Allows each school to receive credit only for the '
                    || 'trajectory periods attributed to its own stint.'
            UNION ALL
            SELECT
                'statistical_tails',
                'retain_primary_report_winsorized_sensitivity',
                'Avoids silently deleting genuine exceptional development.'
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
                'aggregation_policy_version',
                '{AGGREGATION_POLICY_VERSION}'
            UNION ALL
            SELECT
                'input_dataset_version',
                '{INPUT_DATASET_VERSION}'
            UNION ALL
            SELECT
                'athlete_school_total_voting_weight',
                '1.0'
            UNION ALL
            SELECT
                'primary_athlete_formula',
                'mean_of_event_family_mean_value_added'
            UNION ALL
            SELECT
                'official_school_ranking_status',
                'preliminary_unshrunk_not_final'
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
                 FROM trajectory_value_added_snapshot)
                    AS trajectory_rows,
                (SELECT COUNT(*)
                 FROM athlete_event_family_value_added)
                    AS athlete_family_rows,
                (SELECT COUNT(*)
                 FROM athlete_school_value_added)
                    AS athlete_school_rows,
                (SELECT COUNT(DISTINCT canonical_person_id)
                 FROM athlete_school_value_added)
                    AS distinct_people,
                (SELECT COUNT(*)
                 FROM preliminary_school_scores)
                    AS school_rows,
                (SELECT COUNT(DISTINCT resolved_school_id)
                 FROM athlete_school_value_added)
                    AS school_count,
                (SELECT COUNT(*)
                 FROM athlete_school_value_added
                 WHERE trajectory_count > 1)
                    AS multi_trajectory_athlete_school_rows,
                (SELECT COUNT(*)
                 FROM athlete_school_value_added
                 WHERE event_family_count > 1)
                    AS multi_family_athlete_school_rows,
                (SELECT COUNT(*)
                 FROM athlete_school_value_added
                 WHERE school_stint_count > 1)
                    AS multi_stint_same_school_rows,
                (SELECT COUNT(*)
                 FROM (
                    SELECT canonical_person_id
                    FROM athlete_school_value_added
                    GROUP BY canonical_person_id
                    HAVING COUNT(DISTINCT resolved_school_id) > 1
                 ))
                    AS multi_school_people
            """
        )[0]

        quality = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM trajectory_contribution_weights
                 WHERE event_family IS NULL
                    OR canonical_person_id IS NULL
                    OR resolved_school_id IS NULL
                    OR canonical_gender_code IS NULL)
                    AS missing_group_context_rows,
                (SELECT COUNT(*)
                 FROM trajectory_contribution_weights
                 WHERE primary_trajectory_contribution_weight
                    <= 0
                    OR primary_trajectory_contribution_weight > 1)
                    AS invalid_trajectory_weight_rows,
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        canonical_person_id,
                        resolved_school_id,
                        canonical_gender_code,
                        SUM(primary_trajectory_contribution_weight)
                            AS total_weight
                    FROM trajectory_contribution_weights
                    GROUP BY
                        canonical_person_id,
                        resolved_school_id,
                        canonical_gender_code
                    HAVING ABS(total_weight - 1.0)
                        > {WEIGHT_TOLERANCE}
                 ))
                    AS athlete_weight_sum_mismatch_rows,
                (SELECT COUNT(*)
                 FROM athlete_school_value_added
                 WHERE ABS(
                    primary_athlete_value_added
                    - weighted_formula_primary_value_added
                 ) > {FORMULA_TOLERANCE})
                    AS primary_formula_mismatch_rows,
                (SELECT COUNT(*)
                 FROM athlete_school_value_added
                 WHERE ABS(
                    winsorized_athlete_value_added
                    - weighted_formula_winsorized_value_added
                 ) > {FORMULA_TOLERANCE})
                    AS winsorized_formula_mismatch_rows,
                (SELECT COUNT(*)
                 FROM athlete_school_value_added
                 WHERE event_family_count = 1
                   AND ABS(
                        primary_athlete_value_added
                        - raw_trajectory_mean_value_added
                   ) > {FORMULA_TOLERANCE})
                    AS single_family_formula_mismatch_rows,
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        athlete_family_contribution_id,
                        COUNT(*) AS row_count
                    FROM athlete_event_family_value_added
                    GROUP BY athlete_family_contribution_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_athlete_family_ids,
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        athlete_school_contribution_id,
                        COUNT(*) AS row_count
                    FROM athlete_school_value_added
                    GROUP BY athlete_school_contribution_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_athlete_school_ids,
                (SELECT COUNT(*)
                 FROM athlete_school_value_added
                 WHERE total_school_voting_weight <> 1.0)
                    AS invalid_school_voting_weight_rows,
                (SELECT COUNT(*)
                 FROM preliminary_school_scores
                 WHERE preliminary_primary_school_score IS NULL
                    OR athlete_school_unit_count <= 0)
                    AS invalid_preliminary_school_rows
            """
        )[0]

        sensitivity = fetch_dicts(
            con,
            """
            SELECT
                CORR(
                    preliminary_primary_school_score,
                    raw_trajectory_weighted_school_score
                ) AS primary_raw_score_correlation,
                CORR(
                    preliminary_primary_rank,
                    raw_trajectory_rank
                ) AS primary_raw_rank_correlation,
                CORR(
                    preliminary_primary_school_score,
                    equal_athlete_raw_trajectory_score
                ) AS primary_equal_athlete_score_correlation,
                CORR(
                    preliminary_primary_rank,
                    equal_athlete_raw_rank
                ) AS primary_equal_athlete_rank_correlation,
                CORR(
                    preliminary_primary_school_score,
                    winsorized_family_school_score
                ) AS primary_winsorized_score_correlation,
                CORR(
                    preliminary_primary_rank,
                    winsorized_family_rank
                ) AS primary_winsorized_rank_correlation,
                AVG(ABS(
                    preliminary_primary_rank
                    - raw_trajectory_rank
                )) AS mean_abs_rank_change_vs_raw,
                MAX(ABS(
                    preliminary_primary_rank
                    - raw_trajectory_rank
                )) AS max_abs_rank_change_vs_raw,
                AVG(ABS(
                    preliminary_primary_rank
                    - winsorized_family_rank
                )) AS mean_abs_rank_change_vs_winsorized,
                MAX(ABS(
                    preliminary_primary_rank
                    - winsorized_family_rank
                )) AS max_abs_rank_change_vs_winsorized
            FROM preliminary_school_scores
            """
        )[0]

        add_check(
            checks,
            "source_trajectory_row_count",
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
            "preliminary_school_row_count",
            counts["school_rows"] == EXPECTED_SCHOOLS,
            counts["school_rows"],
            EXPECTED_SCHOOLS,
        )
        add_check(
            checks,
            "trajectory_rows_preserved",
            con.execute(
                """
                SELECT COUNT(*)
                FROM trajectory_contribution_weights
                """
            ).fetchone()[0]
            == counts["trajectory_rows"],
            con.execute(
                """
                SELECT COUNT(*)
                FROM trajectory_contribution_weights
                """
            ).fetchone()[0],
            counts["trajectory_rows"],
        )
        add_check(
            checks,
            "all_group_context_complete",
            quality["missing_group_context_rows"] == 0,
            quality["missing_group_context_rows"],
            0,
        )
        add_check(
            checks,
            "all_trajectory_weights_valid",
            quality["invalid_trajectory_weight_rows"] == 0,
            quality["invalid_trajectory_weight_rows"],
            0,
        )
        add_check(
            checks,
            "every_athlete_school_weight_sums_to_one",
            quality["athlete_weight_sum_mismatch_rows"] == 0,
            quality["athlete_weight_sum_mismatch_rows"],
            0,
        )
        add_check(
            checks,
            "primary_athlete_formula_reconciles",
            quality["primary_formula_mismatch_rows"] == 0,
            quality["primary_formula_mismatch_rows"],
            0,
        )
        add_check(
            checks,
            "winsorized_athlete_formula_reconciles",
            quality["winsorized_formula_mismatch_rows"] == 0,
            quality["winsorized_formula_mismatch_rows"],
            0,
        )
        add_check(
            checks,
            "single_family_athletes_match_raw_mean",
            quality["single_family_formula_mismatch_rows"] == 0,
            quality["single_family_formula_mismatch_rows"],
            0,
        )
        add_check(
            checks,
            "athlete_family_ids_unique",
            quality["duplicate_athlete_family_ids"] == 0,
            quality["duplicate_athlete_family_ids"],
            0,
        )
        add_check(
            checks,
            "athlete_school_ids_unique",
            quality["duplicate_athlete_school_ids"] == 0,
            quality["duplicate_athlete_school_ids"],
            0,
        )
        add_check(
            checks,
            "every_athlete_school_has_one_vote",
            quality["invalid_school_voting_weight_rows"] == 0,
            quality["invalid_school_voting_weight_rows"],
            0,
        )
        add_check(
            checks,
            "all_preliminary_school_rows_valid",
            quality["invalid_preliminary_school_rows"] == 0,
            quality["invalid_preliminary_school_rows"],
            0,
        )
        add_check(
            checks,
            "multi_event_population_exists",
            counts["multi_trajectory_athlete_school_rows"] > 0
            and counts["multi_family_athlete_school_rows"] > 0,
            {
                "multi_trajectory":
                    counts["multi_trajectory_athlete_school_rows"],
                "multi_family":
                    counts["multi_family_athlete_school_rows"],
            },
            "both greater than 0",
        )

        distribution_rows = fetch_dicts(
            con,
            """
            SELECT
                trajectory_count,
                event_family_count,
                distinct_event_count,
                distinct_season_type_count,
                contribution_complexity,
                COUNT(*) AS athlete_school_unit_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(primary_athlete_value_added)
                    AS mean_primary_value_added,
                MEDIAN(primary_athlete_value_added)
                    AS median_primary_value_added,
                AVG(
                    primary_athlete_value_added
                    - raw_trajectory_mean_value_added
                ) AS mean_family_neutralization_effect
            FROM athlete_school_value_added
            GROUP BY
                trajectory_count,
                event_family_count,
                distinct_event_count,
                distinct_season_type_count,
                contribution_complexity
            ORDER BY
                trajectory_count,
                event_family_count,
                distinct_event_count,
                distinct_season_type_count
            """
        )

        write_csv(
            OUTPUT_DIR / "multi_event_distribution.csv",
            distribution_rows,
            list(distribution_rows[0].keys())
                if distribution_rows else [],
        )

        school_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM preliminary_school_scores
            ORDER BY
                preliminary_primary_rank,
                resolved_school_id
            """
        )

        write_csv(
            OUTPUT_DIR / "preliminary_school_scores.csv",
            school_rows,
            list(school_rows[0].keys()) if school_rows else [],
        )

        sensitivity_rows = fetch_dicts(
            con,
            """
            SELECT
                resolved_school_id,
                athlete_school_unit_count,
                trajectory_count,
                mean_event_families_per_athlete,
                mean_trajectories_per_athlete,
                preliminary_primary_school_score,
                raw_trajectory_weighted_school_score,
                equal_athlete_raw_trajectory_score,
                family_median_school_score,
                winsorized_family_school_score,
                family_neutralization_effect,
                tail_sensitivity_effect,
                preliminary_primary_rank,
                raw_trajectory_rank,
                equal_athlete_raw_rank,
                family_median_rank,
                winsorized_family_rank,
                ABS(
                    preliminary_primary_rank
                    - raw_trajectory_rank
                ) AS absolute_rank_change_vs_raw,
                ABS(
                    preliminary_primary_rank
                    - winsorized_family_rank
                ) AS absolute_rank_change_vs_winsorized
            FROM preliminary_school_scores
            ORDER BY
                absolute_rank_change_vs_raw DESC,
                resolved_school_id
            """
        )

        write_csv(
            OUTPUT_DIR / "school_aggregation_sensitivity.csv",
            sensitivity_rows,
            list(sensitivity_rows[0].keys())
                if sensitivity_rows else [],
        )

        complex_athletes = fetch_dicts(
            con,
            """
            SELECT *
            FROM athlete_school_value_added
            ORDER BY
                event_family_count DESC,
                trajectory_count DESC,
                ABS(
                    primary_athlete_value_added
                    - raw_trajectory_mean_value_added
                ) DESC,
                athlete_school_contribution_id
            LIMIT 1000
            """
        )

        write_csv(
            OUTPUT_DIR / "complex_athlete_contribution_review.csv",
            complex_athletes,
            list(complex_athletes[0].keys())
                if complex_athletes else [],
        )

        extreme_athletes = fetch_dicts(
            con,
            """
            SELECT *
            FROM athlete_school_value_added
            ORDER BY
                ABS(primary_athlete_value_added) DESC,
                athlete_school_contribution_id
            LIMIT 500
            """
        )

        write_csv(
            OUTPUT_DIR / "extreme_athlete_value_added_review.csv",
            extreme_athletes,
            list(extreme_athletes[0].keys())
                if extreme_athletes else [],
        )

        family_profile = fetch_dicts(
            con,
            """
            SELECT
                canonical_gender_code,
                event_family,
                COUNT(*) AS athlete_family_unit_count,
                COUNT(DISTINCT canonical_person_id)
                    AS distinct_athlete_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(trajectory_count)
                    AS mean_trajectories_per_family_unit,
                AVG(family_mean_value_added)
                    AS mean_family_value_added,
                MEDIAN(family_mean_value_added)
                    AS median_family_value_added,
                STDDEV_SAMP(family_mean_value_added)
                    AS family_value_added_sd,
                AVG(
                    family_mean_value_added
                    - family_winsorized_mean_value_added
                ) AS mean_tail_effect
            FROM athlete_event_family_value_added
            GROUP BY
                canonical_gender_code,
                event_family
            ORDER BY
                canonical_gender_code,
                event_family
            """
        )

        write_csv(
            OUTPUT_DIR / "event_family_contribution_profile.csv",
            family_profile,
            list(family_profile[0].keys())
                if family_profile else [],
        )

        policy_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM aggregation_policy
            ORDER BY policy_level
            """
        )

        write_csv(
            OUTPUT_DIR / "aggregation_policy.csv",
            policy_rows,
            list(policy_rows[0].keys()) if policy_rows else [],
        )

        sensitivity_summary_rows = [
            {
                "metric": key,
                "value": value,
            }
            for key, value in sensitivity.items()
        ]

        write_csv(
            OUTPUT_DIR / "aggregation_sensitivity_summary.csv",
            sensitivity_summary_rows,
            ["metric", "value"],
        )

        summary_rows = [
            {
                "metric": "source_trajectory_rows",
                "value": counts["trajectory_rows"],
            },
            {
                "metric": "athlete_event_family_units",
                "value": counts["athlete_family_rows"],
            },
            {
                "metric": "athlete_school_units",
                "value": counts["athlete_school_rows"],
            },
            {
                "metric": "distinct_people",
                "value": counts["distinct_people"],
            },
            {
                "metric": "schools",
                "value": counts["school_count"],
            },
            {
                "metric": "multi_trajectory_athlete_school_units",
                "value":
                    counts["multi_trajectory_athlete_school_rows"],
            },
            {
                "metric": "multi_family_athlete_school_units",
                "value":
                    counts["multi_family_athlete_school_rows"],
            },
            {
                "metric": "multi_stint_same_school_units",
                "value":
                    counts["multi_stint_same_school_rows"],
            },
            {
                "metric": "multi_school_people",
                "value": counts["multi_school_people"],
            },
            {
                "metric": "primary_raw_score_correlation",
                "value":
                    sensitivity["primary_raw_score_correlation"],
            },
            {
                "metric": "primary_raw_rank_correlation",
                "value":
                    sensitivity["primary_raw_rank_correlation"],
            },
            {
                "metric": "mean_abs_rank_change_vs_raw",
                "value":
                    sensitivity["mean_abs_rank_change_vs_raw"],
            },
            {
                "metric": "max_abs_rank_change_vs_raw",
                "value":
                    sensitivity["max_abs_rank_change_vs_raw"],
            },
            {
                "metric": "primary_winsorized_rank_correlation",
                "value":
                    sensitivity[
                        "primary_winsorized_rank_correlation"
                    ],
            },
        ]

        write_csv(
            OUTPUT_DIR / "phase_5f_summary.csv",
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
                "aggregation_policy_version":
                    AGGREGATION_POLICY_VERSION,
            }
        ],
        [
            "output_name",
            "path",
            "size_bytes",
            "sha256",
            "dataset_version",
            "aggregation_policy_version",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 5 PHASE 5F — MULTI-EVENT-NEUTRAL CONTRIBUTIONS",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "PRIMARY AGGREGATION POLICY",
        "-" * 78,
        "Trajectories are averaged within athlete-school event family.",
        "Event families are averaged within athlete-school.",
        "Each athlete-school unit contributes total school voting weight 1.0.",
        "Multiple stints at one school are consolidated.",
        "Transfers may contribute once to each distinct school.",
        "Statistical tails remain in the primary score.",
        "",
        "RESULTS",
        "-" * 78,
        f"Source trajectory rows: "
        f"{int(counts['trajectory_rows']):,}",
        f"Athlete-event-family units: "
        f"{int(counts['athlete_family_rows']):,}",
        f"Athlete-school units: "
        f"{int(counts['athlete_school_rows']):,}",
        f"Distinct people: "
        f"{int(counts['distinct_people']):,}",
        f"Schools represented: "
        f"{int(counts['school_count']):,}",
        f"Multi-trajectory athlete-school units: "
        f"{int(counts['multi_trajectory_athlete_school_rows']):,}",
        f"Multi-family athlete-school units: "
        f"{int(counts['multi_family_athlete_school_rows']):,}",
        f"Multiple stints consolidated at same school: "
        f"{int(counts['multi_stint_same_school_rows']):,}",
        f"People represented at multiple schools: "
        f"{int(counts['multi_school_people']):,}",
        "",
        "SENSITIVITY",
        "-" * 78,
        "Primary vs raw trajectory score correlation: "
        f"{float(sensitivity['primary_raw_score_correlation']):.6f}",
        "Primary vs raw trajectory rank correlation: "
        f"{float(sensitivity['primary_raw_rank_correlation']):.6f}",
        "Mean absolute school-rank change vs raw trajectory weighting: "
        f"{float(sensitivity['mean_abs_rank_change_vs_raw']):.3f}",
        "Maximum absolute school-rank change vs raw trajectory weighting: "
        f"{float(sensitivity['max_abs_rank_change_vs_raw']):.0f}",
        "Primary vs winsorized rank correlation: "
        f"{float(sensitivity['primary_winsorized_rank_correlation']):.6f}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Multi-event-neutral athlete contributions created."
            if not failed
            else "FAIL — Do not create official school rankings."
        ),
        "",
        "NEXT",
        "-" * 78,
        "Review aggregation sensitivity and complex athlete examples.",
        "Then apply school-level empirical-Bayes shrinkage, uncertainty",
        "intervals, minimum-sample policy, and ranking tiers.",
    ]

    (OUTPUT_DIR / "phase_5f_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Source trajectories: {int(counts['trajectory_rows']):,}"
    )
    print(
        "Athlete-event-family units: "
        f"{int(counts['athlete_family_rows']):,}"
    )
    print(
        f"Athlete-school units: "
        f"{int(counts['athlete_school_rows']):,}"
    )
    print(
        f"Distinct people: {int(counts['distinct_people']):,}"
    )
    print(
        f"Schools represented: {int(counts['school_count']):,}"
    )
    print(
        "Primary/raw school-rank correlation: "
        f"{float(sensitivity['primary_raw_rank_correlation']):.6f}"
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
    print("Next: build uncertainty-adjusted school rankings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
