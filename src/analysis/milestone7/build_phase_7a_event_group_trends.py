#!/usr/bin/env python3
"""Build Milestone 7 Phase 7A.2 Enhanced event and group seasonal trends.

Reads the frozen Milestone 6 final publication in read-only mode and publishes
Enhanced Balanced Production seasonal trend tables for:

- individual events using the frozen 27-event championship taxonomy;
- the frozen seven development groups;
- exact same-season-type year-over-year movement;
- three- and five-year calendar-window trend summaries;
- coverage, manifests, and hard checks.

Missing seasons are never interpolated, carried forward, or converted to zero.
The two companion models are intentionally excluded from this phase.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


DATASET_VERSION = "seasonal_program_trends_v1"
PHASE_VERSION = "phase_7a_2_event_group_trends_v3"
MODEL_KEY = "enhanced_balanced_production"
DEFAULT_SOURCE_DIR = Path(
    "data/processed/milestone6/"
    "final_development_rankings_v1/"
    "phase_6g_final_publication"
)
DEFAULT_OUTPUT_DIR = Path(
    "data/processed/milestone7/"
    "seasonal_program_trends_v1/"
    "phase_7a_event_group_trends"
)


@dataclass(frozen=True)
class CheckResult:
    check_name: str
    status: str
    observed_value: str
    expected_value: str
    details: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build Milestone 7 Phase 7A.2 Enhanced event and group "
            "seasonal trend outputs."
        )
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="Directory containing the final Milestone 6 DuckDB publication.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Phase 7A.2 output directory.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete and rebuild the output directory when it exists.",
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


def sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def scalar(connection: duckdb.DuckDBPyConnection, sql: str) -> Any:
    row = connection.execute(sql).fetchone()
    return None if row is None else row[0]


def add_check(
    checks: list[CheckResult],
    name: str,
    condition: bool,
    observed: Any,
    expected: Any,
    details: str,
) -> None:
    checks.append(
        CheckResult(
            check_name=name,
            status="PASS" if condition else "FAIL",
            observed_value=str(observed),
            expected_value=str(expected),
            details=details,
        )
    )


def export_query(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    destination: Path,
) -> None:
    connection.execute(
        f"COPY ({query}) TO {sql_string(destination)} "
        "(HEADER, DELIMITER ',', QUOTE '\"', ESCAPE '\"')"
    )


def write_output_manifest(output_dir: Path) -> Path:
    manifest_path = output_dir / "output_manifest.csv"
    rows: list[dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        rows.append(
            {
                "relative_path": str(path.relative_to(output_dir)),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["relative_path", "size_bytes", "sha256"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return manifest_path


def create_event_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE event_partition_registry AS
        SELECT DISTINCT
            model_key,
            cohort_key,
            season_year,
            season_type,
            gender_scope,
            canonical_event_code
        FROM src.main.official_school_event_points
        WHERE model_key = '{MODEL_KEY}'
          AND time_scope = 'single_season'
        ORDER BY ALL
        """
    )

    connection.execute(
        f"""
        CREATE TABLE school_season_event_base AS
        SELECT
            source.model_key,
            source.model_label,
            source.is_primary AS is_official_primary,
            source.cohort_key,
            source.cohort_label,
            source.publication_tier,
            source.time_scope,
            source.season_year,
            source.season_type,
            source.season_key,
            source.season_label,
            source.gender_scope,
            source.canonical_event_code,
            source.canonical_event_name,
            source.balanced_group_key,
            source.balanced_group_label,
            source.resolved_school_id,
            source.school_name,
            metadata.state_code,
            metadata.city,
            metadata.conference_name,
            metadata.division_name,
            source.athlete_unit_count,
            source.positive_athlete_count,
            source.negative_athlete_count,
            source.neutral_athlete_count,
            source.trajectory_count,
            source.positive_event_points,
            source.negative_event_points,
            source.net_event_points,
            source.event_balanced_points AS primary_metric_value,
            'event_balanced_points' AS primary_metric_name,
            source.event_point_share AS opportunity_adjusted_metric_value,
            'event_point_share' AS opportunity_adjusted_metric_name,
            source.positive_event_point_share,
            source.posterior_school_score,
            source.relative_development_strength,
            source.source_rank,
            source.ranked_school_count,
            CASE
                WHEN source.source_rank IS NULL
                  OR source.ranked_school_count IS NULL
                  OR source.ranked_school_count <= 0
                THEN NULL
                WHEN source.ranked_school_count = 1 THEN 1.0
                ELSE 1.0 - (
                    CAST(source.source_rank - 1 AS DOUBLE)
                    / CAST(source.ranked_school_count - 1 AS DOUBLE)
                )
            END AS rank_strength_percentile,
            source.mean_reliability_factor,
            source.minimum_evidence_support,
            source.evidence_category,
            source.reliability_tier,
            source.scoring_status,
            source.event_budget,
            source.event_school_count,
            source.event_athlete_unit_count,
            source.negative_pool_was_capped,
            source.source_rank IS NOT NULL
                AND source.ranked_school_count > 0 AS source_eligible,
            source.dataset_version AS source_dataset_version,
            '{DATASET_VERSION}' AS trend_dataset_version
        FROM src.main.official_school_event_points AS source
        LEFT JOIN src.main.school_metadata AS metadata
          ON metadata.resolved_school_id = source.resolved_school_id
        WHERE source.model_key = '{MODEL_KEY}'
          AND source.time_scope = 'single_season'
        ORDER BY
            source.cohort_key,
            source.season_year,
            source.season_type,
            source.gender_scope,
            source.canonical_event_code,
            source.source_rank,
            source.resolved_school_id
        """
    )

    connection.execute(
        """
        CREATE TABLE school_season_event_movement AS
        WITH paired AS (
            SELECT
                current.*,
                previous.season_key AS previous_season_key,
                previous.season_label AS previous_season_label,
                previous.source_eligible AS previous_source_eligible,
                previous.primary_metric_value AS previous_primary_metric,
                previous.opportunity_adjusted_metric_value
                    AS previous_opportunity_adjusted_metric,
                previous.positive_event_point_share
                    AS previous_positive_event_point_share,
                previous.source_rank AS previous_rank,
                previous.ranked_school_count AS previous_ranked_school_count,
                previous.rank_strength_percentile
                    AS previous_rank_strength_percentile,
                previous.athlete_unit_count AS previous_athlete_unit_count,
                partition_previous.model_key IS NOT NULL
                    AS previous_partition_available
            FROM school_season_event_base AS current
            LEFT JOIN event_partition_registry AS partition_previous
              ON partition_previous.model_key = current.model_key
             AND partition_previous.cohort_key = current.cohort_key
             AND partition_previous.season_year = current.season_year - 1
             AND partition_previous.season_type = current.season_type
             AND partition_previous.gender_scope = current.gender_scope
             AND partition_previous.canonical_event_code
                    = current.canonical_event_code
            LEFT JOIN school_season_event_base AS previous
              ON previous.model_key = current.model_key
             AND previous.cohort_key = current.cohort_key
             AND previous.season_year = current.season_year - 1
             AND previous.season_type = current.season_type
             AND previous.gender_scope = current.gender_scope
             AND previous.canonical_event_code = current.canonical_event_code
             AND previous.resolved_school_id = current.resolved_school_id
        )
        SELECT
            model_key,
            model_label,
            is_official_primary,
            cohort_key,
            cohort_label,
            publication_tier,
            season_year AS current_season_year,
            season_type,
            season_key AS current_season_key,
            season_label AS current_season_label,
            season_year - 1 AS expected_previous_year,
            previous_season_key,
            previous_season_label,
            gender_scope,
            canonical_event_code,
            canonical_event_name,
            balanced_group_key,
            balanced_group_label,
            resolved_school_id,
            school_name,
            state_code,
            city,
            conference_name,
            division_name,
            source_eligible AS current_source_eligible,
            previous_source_eligible,
            previous_partition_available,
            CASE
                WHEN NOT previous_partition_available
                    THEN 'previous_partition_unavailable'
                WHEN previous_season_key IS NULL
                    THEN 'previous_school_unavailable'
                WHEN NOT source_eligible OR NOT previous_source_eligible
                    THEN 'source_ineligible'
                ELSE 'comparable'
            END AS comparison_status,
            previous_partition_available
                AND previous_season_key IS NOT NULL
                AND source_eligible
                AND previous_source_eligible AS is_comparable,
            primary_metric_name,
            primary_metric_value AS current_primary_metric,
            previous_primary_metric,
            CASE
                WHEN previous_partition_available
                 AND previous_season_key IS NOT NULL
                 AND source_eligible
                 AND previous_source_eligible
                THEN primary_metric_value - previous_primary_metric
                ELSE NULL
            END AS primary_metric_delta,
            opportunity_adjusted_metric_name,
            opportunity_adjusted_metric_value
                AS current_opportunity_adjusted_metric,
            previous_opportunity_adjusted_metric,
            CASE
                WHEN previous_partition_available
                 AND previous_season_key IS NOT NULL
                 AND source_eligible
                 AND previous_source_eligible
                THEN opportunity_adjusted_metric_value
                   - previous_opportunity_adjusted_metric
                ELSE NULL
            END AS opportunity_adjusted_metric_delta,
            positive_event_point_share
                AS current_positive_event_point_share,
            previous_positive_event_point_share,
            CASE
                WHEN previous_partition_available
                 AND previous_season_key IS NOT NULL
                 AND source_eligible
                 AND previous_source_eligible
                THEN positive_event_point_share
                   - previous_positive_event_point_share
                ELSE NULL
            END AS positive_event_point_share_delta,
            source_rank AS current_rank,
            previous_rank,
            CASE
                WHEN previous_partition_available
                 AND previous_season_key IS NOT NULL
                 AND source_eligible
                 AND previous_source_eligible
                THEN previous_rank - source_rank
                ELSE NULL
            END AS rank_improvement,
            ranked_school_count AS current_ranked_school_count,
            previous_ranked_school_count,
            rank_strength_percentile AS current_rank_strength_percentile,
            previous_rank_strength_percentile,
            CASE
                WHEN previous_partition_available
                 AND previous_season_key IS NOT NULL
                 AND source_eligible
                 AND previous_source_eligible
                THEN rank_strength_percentile
                   - previous_rank_strength_percentile
                ELSE NULL
            END AS rank_strength_delta,
            athlete_unit_count AS current_athlete_unit_count,
            previous_athlete_unit_count,
            CASE
                WHEN previous_partition_available
                 AND previous_season_key IS NOT NULL
                 AND source_eligible
                 AND previous_source_eligible
                THEN athlete_unit_count - previous_athlete_unit_count
                ELSE NULL
            END AS athlete_unit_delta,
            CASE
                WHEN NOT (
                    previous_partition_available
                    AND previous_season_key IS NOT NULL
                    AND source_eligible
                    AND previous_source_eligible
                ) THEN 'not_comparable'
                WHEN primary_metric_value > previous_primary_metric
                 AND previous_rank - source_rank > 0 THEN 'both_improved'
                WHEN primary_metric_value < previous_primary_metric
                 AND previous_rank - source_rank < 0 THEN 'both_declined'
                WHEN primary_metric_value = previous_primary_metric
                 AND previous_rank = source_rank THEN 'unchanged'
                ELSE 'mixed'
            END AS rank_score_alignment,
            source_dataset_version,
            trend_dataset_version
        FROM paired
        ORDER BY
            cohort_key,
            gender_scope,
            canonical_event_code,
            resolved_school_id,
            current_season_year,
            season_type
        """
    )

    connection.execute(
        """
        CREATE TABLE school_event_multiseason_trends AS
        WITH window_sizes AS (
            SELECT 3 AS window_years
            UNION ALL
            SELECT 5 AS window_years
        )
        SELECT
            current.model_key,
            current.model_label,
            current.is_official_primary,
            current.cohort_key,
            current.cohort_label,
            current.publication_tier,
            current.gender_scope,
            current.canonical_event_code,
            current.canonical_event_name,
            current.balanced_group_key,
            current.balanced_group_label,
            current.resolved_school_id,
            current.school_name,
            current.state_code,
            current.city,
            current.conference_name,
            current.division_name,
            current.season_year AS endpoint_year,
            current.season_type,
            current.season_key AS endpoint_season_key,
            current.season_label AS endpoint_season_label,
            window_sizes.window_years,
            current.season_year - window_sizes.window_years + 1
                AS window_start_year,
            current.season_year AS window_end_year,
            COUNT(DISTINCT history.season_year) AS observed_season_count,
            COUNT(DISTINCT history.season_year) FILTER (
                WHERE history.source_eligible
            ) AS eligible_observation_count,
            AVG(history.primary_metric_value) FILTER (
                WHERE history.source_eligible
            ) AS mean_primary_metric,
            MEDIAN(history.primary_metric_value) FILTER (
                WHERE history.source_eligible
            ) AS median_primary_metric,
            STDDEV_SAMP(history.primary_metric_value) FILTER (
                WHERE history.source_eligible
            ) AS standard_deviation_primary_metric,
            CASE
                WHEN COUNT(DISTINCT history.season_year) FILTER (
                    WHERE history.source_eligible
                ) >= 3
                THEN REGR_SLOPE(
                    history.primary_metric_value,
                    history.season_year
                ) FILTER (WHERE history.source_eligible)
                ELSE NULL
            END AS primary_metric_slope_per_year,
            AVG(history.opportunity_adjusted_metric_value) FILTER (
                WHERE history.source_eligible
            ) AS mean_opportunity_adjusted_metric,
            CASE
                WHEN COUNT(DISTINCT history.season_year) FILTER (
                    WHERE history.source_eligible
                ) >= 3
                THEN REGR_SLOPE(
                    history.opportunity_adjusted_metric_value,
                    history.season_year
                ) FILTER (WHERE history.source_eligible)
                ELSE NULL
            END AS opportunity_adjusted_metric_slope_per_year,
            AVG(history.rank_strength_percentile) FILTER (
                WHERE history.source_eligible
            ) AS mean_rank_strength_percentile,
            CASE
                WHEN COUNT(DISTINCT history.season_year) FILTER (
                    WHERE history.source_eligible
                ) >= 3
                THEN REGR_SLOPE(
                    history.rank_strength_percentile,
                    history.season_year
                ) FILTER (WHERE history.source_eligible)
                ELSE NULL
            END AS rank_strength_slope_per_year,
            MIN(history.source_rank) FILTER (
                WHERE history.source_eligible
            ) AS best_rank,
            AVG(history.source_rank) FILTER (
                WHERE history.source_eligible
            ) AS mean_rank,
            current.source_dataset_version,
            current.trend_dataset_version
        FROM school_season_event_base AS current
        CROSS JOIN window_sizes
        LEFT JOIN school_season_event_base AS history
          ON history.model_key = current.model_key
         AND history.cohort_key = current.cohort_key
         AND history.gender_scope = current.gender_scope
         AND history.canonical_event_code = current.canonical_event_code
         AND history.resolved_school_id = current.resolved_school_id
         AND history.season_type = current.season_type
         AND history.season_year BETWEEN
             current.season_year - window_sizes.window_years + 1
             AND current.season_year
        GROUP BY ALL
        ORDER BY
            cohort_key,
            gender_scope,
            canonical_event_code,
            resolved_school_id,
            endpoint_year,
            season_type,
            window_years
        """
    )


