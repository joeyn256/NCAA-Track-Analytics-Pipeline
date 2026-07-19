#!/usr/bin/env python3
"""
Milestone 4: finalize canonical performance attribution v1.1.

This script preserves the v1.0 attribution database and creates a separate
v1.1 database. It applies only the validated result-page fallback rows from:

data/processed/milestone4/uncovered_source_result_evidence/
    performance_result_evidence.csv

No source or prior Milestone 4 database is modified.

Expected targeted correction
-----------------------------
- 18 unresolved performances
- 1 athlete
- 1 resolved team: OH_college_f_Dayton
- 0 unresolved rows after correction

Outputs
-------
data/processed/milestone4/canonical_performance_attribution_v1_1/
    canonical_performance_attribution_v1_1.duckdb
    attribution_report.txt
    hard_checks.csv
    attribution_precedence_summary.csv
    competition_scope_summary.csv
    confidence_summary.csv
    result_page_fallback_summary.csv
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]

SOURCE_DB = (
    PROJECT_ROOT
    / "data/database/"
    / "ncaa_track_analytics.duckdb"
)

V1_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_performance_attribution/"
    / "canonical_performance_attribution.duckdb"
)

EVIDENCE_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "uncovered_source_result_evidence/"
    / "performance_result_evidence.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_performance_attribution_v1_1"
)

OUTPUT_DB = (
    OUTPUT_DIR
    / "canonical_performance_attribution_v1_1.duckdb"
)

ATTRIBUTION_VERSION = (
    "m4_canonical_performance_attribution_v1.1"
)

EXPECTED_SOURCE_ROWS = 6_594_540
EXPECTED_FALLBACK_ROWS = 18
EXPECTED_FALLBACK_ATHLETES = 1
EXPECTED_FALLBACK_TEAMS = 1
EXPECTED_FALLBACK_TEAM_ID = "OH_college_f_Dayton"

EXPECTED_PRECEDENCE = {
    "PERFORMANCE_LEVEL_OVERRIDE": 120,
    "CANONICAL_PROFILE_SECTION": 426_375,
    "TRANSFER_FINAL_TEAM": 160_935,
    "TRANSFER_NON_D1_SCOPE": 3_578,
    "RESULT_PAGE_SOURCE_FALLBACK": 18,
    "ORIGINAL_SOURCE_TEAM": 6_003_514,
    "UNRESOLVED": 0,
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


def require_inputs() -> None:
    for path in [
        SOURCE_DB,
        V1_DB,
        EVIDENCE_CSV,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
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
        OUTPUT_DIR / "attribution_report.txt",
        OUTPUT_DIR / "hard_checks.csv",
        OUTPUT_DIR
        / "attribution_precedence_summary.csv",
        OUTPUT_DIR / "competition_scope_summary.csv",
        OUTPUT_DIR / "confidence_summary.csv",
        OUTPUT_DIR
        / "result_page_fallback_summary.csv",
    ]

    existing = [
        path for path in generated
        if path.exists()
    ]

    if existing and not replace_output:
        raise FileExistsError(
            "Existing v1.1 outputs found. "
            "Use --replace-output only after review."
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


def attach_inputs(
    con: duckdb.DuckDBPyConnection,
) -> None:
    con.execute(
        f"""
        ATTACH '{sql_path(SOURCE_DB)}'
        AS source
        (READ_ONLY)
        """
    )

    con.execute(
        f"""
        ATTACH '{sql_path(V1_DB)}'
        AS v1
        (READ_ONLY)
        """
    )

    con.execute(
        f"""
        CREATE TEMP VIEW result_evidence AS
        SELECT *
        FROM read_csv_auto(
            '{sql_path(EVIDENCE_CSV)}',
            HEADER = TRUE,
            ALL_VARCHAR = TRUE
        )
        """
    )


def validate_evidence(
    con: duckdb.DuckDBPyConnection,
) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            COUNT(*) AS evidence_rows,
            COUNT(DISTINCT performance_id)
                AS distinct_performance_ids,
            COUNT(DISTINCT athlete_id)
                AS athlete_count,
            COUNT(DISTINCT parsed_team_id)
                AS team_count,
            MIN(parsed_team_id)
                AS minimum_team_id,
            MAX(parsed_team_id)
                AS maximum_team_id,
            SUM(
                CASE
                    WHEN team_parse_status
                        != 'TEAM_LINK_FOUND'
                    THEN 1
                    ELSE 0
                END
            ) AS nonresolved_rows,
            SUM(
                CASE
                    WHEN lower(
                        parsed_team_matches_current_team
                    ) != 'true'
                    THEN 1
                    ELSE 0
                END
            ) AS current_team_mismatch_rows,
            SUM(
                CASE
                    WHEN NULLIF(
                        parsed_team_id,
                        ''
                    ) IS NULL
                    THEN 1
                    ELSE 0
                END
            ) AS blank_team_id_rows
        FROM result_evidence
        """
    ).fetchdf()


