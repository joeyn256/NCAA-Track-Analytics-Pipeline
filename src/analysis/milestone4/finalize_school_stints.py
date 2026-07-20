#!/usr/bin/env python3
"""
Milestone 4: finalize D1 school stints v1.1.

This script converts the two result-page-confirmed single-meet A-B-A cases
from blocking diagnostic flags into explicit reviewed chronology exceptions.

It does not alter the canonical performance assignments:
- Emily Venters remains assigned to Colorado for the 2018 Nuttycombe meet.
- Daniella Hubble remains assigned to Illinois for the 2023 Wisconsin Badger
  Classic.

Inputs
------
data/processed/milestone4/final_school_stints/
    final_school_stints.duckdb

data/processed/milestone4/school_stint_island_evidence/
    island_result_evidence.csv
    island_source_attribution_rows.csv

Outputs
-------
data/processed/milestone4/final_school_stints_v1_1/
    final_school_stints_v1_1.duckdb
    final_school_stint_report.txt
    hard_checks.csv
    chronology_exception_registry.csv
    chronology_exception_summary.csv
    stint_count_distribution.csv
    team_stint_summary.csv
    transfer_person_summary.csv
    remaining_unreviewed_islands.csv
    known_identity_validation.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]

PERSON_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_person_layer_v1_1/"
    / "canonical_person_layer_v1_1.duckdb"
)

DIAGNOSTIC_STINT_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "final_school_stints/"
    / "final_school_stints.duckdb"
)

ISLAND_EVIDENCE_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "school_stint_island_evidence/"
    / "island_result_evidence.csv"
)

ISLAND_SOURCE_ROWS_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "school_stint_island_evidence/"
    / "island_source_attribution_rows.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "final_school_stints_v1_1"
)

OUTPUT_DB = (
    OUTPUT_DIR
    / "final_school_stints_v1_1.duckdb"
)

STINT_VERSION = (
    "m4_final_school_stints_v1.1"
)

EXPECTED_ELIGIBLE_ROWS = 6_376_505
EXPECTED_MEET_ASSIGNMENTS = 3_867_249
EXPECTED_DIAGNOSTIC_STINTS = 174_429
EXPECTED_REVIEWED_EXCEPTIONS = 2
EXPECTED_REVIEWED_PEOPLE = 2

EXPECTED_EXCEPTION_TEAMS = {
    "Emily Venters": "CO_college_f_Colorado",
    "Daniella Hubble": "IL_college_f_Illinois",
}


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


def file_state(path: Path) -> dict[str, int]:
    stat = path.stat()

    return {
        "size_bytes": int(stat.st_size),
        "modified_ns": int(stat.st_mtime_ns),
    }


def prepare_output(
    replace_output: bool,
) -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    generated = [
        OUTPUT_DB,
        OUTPUT_DIR / "final_school_stint_report.txt",
        OUTPUT_DIR / "hard_checks.csv",
        OUTPUT_DIR / "chronology_exception_registry.csv",
        OUTPUT_DIR / "chronology_exception_summary.csv",
        OUTPUT_DIR / "stint_count_distribution.csv",
        OUTPUT_DIR / "team_stint_summary.csv",
        OUTPUT_DIR / "transfer_person_summary.csv",
        OUTPUT_DIR / "remaining_unreviewed_islands.csv",
        OUTPUT_DIR / "known_identity_validation.csv",
    ]

    existing = [
        path
        for path in generated
        if path.exists()
    ]

    if existing and not replace_output:
        raise FileExistsError(
            "Final school-stint v1.1 outputs already exist. "
            "Use --replace-output only after reviewing them."
        )

    if replace_output:
        for path in existing:
            path.unlink()


def require_inputs() -> None:
    for path in [
        PERSON_DB,
        DIAGNOSTIC_STINT_DB,
        ISLAND_EVIDENCE_CSV,
        ISLAND_SOURCE_ROWS_CSV,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )


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

    person_before = file_state(PERSON_DB)
    diagnostic_before = file_state(
        DIAGNOSTIC_STINT_DB
    )

    evidence = pd.read_csv(
        ISLAND_EVIDENCE_CSV,
        dtype={
            "school_stint_id": str,
            "canonical_person_id": str,
            "canonical_person_performance_id": str,
            "island_team_id": str,
            "parsed_team_id": str,
            "prior_stint_team_id": str,
            "next_stint_team_id": str,
        },
    )

    source_rows = pd.read_csv(
        ISLAND_SOURCE_ROWS_CSV,
        dtype={
            "canonical_person_id": str,
            "canonical_person_performance_id": str,
            "performance_id": str,
            "athlete_id": str,
        },
    )

    if evidence["school_stint_id"].duplicated().any():
        raise RuntimeError(
            "Duplicate school-stint IDs exist in island evidence."
        )

    evidence[
        "result_page_supports_current_assignment"
    ] = (
        evidence["resolution_status"].eq(
            "RESOLVED_OTHER_TEAM"
        )
        & evidence["parsed_team_id"].eq(
            evidence["island_team_id"]
        )
        & evidence["parsed_team_id"].ne(
            evidence["prior_stint_team_id"]
        )
        & evidence["parsed_team_id"].ne(
            evidence["next_stint_team_id"]
        )
    )

    evidence[
        "review_decision"
    ] = evidence[
        "result_page_supports_current_assignment"
    ].map(
        {
            True: (
                "ACCEPT_RESULT_PAGE_CONFIRMED_"
                "SINGLE_MEET_STINT"
            ),
            False: "UNRESOLVED_REVIEW",
        }
    )

    evidence[
        "exception_type"
    ] = (
        "RESULT_PAGE_CONFIRMED_SINGLE_MEET_ABA"
    )

    evidence[
        "exception_version"
    ] = STINT_VERSION

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
            ATTACH '{sql_path(PERSON_DB)}'
            AS person
            (READ_ONLY)
            """
        )

        con.execute(
            f"""
            ATTACH '{sql_path(DIAGNOSTIC_STINT_DB)}'
            AS diagnostic
            (READ_ONLY)
            """
        )

        con.register(
            "island_evidence_input",
            evidence,
        )

        con.register(
            "island_source_rows_input",
            source_rows,
        )

        print(
            "Validating reviewed chronology exceptions..."
        )

        con.execute(
            """
            CREATE TABLE chronology_exception_registry AS
            SELECT
                school_stint_id,
                canonical_person_id,
                canonical_person_performance_id,
                athlete_name,

                stint_sequence,
                season_id,
                season_year,
                season_type,
                meet_id,
                meet_name,
                meet_date_text,
                event,
                mark,
                place,
                result_url,

                prior_stint_team_id,
                island_team_id
                    AS accepted_team_id,
                island_team_name
                    AS accepted_team_name,
                next_stint_team_id,

                parsed_team_id
                    AS result_page_team_id,
                parsed_team_name
                    AS result_page_team_name,
                parsed_team_url
                    AS result_page_team_url,

                fetch_status,
                row_match_status,
                team_mapping_method,
                resolution_status,

                result_page_supports_current_assignment,
                review_decision,
                exception_type,
                exception_version

            FROM island_evidence_input
            """
        )

        con.execute(
            """
            CREATE UNIQUE INDEX
                chronology_exception_stint_idx
            ON chronology_exception_registry (
                school_stint_id
            )
            """
        )

        con.execute(
            """
            CREATE UNIQUE INDEX
                chronology_exception_performance_idx
            ON chronology_exception_registry (
                canonical_person_performance_id
            )
            """
        )

        con.execute(
            """
            CREATE TABLE chronology_exception_source_rows AS
            SELECT
                *,
                ? AS exception_version
            FROM island_source_rows_input
            """,
            [STINT_VERSION],
        )

        print(
            "Copying validated stint tables..."
        )

        con.execute(
            """
            CREATE TABLE person_meet_team_assignments AS
            SELECT
                * EXCLUDE (school_stint_version),
                ? AS school_stint_version
            FROM diagnostic.person_meet_team_assignments
            """,
            [STINT_VERSION],
        )

        con.execute(
            """
            CREATE UNIQUE INDEX
                person_meet_assignment_idx
            ON person_meet_team_assignments (
                canonical_person_id,
                season_id,
                meet_id
            )
            """
        )

        con.execute(
            """
            CREATE INDEX
                person_meet_stint_idx
            ON person_meet_team_assignments (
                school_stint_id
            )
            """
        )

        con.execute(
            """
            CREATE TABLE canonical_person_school_stints AS
            SELECT
                s.* EXCLUDE (
                    is_single_meet_aba_island,
                    school_stint_version
                ),

                s.is_single_meet_aba_island
                    AS raw_single_meet_aba_island,

                CASE
                    WHEN e.school_stint_id
                        IS NOT NULL
                    THEN TRUE
                    ELSE FALSE
                END AS reviewed_chronology_exception,

                CASE
                    WHEN
                        s.is_single_meet_aba_island
                        AND e.school_stint_id
                            IS NULL
                    THEN TRUE
                    ELSE FALSE
                END AS unreviewed_single_meet_aba_island,

                e.exception_type,
                e.review_decision,
                e.result_page_team_id,
                e.result_page_team_name,

                ? AS school_stint_version

            FROM diagnostic
                .canonical_person_school_stints s

            LEFT JOIN chronology_exception_registry e
              ON s.school_stint_id
                    = e.school_stint_id
             AND e.review_decision
                    =
                    'ACCEPT_RESULT_PAGE_CONFIRMED_'
                    'SINGLE_MEET_STINT'
            """,
            [STINT_VERSION],
        )

        con.execute(
            """
            CREATE UNIQUE INDEX
                canonical_school_stint_idx
            ON canonical_person_school_stints (
                school_stint_id
            )
            """
        )

        con.execute(
            """
            CREATE INDEX
                canonical_school_stint_person_idx
            ON canonical_person_school_stints (
                canonical_person_id,
                stint_sequence
            )
            """
        )

        con.execute(
            """
            CREATE TABLE school_stint_performance_map AS
            SELECT
                * EXCLUDE (school_stint_version),
                ? AS school_stint_version
            FROM diagnostic.school_stint_performance_map
            """,
            [STINT_VERSION],
        )

        con.execute(
            """
            CREATE UNIQUE INDEX
                school_stint_performance_map_idx
            ON school_stint_performance_map (
                canonical_person_performance_id
            )
            """
        )

        con.execute(
            """
            CREATE INDEX
                school_stint_performance_stint_idx
            ON school_stint_performance_map (
                school_stint_id
            )
            """
        )

        con.execute(
            """
            CREATE VIEW transfer_school_stints AS
            SELECT *
            FROM canonical_person_school_stints
            WHERE person_stint_count > 1
            """
        )

        con.execute(
            """
            CREATE VIEW reviewed_chronology_exceptions AS
            SELECT *
            FROM canonical_person_school_stints
            WHERE reviewed_chronology_exception
            """
        )

        con.execute(
            """
            CREATE VIEW analytical_school_stints AS
            SELECT *
            FROM canonical_person_school_stints
            WHERE NOT unreviewed_single_meet_aba_island
            """
        )

        print(
            "Building final audit summaries..."
        )

        remaining_unreviewed = con.execute(
            """
            SELECT *
            FROM canonical_person_school_stints
            WHERE unreviewed_single_meet_aba_island
            ORDER BY
                canonical_person_id,
                stint_sequence
            """
        ).fetchdf()

        remaining_unreviewed.to_csv(
            OUTPUT_DIR
            / "remaining_unreviewed_islands.csv",
            index=False,
        )

        exception_registry = con.execute(
            """
            SELECT *
            FROM chronology_exception_registry
            ORDER BY
                athlete_name,
                season_id,
                meet_id
            """
        ).fetchdf()

        exception_registry.to_csv(
            OUTPUT_DIR
            / "chronology_exception_registry.csv",
            index=False,
        )

        exception_summary = con.execute(
            """
            SELECT
                exception_type,
                review_decision,
                accepted_team_id,
                accepted_team_name,
                COUNT(*) AS exception_count,
                COUNT(
                    DISTINCT canonical_person_id
                ) AS canonical_person_count
            FROM chronology_exception_registry
            GROUP BY
                exception_type,
                review_decision,
                accepted_team_id,
                accepted_team_name
            ORDER BY
                exception_count DESC,
                accepted_team_id
            """
        ).fetchdf()

        exception_summary.to_csv(
            OUTPUT_DIR
            / "chronology_exception_summary.csv",
            index=False,
        )

        stint_distribution = con.execute(
            """
            SELECT
                person_stint_count,
                COUNT(
                    DISTINCT canonical_person_id
                ) AS canonical_person_count
            FROM canonical_person_school_stints
            GROUP BY person_stint_count
            ORDER BY person_stint_count
            """
        ).fetchdf()

        stint_distribution.to_csv(
            OUTPUT_DIR
            / "stint_count_distribution.csv",
            index=False,
        )

        team_summary = con.execute(
            """
            SELECT
                canonical_team_id,
                canonical_team_name,
                canonical_school_id,
                canonical_school_name,
                canonical_gender_code,

                COUNT(*) AS school_stint_count,

                COUNT(
                    DISTINCT canonical_person_id
                ) AS canonical_person_count,

                SUM(meet_count) AS meet_count,

                SUM(
                    canonical_performance_count
                ) AS canonical_performance_count,

                SUM(
                    CASE
                        WHEN reviewed_chronology_exception
                        THEN 1
                        ELSE 0
                    END
                ) AS reviewed_exception_count,

                MIN(stint_start_date)
                    AS first_stint_start_date,

                MAX(stint_end_date)
                    AS last_stint_end_date

            FROM canonical_person_school_stints

            GROUP BY
                canonical_team_id,
                canonical_team_name,
                canonical_school_id,
                canonical_school_name,
                canonical_gender_code

            ORDER BY
                canonical_person_count DESC,
                canonical_team_id
            """
        ).fetchdf()

        team_summary.to_csv(
            OUTPUT_DIR
            / "team_stint_summary.csv",
            index=False,
        )

        transfer_summary = con.execute(
            """
            SELECT
                canonical_person_id,
                MAX(person_stint_count)
                    AS school_stint_count,

                STRING_AGG(
                    canonical_team_id,
                    ' -> '
                    ORDER BY stint_sequence
                ) AS team_sequence,

                STRING_AGG(
                    canonical_school_name,
                    ' -> '
                    ORDER BY stint_sequence
                ) AS school_sequence,

                MIN(stint_start_date)
                    AS career_start_date,

                MAX(stint_end_date)
                    AS career_end_date,

                SUM(meet_count) AS meet_count,

                SUM(
                    canonical_performance_count
                ) AS canonical_performance_count,

                BOOL_OR(returns_to_prior_team)
                    AS returns_to_prior_team,

                BOOL_OR(
                    reviewed_chronology_exception
                ) AS has_reviewed_chronology_exception

            FROM canonical_person_school_stints

            GROUP BY canonical_person_id

            HAVING MAX(person_stint_count) > 1

            ORDER BY
                school_stint_count DESC,
                canonical_person_id
            """
        ).fetchdf()

        transfer_summary.to_csv(
            OUTPUT_DIR
            / "transfer_person_summary.csv",
            index=False,
        )

        known_validation = con.execute(
            """
            SELECT
                e.athlete_name
                    AS validation_name,

                e.canonical_person_id,
                p.athlete_ids,
                p.athlete_names,

                COUNT(
                    DISTINCT s.school_stint_id
                ) AS school_stint_count,

                SUM(
                    CASE
                        WHEN
                            s.reviewed_chronology_exception
                        THEN 1
                        ELSE 0
                    END
                ) AS reviewed_exception_count,

                SUM(
                    CASE
                        WHEN
                            s.unreviewed_single_meet_aba_island
                        THEN 1
                        ELSE 0
                    END
                ) AS unreviewed_island_count,

                STRING_AGG(
                    s.canonical_team_id,
                    ' -> '
                    ORDER BY s.stint_sequence
                ) AS team_sequence

            FROM chronology_exception_registry e

            JOIN person.canonical_people p
              ON e.canonical_person_id
                    = p.canonical_person_id

            JOIN canonical_person_school_stints s
              ON e.canonical_person_id
                    = s.canonical_person_id

            GROUP BY
                e.athlete_name,
                e.canonical_person_id,
                p.athlete_ids,
                p.athlete_names

            ORDER BY e.athlete_name
            """
        ).fetchdf()

        known_validation.to_csv(
            OUTPUT_DIR
            / "known_identity_validation.csv",
            index=False,
        )

        eligible_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM school_stint_performance_map
            """,
        )

        distinct_performance_ids = scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT canonical_person_performance_id
            )
            FROM school_stint_performance_map
            """,
        )

        meet_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM person_meet_team_assignments
            """,
        )

        stint_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_school_stints
            """,
        )

        reviewed_exception_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM chronology_exception_registry
            WHERE review_decision
                =
                'ACCEPT_RESULT_PAGE_CONFIRMED_'
                'SINGLE_MEET_STINT'
            """,
        )

        reviewed_exception_people = scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT canonical_person_id
            )
            FROM chronology_exception_registry
            WHERE review_decision
                =
                'ACCEPT_RESULT_PAGE_CONFIRMED_'
                'SINGLE_MEET_STINT'
            """,
        )

        raw_island_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_school_stints
            WHERE raw_single_meet_aba_island
            """,
        )

        reviewed_island_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_school_stints
            WHERE reviewed_chronology_exception
            """
        )

        unreviewed_island_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_school_stints
            WHERE unreviewed_single_meet_aba_island
            """,
        )

        unsupported_exception_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM chronology_exception_registry
            WHERE NOT
                result_page_supports_current_assignment
            """
        )

        wrong_expected_team_rows = 0

        for athlete_name, expected_team in (
            EXPECTED_EXCEPTION_TEAMS.items()
        ):
            observed = con.execute(
                """
                SELECT
                    COUNT(*)
                FROM chronology_exception_registry
                WHERE athlete_name = ?
                  AND accepted_team_id = ?
                  AND result_page_team_id = ?
                """,
                [
                    athlete_name,
                    expected_team,
                    expected_team,
                ],
            ).fetchone()[0]

            if int(observed) != 1:
                wrong_expected_team_rows += 1

        performance_rows_missing_stint = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM school_stint_performance_map m
            LEFT JOIN canonical_person_school_stints s
              USING (school_stint_id)
            WHERE s.school_stint_id IS NULL
            """,
        )

        stint_performance_total = scalar(
            con,
            """
            SELECT
                SUM(
                    canonical_performance_count
                )
            FROM canonical_person_school_stints
            """,
        )

        duplicate_stint_ids = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM (
                SELECT school_stint_id
                FROM canonical_person_school_stints
                GROUP BY school_stint_id
                HAVING COUNT(*) > 1
            )
            """,
        )

        duplicate_performance_map_ids = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    canonical_person_performance_id
                FROM school_stint_performance_map
                GROUP BY
                    canonical_person_performance_id
                HAVING COUNT(*) > 1
            )
            """,
        )

        person_after = file_state(PERSON_DB)
        diagnostic_after = file_state(
            DIAGNOSTIC_STINT_DB
        )

        checks = pd.DataFrame(
            [
                (
                    "eligible_performance_rows",
                    abs(
                        eligible_rows
                        - EXPECTED_ELIGIBLE_ROWS
                    ),
                    eligible_rows,
                    EXPECTED_ELIGIBLE_ROWS,
                ),
                (
                    "distinct_performance_map_ids",
                    abs(
                        distinct_performance_ids
                        - EXPECTED_ELIGIBLE_ROWS
                    ),
                    distinct_performance_ids,
                    EXPECTED_ELIGIBLE_ROWS,
                ),
                (
                    "person_meet_assignment_rows",
                    abs(
                        meet_rows
                        - EXPECTED_MEET_ASSIGNMENTS
                    ),
                    meet_rows,
                    EXPECTED_MEET_ASSIGNMENTS,
                ),
                (
                    "school_stint_rows",
                    abs(
                        stint_rows
                        - EXPECTED_DIAGNOSTIC_STINTS
                    ),
                    stint_rows,
                    EXPECTED_DIAGNOSTIC_STINTS,
                ),
                (
                    "reviewed_chronology_exceptions",
                    abs(
                        reviewed_exception_rows
                        - EXPECTED_REVIEWED_EXCEPTIONS
                    ),
                    reviewed_exception_rows,
                    EXPECTED_REVIEWED_EXCEPTIONS,
                ),
                (
                    "reviewed_exception_people",
                    abs(
                        reviewed_exception_people
                        - EXPECTED_REVIEWED_PEOPLE
                    ),
                    reviewed_exception_people,
                    EXPECTED_REVIEWED_PEOPLE,
                ),
                (
                    "raw_single_meet_aba_islands",
                    abs(
                        raw_island_rows
                        - EXPECTED_REVIEWED_EXCEPTIONS
                    ),
                    raw_island_rows,
                    EXPECTED_REVIEWED_EXCEPTIONS,
                ),
                (
                    "reviewed_island_rows",
                    abs(
                        reviewed_island_rows
                        - EXPECTED_REVIEWED_EXCEPTIONS
                    ),
                    reviewed_island_rows,
                    EXPECTED_REVIEWED_EXCEPTIONS,
                ),
                (
                    "remaining_unreviewed_islands",
                    unreviewed_island_rows,
                    unreviewed_island_rows,
                    0,
                ),
                (
                    "unsupported_exception_rows",
                    unsupported_exception_rows,
                    unsupported_exception_rows,
                    0,
                ),
                (
                    "known_exception_team_mismatches",
                    wrong_expected_team_rows,
                    wrong_expected_team_rows,
                    0,
                ),
                (
                    "performance_rows_missing_stint",
                    performance_rows_missing_stint,
                    performance_rows_missing_stint,
                    0,
                ),
                (
                    "stint_performance_total",
                    abs(
                        stint_performance_total
                        - EXPECTED_ELIGIBLE_ROWS
                    ),
                    stint_performance_total,
                    EXPECTED_ELIGIBLE_ROWS,
                ),
                (
                    "duplicate_school_stint_ids",
                    duplicate_stint_ids,
                    duplicate_stint_ids,
                    0,
                ),
                (
                    "duplicate_performance_map_ids",
                    duplicate_performance_map_ids,
                    duplicate_performance_map_ids,
                    0,
                ),
                (
                    "person_db_size_unchanged",
                    abs(
                        person_after["size_bytes"]
                        - person_before["size_bytes"]
                    ),
                    person_after["size_bytes"],
                    person_before["size_bytes"],
                ),
                (
                    "person_db_modified_time_unchanged",
                    abs(
                        person_after["modified_ns"]
                        - person_before["modified_ns"]
                    ),
                    person_after["modified_ns"],
                    person_before["modified_ns"],
                ),
                (
                    "diagnostic_stint_db_size_unchanged",
                    abs(
                        diagnostic_after["size_bytes"]
                        - diagnostic_before["size_bytes"]
                    ),
                    diagnostic_after["size_bytes"],
                    diagnostic_before["size_bytes"],
                ),
                (
                    "diagnostic_stint_db_modified_time_unchanged",
                    abs(
                        diagnostic_after["modified_ns"]
                        - diagnostic_before["modified_ns"]
                    ),
                    diagnostic_after["modified_ns"],
                    diagnostic_before["modified_ns"],
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

        canonical_people = scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT canonical_person_id
            )
            FROM canonical_person_school_stints
            """,
        )

        transfer_people = scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT canonical_person_id
            )
            FROM canonical_person_school_stints
            WHERE person_stint_count > 1
            """,
        )

        returning_people = scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT canonical_person_id
            )
            FROM canonical_person_school_stints
            WHERE returns_to_prior_team
            """,
        )

        report = f"""MILESTONE 4 FINAL D1 SCHOOL STINTS V1.1
============================================================
Stint version: {STINT_VERSION}
Canonical-person database modified: no
Diagnostic school-stint database modified: no
Performance team assignments changed: no

SCOPE
- Eligible canonical performances:
  {eligible_rows:,}
- Person-meet assignments:
  {meet_rows:,}
- Canonical people with D1 stints:
  {canonical_people:,}
- Total school stints:
  {stint_rows:,}
- People with multiple stints:
  {transfer_people:,}
- People returning to a prior team:
  {returning_people:,}

CHRONOLOGY EXCEPTIONS
- Raw single-meet A-B-A patterns:
  {raw_island_rows:,}
- Result-page-confirmed reviewed exceptions:
  {reviewed_island_rows:,}
- Remaining unreviewed islands:
  {unreviewed_island_rows:,}

REVIEWED CASES
- Emily Venters:
  Colorado at the 2018 Nuttycombe meet
- Daniella Hubble:
  Illinois at the 2023 Wisconsin Badger Classic

PERFORMANCE MAPPING
- Performance-to-stint rows:
  {eligible_rows:,}
- Missing stint assignments:
  {performance_rows_missing_stint:,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

INTERPRETATION
The two remaining A-B-A patterns are retained because exact result-page
evidence confirms the middle-team assignments. They are registered as reviewed
chronology exceptions rather than silently removed or treated as unresolved
data errors. All other school-stint and performance-mapping checks remain
fully validated.
"""

        (
            OUTPUT_DIR
            / "final_school_stint_report.txt"
        ).write_text(
            report,
            encoding="utf-8",
        )

        con.execute("CHECKPOINT")

        print(
            "Final D1 school-stint v1.1 "
            "finalization complete."
        )
        print(f"Database: {OUTPUT_DB}")
        print(
            "Reviewed chronology exceptions: "
            f"{reviewed_exception_rows:,}"
        )
        print(
            "Remaining unreviewed islands: "
            f"{unreviewed_island_rows:,}"
        )
        print(
            "Eligible performance rows: "
            f"{eligible_rows:,}"
        )
        print(
            "School stints: "
            f"{stint_rows:,}"
        )
        print(f"Failed checks: {failed:,}.")

        if failed:
            raise SystemExit(1)

    finally:
        for name in [
            "island_evidence_input",
            "island_source_rows_input",
        ]:
            try:
                con.unregister(name)
            except Exception:
                pass

        con.close()


if __name__ == "__main__":
    main()