def create_group_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE group_partition_registry AS
        WITH combined AS (
            SELECT DISTINCT
                model_key,
                cohort_key,
                season_year,
                season_type,
                'all' AS gender_scope,
                balanced_group_key
            FROM src.main.official_group_points_combined
            WHERE model_key = '{MODEL_KEY}'
              AND time_scope = 'single_season'
        ),
        gender AS (
            SELECT DISTINCT
                model_key,
                cohort_key,
                season_year,
                season_type,
                gender_scope,
                balanced_group_key
            FROM src.main.official_group_points_gender
            WHERE model_key = '{MODEL_KEY}'
              AND time_scope = 'single_season'
        )
        SELECT * FROM combined
        UNION ALL
        SELECT * FROM gender
        ORDER BY ALL
        """
    )

    connection.execute(
        f"""
        CREATE TABLE school_season_group_base AS
        WITH combined AS (
            SELECT
                source.model_key,
                source.model_label,
                source.is_primary AS is_official_primary,
                source.cohort_key,
                source.cohort_label,
                source.publication_tier,
                source.time_scope,
                source.season_year,
                source.season_type,
                source.season_key,
                source.season_label,
                'all' AS gender_scope,
                source.balanced_group_key,
                source.balanced_group_label,
                source.resolved_school_id,
                source.school_name,
                source.athlete_event_unit_count,
                source.positive_athlete_count,
                source.negative_athlete_count,
                source.group_scoring_event_count,
                source.group_represented_event_count,
                source.positive_group_points,
                source.negative_group_points,
                source.group_balanced_points,
                source.positive_group_point_share,
                source.group_point_share,
                source.combined_group_strength_share AS group_strength_share,
                source.group_source_rank,
                source.group_ranked_school_count,
                source.group_budget,
                source.scoring_status,
                source.dataset_version AS source_dataset_version
            FROM src.main.official_group_points_combined AS source
            WHERE source.model_key = '{MODEL_KEY}'
              AND source.time_scope = 'single_season'
        ),
        gender AS (
            SELECT
                source.model_key,
                source.model_label,
                source.is_primary AS is_official_primary,
                source.cohort_key,
                source.cohort_label,
                source.publication_tier,
                source.time_scope,
                source.season_year,
                source.season_type,
                source.season_key,
                source.season_label,
                source.gender_scope,
                source.balanced_group_key,
                source.balanced_group_label,
                source.resolved_school_id,
                source.school_name,
                source.athlete_event_unit_count,
                source.positive_athlete_count,
                source.negative_athlete_count,
                source.group_scoring_event_count,
                source.group_represented_event_count,
                source.positive_group_points,
                source.negative_group_points,
                source.group_balanced_points,
                source.positive_group_point_share,
                source.group_point_share,
                source.group_strength_share,
                source.group_source_rank,
                source.group_ranked_school_count,
                source.group_budget,
                source.scoring_status,
                source.dataset_version AS source_dataset_version
            FROM src.main.official_group_points_gender AS source
            WHERE source.model_key = '{MODEL_KEY}'
              AND source.time_scope = 'single_season'
        ),
        unioned AS (
            SELECT * FROM combined
            UNION ALL
            SELECT * FROM gender
        )
        SELECT
            source.*,
            metadata.state_code,
            metadata.city,
            metadata.conference_name,
            metadata.division_name,
            source.group_balanced_points AS primary_metric_value,
            'group_balanced_points' AS primary_metric_name,
            source.group_point_share AS opportunity_adjusted_metric_value,
            'group_point_share' AS opportunity_adjusted_metric_name,
            source.group_source_rank AS source_rank,
            source.group_ranked_school_count AS ranked_school_count,
            CASE
                WHEN source.group_source_rank IS NULL
                  OR source.group_ranked_school_count IS NULL
                  OR source.group_ranked_school_count <= 0
                THEN NULL
                WHEN source.group_ranked_school_count = 1 THEN 1.0
                ELSE 1.0 - (
                    CAST(source.group_source_rank - 1 AS DOUBLE)
                    / CAST(source.group_ranked_school_count - 1 AS DOUBLE)
                )
            END AS rank_strength_percentile,
            source.group_source_rank IS NOT NULL
                AND source.group_ranked_school_count > 0 AS source_eligible,
            '{DATASET_VERSION}' AS trend_dataset_version
        FROM unioned AS source
        LEFT JOIN src.main.school_metadata AS metadata
          ON metadata.resolved_school_id = source.resolved_school_id
        ORDER BY
            source.cohort_key,
            source.season_year,
            source.season_type,
            source.gender_scope,
            source.balanced_group_key,
            source.group_source_rank,
            source.resolved_school_id
        """
    )

    connection.execute(
        """
        CREATE TABLE school_season_group_movement AS
        WITH paired AS (
            SELECT
                current.*,
                previous.season_key AS previous_season_key,
                previous.season_label AS previous_season_label,
                previous.source_eligible AS previous_source_eligible,
                previous.primary_metric_value AS previous_primary_metric,
                previous.opportunity_adjusted_metric_value
                    AS previous_opportunity_adjusted_metric,
                previous.positive_group_point_share
                    AS previous_positive_group_point_share,
                previous.source_rank AS previous_rank,
                previous.ranked_school_count AS previous_ranked_school_count,
                previous.rank_strength_percentile
                    AS previous_rank_strength_percentile,
                previous.athlete_event_unit_count
                    AS previous_athlete_event_unit_count,
                partition_previous.model_key IS NOT NULL
                    AS previous_partition_available
            FROM school_season_group_base AS current
            LEFT JOIN group_partition_registry AS partition_previous
              ON partition_previous.model_key = current.model_key
             AND partition_previous.cohort_key = current.cohort_key
             AND partition_previous.season_year = current.season_year - 1
             AND partition_previous.season_type = current.season_type
             AND partition_previous.gender_scope = current.gender_scope
             AND partition_previous.balanced_group_key
                    = current.balanced_group_key
            LEFT JOIN school_season_group_base AS previous
              ON previous.model_key = current.model_key
             AND previous.cohort_key = current.cohort_key
             AND previous.season_year = current.season_year - 1
             AND previous.season_type = current.season_type
             AND previous.gender_scope = current.gender_scope
             AND previous.balanced_group_key = current.balanced_group_key
             AND previous.resolved_school_id = current.resolved_school_id
        )
        SELECT
            model_key,
            model_label,
            is_official_primary,
            cohort_key,
            cohort_label,
            publication_tier,
            season_year AS current_season_year,
            season_type,
            season_key AS current_season_key,
            season_label AS current_season_label,
            season_year - 1 AS expected_previous_year,
            previous_season_key,
            previous_season_label,
            gender_scope,
            balanced_group_key,
            balanced_group_label,
            resolved_school_id,
            school_name,
            state_code,
            city,
            conference_name,
            division_name,
            source_eligible AS current_source_eligible,
            previous_source_eligible,
            previous_partition_available,
            CASE
                WHEN NOT previous_partition_available
                    THEN 'previous_partition_unavailable'
                WHEN previous_season_key IS NULL
                    THEN 'previous_school_unavailable'
                WHEN NOT source_eligible OR NOT previous_source_eligible
                    THEN 'source_ineligible'
                ELSE 'comparable'
            END AS comparison_status,
            previous_partition_available
                AND previous_season_key IS NOT NULL
                AND source_eligible
                AND previous_source_eligible AS is_comparable,
            primary_metric_name,
            primary_metric_value AS current_primary_metric,
            previous_primary_metric,
            CASE
                WHEN previous_partition_available
                 AND previous_season_key IS NOT NULL
                 AND source_eligible
                 AND previous_source_eligible
                THEN primary_metric_value - previous_primary_metric
                ELSE NULL
            END AS primary_metric_delta,
            opportunity_adjusted_metric_name,
            opportunity_adjusted_metric_value
                AS current_opportunity_adjusted_metric,
            previous_opportunity_adjusted_metric,
            CASE
                WHEN previous_partition_available
                 AND previous_season_key IS NOT NULL
                 AND source_eligible
                 AND previous_source_eligible
                THEN opportunity_adjusted_metric_value
                   - previous_opportunity_adjusted_metric
                ELSE NULL
            END AS opportunity_adjusted_metric_delta,
            positive_group_point_share AS current_positive_group_point_share,
            previous_positive_group_point_share,
            CASE
                WHEN previous_partition_available
                 AND previous_season_key IS NOT NULL
                 AND source_eligible
                 AND previous_source_eligible
                THEN positive_group_point_share
                   - previous_positive_group_point_share
                ELSE NULL
            END AS positive_group_point_share_delta,
            source_rank AS current_rank,
            previous_rank,
            CASE
                WHEN previous_partition_available
                 AND previous_season_key IS NOT NULL
                 AND source_eligible
                 AND previous_source_eligible
                THEN previous_rank - source_rank
                ELSE NULL
            END AS rank_improvement,
            ranked_school_count AS current_ranked_school_count,
            previous_ranked_school_count,
            rank_strength_percentile AS current_rank_strength_percentile,
            previous_rank_strength_percentile,
            CASE
                WHEN previous_partition_available
                 AND previous_season_key IS NOT NULL
                 AND source_eligible
                 AND previous_source_eligible
                THEN rank_strength_percentile
                   - previous_rank_strength_percentile
                ELSE NULL
            END AS rank_strength_delta,
            athlete_event_unit_count AS current_athlete_event_unit_count,
            previous_athlete_event_unit_count,
            CASE
                WHEN previous_partition_available
                 AND previous_season_key IS NOT NULL
                 AND source_eligible
                 AND previous_source_eligible
                THEN athlete_event_unit_count
                   - previous_athlete_event_unit_count
                ELSE NULL
            END AS athlete_event_unit_delta,
            CASE
                WHEN NOT (
                    previous_partition_available
                    AND previous_season_key IS NOT NULL
                    AND source_eligible
                    AND previous_source_eligible
                ) THEN 'not_comparable'
                WHEN primary_metric_value > previous_primary_metric
                 AND previous_rank - source_rank > 0 THEN 'both_improved'
                WHEN primary_metric_value < previous_primary_metric
                 AND previous_rank - source_rank < 0 THEN 'both_declined'
                WHEN primary_metric_value = previous_primary_metric
                 AND previous_rank = source_rank THEN 'unchanged'
                ELSE 'mixed'
            END AS rank_score_alignment,
            source_dataset_version,
            trend_dataset_version
        FROM paired
        ORDER BY
            cohort_key,
            gender_scope,
            balanced_group_key,
            resolved_school_id,
            current_season_year,
            season_type
        """
    )

    connection.execute(
        """
        CREATE TABLE school_group_multiseason_trends AS
        WITH window_sizes AS (
            SELECT 3 AS window_years
            UNION ALL
            SELECT 5 AS window_years
        )
        SELECT
            current.model_key,
            current.model_label,
            current.is_official_primary,
            current.cohort_key,
            current.cohort_label,
            current.publication_tier,
            current.gender_scope,
            current.balanced_group_key,
            current.balanced_group_label,
            current.resolved_school_id,
            current.school_name,
            current.state_code,
            current.city,
            current.conference_name,
            current.division_name,
            current.season_year AS endpoint_year,
            current.season_type,
            current.season_key AS endpoint_season_key,
            current.season_label AS endpoint_season_label,
            window_sizes.window_years,
            current.season_year - window_sizes.window_years + 1
                AS window_start_year,
            current.season_year AS window_end_year,
            COUNT(DISTINCT history.season_year) AS observed_season_count,
            COUNT(DISTINCT history.season_year) FILTER (
                WHERE history.source_eligible
            ) AS eligible_observation_count,
            AVG(history.primary_metric_value) FILTER (
                WHERE history.source_eligible
            ) AS mean_primary_metric,
            MEDIAN(history.primary_metric_value) FILTER (
                WHERE history.source_eligible
            ) AS median_primary_metric,
            STDDEV_SAMP(history.primary_metric_value) FILTER (
                WHERE history.source_eligible
            ) AS standard_deviation_primary_metric,
            CASE
                WHEN COUNT(DISTINCT history.season_year) FILTER (
                    WHERE history.source_eligible
                ) >= 3
                THEN REGR_SLOPE(
                    history.primary_metric_value,
                    history.season_year
                ) FILTER (WHERE history.source_eligible)
                ELSE NULL
            END AS primary_metric_slope_per_year,
            AVG(history.opportunity_adjusted_metric_value) FILTER (
                WHERE history.source_eligible
            ) AS mean_opportunity_adjusted_metric,
            CASE
                WHEN COUNT(DISTINCT history.season_year) FILTER (
                    WHERE history.source_eligible
                ) >= 3
                THEN REGR_SLOPE(
                    history.opportunity_adjusted_metric_value,
                    history.season_year
                ) FILTER (WHERE history.source_eligible)
                ELSE NULL
            END AS opportunity_adjusted_metric_slope_per_year,
            AVG(history.rank_strength_percentile) FILTER (
                WHERE history.source_eligible
            ) AS mean_rank_strength_percentile,
            CASE
                WHEN COUNT(DISTINCT history.season_year) FILTER (
                    WHERE history.source_eligible
                ) >= 3
                THEN REGR_SLOPE(
                    history.rank_strength_percentile,
                    history.season_year
                ) FILTER (WHERE history.source_eligible)
                ELSE NULL
            END AS rank_strength_slope_per_year,
            MIN(history.source_rank) FILTER (
                WHERE history.source_eligible
            ) AS best_rank,
            AVG(history.source_rank) FILTER (
                WHERE history.source_eligible
            ) AS mean_rank,
            current.source_dataset_version,
            current.trend_dataset_version
        FROM school_season_group_base AS current
        CROSS JOIN window_sizes
        LEFT JOIN school_season_group_base AS history
          ON history.model_key = current.model_key
         AND history.cohort_key = current.cohort_key
         AND history.gender_scope = current.gender_scope
         AND history.balanced_group_key = current.balanced_group_key
         AND history.resolved_school_id = current.resolved_school_id
         AND history.season_type = current.season_type
         AND history.season_year BETWEEN
             current.season_year - window_sizes.window_years + 1
             AND current.season_year
        GROUP BY ALL
        ORDER BY
            cohort_key,
            gender_scope,
            balanced_group_key,
            resolved_school_id,
            endpoint_year,
            season_type,
            window_years
        """
    )


def create_summaries(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE event_trend_partition_summary AS
        SELECT
            cohort_key,
            cohort_label,
            publication_tier,
            season_year,
            season_type,
            gender_scope,
            canonical_event_code,
            canonical_event_name,
            balanced_group_key,
            balanced_group_label,
            COUNT(*) AS school_row_count,
            COUNT(*) FILTER (WHERE source_eligible) AS eligible_school_count,
            MIN(source_rank) AS best_rank,
            MAX(source_rank) AS worst_rank,
            MAX(ranked_school_count) AS ranked_school_count,
            AVG(primary_metric_value) AS mean_event_points,
            AVG(opportunity_adjusted_metric_value) AS mean_event_point_share
        FROM school_season_event_base
        GROUP BY ALL
        ORDER BY
            cohort_key,
            season_year,
            season_type,
            gender_scope,
            canonical_event_code
        """
    )

    connection.execute(
        """
        CREATE TABLE group_trend_partition_summary AS
        SELECT
            cohort_key,
            cohort_label,
            publication_tier,
            season_year,
            season_type,
            gender_scope,
            balanced_group_key,
            balanced_group_label,
            COUNT(*) AS school_row_count,
            COUNT(*) FILTER (WHERE source_eligible) AS eligible_school_count,
            MIN(source_rank) AS best_rank,
            MAX(source_rank) AS worst_rank,
            MAX(ranked_school_count) AS ranked_school_count,
            AVG(primary_metric_value) AS mean_group_points,
            AVG(opportunity_adjusted_metric_value) AS mean_group_point_share
        FROM school_season_group_base
        GROUP BY ALL
        ORDER BY
            cohort_key,
            season_year,
            season_type,
            gender_scope,
            balanced_group_key
        """
    )

    connection.execute(
        """
        CREATE TABLE trend_comparison_status_summary AS
        SELECT
            'event' AS trend_level,
            cohort_key,
            season_type,
            gender_scope,
            comparison_status,
            COUNT(*) AS row_count
        FROM school_season_event_movement
        GROUP BY ALL
        UNION ALL
        SELECT
            'group' AS trend_level,
            cohort_key,
            season_type,
            gender_scope,
            comparison_status,
            COUNT(*) AS row_count
        FROM school_season_group_movement
        GROUP BY ALL
        ORDER BY ALL
        """
    )


