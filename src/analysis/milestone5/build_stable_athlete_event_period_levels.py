#!/usr/bin/env python3
"""
Milestone 5 Phase 4F — Stable Athlete-Event-Period Levels

Builds robust period-level performance estimates from the frozen
performance-level dataset.

Primary methodology
-------------------
1. Use only primary-scoring-eligible performances.
2. Keep school stints, genders, events, season types, and season years separate.
3. Collapse multiple rounds/results from the same athlete-event meet to the
   best normalized score from that meet.
4. Estimate the period level using the average of the best three distinct-meet
   scores.
5. Preserve one- and two-meet estimates for coverage analysis, but require at
   least three distinct meets for primary trajectory eligibility.

This phase does not yet calculate improvement. It creates the stable inputs
needed for athlete development trajectories.
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
      "phase_4e_materialized_performance_levels/"
      "performance_levels_v1.duckdb"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4f_stable_athlete_event_period_levels"
)

OUTPUT_DB = OUTPUT_DIR / "athlete_event_period_levels_v1.duckdb"

DATASET_VERSION = "athlete_event_period_levels_v1_3"
INPUT_DATASET_VERSION = "performance_levels_v1"
POLICY_VERSION = "performance_level_policy_v1"
PRIMARY_MIN_DISTINCT_MEETS = 3

EXPECTED_INPUT_TOTAL_ROWS = 4_664_090
EXPECTED_INPUT_ELIGIBLE_ROWS = 4_664_041
EXPECTED_INPUT_QUARANTINED_ROWS = 49


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

    print("MILESTONE 5 PHASE 4F — STABLE ATHLETE-EVENT-PERIOD LEVELS")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Input database: {INPUT_DB}")
    print(f"Output database: {OUTPUT_DB}")
    print(
        "Primary minimum distinct meets: "
        f"{PRIMARY_MIN_DISTINCT_MEETS}"
    )

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
                AS source_levels (READ_ONLY)
            """
        )

        source_metadata = {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM source_levels.main.dataset_metadata
                """
            ).fetchall()
        }

        add_check(
            checks,
            "input_dataset_version_matches",
            source_metadata.get("dataset_version")
            == INPUT_DATASET_VERSION,
            source_metadata.get("dataset_version"),
            INPUT_DATASET_VERSION,
        )
        add_check(
            checks,
            "input_policy_version_matches",
            source_metadata.get("policy_version")
            == POLICY_VERSION,
            source_metadata.get("policy_version"),
            POLICY_VERSION,
        )

        source_counts = fetch_dicts(
            con,
            """
            SELECT
                COUNT(*) AS total_rows,
                COUNT(*) FILTER (
                    WHERE primary_scoring_eligible
                ) AS eligible_rows,
                COUNT(*) FILTER (
                    WHERE NOT primary_scoring_eligible
                ) AS quarantined_rows,
                COUNT(*) FILTER (
                    WHERE primary_scoring_eligible
                      AND performance_level IS NULL
                ) AS eligible_null_score_rows
            FROM source_levels.main.performance_levels
            """
        )[0]

        add_check(
            checks,
            "input_total_row_count",
            source_counts["total_rows"] == EXPECTED_INPUT_TOTAL_ROWS,
            source_counts["total_rows"],
            EXPECTED_INPUT_TOTAL_ROWS,
        )
        add_check(
            checks,
            "input_eligible_row_count",
            source_counts["eligible_rows"]
            == EXPECTED_INPUT_ELIGIBLE_ROWS,
            source_counts["eligible_rows"],
            EXPECTED_INPUT_ELIGIBLE_ROWS,
        )
        add_check(
            checks,
            "input_quarantined_row_count",
            source_counts["quarantined_rows"]
            == EXPECTED_INPUT_QUARANTINED_ROWS,
            source_counts["quarantined_rows"],
            EXPECTED_INPUT_QUARANTINED_ROWS,
        )
        add_check(
            checks,
            "input_has_no_eligible_null_scores",
            source_counts["eligible_null_score_rows"] == 0,
            source_counts["eligible_null_score_rows"],
            0,
        )

        con.execute(
            """
            CREATE TABLE eligible_performance_source AS
            SELECT
                canonical_person_performance_id,
                canonical_person_id,
                canonical_person_id AS athlete_id,
                athlete_name,
                canonical_gender_code,
                season_type,
                season_year,
                season_id,
                performance_date,
                meet_name,
                canonical_event_code,
                canonical_event_name,
                canonical_event_family AS event_family,
                school_stint_id,
                school_stint_id AS analytical_school_stint_id,
                resolved_team_id,
                resolved_school_id,
                primary_parsed_value,
                raw_mark,
                performance_level,
                raw_performance_ratio,
                scoring_path,
                performance_level_policy_version,
                performance_level_dataset_version
            FROM source_levels.main.performance_levels
            WHERE primary_scoring_eligible
              AND performance_level IS NOT NULL
            """
        )

        con.execute(
            """
            CREATE TABLE meet_best_levels AS
            WITH prepared AS (
                SELECT
                    *,
                    CASE
                        WHEN performance_date IS NULL
                         AND (
                            meet_name IS NULL
                            OR TRIM(meet_name) = ''
                         )
                        THEN
                            'performance|'
                            || canonical_person_performance_id
                        ELSE
                            COALESCE(
                                CAST(performance_date AS VARCHAR),
                                'unknown_date'
                            )
                            || '|'
                            || COALESCE(
                                NULLIF(TRIM(meet_name), ''),
                                'unknown_meet'
                            )
                    END AS meet_observation_id
                FROM eligible_performance_source
            ),
            ranked AS (
                SELECT
                    *,
                    COUNT(*) OVER (
                        PARTITION BY
                            canonical_person_id,
                            school_stint_id,
                            resolved_school_id,
                            canonical_gender_code,
                            season_type,
                            season_year,
                            season_id,
                            canonical_event_code,
                            meet_observation_id
                    ) AS source_performance_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            canonical_person_id,
                            school_stint_id,
                            resolved_school_id,
                            canonical_gender_code,
                            season_type,
                            season_year,
                            season_id,
                            canonical_event_code,
                            meet_observation_id
                        ORDER BY
                            performance_level DESC,
                            raw_performance_ratio DESC,
                            canonical_person_performance_id
                    ) AS meet_rank
                FROM prepared
            )
            SELECT
                canonical_person_performance_id
                    AS representative_performance_id,
                canonical_person_id,
                athlete_id,
                athlete_name,
                canonical_gender_code,
                season_type,
                season_year,
                season_id,
                canonical_event_code,
                canonical_event_name,
                event_family,
                school_stint_id,
                analytical_school_stint_id,
                resolved_team_id,
                resolved_school_id,
                meet_observation_id,
                performance_date,
                meet_name,
                primary_parsed_value,
                raw_mark,
                performance_level,
                raw_performance_ratio,
                source_performance_count,
                scoring_path
            FROM ranked
            WHERE meet_rank = 1
            """
        )

        con.execute(
            """
            CREATE TABLE athlete_event_period_levels AS
            WITH ranked_meets AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            canonical_person_id,
                            school_stint_id,
                            resolved_school_id,
                            canonical_gender_code,
                            season_type,
                            season_year,
                            season_id,
                            canonical_event_code
                        ORDER BY
                            performance_level DESC,
                            performance_date,
                            meet_name,
                            representative_performance_id
                    ) AS level_rank
                FROM meet_best_levels
            ),
            aggregated AS (
                SELECT
                    canonical_person_id,
                    ANY_VALUE(athlete_id) AS athlete_id,
                    ANY_VALUE(athlete_name) AS athlete_name,
                    school_stint_id,
                    ANY_VALUE(analytical_school_stint_id)
                        AS analytical_school_stint_id,
                    ANY_VALUE(resolved_team_id) AS resolved_team_id,
                    resolved_school_id,
                    canonical_gender_code,
                    season_type,
                    season_year,
                    season_id,
                    canonical_event_code,
                    ANY_VALUE(canonical_event_name)
                        AS canonical_event_name,
                    ANY_VALUE(event_family) AS event_family,
                    COUNT(*) AS distinct_meet_count,
                    SUM(source_performance_count)
                        AS source_performance_count,
                    COUNT(*) FILTER (
                        WHERE level_rank <= 3
                    ) AS selected_meet_count,
                    MAX(performance_level)
                        AS top_1_meet_level,
                    AVG(performance_level) FILTER (
                        WHERE level_rank <= 2
                    ) AS top_2_mean_level,
                    AVG(performance_level) FILTER (
                        WHERE level_rank <= 3
                    ) AS stable_performance_level,
                    MEDIAN(performance_level)
                        AS all_meet_median_level,
                    AVG(performance_level)
                        AS all_meet_mean_level,
                    STDDEV_SAMP(performance_level)
                        AS all_meet_score_sd,
                    MIN(performance_level)
                        AS minimum_meet_level,
                    MAX(performance_level)
                        AS maximum_meet_level,
                    MIN(performance_date)
                        AS first_performance_date,
                    MAX(performance_date)
                        AS last_performance_date,
                    DATE_DIFF(
                        'day',
                        MIN(performance_date),
                        MAX(performance_date)
                    ) AS observed_day_span,
                    STRING_AGG(
                        CASE
                            WHEN level_rank <= 3
                            THEN representative_performance_id
                            ELSE NULL
                        END,
                        '|'
                        ORDER BY level_rank
                    ) FILTER (
                        WHERE level_rank <= 3
                    ) AS selected_performance_ids,
                    STRING_AGG(
                        CASE
                            WHEN level_rank <= 3
                            THEN meet_observation_id
                            ELSE NULL
                        END,
                        '|'
                        ORDER BY level_rank
                    ) FILTER (
                        WHERE level_rank <= 3
                    ) AS selected_meet_ids
                FROM ranked_meets
                GROUP BY
                    canonical_person_id,
                    school_stint_id,
                    resolved_school_id,
                    canonical_gender_code,
                    season_type,
                    season_year,
                    season_id,
                    canonical_event_code
            )
            SELECT
                'aep_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        canonical_person_id,
                        school_stint_id,
                        resolved_school_id,
                        canonical_gender_code,
                        season_type,
                        CAST(season_year AS VARCHAR),
                        season_id,
                        canonical_event_code
                    )
                ) AS athlete_event_period_id,
                *,
                CASE
                    WHEN distinct_meet_count >= 5
                        THEN 'high'
                    WHEN distinct_meet_count >= 3
                        THEN 'standard'
                    WHEN distinct_meet_count = 2
                        THEN 'provisional_two_meet'
                    ELSE 'single_meet'
                END AS reliability_tier,
                distinct_meet_count >= 3
                    AS primary_trajectory_eligible,
                CASE
                    WHEN distinct_meet_count >= 3
                        THEN 'best_three_distinct_meets_mean'
                    WHEN distinct_meet_count = 2
                        THEN 'two_distinct_meets_mean_provisional'
                    ELSE 'single_distinct_meet_provisional'
                END AS estimation_method,
                'athlete_event_period_levels_v1_3'
                    AS dataset_version,
                'performance_level_policy_v1'
                    AS performance_level_policy_version
            FROM aggregated
            """
        )

        con.execute(
            """
            CREATE VIEW primary_athlete_event_period_levels AS
            SELECT *
            FROM athlete_event_period_levels
            WHERE primary_trajectory_eligible
            """
        )

        con.execute(
            """
            CREATE VIEW provisional_athlete_event_period_levels AS
            SELECT *
            FROM athlete_event_period_levels
            WHERE NOT primary_trajectory_eligible
            """
        )

        con.execute(
            """
            CREATE TABLE trajectory_readiness AS
            SELECT
                canonical_person_id,
                ANY_VALUE(athlete_id) AS athlete_id,
                ANY_VALUE(athlete_name) AS athlete_name,
                school_stint_id,
                resolved_school_id,
                canonical_gender_code,
                season_type,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(event_family) AS event_family,
                COUNT(*) AS total_period_count,
                COUNT(*) FILTER (
                    WHERE primary_trajectory_eligible
                ) AS primary_period_count,
                MIN(season_year) FILTER (
                    WHERE primary_trajectory_eligible
                ) AS first_primary_season_year,
                MAX(season_year) FILTER (
                    WHERE primary_trajectory_eligible
                ) AS last_primary_season_year,
                COUNT(*) FILTER (
                    WHERE primary_trajectory_eligible
                ) >= 2 AS trajectory_ready
            FROM athlete_event_period_levels
            GROUP BY
                canonical_person_id,
                school_stint_id,
                resolved_school_id,
                canonical_gender_code,
                season_type,
                canonical_event_code
            """
        )

        con.execute(
            """
            CREATE TABLE dataset_metadata AS
            SELECT
                'dataset_version' AS metadata_key,
                'athlete_event_period_levels_v1_3'
                    AS metadata_value
            UNION ALL
            SELECT
                'input_dataset_version',
                'performance_levels_v1'
            UNION ALL
            SELECT
                'performance_level_policy_version',
                'performance_level_policy_v1'
            UNION ALL
            SELECT
                'primary_min_distinct_meets',
                '3'
            UNION ALL
            SELECT
                'same_meet_rule',
                'retain_best_score_per_athlete_event_meet'
            UNION ALL
            SELECT
                'stable_level_method',
                'mean_best_three_distinct_meets'
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
                 FROM eligible_performance_source)
                    AS eligible_source_rows,
                (SELECT COUNT(*)
                 FROM meet_best_levels)
                    AS meet_best_rows,
                (SELECT COUNT(*)
                 FROM athlete_event_period_levels)
                    AS period_rows,
                (SELECT COUNT(*)
                 FROM primary_athlete_event_period_levels)
                    AS primary_period_rows,
                (SELECT COUNT(*)
                 FROM provisional_athlete_event_period_levels)
                    AS provisional_period_rows,
                (SELECT COUNT(*)
                 FROM trajectory_readiness
                 WHERE trajectory_ready)
                    AS trajectory_ready_segments,
                (SELECT COUNT(DISTINCT canonical_person_id)
                 FROM primary_athlete_event_period_levels)
                    AS primary_period_athletes,
                (SELECT COUNT(DISTINCT resolved_school_id)
                 FROM primary_athlete_event_period_levels)
                    AS primary_period_schools
            """
        )[0]

        quality = fetch_dicts(
            con,
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE stable_performance_level < 0
                       OR stable_performance_level > 100
                ) AS out_of_range_period_scores,
                COUNT(*) FILTER (
                    WHERE stable_performance_level
                        > top_1_meet_level + 1e-12
                ) AS stable_above_top1_rows,
                COUNT(*) FILTER (
                    WHERE distinct_meet_count >= 3
                      AND selected_meet_count <> 3
                ) AS invalid_primary_selected_count,
                COUNT(*) FILTER (
                    WHERE distinct_meet_count = 2
                      AND selected_meet_count <> 2
                ) AS invalid_two_meet_selected_count,
                COUNT(*) FILTER (
                    WHERE distinct_meet_count = 1
                      AND selected_meet_count <> 1
                ) AS invalid_single_meet_selected_count,
                COUNT(*) FILTER (
                    WHERE primary_trajectory_eligible
                      AND distinct_meet_count < 3
                ) AS invalid_primary_eligibility,
                COUNT(*) FILTER (
                    WHERE school_stint_id IS NULL
                       OR resolved_school_id IS NULL
                ) AS missing_school_context_rows,
                COUNT(*) FILTER (
                    WHERE first_performance_date
                        > last_performance_date
                ) AS reversed_date_rows
            FROM athlete_event_period_levels
            """
        )[0]

        duplicate_grain_rows = fetch_dicts(
            con,
            """
            SELECT
                canonical_person_id,
                school_stint_id,
                resolved_school_id,
                canonical_gender_code,
                season_type,
                season_year,
                season_id,
                canonical_event_code,
                COUNT(*) AS row_count
            FROM athlete_event_period_levels
            GROUP BY
                canonical_person_id,
                school_stint_id,
                resolved_school_id,
                canonical_gender_code,
                season_type,
                season_year,
                season_id,
                canonical_event_code
            HAVING COUNT(*) > 1
            LIMIT 100
            """
        )

        duplicate_ids = fetch_dicts(
            con,
            """
            SELECT
                athlete_event_period_id,
                COUNT(*) AS row_count
            FROM athlete_event_period_levels
            GROUP BY athlete_event_period_id
            HAVING COUNT(*) > 1
            LIMIT 100
            """
        )

        add_check(
            checks,
            "eligible_source_rows_reconcile",
            counts["eligible_source_rows"]
            == EXPECTED_INPUT_ELIGIBLE_ROWS,
            counts["eligible_source_rows"],
            EXPECTED_INPUT_ELIGIBLE_ROWS,
        )
        add_check(
            checks,
            "meet_collapse_does_not_expand_rows",
            counts["meet_best_rows"]
            <= counts["eligible_source_rows"],
            counts["meet_best_rows"],
            f"at most {counts['eligible_source_rows']}",
        )
        add_check(
            checks,
            "period_table_has_rows",
            counts["period_rows"] > 0,
            counts["period_rows"],
            "greater than 0",
        )
        add_check(
            checks,
            "period_grain_unique",
            not duplicate_grain_rows,
            len(duplicate_grain_rows),
            0,
        )
        add_check(
            checks,
            "period_ids_unique",
            not duplicate_ids,
            len(duplicate_ids),
            0,
        )
        add_check(
            checks,
            "all_period_scores_in_range",
            quality["out_of_range_period_scores"] == 0,
            quality["out_of_range_period_scores"],
            0,
        )
        add_check(
            checks,
            "stable_level_never_exceeds_best_meet",
            quality["stable_above_top1_rows"] == 0,
            quality["stable_above_top1_rows"],
            0,
        )
        add_check(
            checks,
            "primary_periods_use_three_meets",
            quality["invalid_primary_selected_count"] == 0,
            quality["invalid_primary_selected_count"],
            0,
        )
        add_check(
            checks,
            "two_meet_periods_use_both_meets",
            quality["invalid_two_meet_selected_count"] == 0,
            quality["invalid_two_meet_selected_count"],
            0,
        )
        add_check(
            checks,
            "single_meet_periods_use_one_meet",
            quality["invalid_single_meet_selected_count"] == 0,
            quality["invalid_single_meet_selected_count"],
            0,
        )
        add_check(
            checks,
            "primary_eligibility_requires_three_meets",
            quality["invalid_primary_eligibility"] == 0,
            quality["invalid_primary_eligibility"],
            0,
        )
        add_check(
            checks,
            "all_periods_have_school_context",
            quality["missing_school_context_rows"] == 0,
            quality["missing_school_context_rows"],
            0,
        )
        add_check(
            checks,
            "period_dates_not_reversed",
            quality["reversed_date_rows"] == 0,
            quality["reversed_date_rows"],
            0,
        )
        add_check(
            checks,
            "trajectory_ready_population_exists",
            counts["trajectory_ready_segments"] > 0,
            counts["trajectory_ready_segments"],
            "greater than 0",
        )

        meet_count_distribution = fetch_dicts(
            con,
            """
            SELECT
                CASE
                    WHEN distinct_meet_count >= 8 THEN '8+'
                    ELSE CAST(distinct_meet_count AS VARCHAR)
                END AS distinct_meet_bucket,
                COUNT(*) AS period_count,
                COUNT(DISTINCT canonical_person_id)
                    AS athlete_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(stable_performance_level)
                    AS mean_stable_level,
                MEDIAN(stable_performance_level)
                    AS median_stable_level,
                COUNT(*) FILTER (
                    WHERE primary_trajectory_eligible
                ) AS primary_period_count
            FROM athlete_event_period_levels
            GROUP BY 1
            ORDER BY
                CASE
                    WHEN distinct_meet_bucket = '8+'
                        THEN 8
                    ELSE CAST(
                        distinct_meet_bucket AS INTEGER
                    )
                END
            """
        )

        write_csv(
            OUTPUT_DIR / "meet_count_distribution.csv",
            meet_count_distribution,
            [
                "distinct_meet_bucket",
                "period_count",
                "athlete_count",
                "school_count",
                "mean_stable_level",
                "median_stable_level",
                "primary_period_count",
            ],
        )

        reliability_distribution = fetch_dicts(
            con,
            """
            SELECT
                reliability_tier,
                COUNT(*) AS period_count,
                COUNT(DISTINCT canonical_person_id)
                    AS athlete_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(distinct_meet_count)
                    AS mean_distinct_meets,
                AVG(stable_performance_level)
                    AS mean_stable_level
            FROM athlete_event_period_levels
            GROUP BY reliability_tier
            ORDER BY
                CASE reliability_tier
                    WHEN 'high' THEN 1
                    WHEN 'standard' THEN 2
                    WHEN 'provisional_two_meet' THEN 3
                    ELSE 4
                END
            """
        )

        write_csv(
            OUTPUT_DIR / "reliability_distribution.csv",
            reliability_distribution,
            [
                "reliability_tier",
                "period_count",
                "athlete_count",
                "school_count",
                "mean_distinct_meets",
                "mean_stable_level",
            ],
        )

        event_coverage = fetch_dicts(
            con,
            """
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(event_family) AS event_family,
                COUNT(*) AS period_count,
                COUNT(*) FILTER (
                    WHERE primary_trajectory_eligible
                ) AS primary_period_count,
                COUNT(DISTINCT canonical_person_id)
                    AS athlete_count,
                COUNT(DISTINCT canonical_person_id)
                    FILTER (
                        WHERE primary_trajectory_eligible
                    ) AS primary_athlete_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(distinct_meet_count)
                    AS mean_distinct_meets,
                AVG(stable_performance_level)
                    FILTER (
                        WHERE primary_trajectory_eligible
                    ) AS mean_primary_level,
                MEDIAN(stable_performance_level)
                    FILTER (
                        WHERE primary_trajectory_eligible
                    ) AS median_primary_level
            FROM athlete_event_period_levels
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
            OUTPUT_DIR / "event_period_coverage.csv",
            event_coverage,
            [
                "season_type",
                "canonical_gender_code",
                "canonical_event_code",
                "canonical_event_name",
                "event_family",
                "period_count",
                "primary_period_count",
                "athlete_count",
                "primary_athlete_count",
                "school_count",
                "mean_distinct_meets",
                "mean_primary_level",
                "median_primary_level",
            ],
        )

        season_coverage = fetch_dicts(
            con,
            """
            SELECT
                season_year,
                season_type,
                COUNT(*) AS period_count,
                COUNT(*) FILTER (
                    WHERE primary_trajectory_eligible
                ) AS primary_period_count,
                COUNT(DISTINCT canonical_person_id)
                    AS athlete_count,
                COUNT(DISTINCT canonical_person_id)
                    FILTER (
                        WHERE primary_trajectory_eligible
                    ) AS primary_athlete_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                AVG(distinct_meet_count)
                    AS mean_distinct_meets
            FROM athlete_event_period_levels
            GROUP BY season_year, season_type
            ORDER BY season_year, season_type
            """
        )

        write_csv(
            OUTPUT_DIR / "season_period_coverage.csv",
            season_coverage,
            [
                "season_year",
                "season_type",
                "period_count",
                "primary_period_count",
                "athlete_count",
                "primary_athlete_count",
                "school_count",
                "mean_distinct_meets",
            ],
        )

        readiness_summary = fetch_dicts(
            con,
            """
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                COUNT(*) AS athlete_school_event_segments,
                COUNT(*) FILTER (
                    WHERE trajectory_ready
                ) AS trajectory_ready_segments,
                COUNT(DISTINCT canonical_person_id)
                    FILTER (
                        WHERE trajectory_ready
                    ) AS trajectory_ready_athletes,
                COUNT(DISTINCT resolved_school_id)
                    FILTER (
                        WHERE trajectory_ready
                    ) AS trajectory_ready_schools,
                AVG(primary_period_count)
                    AS mean_primary_period_count
            FROM trajectory_readiness
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
            OUTPUT_DIR / "trajectory_readiness_by_event.csv",
            readiness_summary,
            [
                "season_type",
                "canonical_gender_code",
                "canonical_event_code",
                "canonical_event_name",
                "athlete_school_event_segments",
                "trajectory_ready_segments",
                "trajectory_ready_athletes",
                "trajectory_ready_schools",
                "mean_primary_period_count",
            ],
        )

        method_comparison = fetch_dicts(
            con,
            """
            SELECT
                reliability_tier,
                COUNT(*) AS period_count,
                AVG(top_1_meet_level)
                    AS mean_top_1,
                AVG(top_2_mean_level)
                    AS mean_top_2,
                AVG(stable_performance_level)
                    AS mean_top_3_or_available,
                AVG(
                    top_1_meet_level
                    - stable_performance_level
                ) AS mean_top1_minus_stable,
                MEDIAN(
                    top_1_meet_level
                    - stable_performance_level
                ) AS median_top1_minus_stable,
                APPROX_QUANTILE(
                    top_1_meet_level
                    - stable_performance_level,
                    0.90
                ) AS q90_top1_minus_stable
            FROM athlete_event_period_levels
            GROUP BY reliability_tier
            ORDER BY
                CASE reliability_tier
                    WHEN 'high' THEN 1
                    WHEN 'standard' THEN 2
                    WHEN 'provisional_two_meet' THEN 3
                    ELSE 4
                END
            """
        )

        write_csv(
            OUTPUT_DIR / "stable_method_comparison.csv",
            method_comparison,
            [
                "reliability_tier",
                "period_count",
                "mean_top_1",
                "mean_top_2",
                "mean_top_3_or_available",
                "mean_top1_minus_stable",
                "median_top1_minus_stable",
                "q90_top1_minus_stable",
            ],
        )

        sample_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM athlete_event_period_levels
            ORDER BY
                primary_trajectory_eligible DESC,
                distinct_meet_count DESC,
                stable_performance_level DESC,
                athlete_event_period_id
            LIMIT 500
            """
        )

        write_csv(
            OUTPUT_DIR / "athlete_event_period_samples.csv",
            sample_rows,
            list(sample_rows[0].keys()) if sample_rows else [],
        )

        summary_rows = [
            {
                "metric": "eligible_source_rows",
                "value": counts["eligible_source_rows"],
            },
            {
                "metric": "meet_best_rows",
                "value": counts["meet_best_rows"],
            },
            {
                "metric": "athlete_event_period_rows",
                "value": counts["period_rows"],
            },
            {
                "metric": "primary_period_rows",
                "value": counts["primary_period_rows"],
            },
            {
                "metric": "provisional_period_rows",
                "value": counts["provisional_period_rows"],
            },
            {
                "metric": "primary_period_athletes",
                "value": counts["primary_period_athletes"],
            },
            {
                "metric": "primary_period_schools",
                "value": counts["primary_period_schools"],
            },
            {
                "metric": "trajectory_ready_segments",
                "value": counts["trajectory_ready_segments"],
            },
            {
                "metric": "primary_min_distinct_meets",
                "value": PRIMARY_MIN_DISTINCT_MEETS,
            },
        ]

        write_csv(
            OUTPUT_DIR / "phase_4f_summary.csv",
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
                "policy_version": POLICY_VERSION,
            }
        ],
        [
            "input_name",
            "path",
            "size_bytes",
            "sha256_before",
            "sha256_after",
            "input_dataset_version",
            "policy_version",
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
                "policy_version": POLICY_VERSION,
            }
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
        "MILESTONE 5 PHASE 4F — STABLE ATHLETE-EVENT-PERIOD LEVELS",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "METHOD",
        "-" * 78,
        "Only primary-scoring-eligible performances are used.",
        "Multiple results from the same athlete-event meet are collapsed",
        "to the best normalized performance level from that meet.",
        "The stable period level is the mean of the best three distinct",
        "meets, or all available meets when fewer than three exist.",
        "Primary trajectory eligibility requires at least three distinct meets.",
        "",
        "RESULTS",
        "-" * 78,
        f"Eligible source performances: "
        f"{int(counts['eligible_source_rows']):,}",
        f"Distinct athlete-event meet observations: "
        f"{int(counts['meet_best_rows']):,}",
        f"Athlete-event-period rows: "
        f"{int(counts['period_rows']):,}",
        f"Primary period rows: "
        f"{int(counts['primary_period_rows']):,}",
        f"Provisional period rows: "
        f"{int(counts['provisional_period_rows']):,}",
        f"Athletes with a primary period: "
        f"{int(counts['primary_period_athletes']):,}",
        f"Schools with a primary period: "
        f"{int(counts['primary_period_schools']):,}",
        f"Trajectory-ready athlete-school-event segments: "
        f"{int(counts['trajectory_ready_segments']):,}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Stable athlete-event-period estimates created."
            if not failed
            else "FAIL — Do not build development trajectories."
        ),
        "",
        "NEXT",
        "-" * 78,
        "Review coverage by meet count and event.",
        "Then build athlete development trajectories from primary periods.",
    ]

    (OUTPUT_DIR / "phase_4f_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        "Eligible source performances: "
        f"{int(counts['eligible_source_rows']):,}"
    )
    print(
        "Distinct meet observations: "
        f"{int(counts['meet_best_rows']):,}"
    )
    print(
        "Athlete-event-period rows: "
        f"{int(counts['period_rows']):,}"
    )
    print(
        "Primary period rows: "
        f"{int(counts['primary_period_rows']):,}"
    )
    print(
        "Trajectory-ready segments: "
        f"{int(counts['trajectory_ready_segments']):,}"
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
    print("Next: review coverage and build development trajectories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
