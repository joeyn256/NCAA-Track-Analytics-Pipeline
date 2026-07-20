#!/usr/bin/env python3
"""
Milestone 5 Phase 1E — Freeze Final Event Registry

Creates the production event registry after the reviewed 5,000-performance
policy has been approved.

Outputs:
- 33-row canonical event registry.
- Complete 347-label disposition map.
- Exclusion audit.
- Small DuckDB reference database.
- Validation report and immutable input manifest.

No coach-review or manual-review columns are carried into production outputs.
"""

from __future__ import annotations

import csv
import hashlib
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


REGISTRY_VERSION = "event_registry_v1"
MIN_EVENT_PERFORMANCES = 5_000

ELIGIBLE_GROUPS = Path(
    "data/processed/milestone5/event_registry_v1/"
    "policy_review_v2/track_event_groups_for_coach_review.csv"
)
ELIGIBLE_LABELS = Path(
    "data/processed/milestone5/event_registry_v1/"
    "policy_review_v2/track_event_labels_for_coach_review.csv"
)
LOW_SAMPLE_LABELS = Path(
    "data/processed/milestone5/event_registry_v1/"
    "policy_review_v2/track_event_labels_excluded_low_sample.csv"
)
CROSS_COUNTRY_LABELS = Path(
    "data/processed/milestone5/event_registry_v1/"
    "coach_review_v1/cross_country_auto_classified.csv"
)
RELAY_LABELS = Path(
    "data/processed/milestone5/event_registry_v1/"
    "coach_review_v1/relay_manual_review.csv"
)
ADMIN_LABELS = Path(
    "data/processed/milestone5/event_registry_v1/"
    "coach_review_v1/administrative_exclusions.csv"
)

OUTPUT_DIR = Path(
    "data/processed/milestone5/event_registry_v1/final_v1"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def parse_float_or_blank(value: Any) -> float | str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return float(text)
    except ValueError:
        return ""


def bool_from_text(value: Any) -> bool:
    return str(value).strip().lower() == "true"


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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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


def compact_hurdle_name(code: str, name: str, family: str) -> str:
    if family != "hurdles":
        return name

    metric = re.fullmatch(r"(\d+)H", code)
    if metric:
        return f"{metric.group(1)}m Hurdles"

    yards = re.fullmatch(r"(\d+)YH", code)
    if yards:
        return f"{yards.group(1)}y Hurdles"

    return re.sub(
        r"(\d+)\s+([my])\s+Hurdles",
        r"\1\2 Hurdles",
        name,
        flags=re.IGNORECASE,
    )


def ensure_single_value(
    values: Iterable[str],
    field_name: str,
    code: str,
) -> str:
    unique = {
        str(value).strip()
        for value in values
        if str(value).strip()
    }
    if len(unique) > 1:
        raise ValueError(
            f"{code} has conflicting {field_name} values: {sorted(unique)}"
        )
    return next(iter(unique), "")


def infer_mark_type_and_direction(
    family: str,
    existing_mark_type: str,
    existing_direction: str,
) -> tuple[str, str]:
    mark_type = existing_mark_type.strip()
    direction = existing_direction.strip()

    if mark_type and direction:
        return mark_type, direction

    if family in {
        "running",
        "hurdles",
        "steeplechase",
        "race_walk",
    }:
        return "time", "lower_is_better"

    if family in {
        "horizontal_jumps",
        "vertical_jumps",
        "throws",
    }:
        return "distance", "higher_is_better"

    if family == "combined_events":
        return "points", "higher_is_better"

    return mark_type, direction


def create_duckdb(
    path: Path,
    registry_rows: list[dict[str, Any]],
    mapping_rows: list[dict[str, Any]],
    exclusion_rows: list[dict[str, Any]],
) -> None:
    if path.exists():
        path.unlink()

    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS main")

        con.execute(
            """
            CREATE TABLE main.canonical_events (
                registry_version VARCHAR,
                canonical_event_code VARCHAR,
                canonical_event_name VARCHAR,
                event_family VARCHAR,
                event_subfamily VARCHAR,
                mark_type VARCHAR,
                performance_direction VARCHAR,
                standard_distance_meters DOUBLE,
                performance_count BIGINT,
                raw_label_count INTEGER,
                source_labels VARCHAR,
                minimum_required_performances INTEGER,
                development_model_eligible BOOLEAN
            )
            """
        )

        con.executemany(
            """
            INSERT INTO main.canonical_events VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (
                    row["registry_version"],
                    row["canonical_event_code"],
                    row["canonical_event_name"],
                    row["event_family"],
                    row["event_subfamily"],
                    row["mark_type"],
                    row["performance_direction"],
                    (
                        None
                        if row["standard_distance_meters"] == ""
                        else float(row["standard_distance_meters"])
                    ),
                    int(row["performance_count"]),
                    int(row["raw_label_count"]),
                    row["source_labels"],
                    int(row["minimum_required_performances"]),
                    bool(row["development_model_eligible"]),
                )
                for row in registry_rows
            ],
        )

        con.execute(
            """
            CREATE TABLE main.event_label_map (
                registry_version VARCHAR,
                event_id VARCHAR,
                raw_event_label VARCHAR,
                canonical_event_code VARCHAR,
                canonical_event_name VARCHAR,
                event_family VARCHAR,
                registry_disposition VARCHAR,
                development_model_eligible BOOLEAN,
                exclusion_reason VARCHAR,
                performance_count BIGINT
            )
            """
        )

        con.executemany(
            """
            INSERT INTO main.event_label_map VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (
                    row["registry_version"],
                    row["event_id"],
                    row["raw_event_label"],
                    row["canonical_event_code"],
                    row["canonical_event_name"],
                    row["event_family"],
                    row["registry_disposition"],
                    bool(row["development_model_eligible"]),
                    row["exclusion_reason"],
                    int(row["performance_count"]),
                )
                for row in mapping_rows
            ],
        )

        con.execute(
            """
            CREATE TABLE main.event_exclusions AS
            SELECT *
            FROM main.event_label_map
            WHERE NOT development_model_eligible
            """
        )

        con.execute(
            """
            CREATE UNIQUE INDEX canonical_events_code_uq
            ON main.canonical_events(canonical_event_code)
            """
        )
        con.execute(
            """
            CREATE UNIQUE INDEX event_label_map_id_uq
            ON main.event_label_map(event_id)
            """
        )
    finally:
        con.close()


