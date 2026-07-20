#!/usr/bin/env python3
"""
Milestone 4 performance-team school-history inspection.

Read-only diagnostic. No DuckDB objects are created or modified.

The prior inspection showed:
- exact affiliation-linked performances are internally consistent;
- exact-linked performances support only one school per athlete;
- almost every null-affiliation performance still has performance.team_id.

This script tests whether performance.team_id preserves transfer histories that
are not represented by affiliation_id.

Run from the repository root:
    python src/analysis/milestone4/inspect_performance_team_school_history.py
"""

from __future__ import annotations

from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "data/database/ncaa_track_analytics.duckdb"
OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/inspection_team_school_history"
)


def export_query(
    con: duckdb.DuckDBPyConnection,
    filename: str,
    sql: str,
) -> None:
    dataframe = con.execute(sql).fetchdf()
    dataframe.to_csv(OUTPUT_DIR / filename, index=False)
    print(f"Wrote {filename}: {len(dataframe):,} rows")


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        # --------------------------------------------------------------
        # 1. Basic team attribution completeness
        # --------------------------------------------------------------
        export_query(
            con,
            "performance_team_join_checks.csv",
            """
            SELECT
                'all_performances' AS check_name,
                COUNT(*) AS row_count
            FROM core.performances

            UNION ALL

            SELECT
                'nonnull_performance_team_id',
                COUNT(*)
            FROM core.performances
            WHERE team_id IS NOT NULL

            UNION ALL

            SELECT
                'null_performance_team_id',
                COUNT(*)
            FROM core.performances
            WHERE team_id IS NULL

            UNION ALL

            SELECT
                'nonnull_team_without_core_team',
                COUNT(*)
            FROM core.performances p
            LEFT JOIN core.teams t
              ON p.team_id = t.team_id
            WHERE p.team_id IS NOT NULL
              AND t.team_id IS NULL

            UNION ALL

            SELECT
                'nonnull_team_without_school',
                COUNT(*)
            FROM core.performances p
            JOIN core.teams t
              ON p.team_id = t.team_id
            LEFT JOIN core.schools s
              ON t.school_id = s.school_id
            WHERE p.team_id IS NOT NULL
              AND s.school_id IS NULL
            """,
        )

        export_query(
            con,
            "performance_team_metadata_profile.csv",
            """
            SELECT
                CASE
                    WHEN p.affiliation_id IS NOT NULL
                        THEN 'EXACT_LINKED'
                    WHEN p.team_id IS NOT NULL
                        THEN 'TEAM_ONLY'
                    ELSE 'UNATTRIBUTED'
                END AS attribution_group,
                COALESCE(t.division, '[NULL]') AS division,
                COALESCE(t.sport, '[NULL]') AS sport,
                COALESCE(t.gender_code, '[NULL]') AS gender_code,
                COUNT(*) AS performance_count,
                COUNT(DISTINCT p.athlete_id) AS athlete_count,
                COUNT(DISTINCT t.school_id) AS school_count,
                COUNT(DISTINCT p.team_id) AS team_count
            FROM core.performances p
            LEFT JOIN core.teams t
              ON p.team_id = t.team_id
            GROUP BY
                attribution_group,
                division,
                sport,
                gender_code
            ORDER BY
                attribution_group,
                performance_count DESC
            """,
        )

        # --------------------------------------------------------------
        # 2. All performance-team school histories
        # --------------------------------------------------------------
        export_query(
            con,
            "all_team_attributed_school_count_summary.csv",
            """
            WITH athlete_season_schools AS (
                SELECT DISTINCT
                    p.athlete_id,
                    p.season_id,
                    t.school_id
                FROM core.performances p
                JOIN core.teams t
                  ON p.team_id = t.team_id
                WHERE p.team_id IS NOT NULL
            ),
            counts AS (
                SELECT
                    athlete_id,
                    season_id,
                    COUNT(*) AS distinct_schools
                FROM athlete_season_schools
                GROUP BY athlete_id, season_id
            )
            SELECT
                distinct_schools,
                COUNT(*) AS athlete_season_count,
                COUNT(DISTINCT athlete_id) AS athlete_count
            FROM counts
            GROUP BY distinct_schools
            ORDER BY distinct_schools
            """,
        )

        export_query(
            con,
            "all_team_attributed_distinct_school_summary.csv",
            """
            WITH athlete_schools AS (
                SELECT DISTINCT
                    p.athlete_id,
                    t.school_id
                FROM core.performances p
                JOIN core.teams t
                  ON p.team_id = t.team_id
                WHERE p.team_id IS NOT NULL
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
            "all_team_attributed_multischool_by_season.csv",
            """
            WITH school_evidence AS (
                SELECT
                    p.athlete_id,
                    p.season_id,
                    t.school_id,
                    COUNT(*) AS performance_count,
                    COUNT(DISTINCT p.meet_id) AS meet_count
                FROM core.performances p
                JOIN core.teams t
                  ON p.team_id = t.team_id
                WHERE p.team_id IS NOT NULL
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
                FROM school_evidence
                GROUP BY athlete_id, season_id
            )
            SELECT
                se.season_id,
                se.season_year,
                se.season_type,
                COUNT(*) AS attributed_athlete_seasons,
                COUNT(*) FILTER (
                    WHERE ats.distinct_schools > 1
                ) AS multischool_athlete_seasons,
                ROUND(
                    100.0
                    * COUNT(*) FILTER (WHERE ats.distinct_schools > 1)
                    / NULLIF(COUNT(*), 0),
                    5
                ) AS multischool_percent,
                SUM(ats.performance_count) AS performance_count
            FROM athlete_seasons ats
            JOIN core.seasons se
              ON ats.season_id = se.season_id
            GROUP BY
                se.season_id,
                se.season_year,
                se.season_type
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
            "all_team_attributed_multischool_sample.csv",
            """
            WITH school_evidence AS (
                SELECT
                    p.athlete_id,
                    p.season_id,
                    t.school_id,
                    s.school_name,
                    COUNT(*) AS performance_count,
                    COUNT(DISTINCT p.meet_id) AS meet_count,
                    COUNT(*) FILTER (
                        WHERE p.affiliation_id IS NOT NULL
                    ) AS exact_link_count,
                    COUNT(*) FILTER (
                        WHERE p.affiliation_id IS NULL
                    ) AS team_only_count
                FROM core.performances p
                JOIN core.teams t
                  ON p.team_id = t.team_id
                JOIN core.schools s
                  ON t.school_id = s.school_id
                WHERE p.team_id IS NOT NULL
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
                    COUNT(*) AS distinct_schools
                FROM school_evidence
                GROUP BY athlete_id, season_id
                HAVING COUNT(*) > 1
            )
            SELECT
                e.athlete_id,
                se.season_year,
                se.season_type,
                e.season_id,
                m.distinct_schools,
                e.school_id,
                e.school_name,
                e.performance_count,
                e.meet_count,
                e.exact_link_count,
                e.team_only_count
            FROM multischool m
            JOIN school_evidence e
              ON m.athlete_id = e.athlete_id
             AND m.season_id = e.season_id
            JOIN core.seasons se
              ON e.season_id = se.season_id
            ORDER BY
                m.distinct_schools DESC,
                e.athlete_id,
                se.season_year,
                CASE se.season_type
                    WHEN 'indoor' THEN 1
                    WHEN 'outdoor' THEN 2
                    WHEN 'cross_country' THEN 3
                    ELSE 4
                END,
                e.performance_count DESC,
                e.school_name
            LIMIT 2000
            """,
        )

        # --------------------------------------------------------------
        # 3. Relationship between exact-linked and team-only histories
        # --------------------------------------------------------------
        export_query(
            con,
            "team_only_relation_to_exact_school_history.csv",
            """
            WITH exact_school_history AS (
                SELECT DISTINCT
                    p.athlete_id,
                    t.school_id
                FROM core.performances p
                JOIN core.teams t
                  ON p.team_id = t.team_id
                WHERE p.affiliation_id IS NOT NULL
            ),
            exact_athletes AS (
                SELECT DISTINCT athlete_id
                FROM exact_school_history
            ),
            team_only AS (
                SELECT
                    p.performance_id,
                    p.athlete_id,
                    p.season_id,
                    t.school_id
                FROM core.performances p
                JOIN core.teams t
                  ON p.team_id = t.team_id
                WHERE p.affiliation_id IS NULL
                  AND p.team_id IS NOT NULL
            ),
            classified AS (
                SELECT
                    x.performance_id,
                    x.athlete_id,
                    CASE
                        WHEN h.athlete_id IS NOT NULL
                            THEN 'SAME_AS_EXACT_LINKED_SCHOOL'
                        WHEN ea.athlete_id IS NOT NULL
                            THEN 'DIFFERENT_FROM_EXACT_LINKED_SCHOOL'
                        ELSE 'NO_EXACT_LINKED_HISTORY'
                    END AS relation_to_exact_history
                FROM team_only x
                LEFT JOIN exact_school_history h
                  ON x.athlete_id = h.athlete_id
                 AND x.school_id = h.school_id
                LEFT JOIN exact_athletes ea
                  ON x.athlete_id = ea.athlete_id
            )
            SELECT
                relation_to_exact_history,
                COUNT(*) AS performance_count,
                COUNT(DISTINCT athlete_id) AS athlete_count
            FROM classified
            GROUP BY relation_to_exact_history
            ORDER BY performance_count DESC
            """,
        )

        export_query(
            con,
            "athletes_with_team_only_transfer_evidence.csv",
            """
            WITH exact_school_history AS (
                SELECT DISTINCT
                    p.athlete_id,
                    t.school_id
                FROM core.performances p
                JOIN core.teams t
                  ON p.team_id = t.team_id
                WHERE p.affiliation_id IS NOT NULL
            ),
            all_school_history AS (
                SELECT
                    p.athlete_id,
                    t.school_id,
                    s.school_name,
                    COUNT(*) AS performance_count,
                    COUNT(*) FILTER (
                        WHERE p.affiliation_id IS NOT NULL
                    ) AS exact_link_count,
                    COUNT(*) FILTER (
                        WHERE p.affiliation_id IS NULL
                    ) AS team_only_count,
                    MIN(se.season_year) AS first_season_year,
                    MAX(se.season_year) AS last_season_year
                FROM core.performances p
                JOIN core.teams t
                  ON p.team_id = t.team_id
                JOIN core.schools s
                  ON t.school_id = s.school_id
                JOIN core.seasons se
                  ON p.season_id = se.season_id
                WHERE p.team_id IS NOT NULL
                GROUP BY
                    p.athlete_id,
                    t.school_id,
                    s.school_name
            ),
            candidates AS (
                SELECT
                    athlete_id
                FROM all_school_history
                GROUP BY athlete_id
                HAVING COUNT(*) > 1
            )
            SELECT
                h.athlete_id,
                COUNT(*) OVER (
                    PARTITION BY h.athlete_id
                ) AS distinct_schools,
                h.school_id,
                h.school_name,
                h.performance_count,
                h.exact_link_count,
                h.team_only_count,
                h.first_season_year,
                h.last_season_year,
                CASE
                    WHEN e.athlete_id IS NOT NULL
                        THEN 'HAS_EXACT_LINK_SUPPORT'
                    ELSE 'TEAM_ONLY_SCHOOL'
                END AS school_evidence_type
            FROM candidates c
            JOIN all_school_history h
              ON c.athlete_id = h.athlete_id
            LEFT JOIN exact_school_history e
              ON h.athlete_id = e.athlete_id
             AND h.school_id = e.school_id
            ORDER BY
                distinct_schools DESC,
                h.athlete_id,
                h.first_season_year,
                h.school_name
            LIMIT 5000
            """,
        )

        # --------------------------------------------------------------
        # 4. Chronological performance-backed school sequences
        # --------------------------------------------------------------
        export_query(
            con,
            "performance_team_transfer_sequence_sample.csv",
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
                    COUNT(*) FILTER (
                        WHERE p.affiliation_id IS NOT NULL
                    ) AS exact_link_count,
                    COUNT(*) FILTER (
                        WHERE p.affiliation_id IS NULL
                    ) AS team_only_count
                FROM core.performances p
                JOIN core.teams t
                  ON p.team_id = t.team_id
                JOIN core.schools s
                  ON t.school_id = s.school_id
                JOIN core.seasons se
                  ON p.season_id = se.season_id
                WHERE p.team_id IS NOT NULL
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
                LIMIT 100
            )
            SELECT
                ss.athlete_id,
                c.distinct_schools,
                c.performance_count AS athlete_performance_count,
                ss.season_year,
                ss.season_type,
                ss.season_id,
                ss.school_id,
                ss.school_name,
                ss.gender_code,
                ss.performance_count AS school_season_performance_count,
                ss.meet_count,
                ss.exact_link_count,
                ss.team_only_count
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

        summary = """MILESTONE 4 PERFORMANCE-TEAM SCHOOL-HISTORY INSPECTION
================================================================
Connection mode: read-only

PURPOSE
- Test performance.team_id as the primary school-attribution field.
- Recover transfer histories hidden among null affiliation_id rows.
- Measure same-season multi-school performance evidence.
- Distinguish exact-linked school evidence from team-only evidence.

KEY OUTPUTS
- performance_team_join_checks.csv
- performance_team_metadata_profile.csv
- all_team_attributed_school_count_summary.csv
- all_team_attributed_distinct_school_summary.csv
- all_team_attributed_multischool_by_season.csv
- all_team_attributed_multischool_sample.csv
- team_only_relation_to_exact_school_history.csv
- athletes_with_team_only_transfer_evidence.csv
- performance_team_transfer_sequence_sample.csv

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
