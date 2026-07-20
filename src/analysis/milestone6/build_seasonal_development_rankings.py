#!/usr/bin/env python3
"""
Milestone 6 Phase 6A — Season-by-Season Development Rankings

Builds NCAA Division I athlete-development rankings for every available
indoor and outdoor endpoint season in the frozen Milestone 5 value-added
trajectory dataset.

Season interpretation
---------------------
A ranking such as "2025 Indoor" includes athlete-development trajectories
whose endpoint stable period is the 2025 indoor season. The score therefore
represents development realized by that endpoint season. It is not presented
as a randomized causal estimate of coaching quality or as a strict
single-calendar-year change.

Published scopes
----------------
1. Combined-gender overall rankings by endpoint season.
2. Men's and women's overall rankings by endpoint season.
3. Gender-specific individual-event rankings by endpoint season.
4. Combined-gender individual-event rankings by endpoint season.
5. Gender-specific event-group rankings by endpoint season.
6. Combined-gender event-group rankings by endpoint season.

Publication safeguards
----------------------
- Scores include a season-centered value for cross-season display.
- Partitions with no detectable between-school variance receive no
  official rank or leader.

Weighting
---------
- Overall: trajectories are averaged within athlete-school-event-family,
  then event families are averaged so each athlete-school-season contributes
  one total vote.
- Individual event: one vote per athlete-school-gender-season-event.
- Event group: event contributions are averaged within athlete-school-group,
  so a multi-event athlete contributes one total group vote.
- Transfers may contribute once to each distinct school.
- Multiple analytical stints at the same school and endpoint season are
  consolidated.

Ranking model
-------------
The ranking engine matches Milestone 5:
- stabilized within-school variance with a 20-degree-of-freedom prior;
- method-of-moments between-school variance;
- empirical-Bayes posterior school scores;
- 95% posterior intervals;
- sample thresholds and at least five eligible schools per partition.

Generated databases and CSVs remain local under data/processed and should
remain excluded from Git.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


ROOT = Path.cwd()

TRAJECTORY_DB = (
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

PUBLICATION_DB = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5i_publication_freeze/"
      "ncaa_d1_athlete_development_rankings_v1.duckdb"
)
PHASE_5I_CHECKS = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5i_publication_freeze/"
      "hard_checks.csv"
)

EVENT_DB = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5j_event_and_group_rankings/"
      "ncaa_d1_event_development_rankings_v1.duckdb"
)
PHASE_5J_CHECKS = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5j_event_and_group_rankings/"
      "hard_checks.csv"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "seasonal_development_rankings_v1/"
      "phase_6a_seasonal_rankings"
)
OUTPUT_DB = OUTPUT_DIR / "seasonal_development_rankings_v1.duckdb"

INPUT_TRAJECTORY_VERSION = "expected_improvement_policy_v1_1"
INPUT_PUBLICATION_VERSION = "ncaa_d1_athlete_development_rankings_v1"
INPUT_EVENT_VERSION = "ncaa_d1_event_development_rankings_v1_1"

DATASET_VERSION = "seasonal_development_rankings_v1_1"
POLICY_VERSION = "seasonal_development_rankings_policy_v1_1"

EXPECTED_TRAJECTORY_ROWS = 189_703
EXPECTED_SCHOOLS = 361
EXPECTED_EVENTS = 30
EXPECTED_GROUPS = 10

VARIANCE_PRIOR_DF = 20.0
CI_Z = 1.96
MIN_ELIGIBLE_SCHOOLS_PER_PARTITION = 5

COMBINED_OVERALL_MIN_SAMPLE = 15
GENDER_OVERALL_MIN_SAMPLE = 10
GENDER_EVENT_MIN_SAMPLE = 5
COMBINED_EVENT_MIN_SAMPLE = 8
GENDER_CORE_GROUP_MIN_SAMPLE = 8
GENDER_SPECIAL_GROUP_MIN_SAMPLE = 5
COMBINED_CORE_GROUP_MIN_SAMPLE = 12
COMBINED_SPECIAL_GROUP_MIN_SAMPLE = 8

SPECIAL_GROUPS = {
    "combined_events",
    "steeplechase",
    "race_walks",
    "special_events",
}

FORMULA_TOLERANCE = 1e-10
MIN_BETWEEN_SCHOOL_VARIANCE = 1e-12


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


def export_query(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    path: Path,
) -> int:
    rows = fetch_dicts(connection, sql)
    fieldnames = list(rows[0].keys()) if rows else []
    write_csv(path, rows, fieldnames)
    return len(rows)


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


def failed_checks(path: Path) -> list[str]:
    return [
        row.get("check_name", "")
        for row in read_csv(path)
        if row.get("status") != "PASS"
    ]


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    print("MILESTONE 6 PHASE 6A — SEASON-BY-SEASON DEVELOPMENT RANKINGS")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Output database: {OUTPUT_DB}")

    required_inputs = [
        TRAJECTORY_DB,
        PHASE_5E_CHECKS,
        PUBLICATION_DB,
        PHASE_5I_CHECKS,
        EVENT_DB,
        PHASE_5J_CHECKS,
    ]
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
        print("PHASE GATE: FAIL — Required input missing.")
        return 1

    for phase_name, check_path in [
        ("phase_5e", PHASE_5E_CHECKS),
        ("phase_5i", PHASE_5I_CHECKS),
        ("phase_5j", PHASE_5J_CHECKS),
    ]:
        failures = failed_checks(check_path)
        add_check(
            checks,
            f"{phase_name}_gate_passed",
            not failures,
            failures,
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

        for alias, path in [
            ("trajectory_source", TRAJECTORY_DB),
            ("publication_source", PUBLICATION_DB),
            ("event_source", EVENT_DB),
        ]:
            con.execute(
                f"""
                ATTACH '{sql_path(path)}'
                    AS {alias} (READ_ONLY)
                """
            )

        trajectory_metadata = dict(
            con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM trajectory_source.main.dataset_metadata
                """
            ).fetchall()
        )
        publication_metadata = dict(
            con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM publication_source.main.dataset_metadata
                """
            ).fetchall()
        )
        event_metadata = dict(
            con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM event_source.main.dataset_metadata
                """
            ).fetchall()
        )

        for name, observed, expected in [
            (
                "trajectory_version_matches",
                trajectory_metadata.get("dataset_version"),
                INPUT_TRAJECTORY_VERSION,
            ),
            (
                "publication_version_matches",
                publication_metadata.get("dataset_version"),
                INPUT_PUBLICATION_VERSION,
            ),
            (
                "event_version_matches",
                event_metadata.get("dataset_version"),
                INPUT_EVENT_VERSION,
            ),
        ]:
            add_check(
                checks,
                name,
                observed == expected,
                observed,
                expected,
            )

        con.execute(
            """
            CREATE TABLE school_metadata AS
            SELECT *
            FROM publication_source.main.ranking_school_metadata
            """
        )

        con.execute(
            """
            CREATE TABLE event_taxonomy AS
            SELECT *
            FROM event_source.main.event_taxonomy
            """
        )

        con.execute(
            """
            CREATE TABLE event_group_membership AS
            SELECT *
            FROM event_source.main.event_group_membership
            """
        )

        con.execute(
            """
            CREATE TABLE trajectory_snapshot AS
            SELECT *
            FROM
                trajectory_source.main.expected_improvement_scored_trajectories
            WHERE endpoint_season_year IS NOT NULL
              AND LOWER(season_type) IN ('indoor', 'outdoor')
            """
        )

        con.execute(
            f"""
            CREATE TABLE season_registry AS
            SELECT
                endpoint_season_year AS season_year,
                LOWER(season_type) AS season_type,
                endpoint_season_year::VARCHAR
                    || '_'
                    || LOWER(season_type) AS season_key,
                endpoint_season_year::VARCHAR
                    || ' '
                    || CASE
                        WHEN LOWER(season_type) = 'indoor'
                            THEN 'Indoor'
                        ELSE 'Outdoor'
                    END AS season_label,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT canonical_person_id)
                    AS distinct_athlete_count,
                COUNT(DISTINCT resolved_school_id)
                    AS represented_school_count,
                MIN(baseline_season_year)
                    AS earliest_baseline_year,
                MAX(endpoint_season_year)
                    AS latest_endpoint_year,
                '{DATASET_VERSION}' AS dataset_version
            FROM trajectory_snapshot
            GROUP BY
                endpoint_season_year,
                LOWER(season_type)
            """
        )

        # ------------------------------------------------------------------
        # Equal-family, equal-athlete seasonal overall units
        # ------------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE season_athlete_family_contributions AS
            SELECT
                endpoint_season_year AS season_year,
                LOWER(season_type) AS season_type,
                canonical_person_id,
                ANY_VALUE(athlete_id) AS athlete_id,
                ANY_VALUE(athlete_name) AS athlete_name,
                resolved_school_id,
                canonical_gender_code,
                event_family,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT canonical_event_code) AS event_count,
                AVG(observed_improvement)
                    AS family_mean_observed_improvement,
                AVG(expected_improvement)
                    AS family_mean_expected_improvement,
                AVG(athlete_value_added)
                    AS family_mean_value_added,
                AVG(annualized_athlete_value_added)
                    AS family_mean_annualized_value_added,
                MIN(training_support_n)
                    AS minimum_training_support
            FROM trajectory_snapshot
            GROUP BY
                endpoint_season_year,
                LOWER(season_type),
                canonical_person_id,
                resolved_school_id,
                canonical_gender_code,
                event_family
            """
        )

        con.execute(
            f"""
            CREATE TABLE season_athlete_contributions AS
            SELECT
                'sath_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        season_year,
                        season_type,
                        canonical_person_id,
                        resolved_school_id,
                        canonical_gender_code
                    )
                ) AS season_athlete_contribution_id,
                season_year,
                season_type,
                season_year::VARCHAR
                    || '_'
                    || season_type AS season_key,
                season_year::VARCHAR
                    || ' '
                    || CASE
                        WHEN season_type = 'indoor'
                            THEN 'Indoor'
                        ELSE 'Outdoor'
                    END AS season_label,
                canonical_person_id,
                ANY_VALUE(athlete_id) AS athlete_id,
                ANY_VALUE(athlete_name) AS athlete_name,
                resolved_school_id,
                canonical_gender_code,
                COUNT(*) AS event_family_count,
                SUM(event_count) AS event_count,
                SUM(trajectory_count) AS trajectory_count,
                AVG(family_mean_observed_improvement)
                    AS equal_family_observed_improvement,
                AVG(family_mean_expected_improvement)
                    AS equal_family_expected_improvement,
                AVG(family_mean_value_added)
                    AS season_athlete_value_added,
                AVG(family_mean_annualized_value_added)
                    AS season_athlete_annualized_value_added,
                MIN(minimum_training_support)
                    AS minimum_training_support,
                '{DATASET_VERSION}' AS dataset_version
            FROM season_athlete_family_contributions
            GROUP BY
                season_year,
                season_type,
                canonical_person_id,
                resolved_school_id,
                canonical_gender_code
            """
        )

        # ------------------------------------------------------------------
        # Seasonal individual-event and group units
        # ------------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE season_athlete_event_contributions AS
            SELECT
                'sevt_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        t.endpoint_season_year,
                        LOWER(t.season_type),
                        t.canonical_person_id,
                        t.resolved_school_id,
                        t.canonical_gender_code,
                        t.canonical_event_code
                    )
                ) AS season_athlete_event_contribution_id,
                t.endpoint_season_year AS season_year,
                LOWER(t.season_type) AS season_type,
                t.endpoint_season_year::VARCHAR
                    || '_'
                    || LOWER(t.season_type) AS season_key,
                t.endpoint_season_year::VARCHAR
                    || ' '
                    || CASE
                        WHEN LOWER(t.season_type) = 'indoor'
                            THEN 'Indoor'
                        ELSE 'Outdoor'
                    END AS season_label,
                t.canonical_person_id,
                ANY_VALUE(t.athlete_id) AS athlete_id,
                ANY_VALUE(t.athlete_name) AS athlete_name,
                t.resolved_school_id,
                t.canonical_gender_code,
                t.canonical_event_code,
                ANY_VALUE(t.canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(t.event_family) AS event_family,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT t.school_stint_id)
                    AS school_stint_count,
                AVG(t.observed_improvement)
                    AS mean_observed_improvement,
                AVG(t.expected_improvement)
                    AS mean_expected_improvement,
                AVG(t.athlete_value_added)
                    AS season_athlete_event_value_added,
                AVG(t.annualized_athlete_value_added)
                    AS season_athlete_event_annualized_value_added,
                MIN(t.training_support_n)
                    AS minimum_training_support,
                '{DATASET_VERSION}' AS dataset_version
            FROM trajectory_snapshot t
            JOIN event_taxonomy x
              USING (canonical_event_code)
            WHERE x.taxonomy_publishable
            GROUP BY
                t.endpoint_season_year,
                LOWER(t.season_type),
                t.canonical_person_id,
                t.resolved_school_id,
                t.canonical_gender_code,
                t.canonical_event_code
            """
        )

        con.execute(
            f"""
            CREATE TABLE season_athlete_group_contributions AS
            SELECT
                'sgrp_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        e.season_year,
                        e.season_type,
                        e.canonical_person_id,
                        e.resolved_school_id,
                        e.canonical_gender_code,
                        g.event_group
                    )
                ) AS season_athlete_group_contribution_id,
                e.season_year,
                e.season_type,
                e.season_key,
                e.season_label,
                e.canonical_person_id,
                ANY_VALUE(e.athlete_id) AS athlete_id,
                ANY_VALUE(e.athlete_name) AS athlete_name,
                e.resolved_school_id,
                e.canonical_gender_code,
                g.event_group,
                ANY_VALUE(g.event_group_label)
                    AS event_group_label,
                ANY_VALUE(g.group_level) AS group_level,
                COUNT(*) AS event_count,
                SUM(e.trajectory_count) AS trajectory_count,
                AVG(e.mean_observed_improvement)
                    AS equal_event_observed_improvement,
                AVG(e.mean_expected_improvement)
                    AS equal_event_expected_improvement,
                AVG(e.season_athlete_event_value_added)
                    AS season_athlete_group_value_added,
                AVG(
                    e.season_athlete_event_annualized_value_added
                ) AS season_athlete_group_annualized_value_added,
                MIN(e.minimum_training_support)
                    AS minimum_training_support,
                '{DATASET_VERSION}' AS dataset_version
            FROM season_athlete_event_contributions e
            JOIN event_group_membership g
              USING (canonical_event_code)
            GROUP BY
                e.season_year,
                e.season_type,
                e.season_key,
                e.season_label,
                e.canonical_person_id,
                e.resolved_school_id,
                e.canonical_gender_code,
                g.event_group
            """
        )

        special_group_sql = ", ".join(
            f"'{group}'" for group in sorted(SPECIAL_GROUPS)
        )

        # ------------------------------------------------------------------
        # Unified ranking input
        # ------------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE ranking_input_units AS
            SELECT
                'season_overall_combined' AS ranking_scope,
                season_year,
                season_type,
                season_key,
                season_label,
                'all' AS gender_scope,
                'overall' AS ranking_key,
                'Overall' AS ranking_label,
                'overall' AS ranking_category,
                resolved_school_id,
                canonical_person_id,
                season_athlete_contribution_id AS contribution_id,
                season_athlete_value_added AS score_value,
                {COMBINED_OVERALL_MIN_SAMPLE} AS minimum_sample,
                minimum_training_support
            FROM season_athlete_contributions

            UNION ALL

            SELECT
                'season_overall_gender',
                season_year,
                season_type,
                season_key,
                season_label,
                canonical_gender_code,
                'overall',
                CASE
                    WHEN canonical_gender_code = 'm'
                        THEN 'Men Overall'
                    WHEN canonical_gender_code = 'f'
                        THEN 'Women Overall'
                    ELSE 'Other Gender Overall'
                END,
                'overall',
                resolved_school_id,
                canonical_person_id,
                season_athlete_contribution_id,
                season_athlete_value_added,
                {GENDER_OVERALL_MIN_SAMPLE},
                minimum_training_support
            FROM season_athlete_contributions

            UNION ALL

            SELECT
                'season_event_gender',
                season_year,
                season_type,
                season_key,
                season_label,
                canonical_gender_code,
                canonical_event_code,
                canonical_event_name,
                'individual_event',
                resolved_school_id,
                canonical_person_id,
                season_athlete_event_contribution_id,
                season_athlete_event_value_added,
                {GENDER_EVENT_MIN_SAMPLE},
                minimum_training_support
            FROM season_athlete_event_contributions

            UNION ALL

            SELECT
                'season_event_combined',
                season_year,
                season_type,
                season_key,
                season_label,
                'all',
                canonical_event_code,
                canonical_event_name,
                'individual_event',
                resolved_school_id,
                canonical_person_id,
                season_athlete_event_contribution_id,
                season_athlete_event_value_added,
                {COMBINED_EVENT_MIN_SAMPLE},
                minimum_training_support
            FROM season_athlete_event_contributions

            UNION ALL

            SELECT
                'season_group_gender',
                season_year,
                season_type,
                season_key,
                season_label,
                canonical_gender_code,
                event_group,
                event_group_label,
                'event_group',
                resolved_school_id,
                canonical_person_id,
                season_athlete_group_contribution_id,
                season_athlete_group_value_added,
                CASE
                    WHEN event_group IN ({special_group_sql})
                        THEN {GENDER_SPECIAL_GROUP_MIN_SAMPLE}
                    ELSE {GENDER_CORE_GROUP_MIN_SAMPLE}
                END,
                minimum_training_support
            FROM season_athlete_group_contributions

            UNION ALL

            SELECT
                'season_group_combined',
                season_year,
                season_type,
                season_key,
                season_label,
                'all',
                event_group,
                event_group_label,
                'event_group',
                resolved_school_id,
                canonical_person_id,
                season_athlete_group_contribution_id,
                season_athlete_group_value_added,
                CASE
                    WHEN event_group IN ({special_group_sql})
                        THEN {COMBINED_SPECIAL_GROUP_MIN_SAMPLE}
                    ELSE {COMBINED_CORE_GROUP_MIN_SAMPLE}
                END,
                minimum_training_support
            FROM season_athlete_group_contributions
            """
        )

        # ------------------------------------------------------------------
        # Empirical-Bayes ranking engine
        # ------------------------------------------------------------------
        partition_columns = """
            ranking_scope,
            season_year,
            season_type,
            gender_scope,
            ranking_key
        """

        con.execute(
            f"""
            CREATE TABLE ranking_school_base AS
            SELECT
                {partition_columns},
                ANY_VALUE(season_key) AS season_key,
                ANY_VALUE(season_label) AS season_label,
                ANY_VALUE(ranking_label) AS ranking_label,
                ANY_VALUE(ranking_category) AS ranking_category,
                ANY_VALUE(minimum_sample) AS minimum_sample,
                resolved_school_id,
                COUNT(*) AS athlete_unit_count,
                COUNT(DISTINCT canonical_person_id)
                    AS distinct_athlete_count,
                AVG(score_value) AS raw_school_score,
                MEDIAN(score_value) AS median_athlete_score,
                VAR_SAMP(score_value) AS raw_within_school_variance,
                STDDEV_SAMP(score_value) AS raw_within_school_sd,
                AVG(CAST(score_value > 0 AS DOUBLE))
                    AS above_expected_athlete_share,
                MIN(minimum_training_support)
                    AS minimum_training_support
            FROM ranking_input_units
            GROUP BY
                {partition_columns},
                resolved_school_id
            """
        )

        con.execute(
            f"""
            CREATE TABLE ranking_global_prior AS
            WITH globals AS (
                SELECT
                    {partition_columns},
                    AVG(score_value) AS global_athlete_mean,
                    VAR_SAMP(score_value) AS global_athlete_variance,
                    COUNT(*) AS total_athlete_units
                FROM ranking_input_units
                GROUP BY {partition_columns}
            ),
            pooled AS (
                SELECT
                    {partition_columns},
                    SUM(
                        (athlete_unit_count - 1)
                        * COALESCE(raw_within_school_variance, 0)
                    )
                    / NULLIF(
                        SUM(athlete_unit_count - 1),
                        0
                    ) AS pooled_within_school_variance
                FROM ranking_school_base
                GROUP BY {partition_columns}
            )
            SELECT *
            FROM globals
            JOIN pooled
              USING (
                ranking_scope,
                season_year,
                season_type,
                gender_scope,
                ranking_key
              )
            """
        )

        con.execute(
            f"""
            CREATE TABLE ranking_school_stabilized AS
            SELECT
                b.*,
                p.global_athlete_mean,
                p.global_athlete_variance,
                COALESCE(
                    p.pooled_within_school_variance,
                    p.global_athlete_variance,
                    0.0
                ) AS pooled_within_school_variance,
                (
                    (
                        (b.athlete_unit_count - 1)
                        * COALESCE(
                            b.raw_within_school_variance,
                            p.pooled_within_school_variance,
                            p.global_athlete_variance,
                            0.0
                        )
                    )
                    + {VARIANCE_PRIOR_DF}
                        * COALESCE(
                            p.pooled_within_school_variance,
                            p.global_athlete_variance,
                            0.0
                        )
                )
                / (
                    b.athlete_unit_count - 1
                    + {VARIANCE_PRIOR_DF}
                ) AS stabilized_within_school_variance,
                (
                    (
                        (
                            (b.athlete_unit_count - 1)
                            * COALESCE(
                                b.raw_within_school_variance,
                                p.pooled_within_school_variance,
                                p.global_athlete_variance,
                                0.0
                            )
                        )
                        + {VARIANCE_PRIOR_DF}
                            * COALESCE(
                                p.pooled_within_school_variance,
                                p.global_athlete_variance,
                                0.0
                            )
                    )
                    / (
                        b.athlete_unit_count - 1
                        + {VARIANCE_PRIOR_DF}
                    )
                )
                / b.athlete_unit_count
                    AS stabilized_sampling_variance
            FROM ranking_school_base b
            JOIN ranking_global_prior p
              USING (
                ranking_scope,
                season_year,
                season_type,
                gender_scope,
                ranking_key
              )
            """
        )

        con.execute(
            f"""
            CREATE TABLE ranking_between_school_variance AS
            SELECT
                {partition_columns},
                GREATEST(
                    0.0,
                    VAR_SAMP(raw_school_score)
                    - AVG(stabilized_sampling_variance)
                ) AS between_school_variance,
                VAR_SAMP(raw_school_score)
                    AS observed_school_mean_variance,
                AVG(stabilized_sampling_variance)
                    AS mean_sampling_variance,
                COUNT(*) AS represented_school_count
            FROM ranking_school_stabilized
            GROUP BY {partition_columns}
            """
        )

        con.execute(
            f"""
            CREATE TABLE seasonal_rankings AS
            WITH posterior AS (
                SELECT
                    s.*,
                    t.between_school_variance,
                    t.observed_school_mean_variance,
                    t.mean_sampling_variance,
                    t.represented_school_count,
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
                    s.athlete_unit_count >= s.minimum_sample
                        AS sample_eligible
                FROM ranking_school_stabilized s
                JOIN ranking_between_school_variance t
                  USING (
                    ranking_scope,
                    season_year,
                    season_type,
                    gender_scope,
                    ranking_key
                  )
            ),
            intervals AS (
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
                            ranking_scope,
                            season_year,
                            season_type,
                            gender_scope,
                            ranking_key
                        ORDER BY posterior_school_score DESC
                    ) AS all_school_rank
                FROM posterior
            ),
            partition_counts AS (
                SELECT
                    ranking_scope,
                    season_year,
                    season_type,
                    gender_scope,
                    ranking_key,
                    COUNT(*) FILTER (
                        WHERE sample_eligible
                    ) AS sample_eligible_school_count
                FROM intervals
                GROUP BY
                    ranking_scope,
                    season_year,
                    season_type,
                    gender_scope,
                    ranking_key
            ),
            official AS (
                SELECT
                    i.ranking_scope,
                    i.season_year,
                    i.season_type,
                    i.gender_scope,
                    i.ranking_key,
                    i.resolved_school_id,
                    RANK() OVER (
                        PARTITION BY
                            i.ranking_scope,
                            i.season_year,
                            i.season_type,
                            i.gender_scope,
                            i.ranking_key
                        ORDER BY i.posterior_school_score DESC
                    ) AS official_rank,
                    COUNT(*) OVER (
                        PARTITION BY
                            i.ranking_scope,
                            i.season_year,
                            i.season_type,
                            i.gender_scope,
                            i.ranking_key
                    ) AS official_ranked_school_count
                FROM intervals i
                JOIN partition_counts c
                  USING (
                    ranking_scope,
                    season_year,
                    season_type,
                    gender_scope,
                    ranking_key
                  )
                WHERE i.sample_eligible
                  AND c.sample_eligible_school_count
                        >= {MIN_ELIGIBLE_SCHOOLS_PER_PARTITION}
                  AND i.between_school_variance
                        > {MIN_BETWEEN_SCHOOL_VARIANCE}
            )
            SELECT
                i.*,
                c.sample_eligible_school_count,
                (
                    c.sample_eligible_school_count
                        >= {MIN_ELIGIBLE_SCHOOLS_PER_PARTITION}
                    AND i.between_school_variance
                        > {MIN_BETWEEN_SCHOOL_VARIANCE}
                ) AS partition_publishable,
                (
                    i.sample_eligible
                    AND c.sample_eligible_school_count
                        >= {MIN_ELIGIBLE_SCHOOLS_PER_PARTITION}
                    AND i.between_school_variance
                        > {MIN_BETWEEN_SCHOOL_VARIANCE}
                ) AS official_rank_eligible,
                i.posterior_school_score
                    - i.global_athlete_mean
                    AS season_centered_posterior_score,
                o.official_rank,
                o.official_ranked_school_count,
                m.school_name,
                m.state_code,
                m.city,
                m.conference_name,
                m.division_name,
                CASE
                    WHEN i.between_school_variance
                            <= {MIN_BETWEEN_SCHOOL_VARIANCE}
                        THEN 'no_detectable_separation'
                    WHEN NOT (
                        i.sample_eligible
                        AND c.sample_eligible_school_count
                            >= {MIN_ELIGIBLE_SCHOOLS_PER_PARTITION}
                    )
                        THEN 'insufficient_data'
                    WHEN i.posterior_ci95_lower > 0
                        THEN 'credible_above_expected'
                    WHEN i.posterior_ci95_upper < 0
                        THEN 'credible_below_expected'
                    ELSE 'not_distinguishable_from_expected'
                END AS evidence_category,
                CASE
                    WHEN i.between_school_variance
                            <= {MIN_BETWEEN_SCHOOL_VARIANCE}
                        THEN 'no_detectable_between_school_variance'
                    ELSE 'estimated_between_school_variance'
                END AS variance_status,
                '{DATASET_VERSION}' AS dataset_version
            FROM intervals i
            JOIN partition_counts c
              USING (
                ranking_scope,
                season_year,
                season_type,
                gender_scope,
                ranking_key
              )
            JOIN school_metadata m
              USING (resolved_school_id)
            LEFT JOIN official o
              USING (
                ranking_scope,
                season_year,
                season_type,
                gender_scope,
                ranking_key,
                resolved_school_id
              )
            """
        )

        # ------------------------------------------------------------------
        # Scope summaries and validation
        # ------------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE season_partition_summary AS
            SELECT
                ranking_scope,
                season_year,
                season_type,
                ANY_VALUE(season_key) AS season_key,
                ANY_VALUE(season_label) AS season_label,
                gender_scope,
                ranking_key,
                ANY_VALUE(ranking_label) AS ranking_label,
                ANY_VALUE(ranking_category) AS ranking_category,
                ANY_VALUE(minimum_sample) AS minimum_sample,
                COUNT(*) AS represented_school_count,
                COUNT(*) FILTER (
                    WHERE sample_eligible
                ) AS sample_eligible_school_count,
                COUNT(*) FILTER (
                    WHERE official_rank_eligible
                ) AS officially_ranked_school_count,
                SUM(athlete_unit_count) AS athlete_unit_count,
                MIN(athlete_unit_count) AS minimum_school_sample,
                MAX(athlete_unit_count) AS maximum_school_sample,
                ANY_VALUE(between_school_variance)
                    AS between_school_variance,
                COUNT(*) FILTER (
                    WHERE evidence_category
                        = 'credible_above_expected'
                ) AS credible_above_expected_school_count,
                COUNT(*) FILTER (
                    WHERE evidence_category
                        = 'credible_below_expected'
                ) AS credible_below_expected_school_count
            FROM seasonal_rankings
            GROUP BY
                ranking_scope,
                season_year,
                season_type,
                gender_scope,
                ranking_key
            """
        )

        counts = fetch_dicts(
            con,
            """
            SELECT
                (SELECT COUNT(*) FROM trajectory_snapshot)
                    AS trajectory_rows,
                (SELECT COUNT(*) FROM school_metadata)
                    AS school_rows,
                (SELECT COUNT(*) FROM event_taxonomy)
                    AS event_rows,
                (SELECT COUNT(DISTINCT event_group)
                 FROM event_group_membership)
                    AS group_rows,
                (SELECT COUNT(*) FROM season_registry)
                    AS season_count,
                (SELECT MIN(season_year) FROM season_registry)
                    AS earliest_season_year,
                (SELECT MAX(season_year) FROM season_registry)
                    AS latest_season_year,
                (SELECT COUNT(*) FROM season_athlete_contributions)
                    AS season_athlete_rows,
                (SELECT COUNT(*)
                 FROM season_athlete_event_contributions)
                    AS season_event_rows,
                (SELECT COUNT(*)
                 FROM season_athlete_group_contributions)
                    AS season_group_rows,
                (SELECT COUNT(*) FROM seasonal_rankings)
                    AS ranking_rows,
                (SELECT COUNT(*)
                 FROM seasonal_rankings
                 WHERE official_rank_eligible)
                    AS official_ranking_rows,
                (SELECT COUNT(DISTINCT
                    season_year::VARCHAR || '_' || season_type)
                 FROM seasonal_rankings
                 WHERE ranking_scope = 'season_overall_combined'
                   AND partition_publishable)
                    AS publishable_overall_seasons,
                (SELECT COUNT(DISTINCT season_type)
                 FROM season_registry)
                    AS season_type_count
            """
        )[0]

        quality = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        season_athlete_contribution_id,
                        COUNT(*) AS row_count
                    FROM season_athlete_contributions
                    GROUP BY season_athlete_contribution_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_overall_unit_ids,
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        season_athlete_event_contribution_id,
                        COUNT(*) AS row_count
                    FROM season_athlete_event_contributions
                    GROUP BY season_athlete_event_contribution_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_event_unit_ids,
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        season_athlete_group_contribution_id,
                        COUNT(*) AS row_count
                    FROM season_athlete_group_contributions
                    GROUP BY season_athlete_group_contribution_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_group_unit_ids,
                (SELECT COUNT(*)
                 FROM seasonal_rankings
                 WHERE posterior_school_score IS NULL
                    OR posterior_standard_error IS NULL
                    OR posterior_ci95_lower > posterior_ci95_upper
                    OR shrinkage_weight < 0
                    OR shrinkage_weight > 1)
                    AS invalid_ranking_rows,
                (SELECT COUNT(*)
                 FROM seasonal_rankings
                 WHERE posterior_school_score
                    < LEAST(raw_school_score, global_athlete_mean)
                        - {FORMULA_TOLERANCE}
                    OR posterior_school_score
                    > GREATEST(raw_school_score, global_athlete_mean)
                        + {FORMULA_TOLERANCE})
                    AS nonconvex_posterior_rows,
                (SELECT COUNT(*)
                 FROM seasonal_rankings
                 WHERE official_rank_eligible
                   AND (
                        NOT sample_eligible
                        OR sample_eligible_school_count
                            < {MIN_ELIGIBLE_SCHOOLS_PER_PARTITION}
                        OR between_school_variance
                            <= {MIN_BETWEEN_SCHOOL_VARIANCE}
                        OR official_rank IS NULL
                   ))
                    AS official_eligibility_mismatch_rows,
                (SELECT COUNT(*)
                 FROM seasonal_rankings
                 WHERE between_school_variance
                            <= {MIN_BETWEEN_SCHOOL_VARIANCE}
                   AND official_rank IS NOT NULL)
                    AS zero_variance_official_rank_rows,
                (SELECT COUNT(*)
                 FROM school_metadata
                 WHERE metadata_match_status <> 'matched')
                    AS unmatched_school_metadata_rows,
                (SELECT COUNT(*)
                 FROM trajectory_snapshot
                 WHERE LOWER(season_type)
                    NOT IN ('indoor', 'outdoor'))
                    AS invalid_season_type_rows
            """
        )[0]

        for name, observed, expected in [
            (
                "trajectory_row_count",
                counts["trajectory_rows"],
                EXPECTED_TRAJECTORY_ROWS,
            ),
            (
                "school_metadata_row_count",
                counts["school_rows"],
                EXPECTED_SCHOOLS,
            ),
            (
                "event_taxonomy_count",
                counts["event_rows"],
                EXPECTED_EVENTS,
            ),
            (
                "event_group_count",
                counts["group_rows"],
                EXPECTED_GROUPS,
            ),
            (
                "season_type_count",
                counts["season_type_count"],
                2,
            ),
        ]:
            add_check(
                checks,
                name,
                observed == expected,
                observed,
                expected,
            )

        add_check(
            checks,
            "season_registry_exists",
            counts["season_count"] > 0,
            counts["season_count"],
            "greater than 0",
        )
        add_check(
            checks,
            "seasonal_contribution_units_exist",
            (
                counts["season_athlete_rows"] > 0
                and counts["season_event_rows"] > 0
                and counts["season_group_rows"] > 0
            ),
            {
                "overall": counts["season_athlete_rows"],
                "event": counts["season_event_rows"],
                "group": counts["season_group_rows"],
            },
            "all greater than 0",
        )
        add_check(
            checks,
            "seasonal_rankings_exist",
            counts["ranking_rows"] > 0
            and counts["official_ranking_rows"] > 0,
            {
                "all_rows": counts["ranking_rows"],
                "official_rows": counts["official_ranking_rows"],
            },
            "both greater than 0",
        )
        add_check(
            checks,
            "publishable_overall_seasons_exist",
            counts["publishable_overall_seasons"] > 0,
            counts["publishable_overall_seasons"],
            "greater than 0",
        )

        for name, field in [
            ("overall_unit_ids_unique", "duplicate_overall_unit_ids"),
            ("event_unit_ids_unique", "duplicate_event_unit_ids"),
            ("group_unit_ids_unique", "duplicate_group_unit_ids"),
            ("ranking_rows_valid", "invalid_ranking_rows"),
            ("posterior_scores_are_convex", "nonconvex_posterior_rows"),
            (
                "official_eligibility_reconciles",
                "official_eligibility_mismatch_rows",
            ),
            (
                "zero_variance_partitions_have_no_official_ranks",
                "zero_variance_official_rank_rows",
            ),
            (
                "school_metadata_fully_matched",
                "unmatched_school_metadata_rows",
            ),
            ("season_types_valid", "invalid_season_type_rows"),
        ]:
            add_check(
                checks,
                name,
                quality[field] == 0,
                quality[field],
                0,
            )

        # ------------------------------------------------------------------
        # Exports
        # ------------------------------------------------------------------
        export_query(
            con,
            """
            SELECT *
            FROM season_registry
            ORDER BY season_year, season_type
            """,
            OUTPUT_DIR / "season_coverage_summary.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM seasonal_rankings
            WHERE ranking_scope = 'season_overall_combined'
            ORDER BY
                season_year,
                season_type,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "season_overall_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM seasonal_rankings
            WHERE ranking_scope = 'season_overall_gender'
            ORDER BY
                season_year,
                season_type,
                gender_scope,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "season_gender_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM seasonal_rankings
            WHERE ranking_scope = 'season_event_gender'
            ORDER BY
                season_year,
                season_type,
                gender_scope,
                ranking_label,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "season_individual_event_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM seasonal_rankings
            WHERE ranking_scope = 'season_event_combined'
            ORDER BY
                season_year,
                season_type,
                ranking_label,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR
            / "season_combined_gender_event_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM seasonal_rankings
            WHERE ranking_scope = 'season_group_gender'
            ORDER BY
                season_year,
                season_type,
                gender_scope,
                ranking_label,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "season_event_group_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM seasonal_rankings
            WHERE ranking_scope = 'season_group_combined'
            ORDER BY
                season_year,
                season_type,
                ranking_label,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR
            / "season_combined_gender_group_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM season_partition_summary
            ORDER BY
                season_year,
                season_type,
                ranking_scope,
                gender_scope,
                ranking_label
            """,
            OUTPUT_DIR / "season_partition_summary.csv",
        )

        leader_rows = fetch_dicts(
            con,
            """
            SELECT
                season_year,
                season_type,
                season_label,
                ranking_scope,
                gender_scope,
                ranking_key,
                ranking_label,
                school_name,
                official_rank,
                posterior_school_score,
                posterior_ci95_lower,
                posterior_ci95_upper,
                athlete_unit_count,
                evidence_category
            FROM seasonal_rankings
            WHERE official_rank = 1
            ORDER BY
                season_year,
                season_type,
                ranking_scope,
                gender_scope,
                ranking_label
            """
        )
        write_csv(
            OUTPUT_DIR / "season_ranking_leaders.csv",
            leader_rows,
            list(leader_rows[0].keys()) if leader_rows else [],
        )

        methodology_rows = [
            {
                "scope": "Combined overall",
                "minimum_school_sample": COMBINED_OVERALL_MIN_SAMPLE,
                "athlete_unit":
                    "one equal-family athlete-school-endpoint-season vote",
            },
            {
                "scope": "Gender overall",
                "minimum_school_sample": GENDER_OVERALL_MIN_SAMPLE,
                "athlete_unit":
                    "one equal-family athlete-school-gender-endpoint-season vote",
            },
            {
                "scope": "Gender individual event",
                "minimum_school_sample": GENDER_EVENT_MIN_SAMPLE,
                "athlete_unit":
                    "one athlete-school-gender-endpoint-season-event vote",
            },
            {
                "scope": "Combined individual event",
                "minimum_school_sample": COMBINED_EVENT_MIN_SAMPLE,
                "athlete_unit":
                    "one athlete-school-endpoint-season-event vote",
            },
            {
                "scope": "Gender event group",
                "minimum_school_sample":
                    f"{GENDER_CORE_GROUP_MIN_SAMPLE} core / "
                    f"{GENDER_SPECIAL_GROUP_MIN_SAMPLE} special",
                "athlete_unit":
                    "one equal-event athlete-school-gender-season-group vote",
            },
            {
                "scope": "Combined event group",
                "minimum_school_sample":
                    f"{COMBINED_CORE_GROUP_MIN_SAMPLE} core / "
                    f"{COMBINED_SPECIAL_GROUP_MIN_SAMPLE} special",
                "athlete_unit":
                    "one equal-event athlete-school-season-group vote",
            },
        ]
        write_csv(
            OUTPUT_DIR / "seasonal_ranking_methodology.csv",
            methodology_rows,
            [
                "scope",
                "minimum_school_sample",
                "athlete_unit",
            ],
        )

        con.execute(
            f"""
            CREATE TABLE dataset_metadata AS
            SELECT
                'dataset_version' AS metadata_key,
                '{DATASET_VERSION}' AS metadata_value
            UNION ALL
            SELECT
                'policy_version',
                '{POLICY_VERSION}'
            UNION ALL
            SELECT
                'season_definition',
                'trajectory_endpoint_season'
            UNION ALL
            SELECT
                'ranking_scope_count',
                '6'
            UNION ALL
            SELECT
                'variance_prior_df',
                '{VARIANCE_PRIOR_DF}'
            UNION ALL
            SELECT
                'created_at_utc',
                CURRENT_TIMESTAMP::VARCHAR
            """
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

    output_files = sorted(
        path
        for path in OUTPUT_DIR.iterdir()
        if path.is_file()
        and path.name not in {
            "hard_checks.csv",
            "output_manifest.csv",
            "terminal_output.txt",
        }
    )

    write_csv(
        OUTPUT_DIR / "output_manifest.csv",
        [
            {
                "output_name": path.name,
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "dataset_version": DATASET_VERSION,
                "policy_version": POLICY_VERSION,
            }
            for path in output_files
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
        "MILESTONE 6 PHASE 6A — SEASON-BY-SEASON DEVELOPMENT RANKINGS",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "SEASON DEFINITION",
        "-" * 78,
        "A season ranking uses trajectories whose endpoint stable period is",
        "the named indoor or outdoor season.",
        "",
        "RESULTS",
        "-" * 78,
        f"Source trajectories: {int(counts['trajectory_rows']):,}",
        f"Available endpoint seasons: {int(counts['season_count']):,}",
        f"Earliest endpoint year: {counts['earliest_season_year']}",
        f"Latest endpoint year: {counts['latest_season_year']}",
        f"Season-athlete units: {int(counts['season_athlete_rows']):,}",
        f"Season-event units: {int(counts['season_event_rows']):,}",
        f"Season-group units: {int(counts['season_group_rows']):,}",
        f"All ranking rows: {int(counts['ranking_rows']):,}",
        f"Official ranking rows: {int(counts['official_ranking_rows']):,}",
        f"Publishable combined-overall seasons: "
        f"{int(counts['publishable_overall_seasons']):,}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Seasonal rankings published."
            if not failed
            else "FAIL — Review hard checks before publication."
        ),
    ]

    (OUTPUT_DIR / "phase_6a_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Available endpoint seasons: {int(counts['season_count']):,}")
    print(
        f"Endpoint year range: "
        f"{counts['earliest_season_year']}–"
        f"{counts['latest_season_year']}"
    )
    print(
        f"Season-athlete units: "
        f"{int(counts['season_athlete_rows']):,}"
    )
    print(
        f"Season-event units: "
        f"{int(counts['season_event_rows']):,}"
    )
    print(
        f"Season-group units: "
        f"{int(counts['season_group_rows']):,}"
    )
    print(
        f"Official ranking rows: "
        f"{int(counts['official_ranking_rows']):,}"
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
    print("Next: review season coverage and recent-season leaders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
