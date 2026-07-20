#!/usr/bin/env python3
"""
Milestone 4: audit full multi-section attribution coverage.

Purpose
-------
Determine how the 591,008 performances belonging to multi-section athlete
profiles are covered by existing validated attribution layers and identify
which exact profile sections still require school/entity resolution.

This is a read-only audit. It does not modify:
- the Milestone 3 source database;
- the all-profile staging database;
- the all-performance profile-match database;
- any existing Milestone 4 output.

Inputs
------
data/processed/milestone4/all_performance_profile_match/
    all_performance_profile_match.duckdb
data/processed/milestone4/all_profile_staging/
    all_profile_staging.duckdb
data/processed/milestone4/transfer_candidate_analytical_layer/
    performance_attribution.csv
data/processed/milestone4/blocking_profile_result_resolution/
    performance_team_resolution.csv
data/database/ncaa_track_analytics.duckdb

Outputs
-------
data/processed/milestone4/multi_section_attribution_coverage/
    coverage_report.txt
    hard_checks.csv
    coverage_status_summary.csv
    unresolved_section_inventory.csv
    unresolved_section_performance_summary.csv
    resolved_section_inventory.csv
    athlete_coverage_summary.csv
    section_name_frequency.csv
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
    PROJECT_ROOT / "data/database/ncaa_track_analytics.duckdb"
)
STAGING_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/all_profile_staging"
    / "all_profile_staging.duckdb"
)
MATCH_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/all_performance_profile_match"
    / "all_performance_profile_match.duckdb"
)
TRANSFER_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "transfer_candidate_analytical_layer/"
    / "performance_attribution.csv"
)
BLOCKING_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "blocking_profile_result_resolution/"
    / "performance_team_resolution.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "multi_section_attribution_coverage"
)
FINAL_DB = (
    OUTPUT_DIR
    / "multi_section_attribution_coverage.duckdb"
)
BUILDING_DB = (
    OUTPUT_DIR
    / "multi_section_attribution_coverage.building.duckdb"
)

AUDIT_VERSION = "m4_multi_section_coverage_v1.2"
EXPECTED_MULTI_SECTION_PERFORMANCES = 591_008
EXPECTED_MULTI_SECTION_ATHLETES = 8_349
EXPECTED_TRANSFER_ROWS = 164_964
EXPECTED_BLOCKING_ROWS = 1_134


def sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--replace-output",
        action="store_true",
        help="Replace an existing published coverage database.",
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
        STAGING_DB,
        MATCH_DB,
        TRANSFER_CSV,
        BLOCKING_CSV,
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
        ATTACH '{sql_path(STAGING_DB)}'
            AS stagedb (READ_ONLY);
        ATTACH '{sql_path(MATCH_DB)}'
            AS matchdb (READ_ONLY);
        """
    )

    con.execute(
        f"""
        CREATE TABLE audit_metadata AS
        SELECT
            '{AUDIT_VERSION}'::VARCHAR
                AS audit_version,
            current_timestamp
                AS generated_at,
            false::BOOLEAN
                AS source_database_modified,
            false::BOOLEAN
                AS staging_database_modified,
            false::BOOLEAN
                AS match_database_modified;

        CREATE VIEW transfer_input AS
        SELECT *
        FROM read_csv_auto(
            '{sql_path(TRANSFER_CSV)}',
            header = true,
            all_varchar = true,
            sample_size = -1
        );

        CREATE VIEW blocking_input AS
        SELECT *
        FROM read_csv_auto(
            '{sql_path(BLOCKING_CSV)}',
            header = true,
            all_varchar = true,
            sample_size = -1
        );
        """
    )

    print("Creating multi-section performance coverage table...")

    con.execute(
        """
        CREATE TABLE multi_section_performance_coverage AS
        SELECT
            m.performance_id,
            m.athlete_id,
            a.athlete_name,
            m.matched_section_index,
            m.matched_profile_section_id,
            m.matched_source_section_name,
            m.matched_normalized_section_name,
            m.matched_marker_text,
            m.original_team_id,
            m.original_school_id,
            m.original_school_name,
            m.gender_code,
            p.season_year,
            p.season_type,
            p.meet_id,
            p.meet_name,
            p.event,
            p.mark,
            p.result_url,
            CASE
                WHEN b.performance_id IS NOT NULL
                    THEN 'BLOCKING_RESULT_PAGE_RESOLUTION'
                WHEN t.performance_id IS NOT NULL
                    THEN 'TRANSFER_CANDIDATE_LAYER'
                ELSE 'UNRESOLVED_EXACT_PROFILE_SECTION'
            END AS coverage_status,
            t.final_analytical_team_id
                AS transfer_final_team_id,
            t.final_analytical_school_id
                AS transfer_final_school_id,
            t.final_analytical_school_name
                AS transfer_final_school_name,
            t.final_attribution_status
                AS transfer_final_attribution_status,
            t.career_stage
                AS transfer_career_stage,
            t.governing_system
                AS transfer_governing_system,
            t.competition_level
                AS transfer_competition_level,
            t.d1_development_eligible
                AS transfer_d1_development_eligible,
            t.school_stint_eligible
                AS transfer_school_stint_eligible,
            b.resolved_core_team_id
                AS blocking_resolved_team_id,
            b.resolved_core_school_id
                AS blocking_resolved_school_id,
            b.resolved_core_school_name
                AS blocking_resolved_school_name,
            b.resolved_team
                AS blocking_source_team_name,
            b.is_unattached
                AS blocking_is_unattached,
            b.final_resolution_status
                AS blocking_resolution_status,
            '{AUDIT_VERSION}'
                AS coverage_audit_version
        FROM matchdb.main.performance_profile_match m
        JOIN srcdb.core.performances p
          ON CAST(
                p.performance_id AS VARCHAR
             ) = m.performance_id
        JOIN srcdb.core.athletes a
          ON p.athlete_id = a.athlete_id
        LEFT JOIN transfer_input t
          ON m.performance_id = t.performance_id
        LEFT JOIN blocking_input b
          ON m.performance_id = b.performance_id
        WHERE m.is_multi_section_profile = true;

        CREATE UNIQUE INDEX
            idx_multi_coverage_performance
        ON multi_section_performance_coverage(
            performance_id
        );

        CREATE INDEX
            idx_multi_coverage_section
        ON multi_section_performance_coverage(
            athlete_id,
            matched_section_index
        );
        """
    )

    print("Creating section-level coverage inventories...")

    con.execute(
        """
        CREATE TABLE section_coverage_inventory AS
        SELECT
            athlete_id,
            MIN(athlete_name) AS athlete_name,
            matched_section_index AS section_index,
            MIN(matched_profile_section_id)
                AS profile_section_id,
            MIN(matched_source_section_name)
                AS source_section_name,
            MIN(matched_normalized_section_name)
                AS normalized_section_name,
            MIN(matched_marker_text)
                AS marker_text,
            COUNT(*) AS performance_count,
            COUNT(DISTINCT meet_id)
                AS meet_count,
            MIN(season_year)
                AS first_season_year,
            MAX(season_year)
                AS last_season_year,
            COUNT(
                DISTINCT coverage_status
            ) AS coverage_method_count,
            string_agg(
                DISTINCT coverage_status,
                ' | '
                ORDER BY coverage_status
            ) AS coverage_methods,
            SUM(
                CASE
                    WHEN coverage_status
                        = 'TRANSFER_CANDIDATE_LAYER'
                    THEN 1
                    ELSE 0
                END
            ) AS transfer_performance_count,
            SUM(
                CASE
                    WHEN coverage_status
                        = 'BLOCKING_RESULT_PAGE_RESOLUTION'
                    THEN 1
                    ELSE 0
                END
            ) AS blocking_performance_count,
            SUM(
                CASE
                    WHEN coverage_status
                        = 'UNRESOLVED_EXACT_PROFILE_SECTION'
                    THEN 1
                    ELSE 0
                END
            ) AS unresolved_performance_count,
            CASE
                WHEN SUM(
                    CASE
                        WHEN coverage_status
                            = 'UNRESOLVED_EXACT_PROFILE_SECTION'
                        THEN 1
                        ELSE 0
                    END
                ) = 0
                    THEN 'FULLY_COVERED'
                WHEN SUM(
                    CASE
                        WHEN coverage_status
                            <> 'UNRESOLVED_EXACT_PROFILE_SECTION'
                        THEN 1
                        ELSE 0
                    END
                ) = 0
                    THEN 'UNRESOLVED_SECTION'
                ELSE 'PARTIALLY_COVERED_SECTION'
            END AS section_coverage_status
        FROM multi_section_performance_coverage
        GROUP BY
            athlete_id,
            matched_section_index;

        CREATE UNIQUE INDEX
            idx_section_coverage_inventory
        ON section_coverage_inventory(
            athlete_id,
            section_index
        );

        CREATE TABLE athlete_coverage_summary AS
        SELECT
            athlete_id,
            MIN(athlete_name) AS athlete_name,
            COUNT(DISTINCT section_index)
                AS matched_section_count,
            COUNT(*) AS performance_count,
            SUM(transfer_performance_count)
                AS transfer_performance_count,
            SUM(blocking_performance_count)
                AS blocking_performance_count,
            SUM(unresolved_performance_count)
                AS unresolved_performance_count,
            SUM(
                CASE
                    WHEN section_coverage_status
                        = 'FULLY_COVERED'
                    THEN 1
                    ELSE 0
                END
            ) AS fully_covered_section_count,
            SUM(
                CASE
                    WHEN section_coverage_status
                        = 'PARTIALLY_COVERED_SECTION'
                    THEN 1
                    ELSE 0
                END
            ) AS partially_covered_section_count,
            SUM(
                CASE
                    WHEN section_coverage_status
                        = 'UNRESOLVED_SECTION'
                    THEN 1
                    ELSE 0
                END
            ) AS unresolved_section_count,
            CASE
                WHEN SUM(unresolved_performance_count) = 0
                    THEN 'FULLY_COVERED'
                WHEN SUM(
                    transfer_performance_count
                    + blocking_performance_count
                ) = 0
                    THEN 'FULLY_UNRESOLVED'
                ELSE 'PARTIALLY_COVERED'
            END AS athlete_coverage_status
        FROM section_coverage_inventory
        GROUP BY athlete_id;

        CREATE UNIQUE INDEX
            idx_athlete_coverage_summary
        ON athlete_coverage_summary(
            athlete_id
        );

        CREATE TABLE coverage_status_summary AS
        SELECT
            coverage_status,
            COUNT(*) AS performance_count,
            COUNT(DISTINCT athlete_id)
                AS athlete_count,
            COUNT(
                DISTINCT (
                    athlete_id,
                    matched_section_index
                )
            ) AS section_count
        FROM multi_section_performance_coverage
        GROUP BY coverage_status
        ORDER BY performance_count DESC;

        CREATE TABLE section_name_frequency AS
        SELECT
            matched_normalized_section_name
                AS normalized_section_name,
            MIN(matched_source_section_name)
                AS sample_source_section_name,
            COUNT(*) AS performance_count,
            COUNT(DISTINCT athlete_id)
                AS athlete_count,
            COUNT(
                DISTINCT (
                    athlete_id,
                    matched_section_index
                )
            ) AS section_count,
            SUM(
                CASE
                    WHEN coverage_status
                        = 'UNRESOLVED_EXACT_PROFILE_SECTION'
                    THEN 1
                    ELSE 0
                END
            ) AS unresolved_performance_count
        FROM multi_section_performance_coverage
        GROUP BY
            matched_normalized_section_name
        ORDER BY
            unresolved_performance_count DESC,
            performance_count DESC;
        """
    )


