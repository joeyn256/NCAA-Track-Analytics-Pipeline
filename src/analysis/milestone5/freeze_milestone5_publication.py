#!/usr/bin/env python3
"""
Milestone 5 Phase 5I — Freeze Publication Version 1

Creates the final, metadata-enriched NCAA Division I athlete-development
ranking database and public CSV package.

Inputs
------
- Phase 5H publication audit database and hard checks.
- Main NCAA Track Analytics DuckDB warehouse for readable school metadata.

Publication contents
--------------------
- Overall rankings for all schools.
- Official overall rankings (minimum 30 athlete-school units).
- Insufficient-data school table.
- Men's and women's rankings.
- Event-family rankings.
- School score components and uncertainty fields.
- Athlete-school contribution table for reproducible drill-down.
- School metadata, methodology, data dictionary, and manifests.

The script strictly requires every ranking school ID to match core.schools.
It never substitutes a parsed slug for a missing warehouse school name.
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

AUDIT_DB = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5h_final_ranking_publication_audit/"
      "ranking_publication_audit_v1.duckdb"
)

PHASE_5H_CHECKS = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5h_final_ranking_publication_audit/"
      "hard_checks.csv"
)

WAREHOUSE_DB = (
    ROOT
    / "data/database/ncaa_track_analytics.duckdb"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5i_publication_freeze"
)

OUTPUT_DB = (
    OUTPUT_DIR
    / "ncaa_d1_athlete_development_rankings_v1.duckdb"
)

INPUT_AUDIT_DATASET_VERSION = "ranking_publication_audit_v1_1"
INPUT_AUDIT_POLICY_VERSION = "ranking_publication_audit_policy_v1_1"

DATASET_VERSION = "ncaa_d1_athlete_development_rankings_v1"
PUBLICATION_POLICY_VERSION = "athlete_development_publication_policy_v1"

EXPECTED_SCHOOLS = 361
EXPECTED_OFFICIAL_SCHOOLS = 353
EXPECTED_INSUFFICIENT_SCHOOLS = 8
EXPECTED_ATHLETE_SCHOOL_ROWS = 80_077

OFFICIAL_OVERALL_MIN_SAMPLE = 30
OFFICIAL_GENDER_MIN_SAMPLE = 20
OFFICIAL_EVENT_FAMILY_MIN_SAMPLE = 10

SCHOOL_NAME_CANDIDATES = (
    "school_name",
    "institution_name",
    "display_name",
    "name",
)

SCHOOL_STATE_CANDIDATES = (
    "state_code",
    "state",
    "school_state",
)

SCHOOL_CITY_CANDIDATES = (
    "city",
    "school_city",
)

SCHOOL_SLUG_CANDIDATES = (
    "slug",
    "school_slug",
)

TEAM_CONFERENCE_CANDIDATES = (
    "conference_name",
    "conference",
    "conference_code",
)

TEAM_DIVISION_CANDIDATES = (
    "division",
    "division_name",
    "ncaa_division",
)

TEAM_GENDER_CANDIDATES = (
    "gender",
    "gender_code",
)

FORMULA_TOLERANCE = 1e-10


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


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


def table_columns(
    connection: duckdb.DuckDBPyConnection,
    catalog: str,
    schema: str,
    table: str,
) -> list[str]:
    rows = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_catalog = ?
          AND table_schema = ?
          AND table_name = ?
        ORDER BY ordinal_position
        """,
        [catalog, schema, table],
    ).fetchall()
    return [str(row[0]) for row in rows]


def first_existing(
    columns: Iterable[str],
    candidates: Iterable[str],
) -> str | None:
    column_lookup = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate.lower() in column_lookup:
            return column_lookup[candidate.lower()]
    return None


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


def export_query(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    path: Path,
) -> int:
    rows = fetch_dicts(connection, sql)
    fieldnames = list(rows[0].keys()) if rows else []
    write_csv(path, rows, fieldnames)
    return len(rows)


