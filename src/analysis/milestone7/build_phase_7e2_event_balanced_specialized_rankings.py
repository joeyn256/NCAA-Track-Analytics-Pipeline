#!/usr/bin/env python3
"""Build Phase 7E.2 Event-Balanced Specialized Rankings.

The publication is derived only from the frozen Milestone 6 official
Enhanced Balanced Production tables. It does not reuse the Milestone 5
Average Development/posterior rankings.

Published analyses:
1. Development consistency
2. Elite/frontier development
3. Developing baseline tier
4. Competitive baseline tier
5. Advanced baseline tier
6. Elite baseline tier
7. Breakout rate
8. Balanced program
9. Development efficiency
10. Ranking robustness
11. Inbound transfer development
12. National elite finishers — Endpoint 90+

The source database is attached read-only and verified byte-identical before
and after publication.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


DATASET_VERSION = "event_balanced_specialized_rankings_v2"
PHASE_VERSION = "phase_7e_2_event_balanced_specialized_rankings_v2"
MODEL_KEY = "enhanced_balanced_production"
MODEL_LABEL = "Enhanced Balanced Production"

DEFAULT_SOURCE = Path(
    "data/processed/milestone6/final_development_rankings_v1/"
    "phase_6g_final_publication/final_development_rankings_v1.duckdb"
)
DEFAULT_OUTPUT_DIR = Path(
    "data/processed/milestone7/seasonal_program_trends_v1/"
    "phase_7e2_event_balanced_specialized_rankings"
)

BROAD_COHORT = "broad_all_athletes"
FRONTIER_COHORT = "frontier_70_plus"
ELITE_COHORT = "elite_80_plus"
NATIONAL_ELITE_COHORT = "national_elite_endpoint_90_plus"

MIN_CONSISTENCY_SEASONS = 4
MIN_FRONTIER_SEASONS = 5
MIN_ELITE_SEASONS = 5
MIN_NATIONAL_ELITE_SEASONS = 2
MIN_BASELINE_EVENT_UNITS = 30
MIN_BASELINE_ATHLETE_SCHOOLS = 15
MIN_BASELINE_SEASONS = 2
MIN_BREAKOUT_ATHLETE_SCHOOLS = 30
BREAKOUT_PRIOR_STRENGTH = 30.0
MIN_BALANCED_CELLS = 8
MIN_BALANCED_GENDER_CELLS = 3
MIN_EFFICIENCY_EVENT_UNITS = 100
MIN_EFFICIENCY_ATHLETES = 30
MIN_EFFICIENCY_SEASONS = 2
MIN_ROBUSTNESS_PARTITIONS = 5
MIN_INBOUND_ATHLETE_SCHOOLS = 15
MIN_INBOUND_SEASONS = 2

BALANCED_GROUPS = (
    "sprints",
    "middle_distance",
    "distance",
    "hurdles",
    "jumps",
    "throws",
)

ANALYSIS_REGISTRY = [
    (
        "development_consistency",
        "Development consistency",
        "all_time_broad",
        "Consistency index",
        (
            "65% average national rank strength and 35% inverse seasonal "
            "rank-strength volatility across Broad — All Athletes seasons."
        ),
    ),
    (
        "elite_frontier_development",
        "Elite/frontier development",
        "all_time_frontier_elite",
        "Elite/frontier index",
        (
            "Equal-weight average of all-time Frontier 70+ and Elite 80+ "
            "national rank-strength performance."
        ),
    ),
    (
        "baseline_developing",
        "Developing baseline tier",
        "all_time_broad_baseline",
        "Net Event-Balanced points",
        "Broad-cohort athlete-event units with mean baseline level below 50.",
    ),
    (
        "baseline_competitive",
        "Competitive baseline tier",
        "all_time_broad_baseline",
        "Net Event-Balanced points",
        (
            "Broad-cohort athlete-event units with mean baseline level from "
            "50 inclusive to 65 exclusive."
        ),
    ),
    (
        "baseline_advanced",
        "Advanced baseline tier",
        "all_time_broad_baseline",
        "Net Event-Balanced points",
        (
            "Broad-cohort athlete-event units with mean baseline level from "
            "65 inclusive to 80 exclusive."
        ),
    ),
    (
        "baseline_elite",
        "Elite baseline tier",
        "all_time_broad_baseline",
        "Net Event-Balanced points",
        "Broad-cohort athlete-event units with mean baseline level at least 80.",
    ),
    (
        "breakout_rate",
        "Breakout rate",
        "all_time_broad",
        "Stabilized breakout rate",
        (
            "Empirical-Bayes stabilized share of athlete-school units whose "
            "mean official model development signal is at least five."
        ),
    ),
    (
        "balanced_program",
        "Balanced program",
        "all_time_broad",
        "Balanced program index",
        (
            "Average gender-group strength with penalties for dispersion, "
            "gender imbalance, and incomplete six-group coverage."
        ),
    ),
    (
        "development_efficiency",
        "Development efficiency",
        "all_time_broad",
        "Net points per athlete-event unit",
        (
            "Official net Event-Balanced points produced per athlete-event "
            "contribution unit."
        ),
    ),
    (
        "ranking_robustness",
        "Ranking robustness",
        "all_time_model_comparison",
        "Robustness index",
        (
            "70% Enhanced rank strength and 30% stability against Original "
            "Balanced Production v4.1 across shared school partitions."
        ),
    ),
    (
        "inbound_transfer_development",
        "Inbound transfer development",
        "all_time_broad_inferred_transfer",
        "Inbound net Event-Balanced points",
        (
            "Official points produced at school stints beginning after an "
            "athlete's earliest observed school year. Same-year ambiguous "
            "multi-school starts are excluded. Publication remains provisional "
            "and may be unavailable when frozen Broad coverage is insufficient."
        ),
    ),
    (
        "national_elite_endpoint_90_plus",
        "National elite finishers — Endpoint 90+",
        "all_time_national_elite_endpoint_90_plus",
        "National elite rank-strength index",
        (
            "Average national rank strength across published Endpoint 90+ "
            "seasons, requiring at least two eligible season observations."
        ),
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scalar(connection: duckdb.DuckDBPyConnection, sql: str) -> Any:
    row = connection.execute(sql).fetchone()
    return None if row is None else row[0]


def create_registry(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE specialized_analysis_registry (
            analysis_order INTEGER,
            analysis_key VARCHAR,
            analysis_label VARCHAR,
            analysis_scope VARCHAR,
            official_metric_label VARCHAR,
            methodology_summary VARCHAR,
            model_key VARCHAR,
            model_label VARCHAR,
            dataset_version VARCHAR,
            phase_version VARCHAR
        )
        """
    )
    rows = [
        (
            order,
            key,
            label,
            scope,
            metric,
            summary,
            MODEL_KEY,
            MODEL_LABEL,
            DATASET_VERSION,
            PHASE_VERSION,
        )
        for order, (key, label, scope, metric, summary)
        in enumerate(ANALYSIS_REGISTRY, start=1)
    ]
    connection.executemany(
        """
        INSERT INTO specialized_analysis_registry
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def create_source_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE school_metadata AS
        SELECT *
        FROM src.main.school_metadata
        """
    )

    connection.execute(
        f"""
        CREATE TABLE broad_athlete_points AS
        SELECT
            *
        FROM src.main.official_athlete_points
        WHERE model_key = '{MODEL_KEY}'
          AND cohort_key = '{BROAD_COHORT}'
        """
    )

    connection.execute(
        f"""
        CREATE TABLE broad_overall AS
        WITH ranked AS (
            SELECT
                *,
                COUNT(*) OVER (
                    PARTITION BY
                        cohort_key,
                        time_scope,
                        season_year,
                        season_type
                ) AS ranked_school_count
            FROM src.main.official_overall_combined
            WHERE model_key = '{MODEL_KEY}'
              AND cohort_key = '{BROAD_COHORT}'
        )
        SELECT
            *,
            CASE
                WHEN event_balanced_rank IS NULL
                  OR ranked_school_count <= 1
                THEN NULL
                ELSE
                    1.0
                    - (
                        CAST(event_balanced_rank AS DOUBLE) - 1.0
                    )
                    / (
                        CAST(ranked_school_count AS DOUBLE) - 1.0
                    )
            END AS rank_strength
        FROM ranked
        """
    )

    connection.execute(
        f"""
        CREATE TABLE frontier_elite_overall AS
        WITH ranked AS (
            SELECT
                *,
                COUNT(*) OVER (
                    PARTITION BY
                        cohort_key,
                        time_scope,
                        season_year,
                        season_type
                ) AS ranked_school_count
            FROM src.main.official_overall_combined
            WHERE model_key = '{MODEL_KEY}'
              AND cohort_key IN (
                  '{FRONTIER_COHORT}',
                  '{ELITE_COHORT}'
              )
        )
        SELECT
            *,
            CASE
                WHEN event_balanced_rank IS NULL
                  OR ranked_school_count <= 1
                THEN NULL
                ELSE
                    1.0
                    - (
                        CAST(event_balanced_rank AS DOUBLE) - 1.0
                    )
                    / (
                        CAST(ranked_school_count AS DOUBLE) - 1.0
                    )
            END AS rank_strength
        FROM ranked
        """
    )

    connection.execute(
        f"""
        CREATE TABLE national_elite_overall AS
        WITH ranked AS (
            SELECT
                *,
                COUNT(*) OVER (
                    PARTITION BY
                        cohort_key,
                        time_scope,
                        season_year,
                        season_type
                ) AS ranked_school_count
            FROM src.main.official_overall_combined
            WHERE model_key = '{MODEL_KEY}'
              AND cohort_key = '{NATIONAL_ELITE_COHORT}'
        )
        SELECT
            *,
            CASE
                WHEN event_balanced_rank IS NULL
                  OR ranked_school_count <= 1
                THEN NULL
                ELSE
                    1.0
                    - (
                        CAST(event_balanced_rank AS DOUBLE) - 1.0
                    )
                    / (
                        CAST(ranked_school_count AS DOUBLE) - 1.0
                    )
            END AS rank_strength
        FROM ranked
        """
    )

    connection.execute(
        f"""
        CREATE TABLE broad_group_gender AS
        SELECT *
        FROM src.main.official_group_points_gender
        WHERE model_key = '{MODEL_KEY}'
          AND cohort_key = '{BROAD_COHORT}'
          AND gender_scope IN ('m', 'f')
          AND balanced_group_key IN (
              'sprints',
              'middle_distance',
              'distance',
              'hurdles',
              'jumps',
              'throws'
          )
        """
    )


