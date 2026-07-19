#!/usr/bin/env python3
"""
Milestone 4 Phase 2: school-stint reconstruction preflight.

This script is read-only. It inspects the canonical attribution v1.1 layer and
the immutable Milestone 3 source database to determine whether D1-eligible
performances can be safely grouped into athlete school stints.

No database or prior output is modified.

Outputs
-------
data/processed/milestone4/school_stint_preflight/
    preflight_report.txt
    hard_checks.csv
    athlete_team_summary.csv
    athlete_season_team_summary.csv
    multi_team_same_season_queue.csv
    team_return_candidates.csv
    missing_chronology_queue.csv
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

ATTRIBUTION_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_performance_attribution_v1_1/"
    / "canonical_performance_attribution_v1_1.duckdb"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "school_stint_preflight"
)

PREFLIGHT_VERSION = (
    "m4_school_stint_preflight_v1.1"
)


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
        ATTRIBUTION_DB,
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

    files = [
        OUTPUT_DIR / "preflight_report.txt",
        OUTPUT_DIR / "hard_checks.csv",
        OUTPUT_DIR / "athlete_team_summary.csv",
        OUTPUT_DIR / "athlete_season_team_summary.csv",
        OUTPUT_DIR / "multi_team_same_season_queue.csv",
        OUTPUT_DIR / "team_return_candidates.csv",
        OUTPUT_DIR / "missing_chronology_queue.csv",
    ]

    existing = [
        path
        for path in files
        if path.exists()
    ]

    if existing and not replace_output:
        raise FileExistsError(
            "Existing school-stint preflight outputs found. "
            "Use --replace-output only after reviewing them."
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

    con = duckdb.connect()

    try:
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

        con.execute(
            """
            CREATE TEMP VIEW eligible AS
            SELECT
                a.performance_id,
                a.athlete_id,
                a.canonical_team_id,
                a.canonical_school_id,
                a.canonical_school_name,
                a.canonical_team_name,
                a.canonical_gender_code,
                a.canonical_division,
                a.canonical_competition_level,
                a.attribution_precedence,
                a.attribution_confidence,
                a.season_year,
                a.season_type,
                p.season_id,
                p.meet_id,
                p.meet_name,
                p.meet_date_text,
                p.event,
                p.mark,
                p.result_url
            FROM attribution.main
                .canonical_performance_attribution a
            JOIN source.core.performances p
              ON a.performance_id = p.performance_id
            WHERE a.school_stint_eligible
            """
        )

        con.execute(
            """
            CREATE TEMP VIEW season_ordered AS
            SELECT
                *,
                CASE
                    WHEN season_type = 'cross_country'
                    THEN 1
                    WHEN season_type = 'indoor'
                    THEN 2
                    WHEN season_type = 'outdoor'
                    THEN 3
                    ELSE 9
                END AS season_type_order
            FROM eligible
            """
        )

        athlete_team_summary = con.execute(
            """
            SELECT
                athlete_id,
                canonical_team_id,
                canonical_school_id,
                canonical_school_name,
                canonical_team_name,
                canonical_gender_code,
                MIN(season_year)
                    AS first_season_year,
                MAX(season_year)
                    AS last_season_year,
                COUNT(DISTINCT season_id)
                    AS season_count,
                COUNT(DISTINCT meet_id)
                    AS meet_count,
                COUNT(*) AS performance_rows,
                COUNT(DISTINCT attribution_precedence)
                    AS attribution_method_count,
                STRING_AGG(
                    DISTINCT attribution_precedence,
                    ' | '
                    ORDER BY attribution_precedence
                ) AS attribution_methods
            FROM eligible
            GROUP BY
                athlete_id,
                canonical_team_id,
                canonical_school_id,
                canonical_school_name,
                canonical_team_name,
                canonical_gender_code
            ORDER BY
                athlete_id,
                first_season_year,
                canonical_team_id
            """
        ).fetchdf()

        athlete_season_team_summary = con.execute(
            """
            SELECT
                athlete_id,
                season_year,
                season_type,
                season_id,
                canonical_team_id,
                canonical_school_id,
                canonical_school_name,
                canonical_team_name,
                canonical_gender_code,
                COUNT(*) AS performance_rows,
                COUNT(DISTINCT meet_id)
                    AS meet_count,
                COUNT(DISTINCT event)
                    AS event_count,
                MIN(attribution_confidence)
                    AS minimum_attribution_confidence,
                STRING_AGG(
                    DISTINCT attribution_precedence,
                    ' | '
                    ORDER BY attribution_precedence
                ) AS attribution_methods
            FROM eligible
            GROUP BY
                athlete_id,
                season_year,
                season_type,
                season_id,
                canonical_team_id,
                canonical_school_id,
                canonical_school_name,
                canonical_team_name,
                canonical_gender_code
            ORDER BY
                athlete_id,
                season_year,
                CASE
                    WHEN season_type = 'cross_country'
                    THEN 1
                    WHEN season_type = 'indoor'
                    THEN 2
                    WHEN season_type = 'outdoor'
                    THEN 3
                    ELSE 9
                END,
                canonical_team_id
            """
        ).fetchdf()

        multi_team_same_season = con.execute(
            """
            WITH season_counts AS (
                SELECT
                    athlete_id,
                    season_year,
                    season_type,
                    COUNT(DISTINCT canonical_team_id)
                        AS team_count,
                    COUNT(*) AS performance_rows
                FROM eligible
                GROUP BY
                    athlete_id,
                    season_year,
                    season_type
                HAVING COUNT(
                    DISTINCT canonical_team_id
                ) > 1
            )
            SELECT
                e.athlete_id,
                e.season_year,
                e.season_type,
                s.team_count,
                e.canonical_team_id,
                e.canonical_school_id,
                e.canonical_school_name,
                e.canonical_team_name,
                COUNT(*) AS performance_rows,
                COUNT(DISTINCT e.meet_id)
                    AS meet_count,
                STRING_AGG(
                    DISTINCT e.attribution_precedence,
                    ' | '
                    ORDER BY e.attribution_precedence
                ) AS attribution_methods
            FROM eligible e
            JOIN season_counts s
              ON e.athlete_id = s.athlete_id
             AND e.season_year = s.season_year
             AND e.season_type = s.season_type
            GROUP BY
                e.athlete_id,
                e.season_year,
                e.season_type,
                s.team_count,
                e.canonical_team_id,
                e.canonical_school_id,
                e.canonical_school_name,
                e.canonical_team_name
            ORDER BY
                e.athlete_id,
                e.season_year,
                CASE
                    WHEN e.season_type = 'cross_country'
                    THEN 1
                    WHEN e.season_type = 'indoor'
                    THEN 2
                    WHEN e.season_type = 'outdoor'
                    THEN 3
                    ELSE 9
                END,
                performance_rows DESC
            """
        ).fetchdf()

        team_return_candidates = con.execute(
            """
            WITH ordered AS (
                SELECT DISTINCT
                    athlete_id,
                    canonical_team_id,
                    canonical_school_id,
                    canonical_school_name,
                    season_year,
                    season_type,
                    CASE
                        WHEN season_type = 'cross_country'
                        THEN 1
                        WHEN season_type = 'indoor'
                        THEN 2
                        WHEN season_type = 'outdoor'
                        THEN 3
                        ELSE 9
                    END AS season_type_order
                FROM eligible
            ),
            with_previous AS (
                SELECT
                    *,
                    LAG(canonical_team_id)
                        OVER (
                            PARTITION BY athlete_id
                            ORDER BY
                                season_year,
                                season_type_order,
                                canonical_team_id
                        ) AS previous_team_id
                FROM ordered
            ),
            numbered_runs AS (
                SELECT
                    *,
                    SUM(
                        CASE
                            WHEN previous_team_id IS NULL
                              OR canonical_team_id
                                    != previous_team_id
                            THEN 1
                            ELSE 0
                        END
                    ) OVER (
                        PARTITION BY athlete_id
                        ORDER BY
                            season_year,
                            season_type_order,
                            canonical_team_id
                        ROWS BETWEEN UNBOUNDED PRECEDING
                                 AND CURRENT ROW
                    ) AS team_run_number
                FROM with_previous
            ),
            returning_teams AS (
                SELECT
                    athlete_id,
                    canonical_team_id,
                    COUNT(DISTINCT team_run_number)
                        AS distinct_team_runs
                FROM numbered_runs
                GROUP BY
                    athlete_id,
                    canonical_team_id
                HAVING COUNT(
                    DISTINCT team_run_number
                ) > 1
            )
            SELECT
                n.athlete_id,
                n.canonical_team_id
                    AS returning_team_id,
                n.canonical_school_id
                    AS returning_school_id,
                n.canonical_school_name
                    AS returning_school_name,
                n.season_year,
                n.season_type,
                n.team_run_number,
                r.distinct_team_runs
            FROM numbered_runs n
            JOIN returning_teams r
              ON n.athlete_id = r.athlete_id
             AND n.canonical_team_id
                    = r.canonical_team_id
            ORDER BY
                n.athlete_id,
                n.season_year,
                n.season_type_order,
                n.canonical_team_id
            """
        ).fetchdf()

        missing_chronology = con.execute(
            """
            SELECT
                athlete_id,
                performance_id,
                canonical_team_id,
                canonical_school_name,
                season_year,
                season_type,
                season_id,
                meet_id,
                meet_name,
                meet_date_text,
                event,
                mark,
                result_url
            FROM eligible
            WHERE season_year IS NULL
               OR NULLIF(season_type, '') IS NULL
               OR NULLIF(season_id, '') IS NULL
               OR NULLIF(canonical_team_id, '') IS NULL
            ORDER BY
                athlete_id,
                performance_id
            """
        ).fetchdf()

        source_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM source.core.performances
            """
        )

        eligible_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM eligible
            """
        )

        distinct_eligible_ids = scalar(
            con,
            """
            SELECT COUNT(DISTINCT performance_id)
            FROM eligible
            """
        )

        eligible_athletes = scalar(
            con,
            """
            SELECT COUNT(DISTINCT athlete_id)
            FROM eligible
            """
        )

        eligible_teams = scalar(
            con,
            """
            SELECT COUNT(DISTINCT canonical_team_id)
            FROM eligible
            """
        )

        athletes_with_multiple_teams = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM (
                SELECT athlete_id
                FROM eligible
                GROUP BY athlete_id
                HAVING COUNT(
                    DISTINCT canonical_team_id
                ) > 1
            )
            """
        )

        athlete_seasons_with_multiple_teams = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    athlete_id,
                    season_year,
                    season_type
                FROM eligible
                GROUP BY
                    athlete_id,
                    season_year,
                    season_type
                HAVING COUNT(
                    DISTINCT canonical_team_id
                ) > 1
            )
            """
        )

        blank_team_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM eligible
            WHERE NULLIF(
                canonical_team_id,
                ''
            ) IS NULL
            """
        )

        non_d1_scope_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM eligible
            WHERE canonical_competition_level
                != 'NCAA_D1'
            """
        )

        duplicate_performance_ids = scalar(
            con,
            """
            SELECT COUNT(*) -
                   COUNT(DISTINCT performance_id)
            FROM eligible
            """
        )

        unknown_season_type_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM eligible
            WHERE season_type NOT IN (
                'cross_country',
                'indoor',
                'outdoor'
            )
            """
        )

        checks = pd.DataFrame(
            [
                (
                    "source_performance_rows_positive",
                    int(source_rows <= 0),
                    source_rows,
                    "> 0",
                ),
                (
                    "eligible_rows_match_distinct_ids",
                    abs(
                        eligible_rows
                        - distinct_eligible_ids
                    ),
                    eligible_rows,
                    distinct_eligible_ids,
                ),
                (
                    "duplicate_eligible_performance_ids",
                    duplicate_performance_ids,
                    duplicate_performance_ids,
                    0,
                ),
                (
                    "blank_canonical_team_rows",
                    blank_team_rows,
                    blank_team_rows,
                    0,
                ),
                (
                    "non_d1_scope_rows_in_stint_layer",
                    non_d1_scope_rows,
                    non_d1_scope_rows,
                    0,
                ),
                (
                    "missing_chronology_rows",
                    len(missing_chronology),
                    len(missing_chronology),
                    0,
                ),
                (
                    "unknown_season_type_rows",
                    unknown_season_type_rows,
                    unknown_season_type_rows,
                    0,
                ),
            ],
            columns=[
                "check_name",
                "failed_row_count",
                "observed_value",
                "expected_value",
            ],
        )

        athlete_team_summary.to_csv(
            OUTPUT_DIR
            / "athlete_team_summary.csv",
            index=False,
        )

        athlete_season_team_summary.to_csv(
            OUTPUT_DIR
            / "athlete_season_team_summary.csv",
            index=False,
        )

        multi_team_same_season.to_csv(
            OUTPUT_DIR
            / "multi_team_same_season_queue.csv",
            index=False,
        )

        team_return_candidates.to_csv(
            OUTPUT_DIR
            / "team_return_candidates.csv",
            index=False,
        )

        missing_chronology.to_csv(
            OUTPUT_DIR
            / "missing_chronology_queue.csv",
            index=False,
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

        report = f"""MILESTONE 4 SCHOOL-STINT RECONSTRUCTION PREFLIGHT
============================================================
Preflight version: {PREFLIGHT_VERSION}
Source database modified: no
Attribution database modified: no

SCOPE
- Source performances: {source_rows:,}
- School-stint-eligible performances: {eligible_rows:,}
- Eligible athletes: {eligible_athletes:,}
- Eligible canonical teams: {eligible_teams:,}
- Athlete-team combinations: {len(athlete_team_summary):,}
- Athlete-season-team combinations: {len(athlete_season_team_summary):,}

TRANSFER COMPLEXITY
- Athletes represented by multiple D1 teams:
  {athletes_with_multiple_teams:,}
- Athlete-season combinations with multiple teams:
  {athlete_seasons_with_multiple_teams:,}
- Multi-team same-season detail rows:
  {len(multi_team_same_season):,}
- Team-return candidate rows:
  {len(team_return_candidates):,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}
- Missing chronology rows: {len(missing_chronology):,}
- Blank canonical team rows: {blank_team_rows:,}
- Non-D1 rows in stint-eligible layer: {non_d1_scope_rows:,}

INTERPRETATION
This preflight does not create school stints. It measures the sequence patterns
that the stint builder must handle, especially athletes appearing for multiple
teams within the same season and athletes who later return to a prior team.
"""

        (
            OUTPUT_DIR
            / "preflight_report.txt"
        ).write_text(
            report,
            encoding="utf-8",
        )

        print(
            "School-stint reconstruction "
            "preflight complete."
        )
        print(f"Outputs: {OUTPUT_DIR}")
        print(f"Failed checks: {failed:,}.")

        if failed:
            raise SystemExit(1)

    finally:
        con.close()


if __name__ == "__main__":
    main()
