#!/usr/bin/env python3
"""
Milestone 4: build section-entity resolution candidates.

Purpose
-------
Create a read-only candidate registry for the 12,311 unresolved exact profile
sections identified by the multi-section attribution coverage audit.

Resolution sources, in precedence order:
1. exact normalized core team name;
2. exact normalized core school name;
3. existing validated Milestone 4 alias registry;
4. existing validated Milestone 4 entity registry;
5. unresolved or ambiguous review queue.

This script does not apply final performance attribution and does not modify
the Milestone 3 database or any prior Milestone 4 database.

Outputs
-------
data/processed/milestone4/full_section_entity_resolution/
    section_resolution_candidates.csv
    resolution_status_summary.csv
    candidate_name_frequency.csv
    ambiguous_candidate_queue.csv
    unresolved_candidate_queue.csv
    hard_checks.csv
    resolution_report.txt
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]

SOURCE_DB = (
    PROJECT_ROOT
    / "data/database/ncaa_track_analytics.duckdb"
)

COVERAGE_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "multi_section_attribution_coverage/"
    / "multi_section_attribution_coverage.duckdb"
)

UNRESOLVED_SECTIONS_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "multi_section_attribution_coverage/"
    / "unresolved_section_inventory.csv"
)

ALIAS_REGISTRY_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "profile_section_classification/"
    / "entity_alias_registry_v1.csv"
)

ENTITY_REGISTRY_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "profile_section_classification/"
    / "affiliation_entity_registry_v1.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "full_section_entity_resolution"
)

RESOLUTION_VERSION = "m4_full_section_entity_candidates_v1.2"
EXPECTED_SECTION_ROWS = 12_311


def clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split()).strip()


def normalize_name(value: object) -> str:
    text = clean(value)
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )
    text = text.casefold()

    replacements = {
        "&": " and ",
        "+": " and ",
        "@": " at ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def require_inputs() -> None:
    for path in [
        SOURCE_DB,
        COVERAGE_DB,
        UNRESOLVED_SECTIONS_CSV,
        ALIAS_REGISTRY_CSV,
        ENTITY_REGISTRY_CSV,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--replace-output",
        action="store_true",
        help="Replace existing generated CSV reports.",
    )

    return parser.parse_args()


def load_core_entities() -> tuple[pd.DataFrame, pd.DataFrame]:
    con = duckdb.connect(
        str(SOURCE_DB),
        read_only=True,
    )

    try:
        teams = con.execute(
            """
            SELECT
                CAST(t.team_id AS VARCHAR)
                    AS resolved_team_id,
                CAST(t.school_id AS VARCHAR)
                    AS resolved_school_id,
                s.school_name
                    AS resolved_school_name,
                t.team_name
                    AS source_entity_name,
                t.gender_code,
                t.division,
                'CORE_TEAM' AS match_source_type
            FROM core.teams t
            LEFT JOIN core.schools s
              ON t.school_id = s.school_id
            """
        ).fetchdf()

        schools = con.execute(
            """
            SELECT
                CAST(s.school_id AS VARCHAR)
                    AS resolved_school_id,
                s.school_name
                    AS resolved_school_name,
                s.school_name
                    AS source_entity_name,
                'CORE_SCHOOL' AS match_source_type
            FROM core.schools s
            """
        ).fetchdf()

    finally:
        con.close()

    teams["normalized_entity_name"] = (
        teams["source_entity_name"].map(
            normalize_name
        )
    )
    teams["gender_code"] = (
        teams["gender_code"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.casefold()
    )
    schools["normalized_entity_name"] = (
        schools["source_entity_name"].map(
            normalize_name
        )
    )

    return teams, schools


def load_section_gender_evidence() -> pd.DataFrame:
    con = duckdb.connect(
        str(COVERAGE_DB),
        read_only=True,
    )

    try:
        frame = con.execute(
            """
            SELECT
                athlete_id,
                matched_section_index
                    AS section_index,
                COUNT(
                    DISTINCT NULLIF(
                        trim(gender_code),
                        ''
                    )
                ) AS distinct_gender_count,
                MIN(
                    NULLIF(
                        trim(gender_code),
                        ''
                    )
                ) AS section_gender_code
            FROM multi_section_performance_coverage
            GROUP BY
                athlete_id,
                matched_section_index
            """
        ).fetchdf()
    finally:
        con.close()

    frame["athlete_id"] = pd.to_numeric(
        frame["athlete_id"],
        errors="coerce",
    ).astype("Int64")
    frame["section_index"] = pd.to_numeric(
        frame["section_index"],
        errors="coerce",
    ).astype("Int64")
    frame["distinct_gender_count"] = (
        pd.to_numeric(
            frame["distinct_gender_count"],
            errors="coerce",
        )
        .fillna(0)
        .astype("int64")
    )
    frame["section_gender_code"] = (
        frame["section_gender_code"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.casefold()
    )

    return frame


def build_registry_candidates() -> pd.DataFrame:
    unresolved = pd.read_csv(
        UNRESOLVED_SECTIONS_CSV,
        dtype=str,
        keep_default_na=False,
    )

    unresolved["athlete_id"] = pd.to_numeric(
        unresolved["athlete_id"],
        errors="coerce",
    ).astype("Int64")
    unresolved["section_index"] = pd.to_numeric(
        unresolved["section_index"],
        errors="coerce",
    ).astype("Int64")
    unresolved["performance_count"] = pd.to_numeric(
        unresolved["performance_count"],
        errors="coerce",
    ).fillna(0).astype("int64")

    section_gender = load_section_gender_evidence()
    unresolved = unresolved.merge(
        section_gender,
        on=[
            "athlete_id",
            "section_index",
        ],
        how="left",
    )
    unresolved["distinct_gender_count"] = (
        unresolved["distinct_gender_count"]
        .fillna(0)
        .astype("int64")
    )
    unresolved["section_gender_code"] = (
        unresolved["section_gender_code"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.casefold()
    )

    unresolved["candidate_normalized_name"] = (
        unresolved["normalized_section_name"]
        .where(
            unresolved["normalized_section_name"]
            .ne(""),
            unresolved["source_section_name"],
        )
        .map(normalize_name)
    )

    teams, schools = load_core_entities()

    alias = pd.read_csv(
        ALIAS_REGISTRY_CSV,
        dtype=str,
        keep_default_na=False,
    )
    alias["candidate_normalized_name"] = (
        alias["normalized_section_name"]
        .where(
            alias["normalized_section_name"].ne(""),
            alias["source_section_name"],
        )
        .map(normalize_name)
    )
    alias["match_source_type"] = (
        "VALIDATED_ALIAS_REGISTRY"
    )

    entities = pd.read_csv(
        ENTITY_REGISTRY_CSV,
        dtype=str,
        keep_default_na=False,
    )
    entities["candidate_normalized_name"] = (
        entities["canonical_entity_name"]
        .map(normalize_name)
    )
    entities["match_source_type"] = (
        "VALIDATED_ENTITY_REGISTRY"
    )

    match_rows: list[pd.DataFrame] = []

    team_matches = unresolved.merge(
        teams,
        left_on="candidate_normalized_name",
        right_on="normalized_entity_name",
        how="inner",
        suffixes=("", "_match"),
    )
    team_matches = team_matches.loc[
        team_matches["section_gender_code"].eq("")
        | team_matches["gender_code"].eq(
            team_matches["section_gender_code"]
        )
    ].copy()

    team_matches["match_precedence"] = 1
    team_matches["matched_entity_name"] = (
        team_matches["source_entity_name"]
    )
    team_matches["analytical_entity_id"] = ""
    team_matches["entity_type"] = "school_team"
    match_rows.append(team_matches)

    school_matches = unresolved.merge(
        schools,
        left_on="candidate_normalized_name",
        right_on="normalized_entity_name",
        how="inner",
        suffixes=("", "_match"),
    )
    school_matches["match_precedence"] = 2
    school_matches["matched_entity_name"] = (
        school_matches["source_entity_name"]
    )
    school_matches["resolved_team_id"] = ""
    school_matches["gender_code"] = ""
    school_matches["division"] = ""
    school_matches["analytical_entity_id"] = ""
    school_matches["entity_type"] = "school"
    match_rows.append(school_matches)

    alias_columns = [
        "candidate_normalized_name",
        "analytical_entity_id",
        "canonical_entity_name",
        "entity_type",
        "resolved_team_id",
        "resolved_school_id",
        "resolution_status",
        "resolution_method",
        "resolution_confidence",
        "match_source_type",
    ]
    alias_matches = unresolved.merge(
        alias[alias_columns],
        on="candidate_normalized_name",
        how="inner",
    )
    alias_matches["match_precedence"] = 3
    alias_matches["matched_entity_name"] = (
        alias_matches["canonical_entity_name"]
    )
    alias_matches["resolved_school_name"] = ""
    alias_matches["gender_code"] = ""
    alias_matches["division"] = ""
    match_rows.append(alias_matches)

    entity_columns = [
        "candidate_normalized_name",
        "analytical_entity_id",
        "canonical_entity_name",
        "entity_type",
        "resolved_team_id",
        "resolved_school_id",
        "resolved_school_name",
        "resolved_division",
        "resolution_status",
        "resolution_method",
        "resolution_confidence",
        "match_source_type",
    ]
    entity_matches = unresolved.merge(
        entities[entity_columns],
        on="candidate_normalized_name",
        how="inner",
    )
    entity_matches["match_precedence"] = 4
    entity_matches["matched_entity_name"] = (
        entity_matches["canonical_entity_name"]
    )
    entity_matches["gender_code"] = ""
    entity_matches["division"] = (
        entity_matches["resolved_division"]
    )
    match_rows.append(entity_matches)

    all_matches = pd.concat(
        match_rows,
        ignore_index=True,
        sort=False,
    )

    base_keys = [
        "athlete_id",
        "section_index",
    ]

    candidate_counts = (
        all_matches.groupby(base_keys, dropna=False)
        .agg(
            candidate_match_count=(
                "matched_entity_name",
                "size",
            ),
            candidate_entity_count=(
                "matched_entity_name",
                "nunique",
            ),
            candidate_team_count=(
                "resolved_team_id",
                lambda values: len(
                    {
                        clean(value)
                        for value in values
                        if clean(value)
                    }
                ),
            ),
            candidate_school_count=(
                "resolved_school_id",
                lambda values: len(
                    {
                        clean(value)
                        for value in values
                        if clean(value)
                    }
                ),
            ),
        )
        .reset_index()
    )

    min_precedence = (
        all_matches.groupby(base_keys, dropna=False)[
            "match_precedence"
        ]
        .min()
        .rename("best_precedence")
        .reset_index()
    )

    best = all_matches.merge(
        min_precedence,
        on=base_keys,
        how="inner",
    )
    best = best.loc[
        best["match_precedence"]
        .eq(best["best_precedence"])
    ].copy()

    best_counts = (
        best.groupby(base_keys, dropna=False)
        .agg(
            best_match_row_count=(
                "matched_entity_name",
                "size",
            ),
            best_entity_count=(
                "matched_entity_name",
                "nunique",
            ),
            best_team_count=(
                "resolved_team_id",
                lambda values: len(
                    {
                        clean(value)
                        for value in values
                        if clean(value)
                    }
                ),
            ),
            best_school_count=(
                "resolved_school_id",
                lambda values: len(
                    {
                        clean(value)
                        for value in values
                        if clean(value)
                    }
                ),
            ),
        )
        .reset_index()
    )

    sort_columns = (
        base_keys
        + [
            "match_precedence",
            "matched_entity_name",
            "resolved_team_id",
            "resolved_school_id",
        ]
    )
    best = best.sort_values(sort_columns)

    chosen = best.drop_duplicates(
        base_keys,
        keep="first",
    ).copy()

    chosen = chosen.merge(
        candidate_counts,
        on=base_keys,
        how="left",
    ).merge(
        best_counts,
        on=base_keys,
        how="left",
    )

    chosen["candidate_resolution_status"] = (
        "AUTO_RESOLVED_EXACT"
    )

    ambiguous_mask = (
        chosen["best_entity_count"].gt(1)
        | chosen["best_school_count"].gt(1)
        | chosen["best_team_count"].gt(1)
    )
    chosen.loc[
        ambiguous_mask,
        "candidate_resolution_status",
    ] = "AMBIGUOUS_EXACT_MATCH"

    resolved_keys = chosen[base_keys]
    final = unresolved.merge(
        chosen[
            base_keys
            + [
                "match_source_type",
                "match_precedence",
                "matched_entity_name",
                "analytical_entity_id",
                "entity_type",
                "resolved_team_id",
                "resolved_school_id",
                "resolved_school_name",
                "gender_code",
                "division",
                "resolution_status",
                "resolution_method",
                "resolution_confidence",
                "candidate_match_count",
                "candidate_entity_count",
                "candidate_team_count",
                "candidate_school_count",
                "best_match_row_count",
                "best_entity_count",
                "best_team_count",
                "best_school_count",
                "candidate_resolution_status",
            ]
        ],
        on=base_keys,
        how="left",
    )

    unresolved_mask = final[
        "candidate_resolution_status"
    ].isna()

    final.loc[
        unresolved_mask,
        "candidate_resolution_status",
    ] = "NO_EXACT_CANDIDATE"

    fill_columns = [
        "match_source_type",
        "matched_entity_name",
        "analytical_entity_id",
        "entity_type",
        "resolved_team_id",
        "resolved_school_id",
        "resolved_school_name",
        "gender_code",
        "division",
        "resolution_status",
        "resolution_method",
        "resolution_confidence",
    ]
    for column in fill_columns:
        final[column] = final[column].fillna("")

    count_columns = [
        "candidate_match_count",
        "candidate_entity_count",
        "candidate_team_count",
        "candidate_school_count",
        "best_match_row_count",
        "best_entity_count",
        "best_team_count",
        "best_school_count",
    ]
    for column in count_columns:
        final[column] = (
            pd.to_numeric(
                final[column],
                errors="coerce",
            )
            .fillna(0)
            .astype("int64")
        )

    final["resolution_version"] = (
        RESOLUTION_VERSION
    )

    return final


def build_checks(
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    rows = len(candidates)
    duplicate_count = int(
        candidates.duplicated(
            ["athlete_id", "section_index"]
        ).sum()
    )
    blank_names = int(
        candidates[
            "candidate_normalized_name"
        ].eq("").sum()
    )
    invalid_status = int(
        (
            ~candidates[
                "candidate_resolution_status"
            ].isin(
                [
                    "AUTO_RESOLVED_EXACT",
                    "AMBIGUOUS_EXACT_MATCH",
                    "NO_EXACT_CANDIDATE",
                ]
            )
        ).sum()
    )

    auto_missing_entity = int(
        (
            candidates[
                "candidate_resolution_status"
            ].eq("AUTO_RESOLVED_EXACT")
            & candidates[
                "matched_entity_name"
            ].eq("")
        ).sum()
    )
    conflicting_section_gender = int(
        candidates[
            "distinct_gender_count"
        ].gt(1).sum()
    )

    checks = [
        (
            "input_section_rows",
            abs(rows - EXPECTED_SECTION_ROWS),
            rows,
            EXPECTED_SECTION_ROWS,
        ),
        (
            "duplicate_athlete_section_keys",
            duplicate_count,
            duplicate_count,
            0,
        ),
        (
            "blank_normalized_section_names",
            blank_names,
            blank_names,
            0,
        ),
        (
            "invalid_candidate_status",
            invalid_status,
            invalid_status,
            0,
        ),
        (
            "auto_resolved_rows_missing_entity",
            auto_missing_entity,
            auto_missing_entity,
            0,
        ),
        (
            "sections_with_conflicting_gender_evidence",
            conflicting_section_gender,
            conflicting_section_gender,
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


def write_outputs(
    candidates: pd.DataFrame,
    checks: pd.DataFrame,
) -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    candidates.to_csv(
        OUTPUT_DIR
        / "section_resolution_candidates.csv",
        index=False,
    )

    status_summary = (
        candidates.groupby(
            [
                "candidate_resolution_status",
                "match_source_type",
            ],
            dropna=False,
        )
        .agg(
            section_count=(
                "section_index",
                "size",
            ),
            athlete_count=(
                "athlete_id",
                "nunique",
            ),
            performance_count=(
                "performance_count",
                "sum",
            ),
        )
        .reset_index()
        .sort_values(
            [
                "candidate_resolution_status",
                "performance_count",
            ],
            ascending=[True, False],
        )
    )
    status_summary.to_csv(
        OUTPUT_DIR
        / "resolution_status_summary.csv",
        index=False,
    )

    name_frequency = (
        candidates.groupby(
            [
                "candidate_normalized_name",
                "source_section_name",
                "candidate_resolution_status",
                "match_source_type",
                "matched_entity_name",
            ],
            dropna=False,
        )
        .agg(
            section_count=(
                "section_index",
                "size",
            ),
            athlete_count=(
                "athlete_id",
                "nunique",
            ),
            performance_count=(
                "performance_count",
                "sum",
            ),
        )
        .reset_index()
        .sort_values(
            "performance_count",
            ascending=False,
        )
    )
    name_frequency.to_csv(
        OUTPUT_DIR
        / "candidate_name_frequency.csv",
        index=False,
    )

    candidates.loc[
        candidates[
            "candidate_resolution_status"
        ].eq("AMBIGUOUS_EXACT_MATCH")
    ].to_csv(
        OUTPUT_DIR
        / "ambiguous_candidate_queue.csv",
        index=False,
    )

    candidates.loc[
        candidates[
            "candidate_resolution_status"
        ].eq("NO_EXACT_CANDIDATE")
    ].to_csv(
        OUTPUT_DIR
        / "unresolved_candidate_queue.csv",
        index=False,
    )

    checks.to_csv(
        OUTPUT_DIR / "hard_checks.csv",
        index=False,
    )

    failed_checks = int(
        (checks["failed_row_count"] > 0).sum()
    )
    auto_rows = int(
        candidates[
            "candidate_resolution_status"
        ].eq("AUTO_RESOLVED_EXACT").sum()
    )
    ambiguous_rows = int(
        candidates[
            "candidate_resolution_status"
        ].eq("AMBIGUOUS_EXACT_MATCH").sum()
    )
    unresolved_rows = int(
        candidates[
            "candidate_resolution_status"
        ].eq("NO_EXACT_CANDIDATE").sum()
    )

    auto_performances = int(
        candidates.loc[
            candidates[
                "candidate_resolution_status"
            ].eq("AUTO_RESOLVED_EXACT"),
            "performance_count",
        ].sum()
    )
    ambiguous_performances = int(
        candidates.loc[
            candidates[
                "candidate_resolution_status"
            ].eq("AMBIGUOUS_EXACT_MATCH"),
            "performance_count",
        ].sum()
    )
    unresolved_performances = int(
        candidates.loc[
            candidates[
                "candidate_resolution_status"
            ].eq("NO_EXACT_CANDIDATE"),
            "performance_count",
        ].sum()
    )

    report = f"""MILESTONE 4 FULL SECTION ENTITY CANDIDATES
