#!/usr/bin/env python3
"""
Finalize ambiguous canonical-person result evidence v1.2.

This script reads the v1.1 result-page evidence audit and resolves only
remaining groups that satisfy all of the following:

1. The same canonical person and season contain directly resolved result-page
   evidence for exactly one parsed team.
2. The unresolved row's source team ID or normalized source school agrees with
   that directly established team.
3. No competing directly resolved team exists in that person-season.

It does not modify any database or overwrite the v1.1 audit.

Outputs
-------
data/processed/milestone4/ambiguous_person_result_evidence_v1_3/
    finalized_result_evidence.csv
    fallback_resolution_rows.csv
    unresolved_groups.csv
    resolution_status_summary.csv
    resolved_team_summary.csv
    hard_checks.csv
    finalization_report.txt
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]

SOURCE_DB = (
    PROJECT_ROOT
    / "data/database/"
    / "ncaa_track_analytics.duckdb"
)

INPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "ambiguous_person_result_evidence"
)

INPUT_EVIDENCE = (
    INPUT_DIR
    / "ambiguous_result_page_evidence.csv"
)

INPUT_CHECKS = (
    INPUT_DIR
    / "hard_checks.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "ambiguous_person_result_evidence_v1_3"
)

FINALIZATION_VERSION = (
    "m4_ambiguous_person_result_evidence_v1.3"
)

EXPECTED_ROWS = 162
EXPECTED_DIRECT_ROWS = 158
EXPECTED_FALLBACK_ROWS = 4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--replace-output",
        action="store_true",
    )

    return parser.parse_args()


def normalize_text(
    value: object,
) -> str:
    text = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(
            character
        )
    )

    return re.sub(
        r"[^a-z0-9]+",
        "",
        text.lower(),
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

    generated = [
        OUTPUT_DIR
        / "finalized_result_evidence.csv",
        OUTPUT_DIR
        / "fallback_resolution_rows.csv",
        OUTPUT_DIR
        / "unresolved_groups.csv",
        OUTPUT_DIR
        / "resolution_status_summary.csv",
        OUTPUT_DIR
        / "resolved_team_summary.csv",
        OUTPUT_DIR
        / "hard_checks.csv",
        OUTPUT_DIR
        / "finalization_report.txt",
    ]

    existing = [
        path
        for path in generated
        if path.exists()
    ]

    if existing and not replace_output:
        raise FileExistsError(
            "Finalized evidence outputs already exist. "
            "Use --replace-output only after reviewing "
            "the current files."
        )

    if replace_output:
        for path in existing:
            path.unlink()


def main() -> None:
    args = parse_args()

    for path in [
        SOURCE_DB,
        INPUT_EVIDENCE,
        INPUT_CHECKS,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )

    prepare_output(
        replace_output=args.replace_output,
    )

    prior_checks = pd.read_csv(
        INPUT_CHECKS
    )

    unexpected_failures = prior_checks[
        (prior_checks["failed_row_count"] > 0)
        & (
            prior_checks["check_name"]
            != "unresolved_result_page_groups"
        )
    ]

    if not unexpected_failures.empty:
        raise RuntimeError(
            "The v1.1 result-page audit has failed "
            "checks other than the expected unresolved "
            "group count."
        )

    evidence = pd.read_csv(
        INPUT_EVIDENCE,
        dtype={
            "canonical_person_id": str,
            "canonical_person_performance_id": str,
            "season_id": str,
            "parsed_team_id": str,
            "parsed_school_id": str,
            "source_team_ids": str,
        },
    )

    if evidence[
        "canonical_person_performance_id"
    ].duplicated().any():
        raise RuntimeError(
            "Duplicate canonical-person performance IDs "
            "exist in the v1.1 evidence input."
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

        teams = con.execute(
            """
            SELECT
                team_id,
                team_name,
                school_id,
                gender_code,
                division,
                in_division_i_directory,
                team_url
            FROM source.core.teams
            """
        ).fetchdf()

    finally:
        con.close()

    teams["normalized_team_name"] = (
        teams["team_name"]
        .map(normalize_text)
    )

    teams["normalized_school_name"] = (
        teams["team_name"]
        .map(normalize_text)
    )

    team_lookup = (
        teams.set_index("team_id")
        .to_dict(orient="index")
    )

    direct = evidence[
        evidence["resolution_status"].eq(
            "RESOLVED_EXACT_RESULT_ROW"
        )
    ].copy()

    direct_team_counts = (
        direct.groupby(
            [
                "canonical_person_id",
                "season_id",
            ],
            dropna=False,
        )["parsed_team_id"]
        .nunique()
        .rename(
            "direct_team_count"
        )
        .reset_index()
    )

    direct_unique_team = (
        direct.groupby(
            [
                "canonical_person_id",
                "season_id",
            ],
            dropna=False,
        )["parsed_team_id"]
        .first()
        .rename(
            "direct_team_id"
        )
        .reset_index()
    )

    season_evidence = (
        direct_team_counts.merge(
            direct_unique_team,
            on=[
                "canonical_person_id",
                "season_id",
            ],
            how="left",
            validate="one_to_one",
        )
    )

    finalized = evidence.copy()

    fallback_rows: list[
        dict[str, object]
    ] = []

    unresolved_mask = ~finalized[
        "resolution_status"
    ].eq(
        "RESOLVED_EXACT_RESULT_ROW"
    )

    for index, row in finalized[
        unresolved_mask
    ].iterrows():
        matches = season_evidence[
            season_evidence[
                "canonical_person_id"
            ].eq(
                row["canonical_person_id"]
            )
            & season_evidence[
                "season_id"
            ].eq(
                row["season_id"]
            )
        ]

        fallback_scope = (
            "SAME_PERSON_SAME_SEASON"
        )

        if len(matches) != 1:
            season_year = int(
                row["season_year"]
            )

            prior_indoor_season = (
                f"{season_year}_indoor"
            )

            matches = season_evidence[
                season_evidence[
                    "canonical_person_id"
                ].eq(
                    row["canonical_person_id"]
                )
                & season_evidence[
                    "season_id"
                ].eq(
                    prior_indoor_season
                )
            ]

            fallback_scope = (
                "SAME_PERSON_PRIOR_INDOOR_"
                "SAME_CALENDAR_YEAR"
            )

        if len(matches) != 1:
            continue

        season_row = matches.iloc[0]

        if int(
            season_row["direct_team_count"]
        ) != 1:
            continue

        team_id = str(
            season_row["direct_team_id"]
        )

        team = team_lookup.get(
            team_id
        )

        if not team:
            continue

        source_team_ids = {
            value.strip()
            for value in str(
                row.get(
                    "source_team_ids",
                    "",
                )
                or ""
            ).split("|")
            if value.strip()
        }

        normalized_sources = {
            normalize_text(value)
            for value in str(
                row.get(
                    "source_schools",
                    "",
                )
                or ""
            ).split("|")
            if value.strip()
        }

        normalized_team = normalize_text(
            team.get(
                "team_name",
                "",
            )
        )

        source_agrees = (
            team_id in source_team_ids
            or normalized_team
            in normalized_sources
        )

        if not source_agrees:
            continue

        finalized.at[
            index,
            "parsed_team_id",
        ] = team_id

        finalized.at[
            index,
            "parsed_team_name",
        ] = team.get(
            "team_name",
            "",
        )

        finalized.at[
            index,
            "parsed_team_url",
        ] = team.get(
            "team_url",
            "",
        )

        finalized.at[
            index,
            "parsed_school_id",
        ] = team.get(
            "school_id",
            "",
        )

        finalized.at[
            index,
            "parsed_division",
        ] = team.get(
            "division",
            "",
        )

        finalized.at[
            index,
            "parsed_in_d1_directory",
        ] = team.get(
            "in_division_i_directory"
        )

        finalized.at[
            index,
            "team_mapping_method",
        ] = (
            fallback_scope
            + "_DIRECT_EVIDENCE_"
            + "PLUS_SOURCE_AGREEMENT"
        )

        finalized.at[
            index,
            "resolution_status",
        ] = (
            "RESOLVED_PERSON_SEASON_CONTINUITY"
        )

        finalized.at[
            index,
            "row_match_status",
        ] = (
            str(
                row.get(
                    "row_match_status",
                    "",
                )
            )
            + "|FALLBACK_PERSON_SEASON"
        )

        fallback_rows.append(
            finalized.loc[index].to_dict()
        )

    fallback = pd.DataFrame(
        fallback_rows,
        columns=finalized.columns,
    )

    unresolved = finalized[
        ~finalized[
            "resolution_status"
        ].isin(
            [
                "RESOLVED_EXACT_RESULT_ROW",
                (
                    "RESOLVED_PERSON_SEASON_"
                    "CONTINUITY"
                ),
            ]
        )
    ].copy()

    finalized.to_csv(
        OUTPUT_DIR
        / "finalized_result_evidence.csv",
        index=False,
    )

    fallback.to_csv(
        OUTPUT_DIR
        / "fallback_resolution_rows.csv",
        index=False,
    )

    unresolved.to_csv(
        OUTPUT_DIR
        / "unresolved_groups.csv",
        index=False,
    )

    resolution_summary = (
        finalized.groupby(
            [
                "resolution_status",
                "team_mapping_method",
            ],
            dropna=False,
        )
        .agg(
            conflict_group_count=(
                "canonical_person_performance_id",
                "nunique",
            ),
            canonical_person_count=(
                "canonical_person_id",
                "nunique",
            ),
        )
        .reset_index()
        .sort_values(
            [
                "resolution_status",
                "conflict_group_count",
            ],
            ascending=[
                True,
                False,
            ],
        )
    )

    resolution_summary.to_csv(
        OUTPUT_DIR
        / "resolution_status_summary.csv",
        index=False,
    )

    resolved = finalized[
        finalized["resolution_status"].isin(
            [
                "RESOLVED_EXACT_RESULT_ROW",
                (
                    "RESOLVED_PERSON_SEASON_"
                    "CONTINUITY"
                ),
            ]
        )
    ].copy()

    resolved_team_summary = (
        resolved.groupby(
            [
                "parsed_team_id",
                "parsed_team_name",
                "parsed_school_id",
                "parsed_division",
                "parsed_in_d1_directory",
            ],
            dropna=False,
        )
        .agg(
            conflict_group_count=(
                "canonical_person_performance_id",
                "nunique",
            ),
            canonical_person_count=(
                "canonical_person_id",
                "nunique",
            ),
            first_season_year=(
                "season_year",
                "min",
            ),
            last_season_year=(
                "season_year",
                "max",
            ),
        )
        .reset_index()
        .sort_values(
            [
                "conflict_group_count",
                "parsed_team_id",
            ],
            ascending=[
                False,
                True,
            ],
        )
    )

    resolved_team_summary.to_csv(
        OUTPUT_DIR
        / "resolved_team_summary.csv",
        index=False,
    )

    total_rows = len(finalized)

    direct_rows = int(
        finalized[
            "resolution_status"
        ].eq(
            "RESOLVED_EXACT_RESULT_ROW"
        ).sum()
    )

    fallback_count = int(
        finalized[
            "resolution_status"
        ].eq(
            "RESOLVED_PERSON_SEASON_CONTINUITY"
        ).sum()
    )

    unresolved_count = len(unresolved)

    fallback_people = int(
        fallback[
            "canonical_person_id"
        ].nunique()
        if not fallback.empty
        else 0
    )

    fallback_teams = int(
        fallback[
            "parsed_team_id"
        ].nunique()
        if not fallback.empty
        else 0
    )

    fallback_non_d1 = int(
        (
            ~fallback[
                "parsed_in_d1_directory"
            ]
            .fillna(False)
            .astype(bool)
        ).sum()
        if not fallback.empty
        else 0
    )

    checks = pd.DataFrame(
        [
            (
                "finalized_evidence_rows",
                abs(
                    total_rows
                    - EXPECTED_ROWS
                ),
                total_rows,
                EXPECTED_ROWS,
            ),
            (
                "direct_result_page_rows",
                abs(
                    direct_rows
                    - EXPECTED_DIRECT_ROWS
                ),
                direct_rows,
                EXPECTED_DIRECT_ROWS,
            ),
            (
                "person_season_fallback_rows",
                abs(
                    fallback_count
                    - EXPECTED_FALLBACK_ROWS
                ),
                fallback_count,
                EXPECTED_FALLBACK_ROWS,
            ),
            (
                "unresolved_rows",
                unresolved_count,
                unresolved_count,
                0,
            ),
            (
                "duplicate_performance_group_ids",
                int(
                    finalized[
                        "canonical_person_performance_id"
                    ].duplicated().sum()
                ),
                int(
                    finalized[
                        "canonical_person_performance_id"
                    ].duplicated().sum()
                ),
                0,
            ),
            (
                "fallback_canonical_people",
                abs(
                    fallback_people - 1
                ),
                fallback_people,
                1,
            ),
            (
                "fallback_distinct_teams",
                abs(
                    fallback_teams - 1
                ),
                fallback_teams,
                1,
            ),
            (
                "fallback_non_d1_rows",
                abs(
                    fallback_non_d1
                    - EXPECTED_FALLBACK_ROWS
                ),
                fallback_non_d1,
                EXPECTED_FALLBACK_ROWS,
            ),
        ],
        columns=[
            "check_name",
            "failed_row_count",
            "observed_value",
            "expected_value",
        ],
    )

    checks.to_csv(
        OUTPUT_DIR
        / "hard_checks.csv",
        index=False,
    )

    failed = int(
        (
            checks[
                "failed_row_count"
            ] > 0
        ).sum()
    )

    fallback_team_ids = (
        " | ".join(
            sorted(
                fallback[
                    "parsed_team_id"
                ].dropna()
                .astype(str)
                .unique()
            )
        )
        if not fallback.empty
        else ""
    )

    report = f"""MILESTONE 4 AMBIGUOUS PERSON RESULT EVIDENCE V1.2
