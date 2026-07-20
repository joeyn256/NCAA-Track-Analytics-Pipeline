#!/usr/bin/env python3
"""
Milestone 5 Phase 3A — Build Collegiate Record Anchor Requirements

Creates the exact event × gender × season combinations needed by the frozen
track scoring foundation.

This step does not populate record marks. It determines:
- which combinations exist in the scoring data;
- how much coverage each combination has;
- which source record family is required;
- which combinations need a nonstandard-event fallback.

The output becomes the controlled template for the versioned record registry.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


REQUIREMENTS_VERSION = "record_anchor_requirements_v1"

FOUNDATION_DB = Path(
    "data/processed/milestone5/"
    "track_performance_foundation_v1/final_v1/"
    "track_performance_foundation_v1.duckdb"
)
OUTPUT_DIR = Path(
    "data/processed/milestone5/"
    "collegiate_record_anchors_v1/requirements_v1"
)

STANDARD_INDOOR_EVENTS = {
    "60M",
    "200M",
    "400M",
    "800M",
    "MILE",
    "3000M",
    "5000M",
    "60H",
    "HJ",
    "PV",
    "LJ",
    "TJ",
    "SP",
    "WT",
    "PENT",
    "HEP",
}

STANDARD_OUTDOOR_EVENTS = {
    "100M",
    "200M",
    "400M",
    "800M",
    "1500M",
    "5000M",
    "10000M",
    "100H",
    "110H",
    "400H",
    "3000SC",
    "HJ",
    "PV",
    "LJ",
    "TJ",
    "SP",
    "DT",
    "HT",
    "JT",
    "HEP",
    "DEC",
}

# Events likely to appear on collegiate record pages but outside the NCAA
# championship program. These can still receive direct collegiate anchors.
NONSTANDARD_DIRECT_RECORD_EVENTS = {
    "55M",
    "55H",
    "300M",
    "500M",
    "600M",
    "1000M",
    "MILE",
    "3000M",
    "10000M",
    "60M",
    "60H",
    "100M",
    "100H",
    "110H",
    "1500M",
    "3000SC",
    "DT",
    "HT",
    "JT",
    "WT",
    "PENT",
    "HEP",
    "DEC",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
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


def query_dicts(
    con: duckdb.DuckDBPyConnection,
    sql: str,
) -> list[dict[str, Any]]:
    result = con.execute(sql)
    columns = [item[0] for item in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def source_family(
    season_type: str,
    event_code: str,
) -> tuple[str, str, bool]:
    if season_type == "indoor":
        if event_code in STANDARD_INDOOR_EVENTS:
            return (
                "tfn_indoor_collegiate_record",
                "direct_standard_event",
                True,
            )
        if event_code in NONSTANDARD_DIRECT_RECORD_EVENTS:
            return (
                "tfn_indoor_collegiate_record",
                "direct_nonstandard_event",
                True,
            )
        return (
            "empirical_elite_fallback",
            "record_not_expected_on_standard_source",
            False,
        )

    if season_type == "outdoor":
        if event_code in STANDARD_OUTDOOR_EVENTS:
            return (
                "tfn_absolute_collegiate_record",
                "direct_standard_event",
                True,
            )
        if event_code in NONSTANDARD_DIRECT_RECORD_EVENTS:
            return (
                "tfn_absolute_collegiate_record",
                "direct_nonstandard_event",
                True,
            )
        return (
            "empirical_elite_fallback",
            "record_not_expected_on_standard_source",
            False,
        )

    return (
        "unsupported_season",
        "non_track_season",
        False,
    )


def main() -> int:
    root = Path.cwd()
    foundation_path = root / FOUNDATION_DB
    output_dir = root / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 3A — RECORD ANCHOR REQUIREMENTS")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Requirements version: {REQUIREMENTS_VERSION}")
    print(f"Foundation DB: {foundation_path}")
    print(f"Output: {output_dir}")

    exists = foundation_path.exists()
    add_check(
        checks,
        "track_foundation_database_exists",
        exists,
        exists,
        True,
        str(foundation_path),
    )
    if not exists:
        write_csv(
            output_dir / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Track foundation database is missing.")
        return 1

    before_hash = sha256_file(foundation_path)
    before_stat = foundation_path.stat()

    con = duckdb.connect(str(foundation_path), read_only=True)
    try:
        rows = query_dicts(
            con,
            """
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(mark_type) AS mark_type,
                ANY_VALUE(performance_direction)
                    AS performance_direction,
                ANY_VALUE(normalized_unit) AS normalized_unit,
                COUNT(*) AS performance_count,
                COUNT(DISTINCT canonical_person_id)
                    AS athlete_count,
                COUNT(DISTINCT school_stint_id)
                    AS school_stint_count,
                COUNT(DISTINCT resolved_school_id)
                    AS school_count,
                MIN(season_year) AS first_season_year,
                MAX(season_year) AS last_season_year
            FROM main.track_scoring_performances
            GROUP BY
                season_type,
                canonical_gender_code,
                canonical_event_code
            ORDER BY
                season_type,
                canonical_gender_code,
                canonical_event_code
            """,
        )

        scoring_rows = con.execute(
            """
            SELECT COUNT(*)
            FROM main.track_scoring_performances
            """
        ).fetchone()[0]
        distinct_events = con.execute(
            """
            SELECT COUNT(DISTINCT canonical_event_code)
            FROM main.track_scoring_performances
            """
        ).fetchone()[0]
    finally:
        con.close()

    requirement_rows: list[dict[str, Any]] = []

    for row in rows:
        (
            preferred_source_family,
            anchor_strategy,
            direct_record_expected,
        ) = source_family(
            row["season_type"],
            row["canonical_event_code"],
        )

        requirement_rows.append(
            {
                "requirements_version": REQUIREMENTS_VERSION,
                **row,
                "preferred_source_family": preferred_source_family,
                "anchor_strategy": anchor_strategy,
                "direct_record_expected": direct_record_expected,
                "anchor_status": "pending_source_entry",
                "record_value": "",
                "record_unit": row["normalized_unit"],
                "record_holder": "",
                "record_school": "",
                "record_date": "",
                "record_location": "",
                "ratification_status": "",
                "source_name": "",
                "source_url": "",
                "source_accessed_date": "",
                "effective_as_of_date": "",
                "notes": "",
            }
        )

    combination_count = len(requirement_rows)
    indoor_count = sum(
        row["season_type"] == "indoor"
        for row in requirement_rows
    )
    outdoor_count = sum(
        row["season_type"] == "outdoor"
        for row in requirement_rows
    )
    direct_expected_count = sum(
        bool(row["direct_record_expected"])
        for row in requirement_rows
    )
    fallback_count = combination_count - direct_expected_count

    add_check(
        checks,
        "requirements_created",
        combination_count > 0,
        combination_count,
        "greater than 0",
    )
    add_check(
        checks,
        "indoor_requirements_created",
        indoor_count > 0,
        indoor_count,
        "greater than 0",
    )
    add_check(
        checks,
        "outdoor_requirements_created",
        outdoor_count > 0,
        outdoor_count,
        "greater than 0",
    )
    add_check(
        checks,
        "all_requirements_have_gender",
        all(
            row["canonical_gender_code"] in {"m", "f"}
            for row in requirement_rows
        ),
        sum(
            row["canonical_gender_code"] not in {"m", "f"}
            for row in requirement_rows
        ),
        0,
    )
    add_check(
        checks,
        "all_requirements_have_supported_season",
        all(
            row["season_type"] in {"indoor", "outdoor"}
            for row in requirement_rows
        ),
        sum(
            row["season_type"] not in {"indoor", "outdoor"}
            for row in requirement_rows
        ),
        0,
    )
    add_check(
        checks,
        "all_requirements_have_positive_coverage",
        all(
            int(row["performance_count"]) > 0
            for row in requirement_rows
        ),
        sum(
            int(row["performance_count"]) <= 0
            for row in requirement_rows
        ),
        0,
    )
    add_check(
        checks,
        "requirement_performance_counts_reconcile",
        sum(
            int(row["performance_count"])
            for row in requirement_rows
        )
        == scoring_rows,
        sum(
            int(row["performance_count"])
            for row in requirement_rows
        ),
        scoring_rows,
    )

    fields = list(requirement_rows[0].keys())
    write_csv(
        output_dir / "record_anchor_requirements.csv",
        requirement_rows,
        fields,
    )

    direct_rows = [
        row for row in requirement_rows
        if row["direct_record_expected"]
    ]
    fallback_rows = [
        row for row in requirement_rows
        if not row["direct_record_expected"]
    ]

    write_csv(
        output_dir / "direct_record_requirements.csv",
        direct_rows,
        fields,
    )
    write_csv(
        output_dir / "fallback_anchor_requirements.csv",
        fallback_rows,
        fields,
    )

    source_summary: dict[tuple[str, str], dict[str, Any]] = {}
    for row in requirement_rows:
        key = (
            row["preferred_source_family"],
            row["anchor_strategy"],
        )
        item = source_summary.setdefault(
            key,
            {
                "preferred_source_family": key[0],
                "anchor_strategy": key[1],
                "requirement_count": 0,
                "performance_count": 0,
            },
        )
        item["requirement_count"] += 1
        item["performance_count"] += int(row["performance_count"])

    source_summary_rows = sorted(
        source_summary.values(),
        key=lambda row: (
            row["preferred_source_family"],
            row["anchor_strategy"],
        ),
    )
    write_csv(
        output_dir / "record_source_summary.csv",
        source_summary_rows,
        [
            "preferred_source_family",
            "anchor_strategy",
            "requirement_count",
            "performance_count",
        ],
    )

    after_hash = sha256_file(foundation_path)
    after_stat = foundation_path.stat()
    unchanged = (
        before_hash == after_hash
        and before_stat.st_size == after_stat.st_size
        and before_stat.st_mtime_ns == after_stat.st_mtime_ns
    )
    add_check(
        checks,
        "track_foundation_database_unchanged",
        unchanged,
        after_hash,
        before_hash,
    )

    write_csv(
        output_dir / "input_manifest.csv",
        [
            {
                "stage": "before",
                "path": str(foundation_path),
                "size_bytes": before_stat.st_size,
                "mtime_epoch_ns": before_stat.st_mtime_ns,
                "sha256": before_hash,
            },
            {
                "stage": "after",
                "path": str(foundation_path),
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
        "MILESTONE 5 PHASE 3A — COLLEGIATE RECORD ANCHOR REQUIREMENTS",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Requirements version: {REQUIREMENTS_VERSION}",
        "",
        "FOUNDATION SCALE",
        "-" * 78,
        f"Scoring-eligible performances: {scoring_rows:,}",
        f"Distinct canonical events: {distinct_events:,}",
        f"Event × gender × season requirements: {combination_count:,}",
        f"Indoor requirements: {indoor_count:,}",
        f"Outdoor requirements: {outdoor_count:,}",
        "",
        "ANCHOR COVERAGE PLAN",
        "-" * 78,
        f"Direct collegiate record expected: {direct_expected_count:,}",
        f"Fallback anchor required: {fallback_count:,}",
        "",
        "SOURCE POLICY",
        "-" * 78,
        "Outdoor uses T&FN absolute collegiate records.",
        "Indoor uses T&FN indoor collegiate records.",
        "NCAA championship records are retained as secondary cross-checks.",
        "Nonstandard events use direct collegiate records where published.",
        "Only combinations without a reliable direct record use fallback anchors.",
        "",
        "HARD CHECK SUMMARY",
        "-" * 78,
        f"PASS: {sum(c['status'] == 'PASS' for c in checks)}",
        f"FAIL: {len(failed)}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Record anchor requirements are ready for source population."
            if not failed
            else "FAIL — Correct requirement coverage or reconciliation."
        ),
    ]

    (output_dir / "record_anchor_requirements_report.txt").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Scoring-eligible performances: {scoring_rows:,}")
    print(f"Record-anchor requirements: {combination_count:,}")
    print(f"Direct records expected: {direct_expected_count:,}")
    print(f"Fallback anchors required: {fallback_count:,}")
    print()
    print("Created:")
    for filename in [
        "record_anchor_requirements_report.txt",
        "record_anchor_requirements.csv",
        "direct_record_requirements.csv",
        "fallback_anchor_requirements.csv",
        "record_source_summary.csv",
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
    print("Next: populate and validate versioned collegiate record marks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
