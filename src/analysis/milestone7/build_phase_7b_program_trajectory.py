#!/usr/bin/env python3
"""Build Milestone 7 Phase 7B program trajectory and consistency products.

This publication consumes the two validated Phase 7A DuckDB files and creates
Enhanced Balanced Production program-level summaries. It does not retrain or
modify the Milestone 6 ranking model.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import duckdb


DATASET_VERSION = "seasonal_program_trends_v1"
PHASE_VERSION = "phase_7b_program_trajectory_v1"
MODEL_KEY = "enhanced_balanced_production"
MODEL_LABEL = "Enhanced Balanced Production"

DEFAULT_OVERALL_DB = Path(
    "data/processed/milestone7/seasonal_program_trends_v1/"
    "phase_7a_overall_trends/seasonal_program_trends_v1.duckdb"
)
DEFAULT_DETAIL_DB = Path(
    "data/processed/milestone7/seasonal_program_trends_v1/"
    "phase_7a_event_group_trends/seasonal_program_trends_v1.duckdb"
)
DEFAULT_OUTPUT_DIR = Path(
    "data/processed/milestone7/seasonal_program_trends_v1/"
    "phase_7b_program_trajectory"
)
OUTPUT_DB_NAME = "seasonal_program_trends_v1.duckdb"


@dataclass(frozen=True)
class Check:
    check_name: str
    status: str
    observed_value: object
    expected_value: object
    details: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build Enhanced Balanced Production program trajectory, "
            "consistency, and rise/fall summaries from Phase 7A."
        )
    )
    parser.add_argument(
        "--overall-db",
        type=Path,
        default=DEFAULT_OVERALL_DB,
        help="Phase 7A.1 overall-trends DuckDB file.",
    )
    parser.add_argument(
        "--event-group-db",
        type=Path,
        default=DEFAULT_DETAIL_DB,
        help="Phase 7A.2 event/group-trends DuckDB file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Phase 7B output directory.",
    )
    return parser.parse_args()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def scalar(connection: duckdb.DuckDBPyConnection, sql: str) -> object:
    row = connection.execute(sql).fetchone()
    return None if row is None else row[0]


def table_exists(
    connection: duckdb.DuckDBPyConnection,
    catalog_name: str,
    table_name: str,
) -> bool:
    count = scalar(
        connection,
        f"""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_catalog = '{catalog_name}'
          AND table_schema = 'main'
          AND table_name = '{table_name}'
        """,
    )
    return int(count or 0) == 1


def require_tables(
    connection: duckdb.DuckDBPyConnection,
    catalog_name: str,
    table_names: Iterable[str],
) -> None:
    missing = [
        name
        for name in table_names
        if not table_exists(connection, catalog_name, name)
    ]
    if missing:
        raise RuntimeError(
            f"Missing required tables in {catalog_name}: " + ", ".join(missing)
        )


def add_check(
    checks: list[Check],
    name: str,
    observed: object,
    expected: object,
    passed: bool,
    details: str,
) -> None:
    checks.append(
        Check(
            check_name=name,
            status="PASS" if passed else "FAIL",
            observed_value=observed,
            expected_value=expected,
            details=details,
        )
    )


def create_program_window_trajectory(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(
        f"""
        CREATE TABLE program_window_trajectory AS
        WITH base AS (
            SELECT
                model_key,
                model_label,
                model_role,
                is_official_primary,
                model_family,
                cohort_key,
                cohort_label,
                publication_tier,
                ranking_scope,
                gender_scope,
                resolved_school_id,
                school_name,
                state_code,
                city,
                conference_name,
                division_name,
                endpoint_year,
                season_type,
                endpoint_season_key,
                endpoint_season_label,
                endpoint_source_eligible,
                primary_metric_name,
                opportunity_adjusted_metric_name,
                window_years,
                window_start_year,
                window_end_year,
                observed_season_count,
                eligible_observation_count,
                expected_season_count,
                missing_season_count,
                coverage_rate,
                window_complete,
                mean_primary_metric,
                median_primary_metric,
                median_absolute_deviation_primary_metric,
                standard_deviation_primary_metric,
                minimum_primary_metric,
                maximum_primary_metric,
                first_primary_metric,
                last_primary_metric,
                first_to_last_primary_metric_change,
                primary_metric_slope_per_year,
                mean_opportunity_adjusted_metric,
                opportunity_adjusted_metric_slope_per_year,
                mean_rank_strength_percentile,
                rank_strength_slope_per_year,
                mean_scoring_breadth,
                scoring_breadth_slope_per_year,
                mean_athlete_unit_count,
                athlete_unit_count_slope_per_year,
                trend_status,
                slope_suppressed_for_low_observation_count,
                CASE
                    WHEN mean_primary_metric IS NULL
                      OR ABS(mean_primary_metric) < 1e-12
                    THEN NULL
                    ELSE primary_metric_slope_per_year
                         / ABS(mean_primary_metric)
                END AS normalized_primary_metric_slope,
                CASE
                    WHEN mean_primary_metric IS NULL
                      OR ABS(mean_primary_metric) < 1e-12
                    THEN NULL
                    ELSE standard_deviation_primary_metric
                         / ABS(mean_primary_metric)
                END AS primary_metric_coefficient_of_variation
            FROM overall_src.main.school_multiseason_trends
            WHERE model_key = '{MODEL_KEY}'
              AND window_years IN (3, 5)
        ),
        performance_scores AS (
            SELECT
                cohort_key,
                ranking_scope,
                gender_scope,
                resolved_school_id,
                endpoint_year,
                season_type,
                window_years,
                PERCENT_RANK() OVER (
                    PARTITION BY
                        cohort_key,
                        ranking_scope,
                        gender_scope,
                        endpoint_year,
                        season_type,
                        window_years
                    ORDER BY mean_rank_strength_percentile
                ) AS performance_percentile
            FROM base
            WHERE endpoint_source_eligible
              AND mean_rank_strength_percentile IS NOT NULL
        ),
        momentum_scores AS (
            SELECT
                cohort_key,
                ranking_scope,
                gender_scope,
                resolved_school_id,
                endpoint_year,
                season_type,
                window_years,
                PERCENT_RANK() OVER (
                    PARTITION BY
                        cohort_key,
                        ranking_scope,
                        gender_scope,
                        endpoint_year,
                        season_type,
                        window_years
                    ORDER BY rank_strength_slope_per_year
                ) AS momentum_percentile
            FROM base
            WHERE endpoint_source_eligible
              AND rank_strength_slope_per_year IS NOT NULL
        ),
        consistency_scores AS (
            SELECT
                cohort_key,
                ranking_scope,
                gender_scope,
                resolved_school_id,
                endpoint_year,
                season_type,
                window_years,
                1.0 - PERCENT_RANK() OVER (
                    PARTITION BY
                        cohort_key,
                        ranking_scope,
                        gender_scope,
                        endpoint_year,
                        season_type,
                        window_years
                    ORDER BY standard_deviation_primary_metric
                ) AS consistency_percentile
            FROM base
            WHERE endpoint_source_eligible
              AND standard_deviation_primary_metric IS NOT NULL
        )
        SELECT
            base.*,
            performance_scores.performance_percentile,
            momentum_scores.momentum_percentile,
            consistency_scores.consistency_percentile,
            CASE
                WHEN eligible_observation_count < 3
                  OR primary_metric_slope_per_year IS NULL
                  OR rank_strength_slope_per_year IS NULL
                    THEN 'insufficient_history'
                WHEN primary_metric_slope_per_year > 0
                 AND rank_strength_slope_per_year > 0
                    THEN 'rising_aligned'
                WHEN primary_metric_slope_per_year < 0
                 AND rank_strength_slope_per_year < 0
                    THEN 'falling_aligned'
                WHEN primary_metric_slope_per_year > 0
                 AND rank_strength_slope_per_year < 0
                    THEN 'score_up_rank_down'
                WHEN primary_metric_slope_per_year < 0
                 AND rank_strength_slope_per_year > 0
                    THEN 'score_down_rank_up'
                WHEN ABS(primary_metric_slope_per_year) < 1e-12
                 AND ABS(rank_strength_slope_per_year) < 1e-12
                    THEN 'stable'
                ELSE 'mixed'
            END AS trajectory_direction,
            CASE
                WHEN momentum_scores.momentum_percentile IS NULL
                    THEN 'unavailable'
                WHEN momentum_scores.momentum_percentile >= 0.75
                    THEN 'top_quartile_rising'
                WHEN momentum_scores.momentum_percentile <= 0.25
                    THEN 'bottom_quartile_momentum'
                ELSE 'middle_momentum'
            END AS momentum_tier,
            CASE
                WHEN consistency_scores.consistency_percentile IS NULL
                    THEN 'unavailable'
                WHEN consistency_scores.consistency_percentile >= 0.75
                    THEN 'high_consistency'
                WHEN consistency_scores.consistency_percentile <= 0.25
                    THEN 'high_variability'
                ELSE 'middle_consistency'
            END AS consistency_tier,
            '{DATASET_VERSION}' AS dataset_version,
            '{PHASE_VERSION}' AS phase_version
        FROM base
        LEFT JOIN performance_scores USING (
            cohort_key,
            ranking_scope,
            gender_scope,
            resolved_school_id,
            endpoint_year,
            season_type,
            window_years
        )
        LEFT JOIN momentum_scores USING (
            cohort_key,
            ranking_scope,
            gender_scope,
            resolved_school_id,
            endpoint_year,
            season_type,
            window_years
        )
        LEFT JOIN consistency_scores USING (
            cohort_key,
            ranking_scope,
            gender_scope,
            resolved_school_id,
            endpoint_year,
            season_type,
            window_years
        )
        ORDER BY
            cohort_key,
            ranking_scope,
            gender_scope,
            season_type,
            endpoint_year,
            window_years,
            resolved_school_id
        """
    )


def create_rise_fall_summary(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE program_rise_fall_summary AS
        WITH endpoints AS (
            SELECT
                model_key,
                model_label,
                cohort_key,
                cohort_label,
                publication_tier,
                ranking_scope,
                gender_scope,
                resolved_school_id,
                school_name,
                state_code,
                city,
                conference_name,
                division_name,
                season_type,
                MAX(current_season_year) AS endpoint_year
            FROM overall_src.main.school_season_overall_movement
            WHERE model_key = '{MODEL_KEY}'
            GROUP BY ALL
        ),
        horizons AS (
            SELECT 'recent_5_calendar_years' AS horizon_key, 5 AS window_years
            UNION ALL
            SELECT 'all_available' AS horizon_key, NULL::INTEGER AS window_years
        ),
        aggregated AS (
            SELECT
                endpoints.model_key,
                endpoints.model_label,
                endpoints.cohort_key,
                endpoints.cohort_label,
                endpoints.publication_tier,
                endpoints.ranking_scope,
                endpoints.gender_scope,
                endpoints.resolved_school_id,
                endpoints.school_name,
                endpoints.state_code,
                endpoints.city,
                endpoints.conference_name,
                endpoints.division_name,
                endpoints.season_type,
                endpoints.endpoint_year,
                horizons.horizon_key,
                horizons.window_years,
                COUNT(*) FILTER (WHERE movement.is_comparable)
                    AS comparable_transition_count,
                COUNT(*) FILTER (
                    WHERE movement.is_comparable
                      AND movement.rank_strength_delta > 0
                ) AS improving_transition_count,
                COUNT(*) FILTER (
                    WHERE movement.is_comparable
                      AND movement.rank_strength_delta < 0
                ) AS declining_transition_count,
                COUNT(*) FILTER (
                    WHERE movement.is_comparable
                      AND ABS(movement.rank_strength_delta) < 1e-12
                ) AS flat_transition_count,
                AVG(movement.rank_strength_delta) FILTER (
                    WHERE movement.is_comparable
                ) AS mean_rank_strength_delta,
                MEDIAN(movement.rank_strength_delta) FILTER (
                    WHERE movement.is_comparable
                ) AS median_rank_strength_delta,
                AVG(movement.primary_metric_delta) FILTER (
                    WHERE movement.is_comparable
                ) AS mean_primary_metric_delta,
                MAX(movement.rank_strength_delta) FILTER (
                    WHERE movement.is_comparable
                ) AS best_rank_strength_gain,
                MIN(movement.rank_strength_delta) FILTER (
                    WHERE movement.is_comparable
                ) AS worst_rank_strength_loss,
                MAX(movement.current_season_year) FILTER (
                    WHERE movement.is_comparable
                ) AS latest_comparable_year,
                ARG_MAX(
                    movement.rank_strength_delta,
                    movement.current_season_year
                ) FILTER (
                    WHERE movement.is_comparable
                ) AS latest_rank_strength_delta,
                ARG_MAX(
                    movement.primary_metric_delta,
                    movement.current_season_year
                ) FILTER (
                    WHERE movement.is_comparable
                ) AS latest_primary_metric_delta
            FROM endpoints
            CROSS JOIN horizons
            LEFT JOIN overall_src.main.school_season_overall_movement movement
              ON movement.model_key = endpoints.model_key
             AND movement.cohort_key = endpoints.cohort_key
             AND movement.ranking_scope = endpoints.ranking_scope
             AND movement.gender_scope = endpoints.gender_scope
             AND movement.resolved_school_id = endpoints.resolved_school_id
             AND movement.season_type = endpoints.season_type
             AND (
                    horizons.window_years IS NULL
                    OR movement.current_season_year BETWEEN
                        endpoints.endpoint_year - horizons.window_years + 1
                        AND endpoints.endpoint_year
                 )
            GROUP BY ALL
        )
        SELECT
            *,
            CASE
                WHEN comparable_transition_count = 0 THEN NULL
                ELSE improving_transition_count
                     / CAST(comparable_transition_count AS DOUBLE)
            END AS improvement_rate,
            improving_transition_count - declining_transition_count
                AS net_improving_transitions,
            CASE
                WHEN comparable_transition_count = 0
                    THEN 'no_comparable_history'
                WHEN improving_transition_count > declining_transition_count
                    THEN 'more_improving_than_declining'
                WHEN improving_transition_count < declining_transition_count
                    THEN 'more_declining_than_improving'
                ELSE 'balanced_rise_fall'
            END AS rise_fall_status,
            '{DATASET_VERSION}' AS dataset_version,
            '{PHASE_VERSION}' AS phase_version
        FROM aggregated
        ORDER BY
            cohort_key,
            ranking_scope,
            gender_scope,
            season_type,
            resolved_school_id,
            horizon_key
        """
    )