def run_checks(
    connection: duckdb.DuckDBPyConnection,
    source_database: Path,
    source_size_before: int,
    source_hash_before: str,
) -> list[CheckResult]:
    checks: list[CheckResult] = []

    published_models = scalar(
        connection,
        "SELECT STRING_AGG(DISTINCT model_key, ', ' ORDER BY model_key) "
        "FROM school_season_event_base",
    )
    add_check(
        checks,
        "enhanced_is_exclusive_published_model",
        published_models == MODEL_KEY,
        published_models,
        MODEL_KEY,
        "Phase 7A.2 intentionally publishes only Enhanced Balanced Production.",
    )

    event_source_rows = scalar(
        connection,
        f"""
        SELECT COUNT(*)
        FROM src.main.official_school_event_points
        WHERE model_key = '{MODEL_KEY}'
          AND time_scope = 'single_season'
        """,
    )
    event_base_rows = scalar(
        connection, "SELECT COUNT(*) FROM school_season_event_base"
    )
    add_check(
        checks,
        "event_base_row_count_reconciles",
        event_base_rows == event_source_rows,
        event_base_rows,
        event_source_rows,
        "Every Enhanced single-season event source row must publish once.",
    )

    group_source_rows = scalar(
        connection,
        f"""
        SELECT
            (SELECT COUNT(*)
             FROM src.main.official_group_points_combined
             WHERE model_key = '{MODEL_KEY}'
               AND time_scope = 'single_season')
          + (SELECT COUNT(*)
             FROM src.main.official_group_points_gender
             WHERE model_key = '{MODEL_KEY}'
               AND time_scope = 'single_season')
        """,
    )
    group_base_rows = scalar(
        connection, "SELECT COUNT(*) FROM school_season_group_base"
    )
    add_check(
        checks,
        "group_base_row_count_reconciles",
        group_base_rows == group_source_rows,
        group_base_rows,
        group_source_rows,
        "Combined and gender group rows must publish exactly once.",
    )

    event_duplicate_groups = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM (
            SELECT
                model_key, cohort_key, season_year, season_type,
                gender_scope, canonical_event_code, resolved_school_id,
                COUNT(*) AS n
            FROM school_season_event_base
            GROUP BY ALL
            HAVING COUNT(*) > 1
        )
        """,
    )
    add_check(
        checks,
        "event_base_keys_unique",
        event_duplicate_groups == 0,
        event_duplicate_groups,
        0,
        "Event base natural keys must be unique.",
    )

    group_duplicate_groups = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM (
            SELECT
                model_key, cohort_key, season_year, season_type,
                gender_scope, balanced_group_key, resolved_school_id,
                COUNT(*) AS n
            FROM school_season_group_base
            GROUP BY ALL
            HAVING COUNT(*) > 1
        )
        """,
    )
    add_check(
        checks,
        "group_base_keys_unique",
        group_duplicate_groups == 0,
        group_duplicate_groups,
        0,
        "Group base natural keys must be unique.",
    )

    excluded_event_rows = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_event_base
        WHERE canonical_event_code IN ('500M', '600M', '1000M')
        """,
    )
    add_check(
        checks,
        "nonchampionship_events_excluded",
        excluded_event_rows == 0,
        excluded_event_rows,
        0,
        "500m, 600m, and 1000m must not enter Enhanced trend outputs.",
    )

    invalid_taxonomy_rows = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_event_base AS events
        LEFT JOIN balanced_event_registry AS registry
          ON registry.source_season_type = events.season_type
         AND registry.gender_scope = events.gender_scope
         AND registry.canonical_event_code = events.canonical_event_code
        WHERE registry.canonical_event_code IS NULL
        """,
    )
    add_check(
        checks,
        "event_rows_match_frozen_taxonomy",
        invalid_taxonomy_rows == 0,
        invalid_taxonomy_rows,
        0,
        "Every event row must map to the frozen season/gender taxonomy.",
    )

    registered_group_keys = scalar(
        connection,
        """
        SELECT COUNT(DISTINCT balanced_group_key)
        FROM balanced_event_registry
        """,
    )
    add_check(
        checks,
        "exactly_seven_groups_registered",
        registered_group_keys == 7,
        registered_group_keys,
        7,
        "The frozen Enhanced taxonomy must register exactly seven groups.",
    )

    unregistered_published_groups = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM (
            SELECT DISTINCT balanced_group_key
            FROM school_season_group_base
            EXCEPT
            SELECT DISTINCT balanced_group_key
            FROM balanced_event_registry
        )
        """,
    )
    add_check(
        checks,
        "published_groups_are_registered",
        unregistered_published_groups == 0,
        unregistered_published_groups,
        0,
        "Observed group rows may be sparse, but every published group must belong to the frozen taxonomy.",
    )

    observed_group_keys = scalar(
        connection,
        """
        SELECT COUNT(DISTINCT balanced_group_key)
        FROM school_season_group_base
        """,
    )
    add_check(
        checks,
        "observed_group_count_within_registry",
        0 < observed_group_keys <= registered_group_keys,
        observed_group_keys,
        f"1..{registered_group_keys}",
        "Groups with no publishable source rows remain explicit coverage gaps and are not fabricated.",
    )

    steeple_misclassified = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_event_base
        WHERE canonical_event_code = '3000SC'
          AND balanced_group_key <> 'distance'
        """,
    )
    add_check(
        checks,
        "steeplechase_is_distance",
        steeple_misclassified == 0,
        steeple_misclassified,
        0,
        "3000m steeplechase must remain in Distance.",
    )

    rank_strength_invalid = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM (
            SELECT rank_strength_percentile AS value
            FROM school_season_event_base
            UNION ALL
            SELECT rank_strength_percentile AS value
            FROM school_season_group_base
        )
        WHERE value < 0 OR value > 1
        """,
    )
    add_check(
        checks,
        "rank_strength_percentiles_valid",
        rank_strength_invalid == 0,
        rank_strength_invalid,
        0,
        "Rank-strength percentiles must remain between zero and one.",
    )

    movement_duplicate_groups = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM (
            SELECT
                'event' AS level,
                model_key, cohort_key, current_season_year, season_type,
                gender_scope, canonical_event_code AS dimension_key,
                resolved_school_id, COUNT(*) AS n
            FROM school_season_event_movement
            GROUP BY ALL
            HAVING COUNT(*) > 1
            UNION ALL
            SELECT
                'group' AS level,
                model_key, cohort_key, current_season_year, season_type,
                gender_scope, balanced_group_key AS dimension_key,
                resolved_school_id, COUNT(*) AS n
            FROM school_season_group_movement
            GROUP BY ALL
            HAVING COUNT(*) > 1
        )
        """,
    )
    add_check(
        checks,
        "movement_keys_unique",
        movement_duplicate_groups == 0,
        movement_duplicate_groups,
        0,
        "Event and group movement natural keys must be unique.",
    )

    incorrect_previous_year = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM (
            SELECT
                current_season_year,
                CAST(SPLIT_PART(previous_season_key, '_', 1) AS INTEGER)
                    AS previous_year
            FROM school_season_event_movement
            WHERE is_comparable
            UNION ALL
            SELECT
                current_season_year,
                CAST(SPLIT_PART(previous_season_key, '_', 1) AS INTEGER)
                    AS previous_year
            FROM school_season_group_movement
            WHERE is_comparable
        )
        WHERE previous_year <> current_season_year - 1
        """,
    )
    add_check(
        checks,
        "comparable_movements_use_exact_previous_year",
        incorrect_previous_year == 0,
        incorrect_previous_year,
        0,
        "Comparable rows must use the exact prior calendar year and same season type.",
    )

    event_delta_errors = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_event_movement
        WHERE is_comparable
          AND ABS(
              primary_metric_delta
              - (current_primary_metric - previous_primary_metric)
          ) > 1e-9
        """,
    )
    group_delta_errors = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_group_movement
        WHERE is_comparable
          AND ABS(
              primary_metric_delta
              - (current_primary_metric - previous_primary_metric)
          ) > 1e-9
        """,
    )
    add_check(
        checks,
        "primary_metric_deltas_reconcile",
        event_delta_errors + group_delta_errors == 0,
        event_delta_errors + group_delta_errors,
        0,
        "Comparable score deltas must equal current minus previous.",
    )

    rank_delta_errors = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM (
            SELECT current_rank, previous_rank, rank_improvement
            FROM school_season_event_movement
            WHERE is_comparable
            UNION ALL
            SELECT current_rank, previous_rank, rank_improvement
            FROM school_season_group_movement
            WHERE is_comparable
        )
        WHERE rank_improvement <> previous_rank - current_rank
        """,
    )
    add_check(
        checks,
        "rank_improvement_reconciles",
        rank_delta_errors == 0,
        rank_delta_errors,
        0,
        "Rank improvement must equal previous rank minus current rank.",
    )

    noncomparable_delta_rows = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM (
            SELECT is_comparable, primary_metric_delta,
                   opportunity_adjusted_metric_delta, rank_improvement
            FROM school_season_event_movement
            UNION ALL
            SELECT is_comparable, primary_metric_delta,
                   opportunity_adjusted_metric_delta, rank_improvement
            FROM school_season_group_movement
        )
        WHERE NOT is_comparable
          AND (
              primary_metric_delta IS NOT NULL
              OR opportunity_adjusted_metric_delta IS NOT NULL
              OR rank_improvement IS NOT NULL
          )
        """,
    )
    add_check(
        checks,
        "noncomparable_rows_have_null_deltas",
        noncomparable_delta_rows == 0,
        noncomparable_delta_rows,
        0,
        "Unavailable comparisons must never receive fabricated deltas.",
    )

    fabricated_2020_outdoor = scalar(
        connection,
        """
        SELECT
            (SELECT COUNT(*) FROM school_season_event_base
             WHERE season_year = 2020 AND season_type = 'outdoor')
          + (SELECT COUNT(*) FROM school_season_group_base
             WHERE season_year = 2020 AND season_type = 'outdoor')
        """,
    )
    add_check(
        checks,
        "production_2020_outdoor_not_fabricated",
        fabricated_2020_outdoor == 0,
        fabricated_2020_outdoor,
        0,
        "The missing 2020 Outdoor production season must remain absent.",
    )

    invalid_window_counts = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM (
            SELECT window_years, observed_season_count,
                   eligible_observation_count
            FROM school_event_multiseason_trends
            UNION ALL
            SELECT window_years, observed_season_count,
                   eligible_observation_count
            FROM school_group_multiseason_trends
        )
        WHERE observed_season_count > window_years
           OR eligible_observation_count > observed_season_count
           OR observed_season_count < 1
        """,
    )
    add_check(
        checks,
        "rolling_window_counts_valid",
        invalid_window_counts == 0,
        invalid_window_counts,
        0,
        "Three- and five-year windows must obey calendar-window limits.",
    )

    invalid_slope_rows = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM (
            SELECT eligible_observation_count,
                   primary_metric_slope_per_year,
                   opportunity_adjusted_metric_slope_per_year,
                   rank_strength_slope_per_year
            FROM school_event_multiseason_trends
            UNION ALL
            SELECT eligible_observation_count,
                   primary_metric_slope_per_year,
                   opportunity_adjusted_metric_slope_per_year,
                   rank_strength_slope_per_year
            FROM school_group_multiseason_trends
        )
        WHERE eligible_observation_count < 3
          AND (
              primary_metric_slope_per_year IS NOT NULL
              OR opportunity_adjusted_metric_slope_per_year IS NOT NULL
              OR rank_strength_slope_per_year IS NOT NULL
          )
        """,
    )
    add_check(
        checks,
        "slopes_suppressed_below_three_observations",
        invalid_slope_rows == 0,
        invalid_slope_rows,
        0,
        "Trend slopes require at least three eligible observations.",
    )

    source_size_after = source_database.stat().st_size
    source_hash_after = sha256_file(source_database)
    add_check(
        checks,
        "all_inputs_unchanged",
        source_size_after == source_size_before
        and source_hash_after == source_hash_before,
        f"size={source_size_after}; sha256={source_hash_after}",
        f"size={source_size_before}; sha256={source_hash_before}",
        "The frozen Milestone 6 publication must remain byte-identical.",
    )

    return checks


def main() -> int:
    args = parse_args()
    source_dir = args.source_dir.resolve()
    output_dir = args.output_dir.resolve()

    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source_dir}")

    source_databases = sorted(source_dir.glob("*.duckdb"))
    if len(source_databases) != 1:
        raise RuntimeError(
            "Expected exactly one DuckDB file in the frozen Milestone 6 "
            f"publication; found {len(source_databases)}."
        )
    source_database = source_databases[0]

    if output_dir.exists():
        if not args.overwrite:
            raise FileExistsError(
                f"Output directory already exists: {output_dir}. "
                "Use --overwrite to rebuild it."
            )
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_database = output_dir / f"{DATASET_VERSION}.duckdb"
    source_size_before = source_database.stat().st_size
    source_hash_before = sha256_file(source_database)
    built_at_utc = datetime.now(timezone.utc).isoformat()

    connection = duckdb.connect(str(output_database))
    connection.execute("PRAGMA threads=4")
    connection.execute(
        f"ATTACH {sql_string(source_database)} AS src (READ_ONLY)"
    )

    connection.execute(
        """
        CREATE TABLE final_model_registry AS
        SELECT *
        FROM src.main.final_model_registry
        ORDER BY display_order
        """
    )
    connection.execute(
        """
        CREATE TABLE school_metadata AS
        SELECT *
        FROM src.main.school_metadata
        ORDER BY resolved_school_id
        """
    )
    connection.execute(
        """
        CREATE TABLE balanced_event_registry AS
        SELECT *
        FROM src.main.balanced_event_registry
        ORDER BY
            source_season_type,
            gender_scope,
            balanced_group_key,
            canonical_event_code
        """
    )

    connection.execute(
        """
        CREATE TABLE dataset_metadata (
            metadata_key VARCHAR,
            metadata_value VARCHAR
        )
        """
    )
    metadata_rows = [
        ("dataset_version", DATASET_VERSION),
        ("phase_version", PHASE_VERSION),
        ("publication_mode", "enhanced_primary_only"),
        ("official_primary_model", MODEL_KEY),
        ("built_at_utc", built_at_utc),
        ("source_database", str(source_database)),
        ("source_database_sha256", source_hash_before),
        (
            "movement_definition",
            "Exact previous calendar year within the same season type, gender, "
            "cohort, event/group, and school; no interpolation or carry-forward.",
        ),
        (
            "rank_improvement_definition",
            "Previous rank minus current rank; positive values indicate movement "
            "toward rank 1.",
        ),
        (
            "event_taxonomy",
            "Frozen 27-event championship taxonomy; 500m, 600m, and 1000m excluded.",
        ),
        (
            "group_taxonomy",
            "Frozen seven-group taxonomy; 3000m steeplechase belongs to Distance.",
        ),
    ]
    connection.executemany(
        "INSERT INTO dataset_metadata VALUES (?, ?)", metadata_rows
    )

    connection.execute(
        """
        CREATE TABLE input_manifest (
            input_name VARCHAR,
            absolute_path VARCHAR,
            size_bytes BIGINT,
            sha256 VARCHAR,
            access_mode VARCHAR
        )
        """
    )
    connection.execute(
        "INSERT INTO input_manifest VALUES (?, ?, ?, ?, ?)",
        [
            "final_milestone6_publication",
            str(source_database),
            source_size_before,
            source_hash_before,
            "read_only",
        ],
    )

    create_event_tables(connection)
    create_group_tables(connection)
    create_summaries(connection)

    checks = run_checks(
        connection,
        source_database,
        source_size_before,
        source_hash_before,
    )

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
                check.check_name,
                check.status,
                check.observed_value,
                check.expected_value,
                check.details,
            )
            for check in checks
        ],
    )

    table_exports = {
        "school_season_event_base.csv": "SELECT * FROM school_season_event_base",
        "school_season_event_movement.csv": (
            "SELECT * FROM school_season_event_movement"
        ),
        "school_event_multiseason_trends.csv": (
            "SELECT * FROM school_event_multiseason_trends"
        ),
        "school_season_group_base.csv": "SELECT * FROM school_season_group_base",
        "school_season_group_movement.csv": (
            "SELECT * FROM school_season_group_movement"
        ),
        "school_group_multiseason_trends.csv": (
            "SELECT * FROM school_group_multiseason_trends"
        ),
        "event_trend_partition_summary.csv": (
            "SELECT * FROM event_trend_partition_summary"
        ),
        "group_trend_partition_summary.csv": (
            "SELECT * FROM group_trend_partition_summary"
        ),
        "trend_comparison_status_summary.csv": (
            "SELECT * FROM trend_comparison_status_summary"
        ),
        "hard_checks.csv": "SELECT * FROM hard_checks ORDER BY check_name",
        "dataset_metadata.csv": (
            "SELECT * FROM dataset_metadata ORDER BY metadata_key"
        ),
        "input_manifest.csv": "SELECT * FROM input_manifest",
    }
    for filename, query in table_exports.items():
        export_query(connection, query, output_dir / filename)

    event_base_rows = scalar(
        connection, "SELECT COUNT(*) FROM school_season_event_base"
    )
    event_comparable_rows = scalar(
        connection,
        "SELECT COUNT(*) FROM school_season_event_movement WHERE is_comparable",
    )
    event_window_rows = scalar(
        connection, "SELECT COUNT(*) FROM school_event_multiseason_trends"
    )
    group_base_rows = scalar(
        connection, "SELECT COUNT(*) FROM school_season_group_base"
    )
    group_comparable_rows = scalar(
        connection,
        "SELECT COUNT(*) FROM school_season_group_movement WHERE is_comparable",
    )
    group_window_rows = scalar(
        connection, "SELECT COUNT(*) FROM school_group_multiseason_trends"
    )
    failed_checks = sum(check.status == "FAIL" for check in checks)

    report_lines = [
        "MILESTONE 7 — PHASE 7A.2 EVENT AND GROUP SEASONAL TRENDS",
        "=" * 76,
        "",
        f"Dataset version: {DATASET_VERSION}",
        f"Phase version: {PHASE_VERSION}",
        f"Built at UTC: {built_at_utc}",
        "Publication mode: enhanced_primary_only",
        "Official primary: Enhanced Balanced Production",
        f"Source database: {source_database}",
        f"Output database: {output_database}",
        "",
        "PUBLISHED ROW COUNTS",
        "-" * 76,
        f"Event base rows: {event_base_rows:,}",
        f"Comparable event year-over-year rows: {event_comparable_rows:,}",
        f"Event multiseason window rows: {event_window_rows:,}",
        f"Group base rows: {group_base_rows:,}",
        f"Comparable group year-over-year rows: {group_comparable_rows:,}",
        f"Group multiseason window rows: {group_window_rows:,}",
        "",
        "FROZEN POLICIES",
        "-" * 76,
        "- Enhanced Balanced Production is the exclusive published model.",
        "- Year-over-year comparisons require the exact prior calendar year",
        "  within the same season type, gender, cohort, event/group, and school.",
        "- Missing partitions and schools remain explicitly unavailable.",
        "- No interpolation, carry-forward, or zero-filling is permitted.",
        "- 500m, 600m, and 1000m are excluded.",
        "- 3000m steeplechase is classified as Distance.",
        "- Trend slopes require at least three eligible observations.",
        "",
        "HARD CHECKS",
        "-" * 76,
        f"Total checks: {len(checks)}",
        f"Failed checks: {failed_checks}",
        "",
    ]
    report_lines.extend(
        f"[{check.status}] {check.check_name}: "
        f"observed={check.observed_value}; expected={check.expected_value}"
        for check in checks
    )
    (output_dir / "phase_7a_2_report.txt").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )

    connection.execute("CHECKPOINT")
    connection.close()
    write_output_manifest(output_dir)

    print(f"Dataset version: {DATASET_VERSION}")
    print("Publication mode: enhanced_primary_only")
    print("Official primary: Enhanced Balanced Production")
    print(f"Source database: {source_database}")
    print(f"Output database: {output_database}")
    print(f"Event base rows: {event_base_rows:,}")
    print(f"Comparable event year-over-year rows: {event_comparable_rows:,}")
    print(f"Event multiseason window rows: {event_window_rows:,}")
    print(f"Group base rows: {group_base_rows:,}")
    print(f"Comparable group year-over-year rows: {group_comparable_rows:,}")
    print(f"Group multiseason window rows: {group_window_rows:,}")
    print(f"Failed checks: {failed_checks}")
    print()

    if failed_checks:
        print("PHASE GATE: FAIL")
        return 1

    print("PHASE GATE: PASS")
    print("Phase 7A.2 event and group seasonal trends published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
