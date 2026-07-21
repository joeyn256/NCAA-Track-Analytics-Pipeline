#!/usr/bin/env python3
"""Build Milestone 7 Phase 7C program-comparison products.

This publication consumes the validated Phase 7A.1 overall-trend database and
Phase 7B trajectory database. It creates Enhanced Balanced Production peer,
conference, indoor/outdoor, and comparison-ready tables for the explorer.
It never retrains or modifies the frozen Milestone 6 ranking model.
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
PHASE_VERSION = "phase_7c_program_comparison_v1"
MODEL_KEY = "enhanced_balanced_production"
MODEL_LABEL = "Enhanced Balanced Production"

DEFAULT_OVERALL_DB = Path(
    "data/processed/milestone7/seasonal_program_trends_v1/"
    "phase_7a_overall_trends/seasonal_program_trends_v1.duckdb"
)
DEFAULT_TRAJECTORY_DB = Path(
    "data/processed/milestone7/seasonal_program_trends_v1/"
    "phase_7b_program_trajectory/seasonal_program_trends_v1.duckdb"
)
DEFAULT_OUTPUT_DIR = Path(
    "data/processed/milestone7/seasonal_program_trends_v1/"
    "phase_7c_program_comparison"
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
            "Build Enhanced Balanced Production peer context, conference "
            "leaderboards, indoor/outdoor summaries, and comparison exports."
        )
    )
    parser.add_argument(
        "--overall-db",
        type=Path,
        default=DEFAULT_OVERALL_DB,
        help="Validated Phase 7A.1 overall-trends DuckDB file.",
    )
    parser.add_argument(
        "--trajectory-db",
        type=Path,
        default=DEFAULT_TRAJECTORY_DB,
        help="Validated Phase 7B trajectory DuckDB file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Phase 7C output directory.",
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


def create_peer_context(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE program_peer_context AS
        WITH source_rows AS (
            SELECT *
            FROM trajectory_src.main.program_comparison_snapshot
            WHERE model_key = '{MODEL_KEY}'
        ),
        national AS (
            SELECT
                cohort_key,
                ranking_scope,
                gender_scope,
                endpoint_year,
                season_type,
                window_years,
                COUNT(*) AS national_peer_count,
                MEDIAN(performance_percentile)
                    AS national_median_performance_percentile,
                MEDIAN(momentum_percentile)
                    AS national_median_momentum_percentile,
                MEDIAN(consistency_percentile)
                    AS national_median_consistency_percentile,
                MEDIAN(mean_rank_strength_percentile)
                    AS national_median_rank_strength,
                MEDIAN(rank_strength_slope_per_year)
                    AS national_median_rank_strength_slope
            FROM source_rows
            GROUP BY ALL
        ),
        conference AS (
            SELECT
                cohort_key,
                ranking_scope,
                gender_scope,
                endpoint_year,
                season_type,
                window_years,
                conference_name,
                COUNT(*) AS conference_peer_count,
                MEDIAN(performance_percentile)
                    AS conference_median_performance_percentile,
                MEDIAN(momentum_percentile)
                    AS conference_median_momentum_percentile,
                MEDIAN(consistency_percentile)
                    AS conference_median_consistency_percentile,
                MEDIAN(mean_rank_strength_percentile)
                    AS conference_median_rank_strength,
                MEDIAN(rank_strength_slope_per_year)
                    AS conference_median_rank_strength_slope
            FROM source_rows
            WHERE conference_name IS NOT NULL
            GROUP BY ALL
        )
        SELECT
            source_rows.*,
            national.national_peer_count,
            national.national_median_performance_percentile,
            national.national_median_momentum_percentile,
            national.national_median_consistency_percentile,
            national.national_median_rank_strength,
            national.national_median_rank_strength_slope,
            source_rows.performance_percentile
                - national.national_median_performance_percentile
                AS performance_vs_national_median,
            source_rows.momentum_percentile
                - national.national_median_momentum_percentile
                AS momentum_vs_national_median,
            source_rows.consistency_percentile
                - national.national_median_consistency_percentile
                AS consistency_vs_national_median,
            source_rows.mean_rank_strength_percentile
                - national.national_median_rank_strength
                AS rank_strength_vs_national_median,
            conference.conference_peer_count,
            conference.conference_median_performance_percentile,
            conference.conference_median_momentum_percentile,
            conference.conference_median_consistency_percentile,
            conference.conference_median_rank_strength,
            conference.conference_median_rank_strength_slope,
            source_rows.performance_percentile
                - conference.conference_median_performance_percentile
                AS performance_vs_conference_median,
            source_rows.momentum_percentile
                - conference.conference_median_momentum_percentile
                AS momentum_vs_conference_median,
            source_rows.consistency_percentile
                - conference.conference_median_consistency_percentile
                AS consistency_vs_conference_median,
            source_rows.mean_rank_strength_percentile
                - conference.conference_median_rank_strength
                AS rank_strength_vs_conference_median,
            '{DATASET_VERSION}' AS comparison_dataset_version,
            '{PHASE_VERSION}' AS comparison_phase_version
        FROM source_rows
        JOIN national USING (
            cohort_key,
            ranking_scope,
            gender_scope,
            endpoint_year,
            season_type,
            window_years
        )
        LEFT JOIN conference USING (
            cohort_key,
            ranking_scope,
            gender_scope,
            endpoint_year,
            season_type,
            window_years,
            conference_name
        )
        ORDER BY
            cohort_key,
            ranking_scope,
            gender_scope,
            season_type,
            window_years,
            performance_rank NULLS LAST,
            school_name
        """
    )