def build_v1_1_table(
    con: duckdb.DuckDBPyConnection,
) -> None:
    print(
        "Building canonical performance "
        "attribution v1.1..."
    )

    con.execute(
        """
        CREATE TABLE
            canonical_performance_attribution
        AS

        SELECT
            a.performance_id,
            a.athlete_id,
            a.affiliation_id,
            a.season_year,
            a.season_type,

            a.original_team_id,
            a.original_school_id,
            a.original_school_name,
            a.original_team_name,

            a.matched_section_index,
            a.matched_profile_section_id,
            a.matched_source_section_name,
            a.coverage_status,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN 'school_team'
                ELSE a.canonical_entity_type
            END AS canonical_entity_type,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN COALESCE(
                    NULLIF(t.school_id, ''),
                    NULLIF(e.parsed_team_id, '')
                )
                ELSE a.canonical_analytical_entity_id
            END AS canonical_analytical_entity_id,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN NULLIF(e.parsed_team_id, '')
                ELSE a.canonical_team_id
            END AS canonical_team_id,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN NULLIF(t.school_id, '')
                ELSE a.canonical_school_id
            END AS canonical_school_id,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN COALESCE(
                    NULLIF(s.school_name, ''),
                    NULLIF(e.parsed_team_name, '')
                )
                ELSE a.canonical_school_name
            END AS canonical_school_name,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN COALESCE(
                    NULLIF(t.team_name, ''),
                    NULLIF(e.parsed_team_name, '')
                )
                ELSE a.canonical_team_name
            END AS canonical_team_name,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN COALESCE(
                    NULLIF(t.team_url, ''),
                    NULLIF(e.parsed_team_url, '')
                )
                ELSE a.canonical_team_url
            END AS canonical_team_url,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN COALESCE(
                    NULLIF(t.gender_code, ''),
                    a.canonical_gender_code
                )
                ELSE a.canonical_gender_code
            END AS canonical_gender_code,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN COALESCE(
                    NULLIF(t.division, ''),
                    ''
                )
                ELSE a.canonical_division
            END AS canonical_division,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN 'COLLEGIATE'
                ELSE a.canonical_career_stage
            END AS canonical_career_stage,

            CASE
                WHEN e.performance_id IS NOT NULL
                     AND t.division = 'D1'
                THEN 'NCAA'
                WHEN e.performance_id IS NOT NULL
                THEN 'UNKNOWN_OR_OTHER'
                ELSE a.canonical_governing_system
            END AS canonical_governing_system,

            CASE
                WHEN e.performance_id IS NOT NULL
                     AND t.division = 'D1'
                THEN 'NCAA_D1'
                WHEN e.performance_id IS NOT NULL
                     AND t.division = 'D2'
                THEN 'NCAA_D2'
                WHEN e.performance_id IS NOT NULL
                     AND t.division = 'D3'
                THEN 'NCAA_D3'
                WHEN e.performance_id IS NOT NULL
                THEN 'NON_D1_OR_UNKNOWN'
                ELSE a.canonical_competition_level
            END AS canonical_competition_level,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN COALESCE(
                    t.division = 'D1',
                    FALSE
                )
                ELSE a.d1_development_eligible
            END AS d1_development_eligible,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN COALESCE(
                    t.division = 'D1',
                    FALSE
                )
                ELSE a.school_stint_eligible
            END AS school_stint_eligible,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN 'RESULT_PAGE_SOURCE_FALLBACK'
                ELSE a.attribution_precedence
            END AS attribution_precedence,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN 'RESULT_PAGE_TEAM_RESOLVED'
                ELSE a.attribution_status
            END AS attribution_status,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN 'EXACT_RESULT_PAGE_ATHLETE_ROW'
                ELSE a.attribution_method
            END AS attribution_method,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN 'HIGH'
                ELSE a.attribution_confidence
            END AS attribution_confidence,

            a.requires_performance_override,

            CASE
                WHEN e.performance_id IS NOT NULL
                THEN e.evidence_version
                ELSE a.evidence_source
            END AS evidence_source,

            'm4_canonical_performance_attribution_v1.1'
                AS attribution_version

        FROM v1.main
            .canonical_performance_attribution a

        LEFT JOIN result_evidence e
          ON a.performance_id
             = e.performance_id
         AND e.team_parse_status
             = 'TEAM_LINK_FOUND'

        LEFT JOIN source.core.teams t
          ON NULLIF(
                e.parsed_team_id,
                ''
             ) = t.team_id

        LEFT JOIN source.core.schools s
          ON t.school_id
             = s.school_id
        """
    )


