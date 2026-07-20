#!/usr/bin/env python3
"""
Milestone 4: full performance-to-profile-section URL match audit.

Creates a separate, atomic DuckDB audit database that matches every source
performance to the exact profile section containing its result URL.

The Milestone 3 source database and the all-profile staging database are
attached read-only and are never modified.

Inputs
------
data/database/ncaa_track_analytics.duckdb
data/processed/milestone4/all_profile_staging/all_profile_staging.duckdb
data/processed/milestone4/transfer_candidate_analytical_layer/
    performance_attribution.csv
data/processed/milestone4/blocking_profile_result_resolution/
    performance_team_resolution.csv

Outputs
-------
data/processed/milestone4/all_performance_profile_match/
    all_performance_profile_match.duckdb
    match_audit_report.txt
    hard_checks.csv
    match_status_summary.csv
    section_url_kind_summary.csv
    unmatched_performance_queue.csv
    multiple_section_match_queue.csv
    transfer_validation_failures.csv

No final school attribution is applied in this phase. This is the blocking
coverage audit for the later one-row-per-performance attribution table.
"""

from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime, timezone
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
    / "data/processed/milestone4"
    / "all_performance_profile_match"
)
FINAL_DB = (
    OUTPUT_DIR
    / "all_performance_profile_match.duckdb"
)
BUILDING_DB = (
    OUTPUT_DIR
    / "all_performance_profile_match.building.duckdb"
)
FAILED_DB = (
    OUTPUT_DIR
    / "all_performance_profile_match.failed.duckdb"
)
TEMP_DIR = OUTPUT_DIR / "duckdb_temp"

AUDIT_VERSION = "m4_all_performance_profile_match_v1.1"
EXPECTED_PERFORMANCE_ROWS = 6_594_540
EXPECTED_TRANSFER_ROWS = 164_964
EXPECTED_BLOCKING_ROWS = 1_134


def clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split()).strip()


def sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--replace-output",
        action="store_true",
        help=(
            "Replace an existing published audit database. "
            "The source and staging databases remain read-only."
        ),
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=1,
        help="DuckDB worker threads. Default: 1.",
    )
    parser.add_argument(
        "--memory-limit",
        default="4GB",
        help=(
            "DuckDB memory limit used to encourage disk spilling. "
            "Default: 4GB."
        ),
    )

    return parser.parse_args()


def require_inputs() -> None:
    for path in [
        SOURCE_DB,
        STAGING_DB,
        TRANSFER_CSV,
        BLOCKING_CSV,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )


def remove_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


def scalar(
    con: duckdb.DuckDBPyConnection,
    query: str,
    params: list[Any] | None = None,
) -> Any:
    return con.execute(
        query,
        params or [],
    ).fetchone()[0]


def create_url_macros(
    con: duckdb.DuckDBPyConnection,
) -> None:
    con.execute(
        r"""
        CREATE OR REPLACE MACRO repair_tfrrs_url(input_url) AS (
            replace(
                replace(
                    trim(CAST(input_url AS VARCHAR)),
                    'https://www.tfrrs.orghttps://',
                    'https://'
                ),
                'https://tfrrs.orghttps://',
                'https://'
            )
        );

        CREATE OR REPLACE MACRO absolute_tfrrs_url(input_url) AS (
            CASE
                WHEN input_url IS NULL
                  OR trim(CAST(input_url AS VARCHAR)) = ''
                    THEN NULL
                WHEN starts_with(
                    repair_tfrrs_url(input_url),
                    '/'
                )
                    THEN
                        'https://www.tfrrs.org'
                        || repair_tfrrs_url(input_url)
                WHEN starts_with(
                    repair_tfrrs_url(input_url),
                    'www.tfrrs.org/'
                )
                    THEN
                        'https://'
                        || repair_tfrrs_url(input_url)
                ELSE repair_tfrrs_url(input_url)
            END
        );

        CREATE OR REPLACE MACRO normalize_tfrrs_url(input_url) AS (
            CASE
                WHEN absolute_tfrrs_url(input_url) IS NULL
                    THEN NULL
                ELSE regexp_replace(
                    regexp_replace(
                        replace(
                            replace(
                                replace(
                                    absolute_tfrrs_url(input_url),
                                    'http://www.tfrrs.org',
                                    'https://www.tfrrs.org'
                                ),
                                'http://tfrrs.org',
                                'https://www.tfrrs.org'
                            ),
                            'https://tfrrs.org',
                            'https://www.tfrrs.org'
                        ),
                        '#.*$',
                        ''
                    ),
                    '/$',
                    ''
                )
            END
        );
        """
    )