def create_latest_snapshot(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE program_latest_snapshot AS
        WITH latest AS (
            SELECT *
            FROM overall_src.main.school_season_overall_base
            WHERE model_key = '{MODEL_KEY}'
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY
                    cohort_key,
                    ranking_scope,
                    gender_scope,
                    resolved_school_id,
                    season_type
                ORDER BY season_year DESC
            ) = 1
        ),
        latest_movement AS (
            SELECT *
            FROM overall_src.main.school_season_overall_movement
            WHERE model_key = '{MODEL_KEY}'
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY
                    cohort_key,
                    ranking_scope,
                    gender_scope,
                    resolved_school_id,
                    season_type
                ORDER BY current_season_year DESC
            ) = 1
        ),
        trajectory_3 AS (
            SELECT * FROM program_window_trajectory WHERE window_years = 3
        ),
        trajectory_5 AS (
            SELECT * FROM program_window_trajectory WHERE window_years = 5
        )
        SELECT
            latest.model_key,
            latest.model_label,
            latest.cohort_key,
            latest.cohort_label,
            latest.publication_tier,
            latest.ranking_scope,
            latest.gender_scope,
            latest.resolved_school_id,
            latest.school_name,
            latest.state_code,
            latest.city,
            latest.conference_name,
            latest.division_name,
            latest.season_year AS latest_season_year,
            latest.season_type,
            latest.season_key AS latest_season_key,
            latest.season_label AS latest_season_label,
            latest.source_eligible,
            latest.primary_metric_name,
            latest.primary_metric_value,
            latest.opportunity_adjusted_metric_name,
            latest.opportunity_adjusted_metric_value,
            latest.source_rank,
            latest.ranked_school_count,
            latest.rank_strength_percentile,
            latest.scoring_breadth,
            latest.athlete_unit_count,
            latest_movement.comparison_status AS latest_yoy_status,
            latest_movement.primary_metric_delta AS latest_yoy_primary_delta,
            latest_movement.rank_improvement AS latest_yoy_rank_improvement,
            latest_movement.rank_strength_delta AS latest_yoy_rank_strength_delta,
            trajectory_3.trajectory_direction AS trajectory_3y,
            trajectory_3.momentum_tier AS momentum_tier_3y,
            trajectory_3.consistency_tier AS consistency_tier_3y,
            trajectory_3.rank_strength_slope_per_year
                AS rank_strength_slope_3y,
            trajectory_3.momentum_percentile AS momentum_percentile_3y,
            trajectory_3.performance_percentile
                AS performance_percentile_3y,
            trajectory_5.trajectory_direction AS trajectory_5y,
            trajectory_5.momentum_tier AS momentum_tier_5y,
            trajectory_5.consistency_tier AS consistency_tier_5y,
            trajectory_5.rank_strength_slope_per_year
                AS rank_strength_slope_5y,
            trajectory_5.momentum_percentile AS momentum_percentile_5y,
            trajectory_5.performance_percentile
                AS performance_percentile_5y,
            '{DATASET_VERSION}' AS dataset_version,
            '{PHASE_VERSION}' AS phase_version
        FROM latest
        LEFT JOIN latest_movement
          ON latest_movement.cohort_key = latest.cohort_key
         AND latest_movement.ranking_scope = latest.ranking_scope
         AND latest_movement.gender_scope = latest.gender_scope
         AND latest_movement.resolved_school_id = latest.resolved_school_id
         AND latest_movement.season_type = latest.season_type
         AND latest_movement.current_season_year = latest.season_year
        LEFT JOIN trajectory_3
          ON trajectory_3.cohort_key = latest.cohort_key
         AND trajectory_3.ranking_scope = latest.ranking_scope
         AND trajectory_3.gender_scope = latest.gender_scope
         AND trajectory_3.resolved_school_id = latest.resolved_school_id
         AND trajectory_3.season_type = latest.season_type
         AND trajectory_3.endpoint_year = latest.season_year
        LEFT JOIN trajectory_5
          ON trajectory_5.cohort_key = latest.cohort_key
         AND trajectory_5.ranking_scope = latest.ranking_scope
         AND trajectory_5.gender_scope = latest.gender_scope
         AND trajectory_5.resolved_school_id = latest.resolved_school_id
         AND trajectory_5.season_type = latest.season_type
         AND trajectory_5.endpoint_year = latest.season_year
        ORDER BY
            cohort_key,
            ranking_scope,
            gender_scope,
            season_type,
            source_rank,
            school_name
        """
    )


def create_leaderboard(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE program_trajectory_leaderboard AS
        WITH latest_partition AS (
            SELECT
                cohort_key,
                ranking_scope,
                gender_scope,
                season_type,
                window_years,
                MAX(endpoint_year) AS endpoint_year
            FROM program_window_trajectory
            GROUP BY ALL
        ),
        latest_rows AS (
            SELECT trajectory.*
            FROM program_window_trajectory trajectory
            JOIN latest_partition USING (
                cohort_key,
                ranking_scope,
                gender_scope,
                season_type,
                window_years,
                endpoint_year
            )
            WHERE trajectory.endpoint_source_eligible
        )
        SELECT
            latest_rows.*,
            CASE
                WHEN momentum_percentile IS NULL THEN NULL
                ELSE DENSE_RANK() OVER (
                    PARTITION BY
                        cohort_key,
                        ranking_scope,
                        gender_scope,
                        season_type,
                        window_years,
                        endpoint_year
                    ORDER BY momentum_percentile DESC, school_name
                )
            END AS momentum_rank,
            CASE
                WHEN performance_percentile IS NULL THEN NULL
                ELSE DENSE_RANK() OVER (
                    PARTITION BY
                        cohort_key,
                        ranking_scope,
                        gender_scope,
                        season_type,
                        window_years,
                        endpoint_year
                    ORDER BY performance_percentile DESC, school_name
                )
            END AS performance_rank,
            CASE
                WHEN consistency_percentile IS NULL THEN NULL
                ELSE DENSE_RANK() OVER (
                    PARTITION BY
                        cohort_key,
                        ranking_scope,
                        gender_scope,
                        season_type,
                        window_years,
                        endpoint_year
                    ORDER BY consistency_percentile DESC, school_name
                )
            END AS consistency_rank
        FROM latest_rows
        ORDER BY
            cohort_key,
            ranking_scope,
            gender_scope,
            season_type,
            window_years,
            momentum_rank NULLS LAST,
            school_name
        """
    )


