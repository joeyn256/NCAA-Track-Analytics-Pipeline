#!/usr/bin/env python3
"""
Milestone 4 audit of unresolved profile sections and competition scope.

READ-ONLY:
- Does not modify the Milestone 3 DuckDB database.
- Does not modify raw HTML or prior Milestone 4 outputs.

INPUTS:
    data/processed/milestone4/transfer_attribution_full/
        school_section_mapping.csv
        performance_attribution_candidates.csv
        profile_parse_audit.csv

OUTPUTS:
    data/processed/milestone4/section_scope_audit/

PURPOSE:
The first full transfer pass correctly matched every candidate performance to
one profile section, but some section labels do not represent NCAA college
teams. Examples can include high schools, clubs, unattached competition, or
college-school aliases not yet resolved to core.teams.

This script:
1. Summarizes every section without a resolved team.
2. Suggests a non-authoritative competition-scope class.
3. Identifies likely high-school / pre-collegiate sections.
4. Identifies unattached or club sections.
5. Flags possible college aliases for manual or rule-based resolution.
6. Produces revised audit categories for the production attribution layer.

Suggested classes are diagnostic only. They must not silently overwrite source
or analytical values.

Run from the repository root:

    python src/analysis/milestone4/audit_profile_section_scope.py
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "data/database/ncaa_track_analytics.duckdb"

INPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/transfer_attribution_full"
)
OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/section_scope_audit"
)

SECTION_PATH = INPUT_DIR / "school_section_mapping.csv"
ATTRIBUTION_PATH = INPUT_DIR / "performance_attribution_candidates.csv"
PROFILE_PATH = INPUT_DIR / "profile_parse_audit.csv"

WHITESPACE_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

HIGH_SCHOOL_NAME_PATTERNS = [
    r"\bhigh school\b",
    r"\bhs\b",
    r"\bprep\b",
    r"\bpreparatory\b",
    r"\bacademy\b",
    r"\bsecondary\b",
    r"\bcharter\b",
]

HIGH_SCHOOL_RESULT_PATTERNS = [
    r"/boys-",
    r"/girls-",
    r"\bboys\b",
    r"\bgirls\b",
    r"\bvarsity\b",
    r"\bjunior varsity\b",
    r"\bhigh school\b",
    r"\bstate championship",
    r"\bsectional\b",
    r"\bdistrict\b",
]

UNATTACHED_PATTERNS = [
    r"\bunattached\b",
    r"\buna\b",
    r"\bindependent\b",
    r"\bno team\b",
]

CLUB_PATTERNS = [
    r"\btrack club\b",
    r"\brunning club\b",
    r"\bathletic club\b",
    r"\bathletics club\b",
    r"\bclub\b",
]

COLLEGE_SIGNAL_PATTERNS = [
    r"\bncaa\b",
    r"\bcollege\b",
    r"\bcollegiate\b",
    r"\buniversity\b",
    r"\bconference\b",
    r"\bindoor championships\b",
    r"\boutdoor championships\b",
]


def clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return WHITESPACE_RE.sub(" ", str(value)).strip()


def normalize_name(value: object) -> str:
    text = clean_text(value).lower()
    text = text.replace("&amp;", "and")
    text = text.replace("&", "and")
    return NON_ALNUM_RE.sub("", text)


def contains_any(text: str, patterns: list[str]) -> bool:
    lowered = clean_text(text).lower()
    return any(re.search(pattern, lowered) for pattern in patterns)


def suggest_scope(
    school_name: str,
    evidence_text: str,
    best_core_similarity: float,
) -> tuple[str, str]:
    combined = f"{school_name} {evidence_text}"

    high_school_name = contains_any(
        school_name,
        HIGH_SCHOOL_NAME_PATTERNS,
    )
    high_school_result = contains_any(
        evidence_text,
        HIGH_SCHOOL_RESULT_PATTERNS,
    )
    unattached = contains_any(
        combined,
        UNATTACHED_PATTERNS,
    )
    club = contains_any(
        combined,
        CLUB_PATTERNS,
    )
    college_signal = contains_any(
        evidence_text,
        COLLEGE_SIGNAL_PATTERNS,
    )

    if unattached:
        return (
            "UNATTACHED_LIKELY",
            "School label or result evidence contains unattached/independent terminology.",
        )

    if club:
        return (
            "CLUB_LIKELY",
            "School label or result evidence contains club terminology.",
        )

    if high_school_name or high_school_result:
        return (
            "PRE_COLLEGIATE_LIKELY",
            "School label or result evidence contains high-school, boys/girls, varsity, or school-championship signals.",
        )

    if best_core_similarity >= 0.90:
        return (
            "CORE_SCHOOL_ALIAS_CANDIDATE",
            "Section label closely resembles an existing core school name.",
        )

    if college_signal:
        return (
            "OTHER_COLLEGE_OR_UNRESOLVED_ALIAS",
            "Meet evidence looks collegiate, but the section does not resolve to a core team.",
        )

    return (
        "UNKNOWN_NON_CORE_SECTION",
        "Insufficient evidence for a reliable diagnostic class.",
    )


def top_core_match(
    normalized_value: str,
    core_names: list[tuple[str, str]],
) -> tuple[str, float]:
    if not normalized_value:
        return "", 0.0

    best_name = ""
    best_score = 0.0

    for original_name, normalized_name in core_names:
        score = SequenceMatcher(
            None,
            normalized_value,
            normalized_name,
        ).ratio()

        if score > best_score:
            best_name = original_name
            best_score = score

    return best_name, best_score


def main() -> None:
    for required in [
        DB_PATH,
        SECTION_PATH,
        ATTRIBUTION_PATH,
        PROFILE_PATH,
    ]:
        if not required.exists():
            raise FileNotFoundError(f"Required input not found: {required}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sections = pd.read_csv(
        SECTION_PATH,
        dtype=str,
        keep_default_na=False,
    )
    attribution = pd.read_csv(
        ATTRIBUTION_PATH,
        dtype=str,
        keep_default_na=False,
    )
    profiles = pd.read_csv(
        PROFILE_PATH,
        dtype=str,
        keep_default_na=False,
    )

    unresolved_sections = sections.loc[
        sections["resolved_team_id"].str.strip() == ""
    ].copy()

    unresolved_performances = attribution.loc[
        attribution["analytical_team_id"].str.strip() == ""
    ].copy()

    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        core_school_frame = con.execute(
            """
            SELECT DISTINCT school_name
            FROM core.schools
            WHERE school_name IS NOT NULL
            ORDER BY school_name
            """
        ).fetchdf()
    finally:
        con.close()

    core_names = [
        (
            clean_text(name),
            normalize_name(name),
        )
        for name in core_school_frame["school_name"].tolist()
        if clean_text(name)
    ]

    profile_lookup = (
        profiles[
            [
                "athlete_id",
                "athlete_name",
                "unique_athletes_school",
                "profile_current_school",
            ]
        ]
        .drop_duplicates("athlete_id")
        .set_index("athlete_id")
        .to_dict("index")
    )

    performance_grouped = (
        unresolved_performances.groupby(
            [
                "athlete_id",
                "profile_section_index",
                "parsed_school_name",
            ],
            dropna=False,
        )
        .agg(
            performance_count=("performance_id", "count"),
            meet_count=("meet_id", "nunique"),
            first_season_year=("season_year", "min"),
            last_season_year=("season_year", "max"),
            sample_meet_names=(
                "meet_name",
                lambda values: " | ".join(
                    pd.Series(values)
                    .drop_duplicates()
                    .astype(str)
                    .head(8)
                    .tolist()
                ),
            ),
            sample_result_urls=(
                "result_url",
                lambda values: " | ".join(
                    pd.Series(values)
                    .drop_duplicates()
                    .astype(str)
                    .head(5)
                    .tolist()
                ),
            ),
            sample_events=(
                "event",
                lambda values: " | ".join(
                    pd.Series(values)
                    .drop_duplicates()
                    .astype(str)
                    .head(12)
                    .tolist()
                ),
            ),
        )
        .reset_index()
    )

    detail_rows: list[dict[str, object]] = []

    for row in unresolved_sections.to_dict("records"):
        athlete_id = clean_text(row.get("athlete_id"))
        section_index = clean_text(row.get("section_index"))
        school_name = clean_text(row.get("school_name_clean"))

        matches = performance_grouped.loc[
            (
                performance_grouped["athlete_id"].astype(str)
                == athlete_id
            )
            & (
                performance_grouped[
                    "profile_section_index"
                ].astype(str)
                == section_index
            )
        ]

        if matches.empty:
            evidence = {}
        else:
            evidence = matches.iloc[0].to_dict()

        evidence_text = " ".join(
            [
                clean_text(evidence.get("sample_meet_names")),
                clean_text(evidence.get("sample_result_urls")),
                clean_text(evidence.get("sample_events")),
            ]
        )

        normalized = normalize_name(school_name)
        best_name, best_similarity = top_core_match(
            normalized,
            core_names,
        )

        scope_class, scope_reason = suggest_scope(
            school_name=school_name,
            evidence_text=evidence_text,
            best_core_similarity=best_similarity,
        )

        profile = profile_lookup.get(athlete_id, {})

        detail_rows.append(
            {
                "athlete_id": athlete_id,
                "athlete_name": clean_text(
                    profile.get("athlete_name")
                ),
                "section_index": section_index,
                "section_school_name": school_name,
                "normalized_section_school_name": normalized,
                "suggested_scope_class": scope_class,
                "suggestion_reason": scope_reason,
                "best_core_school_match": best_name,
                "best_core_similarity": round(
                    best_similarity,
                    4,
                ),
                "performance_count": evidence.get(
                    "performance_count",
                    0,
                ),
                "meet_count": evidence.get("meet_count", 0),
                "first_season_year": evidence.get(
                    "first_season_year",
                    "",
                ),
                "last_season_year": evidence.get(
                    "last_season_year",
                    "",
                ),
                "sample_meet_names": clean_text(
                    evidence.get("sample_meet_names")
                ),
                "sample_result_urls": clean_text(
                    evidence.get("sample_result_urls")
                ),
                "sample_events": clean_text(
                    evidence.get("sample_events")
                ),
                "profile_current_school": clean_text(
                    profile.get("profile_current_school")
                ),
                "unique_athletes_school": clean_text(
                    profile.get("unique_athletes_school")
                ),
                "section_team_match_status": clean_text(
                    row.get("team_match_status")
                ),
                "attribution_version": clean_text(
                    row.get("attribution_version")
                ),
            }
        )

    detail = pd.DataFrame(detail_rows)
    detail.to_csv(
        OUTPUT_DIR / "unresolved_section_classification.csv",
        index=False,
    )

    class_summary = (
        detail.groupby(
            "suggested_scope_class",
            dropna=False,
        )
        .agg(
            section_count=("section_school_name", "count"),
            athlete_count=("athlete_id", "nunique"),
            performance_count=("performance_count", "sum"),
            minimum_year=("first_season_year", "min"),
            maximum_year=("last_season_year", "max"),
        )
        .reset_index()
        .sort_values(
            "performance_count",
            ascending=False,
        )
    )
    class_summary.to_csv(
        OUTPUT_DIR / "suggested_scope_class_summary.csv",
        index=False,
    )

    alias_candidates = detail.loc[
        detail["suggested_scope_class"].isin(
            [
                "CORE_SCHOOL_ALIAS_CANDIDATE",
                "OTHER_COLLEGE_OR_UNRESOLVED_ALIAS",
            ]
        )
    ].copy()

    alias_candidates.to_csv(
        OUTPUT_DIR / "college_alias_candidates.csv",
        index=False,
    )

    pre_collegiate = detail.loc[
        detail["suggested_scope_class"]
        == "PRE_COLLEGIATE_LIKELY"
    ].copy()

    pre_collegiate.to_csv(
        OUTPUT_DIR / "pre_collegiate_sections.csv",
        index=False,
    )

    hard_checks = pd.DataFrame(
        [
            {
                "check_name": "unresolved_sections_present",
                "failed_row_count": 0,
                "observed_value": len(detail),
                "interpretation": (
                    "Informational. A null core team is valid for "
                    "classified non-collegiate sections."
                ),
            },
            {
                "check_name": "unknown_non_core_sections",
                "failed_row_count": int(
                    (
                        detail["suggested_scope_class"]
                        == "UNKNOWN_NON_CORE_SECTION"
                    ).sum()
                ),
                "observed_value": int(
                    (
                        detail["suggested_scope_class"]
                        == "UNKNOWN_NON_CORE_SECTION"
                    ).sum()
                ),
                "interpretation": (
                    "Requires additional classification or review."
                ),
            },
            {
                "check_name": "possible_college_alias_sections",
                "failed_row_count": int(
                    detail["suggested_scope_class"].isin(
                        [
                            "CORE_SCHOOL_ALIAS_CANDIDATE",
                            "OTHER_COLLEGE_OR_UNRESOLVED_ALIAS",
                        ]
                    ).sum()
                ),
                "observed_value": int(
                    detail["suggested_scope_class"].isin(
                        [
                            "CORE_SCHOOL_ALIAS_CANDIDATE",
                            "OTHER_COLLEGE_OR_UNRESOLVED_ALIAS",
                        ]
                    ).sum()
                ),
                "interpretation": (
                    "Must be resolved or explicitly classified as "
                    "non-D1 college before production loading."
                ),
            },
        ]
    )

    hard_checks.to_csv(
        OUTPUT_DIR / "scope_audit_checks.csv",
        index=False,
    )

    summary = f"""MILESTONE 4 PROFILE-SECTION SCOPE AUDIT
