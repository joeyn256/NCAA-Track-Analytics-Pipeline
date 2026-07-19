#!/usr/bin/env python3
"""
Milestone 4 profile-section classification registry builder.

READ-ONLY GUARANTEE
-------------------
This script does not modify:
- the Milestone 3 DuckDB database;
- raw TFRRS HTML;
- prior Milestone 4 attribution outputs.

It reads the section-scope audit and creates a versioned analytical
classification registry plus a focused manual-review queue.

INPUTS
------
data/processed/milestone4/section_scope_audit/
    unresolved_section_classification.csv

data/processed/milestone4/transfer_attribution_full/
    school_section_mapping.csv

data/database/
    ncaa_track_analytics.duckdb

OPTIONAL MANUAL OVERRIDES
-------------------------
config/milestone4/profile_section_classification_overrides.csv

The optional override file may contain:

    athlete_id
    section_index
    career_stage
    governing_system
    competition_level
    representation_type
    entity_type
    canonical_entity_name
    resolved_team_id
    resolution_status
    resolution_method
    resolution_confidence
    d1_development_eligible
    frontier_eligible
    school_stint_eligible
    pre_college_baseline_eligible
    sensitivity_analysis_eligible
    exclusion_reason
    manual_review_status
    manual_review_note

OUTPUTS
-------
data/processed/milestone4/profile_section_classification/

    profile_section_classification_v1.csv
    affiliation_entity_registry_v1.csv
    entity_alias_registry_v1.csv
    manual_review_queue.csv
    manual_review_overrides_template.csv
    classification_summary.csv
    classification_hard_checks.csv
    classification_report.txt

METHOD
------
Automatic classification is intentionally conservative. A section is
automatically resolved only when there is strong evidence:

- exact normalized core-school + same-gender team match;
- explicit pre-collegiate / high-school evidence;
- explicit NJCAA evidence;
- explicit NWAC evidence;
- explicit NAIA evidence;
- explicit NCAA Division II or Division III evidence;
- explicit unattached or club evidence.

Fuzzy similarity is retained as review context but is never used as the sole
basis for resolving an entity.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]

DB_PATH = (
    PROJECT_ROOT
    / "data/database/ncaa_track_analytics.duckdb"
)

SCOPE_AUDIT_PATH = (
    PROJECT_ROOT
    / "data/processed/milestone4/section_scope_audit/"
    / "unresolved_section_classification.csv"
)

SECTION_MAPPING_PATH = (
    PROJECT_ROOT
    / "data/processed/milestone4/transfer_attribution_full/"
    / "school_section_mapping.csv"
)

OVERRIDE_PATH = (
    PROJECT_ROOT
    / "config/milestone4/"
    / "profile_section_classification_overrides.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "profile_section_classification"
)

CLASSIFICATION_VERSION = "m4_section_classification_v1.1"

WHITESPACE_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


PRE_COLLEGIATE_PATTERNS = [
    r"\bhigh school\b",
    r"\bhs\b",
    r"\bboys\b",
    r"\bgirls\b",
    r"\bvarsity\b",
    r"\bjunior varsity\b",
    r"\bfhsaa\b",
    r"\buil\b",
    r"\blhsaa\b",
    r"\bnysp(?:h)?saa\b",
    r"\bdistrict\b",
    r"\bsectional\b",
    r"\bstate track\b",
    r"\bstate championship\b",
    r"/boys-",
    r"/girls-",
]

NJCAA_PATTERNS = [
    r"\bnjcaa\b",
    r"\bjuco\b",
    r"\bjunior college\b",
]

NWAC_PATTERNS = [
    r"\bnwac\b",
]

NAIA_PATTERNS = [
    r"\bnaia\b",
]

NCAA_D2_PATTERNS = [
    r"\bncaa division ii\b",
    r"\bncaa div(?:ision)? 2\b",
    r"\bncaa dii\b",
]

NCAA_D3_PATTERNS = [
    r"\bncaa division iii\b",
    r"\bncaa div(?:ision)? 3\b",
    r"\bncaa diii\b",
]

UNATTACHED_PATTERNS = [
    r"\bunattached\b",
    r"\bindependent\b",
    r"\bno team\b",
]

CLUB_PATTERNS = [
    r"\btrack club\b",
    r"\brunning club\b",
    r"\bathletic club\b",
    r"\bathletics club\b",
]

PROFESSIONAL_PATTERNS = [
    r"\bprofessional\b",
    r"\bpro team\b",
]

NATIONAL_TEAM_PATTERNS = [
    r"\bnational team\b",
    r"\bteam usa\b",
]


OUTPUT_COLUMNS = [
    "profile_section_id",
    "athlete_id",
    "athlete_name",
    "section_index",
    "source_section_name",
    "normalized_section_name",
    "athlete_gender",
    "career_stage",
    "governing_system",
    "competition_level",
    "representation_type",
    "entity_type",
    "canonical_entity_name",
    "analytical_entity_id",
    "resolved_team_id",
    "resolved_school_id",
    "resolved_school_name",
    "resolved_division",
    "resolution_status",
    "resolution_method",
    "resolution_confidence",
    "automatic_rule",
    "manual_review_required",
    "manual_review_status",
    "manual_review_note",
    "performance_count",
    "meet_count",
    "first_season_year",
    "last_season_year",
    "d1_development_eligible",
    "frontier_eligible",
    "school_stint_eligible",
    "pre_college_baseline_eligible",
    "sensitivity_analysis_eligible",
    "eligibility_status",
    "exclusion_reason",
    "source_attribution_version",
    "classification_version",
]


OVERRIDE_COLUMNS = [
    "athlete_id",
    "section_index",
    "career_stage",
    "governing_system",
    "competition_level",
    "representation_type",
    "entity_type",
    "canonical_entity_name",
    "resolved_team_id",
    "resolution_status",
    "resolution_method",
    "resolution_confidence",
    "d1_development_eligible",
    "frontier_eligible",
    "school_stint_eligible",
    "pre_college_baseline_eligible",
    "sensitivity_analysis_eligible",
    "exclusion_reason",
    "manual_review_status",
    "manual_review_note",
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


def parse_bool(value: object, default: bool = False) -> bool:
    text = clean_text(value).lower()

    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False

    return default


def contains_any(text: str, patterns: list[str]) -> bool:
    lowered = clean_text(text).lower()
    return any(re.search(pattern, lowered) for pattern in patterns)


def stable_id(prefix: str, *parts: object) -> str:
    joined = "|".join(clean_text(part) for part in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def normalize_division(value: object) -> str:
    text = clean_text(value).upper().replace(" ", "")

    if text in {"D1", "DI", "DIVISIONI", "NCAAD1"}:
        return "NCAA_D1"
    if text in {"D2", "DII", "DIVISIONII", "NCAAD2"}:
        return "NCAA_D2"
    if text in {"D3", "DIII", "DIVISIONIII", "NCAAD3"}:
        return "NCAA_D3"

    return ""


def core_team_maps(
    con: duckdb.DuckDBPyConnection,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[tuple[str, str], list[dict[str, Any]]],
]:
    frame = con.execute(
        """
        SELECT
            t.team_id,
            t.school_id,
            s.school_name,
            t.gender_code,
            t.division,
            t.sport
        FROM core.teams t
        LEFT JOIN core.schools s
          ON t.school_id = s.school_id
        """
    ).fetchdf()

    by_team: dict[str, dict[str, Any]] = {}
    by_school_gender: dict[
        tuple[str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)

    for row in frame.to_dict("records"):
        team_id = clean_text(row.get("team_id"))
        school_name = clean_text(row.get("school_name"))
        gender = clean_text(row.get("gender_code"))

        record = {
            "team_id": team_id,
            "school_id": clean_text(row.get("school_id")),
            "school_name": school_name,
            "gender_code": gender,
            "division": clean_text(row.get("division")),
            "sport": clean_text(row.get("sport")),
        }

        by_team[team_id] = record
        by_school_gender[
            (normalize_name(school_name), gender)
        ].append(record)

    return by_team, by_school_gender


def default_classification() -> dict[str, Any]:
    return {
        "career_stage": "UNKNOWN",
        "governing_system": "UNKNOWN",
        "competition_level": "UNKNOWN",
        "representation_type": "UNKNOWN",
        "entity_type": "UNKNOWN_ENTITY",
        "canonical_entity_name": "",
        "resolved_team_id": "",
        "resolved_school_id": "",
        "resolved_school_name": "",
        "resolved_division": "",
        "resolution_status": "UNKNOWN",
        "resolution_method": "UNRESOLVED",
        "resolution_confidence": "UNRESOLVED",
        "automatic_rule": "NO_STRONG_RULE",
        "manual_review_required": True,
        "manual_review_status": "PENDING",
        "manual_review_note": "",
        "d1_development_eligible": False,
        "frontier_eligible": False,
        "school_stint_eligible": False,
        "pre_college_baseline_eligible": False,
        "sensitivity_analysis_eligible": False,
        "eligibility_status": "EXCLUDED_PENDING_REVIEW",
        "exclusion_reason": "UNCLASSIFIED_PROFILE_SECTION",
    }


def classify_exact_core_match(
    source_name: str,
    athlete_gender: str,
    core_by_school_gender: dict[
        tuple[str, str],
        list[dict[str, Any]],
    ],
) -> dict[str, Any] | None:
    candidates = core_by_school_gender.get(
        (normalize_name(source_name), athlete_gender),
        [],
    )

    if len(candidates) != 1:
        return None

    team = candidates[0]
    competition_level = normalize_division(team["division"])

    if competition_level == "NCAA_D1":
        eligible = True
        exclusion_reason = ""
        eligibility_status = "ELIGIBLE_D1"
    elif competition_level:
        eligible = False
        exclusion_reason = "NON_D1_COLLEGE_PERFORMANCE"
        eligibility_status = "EXCLUDED_NON_D1"
    else:
        eligible = False
        exclusion_reason = "OTHER_COLLEGE_PERFORMANCE"
        eligibility_status = "EXCLUDED_NON_D1"

    return {
        "career_stage": "COLLEGIATE",
        "governing_system": (
            "NCAA" if competition_level.startswith("NCAA_")
            else "OTHER"
        ),
        "competition_level": (
            competition_level or "OTHER_COLLEGE"
        ),
        "representation_type": "SCHOOL",
        "entity_type": "CORE_SCHOOL_TEAM",
        "canonical_entity_name": team["school_name"],
        "resolved_team_id": team["team_id"],
        "resolved_school_id": team["school_id"],
        "resolved_school_name": team["school_name"],
        "resolved_division": team["division"],
        "resolution_status": "CORE_TEAM_MATCH",
        "resolution_method": "EXACT_NORMALIZED_SCHOOL_GENDER_MATCH",
        "resolution_confidence": "HIGH",
        "automatic_rule": "EXACT_CORE_SCHOOL_GENDER",
        "manual_review_required": False,
        "manual_review_status": "NOT_REQUIRED",
        "manual_review_note": "",
        "d1_development_eligible": eligible,
        "frontier_eligible": eligible,
        "school_stint_eligible": eligible,
        "pre_college_baseline_eligible": False,
        "sensitivity_analysis_eligible": eligible,
        "eligibility_status": eligibility_status,
        "exclusion_reason": exclusion_reason,
    }


def classify_by_strong_evidence(
    source_name: str,
    evidence_text: str,
    suggested_scope_class: str,
) -> dict[str, Any]:
    combined = f"{source_name} {evidence_text}"
    result = default_classification()

    pre_collegiate = (
        suggested_scope_class == "PRE_COLLEGIATE_LIKELY"
        or contains_any(combined, PRE_COLLEGIATE_PATTERNS)
    )

    if pre_collegiate:
        result.update(
            {
                "career_stage": "PRE_COLLEGIATE",
                "governing_system": "NFHS_OR_HIGH_SCHOOL",
                "competition_level": "HIGH_SCHOOL",
                "representation_type": "SCHOOL",
                "entity_type": "HIGH_SCHOOL",
                "canonical_entity_name": source_name,
                "resolution_status": "NON_CORE_ENTITY_RESOLVED",
                "resolution_method": "STRONG_PRE_COLLEGIATE_EVIDENCE",
                "resolution_confidence": "HIGH",
                "automatic_rule": "PRE_COLLEGIATE_SIGNAL",
                "manual_review_required": False,
                "manual_review_status": "NOT_REQUIRED",
                "d1_development_eligible": False,
                "frontier_eligible": False,
                "school_stint_eligible": False,
                "pre_college_baseline_eligible": True,
                "sensitivity_analysis_eligible": True,
                "eligibility_status": "EXCLUDED_PRE_COLLEGIATE",
                "exclusion_reason": "PRE_COLLEGIATE_PERFORMANCE",
            }
        )
        return result

    if contains_any(combined, UNATTACHED_PATTERNS):
        result.update(
            {
                "career_stage": "UNKNOWN",
                "governing_system": "UNATTACHED",
                "competition_level": "UNATTACHED",
                "representation_type": "UNATTACHED",
                "entity_type": "UNATTACHED",
                "canonical_entity_name": source_name or "Unattached",
                "resolution_status": "NON_CORE_ENTITY_RESOLVED",
                "resolution_method": "EXPLICIT_UNATTACHED_EVIDENCE",
                "resolution_confidence": "HIGH",
                "automatic_rule": "UNATTACHED_SIGNAL",
                "manual_review_required": False,
                "manual_review_status": "NOT_REQUIRED",
                "eligibility_status": "EXCLUDED_UNATTACHED",
                "exclusion_reason": "UNATTACHED_PERFORMANCE",
                "sensitivity_analysis_eligible": True,
            }
        )
        return result

    if contains_any(combined, CLUB_PATTERNS):
        result.update(
            {
                "career_stage": "UNKNOWN",
                "governing_system": "CLUB",
                "competition_level": "CLUB",
                "representation_type": "CLUB",
                "entity_type": "CLUB",
                "canonical_entity_name": source_name,
                "resolution_status": "NON_CORE_ENTITY_RESOLVED",
                "resolution_method": "EXPLICIT_CLUB_EVIDENCE",
                "resolution_confidence": "HIGH",
                "automatic_rule": "CLUB_SIGNAL",
                "manual_review_required": False,
                "manual_review_status": "NOT_REQUIRED",
                "eligibility_status": "EXCLUDED_CLUB",
                "exclusion_reason": "CLUB_PERFORMANCE",
                "sensitivity_analysis_eligible": True,
            }
        )
        return result

    if contains_any(combined, NATIONAL_TEAM_PATTERNS):
        result.update(
            {
                "career_stage": "POST_COLLEGIATE",
                "governing_system": "NATIONAL_TEAM",
                "competition_level": "PROFESSIONAL_OR_NATIONAL",
                "representation_type": "NATIONAL_TEAM",
                "entity_type": "NATIONAL_TEAM",
                "canonical_entity_name": source_name,
                "resolution_status": "NON_CORE_ENTITY_RESOLVED",
                "resolution_method": "EXPLICIT_NATIONAL_TEAM_EVIDENCE",
                "resolution_confidence": "HIGH",
                "automatic_rule": "NATIONAL_TEAM_SIGNAL",
                "manual_review_required": False,
                "manual_review_status": "NOT_REQUIRED",
                "eligibility_status": "EXCLUDED_POST_COLLEGIATE",
                "exclusion_reason": "NATIONAL_TEAM_PERFORMANCE",
                "sensitivity_analysis_eligible": True,
            }
        )
        return result

    if contains_any(combined, PROFESSIONAL_PATTERNS):
        result.update(
            {
                "career_stage": "POST_COLLEGIATE",
                "governing_system": "PROFESSIONAL",
                "competition_level": "PROFESSIONAL_OR_NATIONAL",
                "representation_type": "PROFESSIONAL_TEAM",
                "entity_type": "PROFESSIONAL_TEAM",
                "canonical_entity_name": source_name,
                "resolution_status": "NON_CORE_ENTITY_RESOLVED",
                "resolution_method": "EXPLICIT_PROFESSIONAL_EVIDENCE",
                "resolution_confidence": "HIGH",
                "automatic_rule": "PROFESSIONAL_SIGNAL",
                "manual_review_required": False,
                "manual_review_status": "NOT_REQUIRED",
                "eligibility_status": "EXCLUDED_POST_COLLEGIATE",
                "exclusion_reason": "PROFESSIONAL_PERFORMANCE",
                "sensitivity_analysis_eligible": True,
            }
        )
        return result

    if contains_any(combined, NWAC_PATTERNS):
        governing_system = "NWAC"
        competition_level = "OTHER_COLLEGE"
        rule = "EXPLICIT_NWAC_EVIDENCE"
    elif contains_any(combined, NJCAA_PATTERNS):
        governing_system = "NJCAA"
        competition_level = "NJCAA"
        rule = "EXPLICIT_NJCAA_EVIDENCE"
    elif contains_any(combined, NAIA_PATTERNS):
        governing_system = "NAIA"
        competition_level = "NAIA"
        rule = "EXPLICIT_NAIA_EVIDENCE"
    elif contains_any(combined, NCAA_D2_PATTERNS):
        governing_system = "NCAA"
        competition_level = "NCAA_D2"
        rule = "EXPLICIT_NCAA_D2_EVIDENCE"
    elif contains_any(combined, NCAA_D3_PATTERNS):
        governing_system = "NCAA"
        competition_level = "NCAA_D3"
        rule = "EXPLICIT_NCAA_D3_EVIDENCE"
    else:
        return result

    result.update(
        {
            "career_stage": "COLLEGIATE",
            "governing_system": governing_system,
            "competition_level": competition_level,
            "representation_type": "SCHOOL",
            "entity_type": "NON_CORE_COLLEGE",
            "canonical_entity_name": source_name,
            "resolution_status": "NON_CORE_ENTITY_RESOLVED",
            "resolution_method": rule,
            "resolution_confidence": "HIGH",
            "automatic_rule": rule,
            "manual_review_required": False,
            "manual_review_status": "NOT_REQUIRED",
            "d1_development_eligible": False,
            "frontier_eligible": False,
            "school_stint_eligible": False,
            "pre_college_baseline_eligible": True,
            "sensitivity_analysis_eligible": True,
            "eligibility_status": "EXCLUDED_NON_D1",
            "exclusion_reason": "NON_D1_COLLEGE_PERFORMANCE",
        }
    )

    return result


def apply_override(
    record: dict[str, Any],
    override: dict[str, Any],
    core_by_team: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    updated = dict(record)

    for column in OVERRIDE_COLUMNS:
        if column not in override:
            continue

        value = override[column]
        if clean_text(value) == "":
            continue

        if column in {
            "d1_development_eligible",
            "frontier_eligible",
            "school_stint_eligible",
            "pre_college_baseline_eligible",
            "sensitivity_analysis_eligible",
        }:
            updated[column] = parse_bool(
                value,
                bool(updated.get(column, False)),
            )
        else:
            updated[column] = clean_text(value)

    team_id = clean_text(updated.get("resolved_team_id"))
    if team_id and team_id in core_by_team:
        team = core_by_team[team_id]
        updated["resolved_school_id"] = team["school_id"]
        updated["resolved_school_name"] = team["school_name"]
        updated["resolved_division"] = team["division"]

    updated["manual_review_required"] = False
    updated["manual_review_status"] = (
        clean_text(updated.get("manual_review_status"))
        or "COMPLETED"
    )
    updated["automatic_rule"] = "MANUAL_OVERRIDE"
    updated["resolution_method"] = (
        clean_text(updated.get("resolution_method"))
        or "MANUAL_OVERRIDE"
    )

    # Recalculate analytical eligibility after the override. The override CSV
    # intentionally stores the component flags and exclusion reason rather than
    # requiring users to maintain a redundant eligibility_status field.
    competition_level = clean_text(
        updated.get("competition_level")
    )
    exclusion_reason = clean_text(
        updated.get("exclusion_reason")
    )
    d1_eligible = bool(
        updated.get("d1_development_eligible", False)
    )

    if d1_eligible:
        updated["eligibility_status"] = "ELIGIBLE_D1"
    elif exclusion_reason == "PRE_COLLEGIATE_PERFORMANCE":
        updated["eligibility_status"] = "EXCLUDED_PRE_COLLEGIATE"
    elif exclusion_reason == "NON_D1_COLLEGE_PERFORMANCE":
        updated["eligibility_status"] = "EXCLUDED_NON_D1"
    elif exclusion_reason == "UNATTACHED_PERFORMANCE":
        updated["eligibility_status"] = "EXCLUDED_UNATTACHED"
    elif exclusion_reason == "CLUB_PERFORMANCE":
        updated["eligibility_status"] = "EXCLUDED_CLUB"
    elif exclusion_reason in {
        "PROFESSIONAL_PERFORMANCE",
        "NATIONAL_TEAM_PERFORMANCE",
    }:
        updated["eligibility_status"] = "EXCLUDED_POST_COLLEGIATE"
    elif competition_level == "HIGH_SCHOOL":
        updated["eligibility_status"] = "EXCLUDED_PRE_COLLEGIATE"
    elif competition_level not in {"", "UNKNOWN", "NCAA_D1"}:
        updated["eligibility_status"] = "EXCLUDED_NON_D1"
    else:
        updated["eligibility_status"] = "EXCLUDED_PENDING_REVIEW"

    return updated


def main() -> None:
    for required in [
        DB_PATH,
        SCOPE_AUDIT_PATH,
        SECTION_MAPPING_PATH,
    ]:
        if not required.exists():
            raise FileNotFoundError(
                f"Required input not found: {required}"
            )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    scope = pd.read_csv(
        SCOPE_AUDIT_PATH,
        dtype=str,
        keep_default_na=False,
    )
    sections = pd.read_csv(
        SECTION_MAPPING_PATH,
        dtype=str,
        keep_default_na=False,
    )

    section_context = sections[
        [
            "athlete_id",
            "section_index",
            "athlete_gender",
            "marker_text",
            "section_attribution_method",
            "attribution_version",
        ]
    ].drop_duplicates(
        ["athlete_id", "section_index"]
    )

    merged = scope.merge(
        section_context,
        how="left",
        on=["athlete_id", "section_index"],
        validate="one_to_one",
    )

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        core_by_team, core_by_school_gender = core_team_maps(con)
    finally:
        con.close()

    overrides: dict[tuple[str, str], dict[str, Any]] = {}

    if OVERRIDE_PATH.exists():
        override_frame = pd.read_csv(
            OVERRIDE_PATH,
            dtype=str,
            keep_default_na=False,
        )

        missing_columns = [
            column
            for column in ["athlete_id", "section_index"]
            if column not in override_frame.columns
        ]
        if missing_columns:
            raise ValueError(
                "Override file is missing key columns: "
                + ", ".join(missing_columns)
            )

        for row in override_frame.to_dict("records"):
            key = (
                clean_text(row.get("athlete_id")),
                clean_text(row.get("section_index")),
            )
            overrides[key] = row

    output_rows: list[dict[str, Any]] = []

    for row in merged.to_dict("records"):
        athlete_id = clean_text(row.get("athlete_id"))
        section_index = clean_text(row.get("section_index"))
        source_name = clean_text(
            row.get("section_school_name")
        )
        athlete_gender = clean_text(
            row.get("athlete_gender")
        )

        evidence_text = " ".join(
            [
                source_name,
                clean_text(row.get("sample_meet_names")),
                clean_text(row.get("sample_result_urls")),
                clean_text(row.get("sample_events")),
            ]
        )

        strong_evidence = classify_by_strong_evidence(
            source_name=source_name,
            evidence_text=evidence_text,
            suggested_scope_class=clean_text(
                row.get("suggested_scope_class")
            ),
        )

        non_college_priority_rules = {
            "PRE_COLLEGIATE_SIGNAL",
            "UNATTACHED_SIGNAL",
            "CLUB_SIGNAL",
            "NATIONAL_TEAM_SIGNAL",
            "PROFESSIONAL_SIGNAL",
        }

        if (
            strong_evidence.get("automatic_rule")
            in non_college_priority_rules
        ):
            # High-school, club, unattached, professional, and national-team
            # evidence takes precedence over a coincidental school-name match.
            classification = strong_evidence
        else:
            classification = classify_exact_core_match(
                source_name=source_name,
                athlete_gender=athlete_gender,
                core_by_school_gender=core_by_school_gender,
            )

            if classification is None:
                classification = strong_evidence

        profile_section_id = stable_id(
            "m4sec",
            athlete_id,
            section_index,
            source_name,
        )

        canonical_entity_name = clean_text(
            classification.get("canonical_entity_name")
        )
        entity_type = clean_text(
            classification.get("entity_type")
        )
        governing_system = clean_text(
            classification.get("governing_system")
        )
        competition_level = clean_text(
            classification.get("competition_level")
        )

        analytical_entity_id = stable_id(
            "m4ent",
            normalize_name(canonical_entity_name or source_name),
            entity_type,
            governing_system,
            competition_level,
        )

        record = {
            "profile_section_id": profile_section_id,
            "athlete_id": athlete_id,
            "athlete_name": clean_text(
                row.get("athlete_name")
            ),
            "section_index": section_index,
            "source_section_name": source_name,
            "normalized_section_name": normalize_name(
                source_name
            ),
            "athlete_gender": athlete_gender,
            **classification,
            "analytical_entity_id": analytical_entity_id,
            "performance_count": int(
                float(clean_text(row.get("performance_count")) or 0)
            ),
            "meet_count": int(
                float(clean_text(row.get("meet_count")) or 0)
            ),
            "first_season_year": clean_text(
                row.get("first_season_year")
            ),
            "last_season_year": clean_text(
                row.get("last_season_year")
            ),
            "source_attribution_version": clean_text(
                row.get("attribution_version")
            ),
            "classification_version": CLASSIFICATION_VERSION,
        }

        override = overrides.get(
            (athlete_id, section_index)
        )
        if override:
            record = apply_override(
                record,
                override,
                core_by_team,
            )

            canonical_entity_name = clean_text(
                record.get("canonical_entity_name")
            )
            record["analytical_entity_id"] = stable_id(
                "m4ent",
                normalize_name(
                    canonical_entity_name or source_name
                ),
                clean_text(record.get("entity_type")),
                clean_text(record.get("governing_system")),
                clean_text(record.get("competition_level")),
            )

        output_rows.append(record)

    classification_frame = pd.DataFrame(
        output_rows,
        columns=OUTPUT_COLUMNS,
    )

    classification_frame.to_csv(
        OUTPUT_DIR / "profile_section_classification_v1.csv",
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
        "resolution_method",
        "resolution_confidence",
        "classification_version",
    ]

    entity_registry = (
        classification_frame[entity_columns]
        .drop_duplicates("analytical_entity_id")
        .sort_values(
            [
                "competition_level",
                "canonical_entity_name",
            ]
        )
    )

    entity_registry.to_csv(
        OUTPUT_DIR / "affiliation_entity_registry_v1.csv",
        index=False,
    )

    alias_registry = (
        classification_frame[
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
                "resolution_method",
                "resolution_confidence",
                "classification_version",
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

    alias_registry.insert(
        0,
        "alias_id",
        [
            stable_id(
                "m4alias",
                row["normalized_section_name"],
                row["analytical_entity_id"],
            )
            for row in alias_registry.to_dict("records")
        ],
    )

    alias_registry.to_csv(
        OUTPUT_DIR / "entity_alias_registry_v1.csv",
        index=False,
    )

    manual_queue = classification_frame.loc[
        classification_frame["manual_review_required"]
    ].copy()

    manual_queue = manual_queue.merge(
        merged[
            [
                "athlete_id",
                "section_index",
                "suggested_scope_class",
                "suggestion_reason",
                "best_core_school_match",
                "best_core_similarity",
                "sample_meet_names",
                "sample_result_urls",
                "sample_events",
                "profile_current_school",
                "unique_athletes_school",
            ]
        ],
        how="left",
        on=["athlete_id", "section_index"],
        validate="one_to_one",
    )

    manual_queue.to_csv(
        OUTPUT_DIR / "manual_review_queue.csv",
        index=False,
    )

    template = manual_queue[
        ["athlete_id", "section_index"]
    ].copy()

    for column in OVERRIDE_COLUMNS:
        if column not in template.columns:
            template[column] = ""

    template = template[OVERRIDE_COLUMNS]
    template.to_csv(
        OUTPUT_DIR / "manual_review_overrides_template.csv",
        index=False,
    )

    summary = (
        classification_frame.groupby(
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
            performance_count=("performance_count", "sum"),
        )
        .reset_index()
        .sort_values(
            [
                "manual_review_required",
                "performance_count",
            ],
            ascending=[True, False],
        )
    )

    summary.to_csv(
        OUTPUT_DIR / "classification_summary.csv",
        index=False,
    )

    duplicate_keys = int(
        classification_frame.duplicated(
            ["athlete_id", "section_index"]
        ).sum()
    )
    missing_classification = int(
        (
            classification_frame["competition_level"]
            .fillna("")
            .eq("")
        ).sum()
    )
    high_school_d1_eligible = int(
        (
            (
                classification_frame["competition_level"]
                == "HIGH_SCHOOL"
            )
            & (
                classification_frame[
                    "d1_development_eligible"
                ]
            )
        ).sum()
    )
    non_d1_stint_eligible = int(
        (
            (
                classification_frame["competition_level"]
                != "NCAA_D1"
            )
            & (
                classification_frame["school_stint_eligible"]
            )
        ).sum()
    )
    completed_review_pending_status = int(
        (
            (~classification_frame["manual_review_required"])
            & (
                classification_frame["eligibility_status"]
                == "EXCLUDED_PENDING_REVIEW"
            )
        ).sum()
    )

    hard_checks = pd.DataFrame(
        [
            {
                "check_name": "input_output_section_count_match",
                "failed_row_count": (
                    0
                    if len(classification_frame) == len(merged)
                    else abs(
                        len(classification_frame) - len(merged)
                    )
                ),
                "observed_value": len(classification_frame),
                "expected_value": len(merged),
            },
            {
                "check_name": "duplicate_section_keys",
                "failed_row_count": duplicate_keys,
                "observed_value": duplicate_keys,
                "expected_value": 0,
            },
            {
                "check_name": "missing_competition_classification",
                "failed_row_count": missing_classification,
                "observed_value": missing_classification,
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
                "check_name": "completed_review_with_pending_eligibility",
                "failed_row_count": completed_review_pending_status,
                "observed_value": completed_review_pending_status,
                "expected_value": 0,
            },
            {
                "check_name": "manual_review_queue",
                "failed_row_count": len(manual_queue),
                "observed_value": len(manual_queue),
                "expected_value": 0,
            },
        ]
    )

    hard_checks.to_csv(
        OUTPUT_DIR / "classification_hard_checks.csv",
        index=False,
    )

    auto_resolved = int(
        (~classification_frame["manual_review_required"]).sum()
    )
    manual_count = len(manual_queue)
    auto_performances = int(
        classification_frame.loc[
            ~classification_frame["manual_review_required"],
            "performance_count",
        ].sum()
    )
    manual_performances = int(
        manual_queue["performance_count"].sum()
    )

    report = f"""MILESTONE 4 PROFILE-SECTION CLASSIFICATION REGISTRY