def main() -> int:
    root = Path.cwd()
    output_dir = root / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = {
        "eligible_groups": root / ELIGIBLE_GROUPS,
        "eligible_labels": root / ELIGIBLE_LABELS,
        "low_sample_labels": root / LOW_SAMPLE_LABELS,
        "cross_country_labels": root / CROSS_COUNTRY_LABELS,
        "relay_labels": root / RELAY_LABELS,
        "administrative_labels": root / ADMIN_LABELS,
    }

    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 1E — FREEZE FINAL EVENT REGISTRY")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Registry version: {REGISTRY_VERSION}")
    print(f"Minimum event performances: {MIN_EVENT_PERFORMANCES:,}")
    print(f"Output: {output_dir}")

    manifest_before: list[dict[str, Any]] = []
    for name, path in inputs.items():
        exists = path.exists()
        add_check(
            checks,
            f"{name}_exists",
            exists,
            exists,
            True,
            str(path),
        )
        if exists:
            stat = path.stat()
            manifest_before.append(
                {
                    "input_name": name,
                    "stage": "before",
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "mtime_epoch_ns": stat.st_mtime_ns,
                    "sha256": sha256_file(path),
                }
            )

    if any(not path.exists() for path in inputs.values()):
        write_csv(
            output_dir / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Missing required Phase 1 inputs.")
        return 1

    eligible_groups = read_csv(inputs["eligible_groups"])
    eligible_labels = read_csv(inputs["eligible_labels"])
    low_sample_labels = read_csv(inputs["low_sample_labels"])
    cross_country_labels = read_csv(inputs["cross_country_labels"])
    relay_labels = read_csv(inputs["relay_labels"])
    admin_labels = read_csv(inputs["administrative_labels"])

    labels_by_code: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in eligible_labels:
        code = row["policy_canonical_event_code"].strip()
        labels_by_code[code].append(row)

    registry_rows: list[dict[str, Any]] = []
    for group in eligible_groups:
        code = group["policy_canonical_event_code"].strip()
        label_members = labels_by_code.get(code, [])
        if not label_members:
            raise ValueError(
                f"Eligible canonical group {code} has no eligible labels."
            )

        family = group["policy_event_family"].strip()
        subfamily = group["policy_event_subfamily"].strip()
        name = compact_hurdle_name(
            code,
            group["policy_canonical_event_name"].strip(),
            family,
        )

        mark_type = ensure_single_value(
            (
                row.get("suggested_mark_type", "")
                for row in label_members
            ),
            "mark_type",
            code,
        )
        direction = ensure_single_value(
            (
                row.get("suggested_performance_direction", "")
                for row in label_members
            ),
            "performance_direction",
            code,
        )
        mark_type, direction = infer_mark_type_and_direction(
            family,
            mark_type,
            direction,
        )

        distance_text = ensure_single_value(
            (
                row.get("suggested_standard_distance_meters", "")
                for row in label_members
            ),
            "standard_distance_meters",
            code,
        )
        distance = parse_float_or_blank(distance_text)

        source_labels = sorted(
            {
                row["raw_event_label"].strip()
                for row in label_members
            }
        )

        registry_rows.append(
            {
                "registry_version": REGISTRY_VERSION,
                "canonical_event_code": code,
                "canonical_event_name": name,
                "event_family": family,
                "event_subfamily": subfamily,
                "mark_type": mark_type,
                "performance_direction": direction,
                "standard_distance_meters": distance,
                "performance_count": parse_int(
                    group["policy_performance_count"]
                ),
                "raw_label_count": len(source_labels),
                "source_labels": " | ".join(source_labels),
                "minimum_required_performances": (
                    MIN_EVENT_PERFORMANCES
                ),
                "development_model_eligible": True,
            }
        )

    registry_rows.sort(
        key=lambda row: (
            row["event_family"],
            row["canonical_event_code"],
        )
    )

    registry_by_code = {
        row["canonical_event_code"]: row
        for row in registry_rows
    }

    mapping_rows: list[dict[str, Any]] = []

    for row in eligible_labels:
        code = row["policy_canonical_event_code"].strip()
        canonical = registry_by_code[code]
        mapping_rows.append(
            {
                "registry_version": REGISTRY_VERSION,
                "event_id": str(row["event_id"]),
                "raw_event_label": row["raw_event_label"],
                "canonical_event_code": code,
                "canonical_event_name": canonical[
                    "canonical_event_name"
                ],
                "event_family": canonical["event_family"],
                "registry_disposition": "include",
                "development_model_eligible": True,
                "exclusion_reason": "",
                "performance_count": parse_int(
                    row["performance_count"]
                ),
            }
        )

    for row in low_sample_labels:
        mapping_rows.append(
            {
                "registry_version": REGISTRY_VERSION,
                "event_id": str(row["event_id"]),
                "raw_event_label": row["raw_event_label"],
                "canonical_event_code": row.get(
                    "policy_canonical_event_code", ""
                ).strip(),
                "canonical_event_name": row.get(
                    "policy_canonical_event_name", ""
                ).strip(),
                "event_family": row.get(
                    "suggested_event_family", ""
                ).strip(),
                "registry_disposition": "exclude_low_sample",
                "development_model_eligible": False,
                "exclusion_reason": (
                    "canonical_event_group_has_fewer_than_"
                    f"{MIN_EVENT_PERFORMANCES}_performances"
                ),
                "performance_count": parse_int(
                    row["performance_count"]
                ),
            }
        )

    for row in cross_country_labels:
        mapping_rows.append(
            {
                "registry_version": REGISTRY_VERSION,
                "event_id": str(row["event_id"]),
                "raw_event_label": row["raw_event_label"],
                "canonical_event_code": "",
                "canonical_event_name": "",
                "event_family": "cross_country",
                "registry_disposition": (
                    "separate_cross_country_model"
                ),
                "development_model_eligible": False,
                "exclusion_reason": (
                    "cross_country_course_times_not_comparable_"
                    "to_track_times"
                ),
                "performance_count": parse_int(
                    row["performance_count"]
                ),
            }
        )

    for row in relay_labels:
        mapping_rows.append(
            {
                "registry_version": REGISTRY_VERSION,
                "event_id": str(row["event_id"]),
                "raw_event_label": row["raw_event_label"],
                "canonical_event_code": "",
                "canonical_event_name": "",
                "event_family": "relays",
                "registry_disposition": "exclude_relay",
                "development_model_eligible": False,
                "exclusion_reason": (
                    "relay_results_not_attributable_to_one_athlete"
                ),
                "performance_count": parse_int(
                    row["performance_count"]
                ),
            }
        )

    for row in admin_labels:
        mapping_rows.append(
            {
                "registry_version": REGISTRY_VERSION,
                "event_id": str(row["event_id"]),
                "raw_event_label": row["raw_event_label"],
                "canonical_event_code": "",
                "canonical_event_name": "",
                "event_family": "administrative",
                "registry_disposition": "exclude_administrative",
                "development_model_eligible": False,
                "exclusion_reason": (
                    row.get("suggested_reason")
                    or row.get("draft_exclusion_reason")
                    or "non_performance_event"
                ),
                "performance_count": parse_int(
                    row["performance_count"]
                ),
            }
        )

    mapping_rows.sort(key=lambda row: int(row["event_id"]))

    exclusion_rows = [
        row
        for row in mapping_rows
        if not row["development_model_eligible"]
    ]

    registry_fields = [
        "registry_version",
        "canonical_event_code",
        "canonical_event_name",
        "event_family",
        "event_subfamily",
        "mark_type",
        "performance_direction",
        "standard_distance_meters",
        "performance_count",
        "raw_label_count",
        "source_labels",
        "minimum_required_performances",
        "development_model_eligible",
    ]
    mapping_fields = [
        "registry_version",
        "event_id",
        "raw_event_label",
        "canonical_event_code",
        "canonical_event_name",
        "event_family",
        "registry_disposition",
        "development_model_eligible",
        "exclusion_reason",
        "performance_count",
    ]

    final_registry_csv = output_dir / "canonical_event_registry.csv"
    final_mapping_csv = output_dir / "event_label_map.csv"
    final_exclusions_csv = output_dir / "event_exclusions.csv"
    final_db = output_dir / "event_registry_v1.duckdb"

    write_csv(final_registry_csv, registry_rows, registry_fields)
    write_csv(final_mapping_csv, mapping_rows, mapping_fields)
    write_csv(final_exclusions_csv, exclusion_rows, mapping_fields)

    create_duckdb(
        final_db,
        registry_rows,
        mapping_rows,
        exclusion_rows,
    )

    canonical_codes = [
        row["canonical_event_code"]
        for row in registry_rows
    ]
    mapping_event_ids = [
        row["event_id"]
        for row in mapping_rows
    ]
    included_mapping_codes = {
        row["canonical_event_code"]
        for row in mapping_rows
        if row["development_model_eligible"]
    }

    add_check(
        checks,
        "canonical_registry_row_count",
        len(registry_rows) == 33,
        len(registry_rows),
        33,
    )
    add_check(
        checks,
        "canonical_event_codes_unique",
        len(canonical_codes) == len(set(canonical_codes)),
        len(canonical_codes) - len(set(canonical_codes)),
        0,
    )
    add_check(
        checks,
        "all_canonical_events_meet_5000_threshold",
        all(
            row["performance_count"] >= MIN_EVENT_PERFORMANCES
            for row in registry_rows
        ),
        sum(
            row["performance_count"] < MIN_EVENT_PERFORMANCES
            for row in registry_rows
        ),
        0,
    )
    add_check(
        checks,
        "complete_label_map_row_count",
        len(mapping_rows) == 347,
        len(mapping_rows),
        347,
    )
    add_check(
        checks,
        "label_map_event_ids_unique",
        len(mapping_event_ids) == len(set(mapping_event_ids)),
        len(mapping_event_ids) - len(set(mapping_event_ids)),
        0,
    )
    add_check(
        checks,
        "included_label_count",
        sum(
            row["development_model_eligible"]
            for row in mapping_rows
        ) == 35,
        sum(
            row["development_model_eligible"]
            for row in mapping_rows
        ),
        35,
    )
    add_check(
        checks,
        "included_mapping_codes_exist_in_registry",
        included_mapping_codes == set(canonical_codes),
        len(included_mapping_codes - set(canonical_codes)),
        0,
        (
            f"missing_from_registry="
            f"{sorted(included_mapping_codes - set(canonical_codes))}; "
            f"unused_registry_codes="
            f"{sorted(set(canonical_codes) - included_mapping_codes)}"
        ),
    )
    add_check(
        checks,
        "every_mapping_has_disposition",
        all(row["registry_disposition"] for row in mapping_rows),
        sum(
            not row["registry_disposition"]
            for row in mapping_rows
        ),
        0,
    )
    add_check(
        checks,
        "excluded_mappings_have_reason",
        all(
            row["exclusion_reason"]
            for row in mapping_rows
            if not row["development_model_eligible"]
        ),
        sum(
            not row["exclusion_reason"]
            for row in mapping_rows
            if not row["development_model_eligible"]
        ),
        0,
    )
    add_check(
        checks,
        "included_events_have_complete_semantics",
        all(
            row["mark_type"]
            and row["performance_direction"]
            in {"lower_is_better", "higher_is_better"}
            and row["event_family"]
            and row["event_subfamily"]
            for row in registry_rows
        ),
        sum(
            not row["mark_type"]
            or row["performance_direction"]
            not in {"lower_is_better", "higher_is_better"}
            or not row["event_family"]
            or not row["event_subfamily"]
            for row in registry_rows
        ),
        0,
    )
    add_check(
        checks,
        "hurdle_names_use_compact_format",
        all(
            not re.search(
                r"\d+\s+[my]\s+Hurdles",
                row["canonical_event_name"],
                flags=re.IGNORECASE,
            )
            for row in registry_rows
            if row["event_family"] == "hurdles"
        ),
        sum(
            bool(
                re.search(
                    r"\d+\s+[my]\s+Hurdles",
                    row["canonical_event_name"],
                    flags=re.IGNORECASE,
                )
            )
            for row in registry_rows
            if row["event_family"] == "hurdles"
        ),
        0,
    )

    production_columns = registry_fields + mapping_fields
    forbidden_columns = [
        column
        for column in production_columns
        if column.startswith("coach_")
        or column.startswith("review_")
        or "manual_review" in column
    ]
    add_check(
        checks,
        "no_coach_or_review_columns_in_production",
        len(forbidden_columns) == 0,
        ",".join(forbidden_columns),
        "none",
    )

    con = duckdb.connect(str(final_db), read_only=True)
    try:
        db_registry_count = con.execute(
            "SELECT COUNT(*) FROM main.canonical_events"
        ).fetchone()[0]
        db_mapping_count = con.execute(
            "SELECT COUNT(*) FROM main.event_label_map"
        ).fetchone()[0]
        db_exclusion_count = con.execute(
            "SELECT COUNT(*) FROM main.event_exclusions"
        ).fetchone()[0]
    finally:
        con.close()

    add_check(
        checks,
        "duckdb_canonical_registry_count",
        db_registry_count == len(registry_rows),
        db_registry_count,
        len(registry_rows),
    )
    add_check(
        checks,
        "duckdb_label_map_count",
        db_mapping_count == len(mapping_rows),
        db_mapping_count,
        len(mapping_rows),
    )
    add_check(
        checks,
        "duckdb_exclusion_count",
        db_exclusion_count == len(exclusion_rows),
        db_exclusion_count,
        len(exclusion_rows),
    )

    manifest_after: list[dict[str, Any]] = []
    before_by_name = {
        row["input_name"]: row
        for row in manifest_before
    }
    for name, path in inputs.items():
        stat = path.stat()
        row = {
            "input_name": name,
            "stage": "after",
            "path": str(path),
            "size_bytes": stat.st_size,
            "mtime_epoch_ns": stat.st_mtime_ns,
            "sha256": sha256_file(path),
        }
        manifest_after.append(row)

        before = before_by_name[name]
        add_check(
            checks,
            f"{name}_input_unchanged",
            (
                row["size_bytes"] == before["size_bytes"]
                and row["mtime_epoch_ns"] == before["mtime_epoch_ns"]
                and row["sha256"] == before["sha256"]
            ),
            row["sha256"],
            before["sha256"],
        )

    write_csv(
        output_dir / "input_manifest.csv",
        manifest_before + manifest_after,
        [
            "input_name",
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

    disposition_counts = Counter(
        row["registry_disposition"]
        for row in mapping_rows
    )
    family_counts = Counter(
        row["event_family"]
        for row in registry_rows
    )

    summary_rows: list[dict[str, Any]] = [
        {
            "summary_type": "registry",
            "value": "canonical_events",
            "count": len(registry_rows),
        },
        {
            "summary_type": "registry",
            "value": "raw_event_labels",
            "count": len(mapping_rows),
        },
        {
            "summary_type": "registry",
            "value": "included_raw_labels",
            "count": sum(
                row["development_model_eligible"]
                for row in mapping_rows
            ),
        },
        {
            "summary_type": "registry",
            "value": "excluded_raw_labels",
            "count": len(exclusion_rows),
        },
    ]
    for value, count in sorted(disposition_counts.items()):
        summary_rows.append(
            {
                "summary_type": "disposition",
                "value": value,
                "count": count,
            }
        )
    for value, count in sorted(family_counts.items()):
        summary_rows.append(
            {
                "summary_type": "eligible_event_family",
                "value": value,
                "count": count,
            }
        )

    write_csv(
        output_dir / "registry_summary.csv",
        summary_rows,
        ["summary_type", "value", "count"],
    )

    failed = [
        check for check in checks
        if check["status"] == "FAIL"
    ]

    report_lines = [
        "MILESTONE 5 PHASE 1E — FINAL EVENT REGISTRY",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Registry version: {REGISTRY_VERSION}",
        (
            "Minimum canonical-event performance count: "
            f"{MIN_EVENT_PERFORMANCES:,}"
        ),
        "",
        "FINAL SCALE",
        "-" * 78,
        f"Canonical eligible events: {len(registry_rows):,}",
        f"Included raw event labels: {sum(row['development_model_eligible'] for row in mapping_rows):,}",
        f"All raw event labels mapped: {len(mapping_rows):,}",
        f"Excluded/separate labels: {len(exclusion_rows):,}",
        "",
        "DISPOSITIONS",
        "-" * 78,
    ]
    for value, count in sorted(disposition_counts.items()):
        report_lines.append(f"{value}: {count:,}")

    report_lines.extend(
        [
            "",
            "PRODUCTION OUTPUT CONTRACT",
            "-" * 78,
            "canonical_event_registry.csv: one row per eligible canonical event",
            "event_label_map.csv: one row per source event label",
            "event_exclusions.csv: explicit non-model dispositions",
            "event_registry_v1.duckdb: production reference database",
            "",
            "No coach-review or manual-review columns are included.",
            "",
            "HARD CHECK SUMMARY",
            "-" * 78,
            f"PASS: {sum(c['status'] == 'PASS' for c in checks)}",
            f"FAIL: {len(failed)}",
            "",
            "PHASE GATE",
            "-" * 78,
            (
                "PASS — Phase 1 event registry is frozen and ready for mark parsing."
                if not failed
                else "FAIL — Correct final-registry validation errors."
            ),
        ]
    )

    (output_dir / "final_registry_report.txt").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Canonical eligible events: {len(registry_rows):,}")
    print(f"Complete raw-label mapping: {len(mapping_rows):,}")
    print(f"Excluded/separate labels: {len(exclusion_rows):,}")
    print()
    print("Created:")
    for filename in [
        "final_registry_report.txt",
        "canonical_event_registry.csv",
        "event_label_map.csv",
        "event_exclusions.csv",
        "event_registry_v1.duckdb",
        "registry_summary.csv",
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
    print("Phase 1 is complete. Next: mark parsing and validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
