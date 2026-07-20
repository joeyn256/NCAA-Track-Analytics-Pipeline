#!/usr/bin/env python3
"""
Milestone 4: build the canonical performance-attribution staging database.

This script creates a separate, compact DuckDB database containing one
attribution row for every source performance. It does not duplicate the full
performance fact table and never modifies the Milestone 3 source database.

Attribution precedence
----------------------
1. Performance-level override
2. Canonical profile-section registry
3. Transfer final team attribution
4. Transfer non-D1 scope classification
5. Original source team
6. Explicit unresolved status

Outputs
-------
data/processed/milestone4/canonical_performance_attribution/
    canonical_performance_attribution.duckdb
    attribution_report.txt
    hard_checks.csv
    attribution_precedence_summary.csv
    competition_scope_summary.csv
    confidence_summary.csv
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

COVERAGE_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "multi_section_attribution_coverage/"
    / "multi_section_attribution_coverage.duckdb"
)

REGISTRY_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_section_registry/"
    / "canonical_profile_section_registry.csv"
)

OVERRIDE_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_section_registry/"
    / "canonical_performance_team_overrides.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_performance_attribution"
)

OUTPUT_DB = (
    OUTPUT_DIR
    / "canonical_performance_attribution.duckdb"
)

ATTRIBUTION_VERSION = (
    "m4_canonical_performance_attribution_v1.0"
)

EXPECTED_SOURCE_ROWS = 6_594_540
EXPECTED_COVERAGE_ROWS = 591_008
EXPECTED_OVERRIDE_ROWS = 120
EXPECTED_SECTION_ROWS = 426_375
EXPECTED_TRANSFER_TEAM_ROWS = 160_935
EXPECTED_TRANSFER_NON_D1_ROWS = 3_578
EXPECTED_ORIGINAL_SOURCE_ROWS = 6_003_532


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--replace-output",
        action="store_true",
        help=(
            "Replace an existing staging database "
            "and report files."
        ),
    )

    return parser.parse_args()


def require_inputs() -> None:
    for path in [
        SOURCE_DB,
        COVERAGE_DB,
        REGISTRY_CSV,
        OVERRIDE_CSV,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )


def sql_path(path: Path) -> str:
    return (
        path.resolve()
        .as_posix()
        .replace("'", "''")
    )


def prepare_output(
    replace_output: bool,
) -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    existing_files = [
        OUTPUT_DB,
        OUTPUT_DIR / "attribution_report.txt",
        OUTPUT_DIR / "hard_checks.csv",
        OUTPUT_DIR
        / "attribution_precedence_summary.csv",
        OUTPUT_DIR
        / "competition_scope_summary.csv",
        OUTPUT_DIR / "confidence_summary.csv",
    ]

    existing = [
        path
        for path in existing_files
        if path.exists()
    ]

    if existing and not replace_output:
        raise FileExistsError(
            "Existing canonical-attribution outputs "
            "were found. Use --replace-output only "
            "after reviewing them."
        )

    if replace_output:
        for path in existing:
            path.unlink()


def source_file_state() -> dict[str, int]:
    stat = SOURCE_DB.stat()

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
        ATTACH '{sql_path(COVERAGE_DB)}'
        AS coverage
        (READ_ONLY)
        """
    )

    con.execute(
        f"""
        CREATE TEMP VIEW registry AS
        SELECT *
        FROM read_csv_auto(
            '{sql_path(REGISTRY_CSV)}',
            HEADER = TRUE,
            ALL_VARCHAR = TRUE
        )
        """
    )

    con.execute(
        f"""
        CREATE TEMP VIEW overrides AS
        SELECT *
        FROM read_csv_auto(
            '{sql_path(OVERRIDE_CSV)}',
            HEADER = TRUE,
            ALL_VARCHAR = TRUE
        )
        """
    )


