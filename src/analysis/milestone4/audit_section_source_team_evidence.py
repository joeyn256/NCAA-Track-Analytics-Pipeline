#!/usr/bin/env python3
"""
Milestone 4: audit source-team evidence for unresolved profile sections.

Purpose
-------
Use the source performance team and school assignments already present in the
Milestone 3 database to resolve or classify the 16 ambiguous exact matches and
1,987 no-exact-candidate sections.

This is evidence generation only. It does not apply final attribution.

Evidence statuses
-----------------
CONSISTENT_SOURCE_TEAM
    Every performance with a nonblank source team points to one team.

CONSISTENT_SOURCE_SCHOOL_MULTIPLE_TEAMS
    More than one source team ID is present, but all map to one school.
    This commonly represents men/women team variants or historical aliases.

MIXED_SOURCE_SCHOOLS
    Performances in the same exact profile section point to multiple schools.

NO_SOURCE_TEAM_EVIDENCE
    All source team IDs are blank.

Outputs
-------
data/processed/milestone4/section_source_team_evidence/
    section_source_team_evidence.csv
    evidence_status_summary.csv
    consistent_team_candidates.csv
    consistent_school_candidates.csv
    mixed_school_review_queue.csv
    no_source_team_evidence_queue.csv
    hard_checks.csv
    evidence_report.txt
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]

SOURCE_DB = (
    PROJECT_ROOT
    / "data/database/ncaa_track_analytics.duckdb"
)
COVERAGE_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "multi_section_attribution_coverage/"
    / "multi_section_attribution_coverage.duckdb"
)
CANDIDATE_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "full_section_entity_resolution/"
    / "section_resolution_candidates.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "section_source_team_evidence"
)
FINAL_DB = (
    OUTPUT_DIR
    / "section_source_team_evidence.duckdb"
)
BUILDING_DB = (
    OUTPUT_DIR
    / "section_source_team_evidence.building.duckdb"
)

EVIDENCE_VERSION = "m4_section_source_team_evidence_v1.1"
EXPECTED_SECTION_ROWS = 2_003
EXPECTED_AMBIGUOUS_ROWS = 16
EXPECTED_NO_CANDIDATE_ROWS = 1_987


def sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--replace-output",
        action="store_true",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=2,
    )
    parser.add_argument(
        "--memory-limit",
        default="4GB",
    )
    return parser.parse_args()


def require_inputs() -> None:
    for path in [
        SOURCE_DB,
        COVERAGE_DB,
        CANDIDATE_CSV,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )


def scalar(
    con: duckdb.DuckDBPyConnection,
    query: str,
    params: list[Any] | None = None,
) -> Any:
    return con.execute(
        query,
        params or [],
    ).fetchone()[0]


def build_database(
    con: duckdb.DuckDBPyConnection,
) -> None:
    con.execute(
        f"""
        ATTACH '{sql_path(SOURCE_DB)}'
            AS srcdb (READ_ONLY);
        ATTACH '{sql_path(COVERAGE_DB)}'
            AS coverdb (READ_ONLY);

        CREATE VIEW candidate_input AS
        SELECT *
        FROM read_csv_auto(
            '{sql_path(CANDIDATE_CSV)}',
            header = true,
            all_varchar = true,
            sample_size = -1
        );
        """
    )

    print("Selecting unresolved candidate sections...")

    con.execute(
        f"""
        CREATE TABLE target_sections AS
        SELECT
            TRY_CAST(athlete_id AS BIGINT)
                AS athlete_id,
            TRY_CAST(section_index AS BIGINT)
                AS section_index,
            athlete_name,
            source_section_name,
            candidate_normalized_name,
            TRY_CAST(performance_count AS BIGINT)
                AS expected_performance_count,
            candidate_resolution_status,
            matched_entity_name,
            resolved_team_id
                AS candidate_team_id,
            resolved_school_id
                AS candidate_school_id,
            resolved_school_name
                AS candidate_school_name,
            '{EVIDENCE_VERSION}'
                AS evidence_version
        FROM candidate_input
        WHERE candidate_resolution_status IN (
            'AMBIGUOUS_EXACT_MATCH',
            'NO_EXACT_CANDIDATE'
        );

        CREATE UNIQUE INDEX
            idx_target_section
        ON target_sections(
            athlete_id,
            section_index
        );
        """
    )

    print("Collecting source performance team evidence...")

    con.execute(
        """
        CREATE TABLE section_source_rows AS
        SELECT
            t.athlete_id,
            t.section_index,
            c.performance_id,
            c.season_year,
            c.season_type,
            c.meet_id,
            c.meet_name,
            c.original_team_id,
            c.original_school_id,
            c.original_school_name,
            c.gender_code,
            tm.team_name AS core_team_name,
            tm.division AS core_team_division,
            tm.gender_code AS core_team_gender_code,
            sc.school_name AS core_school_name
        FROM target_sections t
        JOIN
            coverdb.main.multi_section_performance_coverage c
          ON t.athlete_id = c.athlete_id
         AND t.section_index
           = c.matched_section_index
        LEFT JOIN srcdb.core.teams tm
          ON c.original_team_id
           = CAST(tm.team_id AS VARCHAR)
        LEFT JOIN srcdb.core.schools sc
          ON c.original_school_id
           = CAST(sc.school_id AS VARCHAR);

        CREATE INDEX
            idx_section_source_rows
        ON section_source_rows(
            athlete_id,
            section_index
        );
        """
    )

    print("Building section-level evidence summary...")

    con.execute(
        """
        CREATE TABLE section_source_team_evidence AS
        SELECT
            t.athlete_id,
            t.section_index,
            t.athlete_name,
            t.source_section_name,
            t.candidate_normalized_name,
            t.candidate_resolution_status,
            t.matched_entity_name,
            t.candidate_team_id,
            t.candidate_school_id,
            t.candidate_school_name,
            t.expected_performance_count,
            COUNT(r.performance_id)
                AS observed_performance_count,
            COUNT(
                DISTINCT NULLIF(
                    trim(r.original_team_id),
                    ''
                )
            ) AS distinct_source_team_count,
            COUNT(
                DISTINCT NULLIF(
                    trim(r.original_school_id),
                    ''
                )
            ) AS distinct_source_school_count,
            COUNT(
                DISTINCT NULLIF(
                    trim(r.gender_code),
                    ''
                )
            ) AS distinct_source_gender_count,
            MIN(
                NULLIF(
                    trim(r.original_team_id),
                    ''
                )
            ) AS consistent_source_team_id,
            MIN(
                NULLIF(
                    trim(r.original_school_id),
                    ''
                )
            ) AS consistent_source_school_id,
            MIN(
                NULLIF(
                    trim(r.original_school_name),
                    ''
                )
            ) AS consistent_source_school_name,
            MIN(
                NULLIF(
                    trim(r.core_team_name),
                    ''
                )
            ) AS consistent_core_team_name,
            MIN(
                NULLIF(
                    trim(r.core_team_division),
                    ''
                )
            ) AS consistent_core_team_division,
            MIN(
                NULLIF(
                    trim(r.core_team_gender_code),
                    ''
                )
            ) AS consistent_core_team_gender_code,
            MIN(
                NULLIF(
                    trim(r.core_school_name),
                    ''
                )
            ) AS consistent_core_school_name,
            string_agg(
                DISTINCT NULLIF(
                    trim(r.original_team_id),
                    ''
                ),
                ' | '
                ORDER BY NULLIF(
                    trim(r.original_team_id),
                    ''
                )
            ) AS source_team_ids,
            string_agg(
                DISTINCT NULLIF(
                    trim(r.original_school_name),
                    ''
                ),
                ' | '
                ORDER BY NULLIF(
                    trim(r.original_school_name),
                    ''
                )
            ) AS source_school_names,
            string_agg(
                DISTINCT NULLIF(
                    trim(r.gender_code),
                    ''
                ),
                ' | '
                ORDER BY NULLIF(
                    trim(r.gender_code),
                    ''
                )
            ) AS source_gender_codes,
            MIN(r.season_year)
                AS first_season_year,
            MAX(r.season_year)
                AS last_season_year,
            COUNT(DISTINCT r.meet_id)
                AS meet_count,
            CASE
                WHEN COUNT(
                    DISTINCT NULLIF(
                        trim(r.original_team_id),
                        ''
                    )
                ) = 1
                    THEN 'CONSISTENT_SOURCE_TEAM'
                WHEN COUNT(
                    DISTINCT NULLIF(
                        trim(r.original_team_id),
                        ''
                    )
                ) > 1
                 AND COUNT(
                    DISTINCT NULLIF(
                        trim(r.original_school_id),
                        ''
                    )
                ) = 1
                    THEN
                        'CONSISTENT_SOURCE_SCHOOL_MULTIPLE_TEAMS'
                WHEN COUNT(
                    DISTINCT NULLIF(
                        trim(r.original_school_id),
                        ''
                    )
                ) > 1
                    THEN 'MIXED_SOURCE_SCHOOLS'
                ELSE 'NO_SOURCE_TEAM_EVIDENCE'
            END AS source_evidence_status,
            '{EVIDENCE_VERSION}'
                AS evidence_version
        FROM target_sections t
        LEFT JOIN section_source_rows r
          ON t.athlete_id = r.athlete_id
         AND t.section_index = r.section_index
        GROUP BY
            t.athlete_id,
            t.section_index,
            t.athlete_name,
            t.source_section_name,
            t.candidate_normalized_name,
            t.candidate_resolution_status,
            t.matched_entity_name,
            t.candidate_team_id,
            t.candidate_school_id,
            t.candidate_school_name,
            t.expected_performance_count;

        CREATE UNIQUE INDEX
            idx_section_source_evidence
        ON section_source_team_evidence(
            athlete_id,
            section_index
        );

        CREATE TABLE evidence_status_summary AS
        SELECT
            candidate_resolution_status,
            source_evidence_status,
            COUNT(*) AS section_count,
            COUNT(DISTINCT athlete_id)
                AS athlete_count,
            SUM(observed_performance_count)
                AS performance_count
        FROM section_source_team_evidence
        GROUP BY
            candidate_resolution_status,
            source_evidence_status
        ORDER BY
            candidate_resolution_status,
            performance_count DESC;
        """
    )


def build_checks(
    con: duckdb.DuckDBPyConnection,
) -> pd.DataFrame:
    target_rows = int(
        scalar(
            con,
            "SELECT COUNT(*) FROM target_sections",
        )
    )
    ambiguous_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM target_sections
            WHERE candidate_resolution_status
                = 'AMBIGUOUS_EXACT_MATCH'
            """,
        )
    )
    unresolved_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM target_sections
            WHERE candidate_resolution_status
                = 'NO_EXACT_CANDIDATE'
            """,
        )
    )
    output_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM section_source_team_evidence
            """,
        )
    )
    duplicates = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    athlete_id,
                    section_index,
                    COUNT(*) AS row_count
                FROM section_source_team_evidence
                GROUP BY
                    athlete_id,
                    section_index
                HAVING COUNT(*) > 1
            )
            """,
        )
    )
    count_mismatches = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM section_source_team_evidence
            WHERE expected_performance_count
                <> observed_performance_count
            """,
        )
    )
    invalid_status = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM section_source_team_evidence
            WHERE source_evidence_status NOT IN (
                'CONSISTENT_SOURCE_TEAM',
                'CONSISTENT_SOURCE_SCHOOL_MULTIPLE_TEAMS',
                'MIXED_SOURCE_SCHOOLS',
                'NO_SOURCE_TEAM_EVIDENCE'
            )
            """,
        )
    )

    rows = [
        (
            "target_section_rows",
            abs(target_rows - EXPECTED_SECTION_ROWS),
            target_rows,
            EXPECTED_SECTION_ROWS,
        ),
        (
            "ambiguous_target_rows",
            abs(
                ambiguous_rows
                - EXPECTED_AMBIGUOUS_ROWS
            ),
            ambiguous_rows,
            EXPECTED_AMBIGUOUS_ROWS,
        ),
        (
            "no_candidate_target_rows",
            abs(
                unresolved_rows
                - EXPECTED_NO_CANDIDATE_ROWS
            ),
            unresolved_rows,
            EXPECTED_NO_CANDIDATE_ROWS,
        ),
        (
            "output_row_count_reconciles",
            abs(output_rows - target_rows),
            output_rows,
            target_rows,
        ),
        (
            "duplicate_section_keys",
            duplicates,
            duplicates,
            0,
        ),
        (
            "section_performance_count_mismatches",
            count_mismatches,
            count_mismatches,
            0,
        ),
        (
            "invalid_source_evidence_status",
            invalid_status,
            invalid_status,
            0,
        ),
    ]

    return pd.DataFrame(
        rows,
        columns=[
            "check_name",
            "failed_row_count",
            "observed_value",
            "expected_value",
        ],
    )


def export_outputs(
    con: duckdb.DuckDBPyConnection,
    checks: pd.DataFrame,
) -> None:
    checks.to_csv(
        OUTPUT_DIR / "hard_checks.csv",
        index=False,
    )

    queries = {
        "section_source_team_evidence.csv": """
            SELECT *
            FROM section_source_team_evidence
            ORDER BY
                source_evidence_status,
                observed_performance_count DESC,
                athlete_id,
                section_index
        """,
        "evidence_status_summary.csv": """
            SELECT *
            FROM evidence_status_summary
        """,
        "consistent_team_candidates.csv": """
            SELECT *
            FROM section_source_team_evidence
            WHERE source_evidence_status
                = 'CONSISTENT_SOURCE_TEAM'
            ORDER BY
                observed_performance_count DESC,
                athlete_id,
                section_index
        """,
        "consistent_school_candidates.csv": """
            SELECT *
            FROM section_source_team_evidence
            WHERE source_evidence_status
                = 'CONSISTENT_SOURCE_SCHOOL_MULTIPLE_TEAMS'
            ORDER BY
                observed_performance_count DESC,
                athlete_id,
                section_index
        """,
        "mixed_school_review_queue.csv": """
            SELECT *
            FROM section_source_team_evidence
            WHERE source_evidence_status
                = 'MIXED_SOURCE_SCHOOLS'
            ORDER BY
                observed_performance_count DESC,
                athlete_id,
                section_index
        """,
        "no_source_team_evidence_queue.csv": """
            SELECT *
            FROM section_source_team_evidence
            WHERE source_evidence_status
                = 'NO_SOURCE_TEAM_EVIDENCE'
            ORDER BY
                observed_performance_count DESC,
                athlete_id,
                section_index
        """,
    }

    for filename, query in queries.items():
        con.execute(
            f"""
            COPY (
                {query}
            )
            TO '{sql_path(OUTPUT_DIR / filename)}'
            (
                HEADER,
                DELIMITER ','
            )
            """
        )


def write_report(
    con: duckdb.DuckDBPyConnection,
    checks: pd.DataFrame,
) -> None:
    failed = int(
        (checks["failed_row_count"] > 0).sum()
    )

    counts = {
        row[0]: int(row[1])
        for row in con.execute(
            """
            SELECT
                source_evidence_status,
                COUNT(*)
            FROM section_source_team_evidence
            GROUP BY source_evidence_status
            """
        ).fetchall()
    }

    performances = {
        row[0]: int(row[1])
        for row in con.execute(
            """
            SELECT
                source_evidence_status,
                SUM(observed_performance_count)
            FROM section_source_team_evidence
            GROUP BY source_evidence_status
            """
        ).fetchall()
    }

    consistent_team_sections = counts.get(
        "CONSISTENT_SOURCE_TEAM",
        0,
    )
    consistent_team_performances = performances.get(
        "CONSISTENT_SOURCE_TEAM",
        0,
    )
    consistent_school_sections = counts.get(
        "CONSISTENT_SOURCE_SCHOOL_MULTIPLE_TEAMS",
        0,
    )
    mixed_school_sections = counts.get(
        "MIXED_SOURCE_SCHOOLS",
        0,
    )
    no_source_sections = counts.get(
        "NO_SOURCE_TEAM_EVIDENCE",
        0,
    )

    report = f"""MILESTONE 4 SECTION SOURCE-TEAM EVIDENCE
