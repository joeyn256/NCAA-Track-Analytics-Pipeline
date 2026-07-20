#!/usr/bin/env python3
"""
Milestone 5 Phase 3D — Finalize Official-Event Record Anchors

Policy:
1. The saved Track & Field News record pages define the production
   individual-event universe.
2. Use only regular collegiate-season Track, Field, and Multi-Event listings.
3. Exclude relays, secondary American/low-altitude/division listings, and the
   separate "Marks Made Outside Regular Collegiate Season" section.
4. Pending marks ("p") are eligible immediately. If a pending mark is better
   than the ratified mark, it becomes the active scoring anchor.
5. Track-event records use lower-is-better; field and combined-event records
   use higher-is-better.
6. The ranking event scope is the intersection of official T&FN event keys
   and event combinations present in the frozen performance requirements.

This script does not alter source candidates or performance data.
"""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REGISTRY_VERSION = "official_collegiate_record_anchors_v1"
POLICY_VERSION = "tfn_official_events_pending_active_v1"

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
      "final_official_v1"
)

TIME_EVENTS = {
    "50M", "55M", "60M", "100M", "200M", "300M", "400M",
    "500M", "600M", "800M", "1000M", "1500M", "MILE",
    "2000M", "3000M", "2MILE", "5000M", "10000M",
    "50H", "55H", "60H", "100H", "110H", "400H", "3000SC",
}

HIGHER_IS_BETTER_EVENTS = {
    "HJ", "PV", "LJ", "TJ", "SP", "DT", "HT", "JT", "WT",
    "PENT", "HEP", "DEC",
}

ALLOWED_SECTIONS = {"track", "field", "multi"}

# Broad guards eliminate relay splits, imperial conversions, combined-event
# component marks, and other parser artifacts without imposing elite cutoffs.
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
    "HJ": (1.50, 3.00),
    "PV": (3.00, 7.00),
    "LJ": (5.00, 10.00),
    "TJ": (10.00, 20.00),
    "SP": (10.00, 30.00),
    "DT": (35.00, 90.00),
    "HT": (35.00, 100.00),
    "JT": (35.00, 110.00),
    "WT": (15.00, 35.00),
    "PENT": (3000.0, 6000.0),
    "HEP": (4500.0, 8000.0),
    "DEC": (6000.0, 10000.0),
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


def candidate_is_official_main(row: dict[str, Any]) -> bool:
    event_code = row["canonical_event_code"]
    if event_code not in TIME_EVENTS | HIGHER_IS_BETTER_EVENTS:
        return False

    if row.get("section", "").strip().lower() not in ALLOWED_SECTIONS:
        return False

    if bool_value(row.get("secondary_listing")):
        return False

    if bool_value(row.get("outside_regular_collegiate_season")):
        return False

    try:
        mark = float(row["normalized_mark"])
    except (TypeError, ValueError):
        return False

    lower, upper = PLAUSIBLE_BOUNDS[event_code]
    return lower <= mark <= upper


