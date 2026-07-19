#!/usr/bin/env python3
"""
Milestone 4 performance-backed affiliation inspection.

This is a read-only diagnostic step. It does not create or modify DuckDB
schemas or tables.

Why this exists
---------------
The roster-derived affiliation table can contain more than one institution for
the same athlete and season. Exact performance rows are still internally
consistent with their linked affiliation, team, and season. Before constructing
school stints, this script measures:

1. How often exact performance-backed athlete-seasons contain multiple schools.
2. How many null-affiliation performances can be deterministically recovered
   from athlete_id + team_id + season_id.
3. Whether team-only fallback performances agree with exact school evidence in
   the same athlete-season.
4. Which roster affiliations are supported by at least one linked performance.
5. Performance-backed transfer sequences for manual review.

Run from the repository root:
    python src/analysis/milestone4/inspect_performance_backed_affiliations.py
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "data/database/ncaa_track_analytics.duckdb"
OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/inspection_performance_affiliations"
)


def export_query(
    con: duckdb.DuckDBPyConnection,
    filename: str,
    sql: str,
) -> int:
    dataframe = con.execute(sql).fetchdf()
    output_path = OUTPUT_DIR / filename
    dataframe.to_csv(output_path, index=False)
    print(f"Wrote {filename}: {len(dataframe):,} rows")
    return len(dataframe)


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        # --------------------------------------------------------------
        # 1. Exact performance-backed school evidence
        # --------------------------------------------------------------
        export_query(
            con,
            "performance_backed_school_count_summary.csv",
            """
            WITH school_seasons AS (
                SELECT
                    p.athlete_id,
                    p.season_id,
                    t.school_id,
                    COUNT(*) AS performance_count
                FROM core.performances p
                JOIN core.athlete_affiliations a
                  ON p.affiliation_id = a.affiliation_id
                JOIN core.teams t
                  ON a.team_id = t.team_id
                GROUP BY
                    p.athlete_id,
                    p.season_id,
                    t.school_id
            ),
            athlete_seasons AS (
                SELECT
                    athlete_id,
                    season_id,
                    COUNT(*) AS distinct_schools,
                    SUM(performance_count) AS performance_count
                FROM school_seasons
                GROUP BY athlete_id, season_id
            )
            SELECT
                distinct_schools,
                COUNT(*) AS athlete_season_count,
                SUM(performance_count) AS performance_count,
                COUNT(DISTINCT athlete_id) AS athlete_count
            FROM athlete_seasons
            GROUP BY distinct_schools
            ORDER BY distinct_schools
            """,
        )

        export_query(
            con,
            "performance_backed_multischool_by_season.csv",
            """
            WITH school_seasons AS (
                SELECT
                    p.athlete_id,
                    p.season_id,
                    t.school_id,
                    COUNT(*) AS performance_count
                FROM core.performances p
                JOIN core.athlete_affiliations a
                  ON p.affiliation_id = a.affiliation_id
                JOIN core.teams t
                  ON a.team_id = t.team_id
                GROUP BY
                    p.athlete_id,
                    p.season_id,
                    t.school_id
            ),
            athlete_seasons AS (
                SELECT
                    athlete_id,
                    season_id,
                    COUNT(*) AS distinct_schools,
                    SUM(performance_count) AS performance_count
                FROM school_seasons
                GROUP BY athlete_id, season_id
            )
            SELECT
                se.season_id,
                se.season_year,
                se.season_type,
                COUNT(*) AS exact_attributed_athlete_seasons,
                COUNT(*) FILTER (
                    WHERE ats.distinct_schools > 1
                ) AS multischool_athlete_seasons,
                ROUND(
                    100.0
                    * COUNT(*) FILTER (WHERE ats.distinct_schools > 1)
                    / NULLIF(COUNT(*), 0),
                    4
                ) AS multischool_percent,
                SUM(ats.performance_count) AS exact_performance_count
            FROM athlete_seasons ats
            JOIN core.seasons se
              ON ats.season_id = se.season_id
            GROUP BY se.season_id, se.season_year, se.season_type
            ORDER BY
                se.season_year,
                CASE se.season_type
                    WHEN 'indoor' THEN 1
                    WHEN 'outdoor' THEN 2
                    WHEN 'cross_country' THEN 3
                    ELSE 4
                END
            """,
        )

        export_query(
            con,
            "performance_backed_multischool_sample.csv",
            """
            WITH school_seasons AS (
                SELECT
                    p.athlete_id,
                    p.season_id,
                    t.school_id,
                    s.school_name,
                    COUNT(*) AS performance_count,
                    COUNT(DISTINCT p.meet_id) AS meet_count
                FROM core.performances p
                JOIN core.athlete_affiliations a
                  ON p.affiliation_id = a.affiliation_id
                JOIN core.teams t
                  ON a.team_id = t.team_id
                JOIN core.schools s
                  ON t.school_id = s.school_id
                GROUP BY
                    p.athlete_id,
                    p.season_id,
                    t.school_id,
                    s.school_name
            ),
            multischool AS (
                SELECT
                    athlete_id,
                    season_id,
                    COUNT(*) AS distinct_schools,
                    SUM(performance_count) AS performance_count,
                    SUM(meet_count) AS school_meet_count_sum,
                    STRING_AGG(
                        school_name
                        || ' [performances='
                        || CAST(performance_count AS VARCHAR)
                        || ', meets='
                        || CAST(meet_count AS VARCHAR)
                        || ']',
                        ' | '
                        ORDER BY performance_count DESC, school_name
                    ) AS school_evidence
                FROM school_seasons
                GROUP BY athlete_id, season_id
                HAVING COUNT(*) > 1
            )
            SELECT
                m.athlete_id,
                se.season_year,
                se.season_type,
                m.season_id,
                m.distinct_schools,
                m.performance_count,
                m.school_meet_count_sum,
                m.school_evidence
            FROM multischool m
            JOIN core.seasons se
              ON m.season_id = se.season_id
            ORDER BY
                m.distinct_schools DESC,
                m.performance_count DESC,
                m.athlete_id,
                se.season_year
            LIMIT 1000
            """,
        )

        # --------------------------------------------------------------
        # 2. Null-affiliation deterministic recovery
        # --------------------------------------------------------------
        export_query(
            con,
            "null_affiliation_natural_key_recovery.csv",
            """
            WITH match_counts AS (
                SELECT
                    p.performance_id,
                    p.athlete_id,
                    COUNT(a.affiliation_id) AS matching_affiliations
                FROM core.performances p
                LEFT JOIN core.athlete_affiliations a
                  ON p.athlete_id = a.athlete_id
                 AND p.team_id = a.team_id
                 AND p.season_id = a.season_id
                WHERE p.affiliation_id IS NULL
                  AND p.team_id IS NOT NULL
                GROUP BY p.performance_id, p.athlete_id
            )
            SELECT
                CASE
                    WHEN matching_affiliations = 0
                        THEN 'NO_NATURAL_KEY_MATCH'
                    WHEN matching_affiliations = 1
                        THEN 'UNIQUE_NATURAL_KEY_MATCH'
                    ELSE 'MULTIPLE_NATURAL_KEY_MATCHES'
                END AS recovery_status,
                COUNT(*) AS performance_count,
                COUNT(DISTINCT athlete_id) AS athlete_count
            FROM match_counts
            GROUP BY recovery_status
            ORDER BY performance_count DESC
            """,
        )

        # --------------------------------------------------------------
        # 3. Confidence tiers for null-affiliation rows
        # --------------------------------------------------------------
        export_query(
            con,
            "team_fallback_confidence_tiers.csv",
            """
            WITH exact_schools AS (
                SELECT DISTINCT
                    p.athlete_id,
                    p.season_id,
                    t.school_id
                FROM core.performances p
                JOIN core.athlete_affiliations a
                  ON p.affiliation_id = a.affiliation_id
                JOIN core.teams t
                  ON a.team_id = t.team_id
            ),
            exact_seasons AS (
                SELECT
                    athlete_id,
                    season_id,
                    COUNT(DISTINCT school_id) AS exact_school_count
                FROM exact_schools
                GROUP BY athlete_id, season_id
            ),
            classified AS (
                SELECT
                    p.performance_id,
                    p.athlete_id,
                    CASE
                        WHEN p.team_id IS NULL
                            THEN 'TIER_E_NO_TEAM'
                        WHEN a.affiliation_id IS NOT NULL
                            THEN 'TIER_B_UNIQUE_NATURAL_KEY_MATCH'
                        WHEN es.school_id IS NOT NULL
                            THEN 'TIER_C_SAME_SCHOOL_PERFORMANCE_SUPPORTED'
                        WHEN ec.exact_school_count IS NOT NULL
                            THEN 'TIER_D_DIFFERENT_EXACT_SCHOOL_IN_SEASON'
                        ELSE 'TIER_D_TEAM_ONLY_NO_EXACT_SEASON_EVIDENCE'
                    END AS attribution_tier
                FROM core.performances p
                LEFT JOIN core.teams fallback_team
                  ON p.team_id = fallback_team.team_id
                LEFT JOIN core.athlete_affiliations a
                  ON p.athlete_id = a.athlete_id
                 AND p.team_id = a.team_id
                 AND p.season_id = a.season_id
                LEFT JOIN exact_schools es
                  ON p.athlete_id = es.athlete_id
                 AND p.season_id = es.season_id
                 AND fallback_team.school_id = es.school_id
                LEFT JOIN exact_seasons ec
                  ON p.athlete_id = ec.athlete_id
                 AND p.season_id = ec.season_id
                WHERE p.affiliation_id IS NULL
            )
            SELECT
                attribution_tier,
                COUNT(*) AS performance_count,
                COUNT(DISTINCT athlete_id) AS athlete_count
            FROM classified
            GROUP BY attribution_tier
            ORDER BY attribution_tier
            """,
        )

        # --------------------------------------------------------------
        # 4. Roster affiliations with and without performance support
        # --------------------------------------------------------------
        export_query(
            con,
            "roster_affiliation_performance_support.csv",
            """
            WITH affiliation_support AS (
                SELECT
                    a.affiliation_id,
                    a.athlete_id,
                    a.season_id,
                    a.team_id,
                    COUNT(p.performance_id) AS linked_performance_count
                FROM core.athlete_affiliations a
                LEFT JOIN core.performances p
                  ON a.affiliation_id = p.affiliation_id
                GROUP BY
                    a.affiliation_id,
                    a.athlete_id,
                    a.season_id,
                    a.team_id
            )
            SELECT
                se.season_type,
                CASE
                    WHEN linked_performance_count > 0
                        THEN 'PERFORMANCE_SUPPORTED'
                    ELSE 'ROSTER_ONLY'
                END AS support_status,
                COUNT(*) AS affiliation_count,
                COUNT(DISTINCT athlete_id) AS athlete_count,
                SUM(linked_performance_count) AS linked_performance_count
            FROM affiliation_support aps
            JOIN core.seasons se
              ON aps.season_id = se.season_id
            GROUP BY se.season_type, support_status
            ORDER BY se.season_type, support_status
            """,
        )

        # --------------------------------------------------------------
        # 5. Performance-backed school history and transfer sequences
        # --------------------------------------------------------------
        export_query(
            con,
            "performance_backed_distinct_school_summary.csv",
            """
            WITH athlete_schools AS (
                SELECT DISTINCT
                    p.athlete_id,
                    t.school_id
                FROM core.performances p
                JOIN core.athlete_affiliations a
                  ON p.affiliation_id = a.affiliation_id
                JOIN core.teams t
                  ON a.team_id = t.team_id
            ),
            counts AS (
                SELECT
                    athlete_id,
                    COUNT(*) AS distinct_schools
                FROM athlete_schools
                GROUP BY athlete_id
            )
            SELECT
                distinct_schools,
                COUNT(*) AS athlete_count
            FROM counts
            GROUP BY distinct_schools
            ORDER BY distinct_schools
            """,
        )

        export_query(
            con,
            "performance_backed_transfer_sequence_sample.csv",
            """
            WITH school_seasons AS (
                SELECT
                    p.athlete_id,
                    se.season_year,
                    se.season_type,
                    p.season_id,
                    t.school_id,
                    s.school_name,
                    t.gender_code,
                    COUNT(*) AS performance_count,
                    COUNT(DISTINCT p.meet_id) AS meet_count,
                    MIN(m.canonical_meet_date_text) AS minimum_raw_meet_date,
                    MAX(m.canonical_meet_date_text) AS maximum_raw_meet_date
                FROM core.performances p
                JOIN core.athlete_affiliations a
                  ON p.affiliation_id = a.affiliation_id
                JOIN core.teams t
                  ON a.team_id = t.team_id
                JOIN core.schools s
                  ON t.school_id = s.school_id
                JOIN core.seasons se
                  ON p.season_id = se.season_id
                LEFT JOIN core.meets m
                  ON p.meet_id = m.meet_id
                GROUP BY
                    p.athlete_id,
                    se.season_year,
                    se.season_type,
                    p.season_id,
                    t.school_id,
                    s.school_name,
                    t.gender_code
            ),
            candidates AS (
                SELECT
                    athlete_id,
                    COUNT(DISTINCT school_id) AS distinct_schools,
                    SUM(performance_count) AS performance_count
                FROM school_seasons
                GROUP BY athlete_id
                HAVING COUNT(DISTINCT school_id) > 1
                ORDER BY
                    distinct_schools DESC,
                    performance_count DESC,
                    athlete_id
                LIMIT 50
            )
            SELECT
                ss.athlete_id,
                c.distinct_schools,
                c.performance_count AS athlete_exact_performance_count,
                ss.season_year,
                ss.season_type,
                ss.season_id,
                ss.school_id,
                ss.school_name,
                ss.gender_code,
                ss.performance_count AS school_season_performance_count,
                ss.meet_count,
                ss.minimum_raw_meet_date,
                ss.maximum_raw_meet_date
            FROM candidates c
            JOIN school_seasons ss
              ON c.athlete_id = ss.athlete_id
            ORDER BY
                c.distinct_schools DESC,
                c.performance_count DESC,
                ss.athlete_id,
                ss.season_year,
                CASE ss.season_type
                    WHEN 'indoor' THEN 1
                    WHEN 'outdoor' THEN 2
                    WHEN 'cross_country' THEN 3
                    ELSE 4
                END,
                ss.performance_count DESC,
                ss.school_name
            """,
        )

        # --------------------------------------------------------------
        # 6. Human-readable summary
        # --------------------------------------------------------------
        summary = """MILESTONE 4 PERFORMANCE-BACKED AFFILIATION INSPECTION
================================================================
Database connection: read-only

PURPOSE
- Distinguish performance-supported school evidence from roster-only evidence.
- Measure exact same-season multi-school performance histories.
- Measure deterministic recovery options for null affiliation_id rows.
- Provide evidence for transfer-safe school-stint construction.

OUTPUTS
- performance_backed_school_count_summary.csv
- performance_backed_multischool_by_season.csv
- performance_backed_multischool_sample.csv
- null_affiliation_natural_key_recovery.csv
- team_fallback_confidence_tiers.csv
- roster_affiliation_performance_support.csv
- performance_backed_distinct_school_summary.csv
- performance_backed_transfer_sequence_sample.csv

NO DATABASE OBJECTS WERE CREATED OR MODIFIED.
"""
        (OUTPUT_DIR / "inspection_summary.txt").write_text(
            summary,
            encoding="utf-8",
        )

        print(f"Outputs: {OUTPUT_DIR}")
        print("Database connection was read-only.")

    finally:
        con.close()


if __name__ == "__main__":
    main()
