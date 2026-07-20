#!/usr/bin/env python3
"""
Milestone 5 Phase 3B — Refine Track Record Anchor Scope

Classifies every event × gender × season requirement before record sourcing.

Policy:
- primary_scoring_anchor:
    season-compatible and at least 5,000 scoring performances;
- exploratory_low_sample:
    season-compatible but fewer than 5,000 performances;
- exclude_season_mismatch:
    event is not appropriate for that track season;
- exclude_wrong_gender_event:
    hurdle or combined-event code conflicts with gender.

No performance data is deleted. This controls only which combinations enter
the first production ranking formula.
"""

from __future__ import annotations

import csv
import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCOPE_VERSION = "record_anchor_scope_v1"
MIN_COMBINATION_PERFORMANCES = 5_000

INPUT_CSV = Path(
    "data/processed/milestone5/"
    "collegiate_record_anchors_v1/requirements_v1/"
    "record_anchor_requirements.csv"
)
OUTPUT_DIR = Path(
    "data/processed/milestone5/"
    "collegiate_record_anchors_v1/scope_v1"
)

INDOOR_COMPATIBLE = {
    "55M", "55H", "60M", "60H",
    "200M", "300M", "400M", "500M", "600M",
    "800M", "1000M", "MILE", "3000M", "5000M",
    "HJ", "PV", "LJ", "TJ", "SP", "WT",
    "PENT", "HEP",
}

OUTDOOR_COMPATIBLE = {
    "100M", "100H", "110H", "200M", "300M",
    "400M", "400H", "800M", "1000M", "1500M",
    "MILE", "3000M", "3000SC", "5000M", "10000M",
    "HJ", "PV", "LJ", "TJ", "SP", "DT", "HT", "JT",
    "HEP", "DEC",
}

FEMALE_ONLY = {"100H", "PENT", "HEP"}
MALE_ONLY = {"110H", "DEC"}