============================================================
Classification version: {CLASSIFICATION_VERSION}
Database connection: read-only
Raw files modified: no
Prior attribution outputs modified: no

COUNTS
- Input profile sections: {len(merged):,}
- Automatically resolved sections: {auto_resolved:,}
- Sections requiring manual review: {manual_count:,}
- Performances in automatically resolved sections: {auto_performances:,}
- Performances in manual-review sections: {manual_performances:,}
- Unique analytical entities: {len(entity_registry):,}
- Unique aliases: {len(alias_registry):,}

OUTPUTS
- profile_section_classification_v1.csv
- affiliation_entity_registry_v1.csv
- entity_alias_registry_v1.csv
- manual_review_queue.csv
- manual_review_overrides_template.csv
- classification_summary.csv
- classification_hard_checks.csv

NEXT STEP
{(
    "Classification registry is complete. The manual-review queue is empty."
    if manual_count == 0
    else
    "Review manual_review_queue.csv, copy deterministic decisions into "
    "config/milestone4/profile_section_classification_overrides.csv, "
    "and rerun this script."
)}
"""

    (OUTPUT_DIR / "classification_report.txt").write_text(
        report,
        encoding="utf-8",
    )

    print("Profile-section classification registry complete.")
    print(f"Outputs: {OUTPUT_DIR}")
    print(
        f"Sections: {len(classification_frame):,}; "
        f"auto-resolved: {auto_resolved:,}; "
        f"manual review: {manual_count:,}."
    )
    print("Database connection was read-only.")


if __name__ == "__main__":
    main()