def create_group_profile(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE program_group_profile AS
        WITH source_rows AS (
            SELECT *
            FROM detail_src.main.school_group_multiseason_trends
            WHERE model_key = '{MODEL_KEY}'
              AND window_years IN (3, 5)
        ),
        latest_partition AS (
            SELECT
                cohort_key,
                gender_scope,
                season_type,
                window_years,
                MAX(endpoint_year) AS endpoint_year
            FROM source_rows
            GROUP BY ALL
        ),
        latest_rows AS (
            SELECT source_rows.*
            FROM source_rows
            JOIN latest_partition USING (
                cohort_key,
                gender_scope,
                season_type,
                window_years,
                endpoint_year
            )
        )
        SELECT
            model_key,
            model_label,
            is_official_primary,
            cohort_key,
            cohort_label,
            publication_tier,
            gender_scope,
            resolved_school_id,
            school_name,
            state_code,
            city,
            conference_name,
            division_name,
            endpoint_year,
            season_type,
            endpoint_season_key,
            endpoint_season_label,
            window_years,
            COUNT(DISTINCT balanced_group_key) AS observed_group_count,
            7 AS frozen_taxonomy_group_count,
            COUNT(DISTINCT balanced_group_key) / 7.0
                AS frozen_taxonomy_coverage_rate,
            COUNT(*) FILTER (
                WHERE rank_strength_slope_per_year > 0
            ) AS rising_group_count,
            COUNT(*) FILTER (
                WHERE rank_strength_slope_per_year < 0
            ) AS declining_group_count,
            COUNT(*) FILTER (
                WHERE rank_strength_slope_per_year IS NULL
            ) AS insufficient_history_group_count,
            AVG(mean_rank_strength_percentile)
                AS mean_group_rank_strength,
            AVG(rank_strength_slope_per_year)
                AS mean_group_rank_strength_slope,
            ARG_MAX(
                balanced_group_label,
                mean_rank_strength_percentile
            ) AS strongest_group,
            MAX(mean_rank_strength_percentile)
                AS strongest_group_rank_strength,
            ARG_MIN(
                balanced_group_label,
                mean_rank_strength_percentile
            ) AS weakest_group,
            MIN(mean_rank_strength_percentile)
                AS weakest_group_rank_strength,
            ARG_MAX(
                balanced_group_label,
                rank_strength_slope_per_year
            ) AS fastest_rising_group,
            MAX(rank_strength_slope_per_year)
                AS fastest_rising_group_slope,
            ARG_MIN(
                balanced_group_label,
                rank_strength_slope_per_year
            ) AS fastest_declining_group,
            MIN(rank_strength_slope_per_year)
                AS fastest_declining_group_slope,
            CASE
                WHEN COUNT(DISTINCT balanced_group_key) = 0
                    THEN 'no_group_evidence'
                WHEN COUNT(DISTINCT balanced_group_key) < 4
                    THEN 'limited_group_coverage'
                WHEN COUNT(DISTINCT balanced_group_key) < 7
                    THEN 'partial_group_coverage'
                ELSE 'full_taxonomy_coverage'
            END AS group_profile_status,
            '{DATASET_VERSION}' AS dataset_version,
            '{PHASE_VERSION}' AS phase_version
        FROM latest_rows
        GROUP BY ALL
        ORDER BY
            cohort_key,
            gender_scope,
            season_type,
            window_years,
            school_name
        """
    )


def create_event_profile(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE program_event_profile AS
        WITH source_rows AS (
            SELECT *
            FROM detail_src.main.school_event_multiseason_trends
            WHERE model_key = '{MODEL_KEY}'
              AND window_years IN (3, 5)
        ),
        latest_partition AS (
            SELECT
                cohort_key,
                gender_scope,
                season_type,
                window_years,
                MAX(endpoint_year) AS endpoint_year
            FROM source_rows
            GROUP BY ALL
        ),
        latest_rows AS (
            SELECT source_rows.*
            FROM source_rows
            JOIN latest_partition USING (
                cohort_key,
                gender_scope,
                season_type,
                window_years,
                endpoint_year
            )
        ),
        event_universe AS (
            SELECT
                cohort_key,
                gender_scope,
                season_type,
                window_years,
                endpoint_year,
                COUNT(DISTINCT canonical_event_code)
                    AS available_event_count
            FROM latest_rows
            GROUP BY ALL
        )
        SELECT
            rows.model_key,
            rows.model_label,
            rows.is_official_primary,
            rows.cohort_key,
            rows.cohort_label,
            rows.publication_tier,
            rows.gender_scope,
            rows.resolved_school_id,
            rows.school_name,
            rows.state_code,
            rows.city,
            rows.conference_name,
            rows.division_name,
            rows.endpoint_year,
            rows.season_type,
            rows.endpoint_season_key,
            rows.endpoint_season_label,
            rows.window_years,
            COUNT(DISTINCT rows.canonical_event_code)
                AS observed_event_count,
            MAX(universe.available_event_count) AS available_event_count,
            COUNT(DISTINCT rows.canonical_event_code)
                / NULLIF(CAST(MAX(universe.available_event_count) AS DOUBLE), 0.0)
                AS event_coverage_rate,
            COUNT(*) FILTER (
                WHERE rows.rank_strength_slope_per_year > 0
            ) AS rising_event_count,
            COUNT(*) FILTER (
                WHERE rows.rank_strength_slope_per_year < 0
            ) AS declining_event_count,
            COUNT(*) FILTER (
                WHERE rows.rank_strength_slope_per_year IS NULL
            ) AS insufficient_history_event_count,
            AVG(rows.mean_rank_strength_percentile)
                AS mean_event_rank_strength,
            AVG(rows.rank_strength_slope_per_year)
                AS mean_event_rank_strength_slope,
            ARG_MAX(
                rows.canonical_event_name,
                rows.mean_rank_strength_percentile
            ) AS strongest_event,
            MAX(rows.mean_rank_strength_percentile)
                AS strongest_event_rank_strength,
            ARG_MAX(
                rows.canonical_event_name,
                rows.rank_strength_slope_per_year
            ) AS fastest_rising_event,
            MAX(rows.rank_strength_slope_per_year)
                AS fastest_rising_event_slope,
            ARG_MIN(
                rows.canonical_event_name,
                rows.rank_strength_slope_per_year
            ) AS fastest_declining_event,
            MIN(rows.rank_strength_slope_per_year)
                AS fastest_declining_event_slope,
            '{DATASET_VERSION}' AS dataset_version,
            '{PHASE_VERSION}' AS phase_version
        FROM latest_rows rows
        JOIN event_universe universe USING (
            cohort_key,
            gender_scope,
            season_type,
            window_years,
            endpoint_year
        )
        GROUP BY ALL
        ORDER BY
            rows.cohort_key,
            rows.gender_scope,
            rows.season_type,
            rows.window_years,
            rows.school_name
        """
    )