# Some combined events are season-specific by gender.
# Women's indoor pentathlon and outdoor heptathlon are standard.
# Men's indoor heptathlon and outdoor decathlon are standard.
VALID_COMBINED = {
    ("indoor", "f", "PENT"),
    ("indoor", "m", "HEP"),
    ("outdoor", "f", "HEP"),
    ("outdoor", "m", "DEC"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, block_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(block_size):
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


def classification(
    season_type: str,
    gender: str,
    event_code: str,
    performance_count: int,
) -> tuple[str, str]:
    if event_code in {"PENT", "HEP", "DEC"}:
        if (season_type, gender, event_code) not in VALID_COMBINED:
            return (
                "exclude_wrong_gender_or_season_combined_event",
                "combined_event_not_standard_for_gender_and_season",
            )

    if event_code in FEMALE_ONLY and gender != "f":
        return (
            "exclude_wrong_gender_event",
            "event_code_is_female_specific",
        )

    if event_code in MALE_ONLY and gender != "m":
        return (
            "exclude_wrong_gender_event",
            "event_code_is_male_specific",
        )

    compatible = (
        event_code in INDOOR_COMPATIBLE
        if season_type == "indoor"
        else event_code in OUTDOOR_COMPATIBLE
        if season_type == "outdoor"
        else False
    )

    if not compatible:
        return (
            "exclude_season_mismatch",
            "event_code_not_compatible_with_season",
        )

    if performance_count < MIN_COMBINATION_PERFORMANCES:
        return (
            "exploratory_low_sample",
            "season_compatible_but_below_5000_performances",
        )

    return (
        "primary_scoring_anchor",
        "season_compatible_and_meets_5000_performance_threshold",
    )


def preferred_anchor_source(
    season_type: str,
    scope_status: str,
) -> str:
    if scope_status.startswith("exclude_"):
        return "not_required"
    if season_type == "indoor":
        return "tfn_indoor_collegiate_record"
    if season_type == "outdoor":
        return "tfn_absolute_collegiate_record"
    return "not_required"


def main() -> int:
    root = Path.cwd()
    input_path = root / INPUT_CSV
    output_dir = root / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 3B — REFINE RECORD ANCHOR SCOPE")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Scope version: {SCOPE_VERSION}")
    print(
        "Minimum primary combination performances: "
        f"{MIN_COMBINATION_PERFORMANCES:,}"
    )
    print(f"Input: {input_path}")
    print(f"Output: {output_dir}")

    exists = input_path.exists()
    add_check(
        checks,
        "record_anchor_requirements_exist",
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
        print("PHASE GATE: FAIL — Requirements CSV is missing.")
        return 1

    before_hash = sha256_file(input_path)
    before_stat = input_path.stat()

    with input_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    add_check(
        checks,
        "requirement_row_count",
        len(rows) == 126,
        len(rows),
        126,
    )

    output_rows: list[dict[str, Any]] = []

    for row in rows:
        count = int(row["performance_count"])
        status, reason = classification(
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
            count,
        )

        output_rows.append(
            {
                **row,
                "scope_version": SCOPE_VERSION,
                "minimum_combination_performances": (
                    MIN_COMBINATION_PERFORMANCES
                ),
                "anchor_scope_status": status,
                "anchor_scope_reason": reason,
                "production_scoring_eligible": (
                    status == "primary_scoring_anchor"
                ),
                "record_entry_required": (
                    status in {
                        "primary_scoring_anchor",
                        "exploratory_low_sample",
                    }
                ),
                "refined_preferred_source_family": (
                    preferred_anchor_source(
                        row["season_type"],
                        status,
                    )
                ),
            }
        )

    output_rows.sort(
        key=lambda row: (
            row["anchor_scope_status"],
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
        )
    )

    status_counts = Counter(
        row["anchor_scope_status"]
        for row in output_rows
    )
    status_performances = Counter()
    for row in output_rows:
        status_performances[row["anchor_scope_status"]] += int(
            row["performance_count"]
        )

    primary_rows = [
        row for row in output_rows
        if row["anchor_scope_status"] == "primary_scoring_anchor"
    ]
    exploratory_rows = [
        row for row in output_rows
        if row["anchor_scope_status"] == "exploratory_low_sample"
    ]
    excluded_rows = [
        row for row in output_rows
        if row["anchor_scope_status"].startswith("exclude_")
    ]

    primary_performances = sum(
        int(row["performance_count"]) for row in primary_rows
    )
    all_performances = sum(
        int(row["performance_count"]) for row in output_rows
    )
    primary_coverage = (
        primary_performances / all_performances
        if all_performances
        else 0.0
    )

    add_check(
        checks,
        "every_requirement_classified",
        all(row["anchor_scope_status"] for row in output_rows),
        sum(not row["anchor_scope_status"] for row in output_rows),
        0,
    )
    add_check(
        checks,
        "primary_anchor_requirements_exist",
        len(primary_rows) > 0,
        len(primary_rows),
        "greater than 0",
    )
    add_check(
        checks,
        "primary_anchor_performance_coverage",
        primary_coverage >= 0.98,
        f"{primary_coverage:.6%}",
        "at least 98%",
        "Low-sample and anomalous combinations remain auditable.",
    )
    add_check(
        checks,
        "no_primary_combination_below_threshold",
        all(
            int(row["performance_count"])
            >= MIN_COMBINATION_PERFORMANCES
            for row in primary_rows
        ),
        sum(
            int(row["performance_count"])
            < MIN_COMBINATION_PERFORMANCES
            for row in primary_rows
        ),
        0,
    )
    add_check(
        checks,
        "no_excluded_combination_requests_record",
        all(
            row["record_entry_required"] is False
            for row in excluded_rows
        ),
        sum(
            row["record_entry_required"] is not False
            for row in excluded_rows
        ),
        0,
    )

    fields = list(output_rows[0].keys())
    write_csv(
        output_dir / "record_anchor_scope.csv",
        output_rows,
        fields,
    )
    write_csv(
        output_dir / "primary_record_anchor_requirements.csv",
        primary_rows,
        fields,
    )
    write_csv(
        output_dir / "exploratory_record_anchor_requirements.csv",
        exploratory_rows,
        fields,
    )
    write_csv(
        output_dir / "excluded_record_anchor_combinations.csv",
        excluded_rows,
        fields,
    )

    summary_rows = []
    for status in sorted(status_counts):
        summary_rows.append(
            {
                "anchor_scope_status": status,
                "requirement_count": status_counts[status],
                "performance_count": status_performances[status],
                "performance_share": (
                    status_performances[status] / all_performances
                    if all_performances
                    else 0.0
                ),
            }
        )

    write_csv(
        output_dir / "anchor_scope_summary.csv",
        summary_rows,
        [
            "anchor_scope_status",
            "requirement_count",
            "performance_count",
            "performance_share",
        ],
    )

    after_hash = sha256_file(input_path)
    after_stat = input_path.stat()
    unchanged = (
        before_hash == after_hash
        and before_stat.st_size == after_stat.st_size
        and before_stat.st_mtime_ns == after_stat.st_mtime_ns
    )
    add_check(
        checks,
        "requirements_input_unchanged",
        unchanged,
        after_hash,
        before_hash,
    )

    write_csv(
        output_dir / "input_manifest.csv",
        [
            {
                "stage": "before",
                "path": str(input_path),
                "size_bytes": before_stat.st_size,
                "mtime_epoch_ns": before_stat.st_mtime_ns,
                "sha256": before_hash,
            },
            {
                "stage": "after",
                "path": str(input_path),
                "size_bytes": after_stat.st_size,
                "mtime_epoch_ns": after_stat.st_mtime_ns,
                "sha256": after_hash,
            },
        ],
        [
            "stage",
            "path",
            "size_bytes",
            "mtime_epoch_ns",
            "sha256",
        ],
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

    report_lines = [
        "MILESTONE 5 PHASE 3B — RECORD ANCHOR SCOPE",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Scope version: {SCOPE_VERSION}",
        "",
        "POLICY",
        "-" * 78,
        (
            "Primary production combinations require season compatibility "
            f"and at least {MIN_COMBINATION_PERFORMANCES:,} performances."
        ),
        "Low-sample compatible combinations remain exploratory.",
        "Season mismatches and wrong-gender event codes are excluded.",
        "No underlying performance is deleted.",
        "",
        "SCOPE RESULTS",
        "-" * 78,
        f"All requirements: {len(output_rows):,}",
        f"Primary scoring anchors: {len(primary_rows):,}",
        f"Exploratory low-sample anchors: {len(exploratory_rows):,}",
        f"Excluded combinations: {len(excluded_rows):,}",
        f"Primary scoring performances: {primary_performances:,}",
        f"All requirement performances: {all_performances:,}",
        f"Primary performance coverage: {primary_coverage:.6%}",
        "",
        "HARD CHECK SUMMARY",
        "-" * 78,
        f"PASS: {sum(c['status'] == 'PASS' for c in checks)}",
        f"FAIL: {len(failed)}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Production record-anchor scope is ready for sourcing."
            if not failed
            else "FAIL — Correct event-season scope classification."
        ),
    ]
    (output_dir / "record_anchor_scope_report.txt").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Primary scoring anchors: {len(primary_rows):,}")
    print(f"Exploratory low-sample anchors: {len(exploratory_rows):,}")
    print(f"Excluded combinations: {len(excluded_rows):,}")
    print(f"Primary performance coverage: {primary_coverage:.6%}")
    print()
    print("Created:")
    for filename in [
        "record_anchor_scope_report.txt",
        "record_anchor_scope.csv",
        "primary_record_anchor_requirements.csv",
        "exploratory_record_anchor_requirements.csv",
        "excluded_record_anchor_combinations.csv",
        "anchor_scope_summary.csv",
        "input_manifest.csv",
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
    print("Next: source records for the refined production combinations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
