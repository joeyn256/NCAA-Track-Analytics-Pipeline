#!/usr/bin/env python3
"""Build Milestone 7 Phase 7A.1 overall seasonal trend foundations.

This builder reads the frozen Milestone 6 final publication in read-only mode and
creates descriptive season-over-season outputs centered on Enhanced Balanced
Production, the official primary model.

By default, only Enhanced Balanced Production is published. The two frozen companion
models can be included with ``--include-companions`` when their inclusion is useful
and low-cost:

1. Original Balanced Production v4.1
2. Average Athlete Development

The script does not modify Milestone 5 or Milestone 6 artifacts. It publishes:

- a unified school-season overall base table;
- exact same-season-type year-over-year movement;
- same-year indoor-versus-outdoor comparisons;
- three- and five-year calendar-window summaries;
- coverage, missingness, methodology, manifests, and hard checks.

Missing seasons are never interpolated, carried forward, or converted to zero.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


DATASET_VERSION = "seasonal_program_trends_v1"
PHASE_VERSION = "phase_7a_1_overall_trends_v3"
DEFAULT_SOURCE_DIR = Path(
    "data/processed/milestone6/"
    "final_development_rankings_v1/"
    "phase_6g_final_publication"
)
DEFAULT_OUTPUT_DIR = Path(
    "data/processed/milestone7/"
    "seasonal_program_trends_v1/"
    "phase_7a_overall_trends"
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
            "Build Milestone 7 Phase 7A.1 overall seasonal trend outputs "
            "from the frozen Milestone 6 publication."
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
        help="Phase 7A.1 output directory.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete and rebuild the output directory when it already exists.",
    )
    parser.add_argument(
        "--include-companions",
        action="store_true",
        help=(
            "Also publish Original Balanced Production v4.1 and Average Athlete "
            "Development. The default publication contains only the official "
            "Enhanced Balanced Production model."
        ),
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


def as_float(value: Any) -> float:
    if value is None:
        return math.nan
    return float(value)


def add_boolean_check(
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


def main() -> int:
    args = parse_args()
    source_dir = args.source_dir.resolve()
    output_dir = args.output_dir.resolve()
    include_companions = bool(args.include_companions)
    production_model_filter = (
        "model_key IN ('enhanced_balanced_production', "
        "'original_balanced_production_v4_1')"
        if include_companions
        else "model_key = 'enhanced_balanced_production'"
    )
    average_source_filter = "TRUE" if include_companions else "FALSE"
    publication_mode = (
        "enhanced_plus_companions"
        if include_companions
        else "enhanced_primary_only"
    )

    if not source_dir.exists():
        raise FileNotFoundError(
            f"Milestone 6 source directory does not exist: {source_dir}"
        )

    source_databases = sorted(source_dir.glob("*.duckdb"))
    if len(source_databases) != 1:
        raise RuntimeError(
            "Expected exactly one DuckDB file in the final Milestone 6 "
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

    # ------------------------------------------------------------------
    # Frozen registries and metadata
    # ------------------------------------------------------------------
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
        f"""
        CREATE TABLE dataset_metadata (
            metadata_key VARCHAR,
            metadata_value VARCHAR
        )
        """
    )
    metadata_rows = [
        ("dataset_version", DATASET_VERSION),
        ("phase_version", PHASE_VERSION),
        ("publication_mode", publication_mode),
        ("official_primary_model", "enhanced_balanced_production"),
        ("companions_included", str(include_companions).lower()),
        ("built_at_utc", built_at_utc),
        ("source_database", str(source_database)),
        ("source_database_sha256", source_hash_before),
        (
            "movement_definition",
            "Exact previous calendar year within the same season type; "
            "no interpolation or carry-forward.",
        ),
        (
            "rank_improvement_definition",
            "previous rank minus current rank; positive values indicate "
            "movement toward rank 1.",
        ),
        (
            "rank_strength_definition",
            "1 - (rank - 1) / (ranked_school_count - 1); higher is better.",
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

    # ------------------------------------------------------------------
    # Season registry
    # ------------------------------------------------------------------
    connection.execute(
        f"""
        CREATE TABLE trend_season_registry AS
        WITH production AS (
            SELECT DISTINCT
                season_year,
                season_type,
                season_key,
                season_label
            FROM src.main.event_balanced_overall_combined
            WHERE time_scope = 'single_season'
              AND {production_model_filter}
        ),
        average_development AS (
            SELECT DISTINCT
                season_year,
                season_type,
                season_key,
                season_label
            FROM src.main.average_development_seasonal_rankings
            WHERE ranking_key = 'overall'
              AND {average_source_filter}
        ),
        all_seasons AS (
            SELECT * FROM production
            UNION
            SELECT * FROM average_development
        )
        SELECT
            season_year,
            season_type,
            season_key,
            season_label,
            2 * season_year
                + CASE WHEN season_type = 'outdoor' THEN 1 ELSE 0 END
                AS season_order,
            season_year - 1 AS previous_same_type_year,
            CAST(season_year - 1 AS VARCHAR)
                || '_'
                || season_type AS previous_same_type_key,
            EXISTS (
                SELECT 1
                FROM production p
                WHERE p.season_year = all_seasons.season_year
                  AND p.season_type = all_seasons.season_type
            ) AS production_observed,
            EXISTS (
                SELECT 1
                FROM average_development a
                WHERE a.season_year = all_seasons.season_year
                  AND a.season_type = all_seasons.season_type
            ) AS average_development_observed,
            EXISTS (
                SELECT 1
                FROM all_seasons previous
                WHERE previous.season_year = all_seasons.season_year - 1
                  AND previous.season_type = all_seasons.season_type
            ) AS previous_same_type_observed_any_model
        FROM all_seasons
        ORDER BY season_year, season_order
        """
    )

    # ------------------------------------------------------------------
    # Unified production overall source
    # ------------------------------------------------------------------
    connection.execute(
        f"""
        CREATE TEMP TABLE production_overall_source AS
        SELECT
            model_key,
            cohort_key,
            time_scope,
            season_year,
            season_type,
            model_label,
            is_primary,
            cohort_label,
            publication_tier,
            season_key,
            season_label,
            'production_overall_combined' AS ranking_scope,
            'all' AS gender_scope,
            resolved_school_id,
            school_name,
            total_positive_event_points,
            total_negative_event_points,
            total_event_balanced_points,
            athlete_event_unit_count,
            positive_athlete_count,
            negative_athlete_count,
            scoring_event_count,
            represented_event_count,
            publishable_event_count,
            CAST(available_event_points AS DOUBLE) AS available_event_points,
            positive_share_of_available_points,
            total_event_balanced_points
                / NULLIF(CAST(available_event_points AS DOUBLE), 0.0)
                AS net_share_of_available_points,
            net_points_per_athlete_event_unit,
            event_balanced_rank,
            dataset_version
        FROM src.main.event_balanced_overall_combined
        WHERE time_scope = 'single_season'
          AND {production_model_filter}

        UNION ALL

        SELECT
            model_key,
            cohort_key,
            time_scope,
            season_year,
            season_type,
            model_label,
            is_primary,
            cohort_label,
            publication_tier,
            season_key,
            season_label,
            'production_overall_gender' AS ranking_scope,
            gender_scope,
            resolved_school_id,
            school_name,
            total_positive_event_points,
            total_negative_event_points,
            total_event_balanced_points,
            athlete_event_unit_count,
            positive_athlete_count,
            negative_athlete_count,
            scoring_event_count,
            represented_event_count,
            publishable_event_count,
            CAST(available_event_points AS DOUBLE) AS available_event_points,
            positive_share_of_available_points,
            total_event_balanced_points
                / NULLIF(CAST(available_event_points AS DOUBLE), 0.0)
                AS net_share_of_available_points,
            net_points_per_athlete_event_unit,
            event_balanced_rank,
            dataset_version
        FROM src.main.event_balanced_overall_gender
        WHERE time_scope = 'single_season'
          AND {production_model_filter}
        """
    )

    # ------------------------------------------------------------------
    # Unified school-season overall base
    # ------------------------------------------------------------------
    connection.execute(
        f"""
        CREATE TABLE school_season_overall_base AS
        WITH production_ranked AS (
            SELECT
                source.*,
                COUNT(*) OVER (
                    PARTITION BY
                        model_key,
                        cohort_key,
                        ranking_scope,
                        gender_scope,
                        season_year,
                        season_type
                ) AS ranked_school_count
            FROM production_overall_source source
        ),
        production_rows AS (
            SELECT
                source.model_key,
                source.model_label,
                registry.model_role,
                source.is_primary AS is_official_primary,
                'production' AS model_family,
                source.cohort_key,
                source.cohort_label,
                source.publication_tier,
                source.time_scope,
                source.ranking_scope,
                source.season_year,
                source.season_type,
                source.season_key,
                source.season_label,
                source.gender_scope,
                source.resolved_school_id,
                source.school_name,
                metadata.state_code,
                metadata.city,
                metadata.conference_name,
                metadata.division_name,
                TRUE AS source_eligible,
                'total_event_balanced_points' AS primary_metric_name,
                source.total_event_balanced_points AS primary_metric_value,
                'net_share_of_available_points'
                    AS opportunity_adjusted_metric_name,
                source.net_share_of_available_points
                    AS opportunity_adjusted_metric_value,
                source.total_positive_event_points AS positive_points,
                source.total_negative_event_points AS negative_points,
                source.total_event_balanced_points AS net_points,
                source.available_event_points AS available_points,
                source.positive_share_of_available_points AS positive_share,
                source.net_share_of_available_points AS net_share,
                CAST(source.athlete_event_unit_count AS BIGINT)
                    AS athlete_unit_count,
                CAST(source.positive_athlete_count AS BIGINT)
                    AS positive_athlete_count,
                CAST(source.negative_athlete_count AS BIGINT)
                    AS negative_athlete_count,
                source.scoring_event_count AS scoring_unit_count,
                source.represented_event_count AS represented_unit_count,
                source.publishable_event_count AS publishable_unit_count,
                source.scoring_event_count
                    / NULLIF(CAST(source.publishable_event_count AS DOUBLE), 0.0)
                    AS scoring_breadth,
                source.event_balanced_rank AS source_rank,
                source.event_balanced_rank AS all_school_rank,
                source.ranked_school_count,
                CASE
                    WHEN source.ranked_school_count = 1 THEN 1.0
                    WHEN source.ranked_school_count > 1 THEN
                        1.0
                        - (
                            source.event_balanced_rank - 1.0
                          )
                          / (source.ranked_school_count - 1.0)
                    ELSE NULL
                END AS rank_strength_percentile,
                CAST(NULL AS DOUBLE) AS posterior_ci95_lower,
                CAST(NULL AS DOUBLE) AS posterior_ci95_upper,
                CAST(NULL AS DOUBLE) AS raw_school_score,
                CAST(NULL AS DOUBLE) AS shrinkage_weight,
                CAST(NULL AS VARCHAR) AS evidence_category,
                CAST(NULL AS VARCHAR) AS variance_status,
                source.dataset_version AS source_dataset_version
            FROM production_ranked source
            JOIN final_model_registry registry
              ON registry.model_key = source.model_key
            LEFT JOIN school_metadata metadata
              ON metadata.resolved_school_id = source.resolved_school_id
        ),
        average_rows AS (
            SELECT
                'average_athlete_development' AS model_key,
                'Average Athlete Development' AS model_label,
                'efficiency_companion' AS model_role,
                FALSE AS is_official_primary,
                'average_development' AS model_family,
                'all_athletes' AS cohort_key,
                'All Eligible Athletes' AS cohort_label,
                'secondary_companion' AS publication_tier,
                'single_season' AS time_scope,
                source.ranking_scope,
                source.season_year,
                source.season_type,
                source.season_key,
                source.season_label,
                source.gender_scope,
                source.resolved_school_id,
                source.school_name,
                source.state_code,
                source.city,
                source.conference_name,
                source.division_name,
                source.official_rank_eligible AS source_eligible,
                'posterior_school_score' AS primary_metric_name,
                source.posterior_school_score AS primary_metric_value,
                'season_centered_posterior_score'
                    AS opportunity_adjusted_metric_name,
                source.season_centered_posterior_score
                    AS opportunity_adjusted_metric_value,
                CAST(NULL AS DOUBLE) AS positive_points,
                CAST(NULL AS DOUBLE) AS negative_points,
                CAST(NULL AS DOUBLE) AS net_points,
                CAST(NULL AS DOUBLE) AS available_points,
                CAST(NULL AS DOUBLE) AS positive_share,
                CAST(NULL AS DOUBLE) AS net_share,
                source.athlete_unit_count,
                CAST(NULL AS BIGINT) AS positive_athlete_count,
                CAST(NULL AS BIGINT) AS negative_athlete_count,
                CAST(NULL AS BIGINT) AS scoring_unit_count,
                CAST(NULL AS BIGINT) AS represented_unit_count,
                CAST(NULL AS BIGINT) AS publishable_unit_count,
                CAST(NULL AS DOUBLE) AS scoring_breadth,
                source.official_rank AS source_rank,
                source.all_school_rank,
                source.official_ranked_school_count AS ranked_school_count,
                CASE
                    WHEN NOT source.official_rank_eligible THEN NULL
                    WHEN source.official_ranked_school_count = 1 THEN 1.0
                    WHEN source.official_ranked_school_count > 1 THEN
                        1.0
                        - (source.official_rank - 1.0)
                          / (source.official_ranked_school_count - 1.0)
                    ELSE NULL
                END AS rank_strength_percentile,
                source.posterior_ci95_lower,
                source.posterior_ci95_upper,
                source.raw_school_score,
                source.shrinkage_weight,
                source.evidence_category,
                source.variance_status,
                source.dataset_version AS source_dataset_version
            FROM src.main.average_development_seasonal_rankings source
            WHERE {average_source_filter}
              AND source.ranking_key = 'overall'
              AND source.ranking_scope IN (
                    'season_overall_combined',
                    'season_overall_gender'
              )
        )
        SELECT * FROM production_rows
        UNION ALL
        SELECT * FROM average_rows
        ORDER BY
            model_key,
            cohort_key,
            ranking_scope,
            gender_scope,
            season_year,
            season_type,
            resolved_school_id
        """
    )

    connection.execute(
        """
        CREATE TABLE overall_partition_registry AS
        SELECT
            model_key,
            model_label,
            model_family,
            cohort_key,
            cohort_label,
            publication_tier,
            ranking_scope,
            gender_scope,
            season_year,
            season_type,
            season_key,
            season_label,
            COUNT(*) AS school_row_count,
            COUNT(*) FILTER (WHERE source_eligible)
                AS eligible_school_count,
            COUNT(DISTINCT resolved_school_id) AS distinct_school_count
        FROM school_season_overall_base
        GROUP BY ALL
        ORDER BY
            model_key,
            cohort_key,
            ranking_scope,
            gender_scope,
            season_year,
            season_type
        """
    )

    # ------------------------------------------------------------------
    # Exact previous-year, same-season-type movement
    # ------------------------------------------------------------------
    connection.execute(
        """
        CREATE TABLE school_season_overall_movement AS
        SELECT
            current.model_key,
            current.model_label,
            current.model_role,
            current.is_official_primary,
            current.model_family,
            current.cohort_key,
            current.cohort_label,
            current.publication_tier,
            current.ranking_scope,
            current.gender_scope,
            current.resolved_school_id,
            current.school_name,
            current.state_code,
            current.city,
            current.conference_name,
            current.division_name,
            current.season_year AS current_season_year,
            current.season_type,
            current.season_key AS current_season_key,
            current.season_label AS current_season_label,
            current.season_year - 1 AS expected_previous_year,
            CAST(current.season_year - 1 AS VARCHAR)
                || '_'
                || current.season_type AS expected_previous_season_key,
            previous.season_year AS previous_season_year,
            previous.season_key AS previous_season_key,
            previous.season_label AS previous_season_label,
            CASE
                WHEN previous.season_year IS NULL THEN NULL
                ELSE current.season_year - previous.season_year
            END AS year_gap,
            current.source_eligible AS current_source_eligible,
            previous.source_eligible AS previous_source_eligible,
            previous_partition.season_key IS NOT NULL
                AS previous_partition_available,
            previous.resolved_school_id IS NOT NULL
                AS previous_school_observation_available,
            CASE
                WHEN NOT current.source_eligible
                    THEN 'current_ineligible'
                WHEN previous_partition.season_key IS NULL
                    THEN 'previous_partition_unavailable'
                WHEN previous.resolved_school_id IS NULL
                    THEN 'school_missing_previous_season'
                WHEN NOT previous.source_eligible
                    THEN 'previous_ineligible'
                WHEN current.season_year - previous.season_year <> 1
                    THEN 'nonconsecutive_year_gap'
                ELSE 'comparable'
            END AS comparison_status,
            CASE
                WHEN current.source_eligible
                 AND COALESCE(previous.source_eligible, FALSE)
                 AND previous.season_year = current.season_year - 1
                THEN TRUE
                ELSE FALSE
            END AS is_comparable,
            current.primary_metric_name,
            current.primary_metric_value AS current_primary_metric,
            previous.primary_metric_value AS previous_primary_metric,
            CASE
                WHEN current.source_eligible
                 AND previous.source_eligible
                 AND current.season_year - previous.season_year = 1
                THEN current.primary_metric_value
                   - previous.primary_metric_value
                ELSE NULL
            END AS primary_metric_delta,
            current.opportunity_adjusted_metric_name,
            current.opportunity_adjusted_metric_value
                AS current_opportunity_adjusted_metric,
            previous.opportunity_adjusted_metric_value
                AS previous_opportunity_adjusted_metric,
            CASE
                WHEN current.source_eligible
                 AND previous.source_eligible
                 AND current.season_year - previous.season_year = 1
                THEN current.opportunity_adjusted_metric_value
                   - previous.opportunity_adjusted_metric_value
                ELSE NULL
            END AS opportunity_adjusted_metric_delta,
            current.source_rank AS current_rank,
            previous.source_rank AS previous_rank,
            CASE
                WHEN current.source_eligible
                 AND previous.source_eligible
                 AND current.season_year - previous.season_year = 1
                THEN previous.source_rank - current.source_rank
                ELSE NULL
            END AS rank_improvement,
            current.rank_strength_percentile
                AS current_rank_strength_percentile,
            previous.rank_strength_percentile
                AS previous_rank_strength_percentile,
            CASE
                WHEN current.source_eligible
                 AND previous.source_eligible
                 AND current.season_year - previous.season_year = 1
                THEN current.rank_strength_percentile
                   - previous.rank_strength_percentile
                ELSE NULL
            END AS rank_strength_delta,
            current.positive_share AS current_positive_share,
            previous.positive_share AS previous_positive_share,
            CASE
                WHEN current.source_eligible
                 AND previous.source_eligible
                 AND current.season_year - previous.season_year = 1
                THEN current.positive_share - previous.positive_share
                ELSE NULL
            END AS positive_share_delta,
            current.net_share AS current_net_share,
            previous.net_share AS previous_net_share,
            CASE
                WHEN current.source_eligible
                 AND previous.source_eligible
                 AND current.season_year - previous.season_year = 1
                THEN current.net_share - previous.net_share
                ELSE NULL
            END AS net_share_delta,
            current.scoring_breadth AS current_scoring_breadth,
            previous.scoring_breadth AS previous_scoring_breadth,
            CASE
                WHEN current.source_eligible
                 AND previous.source_eligible
                 AND current.season_year - previous.season_year = 1
                THEN current.scoring_breadth - previous.scoring_breadth
                ELSE NULL
            END AS scoring_breadth_delta,
            current.athlete_unit_count AS current_athlete_unit_count,
            previous.athlete_unit_count AS previous_athlete_unit_count,
            CASE
                WHEN current.source_eligible
                 AND previous.source_eligible
                 AND current.season_year - previous.season_year = 1
                THEN current.athlete_unit_count
                   - previous.athlete_unit_count
                ELSE NULL
            END AS athlete_unit_count_delta,
            CASE
                WHEN NOT (
                    current.source_eligible
                    AND previous.source_eligible
                    AND current.season_year - previous.season_year = 1
                ) THEN 'not_comparable'
                WHEN ABS(
                    current.primary_metric_value
                    - previous.primary_metric_value
                ) < 1e-12
                 AND previous.source_rank - current.source_rank = 0
                    THEN 'unchanged'
                WHEN current.primary_metric_value
                     - previous.primary_metric_value > 0
                 AND previous.source_rank - current.source_rank > 0
                    THEN 'score_up_rank_up'
                WHEN current.primary_metric_value
                     - previous.primary_metric_value > 0
                 AND previous.source_rank - current.source_rank < 0
                    THEN 'score_up_rank_down'
                WHEN current.primary_metric_value
                     - previous.primary_metric_value < 0
                 AND previous.source_rank - current.source_rank > 0
                    THEN 'score_down_rank_up'
                WHEN current.primary_metric_value
                     - previous.primary_metric_value < 0
                 AND previous.source_rank - current.source_rank < 0
                    THEN 'score_down_rank_down'
                WHEN current.primary_metric_value
                     - previous.primary_metric_value > 0
                    THEN 'score_up_rank_flat'
                WHEN current.primary_metric_value
                     - previous.primary_metric_value < 0
                    THEN 'score_down_rank_flat'
                WHEN previous.source_rank - current.source_rank > 0
                    THEN 'score_flat_rank_up'
                WHEN previous.source_rank - current.source_rank < 0
                    THEN 'score_flat_rank_down'
                ELSE 'unchanged'
            END AS rank_score_alignment,
            CASE
                WHEN NOT current.source_eligible
                    THEN 'current_ineligible'
                WHEN previous.resolved_school_id IS NULL
                    THEN 'previous_observation_missing'
                WHEN NOT previous.source_eligible
                    THEN 'previous_ineligible'
                WHEN current.model_family = 'production'
                 AND current.scoring_breadth < 0.5
                    THEN 'current_low_scoring_breadth'
                WHEN current.model_family = 'production'
                 AND previous.scoring_breadth < 0.5
                    THEN 'previous_low_scoring_breadth'
                ELSE 'none'
            END AS support_warning,
            current.evidence_category AS current_evidence_category,
            previous.evidence_category AS previous_evidence_category,
            current.variance_status AS current_variance_status,
            previous.variance_status AS previous_variance_status,
            current.source_dataset_version
        FROM school_season_overall_base current
        LEFT JOIN overall_partition_registry previous_partition
          ON previous_partition.model_key = current.model_key
         AND previous_partition.cohort_key = current.cohort_key
         AND previous_partition.ranking_scope = current.ranking_scope
         AND previous_partition.gender_scope = current.gender_scope
         AND previous_partition.season_type = current.season_type
         AND previous_partition.season_year = current.season_year - 1
        LEFT JOIN school_season_overall_base previous
          ON previous.model_key = current.model_key
         AND previous.cohort_key = current.cohort_key
         AND previous.ranking_scope = current.ranking_scope
         AND previous.gender_scope = current.gender_scope
         AND previous.resolved_school_id = current.resolved_school_id
         AND previous.season_type = current.season_type
         AND previous.season_year = current.season_year - 1
        ORDER BY
            current.model_key,
            current.cohort_key,
            current.ranking_scope,
            current.gender_scope,
            current.resolved_school_id,
            current.season_type,
            current.season_year
        """
    )

    # ------------------------------------------------------------------
    # Same-year indoor versus outdoor comparisons
    # ------------------------------------------------------------------
    connection.execute(
        """
        CREATE TABLE school_indoor_outdoor_comparison AS
        WITH indoor AS (
            SELECT *
            FROM school_season_overall_base
            WHERE season_type = 'indoor'
        ),
        outdoor AS (
            SELECT *
            FROM school_season_overall_base
            WHERE season_type = 'outdoor'
        )
        SELECT
            COALESCE(outdoor.model_key, indoor.model_key) AS model_key,
            COALESCE(outdoor.model_label, indoor.model_label) AS model_label,
            COALESCE(outdoor.model_role, indoor.model_role) AS model_role,
            COALESCE(
                outdoor.is_official_primary,
                indoor.is_official_primary
            ) AS is_official_primary,
            COALESCE(outdoor.model_family, indoor.model_family)
                AS model_family,
            COALESCE(outdoor.cohort_key, indoor.cohort_key) AS cohort_key,
            COALESCE(outdoor.cohort_label, indoor.cohort_label)
                AS cohort_label,
            COALESCE(outdoor.publication_tier, indoor.publication_tier)
                AS publication_tier,
            COALESCE(outdoor.ranking_scope, indoor.ranking_scope)
                AS ranking_scope,
            COALESCE(outdoor.gender_scope, indoor.gender_scope)
                AS gender_scope,
            COALESCE(outdoor.resolved_school_id, indoor.resolved_school_id)
                AS resolved_school_id,
            COALESCE(outdoor.school_name, indoor.school_name) AS school_name,
            COALESCE(outdoor.state_code, indoor.state_code) AS state_code,
            COALESCE(outdoor.city, indoor.city) AS city,
            COALESCE(outdoor.conference_name, indoor.conference_name)
                AS conference_name,
            COALESCE(outdoor.division_name, indoor.division_name)
                AS division_name,
            COALESCE(outdoor.season_year, indoor.season_year) AS season_year,
            indoor.season_key AS indoor_season_key,
            outdoor.season_key AS outdoor_season_key,
            indoor.resolved_school_id IS NOT NULL AS indoor_observed,
            outdoor.resolved_school_id IS NOT NULL AS outdoor_observed,
            indoor.source_eligible AS indoor_source_eligible,
            outdoor.source_eligible AS outdoor_source_eligible,
            CASE
                WHEN indoor.resolved_school_id IS NULL
                    THEN 'indoor_missing'
                WHEN outdoor.resolved_school_id IS NULL
                    THEN 'outdoor_missing'
                WHEN NOT indoor.source_eligible
                 AND NOT outdoor.source_eligible
                    THEN 'both_ineligible'
                WHEN NOT indoor.source_eligible
                    THEN 'indoor_ineligible'
                WHEN NOT outdoor.source_eligible
                    THEN 'outdoor_ineligible'
                ELSE 'comparable'
            END AS comparison_status,
            CASE
                WHEN COALESCE(indoor.source_eligible, FALSE)
                 AND COALESCE(outdoor.source_eligible, FALSE)
                THEN TRUE
                ELSE FALSE
            END AS is_comparable,
            COALESCE(
                outdoor.primary_metric_name,
                indoor.primary_metric_name
            ) AS primary_metric_name,
            indoor.primary_metric_value AS indoor_primary_metric,
            outdoor.primary_metric_value AS outdoor_primary_metric,
            CASE
                WHEN indoor.source_eligible
                 AND outdoor.source_eligible
                THEN outdoor.primary_metric_value
                   - indoor.primary_metric_value
                ELSE NULL
            END AS outdoor_minus_indoor_primary_metric,
            COALESCE(
                outdoor.opportunity_adjusted_metric_name,
                indoor.opportunity_adjusted_metric_name
            ) AS opportunity_adjusted_metric_name,
            indoor.opportunity_adjusted_metric_value
                AS indoor_opportunity_adjusted_metric,
            outdoor.opportunity_adjusted_metric_value
                AS outdoor_opportunity_adjusted_metric,
            CASE
                WHEN indoor.source_eligible
                 AND outdoor.source_eligible
                THEN outdoor.opportunity_adjusted_metric_value
                   - indoor.opportunity_adjusted_metric_value
                ELSE NULL
            END AS outdoor_minus_indoor_opportunity_metric,
            indoor.source_rank AS indoor_rank,
            outdoor.source_rank AS outdoor_rank,
            CASE
                WHEN indoor.source_eligible
                 AND outdoor.source_eligible
                THEN indoor.source_rank - outdoor.source_rank
                ELSE NULL
            END AS outdoor_rank_improvement,
            indoor.rank_strength_percentile
                AS indoor_rank_strength_percentile,
            outdoor.rank_strength_percentile
                AS outdoor_rank_strength_percentile,
            CASE
                WHEN indoor.source_eligible
                 AND outdoor.source_eligible
                THEN outdoor.rank_strength_percentile
                   - indoor.rank_strength_percentile
                ELSE NULL
            END AS outdoor_minus_indoor_rank_strength,
            indoor.positive_share AS indoor_positive_share,
            outdoor.positive_share AS outdoor_positive_share,
            CASE
                WHEN indoor.source_eligible
                 AND outdoor.source_eligible
                THEN outdoor.positive_share - indoor.positive_share
                ELSE NULL
            END AS outdoor_minus_indoor_positive_share,
            indoor.net_share AS indoor_net_share,
            outdoor.net_share AS outdoor_net_share,
            CASE
                WHEN indoor.source_eligible
                 AND outdoor.source_eligible
                THEN outdoor.net_share - indoor.net_share
                ELSE NULL
            END AS outdoor_minus_indoor_net_share,
            indoor.scoring_breadth AS indoor_scoring_breadth,
            outdoor.scoring_breadth AS outdoor_scoring_breadth,
            CASE
                WHEN indoor.source_eligible
                 AND outdoor.source_eligible
                THEN outdoor.scoring_breadth
                   - indoor.scoring_breadth
                ELSE NULL
            END AS outdoor_minus_indoor_scoring_breadth,
            indoor.athlete_unit_count AS indoor_athlete_unit_count,
            outdoor.athlete_unit_count AS outdoor_athlete_unit_count,
            CASE
                WHEN indoor.source_eligible
                 AND outdoor.source_eligible
                THEN outdoor.athlete_unit_count
                   - indoor.athlete_unit_count
                ELSE NULL
            END AS outdoor_minus_indoor_athlete_units,
            COALESCE(
                outdoor.source_dataset_version,
                indoor.source_dataset_version
            ) AS source_dataset_version
        FROM indoor
        FULL OUTER JOIN outdoor
          ON outdoor.model_key = indoor.model_key
         AND outdoor.cohort_key = indoor.cohort_key
         AND outdoor.ranking_scope = indoor.ranking_scope
         AND outdoor.gender_scope = indoor.gender_scope
         AND outdoor.resolved_school_id = indoor.resolved_school_id
         AND outdoor.season_year = indoor.season_year
        ORDER BY
            model_key,
            cohort_key,
            ranking_scope,
            gender_scope,
            resolved_school_id,
            season_year
        """
    )

    # ------------------------------------------------------------------
    # Three- and five-year calendar windows
    # ------------------------------------------------------------------
    connection.execute(
        """
        CREATE TABLE school_multiseason_trends AS
        WITH window_sizes AS (
            SELECT 3 AS window_years
            UNION ALL
            SELECT 5 AS window_years
        ),
        aggregated AS (
            SELECT
                current.model_key,
                current.model_label,
                current.model_role,
                current.is_official_primary,
                current.model_family,
                current.cohort_key,
                current.cohort_label,
                current.publication_tier,
                current.ranking_scope,
                current.gender_scope,
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
                current.source_eligible AS endpoint_source_eligible,
                current.primary_metric_name,
                current.opportunity_adjusted_metric_name,
                window_sizes.window_years,
                current.season_year - window_sizes.window_years + 1
                    AS window_start_year,
                current.season_year AS window_end_year,
                COUNT(DISTINCT history.season_year)
                    AS observed_season_count,
                COUNT(DISTINCT history.season_year) FILTER (
                    WHERE history.source_eligible
                ) AS eligible_observation_count,
                COUNT(DISTINCT history.season_year) FILTER (
                    WHERE history.season_year = current.season_year
                ) > 0 AS endpoint_observation_included,
                AVG(history.primary_metric_value) FILTER (
                    WHERE history.source_eligible
                ) AS mean_primary_metric,
                MEDIAN(history.primary_metric_value) FILTER (
                    WHERE history.source_eligible
                ) AS median_primary_metric,
                MAD(history.primary_metric_value) FILTER (
                    WHERE history.source_eligible
                ) AS median_absolute_deviation_primary_metric,
                STDDEV_SAMP(history.primary_metric_value) FILTER (
                    WHERE history.source_eligible
                ) AS standard_deviation_primary_metric,
                MIN(history.primary_metric_value) FILTER (
                    WHERE history.source_eligible
                ) AS minimum_primary_metric,
                MAX(history.primary_metric_value) FILTER (
                    WHERE history.source_eligible
                ) AS maximum_primary_metric,
                ARG_MIN(
                    history.primary_metric_value,
                    history.season_year
                ) FILTER (
                    WHERE history.source_eligible
                ) AS first_primary_metric,
                ARG_MAX(
                    history.primary_metric_value,
                    history.season_year
                ) FILTER (
                    WHERE history.source_eligible
                ) AS last_primary_metric,
                CASE
                    WHEN COUNT(DISTINCT history.season_year) FILTER (
                        WHERE history.source_eligible
                    ) >= 3
                    THEN REGR_SLOPE(
                        history.primary_metric_value,
                        history.season_year
                    ) FILTER (
                        WHERE history.source_eligible
                    )
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
                    ) FILTER (
                        WHERE history.source_eligible
                    )
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
                    ) FILTER (
                        WHERE history.source_eligible
                    )
                    ELSE NULL
                END AS rank_strength_slope_per_year,
                AVG(history.scoring_breadth) FILTER (
                    WHERE history.source_eligible
                ) AS mean_scoring_breadth,
                CASE
                    WHEN COUNT(DISTINCT history.season_year) FILTER (
                        WHERE history.source_eligible
                    ) >= 3
                    THEN REGR_SLOPE(
                        history.scoring_breadth,
                        history.season_year
                    ) FILTER (
                        WHERE history.source_eligible
                    )
                    ELSE NULL
                END AS scoring_breadth_slope_per_year,
                AVG(history.athlete_unit_count) FILTER (
                    WHERE history.source_eligible
                ) AS mean_athlete_unit_count,
                CASE
                    WHEN COUNT(DISTINCT history.season_year) FILTER (
                        WHERE history.source_eligible
                    ) >= 3
                    THEN REGR_SLOPE(
                        CAST(history.athlete_unit_count AS DOUBLE),
                        history.season_year
                    ) FILTER (
                        WHERE history.source_eligible
                    )
                    ELSE NULL
                END AS athlete_unit_count_slope_per_year
            FROM school_season_overall_base current
            CROSS JOIN window_sizes
            LEFT JOIN school_season_overall_base history
              ON history.model_key = current.model_key
             AND history.cohort_key = current.cohort_key
             AND history.ranking_scope = current.ranking_scope
             AND history.gender_scope = current.gender_scope
             AND history.resolved_school_id = current.resolved_school_id
             AND history.season_type = current.season_type
             AND history.season_year BETWEEN
                    current.season_year - window_sizes.window_years + 1
                    AND current.season_year
            GROUP BY
                current.model_key,
                current.model_label,
                current.model_role,
                current.is_official_primary,
                current.model_family,
                current.cohort_key,
                current.cohort_label,
                current.publication_tier,
                current.ranking_scope,
                current.gender_scope,
                current.resolved_school_id,
                current.school_name,
                current.state_code,
                current.city,
                current.conference_name,
                current.division_name,
                current.season_year,
                current.season_type,
                current.season_key,
                current.season_label,
                current.source_eligible,
                current.primary_metric_name,
                current.opportunity_adjusted_metric_name,
                window_sizes.window_years
        )
        SELECT
            *,
            window_years AS expected_season_count,
            window_years - observed_season_count AS missing_season_count,
            observed_season_count
                / CAST(window_years AS DOUBLE) AS coverage_rate,
            observed_season_count = window_years AS window_complete,
            last_primary_metric - first_primary_metric
                AS first_to_last_primary_metric_change,
            CASE
                WHEN NOT endpoint_source_eligible
                    THEN 'endpoint_ineligible'
                WHEN eligible_observation_count < 2
                    THEN 'insufficient_history'
                WHEN eligible_observation_count = 2
                    THEN 'two_observation_change_only'
                WHEN observed_season_count < window_years
                    THEN 'trend_available_incomplete_window'
                ELSE 'trend_available_complete_window'
            END AS trend_status,
            CASE
                WHEN eligible_observation_count < 3 THEN TRUE
                ELSE FALSE
            END AS slope_suppressed_for_low_observation_count
        FROM aggregated
        ORDER BY
            model_key,
            cohort_key,
            ranking_scope,
            gender_scope,
            resolved_school_id,
            season_type,
            endpoint_year,
            window_years
        """
    )

    # ------------------------------------------------------------------
    # Summaries and methodology
    # ------------------------------------------------------------------
    connection.execute(
        """
        CREATE TABLE trend_partition_summary AS
        SELECT
            model_key,
            model_label,
            model_family,
            cohort_key,
            cohort_label,
            publication_tier,
            ranking_scope,
            gender_scope,
            season_year,
            season_type,
            season_key,
            season_label,
            COUNT(*) AS school_row_count,
            COUNT(*) FILTER (WHERE source_eligible)
                AS eligible_school_count,
            AVG(primary_metric_value) FILTER (WHERE source_eligible)
                AS mean_primary_metric,
            MEDIAN(primary_metric_value) FILTER (WHERE source_eligible)
                AS median_primary_metric,
            MIN(primary_metric_value) FILTER (WHERE source_eligible)
                AS minimum_primary_metric,
            MAX(primary_metric_value) FILTER (WHERE source_eligible)
                AS maximum_primary_metric,
            AVG(rank_strength_percentile) FILTER (WHERE source_eligible)
                AS mean_rank_strength_percentile,
            AVG(scoring_breadth) FILTER (WHERE source_eligible)
                AS mean_scoring_breadth,
            AVG(athlete_unit_count) FILTER (WHERE source_eligible)
                AS mean_athlete_unit_count
        FROM school_season_overall_base
        GROUP BY ALL
        ORDER BY
            model_key,
            cohort_key,
            ranking_scope,
            gender_scope,
            season_year,
            season_type
        """
    )

    connection.execute(
        """
        CREATE TABLE trend_missingness_summary AS
        SELECT
            model_key,
            model_label,
            model_family,
            cohort_key,
            cohort_label,
            publication_tier,
            ranking_scope,
            gender_scope,
            season_type,
            comparison_status,
            COUNT(*) AS row_count,
            COUNT(DISTINCT resolved_school_id) AS school_count,
            MIN(current_season_year) AS first_current_year,
            MAX(current_season_year) AS last_current_year
        FROM school_season_overall_movement
        GROUP BY ALL
        ORDER BY
            model_key,
            cohort_key,
            ranking_scope,
            gender_scope,
            season_type,
            comparison_status
        """
    )

    connection.execute(
        """
        CREATE TABLE trend_methodology (
            methodology_order INTEGER,
            methodology_key VARCHAR,
            methodology_value VARCHAR
        )
        """
    )
    methodology_rows = [
        (
            1,
            "phase_scope",
            "Phase 7A.1 publishes overall seasonal trend foundations with "
            "Enhanced Balanced Production as the official and prioritized model. "
            "Event and group trend extensions follow in later Phase 7A steps.",
        ),
        (
            2,
            "frozen_inputs",
            "Reads the final Milestone 6 DuckDB publication in read-only mode. "
            "No Milestone 5 or Milestone 6 table is recalculated or overwritten.",
        ),
        (
            3,
            "year_over_year_definition",
            "A current observation is compared only with the same school, model, "
            "cohort, ranking scope, gender scope, and season type in the exact "
            "previous calendar year.",
        ),
        (
            4,
            "missing_season_policy",
            "No interpolation, carry-forward, nearest-year substitution, or "
            "zero filling is permitted.",
        ),
        (
            5,
            "rank_improvement",
            "Previous rank minus current rank. Positive values indicate movement "
            "toward rank 1.",
        ),
        (
            6,
            "rank_strength_percentile",
            "1 - (rank - 1) / (ranked school count - 1). Higher values are better "
            "and are more comparable than raw rank when partition size changes.",
        ),
        (
            7,
            "production_metric",
            "The production models use total event-balanced points as the primary "
            "metric and net share of available event points as the opportunity-"
            "adjusted comparison metric.",
        ),
        (
            8,
            "average_development_metric",
            "Average Athlete Development uses posterior school score as the "
            "primary metric and the season-centered posterior score as its "
            "companion metric.",
        ),
        (
            9,
            "indoor_outdoor_definition",
            "Outdoor minus Indoor within the same school, year, model, cohort, "
            "ranking scope, and gender scope.",
        ),
        (
            10,
            "rolling_windows",
            "Three- and five-year windows are calendar windows. Missing seasons "
            "reduce coverage and are not replaced. Slopes require at least three "
            "eligible observations.",
        ),
        (
            11,
            "interpretation_limit",
            "These are observational descriptive trends. Rank movement can differ "
            "from score movement because the competitive field changes by season.",
        ),
        (
            12,
            "coverage_limit",
            "Enhanced Balanced Production is the default publication. Companion "
            "models are optional and are included only when --include-companions is "
            "used. Production cohorts have cohort-specific season coverage.",
        ),
        (
            13,
            "model_priority",
            "Enhanced Balanced Production drives the official trend outputs, "
            "validation summaries, and future explorer defaults. Companion models "
            "are secondary context only.",
        ),
    ]
    connection.executemany(
        "INSERT INTO trend_methodology VALUES (?, ?, ?)", methodology_rows
    )

    connection.execute(
        """
        CREATE TABLE output_registry (
            output_order INTEGER,
            output_name VARCHAR,
            output_type VARCHAR,
            description VARCHAR
        )
        """
    )
    output_registry_rows = [
        (1, "trend_season_registry", "table_csv", "Observed season registry."),
        (2, "school_season_overall_base", "table_csv", "Unified source-backed school-season overall observations."),
        (3, "school_season_overall_movement", "table_csv", "Exact previous-year same-season-type movement."),
        (4, "school_indoor_outdoor_comparison", "table_csv", "Same-year indoor versus outdoor comparison."),
        (5, "school_multiseason_trends", "table_csv", "Three- and five-year calendar-window summaries."),
        (6, "trend_partition_summary", "table_csv", "Partition coverage and metric summaries."),
        (7, "trend_missingness_summary", "table_csv", "Movement comparison-status summary."),
        (8, "trend_methodology", "table_csv", "Frozen Phase 7A.1 methodology."),
        (9, "input_manifest", "table_csv", "Frozen source path, size, and hash."),
        (10, "hard_checks", "table_csv", "Phase validation gate."),
        (11, "phase_7a_report.txt", "text", "Human-readable phase report."),
        (12, "output_manifest.csv", "csv", "Output sizes and SHA-256 hashes."),
        (13, f"{DATASET_VERSION}.duckdb", "duckdb", "Phase 7A.1 analytical database."),
    ]
    connection.executemany(
        "INSERT INTO output_registry VALUES (?, ?, ?, ?)",
        output_registry_rows,
    )

    # ------------------------------------------------------------------
    # Validation gate
    # ------------------------------------------------------------------
    checks: list[CheckResult] = []

    model_keys = connection.execute(
        """
        SELECT STRING_AGG(model_key, ',' ORDER BY display_order)
        FROM final_model_registry
        """
    ).fetchone()[0]
    expected_model_keys = (
        "enhanced_balanced_production,"
        "original_balanced_production_v4_1,"
        "average_athlete_development"
    )
    add_boolean_check(
        checks,
        "final_model_registry_exact",
        model_keys == expected_model_keys,
        model_keys,
        expected_model_keys,
        "The three frozen Milestone 6 model roles must remain unchanged.",
    )

    published_model_keys = connection.execute(
        """
        SELECT STRING_AGG(DISTINCT model_key, ',' ORDER BY model_key)
        FROM school_season_overall_base
        """
    ).fetchone()[0]
    expected_published_model_keys = (
        "average_athlete_development,enhanced_balanced_production,"
        "original_balanced_production_v4_1"
        if include_companions
        else "enhanced_balanced_production"
    )
    add_boolean_check(
        checks,
        "published_models_match_priority_mode",
        published_model_keys == expected_published_model_keys,
        published_model_keys,
        expected_published_model_keys,
        "Default mode must publish only the official Enhanced model.",
    )

    nonprimary_default_rows = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_overall_base
        WHERE model_key <> 'enhanced_balanced_production'
        """,
    )
    add_boolean_check(
        checks,
        "enhanced_is_exclusive_default_model",
        include_companions or nonprimary_default_rows == 0,
        nonprimary_default_rows,
        0 if not include_companions else "companions enabled",
        "No companion rows may enter the default official publication.",
    )

    production_source_rows = scalar(
        connection,
        f"""
        SELECT
            (SELECT COUNT(*)
             FROM src.main.event_balanced_overall_combined
             WHERE time_scope = 'single_season'
               AND {production_model_filter})
          + (SELECT COUNT(*)
             FROM src.main.event_balanced_overall_gender
             WHERE time_scope = 'single_season'
               AND {production_model_filter})
        """,
    )
    production_base_rows = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_overall_base
        WHERE model_family = 'production'
        """,
    )
    add_boolean_check(
        checks,
        "production_base_row_count_reconciles",
        production_base_rows == production_source_rows,
        production_base_rows,
        production_source_rows,
        "All production overall combined and gender rows must be preserved.",
    )

    average_source_rows = scalar(
        connection,
        f"""
        SELECT COUNT(*)
        FROM src.main.average_development_seasonal_rankings
        WHERE {average_source_filter}
          AND ranking_key = 'overall'
          AND ranking_scope IN (
                'season_overall_combined',
                'season_overall_gender'
          )
        """,
    )
    average_base_rows = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_overall_base
        WHERE model_family = 'average_development'
        """,
    )
    add_boolean_check(
        checks,
        "average_development_base_row_count_reconciles",
        average_base_rows == average_source_rows,
        average_base_rows,
        average_source_rows,
        "Every overall Average Development source row must be preserved.",
    )

    duplicate_base_groups = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM (
            SELECT
                model_key,
                cohort_key,
                ranking_scope,
                gender_scope,
                season_year,
                season_type,
                resolved_school_id,
                COUNT(*) AS row_count
            FROM school_season_overall_base
            GROUP BY ALL
            HAVING COUNT(*) > 1
        )
        """,
    )
    add_boolean_check(
        checks,
        "overall_base_keys_unique",
        duplicate_base_groups == 0,
        duplicate_base_groups,
        0,
        "Unified source keys must be unique.",
    )

    null_base_keys = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_overall_base
        WHERE model_key IS NULL
           OR cohort_key IS NULL
           OR ranking_scope IS NULL
           OR gender_scope IS NULL
           OR season_year IS NULL
           OR season_type IS NULL
           OR resolved_school_id IS NULL
        """,
    )
    add_boolean_check(
        checks,
        "overall_base_keys_nonnull",
        null_base_keys == 0,
        null_base_keys,
        0,
        "No trend key component may be null.",
    )

    invalid_rank_strength = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_overall_base
        WHERE rank_strength_percentile IS NOT NULL
          AND (
                rank_strength_percentile < -1e-12
             OR rank_strength_percentile > 1.0 + 1e-12
          )
        """,
    )
    add_boolean_check(
        checks,
        "rank_strength_percentiles_valid",
        invalid_rank_strength == 0,
        invalid_rank_strength,
        0,
        "Rank-strength percentiles must remain in [0, 1].",
    )

    invalid_production_budgets = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_overall_base
        WHERE model_family = 'production'
          AND (
                available_points IS NULL
             OR available_points <= 0
          )
        """,
    )
    add_boolean_check(
        checks,
        "production_available_budgets_positive",
        invalid_production_budgets == 0,
        invalid_production_budgets,
        0,
        "Opportunity-adjusted production denominators must be positive.",
    )

    production_2020_outdoor_rows = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_overall_base
        WHERE model_family = 'production'
          AND season_year = 2020
          AND season_type = 'outdoor'
        """,
    )
    add_boolean_check(
        checks,
        "production_2020_outdoor_not_fabricated",
        production_2020_outdoor_rows == 0,
        production_2020_outdoor_rows,
        0,
        "The genuinely missing 2020 Outdoor production season must stay missing.",
    )

    average_combined_season_count = scalar(
        connection,
        """
        SELECT COUNT(DISTINCT season_key)
        FROM school_season_overall_base
        WHERE model_key = 'average_athlete_development'
          AND ranking_scope = 'season_overall_combined'
          AND gender_scope = 'all'
        """,
    )
    expected_average_seasons = 40 if include_companions else 0
    add_boolean_check(
        checks,
        "average_companion_coverage_matches_mode",
        average_combined_season_count == expected_average_seasons,
        average_combined_season_count,
        expected_average_seasons,
        "Average Development is published only when companion mode is enabled.",
    )

    base_row_count = scalar(
        connection, "SELECT COUNT(*) FROM school_season_overall_base"
    )
    movement_row_count = scalar(
        connection, "SELECT COUNT(*) FROM school_season_overall_movement"
    )
    add_boolean_check(
        checks,
        "movement_rows_equal_base_rows",
        movement_row_count == base_row_count,
        movement_row_count,
        base_row_count,
        "Each current base row must receive one movement-status row.",
    )

    duplicate_movement_groups = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM (
            SELECT
                model_key,
                cohort_key,
                ranking_scope,
                gender_scope,
                current_season_year,
                season_type,
                resolved_school_id,
                COUNT(*) AS row_count
            FROM school_season_overall_movement
            GROUP BY ALL
            HAVING COUNT(*) > 1
        )
        """,
    )
    add_boolean_check(
        checks,
        "movement_keys_unique",
        duplicate_movement_groups == 0,
        duplicate_movement_groups,
        0,
        "Movement output keys must be unique.",
    )

    null_comparable_flags = scalar(
        connection,
        """
        SELECT
            (SELECT COUNT(*)
             FROM school_season_overall_movement
             WHERE is_comparable IS NULL)
          + (SELECT COUNT(*)
             FROM school_indoor_outdoor_comparison
             WHERE is_comparable IS NULL)
        """,
    )
    add_boolean_check(
        checks,
        "comparison_flags_nonnull",
        null_comparable_flags == 0,
        null_comparable_flags,
        0,
        "Comparison eligibility flags must be explicit TRUE or FALSE.",
    )

    invalid_comparable_gaps = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_overall_movement
        WHERE is_comparable
          AND (
                year_gap <> 1
             OR previous_season_year <> current_season_year - 1
             OR previous_season_key <> expected_previous_season_key
          )
        """,
    )
    add_boolean_check(
        checks,
        "comparable_movements_use_exact_previous_year",
        invalid_comparable_gaps == 0,
        invalid_comparable_gaps,
        0,
        "Comparable movement must use the exact previous year and same season type.",
    )

    primary_delta_errors = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_overall_movement
        WHERE is_comparable
          AND ABS(
                primary_metric_delta
                - (current_primary_metric - previous_primary_metric)
          ) > 1e-9
        """,
    )
    add_boolean_check(
        checks,
        "primary_metric_deltas_reconcile",
        primary_delta_errors == 0,
        primary_delta_errors,
        0,
        "Every comparable primary metric delta must reconcile exactly.",
    )

    rank_delta_errors = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_overall_movement
        WHERE is_comparable
          AND rank_improvement <> previous_rank - current_rank
        """,
    )
    add_boolean_check(
        checks,
        "rank_improvement_reconciles",
        rank_delta_errors == 0,
        rank_delta_errors,
        0,
        "Rank improvement must equal previous rank minus current rank.",
    )

    noncomparable_populated_deltas = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_season_overall_movement
        WHERE NOT is_comparable
          AND (
                primary_metric_delta IS NOT NULL
             OR opportunity_adjusted_metric_delta IS NOT NULL
             OR rank_improvement IS NOT NULL
             OR rank_strength_delta IS NOT NULL
          )
        """,
    )
    add_boolean_check(
        checks,
        "noncomparable_rows_have_null_deltas",
        noncomparable_populated_deltas == 0,
        noncomparable_populated_deltas,
        0,
        "Unavailable or ineligible comparisons must not receive synthetic deltas.",
    )

    invalid_indoor_outdoor_years = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_indoor_outdoor_comparison
        WHERE indoor_season_key IS NOT NULL
          AND outdoor_season_key IS NOT NULL
          AND SPLIT_PART(indoor_season_key, '_', 1)
              <> SPLIT_PART(outdoor_season_key, '_', 1)
        """,
    )
    add_boolean_check(
        checks,
        "indoor_outdoor_comparisons_use_same_year",
        invalid_indoor_outdoor_years == 0,
        invalid_indoor_outdoor_years,
        0,
        "Indoor and outdoor comparisons must use the same calendar year.",
    )

    invalid_window_counts = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_multiseason_trends
        WHERE observed_season_count > expected_season_count
           OR eligible_observation_count > observed_season_count
           OR coverage_rate < -1e-12
           OR coverage_rate > 1.0 + 1e-12
        """,
    )
    add_boolean_check(
        checks,
        "rolling_window_counts_valid",
        invalid_window_counts == 0,
        invalid_window_counts,
        0,
        "Calendar-window observation counts and coverage rates must be valid.",
    )

    invalid_low_n_slopes = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM school_multiseason_trends
        WHERE eligible_observation_count < 3
          AND (
                primary_metric_slope_per_year IS NOT NULL
             OR opportunity_adjusted_metric_slope_per_year IS NOT NULL
             OR rank_strength_slope_per_year IS NOT NULL
             OR scoring_breadth_slope_per_year IS NOT NULL
             OR athlete_unit_count_slope_per_year IS NOT NULL
          )
        """,
    )
    add_boolean_check(
        checks,
        "slopes_suppressed_below_three_observations",
        invalid_low_n_slopes == 0,
        invalid_low_n_slopes,
        0,
        "Trend slopes require at least three eligible observations.",
    )

    source_size_after = source_database.stat().st_size
    source_hash_after = sha256_file(source_database)
    source_unchanged = (
        source_size_after == source_size_before
        and source_hash_after == source_hash_before
    )
    add_boolean_check(
        checks,
        "all_inputs_unchanged",
        source_unchanged,
        f"size={source_size_after};sha256={source_hash_after}",
        f"size={source_size_before};sha256={source_hash_before}",
        "The frozen Milestone 6 input must remain byte-for-byte unchanged.",
    )

    required_tables = [
        "trend_season_registry",
        "school_season_overall_base",
        "school_season_overall_movement",
        "school_indoor_outdoor_comparison",
        "school_multiseason_trends",
        "trend_partition_summary",
        "trend_missingness_summary",
        "trend_methodology",
        "input_manifest",
        "output_registry",
    ]
    table_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND table_name IN (
              SELECT * FROM UNNEST(?)
          )
        """,
        [required_tables],
    ).fetchone()[0]
    add_boolean_check(
        checks,
        "required_output_tables_exist",
        table_count == len(required_tables),
        table_count,
        len(required_tables),
        "Every required Phase 7A.1 table must exist in the output database.",
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

    # ------------------------------------------------------------------
    # CSV publication
    # ------------------------------------------------------------------
    exports: list[tuple[str, str]] = [
        (
            "trend_season_registry.csv",
            "SELECT * FROM trend_season_registry ORDER BY season_order",
        ),
        (
            "school_season_overall_base.csv",
            """
            SELECT * FROM school_season_overall_base
            ORDER BY
                model_key, cohort_key, ranking_scope, gender_scope,
                season_year, season_type, source_rank NULLS LAST,
                resolved_school_id
            """,
        ),
        (
            "school_season_overall_movement.csv",
            """
            SELECT * FROM school_season_overall_movement
            ORDER BY
                model_key, cohort_key, ranking_scope, gender_scope,
                resolved_school_id, season_type, current_season_year
            """,
        ),
        (
            "school_indoor_outdoor_comparison.csv",
            """
            SELECT * FROM school_indoor_outdoor_comparison
            ORDER BY
                model_key, cohort_key, ranking_scope, gender_scope,
                resolved_school_id, season_year
            """,
        ),
        (
            "school_multiseason_trends.csv",
            """
            SELECT * FROM school_multiseason_trends
            ORDER BY
                model_key, cohort_key, ranking_scope, gender_scope,
                resolved_school_id, season_type, endpoint_year,
                window_years
            """,
        ),
        (
            "trend_partition_summary.csv",
            """
            SELECT * FROM trend_partition_summary
            ORDER BY
                model_key, cohort_key, ranking_scope, gender_scope,
                season_year, season_type
            """,
        ),
        (
            "trend_missingness_summary.csv",
            """
            SELECT * FROM trend_missingness_summary
            ORDER BY
                model_key, cohort_key, ranking_scope, gender_scope,
                season_type, comparison_status
            """,
        ),
        (
            "trend_methodology.csv",
            "SELECT * FROM trend_methodology ORDER BY methodology_order",
        ),
        (
            "input_manifest.csv",
            "SELECT * FROM input_manifest ORDER BY input_name",
        ),
        (
            "output_registry.csv",
            "SELECT * FROM output_registry ORDER BY output_order",
        ),
    ]

    for filename, query in exports:
        export_query(connection, query, output_dir / filename)

    expected_csvs = [output_dir / filename for filename, _ in exports]
    missing_csvs = [str(path.name) for path in expected_csvs if not path.exists()]
    csv_check = CheckResult(
        check_name="required_csv_outputs_created",
        status="PASS" if not missing_csvs else "FAIL",
        observed_value=str(len(expected_csvs) - len(missing_csvs)),
        expected_value=str(len(expected_csvs)),
        details=(
            "All primary table CSVs were created."
            if not missing_csvs
            else "Missing CSVs: " + ", ".join(missing_csvs)
        ),
    )
    checks.append(csv_check)
    connection.execute(
        "INSERT INTO hard_checks VALUES (?, ?, ?, ?, ?)",
        [
            csv_check.check_name,
            csv_check.status,
            csv_check.observed_value,
            csv_check.expected_value,
            csv_check.details,
        ],
    )

    export_query(
        connection,
        "SELECT * FROM hard_checks ORDER BY check_name",
        output_dir / "hard_checks.csv",
    )

    row_counts = {
        "season_registry": scalar(
            connection, "SELECT COUNT(*) FROM trend_season_registry"
        ),
        "overall_base": base_row_count,
        "overall_movement": movement_row_count,
        "comparable_movements": scalar(
            connection,
            "SELECT COUNT(*) FROM school_season_overall_movement WHERE is_comparable",
        ),
        "indoor_outdoor": scalar(
            connection,
            "SELECT COUNT(*) FROM school_indoor_outdoor_comparison",
        ),
        "comparable_indoor_outdoor": scalar(
            connection,
            "SELECT COUNT(*) FROM school_indoor_outdoor_comparison WHERE is_comparable",
        ),
        "multiseason_windows": scalar(
            connection, "SELECT COUNT(*) FROM school_multiseason_trends"
        ),
    }

    failed_checks = [check for check in checks if check.status != "PASS"]
    phase_status = "PASS" if not failed_checks else "FAIL"

    report_lines = [
        "Milestone 7 — Phase 7A.1 Overall Seasonal Trends",
        "=" * 58,
        "",
        f"Dataset version: {DATASET_VERSION}",
        f"Phase version: {PHASE_VERSION}",
        f"Publication mode: {publication_mode}",
        "Official primary: Enhanced Balanced Production",
        f"Companions included: {include_companions}",
        f"Built at UTC: {built_at_utc}",
        f"Source database: {source_database}",
        f"Source SHA-256: {source_hash_before}",
        "",
        "Published row counts",
        "--------------------",
        f"Season registry rows: {row_counts['season_registry']:,}",
        f"Overall base rows: {row_counts['overall_base']:,}",
        f"Overall movement rows: {row_counts['overall_movement']:,}",
        f"Comparable year-over-year rows: {row_counts['comparable_movements']:,}",
        f"Indoor/outdoor rows: {row_counts['indoor_outdoor']:,}",
        f"Comparable indoor/outdoor rows: {row_counts['comparable_indoor_outdoor']:,}",
        f"Multiseason window rows: {row_counts['multiseason_windows']:,}",
        "",
        "Frozen interpretation",
        "---------------------",
        "Year-over-year comparisons use the exact previous calendar year",
        "within the same season type. Missing seasons are not interpolated,",
        "carried forward, replaced with the nearest observation, or set to zero.",
        "Enhanced Balanced Production is the official trend ranker and receives",
        "priority in outputs, validation, documentation, and future explorer views.",
        "Companion models are included only when explicitly requested.",
        "",
        "Coverage note",
        "-------------",
        "Enhanced production coverage is cohort-specific. The Broad — All Athletes",
        "cohort has only six published endpoint seasons. The missing 2020 Outdoor",
        "production season remains absent by design.",
        "",
        "Hard checks",
        "-----------",
        f"Passed: {len(checks) - len(failed_checks)}",
        f"Failed: {len(failed_checks)}",
    ]

    if failed_checks:
        report_lines.extend(["", "Failed checks:"])
        for check in failed_checks:
            report_lines.append(
                f"- {check.check_name}: observed={check.observed_value}; "
                f"expected={check.expected_value}"
            )

    report_lines.extend(
        [
            "",
            f"PHASE GATE: {phase_status}",
            (
                "Phase 7A.1 overall trend foundation published."
                if phase_status == "PASS"
                else "Phase 7A.1 publication failed validation."
            ),
        ]
    )

    report_path = output_dir / "phase_7a_report.txt"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    connection.execute("DETACH src")
    connection.close()

    write_output_manifest(output_dir)

    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Publication mode: {publication_mode}")
    print("Official primary: Enhanced Balanced Production")
    print(f"Companions included: {include_companions}")
    print(f"Source database: {source_database}")
    print(f"Output database: {output_database}")
    print(f"Overall base rows: {row_counts['overall_base']:,}")
    print(f"Comparable year-over-year rows: {row_counts['comparable_movements']:,}")
    print(f"Comparable indoor/outdoor rows: {row_counts['comparable_indoor_outdoor']:,}")
    print(f"Multiseason window rows: {row_counts['multiseason_windows']:,}")
    print(f"Failed checks: {len(failed_checks)}")
    print()
    print(f"PHASE GATE: {phase_status}")

    if phase_status == "PASS":
        print("Phase 7A.1 overall trend foundation published.")
        return 0

    print("Phase 7A.1 publication failed validation.")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - top-level failure reporting
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
