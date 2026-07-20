#!/usr/bin/env python3
"""
Milestone 4 Phase 2: school-stint chronology preflight.

This read-only audit reconstructs athlete-team chronology at the meet level
using parsed meet dates. It does not create final school stints and does not
modify the source or attribution databases.

Why meet-level chronology is required
-------------------------------------
Some athletes have performances for multiple D1 teams within the same
season-year and season-type. Season-level ordering alone cannot determine the
transition boundary. Meet dates provide the required chronology.

Outputs
-------
data/processed/milestone4/school_stint_chronology_preflight/
    chronology_report.txt
    hard_checks.csv
    meet_date_parse_summary.csv
    unparsed_meet_dates.csv
    conflicting_meet_metadata.csv
    same_meet_multi_team_queue.csv
    same_date_multi_team_queue.csv
    multi_team_same_season_date_ranges.csv
    candidate_school_runs.csv
    return_team_runs.csv
    single_meet_island_runs.csv
"""

from __future__ import annotations

import argparse
import calendar
import re
from datetime import date
from pathlib import Path
from typing import Any

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
    / "school_stint_chronology_preflight"
)

PREFLIGHT_VERSION = (
    "m4_school_stint_chronology_preflight_v1.2"
)

EXPECTED_ELIGIBLE_ROWS = 6_474_538


MONTH_LOOKUP = {
    name.casefold(): number
    for number, name in enumerate(
        calendar.month_name
    )
    if name
}