def create_attribution_table(
    con: duckdb.DuckDBPyConnection,
) -> None:
    print(
        "Building canonical attribution table "
        "for all source performances..."
    )

    con.execute(
        """
        CREATE TABLE canonical_performance_attribution AS

        WITH joined AS (
            SELECT
                p.performance_id,
                p.athlete_id,
                p.affiliation_id,
                p.season_year,
                p.season_type,

                p.team_id
                    AS original_team_id,

                COALESCE(
                    original_team.school_id,
                    ''
                ) AS original_school_id,

                COALESCE(
                    original_school.school_name,
                    p.school,
                    original_team.team_name,
                    ''
                ) AS original_school_name,

                COALESCE(
                    original_team.team_name,
                    p.school,
                    ''
                ) AS original_team_name,

                COALESCE(
                    original_team.gender_code,
                    c.gender_code,
                    ''
                ) AS original_gender_code,

                COALESCE(
                    original_team.division,
                    ''
                ) AS original_division,

                c.coverage_status,
                c.matched_section_index,
                c.matched_profile_section_id,
                c.matched_source_section_name,

                c.transfer_final_team_id,
                c.transfer_final_school_id,
                c.transfer_final_school_name,
                c.transfer_final_attribution_status,
                c.transfer_career_stage,
                c.transfer_governing_system,
                c.transfer_competition_level,
                c.transfer_d1_development_eligible,
                c.transfer_school_stint_eligible,
                c.coverage_audit_version,

                r.profile_section_id
                    AS registry_profile_section_id,

                r.canonical_entity_type
                    AS registry_entity_type,

                r.canonical_analytical_entity_id
                    AS registry_analytical_entity_id,

                r.canonical_team_id
                    AS registry_team_id,

                r.canonical_school_id
                    AS registry_school_id,

                r.canonical_entity_name
                    AS registry_entity_name,

                r.canonical_team_name
                    AS registry_team_name,

                r.canonical_team_url
                    AS registry_team_url,

                r.canonical_gender_code
                    AS registry_gender_code,

                r.canonical_division
                    AS registry_division,

                r.canonical_resolution_status
                    AS registry_resolution_status,

                r.canonical_resolution_method
                    AS registry_resolution_method,

                r.canonical_resolution_confidence
                    AS registry_resolution_confidence,

                r.requires_performance_override
                    AS registry_requires_override,

                r.evidence_source
                    AS registry_evidence_source,

                o.performance_id
                    AS override_performance_id,

                o.canonical_entity_type
                    AS override_entity_type,

                o.canonical_analytical_entity_id
                    AS override_analytical_entity_id,

                o.canonical_team_id
                    AS override_team_id,

                o.canonical_school_id
                    AS override_school_id,

                o.canonical_team_name
                    AS override_team_name,

                o.canonical_team_url
                    AS override_team_url,

                o.gender_code
                    AS override_gender_code,

                o.resolution_status
                    AS override_resolution_status,

                o.resolution_method
                    AS override_resolution_method,

                o.resolution_confidence
                    AS override_resolution_confidence,

                o.evidence_source
                    AS override_evidence_source,

                override_team.school_id
                    AS override_joined_school_id,

                override_team.team_name
                    AS override_joined_team_name,

                override_team.gender_code
                    AS override_joined_gender_code,

                override_team.division
                    AS override_joined_division,

                override_team.team_url
                    AS override_joined_team_url,

                override_school.school_name
                    AS override_joined_school_name,

                registry_team.school_id
                    AS registry_joined_school_id,

                registry_team.team_name
                    AS registry_joined_team_name,

                registry_team.gender_code
                    AS registry_joined_gender_code,

                registry_team.division
                    AS registry_joined_division,

                registry_team.team_url
                    AS registry_joined_team_url,

                registry_school.school_name
                    AS registry_joined_school_name,

                transfer_team.school_id
                    AS transfer_joined_school_id,

                transfer_team.team_name
                    AS transfer_joined_team_name,

                transfer_team.gender_code
                    AS transfer_joined_gender_code,

                transfer_team.division
                    AS transfer_joined_division,

                transfer_team.team_url
                    AS transfer_joined_team_url,

                transfer_school.school_name
                    AS transfer_joined_school_name,

                original_team.team_url
                    AS original_team_url

            FROM source.core.performances p

            LEFT JOIN coverage.main
                .multi_section_performance_coverage c
              ON p.performance_id
                 = c.performance_id

            LEFT JOIN registry r
              ON CAST(c.athlete_id AS VARCHAR)
                 = r.athlete_id
             AND CAST(
                     c.matched_section_index
                     AS VARCHAR
                 ) = r.section_index

            LEFT JOIN overrides o
              ON p.performance_id
                 = o.performance_id

            LEFT JOIN source.core.teams
                original_team
              ON p.team_id
                 = original_team.team_id

            LEFT JOIN source.core.schools
                original_school
              ON original_team.school_id
                 = original_school.school_id

            LEFT JOIN source.core.teams
                override_team
              ON NULLIF(
                    o.canonical_team_id,
                    ''
                 ) = override_team.team_id

            LEFT JOIN source.core.schools
                override_school
              ON COALESCE(
                    NULLIF(
                        o.canonical_school_id,
                        ''
                    ),
                    override_team.school_id
                 ) = override_school.school_id

            LEFT JOIN source.core.teams
                registry_team
              ON NULLIF(
                    r.canonical_team_id,
                    ''
                 ) = registry_team.team_id

            LEFT JOIN source.core.schools
                registry_school
              ON COALESCE(
                    NULLIF(
                        r.canonical_school_id,
                        ''
                    ),
                    registry_team.school_id
                 ) = registry_school.school_id

            LEFT JOIN source.core.teams
                transfer_team
              ON NULLIF(
                    c.transfer_final_team_id,
                    ''
                 ) = transfer_team.team_id

            LEFT JOIN source.core.schools
                transfer_school
              ON COALESCE(
                    NULLIF(
                        c.transfer_final_school_id,
                        ''
                    ),
                    transfer_team.school_id
                 ) = transfer_school.school_id
        ),

        resolved AS (
            SELECT
                performance_id,
                athlete_id,
                affiliation_id,
                season_year,
                season_type,

                original_team_id,
                original_school_id,
                original_school_name,
                original_team_name,

                coverage_status,
                matched_section_index,
                matched_profile_section_id,
                matched_source_section_name,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        'PERFORMANCE_LEVEL_OVERRIDE'

                    WHEN registry_profile_section_id
                        IS NOT NULL
                    THEN
                        'CANONICAL_PROFILE_SECTION'

                    WHEN NULLIF(
                        transfer_final_team_id,
                        ''
                    ) IS NOT NULL
                    THEN
                        'TRANSFER_FINAL_TEAM'

                    WHEN transfer_final_attribution_status
                        = 'NON_D1_SCOPE_CORRECTION'
                    THEN
                        'TRANSFER_NON_D1_SCOPE'

                    WHEN coverage_status IS NULL
                         AND (
                            NULLIF(
                                original_team_id,
                                ''
                            ) IS NOT NULL
                            OR NULLIF(
                                original_school_name,
                                ''
                            ) IS NOT NULL
                         )
                    THEN
                        'ORIGINAL_SOURCE_TEAM'

                    ELSE
                        'UNRESOLVED'
                END AS attribution_precedence,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                override_entity_type,
                                ''
                            ),
                            'external_team'
                        )

                    WHEN registry_profile_section_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                registry_entity_type,
                                ''
                            ),
                            'profile_section_entity'
                        )

                    WHEN NULLIF(
                        transfer_final_team_id,
                        ''
                    ) IS NOT NULL
                    THEN
                        'school_team'

                    WHEN transfer_final_attribution_status
                        = 'NON_D1_SCOPE_CORRECTION'
                    THEN
                        CASE
                            WHEN transfer_career_stage
                                = 'PRE_COLLEGIATE'
                            THEN
                                'high_school_profile_section'
                            ELSE
                                'non_d1_college_profile_section'
                        END

                    WHEN coverage_status IS NULL
                    THEN
                        'school_team'

                    ELSE
                        'unresolved_entity'
                END AS canonical_entity_type,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                override_analytical_entity_id,
                                ''
                            ),
                            NULLIF(
                                override_school_id,
                                ''
                            ),
                            NULLIF(
                                override_joined_school_id,
                                ''
                            ),
                            NULLIF(
                                override_team_id,
                                ''
                            ),
                            'override_performance:'
                                || performance_id
                        )

                    WHEN registry_profile_section_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                registry_analytical_entity_id,
                                ''
                            ),
                            NULLIF(
                                registry_school_id,
                                ''
                            ),
                            NULLIF(
                                registry_joined_school_id,
                                ''
                            ),
                            NULLIF(
                                registry_team_id,
                                ''
                            ),
                            'profile_section:'
                                || registry_profile_section_id
                        )

                    WHEN NULLIF(
                        transfer_final_team_id,
                        ''
                    ) IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                transfer_final_school_id,
                                ''
                            ),
                            NULLIF(
                                transfer_joined_school_id,
                                ''
                            ),
                            transfer_final_team_id
                        )

                    WHEN transfer_final_attribution_status
                        = 'NON_D1_SCOPE_CORRECTION'
                    THEN
                        COALESCE(
                            'profile_section:'
                                || NULLIF(
                                    matched_profile_section_id,
                                    ''
                                ),
                            'non_d1_name:'
                                || regexp_replace(
                                    lower(
                                        COALESCE(
                                            matched_source_section_name,
                                            ''
                                        )
                                    ),
                                    '[^a-z0-9]+',
                                    '',
                                    'g'
                                )
                        )

                    WHEN coverage_status IS NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                original_school_id,
                                ''
                            ),
                            NULLIF(
                                original_team_id,
                                ''
                            ),
                            'source_name:'
                                || regexp_replace(
                                    lower(
                                        COALESCE(
                                            original_school_name,
                                            ''
                                        )
                                    ),
                                    '[^a-z0-9]+',
                                    '',
                                    'g'
                                )
                        )

                    ELSE
                        ''
                END AS canonical_analytical_entity_id,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        NULLIF(
                            override_team_id,
                            ''
                        )

                    WHEN registry_profile_section_id
                        IS NOT NULL
                    THEN
                        NULLIF(
                            registry_team_id,
                            ''
                        )

                    WHEN NULLIF(
                        transfer_final_team_id,
                        ''
                    ) IS NOT NULL
                    THEN
                        transfer_final_team_id

                    WHEN transfer_final_attribution_status
                        = 'NON_D1_SCOPE_CORRECTION'
                    THEN
                        NULL

                    WHEN coverage_status IS NULL
                    THEN
                        NULLIF(
                            original_team_id,
                            ''
                        )

                    ELSE
                        NULL
                END AS canonical_team_id,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                override_school_id,
                                ''
                            ),
                            NULLIF(
                                override_joined_school_id,
                                ''
                            )
                        )

                    WHEN registry_profile_section_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                registry_school_id,
                                ''
                            ),
                            NULLIF(
                                registry_joined_school_id,
                                ''
                            )
                        )

                    WHEN NULLIF(
                        transfer_final_team_id,
                        ''
                    ) IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                transfer_final_school_id,
                                ''
                            ),
                            NULLIF(
                                transfer_joined_school_id,
                                ''
                            )
                        )

                    WHEN transfer_final_attribution_status
                        = 'NON_D1_SCOPE_CORRECTION'
                    THEN
                        NULL

                    WHEN coverage_status IS NULL
                    THEN
                        NULLIF(
                            original_school_id,
                            ''
                        )

                    ELSE
                        NULL
                END AS canonical_school_id,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                override_joined_school_name,
                                ''
                            ),
                            NULLIF(
                                override_team_name,
                                ''
                            ),
                            NULLIF(
                                override_joined_team_name,
                                ''
                            )
                        )

                    WHEN registry_profile_section_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                registry_entity_name,
                                ''
                            ),
                            NULLIF(
                                registry_joined_school_name,
                                ''
                            ),
                            NULLIF(
                                registry_team_name,
                                ''
                            ),
                            matched_source_section_name
                        )

                    WHEN NULLIF(
                        transfer_final_team_id,
                        ''
                    ) IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                transfer_final_school_name,
                                ''
                            ),
                            NULLIF(
                                transfer_joined_school_name,
                                ''
                            ),
                            NULLIF(
                                transfer_joined_team_name,
                                ''
                            )
                        )

                    WHEN transfer_final_attribution_status
                        = 'NON_D1_SCOPE_CORRECTION'
                    THEN
                        matched_source_section_name

                    WHEN coverage_status IS NULL
                    THEN
                        original_school_name

                    ELSE
                        ''
                END AS canonical_school_name,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                override_team_name,
                                ''
                            ),
                            NULLIF(
                                override_joined_team_name,
                                ''
                            )
                        )

                    WHEN registry_profile_section_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                registry_team_name,
                                ''
                            ),
                            NULLIF(
                                registry_joined_team_name,
                                ''
                            ),
                            NULLIF(
                                registry_entity_name,
                                ''
                            )
                        )

                    WHEN NULLIF(
                        transfer_final_team_id,
                        ''
                    ) IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                transfer_joined_team_name,
                                ''
                            ),
                            NULLIF(
                                transfer_final_school_name,
                                ''
                            )
                        )

                    WHEN transfer_final_attribution_status
                        = 'NON_D1_SCOPE_CORRECTION'
                    THEN
                        matched_source_section_name

                    WHEN coverage_status IS NULL
                    THEN
                        original_team_name

                    ELSE
                        ''
                END AS canonical_team_name,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                override_team_url,
                                ''
                            ),
                            NULLIF(
                                override_joined_team_url,
                                ''
                            )
                        )

                    WHEN registry_profile_section_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                registry_team_url,
                                ''
                            ),
                            NULLIF(
                                registry_joined_team_url,
                                ''
                            )
                        )

                    WHEN NULLIF(
                        transfer_final_team_id,
                        ''
                    ) IS NOT NULL
                    THEN
                        NULLIF(
                            transfer_joined_team_url,
                            ''
                        )

                    WHEN coverage_status IS NULL
                    THEN
                        NULLIF(
                            original_team_url,
                            ''
                        )

                    ELSE
                        NULL
                END AS canonical_team_url,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                override_gender_code,
                                ''
                            ),
                            NULLIF(
                                override_joined_gender_code,
                                ''
                            ),
                            original_gender_code
                        )

                    WHEN registry_profile_section_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                registry_gender_code,
                                ''
                            ),
                            NULLIF(
                                registry_joined_gender_code,
                                ''
                            ),
                            original_gender_code
                        )

                    WHEN NULLIF(
                        transfer_final_team_id,
                        ''
                    ) IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                transfer_joined_gender_code,
                                ''
                            ),
                            original_gender_code
                        )

                    ELSE
                        original_gender_code
                END AS canonical_gender_code,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                override_joined_division,
                                ''
                            ),
                            ''
                        )

                    WHEN registry_profile_section_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                registry_division,
                                ''
                            ),
                            NULLIF(
                                registry_joined_division,
                                ''
                            ),
                            ''
                        )

                    WHEN NULLIF(
                        transfer_final_team_id,
                        ''
                    ) IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                transfer_joined_division,
                                ''
                            ),
                            NULLIF(
                                transfer_competition_level,
                                ''
                            ),
                            ''
                        )

                    WHEN transfer_final_attribution_status
                        = 'NON_D1_SCOPE_CORRECTION'
                    THEN
                        COALESCE(
                            transfer_competition_level,
                            ''
                        )

                    WHEN coverage_status IS NULL
                    THEN
                        original_division

                    ELSE
                        ''
                END AS canonical_division,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        override_resolution_status

                    WHEN registry_profile_section_id
                        IS NOT NULL
                    THEN
                        registry_resolution_status

                    WHEN NULLIF(
                        transfer_final_team_id,
                        ''
                    ) IS NOT NULL
                    THEN
                        transfer_final_attribution_status

                    WHEN transfer_final_attribution_status
                        = 'NON_D1_SCOPE_CORRECTION'
                    THEN
                        transfer_final_attribution_status

                    WHEN coverage_status IS NULL
                    THEN
                        'ORIGINAL_SOURCE_TEAM'

                    ELSE
                        'UNRESOLVED_ATTRIBUTION'
                END AS attribution_status,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        override_resolution_method

                    WHEN registry_profile_section_id
                        IS NOT NULL
                    THEN
                        registry_resolution_method

                    WHEN NULLIF(
                        transfer_final_team_id,
                        ''
                    ) IS NOT NULL
                    THEN
                        'TRANSFER_FINAL_ATTRIBUTION'

                    WHEN transfer_final_attribution_status
                        = 'NON_D1_SCOPE_CORRECTION'
                    THEN
                        'TRANSFER_SCOPE_CLASSIFICATION'

                    WHEN coverage_status IS NULL
                    THEN
                        'SOURCE_TEAM_ID'

                    ELSE
                        'UNRESOLVED'
                END AS attribution_method,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                override_resolution_confidence,
                                ''
                            ),
                            'HIGH'
                        )

                    WHEN registry_profile_section_id
                        IS NOT NULL
                    THEN
                        COALESCE(
                            NULLIF(
                                registry_resolution_confidence,
                                ''
                            ),
                            'HIGH'
                        )

                    WHEN NULLIF(
                        transfer_final_team_id,
                        ''
                    ) IS NOT NULL
                    THEN
                        'HIGH'

                    WHEN transfer_final_attribution_status
                        = 'NON_D1_SCOPE_CORRECTION'
                    THEN
                        'HIGH'

                    WHEN coverage_status IS NULL
                    THEN
                        'HIGH'

                    ELSE
                        'UNRESOLVED'
                END AS attribution_confidence,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        TRUE

                    WHEN lower(
                        COALESCE(
                            registry_requires_override,
                            'false'
                        )
                    ) = 'true'
                    THEN
                        TRUE

                    ELSE
                        FALSE
                END AS requires_performance_override,

                CASE
                    WHEN override_performance_id
                        IS NOT NULL
                    THEN
                        override_evidence_source

                    WHEN registry_profile_section_id
                        IS NOT NULL
                    THEN
                        registry_evidence_source

                    WHEN coverage_status IS NOT NULL
                    THEN
                        coverage_audit_version

                    ELSE
                        'source.core.performances'
                END AS evidence_source,

                transfer_career_stage,
                transfer_governing_system,
                transfer_competition_level,
                transfer_d1_development_eligible,
                transfer_school_stint_eligible

            FROM joined
        ),

        classified AS (
            SELECT
                *,

                CASE
                    WHEN attribution_precedence
                        IN (
                            'TRANSFER_FINAL_TEAM',
                            'TRANSFER_NON_D1_SCOPE'
                        )
                    THEN
                        COALESCE(
                            NULLIF(
                                transfer_career_stage,
                                ''
                            ),
                            'UNKNOWN'
                        )

                    WHEN canonical_division
                        IN (
                            'D1',
                            'D2',
                            'D3',
                            'NCAA_D1',
                            'NCAA_D2',
                            'NCAA_D3',
                            'NAIA',
                            'NJCAA'
                        )
                    THEN
                        'COLLEGIATE'

                    WHEN canonical_entity_type
                        = 'high_school_profile_section'
                    THEN
                        'PRE_COLLEGIATE'

                    WHEN canonical_entity_type
                        IN (
                            'external_team',
                            'non_d1_college_profile_section'
                        )
                    THEN
                        'NON_D1_OR_UNKNOWN'

                    ELSE
                        'COLLEGIATE_OR_UNKNOWN'
                END AS canonical_career_stage,

                CASE
                    WHEN attribution_precedence
                        IN (
                            'TRANSFER_FINAL_TEAM',
                            'TRANSFER_NON_D1_SCOPE'
                        )
                    THEN
                        COALESCE(
                            NULLIF(
                                transfer_governing_system,
                                ''
                            ),
                            'UNKNOWN'
                        )

                    WHEN canonical_division
                        IN (
                            'D1',
                            'D2',
                            'D3',
                            'NCAA_D1',
                            'NCAA_D2',
                            'NCAA_D3'
                        )
                    THEN
                        'NCAA'

                    WHEN canonical_division
                        = 'NAIA'
                    THEN
                        'NAIA'

                    WHEN canonical_team_id
                        LIKE '%_jcollege_%'
                    THEN
                        'JUNIOR_COLLEGE'

                    ELSE
                        'UNKNOWN_OR_OTHER'
                END AS canonical_governing_system,

                CASE
                    WHEN attribution_precedence
                        IN (
                            'TRANSFER_FINAL_TEAM',
                            'TRANSFER_NON_D1_SCOPE'
                        )
                    THEN
                        COALESCE(
                            NULLIF(
                                transfer_competition_level,
                                ''
                            ),
                            'UNKNOWN'
                        )

                    WHEN canonical_division
                        IN (
                            'D1',
                            'NCAA_D1'
                        )
                    THEN
                        'NCAA_D1'

                    WHEN canonical_division
                        IN (
                            'D2',
                            'NCAA_D2'
                        )
                    THEN
                        'NCAA_D2'

                    WHEN canonical_division
                        IN (
                            'D3',
                            'NCAA_D3'
                        )
                    THEN
                        'NCAA_D3'

                    WHEN canonical_division
                        = 'NAIA'
                    THEN
                        'NAIA'

                    WHEN canonical_team_id
                        LIKE '%_jcollege_%'
                    THEN
                        'JUNIOR_COLLEGE'

                    WHEN canonical_entity_type
                        = 'high_school_profile_section'
                    THEN
                        'HIGH_SCHOOL'

                    ELSE
                        'NON_D1_OR_UNKNOWN'
                END AS canonical_competition_level,

                CASE
                    WHEN attribution_precedence
                        IN (
                            'TRANSFER_FINAL_TEAM',
                            'TRANSFER_NON_D1_SCOPE'
                        )
                    THEN
                        lower(
                            COALESCE(
                                transfer_d1_development_eligible,
                                'false'
                            )
                        ) = 'true'

                    ELSE
                        canonical_division
                            IN (
                                'D1',
                                'NCAA_D1'
                            )
                END AS d1_development_eligible,

                CASE
                    WHEN attribution_precedence
                        IN (
                            'TRANSFER_FINAL_TEAM',
                            'TRANSFER_NON_D1_SCOPE'
                        )
                    THEN
                        lower(
                            COALESCE(
                                transfer_school_stint_eligible,
                                'false'
                            )
                        ) = 'true'

                    ELSE
                        canonical_division
                            IN (
                                'D1',
                                'NCAA_D1'
                            )
                END AS school_stint_eligible

            FROM resolved
        )

        SELECT
            performance_id,
            athlete_id,
            affiliation_id,
            season_year,
            season_type,

            original_team_id,
            original_school_id,
            original_school_name,
            original_team_name,

            matched_section_index,
            matched_profile_section_id,
            matched_source_section_name,
            coverage_status,

            canonical_entity_type,
            canonical_analytical_entity_id,
            canonical_team_id,
            canonical_school_id,
            canonical_school_name,
            canonical_team_name,
            canonical_team_url,
            canonical_gender_code,
            canonical_division,

            canonical_career_stage,
            canonical_governing_system,
            canonical_competition_level,
            d1_development_eligible,
            school_stint_eligible,

            attribution_precedence,
            attribution_status,
            attribution_method,
            attribution_confidence,
            requires_performance_override,
            evidence_source,

            '"""
        + ATTRIBUTION_VERSION
        + """' AS attribution_version

        FROM classified
        """
    )


