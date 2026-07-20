#!/usr/bin/env python3
"""
Build the complete Milestone 4 analytical layer for transfer candidates.

READ-ONLY GUARANTEE
-------------------
This script does not modify:
- the Milestone 3 DuckDB database;
- raw TFRRS HTML;
- prior Milestone 4 outputs.

It combines:
1. All parsed profile sections for the 2,448 transfer-candidate athletes.
2. Resolved core-team sections.
3. The completed 115-row non-core section classification registry.
4. All 164,964 transfer-candidate performance attributions.
5. Source HTML provenance and checksums.

INPUTS
------
data/processed/milestone4/transfer_attribution_full/
    school_section_mapping.csv
    performance_attribution_candidates.csv
    profile_parse_audit.csv
    manual_fixture_validation.csv

data/processed/milestone4/profile_section_classification/
    profile_section_classification_v1.csv

data/raw/athlete_pages/
    {athlete_id}.html

OUTPUTS
-------
data/processed/milestone4/transfer_candidate_analytical_layer/
    profile_sections.csv
    affiliation_entities.csv
    entity_aliases.csv
    performance_attribution.csv
    profile_section_summary.csv
    performance_attribution_summary.csv
    hard_checks.csv
    build_report.txt

PURPOSE
-------
This is the final dry-run analytical design for the transfer-candidate
population. It should pass before the same logic is scaled to every saved
athlete profile and before permanent DuckDB analytics/audit tables are loaded.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]

TRANSFER_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/transfer_attribution_full"
)

CLASSIFICATION_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/profile_section_classification"
)

ATHLETE_PAGE_DIR = PROJECT_ROOT / "data/raw/athlete_pages"

SECTION_MAPPING_PATH = TRANSFER_DIR / "school_section_mapping.csv"
PERFORMANCE_PATH = (
    TRANSFER_DIR / "performance_attribution_candidates.csv"
)
PROFILE_AUDIT_PATH = TRANSFER_DIR / "profile_parse_audit.csv"
FIXTURE_PATH = TRANSFER_DIR / "manual_fixture_validation.csv"

NON_CORE_CLASSIFICATION_PATH = (
    CLASSIFICATION_DIR / "profile_section_classification_v1.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "transfer_candidate_analytical_layer"
)

LAYER_VERSION = "m4_transfer_candidate_layer_v1.1"
CLASSIFICATION_VERSION = "m4_section_classification_v1.1"

WHITESPACE_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return WHITESPACE_RE.sub(" ", str(value)).strip()


def normalize_name(value: object) -> str:
    text = clean_text(value).lower()
    text = text.replace("&amp;", "and")
    text = text.replace("&", "and")
    return NON_ALNUM_RE.sub("", text)


def parse_bool(value: object, default: bool = False) -> bool:
    text = clean_text(value).lower()

    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False

    return default


def stable_id(prefix: str, *parts: object) -> str:
    joined = "|".join(clean_text(part) for part in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)

    return digest.hexdigest()


def normalize_division(value: object) -> str:
    text = clean_text(value).upper().replace(" ", "")

    if text in {"D1", "DI", "DIVISIONI", "NCAAD1"}:
        return "NCAA_D1"
    if text in {"D2", "DII", "DIVISIONII", "NCAAD2"}:
        return "NCAA_D2"
    if text in {"D3", "DIII", "DIVISIONIII", "NCAAD3"}:
        return "NCAA_D3"

    return "OTHER_COLLEGE"


def core_section_classification(
    row: dict[str, Any],
) -> dict[str, Any]:
    competition_level = normalize_division(
        row.get("resolved_division")
    )
    eligible = competition_level == "NCAA_D1"

    governing_system = (
        "NCAA"
        if competition_level.startswith("NCAA_")
        else "OTHER"
    )

    canonical_name = (
        clean_text(row.get("resolved_school_name"))
        or clean_text(row.get("school_name_clean"))
    )

    resolved_team_id = clean_text(row.get("resolved_team_id"))
    resolved_school_id = clean_text(row.get("resolved_school_id"))

    return {
        "career_stage": "COLLEGIATE",
        "governing_system": governing_system,
        "competition_level": competition_level,
        "representation_type": "SCHOOL",
        "entity_type": "CORE_SCHOOL_TEAM",
        "canonical_entity_name": canonical_name,
        "resolved_team_id": resolved_team_id,
        "resolved_school_id": resolved_school_id,
        "resolved_school_name": clean_text(
            row.get("resolved_school_name")
        ),
        "resolved_division": clean_text(
            row.get("resolved_division")
        ),
        "resolution_status": "CORE_TEAM_MATCH",
        "resolution_method_final": clean_text(
            row.get("resolution_method")
        )
        or "TRANSFER_SECTION_TEAM_RESOLUTION",
        "resolution_confidence": "HIGH",
        "manual_review_required": False,
        "manual_review_status": "NOT_REQUIRED",
        "manual_review_note": "",
        "d1_development_eligible": eligible,
        "frontier_eligible": eligible,
        "school_stint_eligible": eligible,
        "pre_college_baseline_eligible": False,
        "sensitivity_analysis_eligible": eligible,
        "eligibility_status": (
            "ELIGIBLE_D1"
            if eligible
            else "EXCLUDED_NON_D1"
        ),
        "exclusion_reason": (
            ""
            if eligible
            else "NON_D1_COLLEGE_PERFORMANCE"
        ),
        "classification_version": CLASSIFICATION_VERSION,
    }


def non_core_section_lookup(
    frame: pd.DataFrame,
) -> dict[tuple[str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str], dict[str, Any]] = {}

    for row in frame.to_dict("records"):
        key = (
            clean_text(row.get("athlete_id")),
            clean_text(row.get("section_index")),
        )
        lookup[key] = row

    return lookup


def main() -> None:
    required_paths = [
        SECTION_MAPPING_PATH,
        PERFORMANCE_PATH,
        PROFILE_AUDIT_PATH,
        FIXTURE_PATH,
        NON_CORE_CLASSIFICATION_PATH,
    ]

    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(f"Required input not found: {path}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sections = pd.read_csv(
        SECTION_MAPPING_PATH,
        dtype=str,
        keep_default_na=False,
    )
    performances = pd.read_csv(
        PERFORMANCE_PATH,
        dtype=str,
        keep_default_na=False,
    )
    profile_audit = pd.read_csv(
        PROFILE_AUDIT_PATH,
        dtype=str,
        keep_default_na=False,
    )
    fixtures = pd.read_csv(
        FIXTURE_PATH,
        dtype=str,
        keep_default_na=False,
    )
    non_core = pd.read_csv(
        NON_CORE_CLASSIFICATION_PATH,
        dtype=str,
        keep_default_na=False,
    )

    non_core_lookup = non_core_section_lookup(non_core)

    athlete_ids = sorted(
        {
            clean_text(value)
            for value in sections["athlete_id"].tolist()
        }
    )

    checksum_by_athlete: dict[str, str] = {}
    html_path_by_athlete: dict[str, str] = {}

    total_athletes = len(athlete_ids)

    for position, athlete_id in enumerate(
        athlete_ids,
        start=1,
    ):
        html_path = ATHLETE_PAGE_DIR / f"{athlete_id}.html"
        html_path_by_athlete[athlete_id] = str(html_path)

        checksum_by_athlete[athlete_id] = (
            file_sha256(html_path)
            if html_path.exists()
            else ""
        )

        if position % 250 == 0 or position == total_athletes:
            print(
                f"Hashed profiles: {position:,}/"
                f"{total_athletes:,}"
            )

    profile_name_lookup = (
        profile_audit[
            ["athlete_id", "athlete_name"]
        ]
        .drop_duplicates("athlete_id")
        .set_index("athlete_id")["athlete_name"]
        .to_dict()
    )

    section_rows: list[dict[str, Any]] = []

    for row in sections.to_dict("records"):
        athlete_id = clean_text(row.get("athlete_id"))
        section_index = clean_text(row.get("section_index"))
        source_name = clean_text(row.get("school_name_clean"))
        key = (athlete_id, section_index)

        if clean_text(row.get("resolved_team_id")):
            classification = core_section_classification(row)
        else:
            source = non_core_lookup.get(key)

            if source is None:
                classification = {
                    "career_stage": "UNKNOWN",
                    "governing_system": "UNKNOWN",
                    "competition_level": "UNKNOWN",
                    "representation_type": "UNKNOWN",
                    "entity_type": "UNKNOWN_ENTITY",
                    "canonical_entity_name": source_name,
                    "resolved_team_id": "",
                    "resolved_school_id": "",
                    "resolved_school_name": "",
                    "resolved_division": "",
                    "resolution_status": "UNKNOWN",
                    "resolution_method_final": "UNRESOLVED",
                    "resolution_confidence": "UNRESOLVED",
                    "manual_review_required": True,
                    "manual_review_status": "PENDING",
                    "manual_review_note": (
                        "Non-core section missing from completed "
                        "classification registry."
                    ),
                    "d1_development_eligible": False,
                    "frontier_eligible": False,
                    "school_stint_eligible": False,
                    "pre_college_baseline_eligible": False,
                    "sensitivity_analysis_eligible": False,
                    "eligibility_status": "EXCLUDED_PENDING_REVIEW",
                    "exclusion_reason": "UNCLASSIFIED_PROFILE_SECTION",
                    "classification_version": CLASSIFICATION_VERSION,
                }
            else:
                classification = {
                    "career_stage": clean_text(
                        source.get("career_stage")
                    ),
                    "governing_system": clean_text(
                        source.get("governing_system")
                    ),
                    "competition_level": clean_text(
                        source.get("competition_level")
                    ),
                    "representation_type": clean_text(
                        source.get("representation_type")
                    ),
                    "entity_type": clean_text(
                        source.get("entity_type")
                    ),
                    "canonical_entity_name": clean_text(
                        source.get("canonical_entity_name")
                    ),
                    "resolved_team_id": clean_text(
                        source.get("resolved_team_id")
                    ),
                    "resolved_school_id": clean_text(
                        source.get("resolved_school_id")
                    ),
                    "resolved_school_name": clean_text(
                        source.get("resolved_school_name")
                    ),
                    "resolved_division": clean_text(
                        source.get("resolved_division")
                    ),
                    "resolution_status": clean_text(
                        source.get("resolution_status")
                    ),
                    "resolution_method_final": clean_text(
                        source.get("resolution_method")
                    ),
                    "resolution_confidence": clean_text(
                        source.get("resolution_confidence")
                    ),
                    "manual_review_required": parse_bool(
                        source.get("manual_review_required")
                    ),
                    "manual_review_status": clean_text(
                        source.get("manual_review_status")
                    ),
                    "manual_review_note": clean_text(
                        source.get("manual_review_note")
                    ),
                    "d1_development_eligible": parse_bool(
                        source.get("d1_development_eligible")
                    ),
                    "frontier_eligible": parse_bool(
                        source.get("frontier_eligible")
                    ),
                    "school_stint_eligible": parse_bool(
                        source.get("school_stint_eligible")
                    ),
                    "pre_college_baseline_eligible": parse_bool(
                        source.get(
                            "pre_college_baseline_eligible"
                        )
                    ),
                    "sensitivity_analysis_eligible": parse_bool(
                        source.get(
                            "sensitivity_analysis_eligible"
                        )
                    ),
                    "eligibility_status": clean_text(
                        source.get("eligibility_status")
                    ),
                    "exclusion_reason": clean_text(
                        source.get("exclusion_reason")
                    ),
                    "classification_version": clean_text(
                        source.get("classification_version")
                    ),
                }

        canonical_name = (
            clean_text(
                classification.get("canonical_entity_name")
            )
            or source_name
        )

        profile_section_id = stable_id(
            "m4sec",
            athlete_id,
            section_index,
            source_name,
        )

        analytical_entity_id = stable_id(
            "m4ent",
            normalize_name(canonical_name),
            clean_text(classification.get("entity_type")),
            clean_text(classification.get("governing_system")),
            clean_text(classification.get("competition_level")),
        )

        section_rows.append(
            {
                "profile_section_id": profile_section_id,
                "analytical_entity_id": analytical_entity_id,
                "athlete_id": athlete_id,
                "athlete_name": clean_text(
                    profile_name_lookup.get(athlete_id)
                ),
                "section_index": section_index,
                "source_section_name": source_name,
                "normalized_section_name": normalize_name(
                    source_name
                ),
                "school_name_raw": clean_text(
                    row.get("school_name_raw")
                ),
                "marker_text": clean_text(
                    row.get("marker_text")
                ),
                "section_attribution_method": clean_text(
                    row.get("section_attribution_method")
                ),
                "athlete_gender": clean_text(
                    row.get("athlete_gender")
                ),
                "source_team_match_status": clean_text(
                    row.get("team_match_status")
                ),
                "source_team_resolution_method": clean_text(
                    row.get("resolution_method")
                ),
                "roster_evidence_rows": clean_text(
                    row.get("roster_evidence_rows")
                ),
                "roster_seasons": clean_text(
                    row.get("roster_seasons")
                ),
                **classification,
                "source_html_file": html_path_by_athlete.get(
                    athlete_id,
                    "",
                ),
                "source_html_sha256": checksum_by_athlete.get(
                    athlete_id,
                    "",
                ),
                "source_attribution_version": clean_text(
                    row.get("attribution_version")
                ),
                "analytical_layer_version": LAYER_VERSION,
            }
        )

    profile_sections = pd.DataFrame(section_rows)

    profile_sections.to_csv(
        OUTPUT_DIR / "profile_sections.csv",
        index=False,
    )

    section_join_columns = [
        "athlete_id",
        "section_index",
        "profile_section_id",
        "analytical_entity_id",
        "career_stage",
        "governing_system",
        "competition_level",
        "representation_type",
        "entity_type",
        "canonical_entity_name",
        "resolved_team_id",
        "resolved_school_id",
        "resolved_school_name",
        "resolved_division",
        "resolution_status",
        "resolution_method_final",
        "resolution_confidence",
        "manual_review_required",
        "manual_review_status",
        "d1_development_eligible",
        "frontier_eligible",
        "school_stint_eligible",
        "pre_college_baseline_eligible",
        "sensitivity_analysis_eligible",
        "eligibility_status",
        "exclusion_reason",
        "classification_version",
        "source_html_file",
        "source_html_sha256",
    ]

    performance_frame = performances.copy()
    performance_frame["profile_section_index"] = (
        performance_frame["profile_section_index"].astype(str)
    )

    performance_frame = performance_frame.merge(
        profile_sections[section_join_columns],
        how="left",
        left_on=["athlete_id", "profile_section_index"],
        right_on=["athlete_id", "section_index"],
        validate="many_to_one",
        suffixes=("", "_section"),
    )

    performance_frame["final_analytical_team_id"] = (
        performance_frame["resolved_team_id"]
    )
    performance_frame["final_analytical_school_id"] = (
        performance_frame["resolved_school_id"]
    )
    performance_frame["final_analytical_school_name"] = (
        performance_frame["resolved_school_name"]
    )

    def final_status(row: pd.Series) -> str:
        competition_level = clean_text(
            row.get("competition_level")
        )
        original_team = clean_text(
            row.get("original_team_id")
        )
        analytical_team = clean_text(
            row.get("final_analytical_team_id")
        )

        if competition_level == "UNKNOWN":
            return "UNRESOLVED_CLASSIFICATION"

        if competition_level == "NCAA_D1":
            if not analytical_team:
                return "UNRESOLVED_D1_TEAM"
            if analytical_team == original_team:
                return "ORIGINAL_D1_TEAM_MATCH"
            return "D1_TEAM_CORRECTION"

        return "NON_D1_SCOPE_CORRECTION"

    performance_frame["final_attribution_status"] = (
        performance_frame.apply(final_status, axis=1)
    )
    performance_frame["analytical_layer_version"] = LAYER_VERSION

    performance_frame.to_csv(
        OUTPUT_DIR / "performance_attribution.csv",
        index=False,
    )

    entity_columns = [
        "analytical_entity_id",
        "canonical_entity_name",
        "entity_type",
        "career_stage",
        "governing_system",
        "competition_level",
        "representation_type",
        "resolved_team_id",
        "resolved_school_id",
        "resolved_school_name",
        "resolved_division",
        "resolution_status",
        "resolution_method_final",
        "resolution_confidence",
        "classification_version",
        "analytical_layer_version",
    ]

    entities = (
        profile_sections[entity_columns]
        .drop_duplicates("analytical_entity_id")
        .sort_values(
            [
                "competition_level",
                "canonical_entity_name",
            ]
        )
    )

    entities.to_csv(
        OUTPUT_DIR / "affiliation_entities.csv",
        index=False,
    )

    aliases = (
        profile_sections[
            [
                "source_section_name",
                "normalized_section_name",
                "analytical_entity_id",
                "canonical_entity_name",
                "entity_type",
                "governing_system",
                "competition_level",
                "resolved_team_id",
                "resolved_school_id",
                "resolution_status",
                "resolution_method_final",
                "resolution_confidence",
                "classification_version",
                "analytical_layer_version",
            ]
        ]
        .drop_duplicates(
            [
                "normalized_section_name",
                "analytical_entity_id",
            ]
        )
        .sort_values(
            [
                "normalized_section_name",
                "analytical_entity_id",
            ]
        )
    )

    aliases.insert(
        0,
        "alias_id",
        [
            stable_id(
                "m4alias",
                row["normalized_section_name"],
                row["analytical_entity_id"],
            )
            for row in aliases.to_dict("records")
        ],
    )

    aliases.to_csv(
        OUTPUT_DIR / "entity_aliases.csv",
        index=False,
    )

    profile_summary = (
        profile_sections.groupby(
            [
                "career_stage",
                "governing_system",
                "competition_level",
                "resolution_status",
                "manual_review_required",
            ],
            dropna=False,
        )
        .agg(
            section_count=("profile_section_id", "count"),
            athlete_count=("athlete_id", "nunique"),
            entity_count=("analytical_entity_id", "nunique"),
        )
        .reset_index()
        .sort_values(
            "section_count",
            ascending=False,
        )
    )

    profile_summary.to_csv(
        OUTPUT_DIR / "profile_section_summary.csv",
        index=False,
    )

    attribution_summary = (
        performance_frame.groupby(
            [
                "final_attribution_status",
                "career_stage",
                "governing_system",
                "competition_level",
                "eligibility_status",
            ],
            dropna=False,
        )
        .agg(
            performance_count=("performance_id", "count"),
            athlete_count=("athlete_id", "nunique"),
            meet_count=("meet_id", "nunique"),
            season_count=("season_id", "nunique"),
        )
        .reset_index()
        .sort_values(
            "performance_count",
            ascending=False,
        )
    )

    attribution_summary.to_csv(
        OUTPUT_DIR / "performance_attribution_summary.csv",
        index=False,
    )

    duplicate_section_keys = int(
        profile_sections.duplicated(
            ["athlete_id", "section_index"]
        ).sum()
    )
    duplicate_performance_ids = int(
        performance_frame.duplicated(
            ["performance_id"]
        ).sum()
    )
    missing_section_join = int(
        performance_frame["profile_section_id"]
        .fillna("")
        .eq("")
        .sum()
    )
    unclassified_sections = int(
        profile_sections["competition_level"]
        .fillna("")
        .isin(["", "UNKNOWN"])
        .sum()
    )
    manual_review_sections = int(
        profile_sections["manual_review_required"].sum()
    )
    d1_without_team = int(
        (
            (
                profile_sections["competition_level"]
                == "NCAA_D1"
            )
            & (
                profile_sections["resolved_team_id"]
                .fillna("")
                .eq("")
            )
        ).sum()
    )
    eligible_without_team = int(
        (
            profile_sections["d1_development_eligible"]
            & profile_sections["resolved_team_id"]
            .fillna("")
            .eq("")
        ).sum()
    )
    high_school_d1_eligible = int(
        (
            (
                profile_sections["competition_level"]
                == "HIGH_SCHOOL"
            )
            & profile_sections["d1_development_eligible"]
        ).sum()
    )
    non_d1_stint_eligible = int(
        (
            (
                profile_sections["competition_level"]
                != "NCAA_D1"
            )
            & profile_sections["school_stint_eligible"]
        ).sum()
    )
    fixture_failures = int(
        (
            fixtures["fixture_status"].str.upper()
            != "PASS"
        ).sum()
    )
    non_exact_profile_matches = int(
        (
            performance_frame["profile_match_status"]
            != "RESULT_URL_MATCH"
        ).sum()
    )
    unresolved_performances = int(
        performance_frame["final_attribution_status"]
        .isin(
            [
                "UNRESOLVED_CLASSIFICATION",
                "UNRESOLVED_D1_TEAM",
            ]
        )
        .sum()
    )
    missing_html_checksums = int(
        profile_sections["source_html_sha256"]
        .fillna("")
        .eq("")
        .sum()
    )
    completed_review_pending_status = int(
        (
            (~profile_sections["manual_review_required"])
            & (
                profile_sections["eligibility_status"]
                == "EXCLUDED_PENDING_REVIEW"
            )
        ).sum()
    )
    pending_review_performances = int(
        (
            performance_frame["eligibility_status"]
            == "EXCLUDED_PENDING_REVIEW"
        ).sum()
    )

    checks = [
        {
            "check_name": "section_row_count_reconciles",
            "failed_row_count": (
                0
                if len(profile_sections) == len(sections)
                else abs(len(profile_sections) - len(sections))
            ),
            "observed_value": len(profile_sections),
            "expected_value": len(sections),
        },
        {
            "check_name": "performance_row_count_reconciles",
            "failed_row_count": (
                0
                if len(performance_frame) == len(performances)
                else abs(
                    len(performance_frame) - len(performances)
                )
            ),
            "observed_value": len(performance_frame),
            "expected_value": len(performances),
        },
        {
            "check_name": "duplicate_section_keys",
            "failed_row_count": duplicate_section_keys,
            "observed_value": duplicate_section_keys,
            "expected_value": 0,
        },
        {
            "check_name": "duplicate_performance_ids",
            "failed_row_count": duplicate_performance_ids,
            "observed_value": duplicate_performance_ids,
            "expected_value": 0,
        },
        {
            "check_name": "performances_without_profile_section",
            "failed_row_count": missing_section_join,
            "observed_value": missing_section_join,
            "expected_value": 0,
        },
        {
            "check_name": "unclassified_profile_sections",
            "failed_row_count": unclassified_sections,
            "observed_value": unclassified_sections,
            "expected_value": 0,
        },
        {
            "check_name": "manual_review_sections",
            "failed_row_count": manual_review_sections,
            "observed_value": manual_review_sections,
            "expected_value": 0,
        },
        {
            "check_name": "D1_sections_without_team",
            "failed_row_count": d1_without_team,
            "observed_value": d1_without_team,
            "expected_value": 0,
        },
        {
            "check_name": "eligible_sections_without_team",
            "failed_row_count": eligible_without_team,
            "observed_value": eligible_without_team,
            "expected_value": 0,
        },
        {
            "check_name": "high_school_marked_D1_eligible",
            "failed_row_count": high_school_d1_eligible,
            "observed_value": high_school_d1_eligible,
            "expected_value": 0,
        },
        {
            "check_name": "non_D1_section_marked_stint_eligible",
            "failed_row_count": non_d1_stint_eligible,
            "observed_value": non_d1_stint_eligible,
            "expected_value": 0,
        },
        {
            "check_name": "manual_fixture_failures",
            "failed_row_count": fixture_failures,
            "observed_value": fixture_failures,
            "expected_value": 0,
        },
        {
            "check_name": "non_exact_profile_URL_matches",
            "failed_row_count": non_exact_profile_matches,
            "observed_value": non_exact_profile_matches,
            "expected_value": 0,
        },
        {
            "check_name": "unresolved_performances",
            "failed_row_count": unresolved_performances,
            "observed_value": unresolved_performances,
            "expected_value": 0,
        },
        {
            "check_name": "sections_without_HTML_checksum",
            "failed_row_count": missing_html_checksums,
            "observed_value": missing_html_checksums,
            "expected_value": 0,
        },
        {
            "check_name": "completed_review_with_pending_eligibility",
            "failed_row_count": completed_review_pending_status,
            "observed_value": completed_review_pending_status,
            "expected_value": 0,
        },
        {
            "check_name": "performances_with_pending_review_eligibility",
            "failed_row_count": pending_review_performances,
            "observed_value": pending_review_performances,
            "expected_value": 0,
        },
    ]

    hard_checks = pd.DataFrame(checks)
    hard_checks.to_csv(
        OUTPUT_DIR / "hard_checks.csv",
        index=False,
    )

    failed_checks = int(
        (hard_checks["failed_row_count"] > 0).sum()
    )

    status_counts = (
        performance_frame["final_attribution_status"]
        .value_counts()
        .to_dict()
    )

    report = f"""MILESTONE 4 TRANSFER-CANDIDATE ANALYTICAL LAYER