def create_consistency(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE development_consistency_rankings AS
        WITH school_history AS (
            SELECT
                resolved_school_id,
                ANY_VALUE(school_name) AS school_name,
                COUNT(DISTINCT season_key) AS season_count,
                AVG(rank_strength) AS mean_rank_strength,
                STDDEV_SAMP(rank_strength) AS rank_strength_sd,
                AVG(total_event_balanced_points) AS mean_net_points,
                SUM(total_event_balanced_points) AS total_net_points,
                SUM(athlete_event_unit_count) AS athlete_event_unit_count,
                SUM(positive_athlete_count) AS positive_athlete_count,
                SUM(negative_athlete_count) AS negative_athlete_count
            FROM broad_overall
            WHERE rank_strength IS NOT NULL
            GROUP BY resolved_school_id
        ),
        eligible AS (
            SELECT
                *,
                1.0
                - PERCENT_RANK() OVER (
                    ORDER BY COALESCE(rank_strength_sd, 1.0) ASC
                ) AS stability_percentile
            FROM school_history
            WHERE season_count >= {MIN_CONSISTENCY_SEASONS}
        ),
        scored AS (
            SELECT
                *,
                0.65 * mean_rank_strength
                + 0.35 * stability_percentile AS consistency_index
            FROM eligible
        )
        SELECT
            DENSE_RANK() OVER (
                ORDER BY consistency_index DESC, mean_rank_strength DESC,
                         total_net_points DESC, school_name
            ) AS official_rank,
            COUNT(*) OVER () AS official_ranked_school_count,
            resolved_school_id,
            school_name,
            season_count,
            mean_rank_strength,
            rank_strength_sd,
            stability_percentile,
            consistency_index,
            mean_net_points,
            total_net_points,
            athlete_event_unit_count,
            positive_athlete_count,
            negative_athlete_count,
            {MIN_CONSISTENCY_SEASONS} AS minimum_seasons,
            '{MODEL_KEY}' AS model_key,
            '{MODEL_LABEL}' AS model_label,
            '{DATASET_VERSION}' AS dataset_version
        FROM scored
        ORDER BY official_rank, school_name
        """
    )


def create_elite_frontier(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE elite_frontier_development_rankings AS
        WITH cohort_summary AS (
            SELECT
                resolved_school_id,
                ANY_VALUE(school_name) AS school_name,
                cohort_key,
                COUNT(DISTINCT season_key) AS season_count,
                AVG(rank_strength) AS mean_rank_strength,
                SUM(total_event_balanced_points) AS total_net_points,
                SUM(athlete_event_unit_count) AS athlete_event_unit_count
            FROM frontier_elite_overall
            WHERE rank_strength IS NOT NULL
            GROUP BY resolved_school_id, cohort_key
        ),
        pivoted AS (
            SELECT
                resolved_school_id,
                ANY_VALUE(school_name) AS school_name,
                MAX(
                    CASE WHEN cohort_key = '{FRONTIER_COHORT}'
                         THEN season_count END
                ) AS frontier_season_count,
                MAX(
                    CASE WHEN cohort_key = '{ELITE_COHORT}'
                         THEN season_count END
                ) AS elite_season_count,
                MAX(
                    CASE WHEN cohort_key = '{FRONTIER_COHORT}'
                         THEN mean_rank_strength END
                ) AS frontier_mean_rank_strength,
                MAX(
                    CASE WHEN cohort_key = '{ELITE_COHORT}'
                         THEN mean_rank_strength END
                ) AS elite_mean_rank_strength,
                SUM(total_net_points) AS total_net_points,
                SUM(athlete_event_unit_count) AS athlete_event_unit_count
            FROM cohort_summary
            GROUP BY resolved_school_id
        ),
        eligible AS (
            SELECT
                *,
                0.5 * frontier_mean_rank_strength
                + 0.5 * elite_mean_rank_strength
                    AS elite_frontier_index
            FROM pivoted
            WHERE frontier_season_count >= {MIN_FRONTIER_SEASONS}
              AND elite_season_count >= {MIN_ELITE_SEASONS}
              AND frontier_mean_rank_strength IS NOT NULL
              AND elite_mean_rank_strength IS NOT NULL
        )
        SELECT
            DENSE_RANK() OVER (
                ORDER BY elite_frontier_index DESC,
                         elite_mean_rank_strength DESC,
                         frontier_mean_rank_strength DESC,
                         total_net_points DESC,
                         school_name
            ) AS official_rank,
            COUNT(*) OVER () AS official_ranked_school_count,
            resolved_school_id,
            school_name,
            frontier_season_count,
            elite_season_count,
            frontier_mean_rank_strength,
            elite_mean_rank_strength,
            elite_frontier_index,
            total_net_points,
            athlete_event_unit_count,
            {MIN_FRONTIER_SEASONS} AS minimum_frontier_seasons,
            {MIN_ELITE_SEASONS} AS minimum_elite_seasons,
            '{MODEL_KEY}' AS model_key,
            '{MODEL_LABEL}' AS model_label,
            '{DATASET_VERSION}' AS dataset_version
        FROM eligible
        ORDER BY official_rank, school_name
        """
    )