def create_summary_tables(
    con: duckdb.DuckDBPyConnection,
) -> None:
    con.execute(
        """
        CREATE TABLE attribution_precedence_summary AS
        SELECT
            attribution_precedence,
            COUNT(*) AS performance_rows,
            COUNT(
                DISTINCT athlete_id
            ) AS athlete_count,
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
            COUNT(
                DISTINCT athlete_id
            ) AS athlete_count
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
            COUNT(
                DISTINCT athlete_id
            ) AS athlete_count
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
) -> pd.DataFrame:
    observed = {
        "source_rows": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM source.core.performances
            """,
        ),
        "distinct_source_performance_ids": scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT performance_id
            )
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
        "distinct_output_performance_ids": scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT performance_id
            )
            FROM canonical_performance_attribution
            """,
        ),
        "duplicate_output_performance_ids": scalar(
            con,
            """
            SELECT
                COUNT(*) - COUNT(
                    DISTINCT performance_id
                )
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
        "coverage_rows": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM coverage.main
                .multi_section_performance_coverage
            """,
        ),
        "coverage_ids_missing_from_output": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM coverage.main
                .multi_section_performance_coverage c
            LEFT JOIN
                canonical_performance_attribution a
              ON c.performance_id
                 = a.performance_id
            WHERE a.performance_id IS NULL
            """,
        ),
        "performance_override_rows": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE attribution_precedence
                = 'PERFORMANCE_LEVEL_OVERRIDE'
            """,
        ),
        "canonical_section_rows": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE attribution_precedence
                = 'CANONICAL_PROFILE_SECTION'
            """,
        ),
        "transfer_final_team_rows": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE attribution_precedence
                = 'TRANSFER_FINAL_TEAM'
            """,
        ),
        "transfer_non_d1_rows": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE attribution_precedence
                = 'TRANSFER_NON_D1_SCOPE'
            """,
        ),
        "original_source_rows": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE attribution_precedence
                = 'ORIGINAL_SOURCE_TEAM'
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
        "override_rows_without_override_flag": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE attribution_precedence
                    = 'PERFORMANCE_LEVEL_OVERRIDE'
              AND NOT requires_performance_override
            """,
        ),
        "nonoverride_rows_with_override_flag": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE attribution_precedence
                    != 'PERFORMANCE_LEVEL_OVERRIDE'
              AND requires_performance_override
            """,
        ),
        "d1_eligible_rows_without_d1_scope": scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_performance_attribution
            WHERE d1_development_eligible
              AND canonical_competition_level
                    != 'NCAA_D1'
            """,
        ),
    }

    checks = [
        (
            "source_rows",
            abs(
                observed["source_rows"]
                - EXPECTED_SOURCE_ROWS
            ),
            observed["source_rows"],
            EXPECTED_SOURCE_ROWS,
        ),
        (
            "distinct_source_performance_ids",
            abs(
                observed[
                    "distinct_source_performance_ids"
                ]
                - EXPECTED_SOURCE_ROWS
            ),
            observed[
                "distinct_source_performance_ids"
            ],
            EXPECTED_SOURCE_ROWS,
        ),
        (
            "output_rows",
            abs(
                observed["output_rows"]
                - EXPECTED_SOURCE_ROWS
            ),
            observed["output_rows"],
            EXPECTED_SOURCE_ROWS,
        ),
        (
            "distinct_output_performance_ids",
            abs(
                observed[
                    "distinct_output_performance_ids"
                ]
                - EXPECTED_SOURCE_ROWS
            ),
            observed[
                "distinct_output_performance_ids"
            ],
            EXPECTED_SOURCE_ROWS,
        ),
        (
            "duplicate_output_performance_ids",
            observed[
                "duplicate_output_performance_ids"
            ],
            observed[
                "duplicate_output_performance_ids"
            ],
            0,
        ),
        (
            "source_ids_missing_from_output",
            observed[
                "source_ids_missing_from_output"
            ],
            observed[
                "source_ids_missing_from_output"
            ],
            0,
        ),
        (
            "output_ids_missing_from_source",
            observed[
                "output_ids_missing_from_source"
            ],
            observed[
                "output_ids_missing_from_source"
            ],
            0,
        ),
        (
            "coverage_rows",
            abs(
                observed["coverage_rows"]
                - EXPECTED_COVERAGE_ROWS
            ),
            observed["coverage_rows"],
            EXPECTED_COVERAGE_ROWS,
        ),
        (
            "coverage_ids_missing_from_output",
            observed[
                "coverage_ids_missing_from_output"
            ],
            observed[
                "coverage_ids_missing_from_output"
            ],
            0,
        ),
        (
            "performance_override_rows",
            abs(
                observed[
                    "performance_override_rows"
                ]
                - EXPECTED_OVERRIDE_ROWS
            ),
            observed[
                "performance_override_rows"
            ],
            EXPECTED_OVERRIDE_ROWS,
        ),
        (
            "canonical_section_rows",
            abs(
                observed[
                    "canonical_section_rows"
                ]
                - EXPECTED_SECTION_ROWS
            ),
            observed[
                "canonical_section_rows"
            ],
            EXPECTED_SECTION_ROWS,
        ),
        (
            "transfer_final_team_rows",
            abs(
                observed[
                    "transfer_final_team_rows"
                ]
                - EXPECTED_TRANSFER_TEAM_ROWS
            ),
            observed[
                "transfer_final_team_rows"
            ],
            EXPECTED_TRANSFER_TEAM_ROWS,
        ),
        (
            "transfer_non_d1_rows",
            abs(
                observed[
                    "transfer_non_d1_rows"
                ]
                - EXPECTED_TRANSFER_NON_D1_ROWS
            ),
            observed[
                "transfer_non_d1_rows"
            ],
            EXPECTED_TRANSFER_NON_D1_ROWS,
        ),
        (
            "original_source_rows",
            abs(
                observed[
                    "original_source_rows"
                ]
                - EXPECTED_ORIGINAL_SOURCE_ROWS
            ),
            observed[
                "original_source_rows"
            ],
            EXPECTED_ORIGINAL_SOURCE_ROWS,
        ),
        (
            "unresolved_rows",
            observed["unresolved_rows"],
            observed["unresolved_rows"],
            0,
        ),
        (
            "blank_analytical_entity_ids",
            observed[
                "blank_analytical_entity_ids"
            ],
            observed[
                "blank_analytical_entity_ids"
            ],
            0,
        ),
        (
            "override_rows_without_override_flag",
            observed[
                "override_rows_without_override_flag"
            ],
            observed[
                "override_rows_without_override_flag"
            ],
            0,
        ),
        (
            "nonoverride_rows_with_override_flag",
            observed[
                "nonoverride_rows_with_override_flag"
            ],
            observed[
                "nonoverride_rows_with_override_flag"
            ],
            0,
        ),
        (
            "d1_eligible_rows_without_d1_scope",
            observed[
                "d1_eligible_rows_without_d1_scope"
            ],
            observed[
                "d1_eligible_rows_without_d1_scope"
            ],
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


def create_metadata_table(
    con: duckdb.DuckDBPyConnection,
    source_before: dict[str, int],
    source_after: dict[str, int],
) -> None:
    metadata = pd.DataFrame(
        [
            {
                "metadata_key": (
                    "attribution_version"
                ),
                "metadata_value": (
                    ATTRIBUTION_VERSION
                ),
            },
            {
                "metadata_key": "built_at_utc",
                "metadata_value": (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                ),
            },
            {
                "metadata_key": "source_database",
                "metadata_value": str(
                    SOURCE_DB
                ),
            },
            {
                "metadata_key": "coverage_database",
                "metadata_value": str(
                    COVERAGE_DB
                ),
            },
            {
                "metadata_key": "registry_csv",
                "metadata_value": str(
                    REGISTRY_CSV
                ),
            },
            {
                "metadata_key": "override_csv",
                "metadata_value": str(
                    OVERRIDE_CSV
                ),
            },
            {
                "metadata_key": (
                    "source_size_before_bytes"
                ),
                "metadata_value": str(
                    source_before["size_bytes"]
                ),
            },
            {
                "metadata_key": (
                    "source_size_after_bytes"
                ),
                "metadata_value": str(
                    source_after["size_bytes"]
                ),
            },
            {
                "metadata_key": (
                    "source_modified_before_ns"
                ),
                "metadata_value": str(
                    source_before["modified_ns"]
                ),
            },
            {
                "metadata_key": (
                    "source_modified_after_ns"
                ),
                "metadata_value": str(
                    source_after["modified_ns"]
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
        OUTPUT_DIR
        / "confidence_summary.csv",
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

    count_map = {
        row.attribution_precedence: int(
            row.performance_rows
        )
        for row in precedence.itertuples(
            index=False
        )
    }

    source_rows = scalar(
        con,
        """
        SELECT COUNT(*)
        FROM source.core.performances
        """,
    )

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

    report = f"""MILESTONE 4 CANONICAL PERFORMANCE ATTRIBUTION
