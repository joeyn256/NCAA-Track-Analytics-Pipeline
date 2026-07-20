#!/usr/bin/env python3
"""
Milestone 5 Phase 4D — Freeze Performance-Level Scoring Policy

Freezes the primary normalized performance-level transformation after the
Phase 4B calibration and Phase 4C exceedance audit.

Selected transformation
-----------------------
Lower-is-better:
    ratio = anchor_value / performance_value

Higher-is-better:
    ratio = performance_value / anchor_value

Primary score:
    performance_level = 100 * min(1, max(0, ratio)) ** 2

Exceedance treatment
--------------------
- rounding/precision tolerance rows remain eligible and are capped at 100;
- all other unresolved exceedances are excluded from primary scoring;
- raw source rows remain preserved;
- a later authoritative record update requires a versioned anchor refresh
  and complete recomputation.

This phase freezes policy only. It does not materialize scores for all
4.66 million official-event performances.
"""

from __future__ import annotations

import csv
import hashlib
import math
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

PHASE_4C_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4c_anchor_exceedance_audit"
)

GLOBAL_PROFILES = (
    PHASE_4B_DIR / "candidate_exponent_global_profiles.csv"
)
EVENT_CONSISTENCY = (
    PHASE_4B_DIR / "candidate_exponent_event_consistency.csv"
)
DESIGN_EXAMPLES = PHASE_4B_DIR / "design_examples.csv"
ANCHOR_JOIN_COVERAGE = PHASE_4B_DIR / "anchor_join_coverage.csv"

EXCEEDANCE_AUDIT = (
    PHASE_4C_DIR / "anchor_exceedance_audit.csv"
)
PHASE_4C_CHECKS = PHASE_4C_DIR / "hard_checks.csv"

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4d_frozen_performance_level_policy"
)

POLICY_VERSION = "performance_level_policy_v1"
SELECTED_EXPONENT = 2.0

EXPECTED_OFFICIAL_PERFORMANCES = 4_664_090
EXPECTED_OFFICIAL_EVENT_COMBINATIONS = 82
EXPECTED_EXCEEDANCE_ROWS = 51
EXPECTED_QUARANTINED_ROWS = 49
EXPECTED_TOLERANCE_ROWS = 2
EXPECTED_CRITICAL_ROWS = 11
EXPECTED_WIND_REVIEW_ROWS = 19