============================================================
Finalization version: {FINALIZATION_VERSION}
Source database modified: no
Canonical-person database modified: no
v1.1 evidence modified: no

RESULTS
- Input conflict groups: {total_rows:,}
- Direct exact-result-row resolutions:
  {direct_rows:,}
- Person-season continuity resolutions:
  {fallback_count:,}
- Remaining unresolved groups:
  {unresolved_count:,}

TARGETED FALLBACK
- Canonical people affected:
  {fallback_people:,}
- Distinct resolved teams:
  {fallback_teams:,}
- Resolved team IDs:
  {fallback_team_ids}
- Non-D1 fallback rows:
  {fallback_non_d1:,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

INTERPRETATION
The fallback first checks the same person and exact season. When no direct
evidence exists in an outdoor season, it may use that person's immediately
preceding indoor season in the same calendar year, but only when exactly one
team was established there and the unresolved source team or source school
agrees. It is not a general chronology or current-team fallback.
"""

    (
        OUTPUT_DIR
        / "finalization_report.txt"
    ).write_text(
        report,
        encoding="utf-8",
    )

    print(
        "Ambiguous person result evidence "
        "v1.2 finalization complete."
    )
    print(f"Outputs: {OUTPUT_DIR}")
    print(
        "Direct result-page resolutions: "
        f"{direct_rows:,}"
    )
    print(
        "Person-season fallback resolutions: "
        f"{fallback_count:,}"
    )
    print(
        "Remaining unresolved groups: "
        f"{unresolved_count:,}"
    )
    print(f"Failed checks: {failed:,}.")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