============================================================
Resolution version: {RESOLUTION_VERSION}
Source database modified: no
Prior Milestone 4 outputs modified: no
Core-team matching is section-gender aware: yes

INPUT
- Unresolved profile sections: {len(candidates):,}
- Performances represented: {int(candidates['performance_count'].sum()):,}

CANDIDATE RESULTS
- Auto-resolved exact sections: {auto_rows:,}
- Auto-resolved performances: {auto_performances:,}
- Ambiguous exact-match sections: {ambiguous_rows:,}
- Ambiguous performances: {ambiguous_performances:,}
- Sections with no exact candidate: {unresolved_rows:,}
- Performances with no exact candidate: {unresolved_performances:,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed_checks:,}

NEXT GATE
Review ambiguous_candidate_queue.csv and unresolved_candidate_queue.csv.
Do not apply the candidate registry to final performance attribution until
ambiguous matches, competition scope, division, and non-school entities are
classified.
"""

    (
        OUTPUT_DIR / "resolution_report.txt"
    ).write_text(
        report,
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    require_inputs()

    if OUTPUT_DIR.exists() and not args.replace_output:
        existing = list(
            OUTPUT_DIR.glob("*.csv")
        ) + list(
            OUTPUT_DIR.glob("*.txt")
        )
        if existing:
            raise FileExistsError(
                "Existing candidate outputs found. "
                "Use --replace-output after review."
            )

    candidates = build_registry_candidates()
    checks = build_checks(candidates)
    write_outputs(candidates, checks)

    failed_checks = int(
        (checks["failed_row_count"] > 0).sum()
    )

    print(
        "Full section-entity candidate audit complete."
    )
    print(f"Outputs: {OUTPUT_DIR}")
    print(
        f"Failed checks: {failed_checks:,}."
    )

    if failed_checks:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
