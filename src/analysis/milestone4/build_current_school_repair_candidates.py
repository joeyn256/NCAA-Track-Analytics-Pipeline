#!/usr/bin/env python3
"""
Build read-only current-school repair candidates for the 27 unresolved
Milestone 4 athlete profiles.

This script DOES NOT modify the staging database or raw HTML.

It reads:
- all_profile_staging.duckdb
- unresolved_current_school_profiles.csv
- saved athlete HTML

It writes:
data/processed/milestone4/current_school_repair/
    current_school_repair_candidates.csv
    current_school_repair_report.txt
    current_school_repair_checks.csv

Method:
1. Find the athlete-name line in the visible profile header.
2. Skip class/status labels such as "(SR-4)", "(RS/Una)", and "ALL".
3. Select the next plausible institution line before the profile-statistics
   and meet-results sections.
4. If no header institution is present and the athlete has exactly one
   affiliation school, use that as a documented fallback candidate.

No candidate is applied automatically.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd
from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parents[3]

STAGING_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/all_profile_staging"
    / "all_profile_staging.duckdb"
)
AUDIT_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/all_profile_audit"
    / "unresolved_current_school_profiles.csv"
)
HTML_DIR = PROJECT_ROOT / "data/raw/athlete_pages"
OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/current_school_repair"
)

REPAIR_VERSION = "m4_current_school_repair_v1.1"

NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
CLASS_RE = re.compile(
    r"^\((?:FR|SO|JR|SR|RS|UNA|RS/UNA|GR|GS)"
    r"(?:[-/][A-Z0-9]+)?\)$",
    re.IGNORECASE,
)
TIME_OR_MARK_RE = re.compile(
    r"^(?:\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?)$"
)

SKIP_EXACT = {
    "/",
    "ALL",
    "TEAMS",
    "CONFERENCES",
    "RESULTS",
    "LISTS",
    "INDOOR LISTS",
    "OUTDOOR LISTS",
    "ARCHIVES",
    "CONVERSIONS",
    "COLLEGE BESTS",
    "MEET RESULTS",
    "EVENT HISTORY",
    "SEASON HISTORY",
    "PROGRESSION",
    "INDOOR TRACK & FIELD",
    "OUTDOOR TRACK & FIELD",
    "CROSS COUNTRY",
    "HIGH SCHOOL:",
}

STOP_EXACT = {
    "COLLEGE BESTS",
    "MEET RESULTS",
    "EVENT HISTORY",
    "SEASON HISTORY",
    "PROGRESSION",
}


def clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split()).strip()


def normalize(value: object) -> str:
    return NON_ALNUM_RE.sub("", clean(value).lower())


def athlete_name_variants(value: object) -> set[str]:
    """
    Return normalized profile-name variants.

    Core athlete names are usually stored as "Last, First", while the
    TFRRS profile header is usually rendered as "First Last".
    """
    raw = clean(value)
    variants = {normalize(raw)}

    if "," in raw:
        last, first = raw.split(",", 1)
        last = clean(last)
        first = clean(first)

        if first and last:
            variants.add(normalize(f"{first} {last}"))

    return {variant for variant in variants if variant}


def split_affiliation_schools(value: object) -> list[str]:
    schools = [
        clean(item)
        for item in clean(value).split("|")
        if clean(item)
    ]
    return list(dict.fromkeys(schools))


def is_skip_line(line: str) -> bool:
    upper = line.upper()

    if upper in SKIP_EXACT:
        return True
    if CLASS_RE.fullmatch(line):
        return True
    if TIME_OR_MARK_RE.fullmatch(line):
        return True
    if line.startswith("* High School:"):
        return True
    if line.startswith("* previously at"):
        return True
    if line.startswith("TFRRS |"):
        return True
    if line.startswith("http://") or line.startswith("https://"):
        return True

    return False


def extract_header_candidate(
    html_path: Path,
    athlete_name: str,
) -> dict[str, object]:
    html = html_path.read_text(
        encoding="utf-8",
        errors="ignore",
    )
    soup = BeautifulSoup(html, "html.parser")

    lines = [
        clean(line)
        for line in soup.get_text("\n", strip=True).splitlines()
        if clean(line)
    ]

    athlete_variants = athlete_name_variants(
        athlete_name
    )
    name_indices = [
        index
        for index, line in enumerate(lines)
        if normalize(line) in athlete_variants
    ]

    if not name_indices:
        return {
            "header_school_candidate": "",
            "candidate_method": "ATHLETE_NAME_LINE_NOT_FOUND",
            "candidate_confidence": "UNRESOLVED",
            "athlete_name_line_index": None,
            "candidate_line_index": None,
            "candidate_distance_from_name": None,
            "header_evidence_window": " | ".join(lines[:80]),
        }

    name_index = name_indices[0]
    candidate = ""
    candidate_index = None

    evidence_end = min(len(lines), name_index + 20)
    evidence = lines[name_index:evidence_end]

    for index in range(name_index + 1, evidence_end):
        line = lines[index]
        upper = line.upper()

        if upper in STOP_EXACT:
            break

        if is_skip_line(line):
            continue

        # Event labels and obvious page controls are not institutions.
        if re.fullmatch(
            r"\d{2,4}(?:M|K)?",
            upper,
        ):
            continue
        if len(line) > 100:
            continue

        candidate = line
        candidate_index = index
        break

    if candidate:
        distance = candidate_index - name_index
        confidence = (
            "HIGH"
            if distance <= 3
            else "MEDIUM"
        )
        method = "PROFILE_HEADER_POSITIONAL_RULE"
    else:
        distance = None
        confidence = "UNRESOLVED"
        method = "NO_HEADER_INSTITUTION_CANDIDATE"

    return {
        "header_school_candidate": candidate,
        "candidate_method": method,
        "candidate_confidence": confidence,
        "athlete_name_line_index": name_index,
        "candidate_line_index": candidate_index,
        "candidate_distance_from_name": distance,
        "header_evidence_window": " | ".join(evidence),
    }


def main() -> None:
    for path in [STAGING_DB, AUDIT_CSV, HTML_DIR]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    unresolved = pd.read_csv(
        AUDIT_CSV,
        dtype=str,
        keep_default_na=False,
    )
    unresolved["athlete_id"] = pd.to_numeric(
        unresolved["athlete_id"],
        errors="raise",
    ).astype("int64")

    rows: list[dict[str, object]] = []

    for source in unresolved.to_dict("records"):
        athlete_id = int(source["athlete_id"])
        athlete_name = clean(source["athlete_name"])
        html_path = HTML_DIR / f"{athlete_id}.html"

        extracted = extract_header_candidate(
            html_path=html_path,
            athlete_name=athlete_name,
        )

        affiliation_schools = split_affiliation_schools(
            source.get("affiliation_schools")
        )

        candidate = clean(
            extracted["header_school_candidate"]
        )
        method = clean(
            extracted["candidate_method"]
        )
        confidence = clean(
            extracted["candidate_confidence"]
        )
        fallback_used = False

        if not candidate and len(affiliation_schools) == 1:
            candidate = affiliation_schools[0]
            method = "SOLE_CORE_AFFILIATION_FALLBACK"
            confidence = "MEDIUM"
            fallback_used = True

        matches_core_affiliation = (
            normalize(candidate)
            in {
                normalize(school)
                for school in affiliation_schools
            }
            if candidate
            else False
        )

        rows.append(
            {
                "athlete_id": athlete_id,
                "athlete_name": athlete_name,
                "performance_count": int(
                    float(
                        clean(
                            source.get("performance_count")
                        )
                        or 0
                    )
                ),
                "section_count": int(
                    float(
                        clean(source.get("section_count"))
                        or 0
                    )
                ),
                "url_key_count": int(
                    float(
                        clean(source.get("url_key_count"))
                        or 0
                    )
                ),
                "core_affiliation_schools": (
                    " | ".join(affiliation_schools)
                ),
                "proposed_current_school": candidate,
                "proposed_normalized_school": normalize(
                    candidate
                ),
                "candidate_method": method,
                "candidate_confidence": confidence,
                "fallback_used": fallback_used,
                "matches_core_affiliation": (
                    matches_core_affiliation
                ),
                "header_differs_from_core": (
                    bool(candidate)
                    and not matches_core_affiliation
                ),
                "athlete_name_line_index": extracted[
                    "athlete_name_line_index"
                ],
                "candidate_line_index": extracted[
                    "candidate_line_index"
                ],
                "candidate_distance_from_name": extracted[
                    "candidate_distance_from_name"
                ],
                "header_evidence_window": extracted[
                    "header_evidence_window"
                ],
                "repair_version": REPAIR_VERSION,
                "manual_review_status": "PENDING",
                "manual_review_note": "",
            }
        )

    candidates = pd.DataFrame(rows).sort_values(
        ["candidate_confidence", "athlete_id"]
    )

    candidates.to_csv(
        OUTPUT_DIR / "current_school_repair_candidates.csv",
        index=False,
    )

    missing_candidates = int(
        candidates["proposed_current_school"]
        .fillna("")
        .eq("")
        .sum()
    )
    high_confidence = int(
        (
            candidates["candidate_confidence"]
            == "HIGH"
        ).sum()
    )
    medium_confidence = int(
        (
            candidates["candidate_confidence"]
            == "MEDIUM"
        ).sum()
    )
    fallback_count = int(
        candidates["fallback_used"].sum()
    )
    differing_from_core = int(
        (
            ~candidates["matches_core_affiliation"]
            & candidates["proposed_current_school"]
            .fillna("")
            .ne("")
        ).sum()
    )

    checks = pd.DataFrame(
        [
            {
                "check_name": "input_candidate_row_count",
                "failed_row_count": (
                    0 if len(candidates) == 27
                    else abs(len(candidates) - 27)
                ),
                "observed_value": len(candidates),
                "expected_value": 27,
            },
            {
                "check_name": "missing_school_candidate",
                "failed_row_count": missing_candidates,
                "observed_value": missing_candidates,
                "expected_value": 0,
            },
            {
                "check_name": "duplicate_athlete_ids",
                "failed_row_count": int(
                    candidates.duplicated(
                        ["athlete_id"]
                    ).sum()
                ),
                "observed_value": int(
                    candidates.duplicated(
                        ["athlete_id"]
                    ).sum()
                ),
                "expected_value": 0,
            },
            {
                "check_name": "all_rows_used_affiliation_fallback",
                "failed_row_count": (
                    len(candidates)
                    if fallback_count == len(candidates)
                    else 0
                ),
                "observed_value": fallback_count,
                "expected_value": (
                    f"less than {len(candidates)}"
                ),
            },
        ]
    )

    checks.to_csv(
        OUTPUT_DIR / "current_school_repair_checks.csv",
        index=False,
    )

    report = f"""MILESTONE 4 CURRENT-SCHOOL REPAIR CANDIDATES
============================================================
Repair version: {REPAIR_VERSION}
Staging database modified: no
Raw HTML modified: no

COUNTS
- Input unresolved profiles: {len(unresolved):,}
- Candidate rows: {len(candidates):,}
- High-confidence header candidates: {high_confidence:,}
- Medium-confidence candidates: {medium_confidence:,}
- Sole-affiliation fallbacks: {fallback_count:,}
- Candidates differing from core affiliation: {differing_from_core:,}
- Missing candidates: {missing_candidates:,}

NEXT GATE
Review current_school_repair_candidates.csv. No staging rows should be
updated until every candidate is accepted or explicitly overridden.
"""

    (
        OUTPUT_DIR / "current_school_repair_report.txt"
    ).write_text(report, encoding="utf-8")

    print("Current-school repair candidate audit complete.")
    print(f"Outputs: {OUTPUT_DIR}")
    print(
        f"Candidates: {len(candidates):,}; "
        f"missing: {missing_candidates:,}; "
        f"fallbacks: {fallback_count:,}."
    )


if __name__ == "__main__":
    main()