============================================================
Attribution version: {ATTRIBUTION_VERSION}
Source database modified: no
Coverage database modified: no

SCOPE
- Source performances: {source_rows:,}
- Canonical attribution rows: {source_rows:,}
- D1-development-eligible rows: {d1_rows:,}
- School-stint-eligible rows: {stint_rows:,}

ATTRIBUTION PRECEDENCE
- Performance-level overrides:
  {count_map.get('PERFORMANCE_LEVEL_OVERRIDE', 0):,}
- Canonical profile sections:
  {count_map.get('CANONICAL_PROFILE_SECTION', 0):,}
- Transfer final teams:
  {count_map.get('TRANSFER_FINAL_TEAM', 0):,}
- Transfer non-D1 scope entities:
  {count_map.get('TRANSFER_NON_D1_SCOPE', 0):,}
- Original source teams:
  {count_map.get('ORIGINAL_SOURCE_TEAM', 0):,}
- Unresolved:
  {count_map.get('UNRESOLVED', 0):,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

DATABASE CONTENTS
- canonical_performance_attribution
- attribution_precedence_summary
- competition_scope_summary
- confidence_summary
- hard_checks
- audit_metadata
- d1_development_attribution (view)
- school_stint_attribution (view)

INTERPRETATION
The attribution database contains one compact attribution row for every source
performance. Performance facts remain in the immutable Milestone 3 database
and can be joined through performance_id. The 120 performance-level overrides
have the highest precedence. Non-D1 entities remain explicitly classified and
are excluded from D1 development and school-stint eligibility.
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

    source_before = source_file_state()

    con = duckdb.connect(
        str(OUTPUT_DB)
    )

    try:
        con.execute(
            "PRAGMA threads=4"
        )
        con.execute(
            "PRAGMA preserve_insertion_order=false"
        )

        attach_inputs(con)
        create_attribution_table(con)
        create_summary_tables(con)

        source_after = source_file_state()

        if source_before != source_after:
            raise RuntimeError(
                "The source database file state "
                "changed during the read-only build."
            )

        checks = build_checks(con)

        create_metadata_table(
            con=con,
            source_before=source_before,
            source_after=source_after,
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
            "Canonical performance-attribution "
            "build complete."
        )
        print(f"Database: {OUTPUT_DB}")
        print(f"Failed checks: {failed:,}.")

        if failed:
            raise SystemExit(1)

    finally:
        con.close()

    output_size = os.path.getsize(
        OUTPUT_DB
    )

    print(
        "Output database size: "
        f"{output_size / (1024 ** 3):.2f} GiB"
    )


if __name__ == "__main__":
    main()