MONTH_LOOKUP.update(
    {
        name.casefold(): number
        for number, name in enumerate(
            calendar.month_abbr
        )
        if name
    }
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

    generated = [
        OUTPUT_DIR / "chronology_report.txt",
        OUTPUT_DIR / "hard_checks.csv",
        OUTPUT_DIR / "meet_date_parse_summary.csv",
        OUTPUT_DIR / "unparsed_meet_dates.csv",
        OUTPUT_DIR / "conflicting_meet_metadata.csv",
        OUTPUT_DIR / "same_meet_multi_team_queue.csv",
        OUTPUT_DIR / "same_date_multi_team_queue.csv",
        OUTPUT_DIR
        / "multi_team_same_season_date_ranges.csv",
        OUTPUT_DIR / "candidate_school_runs.csv",
        OUTPUT_DIR / "return_team_runs.csv",
        OUTPUT_DIR / "single_meet_island_runs.csv",
    ]

    existing = [
        path
        for path in generated
        if path.exists()
    ]

    if existing and not replace_output:
        raise FileExistsError(
            "Existing chronology-preflight outputs found. "
            "Use --replace-output only after review."
        )

    if replace_output:
        for path in existing:
            path.unlink()


def clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""

    return " ".join(
        str(value).split()
    ).strip()


def month_number(
    value: str,
) -> int | None:
    token = (
        value.strip()
        .rstrip(".")
        .casefold()
    )

    if token in MONTH_LOOKUP:
        return MONTH_LOOKUP[token]

    short = token[:3]

    return MONTH_LOOKUP.get(short)


def safe_date(
    year: int,
    month: int,
    day: int,
) -> date | None:
    try:
        return date(
            int(year),
            int(month),
            int(day),
        )
    except ValueError:
        return None


def parse_meet_date(
    value: object,
    season_year: object,
) -> dict[str, Any]:
    """
    Parse common TFRRS date strings.

    Supported examples include:
    - Mar 20, 2010
    - Mar 26-27, 2010
    - May 31-Jun 1, 2019
    - Dec 31, 2022-Jan 1, 2023
    - Sep 1
    """

    original = clean(value)

    output: dict[str, Any] = {
        "meet_date_start": pd.NaT,
        "meet_date_end": pd.NaT,
        "date_parse_status": "UNPARSED",
        "date_parse_method": "",
        "date_parse_error": "",
    }

    if not original:
        output["date_parse_error"] = (
            "blank meet_date_text"
        )
        return output

    text = (
        original
        .replace("–", "-")
        .replace("—", "-")
    )

    text = re.sub(
        r"(\d)(st|nd|rd|th)\b",
        r"\1",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    years = [
        int(match)
        for match in re.findall(
            r"\b(?:19|20)\d{2}\b",
            text,
        )
    ]

    fallback_year: int | None = None

    try:
        if season_year is not None and not pd.isna(
            season_year
        ):
            fallback_year = int(season_year)
    except (TypeError, ValueError):
        fallback_year = None

    # Complete two-date range, optionally with two years.
    cross_month = re.search(
        r"""
        (?P<m1>[A-Za-z]{3,9})\.?\s+
        (?P<d1>\d{1,2})
        (?:,\s*(?P<y1>(?:19|20)\d{2}))?
        \s*-\s*
        (?P<m2>[A-Za-z]{3,9})\.?\s+
        (?P<d2>\d{1,2})
        (?:,\s*(?P<y2>(?:19|20)\d{2}))?
        """,
        text,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    if cross_month:
        m1 = month_number(
            cross_month.group("m1")
        )
        m2 = month_number(
            cross_month.group("m2")
        )
        d1 = int(cross_month.group("d1"))
        d2 = int(cross_month.group("d2"))

        y1_raw = cross_month.group("y1")
        y2_raw = cross_month.group("y2")

        if y2_raw:
            y2 = int(y2_raw)
        elif years:
            y2 = years[-1]
        else:
            y2 = fallback_year

        if y1_raw:
            y1 = int(y1_raw)
        elif y2 is not None and m1 is not None and m2 is not None:
            y1 = y2 - 1 if m1 > m2 else y2
        else:
            y1 = fallback_year

        if (
            m1 is not None
            and m2 is not None
            and y1 is not None
            and y2 is not None
        ):
            start = safe_date(
                y1,
                m1,
                d1,
            )
            end = safe_date(
                y2,
                m2,
                d2,
            )

            if start and end:
                output.update(
                    {
                        "meet_date_start": pd.Timestamp(
                            start
                        ),
                        "meet_date_end": pd.Timestamp(
                            end
                        ),
                        "date_parse_status": "PARSED",
                        "date_parse_method": (
                            "CROSS_MONTH_RANGE"
                        ),
                    }
                )
                return output

    # Same-month range: Mar 26-27, 2010
    same_month = re.search(
        r"""
        (?P<m>[A-Za-z]{3,9})\.?\s+
        (?P<d1>\d{1,2})
        \s*-\s*
        (?P<d2>\d{1,2})
        (?:,\s*(?P<y>(?:19|20)\d{2}))?
        """,
        text,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    if same_month:
        month = month_number(
            same_month.group("m")
        )
        year = (
            int(same_month.group("y"))
            if same_month.group("y")
            else (
                years[-1]
                if years
                else fallback_year
            )
        )

        if month is not None and year is not None:
            start = safe_date(
                year,
                month,
                int(same_month.group("d1")),
            )
            end = safe_date(
                year,
                month,
                int(same_month.group("d2")),
            )

            if start and end:
                output.update(
                    {
                        "meet_date_start": pd.Timestamp(
                            start
                        ),
                        "meet_date_end": pd.Timestamp(
                            end
                        ),
                        "date_parse_status": "PARSED",
                        "date_parse_method": (
                            "SAME_MONTH_RANGE"
                        ),
                    }
                )
                return output

    # Single date: Mar 20, 2010 or Sep 1
    single = re.search(
        r"""
        (?P<m>[A-Za-z]{3,9})\.?\s+
        (?P<d>\d{1,2})
        (?:,\s*(?P<y>(?:19|20)\d{2}))?
        """,
        text,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    if single:
        month = month_number(
            single.group("m")
        )
        year = (
            int(single.group("y"))
            if single.group("y")
            else (
                years[-1]
                if years
                else fallback_year
            )
        )

        if month is not None and year is not None:
            parsed = safe_date(
                year,
                month,
                int(single.group("d")),
            )

            if parsed:
                timestamp = pd.Timestamp(
                    parsed
                )

                output.update(
                    {
                        "meet_date_start": timestamp,
                        "meet_date_end": timestamp,
                        "date_parse_status": "PARSED",
                        "date_parse_method": "SINGLE_DATE",
                    }
                )
                return output

    output["date_parse_error"] = (
        f"unsupported date format: {original}"
    )

    return output


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
                a.attribution_precedence,
                a.attribution_confidence,
                p.season_id,
                p.season_year,
                p.season_type,
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

        conflicting_meets = con.execute(
            """
            SELECT
                season_id,
                meet_id,
                COUNT(
                    DISTINCT meet_date_text
                ) AS distinct_date_text_count,
                COUNT(
                    DISTINCT season_year
                ) AS distinct_season_year_count,
                COUNT(
                    DISTINCT season_type
                ) AS distinct_season_type_count,
                STRING_AGG(
                    DISTINCT meet_date_text,
                    ' | '
                    ORDER BY meet_date_text
                ) AS meet_date_text_values,
                STRING_AGG(
                    DISTINCT CAST(
                        season_year AS VARCHAR
                    ),
                    ' | '
                    ORDER BY CAST(
                        season_year AS VARCHAR
                    )
                ) AS season_year_values,
                STRING_AGG(
                    DISTINCT season_type,
                    ' | '
                    ORDER BY season_type
                ) AS season_type_values
            FROM eligible
            GROUP BY
                season_id,
                meet_id
            HAVING COUNT(
                    DISTINCT meet_date_text
                   ) > 1
                OR COUNT(
                    DISTINCT season_year
                   ) > 1
                OR COUNT(
                    DISTINCT season_type
                   ) > 1
            ORDER BY
                season_id,
                meet_id
            """
        ).fetchdf()

        meet_metadata = con.execute(
            """
            SELECT
                season_id,
                meet_id,
                MIN(meet_name)
                    AS meet_name,
                MIN(meet_date_text)
                    AS meet_date_text,
                MIN(season_year)
                    AS season_year,
                MIN(season_type)
                    AS season_type,
                COUNT(*) AS eligible_performance_rows,
                COUNT(DISTINCT athlete_id)
                    AS athlete_count
            FROM eligible
            GROUP BY
                season_id,
                meet_id
            ORDER BY
                season_id,
                meet_id
            """
        ).fetchdf()

        parsed_rows: list[dict[str, Any]] = []

        for record in meet_metadata.itertuples(
            index=False
        ):
            parsed = parse_meet_date(
                value=record.meet_date_text,
                season_year=record.season_year,
            )

            parsed_rows.append(
                {
                    "season_id": str(
                        record.season_id
                    ),
                    "meet_id": str(
                        record.meet_id
                    ),
                    "meet_name": record.meet_name,
                    "meet_date_text": (
                        record.meet_date_text
                    ),
                    "season_year": (
                        record.season_year
                    ),
                    "season_type": (
                        record.season_type
                    ),
                    "eligible_performance_rows": (
                        record.eligible_performance_rows
                    ),
                    "athlete_count": (
                        record.athlete_count
                    ),
                    **parsed,
                }
            )

        meet_dates = pd.DataFrame(
            parsed_rows
        )

        meet_dates[
            "meet_date_start"
        ] = pd.to_datetime(
            meet_dates["meet_date_start"],
            errors="coerce",
        )

        meet_dates[
            "meet_date_end"
        ] = pd.to_datetime(
            meet_dates["meet_date_end"],
            errors="coerce",
        )

        con.register(
            "meet_dates_df",
            meet_dates,
        )

        con.execute(
            """
            CREATE TEMP VIEW meet_dates AS
            SELECT *
            FROM meet_dates_df
            """
        )

        con.execute(
            """
            CREATE TEMP VIEW eligible_dated AS
            SELECT
                e.*,
                d.meet_date_start,
                d.meet_date_end,
                d.date_parse_status,
                d.date_parse_method
            FROM eligible e
            LEFT JOIN meet_dates d
              ON e.season_id = d.season_id
             AND e.meet_id = d.meet_id
            """
        )

        con.execute(
            """
            CREATE TEMP VIEW athlete_meet_team AS
            SELECT
                athlete_id,
                season_id,
                meet_id,
                MIN(meet_name)
                    AS meet_name,
                MIN(meet_date_text)
                    AS meet_date_text,
                MIN(meet_date_start)
                    AS meet_date_start,
                MAX(meet_date_end)
                    AS meet_date_end,
                MIN(season_year)
                    AS season_year,
                MIN(season_type)
                    AS season_type,
                canonical_team_id,
                MIN(canonical_school_id)
                    AS canonical_school_id,
                MIN(canonical_school_name)
                    AS canonical_school_name,
                MIN(canonical_team_name)
                    AS canonical_team_name,
                COUNT(*) AS performance_rows,
                COUNT(DISTINCT event)
                    AS event_count,
                STRING_AGG(
                    DISTINCT attribution_precedence,
                    ' | '
                    ORDER BY attribution_precedence
                ) AS attribution_methods
            FROM eligible_dated
            GROUP BY
                athlete_id,
                season_id,
                meet_id,
                canonical_team_id
            """
        )

        same_meet_multi_team = con.execute(
            """
            WITH conflicts AS (
                SELECT
                    athlete_id,
                    season_id,
                    meet_id,
                    COUNT(
                        DISTINCT canonical_team_id
                    ) AS team_count
                FROM athlete_meet_team
                GROUP BY
                    athlete_id,
                    season_id,
                    meet_id
                HAVING COUNT(
                    DISTINCT canonical_team_id
                ) > 1
            )
            SELECT
                m.athlete_id,
                m.season_id,
                m.meet_id,
                m.meet_name,
                m.meet_date_text,
                m.meet_date_start,
                c.team_count,
                m.canonical_team_id,
                m.canonical_school_id,
                m.canonical_school_name,
                m.canonical_team_name,
                m.performance_rows,
                m.event_count,
                m.attribution_methods
            FROM athlete_meet_team m
            JOIN conflicts c
              ON m.athlete_id = c.athlete_id
             AND m.season_id = c.season_id
             AND m.meet_id = c.meet_id
            ORDER BY
                m.athlete_id,
                m.meet_date_start,
                m.meet_id,
                m.canonical_team_id
            """
        ).fetchdf()

        same_date_multi_team = con.execute(
            """
            WITH date_conflicts AS (
                SELECT
                    athlete_id,
                    meet_date_start,
                    COUNT(
                        DISTINCT canonical_team_id
                    ) AS team_count,
                    COUNT(
                        DISTINCT season_id || '|' || meet_id
                    ) AS meet_count
                FROM athlete_meet_team
                WHERE meet_date_start IS NOT NULL
                GROUP BY
                    athlete_id,
                    meet_date_start
                HAVING COUNT(
                    DISTINCT canonical_team_id
                ) > 1
            )
            SELECT
                m.athlete_id,
                m.meet_date_start,
                d.team_count,
                d.meet_count,
                m.season_id,
                m.meet_id,
                m.meet_name,
                m.canonical_team_id,
                m.canonical_school_id,
                m.canonical_school_name,
                m.canonical_team_name,
                m.performance_rows,
                m.attribution_methods
            FROM athlete_meet_team m
            JOIN date_conflicts d
              ON m.athlete_id = d.athlete_id
             AND m.meet_date_start
                    = d.meet_date_start
            ORDER BY
                m.athlete_id,
                m.meet_date_start,
                m.meet_id,
                m.canonical_team_id
            """
        ).fetchdf()

        multi_team_date_ranges = con.execute(
            """
            WITH season_counts AS (
                SELECT
                    athlete_id,
                    season_year,
                    season_type,
                    COUNT(
                        DISTINCT canonical_team_id
                    ) AS team_count
                FROM athlete_meet_team
                GROUP BY
                    athlete_id,
                    season_year,
                    season_type
                HAVING COUNT(
                    DISTINCT canonical_team_id
                ) > 1
            ),
            ranges AS (
                SELECT
                    m.athlete_id,
                    m.season_year,
                    m.season_type,
                    s.team_count,
                    m.canonical_team_id,
                    MIN(m.canonical_school_id)
                        AS canonical_school_id,
                    MIN(m.canonical_school_name)
                        AS canonical_school_name,
                    MIN(m.canonical_team_name)
                        AS canonical_team_name,
                    MIN(m.meet_date_start)
                        AS first_meet_date,
                    MAX(m.meet_date_end)
                        AS last_meet_date,
                    COUNT(
                        DISTINCT m.season_id || '|' || m.meet_id
                    ) AS meet_count,
                    SUM(m.performance_rows)
                        AS performance_rows
                FROM athlete_meet_team m
                JOIN season_counts s
                  ON m.athlete_id = s.athlete_id
                 AND m.season_year = s.season_year
                 AND m.season_type = s.season_type
                GROUP BY
                    m.athlete_id,
                    m.season_year,
                    m.season_type,
                    s.team_count,
                    m.canonical_team_id
            )
            SELECT
                *,
                LAG(last_meet_date)
                    OVER (
                        PARTITION BY
                            athlete_id,
                            season_year,
                            season_type
                        ORDER BY
                            first_meet_date,
                            last_meet_date,
                            canonical_team_id
                    ) AS previous_team_last_date,
                CASE
                    WHEN LAG(last_meet_date)
                        OVER (
                            PARTITION BY
                                athlete_id,
                                season_year,
                                season_type
                            ORDER BY
                                first_meet_date,
                                last_meet_date,
                                canonical_team_id
                        ) IS NULL
                    THEN 'FIRST_TEAM_RANGE'

                    WHEN first_meet_date >
                         LAG(last_meet_date)
                         OVER (
                            PARTITION BY
                                athlete_id,
                                season_year,
                                season_type
                            ORDER BY
                                first_meet_date,
                                last_meet_date,
                                canonical_team_id
                         )
                    THEN 'NON_OVERLAPPING_AFTER_PRIOR'

                    ELSE 'OVERLAPPING_PRIOR_RANGE'
                END AS range_relation
            FROM ranges
            ORDER BY
                athlete_id,
                season_year,
                CASE
                    WHEN season_type = 'indoor'
                    THEN 1
                    WHEN season_type = 'outdoor'
                    THEN 2
                    WHEN season_type = 'cross_country'
                    THEN 3
                    ELSE 9
                END,
                first_meet_date,
                canonical_team_id
            """
        ).fetchdf()

        con.execute(
            """
            CREATE TEMP VIEW candidate_runs AS
            WITH ordered_meets AS (
                SELECT
                    *,
                    LAG(canonical_team_id)
                        OVER (
                            PARTITION BY athlete_id
                            ORDER BY
                                meet_date_start,
                                meet_date_end,
                                season_id,
                                meet_id,
                                canonical_team_id
                        ) AS previous_team_id
                FROM athlete_meet_team
                WHERE meet_date_start IS NOT NULL
            ),
            run_flags AS (
                SELECT
                    *,
                    CASE
                        WHEN previous_team_id IS NULL
                          OR canonical_team_id
                                != previous_team_id
                        THEN 1
                        ELSE 0
                    END AS starts_new_run
                FROM ordered_meets
            ),
            numbered AS (
                SELECT
                    *,
                    SUM(starts_new_run)
                        OVER (
                            PARTITION BY athlete_id
                            ORDER BY
                                meet_date_start,
                                meet_date_end,
                                season_id,
                                meet_id,
                                canonical_team_id
                            ROWS BETWEEN
                                UNBOUNDED PRECEDING
                                AND CURRENT ROW
                        ) AS team_run_number
                FROM run_flags
            )
            SELECT
                athlete_id,
                team_run_number,
                canonical_team_id,
                MIN(canonical_school_id)
                    AS canonical_school_id,
                MIN(canonical_school_name)
                    AS canonical_school_name,
                MIN(canonical_team_name)
                    AS canonical_team_name,
                MIN(meet_date_start)
                    AS stint_start_date,
                MAX(meet_date_end)
                    AS stint_end_date,
                MIN(season_year)
                    AS first_season_year,
                MAX(season_year)
                    AS last_season_year,
                MIN_BY(
                    season_type,
                    meet_date_start
                ) AS first_season_type,
                MAX_BY(
                    season_type,
                    meet_date_end
                ) AS last_season_type,
                COUNT(
                    DISTINCT season_id || '|' || meet_id
                ) AS meet_count,
                SUM(performance_rows)
                    AS performance_rows,
                STRING_AGG(
                    DISTINCT attribution_methods,
                    ' | '
                    ORDER BY attribution_methods
                ) AS attribution_methods
            FROM numbered
            GROUP BY
                athlete_id,
                team_run_number,
                canonical_team_id
            """
        )

        candidate_runs = con.execute(
            """
            SELECT *
            FROM candidate_runs
            ORDER BY
                athlete_id,
                team_run_number
            """
        ).fetchdf()

        return_runs = con.execute(
            """
            WITH returning_teams AS (
                SELECT
                    athlete_id,
                    canonical_team_id,
                    COUNT(*) AS distinct_team_runs
                FROM candidate_runs
                GROUP BY
                    athlete_id,
                    canonical_team_id
                HAVING COUNT(*) > 1
            )
            SELECT
                r.athlete_id,
                r.canonical_team_id,
                r.distinct_team_runs,
                c.team_run_number,
                c.canonical_school_id,
                c.canonical_school_name,
                c.canonical_team_name,
                c.stint_start_date,
                c.stint_end_date,
                c.first_season_year,
                c.last_season_year,
                c.first_season_type,
                c.last_season_type,
                c.meet_count,
                c.performance_rows,
                c.attribution_methods
            FROM returning_teams r
            JOIN candidate_runs c
              ON r.athlete_id = c.athlete_id
             AND r.canonical_team_id
                    = c.canonical_team_id
            ORDER BY
                r.athlete_id,
                c.team_run_number
            """
        ).fetchdf()

        single_meet_islands = con.execute(
            """
            WITH sequenced AS (
                SELECT
                    *,
                    LAG(canonical_team_id)
                        OVER (
                            PARTITION BY athlete_id
                            ORDER BY team_run_number
                        ) AS prior_run_team_id,
                    LEAD(canonical_team_id)
                        OVER (
                            PARTITION BY athlete_id
                            ORDER BY team_run_number
                        ) AS next_run_team_id
                FROM candidate_runs
            )
            SELECT *
            FROM sequenced
            WHERE meet_count = 1
              AND prior_run_team_id IS NOT NULL
              AND next_run_team_id IS NOT NULL
              AND prior_run_team_id
                    = next_run_team_id
              AND canonical_team_id
                    != prior_run_team_id
            ORDER BY
                athlete_id,
                team_run_number
            """
        ).fetchdf()

        parse_summary = (
            meet_dates.groupby(
                [
                    "date_parse_status",
                    "date_parse_method",
                ],
                dropna=False,
            )
            .agg(
                meet_count=(
                    "meet_id",
                    "nunique",
                ),
                performance_rows=(
                    "eligible_performance_rows",
                    "sum",
                ),
            )
            .reset_index()
            .sort_values(
                [
                    "date_parse_status",
                    "meet_count",
                ],
                ascending=[
                    True,
                    False,
                ],
            )
        )

        unparsed_meets = meet_dates.loc[
            meet_dates[
                "date_parse_status"
            ].ne("PARSED")
        ].copy()

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
            SELECT COUNT(
                DISTINCT performance_id
            )
            FROM eligible
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

        performance_rows_without_dates = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM eligible_dated
            WHERE meet_date_start IS NULL
               OR meet_date_end IS NULL
            """
        )

        invalid_date_range_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM meet_dates
            WHERE meet_date_start IS NOT NULL
              AND meet_date_end IS NOT NULL
              AND meet_date_end
                    < meet_date_start
            """
        )

        same_meet_conflict_groups = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    athlete_id,
                    season_id,
                    meet_id
                FROM athlete_meet_team
                GROUP BY
                    athlete_id,
                    season_id,
                    meet_id
                HAVING COUNT(
                    DISTINCT canonical_team_id
                ) > 1
            )
            """
        )

        same_date_conflict_groups = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    athlete_id,
                    meet_date_start
                FROM athlete_meet_team
                WHERE meet_date_start IS NOT NULL
                GROUP BY
                    athlete_id,
                    meet_date_start
                HAVING COUNT(
                    DISTINCT canonical_team_id
                ) > 1
            )
            """
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
                    "distinct_eligible_performance_ids",
                    abs(
                        distinct_eligible_ids
                        - EXPECTED_ELIGIBLE_ROWS
                    ),
                    distinct_eligible_ids,
                    EXPECTED_ELIGIBLE_ROWS,
                ),
                (
                    "duplicate_eligible_performance_ids",
                    eligible_rows
                    - distinct_eligible_ids,
                    eligible_rows
                    - distinct_eligible_ids,
                    0,
                ),
                (
                    "blank_canonical_team_rows",
                    blank_team_rows,
                    blank_team_rows,
                    0,
                ),
                (
                    "conflicting_meet_metadata_rows",
                    len(conflicting_meets),
                    len(conflicting_meets),
                    0,
                ),
                (
                    "unparsed_unique_meets",
                    len(unparsed_meets),
                    len(unparsed_meets),
                    0,
                ),
                (
                    "performance_rows_without_dates",
                    performance_rows_without_dates,
                    performance_rows_without_dates,
                    0,
                ),
                (
                    "invalid_meet_date_ranges",
                    invalid_date_range_rows,
                    invalid_date_range_rows,
                    0,
                ),
                (
                    "same_meet_multi_team_groups",
                    same_meet_conflict_groups,
                    same_meet_conflict_groups,
                    0,
                ),
                (
                    "same_date_multi_team_groups",
                    same_date_conflict_groups,
                    same_date_conflict_groups,
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

        parse_summary.to_csv(
            OUTPUT_DIR
            / "meet_date_parse_summary.csv",
            index=False,
        )

        unparsed_meets.to_csv(
            OUTPUT_DIR
            / "unparsed_meet_dates.csv",
            index=False,
        )

        conflicting_meets.to_csv(
            OUTPUT_DIR
            / "conflicting_meet_metadata.csv",
            index=False,
        )

        same_meet_multi_team.to_csv(
            OUTPUT_DIR
            / "same_meet_multi_team_queue.csv",
            index=False,
        )

        same_date_multi_team.to_csv(
            OUTPUT_DIR
            / "same_date_multi_team_queue.csv",
            index=False,
        )

        multi_team_date_ranges.to_csv(
            OUTPUT_DIR
            / "multi_team_same_season_date_ranges.csv",
            index=False,
        )

        candidate_runs.to_csv(
            OUTPUT_DIR
            / "candidate_school_runs.csv",
            index=False,
        )

        return_runs.to_csv(
            OUTPUT_DIR
            / "return_team_runs.csv",
            index=False,
        )

        single_meet_islands.to_csv(
            OUTPUT_DIR
            / "single_meet_island_runs.csv",
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

        candidate_run_athletes = int(
            candidate_runs[
                "athlete_id"
            ].nunique()
        )

        multi_run_athletes = int(
            (
                candidate_runs.groupby(
                    "athlete_id"
                ).size() > 1
            ).sum()
        )

        return_athletes = int(
            return_runs[
                "athlete_id"
            ].nunique()
            if not return_runs.empty
            else 0
        )

        report = f"""MILESTONE 4 SCHOOL-STINT CHRONOLOGY PREFLIGHT
============================================================
Preflight version: {PREFLIGHT_VERSION}
Source database modified: no
Attribution database modified: no

SCOPE
- School-stint-eligible performances: {eligible_rows:,}
- Distinct eligible meet instances: {len(meet_dates):,}
- Candidate meet-level school runs: {len(candidate_runs):,}
- Athletes represented in candidate runs: {candidate_run_athletes:,}
- Athletes with more than one candidate run: {multi_run_athletes:,}

DATE PARSING
- Parsed unique meets: {len(meet_dates) - len(unparsed_meets):,}
- Unparsed unique meets: {len(unparsed_meets):,}
- Performance rows without parsed dates: {performance_rows_without_dates:,}
- Conflicting meet metadata rows: {len(conflicting_meets):,}

CHRONOLOGY CONFLICTS
- Same athlete and meet with multiple teams:
  {same_meet_conflict_groups:,} groups / {len(same_meet_multi_team):,} detail rows
- Same athlete and date with multiple teams:
  {same_date_conflict_groups:,} groups / {len(same_date_multi_team):,} detail rows
- Same-season team date-range detail rows:
  {len(multi_team_date_ranges):,}

RETURN AND ISLAND PATTERNS
- Athletes returning to a prior team:
  {return_athletes:,}
- Return-team run rows:
  {len(return_runs):,}
- Single-meet A-B-A island runs:
  {len(single_meet_islands):,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

INTERPRETATION
Candidate runs are based on actual meet dates rather than season-label order.
Meet identity uses the composite key season_id plus meet_id because provider
meet IDs are reused across seasons. Same-meet-instance or same-date multi-team
conflicts are blocking because one athlete cannot represent two schools
simultaneously. Single-meet A-B-A islands require
review before final school stints are created because they may be isolated
attribution errors rather than genuine transfers.
"""

        (
            OUTPUT_DIR
            / "chronology_report.txt"
        ).write_text(
            report,
            encoding="utf-8",
        )

        print(
            "School-stint chronology "
            "preflight complete."
        )
        print(f"Outputs: {OUTPUT_DIR}")
        print(f"Failed checks: {failed:,}.")

        if failed:
            raise SystemExit(1)

    finally:
        try:
            con.unregister(
                "meet_dates_df"
            )
        except Exception:
            pass

        con.close()


if __name__ == "__main__":
    main()