def build_school_metadata_sql(
    school_columns: list[str],
    team_columns: list[str],
) -> tuple[str, dict[str, str | None]]:
    school_id = first_existing(school_columns, ("school_id",))
    school_name = first_existing(
        school_columns,
        SCHOOL_NAME_CANDIDATES,
    )
    school_state = first_existing(
        school_columns,
        SCHOOL_STATE_CANDIDATES,
    )
    school_city = first_existing(
        school_columns,
        SCHOOL_CITY_CANDIDATES,
    )
    school_slug = first_existing(
        school_columns,
        SCHOOL_SLUG_CANDIDATES,
    )

    team_school_id = first_existing(team_columns, ("school_id",))
    team_conference = first_existing(
        team_columns,
        TEAM_CONFERENCE_CANDIDATES,
    )
    team_division = first_existing(
        team_columns,
        TEAM_DIVISION_CANDIDATES,
    )
    team_gender = first_existing(
        team_columns,
        TEAM_GENDER_CANDIDATES,
    )

    if school_id is None:
        raise RuntimeError(
            "warehouse.core.schools does not contain school_id."
        )
    if school_name is None:
        raise RuntimeError(
            "No readable school-name column was detected in "
            "warehouse.core.schools."
        )
    if team_school_id is None:
        raise RuntimeError(
            "warehouse.core.teams does not contain school_id."
        )

    school_state_expr = (
        f"CAST(s.{qi(school_state)} AS VARCHAR)"
        if school_state
        else (
            "CASE "
            "WHEN POSITION('_college_' IN CAST("
            f"s.{qi(school_id)} AS VARCHAR)) > 0 "
            "THEN SPLIT_PART(CAST("
            f"s.{qi(school_id)} AS VARCHAR), '_college_', 1) "
            "ELSE NULL END"
        )
    )
    school_city_expr = (
        f"CAST(s.{qi(school_city)} AS VARCHAR)"
        if school_city
        else "NULL::VARCHAR"
    )
    school_slug_expr = (
        f"CAST(s.{qi(school_slug)} AS VARCHAR)"
        if school_slug
        else "NULL::VARCHAR"
    )

    conference_expr = (
        f"CAST(t.{qi(team_conference)} AS VARCHAR)"
        if team_conference
        else "NULL::VARCHAR"
    )
    division_expr = (
        f"CAST(t.{qi(team_division)} AS VARCHAR)"
        if team_division
        else "NULL::VARCHAR"
    )
    gender_expr = (
        f"CAST(t.{qi(team_gender)} AS VARCHAR)"
        if team_gender
        else "NULL::VARCHAR"
    )

    sql = f"""
    WITH team_metadata AS (
        SELECT
            CAST(t.{qi(team_school_id)} AS VARCHAR)
                AS resolved_school_id,
            STRING_AGG(
                DISTINCT NULLIF(TRIM({conference_expr}), ''),
                ' | '
                ORDER BY NULLIF(TRIM({conference_expr}), '')
            ) AS conference_name,
            STRING_AGG(
                DISTINCT NULLIF(TRIM({division_expr}), ''),
                ' | '
                ORDER BY NULLIF(TRIM({division_expr}), '')
            ) AS division_name,
            COUNT(*) AS warehouse_team_count,
            COUNT(DISTINCT NULLIF(TRIM({gender_expr}), ''))
                AS warehouse_gender_count
        FROM warehouse.core.teams t
        GROUP BY CAST(t.{qi(team_school_id)} AS VARCHAR)
    )
    SELECT
        CAST(s.{qi(school_id)} AS VARCHAR)
            AS resolved_school_id,
        CAST(s.{qi(school_name)} AS VARCHAR)
            AS school_name,
        {school_state_expr} AS state_code,
        {school_city_expr} AS city,
        {school_slug_expr} AS school_slug,
        tm.conference_name,
        tm.division_name,
        tm.warehouse_team_count,
        tm.warehouse_gender_count,
        'warehouse.core.schools' AS metadata_source
    FROM warehouse.core.schools s
    LEFT JOIN team_metadata tm
      ON tm.resolved_school_id =
         CAST(s.{qi(school_id)} AS VARCHAR)
    """

    detected = {
        "school_id": school_id,
        "school_name": school_name,
        "school_state": school_state,
        "school_city": school_city,
        "school_slug": school_slug,
        "team_school_id": team_school_id,
        "team_conference": team_conference,
        "team_division": team_division,
        "team_gender": team_gender,
    }
    return sql, detected


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 5I — FREEZE PUBLICATION VERSION 1")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Audit database: {AUDIT_DB}")
    print(f"Warehouse database: {WAREHOUSE_DB}")
    print(f"Output database: {OUTPUT_DB}")

    required_inputs = [
        AUDIT_DB,
        PHASE_5H_CHECKS,
        WAREHOUSE_DB,
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

    phase_5h_checks = read_csv(PHASE_5H_CHECKS)
    failed_phase_5h_checks = [
        row for row in phase_5h_checks
        if row.get("status") != "PASS"
    ]

    add_check(
        checks,
        "phase_5h_gate_passed",
        not failed_phase_5h_checks,
        [row.get("check_name") for row in failed_phase_5h_checks],
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
            ATTACH '{sql_path(AUDIT_DB)}'
                AS audit_source (READ_ONLY)
            """
        )
        con.execute(
            f"""
            ATTACH '{sql_path(WAREHOUSE_DB)}'
                AS warehouse (READ_ONLY)
            """
        )

        audit_metadata = {
            row[0]: row[1]
            for row in con.execute(
                """
                SELECT metadata_key, metadata_value
                FROM audit_source.main.dataset_metadata
                """
            ).fetchall()
        }

        add_check(
            checks,
            "input_audit_dataset_version_matches",
            audit_metadata.get("dataset_version")
            == INPUT_AUDIT_DATASET_VERSION,
            audit_metadata.get("dataset_version"),
            INPUT_AUDIT_DATASET_VERSION,
        )
        add_check(
            checks,
            "input_audit_policy_version_matches",
            audit_metadata.get("audit_policy_version")
            == INPUT_AUDIT_POLICY_VERSION,
            audit_metadata.get("audit_policy_version"),
            INPUT_AUDIT_POLICY_VERSION,
        )

        school_columns = table_columns(
            con,
            "warehouse",
            "core",
            "schools",
        )
        team_columns = table_columns(
            con,
            "warehouse",
            "core",
            "teams",
        )

        school_metadata_sql, detected = build_school_metadata_sql(
            school_columns,
            team_columns,
        )

        con.execute(
            f"""
            CREATE TABLE warehouse_school_metadata AS
            {school_metadata_sql}
            """
        )

        con.execute(
            """
            CREATE TABLE ranking_school_metadata AS
            SELECT
                r.resolved_school_id,
                m.school_name,
                m.state_code,
                m.city,
                m.school_slug,
                m.conference_name,
                m.division_name,
                m.warehouse_team_count,
                m.warehouse_gender_count,
                m.metadata_source,
                CASE
                    WHEN m.resolved_school_id IS NULL
                        THEN 'unmatched'
                    WHEN NULLIF(TRIM(m.school_name), '') IS NULL
                        THEN 'missing_name'
                    ELSE 'matched'
                END AS metadata_match_status
            FROM (
                SELECT DISTINCT resolved_school_id
                FROM audit_source.main.final_overall_rankings_candidate
            ) r
            LEFT JOIN warehouse_school_metadata m
              USING (resolved_school_id)
            """
        )

        con.execute(
            f"""
            CREATE TABLE overall_rankings AS
            SELECT
                r.official_overall_rank,
                r.all_school_posterior_rank,
                r.resolved_school_id,
                m.school_name,
                m.state_code,
                m.city,
                m.conference_name,
                m.division_name,
                r.official_rank_eligible,
                r.official_ranked_school_count,
                r.reliability_tier,
                r.ranking_band,
                r.evidence_category,
                r.athlete_school_unit_count,
                r.distinct_athlete_count,
                r.male_athlete_unit_count,
                r.female_athlete_unit_count,
                r.trajectory_count,
                r.athlete_family_unit_count,
                r.raw_school_score,
                r.posterior_school_score,
                r.posterior_standard_error,
                r.posterior_ci95_lower,
                r.posterior_ci95_upper,
                r.shrinkage_weight,
                r.shrinkage_adjustment,
                r.median_athlete_value_added,
                r.above_expected_athlete_share,
                r.mean_event_families_per_athlete,
                r.mean_trajectories_per_athlete,
                r.winsorized_school_score,
                r.family_median_school_score,
                r.minimum_training_support,
                r.raw_school_rank,
                r.absolute_rank_change_from_raw,
                r.publication_status,
                '{DATASET_VERSION}' AS publication_dataset_version,
                '{PUBLICATION_POLICY_VERSION}'
                    AS publication_policy_version
            FROM audit_source.main.final_overall_rankings_candidate r
            JOIN ranking_school_metadata m
              USING (resolved_school_id)
            """
        )

        con.execute(
            """
            CREATE VIEW official_overall_rankings AS
            SELECT *
            FROM overall_rankings
            WHERE official_rank_eligible
            """
        )

        con.execute(
            """
            CREATE VIEW insufficient_data_schools AS
            SELECT *
            FROM overall_rankings
            WHERE NOT official_rank_eligible
            """
        )

        con.execute(
            f"""
            CREATE TABLE gender_rankings AS
            SELECT
                g.official_gender_rank,
                g.all_school_gender_rank,
                g.canonical_gender_code,
                CASE
                    WHEN g.canonical_gender_code = 'm'
                        THEN 'Men'
                    WHEN g.canonical_gender_code = 'f'
                        THEN 'Women'
                    ELSE g.canonical_gender_code
                END AS gender_label,
                g.resolved_school_id,
                m.school_name,
                m.state_code,
                m.city,
                m.conference_name,
                m.division_name,
                g.official_rank_eligible,
                g.official_ranked_school_count,
                g.reliability_tier,
                g.ranking_band,
                g.evidence_category,
                g.athlete_school_unit_count,
                g.distinct_athlete_count,
                g.trajectory_count,
                g.athlete_family_unit_count,
                g.raw_school_score,
                g.posterior_school_score,
                g.posterior_standard_error,
                g.posterior_ci95_lower,
                g.posterior_ci95_upper,
                g.shrinkage_weight,
                g.shrinkage_adjustment,
                g.above_expected_athlete_share,
                g.winsorized_school_score,
                g.raw_gender_rank,
                g.absolute_rank_change_from_raw,
                '{DATASET_VERSION}' AS publication_dataset_version,
                '{PUBLICATION_POLICY_VERSION}'
                    AS publication_policy_version
            FROM audit_source.main.gender_ranking_snapshot g
            JOIN ranking_school_metadata m
              USING (resolved_school_id)
            """
        )

        con.execute(
            f"""
            CREATE TABLE event_family_rankings AS
            SELECT
                e.official_event_family_rank,
                e.all_school_family_rank,
                e.canonical_gender_code,
                CASE
                    WHEN e.canonical_gender_code = 'm'
                        THEN 'Men'
                    WHEN e.canonical_gender_code = 'f'
                        THEN 'Women'
                    ELSE e.canonical_gender_code
                END AS gender_label,
                e.event_family,
                e.resolved_school_id,
                m.school_name,
                m.state_code,
                m.city,
                m.conference_name,
                m.division_name,
                e.official_rank_eligible,
                e.official_ranked_school_count,
                e.reliability_tier,
                e.ranking_band,
                e.evidence_category,
                e.athlete_family_unit_count,
                e.distinct_athlete_count,
                e.trajectory_count,
                e.raw_school_score,
                e.posterior_school_score,
                e.posterior_standard_error,
                e.posterior_ci95_lower,
                e.posterior_ci95_upper,
                e.shrinkage_weight,
                e.shrinkage_adjustment,
                e.above_expected_athlete_share,
                e.winsorized_school_score,
                e.raw_family_rank,
                e.absolute_rank_change_from_raw,
                '{DATASET_VERSION}' AS publication_dataset_version,
                '{PUBLICATION_POLICY_VERSION}'
                    AS publication_policy_version
            FROM audit_source.main.event_family_ranking_snapshot e
            JOIN ranking_school_metadata m
              USING (resolved_school_id)
            """
        )

        con.execute(
            f"""
            CREATE TABLE school_score_components AS
            SELECT
                s.*,
                m.school_name,
                m.state_code,
                m.city,
                m.conference_name,
                m.division_name,
                '{DATASET_VERSION}' AS publication_dataset_version,
                '{PUBLICATION_POLICY_VERSION}'
                    AS publication_policy_version
            FROM audit_source.main.school_score_component_snapshot s
            JOIN ranking_school_metadata m
              USING (resolved_school_id)
            """
        )

        con.execute(
            f"""
            CREATE TABLE athlete_school_contributions AS
            SELECT
                a.*,
                m.school_name,
                m.state_code,
                m.conference_name,
                '{DATASET_VERSION}' AS publication_dataset_version,
                '{PUBLICATION_POLICY_VERSION}'
                    AS publication_policy_version
            FROM audit_source.main.athlete_school_snapshot a
            JOIN ranking_school_metadata m
              USING (resolved_school_id)
            """
        )

        con.execute(
            """
            CREATE TABLE sensitivity_variant_metrics AS
            SELECT *
            FROM audit_source.main.sensitivity_variant_metrics
            """
        )

        con.execute(
            """
            CREATE TABLE sample_threshold_sensitivity AS
            SELECT *
            FROM audit_source.main.sample_threshold_sensitivity
            """
        )

        con.execute(
            """
            CREATE TABLE school_bias_diagnostics AS
            SELECT *
            FROM audit_source.main.school_bias_diagnostics
            """
        )

        con.execute(
            """
            CREATE TABLE evidence_category_summary AS
            SELECT *
            FROM audit_source.main.evidence_category_summary
            """
        )

        con.execute(
            """
            CREATE TABLE publication_readiness_summary AS
            SELECT *
            FROM audit_source.main.publication_readiness_summary
            """
        )

        con.execute(
            """
            CREATE TABLE publication_methodology (
                methodology_key VARCHAR,
                methodology_value VARCHAR,
                description VARCHAR
            )
            """
        )

        methodology_rows = [
            (
                "ranking_subject",
                "NCAA Division I school athlete development",
                "Measures school-attributed athlete improvement above "
                "a school-held-out expected-improvement benchmark.",
            ),
            (
                "performance_level_scale",
                "0_to_100_squared_anchor_ratio",
                "Event-specific performance levels reward equivalent "
                "improvement more strongly near the human-performance limit.",
            ),
            (
                "trajectory_window",
                "1_to_5_elapsed_same_season_type_seasons",
                "Trajectories spanning six or more seasons are excluded "
                "from primary expected-improvement fitting.",
            ),
            (
                "expected_improvement_model",
                "resolution_raw_mean_cross_fitted_by_school",
                "Predictions for each school are generated without using "
                "that school's assigned cross-fitting fold.",
            ),
            (
                "athlete_value_added_formula",
                "observed_improvement_minus_expected_improvement",
                "Positive values indicate development above expectation.",
            ),
            (
                "multi_event_policy",
                "equal_family_equal_athlete",
                "Trajectories are averaged within event family, then event "
                "families are averaged so each athlete-school unit has one "
                "total school vote.",
            ),
            (
                "overall_school_model",
                "empirical_bayes_df20",
                "School means are shrunk toward the national athlete mean "
                "using stabilized sampling variance.",
            ),
            (
                "overall_official_minimum_sample",
                str(OFFICIAL_OVERALL_MIN_SAMPLE),
                "Minimum athlete-school units for an official overall rank.",
            ),
            (
                "gender_official_minimum_sample",
                str(OFFICIAL_GENDER_MIN_SAMPLE),
                "Minimum same-gender athlete-school units for an official "
                "men's or women's rank.",
            ),
            (
                "event_family_official_minimum_sample",
                str(OFFICIAL_EVENT_FAMILY_MIN_SAMPLE),
                "Minimum athlete-family units for an official event-family "
                "rank.",
            ),
            (
                "confidence_interval",
                "95_percent_normal_posterior_interval",
                "Intervals communicate uncertainty; adjacent ranks are not "
                "necessarily statistically distinguishable.",
            ),
            (
                "publication_interpretation",
                "development_not_absolute_team_quality",
                "The ranking evaluates athlete development relative to "
                "expectation, not championship strength or recruiting class.",
            ),
        ]

        con.executemany(
            """
            INSERT INTO publication_methodology
            VALUES (?, ?, ?)
            """,
            methodology_rows,
        )

        con.execute(
            f"""
            CREATE TABLE dataset_metadata AS
            SELECT
                'dataset_version' AS metadata_key,
                '{DATASET_VERSION}' AS metadata_value
            UNION ALL
            SELECT
                'publication_policy_version',
                '{PUBLICATION_POLICY_VERSION}'
            UNION ALL
            SELECT
                'input_audit_dataset_version',
                '{INPUT_AUDIT_DATASET_VERSION}'
            UNION ALL
            SELECT
                'official_overall_school_count',
                '{EXPECTED_OFFICIAL_SCHOOLS}'
            UNION ALL
            SELECT
                'all_school_count',
                '{EXPECTED_SCHOOLS}'
            UNION ALL
            SELECT
                'publication_status',
                'frozen'
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
                (SELECT COUNT(*) FROM overall_rankings)
                    AS overall_rows,
                (SELECT COUNT(*) FROM official_overall_rankings)
                    AS official_overall_rows,
                (SELECT COUNT(*) FROM insufficient_data_schools)
                    AS insufficient_rows,
                (SELECT COUNT(*) FROM gender_rankings)
                    AS gender_rows,
                (SELECT COUNT(*)
                 FROM audit_source.main.gender_ranking_snapshot)
                    AS source_gender_rows,
                (SELECT COUNT(*) FROM event_family_rankings)
                    AS event_family_rows,
                (SELECT COUNT(*)
                 FROM audit_source.main.event_family_ranking_snapshot)
                    AS source_event_family_rows,
                (SELECT COUNT(*) FROM athlete_school_contributions)
                    AS athlete_school_rows,
                (SELECT COUNT(*) FROM ranking_school_metadata)
                    AS metadata_rows,
                (SELECT COUNT(*)
                 FROM ranking_school_metadata
                 WHERE metadata_match_status <> 'matched')
                    AS unmatched_metadata_rows,
                (SELECT COUNT(*)
                 FROM ranking_school_metadata
                 WHERE NULLIF(TRIM(school_name), '') IS NULL)
                    AS missing_school_name_rows,
                (SELECT COUNT(*)
                 FROM ranking_school_metadata
                 WHERE POSITION(
                    '_college_' IN school_name
                 ) > 0)
                    AS slug_like_school_name_rows
            """
        )[0]

        ranking_quality = fetch_dicts(
            con,
            f"""
            SELECT
                (SELECT COUNT(*)
                 FROM (
                    SELECT resolved_school_id, COUNT(*) AS row_count
                    FROM overall_rankings
                    GROUP BY resolved_school_id
                    HAVING COUNT(*) > 1
                 ))
                    AS duplicate_overall_school_rows,
                (SELECT COUNT(*)
                 FROM official_overall_rankings
                 WHERE official_overall_rank IS NULL)
                    AS missing_official_rank_rows,
                (SELECT COUNT(DISTINCT official_overall_rank)
                 FROM official_overall_rankings)
                    AS distinct_official_rank_count,
                (SELECT MIN(official_overall_rank)
                 FROM official_overall_rankings)
                    AS minimum_official_rank,
                (SELECT MAX(official_overall_rank)
                 FROM official_overall_rankings)
                    AS maximum_official_rank,
                (SELECT COUNT(*)
                 FROM overall_rankings
                 WHERE posterior_ci95_lower > posterior_ci95_upper)
                    AS invalid_interval_rows,
                (SELECT COUNT(*)
                 FROM overall_rankings
                 WHERE shrinkage_weight < 0
                    OR shrinkage_weight > 1)
                    AS invalid_shrinkage_rows,
                (SELECT COUNT(*)
                 FROM overall_rankings
                 WHERE posterior_school_score
                    < LEAST(raw_school_score, -0.04803562435085214)
                        - {FORMULA_TOLERANCE}
                    OR posterior_school_score
                    > GREATEST(raw_school_score, -0.04803562435085214)
                        + {FORMULA_TOLERANCE})
                    AS nonconvex_posterior_rows
            """
        )[0]

        reproduction = fetch_dicts(
            con,
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE ABS(
                        o.posterior_school_score
                        - a.posterior_school_score
                    ) > 1e-12
                ) AS score_mismatch_rows,
                COUNT(*) FILTER (
                    WHERE COALESCE(o.official_overall_rank, -1)
                       <> COALESCE(a.official_overall_rank, -1)
                ) AS rank_mismatch_rows,
                COUNT(*) FILTER (
                    WHERE o.official_rank_eligible
                       <> a.official_rank_eligible
                ) AS eligibility_mismatch_rows
            FROM overall_rankings o
            JOIN audit_source.main.final_overall_rankings_candidate a
              USING (resolved_school_id)
            """
        )[0]

        add_check(
            checks,
            "school_metadata_column_detected",
            detected["school_name"] is not None,
            detected,
            "readable school-name column detected",
        )
        add_check(
            checks,
            "all_ranking_schools_match_core_schools",
            counts["unmatched_metadata_rows"] == 0,
            counts["unmatched_metadata_rows"],
            0,
        )
        add_check(
            checks,
            "all_school_names_present",
            counts["missing_school_name_rows"] == 0,
            counts["missing_school_name_rows"],
            0,
        )
        add_check(
            checks,
            "school_names_are_not_internal_slugs",
            counts["slug_like_school_name_rows"] == 0,
            counts["slug_like_school_name_rows"],
            0,
        )
        add_check(
            checks,
            "overall_school_row_count",
            counts["overall_rows"] == EXPECTED_SCHOOLS,
            counts["overall_rows"],
            EXPECTED_SCHOOLS,
        )
        add_check(
            checks,
            "official_overall_school_row_count",
            counts["official_overall_rows"]
            == EXPECTED_OFFICIAL_SCHOOLS,
            counts["official_overall_rows"],
            EXPECTED_OFFICIAL_SCHOOLS,
        )
        add_check(
            checks,
            "insufficient_school_row_count",
            counts["insufficient_rows"]
            == EXPECTED_INSUFFICIENT_SCHOOLS,
            counts["insufficient_rows"],
            EXPECTED_INSUFFICIENT_SCHOOLS,
        )
        add_check(
            checks,
            "gender_ranking_rows_preserved",
            counts["gender_rows"] == counts["source_gender_rows"],
            counts["gender_rows"],
            counts["source_gender_rows"],
            "Includes official and insufficient-data gender rows.",
        )
        add_check(
            checks,
            "event_family_ranking_rows_preserved",
            counts["event_family_rows"]
            == counts["source_event_family_rows"],
            counts["event_family_rows"],
            counts["source_event_family_rows"],
            "Includes official and insufficient-data family rows.",
        )
        add_check(
            checks,
            "athlete_school_contribution_row_count",
            counts["athlete_school_rows"]
            == EXPECTED_ATHLETE_SCHOOL_ROWS,
            counts["athlete_school_rows"],
            EXPECTED_ATHLETE_SCHOOL_ROWS,
        )
        add_check(
            checks,
            "overall_school_grain_unique",
            ranking_quality["duplicate_overall_school_rows"] == 0,
            ranking_quality["duplicate_overall_school_rows"],
            0,
        )
        add_check(
            checks,
            "official_ranks_complete",
            ranking_quality["missing_official_rank_rows"] == 0,
            ranking_quality["missing_official_rank_rows"],
            0,
        )
        add_check(
            checks,
            "official_ranks_unique",
            ranking_quality["distinct_official_rank_count"]
            == EXPECTED_OFFICIAL_SCHOOLS,
            ranking_quality["distinct_official_rank_count"],
            EXPECTED_OFFICIAL_SCHOOLS,
        )
        add_check(
            checks,
            "official_ranks_contiguous",
            ranking_quality["minimum_official_rank"] == 1
            and ranking_quality["maximum_official_rank"]
                == EXPECTED_OFFICIAL_SCHOOLS,
            {
                "minimum": ranking_quality["minimum_official_rank"],
                "maximum": ranking_quality["maximum_official_rank"],
            },
            {
                "minimum": 1,
                "maximum": EXPECTED_OFFICIAL_SCHOOLS,
            },
        )
        add_check(
            checks,
            "ranking_intervals_valid",
            ranking_quality["invalid_interval_rows"] == 0,
            ranking_quality["invalid_interval_rows"],
            0,
        )
        add_check(
            checks,
            "shrinkage_weights_valid",
            ranking_quality["invalid_shrinkage_rows"] == 0,
            ranking_quality["invalid_shrinkage_rows"],
            0,
        )
        add_check(
            checks,
            "posterior_scores_are_convex",
            ranking_quality["nonconvex_posterior_rows"] == 0,
            ranking_quality["nonconvex_posterior_rows"],
            0,
        )
        add_check(
            checks,
            "phase_5h_scores_reproduced",
            reproduction["score_mismatch_rows"] == 0,
            reproduction["score_mismatch_rows"],
            0,
        )
        add_check(
            checks,
            "phase_5h_ranks_reproduced",
            reproduction["rank_mismatch_rows"] == 0,
            reproduction["rank_mismatch_rows"],
            0,
        )
        add_check(
            checks,
            "phase_5h_eligibility_reproduced",
            reproduction["eligibility_mismatch_rows"] == 0,
            reproduction["eligibility_mismatch_rows"],
            0,
        )

        export_query(
            con,
            """
            SELECT *
            FROM official_overall_rankings
            ORDER BY official_overall_rank
            """,
            OUTPUT_DIR / "official_overall_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM overall_rankings
            ORDER BY
                official_rank_eligible DESC,
                official_overall_rank NULLS LAST,
                all_school_posterior_rank,
                school_name
            """,
            OUTPUT_DIR / "all_school_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM insufficient_data_schools
            ORDER BY all_school_posterior_rank, school_name
            """,
            OUTPUT_DIR / "insufficient_data_schools.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM gender_rankings
            WHERE canonical_gender_code = 'm'
            ORDER BY
                official_rank_eligible DESC,
                official_gender_rank NULLS LAST,
                all_school_gender_rank,
                school_name
            """,
            OUTPUT_DIR / "mens_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM gender_rankings
            WHERE canonical_gender_code = 'f'
            ORDER BY
                official_rank_eligible DESC,
                official_gender_rank NULLS LAST,
                all_school_gender_rank,
                school_name
            """,
            OUTPUT_DIR / "womens_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM event_family_rankings
            ORDER BY
                canonical_gender_code,
                event_family,
                official_rank_eligible DESC,
                official_event_family_rank NULLS LAST,
                all_school_family_rank,
                school_name
            """,
            OUTPUT_DIR / "event_family_rankings.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM school_score_components
            ORDER BY
                official_rank_eligible DESC,
                official_overall_rank NULLS LAST,
                all_school_posterior_rank,
                school_name
            """,
            OUTPUT_DIR / "school_score_components.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM ranking_school_metadata
            ORDER BY school_name, resolved_school_id
            """,
            OUTPUT_DIR / "school_metadata.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM publication_methodology
            ORDER BY methodology_key
            """,
            OUTPUT_DIR / "publication_methodology.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM sensitivity_variant_metrics
            ORDER BY variant_name
            """,
            OUTPUT_DIR / "sensitivity_variant_metrics.csv",
        )

        export_query(
            con,
            """
            SELECT *
            FROM sample_threshold_sensitivity
            ORDER BY minimum_sample
            """,
            OUTPUT_DIR / "sample_threshold_sensitivity.csv",
        )

        data_dictionary_rows = fetch_dicts(
            con,
            """
            SELECT
                table_name,
                column_name,
                data_type,
                is_nullable,
                ordinal_position
            FROM information_schema.columns
            WHERE table_catalog = CURRENT_DATABASE()
              AND table_schema = 'main'
            ORDER BY table_name, ordinal_position
            """
        )
        write_csv(
            OUTPUT_DIR / "data_dictionary.csv",
            data_dictionary_rows,
            list(data_dictionary_rows[0].keys())
                if data_dictionary_rows else [],
        )

        top_25 = fetch_dicts(
            con,
            """
            SELECT
                official_overall_rank,
                school_name,
                state_code,
                conference_name,
                athlete_school_unit_count,
                posterior_school_score,
                posterior_ci95_lower,
                posterior_ci95_upper,
                evidence_category
            FROM official_overall_rankings
            ORDER BY official_overall_rank
            LIMIT 25
            """
        )

        markdown_lines = [
            "# NCAA Division I Athlete Development Rankings — Version 1",
            "",
            f"Generated: {utc_now()}",
            "",
            "## Interpretation",
            "",
            "These rankings estimate how much athletes improved at each "
            "school beyond a school-held-out expected-improvement benchmark. "
            "They measure development, not absolute team quality.",
            "",
            "## Publication policy",
            "",
            f"- Official overall rank: at least "
            f"{OFFICIAL_OVERALL_MIN_SAMPLE} athlete-school units",
            f"- Official men's/women's rank: at least "
            f"{OFFICIAL_GENDER_MIN_SAMPLE} same-gender units",
            f"- Official event-family rank: at least "
            f"{OFFICIAL_EVENT_FAMILY_MIN_SAMPLE} athlete-family units",
            "- Each athlete contributes one total vote per school",
            "- Empirical-Bayes shrinkage stabilizes small samples",
            "- 95% intervals communicate uncertainty",
            "",
            "## Top 25 overall",
            "",
            "| Rank | School | Athletes | Posterior score | 95% CI | Evidence |",
            "|---:|---|---:|---:|---:|---|",
        ]

        for row in top_25:
            interval = (
                f"{float(row['posterior_ci95_lower']):.3f} to "
                f"{float(row['posterior_ci95_upper']):.3f}"
            )
            markdown_lines.append(
                f"| {int(row['official_overall_rank'])} "
                f"| {row['school_name']} "
                f"| {int(row['athlete_school_unit_count']):,} "
                f"| {float(row['posterior_school_score']):.4f} "
                f"| {interval} "
                f"| {row['evidence_category']} |"
            )

        (OUTPUT_DIR / "PUBLICATION_SUMMARY.md").write_text(
            "\n".join(markdown_lines) + "\n",
            encoding="utf-8",
        )

        summary_rows = [
            {
                "metric": "dataset_version",
                "value": DATASET_VERSION,
            },
            {
                "metric": "publication_policy_version",
                "value": PUBLICATION_POLICY_VERSION,
            },
            {
                "metric": "all_schools",
                "value": counts["overall_rows"],
            },
            {
                "metric": "official_overall_schools",
                "value": counts["official_overall_rows"],
            },
            {
                "metric": "insufficient_data_schools",
                "value": counts["insufficient_rows"],
            },
            {
                "metric": "athlete_school_contributions",
                "value": counts["athlete_school_rows"],
            },
            {
                "metric": "school_metadata_matches",
                "value":
                    counts["metadata_rows"]
                    - counts["unmatched_metadata_rows"],
            },
            {
                "metric": "top_ranked_school",
                "value": top_25[0]["school_name"] if top_25 else "",
            },
            {
                "metric": "top_ranked_score",
                "value":
                    top_25[0]["posterior_school_score"]
                    if top_25 else "",
            },
        ]
        write_csv(
            OUTPUT_DIR / "phase_5i_summary.csv",
            summary_rows,
            ["metric", "value"],
        )

        detected_rows = [
            {
                "semantic_field": key,
                "detected_column": value or "",
            }
            for key, value in detected.items()
        ]
        write_csv(
            OUTPUT_DIR / "detected_metadata_columns.csv",
            detected_rows,
            ["semantic_field", "detected_column"],
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

    output_hash = sha256_file(OUTPUT_DB)

    output_files = sorted(
        path
        for path in OUTPUT_DIR.iterdir()
        if path.is_file()
        and path.name not in {
            "output_manifest.csv",
            "hard_checks.csv",
            "terminal_output.txt",
        }
    )

    output_manifest_rows = [
        {
            "output_name": path.name,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "dataset_version": DATASET_VERSION,
            "publication_policy_version":
                PUBLICATION_POLICY_VERSION,
        }
        for path in output_files
    ]

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
        OUTPUT_DIR / "output_manifest.csv",
        output_manifest_rows,
        [
            "output_name",
            "path",
            "size_bytes",
            "sha256",
            "dataset_version",
            "publication_policy_version",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    top_row = top_25[0] if top_25 else None

    report = [
        "MILESTONE 5 PHASE 5I — PUBLICATION VERSION 1 FREEZE",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        "",
        "PUBLICATION CONTENTS",
        "-" * 78,
        f"All schools: {int(counts['overall_rows']):,}",
        f"Officially ranked schools: "
        f"{int(counts['official_overall_rows']):,}",
        f"Insufficient-data schools: "
        f"{int(counts['insufficient_rows']):,}",
        f"Athlete-school contribution rows: "
        f"{int(counts['athlete_school_rows']):,}",
        f"Readable school metadata matches: "
        f"{int(counts['metadata_rows'] - counts['unmatched_metadata_rows']):,}",
        "",
        "TOP OVERALL SCHOOL",
        "-" * 78,
        (
            f"{top_row['school_name']} | "
            f"posterior={float(top_row['posterior_school_score']):.6f} | "
            f"n={int(top_row['athlete_school_unit_count']):,}"
            if top_row
            else "No top-ranked school available."
        ),
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Publication version 1 frozen."
            if not failed
            else "FAIL — Do not publish or commit the final ranking package."
        ),
        "",
        "NEXT",
        "-" * 78,
        "Update milestones/milestone_05_athlete_development_rankings.md.",
        "Update README.md with Milestone 5 status and headline results.",
        "Review data/reference files, then stage scripts and references.",
        "Commit, push, and verify the milestone-5 branch is clean.",
    ]

    (OUTPUT_DIR / "phase_5i_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"All schools: {int(counts['overall_rows']):,}")
    print(
        f"Official overall rankings: "
        f"{int(counts['official_overall_rows']):,}"
    )
    print(
        f"Insufficient-data schools: "
        f"{int(counts['insufficient_rows']):,}"
    )
    print(
        f"School metadata matches: "
        f"{int(counts['metadata_rows'] - counts['unmatched_metadata_rows']):,}"
    )
    if top_row:
        print(
            f"Top-ranked school: {top_row['school_name']} "
            f"({float(top_row['posterior_school_score']):.6f})"
        )
    print(f"Output database: {OUTPUT_DB}")
    print(f"Output SHA-256: {output_hash}")
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
    print("Next: update documentation and commit Milestone 5.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