def create_summary_tables(
    con: duckdb.DuckDBPyConnection,
) -> None:
    con.execute(
        """
        CREATE TABLE
            attribution_precedence_summary
        AS
        SELECT
            attribution_precedence,
            COUNT(*) AS performance_rows,
            COUNT(DISTINCT athlete_id)
                AS athlete_count,
            SUM(
                CASE
                    WHEN d1_development_eligible
                    THEN 1
                    ELSE 0
                END
            ) AS d1_development_rows,
            SUM(
                CASE
                    WHEN school_stint_eligible
                    THEN 1
                    ELSE 0
                END
            ) AS school_stint_rows
        FROM canonical_performance_attribution
        GROUP BY attribution_precedence
        ORDER BY performance_rows DESC
        """
    )

    con.execute(
        """
        CREATE TABLE competition_scope_summary AS
        SELECT
            canonical_career_stage,
            canonical_governing_system,
            canonical_competition_level,
            d1_development_eligible,
            school_stint_eligible,
            COUNT(*) AS performance_rows,
            COUNT(DISTINCT athlete_id)
                AS athlete_count
        FROM canonical_performance_attribution
        GROUP BY
            canonical_career_stage,
            canonical_governing_system,
            canonical_competition_level,
            d1_development_eligible,
            school_stint_eligible
        ORDER BY performance_rows DESC
        """
    )

    con.execute(
        """
        CREATE TABLE confidence_summary AS
        SELECT
            attribution_confidence,
            attribution_status,
            attribution_method,
            COUNT(*) AS performance_rows,
            COUNT(DISTINCT athlete_id)
                AS athlete_count
        FROM canonical_performance_attribution
        GROUP BY
            attribution_confidence,
            attribution_status,
            attribution_method
        ORDER BY performance_rows DESC
        """
    )

    con.execute(
        """
        CREATE TABLE result_page_fallback_summary AS
        SELECT
            canonical_team_id,
            canonical_school_id,
            canonical_school_name,
            canonical_team_name,
            canonical_gender_code,
            canonical_division,
            COUNT(*) AS performance_rows,
            COUNT(DISTINCT athlete_id)
                AS athlete_count,
            COUNT(DISTINCT season_year)
                AS season_year_count,
            MIN(season_year)
                AS first_season_year,
            MAX(season_year)
                AS last_season_year
        FROM canonical_performance_attribution
        WHERE attribution_precedence
            = 'RESULT_PAGE_SOURCE_FALLBACK'
        GROUP BY
            canonical_team_id,
            canonical_school_id,
            canonical_school_name,
            canonical_team_name,
            canonical_gender_code,
            canonical_division
        ORDER BY performance_rows DESC
        """
    )

    con.execute(
        """
        CREATE VIEW d1_development_attribution AS
        SELECT *
        FROM canonical_performance_attribution
        WHERE d1_development_eligible
        """
    )

    con.execute(
        """
        CREATE VIEW school_stint_attribution AS
        SELECT *
        FROM canonical_performance_attribution
        WHERE school_stint_eligible
        """
    )