def create_comparison_snapshot(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE program_comparison_snapshot AS
        SELECT
            leaderboard.model_key,
            leaderboard.model_label,
            leaderboard.cohort_key,
            leaderboard.cohort_label,
            leaderboard.publication_tier,
            leaderboard.ranking_scope,
            leaderboard.gender_scope,
            leaderboard.resolved_school_id,
            leaderboard.school_name,
            leaderboard.state_code,
            leaderboard.city,
            leaderboard.conference_name,
            leaderboard.division_name,
            leaderboard.endpoint_year,
            leaderboard.season_type,
            leaderboard.endpoint_season_key,
            leaderboard.endpoint_season_label,
            leaderboard.window_years,
            leaderboard.mean_primary_metric,
            leaderboard.mean_rank_strength_percentile,
            leaderboard.rank_strength_slope_per_year,
            leaderboard.performance_percentile,
            leaderboard.momentum_percentile,
            leaderboard.consistency_percentile,
            leaderboard.trajectory_direction,
            leaderboard.momentum_tier,
            leaderboard.consistency_tier,
            leaderboard.momentum_rank,
            leaderboard.performance_rank,
            leaderboard.consistency_rank,
            groups.observed_group_count,
            groups.frozen_taxonomy_coverage_rate,
            groups.strongest_group,
            groups.fastest_rising_group,
            groups.fastest_declining_group,
            events.observed_event_count,
            events.available_event_count,
            events.event_coverage_rate,
            events.strongest_event,
            events.fastest_rising_event,
            events.fastest_declining_event,
            leaderboard.dataset_version,
            leaderboard.phase_version
        FROM program_trajectory_leaderboard leaderboard
        LEFT JOIN program_group_profile groups
          ON groups.cohort_key = leaderboard.cohort_key
         AND groups.gender_scope = leaderboard.gender_scope
         AND groups.resolved_school_id = leaderboard.resolved_school_id
         AND groups.endpoint_year = leaderboard.endpoint_year
         AND groups.season_type = leaderboard.season_type
         AND groups.window_years = leaderboard.window_years
        LEFT JOIN program_event_profile events
          ON events.cohort_key = leaderboard.cohort_key
         AND events.gender_scope = leaderboard.gender_scope
         AND events.resolved_school_id = leaderboard.resolved_school_id
         AND events.endpoint_year = leaderboard.endpoint_year
         AND events.season_type = leaderboard.season_type
         AND events.window_years = leaderboard.window_years
        ORDER BY
            leaderboard.cohort_key,
            leaderboard.ranking_scope,
            leaderboard.gender_scope,
            leaderboard.season_type,
            leaderboard.window_years,
            leaderboard.momentum_rank NULLS LAST,
            leaderboard.school_name
        """
    )


def create_methodology(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE program_trajectory_methodology AS
        SELECT * FROM (
            VALUES
                (
                    1,
                    'official_model',
                    '{MODEL_LABEL}',
                    'Phase 7B publishes only the official Enhanced Balanced Production model.'
                ),
                (
                    2,
                    'trajectory_alignment',
                    'sign agreement',
                    'Rising and falling labels require the primary-score slope and rank-strength slope to point in the same direction.'
                ),
                (
                    3,
                    'minimum_trend_history',
                    '3 eligible observations',
                    'Slope-based classifications remain unavailable below three eligible observations.'
                ),
                (
                    4,
                    'consistency',
                    'within-partition percentile',
                    'Consistency compares primary-score volatility only among schools in the same cohort, scope, endpoint, season type, and window.'
                ),
                (
                    5,
                    'rise_fall',
                    'exact comparable year-over-year rows',
                    'Rise/fall counts use only exact prior-calendar-year, same-season-type comparisons already validated in Phase 7A.'
                ),
                (
                    6,
                    'missing_seasons',
                    'no fabrication',
                    'Missing seasons are retained as coverage gaps; no interpolation, zero fill, or carry-forward is used.'
                ),
                (
                    7,
                    'group_taxonomy',
                    'seven frozen groups',
                    'Group coverage is measured against the seven-group production taxonomy even when a group lacks publishable source evidence.'
                )
        ) AS methodology(
            display_order,
            methodology_key,
            methodology_value,
            explanation
        )
        ORDER BY display_order
        """
    )


