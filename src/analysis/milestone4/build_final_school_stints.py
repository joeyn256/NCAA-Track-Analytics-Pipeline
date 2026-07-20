#!/usr/bin/env python3
"""
Milestone 4: build final canonical-person D1 school stints.

Input
-----
data/processed/milestone4/canonical_person_layer_v1_1/
    canonical_person_layer_v1_1.duckdb

Output
------
data/processed/milestone4/final_school_stints/
    final_school_stints.duckdb
    school_stint_report.txt
    hard_checks.csv
    stint_count_distribution.csv
    team_stint_summary.csv
    chronology_parse_summary.csv
    transfer_person_summary.csv
    single_meet_aba_islands.csv
    same_day_multi_team_groups.csv
    known_identity_validation.csv

The input database is attached read-only and is never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from datetime import date
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

PERSON_CHECKS = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_person_layer_v1_1/"
    / "hard_checks.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "final_school_stints"
)

OUTPUT_DB = (
    OUTPUT_DIR
    / "final_school_stints.duckdb"
)

STINT_VERSION = (
    "m4_final_school_stints_v1.0"
)

KNOWN_IDENTITY_PAIRS = {
    "emily_venters": (
        "6550332",
        "7905593",
    ),
    "daniella_hubble": (
        "7913457",
        "8932241",
    ),
}

MONTH_NUMBERS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

MONTH_PATTERN = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|"
    r"Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)

DATE_PATTERN = re.compile(
    rf"""
    (?P<month1>{MONTH_PATTERN})
    \s+
    (?P<day1>\d{{1,2}})
    (?:
        \s*[-–—]\s*
        (?:
            (?P<month2>{MONTH_PATTERN})
            \s*
        )?
        (?P<day2>\d{{1,2}})
    )?
    (?:,\s*|\s+)
    (?P<year>\d{{4}})
    """,
    re.IGNORECASE | re.VERBOSE,
)

SINGLE_DATE_WITHOUT_YEAR_PATTERN = re.compile(
    rf"""
    (?P<month1>{MONTH_PATTERN})
    \s+
    (?P<day1>\d{{1,2}})
    """,
    re.IGNORECASE | re.VERBOSE,
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


def file_state(path: Path) -> dict[str, int]:
    stat = path.stat()

    return {
        "size_bytes": int(stat.st_size),
        "modified_ns": int(stat.st_mtime_ns),
    }


def require_inputs() -> None:
    for path in [
        PERSON_DB,
        PERSON_CHECKS,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )

    checks = pd.read_csv(PERSON_CHECKS)

    failed = checks[
        checks["failed_row_count"] > 0
    ]

    if not failed.empty:
        raise RuntimeError(
            "The final canonical-person layer has "
            "failed hard checks. School-stint "
            "construction is blocked."
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
        OUTPUT_DIR / "school_stint_report.txt",
        OUTPUT_DIR / "hard_checks.csv",
        OUTPUT_DIR / "stint_count_distribution.csv",
        OUTPUT_DIR / "team_stint_summary.csv",
        OUTPUT_DIR / "chronology_parse_summary.csv",
        OUTPUT_DIR / "transfer_person_summary.csv",
        OUTPUT_DIR / "single_meet_aba_islands.csv",
        OUTPUT_DIR / "same_day_multi_team_groups.csv",
        OUTPUT_DIR / "known_identity_validation.csv",
    ]

    existing = [
        path
        for path in generated
        if path.exists()
    ]

    if existing and not replace_output:
        raise FileExistsError(
            "Final school-stint outputs already exist. "
            "Use --replace-output only after reviewing "
            "the existing build."
        )

    if replace_output:
        for path in existing:
            path.unlink()


def normalize_month(value: str) -> int:
    key = value.strip().lower()

    if key not in MONTH_NUMBERS:
        raise ValueError(
            f"Unsupported month token: {value}"
        )

    return MONTH_NUMBERS[key]


def parse_meet_start_date(
    meet_date_text: object,
    season_year: object,
) -> tuple[date, str]:
    text = str(meet_date_text or "").strip()

    try:
        fallback_year = int(season_year)
    except (TypeError, ValueError):
        fallback_year = 1900

    if text:
        normalized = (
            text.replace("\u00a0", " ")
            .replace("\u2011", "-")
            .replace("\u2012", "-")
            .replace("\u2013", "-")
            .replace("\u2014", "-")
        )

        normalized = re.sub(
            r"\s+",
            " ",
            normalized,
        ).strip()

        match = DATE_PATTERN.search(
            normalized
        )

        if match:
            month1 = normalize_month(
                match.group("month1")
            )

            day1 = int(
                match.group("day1")
            )

            year = int(
                match.group("year")
            )

            month2_token = match.group(
                "month2"
            )

            if month2_token:
                month2 = normalize_month(
                    month2_token
                )

                if (
                    month1 == 12
                    and month2 == 1
                ):
                    year -= 1

            try:
                return (
                    date(
                        year,
                        month1,
                        day1,
                    ),
                    "PARSED_EXPLICIT_YEAR",
                )
            except ValueError:
                pass

        match_without_year = (
            SINGLE_DATE_WITHOUT_YEAR_PATTERN
            .search(normalized)
        )

        if match_without_year:
            month1 = normalize_month(
                match_without_year.group(
                    "month1"
                )
            )

            day1 = int(
                match_without_year.group(
                    "day1"
                )
            )

            try:
                return (
                    date(
                        fallback_year,
                        month1,
                        day1,
                    ),
                    "PARSED_SEASON_YEAR_FALLBACK",
                )
            except ValueError:
                pass

    season_type_month = {
        "indoor": 2,
        "outdoor": 4,
        "cross_country": 10,
    }

    return (
        date(
            fallback_year,
            season_type_month.get(
                "",
                7,
            ),
            15,
        ),
        "SYNTHETIC_YEAR_ONLY",
    )


def fallback_chronology_date(
    season_year: object,
    season_type: object,
) -> date:
    try:
        year = int(season_year)
    except (TypeError, ValueError):
        year = 1900

    month = {
        "indoor": 2,
        "outdoor": 4,
        "cross_country": 10,
    }.get(
        str(season_type or "").lower(),
        7,
    )

    return date(
        year,
        month,
        15,
    )


def build_stint_id(
    canonical_person_id: str,
    stint_sequence: int,
    canonical_team_id: str,
) -> str:
    raw = (
        f"{canonical_person_id}\x1f"
        f"{stint_sequence}\x1f"
        f"{canonical_team_id}"
    )

    digest = hashlib.sha1(
        raw.encode("utf-8")
    ).hexdigest()[:20]

    return f"m4stint_{digest}"


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

        print(
            "Auditing school-stint input..."
        )

        input_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM person
                .school_stint_person_performances
            """,
        )

        distinct_input_ids = scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT
                canonical_person_performance_id
            )
            FROM person
                .school_stint_person_performances
            """,
        )

        blank_key_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM person
                .school_stint_person_performances
            WHERE NULLIF(
                    canonical_person_id,
                    ''
                  ) IS NULL
               OR NULLIF(
                    canonical_person_performance_id,
                    ''
                  ) IS NULL
               OR NULLIF(
                    canonical_team_id,
                    ''
                  ) IS NULL
               OR NULLIF(
                    season_id,
                    ''
                  ) IS NULL
               OR NULLIF(
                    meet_id,
                    ''
                  ) IS NULL
            """,
        )

        meet_team_conflicts = con.execute(
            """
            SELECT
                canonical_person_id,
                season_id,
                meet_id,
                COUNT(
                    DISTINCT canonical_team_id
                ) AS team_count,
                STRING_AGG(
                    DISTINCT canonical_team_id,
                    ' | '
                    ORDER BY canonical_team_id
                ) AS canonical_team_ids,
                MIN(meet_name) AS meet_name,
                MIN(meet_date_text)
                    AS meet_date_text
            FROM person
                .school_stint_person_performances
            GROUP BY
                canonical_person_id,
                season_id,
                meet_id
            HAVING COUNT(
                DISTINCT canonical_team_id
            ) > 1
            ORDER BY
                team_count DESC,
                canonical_person_id,
                season_id,
                meet_id
            """
        ).fetchdf()

        if not meet_team_conflicts.empty:
            meet_team_conflicts.to_csv(
                OUTPUT_DIR
                / "same_day_multi_team_groups.csv",
                index=False,
            )

            raise RuntimeError(
                "At least one canonical person has "
                "multiple teams inside the same "
                "season+meet. Final stint construction "
                "is blocked."
            )

        print(
            "Building meet-level team assignments..."
        )

        meet_assignments = con.execute(
            """
            SELECT
                canonical_person_id,
                season_id,
                MIN(season_year)
                    AS season_year,
                MIN(season_type)
                    AS season_type,
                meet_id,
                MIN(meet_name)
                    AS meet_name,
                MIN(meet_date_text)
                    AS meet_date_text,

                canonical_team_id,
                MIN(canonical_team_name)
                    AS canonical_team_name,
                MIN(canonical_school_id)
                    AS canonical_school_id,
                MIN(canonical_school_name)
                    AS canonical_school_name,
                MIN(canonical_gender_code)
                    AS canonical_gender_code,

                COUNT(*)
                    AS canonical_performance_count,
                COUNT(
                    DISTINCT event
                ) AS distinct_event_count,
                COUNT(
                    DISTINCT representative_athlete_id
                ) AS representative_profile_count

            FROM person
                .school_stint_person_performances

            GROUP BY
                canonical_person_id,
                season_id,
                meet_id,
                canonical_team_id
            """
        ).fetchdf()

        print(
            "Parsing meet dates and assigning "
            "chronological stint sequences..."
        )

        unique_date_inputs = (
            meet_assignments[
                [
                    "meet_date_text",
                    "season_year",
                    "season_type",
                ]
            ]
            .drop_duplicates()
            .copy()
        )

        parsed_dates = []

        for row in unique_date_inputs.itertuples(
            index=False
        ):
            parsed_date, parse_status = (
                parse_meet_start_date(
                    row.meet_date_text,
                    row.season_year,
                )
            )

            if (
                parse_status
                == "SYNTHETIC_YEAR_ONLY"
            ):
                parsed_date = (
                    fallback_chronology_date(
                        row.season_year,
                        row.season_type,
                    )
                )

            parsed_dates.append(
                (
                    parsed_date,
                    parse_status,
                )
            )

        unique_date_inputs[
            [
                "chronology_date",
                "date_parse_status",
            ]
        ] = pd.DataFrame(
            parsed_dates,
            index=unique_date_inputs.index,
        )

        meet_assignments = (
            meet_assignments.merge(
                unique_date_inputs,
                on=[
                    "meet_date_text",
                    "season_year",
                    "season_type",
                ],
                how="left",
                validate="many_to_one",
            )
        )

        meet_assignments[
            "meet_id_numeric"
        ] = pd.to_numeric(
            meet_assignments["meet_id"],
            errors="coerce",
        ).fillna(
            9_999_999_999
        ).astype("int64")

        meet_assignments[
            "season_type_order"
        ] = (
            meet_assignments[
                "season_type"
            ]
            .astype(str)
            .str.lower()
            .map(
                {
                    "indoor": 1,
                    "outdoor": 2,
                    "cross_country": 3,
                }
            )
            .fillna(9)
            .astype("int64")
        )

        meet_assignments = (
            meet_assignments.sort_values(
                [
                    "canonical_person_id",
                    "chronology_date",
                    "season_year",
                    "season_type_order",
                    "meet_id_numeric",
                    "meet_id",
                    "canonical_team_id",
                ],
                kind="mergesort",
            )
            .reset_index(drop=True)
        )

        meet_assignments[
            "person_meet_sequence"
        ] = (
            meet_assignments.groupby(
                "canonical_person_id",
                sort=False,
            )
            .cumcount()
            + 1
        )

        meet_assignments[
            "prior_team_id"
        ] = (
            meet_assignments.groupby(
                "canonical_person_id",
                sort=False,
            )["canonical_team_id"]
            .shift(1)
        )

        meet_assignments[
            "starts_new_stint"
        ] = (
            meet_assignments[
                "prior_team_id"
            ].isna()
            | (
                meet_assignments[
                    "canonical_team_id"
                ]
                != meet_assignments[
                    "prior_team_id"
                ]
            )
        )

        meet_assignments[
            "stint_sequence"
        ] = (
            meet_assignments[
                "starts_new_stint"
            ]
            .astype("int64")
            .groupby(
                meet_assignments[
                    "canonical_person_id"
                ],
                sort=False,
            )
            .cumsum()
        )

        meet_assignments[
            "school_stint_id"
        ] = [
            build_stint_id(
                str(person_id),
                int(stint_sequence),
                str(team_id),
            )
            for (
                person_id,
                stint_sequence,
                team_id,
            ) in zip(
                meet_assignments[
                    "canonical_person_id"
                ],
                meet_assignments[
                    "stint_sequence"
                ],
                meet_assignments[
                    "canonical_team_id"
                ],
                strict=True,
            )
        ]

        same_day_scope = meet_assignments[
            meet_assignments[
                "date_parse_status"
            ].ne(
                "SYNTHETIC_YEAR_ONLY"
            )
        ].copy()

        same_day_multi_team = (
            same_day_scope.groupby(
                [
                    "canonical_person_id",
                    "chronology_date",
                ],
                dropna=False,
            )
            .agg(
                canonical_team_count=(
                    "canonical_team_id",
                    "nunique",
                ),
                meet_count=(
                    "meet_id",
                    "nunique",
                ),
                canonical_team_ids=(
                    "canonical_team_id",
                    lambda values: " | ".join(
                        sorted(
                            set(
                                map(str, values)
                            )
                        )
                    ),
                ),
                meet_ids=(
                    "meet_id",
                    lambda values: " | ".join(
                        sorted(
                            set(
                                map(str, values)
                            )
                        )
                    ),
                ),
            )
            .reset_index()
        )

        same_day_multi_team = (
            same_day_multi_team[
                same_day_multi_team[
                    "canonical_team_count"
                ] > 1
            ]
            .copy()
        )

        same_day_multi_team.to_csv(
            OUTPUT_DIR
            / "same_day_multi_team_groups.csv",
            index=False,
        )

        con.register(
            "meet_assignments_input",
            meet_assignments,
        )

        con.execute(
            """
            CREATE TABLE person_meet_team_assignments AS
            SELECT
                canonical_person_id,
                CAST(
                    person_meet_sequence
                    AS BIGINT
                ) AS person_meet_sequence,

                school_stint_id,
                CAST(
                    stint_sequence
                    AS BIGINT
                ) AS stint_sequence,

                season_id,
                CAST(
                    season_year
                    AS INTEGER
                ) AS season_year,
                season_type,

                meet_id,
                meet_name,
                meet_date_text,
                CAST(
                    chronology_date
                    AS DATE
                ) AS chronology_date,
                date_parse_status,

                canonical_team_id,
                canonical_team_name,
                canonical_school_id,
                canonical_school_name,
                canonical_gender_code,

                CAST(
                    canonical_performance_count
                    AS BIGINT
                ) AS canonical_performance_count,

                CAST(
                    distinct_event_count
                    AS BIGINT
                ) AS distinct_event_count,

                CAST(
                    representative_profile_count
                    AS BIGINT
                ) AS representative_profile_count,

                prior_team_id,
                starts_new_stint,

                ?
                    AS school_stint_version

            FROM meet_assignments_input
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

        print(
            "Building canonical-person school stints..."
        )

        con.execute(
            """
            CREATE TABLE canonical_person_school_stints AS
            WITH summarized AS (
                SELECT
                    school_stint_id,
                    canonical_person_id,
                    stint_sequence,

                    MIN(canonical_team_id)
                        AS canonical_team_id,
                    MIN(canonical_team_name)
                        AS canonical_team_name,
                    MIN(canonical_school_id)
                        AS canonical_school_id,
                    MIN(canonical_school_name)
                        AS canonical_school_name,
                    MIN(canonical_gender_code)
                        AS canonical_gender_code,

                    MIN(chronology_date)
                        AS stint_start_date,
                    MAX(chronology_date)
                        AS stint_end_date,

                    ARG_MIN(
                        season_id,
                        person_meet_sequence
                    ) AS stint_start_season_id,

                    ARG_MAX(
                        season_id,
                        person_meet_sequence
                    ) AS stint_end_season_id,

                    ARG_MIN(
                        meet_id,
                        person_meet_sequence
                    ) AS first_meet_id,

                    ARG_MAX(
                        meet_id,
                        person_meet_sequence
                    ) AS last_meet_id,

                    ARG_MIN(
                        meet_name,
                        person_meet_sequence
                    ) AS first_meet_name,

                    ARG_MAX(
                        meet_name,
                        person_meet_sequence
                    ) AS last_meet_name,

                    COUNT(*)
                        AS meet_count,

                    SUM(
                        canonical_performance_count
                    ) AS canonical_performance_count,

                    SUM(
                        distinct_event_count
                    ) AS meet_event_count_sum,

                    MIN(person_meet_sequence)
                        AS first_person_meet_sequence,

                    MAX(person_meet_sequence)
                        AS last_person_meet_sequence

                FROM person_meet_team_assignments

                GROUP BY
                    school_stint_id,
                    canonical_person_id,
                    stint_sequence
            ),

            with_neighbors AS (
                SELECT
                    *,

                    LAG(canonical_team_id)
                        OVER (
                            PARTITION BY
                                canonical_person_id
                            ORDER BY
                                stint_sequence
                        ) AS prior_stint_team_id,

                    LEAD(canonical_team_id)
                        OVER (
                            PARTITION BY
                                canonical_person_id
                            ORDER BY
                                stint_sequence
                        ) AS next_stint_team_id,

                    COUNT(*)
                        OVER (
                            PARTITION BY
                                canonical_person_id
                        ) AS person_stint_count

                FROM summarized
            )

            SELECT
                *,

                CASE
                    WHEN stint_sequence = 1
                    THEN FALSE
                    ELSE TRUE
                END AS begins_after_team_change,

                CASE
                    WHEN prior_stint_team_id
                            IS NOT NULL
                     AND next_stint_team_id
                            = prior_stint_team_id
                     AND canonical_team_id
                            != prior_stint_team_id
                     AND meet_count = 1
                    THEN TRUE
                    ELSE FALSE
                END AS is_single_meet_aba_island,

                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM summarized earlier
                        WHERE
                            earlier.canonical_person_id
                                =
                                with_neighbors
                                .canonical_person_id
                          AND earlier.stint_sequence
                                <
                                with_neighbors
                                .stint_sequence
                          AND earlier.canonical_team_id
                                =
                                with_neighbors
                                .canonical_team_id
                    )
                    THEN TRUE
                    ELSE FALSE
                END AS returns_to_prior_team,

                ?
                    AS school_stint_version

            FROM with_neighbors
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

        print(
            "Mapping every eligible performance "
            "to exactly one school stint..."
        )

        con.execute(
            """
            CREATE TABLE school_stint_performance_map AS
            SELECT
                p.canonical_person_performance_id,
                p.canonical_person_id,
                m.school_stint_id,
                m.stint_sequence,
                p.canonical_team_id,
                p.season_id,
                p.meet_id,
                ?
                    AS school_stint_version

            FROM person
                .school_stint_person_performances p

            JOIN person_meet_team_assignments m
              ON p.canonical_person_id
                    = m.canonical_person_id
             AND p.season_id
                    = m.season_id
             AND p.meet_id
                    = m.meet_id
             AND p.canonical_team_id
                    = m.canonical_team_id
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

        print(
            "Building school-stint audit outputs..."
        )

        aba_islands = con.execute(
            """
            SELECT *
            FROM canonical_person_school_stints
            WHERE is_single_meet_aba_island
            ORDER BY
                canonical_person_id,
                stint_sequence
            """
        ).fetchdf()

        aba_islands.to_csv(
            OUTPUT_DIR
            / "single_meet_aba_islands.csv",
            index=False,
        )

        stint_count_distribution = con.execute(
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

        stint_count_distribution.to_csv(
            OUTPUT_DIR
            / "stint_count_distribution.csv",
            index=False,
        )

        team_stint_summary = con.execute(
            """
            SELECT
                canonical_team_id,
                canonical_team_name,
                canonical_school_id,
                canonical_school_name,
                canonical_gender_code,

                COUNT(*)
                    AS school_stint_count,

                COUNT(
                    DISTINCT canonical_person_id
                ) AS canonical_person_count,

                SUM(meet_count)
                    AS meet_count,

                SUM(
                    canonical_performance_count
                ) AS canonical_performance_count,

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

        team_stint_summary.to_csv(
            OUTPUT_DIR
            / "team_stint_summary.csv",
            index=False,
        )

        chronology_parse_summary = con.execute(
            """
            SELECT
                date_parse_status,
                COUNT(*) AS meet_assignment_count,
                COUNT(
                    DISTINCT meet_id
                ) AS distinct_meet_id_count,
                COUNT(
                    DISTINCT canonical_person_id
                ) AS canonical_person_count
            FROM person_meet_team_assignments
            GROUP BY date_parse_status
            ORDER BY
                meet_assignment_count DESC,
                date_parse_status
            """
        ).fetchdf()

        chronology_parse_summary.to_csv(
            OUTPUT_DIR
            / "chronology_parse_summary.csv",
            index=False,
        )

        transfer_person_summary = con.execute(
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

                SUM(meet_count)
                    AS meet_count,

                SUM(
                    canonical_performance_count
                ) AS canonical_performance_count,

                BOOL_OR(returns_to_prior_team)
                    AS returns_to_prior_team

            FROM canonical_person_school_stints

            GROUP BY canonical_person_id

            HAVING MAX(person_stint_count) > 1

            ORDER BY
                school_stint_count DESC,
                canonical_person_id
            """
        ).fetchdf()

        transfer_person_summary.to_csv(
            OUTPUT_DIR
            / "transfer_person_summary.csv",
            index=False,
        )

        known_rows = []

        for label, athlete_ids in (
            KNOWN_IDENTITY_PAIRS.items()
        ):
            placeholders = ", ".join(
                ["?"] * len(athlete_ids)
            )

            bridge = con.execute(
                f"""
                SELECT
                    athlete_id,
                    canonical_person_id
                FROM person
                    .canonical_person_bridge
                WHERE athlete_id IN (
                    {placeholders}
                )
                ORDER BY athlete_id
                """,
                list(athlete_ids),
            ).fetchdf()

            person_ids = (
                bridge[
                    "canonical_person_id"
                ]
                .dropna()
                .astype(str)
                .unique()
                .tolist()
            )

            island_count = 0
            stint_count = 0
            team_sequence = ""

            if len(person_ids) == 1:
                person_id = person_ids[0]

                validation = con.execute(
                    """
                    SELECT
                        COUNT(*)
                            AS stint_count,

                        SUM(
                            CASE
                                WHEN
                                    is_single_meet_aba_island
                                THEN 1
                                ELSE 0
                            END
                        ) AS island_count,

                        STRING_AGG(
                            canonical_team_id,
                            ' -> '
                            ORDER BY stint_sequence
                        ) AS team_sequence

                    FROM
                        canonical_person_school_stints

                    WHERE canonical_person_id = ?
                    """,
                    [person_id],
                ).fetchone()

                stint_count = int(
                    validation[0] or 0
                )

                island_count = int(
                    validation[1] or 0
                )

                team_sequence = str(
                    validation[2] or ""
                )

            known_rows.append(
                {
                    "validation_name": label,
                    "expected_profile_count": (
                        len(athlete_ids)
                    ),
                    "observed_profile_count": (
                        len(bridge)
                    ),
                    "canonical_person_count": (
                        len(person_ids)
                    ),
                    "canonical_person_id": (
                        person_ids[0]
                        if len(person_ids) == 1
                        else ""
                    ),
                    "school_stint_count": (
                        stint_count
                    ),
                    "single_meet_aba_island_count": (
                        island_count
                    ),
                    "team_sequence": (
                        team_sequence
                    ),
                }
            )

        known_validation = pd.DataFrame(
            known_rows
        )

        known_validation.to_csv(
            OUTPUT_DIR
            / "known_identity_validation.csv",
            index=False,
        )

        meet_assignment_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM person_meet_team_assignments
            """,
        )

        distinct_meet_assignment_keys = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    canonical_person_id,
                    season_id,
                    meet_id
                FROM person_meet_team_assignments
                GROUP BY
                    canonical_person_id,
                    season_id,
                    meet_id
            )
            """,
        )

        stint_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_school_stints
            """,
        )

        blank_stint_ids = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_school_stints
            WHERE NULLIF(
                school_stint_id,
                ''
            ) IS NULL
            """,
        )

        duplicate_stint_ids = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    school_stint_id
                FROM canonical_person_school_stints
                GROUP BY school_stint_id
                HAVING COUNT(*) > 1
            )
            """,
        )

        noncontiguous_stint_sequences = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    canonical_person_id,
                    COUNT(*) AS stint_count,
                    MIN(stint_sequence)
                        AS min_sequence,
                    MAX(stint_sequence)
                        AS max_sequence
                FROM canonical_person_school_stints
                GROUP BY canonical_person_id
                HAVING
                    min_sequence != 1
                    OR max_sequence != stint_count
            )
            """,
        )

        consecutive_same_team_stints = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM canonical_person_school_stints
            WHERE prior_stint_team_id
                = canonical_team_id
            """,
        )

        map_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM school_stint_performance_map
            """,
        )

        distinct_map_ids = scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT
                canonical_person_performance_id
            )
            FROM school_stint_performance_map
            """,
        )

        input_rows_missing_map = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM person
                .school_stint_person_performances p
            LEFT JOIN school_stint_performance_map m
              USING (
                canonical_person_performance_id
              )
            WHERE
                m.canonical_person_performance_id
                    IS NULL
            """,
        )

        map_rows_missing_stint = scalar(
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

        known_pair_failures = int(
            (
                known_validation[
                    "observed_profile_count"
                ]
                != known_validation[
                    "expected_profile_count"
                ]
            ).sum()
            + (
                known_validation[
                    "canonical_person_count"
                ] != 1
            ).sum()
            + (
                known_validation[
                    "single_meet_aba_island_count"
                ] != 0
            ).sum()
        )

        person_after = file_state(PERSON_DB)

        checks = pd.DataFrame(
            [
                (
                    "eligible_input_rows_equal_distinct_ids",
                    abs(
                        input_rows
                        - distinct_input_ids
                    ),
                    distinct_input_ids,
                    input_rows,
                ),
                (
                    "blank_input_keys",
                    blank_key_rows,
                    blank_key_rows,
                    0,
                ),
                (
                    "same_person_meet_multi_team_groups",
                    len(meet_team_conflicts),
                    len(meet_team_conflicts),
                    0,
                ),
                (
                    "meet_assignment_unique_keys",
                    abs(
                        meet_assignment_rows
                        - distinct_meet_assignment_keys
                    ),
                    distinct_meet_assignment_keys,
                    meet_assignment_rows,
                ),
                (
                    "same_day_multi_team_groups",
                    len(same_day_multi_team),
                    len(same_day_multi_team),
                    0,
                ),
                (
                    "blank_school_stint_ids",
                    blank_stint_ids,
                    blank_stint_ids,
                    0,
                ),
                (
                    "duplicate_school_stint_ids",
                    duplicate_stint_ids,
                    duplicate_stint_ids,
                    0,
                ),
                (
                    "noncontiguous_stint_sequences",
                    noncontiguous_stint_sequences,
                    noncontiguous_stint_sequences,
                    0,
                ),
                (
                    "consecutive_same_team_stints",
                    consecutive_same_team_stints,
                    consecutive_same_team_stints,
                    0,
                ),
                (
                    "single_meet_aba_islands",
                    len(aba_islands),
                    len(aba_islands),
                    0,
                ),
                (
                    "performance_map_rows",
                    abs(
                        map_rows
                        - input_rows
                    ),
                    map_rows,
                    input_rows,
                ),
                (
                    "distinct_performance_map_ids",
                    abs(
                        distinct_map_ids
                        - input_rows
                    ),
                    distinct_map_ids,
                    input_rows,
                ),
                (
                    "input_rows_missing_stint_map",
                    input_rows_missing_map,
                    input_rows_missing_map,
                    0,
                ),
                (
                    "stint_map_rows_missing_stint",
                    map_rows_missing_stint,
                    map_rows_missing_stint,
                    0,
                ),
                (
                    "stint_performance_total",
                    abs(
                        stint_performance_total
                        - input_rows
                    ),
                    stint_performance_total,
                    input_rows,
                ),
                (
                    "known_identity_validation_failures",
                    known_pair_failures,
                    known_pair_failures,
                    0,
                ),
                (
                    "input_person_db_size_unchanged",
                    abs(
                        person_after["size_bytes"]
                        - person_before["size_bytes"]
                    ),
                    person_after["size_bytes"],
                    person_before["size_bytes"],
                ),
                (
                    "input_person_db_modified_time_unchanged",
                    abs(
                        person_after["modified_ns"]
                        - person_before["modified_ns"]
                    ),
                    person_after["modified_ns"],
                    person_before["modified_ns"],
                ),
            ],
            columns=[
                "check_name",
                "failed_row_count",
                "observed_value",
                "expected_value",
            ],
        )

        canonical_people_with_stints = scalar(
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

        synthetic_date_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM person_meet_team_assignments
            WHERE date_parse_status
                = 'SYNTHETIC_YEAR_ONLY'
            """,
        )

        synthetic_dates_for_multi_team_people = scalar(
            con,
            """
            WITH multi_team_people AS (
                SELECT
                    canonical_person_id
                FROM person_meet_team_assignments
                GROUP BY canonical_person_id
                HAVING COUNT(
                    DISTINCT canonical_team_id
                ) > 1
            )
            SELECT COUNT(*)
            FROM person_meet_team_assignments m
            JOIN multi_team_people p
              USING (canonical_person_id)
            WHERE m.date_parse_status
                = 'SYNTHETIC_YEAR_ONLY'
            """,
        )

        checks = pd.concat(
            [
                checks,
                pd.DataFrame(
                    [
                        (
                            "synthetic_dates_for_multi_team_people",
                            synthetic_dates_for_multi_team_people,
                            synthetic_dates_for_multi_team_people,
                            0,
                        ),
                    ],
                    columns=checks.columns,
                ),
            ],
            ignore_index=True,
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

        report = f"""MILESTONE 4 FINAL D1 SCHOOL STINTS
============================================================
Stint version: {STINT_VERSION}
Input canonical-person database modified: no

INPUT
- Eligible canonical-person performances:
  {input_rows:,}
- Canonical person-meet assignments:
  {meet_assignment_rows:,}

SCHOOL STINTS
- Canonical people with D1 stints:
  {canonical_people_with_stints:,}
- Total school stints:
  {stint_rows:,}
- People represented by multiple stints:
  {transfer_people:,}
- People returning to a prior team:
  {returning_people:,}

CHRONOLOGY
- Synthetic-date meet assignments:
  {synthetic_date_rows:,}
- Synthetic dates among multi-team people:
  {synthetic_dates_for_multi_team_people:,}
- Same-day multi-team groups:
  {len(same_day_multi_team):,}
- Single-meet A-B-A islands:
  {len(aba_islands):,}

PERFORMANCE MAPPING
- Performance-to-stint map rows:
  {map_rows:,}
- Input performances missing a stint:
  {input_rows_missing_map:,}

KNOWN DUPLICATE-PROFILE VALIDATION
- Emily Venters and Daniella Hubble validation failures:
  {known_pair_failures:,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

INTERPRETATION
Each D1-eligible canonical performance is assigned to exactly one chronological
school stint. Consecutive appearances for the same team are collapsed into one
stint. A return to a former team remains a distinct stint rather than being
merged across an intervening team.
"""

        (
            OUTPUT_DIR
            / "school_stint_report.txt"
        ).write_text(
            report,
            encoding="utf-8",
        )

        con.execute("CHECKPOINT")

        print(
            "Final D1 school-stint build complete."
        )
        print(f"Database: {OUTPUT_DB}")
        print(
            "Eligible performance rows: "
            f"{input_rows:,}"
        )
        print(
            "Canonical person-meet assignments: "
            f"{meet_assignment_rows:,}"
        )
        print(
            "School stints: "
            f"{stint_rows:,}"
        )
        print(
            "People with multiple stints: "
            f"{transfer_people:,}"
        )
        print(
            "Single-meet A-B-A islands: "
            f"{len(aba_islands):,}"
        )
        print(f"Failed checks: {failed:,}.")

        if failed:
            raise SystemExit(1)

    finally:
        try:
            con.unregister(
                "meet_assignments_input"
            )
        except Exception:
            pass

        con.close()


if __name__ == "__main__":
    main()