def scalar(
    con: duckdb.DuckDBPyConnection,
    query: str,
) -> int:
    return int(
        con.execute(query).fetchone()[0]
    )


def build_checks(
    con: duckdb.DuckDBPyConnection,
    evidence_validation: pd.DataFrame,
    source_before: dict[str, int],
    source_after: dict[str, int],
    v1_before: dict[str, int],
    v1_after: dict[str, int],
) -> pd.DataFrame:
    evidence = evidence_validation.iloc[0]

    observed = {
        "source_rows": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM source.core.performances
            """,
        ),
        "output_rows": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            """,
        ),
        "distinct_output_ids": scalar(
            con,
            """
            SELECT COUNT(DISTINCT performance_id)
            FROM canonical_performance_attribution
            """,
        ),
        "duplicate_output_ids": scalar(
            con,
            """
            SELECT COUNT(*) -
                   COUNT(DISTINCT performance_id)
            FROM canonical_performance_attribution
            """,
        ),
        "source_ids_missing_from_output": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM source.core.performances p
            LEFT JOIN
                canonical_performance_attribution a
              ON p.performance_id
                 = a.performance_id
            WHERE a.performance_id IS NULL
            """,
        ),
        "output_ids_missing_from_source": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution a
            LEFT JOIN source.core.performances p
              ON a.performance_id
                 = p.performance_id
            WHERE p.performance_id IS NULL
            """,
        ),
        "blank_analytical_entity_ids": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE NULLIF(
                canonical_analytical_entity_id,
                ''
            ) IS NULL
            """,
        ),
        "unresolved_rows": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE attribution_precedence
                = 'UNRESOLVED'
            """,
        ),
        "fallback_rows": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE attribution_precedence
                = 'RESULT_PAGE_SOURCE_FALLBACK'
            """,
        ),
        "fallback_athletes": scalar(
            con,
            """
            SELECT COUNT(DISTINCT athlete_id)
            FROM canonical_performance_attribution
            WHERE attribution_precedence
                = 'RESULT_PAGE_SOURCE_FALLBACK'
            """,
        ),
        "fallback_teams": scalar(
            con,
            """
            SELECT COUNT(DISTINCT canonical_team_id)
            FROM canonical_performance_attribution
            WHERE attribution_precedence
                = 'RESULT_PAGE_SOURCE_FALLBACK'
            """,
        ),
        "fallback_wrong_team_rows": scalar(
            con,
            f"""
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE attribution_precedence
                = 'RESULT_PAGE_SOURCE_FALLBACK'
              AND canonical_team_id
                != '{EXPECTED_FALLBACK_TEAM_ID}'
            """,
        ),
        "fallback_non_d1_rows": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE attribution_precedence
                = 'RESULT_PAGE_SOURCE_FALLBACK'
              AND (
                    canonical_division != 'D1'
                    OR NOT d1_development_eligible
                    OR NOT school_stint_eligible
                  )
            """,
        ),
        "d1_eligible_without_d1_scope": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE d1_development_eligible
              AND canonical_competition_level
                    != 'NCAA_D1'
            """,
        ),
        "v1_rows_changed_outside_evidence": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution n
            JOIN v1.main
                .canonical_performance_attribution o
              ON n.performance_id
                 = o.performance_id
            LEFT JOIN result_evidence e
              ON n.performance_id
                 = e.performance_id
            WHERE e.performance_id IS NULL
              AND (
                    n.canonical_entity_type
                        IS DISTINCT FROM
                    o.canonical_entity_type
                 OR n.canonical_analytical_entity_id
                        IS DISTINCT FROM
                    o.canonical_analytical_entity_id
                 OR n.canonical_team_id
                        IS DISTINCT FROM
                    o.canonical_team_id
                 OR n.canonical_school_id
                        IS DISTINCT FROM
                    o.canonical_school_id
                 OR n.attribution_precedence
                        IS DISTINCT FROM
                    o.attribution_precedence
                 OR n.attribution_status
                        IS DISTINCT FROM
                    o.attribution_status
                 OR n.attribution_method
                        IS DISTINCT FROM
                    o.attribution_method
                 OR n.attribution_confidence
                        IS DISTINCT FROM
                    o.attribution_confidence
                 OR n.d1_development_eligible
                        IS DISTINCT FROM
                    o.d1_development_eligible
                 OR n.school_stint_eligible
                        IS DISTINCT FROM
                    o.school_stint_eligible
              )
            """,
        ),
    }

    rows: list[tuple[str, int, int, int]] = []

    def exact(
        name: str,
        value: int,
        expected: int,
    ) -> None:
        rows.append(
            (
                name,
                abs(value - expected),
                value,
                expected,
            )
        )

    def zero(
        name: str,
        value: int,
    ) -> None:
        rows.append(
            (
                name,
                value,
                value,
                0,
            )
        )

    exact(
        "source_rows",
        observed["source_rows"],
        EXPECTED_SOURCE_ROWS,
    )
    exact(
        "output_rows",
        observed["output_rows"],
        EXPECTED_SOURCE_ROWS,
    )
    exact(
        "distinct_output_performance_ids",
        observed["distinct_output_ids"],
        EXPECTED_SOURCE_ROWS,
    )
    zero(
        "duplicate_output_performance_ids",
        observed["duplicate_output_ids"],
    )
    zero(
        "source_ids_missing_from_output",
        observed["source_ids_missing_from_output"],
    )
    zero(
        "output_ids_missing_from_source",
        observed["output_ids_missing_from_source"],
    )

    exact(
        "evidence_rows",
        int(evidence["evidence_rows"]),
        EXPECTED_FALLBACK_ROWS,
    )
    exact(
        "distinct_evidence_performance_ids",
        int(evidence["distinct_performance_ids"]),
        EXPECTED_FALLBACK_ROWS,
    )
    exact(
        "evidence_athlete_count",
        int(evidence["athlete_count"]),
        EXPECTED_FALLBACK_ATHLETES,
    )
    exact(
        "evidence_team_count",
        int(evidence["team_count"]),
        EXPECTED_FALLBACK_TEAMS,
    )
    zero(
        "evidence_nonresolved_rows",
        int(evidence["nonresolved_rows"]),
    )
    zero(
        "evidence_current_team_mismatch_rows",
        int(evidence["current_team_mismatch_rows"]),
    )
    zero(
        "evidence_blank_team_id_rows",
        int(evidence["blank_team_id_rows"]),
    )

    exact(
        "result_page_fallback_rows",
        observed["fallback_rows"],
        EXPECTED_FALLBACK_ROWS,
    )
    exact(
        "result_page_fallback_athletes",
        observed["fallback_athletes"],
        EXPECTED_FALLBACK_ATHLETES,
    )
    exact(
        "result_page_fallback_teams",
        observed["fallback_teams"],
        EXPECTED_FALLBACK_TEAMS,
    )
    zero(
        "fallback_wrong_team_rows",
        observed["fallback_wrong_team_rows"],
    )
    zero(
        "fallback_non_d1_rows",
        observed["fallback_non_d1_rows"],
    )

    for precedence, expected in (
        EXPECTED_PRECEDENCE.items()
    ):
        value = scalar(
            con,
            f"""
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE attribution_precedence
                = '{precedence}'
            """,
        )
        exact(
            f"precedence_{precedence.lower()}",
            value,
            expected,
        )

    zero(
        "unresolved_rows",
        observed["unresolved_rows"],
    )
    zero(
        "blank_analytical_entity_ids",
        observed["blank_analytical_entity_ids"],
    )
    zero(
        "d1_eligible_rows_without_d1_scope",
        observed["d1_eligible_without_d1_scope"],
    )
    zero(
        "v1_rows_changed_outside_evidence",
        observed["v1_rows_changed_outside_evidence"],
    )

    exact(
        "source_size_unchanged",
        source_after["size_bytes"],
        source_before["size_bytes"],
    )
    exact(
        "source_modified_time_unchanged",
        source_after["modified_ns"],
        source_before["modified_ns"],
    )
    exact(
        "v1_size_unchanged",
        v1_after["size_bytes"],
        v1_before["size_bytes"],
    )
    exact(
        "v1_modified_time_unchanged",
        v1_after["modified_ns"],
        v1_before["modified_ns"],
    )

    return pd.DataFrame(
        rows,
        columns=[
            "check_name",
            "failed_row_count",
            "observed_value",
            "expected_value",
        ],
    )