def create_national_elite_endpoint90(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute(
        f"""
        CREATE TABLE national_elite_endpoint90_rankings AS
        WITH school_summary AS (
            SELECT
                resolved_school_id,
                ANY_VALUE(school_name) AS school_name,
                COUNT(DISTINCT season_key) AS season_count,
                COUNT(DISTINCT season_year) AS calendar_year_count,
                COUNT(DISTINCT season_type) AS season_type_count,
                AVG(rank_strength) AS mean_rank_strength,
                MEDIAN(rank_strength) AS median_rank_strength,
                MIN(rank_strength) AS minimum_rank_strength,
                MAX(rank_strength) AS maximum_rank_strength,
                SUM(total_event_balanced_points) AS total_net_points,
                SUM(athlete_event_unit_count) AS athlete_event_unit_count
            FROM national_elite_overall
            WHERE rank_strength IS NOT NULL
            GROUP BY resolved_school_id
        ),
        eligible AS (
            SELECT
                *,
                mean_rank_strength AS national_elite_rank_strength_index
            FROM school_summary
            WHERE season_count >= {MIN_NATIONAL_ELITE_SEASONS}
        )
        SELECT
            DENSE_RANK() OVER (
                ORDER BY national_elite_rank_strength_index DESC,
                         median_rank_strength DESC,
                         total_net_points DESC,
                         season_count DESC,
                         school_name
            ) AS official_rank,
            COUNT(*) OVER () AS official_ranked_school_count,
            resolved_school_id,
            school_name,
            season_count,
            calendar_year_count,
            season_type_count,
            mean_rank_strength,
            median_rank_strength,
            minimum_rank_strength,
            maximum_rank_strength,
            national_elite_rank_strength_index,
            total_net_points,
            athlete_event_unit_count,
            {MIN_NATIONAL_ELITE_SEASONS}
                AS minimum_national_elite_seasons,
            '{NATIONAL_ELITE_COHORT}' AS cohort_key,
            '{MODEL_KEY}' AS model_key,
            '{MODEL_LABEL}' AS model_label,
            '{DATASET_VERSION}' AS dataset_version
        FROM eligible
        ORDER BY official_rank, school_name
        """
    )


def create_baseline_tiers(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE baseline_tier_rankings AS
        WITH assigned AS (
            SELECT
                *,
                CASE
                    WHEN mean_baseline_level < 50
                        THEN 'developing'
                    WHEN mean_baseline_level < 65
                        THEN 'competitive'
                    WHEN mean_baseline_level < 80
                        THEN 'advanced'
                    ELSE 'elite'
                END AS baseline_tier_key,
                CASE
                    WHEN mean_baseline_level < 50
                        THEN 'Developing baseline tier'
                    WHEN mean_baseline_level < 65
                        THEN 'Competitive baseline tier'
                    WHEN mean_baseline_level < 80
                        THEN 'Advanced baseline tier'
                    ELSE 'Elite baseline tier'
                END AS baseline_tier_label
            FROM broad_athlete_points
            WHERE mean_baseline_level IS NOT NULL
        ),
        school_tier AS (
            SELECT
                baseline_tier_key,
                ANY_VALUE(baseline_tier_label) AS baseline_tier_label,
                resolved_school_id,
                ANY_VALUE(school_name) AS school_name,
                COUNT(*) AS athlete_event_unit_count,
                COUNT(
                    DISTINCT canonical_person_id || '|' || resolved_school_id
                ) AS athlete_school_unit_count,
                COUNT(DISTINCT canonical_person_id) AS distinct_athlete_count,
                COUNT(DISTINCT season_key) AS season_count,
                COUNT(DISTINCT canonical_event_code) AS event_count,
                SUM(athlete_positive_points) AS positive_points,
                SUM(athlete_negative_points) AS negative_points,
                SUM(athlete_net_points) AS net_points,
                AVG(model_development_signal) AS mean_model_signal,
                AVG(reliability_factor) AS mean_reliability_factor,
                AVG(mean_baseline_level) AS mean_baseline_level,
                AVG(mean_endpoint_level) AS mean_endpoint_level
            FROM assigned
            GROUP BY baseline_tier_key, resolved_school_id
        ),
        eligible AS (
            SELECT *
            FROM school_tier
            WHERE athlete_event_unit_count >= {MIN_BASELINE_EVENT_UNITS}
              AND athlete_school_unit_count >= {MIN_BASELINE_ATHLETE_SCHOOLS}
              AND season_count >= {MIN_BASELINE_SEASONS}
        )
        SELECT
            baseline_tier_key,
            baseline_tier_label,
            DENSE_RANK() OVER (
                PARTITION BY baseline_tier_key
                ORDER BY net_points DESC, positive_points DESC,
                         athlete_school_unit_count DESC, school_name
            ) AS official_rank,
            COUNT(*) OVER (
                PARTITION BY baseline_tier_key
            ) AS official_ranked_school_count,
            resolved_school_id,
            school_name,
            athlete_event_unit_count,
            athlete_school_unit_count,
            distinct_athlete_count,
            season_count,
            event_count,
            positive_points,
            negative_points,
            net_points,
            net_points / NULLIF(athlete_event_unit_count, 0)
                AS net_points_per_event_unit,
            mean_model_signal,
            mean_reliability_factor,
            mean_baseline_level,
            mean_endpoint_level,
            {MIN_BASELINE_EVENT_UNITS} AS minimum_event_units,
            {MIN_BASELINE_ATHLETE_SCHOOLS} AS minimum_athlete_schools,
            {MIN_BASELINE_SEASONS} AS minimum_seasons,
            '{MODEL_KEY}' AS model_key,
            '{MODEL_LABEL}' AS model_label,
            '{DATASET_VERSION}' AS dataset_version
        FROM eligible
        ORDER BY baseline_tier_key, official_rank, school_name
        """
    )


def create_breakout(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE breakout_rate_rankings AS
        WITH athlete_school AS (
            SELECT
                canonical_person_id,
                resolved_school_id,
                ANY_VALUE(school_name) AS school_name,
                AVG(model_development_signal) AS mean_model_signal,
                SUM(athlete_net_points) AS net_points,
                COUNT(*) AS athlete_event_unit_count
            FROM broad_athlete_points
            GROUP BY canonical_person_id, resolved_school_id
        ),
        school_counts AS (
            SELECT
                resolved_school_id,
                ANY_VALUE(school_name) AS school_name,
                COUNT(*) AS athlete_school_unit_count,
                SUM(CASE WHEN mean_model_signal >= 5.0 THEN 1 ELSE 0 END)
                    AS breakout_count,
                AVG(CASE WHEN mean_model_signal >= 5.0 THEN 1.0 ELSE 0.0 END)
                    AS raw_breakout_rate,
                SUM(net_points) AS net_points,
                SUM(athlete_event_unit_count) AS athlete_event_unit_count
            FROM athlete_school
            GROUP BY resolved_school_id
        ),
        prior AS (
            SELECT
                SUM(breakout_count)::DOUBLE
                / NULLIF(SUM(athlete_school_unit_count), 0)
                    AS global_breakout_rate
            FROM school_counts
        ),
        eligible AS (
            SELECT
                school_counts.*,
                prior.global_breakout_rate,
                (
                    breakout_count
                    + prior.global_breakout_rate
                      * {BREAKOUT_PRIOR_STRENGTH}
                )
                / (
                    athlete_school_unit_count
                    + {BREAKOUT_PRIOR_STRENGTH}
                ) AS stabilized_breakout_rate
            FROM school_counts
            CROSS JOIN prior
            WHERE athlete_school_unit_count
                >= {MIN_BREAKOUT_ATHLETE_SCHOOLS}
        )
        SELECT
            DENSE_RANK() OVER (
                ORDER BY stabilized_breakout_rate DESC,
                         raw_breakout_rate DESC,
                         breakout_count DESC,
                         school_name
            ) AS official_rank,
            COUNT(*) OVER () AS official_ranked_school_count,
            resolved_school_id,
            school_name,
            athlete_school_unit_count,
            breakout_count,
            raw_breakout_rate,
            global_breakout_rate,
            {BREAKOUT_PRIOR_STRENGTH} AS prior_strength,
            stabilized_breakout_rate,
            net_points,
            athlete_event_unit_count,
            {MIN_BREAKOUT_ATHLETE_SCHOOLS}
                AS minimum_athlete_school_units,
            '{MODEL_KEY}' AS model_key,
            '{MODEL_LABEL}' AS model_label,
            '{DATASET_VERSION}' AS dataset_version
        FROM eligible
        ORDER BY official_rank, school_name
        """
    )


def create_balanced_program(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE balanced_program_rankings AS
        WITH cell_summary AS (
            SELECT
                resolved_school_id,
                ANY_VALUE(school_name) AS school_name,
                gender_scope,
                balanced_group_key,
                ANY_VALUE(balanced_group_label) AS balanced_group_label,
                COUNT(DISTINCT season_key) AS season_count,
                AVG(group_strength_share) AS mean_group_strength_share,
                SUM(group_balanced_points) AS total_group_points,
                SUM(athlete_event_unit_count) AS athlete_event_unit_count
            FROM broad_group_gender
            GROUP BY
                resolved_school_id,
                gender_scope,
                balanced_group_key
        ),
        ranked_cells AS (
            SELECT
                *,
                PERCENT_RANK() OVER (
                    PARTITION BY gender_scope, balanced_group_key
                    ORDER BY mean_group_strength_share
                ) AS cell_strength_percentile
            FROM cell_summary
        ),
        school_summary AS (
            SELECT
                resolved_school_id,
                ANY_VALUE(school_name) AS school_name,
                COUNT(*) AS covered_cell_count,
                COUNT(*) FILTER (WHERE gender_scope = 'm')
                    AS men_cell_count,
                COUNT(*) FILTER (WHERE gender_scope = 'f')
                    AS women_cell_count,
                AVG(cell_strength_percentile)
                    AS mean_cell_strength_percentile,
                STDDEV_SAMP(cell_strength_percentile)
                    AS cell_strength_sd,
                AVG(cell_strength_percentile)
                    FILTER (WHERE gender_scope = 'm')
                    AS men_mean_strength,
                AVG(cell_strength_percentile)
                    FILTER (WHERE gender_scope = 'f')
                    AS women_mean_strength,
                SUM(total_group_points) AS total_group_points,
                SUM(athlete_event_unit_count) AS athlete_event_unit_count
            FROM ranked_cells
            GROUP BY resolved_school_id
        ),
        eligible AS (
            SELECT
                *,
                ABS(men_mean_strength - women_mean_strength)
                    AS gender_strength_gap,
                (
                    mean_cell_strength_percentile
                    - 0.20 * COALESCE(cell_strength_sd, 0.0)
                    - 0.10 * ABS(
                        men_mean_strength - women_mean_strength
                    )
                    - 0.05 * (
                        12.0 - covered_cell_count
                    ) / 12.0
                ) AS balanced_program_index
            FROM school_summary
            WHERE covered_cell_count >= {MIN_BALANCED_CELLS}
              AND men_cell_count >= {MIN_BALANCED_GENDER_CELLS}
              AND women_cell_count >= {MIN_BALANCED_GENDER_CELLS}
        )
        SELECT
            DENSE_RANK() OVER (
                ORDER BY balanced_program_index DESC,
                         mean_cell_strength_percentile DESC,
                         total_group_points DESC,
                         school_name
            ) AS official_rank,
            COUNT(*) OVER () AS official_ranked_school_count,
            resolved_school_id,
            school_name,
            covered_cell_count,
            men_cell_count,
            women_cell_count,
            mean_cell_strength_percentile,
            cell_strength_sd,
            men_mean_strength,
            women_mean_strength,
            gender_strength_gap,
            balanced_program_index,
            total_group_points,
            athlete_event_unit_count,
            {MIN_BALANCED_CELLS} AS minimum_cells,
            {MIN_BALANCED_GENDER_CELLS} AS minimum_gender_cells,
            '{MODEL_KEY}' AS model_key,
            '{MODEL_LABEL}' AS model_label,
            '{DATASET_VERSION}' AS dataset_version
        FROM eligible
        ORDER BY official_rank, school_name
        """
    )


def create_efficiency(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE development_efficiency_rankings AS
        WITH school_summary AS (
            SELECT
                resolved_school_id,
                ANY_VALUE(school_name) AS school_name,
                COUNT(*) AS athlete_event_unit_count,
                COUNT(DISTINCT canonical_person_id) AS distinct_athlete_count,
                COUNT(DISTINCT season_key) AS season_count,
                COUNT(DISTINCT canonical_event_code) AS event_count,
                SUM(athlete_positive_points) AS positive_points,
                SUM(athlete_negative_points) AS negative_points,
                SUM(athlete_net_points) AS net_points,
                SUM(athlete_net_points) / NULLIF(COUNT(*), 0)
                    AS net_points_per_event_unit,
                SUM(athlete_positive_points) / NULLIF(COUNT(*), 0)
                    AS positive_points_per_event_unit,
                AVG(model_development_signal) AS mean_model_signal,
                AVG(annualized_development_signal)
                    AS mean_annualized_development_signal,
                AVG(reliability_factor) AS mean_reliability_factor
            FROM broad_athlete_points
            GROUP BY resolved_school_id
        ),
        eligible AS (
            SELECT *
            FROM school_summary
            WHERE athlete_event_unit_count >= {MIN_EFFICIENCY_EVENT_UNITS}
              AND distinct_athlete_count >= {MIN_EFFICIENCY_ATHLETES}
              AND season_count >= {MIN_EFFICIENCY_SEASONS}
        )
        SELECT
            DENSE_RANK() OVER (
                ORDER BY net_points_per_event_unit DESC,
                         positive_points_per_event_unit DESC,
                         net_points DESC,
                         school_name
            ) AS official_rank,
            COUNT(*) OVER () AS official_ranked_school_count,
            resolved_school_id,
            school_name,
            athlete_event_unit_count,
            distinct_athlete_count,
            season_count,
            event_count,
            positive_points,
            negative_points,
            net_points,
            net_points_per_event_unit,
            positive_points_per_event_unit,
            mean_model_signal,
            mean_annualized_development_signal,
            mean_reliability_factor,
            {MIN_EFFICIENCY_EVENT_UNITS} AS minimum_event_units,
            {MIN_EFFICIENCY_ATHLETES} AS minimum_athletes,
            {MIN_EFFICIENCY_SEASONS} AS minimum_seasons,
            '{MODEL_KEY}' AS model_key,
            '{MODEL_LABEL}' AS model_label,
            '{DATASET_VERSION}' AS dataset_version
        FROM eligible
        ORDER BY official_rank, school_name
        """
    )


def create_robustness(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE ranking_robustness_rankings AS
        WITH official_ranked AS (
            SELECT
                *,
                COUNT(*) OVER (
                    PARTITION BY
                        cohort_key,
                        time_scope,
                        season_year,
                        season_type
                ) AS ranked_school_count
            FROM src.main.event_balanced_overall_combined
            WHERE model_key = '{MODEL_KEY}'
        ),
        joined AS (
            SELECT
                comparison.resolved_school_id,
                comparison.school_name,
                comparison.cohort_key,
                comparison.time_scope,
                comparison.season_year,
                comparison.season_type,
                comparison.enhanced_rank,
                comparison.original_v4_1_rank,
                comparison.rank_shift,
                comparison.absolute_rank_shift,
                official.ranked_school_count,
                CASE
                    WHEN official.ranked_school_count <= 1
                    THEN NULL
                    ELSE
                        1.0
                        - (
                            CAST(comparison.enhanced_rank AS DOUBLE) - 1.0
                        )
                        / (
                            CAST(official.ranked_school_count AS DOUBLE) - 1.0
                        )
                END AS enhanced_rank_strength
            FROM src.main.model_rank_comparison_school AS comparison
            INNER JOIN official_ranked AS official
                ON official.cohort_key = comparison.cohort_key
               AND official.time_scope = comparison.time_scope
               AND official.season_year = comparison.season_year
               AND official.season_type = comparison.season_type
               AND official.resolved_school_id
                    = comparison.resolved_school_id
        ),
        school_summary AS (
            SELECT
                resolved_school_id,
                ANY_VALUE(school_name) AS school_name,
                COUNT(*) AS compared_partition_count,
                AVG(enhanced_rank_strength)
                    AS mean_enhanced_rank_strength,
                AVG(absolute_rank_shift) AS mean_absolute_rank_shift,
                MAX(absolute_rank_shift) AS maximum_absolute_rank_shift,
                MEDIAN(absolute_rank_shift)
                    AS median_absolute_rank_shift,
                AVG(CASE WHEN absolute_rank_shift <= 5 THEN 1.0 ELSE 0.0 END)
                    AS within_five_rank_share,
                AVG(CASE WHEN rank_shift >= 0 THEN 1.0 ELSE 0.0 END)
                    AS enhanced_same_or_better_share
            FROM joined
            WHERE enhanced_rank_strength IS NOT NULL
            GROUP BY resolved_school_id
        ),
        eligible AS (
            SELECT
                *,
                1.0
                - PERCENT_RANK() OVER (
                    ORDER BY mean_absolute_rank_shift ASC
                ) AS rank_stability_percentile
            FROM school_summary
            WHERE compared_partition_count >= {MIN_ROBUSTNESS_PARTITIONS}
        ),
        scored AS (
            SELECT
                *,
                0.70 * mean_enhanced_rank_strength
                + 0.30 * rank_stability_percentile
                    AS robustness_index
            FROM eligible
        )
        SELECT
            DENSE_RANK() OVER (
                ORDER BY robustness_index DESC,
                         mean_enhanced_rank_strength DESC,
                         mean_absolute_rank_shift ASC,
                         school_name
            ) AS official_rank,
            COUNT(*) OVER () AS official_ranked_school_count,
            resolved_school_id,
            school_name,
            compared_partition_count,
            mean_enhanced_rank_strength,
            mean_absolute_rank_shift,
            median_absolute_rank_shift,
            maximum_absolute_rank_shift,
            within_five_rank_share,
            enhanced_same_or_better_share,
            rank_stability_percentile,
            robustness_index,
            {MIN_ROBUSTNESS_PARTITIONS} AS minimum_partitions,
            '{MODEL_KEY}' AS model_key,
            '{MODEL_LABEL}' AS model_label,
            '{DATASET_VERSION}' AS dataset_version
        FROM scored
        ORDER BY official_rank, school_name
        """
    )


def create_inbound_transfer(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE inbound_transfer_development_rankings AS
        WITH athlete_school AS (
            SELECT
                canonical_person_id,
                resolved_school_id,
                ANY_VALUE(school_name) AS school_name,
                MIN(season_year) AS school_first_year,
                MAX(season_year) AS school_last_year,
                COUNT(DISTINCT season_key) AS school_season_count,
                COUNT(*) AS athlete_event_unit_count,
                SUM(athlete_positive_points) AS positive_points,
                SUM(athlete_negative_points) AS negative_points,
                SUM(athlete_net_points) AS net_points,
                AVG(model_development_signal) AS mean_model_signal,
                AVG(reliability_factor) AS mean_reliability_factor
            FROM broad_athlete_points
            GROUP BY canonical_person_id, resolved_school_id
        ),
        athlete_history AS (
            SELECT
                canonical_person_id,
                MIN(school_first_year) AS athlete_first_year,
                COUNT(*) AS observed_school_count,
                COUNT(*) FILTER (
                    WHERE school_first_year = minimum_year
                ) AS earliest_year_school_count
            FROM (
                SELECT
                    *,
                    MIN(school_first_year) OVER (
                        PARTITION BY canonical_person_id
                    ) AS minimum_year
                FROM athlete_school
            )
            GROUP BY canonical_person_id
        ),
        inbound_units AS (
            SELECT
                athlete_school.*,
                athlete_history.athlete_first_year,
                athlete_history.observed_school_count,
                athlete_history.earliest_year_school_count
            FROM athlete_school
            INNER JOIN athlete_history
                USING (canonical_person_id)
            WHERE observed_school_count > 1
              AND earliest_year_school_count = 1
              AND school_first_year > athlete_first_year
        ),
        school_summary AS (
            SELECT
                resolved_school_id,
                ANY_VALUE(school_name) AS school_name,
                COUNT(*) AS inbound_athlete_school_unit_count,
                COUNT(DISTINCT canonical_person_id)
                    AS distinct_inbound_athlete_count,
                COUNT(DISTINCT school_first_year)
                    AS inbound_start_year_count,
                COUNT(DISTINCT school_last_year)
                    AS represented_end_year_count,
                SUM(athlete_event_unit_count)
                    AS athlete_event_unit_count,
                SUM(positive_points) AS positive_points,
                SUM(negative_points) AS negative_points,
                SUM(net_points) AS net_points,
                SUM(net_points)
                    / NULLIF(COUNT(*), 0)
                    AS net_points_per_inbound_athlete,
                AVG(mean_model_signal) AS mean_model_signal,
                AVG(mean_reliability_factor)
                    AS mean_reliability_factor
            FROM inbound_units
            GROUP BY resolved_school_id
        ),
        eligible AS (
            SELECT *
            FROM school_summary
            WHERE inbound_athlete_school_unit_count
                >= {MIN_INBOUND_ATHLETE_SCHOOLS}
              AND inbound_start_year_count >= {MIN_INBOUND_SEASONS}
        )
        SELECT
            DENSE_RANK() OVER (
                ORDER BY net_points DESC,
                         net_points_per_inbound_athlete DESC,
                         inbound_athlete_school_unit_count DESC,
                         school_name
            ) AS official_rank,
            COUNT(*) OVER () AS official_ranked_school_count,
            resolved_school_id,
            school_name,
            inbound_athlete_school_unit_count,
            distinct_inbound_athlete_count,
            inbound_start_year_count,
            represented_end_year_count,
            athlete_event_unit_count,
            positive_points,
            negative_points,
            net_points,
            net_points_per_inbound_athlete,
            mean_model_signal,
            mean_reliability_factor,
            {MIN_INBOUND_ATHLETE_SCHOOLS}
                AS minimum_inbound_athlete_schools,
            {MIN_INBOUND_SEASONS} AS minimum_inbound_start_years,
            'chronology_inferred_after_unique_earliest_school_year'
                AS transfer_inference_method,
            '{MODEL_KEY}' AS model_key,
            '{MODEL_LABEL}' AS model_label,
            '{DATASET_VERSION}' AS dataset_version
        FROM eligible
        ORDER BY official_rank, school_name
        """
    )

    connection.execute(
        f"""
        CREATE TABLE transfer_inference_registry AS
        SELECT
            'chronology_inferred_after_unique_earliest_school_year'
                AS transfer_inference_method,
            CASE
                WHEN COUNT(*) > 0
                THEN 'published_provisional'
                ELSE 'not_publishable_under_frozen_broad_coverage'
            END AS publication_status,
            COUNT(*) AS published_school_count,
            {MIN_INBOUND_ATHLETE_SCHOOLS} AS minimum_inbound_athlete_schools,
            {MIN_INBOUND_SEASONS} AS minimum_inbound_start_years,
            '{MODEL_KEY}' AS model_key,
            '{DATASET_VERSION}' AS dataset_version
        FROM inbound_transfer_development_rankings
        """
    )


def create_leader_summary(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE specialized_ranking_leaders AS
        SELECT
            1 AS analysis_order,
            'development_consistency' AS analysis_key,
            'Development consistency' AS analysis_label,
            school_name AS leader_school,
            consistency_index AS leader_metric_value,
            'Consistency index' AS metric_label
        FROM development_consistency_rankings
        WHERE official_rank = 1

        UNION ALL

        SELECT
            2,
            'elite_frontier_development',
            'Elite/frontier development',
            school_name,
            elite_frontier_index,
            'Elite/frontier index'
        FROM elite_frontier_development_rankings
        WHERE official_rank = 1

        UNION ALL

        SELECT
            CASE baseline_tier_key
                WHEN 'developing' THEN 3
                WHEN 'competitive' THEN 4
                WHEN 'advanced' THEN 5
                WHEN 'elite' THEN 6
            END,
            'baseline_' || baseline_tier_key,
            baseline_tier_label,
            school_name,
            net_points,
            'Net Event-Balanced points'
        FROM baseline_tier_rankings
        WHERE official_rank = 1

        UNION ALL

        SELECT
            7,
            'breakout_rate',
            'Breakout rate',
            school_name,
            stabilized_breakout_rate,
            'Stabilized breakout rate'
        FROM breakout_rate_rankings
        WHERE official_rank = 1

        UNION ALL

        SELECT
            8,
            'balanced_program',
            'Balanced program',
            school_name,
            balanced_program_index,
            'Balanced program index'
        FROM balanced_program_rankings
        WHERE official_rank = 1

        UNION ALL

        SELECT
            9,
            'development_efficiency',
            'Development efficiency',
            school_name,
            net_points_per_event_unit,
            'Net points per athlete-event unit'
        FROM development_efficiency_rankings
        WHERE official_rank = 1

        UNION ALL

        SELECT
            10,
            'ranking_robustness',
            'Ranking robustness',
            school_name,
            robustness_index,
            'Robustness index'
        FROM ranking_robustness_rankings
        WHERE official_rank = 1

        UNION ALL

        SELECT
            11,
            'inbound_transfer_development',
            'Inbound transfer development',
            school_name,
            net_points,
            'Inbound net Event-Balanced points'
        FROM inbound_transfer_development_rankings
        WHERE official_rank = 1

        UNION ALL

        SELECT
            12,
            'national_elite_endpoint_90_plus',
            'National elite finishers — Endpoint 90+',
            school_name,
            national_elite_rank_strength_index,
            'National elite rank-strength index'
        FROM national_elite_endpoint90_rankings
        WHERE official_rank = 1

        ORDER BY analysis_order
        """
    )


def add_check(
    rows: list[tuple[str, str, str, str, str]],
    name: str,
    passed: bool,
    observed: Any,
    expected: Any,
    details: str,
) -> None:
    rows.append(
        (
            name,
            "PASS" if passed else "FAIL",
            str(observed),
            str(expected),
            details,
        )
    )


def create_hard_checks(
    connection: duckdb.DuckDBPyConnection,
    source_hash_before: str,
    source_hash_after: str,
) -> int:
    checks: list[tuple[str, str, str, str, str]] = []

    source_models = scalar(
        connection,
        """
        SELECT COUNT(DISTINCT model_key)
        FROM broad_athlete_points
        """,
    )
    source_model_value = scalar(
        connection,
        """
        SELECT MIN(model_key)
        FROM broad_athlete_points
        """,
    )
    add_check(
        checks,
        "enhanced_is_exclusive_model",
        source_models == 1 and source_model_value == MODEL_KEY,
        f"{source_models}:{source_model_value}",
        f"1:{MODEL_KEY}",
        "Specialized rankings must use Enhanced Balanced Production only.",
    )

    analysis_count = scalar(
        connection,
        "SELECT COUNT(*) FROM specialized_analysis_registry",
    )
    add_check(
        checks,
        "exactly_twelve_analyses_registered",
        analysis_count == 12,
        analysis_count,
        12,
        "The frozen specialized-ranking contract contains twelve analyses, including Endpoint 90+.",
    )

    leader_count = scalar(
        connection,
        "SELECT COUNT(*) FROM specialized_ranking_leaders",
    )
    transfer_row_count = scalar(
        connection,
        "SELECT COUNT(*) FROM inbound_transfer_development_rankings",
    )
    expected_leader_count = 11 + (1 if transfer_row_count > 0 else 0)
    add_check(
        checks,
        "all_publishable_leaders_published",
        leader_count == expected_leader_count,
        leader_count,
        expected_leader_count,
        (
            "Every publishable specialized analysis must publish a current "
            "leader. Inbound transfer may remain unavailable when frozen "
            "Broad coverage yields no eligible destination schools."
        ),
    )

    endpoint90_leader_count = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM specialized_ranking_leaders
        WHERE analysis_key = 'national_elite_endpoint_90_plus'
        """,
    )
    add_check(
        checks,
        "national_elite_endpoint90_leader_published",
        endpoint90_leader_count == 1,
        endpoint90_leader_count,
        1,
        "The existing Endpoint 90+ cohort must publish one specialized leader.",
    )

    table_key_checks = [
        (
            "development_consistency_rankings",
            "resolved_school_id",
        ),
        (
            "elite_frontier_development_rankings",
            "resolved_school_id",
        ),
        (
            "national_elite_endpoint90_rankings",
            "resolved_school_id",
        ),
        (
            "baseline_tier_rankings",
            "baseline_tier_key || '|' || resolved_school_id",
        ),
        (
            "breakout_rate_rankings",
            "resolved_school_id",
        ),
        (
            "balanced_program_rankings",
            "resolved_school_id",
        ),
        (
            "development_efficiency_rankings",
            "resolved_school_id",
        ),
        (
            "ranking_robustness_rankings",
            "resolved_school_id",
        ),
        (
            "inbound_transfer_development_rankings",
            "resolved_school_id",
        ),
    ]
    for table_name, key_expr in table_key_checks:
        duplicates = scalar(
            connection,
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT {key_expr} AS row_key, COUNT(*) AS row_count
                FROM {table_name}
                GROUP BY row_key
                HAVING COUNT(*) > 1
            )
            """,
        )
        add_check(
            checks,
            f"{table_name}_keys_unique",
            duplicates == 0,
            duplicates,
            0,
            f"{table_name} publication keys must be unique.",
        )

    missing_tiers = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM (
            VALUES
                ('developing'),
                ('competitive'),
                ('advanced'),
                ('elite')
        ) AS required(tier)
        WHERE tier NOT IN (
            SELECT DISTINCT baseline_tier_key
            FROM baseline_tier_rankings
        )
        """,
    )
    add_check(
        checks,
        "all_four_baseline_tiers_published",
        missing_tiers == 0,
        missing_tiers,
        0,
        "Developing, competitive, advanced, and elite tiers must all publish.",
    )

    bad_baseline_bounds = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM baseline_tier_rankings
        WHERE
            (baseline_tier_key = 'developing'
             AND mean_baseline_level >= 50)
         OR (baseline_tier_key = 'competitive'
             AND (mean_baseline_level < 50
                  OR mean_baseline_level >= 65))
         OR (baseline_tier_key = 'advanced'
             AND (mean_baseline_level < 65
                  OR mean_baseline_level >= 80))
         OR (baseline_tier_key = 'elite'
             AND mean_baseline_level < 80)
        """,
    )
    add_check(
        checks,
        "baseline_tier_bounds_valid",
        bad_baseline_bounds == 0,
        bad_baseline_bounds,
        0,
        "Published baseline-tier school means must remain inside tier bounds.",
    )

    bad_breakout_rates = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM breakout_rate_rankings
        WHERE stabilized_breakout_rate < 0
           OR stabilized_breakout_rate > 1
           OR raw_breakout_rate < 0
           OR raw_breakout_rate > 1
        """,
    )
    add_check(
        checks,
        "breakout_rates_in_bounds",
        bad_breakout_rates == 0,
        bad_breakout_rates,
        0,
        "Breakout rates must be bounded by zero and one.",
    )

    bad_balanced_coverage = scalar(
        connection,
        f"""
        SELECT COUNT(*)
        FROM balanced_program_rankings
        WHERE covered_cell_count < {MIN_BALANCED_CELLS}
           OR covered_cell_count > 12
           OR men_cell_count < {MIN_BALANCED_GENDER_CELLS}
           OR women_cell_count < {MIN_BALANCED_GENDER_CELLS}
        """,
    )
    add_check(
        checks,
        "balanced_program_coverage_valid",
        bad_balanced_coverage == 0,
        bad_balanced_coverage,
        0,
        "Balanced-program coverage must satisfy the frozen 12-cell contract.",
    )

    unexpected_groups = scalar(
        connection,
        f"""
        SELECT COUNT(*)
        FROM (
            SELECT DISTINCT balanced_group_key
            FROM broad_group_gender
        )
        WHERE balanced_group_key NOT IN (
            'sprints',
            'middle_distance',
            'distance',
            'hurdles',
            'jumps',
            'throws'
        )
        """,
    )
    add_check(
        checks,
        "balanced_program_uses_six_groups",
        unexpected_groups == 0,
        unexpected_groups,
        0,
        "Balanced program uses the six cross-gender event groups.",
    )

    fabricated_2020 = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM broad_overall
        WHERE season_year = 2020
          AND season_type = 'outdoor'
        """,
    )
    add_check(
        checks,
        "production_2020_outdoor_not_fabricated",
        fabricated_2020 == 0,
        fabricated_2020,
        0,
        "The known missing 2020 Outdoor broad production season remains absent.",
    )

    transfer_method_count = scalar(
        connection,
        """
        SELECT COUNT(DISTINCT transfer_inference_method)
        FROM transfer_inference_registry
        """,
    )
    add_check(
        checks,
        "single_transfer_inference_method",
        transfer_method_count == 1,
        transfer_method_count,
        1,
        "Inbound transfer rankings use one documented chronology rule.",
    )

    transfer_status_count = scalar(
        connection,
        """
        SELECT COUNT(*)
        FROM transfer_inference_registry
        WHERE publication_status IN (
            'published_provisional',
            'not_publishable_under_frozen_broad_coverage'
        )
        """,
    )
    add_check(
        checks,
        "transfer_publication_status_explicit",
        transfer_status_count == 1,
        transfer_status_count,
        1,
        (
            "Inbound transfer availability must be stated explicitly rather "
            "than forcing a leaderboard from insufficient source coverage."
        ),
    )

    add_check(
        checks,
        "source_database_unchanged",
        source_hash_before == source_hash_after,
        source_hash_after,
        source_hash_before,
        "The frozen Milestone 6 source database remains byte-identical.",
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
        checks,
    )

    return sum(1 for row in checks if row[1] != "PASS")


def create_table_registry(connection: duckdb.DuckDBPyConnection) -> None:
    table_names = [
        "specialized_analysis_registry",
        "school_metadata",
        "development_consistency_rankings",
        "elite_frontier_development_rankings",
        "national_elite_endpoint90_rankings",
        "baseline_tier_rankings",
        "breakout_rate_rankings",
        "balanced_program_rankings",
        "development_efficiency_rankings",
        "ranking_robustness_rankings",
        "inbound_transfer_development_rankings",
        "transfer_inference_registry",
        "specialized_ranking_leaders",
        "hard_checks",
    ]

    connection.execute(
        """
        CREATE TABLE publication_table_registry (
            table_name VARCHAR,
            row_count BIGINT,
            dataset_version VARCHAR,
            phase_version VARCHAR
        )
        """
    )
    rows = []
    for table_name in table_names:
        count = scalar(
            connection,
            f"SELECT COUNT(*) FROM {table_name}",
        )
        rows.append(
            (
                table_name,
                int(count),
                DATASET_VERSION,
                PHASE_VERSION,
            )
        )
    connection.executemany(
        "INSERT INTO publication_table_registry VALUES (?, ?, ?, ?)",
        rows,
    )


def export_tables(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
) -> None:
    export_names = [
        "specialized_analysis_registry",
        "development_consistency_rankings",
        "elite_frontier_development_rankings",
        "national_elite_endpoint90_rankings",
        "baseline_tier_rankings",
        "breakout_rate_rankings",
        "balanced_program_rankings",
        "development_efficiency_rankings",
        "ranking_robustness_rankings",
        "inbound_transfer_development_rankings",
        "transfer_inference_registry",
        "specialized_ranking_leaders",
        "hard_checks",
        "publication_table_registry",
    ]
    for table_name in export_names:
        frame = connection.execute(
            f"SELECT * FROM {table_name}"
        ).df()
        frame.to_csv(output_dir / f"{table_name}.csv", index=False)


def write_report(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
    output_database: Path,
    failed_checks: int,
) -> None:
    leaders = connection.execute(
        """
        SELECT
            analysis_order,
            analysis_label,
            leader_school,
            leader_metric_value,
            metric_label
        FROM specialized_ranking_leaders
        ORDER BY analysis_order
        """
    ).fetchall()

    table_rows = connection.execute(
        """
        SELECT table_name, row_count
        FROM publication_table_registry
        ORDER BY table_name
        """
    ).fetchall()

    lines = [
        "MILESTONE 7 — PHASE 7E.2 EVENT-BALANCED SPECIALIZED RANKINGS",
        "=" * 82,
        f"Dataset version: {DATASET_VERSION}",
        f"Phase version: {PHASE_VERSION}",
        f"Official model: {MODEL_LABEL}",
        f"Output database: {output_database}",
        "",
        "CURRENT LEADERS",
        "-" * 82,
    ]
    for _, label, school, value, metric in leaders:
        lines.append(
            f"{label}: {school} | {metric}={float(value):,.6f}"
        )

    lines.extend(
        [
            "",
            "PUBLICATION TABLES",
            "-" * 82,
        ]
    )
    for table_name, row_count in table_rows:
        lines.append(f"{table_name}: {int(row_count):,}")

    total_checks = int(
        scalar(connection, "SELECT COUNT(*) FROM hard_checks")
    )
    transfer_status = scalar(
        connection,
        """
        SELECT publication_status
        FROM transfer_inference_registry
        """
    )
    transfer_school_count = scalar(
        connection,
        """
        SELECT published_school_count
        FROM transfer_inference_registry
        """
    )

    lines.extend(
        [
            "",
            "HARD GATE",
            "-" * 82,
            f"Total checks: {total_checks}",
            f"Failed checks: {failed_checks}",
            f"PHASE GATE: {'PASS' if failed_checks == 0 else 'FAIL'}",
            "",
            "INBOUND TRANSFER STATUS",
            "-" * 82,
            f"Publication status: {transfer_status}",
            f"Published schools: {int(transfer_school_count)}",
            (
                "No transfer leaderboard is fabricated when the frozen Broad "
                "publication does not contain enough eligible inferred "
                "destination-school coverage."
            ),
            "",
            "INTERPRETATION NOTE",
            "-" * 82,
            (
                "These are Enhanced Balanced Production specialized rankings, "
                "including the Endpoint 90+ publication. They are not "
                "the frozen Milestone 5 Average Development supplemental "
                "rankings, and their leaders may differ."
            ),
        ]
    )

    report = "\n".join(lines) + "\n"
    (output_dir / "phase_7e2_report.txt").write_text(
        report,
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    output_dir = args.output_dir.resolve()
    output_database = output_dir / f"{DATASET_VERSION}.duckdb"

    if not source.exists():
        raise FileNotFoundError(f"Source database not found: {source}")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    source_hash_before = sha256(source)

    connection = duckdb.connect(str(output_database))
    connection.execute(
        f"ATTACH '{source.as_posix()}' AS src (READ_ONLY)"
    )

    create_registry(connection)
    create_source_tables(connection)
    create_consistency(connection)
    create_elite_frontier(connection)
    create_national_elite_endpoint90(connection)
    create_baseline_tiers(connection)
    create_breakout(connection)
    create_balanced_program(connection)
    create_efficiency(connection)
    create_robustness(connection)
    create_inbound_transfer(connection)
    create_leader_summary(connection)

    connection.execute("DETACH src")
    connection.execute("CHECKPOINT")
    source_hash_after = sha256(source)

    failed_checks = create_hard_checks(
        connection,
        source_hash_before,
        source_hash_after,
    )
    create_table_registry(connection)
    export_tables(connection, output_dir)
    write_report(
        connection,
        output_dir,
        output_database,
        failed_checks,
    )

    leader_rows = connection.execute(
        """
        SELECT analysis_label, leader_school
        FROM specialized_ranking_leaders
        ORDER BY analysis_order
        """
    ).fetchall()

    transfer_status = scalar(
        connection,
        "SELECT publication_status FROM transfer_inference_registry",
    )

    row_counts = {
        table_name: int(
            scalar(connection, f"SELECT COUNT(*) FROM {table_name}")
        )
        for table_name in [
            "development_consistency_rankings",
            "elite_frontier_development_rankings",
            "national_elite_endpoint90_rankings",
            "baseline_tier_rankings",
            "breakout_rate_rankings",
            "balanced_program_rankings",
            "development_efficiency_rankings",
            "ranking_robustness_rankings",
            "inbound_transfer_development_rankings",
        ]
    }

    connection.close()

    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Phase version: {PHASE_VERSION}")
    print("Publication mode: enhanced_primary_only")
    print(f"Official primary: {MODEL_LABEL}")
    print(f"Source database: {source}")
    print(f"Output database: {output_database}")
    for table_name, count in row_counts.items():
        print(f"{table_name}: {count:,}")
    print("Current leaders:")
    for label, school in leader_rows:
        print(f"  {label}: {school}")
    print(f"Inbound transfer status: {transfer_status}")
    print(f"Failed checks: {failed_checks}")
    print()
    print(f"PHASE GATE: {'PASS' if failed_checks == 0 else 'FAIL'}")
    if failed_checks == 0:
        print(
            "Phase 7E.2 Event-Balanced specialized rankings published."
        )

    return 0 if failed_checks == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