def create_conference_leaderboard(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE program_conference_leaderboard AS
        SELECT
            peer.*,
            CASE
                WHEN conference_name IS NULL
                  OR performance_percentile IS NULL
                THEN NULL
                ELSE DENSE_RANK() OVER (
                    PARTITION BY
                        cohort_key,
                        ranking_scope,
                        gender_scope,
                        endpoint_year,
                        season_type,
                        window_years,
                        conference_name
                    ORDER BY performance_percentile DESC, school_name
                )
            END AS conference_performance_rank,
            CASE
                WHEN conference_name IS NULL
                  OR momentum_percentile IS NULL
                THEN NULL
                ELSE DENSE_RANK() OVER (
                    PARTITION BY
                        cohort_key,
                        ranking_scope,
                        gender_scope,
                        endpoint_year,
                        season_type,
                        window_years,
                        conference_name
                    ORDER BY momentum_percentile DESC, school_name
                )
            END AS conference_momentum_rank,
            CASE
                WHEN conference_name IS NULL
                  OR consistency_percentile IS NULL
                THEN NULL
                ELSE DENSE_RANK() OVER (
                    PARTITION BY
                        cohort_key,
                        ranking_scope,
                        gender_scope,
                        endpoint_year,
                        season_type,
                        window_years,
                        conference_name
                    ORDER BY consistency_percentile DESC, school_name
                )
            END AS conference_consistency_rank,
            CASE
                WHEN conference_name IS NULL
                  OR mean_rank_strength_percentile IS NULL
                THEN NULL
                ELSE DENSE_RANK() OVER (
                    PARTITION BY
                        cohort_key,
                        ranking_scope,
                        gender_scope,
                        endpoint_year,
                        season_type,
                        window_years,
                        conference_name
                    ORDER BY mean_rank_strength_percentile DESC, school_name
                )
            END AS conference_rank_strength_rank
        FROM program_peer_context peer
        ORDER BY
            cohort_key,
            ranking_scope,
            gender_scope,
            season_type,
            window_years,
            conference_name NULLS LAST,
            conference_performance_rank NULLS LAST,
            school_name
        """
    )


def create_indoor_outdoor_latest(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE program_indoor_outdoor_latest AS
        SELECT
            comparisons.*,
            CASE
                WHEN outdoor_minus_indoor_rank_strength > 1e-12
                    THEN 'outdoor_stronger'
                WHEN outdoor_minus_indoor_rank_strength < -1e-12
                    THEN 'indoor_stronger'
                ELSE 'approximately_even'
            END AS seasonal_strength_direction,
            CASE
                WHEN outdoor_minus_indoor_primary_metric > 1e-12
                    THEN 'outdoor_higher'
                WHEN outdoor_minus_indoor_primary_metric < -1e-12
                    THEN 'indoor_higher'
                ELSE 'approximately_even'
            END AS seasonal_metric_direction,
            '{DATASET_VERSION}' AS dataset_version,
            '{PHASE_VERSION}' AS phase_version
        FROM overall_src.main.school_indoor_outdoor_comparison comparisons
        WHERE model_key = '{MODEL_KEY}'
          AND is_comparable
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY
                cohort_key,
                ranking_scope,
                gender_scope,
                resolved_school_id
            ORDER BY season_year DESC
        ) = 1
        ORDER BY
            cohort_key,
            ranking_scope,
            gender_scope,
            outdoor_rank,
            school_name
        """
    )


