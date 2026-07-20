#!/usr/bin/env python3
"""
Milestone 4: build finalized canonical-person layer v1.1.

This build consumes:
- canonical-person layer v1.0 diagnostic database;
- canonical-person conflict audit;
- finalized ambiguous result evidence v1.3;
- immutable source database.

Conflict resolution precedence
------------------------------
1. FINALIZED_RESULT_EVIDENCE
   - 158 exact result-page resolutions
   - 4 narrowly constrained person-season continuity resolutions
2. UNIQUE_BEST_ATTRIBUTION_EVIDENCE
3. UNIQUE_CANONICAL_TEAM_MATCHES_SOURCE
4. Existing canonical attribution for non-conflicting groups

The script writes a new database and does not modify any input.

Outputs
-------
data/processed/milestone4/canonical_person_layer_v1_1/
    canonical_person_layer_v1_1.duckdb
    canonical_person_layer_report.txt
    hard_checks.csv
    conflict_resolution_method_summary.csv
    deduplication_summary.csv
    identity_status_summary.csv
    component_size_summary.csv
    changed_team_summary.csv
    remaining_conflicts.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]

SOURCE_DB = (
    PROJECT_ROOT
    / "data/database/"
    / "ncaa_track_analytics.duckdb"
)

INPUT_PERSON_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_person_layer/"
    / "canonical_person_layer.duckdb"
)

CONFLICT_GROUP_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_person_team_conflict_audit/"
    / "conflict_group_summary.csv"
)

CONFLICT_AUDIT_CHECKS = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_person_team_conflict_audit/"
    / "hard_checks.csv"
)

FINAL_EVIDENCE_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "ambiguous_person_result_evidence_v1_3/"
    / "finalized_result_evidence.csv"
)

FINAL_EVIDENCE_CHECKS = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "ambiguous_person_result_evidence_v1_3/"
    / "hard_checks.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_person_layer_v1_1"
)

OUTPUT_DB = (
    OUTPUT_DIR
    / "canonical_person_layer_v1_1.duckdb"
)

LAYER_VERSION = (
    "m4_canonical_person_layer_v1.1"
)

EXPECTED_SOURCE_ROWS = 6_594_540
EXPECTED_SOURCE_ATHLETES = 193_961
EXPECTED_ELIGIBLE_ROWS = 6_474_538
EXPECTED_DEDUP_ROWS = 6_376_667
EXPECTED_DUPLICATE_ROWS_REMOVED = 97_871
EXPECTED_CANONICAL_PEOPLE = 192_561
EXPECTED_COMPONENT_PEOPLE = 1_352
EXPECTED_COMPONENT_PROFILES = 2_752

EXPECTED_CONFLICT_GROUPS = 35_694
EXPECTED_FINAL_EVIDENCE_GROUPS = 162
EXPECTED_UNIQUE_BEST_GROUPS = 1_247
EXPECTED_SOURCE_MATCH_GROUPS = 34_285


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--replace-output",
        action="store_true",
    )

    return parser.parse_args()


def sql_path(path: Path) -> str:
    return (
        path.resolve()
        .as_posix()
        .replace("'", "''")
    )


def file_state(
    path: Path,
) -> dict[str, int]:
    stat = path.stat()

    return {
        "size_bytes": int(stat.st_size),
        "modified_ns": int(stat.st_mtime_ns),
    }


def require_zero_failed_checks(
    path: Path,
    label: str,
) -> None:
    checks = pd.read_csv(path)

    failed = checks[
        checks["failed_row_count"] > 0
    ]

    if not failed.empty:
        raise RuntimeError(
            f"{label} has failed hard checks:\n"
            f"{failed.to_string(index=False)}"
        )


def require_inputs() -> None:
    required = [
        SOURCE_DB,
        INPUT_PERSON_DB,
        CONFLICT_GROUP_CSV,
        CONFLICT_AUDIT_CHECKS,
        FINAL_EVIDENCE_CSV,
        FINAL_EVIDENCE_CHECKS,
    ]

    for path in required:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )

    require_zero_failed_checks(
        CONFLICT_AUDIT_CHECKS,
        "Canonical-person conflict audit",
    )

    require_zero_failed_checks(
        FINAL_EVIDENCE_CHECKS,
        "Final ambiguous evidence package",
    )


def prepare_output(
    replace_output: bool,
) -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    generated = [
        OUTPUT_DB,
        OUTPUT_DIR
        / "canonical_person_layer_report.txt",
        OUTPUT_DIR / "hard_checks.csv",
        OUTPUT_DIR
        / "conflict_resolution_method_summary.csv",
        OUTPUT_DIR / "deduplication_summary.csv",
        OUTPUT_DIR / "identity_status_summary.csv",
        OUTPUT_DIR / "component_size_summary.csv",
        OUTPUT_DIR / "changed_team_summary.csv",
        OUTPUT_DIR / "remaining_conflicts.csv",
    ]

    existing = [
        path
        for path in generated
        if path.exists()
    ]

    if existing and not replace_output:
        raise FileExistsError(
            "Final canonical-person outputs already "
            "exist. Use --replace-output only after "
            "reviewing the existing build."
        )

    if replace_output:
        for path in existing:
            path.unlink()


def scalar(
    con: duckdb.DuckDBPyConnection,
    query: str,
) -> int:
    return int(
        con.execute(query).fetchone()[0]
    )


def main() -> None:
    args = parse_args()

    require_inputs()
    prepare_output(
        replace_output=args.replace_output,
    )

    source_before = file_state(SOURCE_DB)
    person_before = file_state(
        INPUT_PERSON_DB
    )

    conflicts = pd.read_csv(
        CONFLICT_GROUP_CSV,
        dtype={
            "canonical_person_id": str,
            "canonical_person_performance_id": str,
        },
    )

    final_evidence = pd.read_csv(
        FINAL_EVIDENCE_CSV,
        dtype={
            "canonical_person_id": str,
            "canonical_person_performance_id": str,
            "parsed_team_id": str,
        },
    )

    final_evidence = final_evidence[
        final_evidence[
            "resolution_status"
        ].isin(
            [
                "RESOLVED_EXACT_RESULT_ROW",
                "RESOLVED_PERSON_SEASON_CONTINUITY",
            ]
        )
    ].copy()

    if final_evidence[
        "canonical_person_performance_id"
    ].duplicated().any():
        raise RuntimeError(
            "Final evidence contains duplicate "
            "canonical-person performance IDs."
        )

    con = duckdb.connect(
        str(OUTPUT_DB)
    )

    try:
        con.execute("PRAGMA threads=4")
        con.execute(
            "PRAGMA preserve_insertion_order=false"
        )

        con.execute(
            f"""
            ATTACH '{sql_path(SOURCE_DB)}'
            AS source
            (READ_ONLY)
            """
        )

        con.execute(
            f"""
            ATTACH '{sql_path(INPUT_PERSON_DB)}'
            AS prior
            (READ_ONLY)
            """
        )

        con.register(
            "conflicts_input",
            conflicts,
        )

        con.register(
            "final_evidence_input",
            final_evidence,
        )

        print(
            "Copying canonical-person identity tables..."
        )

        con.execute(
            """
            CREATE TABLE canonical_person_bridge AS
            SELECT
                * EXCLUDE (person_layer_version),
                ? AS person_layer_version
            FROM prior.canonical_person_bridge
            """,
            [LAYER_VERSION],
        )

        con.execute(
            """
            CREATE UNIQUE INDEX
                canonical_person_bridge_athlete_idx
            ON canonical_person_bridge (
                athlete_id
            )
            """
        )

        con.execute(
            """
            CREATE INDEX
                canonical_person_bridge_person_idx
            ON canonical_person_bridge (
                canonical_person_id
            )
            """
        )

        con.execute(
            """
            CREATE TABLE canonical_people AS
            SELECT
                * EXCLUDE (person_layer_version),
                ? AS person_layer_version
            FROM prior.canonical_people
            """,
            [LAYER_VERSION],
        )

        con.execute(
            """
            CREATE UNIQUE INDEX
                canonical_people_person_idx
            ON canonical_people (
                canonical_person_id
            )
            """
        )

        print(
            "Building complete conflict-resolution "
            "registry..."
        )

        con.execute(
            """
            CREATE TEMP TABLE conflict_scope AS
            SELECT
                canonical_person_id,
                canonical_person_performance_id,
                evidence_resolution_class
            FROM conflicts_input
            """
        )

        con.execute(
            """
            CREATE TEMP TABLE final_evidence_registry AS
            SELECT
                canonical_person_id,
                canonical_person_performance_id,
                parsed_team_id
                    AS resolved_team_id,

                CASE resolution_status
                    WHEN
                    'RESOLVED_EXACT_RESULT_ROW'
                    THEN
                    'FINALIZED_EXACT_RESULT_PAGE'

                    WHEN
                    'RESOLVED_PERSON_SEASON_CONTINUITY'
                    THEN
                    'FINALIZED_PERSON_SEASON_CONTINUITY'

                    ELSE
                    'UNEXPECTED_FINAL_EVIDENCE_STATUS'
                END AS resolution_method,

                team_mapping_method
                    AS resolution_detail,

                1 AS resolution_priority

            FROM final_evidence_input
            """
        )

        con.execute(
            """
            CREATE TEMP TABLE unique_best_registry AS
            WITH candidate_teams AS (
                SELECT
                    m.canonical_person_id,
                    m.canonical_person_performance_id,
                    m.canonical_team_id,

                    MIN(
                        CASE m.attribution_precedence
                            WHEN
                            'PERFORMANCE_LEVEL_OVERRIDE'
                            THEN 1
                            WHEN
                            'RESULT_PAGE_SOURCE_FALLBACK'
                            THEN 2
                            WHEN
                            'CANONICAL_PROFILE_SECTION'
                            THEN 3
                            WHEN
                            'TRANSFER_FINAL_TEAM'
                            THEN 4
                            WHEN
                            'ORIGINAL_SOURCE_TEAM'
                            THEN 5
                            ELSE 9
                        END
                    ) AS best_evidence_rank

                FROM prior
                    .canonical_person_performance_map m

                JOIN conflict_scope c
                  ON m.canonical_person_performance_id
                        =
                        c.canonical_person_performance_id

                WHERE c.evidence_resolution_class
                    =
                    'UNIQUE_BEST_ATTRIBUTION_EVIDENCE'

                GROUP BY
                    m.canonical_person_id,
                    m.canonical_person_performance_id,
                    m.canonical_team_id
            ),

            ranked AS (
                SELECT
                    *,

                    DENSE_RANK()
                        OVER (
                            PARTITION BY
                                canonical_person_performance_id
                            ORDER BY
                                best_evidence_rank
                        ) AS evidence_rank_order

                FROM candidate_teams
            )

            SELECT
                canonical_person_id,
                canonical_person_performance_id,
                canonical_team_id
                    AS resolved_team_id,
                'UNIQUE_BEST_ATTRIBUTION_EVIDENCE'
                    AS resolution_method,
                'MIN_ATTRIBUTION_PRECEDENCE_RANK'
                    AS resolution_detail,
                2 AS resolution_priority

            FROM ranked

            WHERE evidence_rank_order = 1
            """
        )

        con.execute(
            """
            CREATE TEMP TABLE source_match_registry AS
            WITH matches AS (
                SELECT DISTINCT
                    m.canonical_person_id,
                    m.canonical_person_performance_id,
                    m.canonical_team_id
                        AS resolved_team_id

                FROM prior
                    .canonical_person_performance_map m

                JOIN conflict_scope c
                  ON m.canonical_person_performance_id
                        =
                        c.canonical_person_performance_id

                WHERE c.evidence_resolution_class
                    =
                    'UNIQUE_CANONICAL_TEAM_MATCHES_SOURCE'

                  AND NULLIF(
                        m.source_team_id,
                        ''
                      ) IS NOT NULL

                  AND m.source_team_id
                        = m.canonical_team_id
            )

            SELECT
                canonical_person_id,
                canonical_person_performance_id,
                resolved_team_id,
                'UNIQUE_CANONICAL_TEAM_MATCHES_SOURCE'
                    AS resolution_method,
                'SOURCE_TEAM_ID_EQUALS_CANONICAL_TEAM_ID'
                    AS resolution_detail,
                3 AS resolution_priority

            FROM matches
            """
        )

        con.execute(
            """
            CREATE TABLE conflict_resolution_registry AS
            WITH combined AS (
                SELECT *
                FROM final_evidence_registry

                UNION ALL

                SELECT *
                FROM unique_best_registry

                UNION ALL

                SELECT *
                FROM source_match_registry
            ),

            ranked AS (
                SELECT
                    *,

                    ROW_NUMBER()
                        OVER (
                            PARTITION BY
                                canonical_person_performance_id
                            ORDER BY
                                resolution_priority,
                                resolved_team_id
                        ) AS registry_rank,

                    COUNT(*)
                        OVER (
                            PARTITION BY
                                canonical_person_performance_id
                        ) AS candidate_resolution_rows

                FROM combined
            )

            SELECT
                canonical_person_id,
                canonical_person_performance_id,
                resolved_team_id,
                resolution_method,
                resolution_detail,
                resolution_priority,
                candidate_resolution_rows,
                ? AS person_layer_version

            FROM ranked

            WHERE registry_rank = 1
            """,
            [LAYER_VERSION],
        )

        con.execute(
            """
            CREATE UNIQUE INDEX
                conflict_resolution_registry_idx
            ON conflict_resolution_registry (
                canonical_person_performance_id
            )
            """
        )

        print(
            "Applying finalized team resolutions to "
            "the full performance map..."
        )

        con.execute(
            """
            CREATE TABLE canonical_person_performance_map AS
            SELECT
                m.performance_id,
                m.athlete_id,
                m.canonical_person_id,
                m.identity_status,
                m.component_size,
                m.canonical_person_performance_id,

                m.athlete_name,
                m.athlete_class,
                m.source_school,
                m.source_team_id,
                m.affiliation_id,

                m.season_id,
                m.season_year,
                m.season_type,
                m.season_label,

                m.meet_id,
                m.meet_name,
                m.meet_date_text,

                m.event_id,
                m.event,
                m.mark,
                m.secondary_mark,
                m.wind,
                m.place,
                m.competition_round,
                m.raw_place,

                m.meet_url,
                m.result_url,
                m.highlighted,

                COALESCE(
                    r.resolved_team_id,
                    m.canonical_team_id
                ) AS canonical_team_id,

                COALESCE(
                    t.team_name,
                    m.canonical_team_name
                ) AS canonical_team_name,

                COALESCE(
                    t.school_id,
                    m.canonical_school_id
                ) AS canonical_school_id,

                COALESCE(
                    s.school_name,
                    m.canonical_school_name
                ) AS canonical_school_name,

                COALESCE(
                    t.gender_code,
                    m.canonical_gender_code
                ) AS canonical_gender_code,

                CASE
                    WHEN r.resolved_team_id
                        IS NOT NULL
                    THEN
                        CASE
                            WHEN
                                t.in_division_i_directory
                            THEN 'NCAA_D1'
                            ELSE 'NON_D1'
                        END
                    ELSE
                        m.canonical_competition_level
                END AS canonical_competition_level,

                CASE
                    WHEN r.resolved_team_id
                        IS NOT NULL
                    THEN
                        'CANONICAL_PERSON_CONFLICT_RESOLUTION'
                    ELSE
                        m.attribution_precedence
                END AS attribution_precedence,

                CASE
                    WHEN r.resolved_team_id
                        IS NOT NULL
                    THEN
                        'PERSON_LEVEL_TEAM_CONFLICT_RESOLVED'
                    ELSE
                        m.attribution_status
                END AS attribution_status,

                CASE
                    WHEN r.resolved_team_id
                        IS NOT NULL
                    THEN
                        r.resolution_method
                    ELSE
                        m.attribution_method
                END AS attribution_method,

                CASE
                    WHEN r.resolved_team_id
                        IS NOT NULL
                    THEN
                        'HIGH'
                    ELSE
                        m.attribution_confidence
                END AS attribution_confidence,

                CASE
                    WHEN r.resolved_team_id
                        IS NOT NULL
                    THEN
                        r.resolution_detail
                    ELSE
                        m.evidence_source
                END AS evidence_source,

                CASE
                    WHEN r.resolved_team_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            t.in_division_i_directory,
                            FALSE
                        )
                    ELSE
                        m.d1_development_eligible
                END AS d1_development_eligible,

                CASE
                    WHEN r.resolved_team_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            t.in_division_i_directory,
                            FALSE
                        )
                    ELSE
                        m.school_stint_eligible
                END AS school_stint_eligible,

                m.source_file,
                m.source_chunk_file,

                CASE
                    WHEN r.resolved_team_id
                        IS NOT NULL
                    THEN TRUE
                    ELSE FALSE
                END AS person_team_resolution_applied,

                r.resolution_method
                    AS person_team_resolution_method,

                r.resolution_detail
                    AS person_team_resolution_detail,

                m.canonical_team_id
                    AS pre_resolution_team_id,

                ? AS person_layer_version

            FROM prior
                .canonical_person_performance_map m

            LEFT JOIN conflict_resolution_registry r
              ON m.canonical_person_performance_id
                    =
                    r.canonical_person_performance_id

            LEFT JOIN source.core.teams t
              ON r.resolved_team_id
                    = t.team_id

            LEFT JOIN source.core.schools s
              ON t.school_id = s.school_id
            """,
            [LAYER_VERSION],
        )

        con.execute(
            """
            CREATE UNIQUE INDEX
                person_performance_map_source_idx
            ON canonical_person_performance_map (
                performance_id
            )
            """
        )

        con.execute(
            """
            CREATE INDEX
                person_performance_map_person_perf_idx
            ON canonical_person_performance_map (
                canonical_person_performance_id
            )
            """
        )

        print(
            "Auditing remaining team conflicts..."
        )

        remaining_conflicts = con.execute(
            """
            SELECT
                canonical_person_id,
                canonical_person_performance_id,

                COUNT(*) AS source_performance_rows,

                COUNT(
                    DISTINCT athlete_id
                ) AS source_profile_count,

                COUNT(
                    DISTINCT canonical_team_id
                ) AS canonical_team_count,

                STRING_AGG(
                    DISTINCT athlete_id,
                    ' | '
                    ORDER BY athlete_id
                ) AS athlete_ids,

                STRING_AGG(
                    DISTINCT canonical_team_id,
                    ' | '
                    ORDER BY canonical_team_id
                ) AS canonical_team_ids,

                MIN(athlete_name)
                    AS athlete_name,

                MIN(season_id)
                    AS season_id,

                MIN(meet_name)
                    AS meet_name,

                MIN(event)
                    AS event,

                MIN(mark)
                    AS mark

            FROM canonical_person_performance_map

            GROUP BY
                canonical_person_id,
                canonical_person_performance_id

            HAVING COUNT(
                DISTINCT canonical_team_id
            ) > 1

            ORDER BY
                canonical_team_count DESC,
                source_performance_rows DESC,
                canonical_person_id
            """
        ).fetchdf()

        remaining_conflicts.to_csv(
            OUTPUT_DIR
            / "remaining_conflicts.csv",
            index=False,
        )

        print(
            "Building finalized deduplicated "
            "person-performances..."
        )

        con.execute(
            """
            CREATE TABLE canonical_person_performances AS
            WITH ranked AS (
                SELECT
                    m.*,

                    COUNT(*)
                        OVER (
                            PARTITION BY
                                canonical_person_performance_id
                        )
                        AS source_performance_rows,

                    COUNT(
                        DISTINCT athlete_id
                    )
                        OVER (
                            PARTITION BY
                                canonical_person_performance_id
                        )
                        AS source_profile_count,

                    ROW_NUMBER()
                        OVER (
                            PARTITION BY
                                canonical_person_performance_id
                            ORDER BY
                                CASE
                                    WHEN
                                        person_team_resolution_applied
                                    THEN 1
                                    ELSE 2
                                END,
                                CASE attribution_precedence
                                    WHEN
                                    'CANONICAL_PERSON_CONFLICT_RESOLUTION'
                                    THEN 1
                                    WHEN
                                    'PERFORMANCE_LEVEL_OVERRIDE'
                                    THEN 2
                                    WHEN
                                    'RESULT_PAGE_SOURCE_FALLBACK'
                                    THEN 3
                                    WHEN
                                    'CANONICAL_PROFILE_SECTION'
                                    THEN 4
                                    WHEN
                                    'TRANSFER_FINAL_TEAM'
                                    THEN 5
                                    WHEN
                                    'ORIGINAL_SOURCE_TEAM'
                                    THEN 6
                                    ELSE 9
                                END,
                                performance_id
                        )
                        AS canonical_row_rank

                FROM canonical_person_performance_map m
            )

            SELECT
                canonical_person_performance_id,
                canonical_person_id,

                performance_id
                    AS representative_performance_id,

                athlete_id
                    AS representative_athlete_id,

                athlete_name,
                athlete_class,

                source_performance_rows,
                source_profile_count,

                season_id,
                season_year,
                season_type,
                season_label,

                meet_id,
                meet_name,
                meet_date_text,

                event_id,
                event,
                mark,
                secondary_mark,
                wind,
                place,
                competition_round,
                raw_place,

                meet_url,
                result_url,
                highlighted,

                canonical_team_id,
                canonical_team_name,
                canonical_school_id,
                canonical_school_name,
                canonical_gender_code,
                canonical_competition_level,

                attribution_precedence,
                attribution_status,
                attribution_method,
                attribution_confidence,
                evidence_source,

                d1_development_eligible,
                school_stint_eligible,

                person_team_resolution_applied,
                person_team_resolution_method,
                person_team_resolution_detail,

                person_layer_version

            FROM ranked

            WHERE canonical_row_rank = 1
            """
        )

        con.execute(
            """
            CREATE UNIQUE INDEX
                canonical_person_performances_idx
            ON canonical_person_performances (
                canonical_person_performance_id
            )
            """
        )

        con.execute(
            """
            CREATE INDEX
                canonical_person_performances_person_idx
            ON canonical_person_performances (
                canonical_person_id
            )
            """
        )

        con.execute(
            """
            CREATE VIEW school_stint_person_performances AS
            SELECT *
            FROM canonical_person_performances
            WHERE school_stint_eligible
            """
        )

        print("Building summaries...")

        conflict_resolution_summary = con.execute(
            """
            SELECT
                resolution_method,
                resolution_detail,
                COUNT(*)
                    AS conflict_group_count
            FROM conflict_resolution_registry
            GROUP BY
                resolution_method,
                resolution_detail
            ORDER BY
                conflict_group_count DESC,
                resolution_method
            """
        ).fetchdf()

        deduplication_summary = con.execute(
            """
            SELECT
                CASE
                    WHEN source_profile_count = 1
                    THEN
                        'SINGLE_PROFILE_SIGNATURE'
                    ELSE
                        'MULTI_PROFILE_DUPLICATE'
                END AS deduplication_status,

                COUNT(*)
                    AS canonical_performance_rows,

                SUM(source_performance_rows)
                    AS source_performance_rows,

                SUM(
                    source_performance_rows - 1
                ) AS duplicate_rows_removed

            FROM canonical_person_performances

            GROUP BY deduplication_status

            ORDER BY deduplication_status
            """
        ).fetchdf()

        identity_status_summary = con.execute(
            """
            SELECT
                identity_status,
                COUNT(*) AS athlete_profile_count,
                COUNT(
                    DISTINCT canonical_person_id
                ) AS canonical_person_count
            FROM canonical_person_bridge
            GROUP BY identity_status
            ORDER BY identity_status
            """
        ).fetchdf()

        component_size_summary = con.execute(
            """
            SELECT
                profile_count,
                COUNT(*) AS canonical_person_count
            FROM canonical_people
            GROUP BY profile_count
            ORDER BY profile_count
            """
        ).fetchdf()

        changed_team_summary = con.execute(
            """
            SELECT
                person_team_resolution_method,
                pre_resolution_team_id,
                canonical_team_id,
                COUNT(
                    DISTINCT canonical_person_performance_id
                ) AS conflict_group_count,
                COUNT(*) AS source_row_count,
                COUNT(
                    DISTINCT canonical_person_id
                ) AS canonical_person_count
            FROM canonical_person_performance_map
            WHERE person_team_resolution_applied
            GROUP BY
                person_team_resolution_method,
                pre_resolution_team_id,
                canonical_team_id
            ORDER BY
                conflict_group_count DESC,
                pre_resolution_team_id,
                canonical_team_id
            """
        ).fetchdf()

        conflict_resolution_summary.to_csv(
            OUTPUT_DIR
            / "conflict_resolution_method_summary.csv",
            index=False,
        )

        deduplication_summary.to_csv(
            OUTPUT_DIR
            / "deduplication_summary.csv",
            index=False,
        )

        identity_status_summary.to_csv(
            OUTPUT_DIR
            / "identity_status_summary.csv",
            index=False,
        )

        component_size_summary.to_csv(
            OUTPUT_DIR
            / "component_size_summary.csv",
            index=False,
        )

        changed_team_summary.to_csv(
            OUTPUT_DIR
            / "changed_team_summary.csv",
            index=False,
        )

        source_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM source.core.performances
            """,
        )

        source_athletes = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM source.core.athletes
            """,
        )

        bridge_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_bridge
            """,
        )

        canonical_people_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_people
            """,
        )

        component_people = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_people
            WHERE identity_status
                =
                'HIGH_CONFIDENCE_COMPONENT'
            """,
        )

        component_profiles = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_bridge
            WHERE identity_status
                =
                'HIGH_CONFIDENCE_COMPONENT'
            """,
        )

        map_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_performance_map
            """,
        )

        distinct_map_ids = scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT performance_id
            )
            FROM canonical_person_performance_map
            """,
        )

        resolution_registry_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM conflict_resolution_registry
            """,
        )

        final_evidence_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM conflict_resolution_registry
            WHERE resolution_method IN (
                'FINALIZED_EXACT_RESULT_PAGE',
                'FINALIZED_PERSON_SEASON_CONTINUITY'
            )
            """,
        )

        unique_best_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM conflict_resolution_registry
            WHERE resolution_method
                =
                'UNIQUE_BEST_ATTRIBUTION_EVIDENCE'
            """,
        )

        source_match_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM conflict_resolution_registry
            WHERE resolution_method
                =
                'UNIQUE_CANONICAL_TEAM_MATCHES_SOURCE'
            """,
        )

        registry_missing_conflicts = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM conflict_scope c
            LEFT JOIN conflict_resolution_registry r
              USING (
                canonical_person_performance_id
              )
            WHERE
                r.canonical_person_performance_id
                    IS NULL
            """,
        )

        registry_outside_conflicts = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM conflict_resolution_registry r
            LEFT JOIN conflict_scope c
              USING (
                canonical_person_performance_id
              )
            WHERE
                c.canonical_person_performance_id
                    IS NULL
            """,
        )

        duplicate_registry_ids = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    canonical_person_performance_id
                FROM conflict_resolution_registry
                GROUP BY
                    canonical_person_performance_id
                HAVING COUNT(*) > 1
            )
            """,
        )

        resolved_map_group_count = scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT canonical_person_performance_id
            )
            FROM canonical_person_performance_map
            WHERE person_team_resolution_applied
            """,
        )

        dedup_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_performances
            """,
        )

        duplicate_rows_removed = (
            map_rows - dedup_rows
        )

        duplicate_dedup_ids = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    canonical_person_performance_id
                FROM canonical_person_performances
                GROUP BY
                    canonical_person_performance_id
                HAVING COUNT(*) > 1
            )
            """,
        )

        map_missing_dedup = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_performance_map m
            LEFT JOIN canonical_person_performances d
              USING (
                canonical_person_performance_id
              )
            WHERE
                d.canonical_person_performance_id
                    IS NULL
            """,
        )

        non_d1_stint_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_performances
            WHERE school_stint_eligible
              AND canonical_competition_level
                    != 'NCAA_D1'
            """,
        )

        d1_ineligible_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_performances
            WHERE d1_development_eligible
              AND canonical_competition_level
                    != 'NCAA_D1'
            """,
        )

        source_after = file_state(SOURCE_DB)
        person_after = file_state(
            INPUT_PERSON_DB
        )

        checks = pd.DataFrame(
            [
                (
                    "source_performance_rows",
                    abs(
                        source_rows
                        - EXPECTED_SOURCE_ROWS
                    ),
                    source_rows,
                    EXPECTED_SOURCE_ROWS,
                ),
                (
                    "source_athlete_rows",
                    abs(
                        source_athletes
                        - EXPECTED_SOURCE_ATHLETES
                    ),
                    source_athletes,
                    EXPECTED_SOURCE_ATHLETES,
                ),
                (
                    "bridge_rows",
                    abs(
                        bridge_rows
                        - EXPECTED_SOURCE_ATHLETES
                    ),
                    bridge_rows,
                    EXPECTED_SOURCE_ATHLETES,
                ),
                (
                    "canonical_people_rows",
                    abs(
                        canonical_people_rows
                        - EXPECTED_CANONICAL_PEOPLE
                    ),
                    canonical_people_rows,
                    EXPECTED_CANONICAL_PEOPLE,
                ),
                (
                    "component_people",
                    abs(
                        component_people
                        - EXPECTED_COMPONENT_PEOPLE
                    ),
                    component_people,
                    EXPECTED_COMPONENT_PEOPLE,
                ),
                (
                    "component_profiles",
                    abs(
                        component_profiles
                        - EXPECTED_COMPONENT_PROFILES
                    ),
                    component_profiles,
                    EXPECTED_COMPONENT_PROFILES,
                ),
                (
                    "eligible_map_rows",
                    abs(
                        map_rows
                        - EXPECTED_ELIGIBLE_ROWS
                    ),
                    map_rows,
                    EXPECTED_ELIGIBLE_ROWS,
                ),
                (
                    "distinct_mapped_performance_ids",
                    abs(
                        distinct_map_ids
                        - EXPECTED_ELIGIBLE_ROWS
                    ),
                    distinct_map_ids,
                    EXPECTED_ELIGIBLE_ROWS,
                ),
                (
                    "conflict_resolution_registry_rows",
                    abs(
                        resolution_registry_rows
                        - EXPECTED_CONFLICT_GROUPS
                    ),
                    resolution_registry_rows,
                    EXPECTED_CONFLICT_GROUPS,
                ),
                (
                    "finalized_evidence_resolution_rows",
                    abs(
                        final_evidence_rows
                        - EXPECTED_FINAL_EVIDENCE_GROUPS
                    ),
                    final_evidence_rows,
                    EXPECTED_FINAL_EVIDENCE_GROUPS,
                ),
                (
                    "unique_best_resolution_rows",
                    abs(
                        unique_best_rows
                        - EXPECTED_UNIQUE_BEST_GROUPS
                    ),
                    unique_best_rows,
                    EXPECTED_UNIQUE_BEST_GROUPS,
                ),
                (
                    "source_match_resolution_rows",
                    abs(
                        source_match_rows
                        - EXPECTED_SOURCE_MATCH_GROUPS
                    ),
                    source_match_rows,
                    EXPECTED_SOURCE_MATCH_GROUPS,
                ),
                (
                    "conflicts_missing_registry_resolution",
                    registry_missing_conflicts,
                    registry_missing_conflicts,
                    0,
                ),
                (
                    "registry_rows_outside_conflict_scope",
                    registry_outside_conflicts,
                    registry_outside_conflicts,
                    0,
                ),
                (
                    "duplicate_registry_ids",
                    duplicate_registry_ids,
                    duplicate_registry_ids,
                    0,
                ),
                (
                    "resolved_map_group_count",
                    abs(
                        resolved_map_group_count
                        - EXPECTED_CONFLICT_GROUPS
                    ),
                    resolved_map_group_count,
                    EXPECTED_CONFLICT_GROUPS,
                ),
                (
                    "remaining_person_team_conflicts",
                    len(remaining_conflicts),
                    len(remaining_conflicts),
                    0,
                ),
                (
                    "deduplicated_rows",
                    abs(
                        dedup_rows
                        - EXPECTED_DEDUP_ROWS
                    ),
                    dedup_rows,
                    EXPECTED_DEDUP_ROWS,
                ),
                (
                    "duplicate_rows_removed",
                    abs(
                        duplicate_rows_removed
                        - EXPECTED_DUPLICATE_ROWS_REMOVED
                    ),
                    duplicate_rows_removed,
                    EXPECTED_DUPLICATE_ROWS_REMOVED,
                ),
                (
                    "duplicate_deduplicated_ids",
                    duplicate_dedup_ids,
                    duplicate_dedup_ids,
                    0,
                ),
                (
                    "map_rows_missing_from_dedup",
                    map_missing_dedup,
                    map_missing_dedup,
                    0,
                ),
                (
                    "non_d1_school_stint_eligible_rows",
                    non_d1_stint_rows,
                    non_d1_stint_rows,
                    0,
                ),
                (
                    "non_d1_d1_development_eligible_rows",
                    d1_ineligible_rows,
                    d1_ineligible_rows,
                    0,
                ),
                (
                    "source_size_unchanged",
                    abs(
                        source_after["size_bytes"]
                        - source_before["size_bytes"]
                    ),
                    source_after["size_bytes"],
                    source_before["size_bytes"],
                ),
                (
                    "source_modified_time_unchanged",
                    abs(
                        source_after["modified_ns"]
                        - source_before["modified_ns"]
                    ),
                    source_after["modified_ns"],
                    source_before["modified_ns"],
                ),
                (
                    "input_person_db_size_unchanged",
                    abs(
                        person_after["size_bytes"]
                        - person_before["size_bytes"]
                    ),
                    person_after["size_bytes"],
                    person_before["size_bytes"],
                ),
                (
                    "input_person_db_modified_time_unchanged",
                    abs(
                        person_after["modified_ns"]
                        - person_before["modified_ns"]
                    ),
                    person_after["modified_ns"],
                    person_before["modified_ns"],
                ),
            ],
            columns=[
                "check_name",
                "failed_row_count",
                "observed_value",
                "expected_value",
            ],
        )

        checks.to_csv(
            OUTPUT_DIR / "hard_checks.csv",
            index=False,
        )

        failed = int(
            (
                checks["failed_row_count"] > 0
            ).sum()
        )

        report = f"""MILESTONE 4 FINAL CANONICAL-PERSON LAYER V1.1
============================================================
Layer version: {LAYER_VERSION}
Source database modified: no
Input canonical-person database modified: no
Conflict-audit outputs modified: no
Final evidence outputs modified: no

IDENTITY
- Source athlete profiles: {source_athletes:,}
- Canonical people: {canonical_people_rows:,}
- High-confidence multi-profile people:
  {component_people:,}
- Profiles in high-confidence components:
  {component_profiles:,}

CONFLICT RESOLUTION
- Total person-performance conflict groups:
  {resolution_registry_rows:,}
- Finalized result evidence:
  {final_evidence_rows:,}
- Unique best attribution evidence:
  {unique_best_rows:,}
- Unique source-team matches:
  {source_match_rows:,}
- Remaining conflicts:
  {len(remaining_conflicts):,}

PERFORMANCE LAYER
- Mapped eligible source rows:
  {map_rows:,}
- Deduplicated person-performance rows:
  {dedup_rows:,}
- Duplicate source rows removed:
  {duplicate_rows_removed:,}

ELIGIBILITY
- Non-D1 rows marked school-stint eligible:
  {non_d1_stint_rows:,}
- Non-D1 rows marked D1-development eligible:
  {d1_ineligible_rows:,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

INTERPRETATION
All duplicate-person performance groups now have one explicit canonical team.
The original source-performance map remains complete, while the deduplicated
person-performance table retains one representative row per exact performance
within a canonical person. Non-D1 resolved performances remain excluded from
D1 development and school-stint analysis.
"""

        (
            OUTPUT_DIR
            / "canonical_person_layer_report.txt"
        ).write_text(
            report,
            encoding="utf-8",
        )

        con.execute("CHECKPOINT")

        print(
            "Final canonical-person layer v1.1 "
            "build complete."
        )
        print(f"Database: {OUTPUT_DB}")
        print(
            "Conflict registry rows: "
            f"{resolution_registry_rows:,}"
        )
        print(
            "Remaining conflicts: "
            f"{len(remaining_conflicts):,}"
        )
        print(
            "Deduplicated rows: "
            f"{dedup_rows:,}"
        )
        print(
            "Duplicate rows removed: "
            f"{duplicate_rows_removed:,}"
        )
        print(f"Failed checks: {failed:,}.")

        if failed:
            raise SystemExit(1)

    finally:
        for name in [
            "conflicts_input",
            "final_evidence_input",
        ]:
            try:
                con.unregister(name)
            except Exception:
                pass

        con.close()


if __name__ == "__main__":
    main()