============================================================
Evidence version: {EVIDENCE_VERSION}
Source database modified: no
Prior Milestone 4 outputs modified: no

INPUT
- Ambiguous exact-match sections: {EXPECTED_AMBIGUOUS_ROWS:,}
- No-exact-candidate sections: {EXPECTED_NO_CANDIDATE_ROWS:,}
- Total target sections: {EXPECTED_SECTION_ROWS:,}

EVIDENCE RESULTS
- Consistent source-team sections: {consistent_team_sections:,}
- Performances in consistent-team sections: {consistent_team_performances:,}
- Consistent source-school/multiple-team sections: {consistent_school_sections:,}
- Mixed-source-school sections: {mixed_school_sections:,}
- Sections without source-team evidence: {no_source_sections:,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

NEXT GATE
Consistent source-team and source-school rows can become high-confidence
resolution candidates after verifying that the source school agrees with the
profile section name or a documented alias. Mixed-school and no-evidence rows
remain blocked for narrower review.
"""

    (
        OUTPUT_DIR / "evidence_report.txt"
    ).write_text(
        report,
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    require_inputs()

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if FINAL_DB.exists() and not args.replace_output:
        raise FileExistsError(
            "Published evidence database already exists. "
            "Use --replace-output after review."
        )

    if BUILDING_DB.exists():
        BUILDING_DB.unlink()

    con = duckdb.connect(str(BUILDING_DB))

    try:
        con.execute(
            f"SET threads = {args.threads};"
        )
        con.execute(
            "SET memory_limit = ?;",
            [args.memory_limit],
        )
        con.execute(
            "SET preserve_insertion_order = false;"
        )

        build_database(con)
        checks = build_checks(con)

        con.register("checks_df", checks)
        con.execute(
            """
            CREATE TABLE hard_checks AS
            SELECT *
            FROM checks_df
            """
        )
        con.unregister("checks_df")

        export_outputs(con, checks)
        con.execute("CHECKPOINT;")
        con.close()

        failed = int(
            (checks["failed_row_count"] > 0).sum()
        )

        if FINAL_DB.exists():
            FINAL_DB.unlink()
        os.replace(BUILDING_DB, FINAL_DB)

        report_con = duckdb.connect(
            str(FINAL_DB),
            read_only=True,
        )
        try:
            write_report(report_con, checks)
        finally:
            report_con.close()

        print(
            "Section source-team evidence audit complete."
        )
        print(f"Outputs: {OUTPUT_DIR}")
        print(f"Failed checks: {failed:,}.")

        if failed:
            raise SystemExit(1)

    except BaseException:
        try:
            con.close()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