def create_database(
    con: duckdb.DuckDBPyConnection,
) -> None:
    source_path = sql_path(SOURCE_DB)
    staging_path = sql_path(STAGING_DB)
    transfer_path = sql_path(TRANSFER_CSV)
    blocking_path = sql_path(BLOCKING_CSV)

    con.execute(
        f"""
        ATTACH '{source_path}'
            AS srcdb (READ_ONLY);
        ATTACH '{staging_path}'
            AS stagedb (READ_ONLY);
        """
    )

    create_url_macros(con)

    con.execute(
        f"""
        CREATE TABLE audit_metadata (
            audit_version VARCHAR NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL,
            source_database VARCHAR NOT NULL,
            staging_database VARCHAR NOT NULL,
            transfer_file VARCHAR NOT NULL,
            blocking_file VARCHAR NOT NULL,
            source_database_modified BOOLEAN NOT NULL,
            staging_database_modified BOOLEAN NOT NULL
        );

        INSERT INTO audit_metadata
        VALUES (
            '{AUDIT_VERSION}',
            current_timestamp,
            '{source_path}',
            '{staging_path}',
            '{transfer_path}',
            '{blocking_path}',
            false,
            false
        );

        CREATE VIEW transfer_input AS
        SELECT *
        FROM read_csv_auto(
            '{transfer_path}',
            header = true,
            all_varchar = true,
            sample_size = -1
        );

        CREATE VIEW blocking_input AS
        SELECT *
        FROM read_csv_auto(
            '{blocking_path}',
            header = true,
            all_varchar = true,
            sample_size = -1
        );
        """
    )

    print("Creating normalized performance URL table...")

    con.execute(
        """
        CREATE TABLE normalized_performance_urls AS
        SELECT
            CAST(
                p.performance_id AS VARCHAR
            ) AS performance_id,
            CAST(
                p.athlete_id AS BIGINT
            ) AS athlete_id,
            CAST(
                p.team_id AS VARCHAR
            ) AS original_team_id,
            CAST(
                t.school_id AS VARCHAR
            ) AS original_school_id,
            s.school_name
                AS original_school_name,
            t.gender_code,
            p.result_url AS source_result_url,
            normalize_tfrrs_url(
                p.result_url
            ) AS normalized_result_url,
            CASE
                WHEN normalize_tfrrs_url(
                    p.result_url
                ) IS NULL
                    THEN NULL
                ELSE sha256(
                    normalize_tfrrs_url(
                        p.result_url
                    )
                )
            END AS result_url_sha256
        FROM srcdb.core.performances p
        LEFT JOIN srcdb.core.teams t
          ON p.team_id = t.team_id
        LEFT JOIN srcdb.core.schools s
          ON t.school_id = s.school_id;

        CREATE UNIQUE INDEX
            idx_normalized_performance_id
        ON normalized_performance_urls(
            performance_id
        );
        """
    )

    print("Creating profile section-count tables...")

    con.execute(
        """
        CREATE TABLE profile_section_counts AS
        SELECT
            athlete_id,
            COUNT(*) AS profile_section_count
        FROM stagedb.main.profile_sections
        GROUP BY athlete_id;

        CREATE UNIQUE INDEX
            idx_profile_section_counts_athlete
        ON profile_section_counts(
            athlete_id
        );

        CREATE TABLE single_profile_sections AS
        SELECT
            s.athlete_id,
            s.section_index,
            s.profile_section_id,
            s.source_section_name,
            s.normalized_section_name,
            s.marker_text,
            s.attribution_method
                AS profile_attribution_method,
            s.is_current_section,
            s.source_html_sha256,
            s.parser_version
        FROM stagedb.main.profile_sections s
        JOIN profile_section_counts c
          ON s.athlete_id = c.athlete_id
        WHERE c.profile_section_count = 1;

        CREATE UNIQUE INDEX
            idx_single_profile_sections_athlete
        ON single_profile_sections(
            athlete_id
        );

        CREATE TABLE multi_section_athletes AS
        SELECT athlete_id
        FROM profile_section_counts
        WHERE profile_section_count > 1;

        CREATE UNIQUE INDEX
            idx_multi_section_athletes_id
        ON multi_section_athletes(
            athlete_id
        );
        """
    )

    print(
        "Filtering performances and URL keys to "
        "multi-section athletes..."
    )

    con.execute(
        """
        CREATE TABLE multi_section_performance_urls AS
        SELECT p.*
        FROM normalized_performance_urls p
        JOIN multi_section_athletes m
          ON p.athlete_id = m.athlete_id;

        CREATE INDEX
            idx_multi_performance_match_key
        ON multi_section_performance_urls(
            athlete_id,
            result_url_sha256
        );

        CREATE TABLE multi_section_url_keys AS
        SELECT
            k.athlete_id,
            k.section_index,
            k.url_sha256,
            k.url_kind
        FROM stagedb.main.section_url_keys k
        JOIN multi_section_athletes m
          ON k.athlete_id = m.athlete_id;

        CREATE INDEX
            idx_multi_url_key
        ON multi_section_url_keys(
            athlete_id,
            url_sha256
        );
        """
    )

    print(
        "Matching multi-section performance URLs "
        "to exact profile sections..."
    )

    con.execute(
        """
        CREATE TABLE performance_section_match_rows AS
        SELECT
            p.performance_id,
            p.athlete_id,
            k.section_index,
            k.url_kind,
            s.profile_section_id,
            s.source_section_name,
            s.normalized_section_name,
            s.marker_text,
            s.attribution_method
                AS profile_attribution_method,
            s.is_current_section,
            s.source_html_sha256,
            s.parser_version
        FROM multi_section_performance_urls p
        JOIN multi_section_url_keys k
          ON p.athlete_id = k.athlete_id
         AND p.result_url_sha256 = k.url_sha256
        LEFT JOIN stagedb.main.profile_sections s
          ON k.athlete_id = s.athlete_id
         AND k.section_index = s.section_index;

        CREATE TABLE performance_section_match_agg AS
        SELECT
            performance_id,
            COUNT(*) AS matched_key_count,
            COUNT(
                DISTINCT section_index
            ) AS matched_section_count,
            MIN(section_index)
                AS matched_section_index,
            string_agg(
                DISTINCT CAST(
                    section_index AS VARCHAR
                ),
                ' | '
                ORDER BY CAST(
                    section_index AS VARCHAR
                )
            ) AS matched_section_indexes,
            string_agg(
                DISTINCT profile_section_id,
                ' | '
                ORDER BY profile_section_id
            ) AS matched_profile_section_ids,
            MIN(profile_section_id)
                AS matched_profile_section_id,
            MIN(source_section_name)
                AS matched_source_section_name,
            MIN(normalized_section_name)
                AS matched_normalized_section_name,
            MIN(marker_text)
                AS matched_marker_text,
            MIN(profile_attribution_method)
                AS matched_profile_attribution_method,
            MIN(is_current_section)
                AS matched_is_current_section,
            MIN(source_html_sha256)
                AS source_html_sha256,
            MIN(parser_version)
                AS parser_version
        FROM performance_section_match_rows
        GROUP BY performance_id;

        CREATE UNIQUE INDEX
            idx_match_agg_performance_id
        ON performance_section_match_agg(
            performance_id
        );
        """
    )

    print("Creating one-row-per-performance match table...")

    con.execute(
        """
        CREATE TABLE performance_profile_match AS
        SELECT
            p.performance_id,
            p.athlete_id,
            p.original_team_id,
            p.original_school_id,
            p.original_school_name,
            p.gender_code,
            p.source_result_url,
            p.normalized_result_url,
            p.result_url_sha256,
            COALESCE(
                c.profile_section_count,
                0
            ) AS profile_section_count,
            CASE
                WHEN c.profile_section_count = 1
                    THEN 0
                ELSE COALESCE(
                    a.matched_key_count,
                    0
                )
            END AS matched_key_count,
            CASE
                WHEN c.profile_section_count = 1
                    THEN 1
                ELSE COALESCE(
                    a.matched_section_count,
                    0
                )
            END AS matched_section_count,
            CASE
                WHEN c.profile_section_count = 1
                    THEN one.section_index
                ELSE a.matched_section_index
            END AS matched_section_index,
            CASE
                WHEN c.profile_section_count = 1
                    THEN CAST(
                        one.section_index
                        AS VARCHAR
                    )
                ELSE a.matched_section_indexes
            END AS matched_section_indexes,
            CASE
                WHEN c.profile_section_count = 1
                    THEN one.profile_section_id
                ELSE a.matched_profile_section_id
            END AS matched_profile_section_id,
            CASE
                WHEN c.profile_section_count = 1
                    THEN one.profile_section_id
                ELSE a.matched_profile_section_ids
            END AS matched_profile_section_ids,
            CASE
                WHEN c.profile_section_count = 1
                    THEN one.source_section_name
                ELSE a.matched_source_section_name
            END AS matched_source_section_name,
            CASE
                WHEN c.profile_section_count = 1
                    THEN one.normalized_section_name
                ELSE a.matched_normalized_section_name
            END AS matched_normalized_section_name,
            CASE
                WHEN c.profile_section_count = 1
                    THEN one.marker_text
                ELSE a.matched_marker_text
            END AS matched_marker_text,
            CASE
                WHEN c.profile_section_count = 1
                    THEN one.profile_attribution_method
                ELSE a.matched_profile_attribution_method
            END AS matched_profile_attribution_method,
            CASE
                WHEN c.profile_section_count = 1
                    THEN one.is_current_section
                ELSE a.matched_is_current_section
            END AS matched_is_current_section,
            CASE
                WHEN c.profile_section_count = 1
                    THEN one.source_html_sha256
                ELSE a.source_html_sha256
            END AS source_html_sha256,
            CASE
                WHEN c.profile_section_count = 1
                    THEN one.parser_version
                ELSE a.parser_version
            END AS parser_version,
            CASE
                WHEN c.profile_section_count = 1
                    THEN 'SOLE_PROFILE_SECTION_INFERENCE'
                WHEN a.matched_section_count = 1
                    THEN 'EXACT_RESULT_URL_SECTION_MATCH'
                ELSE NULL
            END AS match_evidence_method,
            CASE
                WHEN p.normalized_result_url
                    IS NULL
                    THEN 'MISSING_RESULT_URL'
                WHEN COALESCE(
                    c.profile_section_count,
                    0
                ) = 0
                    THEN 'NO_PROFILE_SECTIONS'
                WHEN c.profile_section_count = 1
                    THEN 'INFERRED_SINGLE_SECTION_PROFILE'
                WHEN COALESCE(
                    a.matched_section_count,
                    0
                ) = 0
                    THEN 'NO_PROFILE_SECTION_MATCH'
                WHEN a.matched_section_count > 1
                    THEN 'MULTIPLE_PROFILE_SECTION_MATCHES'
                ELSE 'MATCHED_MULTI_SECTION_PROFILE'
            END AS profile_match_status,
            (
                COALESCE(
                    c.profile_section_count,
                    0
                ) > 1
            ) AS is_multi_section_profile,
            '{AUDIT_VERSION}'
                AS match_audit_version
        FROM normalized_performance_urls p
        LEFT JOIN profile_section_counts c
          ON p.athlete_id = c.athlete_id
        LEFT JOIN single_profile_sections one
          ON p.athlete_id = one.athlete_id
        LEFT JOIN performance_section_match_agg a
          ON p.performance_id = a.performance_id;

        CREATE UNIQUE INDEX
            idx_performance_profile_match_id
        ON performance_profile_match(
            performance_id
        );
        """
    )

    print("Validating the known transfer layer...")

    con.execute(
        """
        CREATE TABLE transfer_layer_validation AS
        SELECT
            t.performance_id,
            TRY_CAST(
                t.athlete_id AS BIGINT
            ) AS athlete_id,
            TRY_CAST(
                t.profile_section_index
                    AS BIGINT
            ) AS expected_section_index,
            m.matched_section_index,
            m.matched_section_count,
            m.profile_match_status,
            m.match_evidence_method,
            t.normalized_result_url
                AS transfer_normalized_result_url,
            m.normalized_result_url
                AS source_normalized_result_url,
            CASE
                WHEN t.normalized_result_url
                    = m.normalized_result_url
                    THEN true
                ELSE false
            END AS normalized_url_matches,
            CASE
                WHEN TRY_CAST(
                    t.profile_section_index
                        AS BIGINT
                ) = m.matched_section_index
                 AND m.matched_section_count = 1
                    THEN true
                ELSE false
            END AS section_match_validated
        FROM transfer_input t
        LEFT JOIN performance_profile_match m
          ON t.performance_id
           = m.performance_id;
        """
    )

    con.execute(
        """
        CREATE TABLE section_url_kind_summary AS
        SELECT
            url_kind,
            COUNT(*) AS url_key_count,
            COUNT(
                DISTINCT athlete_id
            ) AS athlete_count
        FROM stagedb.main.section_url_keys
        GROUP BY url_kind
        ORDER BY url_key_count DESC;

        CREATE TABLE match_status_summary AS
        SELECT
            profile_match_status,
            match_evidence_method,
            is_multi_section_profile,
            COUNT(*) AS performance_count,
            COUNT(
                DISTINCT athlete_id
            ) AS athlete_count
        FROM performance_profile_match
        GROUP BY
            profile_match_status,
            match_evidence_method,
            is_multi_section_profile
        ORDER BY
            profile_match_status,
            match_evidence_method,
            is_multi_section_profile;
        """
    )


