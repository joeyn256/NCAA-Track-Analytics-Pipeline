#!/usr/bin/env python3
"""
Milestone 5 Phase 5J — Individual Event and Coaching-Group Rankings

Creates supplemental NCAA Division I athlete-development rankings for:

1. Each canonical individual event, combining indoor/outdoor observations.
2. Each canonical event split by season type.
3. Coaching-oriented event groups.
4. Combined-gender versions of individual-event and group rankings.

Track and Endurance are intentionally not published as separate umbrella
groups. Their requested public names, Sprints and Distance, already exist as
primary groups, so retaining the old umbrellas would duplicate athlete-group
memberships and create two different rankings with the same displayed name.

Weighting policy
----------------
- Individual event: one vote per athlete, school, gender, and event.
  Indoor/outdoor trajectories are averaged before school aggregation.
- Season event: one vote per athlete, school, gender, season type, and event.
- Event group: individual-event contributions are averaged within the group,
  so a 100/200/400 athlete still contributes one total sprint-group vote.
- Transfers may contribute once to each distinct school.
- Multiple analytical stints at the same school are consolidated.

Ranking policy
--------------
- Empirical-Bayes shrinkage uses the same 20-degree-of-freedom variance
  stabilization as the official overall ranking.
- Individual event minimum: 10 athlete-event units.
- Season-event minimum: 10 athlete-event-season units.
- Core group minimum: 20 athlete-group units by gender.
- Special group minimum: 10 athlete-group units by gender.
- Combined-gender group minimum: 30 for core groups and 15 for special groups.
- A ranking partition must contain at least five eligible schools before
  official ranks are assigned.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import re
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

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5j_event_and_group_rankings"
)

OUTPUT_DB = OUTPUT_DIR / "ncaa_d1_event_development_rankings_v1.duckdb"

INPUT_TRAJECTORY_DATASET_VERSION = "expected_improvement_policy_v1_1"
INPUT_PUBLICATION_DATASET_VERSION = (
    "ncaa_d1_athlete_development_rankings_v1"
)

DATASET_VERSION = "ncaa_d1_event_development_rankings_v1_1"
RANKING_POLICY_VERSION = "event_and_group_rankings_policy_v1_1"
TAXONOMY_VERSION = "coaching_event_taxonomy_v1_1"

EXPECTED_TRAJECTORY_ROWS = 189_703
EXPECTED_SCHOOLS = 361

VARIANCE_PRIOR_DF = 20.0
CI_Z = 1.96
MIN_ELIGIBLE_SCHOOLS_PER_SCOPE = 5

EVENT_MIN_SAMPLE = 10
SEASON_EVENT_MIN_SAMPLE = 10
GENDER_GROUP_MIN_SAMPLE = 20
GENDER_SPECIAL_GROUP_MIN_SAMPLE = 10
COMBINED_EVENT_MIN_SAMPLE = 15
COMBINED_GROUP_MIN_SAMPLE = 30
COMBINED_SPECIAL_GROUP_MIN_SAMPLE = 15

SPECIAL_GROUPS = {
    "combined_events",
    "steeplechase",
    "race_walks",
    "special_events",
}

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


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 5J — EVENT AND GROUP RANKINGS")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Trajectory database: {TRAJECTORY_DB}")
    print(f"Publication database: {PUBLICATION_DB}")
    print(f"Output database: {OUTPUT_DB}")

    required_inputs = [
        TRAJECTORY_DB,
        PHASE_5E_CHECKS,
        PUBLICATION_DB,
        PHASE_5I_CHECKS,
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

    failed_5e = [
        row
        for row in read_csv(PHASE_5E_CHECKS)
        if row.get("status") != "PASS"
    ]
    failed_5i = [
        row
        for row in read_csv(PHASE_5I_CHECKS)
        if row.get("status") != "PASS"
    ]

    add_check(
        checks,
        "phase_5e_gate_passed",
        not failed_5e,
        [row.get("check_name") for row in failed_5e],
        [],
    )
    add_check(
        checks,
        "phase_5i_gate_passed",
        not failed_5i,
        [row.get("check_name") for row in failed_5i],
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
            ATTACH '{sql_path(TRAJECTORY_DB)}'
                AS trajectory_source (READ_ONLY)
            """
        )
        con.execute(
            f"""
            ATTACH '{sql_path(PUBLICATION_DB)}'
                AS publication_source (READ_ONLY)
            """
        )

        trajectory_metadata = {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM trajectory_source.main.dataset_metadata
                """
            ).fetchall()
        }
        publication_metadata = {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM publication_source.main.dataset_metadata
                """
            ).fetchall()
        }

        add_check(
            checks,
            "trajectory_dataset_version_matches",
            trajectory_metadata.get("dataset_version")
            == INPUT_TRAJECTORY_DATASET_VERSION,
            trajectory_metadata.get("dataset_version"),
            INPUT_TRAJECTORY_DATASET_VERSION,
        )
        add_check(
            checks,
            "publication_dataset_version_matches",
            publication_metadata.get("dataset_version")
            == INPUT_PUBLICATION_DATASET_VERSION,
            publication_metadata.get("dataset_version"),
            INPUT_PUBLICATION_DATASET_VERSION,
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
            CREATE TABLE trajectory_snapshot AS
            SELECT *
            FROM
                trajectory_source.main.expected_improvement_scored_trajectories
            """
        )

        # ------------------------------------------------------------------
        # Canonical coaching taxonomy
        # ------------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE event_taxonomy AS
            WITH distinct_events AS (
                SELECT
                    canonical_event_code,
                    ANY_VALUE(canonical_event_name)
                        AS canonical_event_name,
                    ANY_VALUE(event_family) AS source_event_family,
                    UPPER(
                        COALESCE(canonical_event_code, '')
                        || ' '
                        || COALESCE(
                            ANY_VALUE(canonical_event_name),
                            ''
                        )
                    ) AS event_search_text
                FROM trajectory_snapshot
                GROUP BY canonical_event_code
            ),
            classified AS (
                SELECT
                    *,
                    TRY_CAST(
                        REGEXP_EXTRACT(
                            event_search_text,
                            '([0-9]{{2,5}})',
                            1
                        ) AS INTEGER
                    ) AS extracted_distance_m,
                    CASE
                        WHEN REGEXP_MATCHES(
                            event_search_text,
                            '(DECATH|HEPTATH|PENTATH|COMBINED)'
                        )
                            THEN 'combined_events'
                        WHEN LOWER(source_event_family)
                            = 'combined_events'
                            THEN 'combined_events'
                        WHEN LOWER(source_event_family)
                            IN ('horizontal_jumps', 'vertical_jumps')
                            THEN 'jumps'
                        WHEN LOWER(source_event_family) = 'throws'
                            THEN 'throws'
                        WHEN REGEXP_MATCHES(
                            event_search_text,
                            '(RACE.?WALK|WALK)'
                        )
                            THEN 'race_walks'
                        WHEN LOWER(source_event_family) = 'steeplechase'
                          OR REGEXP_MATCHES(
                                event_search_text,
                                'STEEPLE'
                             )
                            THEN 'steeplechase'
                        WHEN LOWER(source_event_family) = 'hurdles'
                          OR REGEXP_MATCHES(
                                event_search_text,
                                '(HURD|\\bH\\b)'
                             )
                            THEN 'hurdles'
                        WHEN REGEXP_MATCHES(
                            event_search_text,
                            '(RELAY|4X|DMR|SMR)'
                        )
                            THEN 'relays'
                        WHEN REGEXP_MATCHES(
                            event_search_text,
                            '(MILE|1600)'
                        )
                            THEN 'middle_distance'
                        WHEN TRY_CAST(
                            REGEXP_EXTRACT(
                                event_search_text,
                                '([0-9]{{2,5}})',
                                1
                            ) AS INTEGER
                        ) BETWEEN 50 AND 400
                            THEN 'sprints'
                        WHEN TRY_CAST(
                            REGEXP_EXTRACT(
                                event_search_text,
                                '([0-9]{{2,5}})',
                                1
                            ) AS INTEGER
                        ) BETWEEN 500 AND 1609
                            THEN 'middle_distance'
                        WHEN TRY_CAST(
                            REGEXP_EXTRACT(
                                event_search_text,
                                '([0-9]{{2,5}})',
                                1
                            ) AS INTEGER
                        ) >= 2000
                            THEN 'distance'
                        WHEN LOWER(source_event_family) = 'running'
                            THEN 'other_running'
                        ELSE 'other'
                    END AS primary_event_group
                FROM distinct_events
            )
            SELECT
                canonical_event_code,
                canonical_event_name,
                source_event_family,
                extracted_distance_m,
                primary_event_group,
                CASE
                    WHEN primary_event_group = 'sprints'
                        THEN 'Sprints'
                    WHEN primary_event_group = 'middle_distance'
                        THEN 'Middle Distance'
                    WHEN primary_event_group = 'distance'
                        THEN 'Distance'
                    WHEN primary_event_group = 'hurdles'
                        THEN 'Hurdles'
                    WHEN primary_event_group = 'steeplechase'
                        THEN 'Steeplechase'
                    WHEN primary_event_group = 'jumps'
                        THEN 'Jumps'
                    WHEN primary_event_group = 'throws'
                        THEN 'Throws'
                    WHEN primary_event_group = 'combined_events'
                        THEN 'Combined Events'
                    WHEN primary_event_group = 'race_walks'
                        THEN 'Race Walks'
                    WHEN primary_event_group = 'relays'
                        THEN 'Relays'
                    WHEN primary_event_group = 'other_running'
                        THEN 'Other Running'
                    ELSE 'Other'
                END AS primary_event_group_label,
                primary_event_group NOT IN ('other', 'other_running')
                    AS taxonomy_publishable,
                '{TAXONOMY_VERSION}' AS taxonomy_version
            FROM classified
            """
        )

        con.execute(
            f"""
            CREATE TABLE event_group_membership AS
            SELECT
                canonical_event_code,
                primary_event_group AS event_group,
                primary_event_group_label AS event_group_label,
                'primary' AS group_level,
                '{TAXONOMY_VERSION}' AS taxonomy_version
            FROM event_taxonomy
            WHERE taxonomy_publishable

            UNION ALL

            SELECT
                canonical_event_code,
                'field' AS event_group,
                'Field' AS event_group_label,
                'umbrella' AS group_level,
                '{TAXONOMY_VERSION}' AS taxonomy_version
            FROM event_taxonomy
            WHERE primary_event_group IN ('jumps', 'throws')

            UNION ALL

            SELECT
                canonical_event_code,
                'special_events' AS event_group,
                'Special Events' AS event_group_label,
                'umbrella' AS group_level,
                '{TAXONOMY_VERSION}' AS taxonomy_version
            FROM event_taxonomy
            WHERE primary_event_group IN (
                'combined_events',
                'steeplechase',
                'race_walks'
            )
            """
        )

        # ------------------------------------------------------------------
        # Athlete contribution units
        # ------------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE athlete_event_contributions AS
            SELECT
                'aevt_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        t.canonical_person_id,
                        t.resolved_school_id,
                        t.canonical_gender_code,
                        t.canonical_event_code
                    )
                ) AS athlete_event_contribution_id,
                t.canonical_person_id,
                ANY_VALUE(t.athlete_id) AS athlete_id,
                ANY_VALUE(t.athlete_name) AS athlete_name,
                t.resolved_school_id,
                t.canonical_gender_code,
                t.canonical_event_code,
                ANY_VALUE(t.canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(t.event_family) AS source_event_family,
                ANY_VALUE(x.primary_event_group)
                    AS primary_event_group,
                ANY_VALUE(x.primary_event_group_label)
                    AS primary_event_group_label,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT t.season_type)
                    AS season_type_count,
                COUNT(DISTINCT t.school_stint_id)
                    AS school_stint_count,
                MIN(t.baseline_season_year)
                    AS first_baseline_season_year,
                MAX(t.endpoint_season_year)
                    AS last_endpoint_season_year,
                AVG(t.observed_improvement)
                    AS mean_observed_improvement,
                AVG(t.expected_improvement)
                    AS mean_expected_improvement,
                AVG(t.athlete_value_added)
                    AS athlete_event_value_added,
                MEDIAN(t.athlete_value_added)
                    AS median_trajectory_value_added,
                SUM(t.total_distinct_meets)
                    AS total_distinct_meets,
                SUM(t.qualifying_period_count)
                    AS total_qualifying_periods,
                MIN(t.training_support_n)
                    AS minimum_training_support,
                '{DATASET_VERSION}' AS dataset_version
            FROM trajectory_snapshot t
            JOIN event_taxonomy x
              USING (canonical_event_code)
            WHERE x.taxonomy_publishable
            GROUP BY
                t.canonical_person_id,
                t.resolved_school_id,
                t.canonical_gender_code,
                t.canonical_event_code
            """
        )

        con.execute(
            f"""
            CREATE TABLE athlete_season_event_contributions AS
            SELECT
                'asev_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        t.canonical_person_id,
                        t.resolved_school_id,
                        t.canonical_gender_code,
                        t.season_type,
                        t.canonical_event_code
                    )
                ) AS athlete_season_event_contribution_id,
                t.canonical_person_id,
                ANY_VALUE(t.athlete_id) AS athlete_id,
                ANY_VALUE(t.athlete_name) AS athlete_name,
                t.resolved_school_id,
                t.canonical_gender_code,
                t.season_type,
                t.canonical_event_code,
                ANY_VALUE(t.canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(t.event_family) AS source_event_family,
                ANY_VALUE(x.primary_event_group)
                    AS primary_event_group,
                ANY_VALUE(x.primary_event_group_label)
                    AS primary_event_group_label,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT t.school_stint_id)
                    AS school_stint_count,
                MIN(t.baseline_season_year)
                    AS first_baseline_season_year,
                MAX(t.endpoint_season_year)
                    AS last_endpoint_season_year,
                AVG(t.observed_improvement)
                    AS mean_observed_improvement,
                AVG(t.expected_improvement)
                    AS mean_expected_improvement,
                AVG(t.athlete_value_added)
                    AS athlete_season_event_value_added,
                MIN(t.training_support_n)
                    AS minimum_training_support,
                '{DATASET_VERSION}' AS dataset_version
            FROM trajectory_snapshot t
            JOIN event_taxonomy x
              USING (canonical_event_code)
            WHERE x.taxonomy_publishable
            GROUP BY
                t.canonical_person_id,
                t.resolved_school_id,
                t.canonical_gender_code,
                t.season_type,
                t.canonical_event_code
            """
        )

        con.execute(
            f"""
            CREATE TABLE athlete_group_contributions AS
            SELECT
                'agrp_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        a.canonical_person_id,
                        a.resolved_school_id,
                        a.canonical_gender_code,
                        g.event_group
                    )
                ) AS athlete_group_contribution_id,
                a.canonical_person_id,
                ANY_VALUE(a.athlete_id) AS athlete_id,
                ANY_VALUE(a.athlete_name) AS athlete_name,
                a.resolved_school_id,
                a.canonical_gender_code,
                g.event_group,
                ANY_VALUE(g.event_group_label)
                    AS event_group_label,
                ANY_VALUE(g.group_level) AS group_level,
                COUNT(*) AS event_count,
                SUM(a.trajectory_count) AS trajectory_count,
                SUM(a.season_type_count) AS summed_season_type_count,
                MIN(a.first_baseline_season_year)
                    AS first_baseline_season_year,
                MAX(a.last_endpoint_season_year)
                    AS last_endpoint_season_year,
                AVG(a.mean_observed_improvement)
                    AS equal_event_mean_observed_improvement,
                AVG(a.mean_expected_improvement)
                    AS equal_event_mean_expected_improvement,
                AVG(a.athlete_event_value_added)
                    AS athlete_group_value_added,
                MEDIAN(a.athlete_event_value_added)
                    AS median_event_value_added,
                MIN(a.minimum_training_support)
                    AS minimum_training_support,
                '{DATASET_VERSION}' AS dataset_version
            FROM athlete_event_contributions a
            JOIN event_group_membership g
              USING (canonical_event_code)
            GROUP BY
                a.canonical_person_id,
                a.resolved_school_id,
                a.canonical_gender_code,
                g.event_group
            """
        )

        # ------------------------------------------------------------------
        # Unified ranking input
        # ------------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE ranking_input_units AS
            SELECT
                'gender_event' AS ranking_scope,
                canonical_gender_code AS gender_scope,
                'all' AS season_scope,
                canonical_event_code AS ranking_key,
                canonical_event_name AS ranking_label,
                'individual_event' AS ranking_category,
                resolved_school_id,
                canonical_person_id,
                athlete_event_contribution_id AS contribution_id,
                athlete_event_value_added AS score_value,
                {EVENT_MIN_SAMPLE} AS minimum_sample,
                minimum_training_support
            FROM athlete_event_contributions

            UNION ALL

            SELECT
                'combined_event',
                'all',
                'all',
                canonical_event_code,
                canonical_event_name,
                'individual_event',
                resolved_school_id,
                canonical_person_id,
                athlete_event_contribution_id,
                athlete_event_value_added,
                {COMBINED_EVENT_MIN_SAMPLE},
                minimum_training_support
            FROM athlete_event_contributions

            UNION ALL

            SELECT
                'gender_season_event',
                canonical_gender_code,
                season_type,
                canonical_event_code,
                canonical_event_name,
                'season_event',
                resolved_school_id,
                canonical_person_id,
                athlete_season_event_contribution_id,
                athlete_season_event_value_added,
                {SEASON_EVENT_MIN_SAMPLE},
                minimum_training_support
            FROM athlete_season_event_contributions

            UNION ALL

            SELECT
                'gender_group',
                canonical_gender_code,
                'all',
                event_group,
                event_group_label,
                'event_group',
                resolved_school_id,
                canonical_person_id,
                athlete_group_contribution_id,
                athlete_group_value_added,
                CASE
                    WHEN event_group IN (
                        'combined_events',
                        'steeplechase',
                        'race_walks',
                        'special_events'
                    )
                        THEN {GENDER_SPECIAL_GROUP_MIN_SAMPLE}
                    ELSE {GENDER_GROUP_MIN_SAMPLE}
                END,
                minimum_training_support
            FROM athlete_group_contributions

            UNION ALL

            SELECT
                'combined_group',
                'all',
                'all',
                event_group,
                event_group_label,
                'event_group',
                resolved_school_id,
                canonical_person_id,
                athlete_group_contribution_id,
                athlete_group_value_added,
                CASE
                    WHEN event_group IN (
                        'combined_events',
                        'steeplechase',
                        'race_walks',
                        'special_events'
                    )
                        THEN {COMBINED_SPECIAL_GROUP_MIN_SAMPLE}
                    ELSE {COMBINED_GROUP_MIN_SAMPLE}
                END,
                minimum_training_support
            FROM athlete_group_contributions
            """
        )

        con.execute(
            """
            CREATE TABLE ranking_school_base AS
            SELECT
                ranking_scope,
                gender_scope,
                season_scope,
                ranking_key,
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
                ranking_scope,
                gender_scope,
                season_scope,
                ranking_key,
                resolved_school_id
            """
        )

        con.execute(
            """
            CREATE TABLE ranking_global_prior AS
            WITH globals AS (
                SELECT
                    ranking_scope,
                    gender_scope,
                    season_scope,
                    ranking_key,
                    AVG(score_value) AS global_athlete_mean,
                    VAR_SAMP(score_value) AS global_athlete_variance,
                    COUNT(*) AS total_athlete_units
                FROM ranking_input_units
                GROUP BY
                    ranking_scope,
                    gender_scope,
                    season_scope,
                    ranking_key
            ),
            pooled AS (
                SELECT
                    ranking_scope,
                    gender_scope,
                    season_scope,
                    ranking_key,
                    SUM(
                        (athlete_unit_count - 1)
                        * COALESCE(raw_within_school_variance, 0)
                    )
                    / NULLIF(
                        SUM(athlete_unit_count - 1),
                        0
                    ) AS pooled_within_school_variance
                FROM ranking_school_base
                GROUP BY
                    ranking_scope,
                    gender_scope,
                    season_scope,
                    ranking_key
            )
            SELECT *
            FROM globals
            JOIN pooled
              USING (
                ranking_scope,
                gender_scope,
                season_scope,
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
                gender_scope,
                season_scope,
                ranking_key
              )
            """
        )

        con.execute(
            """
            CREATE TABLE ranking_between_school_variance AS
            SELECT
                ranking_scope,
                gender_scope,
                season_scope,
                ranking_key,
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
            GROUP BY
                ranking_scope,
                gender_scope,
                season_scope,
                ranking_key
            """
        )

        con.execute(
            f"""
            CREATE TABLE ranking_school_posterior_base AS
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
                gender_scope,
                season_scope,
                ranking_key
              )
            """
        )

        con.execute(
            f"""
            CREATE TABLE event_and_group_rankings AS
            WITH intervals AS (
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
                            gender_scope,
                            season_scope,
                            ranking_key
                        ORDER BY posterior_school_score DESC
                    ) AS all_school_rank
                FROM ranking_school_posterior_base
            ),
            scope_counts AS (
                SELECT
                    ranking_scope,
                    gender_scope,
                    season_scope,
                    ranking_key,
                    COUNT(*) FILTER (
                        WHERE sample_eligible
                    ) AS sample_eligible_school_count
                FROM intervals
                GROUP BY
                    ranking_scope,
                    gender_scope,
                    season_scope,
                    ranking_key
            ),
            official AS (
                SELECT
                    i.ranking_scope,
                    i.gender_scope,
                    i.season_scope,
                    i.ranking_key,
                    i.resolved_school_id,
                    RANK() OVER (
                        PARTITION BY
                            i.ranking_scope,
                            i.gender_scope,
                            i.season_scope,
                            i.ranking_key
                        ORDER BY i.posterior_school_score DESC
                    ) AS official_rank,
                    COUNT(*) OVER (
                        PARTITION BY
                            i.ranking_scope,
                            i.gender_scope,
                            i.season_scope,
                            i.ranking_key
                    ) AS official_ranked_school_count
                FROM intervals i
                JOIN scope_counts c
                  USING (
                    ranking_scope,
                    gender_scope,
                    season_scope,
                    ranking_key
                  )
                WHERE i.sample_eligible
                  AND c.sample_eligible_school_count
                        >= {MIN_ELIGIBLE_SCHOOLS_PER_SCOPE}
            )
            SELECT
                i.*,
                c.sample_eligible_school_count,
                c.sample_eligible_school_count
                    >= {MIN_ELIGIBLE_SCHOOLS_PER_SCOPE}
                    AS scope_publishable,
                (
                    i.sample_eligible
                    AND c.sample_eligible_school_count
                        >= {MIN_ELIGIBLE_SCHOOLS_PER_SCOPE}
                ) AS official_rank_eligible,
                o.official_rank,
                o.official_ranked_school_count,
                m.school_name,
                m.state_code,
                m.city,
                m.conference_name,
                m.division_name,
                CASE
                    WHEN NOT (
                        i.sample_eligible
                        AND c.sample_eligible_school_count
                            >= {MIN_ELIGIBLE_SCHOOLS_PER_SCOPE}
                    )
                        THEN 'insufficient_data'
                    WHEN o.official_rank::DOUBLE
                            / o.official_ranked_school_count <= 0.10
                        THEN 'top_10_percent'
                    WHEN o.official_rank::DOUBLE
                            / o.official_ranked_school_count <= 0.25
                        THEN 'top_25_percent'
                    WHEN o.official_rank::DOUBLE
                            / o.official_ranked_school_count <= 0.50
                        THEN 'top_half'
                    WHEN o.official_rank::DOUBLE
                            / o.official_ranked_school_count <= 0.75
                        THEN 'lower_middle'
                    ELSE 'bottom_25_percent'
                END AS ranking_band,
                CASE
                    WHEN i.posterior_ci95_lower > 0
                        THEN 'credible_above_expected'
                    WHEN i.posterior_ci95_upper < 0
                        THEN 'credible_below_expected'
                    ELSE 'not_distinguishable_from_expected'
                END AS evidence_category,
                CASE
                    WHEN i.athlete_unit_count >= 50
                        THEN 'high_reliability'
                    WHEN i.athlete_unit_count >= 25
                        THEN 'strong_reliability'
                    WHEN i.athlete_unit_count >= i.minimum_sample
                        THEN 'standard_reliability'
                    ELSE 'insufficient_data'
                END AS reliability_tier,
                '{DATASET_VERSION}' AS dataset_version,
                '{RANKING_POLICY_VERSION}' AS ranking_policy_version
            FROM intervals i
            JOIN scope_counts c
              USING (
                ranking_scope,
                gender_scope,
                season_scope,
                ranking_key
              )
            JOIN school_metadata m
              USING (resolved_school_id)
            LEFT JOIN official o
              USING (
                ranking_scope,
                gender_scope,
                season_scope,
                ranking_key,
                resolved_school_id
              )
            """
        )

        # ------------------------------------------------------------------
        # Validation
        # ------------------------------------------------------------------
        counts = fetch_dicts(
            con,
            """
            SELECT
                (SELECT COUNT(*) FROM trajectory_snapshot)
                    AS trajectory_rows,
                (SELECT COUNT(*) FROM event_taxonomy)
                    AS taxonomy_event_rows,
                (SELECT COUNT(*)
                 FROM event_taxonomy
                 WHERE taxonomy_publishable)
                    AS publishable_event_rows,
                (SELECT COUNT(*)
                 FROM event_taxonomy
                 WHERE NOT taxonomy_publishable)
                    AS unresolved_event_rows,
                (SELECT COUNT(*) FROM athlete_event_contributions)
                    AS athlete_event_rows,
                (SELECT COUNT(*)
                 FROM athlete_season_event_contributions)
                    AS athlete_season_event_rows,
                (SELECT COUNT(*) FROM athlete_group_contributions)
                    AS athlete_group_rows,
                (SELECT COUNT(*) FROM event_and_group_rankings)
                    AS ranking_rows,
                (SELECT COUNT(*)
                 FROM event_and_group_rankings
                 WHERE official_rank_eligible)
                    AS official_ranking_rows,
                (SELECT COUNT(DISTINCT resolved_school_id)
                 FROM event_and_group_rankings)
                    AS represented_schools,
                (SELECT COUNT(DISTINCT ranking_key)
                 FROM event_and_group_rankings
                 WHERE ranking_scope = 'gender_event')
                    AS ranked_individual_events,
                (SELECT COUNT(DISTINCT ranking_key)
                 FROM event_and_group_rankings
                 WHERE ranking_scope = 'gender_group')
                    AS ranked_event_groups
            """
        )[0]

        quality = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        athlete_event_contribution_id,
                        COUNT(*) AS row_count
                    FROM athlete_event_contributions
                    GROUP BY athlete_event_contribution_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_athlete_event_ids,
                (SELECT COUNT(*)
                 FROM (
                    SELECT
                        athlete_group_contribution_id,
                        COUNT(*) AS row_count
                    FROM athlete_group_contributions
                    GROUP BY athlete_group_contribution_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_athlete_group_ids,
                (SELECT COUNT(*)
                 FROM event_and_group_rankings
                 WHERE posterior_school_score IS NULL
                    OR posterior_standard_error IS NULL
                    OR posterior_ci95_lower > posterior_ci95_upper
                    OR shrinkage_weight < 0
                    OR shrinkage_weight > 1)
                    AS invalid_ranking_rows,
                (SELECT COUNT(*)
                 FROM event_and_group_rankings
                 WHERE posterior_school_score
                    < LEAST(raw_school_score, global_athlete_mean)
                        - {FORMULA_TOLERANCE}
                    OR posterior_school_score
                    > GREATEST(raw_school_score, global_athlete_mean)
                        + {FORMULA_TOLERANCE})
                    AS nonconvex_posterior_rows,
                (SELECT COUNT(*)
                 FROM event_and_group_rankings
                 WHERE official_rank_eligible
                   AND official_rank IS NULL)
                    AS missing_official_rank_rows,
                (SELECT COUNT(*)
                 FROM event_and_group_rankings
                 WHERE NOT official_rank_eligible
                   AND official_rank IS NOT NULL)
                    AS ineligible_official_rank_rows,
                (SELECT COUNT(*)
                 FROM event_and_group_rankings
                 WHERE official_rank_eligible
                    <> (
                        sample_eligible
                        AND scope_publishable
                    ))
                    AS eligibility_mismatch_rows,
                (SELECT COUNT(*)
                 FROM school_metadata
                 WHERE metadata_match_status <> 'matched')
                    AS unmatched_school_metadata_rows,
                (SELECT COUNT(*)
                 FROM athlete_event_contributions
                 WHERE athlete_event_value_added IS NULL
                    OR canonical_event_code IS NULL
                    OR canonical_person_id IS NULL
                    OR resolved_school_id IS NULL)
                    AS invalid_athlete_event_rows,
                (SELECT COUNT(*)
                 FROM athlete_group_contributions
                 WHERE athlete_group_value_added IS NULL
                    OR event_count <= 0)
                    AS invalid_athlete_group_rows
            """
        )[0]

        add_check(
            checks,
            "trajectory_row_count",
            counts["trajectory_rows"] == EXPECTED_TRAJECTORY_ROWS,
            counts["trajectory_rows"],
            EXPECTED_TRAJECTORY_ROWS,
        )
        add_check(
            checks,
            "all_school_metadata_matched",
            quality["unmatched_school_metadata_rows"] == 0,
            quality["unmatched_school_metadata_rows"],
            0,
        )
        add_check(
            checks,
            "athlete_event_grain_unique",
            quality["duplicate_athlete_event_ids"] == 0,
            quality["duplicate_athlete_event_ids"],
            0,
        )
        add_check(
            checks,
            "athlete_group_grain_unique",
            quality["duplicate_athlete_group_ids"] == 0,
            quality["duplicate_athlete_group_ids"],
            0,
        )
        add_check(
            checks,
            "athlete_event_rows_valid",
            quality["invalid_athlete_event_rows"] == 0,
            quality["invalid_athlete_event_rows"],
            0,
        )
        add_check(
            checks,
            "athlete_group_rows_valid",
            quality["invalid_athlete_group_rows"] == 0,
            quality["invalid_athlete_group_rows"],
            0,
        )
        add_check(
            checks,
            "ranking_rows_valid",
            quality["invalid_ranking_rows"] == 0,
            quality["invalid_ranking_rows"],
            0,
        )
        add_check(
            checks,
            "posterior_scores_are_convex",
            quality["nonconvex_posterior_rows"] == 0,
            quality["nonconvex_posterior_rows"],
            0,
        )
        add_check(
            checks,
            "official_ranks_complete",
            quality["missing_official_rank_rows"] == 0,
            quality["missing_official_rank_rows"],
            0,
        )
        add_check(
            checks,
            "ineligible_rows_not_officially_ranked",
            quality["ineligible_official_rank_rows"] == 0,
            quality["ineligible_official_rank_rows"],
            0,
        )
        add_check(
            checks,
            "eligibility_policy_reconciles",
            quality["eligibility_mismatch_rows"] == 0,
            quality["eligibility_mismatch_rows"],
            0,
        )
        add_check(
            checks,
            "individual_events_exist",
            counts["ranked_individual_events"] > 0,
            counts["ranked_individual_events"],
            "greater than 0",
        )
        add_check(
            checks,
            "event_groups_exist",
            counts["ranked_event_groups"] >= 8,
            counts["ranked_event_groups"],
            "at least 8",
        )
        add_check(
            checks,
            "all_schools_remain_represented",
            counts["represented_schools"] == EXPECTED_SCHOOLS,
            counts["represented_schools"],
            EXPECTED_SCHOOLS,
        )

        # ------------------------------------------------------------------
        # Exports
        # ------------------------------------------------------------------
        export_query(
            con,
            """
            SELECT *
            FROM event_and_group_rankings
            WHERE ranking_scope = 'gender_event'
            ORDER BY
                gender_scope,
                ranking_label,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "individual_event_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM event_and_group_rankings
            WHERE ranking_scope = 'combined_event'
            ORDER BY
                ranking_label,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "combined_gender_event_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM event_and_group_rankings
            WHERE ranking_scope = 'gender_season_event'
            ORDER BY
                gender_scope,
                season_scope,
                ranking_label,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "season_event_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM event_and_group_rankings
            WHERE ranking_scope = 'gender_group'
            ORDER BY
                gender_scope,
                ranking_label,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "event_group_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM event_and_group_rankings
            WHERE ranking_scope = 'combined_group'
            ORDER BY
                ranking_label,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "combined_gender_group_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM event_taxonomy
            ORDER BY
                primary_event_group,
                canonical_event_name,
                canonical_event_code
            """,
            OUTPUT_DIR / "event_taxonomy.csv",
        )

        export_query(
            con,
            """
            SELECT
                g.*,
                t.canonical_event_name,
                t.source_event_family,
                t.primary_event_group,
                t.primary_event_group_label
            FROM event_group_membership g
            JOIN event_taxonomy t
              USING (canonical_event_code)
            ORDER BY
                g.event_group,
                t.canonical_event_name,
                g.canonical_event_code
            """,
            OUTPUT_DIR / "event_group_membership.csv",
        )

        export_query(
            con,
            """
            SELECT
                ranking_scope,
                gender_scope,
                season_scope,
                ranking_key,
                ANY_VALUE(ranking_label) AS ranking_label,
                ANY_VALUE(ranking_category) AS ranking_category,
                ANY_VALUE(minimum_sample) AS minimum_sample,
                COUNT(*) AS represented_school_count,
                COUNT(*) FILTER (
                    WHERE official_rank_eligible
                ) AS officially_ranked_school_count,
                SUM(athlete_unit_count) AS athlete_unit_count,
                MIN(athlete_unit_count) AS minimum_school_sample,
                MAX(athlete_unit_count) AS maximum_school_sample,
                AVG(posterior_school_score)
                    AS mean_posterior_school_score,
                MAX(posterior_school_score)
                    AS leading_posterior_school_score
            FROM event_and_group_rankings
            GROUP BY
                ranking_scope,
                gender_scope,
                season_scope,
                ranking_key
            ORDER BY
                ranking_scope,
                gender_scope,
                season_scope,
                ranking_label
            """,
            OUTPUT_DIR / "ranking_scope_summary.csv",
        )

        unresolved_rows = fetch_dicts(
            con,
            """
            SELECT *
            FROM event_taxonomy
            WHERE NOT taxonomy_publishable
            ORDER BY canonical_event_name, canonical_event_code
            """
        )
        write_csv(
            OUTPUT_DIR / "unresolved_event_taxonomy_review.csv",
            unresolved_rows,
            list(unresolved_rows[0].keys()) if unresolved_rows else [],
        )

        top_group_rows = fetch_dicts(
            con,
            """
            SELECT
                ranking_scope,
                gender_scope,
                ranking_key,
                ranking_label,
                official_rank,
                school_name,
                athlete_unit_count,
                posterior_school_score,
                posterior_ci95_lower,
                posterior_ci95_upper
            FROM event_and_group_rankings
            WHERE ranking_scope IN (
                'gender_group',
                'combined_group'
            )
              AND official_rank = 1
            ORDER BY ranking_scope, gender_scope, ranking_label
            """
        )
        write_csv(
            OUTPUT_DIR / "event_group_leaders.csv",
            top_group_rows,
            list(top_group_rows[0].keys()) if top_group_rows else [],
        )

        methodology_rows = [
            {
                "policy_key": "individual_event_unit",
                "policy_value":
                    "one athlete-school-gender-event vote",
                "description":
                    "Indoor and outdoor trajectories for the same event "
                    "are averaged before school aggregation.",
            },
            {
                "policy_key": "season_event_unit",
                "policy_value":
                    "one athlete-school-gender-season-event vote",
                "description":
                    "Preserves separate indoor and outdoor event rankings.",
            },
            {
                "policy_key": "group_unit",
                "policy_value":
                    "equal event average within athlete-school-group",
                "description":
                    "Prevents multi-event athletes from receiving extra "
                    "school voting weight inside a group.",
            },
            {
                "policy_key": "primary_groups",
                "policy_value":
                    "sprints|middle_distance|distance|hurdles|"
                    "steeplechase|jumps|throws|combined_events|"
                    "race_walks|relays",
                "description":
                    "Coaching-oriented primary classification.",
            },
            {
                "policy_key": "umbrella_groups",
                "policy_value":
                    "field|special_events",
                "description":
                    "Field and Special Events are the retained umbrella "
                    "groups; Sprints and Distance remain primary groups.",
            },
            {
                "policy_key": "ranking_model",
                "policy_value": "empirical_bayes_df20",
                "description":
                    "Uses the same variance stabilization and shrinkage "
                    "structure as the official overall rankings.",
            },
            {
                "policy_key": "minimum_scope_school_count",
                "policy_value":
                    str(MIN_ELIGIBLE_SCHOOLS_PER_SCOPE),
                "description":
                    "At least five sample-eligible schools are required "
                    "before an official partition rank is assigned.",
            },
        ]
        write_csv(
            OUTPUT_DIR / "event_ranking_methodology.csv",
            methodology_rows,
            ["policy_key", "policy_value", "description"],
        )

        summary_rows = [
            {
                "metric": "source_trajectory_rows",
                "value": counts["trajectory_rows"],
            },
            {
                "metric": "canonical_events_detected",
                "value": counts["taxonomy_event_rows"],
            },
            {
                "metric": "publishable_events",
                "value": counts["publishable_event_rows"],
            },
            {
                "metric": "unresolved_events",
                "value": counts["unresolved_event_rows"],
            },
            {
                "metric": "athlete_event_units",
                "value": counts["athlete_event_rows"],
            },
            {
                "metric": "athlete_season_event_units",
                "value": counts["athlete_season_event_rows"],
            },
            {
                "metric": "athlete_group_units",
                "value": counts["athlete_group_rows"],
            },
            {
                "metric": "ranking_rows",
                "value": counts["ranking_rows"],
            },
            {
                "metric": "official_ranking_rows",
                "value": counts["official_ranking_rows"],
            },
            {
                "metric": "individual_events_ranked",
                "value": counts["ranked_individual_events"],
            },
            {
                "metric": "event_groups_ranked",
                "value": counts["ranked_event_groups"],
            },
        ]
        write_csv(
            OUTPUT_DIR / "phase_5j_summary.csv",
            summary_rows,
            ["metric", "value"],
        )

        con.execute(
            f"""
            CREATE TABLE dataset_metadata AS
            SELECT
                'dataset_version' AS metadata_key,
                '{DATASET_VERSION}' AS metadata_value
            UNION ALL
            SELECT
                'ranking_policy_version',
                '{RANKING_POLICY_VERSION}'
            UNION ALL
            SELECT
                'taxonomy_version',
                '{TAXONOMY_VERSION}'
            UNION ALL
            SELECT
                'individual_event_minimum_sample',
                '{EVENT_MIN_SAMPLE}'
            UNION ALL
            SELECT
                'gender_group_minimum_sample',
                '{GENDER_GROUP_MIN_SAMPLE}'
            UNION ALL
            SELECT
                'publication_status',
                'supplemental_rankings_frozen'
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
            "output_manifest.csv",
            "hard_checks.csv",
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
                "ranking_policy_version": RANKING_POLICY_VERSION,
            }
            for path in output_files
        ],
        [
            "output_name",
            "path",
            "size_bytes",
            "sha256",
            "dataset_version",
            "ranking_policy_version",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 5 PHASE 5J — EVENT AND GROUP RANKINGS",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "RANKING PRODUCTS",
        "-" * 78,
        "Gender-specific individual event rankings",
        "Combined-gender individual event rankings",
        "Indoor/outdoor season-event rankings",
        "Gender-specific coaching-group rankings",
        "Combined-gender coaching-group rankings",
        "",
        "GROUP TAXONOMY",
        "-" * 78,
        "Primary: sprints, middle distance, distance, hurdles,",
        "steeplechase, jumps, throws, combined events, race walks, relays",
        "Umbrella: field, special events",
        "",
        "RESULTS",
        "-" * 78,
        f"Source trajectories: {int(counts['trajectory_rows']):,}",
        f"Canonical events detected: "
        f"{int(counts['taxonomy_event_rows']):,}",
        f"Publishable events: "
        f"{int(counts['publishable_event_rows']):,}",
        f"Unresolved events: "
        f"{int(counts['unresolved_event_rows']):,}",
        f"Athlete-event units: "
        f"{int(counts['athlete_event_rows']):,}",
        f"Athlete-group units: "
        f"{int(counts['athlete_group_rows']):,}",
        f"Official ranking rows: "
        f"{int(counts['official_ranking_rows']):,}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Event and coaching-group rankings frozen."
            if not failed
            else "FAIL — Review taxonomy or ranking validation."
        ),
        "",
        "NEXT",
        "-" * 78,
        "Review unresolved_event_taxonomy_review.csv.",
        "Spot-check individual-event and group leaders.",
        "Then update the Milestone 5 documentation and README.",
    ]

    (OUTPUT_DIR / "phase_5j_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Canonical events detected: "
        f"{int(counts['taxonomy_event_rows']):,}"
    )
    print(
        f"Publishable individual events: "
        f"{int(counts['publishable_event_rows']):,}"
    )
    print(
        f"Event groups ranked: "
        f"{int(counts['ranked_event_groups']):,}"
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
    print("Next: review taxonomy and update Milestone 5 documentation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
