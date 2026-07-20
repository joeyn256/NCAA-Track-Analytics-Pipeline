#!/usr/bin/env python3
"""
Milestone 5 Phase 3D-S — Freeze Collegiate-Eligibility Anchor Metadata

Applies the explicit, version-controlled T&FN outside-season classification
to the five already-selected collegiate-eligibility anchors. This changes
metadata only; it does not change any selected record mark.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path.cwd()

INPUT_DIR = (
    ROOT
    / "data/reference/collegiate_records/v1/final_eligibility_v1"
)
INPUT_ANCHORS = INPUT_DIR / "active_collegiate_eligibility_anchors.csv"

OUTPUT_DIR = (
    ROOT
    / "data/reference/collegiate_records/v1/final_eligibility_v1_1"
)

REGISTRY_VERSION = "collegiate_eligibility_anchors_v1_1"
POLICY_VERSION = (
    "tfn_regular_plus_explicit_verified_postseason_pending_active_v1"
)

OUTSIDE_SEASON_OVERRIDES = {
    ("outdoor", "m", "800M"): {
        "mark": "1:41.77",
        "regular_mark": "1:43.25",
        "regular_holder": "Michael Saruni",
    },
    ("outdoor", "m", "1500M"): {
        "mark": "3:31.04",
        "regular_mark": "3:31.69",
        "regular_holder": "Simeon Birnbaum",
    },
    ("outdoor", "m", "HT"): {
        "mark": "82.56",
        "regular_mark": "81.94",
        "regular_holder": "Balázs Kiss",
    },
    ("outdoor", "f", "HJ"): {
        "mark": "2.03",
        "regular_mark": "2.00",
        "regular_holder": "Lamara Distin",
    },
    ("outdoor", "f", "HEP"): {
        "mark": "6755",
        "regular_mark": "6527",
        "regular_holder": "Diane Guthrie-Gresham",
    },
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


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
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


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 3D-S — FREEZE ELIGIBILITY ANCHOR METADATA")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Input: {INPUT_ANCHORS}")
    print(f"Output: {OUTPUT_DIR}")

    add_check(
        checks,
        "input_anchor_registry_exists",
        INPUT_ANCHORS.exists(),
        INPUT_ANCHORS.exists(),
        True,
    )

    if not INPUT_ANCHORS.exists():
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Input registry missing.")
        return 1

    input_hash_before = sha256_file(INPUT_ANCHORS)

    with INPUT_ANCHORS.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    fields = list(rows[0].keys())
    corrected: list[dict[str, Any]] = []
    outside_rows: list[dict[str, Any]] = []

    observed_override_keys: set[tuple[str, str, str]] = set()

    for source_row in rows:
        row = dict(source_row)
        key = (
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
        )

        row["registry_version"] = REGISTRY_VERSION
        row["policy_version"] = POLICY_VERSION

        override = OUTSIDE_SEASON_OVERRIDES.get(key)
        if override is not None:
            observed_override_keys.add(key)

            if row["record_mark_raw"] == override["mark"]:
                row["outside_regular_collegiate_season"] = "True"
                row["tfn_eligibility_verified"] = "True"
                row["anchor_status"] = (
                    "verified_outside_season_active_anchor"
                )
                row["performance_context"] = (
                    "outside_regular_season_tfn_eligibility_verified"
                )
                row["selection_policy"] = (
                    "best T&FN-listed collegiate-eligible mark; "
                    "explicit verified outside-season and pending marks allowed"
                )

                outside_rows.append(
                    {
                        **row,
                        "superseded_regular_season_mark": override[
                            "regular_mark"
                        ],
                        "superseded_regular_season_holder": override[
                            "regular_holder"
                        ],
                    }
                )

        corrected.append(row)

    corrected_by_key = {
        (
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
        ): row
        for row in corrected
    }

    add_check(
        checks,
        "anchor_row_count",
        len(corrected) == 82,
        len(corrected),
        82,
    )
    add_check(
        checks,
        "anchor_keys_unique",
        len(corrected_by_key) == len(corrected),
        len(corrected) - len(corrected_by_key),
        0,
    )
    add_check(
        checks,
        "all_override_keys_present",
        observed_override_keys == set(OUTSIDE_SEASON_OVERRIDES),
        sorted(observed_override_keys),
        sorted(OUTSIDE_SEASON_OVERRIDES),
    )
    add_check(
        checks,
        "outside_season_anchor_count",
        len(outside_rows) == 5,
        len(outside_rows),
        5,
    )
    add_check(
        checks,
        "pending_anchor_count",
        sum(
            bool_value(row["pending_ratification"])
            for row in corrected
        ) == 8,
        sum(
            bool_value(row["pending_ratification"])
            for row in corrected
        ),
        8,
    )
    add_check(
        checks,
        "unsupported_55m_events_absent",
        not any(
            row["canonical_event_code"] in {"55M", "55H"}
            for row in corrected
        ),
        sum(
            row["canonical_event_code"] in {"55M", "55H"}
            for row in corrected
        ),
        0,
    )
    add_check(
        checks,
        "high_jump_marks_realistic",
        all(
            1.50 <= float(row["record_mark_normalized"]) <= 2.60
            for row in corrected
            if row["canonical_event_code"] == "HJ"
        ),
        [
            row["record_mark_raw"]
            for row in corrected
            if row["canonical_event_code"] == "HJ"
        ],
        "all between 1.50 and 2.60 meters",
    )

    for key, override in OUTSIDE_SEASON_OVERRIDES.items():
        row = corrected_by_key.get(key)
        observed = (
            (
                f"{row['record_mark_raw']}|"
                f"{row['outside_regular_collegiate_season']}|"
                f"{row['tfn_eligibility_verified']}"
            )
            if row else "missing"
        )
        expected = f"{override['mark']}|True|True"

        add_check(
            checks,
            "override_" + "_".join(key),
            bool(
                row
                and row["record_mark_raw"] == override["mark"]
                and bool_value(
                    row["outside_regular_collegiate_season"]
                )
                and bool_value(row["tfn_eligibility_verified"])
            ),
            observed,
            expected,
        )

    input_hash_after = sha256_file(INPUT_ANCHORS)
    add_check(
        checks,
        "input_registry_unchanged",
        input_hash_before == input_hash_after,
        input_hash_after,
        input_hash_before,
    )

    write_csv(
        OUTPUT_DIR / "active_collegiate_eligibility_anchors.csv",
        corrected,
        fields,
    )

    write_csv(
        OUTPUT_DIR / "outside_season_promoted_to_active.csv",
        outside_rows,
        fields
        + [
            "superseded_regular_season_mark",
            "superseded_regular_season_holder",
        ],
    )

    pending_rows = [
        row
        for row in corrected
        if bool_value(row["pending_ratification"])
    ]
    write_csv(
        OUTPUT_DIR / "pending_active_anchors.csv",
        pending_rows,
        fields,
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    write_csv(
        OUTPUT_DIR / "input_manifest.csv",
        [
            {
                "input_name": "phase_3d_r_anchor_registry",
                "path": str(INPUT_ANCHORS),
                "sha256_before": input_hash_before,
                "sha256_after": input_hash_after,
            }
        ],
        [
            "input_name",
            "path",
            "sha256_before",
            "sha256_after",
        ],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 5 PHASE 3D-S — ELIGIBILITY ANCHOR METADATA",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Registry version: {REGISTRY_VERSION}",
        f"Policy version: {POLICY_VERSION}",
        "",
        "RESULTS",
        "-" * 78,
        f"Active anchors: {len(corrected):,}",
        f"Pending active anchors: {len(pending_rows):,}",
        f"Explicit verified outside-season anchors: {len(outside_rows):,}",
        "",
        "POLICY",
        "-" * 78,
        "Selected marks were not changed.",
        "Five T&FN eligibility-screened outside-season marks were tagged.",
        "Ordinary performance attribution still requires school-stint checks.",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Authoritative anchor registry frozen."
            if not failed
            else "FAIL — Do not use this registry."
        ),
    ]

    (OUTPUT_DIR / "eligibility_anchor_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Active anchors: {len(corrected):,}")
    print(f"Pending active anchors: {len(pending_rows):,}")
    print(f"Outside-season anchors tagged: {len(outside_rows):,}")
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
    print("Next: profile the scoring cohort and participation reach.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
