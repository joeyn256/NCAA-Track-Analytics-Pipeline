#!/usr/bin/env python3
"""
Milestone 4: build provisional canonical-person and deduplicated performance layer.

This script reads:
- the immutable Milestone 3 source database;
- canonical performance attribution v1.1;
- the validated duplicate-athlete identity preflight outputs.

It writes a separate DuckDB database and audit files. It does not modify any
input database or identity-preflight output.

Identity policy
---------------
- Profiles in validated high-confidence components share a provisional
  canonical_person_id.
- Every unmatched athlete profile receives its own singleton person ID.
- No medium-confidence or review pair is merged.

Performance deduplication policy
--------------------------------
Exact individual or relay performance rows are grouped within a canonical
person using:
- season_id
- meet_id
- event
- mark
- secondary_mark
- wind
- place
- competition_round
- raw_place
- result_url

The canonical team is not part of the signature. Instead, conflicting
canonical-team assignments inside an otherwise identical person-performance
group are treated as a blocking audit failure.

Outputs
-------
data/processed/milestone4/canonical_person_layer/
    canonical_person_layer.duckdb
    person_layer_report.txt
    hard_checks.csv
    identity_status_summary.csv
    component_size_summary.csv
    deduplication_summary.csv
    conflicting_person_performance_teams.csv
    multi_profile_person_summary.csv
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]

SOURCE_DB = (
    PROJECT_ROOT
    / "data/database/"
    / "ncaa_track_analytics.duckdb"
)

ATTRIBUTION_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_performance_attribution_v1_1/"
    / "canonical_performance_attribution_v1_1.duckdb"
)

IDENTITY_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "duplicate_athlete_identity_preflight_v1_1"
)

COMPONENT_MEMBERS_CSV = (
    IDENTITY_DIR
    / "candidate_component_members.csv"
)

COMPONENTS_CSV = (
    IDENTITY_DIR
    / "candidate_components.csv"
)

HIGH_CONFIDENCE_PAIRS_CSV = (
    IDENTITY_DIR
    / "high_confidence_profile_pairs.csv"
)

IDENTITY_CHECKS_CSV = (
    IDENTITY_DIR
    / "hard_checks.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_person_layer"
)

OUTPUT_DB = (
    OUTPUT_DIR
    / "canonical_person_layer.duckdb"
)

LAYER_VERSION = (
    "m4_canonical_person_layer_v1.0"
)

EXPECTED_SOURCE_ROWS = 6_594_540
EXPECTED_SOURCE_ATHLETES = 193_961
EXPECTED_ELIGIBLE_ROWS = 6_474_538
EXPECTED_COMPONENTS = 1_352
EXPECTED_COMPONENT_PROFILES = 2_752


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


def require_inputs() -> None:
    required = [
        SOURCE_DB,
        ATTRIBUTION_DB,
        COMPONENT_MEMBERS_CSV,
        COMPONENTS_CSV,
        HIGH_CONFIDENCE_PAIRS_CSV,
        IDENTITY_CHECKS_CSV,
    ]

    for path in required:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )

    checks = pd.read_csv(
        IDENTITY_CHECKS_CSV
    )

    failed = checks[
        checks["failed_row_count"] > 0
    ]

    if not failed.empty:
        raise RuntimeError(
            "The identity preflight still has failed "
            "hard checks. Canonical-person construction "
            "is blocked."
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
        OUTPUT_DIR / "person_layer_report.txt",
        OUTPUT_DIR / "hard_checks.csv",
        OUTPUT_DIR / "identity_status_summary.csv",
        OUTPUT_DIR / "component_size_summary.csv",
        OUTPUT_DIR / "deduplication_summary.csv",
        OUTPUT_DIR
        / "conflicting_person_performance_teams.csv",
        OUTPUT_DIR / "multi_profile_person_summary.csv",
    ]

    existing = [
        path
        for path in generated
        if path.exists()
    ]

    if existing and not replace_output:
        raise FileExistsError(
            "Canonical-person layer outputs already "
            "exist. Use --replace-output only after "
            "reviewing them."
        )

    if replace_output:
        for path in existing:
            path.unlink()


def file_state(
    path: Path,
) -> dict[str, int]:
    stat = path.stat()

    return {
        "size_bytes": int(stat.st_size),
        "modified_ns": int(stat.st_mtime_ns),
    }


def scalar(
    con: duckdb.DuckDBPyConnection,
    query: str,
) -> int:
    return int(
        con.execute(query).fetchone()[0]
    )


def singleton_person_id(
    athlete_id: str,
) -> str:
    return f"m4person_single_{athlete_id}"


def main() -> None:
    args = parse_args()

    require_inputs()
    prepare_output(
        replace_output=args.replace_output,
    )

    source_before = file_state(SOURCE_DB)
    attribution_before = file_state(
        ATTRIBUTION_DB
    )

    component_members = pd.read_csv(
        COMPONENT_MEMBERS_CSV,
        dtype={
            "candidate_person_id": str,
            "athlete_id": str,
        },
    )

    components = pd.read_csv(
        COMPONENTS_CSV,
        dtype={
            "candidate_person_id": str,
        },
    )

    high_confidence_pairs = pd.read_csv(
        HIGH_CONFIDENCE_PAIRS_CSV,
        dtype={
            "athlete_id_1": str,
            "athlete_id_2": str,
        },
    )

    if component_members["athlete_id"].duplicated().any():
        raise RuntimeError(
            "An athlete appears more than once in the "
            "validated component-member file."
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
            ATTACH '{sql_path(ATTRIBUTION_DB)}'
            AS attribution
            (READ_ONLY)
            """
        )

        con.register(
            "component_members_input",
            component_members,
        )

        con.register(
            "components_input",
            components,
        )

        con.register(
            "high_confidence_pairs_input",
            high_confidence_pairs,
        )

        print(
            "Building canonical-person bridge..."
        )

        con.execute(
            """
            CREATE TABLE canonical_person_bridge AS
            WITH component_profiles AS (
                SELECT
                    candidate_person_id
                        AS canonical_person_id,
                    athlete_id,
                    CAST(component_size AS INTEGER)
                        AS component_size,
                    athlete_name,
                    normalized_name,
                    current_school_name,
                    current_team_id,
                    dominant_gender_code,
                    CAST(
                        total_individual_signatures
                        AS BIGINT
                    ) AS total_individual_signatures,
                    CAST(
                        first_performance_year
                        AS INTEGER
                    ) AS first_performance_year,
                    CAST(
                        last_performance_year
                        AS INTEGER
                    ) AS last_performance_year
                FROM component_members_input
            )
            SELECT
                a.athlete_id,

                COALESCE(
                    c.canonical_person_id,
                    'm4person_single_'
                        || a.athlete_id
                ) AS canonical_person_id,

                CASE
                    WHEN c.athlete_id IS NOT NULL
                    THEN
                        'HIGH_CONFIDENCE_COMPONENT'
                    ELSE
                        'SINGLE_PROFILE'
                END AS identity_status,

                COALESCE(
                    c.component_size,
                    1
                ) AS component_size,

                MIN(a.athlete_id)
                    OVER (
                        PARTITION BY COALESCE(
                            c.canonical_person_id,
                            'm4person_single_'
                                || a.athlete_id
                        )
                    )
                    AS representative_athlete_id,

                a.athlete_name,
                c.normalized_name,
                a.current_school_name,
                a.current_team_id,
                c.dominant_gender_code,
                c.total_individual_signatures,
                c.first_performance_year,
                c.last_performance_year,

                CASE
                    WHEN c.athlete_id IS NOT NULL
                    THEN
                        'm4_duplicate_athlete_identity_'
                        || 'preflight_v1.2'
                    ELSE
                        'SOURCE_PROFILE_SINGLETON'
                END AS identity_evidence_source,

                ?
                    AS person_layer_version

            FROM source.core.athletes a

            LEFT JOIN component_profiles c
              ON a.athlete_id = c.athlete_id
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

        print(
            "Building canonical-person summary..."
        )

        con.execute(
            """
            CREATE TABLE canonical_people AS
            SELECT
                canonical_person_id,
                identity_status,
                MAX(component_size)
                    AS profile_count,
                MIN(representative_athlete_id)
                    AS representative_athlete_id,
                STRING_AGG(
                    athlete_id,
                    ' | '
                    ORDER BY athlete_id
                ) AS athlete_ids,
                STRING_AGG(
                    DISTINCT athlete_name,
                    ' | '
                    ORDER BY athlete_name
                ) AS athlete_names,
                STRING_AGG(
                    DISTINCT current_school_name,
                    ' | '
                    ORDER BY current_school_name
                ) FILTER (
                    WHERE NULLIF(
                        current_school_name,
                        ''
                    ) IS NOT NULL
                ) AS current_school_names,
                STRING_AGG(
                    DISTINCT current_team_id,
                    ' | '
                    ORDER BY current_team_id
                ) FILTER (
                    WHERE NULLIF(
                        current_team_id,
                        ''
                    ) IS NOT NULL
                ) AS current_team_ids,
                MIN(normalized_name)
                    AS normalized_name,
                MIN(dominant_gender_code)
                    AS dominant_gender_code,
                MIN(first_performance_year)
                    AS first_performance_year,
                MAX(last_performance_year)
                    AS last_performance_year,
                MIN(person_layer_version)
                    AS person_layer_version
            FROM canonical_person_bridge
            GROUP BY
                canonical_person_id,
                identity_status
            """
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
            "Mapping eligible performances to "
            "canonical people..."
        )

        con.execute(
            """
            CREATE TABLE canonical_person_performance_map AS
            SELECT
                p.performance_id,
                p.athlete_id,
                b.canonical_person_id,
                b.identity_status,
                b.component_size,

                md5(
                    b.canonical_person_id
                    || chr(31)
                    || COALESCE(p.season_id, '')
                    || chr(31)
                    || COALESCE(p.meet_id, '')
                    || chr(31)
                    || COALESCE(p.event, '')
                    || chr(31)
                    || COALESCE(p.mark, '')
                    || chr(31)
                    || COALESCE(
                        p.secondary_mark,
                        ''
                    )
                    || chr(31)
                    || COALESCE(p.wind, '')
                    || chr(31)
                    || COALESCE(p.place, '')
                    || chr(31)
                    || COALESCE(
                        p.competition_round,
                        ''
                    )
                    || chr(31)
                    || COALESCE(
                        p.raw_place,
                        ''
                    )
                    || chr(31)
                    || COALESCE(
                        p.result_url,
                        ''
                    )
                ) AS canonical_person_performance_id,

                p.athlete_name,
                p.athlete_class,
                p.school AS source_school,
                p.team_id AS source_team_id,
                p.affiliation_id,

                p.season_id,
                p.season_year,
                p.season_type,
                p.season_label,

                p.meet_id,
                p.meet_name,
                p.meet_date_text,

                p.event_id,
                p.event,
                p.mark,
                p.secondary_mark,
                p.wind,
                p.place,
                p.competition_round,
                p.raw_place,

                p.meet_url,
                p.result_url,
                p.highlighted,

                a.canonical_team_id,
                a.canonical_team_name,
                a.canonical_school_id,
                a.canonical_school_name,
                a.canonical_gender_code,
                a.canonical_competition_level,

                a.attribution_precedence,
                a.attribution_status,
                a.attribution_method,
                a.attribution_confidence,
                a.evidence_source,

                a.d1_development_eligible,
                a.school_stint_eligible,

                p.source_file,
                p.source_chunk_file,

                ?
                    AS person_layer_version

            FROM source.core.performances p

            JOIN attribution.main
                .canonical_performance_attribution a
              ON p.performance_id = a.performance_id

            JOIN canonical_person_bridge b
              ON p.athlete_id = b.athlete_id

            WHERE a.school_stint_eligible
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
            "Auditing conflicting team assignments..."
        )

        conflicts = con.execute(
            """
            SELECT
                canonical_person_id,
                canonical_person_performance_id,

                COUNT(*)
                    AS source_performance_rows,

                COUNT(DISTINCT athlete_id)
                    AS source_profile_count,

                COUNT(
                    DISTINCT canonical_team_id
                ) AS canonical_team_count,

                STRING_AGG(
                    DISTINCT athlete_id,
                    ' | '
                    ORDER BY athlete_id
                ) AS athlete_ids,

                STRING_AGG(
                    DISTINCT performance_id,
                    ' | '
                    ORDER BY performance_id
                ) AS performance_ids,

                STRING_AGG(
                    DISTINCT canonical_team_id,
                    ' | '
                    ORDER BY canonical_team_id
                ) AS canonical_team_ids,

                MIN(athlete_name)
                    AS athlete_name,

                MIN(season_id)
                    AS season_id,

                MIN(meet_id)
                    AS meet_id,

                MIN(meet_name)
                    AS meet_name,

                MIN(meet_date_text)
                    AS meet_date_text,

                MIN(event)
                    AS event,

                MIN(mark)
                    AS mark,

                MIN(place)
                    AS place,

                MIN(result_url)
                    AS result_url

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
                canonical_person_id,
                canonical_person_performance_id
            """
        ).fetchdf()

        conflicts.to_csv(
            OUTPUT_DIR
            / "conflicting_person_performance_teams.csv",
            index=False,
        )

        print(
            "Building deduplicated canonical-person "
            "performances..."
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
                                CASE attribution_precedence
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

        print(
            "Building audit summaries..."
        )

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

        deduplication_summary = con.execute(
            """
            SELECT
                CASE
                    WHEN source_profile_count = 1
                    THEN 'SINGLE_PROFILE_SIGNATURE'
                    ELSE 'MULTI_PROFILE_DUPLICATE'
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

        multi_profile_person_summary = con.execute(
            """
            SELECT
                p.canonical_person_id,
                p.profile_count,
                p.athlete_ids,
                p.athlete_names,
                p.current_school_names,
                p.current_team_ids,
                p.normalized_name,
                p.dominant_gender_code,
                COUNT(
                    DISTINCT perf
                        .canonical_person_performance_id
                ) AS canonical_performance_rows,
                SUM(
                    perf.source_performance_rows
                ) AS mapped_source_rows,
                SUM(
                    perf.source_performance_rows - 1
                ) AS duplicate_rows_removed,
                MIN(perf.season_year)
                    AS first_performance_year,
                MAX(perf.season_year)
                    AS last_performance_year
            FROM canonical_people p
            LEFT JOIN canonical_person_performances perf
              ON p.canonical_person_id
                    = perf.canonical_person_id
            WHERE p.profile_count > 1
            GROUP BY
                p.canonical_person_id,
                p.profile_count,
                p.athlete_ids,
                p.athlete_names,
                p.current_school_names,
                p.current_team_ids,
                p.normalized_name,
                p.dominant_gender_code
            ORDER BY
                duplicate_rows_removed DESC,
                p.profile_count DESC,
                p.canonical_person_id
            """
        ).fetchdf()

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

        deduplication_summary.to_csv(
            OUTPUT_DIR
            / "deduplication_summary.csv",
            index=False,
        )

        multi_profile_person_summary.to_csv(
            OUTPUT_DIR
            / "multi_profile_person_summary.csv",
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

        distinct_bridge_athletes = scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT athlete_id
            )
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

        component_person_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_people
            WHERE identity_status
                = 'HIGH_CONFIDENCE_COMPONENT'
            """,
        )

        component_profile_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_bridge
            WHERE identity_status
                = 'HIGH_CONFIDENCE_COMPONENT'
            """,
        )

        singleton_person_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_people
            WHERE identity_status
                = 'SINGLE_PROFILE'
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

        blank_person_ids = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_bridge
            WHERE NULLIF(
                canonical_person_id,
                ''
            ) IS NULL
            """,
        )

        duplicate_person_performance_ids = scalar(
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

        map_rows_missing_from_dedup = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_performance_map m
            LEFT JOIN canonical_person_performances d
              ON m.canonical_person_performance_id
                    =
                    d.canonical_person_performance_id
            WHERE d.canonical_person_performance_id
                    IS NULL
            """,
        )

        dedup_ids_missing_from_map = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_performances d
            LEFT JOIN canonical_person_performance_map m
              ON d.canonical_person_performance_id
                    =
                    m.canonical_person_performance_id
            WHERE m.canonical_person_performance_id
                    IS NULL
            """,
        )

        source_after = file_state(SOURCE_DB)
        attribution_after = file_state(
            ATTRIBUTION_DB
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
                    "distinct_bridge_athlete_ids",
                    abs(
                        distinct_bridge_athletes
                        - EXPECTED_SOURCE_ATHLETES
                    ),
                    distinct_bridge_athletes,
                    EXPECTED_SOURCE_ATHLETES,
                ),
                (
                    "blank_canonical_person_ids",
                    blank_person_ids,
                    blank_person_ids,
                    0,
                ),
                (
                    "validated_component_people",
                    abs(
                        component_person_rows
                        - EXPECTED_COMPONENTS
                    ),
                    component_person_rows,
                    EXPECTED_COMPONENTS,
                ),
                (
                    "validated_component_profiles",
                    abs(
                        component_profile_rows
                        - EXPECTED_COMPONENT_PROFILES
                    ),
                    component_profile_rows,
                    EXPECTED_COMPONENT_PROFILES,
                ),
                (
                    "canonical_person_count_identity",
                    abs(
                        canonical_people_rows
                        - (
                            singleton_person_rows
                            + component_person_rows
                        )
                    ),
                    canonical_people_rows,
                    (
                        singleton_person_rows
                        + component_person_rows
                    ),
                ),
                (
                    "eligible_performance_map_rows",
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
                    "conflicting_person_performance_teams",
                    len(conflicts),
                    len(conflicts),
                    0,
                ),
                (
                    "duplicate_canonical_person_performance_ids",
                    duplicate_person_performance_ids,
                    duplicate_person_performance_ids,
                    0,
                ),
                (
                    "map_rows_missing_from_dedup",
                    map_rows_missing_from_dedup,
                    map_rows_missing_from_dedup,
                    0,
                ),
                (
                    "dedup_ids_missing_from_map",
                    dedup_ids_missing_from_map,
                    dedup_ids_missing_from_map,
                    0,
                ),
                (
                    "deduplicated_rows_not_greater_than_map",
                    max(
                        dedup_rows - map_rows,
                        0,
                    ),
                    dedup_rows,
                    f"<= {map_rows}",
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
                    "attribution_size_unchanged",
                    abs(
                        attribution_after["size_bytes"]
                        - attribution_before[
                            "size_bytes"
                        ]
                    ),
                    attribution_after["size_bytes"],
                    attribution_before[
                        "size_bytes"
                    ],
                ),
                (
                    "attribution_modified_time_unchanged",
                    abs(
                        attribution_after["modified_ns"]
                        - attribution_before[
                            "modified_ns"
                        ]
                    ),
                    attribution_after["modified_ns"],
                    attribution_before[
                        "modified_ns"
                    ],
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

        report = f"""MILESTONE 4 CANONICAL-PERSON LAYER
============================================================
Layer version: {LAYER_VERSION}
Source database modified: no
Attribution database modified: no
Identity preflight outputs modified: no

IDENTITY BRIDGE
- Source athlete profiles: {source_athletes:,}
- Canonical people: {canonical_people_rows:,}
- High-confidence multi-profile people:
  {component_person_rows:,}
- Profiles inside high-confidence components:
  {component_profile_rows:,}
- Singleton canonical people:
  {singleton_person_rows:,}

PERFORMANCE MAPPING
- School-stint-eligible source performances:
  {map_rows:,}
- Deduplicated canonical-person performances:
  {dedup_rows:,}
- Exact duplicate source rows removed:
  {duplicate_rows_removed:,}
- Conflicting canonical-team groups:
  {len(conflicts):,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

INTERPRETATION
Only validated high-confidence identity components are merged. Every other
athlete profile remains a singleton canonical person. Exact repeated
performances are deduplicated only within a canonical person. Conflicting team
assignments for the same canonical-person performance are blocking and are
written to a dedicated audit queue.
"""

        (
            OUTPUT_DIR
            / "person_layer_report.txt"
        ).write_text(
            report,
            encoding="utf-8",
        )

        con.execute(
            """
            CREATE VIEW school_stint_person_performances AS
            SELECT *
            FROM canonical_person_performances
            WHERE school_stint_eligible
            """
        )

        con.execute(
            """
            CHECKPOINT
            """
        )

        print(
            "Canonical-person layer build complete."
        )
        print(f"Database: {OUTPUT_DB}")
        print(f"Failed checks: {failed:,}.")
        print(
            "Deduplicated rows: "
            f"{dedup_rows:,}"
        )
        print(
            "Duplicate source rows removed: "
            f"{duplicate_rows_removed:,}"
        )

        if failed:
            raise SystemExit(1)

    finally:
        for name in [
            "component_members_input",
            "components_input",
            "high_confidence_pairs_input",
        ]:
            try:
                con.unregister(name)
            except Exception:
                pass

        con.close()


if __name__ == "__main__":
    main()