def create_metadata(
    con: duckdb.DuckDBPyConnection,
    source_before: dict[str, int],
    source_after: dict[str, int],
    v1_before: dict[str, int],
    v1_after: dict[str, int],
) -> None:
    metadata = pd.DataFrame(
        [
            {
                "metadata_key": "attribution_version",
                "metadata_value": ATTRIBUTION_VERSION,
            },
            {
                "metadata_key": "built_at_utc",
                "metadata_value": datetime.now(
                    timezone.utc
                ).isoformat(),
            },
            {
                "metadata_key": "source_database",
                "metadata_value": str(SOURCE_DB),
            },
            {
                "metadata_key": "v1_database",
                "metadata_value": str(V1_DB),
            },
            {
                "metadata_key": "result_evidence_csv",
                "metadata_value": str(EVIDENCE_CSV),
            },
            {
                "metadata_key": "source_size_before_bytes",
                "metadata_value": str(
                    source_before["size_bytes"]
                ),
            },
            {
                "metadata_key": "source_size_after_bytes",
                "metadata_value": str(
                    source_after["size_bytes"]
                ),
            },
            {
                "metadata_key": "v1_size_before_bytes",
                "metadata_value": str(
                    v1_before["size_bytes"]
                ),
            },
            {
                "metadata_key": "v1_size_after_bytes",
                "metadata_value": str(
                    v1_after["size_bytes"]
                ),
            },
        ]
    )

    con.register(
        "metadata_df",
        metadata,
    )
    con.execute(
        """
        CREATE TABLE audit_metadata AS
        SELECT *
        FROM metadata_df
        """
    )
    con.unregister(
        "metadata_df"
    )


