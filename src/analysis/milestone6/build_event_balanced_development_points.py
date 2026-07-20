#!/usr/bin/env python3
"""
Milestone 6 Phase 6D — Athlete-Level Event-Balanced Development Points

This is the primary multi-event development ranking.

Core principle
--------------
The original athlete development formula is preserved:

    athlete development signal
    = observed improvement
      - cross-fitted expected improvement

The existing normalized performance-level scale, stable-period construction,
baseline difficulty, human-limit proximity, school attribution, and expected
improvement model are therefore retained.

Every publishable NCAA championship event has one positive point pool:

    positive event pool = 100,000 points

The pool is allocated to individual athlete-school-event units:

    positive scale
    = 100,000 / sum(max(athlete development signal, 0))

    athlete points
    = athlete development signal * positive scale

Consequences:
- Positive athlete points sum to exactly 100,000 in every event partition.
- Negative athlete signals receive negative points using the same conversion.
- Negative points do not consume or reduce the 100,000 positive pool.
- School event points are sums of their athletes' points.
- There is no top-eight cutoff and no school-rank point simulation.
- Participation-heavy events cannot receive a larger positive pool.

Athlete unit
------------
One athlete is counted once per school, event, cohort, and time partition.
Multiple underlying trajectories in the same unit are averaged, preventing
duplicate trajectory or meet volume from multiplying that athlete's signal.

Primary outputs
---------------
- Athlete event contributions
- School event positive, negative, and net points
- Overall event-balanced school rankings
- Coaching-group rankings with 100,000 positive points per group
- Broad, Frontier, Elite, Endpoint 90+, and Endpoint 95+ cohorts
- All-time, all-time indoor/outdoor, and single-season rankings
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


ROOT = Path.cwd()

PHASE_5J_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5j_event_and_group_rankings"
)
PHASE_5J_DB = (
    PHASE_5J_DIR / "ncaa_d1_event_development_rankings_v1.duckdb"
)
PHASE_5J_CHECKS = PHASE_5J_DIR / "hard_checks.csv"

PHASE_6A_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "seasonal_development_rankings_v1/"
      "phase_6a_seasonal_rankings"
)
PHASE_6A_DB = PHASE_6A_DIR / "seasonal_development_rankings_v1.duckdb"
PHASE_6A_CHECKS = PHASE_6A_DIR / "hard_checks.csv"

PHASE_6B_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "seasonal_elite_development_v1/"
      "phase_6b_seasonal_elite_rankings"
)
PHASE_6B_DB = (
    PHASE_6B_DIR / "seasonal_elite_development_rankings_v1.duckdb"
)
PHASE_6B_CHECKS = PHASE_6B_DIR / "hard_checks.csv"

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "event_balanced_development_points_v1/"
      "phase_6d_event_balanced_points"
)
OUTPUT_DB = OUTPUT_DIR / "event_balanced_development_points_v1.duckdb"

INPUT_PHASE_5J_VERSION = "ncaa_d1_event_development_rankings_v1_1"
INPUT_PHASE_6A_VERSION = "seasonal_development_rankings_v1_1"
INPUT_PHASE_6B_VERSION = "seasonal_elite_development_rankings_v1_2"

DATASET_VERSION = "event_balanced_development_points_v4_1"
POLICY_VERSION = "athlete_signal_equal_100k_positive_event_pool_v1"
GROUP_TAXONOMY_VERSION = "balanced_coaching_groups_v1"

EVENT_POSITIVE_BUDGET = 100_000.0
GROUP_POSITIVE_BUDGET = 100_000.0
POINT_TOLERANCE = 1e-6
SIGNAL_TOLERANCE = 1e-12

EXPECTED_GROUPS = 7
EXPECTED_COHORTS = 5

COHORTS = (
    (
        "broad_all_athletes",
        "Broad — All Athletes",
        "standard_primary",
    ),
    (
        "frontier_70_plus",
        "Frontier — Baseline 70+",
        "standard_development",
    ),
    (
        "elite_80_plus",
        "Elite — Baseline 80+",
        "standard_development",
    ),
    (
        "national_elite_endpoint_90_plus",
        "National Elite Finishers — Endpoint 90+",
        "provisional_national_elite",
    ),
    (
        "championship_endpoint_95_plus",
        "Championship-Caliber Finishers — Endpoint 95+",
        "exploratory_extreme_elite",
    ),
)

COMMON_INDOOR_EVENTS = (
    ("60m", "sprints", "Sprints"),
    ("200m", "sprints", "Sprints"),
    ("400m", "sprints", "Sprints"),
    ("800m", "middle_distance", "Middle Distance"),
    ("Mile", "middle_distance", "Middle Distance"),
    ("3000m", "distance", "Distance"),
    ("5000m", "distance", "Distance"),
    ("60m Hurdles", "hurdles", "Hurdles"),
    ("High Jump", "jumps", "Jumps"),
    ("Pole Vault", "jumps", "Jumps"),
    ("Long Jump", "jumps", "Jumps"),
    ("Triple Jump", "jumps", "Jumps"),
    ("Shot Put", "throws", "Throws"),
    ("Weight Throw", "throws", "Throws"),
)

COMMON_OUTDOOR_EVENTS = (
    ("100m", "sprints", "Sprints"),
    ("200m", "sprints", "Sprints"),
    ("400m", "sprints", "Sprints"),
    ("800m", "middle_distance", "Middle Distance"),
    ("1500m", "middle_distance", "Middle Distance"),
    ("5000m", "distance", "Distance"),
    ("10000m", "distance", "Distance"),
    ("3000m Steeplechase", "distance", "Distance"),
    ("400m Hurdles", "hurdles", "Hurdles"),
    ("High Jump", "jumps", "Jumps"),
    ("Pole Vault", "jumps", "Jumps"),
    ("Long Jump", "jumps", "Jumps"),
    ("Triple Jump", "jumps", "Jumps"),
    ("Shot Put", "throws", "Throws"),
    ("Discus Throw", "throws", "Throws"),
    ("Hammer Throw", "throws", "Throws"),
    ("Javelin Throw", "throws", "Throws"),
)

GENDER_SPECIFIC_EVENTS = (
    (
        "indoor",
        "m",
        "Heptathlon",
        "combined_events",
        "Combined Events",
    ),
    (
        "indoor",
        "f",
        "Pentathlon",
        "combined_events",
        "Combined Events",
    ),
    (
        "outdoor",
        "m",
        "110m Hurdles",
        "hurdles",
        "Hurdles",
    ),
    (
        "outdoor",
        "f",
        "100m Hurdles",
        "hurdles",
        "Hurdles",
    ),
    (
        "outdoor",
        "m",
        "Decathlon",
        "combined_events",
        "Combined Events",
    ),
    (
        "outdoor",
        "f",
        "Heptathlon",
        "combined_events",
        "Combined Events",
    ),
)


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


def hard_checks_pass(path: Path) -> bool:
    rows = read_csv(path)
    return bool(rows) and all(row.get("status") == "PASS" for row in rows)


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


def championship_registry_rows() -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []

    for gender in ("m", "f"):
        for event_name, group_key, group_label in COMMON_INDOOR_EVENTS:
            rows.append(
                (
                    "indoor",
                    gender,
                    event_name,
                    group_key,
                    group_label,
                )
            )
        for event_name, group_key, group_label in COMMON_OUTDOOR_EVENTS:
            rows.append(
                (
                    "outdoor",
                    gender,
                    event_name,
                    group_key,
                    group_label,
                )
            )

    rows.extend(GENDER_SPECIFIC_EVENTS)
    return rows


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("MILESTONE 6 PHASE 6D — ATHLETE-LEVEL EVENT-BALANCED POINTS")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Positive event budget: {EVENT_POSITIVE_BUDGET:,.0f}")
    print(f"Positive group budget: {GROUP_POSITIVE_BUDGET:,.0f}")
    print(f"Output database: {OUTPUT_DB}")

    checks: list[dict[str, Any]] = []

    required_inputs = (
        PHASE_5J_DB,
        PHASE_5J_CHECKS,
        PHASE_6A_DB,
        PHASE_6A_CHECKS,
        PHASE_6B_DB,
        PHASE_6B_CHECKS,
    )
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
        print("PHASE GATE: FAIL — Required inputs are missing.")
        return 1

    upstream_gates = {
        "phase_5j_gate_passed": hard_checks_pass(PHASE_5J_CHECKS),
        "phase_6a_gate_passed": hard_checks_pass(PHASE_6A_CHECKS),
        "phase_6b_gate_passed": hard_checks_pass(PHASE_6B_CHECKS),
    }
    for name, passed in upstream_gates.items():
        add_check(checks, name, passed, passed, True)

    if not all(upstream_gates.values()):
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — An upstream phase did not pass.")
        return 1

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
            f"ATTACH '{sql_path(PHASE_5J_DB)}' AS p5j (READ_ONLY)"
        )
        con.execute(
            f"ATTACH '{sql_path(PHASE_6A_DB)}' AS p6a (READ_ONLY)"
        )
        con.execute(
            f"ATTACH '{sql_path(PHASE_6B_DB)}' AS p6b (READ_ONLY)"
        )

        versions = {}
        for schema_name in ("p5j", "p6a", "p6b"):
            versions[schema_name] = dict(
                con.execute(
                    f"""
                    SELECT metadata_key, metadata_value
                    FROM {schema_name}.main.dataset_metadata
                    """
                ).fetchall()
            ).get("dataset_version")

        expected_versions = {
            "p5j": INPUT_PHASE_5J_VERSION,
            "p6a": INPUT_PHASE_6A_VERSION,
            "p6b": INPUT_PHASE_6B_VERSION,
        }
        for schema_name, expected in expected_versions.items():
            add_check(
                checks,
                f"{schema_name}_version_matches",
                versions[schema_name] == expected,
                versions[schema_name],
                expected,
            )

        con.execute(
            """
            CREATE TABLE school_metadata AS
            SELECT *
            FROM p6a.main.school_metadata
            """
        )
        con.execute(
            """
            CREATE TABLE event_taxonomy AS
            SELECT *
            FROM p6a.main.event_taxonomy
            """
        )

        con.execute(
            """
            CREATE TABLE cohort_registry (
                cohort_key VARCHAR,
                cohort_label VARCHAR,
                publication_tier VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO cohort_registry VALUES (?, ?, ?)",
            COHORTS,
        )

        con.execute(
            """
            CREATE TABLE championship_event_registry (
                source_season_type VARCHAR,
                gender_scope VARCHAR,
                canonical_event_name VARCHAR,
                balanced_group_key VARCHAR,
                balanced_group_label VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO championship_event_registry VALUES (?, ?, ?, ?, ?)",
            championship_registry_rows(),
        )

        con.execute(
            f"""
            CREATE TABLE balanced_event_registry AS
            SELECT
                r.source_season_type,
                r.gender_scope,
                t.canonical_event_code,
                r.canonical_event_name,
                r.balanced_group_key,
                r.balanced_group_label,
                '{GROUP_TAXONOMY_VERSION}' AS taxonomy_version
            FROM championship_event_registry r
            JOIN event_taxonomy t
              ON LOWER(r.canonical_event_name)
                    = LOWER(t.canonical_event_name)
            """
        )

        # --------------------------------------------------------------
        # Preserve the original trajectory-level development signal.
        # --------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE source_trajectory_rows AS
            SELECT
                'broad_all_athletes' AS cohort_key,
                'Broad — All Athletes' AS cohort_label,
                'standard_primary' AS publication_tier,
                t.canonical_person_id,
                t.athlete_id,
                t.athlete_name,
                t.resolved_school_id,
                t.canonical_gender_code,
                t.canonical_event_code,
                t.canonical_event_name,
                t.event_family,
                t.school_stint_id,
                t.baseline_stable_level,
                t.endpoint_stable_level,
                t.observed_improvement,
                t.expected_improvement,
                t.athlete_value_added,
                t.annualized_athlete_value_added,
                t.training_support_n,
                t.endpoint_season_year,
                LOWER(t.season_type) AS source_season_type
            FROM p6a.main.trajectory_snapshot t

            UNION ALL

            SELECT
                t.cohort_key,
                t.cohort_label,
                CASE
                    WHEN t.cohort_key
                        = 'national_elite_endpoint_90_plus'
                        THEN 'provisional_national_elite'
                    WHEN t.cohort_key
                        = 'championship_endpoint_95_plus'
                        THEN 'exploratory_extreme_elite'
                    ELSE 'standard_development'
                END AS publication_tier,
                t.canonical_person_id,
                t.athlete_id,
                t.athlete_name,
                t.resolved_school_id,
                t.canonical_gender_code,
                t.canonical_event_code,
                t.canonical_event_name,
                t.event_family,
                t.school_stint_id,
                t.baseline_stable_level,
                t.endpoint_stable_level,
                t.observed_improvement,
                t.expected_improvement,
                t.athlete_value_added,
                t.annualized_athlete_value_added,
                t.training_support_n,
                t.endpoint_season_year,
                LOWER(t.season_type)
            FROM p6b.main.elite_trajectory_snapshot t
            """
        )

        # Expand broad trajectories into all-time, season-type all-time,
        # and single-season scopes. Elite cohorts are seasonal only.
        con.execute(
            """
            CREATE TABLE trajectory_scope_rows AS
            SELECT
                t.*,
                'all_time' AS time_scope,
                NULL::INTEGER AS season_year,
                'all' AS season_type,
                'all_time' AS season_key,
                'All Time' AS season_label
            FROM source_trajectory_rows t
            WHERE t.cohort_key = 'broad_all_athletes'

            UNION ALL

            SELECT
                t.*,
                'all_time_season_type',
                NULL::INTEGER,
                t.source_season_type,
                'all_time_' || t.source_season_type,
                'All-Time '
                    || CASE
                        WHEN LOWER(t.source_season_type) = 'indoor'
                            THEN 'Indoor'
                        WHEN LOWER(t.source_season_type) = 'outdoor'
                            THEN 'Outdoor'
                        ELSE t.source_season_type
                    END
            FROM source_trajectory_rows t
            WHERE t.cohort_key = 'broad_all_athletes'

            UNION ALL

            SELECT
                t.*,
                'single_season',
                t.endpoint_season_year,
                t.source_season_type,
                t.endpoint_season_year::VARCHAR
                    || '_'
                    || t.source_season_type,
                t.endpoint_season_year::VARCHAR
                    || ' '
                    || CASE
                        WHEN LOWER(t.source_season_type) = 'indoor'
                            THEN 'Indoor'
                        WHEN LOWER(t.source_season_type) = 'outdoor'
                            THEN 'Outdoor'
                        ELSE t.source_season_type
                    END
            FROM source_trajectory_rows t
            """
        )

        # --------------------------------------------------------------
        # Publishable event partitions use the existing uncertainty and
        # sample-size gates, but every athlete unit inside a publishable
        # partition may contribute points.
        # --------------------------------------------------------------
        con.execute(
            """
            CREATE TABLE publishable_event_partitions AS
            SELECT DISTINCT
                'broad_all_athletes' AS cohort_key,
                'all_time' AS time_scope,
                NULL::INTEGER AS season_year,
                'all' AS season_type,
                r.gender_scope,
                r.ranking_key AS canonical_event_code
            FROM p5j.main.event_and_group_rankings r
            WHERE r.ranking_scope = 'gender_event'
              AND r.official_rank_eligible

            UNION ALL

            SELECT DISTINCT
                'broad_all_athletes',
                'all_time_season_type',
                NULL::INTEGER,
                LOWER(r.season_scope),
                r.gender_scope,
                r.ranking_key
            FROM p5j.main.event_and_group_rankings r
            WHERE r.ranking_scope = 'gender_season_event'
              AND r.official_rank_eligible

            UNION ALL

            SELECT DISTINCT
                'broad_all_athletes',
                'single_season',
                r.season_year,
                LOWER(r.season_type),
                r.gender_scope,
                r.ranking_key
            FROM p6a.main.seasonal_rankings r
            WHERE r.ranking_scope = 'season_event_gender'
              AND r.official_rank_eligible

            UNION ALL

            SELECT DISTINCT
                r.cohort_key,
                'single_season',
                r.season_year,
                LOWER(r.season_type),
                r.gender_scope,
                r.ranking_key
            FROM p6b.main.seasonal_elite_rankings r
            WHERE r.ranking_scope = 'elite_event_gender'
              AND r.official_rank_eligible
            """
        )

        # One athlete-school-event unit. Multiple trajectories in the same
        # unit are averaged so trajectory count does not multiply points.
        con.execute(
            f"""
            CREATE TABLE athlete_event_development_units AS
            SELECT
                s.cohort_key,
                ANY_VALUE(s.cohort_label) AS cohort_label,
                ANY_VALUE(s.publication_tier)
                    AS publication_tier,
                s.time_scope,
                s.season_year,
                s.season_type,
                ANY_VALUE(s.season_key) AS season_key,
                ANY_VALUE(s.season_label) AS season_label,
                s.canonical_gender_code AS gender_scope,
                s.canonical_event_code,
                ANY_VALUE(s.canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(e.balanced_group_key)
                    AS balanced_group_key,
                ANY_VALUE(e.balanced_group_label)
                    AS balanced_group_label,
                s.canonical_person_id,
                ANY_VALUE(s.athlete_id) AS athlete_id,
                ANY_VALUE(s.athlete_name) AS athlete_name,
                s.resolved_school_id,
                ANY_VALUE(m.school_name) AS school_name,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT s.school_stint_id)
                    AS school_stint_count,
                AVG(s.baseline_stable_level)
                    AS mean_baseline_level,
                AVG(s.endpoint_stable_level)
                    AS mean_endpoint_level,
                AVG(s.observed_improvement)
                    AS mean_observed_improvement,
                AVG(s.expected_improvement)
                    AS mean_expected_improvement,
                AVG(s.athlete_value_added)
                    AS athlete_development_signal,
                AVG(s.annualized_athlete_value_added)
                    AS annualized_development_signal,
                MIN(s.training_support_n)
                    AS minimum_training_support,
                '{DATASET_VERSION}' AS dataset_version
            FROM trajectory_scope_rows s
            JOIN publishable_event_partitions p
              ON s.cohort_key = p.cohort_key
             AND s.time_scope = p.time_scope
             AND s.season_year IS NOT DISTINCT FROM p.season_year
             AND s.season_type = p.season_type
             AND s.canonical_gender_code = p.gender_scope
             AND s.canonical_event_code = p.canonical_event_code
            JOIN balanced_event_registry e
              ON s.source_season_type = e.source_season_type
             AND s.canonical_gender_code = e.gender_scope
             AND s.canonical_event_code = e.canonical_event_code
            JOIN school_metadata m
              USING (resolved_school_id)
            GROUP BY
                s.cohort_key,
                s.time_scope,
                s.season_year,
                s.season_type,
                s.canonical_gender_code,
                s.canonical_event_code,
                s.canonical_person_id,
                s.resolved_school_id
            """
        )

        event_partition = """
            cohort_key,
            time_scope,
            season_year,
            season_type,
            gender_scope,
            canonical_event_code
        """

        # --------------------------------------------------------------
        # Athlete-level point allocation.
        # Positive signal receives the fixed 100,000 pool.
        # Negative signal uses the same scale and remains negative.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE athlete_event_development_points AS
            WITH signal_parts AS (
                SELECT
                    *,
                    GREATEST(
                        athlete_development_signal,
                        0.0
                    ) AS positive_development_signal,
                    LEAST(
                        athlete_development_signal,
                        0.0
                    ) AS negative_development_signal
                FROM athlete_event_development_units
            ),
            partition_totals AS (
                SELECT
                    *,
                    SUM(positive_development_signal) OVER (
                        PARTITION BY {event_partition}
                    ) AS total_positive_development_signal,
                    SUM(negative_development_signal) OVER (
                        PARTITION BY {event_partition}
                    ) AS total_negative_development_signal,
                    COUNT(*) OVER (
                        PARTITION BY {event_partition}
                    ) AS event_athlete_unit_count,
                    COUNT(DISTINCT resolved_school_id) OVER (
                        PARTITION BY {event_partition}
                    ) AS event_school_count
                FROM signal_parts
            )
            SELECT
                *,
                CASE
                    WHEN total_positive_development_signal
                            > {SIGNAL_TOLERANCE}
                        THEN {EVENT_POSITIVE_BUDGET}
                            / total_positive_development_signal
                    ELSE NULL
                END AS points_per_development_unit,
                positive_development_signal
                    * points_per_development_unit
                    AS athlete_positive_points,
                negative_development_signal
                    * points_per_development_unit
                    AS athlete_negative_points,
                athlete_development_signal
                    * points_per_development_unit
                    AS athlete_net_points,
                positive_development_signal
                    / NULLIF(
                        total_positive_development_signal,
                        0
                    ) AS positive_event_point_share,
                athlete_development_signal
                    / NULLIF(
                        total_positive_development_signal,
                        0
                    ) AS net_event_point_share,
                CASE
                    WHEN athlete_development_signal
                            > {SIGNAL_TOLERANCE}
                        THEN 'positive_development'
                    WHEN athlete_development_signal
                            < -{SIGNAL_TOLERANCE}
                        THEN 'negative_regression'
                    ELSE 'neutral_development'
                END AS development_direction,
                {EVENT_POSITIVE_BUDGET}::DOUBLE
                    AS positive_event_budget,
                '{POLICY_VERSION}' AS policy_version
            FROM partition_totals
            WHERE total_positive_development_signal
                    > {SIGNAL_TOLERANCE}
            """
        )

        # --------------------------------------------------------------
        # School event totals are direct sums of athlete points.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE school_event_development_points AS
            WITH school_totals AS (
                SELECT
                    {event_partition},
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(publication_tier)
                        AS publication_tier,
                    ANY_VALUE(season_key) AS season_key,
                    ANY_VALUE(season_label) AS season_label,
                    ANY_VALUE(canonical_event_name)
                        AS canonical_event_name,
                    ANY_VALUE(balanced_group_key)
                        AS balanced_group_key,
                    ANY_VALUE(balanced_group_label)
                        AS balanced_group_label,
                    resolved_school_id,
                    ANY_VALUE(school_name) AS school_name,
                    COUNT(*) AS athlete_unit_count,
                    COUNT(*) FILTER (
                        WHERE development_direction
                            = 'positive_development'
                    ) AS positive_athlete_count,
                    COUNT(*) FILTER (
                        WHERE development_direction
                            = 'negative_regression'
                    ) AS negative_athlete_count,
                    COUNT(*) FILTER (
                        WHERE development_direction
                            = 'neutral_development'
                    ) AS neutral_athlete_count,
                    SUM(trajectory_count) AS trajectory_count,
                    AVG(mean_baseline_level)
                        AS mean_baseline_level,
                    AVG(mean_endpoint_level)
                        AS mean_endpoint_level,
                    AVG(mean_observed_improvement)
                        AS mean_observed_improvement,
                    AVG(mean_expected_improvement)
                        AS mean_expected_improvement,
                    AVG(athlete_development_signal)
                        AS school_mean_development_signal,
                    SUM(athlete_development_signal)
                        AS school_total_development_signal,
                    SUM(positive_development_signal)
                        AS school_positive_development_signal,
                    SUM(negative_development_signal)
                        AS school_negative_development_signal,
                    SUM(athlete_positive_points)
                        AS positive_event_points,
                    SUM(athlete_negative_points)
                        AS negative_event_points,
                    SUM(athlete_net_points)
                        AS net_event_points,
                    MIN(minimum_training_support)
                        AS minimum_training_support,
                    MAX(event_athlete_unit_count)
                        AS event_athlete_unit_count,
                    MAX(event_school_count)
                        AS event_school_count,
                    MAX(points_per_development_unit)
                        AS points_per_development_unit
                FROM athlete_event_development_points
                GROUP BY
                    {event_partition},
                    resolved_school_id
            ),
            ranked AS (
                SELECT
                    *,
                    RANK() OVER (
                        PARTITION BY {event_partition}
                        ORDER BY
                            net_event_points DESC,
                            positive_event_points DESC,
                            athlete_unit_count DESC
                    ) AS source_rank,
                    COUNT(*) OVER (
                        PARTITION BY {event_partition}
                    ) AS ranked_school_count
                FROM school_totals
            )
            SELECT
                *,
                net_event_points AS event_balanced_points,
                positive_event_points / {EVENT_POSITIVE_BUDGET}
                    AS positive_event_point_share,
                net_event_points / {EVENT_POSITIVE_BUDGET}
                    AS event_point_share,
                school_mean_development_signal
                    AS posterior_school_score,
                school_positive_development_signal
                    AS relative_development_strength,
                NULL::DOUBLE AS posterior_ci95_lower,
                NULL::DOUBLE AS posterior_ci95_upper,
                CASE
                    WHEN athlete_unit_count >= 8
                        THEN 'strong_sample'
                    WHEN athlete_unit_count >= 5
                        THEN 'moderate_sample'
                    WHEN athlete_unit_count >= 3
                        THEN 'limited_sample'
                    ELSE 'single_or_small_sample'
                END AS evidence_category,
                CASE
                    WHEN athlete_unit_count >= 8
                        THEN 'high'
                    WHEN athlete_unit_count >= 5
                        THEN 'medium'
                    ELSE 'low'
                END AS reliability_tier,
                CASE
                    WHEN positive_event_points > 0
                        THEN 'positive_formula_share'
                    WHEN negative_event_points < 0
                        THEN 'negative_regression_only'
                    ELSE 'neutral'
                END AS scoring_status,
                {EVENT_POSITIVE_BUDGET}::DOUBLE
                    AS event_budget,
                'athlete_original_value_added_linear_allocation'
                    AS point_distribution_method,
                '{DATASET_VERSION}' AS dataset_version,
                '{POLICY_VERSION}' AS policy_version
            FROM ranked
            """
        )

        # --------------------------------------------------------------
        # Event budget audit: positive pool is exactly 100,000.
        # Negative points are reported separately and never enter the pool.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE event_budget_audit AS
            SELECT
                {event_partition},
                ANY_VALUE(cohort_label) AS cohort_label,
                ANY_VALUE(season_key) AS season_key,
                ANY_VALUE(season_label) AS season_label,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(balanced_group_key)
                    AS balanced_group_key,
                ANY_VALUE(balanced_group_label)
                    AS balanced_group_label,
                COUNT(*) AS ranked_school_count,
                SUM(athlete_unit_count)
                    AS athlete_unit_count,
                SUM(positive_event_points)
                    AS distributed_positive_event_points,
                SUM(negative_event_points)
                    AS distributed_negative_event_points,
                SUM(net_event_points)
                    AS distributed_net_event_points,
                SUM(positive_event_points)
                    AS distributed_event_points,
                {EVENT_POSITIVE_BUDGET}::DOUBLE
                    AS required_positive_event_points,
                SUM(positive_event_points)
                    - {EVENT_POSITIVE_BUDGET}
                    AS positive_budget_difference
            FROM school_event_development_points
            GROUP BY {event_partition}
            """
        )

        # --------------------------------------------------------------
        # Overall event-balanced rankings.
        # --------------------------------------------------------------
        overall_gender_partition = """
            cohort_key,
            time_scope,
            season_year,
            season_type,
            gender_scope
        """

        con.execute(
            f"""
            CREATE TABLE event_balanced_overall_gender AS
            WITH partition_events AS (
                SELECT
                    {overall_gender_partition},
                    COUNT(DISTINCT canonical_event_code)
                        AS publishable_event_count
                FROM school_event_development_points
                GROUP BY {overall_gender_partition}
            ),
            school_totals AS (
                SELECT
                    {overall_gender_partition},
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(publication_tier)
                        AS publication_tier,
                    ANY_VALUE(season_key) AS season_key,
                    ANY_VALUE(season_label) AS season_label,
                    resolved_school_id,
                    ANY_VALUE(school_name) AS school_name,
                    SUM(positive_event_points)
                        AS total_positive_event_points,
                    SUM(negative_event_points)
                        AS total_negative_event_points,
                    SUM(net_event_points)
                        AS total_event_balanced_points,
                    SUM(athlete_unit_count)
                        AS athlete_event_unit_count,
                    COUNT(DISTINCT canonical_event_code) FILTER (
                        WHERE positive_event_points > 0
                    ) AS scoring_event_count,
                    COUNT(DISTINCT canonical_event_code)
                        AS represented_event_count
                FROM school_event_development_points
                GROUP BY
                    {overall_gender_partition},
                    resolved_school_id
            )
            SELECT
                s.*,
                p.publishable_event_count,
                p.publishable_event_count
                    * {EVENT_POSITIVE_BUDGET}
                    AS available_event_points,
                s.total_positive_event_points
                    / NULLIF(
                        p.publishable_event_count
                            * {EVENT_POSITIVE_BUDGET},
                        0
                    ) AS positive_share_of_available_points,
                s.total_event_balanced_points
                    / NULLIF(
                        p.publishable_event_count
                            * {EVENT_POSITIVE_BUDGET},
                        0
                    ) AS percent_of_available_points,
                RANK() OVER (
                    PARTITION BY {overall_gender_partition}
                    ORDER BY
                        s.total_event_balanced_points DESC,
                        s.total_positive_event_points DESC,
                        s.scoring_event_count DESC
                ) AS event_balanced_rank,
                '{DATASET_VERSION}' AS dataset_version
            FROM school_totals s
            JOIN partition_events p
              USING (
                cohort_key,
                time_scope,
                season_year,
                season_type,
                gender_scope
              )
            """
        )

        combined_partition = """
            cohort_key,
            time_scope,
            season_year,
            season_type
        """

        con.execute(
            f"""
            CREATE TABLE event_balanced_overall_combined AS
            WITH partition_events AS (
                SELECT
                    {combined_partition},
                    COUNT(DISTINCT
                        gender_scope || '|'
                        || canonical_event_code
                    ) AS publishable_event_count
                FROM school_event_development_points
                GROUP BY {combined_partition}
            ),
            school_totals AS (
                SELECT
                    {combined_partition},
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(publication_tier)
                        AS publication_tier,
                    ANY_VALUE(season_key) AS season_key,
                    ANY_VALUE(season_label) AS season_label,
                    resolved_school_id,
                    ANY_VALUE(school_name) AS school_name,
                    SUM(positive_event_points)
                        AS total_positive_event_points,
                    SUM(negative_event_points)
                        AS total_negative_event_points,
                    SUM(net_event_points)
                        AS total_event_balanced_points,
                    SUM(positive_event_points) FILTER (
                        WHERE gender_scope = 'm'
                    ) AS men_positive_event_points,
                    SUM(negative_event_points) FILTER (
                        WHERE gender_scope = 'm'
                    ) AS men_negative_event_points,
                    SUM(net_event_points) FILTER (
                        WHERE gender_scope = 'm'
                    ) AS men_event_balanced_points,
                    SUM(positive_event_points) FILTER (
                        WHERE gender_scope = 'f'
                    ) AS women_positive_event_points,
                    SUM(negative_event_points) FILTER (
                        WHERE gender_scope = 'f'
                    ) AS women_negative_event_points,
                    SUM(net_event_points) FILTER (
                        WHERE gender_scope = 'f'
                    ) AS women_event_balanced_points,
                    SUM(athlete_unit_count)
                        AS athlete_event_unit_count,
                    COUNT(DISTINCT
                        gender_scope || '|'
                        || canonical_event_code
                    ) FILTER (
                        WHERE positive_event_points > 0
                    ) AS scoring_event_count,
                    COUNT(DISTINCT
                        gender_scope || '|'
                        || canonical_event_code
                    ) AS represented_event_count
                FROM school_event_development_points
                GROUP BY
                    {combined_partition},
                    resolved_school_id
            )
            SELECT
                s.*,
                p.publishable_event_count,
                p.publishable_event_count
                    * {EVENT_POSITIVE_BUDGET}
                    AS available_event_points,
                s.total_positive_event_points
                    / NULLIF(
                        p.publishable_event_count
                            * {EVENT_POSITIVE_BUDGET},
                        0
                    ) AS positive_share_of_available_points,
                s.total_event_balanced_points
                    / NULLIF(
                        p.publishable_event_count
                            * {EVENT_POSITIVE_BUDGET},
                        0
                    ) AS percent_of_available_points,
                RANK() OVER (
                    PARTITION BY {combined_partition}
                    ORDER BY
                        s.total_event_balanced_points DESC,
                        s.total_positive_event_points DESC,
                        s.scoring_event_count DESC
                ) AS event_balanced_rank,
                '{DATASET_VERSION}' AS dataset_version
            FROM school_totals s
            JOIN partition_events p
              USING (
                cohort_key,
                time_scope,
                season_year,
                season_type
              )
            """
        )

        # --------------------------------------------------------------
        # Group points.
        # Each event already has a 100,000 positive pool. Dividing group
        # event sums by the number of publishable events produces exactly
        # one 100,000 positive group pool. Negative points use the same
        # divisor and remain separate.
        # --------------------------------------------------------------
        group_gender_partition = """
            cohort_key,
            time_scope,
            season_year,
            season_type,
            gender_scope,
            balanced_group_key
        """

        con.execute(
            f"""
            CREATE TABLE group_balanced_points_gender AS
            WITH group_events AS (
                SELECT
                    {group_gender_partition},
                    ANY_VALUE(balanced_group_label)
                        AS balanced_group_label,
                    COUNT(DISTINCT canonical_event_code)
                        AS group_event_count
                FROM school_event_development_points
                GROUP BY {group_gender_partition}
            ),
            school_group_totals AS (
                SELECT
                    {group_gender_partition},
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(publication_tier)
                        AS publication_tier,
                    ANY_VALUE(season_key) AS season_key,
                    ANY_VALUE(season_label) AS season_label,
                    ANY_VALUE(balanced_group_label)
                        AS balanced_group_label,
                    resolved_school_id,
                    ANY_VALUE(school_name) AS school_name,
                    SUM(positive_event_points)
                        AS raw_positive_group_points,
                    SUM(negative_event_points)
                        AS raw_negative_group_points,
                    SUM(net_event_points)
                        AS raw_net_group_points,
                    SUM(athlete_unit_count)
                        AS athlete_event_unit_count,
                    COUNT(DISTINCT canonical_event_code) FILTER (
                        WHERE positive_event_points > 0
                    ) AS group_scoring_event_count,
                    COUNT(DISTINCT canonical_event_code)
                        AS group_represented_event_count
                FROM school_event_development_points
                GROUP BY
                    {group_gender_partition},
                    resolved_school_id
            ),
            normalized AS (
                SELECT
                    s.*,
                    g.group_event_count,
                    s.raw_positive_group_points
                        / g.group_event_count
                        AS positive_group_points,
                    s.raw_negative_group_points
                        / g.group_event_count
                        AS negative_group_points,
                    s.raw_net_group_points
                        / g.group_event_count
                        AS group_balanced_points
                FROM school_group_totals s
                JOIN group_events g
                  USING (
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    gender_scope,
                    balanced_group_key
                  )
            )
            SELECT
                *,
                positive_group_points
                    / {GROUP_POSITIVE_BUDGET}
                    AS positive_group_point_share,
                group_balanced_points
                    / {GROUP_POSITIVE_BUDGET}
                    AS group_point_share,
                group_balanced_points
                    / {GROUP_POSITIVE_BUDGET}
                    AS group_strength_share,
                RANK() OVER (
                    PARTITION BY {group_gender_partition}
                    ORDER BY
                        group_balanced_points DESC,
                        positive_group_points DESC
                ) AS group_source_rank,
                COUNT(*) OVER (
                    PARTITION BY {group_gender_partition}
                ) AS group_ranked_school_count,
                {GROUP_POSITIVE_BUDGET}::DOUBLE
                    AS group_budget,
                CASE
                    WHEN positive_group_points > 0
                        THEN 'positive_formula_share'
                    WHEN negative_group_points < 0
                        THEN 'negative_regression_only'
                    ELSE 'neutral'
                END AS scoring_status,
                'mean_of_equal_event_athlete_point_pools'
                    AS point_distribution_method,
                '{DATASET_VERSION}' AS dataset_version
            FROM normalized
            """
        )

        # Combined-gender group points use equal gender weight when both
        # gender partitions exist and full weight when only one is available.
        con.execute(
            """
            CREATE TABLE group_balanced_points_combined AS
            WITH partition_availability AS (
                SELECT
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    balanced_group_key,
                    ANY_VALUE(balanced_group_label)
                        AS balanced_group_label,
                    COUNT(DISTINCT gender_scope)
                        AS available_gender_count
                FROM group_balanced_points_gender
                GROUP BY
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    balanced_group_key
            ),
            school_values AS (
                SELECT
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    balanced_group_key,
                    resolved_school_id,
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(publication_tier)
                        AS publication_tier,
                    ANY_VALUE(season_key) AS season_key,
                    ANY_VALUE(season_label) AS season_label,
                    ANY_VALUE(school_name) AS school_name,
                    SUM(positive_group_points)
                        AS summed_positive_group_points,
                    SUM(negative_group_points)
                        AS summed_negative_group_points,
                    SUM(group_balanced_points)
                        AS summed_net_group_points,
                    SUM(athlete_event_unit_count)
                        AS athlete_event_unit_count,
                    SUM(group_scoring_event_count)
                        AS group_scoring_event_count,
                    SUM(group_represented_event_count)
                        AS group_represented_event_count,
                    MAX(positive_group_points) FILTER (
                        WHERE gender_scope = 'm'
                    ) AS men_positive_group_points,
                    MAX(negative_group_points) FILTER (
                        WHERE gender_scope = 'm'
                    ) AS men_negative_group_points,
                    MAX(group_balanced_points) FILTER (
                        WHERE gender_scope = 'm'
                    ) AS men_group_points,
                    MAX(positive_group_points) FILTER (
                        WHERE gender_scope = 'f'
                    ) AS women_positive_group_points,
                    MAX(negative_group_points) FILTER (
                        WHERE gender_scope = 'f'
                    ) AS women_negative_group_points,
                    MAX(group_balanced_points) FILTER (
                        WHERE gender_scope = 'f'
                    ) AS women_group_points
                FROM group_balanced_points_gender
                GROUP BY
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    balanced_group_key,
                    resolved_school_id
            ),
            normalized AS (
                SELECT
                    s.*,
                    p.balanced_group_label,
                    p.available_gender_count,
                    s.summed_positive_group_points
                        / p.available_gender_count
                        AS positive_group_points,
                    s.summed_negative_group_points
                        / p.available_gender_count
                        AS negative_group_points,
                    s.summed_net_group_points
                        / p.available_gender_count
                        AS group_balanced_points
                FROM school_values s
                JOIN partition_availability p
                  USING (
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    balanced_group_key
                  )
            )
            SELECT
                *,
                positive_group_points / 100000.0
                    AS positive_group_point_share,
                group_balanced_points / 100000.0
                    AS group_point_share,
                group_balanced_points / 100000.0
                    AS combined_group_strength_share,
                RANK() OVER (
                    PARTITION BY
                        cohort_key,
                        time_scope,
                        season_year,
                        season_type,
                        balanced_group_key
                    ORDER BY
                        group_balanced_points DESC,
                        positive_group_points DESC
                ) AS group_source_rank,
                COUNT(*) OVER (
                    PARTITION BY
                        cohort_key,
                        time_scope,
                        season_year,
                        season_type,
                        balanced_group_key
                ) AS group_ranked_school_count,
                100000.0 AS group_budget,
                CASE
                    WHEN positive_group_points > 0
                        THEN 'positive_formula_share'
                    WHEN negative_group_points < 0
                        THEN 'negative_regression_only'
                    ELSE 'neutral'
                END AS scoring_status,
                'equal_available_gender_group_point_pools'
                    AS point_distribution_method,
                '{DATASET_VERSION}' AS dataset_version
            FROM normalized
            """
        )

        con.execute(
            f"""
            CREATE TABLE group_budget_audit AS
            SELECT
                cohort_key,
                ANY_VALUE(cohort_label) AS cohort_label,
                time_scope,
                season_year,
                season_type,
                gender_scope,
                balanced_group_key,
                ANY_VALUE(balanced_group_label)
                    AS balanced_group_label,
                COUNT(*) AS ranked_school_count,
                SUM(positive_group_points)
                    AS distributed_positive_group_points,
                SUM(negative_group_points)
                    AS distributed_negative_group_points,
                SUM(group_balanced_points)
                    AS distributed_net_group_points,
                SUM(positive_group_points)
                    AS distributed_group_points,
                {GROUP_POSITIVE_BUDGET}::DOUBLE
                    AS required_positive_group_points,
                SUM(positive_group_points)
                    - {GROUP_POSITIVE_BUDGET}
                    AS positive_budget_difference
            FROM group_balanced_points_gender
            GROUP BY
                cohort_key,
                time_scope,
                season_year,
                season_type,
                gender_scope,
                balanced_group_key

            UNION ALL

            SELECT
                cohort_key,
                ANY_VALUE(cohort_label),
                time_scope,
                season_year,
                season_type,
                'all' AS gender_scope,
                balanced_group_key,
                ANY_VALUE(balanced_group_label),
                COUNT(*),
                SUM(positive_group_points),
                SUM(negative_group_points),
                SUM(group_balanced_points),
                SUM(positive_group_points),
                {GROUP_POSITIVE_BUDGET}::DOUBLE,
                SUM(positive_group_points)
                    - {GROUP_POSITIVE_BUDGET}
            FROM group_balanced_points_combined
            GROUP BY
                cohort_key,
                time_scope,
                season_year,
                season_type,
                balanced_group_key
            """
        )

        # --------------------------------------------------------------
        # Group-balanced overall rankings.
        # --------------------------------------------------------------
        con.execute(
            f"""
            CREATE TABLE group_balanced_overall_gender AS
            WITH partition_groups AS (
                SELECT
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    gender_scope,
                    COUNT(DISTINCT balanced_group_key)
                        AS publishable_group_count
                FROM group_balanced_points_gender
                GROUP BY
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    gender_scope
            ),
            school_totals AS (
                SELECT
                    cohort_key,
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(publication_tier)
                        AS publication_tier,
                    time_scope,
                    season_year,
                    season_type,
                    ANY_VALUE(season_key) AS season_key,
                    ANY_VALUE(season_label) AS season_label,
                    gender_scope,
                    resolved_school_id,
                    ANY_VALUE(school_name) AS school_name,
                    SUM(positive_group_points)
                        AS total_positive_group_points,
                    SUM(negative_group_points)
                        AS total_negative_group_points,
                    SUM(group_balanced_points)
                        AS total_group_balanced_points,
                    SUM(athlete_event_unit_count)
                        AS athlete_event_unit_count,
                    COUNT(DISTINCT balanced_group_key) FILTER (
                        WHERE positive_group_points > 0
                    ) AS scoring_group_count,
                    COUNT(DISTINCT balanced_group_key)
                        AS represented_group_count
                FROM group_balanced_points_gender
                GROUP BY
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    gender_scope,
                    resolved_school_id
            )
            SELECT
                s.*,
                p.publishable_group_count,
                p.publishable_group_count
                    * {GROUP_POSITIVE_BUDGET}
                    AS available_group_points,
                s.total_positive_group_points
                    / NULLIF(
                        p.publishable_group_count
                            * {GROUP_POSITIVE_BUDGET},
                        0
                    ) AS positive_share_of_available_group_points,
                s.total_group_balanced_points
                    / NULLIF(
                        p.publishable_group_count
                            * {GROUP_POSITIVE_BUDGET},
                        0
                    ) AS percent_of_available_group_points,
                RANK() OVER (
                    PARTITION BY
                        s.cohort_key,
                        s.time_scope,
                        s.season_year,
                        s.season_type,
                        s.gender_scope
                    ORDER BY
                        s.total_group_balanced_points DESC,
                        s.total_positive_group_points DESC
                ) AS group_balanced_rank,
                '{DATASET_VERSION}' AS dataset_version
            FROM school_totals s
            JOIN partition_groups p
              USING (
                cohort_key,
                time_scope,
                season_year,
                season_type,
                gender_scope
              )
            """
        )

        con.execute(
            f"""
            CREATE TABLE group_balanced_overall_combined AS
            WITH partition_groups AS (
                SELECT
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    COUNT(DISTINCT balanced_group_key)
                        AS publishable_group_count
                FROM group_balanced_points_combined
                GROUP BY
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type
            ),
            school_totals AS (
                SELECT
                    cohort_key,
                    ANY_VALUE(cohort_label) AS cohort_label,
                    ANY_VALUE(publication_tier)
                        AS publication_tier,
                    time_scope,
                    season_year,
                    season_type,
                    ANY_VALUE(season_key) AS season_key,
                    ANY_VALUE(season_label) AS season_label,
                    resolved_school_id,
                    ANY_VALUE(school_name) AS school_name,
                    SUM(positive_group_points)
                        AS total_positive_group_points,
                    SUM(negative_group_points)
                        AS total_negative_group_points,
                    SUM(group_balanced_points)
                        AS total_group_balanced_points,
                    SUM(athlete_event_unit_count)
                        AS athlete_event_unit_count,
                    COUNT(DISTINCT balanced_group_key) FILTER (
                        WHERE positive_group_points > 0
                    ) AS scoring_group_count,
                    COUNT(DISTINCT balanced_group_key)
                        AS represented_group_count
                FROM group_balanced_points_combined
                GROUP BY
                    cohort_key,
                    time_scope,
                    season_year,
                    season_type,
                    resolved_school_id
            )
            SELECT
                s.*,
                p.publishable_group_count,
                p.publishable_group_count
                    * {GROUP_POSITIVE_BUDGET}
                    AS available_group_points,
                s.total_positive_group_points
                    / NULLIF(
                        p.publishable_group_count
                            * {GROUP_POSITIVE_BUDGET},
                        0
                    ) AS positive_share_of_available_group_points,
                s.total_group_balanced_points
                    / NULLIF(
                        p.publishable_group_count
                            * {GROUP_POSITIVE_BUDGET},
                        0
                    ) AS percent_of_available_group_points,
                RANK() OVER (
                    PARTITION BY
                        s.cohort_key,
                        s.time_scope,
                        s.season_year,
                        s.season_type
                    ORDER BY
                        s.total_group_balanced_points DESC,
                        s.total_positive_group_points DESC
                ) AS group_balanced_rank,
                '{DATASET_VERSION}' AS dataset_version
            FROM school_totals s
            JOIN partition_groups p
              USING (
                cohort_key,
                time_scope,
                season_year,
                season_type
              )
            """
        )

        # --------------------------------------------------------------
        # Validation.
        # --------------------------------------------------------------
        counts = fetch_dicts(
            con,
            """
            SELECT
                (SELECT COUNT(DISTINCT balanced_group_key)
                 FROM balanced_event_registry)
                    AS balanced_group_count,
                (SELECT COUNT(DISTINCT cohort_key)
                 FROM athlete_event_development_points
                 WHERE time_scope = 'single_season')
                    AS seasonal_cohort_count,
                (SELECT COUNT(*)
                 FROM athlete_event_development_units)
                    AS athlete_unit_rows,
                (SELECT COUNT(*)
                 FROM athlete_event_development_points)
                    AS athlete_point_rows,
                (SELECT COUNT(*)
                 FROM school_event_development_points)
                    AS school_event_rows,
                (SELECT COUNT(*)
                 FROM event_budget_audit)
                    AS event_partition_count,
                (SELECT COUNT(*)
                 FROM group_budget_audit)
                    AS group_partition_count,
                (SELECT COUNT(*)
                 FROM event_balanced_overall_combined
                 WHERE time_scope = 'single_season')
                    AS seasonal_combined_overall_rows,
                (SELECT MAX(season_year)
                 FROM athlete_event_development_points
                 WHERE time_scope = 'single_season')
                    AS latest_season_year
            """
        )[0]

        quality = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM event_budget_audit
                 WHERE ABS(positive_budget_difference)
                    > {POINT_TOLERANCE})
                    AS invalid_positive_event_budgets,
                (SELECT COUNT(*)
                 FROM group_budget_audit
                 WHERE ABS(positive_budget_difference)
                    > {POINT_TOLERANCE})
                    AS invalid_positive_group_budgets,
                (SELECT COUNT(*)
                 FROM athlete_event_development_points
                 WHERE athlete_positive_points < -{POINT_TOLERANCE})
                    AS invalid_positive_athlete_points,
                (SELECT COUNT(*)
                 FROM athlete_event_development_points
                 WHERE athlete_negative_points > {POINT_TOLERANCE})
                    AS invalid_negative_athlete_points,
                (SELECT COUNT(*)
                 FROM athlete_event_development_points
                 WHERE development_direction = 'negative_regression'
                   AND athlete_negative_points >= 0)
                    AS unpenalized_negative_athletes,
                (SELECT COUNT(*)
                 FROM athlete_event_development_points
                 WHERE development_direction = 'positive_development'
                   AND athlete_positive_points <= 0)
                    AS unrewarded_positive_athletes,
                (SELECT COUNT(*)
                 FROM athlete_event_development_points
                 WHERE development_direction = 'negative_regression')
                    AS negative_athlete_row_count,
                (SELECT MAX(ABS(
                    athlete_net_points
                    - athlete_development_signal
                        * points_per_development_unit
                 ))
                 FROM athlete_event_development_points)
                    AS maximum_athlete_formula_error,
                (SELECT MAX(ABS(
                    school_net_points
                    - event_net_points
                 ))
                 FROM (
                    SELECT
                        a.cohort_key,
                        a.time_scope,
                        a.season_year,
                        a.season_type,
                        a.gender_scope,
                        a.canonical_event_code,
                        a.resolved_school_id,
                        SUM(a.athlete_net_points)
                            AS school_net_points,
                        MAX(s.net_event_points)
                            AS event_net_points
                    FROM athlete_event_development_points a
                    JOIN school_event_development_points s
                      USING (
                        cohort_key,
                        time_scope,
                        season_year,
                        season_type,
                        gender_scope,
                        canonical_event_code,
                        resolved_school_id
                      )
                    GROUP BY
                        a.cohort_key,
                        a.time_scope,
                        a.season_year,
                        a.season_type,
                        a.gender_scope,
                        a.canonical_event_code,
                        a.resolved_school_id
                 ))
                    AS maximum_school_sum_error,
                (SELECT COUNT(*)
                 FROM school_event_development_points
                 WHERE source_rank > 8
                   AND ABS(net_event_points) > {POINT_TOLERANCE})
                    AS nonzero_schools_beyond_rank_eight,
                (SELECT COUNT(*)
                 FROM balanced_event_registry
                 WHERE balanced_group_key = 'steeplechase')
                    AS standalone_steeplechase_rows,
                (SELECT COUNT(*)
                 FROM balanced_event_registry
                 WHERE LOWER(canonical_event_name) LIKE '%steeple%'
                   AND balanced_group_key <> 'distance')
                    AS steeplechase_not_distance_rows,
                (SELECT COUNT(*)
                 FROM athlete_event_development_points
                 WHERE LOWER(canonical_event_name)
                    IN ('500m', '600m', '1000m'))
                    AS nonchampionship_event_rows,
                (SELECT COUNT(*)
                 FROM school_metadata
                 WHERE metadata_match_status <> 'matched')
                    AS unmatched_school_metadata_rows
            """
        )[0]

        add_check(
            checks,
            "balanced_group_count",
            counts["balanced_group_count"] == EXPECTED_GROUPS,
            counts["balanced_group_count"],
            EXPECTED_GROUPS,
        )
        add_check(
            checks,
            "seasonal_cohort_count",
            counts["seasonal_cohort_count"] == EXPECTED_COHORTS,
            counts["seasonal_cohort_count"],
            EXPECTED_COHORTS,
        )
        add_check(
            checks,
            "athlete_point_rows_exist",
            counts["athlete_point_rows"] > 0,
            counts["athlete_point_rows"],
            "greater than 0",
        )
        add_check(
            checks,
            "all_publishable_athlete_units_receive_points",
            counts["athlete_point_rows"]
                == counts["athlete_unit_rows"],
            counts["athlete_point_rows"],
            counts["athlete_unit_rows"],
            (
                "A mismatch indicates a publishable event partition "
                "with no positive development signal."
            ),
        )
        add_check(
            checks,
            "school_event_rows_exist",
            counts["school_event_rows"] > 0,
            counts["school_event_rows"],
            "greater than 0",
        )
        add_check(
            checks,
            "single_season_overall_rows_exist",
            counts["seasonal_combined_overall_rows"] > 0,
            counts["seasonal_combined_overall_rows"],
            "greater than 0",
        )
        add_check(
            checks,
            "all_positive_event_pools_equal_100000",
            quality["invalid_positive_event_budgets"] == 0,
            quality["invalid_positive_event_budgets"],
            0,
        )
        add_check(
            checks,
            "all_positive_group_pools_equal_100000",
            quality["invalid_positive_group_budgets"] == 0,
            quality["invalid_positive_group_budgets"],
            0,
        )
        add_check(
            checks,
            "positive_athlete_points_nonnegative",
            quality["invalid_positive_athlete_points"] == 0,
            quality["invalid_positive_athlete_points"],
            0,
        )
        add_check(
            checks,
            "negative_athlete_points_nonpositive",
            quality["invalid_negative_athlete_points"] == 0,
            quality["invalid_negative_athlete_points"],
            0,
        )
        add_check(
            checks,
            "negative_athletes_receive_negative_points",
            quality["unpenalized_negative_athletes"] == 0,
            quality["unpenalized_negative_athletes"],
            0,
        )
        add_check(
            checks,
            "positive_athletes_receive_positive_points",
            quality["unrewarded_positive_athletes"] == 0,
            quality["unrewarded_positive_athletes"],
            0,
        )
        add_check(
            checks,
            "negative_athlete_points_exist",
            quality["negative_athlete_row_count"] > 0,
            quality["negative_athlete_row_count"],
            "greater than 0",
        )
        add_check(
            checks,
            "athlete_points_follow_original_signal",
            float(quality["maximum_athlete_formula_error"])
                <= POINT_TOLERANCE,
            quality["maximum_athlete_formula_error"],
            f"<= {POINT_TOLERANCE}",
        )
        add_check(
            checks,
            "school_event_points_equal_athlete_sum",
            float(quality["maximum_school_sum_error"])
                <= POINT_TOLERANCE,
            quality["maximum_school_sum_error"],
            f"<= {POINT_TOLERANCE}",
        )
        add_check(
            checks,
            "points_are_not_limited_to_top_eight",
            quality["nonzero_schools_beyond_rank_eight"] > 0,
            quality["nonzero_schools_beyond_rank_eight"],
            "greater than 0",
        )
        add_check(
            checks,
            "no_standalone_steeplechase_group",
            quality["standalone_steeplechase_rows"] == 0,
            quality["standalone_steeplechase_rows"],
            0,
        )
        add_check(
            checks,
            "steeplechase_is_distance",
            quality["steeplechase_not_distance_rows"] == 0,
            quality["steeplechase_not_distance_rows"],
            0,
        )
        add_check(
            checks,
            "nonchampionship_events_excluded",
            quality["nonchampionship_event_rows"] == 0,
            quality["nonchampionship_event_rows"],
            0,
        )
        add_check(
            checks,
            "school_metadata_fully_matched",
            quality["unmatched_school_metadata_rows"] == 0,
            quality["unmatched_school_metadata_rows"],
            0,
        )

        # --------------------------------------------------------------
        # Exports.
        # --------------------------------------------------------------
        exports = (
            (
                "balanced_event_registry.csv",
                """
                SELECT *
                FROM balanced_event_registry
                ORDER BY
                    source_season_type,
                    gender_scope,
                    balanced_group_label,
                    canonical_event_name
                """,
            ),
            (
                "athlete_event_development_points.csv",
                """
                SELECT *
                FROM athlete_event_development_points
                ORDER BY
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    canonical_event_name,
                    athlete_net_points DESC,
                    athlete_name
                """,
            ),
            (
                "event_balanced_point_rows.csv",
                """
                SELECT *
                FROM school_event_development_points
                ORDER BY
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    canonical_event_name,
                    source_rank,
                    school_name
                """,
            ),
            (
                "event_budget_audit.csv",
                """
                SELECT *
                FROM event_budget_audit
                ORDER BY
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    canonical_event_name
                """,
            ),
            (
                "event_balanced_overall_gender.csv",
                """
                SELECT *
                FROM event_balanced_overall_gender
                ORDER BY
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    event_balanced_rank,
                    school_name
                """,
            ),
            (
                "event_balanced_overall_combined.csv",
                """
                SELECT *
                FROM event_balanced_overall_combined
                ORDER BY
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    event_balanced_rank,
                    school_name
                """,
            ),
            (
                "group_balanced_points_gender.csv",
                """
                SELECT *
                FROM group_balanced_points_gender
                ORDER BY
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    balanced_group_label,
                    group_source_rank,
                    school_name
                """,
            ),
            (
                "group_balanced_points_combined.csv",
                """
                SELECT *
                FROM group_balanced_points_combined
                ORDER BY
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    balanced_group_label,
                    group_source_rank,
                    school_name
                """,
            ),
            (
                "group_budget_audit.csv",
                """
                SELECT *
                FROM group_budget_audit
                ORDER BY
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    balanced_group_label
                """,
            ),
            (
                "group_balanced_overall_gender.csv",
                """
                SELECT *
                FROM group_balanced_overall_gender
                ORDER BY
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    gender_scope,
                    group_balanced_rank,
                    school_name
                """,
            ),
            (
                "group_balanced_overall_combined.csv",
                """
                SELECT *
                FROM group_balanced_overall_combined
                ORDER BY
                    time_scope,
                    cohort_key,
                    season_year,
                    season_type,
                    group_balanced_rank,
                    school_name
                """,
            ),
        )

        output_counts = {}
        for filename, sql in exports:
            output_counts[filename] = export_query(
                con,
                sql,
                OUTPUT_DIR / filename,
            )

        export_query(
            con,
            """
            SELECT *
            FROM athlete_event_development_points
            WHERE time_scope = 'single_season'
            ORDER BY
                cohort_key,
                season_year,
                season_type,
                gender_scope,
                canonical_event_name,
                athlete_net_points DESC
            """,
            OUTPUT_DIR / "season_athlete_event_development_points.csv",
        )
        export_query(
            con,
            """
            SELECT *
            FROM school_event_development_points
            WHERE time_scope = 'single_season'
            ORDER BY
                cohort_key,
                season_year,
                season_type,
                gender_scope,
                canonical_event_name,
                source_rank
            """,
            OUTPUT_DIR / "season_event_balanced_points.csv",
        )
        export_query(
            con,
            """
            SELECT *
            FROM event_balanced_overall_gender
            WHERE time_scope = 'single_season'
            ORDER BY
                cohort_key,
                season_year,
                season_type,
                gender_scope,
                event_balanced_rank
            """,
            OUTPUT_DIR / "season_event_balanced_overall_gender.csv",
        )
        export_query(
            con,
            """
            SELECT *
            FROM event_balanced_overall_combined
            WHERE time_scope = 'single_season'
            ORDER BY
                cohort_key,
                season_year,
                season_type,
                event_balanced_rank
            """,
            OUTPUT_DIR / "season_event_balanced_overall_combined.csv",
        )
        export_query(
            con,
            """
            SELECT *
            FROM group_balanced_points_gender
            WHERE time_scope = 'single_season'
            ORDER BY
                cohort_key,
                season_year,
                season_type,
                gender_scope,
                balanced_group_label,
                group_source_rank
            """,
            OUTPUT_DIR / "season_group_balanced_points_gender.csv",
        )
        export_query(
            con,
            """
            SELECT *
            FROM group_balanced_points_combined
            WHERE time_scope = 'single_season'
            ORDER BY
                cohort_key,
                season_year,
                season_type,
                balanced_group_label,
                group_source_rank
            """,
            OUTPUT_DIR / "season_group_balanced_points_combined.csv",
        )

        con.execute(
            f"""
            CREATE TABLE dataset_metadata AS
            SELECT
                'dataset_version' AS metadata_key,
                '{DATASET_VERSION}' AS metadata_value
            UNION ALL
            SELECT 'policy_version', '{POLICY_VERSION}'
            UNION ALL
            SELECT 'group_taxonomy_version',
                   '{GROUP_TAXONOMY_VERSION}'
            UNION ALL
            SELECT 'positive_event_budget',
                   '{EVENT_POSITIVE_BUDGET}'
            UNION ALL
            SELECT 'positive_group_budget',
                   '{GROUP_POSITIVE_BUDGET}'
            UNION ALL
            SELECT
                'athlete_signal',
                'mean original athlete_value_added within athlete-school-event unit'
            UNION ALL
            SELECT
                'negative_point_policy',
                'same linear conversion as positive points; excluded from positive pool'
            UNION ALL
            SELECT
                'school_aggregation',
                'sum athlete positive, negative, and net points'
            UNION ALL
            SELECT 'steeplechase_group', 'distance'
            UNION ALL
            SELECT
                'duckdb_compatibility_patch',
                'replaced unsupported INITCAP with explicit season labels'
            UNION ALL
            SELECT 'created_at_utc', CURRENT_TIMESTAMP::VARCHAR
            """
        )

        latest_year = int(counts["latest_season_year"])
        latest_leaders = fetch_dicts(
            con,
            f"""
            SELECT
                cohort_label,
                season_label,
                school_name,
                total_positive_event_points,
                total_negative_event_points,
                total_event_balanced_points,
                event_balanced_rank
            FROM event_balanced_overall_combined
            WHERE time_scope = 'single_season'
              AND season_year = {latest_year}
              AND event_balanced_rank <= 3
            ORDER BY
                cohort_key,
                season_type,
                event_balanced_rank
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

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 6 PHASE 6D — ATHLETE-LEVEL EVENT-BALANCED POINTS",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "POLICY",
        "-" * 78,
        f"Positive event pool: {EVENT_POSITIVE_BUDGET:,.0f}",
        f"Positive group pool: {GROUP_POSITIVE_BUDGET:,.0f}",
        "Athlete signal: original observed improvement minus "
        "cross-fitted expected improvement",
        "Positive allocation: proportional to positive athlete signal",
        "Negative allocation: same conversion, remains negative, "
        "does not consume positive pool",
        "School aggregation: sum of athlete positive, negative, and net points",
        "Top-eight cutoff: none",
        "Steeplechase group: Distance",
        "Non-championship 500m/600m/1000m: excluded",
        "",
        "RESULTS",
        "-" * 78,
        f"Athlete event units before positive-pool gate: "
        f"{int(counts['athlete_unit_rows']):,}",
        f"Athlete point rows: {int(counts['athlete_point_rows']):,}",
        f"School-event rows: {int(counts['school_event_rows']):,}",
        f"Event partitions: {int(counts['event_partition_count']):,}",
        f"Group partitions: {int(counts['group_partition_count']):,}",
        f"Single-season combined overall rows: "
        f"{int(counts['seasonal_combined_overall_rows']):,}",
        f"Latest endpoint year: {int(counts['latest_season_year'])}",
        "",
        "LATEST TOP THREE",
        "-" * 78,
    ]

    for row in latest_leaders:
        report.append(
            f"{row['cohort_label']} | {row['season_label']} | "
            f"#{int(row['event_balanced_rank'])} "
            f"{row['school_name']} | "
            f"positive={float(row['total_positive_event_points']):,.2f} | "
            f"negative={float(row['total_negative_event_points']):,.2f} | "
            f"net={float(row['total_event_balanced_points']):,.2f}"
        )

    report.extend(
        [
            "",
            "PHASE GATE",
            "-" * 78,
            (
                "PASS — Athlete-level event-balanced points published."
                if not failed
                else "FAIL — Review hard checks."
            ),
        ]
    )

    (OUTPUT_DIR / "phase_6d_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Athlete point rows: {int(counts['athlete_point_rows']):,}")
    print(f"School-event rows: {int(counts['school_event_rows']):,}")
    print(
        f"Event partitions with 100,000 positive-point pools: "
        f"{int(counts['event_partition_count']):,}"
    )
    print(
        f"Negative athlete rows: "
        f"{int(quality['negative_athlete_row_count']):,}"
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
    print("Next: inspect athlete, school, event, and negative-point totals.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
