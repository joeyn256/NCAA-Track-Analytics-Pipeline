#!/usr/bin/env python3
"""
Milestone 4: validate remaining section resolutions.

Purpose
-------
Validate the 1,987 consistent-source-team sections against their profile
section names and resolve the final 16 gender-ambiguous school sections using
athlete affiliation evidence.

This script does not apply final performance attribution. It generates the
last section-resolution evidence and review queues.

Outputs
-------
data/processed/milestone4/final_section_resolution_audit/
    consistent_team_name_validation.csv
    consistent_team_validation_summary.csv
    gender_ambiguous_resolution_candidates.csv
    unresolved_gender_queue.csv
    name_disagreement_queue.csv
    hard_checks.csv
    audit_report.txt
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

EVIDENCE_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "section_source_team_evidence/"
    / "section_source_team_evidence.csv"
)

ALIAS_REGISTRY_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "profile_section_classification/"
    / "entity_alias_registry_v1.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "final_section_resolution_audit"
)

AUDIT_VERSION = "m4_final_section_resolution_audit_v1.0"
EXPECTED_CONSISTENT_TEAM_ROWS = 1_987
EXPECTED_GENDER_AMBIGUOUS_ROWS = 16


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
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--replace-output",
        action="store_true",
    )
    return parser.parse_args()


def require_inputs() -> None:
    for path in [
        SOURCE_DB,
        EVIDENCE_CSV,
        ALIAS_REGISTRY_CSV,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )


def load_affiliation_gender() -> pd.DataFrame:
    con = duckdb.connect(
        str(SOURCE_DB),
        read_only=True,
    )

    try:
        affiliations = con.execute(
            """
            SELECT
                a.athlete_id,
                COUNT(
                    DISTINCT NULLIF(
                        trim(t.gender_code),
                        ''
                    )
                ) AS distinct_affiliation_gender_count,
                MIN(
                    NULLIF(
                        trim(t.gender_code),
                        ''
                    )
                ) AS affiliation_gender_code,
                COUNT(
                    DISTINCT t.team_id
                ) AS affiliation_team_count,
                string_agg(
                    DISTINCT NULLIF(
                        trim(t.gender_code),
                        ''
                    ),
                    ' | '
                    ORDER BY NULLIF(
                        trim(t.gender_code),
                        ''
                    )
                ) AS affiliation_gender_codes
            FROM core.athlete_affiliations a
            LEFT JOIN core.teams t
              ON a.team_id = t.team_id
            GROUP BY a.athlete_id
            """
        ).fetchdf()

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
                    AS resolved_team_name,
                t.gender_code,
                t.division
            FROM core.teams t
            LEFT JOIN core.schools s
              ON t.school_id = s.school_id
            """
        ).fetchdf()

    finally:
        con.close()

    affiliations["athlete_id"] = pd.to_numeric(
        affiliations["athlete_id"],
        errors="coerce",
    ).astype("Int64")

    affiliations[
        "distinct_affiliation_gender_count"
    ] = (
        pd.to_numeric(
            affiliations[
                "distinct_affiliation_gender_count"
            ],
            errors="coerce",
        )
        .fillna(0)
        .astype("int64")
    )

    affiliations["affiliation_gender_code"] = (
        affiliations["affiliation_gender_code"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.casefold()
    )

    teams["gender_code"] = (
        teams["gender_code"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.casefold()
    )
    teams["normalized_school_name"] = (
        teams["resolved_school_name"]
        .map(normalize_name)
    )

    return affiliations, teams


def build_outputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    evidence = pd.read_csv(
        EVIDENCE_CSV,
        dtype=str,
        keep_default_na=False,
    )

    evidence["athlete_id"] = pd.to_numeric(
        evidence["athlete_id"],
        errors="coerce",
    ).astype("Int64")
    evidence["section_index"] = pd.to_numeric(
        evidence["section_index"],
        errors="coerce",
    ).astype("Int64")
    evidence["observed_performance_count"] = (
        pd.to_numeric(
            evidence["observed_performance_count"],
            errors="coerce",
        )
        .fillna(0)
        .astype("int64")
    )

    alias = pd.read_csv(
        ALIAS_REGISTRY_CSV,
        dtype=str,
        keep_default_na=False,
    )
    alias["normalized_alias"] = (
        alias["normalized_section_name"]
        .where(
            alias["normalized_section_name"].ne(""),
            alias["source_section_name"],
        )
        .map(normalize_name)
    )
    alias["normalized_canonical"] = (
        alias["canonical_entity_name"]
        .map(normalize_name)
    )

    alias_pairs = {
        (
            row.normalized_alias,
            row.normalized_canonical,
        )
        for row in alias.itertuples(index=False)
        if row.normalized_alias
        and row.normalized_canonical
    }

    consistent = evidence.loc[
        evidence["source_evidence_status"]
        .eq("CONSISTENT_SOURCE_TEAM")
    ].copy()

    consistent["normalized_section_name_check"] = (
        consistent["source_section_name"]
        .map(normalize_name)
    )
    consistent["normalized_source_school_name"] = (
        consistent["consistent_source_school_name"]
        .map(normalize_name)
    )
    consistent["normalized_core_team_name"] = (
        consistent["consistent_core_team_name"]
        .map(normalize_name)
    )

    def classify_name_agreement(
        row: pd.Series,
    ) -> str:
        section = row[
            "normalized_section_name_check"
        ]
        school = row[
            "normalized_source_school_name"
        ]
        team = row[
            "normalized_core_team_name"
        ]

        if section and section == school:
            return "EXACT_SECTION_TO_SOURCE_SCHOOL"

        if section and section == team:
            return "EXACT_SECTION_TO_SOURCE_TEAM"

        if (
            (section, school) in alias_pairs
            or (school, section) in alias_pairs
            or (section, team) in alias_pairs
            or (team, section) in alias_pairs
        ):
            return "VALIDATED_ALIAS_AGREEMENT"

        return "NAME_DISAGREEMENT_REVIEW"

    consistent["name_validation_status"] = (
        consistent.apply(
            classify_name_agreement,
            axis=1,
        )
    )
    consistent["audit_version"] = AUDIT_VERSION

    ambiguous = evidence.loc[
        evidence["source_evidence_status"]
        .eq("NO_SOURCE_TEAM_EVIDENCE")
    ].copy()

    affiliations, teams = load_affiliation_gender()

    ambiguous = ambiguous.merge(
        affiliations,
        on="athlete_id",
        how="left",
    )

    ambiguous[
        "distinct_affiliation_gender_count"
    ] = (
        ambiguous[
            "distinct_affiliation_gender_count"
        ]
        .fillna(0)
        .astype("int64")
    )
    ambiguous["affiliation_gender_code"] = (
        ambiguous["affiliation_gender_code"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.casefold()
    )

    ambiguous["normalized_section_name_check"] = (
        ambiguous["source_section_name"]
        .map(normalize_name)
    )

    gender_candidates = ambiguous.merge(
        teams,
        left_on=[
            "normalized_section_name_check",
            "affiliation_gender_code",
        ],
        right_on=[
            "normalized_school_name",
            "gender_code",
        ],
        how="left",
        suffixes=("", "_team"),
    )

    candidate_counts = (
        gender_candidates.groupby(
            ["athlete_id", "section_index"],
            dropna=False,
        )
        .agg(
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

    gender_candidates = (
        gender_candidates.sort_values(
            [
                "athlete_id",
                "section_index",
                "resolved_team_id",
            ]
        )
        .drop_duplicates(
            ["athlete_id", "section_index"],
            keep="first",
        )
        .merge(
            candidate_counts,
            on=["athlete_id", "section_index"],
            how="left",
        )
    )

    gender_candidates[
        "gender_resolution_status"
    ] = "UNRESOLVED_GENDER"

    resolved_mask = (
        gender_candidates[
            "distinct_affiliation_gender_count"
        ].eq(1)
        & gender_candidates[
            "affiliation_gender_code"
        ].ne("")
        & gender_candidates[
            "candidate_team_count"
        ].eq(1)
        & gender_candidates[
            "candidate_school_count"
        ].eq(1)
    )

    gender_candidates.loc[
        resolved_mask,
        "gender_resolution_status",
    ] = "RESOLVED_FROM_SOLE_AFFILIATION_GENDER"

    gender_candidates["audit_version"] = (
        AUDIT_VERSION
    )

    return consistent, gender_candidates


def build_checks(
    consistent: pd.DataFrame,
    gender_candidates: pd.DataFrame,
) -> pd.DataFrame:
    consistent_rows = len(consistent)
    ambiguous_rows = len(gender_candidates)

    consistent_duplicates = int(
        consistent.duplicated(
            ["athlete_id", "section_index"]
        ).sum()
    )
    ambiguous_duplicates = int(
        gender_candidates.duplicated(
            ["athlete_id", "section_index"]
        ).sum()
    )

    invalid_name_status = int(
        (
            ~consistent[
                "name_validation_status"
            ].isin(
                [
                    "EXACT_SECTION_TO_SOURCE_SCHOOL",
                    "EXACT_SECTION_TO_SOURCE_TEAM",
                    "VALIDATED_ALIAS_AGREEMENT",
                    "NAME_DISAGREEMENT_REVIEW",
                ]
            )
        ).sum()
    )

    invalid_gender_status = int(
        (
            ~gender_candidates[
                "gender_resolution_status"
            ].isin(
                [
                    "RESOLVED_FROM_SOLE_AFFILIATION_GENDER",
                    "UNRESOLVED_GENDER",
                ]
            )
        ).sum()
    )

    rows = [
        (
            "consistent_source_team_rows",
            abs(
                consistent_rows
                - EXPECTED_CONSISTENT_TEAM_ROWS
            ),
            consistent_rows,
            EXPECTED_CONSISTENT_TEAM_ROWS,
        ),
        (
            "gender_ambiguous_rows",
            abs(
                ambiguous_rows
                - EXPECTED_GENDER_AMBIGUOUS_ROWS
            ),
            ambiguous_rows,
            EXPECTED_GENDER_AMBIGUOUS_ROWS,
        ),
        (
            "duplicate_consistent_section_keys",
            consistent_duplicates,
            consistent_duplicates,
            0,
        ),
        (
            "duplicate_gender_section_keys",
            ambiguous_duplicates,
            ambiguous_duplicates,
            0,
        ),
        (
            "invalid_name_validation_status",
            invalid_name_status,
            invalid_name_status,
            0,
        ),
        (
            "invalid_gender_resolution_status",
            invalid_gender_status,
            invalid_gender_status,
            0,
        ),
    ]

    return pd.DataFrame(
        rows,
        columns=[
            "check_name",
            "failed_row_count",
            "observed_value",
            "expected_value",
        ],
    )


def write_outputs(
    consistent: pd.DataFrame,
    gender_candidates: pd.DataFrame,
    checks: pd.DataFrame,
) -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    consistent.to_csv(
        OUTPUT_DIR
        / "consistent_team_name_validation.csv",
        index=False,
    )

    (
        consistent.groupby(
            "name_validation_status",
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
                "observed_performance_count",
                "sum",
            ),
        )
        .reset_index()
        .sort_values(
            "performance_count",
            ascending=False,
        )
        .to_csv(
            OUTPUT_DIR
            / "consistent_team_validation_summary.csv",
            index=False,
        )
    )

    gender_candidates.to_csv(
        OUTPUT_DIR
        / "gender_ambiguous_resolution_candidates.csv",
        index=False,
    )

    gender_candidates.loc[
        gender_candidates[
            "gender_resolution_status"
        ].eq("UNRESOLVED_GENDER")
    ].to_csv(
        OUTPUT_DIR
        / "unresolved_gender_queue.csv",
        index=False,
    )

    consistent.loc[
        consistent[
            "name_validation_status"
        ].eq("NAME_DISAGREEMENT_REVIEW")
    ].to_csv(
        OUTPUT_DIR
        / "name_disagreement_queue.csv",
        index=False,
    )

    checks.to_csv(
        OUTPUT_DIR / "hard_checks.csv",
        index=False,
    )

    failed = int(
        (checks["failed_row_count"] > 0).sum()
    )
    disagreements = int(
        consistent[
            "name_validation_status"
        ].eq("NAME_DISAGREEMENT_REVIEW").sum()
    )
    disagreement_performances = int(
        consistent.loc[
            consistent[
                "name_validation_status"
            ].eq("NAME_DISAGREEMENT_REVIEW"),
            "observed_performance_count",
        ].sum()
    )
    gender_resolved = int(
        gender_candidates[
            "gender_resolution_status"
        ].eq(
            "RESOLVED_FROM_SOLE_AFFILIATION_GENDER"
        ).sum()
    )
    gender_unresolved = int(
        gender_candidates[
            "gender_resolution_status"
        ].eq("UNRESOLVED_GENDER").sum()
    )

    report = f"""MILESTONE 4 FINAL SECTION RESOLUTION AUDIT
============================================================
Audit version: {AUDIT_VERSION}
Source database modified: no
Prior Milestone 4 outputs modified: no

CONSISTENT SOURCE-TEAM VALIDATION
- Sections tested: {len(consistent):,}
- Name-disagreement sections: {disagreements:,}
- Performances in name-disagreement sections: {disagreement_performances:,}

GENDER-AMBIGUOUS RESOLUTION
- Sections tested: {len(gender_candidates):,}
- Resolved from sole affiliation gender: {gender_resolved:,}
- Still unresolved: {gender_unresolved:,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

NEXT GATE
If the name-disagreement and unresolved-gender queues are empty, all remaining
profile sections have sufficient deterministic resolution evidence. The final
section registry and one-row-per-performance attribution layer can then be
built without modifying the Milestone 3 source database.
"""

    (
        OUTPUT_DIR / "audit_report.txt"
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
                "Existing audit outputs found. "
                "Use --replace-output after review."
            )

    consistent, gender_candidates = (
        build_outputs()
    )
    checks = build_checks(
        consistent,
        gender_candidates,
    )
    write_outputs(
        consistent,
        gender_candidates,
        checks,
    )

    failed = int(
        (checks["failed_row_count"] > 0).sum()
    )

    print(
        "Final section-resolution audit complete."
    )
    print(f"Outputs: {OUTPUT_DIR}")
    print(f"Failed checks: {failed:,}.")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