def write_outputs(
    con: duckdb.DuckDBPyConnection,
    checks: pd.DataFrame,
) -> None:
    precedence = con.execute(
        """
        SELECT *
        FROM attribution_precedence_summary
        """
    ).fetchdf()

    competition = con.execute(
        """
        SELECT *
        FROM competition_scope_summary
        """
    ).fetchdf()

    confidence = con.execute(
        """
        SELECT *
        FROM confidence_summary
        """
    ).fetchdf()

    fallback = con.execute(
        """
        SELECT *
        FROM result_page_fallback_summary
        """
    ).fetchdf()

    checks.to_csv(
        OUTPUT_DIR / "hard_checks.csv",
        index=False,
    )
    precedence.to_csv(
        OUTPUT_DIR
        / "attribution_precedence_summary.csv",
        index=False,
    )
    competition.to_csv(
        OUTPUT_DIR
        / "competition_scope_summary.csv",
        index=False,
    )
    confidence.to_csv(
        OUTPUT_DIR / "confidence_summary.csv",
        index=False,
    )
    fallback.to_csv(
        OUTPUT_DIR
        / "result_page_fallback_summary.csv",
        index=False,
    )

    con.register(
        "hard_checks_df",
        checks,
    )
    con.execute(
        """
        CREATE TABLE hard_checks AS
        SELECT *
        FROM hard_checks_df
        """
    )
    con.unregister(
        "hard_checks_df"
    )

    failed = int(
        (
            checks["failed_row_count"] > 0
        ).sum()
    )

    counts = {
        row.attribution_precedence: int(
            row.performance_rows
        )
        for row in precedence.itertuples(
            index=False
        )
    }

    d1_rows = scalar(
        con,
        """
        SELECT COUNT(*)
        FROM canonical_performance_attribution
        WHERE d1_development_eligible
        """,
    )

    stint_rows = scalar(
        con,
        """
        SELECT COUNT(*)
        FROM canonical_performance_attribution
        WHERE school_stint_eligible
        """,
    )

    report = f"""MILESTONE 4 CANONICAL PERFORMANCE ATTRIBUTION V1.1
============================================================
Attribution version: {ATTRIBUTION_VERSION}
Source database modified: no
Version 1.0 database modified: no

SCOPE
- Canonical attribution rows: {EXPECTED_SOURCE_ROWS:,}
- D1-development-eligible rows: {d1_rows:,}
- School-stint-eligible rows: {stint_rows:,}

ATTRIBUTION PRECEDENCE
- Performance-level overrides:
  {counts.get('PERFORMANCE_LEVEL_OVERRIDE', 0):,}
- Canonical profile sections:
  {counts.get('CANONICAL_PROFILE_SECTION', 0):,}
- Transfer final teams:
  {counts.get('TRANSFER_FINAL_TEAM', 0):,}
- Transfer non-D1 scope:
  {counts.get('TRANSFER_NON_D1_SCOPE', 0):,}
- Result-page source fallbacks:
  {counts.get('RESULT_PAGE_SOURCE_FALLBACK', 0):,}
- Original source teams:
  {counts.get('ORIGINAL_SOURCE_TEAM', 0):,}
- Unresolved:
  {counts.get('UNRESOLVED', 0):,}

TARGETED V1.1 CORRECTION
- Corrected performances: {EXPECTED_FALLBACK_ROWS:,}
- Corrected athletes: {EXPECTED_FALLBACK_ATHLETES:,}
- Corrected team: {EXPECTED_FALLBACK_TEAM_ID}
- Evidence method: exact athlete row on result page
- Current-team field used only as corroboration

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

INTERPRETATION
Version 1.1 differs from version 1.0 only for the 18 audited Emma Jankowski
performances. All 18 result pages independently identify Dayton. No general
current-team fallback was introduced.
"""

    (
        OUTPUT_DIR
        / "attribution_report.txt"
    ).write_text(
        report,
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()

    require_inputs()
    prepare_output(
        replace_output=args.replace_output,
    )

    source_before = file_state(SOURCE_DB)
    v1_before = file_state(V1_DB)

    con = duckdb.connect(
        str(OUTPUT_DB)
    )

    try:
        con.execute("PRAGMA threads=4")
        con.execute(
            "PRAGMA preserve_insertion_order=false"
        )

        attach_inputs(con)

        evidence_validation = (
            validate_evidence(con)
        )

        build_v1_1_table(con)
        create_summary_tables(con)

        source_after = file_state(SOURCE_DB)
        v1_after = file_state(V1_DB)

        checks = build_checks(
            con=con,
            evidence_validation=(
                evidence_validation
            ),
            source_before=source_before,
            source_after=source_after,
            v1_before=v1_before,
            v1_after=v1_after,
        )

        create_metadata(
            con=con,
            source_before=source_before,
            source_after=source_after,
            v1_before=v1_before,
            v1_after=v1_after,
        )

        write_outputs(
            con=con,
            checks=checks,
        )

        con.execute("CHECKPOINT")

        failed = int(
            (
                checks["failed_row_count"] > 0
            ).sum()
        )

        print(
            "Canonical performance attribution "
            "v1.1 build complete."
        )
        print(f"Database: {OUTPUT_DB}")
        print(f"Failed checks: {failed:,}.")

        if failed:
            raise SystemExit(1)

    finally:
        con.close()

    size_gib = os.path.getsize(
        OUTPUT_DB
    ) / (1024 ** 3)

    print(
        "Output database size: "
        f"{size_gib:.2f} GiB"
    )


if __name__ == "__main__":
    main()