def run_checks(
    connection: duckdb.DuckDBPyConnection,
    overall_hash_before: str,
    detail_hash_before: str,
    overall_db: Path,
    detail_db: Path,
) -> list[Check]:
    checks: list[Check] = []

    overall_failed = int(
        scalar(
            connection,
            "SELECT COUNT(*) FROM overall_src.main.hard_checks WHERE status <> 'PASS'",
        )
        or 0
    )
    add_check(
        checks,
        "phase_7a_overall_source_passed",
        overall_failed,
        0,
        overall_failed == 0,
        "Phase 7A.1 must have no failed source checks.",
    )

    detail_failed = int(
        scalar(
            connection,
            "SELECT COUNT(*) FROM detail_src.main.hard_checks WHERE status <> 'PASS'",
        )
        or 0
    )
    add_check(
        checks,
        "phase_7a_event_group_source_passed",
        detail_failed,
        0,
        detail_failed == 0,
        "Phase 7A.2 must have no failed source checks.",
    )

    source_trajectory_rows = int(
        scalar(
            connection,
            f"""
            SELECT COUNT(*)
            FROM overall_src.main.school_multiseason_trends
            WHERE model_key = '{MODEL_KEY}'
              AND window_years IN (3, 5)
            """,
        )
        or 0
    )
    output_trajectory_rows = int(
        scalar(connection, "SELECT COUNT(*) FROM program_window_trajectory") or 0
    )
    add_check(
        checks,
        "trajectory_rows_reconcile_to_phase_7a",
        output_trajectory_rows,
        source_trajectory_rows,
        output_trajectory_rows == source_trajectory_rows,
        "Every Enhanced 3-year and 5-year overall trend row is retained.",
    )

    model_count = int(
        scalar(
            connection,
            "SELECT COUNT(DISTINCT model_key) FROM program_window_trajectory",
        )
        or 0
    )
    model_key = scalar(
        connection,
        "SELECT MIN(model_key) FROM program_window_trajectory",
    )
    add_check(
        checks,
        "enhanced_is_exclusive_model",
        f"{model_count}:{model_key}",
        f"1:{MODEL_KEY}",
        model_count == 1 and model_key == MODEL_KEY,
        "Phase 7B is Enhanced Balanced Production only.",
    )

    duplicate_trajectory = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    cohort_key,
                    ranking_scope,
                    gender_scope,
                    resolved_school_id,
                    endpoint_year,
                    season_type,
                    window_years,
                    COUNT(*) AS row_count
                FROM program_window_trajectory
                GROUP BY ALL
                HAVING COUNT(*) > 1
            )
            """,
        )
        or 0
    )
    add_check(
        checks,
        "trajectory_keys_unique",
        duplicate_trajectory,
        0,
        duplicate_trajectory == 0,
        "Program trajectory keys are unique.",
    )

    invalid_windows = int(
        scalar(
            connection,
            "SELECT COUNT(*) FROM program_window_trajectory WHERE window_years NOT IN (3, 5)",
        )
        or 0
    )
    add_check(
        checks,
        "only_three_and_five_year_windows",
        invalid_windows,
        0,
        invalid_windows == 0,
        "Only the frozen three- and five-calendar-year windows are published.",
    )

    invalid_percentiles = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM program_window_trajectory
            WHERE performance_percentile NOT BETWEEN 0 AND 1
               OR momentum_percentile NOT BETWEEN 0 AND 1
               OR consistency_percentile NOT BETWEEN 0 AND 1
            """,
        )
        or 0
    )
    add_check(
        checks,
        "trajectory_percentiles_in_bounds",
        invalid_percentiles,
        0,
        invalid_percentiles == 0,
        "Performance, momentum, and consistency percentiles are bounded by zero and one.",
    )

    invalid_low_history = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM program_window_trajectory
            WHERE eligible_observation_count < 3
              AND trajectory_direction <> 'insufficient_history'
            """,
        )
        or 0
    )
    add_check(
        checks,
        "low_history_trajectory_suppressed",
        invalid_low_history,
        0,
        invalid_low_history == 0,
        "Slope-based direction is suppressed below three eligible observations.",
    )

    snapshot_duplicates = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    cohort_key,
                    ranking_scope,
                    gender_scope,
                    resolved_school_id,
                    season_type,
                    COUNT(*) AS row_count
                FROM program_latest_snapshot
                GROUP BY ALL
                HAVING COUNT(*) > 1
            )
            """,
        )
        or 0
    )
    add_check(
        checks,
        "latest_snapshot_keys_unique",
        snapshot_duplicates,
        0,
        snapshot_duplicates == 0,
        "Each school has at most one latest snapshot per overall partition and season type.",
    )

    invalid_rise_fall = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM program_rise_fall_summary
            WHERE comparable_transition_count < 0
               OR improving_transition_count < 0
               OR declining_transition_count < 0
               OR flat_transition_count < 0
               OR improving_transition_count
                    + declining_transition_count
                    + flat_transition_count
                    > comparable_transition_count
               OR improvement_rate NOT BETWEEN 0 AND 1
            """,
        )
        or 0
    )
    add_check(
        checks,
        "rise_fall_counts_valid",
        invalid_rise_fall,
        0,
        invalid_rise_fall == 0,
        "Rise/fall counts and rates are internally valid.",
    )

    invalid_group_coverage = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM program_group_profile
            WHERE observed_group_count < 0
               OR observed_group_count > frozen_taxonomy_group_count
               OR frozen_taxonomy_group_count <> 7
               OR frozen_taxonomy_coverage_rate NOT BETWEEN 0 AND 1
            """,
        )
        or 0
    )
    add_check(
        checks,
        "group_profile_respects_frozen_taxonomy",
        invalid_group_coverage,
        0,
        invalid_group_coverage == 0,
        "Observed group coverage never exceeds the frozen seven-group taxonomy.",
    )

    invalid_event_coverage = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM program_event_profile
            WHERE observed_event_count < 0
               OR observed_event_count > available_event_count
               OR event_coverage_rate NOT BETWEEN 0 AND 1
            """,
        )
        or 0
    )
    add_check(
        checks,
        "event_profile_coverage_valid",
        invalid_event_coverage,
        0,
        invalid_event_coverage == 0,
        "School event coverage is bounded by the partition event universe.",
    )

    fabricated_2020_outdoor = int(
        scalar(
            connection,
            f"""
            SELECT COUNT(*)
            FROM overall_src.main.school_season_overall_base
            WHERE model_key = '{MODEL_KEY}'
              AND season_year = 2020
              AND season_type = 'outdoor'
            """,
        )
        or 0
    )
    add_check(
        checks,
        "production_2020_outdoor_not_fabricated",
        fabricated_2020_outdoor,
        0,
        fabricated_2020_outdoor == 0,
        "The known missing 2020 Outdoor production season remains absent.",
    )

    overall_hash_after = sha256_file(overall_db)
    detail_hash_after = sha256_file(detail_db)
    add_check(
        checks,
        "overall_input_unchanged",
        overall_hash_after,
        overall_hash_before,
        overall_hash_after == overall_hash_before,
        "The Phase 7A.1 source database is byte-identical after publication.",
    )
    add_check(
        checks,
        "event_group_input_unchanged",
        detail_hash_after,
        detail_hash_before,
        detail_hash_after == detail_hash_before,
        "The Phase 7A.2 source database is byte-identical after publication.",
    )

    return checks


def write_checks(
    connection: duckdb.DuckDBPyConnection,
    checks: list[Check],
    output_dir: Path,
) -> None:
    connection.execute(
        """
        CREATE TABLE hard_checks (
            check_name VARCHAR,
            status VARCHAR,
            observed_value VARCHAR,
            expected_value VARCHAR,
            details VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO hard_checks VALUES (?, ?, ?, ?, ?)",
        [
            (
                item.check_name,
                item.status,
                str(item.observed_value),
                str(item.expected_value),
                item.details,
            )
            for item in checks
        ],
    )
    with (output_dir / "hard_checks.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "check_name",
                "status",
                "observed_value",
                "expected_value",
                "details",
            ]
        )
        for item in checks:
            writer.writerow(
                [
                    item.check_name,
                    item.status,
                    item.observed_value,
                    item.expected_value,
                    item.details,
                ]
            )


