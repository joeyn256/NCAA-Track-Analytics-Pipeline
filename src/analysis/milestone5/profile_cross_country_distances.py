#!/usr/bin/env python3
"""
Milestone 5 Phase 2D — Cross-Country Distance Normalization Profile

Builds a read-only draft distance registry for cross-country labels.

Goals:
- preserve cross country as a separate ranking model;
- normalize equivalent labels such as 3.1M/3.11M/3.12M to 5K;
- normalize labels such as 4.971M and 8000 to 8K;
- preserve actual measured distance for later time conversion;
- avoid combining materially different course distances;
- do not treat XC times as directly comparable to track times.

This step profiles and proposes mappings. It does not freeze the XC scoring
methodology or create final school rankings.
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


PROFILE_VERSION = "xc_distance_profile_v1"
EXPECTED_ALL_LABELS = 347
EXPECTED_EXISTING_XC_LABELS = 226
DIRECT_EQUIVALENCE_TOLERANCE = 0.02  # +/- 2 percent
MIN_PROFILED_GROUP_PERFORMANCES = 5_000

EVENT_LABEL_MAP = Path(
    "data/processed/milestone5/event_registry_v1/"
    "final_v1/event_label_map.csv"
)
OUTPUT_DIR = Path(
    "data/processed/milestone5/cross_country_registry_v1/"
    "profile_v1"
)

STANDARD_DISTANCES = {
    3000: "3K",
    4000: "4K",
    5000: "5K",
    6000: "6K",
    8000: "8K",
    10000: "10K",
}

MILES_TO_METERS = 1609.344


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, block_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(block_size):
            digest.update(chunk)
    return digest.hexdigest()


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


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
        for row in rows:
            writer.writerow(row)


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


def normalize_label(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def parse_distance_label(raw_label: str) -> tuple[float | None, str, str]:
    """
    Returns:
        actual_distance_meters
        parsed_unit
        parse_rule
    """
    label = normalize_label(raw_label)

    # Case-sensitive uppercase M is treated as miles. This preserves the
    # distinction that was intentionally identified in Phase 1C.
    match = re.fullmatch(r"(\d+(?:\.\d+)?)M", label)
    if match:
        miles = float(match.group(1))
        return (
            miles * MILES_TO_METERS,
            "miles",
            "numeric_uppercase_M_miles",
        )

    # K/k labels are course distances in kilometers.
    match = re.fullmatch(r"(\d+(?:\.\d+)?)[Kk]", label)
    if match:
        kilometers = float(match.group(1))
        return (
            kilometers * 1000.0,
            "kilometers",
            "numeric_kilometers",
        )

    match = re.fullmatch(
        r"(\d+(?:\.\d+)?)(?:mi|mile|miles)",
        label,
        flags=re.IGNORECASE,
    )
    if match:
        miles = float(match.group(1))
        return (
            miles * MILES_TO_METERS,
            "miles",
            "named_miles",
        )

    match = re.fullmatch(
        r"(\d+(?:\.\d+)?)(?:km|kilometer|kilometers)",
        label,
        flags=re.IGNORECASE,
    )
    if match:
        kilometers = float(match.group(1))
        return (
            kilometers * 1000.0,
            "kilometers",
            "named_kilometers",
        )

    # Bare course-like labels such as 8000 are interpreted as meters only
    # when they are at least 1000. Small bare labels remain outside XC.
    match = re.fullmatch(r"(\d{4,5})", label)
    if match:
        meters = float(match.group(1))
        if 1000 <= meters <= 20000:
            return meters, "meters", "bare_numeric_meters"

    return None, "", "unresolved"


def nearest_standard_distance(
    actual_meters: float,
) -> tuple[int, str, float, float]:
    target = min(
        STANDARD_DISTANCES,
        key=lambda candidate: abs(actual_meters - candidate),
    )
    absolute_difference = actual_meters - target
    relative_difference = absolute_difference / target
    return (
        target,
        STANDARD_DISTANCES[target],
        absolute_difference,
        relative_difference,
    )


def candidate_reason(row: dict[str, str]) -> str:
    disposition = row["registry_disposition"].strip()
    raw_label = row["raw_event_label"].strip()

    if disposition == "separate_cross_country_model":
        return "existing_cross_country_disposition"

    distance, _, parse_rule = parse_distance_label(raw_label)
    if (
        disposition == "exclude_low_sample"
        and distance is not None
        and parse_rule == "bare_numeric_meters"
    ):
        return "course_like_bare_meter_label_from_low_sample_exclusions"

    return ""


def main() -> int:
    root = Path.cwd()
    input_path = root / EVENT_LABEL_MAP
    output_dir = root / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 2D — CROSS-COUNTRY DISTANCE PROFILE")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Profile version: {PROFILE_VERSION}")
    print(f"Direct-equivalence tolerance: {DIRECT_EQUIVALENCE_TOLERANCE:.2%}")
    print(f"Input: {input_path}")
    print(f"Output: {output_dir}")

    exists = input_path.exists()
    add_check(
        checks,
        "event_label_map_exists",
        exists,
        exists,
        True,
        str(input_path),
    )
    if not exists:
        write_csv(
            output_dir / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Final event label map is missing.")
        return 1

    input_hash_before = sha256_file(input_path)
    input_stat_before = input_path.stat()

    with input_path.open(newline="", encoding="utf-8") as handle:
        all_rows = list(csv.DictReader(handle))

    existing_xc_count = sum(
        row["registry_disposition"] == "separate_cross_country_model"
        for row in all_rows
    )

    add_check(
        checks,
        "all_event_label_rows_loaded",
        len(all_rows) == EXPECTED_ALL_LABELS,
        len(all_rows),
        EXPECTED_ALL_LABELS,
    )
    add_check(
        checks,
        "existing_cross_country_label_count",
        existing_xc_count == EXPECTED_EXISTING_XC_LABELS,
        existing_xc_count,
        EXPECTED_EXISTING_XC_LABELS,
    )

    candidate_rows: list[dict[str, Any]] = []

    for row in all_rows:
        reason = candidate_reason(row)
        if not reason:
            continue

        raw_label = row["raw_event_label"].strip()
        actual_meters, parsed_unit, parse_rule = parse_distance_label(
            raw_label
        )
        performance_count = parse_int(row["performance_count"])

        output_row: dict[str, Any] = {
            "profile_version": PROFILE_VERSION,
            "event_id": row["event_id"],
            "raw_event_label": raw_label,
            "source_registry_disposition": row[
                "registry_disposition"
            ],
            "candidate_reason": reason,
            "performance_count": performance_count,
            "actual_distance_meters": (
                ""
                if actual_meters is None
                else round(actual_meters, 6)
            ),
            "parsed_unit": parsed_unit,
            "distance_parse_rule": parse_rule,
            "suggested_canonical_distance_code": "",
            "suggested_canonical_distance_name": "",
            "canonical_distance_meters": "",
            "distance_difference_meters": "",
            "distance_difference_percent": "",
            "normalization_disposition": "",
            "time_conversion_required": "",
            "suggested_time_conversion_exponent": "",
            "normalization_reason": "",
        }

        if actual_meters is None or actual_meters <= 0:
            output_row.update(
                {
                    "normalization_disposition": (
                        "unresolved_distance_label"
                    ),
                    "time_conversion_required": "",
                    "normalization_reason": (
                        "distance_could_not_be_parsed_reliably"
                    ),
                }
            )
            candidate_rows.append(output_row)
            continue

        (
            target_meters,
            target_code,
            difference_meters,
            difference_ratio,
        ) = nearest_standard_distance(actual_meters)

        directly_equivalent = (
            abs(difference_ratio) <= DIRECT_EQUIVALENCE_TOLERANCE
        )

        output_row.update(
            {
                "suggested_canonical_distance_code": target_code,
                "suggested_canonical_distance_name": (
                    f"{target_code} Cross Country"
                ),
                "canonical_distance_meters": target_meters,
                "distance_difference_meters": round(
                    difference_meters,
                    6,
                ),
                "distance_difference_percent": round(
                    difference_ratio * 100.0,
                    6,
                ),
                "normalization_disposition": (
                    "direct_canonical_equivalent"
                    if directly_equivalent
                    else "preserve_distinct_distance"
                ),
                "time_conversion_required": (
                    "false" if math.isclose(
                        actual_meters,
                        target_meters,
                        rel_tol=0,
                        abs_tol=0.5,
                    )
                    else (
                        "true"
                        if directly_equivalent
                        else "not_applicable"
                    )
                ),
                "suggested_time_conversion_exponent": (
                    1.06 if directly_equivalent else ""
                ),
                "normalization_reason": (
                    "within_2_percent_of_standard_xc_distance"
                    if directly_equivalent
                    else "materially_different_from_standard_xc_distance"
                ),
            }
        )

        candidate_rows.append(output_row)

    candidate_rows.sort(
        key=lambda row: (
            row["normalization_disposition"],
            row["suggested_canonical_distance_code"],
            float(row["actual_distance_meters"] or 0),
            row["raw_event_label"],
        )
    )

    direct_rows = [
        row
        for row in candidate_rows
        if row["normalization_disposition"]
        == "direct_canonical_equivalent"
    ]
    distinct_rows = [
        row
        for row in candidate_rows
        if row["normalization_disposition"]
        == "preserve_distinct_distance"
    ]
    unresolved_rows = [
        row
        for row in candidate_rows
        if row["normalization_disposition"]
        == "unresolved_distance_label"
    ]

    summary: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "canonical_distance_code": "",
            "canonical_distance_name": "",
            "canonical_distance_meters": 0,
            "raw_label_count": 0,
            "performance_count": 0,
            "raw_labels": [],
            "minimum_group_performances": (
                MIN_PROFILED_GROUP_PERFORMANCES
            ),
        }
    )

    for row in direct_rows:
        code = row["suggested_canonical_distance_code"]
        item = summary[code]
        item["canonical_distance_code"] = code
        item["canonical_distance_name"] = row[
            "suggested_canonical_distance_name"
        ]
        item["canonical_distance_meters"] = row[
            "canonical_distance_meters"
        ]
        item["raw_label_count"] += 1
        item["performance_count"] += int(row["performance_count"])
        item["raw_labels"].append(row["raw_event_label"])

    summary_rows: list[dict[str, Any]] = []
    for code, row in summary.items():
        row["raw_labels"] = " | ".join(
            sorted(set(row["raw_labels"]))
        )
        row["meets_5000_performance_threshold"] = (
            row["performance_count"]
            >= MIN_PROFILED_GROUP_PERFORMANCES
        )
        summary_rows.append(row)

    summary_rows.sort(
        key=lambda row: (
            -int(row["performance_count"]),
            row["canonical_distance_code"],
        )
    )

    all_candidate_ids = [row["event_id"] for row in candidate_rows]
    duplicate_candidate_ids = (
        len(all_candidate_ids) - len(set(all_candidate_ids))
    )

    add_check(
        checks,
        "candidate_event_ids_unique",
        duplicate_candidate_ids == 0,
        duplicate_candidate_ids,
        0,
    )
    add_check(
        checks,
        "all_existing_xc_labels_enter_profile",
        sum(
            row["candidate_reason"]
            == "existing_cross_country_disposition"
            for row in candidate_rows
        )
        == EXPECTED_EXISTING_XC_LABELS,
        sum(
            row["candidate_reason"]
            == "existing_cross_country_disposition"
            for row in candidate_rows
        ),
        EXPECTED_EXISTING_XC_LABELS,
    )
    add_check(
        checks,
        "requested_5k_examples_map_correctly",
        all(
            any(
                row["raw_event_label"] == label
                and row["suggested_canonical_distance_code"] == "5K"
                and row["normalization_disposition"]
                == "direct_canonical_equivalent"
                for row in candidate_rows
            )
            for label in ["3.1M", "3.11M", "3.12M"]
            if any(
                source["raw_event_label"] == label
                for source in all_rows
            )
        ),
        "checked labels present in source",
        "all present examples map to 5K",
    )
    add_check(
        checks,
        "requested_8k_examples_map_correctly",
        all(
            any(
                row["raw_event_label"] == label
                and row["suggested_canonical_distance_code"] == "8K"
                and row["normalization_disposition"]
                == "direct_canonical_equivalent"
                for row in candidate_rows
            )
            for label in ["4.971M", "8000"]
            if any(
                source["raw_event_label"] == label
                for source in all_rows
            )
        ),
        "checked labels present in source",
        "all present examples map to 8K",
    )

    fields = [
        "profile_version",
        "event_id",
        "raw_event_label",
        "source_registry_disposition",
        "candidate_reason",
        "performance_count",
        "actual_distance_meters",
        "parsed_unit",
        "distance_parse_rule",
        "suggested_canonical_distance_code",
        "suggested_canonical_distance_name",
        "canonical_distance_meters",
        "distance_difference_meters",
        "distance_difference_percent",
        "normalization_disposition",
        "time_conversion_required",
        "suggested_time_conversion_exponent",
        "normalization_reason",
    ]

    write_csv(
        output_dir / "xc_distance_profile.csv",
        candidate_rows,
        fields,
    )
    write_csv(
        output_dir / "xc_direct_equivalence_map.csv",
        direct_rows,
        fields,
    )
    write_csv(
        output_dir / "xc_distinct_distance_labels.csv",
        distinct_rows,
        fields,
    )
    write_csv(
        output_dir / "xc_unresolved_labels.csv",
        unresolved_rows,
        fields,
    )
    write_csv(
        output_dir / "xc_canonical_distance_summary.csv",
        summary_rows,
        [
            "canonical_distance_code",
            "canonical_distance_name",
            "canonical_distance_meters",
            "raw_label_count",
            "performance_count",
            "raw_labels",
            "minimum_group_performances",
            "meets_5000_performance_threshold",
        ],
    )

    input_hash_after = sha256_file(input_path)
    input_stat_after = input_path.stat()
    unchanged = (
        input_hash_after == input_hash_before
        and input_stat_after.st_size == input_stat_before.st_size
        and input_stat_after.st_mtime_ns
        == input_stat_before.st_mtime_ns
    )
    add_check(
        checks,
        "event_label_map_unchanged",
        unchanged,
        input_hash_after,
        input_hash_before,
    )

    write_csv(
        output_dir / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [
        check for check in checks
        if check["status"] == "FAIL"
    ]

    performance_counts = Counter(
        row["normalization_disposition"]
        for row in candidate_rows
        for _ in range(0)
    )
    # Explicit sums are clearer than expanding rows.
    direct_performances = sum(
        int(row["performance_count"]) for row in direct_rows
    )
    distinct_performances = sum(
        int(row["performance_count"]) for row in distinct_rows
    )
    unresolved_performances = sum(
        int(row["performance_count"]) for row in unresolved_rows
    )

    report_lines = [
        "MILESTONE 5 PHASE 2D — CROSS-COUNTRY DISTANCE PROFILE",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Profile version: {PROFILE_VERSION}",
        "",
        "CANDIDATE SCALE",
        "-" * 78,
        f"All source event labels: {len(all_rows):,}",
        f"Existing XC labels: {existing_xc_count:,}",
        f"Total XC/course candidates profiled: {len(candidate_rows):,}",
        f"Direct canonical equivalents: {len(direct_rows):,}",
        f"Distinct-distance labels preserved: {len(distinct_rows):,}",
        f"Unresolved distance labels: {len(unresolved_rows):,}",
        "",
        "PERFORMANCE COVERAGE",
        "-" * 78,
        f"Direct-equivalent performances: {direct_performances:,}",
        f"Distinct-distance performances: {distinct_performances:,}",
        f"Unresolved-label performances: {unresolved_performances:,}",
        "",
        "NORMALIZATION POLICY",
        "-" * 78,
        "Uppercase M labels are interpreted as miles.",
        "K/k labels are interpreted as kilometers.",
        "Bare four- or five-digit labels are interpreted as meters.",
        "Labels within +/-2% of 3K/4K/5K/6K/8K/10K map directly.",
        "Actual measured distance is retained for later time conversion.",
        "Materially different distances remain separate.",
        "",
        "EXAMPLES",
        "-" * 78,
        "3.1M, 3.11M, and 3.12M -> 5K",
        "4.971M and 8000 -> 8K",
        "",
        "SCORING BOUNDARY",
        "-" * 78,
        "XC is a separate ranking model from indoor and outdoor track.",
        "Course times will not be compared as if all courses were identical.",
        "NCAA track records will not be used as XC scoring ceilings.",
        "Later XC scoring should include course/meet difficulty adjustment.",
        "",
        "HARD CHECK SUMMARY",
        "-" * 78,
        f"PASS: {sum(c['status'] == 'PASS' for c in checks)}",
        f"FAIL: {len(failed)}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — XC distance labels are profiled for registry construction."
            if not failed
            else "FAIL — Correct XC distance-profile accounting errors."
        ),
    ]

    (output_dir / "xc_distance_profile_report.txt").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"XC/course candidates profiled: {len(candidate_rows):,}")
    print(f"Direct canonical equivalents: {len(direct_rows):,}")
    print(f"Distinct-distance labels preserved: {len(distinct_rows):,}")
    print(f"Unresolved labels: {len(unresolved_rows):,}")
    print()
    print("Created:")
    for filename in [
        "xc_distance_profile_report.txt",
        "xc_distance_profile.csv",
        "xc_direct_equivalence_map.csv",
        "xc_distinct_distance_labels.csv",
        "xc_unresolved_labels.csv",
        "xc_canonical_distance_summary.csv",
        "hard_checks.csv",
    ]:
        print(f"  {output_dir / filename}")

    if failed:
        print()
        print("PHASE GATE: FAIL")
        for check in failed:
            print(
                f"  {check['check_name']}: "
                f"observed={check['observed']} "
                f"expected={check['expected']}"
            )
        return 1

    print()
    print("PHASE GATE: PASS")
    print("Stop here and inspect canonical distance coverage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