def build_checks(
    con: duckdb.DuckDBPyConnection,
) -> pd.DataFrame:
    total_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM multi_section_performance_coverage
            """,
        )
    )
    distinct_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT performance_id
            )
            FROM multi_section_performance_coverage
            """,
        )
    )
    athlete_count = int(
        scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT athlete_id
            )
            FROM multi_section_performance_coverage
            """,
        )
    )
    transfer_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM transfer_input
            """,
        )
    )
    blocking_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM blocking_input
            """,
        )
    )
    overlap = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM transfer_input t
            JOIN blocking_input b
              ON t.performance_id
               = b.performance_id
            """,
        )
    )
    transfer_multi_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM transfer_input t
            JOIN
                matchdb.main.performance_profile_match m
              ON t.performance_id
               = m.performance_id
            WHERE m.is_multi_section_profile = true
            """,
        )
    )
    transfer_single_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM transfer_input t
            JOIN
                matchdb.main.performance_profile_match m
              ON t.performance_id
               = m.performance_id
            WHERE m.is_multi_section_profile = false
            """,
        )
    )
    transfer_missing_profile_match = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM transfer_input t
            LEFT JOIN
                matchdb.main.performance_profile_match m
              ON t.performance_id
               = m.performance_id
            WHERE m.performance_id IS NULL
            """,
        )
    )
    transfer_multi_missing_coverage = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM transfer_input t
            JOIN
                matchdb.main.performance_profile_match pm
              ON t.performance_id
               = pm.performance_id
            LEFT JOIN
                multi_section_performance_coverage m
              ON t.performance_id
               = m.performance_id
            WHERE pm.is_multi_section_profile = true
              AND m.performance_id IS NULL
            """,
        )
    )
    blocking_multi_count = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM blocking_input b
            JOIN
                matchdb.main.performance_profile_match m
              ON b.performance_id
               = m.performance_id
            WHERE m.is_multi_section_profile = true
            """,
        )
    )
    blocking_missing = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM blocking_input b
            JOIN
                matchdb.main.performance_profile_match pm
              ON b.performance_id
               = pm.performance_id
            LEFT JOIN
                multi_section_performance_coverage m
              ON b.performance_id
               = m.performance_id
            WHERE pm.is_multi_section_profile = true
              AND m.performance_id IS NULL
            """,
        )
    )
    null_sections = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM multi_section_performance_coverage
            WHERE matched_section_index IS NULL
               OR matched_profile_section_id IS NULL
            """,
        )
    )
    invalid_status = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM multi_section_performance_coverage
            WHERE coverage_status NOT IN (
                'BLOCKING_RESULT_PAGE_RESOLUTION',
                'TRANSFER_CANDIDATE_LAYER',
                'UNRESOLVED_EXACT_PROFILE_SECTION'
            )
            """,
        )
    )

    rows = [
        (
            "multi_section_performance_rows",
            abs(
                total_rows
                - EXPECTED_MULTI_SECTION_PERFORMANCES
            ),
            total_rows,
            EXPECTED_MULTI_SECTION_PERFORMANCES,
        ),
        (
            "duplicate_performance_ids",
            total_rows - distinct_rows,
            total_rows - distinct_rows,
            0,
        ),
        (
            "multi_section_athlete_count",
            abs(
                athlete_count
                - EXPECTED_MULTI_SECTION_ATHLETES
            ),
            athlete_count,
            EXPECTED_MULTI_SECTION_ATHLETES,
        ),
        (
            "transfer_input_rows",
            abs(
                transfer_rows
                - EXPECTED_TRANSFER_ROWS
            ),
            transfer_rows,
            EXPECTED_TRANSFER_ROWS,
        ),
        (
            "blocking_input_rows",
            abs(
                blocking_rows
                - EXPECTED_BLOCKING_ROWS
            ),
            blocking_rows,
            EXPECTED_BLOCKING_ROWS,
        ),
        (
            "transfer_blocking_overlap",
            overlap,
            overlap,
            0,
        ),
        (
            "transfer_rows_missing_profile_match",
            transfer_missing_profile_match,
            transfer_missing_profile_match,
            0,
        ),
        (
            "transfer_multi_section_rows_missing_coverage",
            transfer_multi_missing_coverage,
            transfer_multi_missing_coverage,
            0,
        ),
        (
            "transfer_multi_section_row_count",
            0,
            transfer_multi_rows,
            "informational",
        ),
        (
            "transfer_single_section_row_count",
            0,
            transfer_single_rows,
            "informational",
        ),
        (
            "transfer_profile_type_reconciliation",
            abs(
                transfer_rows
                - transfer_multi_rows
                - transfer_single_rows
            ),
            (
                transfer_multi_rows
                + transfer_single_rows
            ),
            transfer_rows,
        ),
        (
            "blocking_multi_section_rows_missing_match",
            blocking_missing,
            blocking_missing,
            0,
        ),
        (
            "null_matched_sections",
            null_sections,
            null_sections,
            0,
        ),
        (
            "invalid_coverage_status",
            invalid_status,
            invalid_status,
            0,
        ),
        (
            "blocking_multi_section_row_count",
            0,
            blocking_multi_count,
            "informational",
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

    output_queries = {
        "coverage_status_summary.csv": """
            SELECT *
            FROM coverage_status_summary
        """,
        "unresolved_section_inventory.csv": """
            SELECT *
            FROM section_coverage_inventory
            WHERE section_coverage_status
                <> 'FULLY_COVERED'
            ORDER BY
                unresolved_performance_count DESC,
                athlete_id,
                section_index
        """,
        "unresolved_section_performance_summary.csv": """
            SELECT
                athlete_id,
                athlete_name,
                matched_section_index
                    AS section_index,
                matched_profile_section_id
                    AS profile_section_id,
                matched_source_section_name
                    AS source_section_name,
                matched_normalized_section_name
                    AS normalized_section_name,
                matched_marker_text
                    AS marker_text,
                original_team_id,
                original_school_id,
                original_school_name,
                gender_code,
                MIN(season_year)
                    AS first_season_year,
                MAX(season_year)
                    AS last_season_year,
                COUNT(*) AS performance_count,
                COUNT(DISTINCT meet_id)
                    AS meet_count,
                string_agg(
                    DISTINCT original_school_name,
                    ' | '
                    ORDER BY original_school_name
                ) AS original_school_names,
                string_agg(
                    DISTINCT meet_name,
                    ' | '
                    ORDER BY meet_name
                ) AS sample_meet_names
            FROM multi_section_performance_coverage
            WHERE coverage_status
                = 'UNRESOLVED_EXACT_PROFILE_SECTION'
            GROUP BY
                athlete_id,
                athlete_name,
                matched_section_index,
                matched_profile_section_id,
                matched_source_section_name,
                matched_normalized_section_name,
                matched_marker_text,
                original_team_id,
                original_school_id,
                original_school_name,
                gender_code
            ORDER BY
                performance_count DESC,
                athlete_id,
                section_index
        """,
        "resolved_section_inventory.csv": """
            SELECT *
            FROM section_coverage_inventory
            WHERE section_coverage_status
                = 'FULLY_COVERED'
            ORDER BY
                athlete_id,
                section_index
        """,
        "athlete_coverage_summary.csv": """
            SELECT *
            FROM athlete_coverage_summary
            ORDER BY
                unresolved_performance_count DESC,
                athlete_id
        """,
        "section_name_frequency.csv": """
            SELECT *
            FROM section_name_frequency
        """,
    }

    for filename, query in output_queries.items():
        con.execute(
            f"""
            COPY (
                {query}
            )
            TO '{
                sql_path(
                    OUTPUT_DIR / filename
                )
            }'
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
    failed_checks = int(
        (checks["failed_row_count"] > 0).sum()
    )
    total_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM multi_section_performance_coverage
            """,
        )
    )
    transfer_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM multi_section_performance_coverage
            WHERE coverage_status
                = 'TRANSFER_CANDIDATE_LAYER'
            """,
        )
    )
    blocking_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM multi_section_performance_coverage
            WHERE coverage_status
                = 'BLOCKING_RESULT_PAGE_RESOLUTION'
            """,
        )
    )
    unresolved_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM multi_section_performance_coverage
            WHERE coverage_status
                = 'UNRESOLVED_EXACT_PROFILE_SECTION'
            """,
        )
    )
    transfer_multi_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM multi_section_performance_coverage
            WHERE coverage_status
                = 'TRANSFER_CANDIDATE_LAYER'
            """,
        )
    )
    transfer_total_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM transfer_input
            """,
        )
    )
    transfer_single_rows = (
        transfer_total_rows
        - transfer_multi_rows
    )
    total_sections = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM section_coverage_inventory
            """,
        )
    )
    unresolved_sections = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM section_coverage_inventory
            WHERE section_coverage_status
                <> 'FULLY_COVERED'
            """,
        )
    )
    unresolved_athletes = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM athlete_coverage_summary
            WHERE unresolved_performance_count > 0
            """,
        )
    )

    report = f"""MILESTONE 4 MULTI-SECTION ATTRIBUTION COVERAGE
============================================================
Audit version: {AUDIT_VERSION}
Source database modified: no
Staging database modified: no
Profile-match database modified: no

COVERAGE
- Multi-section performances: {total_rows:,}
- Covered by transfer-candidate layer: {transfer_rows:,}
- Transfer-layer rows on sole-section profiles: {transfer_single_rows:,}
- Total transfer-layer rows reconciled: {transfer_multi_rows + transfer_single_rows:,}
- Covered by blocking result-page layer: {blocking_rows:,}
- Exact-section performances still requiring resolution: {unresolved_rows:,}
- Matched profile sections represented: {total_sections:,}
- Sections still requiring resolution: {unresolved_sections:,}
- Athletes with unresolved sections: {unresolved_athletes:,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed_checks:,}

NEXT GATE
Use unresolved_section_inventory.csv and section_name_frequency.csv to
build the full profile-section entity and alias registry. Do not assign
final schools to the remaining exact-section rows until their section
names, competition scope, and school/team entities are resolved.
"""

    (
        OUTPUT_DIR / "coverage_report.txt"
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
            "Published coverage database already exists. "
            "Use --replace-output after reviewing it."
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

        failed_checks = int(
            (checks["failed_row_count"] > 0).sum()
        )

        if failed_checks == 0:
            if FINAL_DB.exists():
                FINAL_DB.unlink()
            os.replace(BUILDING_DB, FINAL_DB)
            published = FINAL_DB
        else:
            failed_db = OUTPUT_DIR / (
                "multi_section_attribution_coverage."
                "failed.duckdb"
            )
            if failed_db.exists():
                failed_db.unlink()
            os.replace(BUILDING_DB, failed_db)
            published = failed_db

        report_con = duckdb.connect(
            str(published),
            read_only=True,
        )
        try:
            write_report(
                report_con,
                checks,
            )
        finally:
            report_con.close()

        print(
            "Multi-section attribution coverage audit complete."
        )
        print(f"Outputs: {OUTPUT_DIR}")
        print(
            f"Failed checks: {failed_checks:,}."
        )

        if failed_checks:
            raise SystemExit(1)

    except BaseException:
        try:
            con.close()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