============================================================
Analytical layer version: {LAYER_VERSION}
Classification version: {CLASSIFICATION_VERSION}
Source database modified: no
Raw files modified: no

PROFILE SECTIONS
- Athletes: {profile_sections['athlete_id'].nunique():,}
- Sections: {len(profile_sections):,}
- Analytical entities: {len(entities):,}
- Aliases: {len(aliases):,}
- Unclassified sections: {unclassified_sections:,}
- Manual-review sections: {manual_review_sections:,}

PERFORMANCES
- Total transfer-candidate performances: {len(performance_frame):,}
- Original D1 team matches: {status_counts.get('ORIGINAL_D1_TEAM_MATCH', 0):,}
- D1 team corrections: {status_counts.get('D1_TEAM_CORRECTION', 0):,}
- Non-D1 scope corrections: {status_counts.get('NON_D1_SCOPE_CORRECTION', 0):,}
- Unresolved performances: {unresolved_performances:,}

PROVENANCE
- Unique source athlete HTML files: {len(athlete_ids):,}
- Sections missing HTML checksum: {missing_html_checksums:,}

VALIDATION
- Hard checks: {len(hard_checks):,}
- Failed hard checks: {failed_checks:,}
- Manual fixture failures: {fixture_failures:,}

OUTPUTS
- profile_sections.csv
- affiliation_entities.csv
- entity_aliases.csv
- performance_attribution.csv
- profile_section_summary.csv
- performance_attribution_summary.csv
- hard_checks.csv

NEXT GATE
This dry-run layer must have zero failed hard checks before the parser and
classification logic are scaled to all saved athlete profiles.
"""

    (OUTPUT_DIR / "build_report.txt").write_text(
        report,
        encoding="utf-8",
    )

    print("Transfer-candidate analytical layer complete.")
    print(f"Outputs: {OUTPUT_DIR}")
    print(
        f"Sections: {len(profile_sections):,}; "
        f"performances: {len(performance_frame):,}; "
        f"failed checks: {failed_checks:,}."
    )
    print("Database and raw files were not modified.")


if __name__ == "__main__":
    main()