def create_indoor_outdoor_history(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE program_indoor_outdoor_history AS
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
            COUNT(*) AS comparable_year_count,
            MIN(season_year) AS first_comparable_year,
            MAX(season_year) AS latest_comparable_year,
            AVG(outdoor_minus_indoor_primary_metric)
                AS mean_outdoor_minus_indoor_primary_metric,
            MEDIAN(outdoor_minus_indoor_primary_metric)
                AS median_outdoor_minus_indoor_primary_metric,
            AVG(outdoor_minus_indoor_rank_strength)
                AS mean_outdoor_minus_indoor_rank_strength,
            MEDIAN(outdoor_minus_indoor_rank_strength)
                AS median_outdoor_minus_indoor_rank_strength,
            AVG(outdoor_minus_indoor_positive_share)
                AS mean_outdoor_minus_indoor_positive_share,
            AVG(outdoor_minus_indoor_net_share)
                AS mean_outdoor_minus_indoor_net_share,
            AVG(outdoor_minus_indoor_scoring_breadth)
                AS mean_outdoor_minus_indoor_scoring_breadth,
            COUNT(*) FILTER (
                WHERE outdoor_minus_indoor_rank_strength > 1e-12
            ) AS outdoor_stronger_year_count,
            COUNT(*) FILTER (
                WHERE outdoor_minus_indoor_rank_strength < -1e-12
            ) AS indoor_stronger_year_count,
            COUNT(*) FILTER (
                WHERE ABS(outdoor_minus_indoor_rank_strength) <= 1e-12
            ) AS approximately_even_year_count,
            CASE
                WHEN COUNT(*) = 0 THEN NULL
                ELSE COUNT(*) FILTER (
                    WHERE outdoor_minus_indoor_rank_strength > 1e-12
                ) / CAST(COUNT(*) AS DOUBLE)
            END AS outdoor_stronger_rate,
            CASE
                WHEN COUNT(*) = 0 THEN 'no_comparable_history'
                WHEN COUNT(*) FILTER (
                    WHERE outdoor_minus_indoor_rank_strength > 1e-12
                ) > COUNT(*) FILTER (
                    WHERE outdoor_minus_indoor_rank_strength < -1e-12
                ) THEN 'usually_stronger_outdoors'
                WHEN COUNT(*) FILTER (
                    WHERE outdoor_minus_indoor_rank_strength > 1e-12
                ) < COUNT(*) FILTER (
                    WHERE outdoor_minus_indoor_rank_strength < -1e-12
                ) THEN 'usually_stronger_indoors'
                ELSE 'balanced_indoor_outdoor'
            END AS indoor_outdoor_profile,
            '{DATASET_VERSION}' AS dataset_version,
            '{PHASE_VERSION}' AS phase_version
        FROM overall_src.main.school_indoor_outdoor_comparison
        WHERE model_key = '{MODEL_KEY}'
          AND is_comparable
        GROUP BY ALL
        ORDER BY
            cohort_key,
            ranking_scope,
            gender_scope,
            school_name
        """
    )


def create_metric_long(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE program_comparison_metric_long AS
        SELECT
            peer.model_key,
            peer.model_label,
            peer.cohort_key,
            peer.cohort_label,
            peer.publication_tier,
            peer.ranking_scope,
            peer.gender_scope,
            peer.resolved_school_id,
            peer.school_name,
            peer.state_code,
            peer.city,
            peer.conference_name,
            peer.division_name,
            peer.endpoint_year,
            peer.season_type,
            peer.endpoint_season_key,
            peer.endpoint_season_label,
            peer.window_years,
            metrics.metric_order,
            metrics.metric_key,
            metrics.metric_label,
            metrics.metric_family,
            metrics.metric_value,
            metrics.higher_is_better,
            peer.dataset_version,
            peer.comparison_phase_version AS phase_version
        FROM program_peer_context peer
        CROSS JOIN LATERAL (
            VALUES
                (1, 'performance_percentile', 'Performance percentile',
                 'percentile', peer.performance_percentile, TRUE),
                (2, 'momentum_percentile', 'Momentum percentile',
                 'percentile', peer.momentum_percentile, TRUE),
                (3, 'consistency_percentile', 'Consistency percentile',
                 'percentile', peer.consistency_percentile, TRUE),
                (4, 'mean_rank_strength_percentile', 'Mean rank strength',
                 'percentile', peer.mean_rank_strength_percentile, TRUE),
                (5, 'rank_strength_slope_per_year', 'Rank-strength slope',
                 'slope', peer.rank_strength_slope_per_year, TRUE),
                (6, 'mean_primary_metric', 'Mean Enhanced points',
                 'production', peer.mean_primary_metric, TRUE),
                (7, 'frozen_taxonomy_coverage_rate', 'Group coverage',
                 'coverage', peer.frozen_taxonomy_coverage_rate, TRUE),
                (8, 'event_coverage_rate', 'Event coverage',
                 'coverage', peer.event_coverage_rate, TRUE)
        ) AS metrics(
            metric_order,
            metric_key,
            metric_label,
            metric_family,
            metric_value,
            higher_is_better
        )
        ORDER BY
            peer.cohort_key,
            peer.ranking_scope,
            peer.gender_scope,
            peer.season_type,
            peer.window_years,
            peer.school_name,
            metrics.metric_order
        """
    )