def export_tables(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
) -> list[tuple[str, str, int]]:
    table_files = [
        ("program_window_trajectory", "program_window_trajectory.csv"),
        ("program_rise_fall_summary", "program_rise_fall_summary.csv"),
        ("program_latest_snapshot", "program_latest_snapshot.csv"),
        ("program_trajectory_leaderboard", "program_trajectory_leaderboard.csv"),
        ("program_group_profile", "program_group_profile.csv"),
        ("program_event_profile", "program_event_profile.csv"),
        ("program_comparison_snapshot", "program_comparison_snapshot.csv"),
        ("program_trajectory_methodology", "program_trajectory_methodology.csv"),
    ]
    registry: list[tuple[str, str, int]] = []
    for table_name, file_name in table_files:
        target = output_dir / file_name
        connection.execute(
            f"COPY {table_name} TO '{sql_path(target)}' (HEADER, DELIMITER ',')"
        )
        row_count = int(
            scalar(connection, f"SELECT COUNT(*) FROM {table_name}") or 0
        )
        registry.append((table_name, file_name, row_count))
    return registry


def create_manifests(
    connection: duckdb.DuckDBPyConnection,
    overall_db: Path,
    detail_db: Path,
    overall_hash: str,
    detail_hash: str,
    output_registry: list[tuple[str, str, int]],
    output_dir: Path,
) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        CREATE TABLE input_manifest (
            input_role VARCHAR,
            input_path VARCHAR,
            size_bytes BIGINT,
            sha256 VARCHAR,
            dataset_version VARCHAR,
            phase_version VARCHAR,
            generated_at_utc VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO input_manifest VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "phase_7a_overall_trends",
                str(overall_db.resolve()),
                overall_db.stat().st_size,
                overall_hash,
                DATASET_VERSION,
                PHASE_VERSION,
                generated_at,
            ),
            (
                "phase_7a_event_group_trends",
                str(detail_db.resolve()),
                detail_db.stat().st_size,
                detail_hash,
                DATASET_VERSION,
                PHASE_VERSION,
                generated_at,
            ),
        ],
    )
    connection.execute(
        """
        CREATE TABLE output_registry (
            table_name VARCHAR,
            csv_file VARCHAR,
            row_count BIGINT,
            dataset_version VARCHAR,
            phase_version VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO output_registry VALUES (?, ?, ?, ?, ?)",
        [
            (table, csv_file, count, DATASET_VERSION, PHASE_VERSION)
            for table, csv_file, count in output_registry
        ],
    )

    for table_name, file_name in [
        ("input_manifest", "input_manifest.csv"),
        ("output_registry", "output_registry.csv"),
    ]:
        connection.execute(
            f"COPY {table_name} TO '{sql_path(output_dir / file_name)}' "
            "(HEADER, DELIMITER ',')"
        )


def write_report(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
    output_db: Path,
    checks: list[Check],
) -> None:
    failed = [item for item in checks if item.status != "PASS"]
    counts = {
        table: int(scalar(connection, f"SELECT COUNT(*) FROM {table}") or 0)
        for table in [
            "program_window_trajectory",
            "program_rise_fall_summary",
            "program_latest_snapshot",
            "program_trajectory_leaderboard",
            "program_group_profile",
            "program_event_profile",
            "program_comparison_snapshot",
        ]
    }
    trajectory_counts = connection.execute(
        """
        SELECT trajectory_direction, COUNT(*)
        FROM program_window_trajectory
        GROUP BY trajectory_direction
        ORDER BY trajectory_direction
        """
    ).fetchall()

    lines = [
        "MILESTONE 7 — PHASE 7B PROGRAM TRAJECTORY REPORT",
        "=" * 72,
        f"Dataset version: {DATASET_VERSION}",
        f"Phase version: {PHASE_VERSION}",
        f"Official model: {MODEL_LABEL}",
        f"Output database: {output_db.resolve()}",
        "",
        "ROW COUNTS",
        "-" * 72,
    ]
    for table, count in counts.items():
        lines.append(f"{table}: {count:,}")
    lines.extend(
        [
            "",
            "TRAJECTORY DIRECTIONS",
            "-" * 72,
        ]
    )
    for label, count in trajectory_counts:
        lines.append(f"{label}: {count:,}")
    lines.extend(
        [
            "",
            "HARD GATE",
            "-" * 72,
            f"Total checks: {len(checks)}",
            f"Failed checks: {len(failed)}",
            "PHASE GATE: " + ("PASS" if not failed else "FAIL"),
        ]
    )
    if failed:
        lines.extend(["", "FAILED CHECKS", "-" * 72])
        for item in failed:
            lines.append(
                f"{item.check_name}: observed={item.observed_value}; "
                f"expected={item.expected_value}; {item.details}"
            )
    (output_dir / "phase_7b_report.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> int:
    args = parse_args()
    overall_db = args.overall_db.resolve()
    detail_db = args.event_group_db.resolve()
    output_dir = args.output_dir.resolve()
    output_db = output_dir / OUTPUT_DB_NAME

    for path, label in [
        (overall_db, "Phase 7A.1 overall database"),
        (detail_db, "Phase 7A.2 event/group database"),
    ]:
        if not path.exists():
            print(f"ERROR: {label} does not exist: {path}", file=sys.stderr)
            return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    if output_db.exists():
        output_db.unlink()

    overall_hash_before = sha256_file(overall_db)
    detail_hash_before = sha256_file(detail_db)

    connection = duckdb.connect(str(output_db))
    try:
        connection.execute(
            f"ATTACH '{sql_path(overall_db)}' AS overall_src (READ_ONLY)"
        )
        connection.execute(
            f"ATTACH '{sql_path(detail_db)}' AS detail_src (READ_ONLY)"
        )
        require_tables(
            connection,
            "overall_src",
            [
                "school_season_overall_base",
                "school_season_overall_movement",
                "school_multiseason_trends",
                "hard_checks",
            ],
        )
        require_tables(
            connection,
            "detail_src",
            [
                "school_event_multiseason_trends",
                "school_group_multiseason_trends",
                "hard_checks",
            ],
        )

        create_program_window_trajectory(connection)
        create_rise_fall_summary(connection)
        create_latest_snapshot(connection)
        create_leaderboard(connection)
        create_group_profile(connection)
        create_event_profile(connection)
        create_comparison_snapshot(connection)
        create_methodology(connection)

        checks = run_checks(
            connection,
            overall_hash_before,
            detail_hash_before,
            overall_db,
            detail_db,
        )
        write_checks(connection, checks, output_dir)
        registry = export_tables(connection, output_dir)
        create_manifests(
            connection,
            overall_db,
            detail_db,
            overall_hash_before,
            detail_hash_before,
            registry,
            output_dir,
        )
        write_report(connection, output_dir, output_db, checks)
        connection.execute("CHECKPOINT")

        failed_count = sum(item.status != "PASS" for item in checks)
        counts = {
            table: int(scalar(connection, f"SELECT COUNT(*) FROM {table}") or 0)
            for table in [
                "program_window_trajectory",
                "program_rise_fall_summary",
                "program_latest_snapshot",
                "program_trajectory_leaderboard",
                "program_group_profile",
                "program_event_profile",
                "program_comparison_snapshot",
            ]
        }

        print(f"Dataset version: {DATASET_VERSION}")
        print(f"Phase version: {PHASE_VERSION}")
        print("Publication mode: enhanced_primary_only")
        print(f"Official primary: {MODEL_LABEL}")
        print(f"Overall source: {overall_db}")
        print(f"Event/group source: {detail_db}")
        print(f"Output database: {output_db}")
        print(f"Program trajectory rows: {counts['program_window_trajectory']:,}")
        print(f"Rise/fall summary rows: {counts['program_rise_fall_summary']:,}")
        print(f"Latest snapshot rows: {counts['program_latest_snapshot']:,}")
        print(f"Trajectory leaderboard rows: {counts['program_trajectory_leaderboard']:,}")
        print(f"Group profile rows: {counts['program_group_profile']:,}")
        print(f"Event profile rows: {counts['program_event_profile']:,}")
        print(f"Comparison snapshot rows: {counts['program_comparison_snapshot']:,}")
        print(f"Failed checks: {failed_count}")
        print()
        if failed_count:
            print("PHASE GATE: FAIL")
            return 1
        print("PHASE GATE: PASS")
        print("Phase 7B program trajectory and consistency products published.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
