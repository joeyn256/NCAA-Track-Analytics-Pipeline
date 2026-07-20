#!/usr/bin/env python3
"""
Milestone 6 Phase 6B — Seasonal Frontier and Elite Development Rankings

Creates season-by-season development rankings for athletes who began their
modeled trajectory near the performance frontier.

Cohorts
-------
1. frontier_70_plus:
   baseline_stable_level >= 70

2. elite_80_plus:
   baseline_stable_level >= 80

3. national_elite_endpoint_90_plus:
   endpoint_stable_level >= 90

4. championship_endpoint_95_plus:
   endpoint_stable_level >= 95

The broad all-athlete ranking from Phase 6A remains the primary project
ranking. These are separate analytical views that answer:

    Which schools developed athletes who began at a high level, or
    finished at a nationally elite or championship-caliber level?

Season interpretation
---------------------
A ranking such as "2026 Outdoor" includes eligible trajectories whose endpoint
stable period is the 2026 outdoor season.

Weighting
---------
- Overall: average trajectories within athlete-school-season-event-family,
  then average event families so each athlete-school-season receives one vote.
- Individual event: one athlete-school-season-event vote.
- Event group: average event contributions within athlete-school-season-group.
- Transfers may contribute once to each distinct school.
- Repeated same-school analytical stints are consolidated.

Ranking model
-------------
Matches the validated Milestone 5 / Phase 6A structure:
- stabilized within-school variance with a 20-df prior;
- method-of-moments between-school variance;
- empirical-Bayes posterior score;
- 95% posterior interval;
- season-centered score;
- minimum sample and partition coverage requirements;
- no published ranks when between-school variance is not detectable;
- lower cohort-specific sample thresholds for endpoint 90+ and 95+;
- endpoint 95+ ranks are explicitly exploratory.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


ROOT = Path.cwd()

PHASE_6A_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "seasonal_development_rankings_v1/"
      "phase_6a_seasonal_rankings"
)
PHASE_6A_DB = PHASE_6A_DIR / "seasonal_development_rankings_v1.duckdb"
PHASE_6A_CHECKS = PHASE_6A_DIR / "hard_checks.csv"

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "seasonal_elite_development_v1/"
      "phase_6b_seasonal_elite_rankings"
)
OUTPUT_DB = OUTPUT_DIR / "seasonal_elite_development_rankings_v1.duckdb"

INPUT_DATASET_VERSION = "seasonal_development_rankings_v1_1"
DATASET_VERSION = "seasonal_elite_development_rankings_v1_2"
POLICY_VERSION = "seasonal_elite_development_policy_v1_2"

EXPECTED_SOURCE_TRAJECTORIES = 189_703
EXPECTED_SCHOOLS = 361
EXPECTED_EVENTS = 30
EXPECTED_GROUPS = 10

FRONTIER_MINIMUM = 70.0
ELITE_MINIMUM = 80.0
NATIONAL_ELITE_ENDPOINT_MINIMUM = 90.0
CHAMPIONSHIP_ENDPOINT_MINIMUM = 95.0

VARIANCE_PRIOR_DF = 20.0
CI_Z = 1.96
MIN_BETWEEN_SCHOOL_VARIANCE = 1e-12
MIN_ELIGIBLE_SCHOOLS_PER_PARTITION = 5
FORMULA_TOLERANCE = 1e-10

# Smaller than broad-ranking thresholds because these cohorts are subsets.
COMBINED_OVERALL_MIN_SAMPLE = 8
GENDER_OVERALL_MIN_SAMPLE = 5
GENDER_EVENT_MIN_SAMPLE = 3
COMBINED_EVENT_MIN_SAMPLE = 5
GENDER_CORE_GROUP_MIN_SAMPLE = 5
GENDER_SPECIAL_GROUP_MIN_SAMPLE = 3
COMBINED_CORE_GROUP_MIN_SAMPLE = 8
COMBINED_SPECIAL_GROUP_MIN_SAMPLE = 5

# Endpoint-selected cohorts are much smaller. These thresholds are applied
# only to the 90+ and 95+ cohorts; baseline-selected cohorts retain the
# original Phase 6B thresholds above.
NATIONAL_ELITE_COMBINED_OVERALL_MIN_SAMPLE = 3
NATIONAL_ELITE_GENDER_OVERALL_MIN_SAMPLE = 2
NATIONAL_ELITE_GENDER_EVENT_MIN_SAMPLE = 1
NATIONAL_ELITE_COMBINED_EVENT_MIN_SAMPLE = 2
NATIONAL_ELITE_GENDER_CORE_GROUP_MIN_SAMPLE = 2
NATIONAL_ELITE_GENDER_SPECIAL_GROUP_MIN_SAMPLE = 1
NATIONAL_ELITE_COMBINED_CORE_GROUP_MIN_SAMPLE = 3
NATIONAL_ELITE_COMBINED_SPECIAL_GROUP_MIN_SAMPLE = 2

# The 95+ cohort is an exploratory spotlight. One-athlete school samples
# are permitted, but the existing five-school and nonzero-variance gates
# still apply before a rank is published.
CHAMPIONSHIP_COMBINED_OVERALL_MIN_SAMPLE = 1
CHAMPIONSHIP_GENDER_OVERALL_MIN_SAMPLE = 1
CHAMPIONSHIP_GENDER_EVENT_MIN_SAMPLE = 1
CHAMPIONSHIP_COMBINED_EVENT_MIN_SAMPLE = 1
CHAMPIONSHIP_GENDER_CORE_GROUP_MIN_SAMPLE = 1
CHAMPIONSHIP_GENDER_SPECIAL_GROUP_MIN_SAMPLE = 1
CHAMPIONSHIP_COMBINED_CORE_GROUP_MIN_SAMPLE = 1
CHAMPIONSHIP_COMBINED_SPECIAL_GROUP_MIN_SAMPLE = 1

SPECIAL_GROUPS = {
    "combined_events",
    "steeplechase",
    "race_walks",
    "special_events",
}


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

    print(
        "MILESTONE 6 PHASE 6B — "
        "SEASONAL FRONTIER, ELITE, AND CHAMPIONSHIP-CALIBER DEVELOPMENT RANKINGS"
    )
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Output database: {OUTPUT_DB}")

    required_inputs = [PHASE_6A_DB, PHASE_6A_CHECKS]
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
        print("PHASE GATE: FAIL — Required Phase 6A input is missing.")
        return 1

    phase_6a_failures = failed_checks(PHASE_6A_CHECKS)
    add_check(
        checks,
        "phase_6a_gate_passed",
        not phase_6a_failures,
        phase_6a_failures,
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
            ATTACH '{sql_path(PHASE_6A_DB)}'
                AS seasonal_source (READ_ONLY)
            """
        )

        source_metadata = dict(
            con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM seasonal_source.main.dataset_metadata
                """
            ).fetchall()
        )

        observed_version = source_metadata.get("dataset_version")
        add_check(
            checks,
            "phase_6a_version_matches",
            observed_version == INPUT_DATASET_VERSION,
            observed_version,
            INPUT_DATASET_VERSION,
        )

        con.execute(
            """
            CREATE TABLE school_metadata AS
            SELECT *
            FROM seasonal_source.main.school_metadata
            """
        )
        con.execute(
            """
            CREATE TABLE event_taxonomy AS
            SELECT *
            FROM seasonal_source.main.event_taxonomy
            """
        )
        con.execute(
            """
            CREATE TABLE event_group_membership AS
            SELECT *
            FROM seasonal_source.main.event_group_membership
            """
        )
        con.execute(
            """
            CREATE TABLE source_trajectory_snapshot AS
            SELECT *
            FROM seasonal_source.main.trajectory_snapshot
            """
        )

        # --------------------------------------------------------------
        # Cohort registry and trajectory expansion
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE elite_cohort_registry AS
            SELECT
                'frontier_70_plus' AS cohort_key,
                'Frontier (Baseline 70+)' AS cohort_label,
                'baseline' AS selection_basis,
                {FRONTIER_MINIMUM}::DOUBLE AS minimum_level,
                {FRONTIER_MINIMUM}::DOUBLE
                    AS minimum_baseline_level,
                NULL::DOUBLE AS minimum_endpoint_level,
                'Athletes beginning near the performance frontier.'
                    AS interpretation
            UNION ALL
            SELECT
                'elite_80_plus',
                'Elite (Baseline 80+)',
                'baseline',
                {ELITE_MINIMUM}::DOUBLE,
                {ELITE_MINIMUM}::DOUBLE,
                NULL::DOUBLE,
                'Athletes beginning at an elite normalized level.'
            UNION ALL
            SELECT
                'national_elite_endpoint_90_plus',
                'National Elite Finishers (Endpoint 90+)',
                'endpoint',
                {NATIONAL_ELITE_ENDPOINT_MINIMUM}::DOUBLE,
                NULL::DOUBLE,
                {NATIONAL_ELITE_ENDPOINT_MINIMUM}::DOUBLE,
                'Athletes finishing at a nationally elite normalized level.'
            UNION ALL
            SELECT
                'championship_endpoint_95_plus',
                'Championship-Caliber Finishers (Endpoint 95+)',
                'endpoint',
                {CHAMPIONSHIP_ENDPOINT_MINIMUM}::DOUBLE,
                NULL::DOUBLE,
                {CHAMPIONSHIP_ENDPOINT_MINIMUM}::DOUBLE,
                'Athletes finishing extremely close to the collegiate frontier.'
            """
        )

        con.execute(
            f"""
            CREATE TABLE elite_trajectory_snapshot AS
            SELECT
                'frontier_70_plus' AS cohort_key,
                'Frontier (Baseline 70+)' AS cohort_label,
                {FRONTIER_MINIMUM}::DOUBLE
                    AS minimum_baseline_level,
                t.*
            FROM source_trajectory_snapshot t
            WHERE t.baseline_stable_level >= {FRONTIER_MINIMUM}

            UNION ALL

            SELECT
                'elite_80_plus',
                'Elite (Baseline 80+)',
                {ELITE_MINIMUM}::DOUBLE,
                t.*
            FROM source_trajectory_snapshot t
            WHERE t.baseline_stable_level >= {ELITE_MINIMUM}

            UNION ALL

            SELECT
                'national_elite_endpoint_90_plus',
                'National Elite Finishers (Endpoint 90+)',
                {NATIONAL_ELITE_ENDPOINT_MINIMUM}::DOUBLE,
                t.*
            FROM source_trajectory_snapshot t
            WHERE t.endpoint_stable_level
                >= {NATIONAL_ELITE_ENDPOINT_MINIMUM}

            UNION ALL

            SELECT
                'championship_endpoint_95_plus',
                'Championship-Caliber Finishers (Endpoint 95+)',
                {CHAMPIONSHIP_ENDPOINT_MINIMUM}::DOUBLE,
                t.*
            FROM source_trajectory_snapshot t
            WHERE t.endpoint_stable_level
                >= {CHAMPIONSHIP_ENDPOINT_MINIMUM}
            """
        )

        con.execute(
            f"""
            CREATE TABLE elite_season_coverage AS
            SELECT
                cohort_key,
                ANY_VALUE(cohort_label) AS cohort_label,
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
                AVG(baseline_stable_level)
                    AS mean_baseline_level,
                MIN(baseline_stable_level)
                    AS minimum_observed_baseline_level,
                MAX(baseline_stable_level)
                    AS maximum_observed_baseline_level,
                '{DATASET_VERSION}' AS dataset_version
            FROM elite_trajectory_snapshot
            GROUP BY
                cohort_key,
                endpoint_season_year,
                LOWER(season_type)
            """
        )

        # --------------------------------------------------------------
        # Overall equal-family athlete contributions
        # --------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE elite_athlete_family_contributions AS
            SELECT
                cohort_key,
                ANY_VALUE(cohort_label) AS cohort_label,
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
                AVG(baseline_stable_level) AS mean_baseline_level,
                AVG(endpoint_stable_level) AS mean_endpoint_level,
                AVG(observed_improvement)
                    AS family_mean_observed_improvement,
                AVG(expected_improvement)
                    AS family_mean_expected_improvement,
                AVG(athlete_value_added)
                    AS family_mean_value_added,
                AVG(annualized_athlete_value_added)
                    AS family_mean_annualized_value_added,
                MIN(training_support_n) AS minimum_training_support
            FROM elite_trajectory_snapshot
            GROUP BY
                cohort_key,
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
            CREATE TABLE elite_season_athlete_contributions AS
            SELECT
                'esath_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        cohort_key,
                        season_year,
                        season_type,
                        canonical_person_id,
                        resolved_school_id,
                        canonical_gender_code
                    )
                ) AS contribution_id,
                cohort_key,
                ANY_VALUE(cohort_label) AS cohort_label,
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
                AVG(mean_baseline_level) AS mean_baseline_level,
                AVG(mean_endpoint_level) AS mean_endpoint_level,
                AVG(family_mean_observed_improvement)
                    AS equal_family_observed_improvement,
                AVG(family_mean_expected_improvement)
                    AS equal_family_expected_improvement,
                AVG(family_mean_value_added)
                    AS elite_athlete_value_added,
                AVG(family_mean_annualized_value_added)
                    AS elite_athlete_annualized_value_added,
                MIN(minimum_training_support)
                    AS minimum_training_support,
                '{DATASET_VERSION}' AS dataset_version
            FROM elite_athlete_family_contributions
            GROUP BY
                cohort_key,
                season_year,
                season_type,
                canonical_person_id,
                resolved_school_id,
                canonical_gender_code
            """
        )

        # --------------------------------------------------------------
        # Event and group athlete contributions
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE elite_season_event_contributions AS
            SELECT
                'esevt_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        t.cohort_key,
                        t.endpoint_season_year,
                        LOWER(t.season_type),
                        t.canonical_person_id,
                        t.resolved_school_id,
                        t.canonical_gender_code,
                        t.canonical_event_code
                    )
                ) AS contribution_id,
                t.cohort_key,
                ANY_VALUE(t.cohort_label) AS cohort_label,
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
                AVG(t.baseline_stable_level) AS mean_baseline_level,
                AVG(t.endpoint_stable_level) AS mean_endpoint_level,
                AVG(t.observed_improvement)
                    AS mean_observed_improvement,
                AVG(t.expected_improvement)
                    AS mean_expected_improvement,
                AVG(t.athlete_value_added)
                    AS elite_event_value_added,
                AVG(t.annualized_athlete_value_added)
                    AS elite_event_annualized_value_added,
                MIN(t.training_support_n)
                    AS minimum_training_support,
                '{DATASET_VERSION}' AS dataset_version
            FROM elite_trajectory_snapshot t
            JOIN event_taxonomy x
              USING (canonical_event_code)
            WHERE x.taxonomy_publishable
            GROUP BY
                t.cohort_key,
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
            CREATE TABLE elite_season_group_contributions AS
            SELECT
                'esgrp_'
                || MD5(
                    CONCAT_WS(
                        '|',
                        e.cohort_key,
                        e.season_year,
                        e.season_type,
                        e.canonical_person_id,
                        e.resolved_school_id,
                        e.canonical_gender_code,
                        g.event_group
                    )
                ) AS contribution_id,
                e.cohort_key,
                ANY_VALUE(e.cohort_label) AS cohort_label,
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
                AVG(e.mean_baseline_level) AS mean_baseline_level,
                AVG(e.mean_endpoint_level) AS mean_endpoint_level,
                AVG(e.mean_observed_improvement)
                    AS equal_event_observed_improvement,
                AVG(e.mean_expected_improvement)
                    AS equal_event_expected_improvement,
                AVG(e.elite_event_value_added)
                    AS elite_group_value_added,
                AVG(e.elite_event_annualized_value_added)
                    AS elite_group_annualized_value_added,
                MIN(e.minimum_training_support)
                    AS minimum_training_support,
                '{DATASET_VERSION}' AS dataset_version
            FROM elite_season_event_contributions e
            JOIN event_group_membership g
              USING (canonical_event_code)
            GROUP BY
                e.cohort_key,
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

        # --------------------------------------------------------------
        # Unified ranking input
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE ranking_input_units AS
            SELECT
                'elite_overall_combined' AS ranking_scope,
                cohort_key,
                cohort_label,
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
                contribution_id,
                elite_athlete_value_added AS score_value,
                mean_baseline_level,
                mean_endpoint_level,
                CASE
                    WHEN cohort_key
                        = 'national_elite_endpoint_90_plus'
                        THEN {NATIONAL_ELITE_COMBINED_OVERALL_MIN_SAMPLE}
                    WHEN cohort_key
                        = 'championship_endpoint_95_plus'
                        THEN {CHAMPIONSHIP_COMBINED_OVERALL_MIN_SAMPLE}
                    ELSE {COMBINED_OVERALL_MIN_SAMPLE}
                END AS minimum_sample,
                minimum_training_support
            FROM elite_season_athlete_contributions

            UNION ALL

            SELECT
                'elite_overall_gender',
                cohort_key,
                cohort_label,
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
                contribution_id,
                elite_athlete_value_added,
                mean_baseline_level,
                mean_endpoint_level,
                CASE
                    WHEN cohort_key
                        = 'national_elite_endpoint_90_plus'
                        THEN {NATIONAL_ELITE_GENDER_OVERALL_MIN_SAMPLE}
                    WHEN cohort_key
                        = 'championship_endpoint_95_plus'
                        THEN {CHAMPIONSHIP_GENDER_OVERALL_MIN_SAMPLE}
                    ELSE {GENDER_OVERALL_MIN_SAMPLE}
                END,
                minimum_training_support
            FROM elite_season_athlete_contributions

            UNION ALL

            SELECT
                'elite_event_gender',
                cohort_key,
                cohort_label,
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
                contribution_id,
                elite_event_value_added,
                mean_baseline_level,
                mean_endpoint_level,
                CASE
                    WHEN cohort_key
                        = 'national_elite_endpoint_90_plus'
                        THEN {NATIONAL_ELITE_GENDER_EVENT_MIN_SAMPLE}
                    WHEN cohort_key
                        = 'championship_endpoint_95_plus'
                        THEN {CHAMPIONSHIP_GENDER_EVENT_MIN_SAMPLE}
                    ELSE {GENDER_EVENT_MIN_SAMPLE}
                END,
                minimum_training_support
            FROM elite_season_event_contributions

            UNION ALL

            SELECT
                'elite_event_combined',
                cohort_key,
                cohort_label,
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
                contribution_id,
                elite_event_value_added,
                mean_baseline_level,
                mean_endpoint_level,
                CASE
                    WHEN cohort_key
                        = 'national_elite_endpoint_90_plus'
                        THEN {NATIONAL_ELITE_COMBINED_EVENT_MIN_SAMPLE}
                    WHEN cohort_key
                        = 'championship_endpoint_95_plus'
                        THEN {CHAMPIONSHIP_COMBINED_EVENT_MIN_SAMPLE}
                    ELSE {COMBINED_EVENT_MIN_SAMPLE}
                END,
                minimum_training_support
            FROM elite_season_event_contributions

            UNION ALL

            SELECT
                'elite_group_gender',
                cohort_key,
                cohort_label,
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
                contribution_id,
                elite_group_value_added,
                mean_baseline_level,
                mean_endpoint_level,
                CASE
                    WHEN cohort_key
                        = 'championship_endpoint_95_plus'
                        THEN CASE
                            WHEN event_group IN ({special_group_sql})
                                THEN {CHAMPIONSHIP_GENDER_SPECIAL_GROUP_MIN_SAMPLE}
                            ELSE {CHAMPIONSHIP_GENDER_CORE_GROUP_MIN_SAMPLE}
                        END
                    WHEN cohort_key
                        = 'national_elite_endpoint_90_plus'
                        THEN CASE
                            WHEN event_group IN ({special_group_sql})
                                THEN {NATIONAL_ELITE_GENDER_SPECIAL_GROUP_MIN_SAMPLE}
                            ELSE {NATIONAL_ELITE_GENDER_CORE_GROUP_MIN_SAMPLE}
                        END
                    WHEN event_group IN ({special_group_sql})
                        THEN {GENDER_SPECIAL_GROUP_MIN_SAMPLE}
                    ELSE {GENDER_CORE_GROUP_MIN_SAMPLE}
                END,
                minimum_training_support
            FROM elite_season_group_contributions

            UNION ALL

            SELECT
                'elite_group_combined',
                cohort_key,
                cohort_label,
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
                contribution_id,
                elite_group_value_added,
                mean_baseline_level,
                mean_endpoint_level,
                CASE
                    WHEN cohort_key
                        = 'championship_endpoint_95_plus'
                        THEN CASE
                            WHEN event_group IN ({special_group_sql})
                                THEN {CHAMPIONSHIP_COMBINED_SPECIAL_GROUP_MIN_SAMPLE}
                            ELSE {CHAMPIONSHIP_COMBINED_CORE_GROUP_MIN_SAMPLE}
                        END
                    WHEN cohort_key
                        = 'national_elite_endpoint_90_plus'
                        THEN CASE
                            WHEN event_group IN ({special_group_sql})
                                THEN {NATIONAL_ELITE_COMBINED_SPECIAL_GROUP_MIN_SAMPLE}
                            ELSE {NATIONAL_ELITE_COMBINED_CORE_GROUP_MIN_SAMPLE}
                        END
                    WHEN event_group IN ({special_group_sql})
                        THEN {COMBINED_SPECIAL_GROUP_MIN_SAMPLE}
                    ELSE {COMBINED_CORE_GROUP_MIN_SAMPLE}
                END,
                minimum_training_support
            FROM elite_season_group_contributions
            """
        )

        partition_columns = """
            ranking_scope,
            cohort_key,
            season_year,
            season_type,
            gender_scope,
            ranking_key
        """

        # --------------------------------------------------------------
        # Empirical-Bayes ranking engine
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE ranking_school_base AS
            SELECT
                {partition_columns},
                ANY_VALUE(cohort_label) AS cohort_label,
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
                AVG(mean_baseline_level) AS mean_baseline_level,
                AVG(mean_endpoint_level) AS mean_endpoint_level,
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
                cohort_key,
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
                cohort_key,
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
            CREATE TABLE seasonal_elite_rankings AS
            WITH posterior AS (
                SELECT
                    s.*,
                    t.between_school_variance,
                    t.observed_school_mean_variance,
                    t.mean_sampling_variance,
                    t.represented_school_count,
                    CASE
                        WHEN t.between_school_variance
                                <= {MIN_BETWEEN_SCHOOL_VARIANCE}
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
                                WHEN t.between_school_variance
                                        <= {MIN_BETWEEN_SCHOOL_VARIANCE}
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
                        WHEN t.between_school_variance
                                <= {MIN_BETWEEN_SCHOOL_VARIANCE}
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
                    cohort_key,
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
                            cohort_key,
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
                    cohort_key,
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
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    ranking_key
            ),
            official AS (
                SELECT
                    i.ranking_scope,
                    i.cohort_key,
                    i.season_year,
                    i.season_type,
                    i.gender_scope,
                    i.ranking_key,
                    i.resolved_school_id,
                    RANK() OVER (
                        PARTITION BY
                            i.ranking_scope,
                            i.cohort_key,
                            i.season_year,
                            i.season_type,
                            i.gender_scope,
                            i.ranking_key
                        ORDER BY i.posterior_school_score DESC
                    ) AS official_rank,
                    COUNT(*) OVER (
                        PARTITION BY
                            i.ranking_scope,
                            i.cohort_key,
                            i.season_year,
                            i.season_type,
                            i.gender_scope,
                            i.ranking_key
                    ) AS official_ranked_school_count
                FROM intervals i
                JOIN partition_counts c
                  USING (
                    ranking_scope,
                    cohort_key,
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
                CASE
                    WHEN i.cohort_key
                        = 'championship_endpoint_95_plus'
                        THEN 'exploratory_extreme_elite'
                    WHEN i.cohort_key
                        = 'national_elite_endpoint_90_plus'
                        THEN 'provisional_national_elite'
                    ELSE 'standard_development'
                END AS publication_tier,
                '{DATASET_VERSION}' AS dataset_version
            FROM intervals i
            JOIN partition_counts c
              USING (
                ranking_scope,
                cohort_key,
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
                cohort_key,
                season_year,
                season_type,
                gender_scope,
                ranking_key,
                resolved_school_id
              )
            """
        )

        con.execute(
            """
            CREATE TABLE elite_partition_summary AS
            SELECT
                ranking_scope,
                cohort_key,
                ANY_VALUE(cohort_label) AS cohort_label,
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
            FROM seasonal_elite_rankings
            GROUP BY
                ranking_scope,
                cohort_key,
                season_year,
                season_type,
                gender_scope,
                ranking_key
            """
        )

        # --------------------------------------------------------------
        # Validation
        # --------------------------------------------------------------
        counts = fetch_dicts(
            con,
            """
            SELECT
                (SELECT COUNT(*) FROM source_trajectory_snapshot)
                    AS source_trajectory_rows,
                (SELECT COUNT(*) FROM school_metadata)
                    AS school_rows,
                (SELECT COUNT(*) FROM event_taxonomy)
                    AS event_rows,
                (SELECT COUNT(DISTINCT event_group)
                 FROM event_group_membership)
                    AS group_rows,
                (SELECT COUNT(*)
                 FROM elite_trajectory_snapshot
                 WHERE cohort_key = 'frontier_70_plus')
                    AS frontier_trajectory_rows,
                (SELECT COUNT(*)
                 FROM elite_trajectory_snapshot
                 WHERE cohort_key = 'elite_80_plus')
                    AS elite_trajectory_rows,
                (SELECT COUNT(*)
                 FROM elite_trajectory_snapshot
                 WHERE cohort_key
                    = 'national_elite_endpoint_90_plus')
                    AS national_elite_trajectory_rows,
                (SELECT COUNT(*)
                 FROM elite_trajectory_snapshot
                 WHERE cohort_key
                    = 'championship_endpoint_95_plus')
                    AS championship_trajectory_rows,
                (SELECT COUNT(*) FROM elite_season_coverage)
                    AS coverage_rows,
                (SELECT COUNT(*)
                 FROM elite_season_athlete_contributions)
                    AS athlete_unit_rows,
                (SELECT COUNT(*)
                 FROM elite_season_event_contributions)
                    AS event_unit_rows,
                (SELECT COUNT(*)
                 FROM elite_season_group_contributions)
                    AS group_unit_rows,
                (SELECT COUNT(*) FROM seasonal_elite_rankings)
                    AS ranking_rows,
                (SELECT COUNT(*)
                 FROM seasonal_elite_rankings
                 WHERE official_rank_eligible)
                    AS official_ranking_rows,
                (SELECT COUNT(DISTINCT cohort_key)
                 FROM seasonal_elite_rankings)
                    AS cohort_count
            """
        )[0]

        quality = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM elite_trajectory_snapshot
                 WHERE cohort_key = 'frontier_70_plus'
                   AND baseline_stable_level < {FRONTIER_MINIMUM})
                    AS invalid_frontier_rows,
                (SELECT COUNT(*)
                 FROM elite_trajectory_snapshot
                 WHERE cohort_key = 'elite_80_plus'
                   AND baseline_stable_level < {ELITE_MINIMUM})
                    AS invalid_elite_rows,
                (SELECT COUNT(*)
                 FROM elite_trajectory_snapshot
                 WHERE cohort_key
                    = 'national_elite_endpoint_90_plus'
                   AND endpoint_stable_level
                    < {NATIONAL_ELITE_ENDPOINT_MINIMUM})
                    AS invalid_national_elite_rows,
                (SELECT COUNT(*)
                 FROM elite_trajectory_snapshot
                 WHERE cohort_key
                    = 'championship_endpoint_95_plus'
                   AND endpoint_stable_level
                    < {CHAMPIONSHIP_ENDPOINT_MINIMUM})
                    AS invalid_championship_rows,
                (SELECT COUNT(*)
                 FROM elite_trajectory_snapshot e
                 WHERE e.cohort_key = 'elite_80_plus'
                   AND NOT EXISTS (
                        SELECT 1
                        FROM elite_trajectory_snapshot f
                        WHERE f.cohort_key = 'frontier_70_plus'
                          AND f.trajectory_id = e.trajectory_id
                   ))
                    AS elite_not_nested_rows,
                (SELECT COUNT(*)
                 FROM elite_trajectory_snapshot c
                 WHERE c.cohort_key
                    = 'championship_endpoint_95_plus'
                   AND NOT EXISTS (
                        SELECT 1
                        FROM elite_trajectory_snapshot n
                        WHERE n.cohort_key
                            = 'national_elite_endpoint_90_plus'
                          AND n.trajectory_id = c.trajectory_id
                   ))
                    AS championship_not_nested_rows,
                (SELECT COUNT(*)
                 FROM (
                    SELECT contribution_id, COUNT(*) AS row_count
                    FROM elite_season_athlete_contributions
                    GROUP BY contribution_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_athlete_unit_ids,
                (SELECT COUNT(*)
                 FROM (
                    SELECT contribution_id, COUNT(*) AS row_count
                    FROM elite_season_event_contributions
                    GROUP BY contribution_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_event_unit_ids,
                (SELECT COUNT(*)
                 FROM (
                    SELECT contribution_id, COUNT(*) AS row_count
                    FROM elite_season_group_contributions
                    GROUP BY contribution_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_group_unit_ids,
                (SELECT COUNT(*)
                 FROM seasonal_elite_rankings
                 WHERE posterior_school_score IS NULL
                    OR posterior_standard_error IS NULL
                    OR posterior_ci95_lower > posterior_ci95_upper
                    OR shrinkage_weight < 0
                    OR shrinkage_weight > 1)
                    AS invalid_ranking_rows,
                (SELECT COUNT(*)
                 FROM seasonal_elite_rankings
                 WHERE posterior_school_score
                    < LEAST(raw_school_score, global_athlete_mean)
                        - {FORMULA_TOLERANCE}
                    OR posterior_school_score
                    > GREATEST(raw_school_score, global_athlete_mean)
                        + {FORMULA_TOLERANCE})
                    AS nonconvex_posterior_rows,
                (SELECT COUNT(*)
                 FROM seasonal_elite_rankings
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
                 FROM seasonal_elite_rankings
                 WHERE between_school_variance
                            <= {MIN_BETWEEN_SCHOOL_VARIANCE}
                   AND official_rank IS NOT NULL)
                    AS zero_variance_official_rank_rows,
                (SELECT COUNT(*)
                 FROM school_metadata
                 WHERE metadata_match_status <> 'matched')
                    AS unmatched_school_metadata_rows
            """
        )[0]

        for name, observed, expected in [
            (
                "source_trajectory_row_count",
                counts["source_trajectory_rows"],
                EXPECTED_SOURCE_TRAJECTORIES,
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
                "cohort_count",
                counts["cohort_count"],
                4,
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
            "frontier_cohort_exists",
            counts["frontier_trajectory_rows"] > 0,
            counts["frontier_trajectory_rows"],
            "greater than 0",
        )
        add_check(
            checks,
            "elite_cohort_exists",
            counts["elite_trajectory_rows"] > 0,
            counts["elite_trajectory_rows"],
            "greater than 0",
        )
        add_check(
            checks,
            "elite_cohort_is_subset_of_frontier",
            counts["elite_trajectory_rows"]
                <= counts["frontier_trajectory_rows"],
            {
                "elite": counts["elite_trajectory_rows"],
                "frontier": counts["frontier_trajectory_rows"],
            },
            "elite <= frontier",
        )
        add_check(
            checks,
            "national_elite_endpoint_cohort_exists",
            counts["national_elite_trajectory_rows"] > 0,
            counts["national_elite_trajectory_rows"],
            "greater than 0",
        )
        add_check(
            checks,
            "championship_endpoint_cohort_exists",
            counts["championship_trajectory_rows"] > 0,
            counts["championship_trajectory_rows"],
            "greater than 0",
        )
        add_check(
            checks,
            "championship_is_subset_of_national_elite",
            counts["championship_trajectory_rows"]
                <= counts["national_elite_trajectory_rows"],
            {
                "championship": counts["championship_trajectory_rows"],
                "national_elite":
                    counts["national_elite_trajectory_rows"],
            },
            "championship <= national elite",
        )
        add_check(
            checks,
            "elite_contribution_units_exist",
            (
                counts["athlete_unit_rows"] > 0
                and counts["event_unit_rows"] > 0
                and counts["group_unit_rows"] > 0
            ),
            {
                "athlete": counts["athlete_unit_rows"],
                "event": counts["event_unit_rows"],
                "group": counts["group_unit_rows"],
            },
            "all greater than 0",
        )
        add_check(
            checks,
            "elite_rankings_exist",
            counts["ranking_rows"] > 0,
            counts["ranking_rows"],
            "greater than 0",
        )

        for name, field in [
            ("frontier_threshold_valid", "invalid_frontier_rows"),
            ("elite_threshold_valid", "invalid_elite_rows"),
            (
                "national_elite_endpoint_threshold_valid",
                "invalid_national_elite_rows",
            ),
            (
                "championship_endpoint_threshold_valid",
                "invalid_championship_rows",
            ),
            ("elite_rows_nested_in_frontier", "elite_not_nested_rows"),
            (
                "championship_rows_nested_in_national_elite",
                "championship_not_nested_rows",
            ),
            ("athlete_unit_ids_unique", "duplicate_athlete_unit_ids"),
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
        ]:
            add_check(
                checks,
                name,
                quality[field] == 0,
                quality[field],
                0,
            )

        # --------------------------------------------------------------
        # Exports
        # --------------------------------------------------------------
        export_query(
            con,
            """
            SELECT *
            FROM elite_cohort_registry
            ORDER BY minimum_level
            """,
            OUTPUT_DIR / "elite_cohort_registry.csv",
        )
        export_query(
            con,
            """
            SELECT *
            FROM elite_season_coverage
            ORDER BY cohort_key, season_year, season_type
            """,
            OUTPUT_DIR / "elite_season_coverage.csv",
        )
        export_query(
            con,
            """
            SELECT *
            FROM seasonal_elite_rankings
            WHERE ranking_scope = 'elite_overall_combined'
            ORDER BY
                cohort_key,
                season_year,
                season_type,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "elite_season_overall_rankings.csv",
        )
        export_query(
            con,
            """
            SELECT *
            FROM seasonal_elite_rankings
            WHERE ranking_scope = 'elite_overall_gender'
            ORDER BY
                cohort_key,
                season_year,
                season_type,
                gender_scope,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "elite_season_gender_rankings.csv",
        )
        export_query(
            con,
            """
            SELECT *
            FROM seasonal_elite_rankings
            WHERE ranking_scope = 'elite_event_gender'
            ORDER BY
                cohort_key,
                season_year,
                season_type,
                gender_scope,
                ranking_label,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "elite_season_event_gender_rankings.csv",
        )
        export_query(
            con,
            """
            SELECT *
            FROM seasonal_elite_rankings
            WHERE ranking_scope = 'elite_event_combined'
            ORDER BY
                cohort_key,
                season_year,
                season_type,
                ranking_label,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "elite_season_event_combined_rankings.csv",
        )
        export_query(
            con,
            """
            SELECT *
            FROM seasonal_elite_rankings
            WHERE ranking_scope = 'elite_group_gender'
            ORDER BY
                cohort_key,
                season_year,
                season_type,
                gender_scope,
                ranking_label,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "elite_season_group_gender_rankings.csv",
        )
        export_query(
            con,
            """
            SELECT *
            FROM seasonal_elite_rankings
            WHERE ranking_scope = 'elite_group_combined'
            ORDER BY
                cohort_key,
                season_year,
                season_type,
                ranking_label,
                official_rank_eligible DESC,
                official_rank NULLS LAST,
                all_school_rank,
                school_name
            """,
            OUTPUT_DIR / "elite_season_group_combined_rankings.csv",
        )
        export_query(
            con,
            """
            SELECT *
            FROM elite_partition_summary
            ORDER BY
                cohort_key,
                season_year,
                season_type,
                ranking_scope,
                gender_scope,
                ranking_label
            """,
            OUTPUT_DIR / "elite_partition_summary.csv",
        )
        export_query(
            con,
            """
            SELECT
                cohort_key,
                cohort_label,
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
                season_centered_posterior_score,
                posterior_ci95_lower,
                posterior_ci95_upper,
                athlete_unit_count,
                mean_baseline_level,
                mean_endpoint_level,
                evidence_category
            FROM seasonal_elite_rankings
            WHERE official_rank = 1
            ORDER BY
                cohort_key,
                season_year,
                season_type,
                ranking_scope,
                gender_scope,
                ranking_label
            """,
            OUTPUT_DIR / "elite_season_leaders.csv",
        )

        methodology_rows = [
            {
                "cohort_key": "frontier_70_plus",
                "cohort_label": "Frontier (Baseline 70+)",
                "selection_basis": "baseline",
                "minimum_level": FRONTIER_MINIMUM,
                "interpretation":
                    "Development among athletes beginning near the performance frontier.",
            },
            {
                "cohort_key": "elite_80_plus",
                "cohort_label": "Elite (Baseline 80+)",
                "selection_basis": "baseline",
                "minimum_level": ELITE_MINIMUM,
                "interpretation":
                    "Development among athletes beginning at an elite normalized level.",
            },
            {
                "cohort_key": "national_elite_endpoint_90_plus",
                "cohort_label":
                    "National Elite Finishers (Endpoint 90+)",
                "selection_basis": "endpoint",
                "minimum_level": NATIONAL_ELITE_ENDPOINT_MINIMUM,
                "interpretation":
                    "Development among athletes finishing at a nationally elite level.",
            },
            {
                "cohort_key": "championship_endpoint_95_plus",
                "cohort_label":
                    "Championship-Caliber Finishers (Endpoint 95+)",
                "selection_basis": "endpoint",
                "minimum_level": CHAMPIONSHIP_ENDPOINT_MINIMUM,
                "interpretation":
                    "Development among athletes finishing extremely close to the collegiate frontier.",
            },
        ]
        write_csv(
            OUTPUT_DIR / "elite_ranking_methodology.csv",
            methodology_rows,
            [
                "cohort_key",
                "cohort_label",
                "selection_basis",
                "minimum_level",
                "interpretation",
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
                'input_phase_6a_version',
                '{INPUT_DATASET_VERSION}'
            UNION ALL
            SELECT
                'frontier_minimum',
                '{FRONTIER_MINIMUM}'
            UNION ALL
            SELECT
                'elite_minimum',
                '{ELITE_MINIMUM}'
            UNION ALL
            SELECT
                'national_elite_endpoint_minimum',
                '{NATIONAL_ELITE_ENDPOINT_MINIMUM}'
            UNION ALL
            SELECT
                'championship_endpoint_minimum',
                '{CHAMPIONSHIP_ENDPOINT_MINIMUM}'
            UNION ALL
            SELECT
                'national_elite_combined_overall_min_sample',
                '{NATIONAL_ELITE_COMBINED_OVERALL_MIN_SAMPLE}'
            UNION ALL
            SELECT
                'championship_combined_overall_min_sample',
                '{CHAMPIONSHIP_COMBINED_OVERALL_MIN_SAMPLE}'
            UNION ALL
            SELECT
                'championship_publication_tier',
                'exploratory_extreme_elite'
            UNION ALL
            SELECT
                'cohort_count',
                '4'
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
        "MILESTONE 6 PHASE 6B — "
        "SEASONAL FRONTIER, ELITE, AND CHAMPIONSHIP-CALIBER DEVELOPMENT RANKINGS",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "COHORTS",
        "-" * 78,
        f"Frontier: baseline stable level >= {FRONTIER_MINIMUM:g}",
        f"Elite: baseline stable level >= {ELITE_MINIMUM:g}",
        f"National Elite Finishers: endpoint stable level >= "
        f"{NATIONAL_ELITE_ENDPOINT_MINIMUM:g}",
        f"Championship-Caliber Finishers: endpoint stable level >= "
        f"{CHAMPIONSHIP_ENDPOINT_MINIMUM:g}",
        "",
        "RESULTS",
        "-" * 78,
        f"Source trajectories: "
        f"{int(counts['source_trajectory_rows']):,}",
        f"Frontier trajectory rows: "
        f"{int(counts['frontier_trajectory_rows']):,}",
        f"Elite trajectory rows: "
        f"{int(counts['elite_trajectory_rows']):,}",
        f"National elite endpoint rows: "
        f"{int(counts['national_elite_trajectory_rows']):,}",
        f"Championship-caliber endpoint rows: "
        f"{int(counts['championship_trajectory_rows']):,}",
        f"Season-athlete contribution rows: "
        f"{int(counts['athlete_unit_rows']):,}",
        f"Season-event contribution rows: "
        f"{int(counts['event_unit_rows']):,}",
        f"Season-group contribution rows: "
        f"{int(counts['group_unit_rows']):,}",
        f"All ranking rows: {int(counts['ranking_rows']):,}",
        f"Official ranking rows: "
        f"{int(counts['official_ranking_rows']):,}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Seasonal frontier and elite rankings published."
            if not failed
            else "FAIL — Review hard checks before publication."
        ),
    ]

    (OUTPUT_DIR / "phase_6b_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Frontier trajectory rows: "
        f"{int(counts['frontier_trajectory_rows']):,}"
    )
    print(
        f"Elite trajectory rows: "
        f"{int(counts['elite_trajectory_rows']):,}"
    )
    print(
        f"National elite endpoint rows: "
        f"{int(counts['national_elite_trajectory_rows']):,}"
    )
    print(
        f"Championship-caliber endpoint rows: "
        f"{int(counts['championship_trajectory_rows']):,}"
    )
    print(
        f"Season-athlete contribution rows: "
        f"{int(counts['athlete_unit_rows']):,}"
    )
    print(
        f"Season-event contribution rows: "
        f"{int(counts['event_unit_rows']):,}"
    )
    print(
        f"Season-group contribution rows: "
        f"{int(counts['group_unit_rows']):,}"
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
    print("Next: review cohort coverage and recent-season leaders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
