#!/usr/bin/env python3
"""
Milestone 5 Phase 4C — Anchor Exceedance Audit

Purpose
-------
Classify every performance that appears better than its collegiate-
eligibility anchor before the performance-level exponent is frozen.

This phase is intentionally conservative:

- no unverified performance silently replaces an anchor;
- no unresolved exceedance enters primary development scoring;
- tiny floating-point/rounding overages may remain eligible at a score of 100;
- obvious event/mark mismatches are quarantined without deleting raw data;
- wind-sensitive exceedances require legality evidence;
- plausible new records require authoritative verification and an anchor refresh.

The script reads the complete Phase 4B exceedance exports. Phase 4B retained
up to 25 rows per event, and this script verifies that no event has more than
25 exceedances before treating the sample export as complete.
"""

from __future__ import annotations

import csv
import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path.cwd()

PHASE_4B_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4b_performance_level_calibration"
)

EXCEEDANCE_SAMPLES = PHASE_4B_DIR / "anchor_exceedance_samples.csv"
EXCEEDANCE_SUMMARY = PHASE_4B_DIR / "anchor_exceedance_summary.csv"

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4c_anchor_exceedance_audit"
)

AUDIT_VERSION = "anchor_exceedance_audit_v1_1"

EXPECTED_EXCEEDANCE_ROWS = 51
EXPECTED_EVENT_COMBINATIONS = 15
EXPECTED_MAX_RATIO = 1.2399011288558976
PHASE_4B_SAMPLE_LIMIT_PER_EVENT = 25

# A ratio no more than 0.05% above the anchor can plausibly be caused by
# source precision, unit rounding, or floating-point representation.
ROUNDING_TOLERANCE_RATIO = 1.0005

# A performance at least 5% beyond an established collegiate anchor is
# provisionally treated as a likely event, distance, unit, or parsing issue.
# It remains preserved in raw data but is quarantined from primary scoring.
AUTOMATIC_ANOMALY_RATIO = 1.05

# These events require legal wind evidence when an outdoor mark exceeds the
# anchor. Indoor marks do not receive an outdoor wind classification.
WIND_SENSITIVE_OUTDOOR_EVENTS = {
    "100M",
    "200M",
    "100H",
    "110H",
    "LJ",
    "TJ",
}

TIME_EVENTS = {
    "60M",
    "100M",
    "200M",
    "300M",
    "400M",
    "500M",
    "600M",
    "800M",
    "1000M",
    "1500M",
    "MILE",
    "3000M",
    "5000M",
    "10000M",
    "60H",
    "100H",
    "110H",
    "400H",
    "3000SC",
}

FIELD_EVENTS = {
    "HJ",
    "PV",
    "LJ",
    "TJ",
    "SP",
    "DT",
    "HT",
    "WT",
    "JT",
}

COMBINED_EVENTS = {"PENT", "HEP", "DEC"}

EXPLICIT_WIND_AIDED_PATTERNS = [
    re.compile(r"wind[\s_-]*aided", re.IGNORECASE),
    re.compile(r"\bwindy\b", re.IGNORECASE),
    re.compile(r"\bwa\b", re.IGNORECASE),
    re.compile(r"(?<=\d)w\b", re.IGNORECASE),
]

