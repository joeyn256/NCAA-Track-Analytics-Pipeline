#!/usr/bin/env python3
"""
Milestone 5 Phase 3D-R — Finalize Collegiate-Eligibility Anchors

Authoritative policy
--------------------
1. T&FN individual collegiate record pages define the scoring event universe.
2. Regular-season and T&FN-listed outside-season marks are both eligible.
3. T&FN states that its outside-season list includes only athletes who had
   not graduated or turned professional.
4. Pending marks are treated as active when they are the best eligible mark.
5. Relays and secondary sub-listings are excluded.
6. Table-parser candidates are authoritative; fallback rows are audit-only.
7. Lower is better for running events. Higher is better for field and
   combined events.

This creates a new corrected version and does not overwrite the earlier
Phase 3D audit output.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REGISTRY_VERSION = "collegiate_eligibility_anchors_v1"
POLICY_VERSION = "tfn_regular_plus_verified_postseason_pending_active_v1"

ROOT = Path.cwd()

CANDIDATES_CSV = (
    ROOT
    / "data/reference/collegiate_records/v1/"
      "all_record_candidates.csv"
)
REQUIREMENTS_CSV = (
    ROOT
    / "data/processed/milestone5/"
      "collegiate_record_anchors_v1/requirements_v1/"
      "record_anchor_requirements.csv"
)
SOURCE_MANIFEST_CSV = (
    ROOT
    / "data/reference/collegiate_records/v1/"
      "source_manifest.csv"
)

OUTPUT_DIR = (
    ROOT
    / "data/reference/collegiate_records/v1/"
      "final_eligibility_v1"
)

TIME_EVENTS = {
    "50M", "55M", "60M", "100M", "200M", "300M", "400M",
    "500M", "600M", "800M", "1000M", "1500M", "MILE",
    "2000M", "3000M", "2MILE", "5000M", "10000M",
    "50H", "55H", "60H", "100H", "110H", "400H", "3000SC",
}
FIELD_EVENTS = {
    "HJ", "PV", "LJ", "TJ", "SP", "DT", "HT", "JT", "WT",
}
MULTI_EVENTS = {"PENT", "HEP", "DEC"}
SUPPORTED_EVENTS = TIME_EVENTS | FIELD_EVENTS | MULTI_EVENTS
ALLOWED_SECTIONS = {"track", "field", "multi"}

# Broad guards reject parsing artifacts, relay splits, dates, and component
# marks. They are deliberately wider than real collegiate-record ranges.
PLAUSIBLE_BOUNDS = {
    "50M": (4.0, 9.0),
    "55M": (5.0, 10.0),
    "60M": (5.0, 10.0),
    "100M": (8.0, 16.0),
    "200M": (17.0, 35.0),
    "300M": (28.0, 55.0),
    "400M": (38.0, 80.0),
    "500M": (50.0, 110.0),
    "600M": (60.0, 140.0),
    "800M": (85.0, 190.0),
    "1000M": (115.0, 240.0),
    "1500M": (170.0, 360.0),
    "MILE": (190.0, 390.0),
    "2000M": (230.0, 500.0),
    "3000M": (380.0, 850.0),
    "2MILE": (420.0, 900.0),
    "5000M": (650.0, 1500.0),
    "10000M": (1350.0, 3200.0),
    "50H": (5.0, 12.0),
    "55H": (5.0, 13.0),
    "60H": (6.0, 14.0),
    "100H": (10.0, 22.0),
    "110H": (10.0, 22.0),
    "400H": (40.0, 90.0),
    "3000SC": (430.0, 1000.0),
    "HJ": (1.50, 2.60),
    "PV": (3.00, 6.50),
    "LJ": (5.00, 9.50),
    "TJ": (10.00, 19.00),
    "SP": (10.00, 25.00),
    "DT": (35.00, 80.00),
    "HT": (35.00, 90.00),
    "JT": (35.00, 100.00),
    "WT": (15.00, 30.00),
    "PENT": (3000.0, 5500.0),
    "HEP": (4500.0, 7500.0),
    "DEC": (6000.0, 9500.0),
}

# Snapshot sentinels protect the most important policy decisions and the
# parser failures discovered in the previous Phase 3D output.
SENTINELS = {
    # Superior outside-season marks.
    ("outdoor", "m", "800M"): ("1:41.77", False, True),
    ("outdoor", "m", "1500M"): ("3:31.04", False, True),
    ("outdoor", "m", "HT"): ("82.56", False, True),
    ("outdoor", "f", "HJ"): ("2.03", False, True),
    ("outdoor", "f", "HEP"): ("6755", False, True),

    # Pending regular-season marks treated as active.
    ("outdoor", "f", "100M"): ("10.63", True, False),
    ("outdoor", "f", "200M"): ("21.68", True, False),
    ("outdoor", "f", "400M"): ("48.79", True, False),
    ("outdoor", "f", "800M"): ("1:56.85", True, False),
    ("outdoor", "f", "10000M"): ("30:46.80", True, False),
    ("outdoor", "m", "110H"): ("12.75", True, False),
    ("outdoor", "m", "200M"): ("19.63", True, False),
    ("outdoor", "m", "400M"): ("43.38", True, False),

    # Field-event artifact guards.
    ("indoor", "f", "HJ"): ("2.00", False, False),
    ("indoor", "m", "HJ"): ("2.37", False, False),
    ("outdoor", "m", "HJ"): ("2.38", False, False),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def bool_value(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def candidate_rejection_reason(row: dict[str, Any]) -> str:
    event_code = row.get("canonical_event_code", "")

    if row.get("parser_method", "") != "table":
        return "reject_fallback_parser"

    if event_code not in SUPPORTED_EVENTS:
        return "reject_unsupported_or_relay_event"

    section = row.get("section", "").strip().lower()
    outside = bool_value(row.get("outside_regular_collegiate_season"))

    # Outside-season rows can be eligible even when the parser's section
    # value is blank or inherited differently.
    if not outside and section not in ALLOWED_SECTIONS:
        return "reject_non_individual_section"

    if bool_value(row.get("secondary_listing")):
        return "reject_secondary_sublisting"

    try:
        mark = float(row["normalized_mark"])
    except (TypeError, ValueError):
        return "reject_non_numeric_normalized_mark"

    lower, upper = PLAUSIBLE_BOUNDS[event_code]
    if not (lower <= mark <= upper):
        return "reject_implausible_event_mark"

    return ""


def record_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    event_code = row["canonical_event_code"]
    mark = float(row["normalized_mark"])

    quality = mark if event_code in TIME_EVENTS else -mark

    # Pending status does not receive a penalty. It is used only as a
    # deterministic tie-breaker in favor of the user's active-pending rule.
    pending_tiebreak = (
        0 if bool_value(row["pending_ratification"]) else 1
    )

    return (
        quality,
        pending_tiebreak,
        int(row.get("source_table_index") or 0),
        int(row.get("source_row_index") or 0),
    )


def clean_holder_school(row: dict[str, Any]) -> tuple[str, str]:
    line = row.get("source_line", "").strip()
    raw_mark = row.get("raw_mark", "").strip()

    if not line or not raw_mark or raw_mark not in line:
        return (
            row.get("holder", "").strip(),
            row.get("school", "").strip(),
        )

    tail = line.split(raw_mark, 1)[1]

    # Remove immediate record flags.
    tail = re.sub(
        r"^\s*(?:(?:\(A\))|[ipyw])*\s*",
        "",
        tail,
        flags=re.IGNORECASE,
    )

    # Remove imperial equivalent on field-event rows.
    tail = re.sub(
        r"^\|\s*"
        r"[0-9]+-[0-9¼½¾⅛⅜⅝⅞\-]*"
        r"(?:\(A\))?"
        r"\s*",
        "",
        tail,
        flags=re.IGNORECASE,
    )

    school_match = re.search(r"\(([^()]*)\)", tail)
    if school_match:
        holder = tail[: school_match.start()].strip()
        school = school_match.group(1).strip()
        return holder, school

    holder = re.sub(
        r"\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ .’'\-]+,\s+"
        r"[A-ZÀ-Ý][A-Za-zÀ-ÿ .’'\-]+\s+"
        r"\d{1,2}/\d{1,2}(?:-\d{1,2})?/\d{2,4}$",
        "",
        tail,
    ).strip()

    return holder, row.get("school", "").strip()


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 3D-R — COLLEGIATE-ELIGIBILITY ANCHORS")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Registry version: {REGISTRY_VERSION}")
    print(f"Policy version: {POLICY_VERSION}")
    print(f"Output: {OUTPUT_DIR}")

    inputs = {
        "record_candidates": CANDIDATES_CSV,
        "record_requirements": REQUIREMENTS_CSV,
        "source_manifest": SOURCE_MANIFEST_CSV,
    }
    missing = [
        f"{name}: {path}"
        for name, path in inputs.items()
        if not path.exists()
    ]

    add_check(
        checks,
        "all_required_inputs_exist",
        not missing,
        len(missing),
        0,
        "; ".join(missing),
    )

    if missing:
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Missing required inputs.")
        return 1

    hashes_before = {
        name: sha256_file(path)
        for name, path in inputs.items()
    }

    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as handle:
        all_candidates = list(csv.DictReader(handle))

    with REQUIREMENTS_CSV.open(newline="", encoding="utf-8") as handle:
        requirements = list(csv.DictReader(handle))

    add_check(
        checks,
        "candidate_registry_has_rows",
        len(all_candidates) >= 100,
        len(all_candidates),
        "at least 100",
    )
    add_check(
        checks,
        "requirement_registry_has_126_rows",
        len(requirements) == 126,
        len(requirements),
        126,
    )

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for row in all_candidates:
        reason = candidate_rejection_reason(row)
        if reason:
            rejected.append({**row, "rejection_reason": reason})
        else:
            accepted.append(row)

    add_check(
        checks,
        "only_table_parser_candidates_accepted",
        all(row.get("parser_method") == "table" for row in accepted),
        sum(row.get("parser_method") != "table" for row in accepted),
        0,
    )

    # Deduplicate exact duplicate representations while retaining tied
    # record holders and separate pending/ratified marks.
    unique_candidates: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for row in sorted(
        accepted,
        key=lambda item: (
            item["source_key"],
            item["canonical_event_code"],
            record_sort_key(item),
        ),
    ):
        key = (
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
            row["raw_mark"],
            bool_value(row["pending_ratification"]),
            bool_value(row["outside_regular_collegiate_season"]),
            row.get("source_line", "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(row)

    candidates_by_key: dict[
        tuple[str, str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)

    for row in unique_candidates:
        key = (
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
        )
        candidates_by_key[key].append(row)

    requirement_by_key = {
        (
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
        ): row
        for row in requirements
    }

    official_source_keys = set(candidates_by_key)
    scoring_keys = sorted(official_source_keys & set(requirement_by_key))
    excluded_keys = sorted(set(requirement_by_key) - official_source_keys)

    anchors: list[dict[str, Any]] = []
    pending_promotions: list[dict[str, Any]] = []
    outside_promotions: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    scope_rows: list[dict[str, Any]] = []

    for key in scoring_keys:
        rows = sorted(candidates_by_key[key], key=record_sort_key)
        winner = rows[0]
        requirement = requirement_by_key[key]

        regular_rows = [
            row for row in rows
            if not bool_value(
                row.get("outside_regular_collegiate_season")
            )
        ]
        outside_rows = [
            row for row in rows
            if bool_value(
                row.get("outside_regular_collegiate_season")
            )
        ]
        ratified_rows = [
            row for row in rows
            if not bool_value(row.get("pending_ratification"))
        ]
        pending_rows = [
            row for row in rows
            if bool_value(row.get("pending_ratification"))
        ]

        best_regular = (
            sorted(regular_rows, key=record_sort_key)[0]
            if regular_rows else None
        )
        best_outside = (
            sorted(outside_rows, key=record_sort_key)[0]
            if outside_rows else None
        )
        best_ratified = (
            sorted(ratified_rows, key=record_sort_key)[0]
            if ratified_rows else None
        )
        best_pending = (
            sorted(pending_rows, key=record_sort_key)[0]
            if pending_rows else None
        )

        pending = bool_value(winner.get("pending_ratification"))
        outside = bool_value(
            winner.get("outside_regular_collegiate_season")
        )
        holder, school = clean_holder_school(winner)

        if outside:
            status = "verified_outside_season_active_anchor"
            context = "outside_regular_season_tfn_eligibility_verified"
        elif pending:
            status = "pending_active_anchor"
            context = "regular_collegiate_season"
        else:
            status = "ratified_active_anchor"
            context = "regular_collegiate_season"

        anchor = {
            "registry_version": REGISTRY_VERSION,
            "policy_version": POLICY_VERSION,
            "season_type": key[0],
            "canonical_gender_code": key[1],
            "canonical_event_code": key[2],
            "canonical_event_name": requirement["canonical_event_name"],
            "performance_count": requirement["performance_count"],
            "athlete_count": requirement["athlete_count"],
            "school_count": requirement["school_count"],
            "record_mark_raw": winner["raw_mark"],
            "record_mark_normalized": winner["normalized_mark"],
            "anchor_status": status,
            "performance_context": context,
            "pending_ratification": pending,
            "outside_regular_collegiate_season": outside,
            "tfn_eligibility_verified": True,
            "holder": holder,
            "school": school,
            "record_date_text": winner.get("record_date_text", ""),
            "mark_flags": winner.get("mark_flags", ""),
            "source_key": winner["source_key"],
            "source_url": winner["source_url"],
            "source_as_of": winner.get("source_as_of", ""),
            "source_line": winner.get("source_line", ""),
            "source_html_sha256": winner.get(
                "local_html_sha256", ""
            ),
            "parser_method": winner.get("parser_method", ""),
            "selection_direction": (
                "lower_is_better"
                if key[2] in TIME_EVENTS
                else "higher_is_better"
            ),
            "selection_policy": (
                "best T&FN-listed collegiate-eligible mark; "
                "verified outside-season and pending marks allowed"
            ),
        }
        anchors.append(anchor)

        scope_rows.append(
            {
                "season_type": key[0],
                "canonical_gender_code": key[1],
                "canonical_event_code": key[2],
                "canonical_event_name": requirement["canonical_event_name"],
                "performance_count": requirement["performance_count"],
                "candidate_count": len(rows),
                "regular_candidate_count": len(regular_rows),
                "outside_candidate_count": len(outside_rows),
                "ratified_candidate_count": len(ratified_rows),
                "pending_candidate_count": len(pending_rows),
                "active_anchor_mark": winner["raw_mark"],
                "active_anchor_status": status,
            }
        )

        comparisons.append(
            {
                "season_type": key[0],
                "canonical_gender_code": key[1],
                "canonical_event_code": key[2],
                "best_regular_mark": (
                    best_regular["raw_mark"] if best_regular else ""
                ),
                "best_outside_mark": (
                    best_outside["raw_mark"] if best_outside else ""
                ),
                "best_ratified_mark": (
                    best_ratified["raw_mark"] if best_ratified else ""
                ),
                "best_pending_mark": (
                    best_pending["raw_mark"] if best_pending else ""
                ),
                "selected_active_mark": winner["raw_mark"],
                "selected_status": status,
            }
        )

        if pending:
            pending_promotions.append(
                {
                    **anchor,
                    "superseded_ratified_mark": (
                        best_ratified["raw_mark"]
                        if best_ratified else ""
                    ),
                    "superseded_ratified_holder": (
                        clean_holder_school(best_ratified)[0]
                        if best_ratified else ""
                    ),
                }
            )

        if outside:
            outside_promotions.append(
                {
                    **anchor,
                    "superseded_regular_season_mark": (
                        best_regular["raw_mark"]
                        if best_regular else ""
                    ),
                    "superseded_regular_season_holder": (
                        clean_holder_school(best_regular)[0]
                        if best_regular else ""
                    ),
                }
            )

    excluded_rows = []
    for key in excluded_keys:
        requirement = requirement_by_key[key]
        excluded_rows.append(
            {
                "season_type": key[0],
                "canonical_gender_code": key[1],
                "canonical_event_code": key[2],
                "canonical_event_name": requirement[
                    "canonical_event_name"
                ],
                "performance_count": requirement["performance_count"],
                "athlete_count": requirement["athlete_count"],
                "school_count": requirement["school_count"],
                "exclusion_reason": (
                    "not_an_individual_event_on_matching_tfn_record_page"
                ),
            }
        )

    anchor_by_key = {
        (
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
        ): row
        for row in anchors
    }

    add_check(
        checks,
        "official_scoring_anchor_count",
        len(anchors) == 82,
        len(anchors),
        82,
    )
    add_check(
        checks,
        "active_anchor_keys_unique",
        len(anchor_by_key) == len(anchors),
        len(anchors) - len(anchor_by_key),
        0,
    )
    add_check(
        checks,
        "unsupported_55m_events_removed",
        not any(
            row["canonical_event_code"] in {"55M", "55H"}
            for row in anchors
        ),
        sum(
            row["canonical_event_code"] in {"55M", "55H"}
            for row in anchors
        ),
        0,
    )
    add_check(
        checks,
        "pending_active_anchor_count",
        len(pending_promotions) == 8,
        len(pending_promotions),
        8,
    )
    add_check(
        checks,
        "verified_outside_anchor_count",
        len(outside_promotions) == 5,
        len(outside_promotions),
        5,
    )

    for key, (
        expected_mark,
        expected_pending,
        expected_outside,
    ) in SENTINELS.items():
        row = anchor_by_key.get(key)
        observed = (
            (
                f"{row['record_mark_raw']}|"
                f"{row['pending_ratification']}|"
                f"{row['outside_regular_collegiate_season']}"
            )
            if row else "missing"
        )
        expected = (
            f"{expected_mark}|"
            f"{expected_pending}|"
            f"{expected_outside}"
        )

        add_check(
            checks,
            "sentinel_" + "_".join(key),
            bool(
                row
                and row["record_mark_raw"] == expected_mark
                and bool_value(row["pending_ratification"])
                == expected_pending
                and bool_value(
                    row["outside_regular_collegiate_season"]
                ) == expected_outside
            ),
            observed,
            expected,
        )

    add_check(
        checks,
        "all_high_jump_marks_realistic",
        all(
            1.50
            <= float(row["record_mark_normalized"])
            <= 2.60
            for row in anchors
            if row["canonical_event_code"] == "HJ"
        ),
        [
            row["record_mark_raw"]
            for row in anchors
            if row["canonical_event_code"] == "HJ"
        ],
        "all between 1.50 and 2.60 meters",
    )

    add_check(
        checks,
        "all_outside_anchors_tfn_verified",
        all(
            bool_value(row["tfn_eligibility_verified"])
            for row in outside_promotions
        ),
        sum(
            not bool_value(row["tfn_eligibility_verified"])
            for row in outside_promotions
        ),
        0,
    )

    official_performances = sum(
        int(row["performance_count"]) for row in anchors
    )
    all_performances = sum(
        int(row["performance_count"]) for row in requirements
    )
    coverage = (
        official_performances / all_performances
        if all_performances else 0.0
    )

    hashes_after = {
        name: sha256_file(path)
        for name, path in inputs.items()
    }
    add_check(
        checks,
        "all_inputs_unchanged",
        hashes_before == hashes_after,
        hashes_after,
        hashes_before,
    )

    anchor_fields = [
        "registry_version",
        "policy_version",
        "season_type",
        "canonical_gender_code",
        "canonical_event_code",
        "canonical_event_name",
        "performance_count",
        "athlete_count",
        "school_count",
        "record_mark_raw",
        "record_mark_normalized",
        "anchor_status",
        "performance_context",
        "pending_ratification",
        "outside_regular_collegiate_season",
        "tfn_eligibility_verified",
        "holder",
        "school",
        "record_date_text",
        "mark_flags",
        "source_key",
        "source_url",
        "source_as_of",
        "source_line",
        "source_html_sha256",
        "parser_method",
        "selection_direction",
        "selection_policy",
    ]

    write_csv(
        OUTPUT_DIR / "active_collegiate_eligibility_anchors.csv",
        anchors,
        anchor_fields,
    )
    write_csv(
        OUTPUT_DIR / "pending_promoted_to_active.csv",
        pending_promotions,
        anchor_fields
        + [
            "superseded_ratified_mark",
            "superseded_ratified_holder",
        ],
    )
    write_csv(
        OUTPUT_DIR / "outside_season_promoted_to_active.csv",
        outside_promotions,
        anchor_fields
        + [
            "superseded_regular_season_mark",
            "superseded_regular_season_holder",
        ],
    )
    write_csv(
        OUTPUT_DIR / "official_scoring_event_scope.csv",
        scope_rows,
        [
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "canonical_event_name",
            "performance_count",
            "candidate_count",
            "regular_candidate_count",
            "outside_candidate_count",
            "ratified_candidate_count",
            "pending_candidate_count",
            "active_anchor_mark",
            "active_anchor_status",
        ],
    )
    write_csv(
        OUTPUT_DIR / "record_candidate_comparison.csv",
        comparisons,
        [
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "best_regular_mark",
            "best_outside_mark",
            "best_ratified_mark",
            "best_pending_mark",
            "selected_active_mark",
            "selected_status",
        ],
    )
    write_csv(
        OUTPUT_DIR / "excluded_nonofficial_event_combinations.csv",
        excluded_rows,
        [
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "canonical_event_name",
            "performance_count",
            "athlete_count",
            "school_count",
            "exclusion_reason",
        ],
    )

    rejected_fields = list(all_candidates[0].keys()) + [
        "rejection_reason"
    ]
    write_csv(
        OUTPUT_DIR / "rejected_record_candidates.csv",
        rejected,
        rejected_fields,
    )

    reason_summary = Counter(
        row["rejection_reason"] for row in rejected
    )
    write_csv(
        OUTPUT_DIR / "rejection_summary.csv",
        [
            {
                "rejection_reason": reason,
                "candidate_count": count,
            }
            for reason, count in sorted(reason_summary.items())
        ],
        ["rejection_reason", "candidate_count"],
    )

    write_csv(
        OUTPUT_DIR / "input_manifest.csv",
        [
            {
                "input_name": name,
                "path": str(inputs[name]),
                "sha256_before": hashes_before[name],
                "sha256_after": hashes_after[name],
            }
            for name in inputs
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
        [
            "check_name",
            "status",
            "observed",
            "expected",
            "details",
        ],
    )

    failed = [
        row for row in checks if row["status"] == "FAIL"
    ]

    report = [
        "MILESTONE 5 PHASE 3D-R — COLLEGIATE-ELIGIBILITY ANCHORS",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Registry version: {REGISTRY_VERSION}",
        f"Policy version: {POLICY_VERSION}",
        "",
        "ELIGIBILITY POLICY",
        "-" * 78,
        "T&FN individual record pages define official events.",
        "Regular-season and T&FN-verified outside-season marks count.",
        "T&FN states outside-season athletes have not graduated/turned pro.",
        "Pending marks count immediately when they are the best mark.",
        "Ordinary pipeline performances still require school-stint validation.",
        "",
        "RESULTS",
        "-" * 78,
        f"Accepted unique source candidates: {len(unique_candidates):,}",
        f"Rejected candidates: {len(rejected):,}",
        f"Official scoring anchors: {len(anchors):,}",
        f"Pending marks promoted: {len(pending_promotions):,}",
        f"Outside-season marks promoted: {len(outside_promotions):,}",
        f"Excluded nonofficial combinations: {len(excluded_rows):,}",
        f"Official-event performance coverage: {coverage:.6%}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Collegiate-eligibility anchors are ready to validate."
            if not failed
            else "FAIL — Do not use or commit this registry."
        ),
    ]
    (OUTPUT_DIR / "eligibility_anchor_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Accepted unique source candidates: {len(unique_candidates):,}")
    print(f"Rejected candidates: {len(rejected):,}")
    print(f"Official scoring anchors: {len(anchors):,}")
    print(f"Pending marks promoted: {len(pending_promotions):,}")
    print(f"Outside-season marks promoted: {len(outside_promotions):,}")
    print(f"Official-event performance coverage: {coverage:.6%}")
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
    print("Next: compare every anchor to observed elite marks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