def create_enriched_snapshot(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE program_comparison_snapshot_enriched AS
        SELECT
            peer.*,
            latest.latest_season_year,
            latest.latest_season_key,
            latest.latest_season_label,
            latest.primary_metric_value AS latest_primary_metric_value,
            latest.source_rank AS latest_source_rank,
            latest.ranked_school_count AS latest_ranked_school_count,
            latest.rank_strength_percentile
                AS latest_rank_strength_percentile,
            latest.latest_yoy_status,
            latest.latest_yoy_primary_delta,
            latest.latest_yoy_rank_improvement,
            latest.latest_yoy_rank_strength_delta,
            rise_fall.comparable_transition_count,
            rise_fall.improving_transition_count,
            rise_fall.declining_transition_count,
            rise_fall.improvement_rate,
            rise_fall.net_improving_transitions,
            rise_fall.rise_fall_status,
            io_latest.season_year AS latest_indoor_outdoor_year,
            io_latest.indoor_rank,
            io_latest.outdoor_rank,
            io_latest.outdoor_rank_improvement,
            io_latest.outdoor_minus_indoor_rank_strength,
            io_latest.seasonal_strength_direction,
            io_history.comparable_year_count
                AS indoor_outdoor_comparable_year_count,
            io_history.mean_outdoor_minus_indoor_rank_strength,
            io_history.outdoor_stronger_rate,
            io_history.indoor_outdoor_profile
        FROM program_peer_context peer
        LEFT JOIN trajectory_src.main.program_latest_snapshot latest
          ON latest.cohort_key = peer.cohort_key
         AND latest.ranking_scope = peer.ranking_scope
         AND latest.gender_scope = peer.gender_scope
         AND latest.resolved_school_id = peer.resolved_school_id
         AND latest.season_type = peer.season_type
        LEFT JOIN trajectory_src.main.program_rise_fall_summary rise_fall
          ON rise_fall.cohort_key = peer.cohort_key
         AND rise_fall.ranking_scope = peer.ranking_scope
         AND rise_fall.gender_scope = peer.gender_scope
         AND rise_fall.resolved_school_id = peer.resolved_school_id
         AND rise_fall.season_type = peer.season_type
         AND rise_fall.horizon_key = 'recent_5_calendar_years'
        LEFT JOIN program_indoor_outdoor_latest io_latest
          ON io_latest.cohort_key = peer.cohort_key
         AND io_latest.ranking_scope = peer.ranking_scope
         AND io_latest.gender_scope = peer.gender_scope
         AND io_latest.resolved_school_id = peer.resolved_school_id
        LEFT JOIN program_indoor_outdoor_history io_history
          ON io_history.cohort_key = peer.cohort_key
         AND io_history.ranking_scope = peer.ranking_scope
         AND io_history.gender_scope = peer.gender_scope
         AND io_history.resolved_school_id = peer.resolved_school_id
        ORDER BY
            peer.cohort_key,
            peer.ranking_scope,
            peer.gender_scope,
            peer.season_type,
            peer.window_years,
            peer.performance_rank NULLS LAST,
            peer.school_name
        """
    )


def create_partition_registry(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE comparison_partition_registry AS
        SELECT
            cohort_key,
            cohort_label,
            publication_tier,
            ranking_scope,
            gender_scope,
            endpoint_year,
            season_type,
            window_years,
            COUNT(*) AS school_count,
            COUNT(*) FILTER (WHERE conference_name IS NOT NULL)
                AS schools_with_conference,
            COUNT(DISTINCT conference_name) FILTER (
                WHERE conference_name IS NOT NULL
            ) AS conference_count,
            COUNT(*) FILTER (WHERE performance_percentile IS NOT NULL)
                AS performance_metric_count,
            COUNT(*) FILTER (WHERE momentum_percentile IS NOT NULL)
                AS momentum_metric_count,
            COUNT(*) FILTER (WHERE consistency_percentile IS NOT NULL)
                AS consistency_metric_count,
            MIN(performance_percentile) AS minimum_performance_percentile,
            MAX(performance_percentile) AS maximum_performance_percentile,
            MIN(momentum_percentile) AS minimum_momentum_percentile,
            MAX(momentum_percentile) AS maximum_momentum_percentile,
            MIN(consistency_percentile) AS minimum_consistency_percentile,
            MAX(consistency_percentile) AS maximum_consistency_percentile,
            '{DATASET_VERSION}' AS dataset_version,
            '{PHASE_VERSION}' AS phase_version
        FROM program_peer_context
        GROUP BY ALL
        ORDER BY
            cohort_key,
            ranking_scope,
            gender_scope,
            season_type,
            window_years
        """
    )