=================================================
Database connection: read-only
Prior Milestone 4 outputs modified: no
Raw files modified: no

INPUT COUNTS
- Unresolved school sections: {len(unresolved_sections):,}
- Performances in unresolved sections: {len(unresolved_performances):,}
- Athletes represented: {unresolved_performances['athlete_id'].nunique():,}

OUTPUTS
- unresolved_section_classification.csv
- suggested_scope_class_summary.csv
- college_alias_candidates.csv
- pre_collegiate_sections.csv
- scope_audit_checks.csv

INTERPRETATION
A profile section that does not resolve to core.teams is not automatically a
parser failure. High-school, club, unattached, and other non-core sections
should retain a null analytical_team_id while receiving an explicit
competition_scope / entity_type classification.

Only unresolved sections that appear to represent NCAA or other collegiate
institutions should remain blocking exceptions.
"""

    (OUTPUT_DIR / "section_scope_audit_summary.txt").write_text(
        summary,
        encoding="utf-8",
    )

    print("Profile-section scope audit complete.")
    print(f"Outputs: {OUTPUT_DIR}")
    print(
        f"Sections: {len(detail):,}; "
        f"performances: {len(unresolved_performances):,}."
    )
    print("Database connection was read-only.")


if __name__ == "__main__":
    main()