def record_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    event_code = row["canonical_event_code"]
    mark = float(row["normalized_mark"])

    # Better mark first. Pending wins a tie because the policy treats it as
    # active immediately.
    quality = mark if event_code in TIME_EVENTS else -mark
    pending_tiebreak = 0 if bool_value(row["pending_ratification"]) else 1

    # Prefer table parsing over fallback when otherwise identical.
    parser_tiebreak = 0 if row.get("parser_method") == "table" else 1

    return (
        quality,
        pending_tiebreak,
        parser_tiebreak,
        int(row.get("source_table_index") or 0),
        int(row.get("source_row_index") or 0),
    )


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 3D — FINALIZE OFFICIAL-EVENT RECORD ANCHORS")
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

    missing_inputs = [
        f"{name}: {path}"
        for name, path in inputs.items()
        if not path.exists()
    ]

    add_check(
        checks,
        "all_required_inputs_exist",
        not missing_inputs,
        len(missing_inputs),
        0,
        "; ".join(missing_inputs),
    )

    if missing_inputs:
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Missing required inputs.")
        return 1

    input_hashes_before = {
        name: sha256_file(path)
        for name, path in inputs.items()
    }

    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as handle:
        candidate_rows = list(csv.DictReader(handle))

    with REQUIREMENTS_CSV.open(newline="", encoding="utf-8") as handle:
        requirement_rows = list(csv.DictReader(handle))

    add_check(
        checks,
        "candidate_registry_has_rows",
        len(candidate_rows) >= 100,
        len(candidate_rows),
        "at least 100",
    )
    add_check(
        checks,
        "requirement_registry_has_126_rows",
        len(requirement_rows) == 126,
        len(requirement_rows),
        126,
    )

    official_candidates = [
        row for row in candidate_rows
        if candidate_is_official_main(row)
    ]

    # Remove duplicate table/fallback representations while preserving ties
    # and distinct pending/ratified marks.
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for row in sorted(
        official_candidates,
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
            row.get("holder", "").strip(),
            row.get("school", "").strip(),
            row.get("record_date_text", "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(row)

    candidates_by_key: dict[
        tuple[str, str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)

    for row in deduplicated:
        key = (
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
        )
        candidates_by_key[key].append(row)

    official_source_keys = set(candidates_by_key)

    requirement_by_key = {
        (
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
        ): row
        for row in requirement_rows
    }

    official_scoring_keys = sorted(
        official_source_keys & set(requirement_by_key)
    )

    excluded_requirement_keys = sorted(
        set(requirement_by_key) - official_source_keys
    )

    active_anchors: list[dict[str, Any]] = []
    pending_promotions: list[dict[str, Any]] = []
    official_scope_rows: list[dict[str, Any]] = []
    candidate_comparisons: list[dict[str, Any]] = []

    for key in official_scoring_keys:
        rows = sorted(candidates_by_key[key], key=record_sort_key)
        winner = rows[0]
        requirement = requirement_by_key[key]

        ratified_rows = [
            row for row in rows
            if not bool_value(row["pending_ratification"])
        ]
        pending_rows = [
            row for row in rows
            if bool_value(row["pending_ratification"])
        ]

        best_ratified = (
            sorted(ratified_rows, key=record_sort_key)[0]
            if ratified_rows
            else None
        )
        best_pending = (
            sorted(pending_rows, key=record_sort_key)[0]
            if pending_rows
            else None
        )

        winner_pending = bool_value(winner["pending_ratification"])
        status = (
            "pending_used_as_active_record"
            if winner_pending
            else "ratified_active_record"
        )

        active_row = {
            "registry_version": REGISTRY_VERSION,
            "policy_version": POLICY_VERSION,
            "season_type": key[0],
            "canonical_gender_code": key[1],
            "canonical_event_code": key[2],
            "canonical_event_name": requirement[
                "canonical_event_name"
            ],
            "performance_count": requirement["performance_count"],
            "athlete_count": requirement["athlete_count"],
            "school_count": requirement["school_count"],
            "record_mark_raw": winner["raw_mark"],
            "record_mark_normalized": winner["normalized_mark"],
            "record_status": status,
            "pending_ratification": winner_pending,
            "holder": winner.get("holder", ""),
            "school": winner.get("school", ""),
            "record_date_text": winner.get("record_date_text", ""),
            "mark_flags": winner.get("mark_flags", ""),
            "source_key": winner["source_key"],
            "source_url": winner["source_url"],
            "source_as_of": winner.get("source_as_of", ""),
            "source_line": winner.get("source_line", ""),
            "source_html_sha256": winner.get(
                "local_html_sha256", ""
            ),
            "selection_direction": (
                "lower_is_better"
                if key[2] in TIME_EVENTS
                else "higher_is_better"
            ),
            "selection_policy": (
                "best official main-listing mark; pending marks active"
            ),
        }
        active_anchors.append(active_row)

        official_scope_rows.append(
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
                "source_candidate_count": len(rows),
                "ratified_candidate_count": len(ratified_rows),
                "pending_candidate_count": len(pending_rows),
                "active_record_status": status,
                "active_record_mark": winner["raw_mark"],
            }
        )

        comparison = {
            "season_type": key[0],
            "canonical_gender_code": key[1],
            "canonical_event_code": key[2],
            "best_ratified_mark": (
                best_ratified["raw_mark"]
                if best_ratified else ""
            ),
            "best_pending_mark": (
                best_pending["raw_mark"]
                if best_pending else ""
            ),
            "selected_active_mark": winner["raw_mark"],
            "selected_status": status,
            "pending_superseded_ratified": winner_pending,
        }
        candidate_comparisons.append(comparison)

        if winner_pending:
            pending_promotions.append(
                {
                    **active_row,
                    "superseded_ratified_mark": (
                        best_ratified["raw_mark"]
                        if best_ratified else ""
                    ),
                    "superseded_ratified_holder": (
                        best_ratified.get("holder", "")
                        if best_ratified else ""
                    ),
                }
            )

    excluded_rows: list[dict[str, Any]] = []
    for key in excluded_requirement_keys:
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
                    "not_an_official_individual_event_on_matching_tfn_page"
                ),
            }
        )

    source_universe_rows = []
    for key in sorted(official_source_keys):
        rows = sorted(candidates_by_key[key], key=record_sort_key)
        source_universe_rows.append(
            {
                "season_type": key[0],
                "canonical_gender_code": key[1],
                "canonical_event_code": key[2],
                "candidate_count": len(rows),
                "present_in_performance_requirements": (
                    key in requirement_by_key
                ),
                "production_scoring_event": (
                    key in official_scoring_keys
                ),
            }
        )

    official_performance_count = sum(
        int(row["performance_count"])
        for row in official_scope_rows
    )
    all_performance_count = sum(
        int(row["performance_count"])
        for row in requirement_rows
    )
    coverage = (
        official_performance_count / all_performance_count
        if all_performance_count else 0.0
    )

    active_keys = {
        (
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
        )
        for row in active_anchors
    }

    add_check(
        checks,
        "every_official_scoring_event_has_one_anchor",
        active_keys == set(official_scoring_keys),
        len(active_keys),
        len(official_scoring_keys),
    )
    add_check(
        checks,
        "active_anchor_keys_are_unique",
        len(active_keys) == len(active_anchors),
        len(active_anchors) - len(active_keys),
        0,
    )
    add_check(
        checks,
        "unsupported_55m_events_removed",
        not any(
            row["canonical_event_code"] in {"55M", "55H"}
            for row in official_scope_rows
        ),
        sum(
            row["canonical_event_code"] in {"55M", "55H"}
            for row in official_scope_rows
        ),
        0,
    )
    add_check(
        checks,
        "mens_indoor_heptathlon_included",
        ("indoor", "m", "HEP") in active_keys,
        ("indoor", "m", "HEP") in active_keys,
        True,
    )
    add_check(
        checks,
        "indoor_1500_included_for_both_genders",
        all(
            key in active_keys
            for key in [
                ("indoor", "f", "1500M"),
                ("indoor", "m", "1500M"),
            ]
        ),
        sum(
            key in active_keys
            for key in [
                ("indoor", "f", "1500M"),
                ("indoor", "m", "1500M"),
            ]
        ),
        2,
    )
    add_check(
        checks,
        "outdoor_mile_included_for_both_genders",
        all(
            key in active_keys
            for key in [
                ("outdoor", "f", "MILE"),
                ("outdoor", "m", "MILE"),
            ]
        ),
        sum(
            key in active_keys
            for key in [
                ("outdoor", "f", "MILE"),
                ("outdoor", "m", "MILE"),
            ]
        ),
        2,
    )
    add_check(
        checks,
        "pending_marks_can_be_active",
        len(pending_promotions) > 0,
        len(pending_promotions),
        "greater than 0",
    )

    input_hashes_after = {
        name: sha256_file(path)
        for name, path in inputs.items()
    }
    add_check(
        checks,
        "all_inputs_unchanged",
        input_hashes_before == input_hashes_after,
        input_hashes_after,
        input_hashes_before,
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
        "record_status",
        "pending_ratification",
        "holder",
        "school",
        "record_date_text",
        "mark_flags",
        "source_key",
        "source_url",
        "source_as_of",
        "source_line",
        "source_html_sha256",
        "selection_direction",
        "selection_policy",
    ]

    write_csv(
        OUTPUT_DIR / "active_official_record_anchors.csv",
        active_anchors,
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
        OUTPUT_DIR / "official_scoring_event_scope.csv",
        official_scope_rows,
        [
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "canonical_event_name",
            "performance_count",
            "athlete_count",
            "school_count",
            "source_candidate_count",
            "ratified_candidate_count",
            "pending_candidate_count",
            "active_record_status",
            "active_record_mark",
        ],
    )
    write_csv(
        OUTPUT_DIR / "record_candidate_comparison.csv",
        candidate_comparisons,
        [
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "best_ratified_mark",
            "best_pending_mark",
            "selected_active_mark",
            "selected_status",
            "pending_superseded_ratified",
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
    write_csv(
        OUTPUT_DIR / "tfn_official_source_event_universe.csv",
        source_universe_rows,
        [
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "candidate_count",
            "present_in_performance_requirements",
            "production_scoring_event",
        ],
    )
    write_csv(
        OUTPUT_DIR / "input_manifest.csv",
        [
            {
                "input_name": name,
                "path": str(inputs[name]),
                "sha256_before": input_hashes_before[name],
                "sha256_after": input_hashes_after[name],
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
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 5 PHASE 3D — OFFICIAL-EVENT RECORD ANCHORS",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Registry version: {REGISTRY_VERSION}",
        f"Policy version: {POLICY_VERSION}",
        "",
        "SOURCE-DEFINED EVENT POLICY",
        "-" * 78,
        "T&FN individual record tables define the event universe.",
        "Relays and unsupported event combinations are excluded.",
        "No minimum-performance threshold defines event legitimacy.",
        "Pending marks are active when better than ratified marks.",
        "",
        "RESULTS",
        "-" * 78,
        f"Official source event keys: {len(official_source_keys):,}",
        f"Official scoring event combinations: {len(active_anchors):,}",
        f"Pending marks promoted to active: {len(pending_promotions):,}",
        f"Excluded nonofficial requirement combinations: "
        f"{len(excluded_rows):,}",
        f"Official-event scoring performances: "
        f"{official_performance_count:,}",
        f"All requirement performances: {all_performance_count:,}",
        f"Official-event performance coverage: {coverage:.6%}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Official event scope and active record anchors frozen."
            if not failed
            else "FAIL — Review source candidate selection."
        ),
    ]
    (OUTPUT_DIR / "official_anchor_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Official source event keys: {len(official_source_keys):,}")
    print(f"Official scoring event combinations: {len(active_anchors):,}")
    print(f"Pending marks promoted to active: {len(pending_promotions):,}")
    print(
        "Excluded nonofficial requirement combinations: "
        f"{len(excluded_rows):,}"
    )
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
    print("Next: validate record anchors against observed elite marks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