def build_checks(
    con: duckdb.DuckDBPyConnection,
) -> pd.DataFrame:
    source_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM srcdb.core.performances
            """,
        )
    )
    source_distinct = int(
        scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT performance_id
            )
            FROM srcdb.core.performances
            """,
        )
    )
    output_rows = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM performance_profile_match
            """,
        )
    )
    output_distinct = int(
        scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT performance_id
            )
            FROM performance_profile_match
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
    missing_result_urls = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM performance_profile_match
            WHERE normalized_result_url
                IS NULL
            """,
        )
    )
    no_profile_match = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM performance_profile_match
            WHERE matched_section_count = 0
            """,
        )
    )
    multiple_matches = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM performance_profile_match
            WHERE matched_section_count > 1
            """,
        )
    )
    missing_profile_status = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT athlete_id
                FROM normalized_performance_urls
            ) p
            LEFT JOIN
                stagedb.main.profile_parse_status s
              ON p.athlete_id = s.athlete_id
            WHERE s.athlete_id IS NULL
            """,
        )
    )
    non_ok_profiles_with_performances = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT athlete_id
                FROM normalized_performance_urls
            ) p
            JOIN stagedb.main.profile_parse_status s
              ON p.athlete_id = s.athlete_id
            WHERE s.parse_status <> 'OK'
            """,
        )
    )
    transfer_missing_output = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM transfer_layer_validation
            WHERE matched_section_count IS NULL
            """,
        )
    )
    transfer_url_mismatch = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM transfer_layer_validation
            WHERE normalized_url_matches
                IS DISTINCT FROM true
            """,
        )
    )
    transfer_section_mismatch = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM transfer_layer_validation
            WHERE section_match_validated
                IS DISTINCT FROM true
            """,
        )
    )
    blocking_overlap = int(
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

    checks = [
        (
            "source_performance_rows",
            abs(
                source_rows
                - EXPECTED_PERFORMANCE_ROWS
            ),
            source_rows,
            EXPECTED_PERFORMANCE_ROWS,
        ),
        (
            "source_duplicate_performance_ids",
            source_rows - source_distinct,
            source_rows - source_distinct,
            0,
        ),
        (
            "output_row_count_reconciles",
            abs(output_rows - source_rows),
            output_rows,
            source_rows,
        ),
        (
            "output_duplicate_performance_ids",
            output_rows - output_distinct,
            output_rows - output_distinct,
            0,
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
            "missing_result_URLs",
            missing_result_urls,
            missing_result_urls,
            0,
        ),
        (
            "performances_without_profile_match",
            no_profile_match,
            no_profile_match,
            0,
        ),
        (
            "performances_matching_multiple_sections",
            multiple_matches,
            multiple_matches,
            0,
        ),
        (
            "performance_athletes_missing_parse_status",
            missing_profile_status,
            missing_profile_status,
            0,
        ),
        (
            "non_OK_profiles_with_performances",
            non_ok_profiles_with_performances,
            non_ok_profiles_with_performances,
            0,
        ),
        (
            "transfer_rows_missing_consolidated_match",
            transfer_missing_output,
            transfer_missing_output,
            0,
        ),
        (
            "transfer_URL_normalization_mismatches",
            transfer_url_mismatch,
            transfer_url_mismatch,
            0,
        ),
        (
            "transfer_section_validation_mismatches",
            transfer_section_mismatch,
            transfer_section_mismatch,
            0,
        ),
        (
            "transfer_blocking_overlap",
            blocking_overlap,
            blocking_overlap,
            0,
        ),
    ]

    return pd.DataFrame(
        checks,
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

    con.execute(
        f"""
        COPY match_status_summary
        TO '{
            sql_path(
                OUTPUT_DIR
                / "match_status_summary.csv"
            )
        }'
        (
            HEADER,
            DELIMITER ','
        );

        COPY section_url_kind_summary
        TO '{
            sql_path(
                OUTPUT_DIR
                / "section_url_kind_summary.csv"
            )
        }'
        (
            HEADER,
            DELIMITER ','
        );

        COPY (
            SELECT *
            FROM performance_profile_match
            WHERE matched_section_count = 0
            ORDER BY
                athlete_id,
                performance_id
        )
        TO '{
            sql_path(
                OUTPUT_DIR
                / "unmatched_performance_queue.csv"
            )
        }'
        (
            HEADER,
            DELIMITER ','
        );

        COPY (
            SELECT *
            FROM performance_profile_match
            WHERE matched_section_count > 1
            ORDER BY
                athlete_id,
                performance_id
        )
        TO '{
            sql_path(
                OUTPUT_DIR
                / "multiple_section_match_queue.csv"
            )
        }'
        (
            HEADER,
            DELIMITER ','
        );

        COPY (
            SELECT *
            FROM transfer_layer_validation
            WHERE normalized_url_matches
                    IS DISTINCT FROM true
               OR section_match_validated
                    IS DISTINCT FROM true
            ORDER BY
                athlete_id,
                performance_id
        )
        TO '{
            sql_path(
                OUTPUT_DIR
                / "transfer_validation_failures.csv"
            )
        }'
        (
            HEADER,
            DELIMITER ','
        );
        """
    )


def write_report(
    con: duckdb.DuckDBPyConnection,
    checks: pd.DataFrame,
    published_db: Path,
) -> None:
    failed_checks = int(
        (
            checks["failed_row_count"] > 0
        ).sum()
    )
    matched_single = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM performance_profile_match
            WHERE profile_match_status
                = 'INFERRED_SINGLE_SECTION_PROFILE'
            """,
        )
    )
    matched_multi = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM performance_profile_match
            WHERE profile_match_status
                = 'MATCHED_MULTI_SECTION_PROFILE'
            """,
        )
    )
    unmatched = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM performance_profile_match
            WHERE matched_section_count = 0
            """,
        )
    )
    multiple = int(
        scalar(
            con,
            """
            SELECT COUNT(*)
            FROM performance_profile_match
            WHERE matched_section_count > 1
            """,
        )
    )
    matched_athletes = int(
        scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT athlete_id
            )
            FROM performance_profile_match
            WHERE matched_section_count = 1
            """,
        )
    )
    multi_profile_athletes = int(
        scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT athlete_id
            )
            FROM performance_profile_match
            WHERE is_multi_section_profile
            """,
        )
    )

    report = f"""MILESTONE 4 ALL-PERFORMANCE PROFILE MATCH AUDIT
============================================================
Audit version: {AUDIT_VERSION}
Generated at: {
    datetime.now(timezone.utc).isoformat()
}
Source database modified: no
Staging database modified: no

OUTPUT
- Audit database: {published_db}

COVERAGE
- Source performances: {EXPECTED_PERFORMANCE_ROWS:,}
- Single-section-profile inferences: {matched_single:,}
- Exact multi-section-profile matches: {matched_multi:,}
- Performances without a profile match: {unmatched:,}
- Performances matching multiple sections: {multiple:,}
- Athletes with matched performances: {matched_athletes:,}
- Multi-section athletes represented: {multi_profile_athletes:,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed_checks:,}

NEXT GATE
If all hard checks pass, use performance_profile_match as the full-scale
profile-section evidence table. The later consolidated attribution layer
will apply deterministic precedence:
1. blocking result-page resolution;
2. validated classified transfer attribution;
3. exact multi-section URL evidence;
4. sole-section inference for one-section profiles;
5. original source attribution only where no correction is required.
"""

    (
        OUTPUT_DIR / "match_audit_report.txt"
    ).write_text(
        report,
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    require_inputs()

    if args.threads < 1:
        raise ValueError(
            "--threads must be at least 1."
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)

    TEMP_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if (
        FINAL_DB.exists()
        and not args.replace_output
    ):
        raise FileExistsError(
            "Published audit database already exists. "
            "Use --replace-output only after reviewing "
            f"the existing output: {FINAL_DB}"
        )

    remove_if_exists(BUILDING_DB)
    remove_if_exists(FAILED_DB)

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
            f"""
            SET temp_directory = '{
                sql_path(TEMP_DIR)
            }';
            """
        )
        con.execute(
            "SET preserve_insertion_order = false;"
        )

        create_database(con)
        checks = build_checks(con)

        con.register(
            "checks_frame",
            checks,
        )
        con.execute(
            """
            CREATE TABLE hard_checks AS
            SELECT *
            FROM checks_frame;
            """
        )
        con.unregister("checks_frame")

        export_outputs(
            con=con,
            checks=checks,
        )

        failed_checks = int(
            (
                checks["failed_row_count"] > 0
            ).sum()
        )

        con.execute("CHECKPOINT;")
        con.close()

        if failed_checks == 0:
            if FINAL_DB.exists():
                FINAL_DB.unlink()
            os.replace(
                BUILDING_DB,
                FINAL_DB,
            )
            published = FINAL_DB
        else:
            os.replace(
                BUILDING_DB,
                FAILED_DB,
            )
            published = FAILED_DB

        report_con = duckdb.connect(
            str(published),
            read_only=True,
        )
        try:
            write_report(
                con=report_con,
                checks=checks,
                published_db=published,
            )
        finally:
            report_con.close()

        print(
            "All-performance profile match audit complete."
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
