#!/usr/bin/env python3
"""
Milestone 5 Phase 5A — Observed Athlete Development Trajectories

Constructs the first actual athlete-development dataset from the frozen
event-specific period eligibility policy.

Primary trajectory grain
------------------------
canonical person
× school stint
× resolved school
× gender
× season type
× canonical event

Primary observed development
----------------------------
endpoint stable level - baseline stable level

The baseline is the first chronologically eligible stable period and the
endpoint is the last chronologically eligible stable period within the same
school stint and event. The script also preserves consecutive period changes,
trajectory slope, sustained peak, duration, and reliability metadata.

This phase measures observed development only. It does not yet estimate
expected improvement or school value added.
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
      "phase_4h_frozen_event_period_policy/"
      "event_period_policy_v1.duckdb"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5a_observed_development_trajectories"
)

OUTPUT_DB = OUTPUT_DIR / "observed_development_trajectories_v1.duckdb"

INPUT_DATASET_VERSION = "event_period_policy_v1"
INPUT_POLICY_VERSION = "event_period_eligibility_policy_v1"
DATASET_VERSION = "observed_development_trajectories_v1"
TRAJECTORY_POLICY_VERSION = "observed_development_policy_v1"

EXPECTED_TRAJECTORY_ROWS = 189_839
EXPECTED_TRAJECTORY_ATHLETES = 79_551
EXPECTED_TRAJECTORY_SCHOOLS = 361
EXPECTED_EXCEPTION_TRAJECTORIES = 1_354
EXPECTED_SUPPORTING_TRAJECTORIES = 0


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

    print("MILESTONE 5 PHASE 5A — OBSERVED DEVELOPMENT TRAJECTORIES")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Input database: {INPUT_DB}")
    print(f"Output database: {OUTPUT_DB}")

    add_check(
        checks,
        "input_database_exists",
        INPUT_DB.exists(),
        INPUT_DB.exists(),
        True,
    )

    if not INPUT_DB.exists():
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Input database missing.")
        return 1

    input_hash_before = sha256_file(INPUT_DB)

    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()

    con = duckdb.connect(str(OUTPUT_DB))

    try:
        con.execute("PRAGMA threads=4")
        con.execute("PRAGMA enable_progress_bar=false")

        con.execute(
            f"""
            ATTACH '{sql_path(INPUT_DB)}'
                AS policy_source (READ_ONLY)
            """
        )

        metadata = {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM policy_source.main.dataset_metadata
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
            metadata.get("event_period_policy_version")
            == INPUT_POLICY_VERSION,
            metadata.get("event_period_policy_version"),
            INPUT_POLICY_VERSION,
        )

        con.execute(
            """
            CREATE TABLE eligible_trajectory_periods AS
            SELECT
                athlete_event_period_id,
                canonical_person_id,
                athlete_id,
                athlete_name,
                school_stint_id,
                analytical_school_stint_id,
                resolved_team_id,
                resolved_school_id,
                canonical_gender_code,
                season_type,
                CAST(season_year AS INTEGER) AS season_year,
                season_id,
                canonical_event_code,
                canonical_event_name,
                event_family,
                distinct_meet_count,
                source_performance_count,
                selected_meet_count,
                stable_performance_level,
                top_1_meet_level,
                top_2_mean_level,
                all_meet_median_level,
                all_meet_mean_level,
                all_meet_score_sd,
                minimum_meet_level,
                maximum_meet_level,
                first_performance_date,
                last_performance_date,
                observed_day_span,
                selected_performance_ids,
                selected_meet_ids,
                reliability_tier,
                estimation_method,
                standalone_min_distinct_meets,
                frozen_role,
                frozen_eligibility_path,
                event_policy_version
            FROM policy_source.main.policy_applied_period_levels
            WHERE standalone_primary_eligible
            """
        )

        duplicate_period_years = fetch_dicts(
            con,
            """
            SELECT
                canonical_person_id,
                school_stint_id,
                resolved_school_id,
                canonical_gender_code,
                season_type,
                canonical_event_code,
                season_year,
                COUNT(*) AS period_count
            FROM eligible_trajectory_periods
            GROUP BY
                canonical_person_id,
                school_stint_id,
                resolved_school_id,
                canonical_gender_code,
                season_type,
                canonical_event_code,
                season_year
            HAVING COUNT(*) > 1
            ORDER BY period_count DESC
            LIMIT 500
            """
        )

        if duplicate_period_years:
            write_csv(
                OUTPUT_DIR / "duplicate_eligible_season_year_issues.csv",
                duplicate_period_years,
                [
                    "canonical_person_id",
                    "school_stint_id",
                    "resolved_school_id",
                    "canonical_gender_code",
                    "season_type",
                    "canonical_event_code",
                    "season_year",
                    "period_count",
                ],
            )

        con.execute(
            """
            CREATE TABLE ranked_trajectory_periods AS
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        canonical_person_id,
                        school_stint_id,
                        resolved_school_id,
                        canonical_gender_code,
                        season_type,
                        canonical_event_code
                    ORDER BY
                        season_year,
                        season_id,
                        athlete_event_period_id
                ) AS trajectory_period_index,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        canonical_person_id,
                        school_stint_id,
                        resolved_school_id,
                        canonical_gender_code,
                        season_type,
                        canonical_event_code
                    ORDER BY
                        season_year DESC,
                        season_id DESC,
                        athlete_event_period_id DESC
                ) AS reverse_trajectory_period_index,
                COUNT(*) OVER (
                    PARTITION BY
                        canonical_person_id,
                        school_stint_id,
                        resolved_school_id,
                        canonical_gender_code,
                        season_type,
                        canonical_event_code
                ) AS trajectory_period_count
            FROM eligible_trajectory_periods
            """
        )

        con.execute(
            """
            CREATE TABLE consecutive_period_transitions AS
            WITH ordered AS (
                SELECT
                    *,
                    LEAD(athlete_event_period_id) OVER w
                        AS next_period_id,
                    LEAD(season_year) OVER w
                        AS next_season_year,
                    LEAD(stable_performance_level) OVER w
                        AS next_stable_level,
                    LEAD(distinct_meet_count) OVER w
                        AS next_distinct_meet_count,
                    LEAD(first_performance_date) OVER w
                        AS next_first_performance_date,
                    LEAD(last_performance_date) OVER w
                        AS next_last_performance_date
                FROM ranked_trajectory_periods
                WINDOW w AS (
                    PARTITION BY
                        canonical_person_id,
                        school_stint_id,
                        resolved_school_id,
                        canonical_gender_code,
                        season_type,
                        canonical_event_code
                    ORDER BY
                        season_year,
                        season_id,
                        athlete_event_period_id
                )
            )
            SELECT
                'trn_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        athlete_event_period_id,
                        next_period_id
                    )
                ) AS transition_id,
                canonical_person_id,
                athlete_id,
                athlete_name,
                school_stint_id,
                analytical_school_stint_id,
                resolved_team_id,
                resolved_school_id,
                canonical_gender_code,
                season_type,
                canonical_event_code,
                canonical_event_name,
                event_family,
                frozen_role,
                standalone_min_distinct_meets,
                athlete_event_period_id AS earlier_period_id,
                next_period_id AS later_period_id,
                season_year AS earlier_season_year,
                next_season_year AS later_season_year,
                stable_performance_level AS earlier_stable_level,
                next_stable_level AS later_stable_level,
                next_stable_level - stable_performance_level
                    AS observed_change,
                next_season_year - season_year
                    AS elapsed_seasons,
                CASE
                    WHEN next_season_year > season_year
                    THEN
                        (next_stable_level - stable_performance_level)
                        / (next_season_year - season_year)
                    ELSE NULL
                END AS annualized_observed_change,
                distinct_meet_count AS earlier_distinct_meets,
                next_distinct_meet_count AS later_distinct_meets,
                first_performance_date
                    AS earlier_first_performance_date,
                last_performance_date
                    AS earlier_last_performance_date,
                next_first_performance_date
                    AS later_first_performance_date,
                next_last_performance_date
                    AS later_last_performance_date,
                '{DATASET_VERSION}' AS dataset_version,
                '{TRAJECTORY_POLICY_VERSION}'
                    AS trajectory_policy_version
            FROM ordered
            WHERE next_period_id IS NOT NULL
            """
        )

        con.execute(
            """
            CREATE TABLE athlete_event_trajectories AS
            WITH aggregates AS (
                SELECT
                    canonical_person_id,
                    ANY_VALUE(athlete_id) AS athlete_id,
                    ANY_VALUE(athlete_name) AS athlete_name,
                    school_stint_id,
                    ANY_VALUE(analytical_school_stint_id)
                        AS analytical_school_stint_id,
                    ANY_VALUE(resolved_team_id)
                        AS resolved_team_id,
                    resolved_school_id,
                    canonical_gender_code,
                    season_type,
                    canonical_event_code,
                    ANY_VALUE(canonical_event_name)
                        AS canonical_event_name,
                    ANY_VALUE(event_family) AS event_family,
                    ANY_VALUE(frozen_role) AS frozen_role,
                    ANY_VALUE(standalone_min_distinct_meets)
                        AS standalone_min_distinct_meets,

                    COUNT(*) AS qualifying_period_count,
                    COUNT(DISTINCT season_year)
                        AS distinct_season_year_count,
                    SUM(distinct_meet_count)
                        AS total_distinct_meets,
                    SUM(source_performance_count)
                        AS total_source_performances,
                    MIN(distinct_meet_count)
                        AS minimum_period_distinct_meets,
                    MAX(distinct_meet_count)
                        AS maximum_period_distinct_meets,
                    AVG(distinct_meet_count)
                        AS mean_period_distinct_meets,

                    MAX(CASE
                        WHEN trajectory_period_index = 1
                        THEN athlete_event_period_id
                    END) AS baseline_period_id,
                    MAX(CASE
                        WHEN trajectory_period_index = 1
                        THEN season_year
                    END) AS baseline_season_year,
                    MAX(CASE
                        WHEN trajectory_period_index = 1
                        THEN stable_performance_level
                    END) AS baseline_stable_level,
                    MAX(CASE
                        WHEN trajectory_period_index = 1
                        THEN distinct_meet_count
                    END) AS baseline_distinct_meets,
                    MAX(CASE
                        WHEN trajectory_period_index = 1
                        THEN reliability_tier
                    END) AS baseline_reliability_tier,
                    MAX(CASE
                        WHEN trajectory_period_index = 1
                        THEN first_performance_date
                    END) AS baseline_first_performance_date,
                    MAX(CASE
                        WHEN trajectory_period_index = 1
                        THEN last_performance_date
                    END) AS baseline_last_performance_date,

                    MAX(CASE
                        WHEN reverse_trajectory_period_index = 1
                        THEN athlete_event_period_id
                    END) AS endpoint_period_id,
                    MAX(CASE
                        WHEN reverse_trajectory_period_index = 1
                        THEN season_year
                    END) AS endpoint_season_year,
                    MAX(CASE
                        WHEN reverse_trajectory_period_index = 1
                        THEN stable_performance_level
                    END) AS endpoint_stable_level,
                    MAX(CASE
                        WHEN reverse_trajectory_period_index = 1
                        THEN distinct_meet_count
                    END) AS endpoint_distinct_meets,
                    MAX(CASE
                        WHEN reverse_trajectory_period_index = 1
                        THEN reliability_tier
                    END) AS endpoint_reliability_tier,
                    MAX(CASE
                        WHEN reverse_trajectory_period_index = 1
                        THEN first_performance_date
                    END) AS endpoint_first_performance_date,
                    MAX(CASE
                        WHEN reverse_trajectory_period_index = 1
                        THEN last_performance_date
                    END) AS endpoint_last_performance_date,

                    MAX(stable_performance_level)
                        AS peak_sustained_level,
                    ARG_MAX(
                        athlete_event_period_id,
                        stable_performance_level
                    ) AS peak_period_id,
                    ARG_MAX(
                        season_year,
                        stable_performance_level
                    ) AS peak_season_year,

                    MIN(stable_performance_level)
                        AS minimum_sustained_level,
                    AVG(stable_performance_level)
                        AS mean_sustained_level,
                    MEDIAN(stable_performance_level)
                        AS median_sustained_level,
                    STDDEV_SAMP(stable_performance_level)
                        AS period_level_sd,
                    REGR_SLOPE(
                        stable_performance_level,
                        season_year
                    ) AS season_year_regression_slope
                FROM ranked_trajectory_periods
                GROUP BY
                    canonical_person_id,
                    school_stint_id,
                    resolved_school_id,
                    canonical_gender_code,
                    season_type,
                    canonical_event_code
                HAVING COUNT(*) >= 2
            ),
            transition_summary AS (
                SELECT
                    canonical_person_id,
                    school_stint_id,
                    resolved_school_id,
                    canonical_gender_code,
                    season_type,
                    canonical_event_code,
                    COUNT(*) AS transition_count,
                    AVG(observed_change)
                        AS mean_consecutive_change,
                    MEDIAN(observed_change)
                        AS median_consecutive_change,
                    MIN(observed_change)
                        AS minimum_consecutive_change,
                    MAX(observed_change)
                        AS maximum_consecutive_change,
                    COUNT(*) FILTER (
                        WHERE observed_change > 0
                    ) AS positive_transition_count,
                    COUNT(*) FILTER (
                        WHERE observed_change < 0
                    ) AS negative_transition_count,
                    COUNT(*) FILTER (
                        WHERE ABS(observed_change) <= 1e-12
                    ) AS zero_transition_count
                FROM consecutive_period_transitions
                GROUP BY
                    canonical_person_id,
                    school_stint_id,
                    resolved_school_id,
                    canonical_gender_code,
                    season_type,
                    canonical_event_code
            )
            SELECT
                'traj_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        a.canonical_person_id,
                        a.school_stint_id,
                        a.resolved_school_id,
                        a.canonical_gender_code,
                        a.season_type,
                        a.canonical_event_code
                    )
                ) AS trajectory_id,
                a.*,
                a.endpoint_season_year
                    - a.baseline_season_year
                    AS elapsed_seasons,
                DATE_DIFF(
                    'day',
                    a.baseline_first_performance_date,
                    a.endpoint_last_performance_date
                ) AS elapsed_observed_days,
                a.endpoint_stable_level
                    - a.baseline_stable_level
                    AS observed_improvement,
                CASE
                    WHEN a.endpoint_season_year
                            > a.baseline_season_year
                    THEN
                        (
                            a.endpoint_stable_level
                            - a.baseline_stable_level
                        )
                        / (
                            a.endpoint_season_year
                            - a.baseline_season_year
                        )
                    ELSE NULL
                END AS annualized_observed_improvement,
                a.peak_sustained_level
                    - a.baseline_stable_level
                    AS first_to_peak_improvement,
                t.transition_count,
                t.mean_consecutive_change,
                t.median_consecutive_change,
                t.minimum_consecutive_change,
                t.maximum_consecutive_change,
                t.positive_transition_count,
                t.negative_transition_count,
                t.zero_transition_count,
                t.positive_transition_count::DOUBLE
                    / NULLIF(t.transition_count, 0)
                    AS positive_transition_share,
                CASE
                    WHEN a.frozen_role =
                        'standalone_primary_two_meet_exception'
                        THEN 'two_meet_event_exception'
                    WHEN a.qualifying_period_count >= 3
                     AND a.minimum_period_distinct_meets >= 5
                        THEN 'high'
                    WHEN a.minimum_period_distinct_meets >= 3
                        THEN 'standard'
                    ELSE 'mixed_period_reliability'
                END AS trajectory_reliability_tier,
                CASE
                    WHEN a.endpoint_stable_level
                            - a.baseline_stable_level > 1e-12
                        THEN 'improved'
                    WHEN a.endpoint_stable_level
                            - a.baseline_stable_level < -1e-12
                        THEN 'declined'
                    ELSE 'unchanged'
                END AS observed_direction,
                '{DATASET_VERSION}' AS dataset_version,
                '{TRAJECTORY_POLICY_VERSION}'
                    AS trajectory_policy_version
            FROM aggregates a
            JOIN transition_summary t
              USING (
                canonical_person_id,
                school_stint_id,
                resolved_school_id,
                canonical_gender_code,
                season_type,
                canonical_event_code
              )
            """
        )

        con.execute(
            """
            CREATE VIEW improved_trajectories AS
            SELECT *
            FROM athlete_event_trajectories
            WHERE observed_improvement > 0
            """
        )

        con.execute(
            """
            CREATE VIEW declined_trajectories AS
            SELECT *
            FROM athlete_event_trajectories
            WHERE observed_improvement < 0
            """
        )

        con.execute(
            """
            CREATE TABLE dataset_metadata AS
            SELECT
                'dataset_version' AS metadata_key,
                'observed_development_trajectories_v1'
                    AS metadata_value
            UNION ALL
            SELECT
                'input_dataset_version',
                'event_period_policy_v1'
            UNION ALL
            SELECT
                'input_event_period_policy_version',
                'event_period_eligibility_policy_v1'
            UNION ALL
            SELECT
                'trajectory_policy_version',
                'observed_development_policy_v1'
            UNION ALL
            SELECT
                'primary_observed_development',
                'endpoint_stable_level_minus_baseline_stable_level'
            UNION ALL
            SELECT
                'annualization_denominator',
                'endpoint_season_year_minus_baseline_season_year'
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
                    AS trajectory_athletes,
                COUNT(DISTINCT resolved_school_id)
                    AS trajectory_schools,
                COUNT(*) FILTER (
                    WHERE frozen_role =
                        'standalone_primary_two_meet_exception'
                ) AS exception_trajectories,
                COUNT(*) FILTER (
                    WHERE frozen_role =
                        'family_pooling_supporting_only'
                ) AS supporting_trajectories,
                COUNT(*) FILTER (
                    WHERE observed_improvement > 0
                ) AS improved_trajectories,
                COUNT(*) FILTER (
                    WHERE observed_improvement < 0
                ) AS declined_trajectories,
                COUNT(*) FILTER (
                    WHERE ABS(observed_improvement) <= 1e-12
                ) AS unchanged_trajectories,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                MEDIAN(observed_improvement)
                    AS median_observed_improvement,
                AVG(annualized_observed_improvement)
                    AS mean_annualized_improvement,
                MEDIAN(annualized_observed_improvement)
                    AS median_annualized_improvement,
                MIN(observed_improvement)
                    AS minimum_observed_improvement,
                MAX(observed_improvement)
                    AS maximum_observed_improvement
            FROM athlete_event_trajectories
            """
        )[0]

        transition_count = con.execute(
            """
            SELECT COUNT(*)
            FROM consecutive_period_transitions
            """
        ).fetchone()[0]

        expected_transition_count = con.execute(
            """
            SELECT SUM(qualifying_period_count - 1)
            FROM athlete_event_trajectories
            """
        ).fetchone()[0]

        quality = fetch_dicts(
            con,
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE qualifying_period_count < 2
                ) AS too_few_period_rows,
                COUNT(*) FILTER (
                    WHERE distinct_season_year_count
                        <> qualifying_period_count
                ) AS duplicate_season_year_trajectory_rows,
                COUNT(*) FILTER (
                    WHERE baseline_season_year
                        >= endpoint_season_year
                ) AS nonpositive_elapsed_season_rows,
                COUNT(*) FILTER (
                    WHERE elapsed_seasons <= 0
                ) AS invalid_elapsed_season_rows,
                COUNT(*) FILTER (
                    WHERE baseline_stable_level < 0
                       OR baseline_stable_level > 100
                       OR endpoint_stable_level < 0
                       OR endpoint_stable_level > 100
                       OR peak_sustained_level < 0
                       OR peak_sustained_level > 100
                ) AS score_out_of_range_rows,
                COUNT(*) FILTER (
                    WHERE ABS(
                        observed_improvement
                        - (
                            endpoint_stable_level
                            - baseline_stable_level
                        )
                    ) > 1e-10
                ) AS improvement_formula_mismatch_rows,
                COUNT(*) FILTER (
                    WHERE ABS(
                        annualized_observed_improvement
                        - observed_improvement
                          / elapsed_seasons
                    ) > 1e-10
                ) AS annualization_formula_mismatch_rows,
                COUNT(*) FILTER (
                    WHERE peak_sustained_level
                        + 1e-12 < baseline_stable_level
                       OR peak_sustained_level
                        + 1e-12 < endpoint_stable_level
                ) AS invalid_peak_rows,
                COUNT(*) FILTER (
                    WHERE transition_count
                        <> qualifying_period_count - 1
                ) AS transition_count_mismatch_rows
            FROM athlete_event_trajectories
            """
        )[0]

        duplicate_trajectory_ids = fetch_dicts(
            con,
            """
            SELECT trajectory_id, COUNT(*) AS row_count
            FROM athlete_event_trajectories
            GROUP BY trajectory_id
            HAVING COUNT(*) > 1
            LIMIT 100
            """
        )

        duplicate_trajectory_grain = fetch_dicts(
            con,
            """
            SELECT
                canonical_person_id,
                school_stint_id,
                resolved_school_id,
                canonical_gender_code,
                season_type,
                canonical_event_code,
                COUNT(*) AS row_count
            FROM athlete_event_trajectories
            GROUP BY
                canonical_person_id,
                school_stint_id,
                resolved_school_id,
                canonical_gender_code,
                season_type,
                canonical_event_code
            HAVING COUNT(*) > 1
            LIMIT 100
            """
        )

        add_check(
            checks,
            "no_duplicate_eligible_season_years",
            not duplicate_period_years,
            len(duplicate_period_years),
            0,
        )
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
            "trajectory_athlete_count",
            counts["trajectory_athletes"]
            == EXPECTED_TRAJECTORY_ATHLETES,
            counts["trajectory_athletes"],
            EXPECTED_TRAJECTORY_ATHLETES,
        )
        add_check(
            checks,
            "trajectory_school_count",
            counts["trajectory_schools"]
            == EXPECTED_TRAJECTORY_SCHOOLS,
            counts["trajectory_schools"],
            EXPECTED_TRAJECTORY_SCHOOLS,
        )
        add_check(
            checks,
            "two_meet_exception_trajectory_count",
            counts["exception_trajectories"]
            == EXPECTED_EXCEPTION_TRAJECTORIES,
            counts["exception_trajectories"],
            EXPECTED_EXCEPTION_TRAJECTORIES,
        )
        add_check(
            checks,
            "supporting_events_excluded",
            counts["supporting_trajectories"]
            == EXPECTED_SUPPORTING_TRAJECTORIES,
            counts["supporting_trajectories"],
            EXPECTED_SUPPORTING_TRAJECTORIES,
        )
        add_check(
            checks,
            "trajectory_ids_unique",
            not duplicate_trajectory_ids,
            len(duplicate_trajectory_ids),
            0,
        )
        add_check(
            checks,
            "trajectory_grain_unique",
            not duplicate_trajectory_grain,
            len(duplicate_trajectory_grain),
            0,
        )
        add_check(
            checks,
            "all_trajectories_have_two_periods",
            quality["too_few_period_rows"] == 0,
            quality["too_few_period_rows"],
            0,
        )
        add_check(
            checks,
            "trajectory_season_years_unique",
            quality["duplicate_season_year_trajectory_rows"] == 0,
            quality["duplicate_season_year_trajectory_rows"],
            0,
        )
        add_check(
            checks,
            "baseline_precedes_endpoint",
            quality["nonpositive_elapsed_season_rows"] == 0,
            quality["nonpositive_elapsed_season_rows"],
            0,
        )
        add_check(
            checks,
            "elapsed_seasons_positive",
            quality["invalid_elapsed_season_rows"] == 0,
            quality["invalid_elapsed_season_rows"],
            0,
        )
        add_check(
            checks,
            "trajectory_scores_in_range",
            quality["score_out_of_range_rows"] == 0,
            quality["score_out_of_range_rows"],
            0,
        )
        add_check(
            checks,
            "observed_improvement_formula",
            quality["improvement_formula_mismatch_rows"] == 0,
            quality["improvement_formula_mismatch_rows"],
            0,
        )
        add_check(
            checks,
            "annualization_formula",
            quality["annualization_formula_mismatch_rows"] == 0,
            quality["annualization_formula_mismatch_rows"],
            0,
        )
        add_check(
            checks,
            "peak_level_valid",
            quality["invalid_peak_rows"] == 0,
            quality["invalid_peak_rows"],
            0,
        )
        add_check(
            checks,
            "transition_counts_reconcile",
            transition_count == expected_transition_count
            and quality["transition_count_mismatch_rows"] == 0,
            {
                "materialized_transitions": transition_count,
                "expected_transitions": expected_transition_count,
                "trajectory_mismatches":
                    quality["transition_count_mismatch_rows"],
            },
            {
                "materialized_transitions":
                    expected_transition_count,
                "expected_transitions":
                    expected_transition_count,
                "trajectory_mismatches": 0,
            },
        )
        add_check(
            checks,
            "improved_and_declined_populations_exist",
            counts["improved_trajectories"] > 0
            and counts["declined_trajectories"] > 0,
            {
                "improved": counts["improved_trajectories"],
                "declined": counts["declined_trajectories"],
            },
            "both greater than 0",
        )

        event_profiles = fetch_dicts(
            con,
            """
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(event_family) AS event_family,
                ANY_VALUE(frozen_role) AS frozen_role,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT canonical_person_id)
                    AS athlete_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(qualifying_period_count)
                    AS mean_period_count,
                AVG(elapsed_seasons)
                    AS mean_elapsed_seasons,
                AVG(baseline_stable_level)
                    AS mean_baseline_level,
                AVG(endpoint_stable_level)
                    AS mean_endpoint_level,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                MEDIAN(observed_improvement)
                    AS median_observed_improvement,
                APPROX_QUANTILE(
                    observed_improvement,
                    0.10
                ) AS improvement_q10,
                APPROX_QUANTILE(
                    observed_improvement,
                    0.25
                ) AS improvement_q25,
                APPROX_QUANTILE(
                    observed_improvement,
                    0.75
                ) AS improvement_q75,
                APPROX_QUANTILE(
                    observed_improvement,
                    0.90
                ) AS improvement_q90,
                AVG(annualized_observed_improvement)
                    AS mean_annualized_improvement,
                COUNT(*) FILTER (
                    WHERE observed_improvement > 0
                )::DOUBLE
                    / COUNT(*) AS improvement_rate
            FROM athlete_event_trajectories
            GROUP BY
                season_type,
                canonical_gender_code,
                canonical_event_code
            ORDER BY
                season_type,
                canonical_gender_code,
                canonical_event_code
            """
        )

        write_csv(
            OUTPUT_DIR / "trajectory_event_profiles.csv",
            event_profiles,
            [
                "season_type",
                "canonical_gender_code",
                "canonical_event_code",
                "canonical_event_name",
                "event_family",
                "frozen_role",
                "trajectory_count",
                "athlete_count",
                "school_count",
                "mean_period_count",
                "mean_elapsed_seasons",
                "mean_baseline_level",
                "mean_endpoint_level",
                "mean_observed_improvement",
                "median_observed_improvement",
                "improvement_q10",
                "improvement_q25",
                "improvement_q75",
                "improvement_q90",
                "mean_annualized_improvement",
                "improvement_rate",
            ],
        )

        duration_profiles = fetch_dicts(
            con,
            """
            SELECT
                elapsed_seasons,
                qualifying_period_count,
                trajectory_reliability_tier,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT canonical_person_id)
                    AS athlete_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(baseline_stable_level)
                    AS mean_baseline_level,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                MEDIAN(observed_improvement)
                    AS median_observed_improvement,
                AVG(annualized_observed_improvement)
                    AS mean_annualized_improvement,
                COUNT(*) FILTER (
                    WHERE observed_improvement > 0
                )::DOUBLE
                    / COUNT(*) AS improvement_rate
            FROM athlete_event_trajectories
            GROUP BY
                elapsed_seasons,
                qualifying_period_count,
                trajectory_reliability_tier
            ORDER BY
                elapsed_seasons,
                qualifying_period_count,
                trajectory_reliability_tier
            """
        )

        write_csv(
            OUTPUT_DIR / "trajectory_duration_profiles.csv",
            duration_profiles,
            [
                "elapsed_seasons",
                "qualifying_period_count",
                "trajectory_reliability_tier",
                "trajectory_count",
                "athlete_count",
                "school_count",
                "mean_baseline_level",
                "mean_observed_improvement",
                "median_observed_improvement",
                "mean_annualized_improvement",
                "improvement_rate",
            ],
        )

        baseline_bands = fetch_dicts(
            con,
            """
            WITH banded AS (
                SELECT
                    *,
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
                    ) AS baseline_level_band
                FROM athlete_event_trajectories
            )
            SELECT
                canonical_gender_code,
                season_type,
                event_family,
                baseline_level_band,
                COUNT(*) AS trajectory_count,
                AVG(baseline_stable_level)
                    AS mean_baseline_level,
                AVG(observed_improvement)
                    AS mean_observed_improvement,
                MEDIAN(observed_improvement)
                    AS median_observed_improvement,
                AVG(annualized_observed_improvement)
                    AS mean_annualized_improvement,
                COUNT(*) FILTER (
                    WHERE observed_improvement > 0
                )::DOUBLE
                    / COUNT(*) AS improvement_rate
            FROM banded
            GROUP BY
                canonical_gender_code,
                season_type,
                event_family,
                baseline_level_band
            ORDER BY
                canonical_gender_code,
                season_type,
                event_family,
                baseline_level_band
            """
        )

        write_csv(
            OUTPUT_DIR / "baseline_level_development_profiles.csv",
            baseline_bands,
            [
                "canonical_gender_code",
                "season_type",
                "event_family",
                "baseline_level_band",
                "trajectory_count",
                "mean_baseline_level",
                "mean_observed_improvement",
                "median_observed_improvement",
                "mean_annualized_improvement",
                "improvement_rate",
            ],
        )

        sample_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM athlete_event_trajectories
            ORDER BY
                ABS(observed_improvement) DESC,
                trajectory_id
            LIMIT 500
            """
        )

        write_csv(
            OUTPUT_DIR / "trajectory_samples.csv",
            sample_rows,
            list(sample_rows[0].keys()) if sample_rows else [],
        )

        summary_rows = [
            {
                "metric": "trajectory_rows",
                "value": counts["trajectory_rows"],
            },
            {
                "metric": "trajectory_athletes",
                "value": counts["trajectory_athletes"],
            },
            {
                "metric": "trajectory_schools",
                "value": counts["trajectory_schools"],
            },
            {
                "metric": "two_meet_exception_trajectories",
                "value": counts["exception_trajectories"],
            },
            {
                "metric": "consecutive_transitions",
                "value": transition_count,
            },
            {
                "metric": "improved_trajectories",
                "value": counts["improved_trajectories"],
            },
            {
                "metric": "declined_trajectories",
                "value": counts["declined_trajectories"],
            },
            {
                "metric": "unchanged_trajectories",
                "value": counts["unchanged_trajectories"],
            },
            {
                "metric": "mean_observed_improvement",
                "value": counts["mean_observed_improvement"],
            },
            {
                "metric": "median_observed_improvement",
                "value": counts["median_observed_improvement"],
            },
            {
                "metric": "mean_annualized_improvement",
                "value": counts["mean_annualized_improvement"],
            },
            {
                "metric": "median_annualized_improvement",
                "value": counts["median_annualized_improvement"],
            },
            {
                "metric": "minimum_observed_improvement",
                "value": counts["minimum_observed_improvement"],
            },
            {
                "metric": "maximum_observed_improvement",
                "value": counts["maximum_observed_improvement"],
            },
        ]

        write_csv(
            OUTPUT_DIR / "phase_5a_summary.csv",
            summary_rows,
            ["metric", "value"],
        )

    finally:
        con.close()

    input_hash_after = sha256_file(INPUT_DB)

    add_check(
        checks,
        "input_database_unchanged",
        input_hash_before == input_hash_after,
        input_hash_after,
        input_hash_before,
    )

    output_hash = sha256_file(OUTPUT_DB)

    write_csv(
        OUTPUT_DIR / "input_manifest.csv",
        [
            {
                "input_name": INPUT_DB.name,
                "path": str(INPUT_DB),
                "size_bytes": INPUT_DB.stat().st_size,
                "sha256_before": input_hash_before,
                "sha256_after": input_hash_after,
                "input_dataset_version": INPUT_DATASET_VERSION,
                "input_policy_version": INPUT_POLICY_VERSION,
            }
        ],
        [
            "input_name",
            "path",
            "size_bytes",
            "sha256_before",
            "sha256_after",
            "input_dataset_version",
            "input_policy_version",
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
                "trajectory_policy_version":
                    TRAJECTORY_POLICY_VERSION,
            }
        ],
        [
            "output_name",
            "path",
            "size_bytes",
            "sha256",
            "dataset_version",
            "trajectory_policy_version",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 5 PHASE 5A — OBSERVED DEVELOPMENT TRAJECTORIES",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "PRIMARY DEFINITION",
        "-" * 78,
        "Baseline: first eligible stable athlete-event period.",
        "Endpoint: last eligible stable athlete-event period.",
        "Observed improvement: endpoint level minus baseline level.",
        "Annualized improvement: observed improvement divided by",
        "elapsed same-season-type season years.",
        "All comparisons remain inside one school stint and event.",
        "",
        "RESULTS",
        "-" * 78,
        f"Trajectory rows: "
        f"{int(counts['trajectory_rows']):,}",
        f"Unique athletes: "
        f"{int(counts['trajectory_athletes']):,}",
        f"Schools represented: "
        f"{int(counts['trajectory_schools']):,}",
        f"Two-meet exception trajectories: "
        f"{int(counts['exception_trajectories']):,}",
        f"Consecutive period transitions: "
        f"{int(transition_count):,}",
        f"Improved trajectories: "
        f"{int(counts['improved_trajectories']):,}",
        f"Declined trajectories: "
        f"{int(counts['declined_trajectories']):,}",
        f"Mean observed improvement: "
        f"{float(counts['mean_observed_improvement']):.6f}",
        f"Median observed improvement: "
        f"{float(counts['median_observed_improvement']):.6f}",
        f"Mean annualized improvement: "
        f"{float(counts['mean_annualized_improvement']):.6f}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Observed development trajectories created."
            if not failed
            else "FAIL — Do not estimate expected improvement."
        ),
        "",
        "NEXT",
        "-" * 78,
        "Profile development by baseline level, event, gender, and duration.",
        "Then build an out-of-sample expected-improvement benchmark.",
    ]

    (OUTPUT_DIR / "phase_5a_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Trajectory rows: {int(counts['trajectory_rows']):,}"
    )
    print(
        f"Unique athletes: {int(counts['trajectory_athletes']):,}"
    )
    print(
        f"Schools represented: {int(counts['trajectory_schools']):,}"
    )
    print(
        "Two-meet exception trajectories: "
        f"{int(counts['exception_trajectories']):,}"
    )
    print(
        f"Consecutive transitions: {int(transition_count):,}"
    )
    print(
        "Mean observed improvement: "
        f"{float(counts['mean_observed_improvement']):.6f}"
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
    print("Next: profile and model expected improvement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
