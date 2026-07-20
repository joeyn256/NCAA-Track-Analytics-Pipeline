#!/usr/bin/env python3
"""
Milestone 5 Phase 1D — Apply Coach Event-Review Policy

Applies two reviewed policy decisions to the Phase 1C coach package:

1. Canonical track/field event groups with fewer than 100 total performances
   are excluded from the development model.
2. Metric hurdle names use compact formatting such as "400m Hurdles" and
   "110m Hurdles" rather than "400 m Hurdles".

The performance threshold is applied AFTER raw labels are grouped into their
suggested canonical event. This preserves low-frequency aliases when their
canonical group has sufficient total coverage.

This script creates a filtered manual-review package. It does not freeze the
final event registry.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MIN_CANONICAL_EVENT_PERFORMANCES = 5000
POLICY_VERSION = "event_review_policy_v2"

GROUP_INPUT = Path(
    "data/processed/milestone5/event_registry_v1/"
    "coach_review_v1/track_event_group_summary.csv"
)
LABEL_INPUT = Path(
    "data/processed/milestone5/event_registry_v1/"
    "coach_review_v1/track_event_manual_review.csv"
)
OUTPUT_DIR = Path(
    "data/processed/milestone5/event_registry_v1/"
    "policy_review_v2"
)


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


def compact_hurdle_name(
    code: str,
    current_name: str,
    family: str,
) -> str:
    """
    Standardize hurdle display names.

    Examples:
      400H  -> 400m Hurdles
      110H  -> 110m Hurdles
      60H   -> 60m Hurdles
      60YH  -> 60y Hurdles
    """
    if family != "hurdles":
        return current_name

    metric_match = re.fullmatch(r"(\d+)H", code or "")
    if metric_match:
        return f"{metric_match.group(1)}m Hurdles"

    yard_match = re.fullmatch(r"(\d+)YH", code or "")
    if yard_match:
        return f"{yard_match.group(1)}y Hurdles"

    # Fallback: remove whitespace before m/y in existing hurdle names.
    return re.sub(
        r"(\d+)\s+([my])\s+Hurdles",
        r"\1\2 Hurdles",
        current_name or "",
        flags=re.IGNORECASE,
    )


def group_key_for_label(row: dict[str, str]) -> str:
    code = (row.get("suggested_canonical_event_code") or "").strip()
    if code:
        return code
    return f"UNRESOLVED::{row.get('raw_event_label', '')}"


def main() -> int:
    root = Path.cwd()
    group_path = root / GROUP_INPUT
    label_path = root / LABEL_INPUT
    output_dir = root / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 1D — APPLY COACH EVENT-REVIEW POLICY")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Minimum canonical-event performances: {MIN_CANONICAL_EVENT_PERFORMANCES}")
    print(f"Group input: {group_path}")
    print(f"Label input: {label_path}")
    print(f"Output: {output_dir}")

    add_check(
        checks,
        "group_input_exists",
        group_path.exists(),
        group_path.exists(),
        True,
        str(group_path),
    )
    add_check(
        checks,
        "label_input_exists",
        label_path.exists(),
        label_path.exists(),
        True,
        str(label_path),
    )

    if not group_path.exists() or not label_path.exists():
        write_csv(
            output_dir / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Missing Phase 1C coach-review inputs.")
        return 1

    group_hash_before = sha256_file(group_path)
    label_hash_before = sha256_file(label_path)

    with group_path.open(newline="", encoding="utf-8") as handle:
        group_rows = list(csv.DictReader(handle))

    with label_path.open(newline="", encoding="utf-8") as handle:
        label_rows = list(csv.DictReader(handle))

    eligible_groups: list[dict[str, Any]] = []
    excluded_groups: list[dict[str, Any]] = []
    group_policy: dict[str, dict[str, Any]] = {}

    for source_row in group_rows:
        row = dict(source_row)
        count = parse_int(row.get("performance_count"))
        code = (row.get("suggested_canonical_event_code") or "").strip()
        family = (row.get("suggested_event_family") or "").strip()
        original_name = (
            row.get("suggested_canonical_event_name") or ""
        ).strip()
        policy_name = compact_hurdle_name(code, original_name, family)

        row.update(
            {
                "policy_version": POLICY_VERSION,
                "minimum_required_performances": (
                    MIN_CANONICAL_EVENT_PERFORMANCES
                ),
                "policy_canonical_event_code": code,
                "policy_canonical_event_name": policy_name,
                "policy_event_family": family,
                "policy_event_subfamily": (
                    row.get("suggested_event_subfamily") or ""
                ),
                "policy_performance_count": count,
                "policy_eligible": (
                    "true"
                    if count >= MIN_CANONICAL_EVENT_PERFORMANCES
                    else "false"
                ),
                "policy_registry_disposition": (
                    "coach_review"
                    if count >= MIN_CANONICAL_EVENT_PERFORMANCES
                    else "exclude_low_sample"
                ),
                "policy_exclusion_reason": (
                    ""
                    if count >= MIN_CANONICAL_EVENT_PERFORMANCES
                    else (
                        "canonical_event_group_has_fewer_than_"
                        f"{MIN_CANONICAL_EVENT_PERFORMANCES}_performances"
                    )
                ),
                "coach_decision": "",
                "coach_final_canonical_event_code": "",
                "coach_final_canonical_event_name": "",
                "coach_final_event_family": "",
                "coach_final_event_subfamily": "",
                "coach_final_registry_disposition": "",
                "coach_final_development_model_eligible": "",
                "coach_merge_target_event_code": "",
                "coach_notes": "",
            }
        )

        group_key = row["group_key"]
        group_policy[group_key] = row

        if count >= MIN_CANONICAL_EVENT_PERFORMANCES:
            eligible_groups.append(row)
        else:
            excluded_groups.append(row)

    eligible_labels: list[dict[str, Any]] = []
    excluded_labels: list[dict[str, Any]] = []
    missing_group_labels: list[dict[str, Any]] = []

    for source_row in label_rows:
        row = dict(source_row)
        key = group_key_for_label(row)
        policy = group_policy.get(key)

        if policy is None:
            row.update(
                {
                    "policy_version": POLICY_VERSION,
                    "policy_group_key": key,
                    "policy_eligible": "false",
                    "policy_registry_disposition": "error_missing_group",
                    "policy_exclusion_reason": (
                        "label_did_not_match_group_summary"
                    ),
                    "policy_canonical_event_code": "",
                    "policy_canonical_event_name": "",
                    "policy_group_performance_count": "",
                }
            )
            missing_group_labels.append(row)
            continue

        row.update(
            {
                "policy_version": POLICY_VERSION,
                "policy_group_key": key,
                "policy_eligible": policy["policy_eligible"],
                "policy_registry_disposition": (
                    policy["policy_registry_disposition"]
                ),
                "policy_exclusion_reason": (
                    policy["policy_exclusion_reason"]
                ),
                "policy_canonical_event_code": (
                    policy["policy_canonical_event_code"]
                ),
                "policy_canonical_event_name": (
                    policy["policy_canonical_event_name"]
                ),
                "policy_group_performance_count": (
                    policy["policy_performance_count"]
                ),
            }
        )

        if policy["policy_eligible"] == "true":
            eligible_labels.append(row)
        else:
            excluded_labels.append(row)

    eligible_groups.sort(
        key=lambda row: (
            -parse_int(row["policy_performance_count"]),
            row["policy_canonical_event_code"],
        )
    )
    excluded_groups.sort(
        key=lambda row: (
            -parse_int(row["policy_performance_count"]),
            row["group_key"],
        )
    )
    eligible_labels.sort(
        key=lambda row: (
            -parse_int(row["policy_group_performance_count"]),
            row["policy_canonical_event_code"],
            row["raw_event_label"],
        )
    )
    excluded_labels.sort(
        key=lambda row: (
            -parse_int(row["policy_group_performance_count"]),
            row["raw_event_label"],
        )
    )

    group_fields = [
        "policy_version",
        "group_key",
        "raw_label_count",
        "raw_labels",
        "performance_count",
        "athlete_count_sum_not_distinct",
        "suggestion_rules",
        "minimum_required_performances",
        "policy_canonical_event_code",
        "policy_canonical_event_name",
        "policy_event_family",
        "policy_event_subfamily",
        "policy_performance_count",
        "policy_eligible",
        "policy_registry_disposition",
        "policy_exclusion_reason",
        "coach_decision",
        "coach_final_canonical_event_code",
        "coach_final_canonical_event_name",
        "coach_final_event_family",
        "coach_final_event_subfamily",
        "coach_final_registry_disposition",
        "coach_final_development_model_eligible",
        "coach_merge_target_event_code",
        "coach_notes",
    ]

    label_fields = list(label_rows[0].keys()) + [
        "policy_version",
        "policy_group_key",
        "policy_eligible",
        "policy_registry_disposition",
        "policy_exclusion_reason",
        "policy_canonical_event_code",
        "policy_canonical_event_name",
        "policy_group_performance_count",
    ]

    write_csv(
        output_dir / "track_event_groups_for_coach_review.csv",
        eligible_groups,
        group_fields,
    )
    write_csv(
        output_dir / "track_event_groups_excluded_low_sample.csv",
        excluded_groups,
        group_fields,
    )
    write_csv(
        output_dir / "track_event_labels_for_coach_review.csv",
        eligible_labels,
        label_fields,
    )
    write_csv(
        output_dir / "track_event_labels_excluded_low_sample.csv",
        excluded_labels,
        label_fields,
    )
    write_csv(
        output_dir / "labels_missing_group.csv",
        missing_group_labels,
        label_fields,
    )

    compact_hurdle_failures = [
        row
        for row in eligible_groups + excluded_groups
        if row["policy_event_family"] == "hurdles"
        and re.search(
            r"\d+\s+[my]\s+Hurdles",
            row["policy_canonical_event_name"],
            flags=re.IGNORECASE,
        )
    ]

    below_threshold_eligible = [
        row
        for row in eligible_groups
        if parse_int(row["policy_performance_count"])
        < MIN_CANONICAL_EVENT_PERFORMANCES
    ]
    above_threshold_excluded = [
        row
        for row in excluded_groups
        if parse_int(row["policy_performance_count"])
        >= MIN_CANONICAL_EVENT_PERFORMANCES
    ]

    add_check(
        checks,
        "all_groups_partitioned",
        len(eligible_groups) + len(excluded_groups) == len(group_rows),
        len(eligible_groups) + len(excluded_groups),
        len(group_rows),
    )
    add_check(
        checks,
        "all_labels_partitioned",
        (
            len(eligible_labels)
            + len(excluded_labels)
            + len(missing_group_labels)
            == len(label_rows)
        ),
        (
            len(eligible_labels)
            + len(excluded_labels)
            + len(missing_group_labels)
        ),
        len(label_rows),
    )
    add_check(
        checks,
        "no_labels_missing_group",
        len(missing_group_labels) == 0,
        len(missing_group_labels),
        0,
    )
    add_check(
        checks,
        "eligible_groups_meet_threshold",
        len(below_threshold_eligible) == 0,
        len(below_threshold_eligible),
        0,
    )
    add_check(
        checks,
        "excluded_groups_are_below_threshold",
        len(above_threshold_excluded) == 0,
        len(above_threshold_excluded),
        0,
    )
    add_check(
        checks,
        "hurdle_names_use_compact_metric_format",
        len(compact_hurdle_failures) == 0,
        len(compact_hurdle_failures),
        0,
        "Expected names such as 400m Hurdles and 110m Hurdles.",
    )

    group_hash_after = sha256_file(group_path)
    label_hash_after = sha256_file(label_path)

    add_check(
        checks,
        "group_input_unchanged",
        group_hash_after == group_hash_before,
        group_hash_after,
        group_hash_before,
    )
    add_check(
        checks,
        "label_input_unchanged",
        label_hash_after == label_hash_before,
        label_hash_after,
        label_hash_before,
    )

    write_csv(
        output_dir / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    family_counts = Counter(
        row["policy_event_family"]
        for row in eligible_groups
    )
    excluded_performances = sum(
        parse_int(row["policy_performance_count"])
        for row in excluded_groups
    )
    eligible_performances = sum(
        parse_int(row["policy_performance_count"])
        for row in eligible_groups
    )

    summary_rows: list[dict[str, Any]] = [
        {
            "metric": "minimum_canonical_event_performances",
            "value": MIN_CANONICAL_EVENT_PERFORMANCES,
        },
        {
            "metric": "eligible_canonical_event_groups",
            "value": len(eligible_groups),
        },
        {
            "metric": "excluded_low_sample_event_groups",
            "value": len(excluded_groups),
        },
        {
            "metric": "eligible_raw_event_labels",
            "value": len(eligible_labels),
        },
        {
            "metric": "excluded_low_sample_raw_event_labels",
            "value": len(excluded_labels),
        },
        {
            "metric": "eligible_group_performance_count_sum",
            "value": eligible_performances,
        },
        {
            "metric": "excluded_group_performance_count_sum",
            "value": excluded_performances,
        },
    ]
    for family, count in sorted(family_counts.items()):
        summary_rows.append(
            {
                "metric": f"eligible_family:{family}",
                "value": count,
            }
        )

    write_csv(
        output_dir / "policy_summary.csv",
        summary_rows,
        ["metric", "value"],
    )

    failed = [
        check for check in checks
        if check["status"] == "FAIL"
    ]

    report_lines = [
        "MILESTONE 5 PHASE 1D — COACH EVENT-REVIEW POLICY",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Policy version: {POLICY_VERSION}",
        "",
        "POLICY DECISIONS",
        "-" * 78,
        (
            "Minimum canonical event group count: "
            f"{MIN_CANONICAL_EVENT_PERFORMANCES:,}"
        ),
        (
            "Threshold timing: after alias grouping, before final registry "
            "freeze"
        ),
        (
            "Hurdle naming: compact unit format, e.g. 400m Hurdles and "
            "110m Hurdles"
        ),
        "",
        "RESULTS",
        "-" * 78,
        f"Eligible canonical event groups: {len(eligible_groups):,}",
        f"Excluded low-sample event groups: {len(excluded_groups):,}",
        f"Eligible raw labels: {len(eligible_labels):,}",
        f"Excluded low-sample raw labels: {len(excluded_labels):,}",
        (
            "Eligible group performance-count sum: "
            f"{eligible_performances:,}"
        ),
        (
            "Excluded group performance-count sum: "
            f"{excluded_performances:,}"
        ),
        "",
        "IMPORTANT",
        "-" * 78,
        (
            "A raw alias with fewer than 100 rows remains eligible when its "
            "canonical group has at least 100 rows."
        ),
        (
            "Example: the 1000m alias can remain attached to the larger "
            "1000M canonical group."
        ),
        (
            "The eligible group file remains a coach-review file; it is not "
            "the frozen final registry."
        ),
        "",
        "HARD CHECK SUMMARY",
        "-" * 78,
        f"PASS: {sum(c['status'] == 'PASS' for c in checks)}",
        f"FAIL: {len(failed)}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Policy-filtered coach review is ready."
            if not failed
            else "FAIL — Correct policy application errors."
        ),
    ]

    (output_dir / "policy_report.txt").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Eligible canonical event groups: {len(eligible_groups):,}")
    print(f"Excluded low-sample event groups: {len(excluded_groups):,}")
    print(f"Eligible raw labels: {len(eligible_labels):,}")
    print(f"Excluded low-sample raw labels: {len(excluded_labels):,}")
    print()
    print("Created:")
    for filename in [
        "policy_report.txt",
        "track_event_groups_for_coach_review.csv",
        "track_event_groups_excluded_low_sample.csv",
        "track_event_labels_for_coach_review.csv",
        "track_event_labels_excluded_low_sample.csv",
        "labels_missing_group.csv",
        "policy_summary.csv",
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
    print("Stop here for coach review; do not freeze the registry yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