UNKNOWN_WIND_PATTERNS = [
    re.compile(r"\bnwi\b", re.IGNORECASE),
    re.compile(r"no[\s_-]*wind", re.IGNORECASE),
    re.compile(r"wind[\s_-]*unknown", re.IGNORECASE),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(
    path: Path,
    rows: Iterable[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def add_check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    observed: Any,
    expected: Any,
    details: str = "",
) -> None:
    checks.append(
        {
            "check_name": name,
            "status": "PASS" if passed else "FAIL",
            "observed": observed,
            "expected": expected,
            "details": details,
        }
    )


def as_float(row: dict[str, str], field: str) -> float:
    value = float(row[field])
    if not math.isfinite(value):
        raise ValueError(f"{field} is not finite: {row[field]}")
    return value


def as_int(row: dict[str, str], field: str) -> int:
    return int(float(row[field]))


def event_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        row["season_type"],
        row["canonical_gender_code"],
        row["canonical_event_code"],
    )


def event_family(event_code: str) -> str:
    if event_code in TIME_EVENTS:
        return "time"
    if event_code in FIELD_EVENTS:
        return "field"
    if event_code in COMBINED_EVENTS:
        return "combined"
    return "other"


def wind_evidence(raw_mark: str) -> str:
    text = raw_mark or ""

    if any(pattern.search(text) for pattern in EXPLICIT_WIND_AIDED_PATTERNS):
        return "possible_wind_aided_indicator"

    if any(pattern.search(text) for pattern in UNKNOWN_WIND_PATTERNS):
        return "wind_status_explicitly_unknown"

    return "no_wind_evidence_in_export"


def normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def logical_result_fingerprint(row: dict[str, str]) -> tuple[str, ...]:
    return (
        row["season_type"],
        row["canonical_gender_code"],
        row["canonical_event_code"],
        normalize_text(row.get("canonical_person_id", "")),
        normalize_text(row.get("athlete_name", "")),
        row.get("performance_value", "").strip(),
        row.get("performance_date", "").strip(),
        normalize_text(row.get("meet_name", "")),
        normalize_text(row.get("resolved_school_id", "")),
    )


PERFORMANCE_ID_CANDIDATES = [
    "canonical_person_performance_id",
    "canonical_performance_id",
    "performance_id",
    "source_performance_id",
]


def source_performance_id(row: dict[str, str]) -> str:
    for field in PERFORMANCE_ID_CANDIDATES:
        value = (row.get(field) or "").strip()
        if value:
            return value
    return ""


def stable_audit_exceedance_id(row: dict[str, str]) -> str:
    """
    Create a deterministic row identifier when the Phase 4B export does not
    contain a source performance ID.

    event_rank is intentionally included because Phase 4B establishes a
    deterministic within-event ordering for the exceedance export.
    """
    components = [
        row.get("season_type", ""),
        row.get("canonical_gender_code", ""),
        row.get("canonical_event_code", ""),
        row.get("event_rank", ""),
        row.get("canonical_person_id", ""),
        row.get("athlete_name", ""),
        row.get("performance_value", ""),
        row.get("raw_mark", ""),
        row.get("performance_date", ""),
        row.get("meet_name", ""),
        row.get("resolved_school_id", ""),
        row.get("school_stint_id", ""),
        row.get("season_id", ""),
    ]
    payload = "|".join(normalize_text(value) for value in components)
    return "exc_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def classify_row(
    row: dict[str, str],
    duplicate_group_size: int,
) -> dict[str, str]:
    ratio = as_float(row, "raw_performance_ratio")
    gap_pct = (ratio - 1.0) * 100.0

    season_type = row["season_type"]
    event_code = row["canonical_event_code"]
    family = event_family(event_code)

    is_wind_sensitive = (
        season_type == "outdoor"
        and event_code in WIND_SENSITIVE_OUTDOOR_EVENTS
    )

    raw_wind_evidence = wind_evidence(row.get("raw_mark", ""))

    if ratio <= ROUNDING_TOLERANCE_RATIO:
        severity = "low"
        classification = "rounding_or_precision_tolerance"
        scoring_action = "eligible_capped_at_100"
        anchor_action = "no_anchor_change"
        review_priority = "optional"
        evidence_needed = (
            "Confirm source precision only if this row becomes influential."
        )

    elif ratio >= AUTOMATIC_ANOMALY_RATIO:
        severity = "critical"

        if family == "time":
            classification = (
                "probable_event_distance_unit_or_time_misclassification"
            )
        elif family == "field":
            classification = (
                "probable_event_unit_or_mark_misclassification"
            )
        else:
            classification = "probable_event_or_mark_misclassification"

        scoring_action = "quarantine_from_primary_scoring"
        anchor_action = "do_not_update_anchor"
        review_priority = "immediate"
        evidence_needed = (
            "Inspect source event label, raw mark, meet result, units, "
            "and event-distance mapping."
        )

    elif is_wind_sensitive:
        severity = "high"

        if raw_wind_evidence == "possible_wind_aided_indicator":
            classification = "probable_nonlegal_or_noncomparable_wind_mark"
        else:
            classification = "wind_legality_unverified"

        scoring_action = "quarantine_from_primary_scoring"
        anchor_action = (
            "verify_legality_before_any_anchor_refresh"
        )
        review_priority = "high"
        evidence_needed = (
            "Authoritative result with wind reading and legal-status evidence."
        )

    elif ratio >= 1.03:
        severity = "high"
        classification = "major_anchor_exceedance_requires_source_review"
        scoring_action = "quarantine_from_primary_scoring"
        anchor_action = (
            "verify_event_and_authoritative_record_before_refresh"
        )
        review_priority = "high"
        evidence_needed = (
            "Official result, event identity, conditions, and eligibility."
        )

    elif ratio >= 1.015:
        severity = "medium_high"
        classification = "material_anchor_exceedance_requires_source_review"
        scoring_action = "quarantine_from_primary_scoring"
        anchor_action = (
            "verify_authoritative_record_before_refresh"
        )
        review_priority = "medium_high"
        evidence_needed = (
            "Official result and confirmation that the mark is comparable "
            "to the anchor definition."
        )

    else:
        severity = "medium"
        classification = "plausible_record_or_anchor_scope_difference"
        scoring_action = "quarantine_from_primary_scoring"
        anchor_action = (
            "verify_authoritative_record_before_refresh"
        )
        review_priority = "medium"
        evidence_needed = (
            "Authoritative record source; check pending status, timing "
            "precision, eligibility, and event conditions."
        )

    if duplicate_group_size > 1:
        duplicate_status = "logical_duplicate_group"
    else:
        duplicate_status = "unique_logical_result"

    return {
        "ratio_gap_pct": f"{gap_pct:.9f}",
        "event_family": family,
        "wind_sensitive_event": str(is_wind_sensitive),
        "wind_evidence": raw_wind_evidence,
        "duplicate_group_size": str(duplicate_group_size),
        "duplicate_status": duplicate_status,
        "severity": severity,
        "provisional_classification": classification,
        "scoring_action": scoring_action,
        "anchor_action": anchor_action,
        "review_priority": review_priority,
        "evidence_needed": evidence_needed,
    }


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 4C — ANCHOR EXCEEDANCE AUDIT")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Audit version: {AUDIT_VERSION}")
    print(f"Samples: {EXCEEDANCE_SAMPLES}")
    print(f"Summary: {EXCEEDANCE_SUMMARY}")
    print(f"Output: {OUTPUT_DIR}")

    add_check(
        checks,
        "exceedance_samples_exist",
        EXCEEDANCE_SAMPLES.exists(),
        EXCEEDANCE_SAMPLES.exists(),
        True,
    )
    add_check(
        checks,
        "exceedance_summary_exists",
        EXCEEDANCE_SUMMARY.exists(),
        EXCEEDANCE_SUMMARY.exists(),
        True,
    )

    if not EXCEEDANCE_SAMPLES.exists() or not EXCEEDANCE_SUMMARY.exists():
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Phase 4B outputs are missing.")
        return 1

    sample_hash_before = sha256_file(EXCEEDANCE_SAMPLES)
    summary_hash_before = sha256_file(EXCEEDANCE_SUMMARY)

    samples = read_csv(EXCEEDANCE_SAMPLES)
    summary_all = read_csv(EXCEEDANCE_SUMMARY)
    summary = [
        row
        for row in summary_all
        if as_int(row, "anchor_exceedance_count") > 0
    ]

    required_sample_fields = {
        "season_type",
        "canonical_gender_code",
        "canonical_event_code",
        "canonical_event_name",
        "event_rank",
        "raw_performance_ratio",
        "anchor_value",
        "performance_value",
        "raw_mark",
        "canonical_person_id",
        "athlete_name",
        "resolved_school_id",
        "school_stint_id",
        "season_year",
        "season_id",
        "performance_date",
        "meet_name",
        "anchor_holder",
        "anchor_school",
    }

    sample_fields = set(samples[0].keys()) if samples else set()
    missing_sample_fields = sorted(
        required_sample_fields - sample_fields
    )

    add_check(
        checks,
        "required_sample_fields_present",
        not missing_sample_fields,
        ",".join(missing_sample_fields),
        "none missing",
    )

    if missing_sample_fields:
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print(
            "PHASE GATE: FAIL — Missing fields: "
            + ", ".join(missing_sample_fields)
        )
        return 1

    summary_count_total = sum(
        as_int(row, "anchor_exceedance_count")
        for row in summary
    )
    summary_max_event_count = max(
        (
            as_int(row, "anchor_exceedance_count")
            for row in summary
        ),
        default=0,
    )

    summary_by_key = {
        event_key(row): row
        for row in summary
    }

    sample_counts = Counter(event_key(row) for row in samples)

    add_check(
        checks,
        "phase_4b_sample_export_complete",
        summary_max_event_count
        <= PHASE_4B_SAMPLE_LIMIT_PER_EVENT,
        summary_max_event_count,
        f"at most {PHASE_4B_SAMPLE_LIMIT_PER_EVENT}",
        (
            "Phase 4B exported up to 25 exceedances per event. "
            "This check proves the sample file contains every exceedance."
        ),
    )
    add_check(
        checks,
        "summary_exceedance_row_count",
        summary_count_total == EXPECTED_EXCEEDANCE_ROWS,
        summary_count_total,
        EXPECTED_EXCEEDANCE_ROWS,
    )
    add_check(
        checks,
        "sample_exceedance_row_count",
        len(samples) == EXPECTED_EXCEEDANCE_ROWS,
        len(samples),
        EXPECTED_EXCEEDANCE_ROWS,
    )
    add_check(
        checks,
        "event_combination_count",
        len(summary) == EXPECTED_EVENT_COMBINATIONS,
        len(summary),
        EXPECTED_EVENT_COMBINATIONS,
    )
    add_check(
        checks,
        "sample_counts_match_summary",
        all(
            sample_counts[key]
            == as_int(row, "anchor_exceedance_count")
            for key, row in summary_by_key.items()
        )
        and set(sample_counts) == set(summary_by_key),
        {
            "|".join(key): sample_counts[key]
            for key in sorted(sample_counts)
        },
        {
            "|".join(key): as_int(summary_by_key[key], "anchor_exceedance_count")
            for key in sorted(summary_by_key)
        },
    )

    observed_max_ratio = max(
        (as_float(row, "raw_performance_ratio") for row in samples),
        default=0.0,
    )
    add_check(
        checks,
        "maximum_ratio_reproduced",
        abs(observed_max_ratio - EXPECTED_MAX_RATIO) <= 1e-12,
        observed_max_ratio,
        EXPECTED_MAX_RATIO,
    )
    add_check(
        checks,
        "every_row_exceeds_anchor",
        all(
            as_float(row, "raw_performance_ratio")
            > 1.000000001
            for row in samples
        ),
        sum(
            as_float(row, "raw_performance_ratio")
            <= 1.000000001
            for row in samples
        ),
        0,
    )

    fingerprints = [
        logical_result_fingerprint(row)
        for row in samples
    ]
    fingerprint_counts = Counter(fingerprints)

    audit_rows: list[dict[str, Any]] = []

    for row, fingerprint in zip(samples, fingerprints):
        classification = classify_row(
            row,
            fingerprint_counts[fingerprint],
        )

        audit_rows.append(
            {
                **row,
                "audit_exceedance_id": stable_audit_exceedance_id(row),
                "source_performance_id": source_performance_id(row),
                "audit_version": AUDIT_VERSION,
                **classification,
            }
        )

    audit_rows.sort(
        key=lambda row: (
            {
                "immediate": 0,
                "high": 1,
                "medium_high": 2,
                "medium": 3,
                "optional": 4,
            }.get(row["review_priority"], 9),
            -float(row["raw_performance_ratio"]),
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
            int(row["event_rank"]),
        )
    )

    audit_fields = list(samples[0].keys()) + [
        "audit_exceedance_id",
        "source_performance_id",
        "audit_version",
        "ratio_gap_pct",
        "event_family",
        "wind_sensitive_event",
        "wind_evidence",
        "duplicate_group_size",
        "duplicate_status",
        "severity",
        "provisional_classification",
        "scoring_action",
        "anchor_action",
        "review_priority",
        "evidence_needed",
    ]

    write_csv(
        OUTPUT_DIR / "anchor_exceedance_audit.csv",
        audit_rows,
        audit_fields,
    )

    quarantine_rows = [
        row
        for row in audit_rows
        if row["scoring_action"]
        == "quarantine_from_primary_scoring"
    ]
    tolerance_rows = [
        row
        for row in audit_rows
        if row["scoring_action"]
        == "eligible_capped_at_100"
    ]
    critical_rows = [
        row
        for row in audit_rows
        if row["severity"] == "critical"
    ]
    wind_review_rows = [
        row
        for row in audit_rows
        if row["wind_sensitive_event"] == "True"
        and row["scoring_action"]
        == "quarantine_from_primary_scoring"
    ]

    write_csv(
        OUTPUT_DIR / "quarantined_exceedances.csv",
        quarantine_rows,
        audit_fields,
    )
    write_csv(
        OUTPUT_DIR / "rounding_tolerance_exceedances.csv",
        tolerance_rows,
        audit_fields,
    )
    write_csv(
        OUTPUT_DIR / "critical_anomalies.csv",
        critical_rows,
        audit_fields,
    )
    write_csv(
        OUTPUT_DIR / "wind_legality_review.csv",
        wind_review_rows,
        audit_fields,
    )

    duplicate_groups: list[dict[str, Any]] = []
    group_members: defaultdict[tuple[str, ...], list[dict[str, Any]]]
    group_members = defaultdict(list)

    for row, fingerprint in zip(samples, fingerprints):
        group_members[fingerprint].append(row)

    duplicate_group_number = 0
    for fingerprint, members in sorted(
        group_members.items(),
        key=lambda item: (-len(item[1]), item[0]),
    ):
        if len(members) <= 1:
            continue

        duplicate_group_number += 1
        duplicate_groups.append(
            {
                "duplicate_group_id": (
                    f"duplicate_group_{duplicate_group_number:04d}"
                ),
                "group_size": len(members),
                "season_type": fingerprint[0],
                "canonical_gender_code": fingerprint[1],
                "canonical_event_code": fingerprint[2],
                "canonical_person_id": fingerprint[3],
                "athlete_name": fingerprint[4],
                "performance_value": fingerprint[5],
                "performance_date": fingerprint[6],
                "meet_name": fingerprint[7],
                "resolved_school_id": fingerprint[8],
                "performance_ids": "|".join(
                    sorted(
                        source_performance_id(row)
                        or stable_audit_exceedance_id(row)
                        for row in members
                    )
                ),
            }
        )

    write_csv(
        OUTPUT_DIR / "logical_duplicate_groups.csv",
        duplicate_groups,
        [
            "duplicate_group_id",
            "group_size",
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "canonical_person_id",
            "athlete_name",
            "performance_value",
            "performance_date",
            "meet_name",
            "resolved_school_id",
            "performance_ids",
        ],
    )

    classification_counts = Counter(
        row["provisional_classification"]
        for row in audit_rows
    )
    action_counts = Counter(
        row["scoring_action"]
        for row in audit_rows
    )

    event_audit_summary: list[dict[str, Any]] = []

    for key in sorted(summary_by_key):
        rows = [
            row
            for row in audit_rows
            if event_key(row) == key
        ]

        event_audit_summary.append(
            {
                "season_type": key[0],
                "canonical_gender_code": key[1],
                "canonical_event_code": key[2],
                "canonical_event_name": rows[0][
                    "canonical_event_name"
                ],
                "exceedance_count": len(rows),
                "max_raw_ratio": max(
                    float(row["raw_performance_ratio"])
                    for row in rows
                ),
                "max_gap_pct": max(
                    float(row["ratio_gap_pct"])
                    for row in rows
                ),
                "critical_count": sum(
                    row["severity"] == "critical"
                    for row in rows
                ),
                "wind_review_count": sum(
                    row["wind_sensitive_event"] == "True"
                    and row["scoring_action"]
                    == "quarantine_from_primary_scoring"
                    for row in rows
                ),
                "quarantine_count": sum(
                    row["scoring_action"]
                    == "quarantine_from_primary_scoring"
                    for row in rows
                ),
                "rounding_tolerance_count": sum(
                    row["scoring_action"]
                    == "eligible_capped_at_100"
                    for row in rows
                ),
                "logical_result_count": len(
                    {
                        logical_result_fingerprint(row)
                        for row in rows
                    }
                ),
                "primary_review_priority": rows[0][
                    "review_priority"
                ],
            }
        )

    event_audit_summary.sort(
        key=lambda row: (
            -row["critical_count"],
            -row["max_raw_ratio"],
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
        )
    )

    write_csv(
        OUTPUT_DIR / "event_exceedance_audit_summary.csv",
        event_audit_summary,
        [
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "canonical_event_name",
            "exceedance_count",
            "max_raw_ratio",
            "max_gap_pct",
            "critical_count",
            "wind_review_count",
            "quarantine_count",
            "rounding_tolerance_count",
            "logical_result_count",
            "primary_review_priority",
        ],
    )

    manual_template_rows = [
        {
            "audit_exceedance_id": row["audit_exceedance_id"],
            "source_performance_id": row["source_performance_id"],
            "season_type": row["season_type"],
            "canonical_gender_code": row[
                "canonical_gender_code"
            ],
            "canonical_event_code": row[
                "canonical_event_code"
            ],
            "athlete_name": row["athlete_name"],
            "raw_mark": row["raw_mark"],
            "performance_value": row["performance_value"],
            "anchor_value": row["anchor_value"],
            "raw_performance_ratio": row[
                "raw_performance_ratio"
            ],
            "meet_name": row["meet_name"],
            "performance_date": row["performance_date"],
            "provisional_classification": row[
                "provisional_classification"
            ],
            "provisional_scoring_action": row[
                "scoring_action"
            ],
            "resolution_status": "",
            "final_classification": "",
            "final_scoring_action": "",
            "final_anchor_action": "",
            "authoritative_evidence_reference": "",
            "reviewer_notes": "",
            "reviewed_by": "",
            "reviewed_at_utc": "",
        }
        for row in audit_rows
    ]

    write_csv(
        OUTPUT_DIR / "manual_resolution_template.csv",
        manual_template_rows,
        [
            "audit_exceedance_id",
            "source_performance_id",
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "athlete_name",
            "raw_mark",
            "performance_value",
            "anchor_value",
            "raw_performance_ratio",
            "meet_name",
            "performance_date",
            "provisional_classification",
            "provisional_scoring_action",
            "resolution_status",
            "final_classification",
            "final_scoring_action",
            "final_anchor_action",
            "authoritative_evidence_reference",
            "reviewer_notes",
            "reviewed_by",
            "reviewed_at_utc",
        ],
    )

    policy_rows = [
        {
            "rule_id": "EXC-001",
            "rule": "No silent anchor replacement",
            "threshold_or_scope": "all exceedances",
            "scoring_treatment": (
                "Anchor remains unchanged until authoritative verification"
            ),
            "rationale": (
                "A pipeline observation is not itself proof of an official "
                "collegiate-eligibility record."
            ),
        },
        {
            "rule_id": "EXC-002",
            "rule": "Rounding tolerance",
            "threshold_or_scope": (
                f"1 < ratio <= {ROUNDING_TOLERANCE_RATIO}"
            ),
            "scoring_treatment": "retain and cap score at 100",
            "rationale": (
                "Prevents harmless source precision differences from "
                "creating false audit failures."
            ),
        },
        {
            "rule_id": "EXC-003",
            "rule": "Automatic anomaly quarantine",
            "threshold_or_scope": (
                f"ratio >= {AUTOMATIC_ANOMALY_RATIO}"
            ),
            "scoring_treatment": (
                "quarantine from primary scoring; preserve raw row"
            ),
            "rationale": (
                "A gap of at least 5% beyond an established collegiate "
                "anchor strongly suggests event, distance, unit, or parse "
                "mismatch."
            ),
        },
        {
            "rule_id": "EXC-004",
            "rule": "Wind-sensitive exceedance",
            "threshold_or_scope": (
                "outdoor 100m, 200m, 100H, 110H, LJ, TJ"
            ),
            "scoring_treatment": (
                "quarantine until legal wind evidence is available"
            ),
            "rationale": (
                "A mark cannot be compared with an anchor without "
                "comparable legal conditions."
            ),
        },
        {
            "rule_id": "EXC-005",
            "rule": "Verified future record",
            "threshold_or_scope": (
                "authoritative source plus matching eligibility and event"
            ),
            "scoring_treatment": (
                "refresh the versioned anchor, then recompute all levels"
            ),
            "rationale": (
                "The performance should not merely receive a score above "
                "100; the reference registry must be updated."
            ),
        },
        {
            "rule_id": "EXC-006",
            "rule": "Unresolved exceedance",
            "threshold_or_scope": (
                "all non-tolerance rows without final resolution"
            ),
            "scoring_treatment": (
                "excluded from primary ranking; retained in audit outputs"
            ),
            "rationale": (
                "Uncertainty must not silently improve an athlete or school."
            ),
        },
        {
            "rule_id": "EXC-007",
            "rule": "Logical duplicates",
            "threshold_or_scope": (
                "same athlete, event, value, date, meet, and school"
            ),
            "scoring_treatment": (
                "review as one underlying result; preserve row lineage"
            ),
            "rationale": (
                "Multiple rounds or duplicate imports must not multiply "
                "the influence of one result."
            ),
        },
        {
            "rule_id": "EXC-008",
            "rule": "No raw-data deletion",
            "threshold_or_scope": "all audit classifications",
            "scoring_treatment": (
                "apply an eligibility/quarantine flag only"
            ),
            "rationale": (
                "The source record remains traceable and reversible."
            ),
        },
    ]

    write_csv(
        OUTPUT_DIR / "exceedance_policy_rules.csv",
        policy_rows,
        [
            "rule_id",
            "rule",
            "threshold_or_scope",
            "scoring_treatment",
            "rationale",
        ],
    )

    add_check(
        checks,
        "stable_audit_ids_unique",
        len(
            {
                row["audit_exceedance_id"]
                for row in audit_rows
            }
        ) == len(audit_rows),
        len(audit_rows)
        - len(
            {
                row["audit_exceedance_id"]
                for row in audit_rows
            }
        ),
        0,
    )
    add_check(
        checks,
        "row_identifier_strategy_valid",
        all(row["audit_exceedance_id"] for row in audit_rows),
        sum(
            not row["audit_exceedance_id"]
            for row in audit_rows
        ),
        0,
        (
            "Uses a source performance ID when available and always emits "
            "a deterministic audit_exceedance_id."
        ),
    )

    add_check(
        checks,
        "every_exceedance_classified",
        all(
            row["provisional_classification"]
            for row in audit_rows
        ),
        sum(
            not row["provisional_classification"]
            for row in audit_rows
        ),
        0,
    )
    add_check(
        checks,
        "every_exceedance_has_scoring_action",
        all(row["scoring_action"] for row in audit_rows),
        sum(not row["scoring_action"] for row in audit_rows),
        0,
    )
    add_check(
        checks,
        "all_critical_rows_quarantined",
        all(
            row["scoring_action"]
            == "quarantine_from_primary_scoring"
            for row in critical_rows
        ),
        sum(
            row["scoring_action"]
            != "quarantine_from_primary_scoring"
            for row in critical_rows
        ),
        0,
    )
    add_check(
        checks,
        "all_unverified_wind_rows_quarantined",
        all(
            row["scoring_action"]
            == "quarantine_from_primary_scoring"
            for row in wind_review_rows
        ),
        sum(
            row["scoring_action"]
            != "quarantine_from_primary_scoring"
            for row in wind_review_rows
        ),
        0,
    )
    add_check(
        checks,
        "manual_resolution_template_complete",
        len(manual_template_rows) == len(samples),
        len(manual_template_rows),
        len(samples),
    )
    add_check(
        checks,
        "event_audit_summary_complete",
        len(event_audit_summary) == len(summary),
        len(event_audit_summary),
        len(summary),
    )

    sample_hash_after = sha256_file(EXCEEDANCE_SAMPLES)
    summary_hash_after = sha256_file(EXCEEDANCE_SUMMARY)

    add_check(
        checks,
        "phase_4b_samples_unchanged",
        sample_hash_before == sample_hash_after,
        sample_hash_after,
        sample_hash_before,
    )
    add_check(
        checks,
        "phase_4b_summary_unchanged",
        summary_hash_before == summary_hash_after,
        summary_hash_after,
        summary_hash_before,
    )

    write_csv(
        OUTPUT_DIR / "classification_summary.csv",
        [
            {
                "summary_type": "classification",
                "category": key,
                "row_count": value,
            }
            for key, value in sorted(
                classification_counts.items()
            )
        ]
        + [
            {
                "summary_type": "scoring_action",
                "category": key,
                "row_count": value,
            }
            for key, value in sorted(action_counts.items())
        ],
        ["summary_type", "category", "row_count"],
    )

    write_csv(
        OUTPUT_DIR / "input_manifest.csv",
        [
            {
                "input_name": "anchor_exceedance_samples",
                "path": str(EXCEEDANCE_SAMPLES),
                "sha256_before": sample_hash_before,
                "sha256_after": sample_hash_after,
            },
            {
                "input_name": "anchor_exceedance_summary",
                "path": str(EXCEEDANCE_SUMMARY),
                "sha256_before": summary_hash_before,
                "sha256_after": summary_hash_after,
            },
        ],
        [
            "input_name",
            "path",
            "sha256_before",
            "sha256_after",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 5 PHASE 4C — ANCHOR EXCEEDANCE AUDIT",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Audit version: {AUDIT_VERSION}",
        "",
        "POLICY",
        "-" * 78,
        "No unverified performance silently replaces an anchor.",
        "Rounding-only overages may remain eligible and cap at 100.",
        "All other exceedances are quarantined pending resolution.",
        "Verified new records require an anchor-registry refresh.",
        "Raw source rows are never deleted.",
        "",
        "AUDIT POPULATION",
        "-" * 78,
        f"Exceedance rows: {len(audit_rows):,}",
        f"Event combinations: {len(event_audit_summary):,}",
        f"Maximum raw ratio: {observed_max_ratio:.9f}",
        f"Logical duplicate groups: {len(duplicate_groups):,}",
        "",
        "PROVISIONAL ACTIONS",
        "-" * 78,
        f"Quarantined rows: {len(quarantine_rows):,}",
        f"Rounding-tolerance rows: {len(tolerance_rows):,}",
        f"Critical anomalies: {len(critical_rows):,}",
        f"Wind-legality reviews: {len(wind_review_rows):,}",
        "",
        "NEXT DECISION",
        "-" * 78,
        "Review critical anomalies first, then wind-sensitive marks.",
        "Complete manual_resolution_template.csv for unresolved rows.",
        "Do not freeze the exponent until all material rows are resolved.",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Complete audit inventory created; manual resolution "
            "is the next controlled step."
            if not failed
            else "FAIL — Repair audit reconciliation before review."
        ),
    ]

    (OUTPUT_DIR / "phase_4c_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Exceedance rows audited: {len(audit_rows):,}")
    print(f"Event combinations: {len(event_audit_summary):,}")
    print(f"Quarantined rows: {len(quarantine_rows):,}")
    print(f"Rounding-tolerance rows: {len(tolerance_rows):,}")
    print(f"Critical anomalies: {len(critical_rows):,}")
    print(f"Wind-legality reviews: {len(wind_review_rows):,}")
    print(f"Logical duplicate groups: {len(duplicate_groups):,}")
    print()

    if failed:
        print("PHASE GATE: FAIL")
        for row in failed:
            print(
                f"  {row['check_name']}: "
                f"observed={row['observed']} "
                f"expected={row['expected']}"
            )
        return 1

    print("PHASE GATE: PASS")
    print("Next: resolve critical and wind-sensitive exceedances.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