def create_methodology(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE program_comparison_methodology AS
        SELECT * FROM (
            VALUES
                ('dataset_version', '{DATASET_VERSION}',
                 'Versioned Milestone 7 seasonal program-trend dataset.'),
                ('phase_version', '{PHASE_VERSION}',
                 'Phase 7C peer and program-comparison publication.'),
                ('official_model', '{MODEL_KEY}',
                 'Enhanced Balanced Production is the exclusive model.'),
                ('peer_context', 'same_partition',
                 'National and conference baselines use the exact same cohort, scope, gender, endpoint year, season type, and window.'),
                ('indoor_outdoor', 'same_calendar_year_only',
                 'Indoor/outdoor comparisons retain only exact same-year comparable observations.'),
                ('head_to_head_strategy', 'comparison_ready_rows',
                 'School pairs are compared on demand from compact school-level rows rather than a large precomputed Cartesian matrix.'),
                ('metric_direction', 'higher_is_better',
                 'All Phase 7C exported comparison metrics are oriented so higher values indicate stronger results.'),
                ('missingness', 'preserve_gaps',
                 'No interpolation, zero filling, nearest-year matching, or carry-forward is used.'),
                ('source_mutation', 'forbidden',
                 'Phase 7A.1 and Phase 7B input databases are attached read-only and hash-checked.')
        ) AS methodology(method_key, method_value, details)
        """
    )


def run_checks(
    connection: duckdb.DuckDBPyConnection,
    overall_hash_before: str,
    trajectory_hash_before: str,
    overall_db: Path,
    trajectory_db: Path,
) -> list[Check]:
    checks: list[Check] = []

    overall_failed = int(
        scalar(
            connection,
            "SELECT COUNT(*) FROM overall_src.main.hard_checks "
            "WHERE status <> 'PASS'",
        )
        or 0
    )
    trajectory_failed = int(
        scalar(
            connection,
            "SELECT COUNT(*) FROM trajectory_src.main.hard_checks "
            "WHERE status <> 'PASS'",
        )
        or 0
    )
    add_check(
        checks,
        "phase_7a_overall_source_passed",
        overall_failed,
        0,
        overall_failed == 0,
        "Phase 7A.1 must have no failed checks.",
    )
    add_check(
        checks,
        "phase_7b_trajectory_source_passed",
        trajectory_failed,
        0,
        trajectory_failed == 0,
        "Phase 7B must have no failed checks.",
    )

    source_rows = int(
        scalar(
            connection,
            f"SELECT COUNT(*) FROM trajectory_src.main.program_comparison_snapshot "
            f"WHERE model_key = '{MODEL_KEY}'",
        )
        or 0
    )
    peer_rows = int(scalar(connection, "SELECT COUNT(*) FROM program_peer_context") or 0)
    add_check(
        checks,
        "peer_rows_reconcile_to_phase_7b",
        peer_rows,
        source_rows,
        peer_rows == source_rows,
        "Every Enhanced Phase 7B comparison row is retained exactly once.",
    )

    model_signature = str(
        scalar(
            connection,
            """
            SELECT CAST(COUNT(DISTINCT model_key) AS VARCHAR)
                   || ':' || COALESCE(MIN(model_key), '')
            FROM program_peer_context
            """,
        )
        or ""
    )
    expected_signature = f"1:{MODEL_KEY}"
    add_check(
        checks,
        "enhanced_is_exclusive_model",
        model_signature,
        expected_signature,
        model_signature == expected_signature,
        "Phase 7C is Enhanced Balanced Production only.",
    )

    peer_duplicates = int(
        scalar(
            connection,
            """
            SELECT COUNT(*) FROM (
                SELECT
                    cohort_key, ranking_scope, gender_scope,
                    resolved_school_id, endpoint_year, season_type,
                    window_years, COUNT(*) AS row_count
                FROM program_peer_context
                GROUP BY ALL
                HAVING COUNT(*) > 1
            )
            """,
        )
        or 0
    )
    add_check(
        checks,
        "peer_context_keys_unique",
        peer_duplicates,
        0,
        peer_duplicates == 0,
        "Program peer-context keys are unique.",
    )

    percentile_errors = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM program_peer_context
            WHERE (performance_percentile IS NOT NULL
                   AND performance_percentile NOT BETWEEN 0 AND 1)
               OR (momentum_percentile IS NOT NULL
                   AND momentum_percentile NOT BETWEEN 0 AND 1)
               OR (consistency_percentile IS NOT NULL
                   AND consistency_percentile NOT BETWEEN 0 AND 1)
               OR (mean_rank_strength_percentile IS NOT NULL
                   AND mean_rank_strength_percentile NOT BETWEEN 0 AND 1)
            """,
        )
        or 0
    )
    add_check(
        checks,
        "comparison_percentiles_in_bounds",
        percentile_errors,
        0,
        percentile_errors == 0,
        "All percentile comparison metrics are bounded by zero and one.",
    )

    conference_rank_errors = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM program_conference_leaderboard
            WHERE (conference_performance_rank IS NOT NULL
                   AND conference_performance_rank > conference_peer_count)
               OR (conference_momentum_rank IS NOT NULL
                   AND conference_momentum_rank > conference_peer_count)
               OR (conference_consistency_rank IS NOT NULL
                   AND conference_consistency_rank > conference_peer_count)
               OR (conference_rank_strength_rank IS NOT NULL
                   AND conference_rank_strength_rank > conference_peer_count)
            """,
        )
        or 0
    )
    add_check(
        checks,
        "conference_ranks_within_peer_counts",
        conference_rank_errors,
        0,
        conference_rank_errors == 0,
        "Conference ranks cannot exceed the matching conference peer count.",
    )

    io_latest_duplicates = int(
        scalar(
            connection,
            """
            SELECT COUNT(*) FROM (
                SELECT
                    cohort_key, ranking_scope, gender_scope,
                    resolved_school_id, COUNT(*) AS row_count
                FROM program_indoor_outdoor_latest
                GROUP BY ALL
                HAVING COUNT(*) > 1
            )
            """,
        )
        or 0
    )
    add_check(
        checks,
        "indoor_outdoor_latest_keys_unique",
        io_latest_duplicates,
        0,
        io_latest_duplicates == 0,
        "At most one latest comparable same-year indoor/outdoor row exists per school partition.",
    )

    io_noncomparable = int(
        scalar(
            connection,
            "SELECT COUNT(*) FROM program_indoor_outdoor_latest "
            "WHERE NOT is_comparable OR comparison_status <> 'comparable'",
        )
        or 0
    )
    add_check(
        checks,
        "indoor_outdoor_latest_is_comparable",
        io_noncomparable,
        0,
        io_noncomparable == 0,
        "Latest indoor/outdoor rows must be exact same-year comparable observations.",
    )

    io_history_errors = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM program_indoor_outdoor_history
            WHERE comparable_year_count < 1
               OR outdoor_stronger_year_count < 0
               OR indoor_stronger_year_count < 0
               OR approximately_even_year_count < 0
               OR outdoor_stronger_year_count
                  + indoor_stronger_year_count
                  + approximately_even_year_count <> comparable_year_count
               OR outdoor_stronger_rate NOT BETWEEN 0 AND 1
            """,
        )
        or 0
    )
    add_check(
        checks,
        "indoor_outdoor_history_counts_valid",
        io_history_errors,
        0,
        io_history_errors == 0,
        "Indoor/outdoor historical counts and rates are internally valid.",
    )

    fabricated_2020 = int(
        scalar(
            connection,
            "SELECT COUNT(*) FROM program_indoor_outdoor_latest "
            "WHERE season_year = 2020",
        )
        or 0
    )
    add_check(
        checks,
        "production_2020_outdoor_not_fabricated",
        fabricated_2020,
        0,
        fabricated_2020 == 0,
        "The known missing 2020 Outdoor production season cannot produce a same-year pair.",
    )

    metric_rows = int(
        scalar(connection, "SELECT COUNT(*) FROM program_comparison_metric_long") or 0
    )
    expected_metric_rows = peer_rows * 8
    add_check(
        checks,
        "comparison_metric_long_row_count",
        metric_rows,
        expected_metric_rows,
        metric_rows == expected_metric_rows,
        "The comparison-long table contains exactly eight metric rows per school profile.",
    )

    metric_duplicates = int(
        scalar(
            connection,
            """
            SELECT COUNT(*) FROM (
                SELECT
                    cohort_key, ranking_scope, gender_scope,
                    resolved_school_id, endpoint_year, season_type,
                    window_years, metric_key, COUNT(*) AS row_count
                FROM program_comparison_metric_long
                GROUP BY ALL
                HAVING COUNT(*) > 1
            )
            """,
        )
        or 0
    )
    add_check(
        checks,
        "comparison_metric_long_keys_unique",
        metric_duplicates,
        0,
        metric_duplicates == 0,
        "Comparison-long school/partition/metric keys are unique.",
    )

    enriched_rows = int(
        scalar(
            connection,
            "SELECT COUNT(*) FROM program_comparison_snapshot_enriched",
        )
        or 0
    )
    add_check(
        checks,
        "enriched_snapshot_rows_reconcile",
        enriched_rows,
        peer_rows,
        enriched_rows == peer_rows,
        "The enriched comparison snapshot retains every peer-context row exactly once.",
    )

    enriched_duplicates = int(
        scalar(
            connection,
            """
            SELECT COUNT(*) FROM (
                SELECT
                    cohort_key, ranking_scope, gender_scope,
                    resolved_school_id, endpoint_year, season_type,
                    window_years, COUNT(*) AS row_count
                FROM program_comparison_snapshot_enriched
                GROUP BY ALL
                HAVING COUNT(*) > 1
            )
            """,
        )
        or 0
    )
    add_check(
        checks,
        "enriched_snapshot_keys_unique",
        enriched_duplicates,
        0,
        enriched_duplicates == 0,
        "Enriched program-comparison snapshot keys are unique.",
    )

    registry_errors = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM comparison_partition_registry
            WHERE school_count < 1
               OR schools_with_conference < 0
               OR schools_with_conference > school_count
               OR conference_count < 0
            """,
        )
        or 0
    )
    add_check(
        checks,
        "comparison_partition_registry_valid",
        registry_errors,
        0,
        registry_errors == 0,
        "Comparison partition counts are internally valid.",
    )

    overall_hash_after = sha256_file(overall_db)
    trajectory_hash_after = sha256_file(trajectory_db)
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
        "trajectory_input_unchanged",
        trajectory_hash_after,
        trajectory_hash_before,
        trajectory_hash_after == trajectory_hash_before,
        "The Phase 7B source database is byte-identical after publication.",
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
    connection.execute(
        f"COPY hard_checks TO '{sql_path(output_dir / 'hard_checks.csv')}' "
        "(HEADER, DELIMITER ',')"
    )


def export_tables(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
) -> list[tuple[str, str, int]]:
    tables = [
        "program_peer_context",
        "program_conference_leaderboard",
        "program_indoor_outdoor_latest",
        "program_indoor_outdoor_history",
        "program_comparison_metric_long",
        "program_comparison_snapshot_enriched",
        "comparison_partition_registry",
        "program_comparison_methodology",
        "hard_checks",
    ]
    registry: list[tuple[str, str, int]] = []
    for table in tables:
        file_name = f"{table}.csv"
        if table != "hard_checks":
            connection.execute(
                f"COPY {table} TO '{sql_path(output_dir / file_name)}' "
                "(HEADER, DELIMITER ',')"
            )
        count = int(scalar(connection, f"SELECT COUNT(*) FROM {table}") or 0)
        registry.append((table, file_name, count))
    return registry


def create_manifests(
    connection: duckdb.DuckDBPyConnection,
    overall_db: Path,
    trajectory_db: Path,
    overall_hash: str,
    trajectory_hash: str,
    registry: list[tuple[str, str, int]],
    output_dir: Path,
) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        CREATE TABLE input_manifest (
            input_name VARCHAR,
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
                "phase_7b_program_trajectory",
                str(trajectory_db.resolve()),
                trajectory_db.stat().st_size,
                trajectory_hash,
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
            (table, file_name, count, DATASET_VERSION, PHASE_VERSION)
            for table, file_name, count in registry
        ],
    )
    for table, file_name in [
        ("input_manifest", "input_manifest.csv"),
        ("output_registry", "output_registry.csv"),
    ]:
        connection.execute(
            f"COPY {table} TO '{sql_path(output_dir / file_name)}' "
            "(HEADER, DELIMITER ',')"
        )


def write_report(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
    output_db: Path,
    checks: list[Check],
) -> None:
    failed = [item for item in checks if item.status != "PASS"]
    tables = [
        "program_peer_context",
        "program_conference_leaderboard",
        "program_indoor_outdoor_latest",
        "program_indoor_outdoor_history",
        "program_comparison_metric_long",
        "program_comparison_snapshot_enriched",
        "comparison_partition_registry",
    ]
    counts = {
        table: int(scalar(connection, f"SELECT COUNT(*) FROM {table}") or 0)
        for table in tables
    }
    lines = [
        "MILESTONE 7 — PHASE 7C PROGRAM COMPARISON REPORT",
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
    (output_dir / "phase_7c_report.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> int:
    args = parse_args()
    overall_db = args.overall_db.resolve()
    trajectory_db = args.trajectory_db.resolve()
    output_dir = args.output_dir.resolve()
    output_db = output_dir / OUTPUT_DB_NAME

    for path, label in [
        (overall_db, "Phase 7A.1 overall database"),
        (trajectory_db, "Phase 7B trajectory database"),
    ]:
        if not path.exists():
            print(f"ERROR: {label} does not exist: {path}", file=sys.stderr)
            return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    if output_db.exists():
        output_db.unlink()

    overall_hash_before = sha256_file(overall_db)
    trajectory_hash_before = sha256_file(trajectory_db)

    connection = duckdb.connect(str(output_db))
    try:
        connection.execute(
            f"ATTACH '{sql_path(overall_db)}' AS overall_src (READ_ONLY)"
        )
        connection.execute(
            f"ATTACH '{sql_path(trajectory_db)}' AS trajectory_src (READ_ONLY)"
        )
        require_tables(
            connection,
            "overall_src",
            ["school_indoor_outdoor_comparison", "hard_checks"],
        )
        require_tables(
            connection,
            "trajectory_src",
            [
                "program_comparison_snapshot",
                "program_latest_snapshot",
                "program_rise_fall_summary",
                "hard_checks",
            ],
        )

        create_peer_context(connection)
        create_conference_leaderboard(connection)
        create_indoor_outdoor_latest(connection)
        create_indoor_outdoor_history(connection)
        create_metric_long(connection)
        create_enriched_snapshot(connection)
        create_partition_registry(connection)
        create_methodology(connection)

        checks = run_checks(
            connection,
            overall_hash_before,
            trajectory_hash_before,
            overall_db,
            trajectory_db,
        )
        write_checks(connection, checks, output_dir)
        registry = export_tables(connection, output_dir)
        create_manifests(
            connection,
            overall_db,
            trajectory_db,
            overall_hash_before,
            trajectory_hash_before,
            registry,
            output_dir,
        )
        write_report(connection, output_dir, output_db, checks)
        connection.execute("CHECKPOINT")

        failed_count = sum(item.status != "PASS" for item in checks)
        counts = {
            table: int(scalar(connection, f"SELECT COUNT(*) FROM {table}") or 0)
            for table in [
                "program_peer_context",
                "program_conference_leaderboard",
                "program_indoor_outdoor_latest",
                "program_indoor_outdoor_history",
                "program_comparison_metric_long",
                "program_comparison_snapshot_enriched",
                "comparison_partition_registry",
            ]
        }

        print(f"Dataset version: {DATASET_VERSION}")
        print(f"Phase version: {PHASE_VERSION}")
        print("Publication mode: enhanced_primary_only")
        print(f"Official primary: {MODEL_LABEL}")
        print(f"Overall source: {overall_db}")
        print(f"Trajectory source: {trajectory_db}")
        print(f"Output database: {output_db}")
        print(f"Peer-context rows: {counts['program_peer_context']:,}")
        print(
            "Conference leaderboard rows: "
            f"{counts['program_conference_leaderboard']:,}"
        )
        print(
            "Latest indoor/outdoor rows: "
            f"{counts['program_indoor_outdoor_latest']:,}"
        )
        print(
            "Indoor/outdoor history rows: "
            f"{counts['program_indoor_outdoor_history']:,}"
        )
        print(
            "Comparison metric rows: "
            f"{counts['program_comparison_metric_long']:,}"
        )
        print(
            "Enriched comparison rows: "
            f"{counts['program_comparison_snapshot_enriched']:,}"
        )
        print(
            "Comparison partition rows: "
            f"{counts['comparison_partition_registry']:,}"
        )
        print(f"Failed checks: {failed_count}")
        print()
        if failed_count:
            print("PHASE GATE: FAIL")
            return 1
        print("PHASE GATE: PASS")
        print("Phase 7C program comparison products published.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