EXPECTED_SELECTED_METRICS = {
    "score_q25": 55.46,
    "score_q50": 68.15,
    "score_q75": 76.63,
    "score_q90": 82.46,
    "score_q95": 85.48,
    "score_q99": 90.48,
    "score_mean": 64.23,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def close_enough(
    observed: float,
    expected: float,
    tolerance: float = 0.02,
) -> bool:
    return abs(observed - expected) <= tolerance


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    required_inputs = [
        GLOBAL_PROFILES,
        EVENT_CONSISTENCY,
        DESIGN_EXAMPLES,
        ANCHOR_JOIN_COVERAGE,
        EXCEEDANCE_AUDIT,
        PHASE_4C_CHECKS,
    ]

    print("MILESTONE 5 PHASE 4D — FREEZE PERFORMANCE-LEVEL POLICY")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Policy version: {POLICY_VERSION}")
    print(f"Selected exponent: {SELECTED_EXPONENT}")
    print(f"Output: {OUTPUT_DIR}")

    missing_inputs = [
        str(path) for path in required_inputs if not path.exists()
    ]

    add_check(
        checks,
        "all_required_inputs_exist",
        not missing_inputs,
        missing_inputs,
        [],
    )

    if missing_inputs:
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Required input missing.")
        return 1

    hashes_before = {
        str(path): sha256_file(path)
        for path in required_inputs
    }

    global_profiles = read_csv(GLOBAL_PROFILES)
    consistency_rows = read_csv(EVENT_CONSISTENCY)
    design_rows = read_csv(DESIGN_EXAMPLES)
    coverage_rows = read_csv(ANCHOR_JOIN_COVERAGE)
    audit_rows = read_csv(EXCEEDANCE_AUDIT)
    phase_4c_checks = read_csv(PHASE_4C_CHECKS)

    failed_phase_4c_checks = [
        row
        for row in phase_4c_checks
        if row.get("status") != "PASS"
    ]

    add_check(
        checks,
        "phase_4c_gate_passed",
        not failed_phase_4c_checks,
        [row.get("check_name") for row in failed_phase_4c_checks],
        [],
    )

    selected_global_matches = [
        row
        for row in global_profiles
        if as_float(row, "exponent") == SELECTED_EXPONENT
    ]
    selected_consistency_matches = [
        row
        for row in consistency_rows
        if as_float(row, "exponent") == SELECTED_EXPONENT
    ]

    add_check(
        checks,
        "selected_global_profile_unique",
        len(selected_global_matches) == 1,
        len(selected_global_matches),
        1,
    )
    add_check(
        checks,
        "selected_consistency_profile_unique",
        len(selected_consistency_matches) == 1,
        len(selected_consistency_matches),
        1,
    )

    if (
        len(selected_global_matches) != 1
        or len(selected_consistency_matches) != 1
    ):
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Selected exponent profile unresolved.")
        return 1

    selected_global = selected_global_matches[0]
    selected_consistency = selected_consistency_matches[0]

    for field, expected in EXPECTED_SELECTED_METRICS.items():
        observed = as_float(selected_global, field)
        add_check(
            checks,
            f"selected_{field}_matches_calibration",
            close_enough(observed, expected),
            observed,
            f"approximately {expected}",
        )

    coverage_lookup = {
        row["metric"]: row["value"]
        for row in coverage_rows
    }

    official_performances = int(
        float(
            coverage_lookup[
                "official_event_performances_with_anchor"
            ]
        )
    )
    official_combinations = int(
        float(
            coverage_lookup[
                "official_anchor_combinations_joined"
            ]
        )
    )

    add_check(
        checks,
        "official_performance_count",
        official_performances == EXPECTED_OFFICIAL_PERFORMANCES,
        official_performances,
        EXPECTED_OFFICIAL_PERFORMANCES,
    )
    add_check(
        checks,
        "official_event_combination_count",
        official_combinations
        == EXPECTED_OFFICIAL_EVENT_COMBINATIONS,
        official_combinations,
        EXPECTED_OFFICIAL_EVENT_COMBINATIONS,
    )

    quarantined_rows = [
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
        row for row in audit_rows if row["severity"] == "critical"
    ]
    wind_review_rows = [
        row
        for row in audit_rows
        if row["wind_sensitive_event"] == "True"
        and row["scoring_action"]
        == "quarantine_from_primary_scoring"
    ]

    add_check(
        checks,
        "exceedance_row_count",
        len(audit_rows) == EXPECTED_EXCEEDANCE_ROWS,
        len(audit_rows),
        EXPECTED_EXCEEDANCE_ROWS,
    )
    add_check(
        checks,
        "quarantined_exceedance_count",
        len(quarantined_rows) == EXPECTED_QUARANTINED_ROWS,
        len(quarantined_rows),
        EXPECTED_QUARANTINED_ROWS,
    )
    add_check(
        checks,
        "rounding_tolerance_count",
        len(tolerance_rows) == EXPECTED_TOLERANCE_ROWS,
        len(tolerance_rows),
        EXPECTED_TOLERANCE_ROWS,
    )
    add_check(
        checks,
        "critical_anomaly_count",
        len(critical_rows) == EXPECTED_CRITICAL_ROWS,
        len(critical_rows),
        EXPECTED_CRITICAL_ROWS,
    )
    add_check(
        checks,
        "wind_review_count",
        len(wind_review_rows) == EXPECTED_WIND_REVIEW_ROWS,
        len(wind_review_rows),
        EXPECTED_WIND_REVIEW_ROWS,
    )
    add_check(
        checks,
        "every_exceedance_has_unique_audit_id",
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
        "all_quarantined_rows_excluded",
        all(
            row["scoring_action"]
            == "quarantine_from_primary_scoring"
            for row in quarantined_rows
        ),
        sum(
            row["scoring_action"]
            != "quarantine_from_primary_scoring"
            for row in quarantined_rows
        ),
        0,
    )
    add_check(
        checks,
        "all_tolerance_rows_cap_at_100",
        all(
            row["scoring_action"] == "eligible_capped_at_100"
            for row in tolerance_rows
        ),
        sum(
            row["scoring_action"] != "eligible_capped_at_100"
            for row in tolerance_rows
        ),
        0,
    )

    selected_examples = [
        row
        for row in design_rows
        if as_float(row, "exponent") == SELECTED_EXPONENT
    ]
    example_lookup = {
        (row["event_code"], row["scenario"]): as_float(
            row, "score_gain"
        )
        for row in selected_examples
    }

    dev_5k = example_lookup[
        ("5000M", "developmental_17:00_to_16:50")
    ]
    elite_5k = example_lookup[
        ("5000M", "elite_14:00_to_13:50")
    ]
    dev_lj = example_lookup[
        ("LJ", "developmental_7.00_to_7.10")
    ]
    elite_lj = example_lookup[
        ("LJ", "elite_8.00_to_8.10")
    ]

    add_check(
        checks,
        "selected_exponent_rewards_elite_5k_more",
        elite_5k > dev_5k,
        elite_5k / dev_5k,
        "greater than 1",
    )
    add_check(
        checks,
        "selected_exponent_rewards_elite_lj_more",
        elite_lj > dev_lj,
        elite_lj / dev_lj,
        "greater than 1",
    )

    override_rows = [
        {
            "audit_exceedance_id": row["audit_exceedance_id"],
            "source_performance_id": row.get(
                "source_performance_id", ""
            ),
            "season_type": row["season_type"],
            "canonical_gender_code": row[
                "canonical_gender_code"
            ],
            "canonical_event_code": row[
                "canonical_event_code"
            ],
            "canonical_person_id": row["canonical_person_id"],
            "athlete_name": row["athlete_name"],
            "performance_value": row["performance_value"],
            "raw_mark": row["raw_mark"],
            "raw_performance_ratio": row[
                "raw_performance_ratio"
            ],
            "primary_scoring_eligible": (
                "True"
                if row["scoring_action"]
                == "eligible_capped_at_100"
                else "False"
            ),
            "performance_level_override": (
                "100.0"
                if row["scoring_action"]
                == "eligible_capped_at_100"
                else ""
            ),
            "scoring_action": row["scoring_action"],
            "provisional_classification": row[
                "provisional_classification"
            ],
            "policy_version": POLICY_VERSION,
        }
        for row in audit_rows
    ]

    write_csv(
        OUTPUT_DIR / "exceedance_scoring_overrides.csv",
        override_rows,
        [
            "audit_exceedance_id",
            "source_performance_id",
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "canonical_person_id",
            "athlete_name",
            "performance_value",
            "raw_mark",
            "raw_performance_ratio",
            "primary_scoring_eligible",
            "performance_level_override",
            "scoring_action",
            "provisional_classification",
            "policy_version",
        ],
    )

    policy_rows = [
        {
            "policy_component": "policy_version",
            "value": POLICY_VERSION,
            "definition": "Frozen normalized performance-level policy",
        },
        {
            "policy_component": "selected_exponent",
            "value": SELECTED_EXPONENT,
            "definition": (
                "Balanced square-law frontier weighting selected "
                "after empirical calibration"
            ),
        },
        {
            "policy_component": "lower_is_better_ratio",
            "value": "anchor_value / performance_value",
            "definition": "Running and timed events",
        },
        {
            "policy_component": "higher_is_better_ratio",
            "value": "performance_value / anchor_value",
            "definition": "Field and combined events",
        },
        {
            "policy_component": "bounded_ratio",
            "value": "min(1, max(0, ratio))",
            "definition": "Primary scoring ratio",
        },
        {
            "policy_component": "performance_level",
            "value": "100 * bounded_ratio ** 2",
            "definition": "Frozen event-independent score",
        },
        {
            "policy_component": "rounding_exceedance",
            "value": "eligible; score overridden to 100",
            "definition": "Phase 4C precision-tolerance classification",
        },
        {
            "policy_component": "unresolved_exceedance",
            "value": "excluded from primary scoring",
            "definition": "Preserved in source and audit outputs",
        },
        {
            "policy_component": "verified_new_record",
            "value": (
                "refresh versioned anchor registry and recompute"
            ),
            "definition": "No silent record replacement",
        },
        {
            "policy_component": "development_definition",
            "value": "later_stable_level - earlier_stable_level",
            "definition": (
                "Deferred until stable athlete-period estimates are built"
            ),
        },
    ]

    write_csv(
        OUTPUT_DIR / "performance_level_policy.csv",
        policy_rows,
        ["policy_component", "value", "definition"],
    )

    metric_rows = [
        {
            "metric": "selected_exponent",
            "value": SELECTED_EXPONENT,
        },
        {
            "metric": "official_performance_count",
            "value": official_performances,
        },
        {
            "metric": "official_event_combination_count",
            "value": official_combinations,
        },
        {
            "metric": "score_q25",
            "value": selected_global["score_q25"],
        },
        {
            "metric": "score_median",
            "value": selected_global["score_q50"],
        },
        {
            "metric": "score_q75",
            "value": selected_global["score_q75"],
        },
        {
            "metric": "score_q90",
            "value": selected_global["score_q90"],
        },
        {
            "metric": "score_q95",
            "value": selected_global["score_q95"],
        },
        {
            "metric": "score_q99",
            "value": selected_global["score_q99"],
        },
        {
            "metric": "score_mean",
            "value": selected_global["score_mean"],
        },
        {
            "metric": "event_median_mean",
            "value": selected_consistency[
                "score_q50_event_mean"
            ],
        },
        {
            "metric": "event_median_sd",
            "value": selected_consistency[
                "score_q50_event_sd"
            ],
        },
        {
            "metric": "5k_elite_to_developmental_gain_ratio",
            "value": elite_5k / dev_5k,
        },
        {
            "metric": "long_jump_elite_to_developmental_gain_ratio",
            "value": elite_lj / dev_lj,
        },
        {
            "metric": "quarantined_exceedance_rows",
            "value": len(quarantined_rows),
        },
        {
            "metric": "rounding_tolerance_rows",
            "value": len(tolerance_rows),
        },
    ]

    write_csv(
        OUTPUT_DIR / "selected_exponent_metrics.csv",
        metric_rows,
        ["metric", "value"],
    )

    decision_rows = [
        {
            "candidate_exponent": row["exponent"],
            "selected": (
                "True"
                if as_float(row, "exponent") == SELECTED_EXPONENT
                else "False"
            ),
            "score_q50": row["score_q50"],
            "score_q90": row["score_q90"],
            "score_q99": row["score_q99"],
            "score_mean": row["score_mean"],
            "decision_note": (
                "Selected: interpretable square-law; meaningful "
                "frontier weighting without the stronger compression "
                "of p=2.5 or p=3.0."
                if as_float(row, "exponent") == SELECTED_EXPONENT
                else (
                    "Not selected: weaker frontier differentiation."
                    if as_float(row, "exponent") < SELECTED_EXPONENT
                    else (
                        "Not selected: stronger distribution compression "
                        "and event-level dispersion than necessary."
                    )
                )
            ),
        }
        for row in global_profiles
    ]

    write_csv(
        OUTPUT_DIR / "exponent_decision_table.csv",
        decision_rows,
        [
            "candidate_exponent",
            "selected",
            "score_q50",
            "score_q90",
            "score_q99",
            "score_mean",
            "decision_note",
        ],
    )

    hashes_after = {
        str(path): sha256_file(path)
        for path in required_inputs
    }

    add_check(
        checks,
        "all_inputs_unchanged",
        hashes_before == hashes_after,
        hashes_after,
        hashes_before,
    )

    write_csv(
        OUTPUT_DIR / "input_manifest.csv",
        [
            {
                "input_name": path.name,
                "path": str(path),
                "sha256_before": hashes_before[str(path)],
                "sha256_after": hashes_after[str(path)],
            }
            for path in required_inputs
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
        "MILESTONE 5 PHASE 4D — FROZEN PERFORMANCE-LEVEL POLICY",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Policy version: {POLICY_VERSION}",
        "",
        "FROZEN FORMULA",
        "-" * 78,
        "Lower-is-better ratio: anchor / performance",
        "Higher-is-better ratio: performance / anchor",
        "Bounded ratio: min(1, max(0, ratio))",
        "Performance level: 100 × bounded_ratio²",
        "",
        "WHY p = 2.0",
        "-" * 78,
        "The square-law is mathematically transparent.",
        "It materially rewards improvement near the collegiate frontier.",
        "It avoids the stronger compression of p = 2.5 and p = 3.0.",
        f"Global median score: "
        f"{as_float(selected_global, 'score_q50'):.2f}",
        f"Global 90th percentile: "
        f"{as_float(selected_global, 'score_q90'):.2f}",
        f"5K elite/developmental gain ratio: "
        f"{elite_5k / dev_5k:.3f}",
        f"LJ elite/developmental gain ratio: "
        f"{elite_lj / dev_lj:.3f}",
        "",
        "EXCEEDANCE POLICY",
        "-" * 78,
        f"Quarantined unresolved rows: {len(quarantined_rows):,}",
        f"Rounding-tolerance rows retained at 100: "
        f"{len(tolerance_rows):,}",
        "No unresolved row can improve an athlete or school ranking.",
        "Verified future records require an anchor refresh and recomputation.",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Performance-level transformation and exceedance "
            "overrides are frozen."
            if not failed
            else "FAIL — Do not materialize normalized scores."
        ),
        "",
        "NEXT",
        "-" * 78,
        "Materialize normalized performance levels for the eligible cohort.",
        "Then construct stable athlete-period performance estimates.",
    ]

    (OUTPUT_DIR / "phase_4d_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Selected exponent: {SELECTED_EXPONENT}")
    print(
        "Global median score: "
        f"{as_float(selected_global, 'score_q50'):.2f}"
    )
    print(
        "Global 90th percentile: "
        f"{as_float(selected_global, 'score_q90'):.2f}"
    )
    print(f"Quarantined exceedances: {len(quarantined_rows):,}")
    print(f"Tolerance exceedances: {len(tolerance_rows):,}")
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
    print("Next: materialize normalized performance levels.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
