#!/usr/bin/env python3
"""
Milestone 5 Phase 2A — Eligible Mark-Format Audit

Profiles the raw mark formats used by the frozen 33-event registry before
building the production numeric parser.

This is a read-only audit. It does not create the final parsed-performance
table and does not modify either input DuckDB database.
"""

from __future__ import annotations

import csv
import hashlib
import math
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


PROFILE_VERSION = "mark_profile_v1"
EXPECTED_CANONICAL_EVENTS = 33
EXPECTED_INCLUDED_LABELS = 35
EXPECTED_INCLUDED_PERFORMANCES = 4_953_801

CANONICAL_DB = Path(
    "data/processed/milestone4/canonical_person_layer_v1_1/"
    "canonical_person_layer_v1_1.duckdb"
)
REGISTRY_DB = Path(
    "data/processed/milestone5/event_registry_v1/final_v1/"
    "event_registry_v1.duckdb"
)
OUTPUT_DIR = Path(
    "data/processed/milestone5/mark_parsing_v1/profile_v1"
)

STATUS_CODES = {
    "DNF",
    "DNS",
    "DQ",
    "DSQ",
    "NM",
    "NH",
    "NT",
    "SCR",
    "FS",
    "FOUL",
    "WD",
    "ND",
}

# Conservative trailing annotations observed in track databases commonly
# include hand timing, altitude, conversions, and record/qualification flags.
TRAILING_ANNOTATION_RE = re.compile(
    r"""
    (?:
        \s*
        (?:
            [*+#@!]
            |
            \((?:A|C|H|HT|ALT|CONV)\)
            |
            (?:A|C|H|HT|ALT|CONV|W)
        )
    )+$
    """,
    re.IGNORECASE | re.VERBOSE,
)

TIME_SECONDS_RE = re.compile(r"^\d+(?:\.\d+)?$")
TIME_MINUTES_RE = re.compile(r"^(?P<m>\d{1,3}):(?P<s>\d{1,2}(?:\.\d+)?)$")
TIME_HOURS_RE = re.compile(
    r"^(?P<h>\d{1,2}):(?P<m>\d{1,2}):(?P<s>\d{1,2}(?:\.\d+)?)$"
)

METRIC_DISTANCE_RE = re.compile(
    r"^(?P<value>\d+(?:\.\d+)?)\s*(?:m|meter|meters|metre|metres)?$",
    re.IGNORECASE,
)
FEET_INCHES_HYPHEN_RE = re.compile(
    r"^(?P<feet>\d{1,3})\s*-\s*(?P<inches>\d{1,2}(?:\.\d+)?)$"
)
FEET_INCHES_QUOTES_RE = re.compile(
    r"""^(?P<feet>\d{1,3})\s*['′]\s*(?P<inches>\d{1,2}(?:\.\d+)?)\s*(?:["″])?$"""
)
POINTS_RE = re.compile(r"^\d+(?:\.\d+)?$")


@dataclass(frozen=True)
class ParseResult:
    parser_class: str
    parsed_value: float | None
    parseable: bool
    is_status: bool
    normalized_token: str
    annotation_removed: bool


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


def normalize_mark(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    text = (
        text.replace("–", "-")
        .replace("—", "-")
        .replace("’", "'")
        .replace("′", "'")
        .replace("″", '"')
    )
    text = re.sub(r"\s+", " ", text)
    return text


def strip_trailing_annotations(token: str) -> tuple[str, bool]:
    current = token.strip()
    changed = False

    while current:
        updated = TRAILING_ANNOTATION_RE.sub("", current).strip()
        if updated == current:
            break
        changed = True
        current = updated

    return current, changed


def status_token(token: str) -> str | None:
    cleaned = token.upper().strip().strip(".")
    cleaned = re.sub(r"\s+", "", cleaned)
    if cleaned in STATUS_CODES:
        return cleaned
    return None


def parse_time(value: Any) -> ParseResult:
    original = normalize_mark(value)
    if not original:
        return ParseResult("blank", None, False, False, "", False)

    status = status_token(original)
    if status:
        return ParseResult(
            f"status:{status}",
            None,
            False,
            True,
            status,
            False,
        )

    token, annotated = strip_trailing_annotations(original)

    match = TIME_HOURS_RE.fullmatch(token)
    if match:
        hours = float(match.group("h"))
        minutes = float(match.group("m"))
        seconds = float(match.group("s"))
        valid = minutes < 60 and seconds < 60
        return ParseResult(
            (
                "hours_minutes_seconds_annotated"
                if annotated
                else "hours_minutes_seconds"
            ),
            hours * 3600 + minutes * 60 + seconds if valid else None,
            valid,
            False,
            token,
            annotated,
        )

    match = TIME_MINUTES_RE.fullmatch(token)
    if match:
        minutes = float(match.group("m"))
        seconds = float(match.group("s"))
        valid = seconds < 60
        return ParseResult(
            (
                "minutes_seconds_annotated"
                if annotated
                else "minutes_seconds"
            ),
            minutes * 60 + seconds if valid else None,
            valid,
            False,
            token,
            annotated,
        )

    if TIME_SECONDS_RE.fullmatch(token):
        seconds = float(token)
        return ParseResult(
            "numeric_seconds_annotated" if annotated else "numeric_seconds",
            seconds,
            math.isfinite(seconds),
            False,
            token,
            annotated,
        )

    return ParseResult(
        "unrecognized",
        None,
        False,
        False,
        token,
        annotated,
    )


def parse_distance(value: Any) -> ParseResult:
    original = normalize_mark(value)
    if not original:
        return ParseResult("blank", None, False, False, "", False)

    status = status_token(original)
    if status:
        return ParseResult(
            f"status:{status}",
            None,
            False,
            True,
            status,
            False,
        )

    token, annotated = strip_trailing_annotations(original)

    match = METRIC_DISTANCE_RE.fullmatch(token)
    if match:
        meters = float(match.group("value"))
        return ParseResult(
            "metric_distance_annotated" if annotated else "metric_distance",
            meters,
            math.isfinite(meters),
            False,
            token,
            annotated,
        )

    match = FEET_INCHES_HYPHEN_RE.fullmatch(token)
    if not match:
        match = FEET_INCHES_QUOTES_RE.fullmatch(token)

    if match:
        feet = float(match.group("feet"))
        inches = float(match.group("inches"))
        valid = 0 <= inches < 12
        meters = (feet * 12 + inches) * 0.0254 if valid else None
        return ParseResult(
            (
                "feet_inches_annotated"
                if annotated
                else "feet_inches"
            ),
            meters,
            valid,
            False,
            token,
            annotated,
        )

    return ParseResult(
        "unrecognized",
        None,
        False,
        False,
        token,
        annotated,
    )


def parse_points(value: Any) -> ParseResult:
    original = normalize_mark(value)
    if not original:
        return ParseResult("blank", None, False, False, "", False)

    status = status_token(original)
    if status:
        return ParseResult(
            f"status:{status}",
            None,
            False,
            True,
            status,
            False,
        )

    token, annotated = strip_trailing_annotations(original)

    if POINTS_RE.fullmatch(token):
        points = float(token)
        return ParseResult(
            "numeric_points_annotated" if annotated else "numeric_points",
            points,
            math.isfinite(points),
            False,
            token,
            annotated,
        )

    return ParseResult(
        "unrecognized",
        None,
        False,
        False,
        token,
        annotated,
    )


def parse_mark(mark_type: str, value: Any) -> ParseResult:
    if mark_type == "time":
        return parse_time(value)
    if mark_type == "distance":
        return parse_distance(value)
    if mark_type == "points":
        return parse_points(value)

    token = normalize_mark(value)
    return ParseResult(
        "unsupported_mark_type",
        None,
        False,
        False,
        token,
        False,
    )


def manifest_row(name: str, path: Path, stage: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "input_name": name,
        "stage": stage,
        "path": str(path),
        "size_bytes": stat.st_size,
        "mtime_epoch_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def main() -> int:
    root = Path.cwd()
    canonical_path = root / CANONICAL_DB
    registry_path = root / REGISTRY_DB
    output_dir = root / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = {
        "canonical_person_database": canonical_path,
        "event_registry_database": registry_path,
    }

    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 2A — ELIGIBLE MARK-FORMAT AUDIT")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Profile version: {PROFILE_VERSION}")
    print(f"Canonical DB: {canonical_path}")
    print(f"Registry DB: {registry_path}")
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
            manifest_before.append(manifest_row(name, path, "before"))

    if any(not path.exists() for path in inputs.values()):
        write_csv(
            output_dir / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Missing required input.")
        return 1

    disk = shutil.disk_usage(root)
    write_csv(
        output_dir / "disk_space.csv",
        [
            {
                "path": str(root),
                "total_bytes": disk.total,
                "used_bytes": disk.used,
                "free_bytes": disk.free,
                "free_gib": round(disk.free / (1024**3), 3),
            }
        ],
        ["path", "total_bytes", "used_bytes", "free_bytes", "free_gib"],
    )

    con = duckdb.connect(":memory:")
    try:
        con.execute(
            f"ATTACH '{canonical_path.as_posix().replace(chr(39), chr(39) * 2)}' "
            "AS canonical_person (READ_ONLY)"
        )
        con.execute(
            f"ATTACH '{registry_path.as_posix().replace(chr(39), chr(39) * 2)}' "
            "AS event_registry (READ_ONLY)"
        )

        canonical_event_count = con.execute(
            """
            SELECT COUNT(*)
            FROM event_registry.main.canonical_events
            """
        ).fetchone()[0]
        included_label_count = con.execute(
            """
            SELECT COUNT(*)
            FROM event_registry.main.event_label_map
            WHERE development_model_eligible
            """
        ).fetchone()[0]
        expected_performance_sum = con.execute(
            """
            SELECT SUM(performance_count)
            FROM event_registry.main.canonical_events
            """
        ).fetchone()[0]

        add_check(
            checks,
            "canonical_event_count",
            canonical_event_count == EXPECTED_CANONICAL_EVENTS,
            canonical_event_count,
            EXPECTED_CANONICAL_EVENTS,
        )
        add_check(
            checks,
            "included_raw_label_count",
            included_label_count == EXPECTED_INCLUDED_LABELS,
            included_label_count,
            EXPECTED_INCLUDED_LABELS,
        )
        add_check(
            checks,
            "registry_expected_performance_sum",
            expected_performance_sum == EXPECTED_INCLUDED_PERFORMANCES,
            expected_performance_sum,
            EXPECTED_INCLUDED_PERFORMANCES,
        )

        unsupported_mark_types = con.execute(
            """
            SELECT COUNT(*)
            FROM event_registry.main.canonical_events
            WHERE mark_type NOT IN ('time', 'distance', 'points')
            """
        ).fetchone()[0]
        add_check(
            checks,
            "all_registry_mark_types_supported",
            unsupported_mark_types == 0,
            unsupported_mark_types,
            0,
        )

        joined_count = con.execute(
            """
            SELECT COUNT(*)
            FROM canonical_person.main.canonical_person_performances AS p
            JOIN event_registry.main.event_label_map AS m
              ON CAST(p.event_id AS VARCHAR) = m.event_id
            WHERE m.development_model_eligible
            """
        ).fetchone()[0]

        add_check(
            checks,
            "eligible_performance_join_count",
            joined_count == EXPECTED_INCLUDED_PERFORMANCES,
            joined_count,
            EXPECTED_INCLUDED_PERFORMANCES,
        )

        registry_rows_raw = con.execute(
            """
            SELECT
                canonical_event_code,
                canonical_event_name,
                event_family,
                event_subfamily,
                mark_type,
                performance_direction,
                performance_count
            FROM event_registry.main.canonical_events
            ORDER BY canonical_event_code
            """
        ).fetchall()
        registry_columns = [item[0] for item in con.description]
        registry_rows = [
            dict(zip(registry_columns, row))
            for row in registry_rows_raw
        ]
        registry_by_code = {
            row["canonical_event_code"]: row
            for row in registry_rows
        }

        print("Reading distinct eligible mark combinations...")

        cursor = con.execute(
            """
            SELECT
                m.canonical_event_code,
                m.canonical_event_name,
                m.event_family,
                e.mark_type,
                e.performance_direction,
                m.event_id,
                m.raw_event_label,
                p.mark,
                p.secondary_mark,
                COUNT(*) AS performance_count
            FROM canonical_person.main.canonical_person_performances AS p
            JOIN event_registry.main.event_label_map AS m
              ON CAST(p.event_id AS VARCHAR) = m.event_id
            JOIN event_registry.main.canonical_events AS e
              ON m.canonical_event_code = e.canonical_event_code
            WHERE m.development_model_eligible
            GROUP BY
                m.canonical_event_code,
                m.canonical_event_name,
                m.event_family,
                e.mark_type,
                e.performance_direction,
                m.event_id,
                m.raw_event_label,
                p.mark,
                p.secondary_mark
            ORDER BY
                m.canonical_event_code,
                performance_count DESC,
                p.mark,
                p.secondary_mark
            """
        )

        event_stats: dict[str, dict[str, Any]] = {}
        format_counts: Counter[tuple[str, str, str]] = Counter()
        status_counts: Counter[tuple[str, str, str]] = Counter()
        primary_unique_values: dict[str, set[str]] = defaultdict(set)
        secondary_unique_values: dict[str, set[str]] = defaultdict(set)
        failure_candidates: dict[
            str,
            list[dict[str, Any]],
        ] = defaultdict(list)
        paired_examples: dict[
            tuple[str, str],
            list[str],
        ] = defaultdict(list)

        for code, registry in registry_by_code.items():
            event_stats[code] = {
                "canonical_event_code": code,
                "canonical_event_name": registry["canonical_event_name"],
                "event_family": registry["event_family"],
                "event_subfamily": registry["event_subfamily"],
                "mark_type": registry["mark_type"],
                "performance_direction": registry[
                    "performance_direction"
                ],
                "registry_performance_count": int(
                    registry["performance_count"]
                ),
                "joined_performance_count": 0,
                "primary_blank_count": 0,
                "primary_status_count": 0,
                "primary_parseable_count": 0,
                "primary_unrecognized_count": 0,
                "primary_annotation_count": 0,
                "secondary_present_count": 0,
                "secondary_parseable_count": 0,
                "secondary_unrecognized_count": 0,
                "secondary_annotation_count": 0,
            }

        while True:
            batch = cursor.fetchmany(10_000)
            if not batch:
                break

            for (
                code,
                event_name,
                family,
                mark_type,
                direction,
                event_id,
                raw_label,
                mark,
                secondary_mark,
                count,
            ) in batch:
                count = int(count)
                stats = event_stats[code]
                stats["joined_performance_count"] += count

                primary = parse_mark(mark_type, mark)
                primary_token = normalize_mark(mark)
                primary_unique_values[code].add(primary_token)
                format_counts[(code, "primary", primary.parser_class)] += count

                if primary.parser_class == "blank":
                    stats["primary_blank_count"] += count
                elif primary.is_status:
                    stats["primary_status_count"] += count
                    status_counts[
                        (code, "primary", primary.parser_class)
                    ] += count
                elif primary.parseable:
                    stats["primary_parseable_count"] += count
                else:
                    stats["primary_unrecognized_count"] += count
                    failure_candidates[code].append(
                        {
                            "canonical_event_code": code,
                            "canonical_event_name": event_name,
                            "event_family": family,
                            "mark_type": mark_type,
                            "event_id": event_id,
                            "raw_event_label": raw_label,
                            "mark": "" if mark is None else str(mark),
                            "secondary_mark": (
                                ""
                                if secondary_mark is None
                                else str(secondary_mark)
                            ),
                            "primary_parser_class": primary.parser_class,
                            "normalized_primary_token": (
                                primary.normalized_token
                            ),
                            "performance_count": count,
                        }
                    )

                if primary.annotation_removed:
                    stats["primary_annotation_count"] += count

                secondary_token = normalize_mark(secondary_mark)
                if secondary_token:
                    stats["secondary_present_count"] += count
                    secondary_unique_values[code].add(secondary_token)
                    secondary = parse_mark(mark_type, secondary_mark)
                    format_counts[
                        (code, "secondary", secondary.parser_class)
                    ] += count

                    if secondary.is_status:
                        status_counts[
                            (code, "secondary", secondary.parser_class)
                        ] += count
                    elif secondary.parseable:
                        stats["secondary_parseable_count"] += count
                    else:
                        stats["secondary_unrecognized_count"] += count

                    if secondary.annotation_removed:
                        stats["secondary_annotation_count"] += count

                    pair_key = (
                        primary.parser_class,
                        secondary.parser_class,
                    )
                    examples_key = (code, " | ".join(pair_key))
                    if len(paired_examples[examples_key]) < 8:
                        paired_examples[examples_key].append(
                            f"{primary_token!r} -> {secondary_token!r} [{count:,}]"
                        )

        event_summary_rows: list[dict[str, Any]] = []
        event_count_mismatches = 0
        total_primary_parseable = 0
        total_primary_unrecognized = 0
        total_primary_status = 0
        total_primary_blank = 0

        for code in sorted(event_stats):
            row = event_stats[code]
            row["unique_primary_mark_values"] = len(
                primary_unique_values[code]
            )
            row["unique_secondary_mark_values"] = len(
                secondary_unique_values[code]
            )

            attempted = (
                row["joined_performance_count"]
                - row["primary_blank_count"]
                - row["primary_status_count"]
            )
            row["primary_parse_rate_excluding_blank_status"] = (
                round(row["primary_parseable_count"] / attempted, 8)
                if attempted > 0
                else ""
            )
            row["primary_unrecognized_rate_total"] = round(
                row["primary_unrecognized_count"]
                / row["joined_performance_count"],
                8,
            )
            row["registry_count_matches_join"] = (
                row["registry_performance_count"]
                == row["joined_performance_count"]
            )

            if not row["registry_count_matches_join"]:
                event_count_mismatches += 1

            total_primary_parseable += row["primary_parseable_count"]
            total_primary_unrecognized += row[
                "primary_unrecognized_count"
            ]
            total_primary_status += row["primary_status_count"]
            total_primary_blank += row["primary_blank_count"]

            event_summary_rows.append(row)

        add_check(
            checks,
            "every_event_count_matches_registry",
            event_count_mismatches == 0,
            event_count_mismatches,
            0,
        )
        add_check(
            checks,
            "all_eligible_events_have_rows",
            all(
                row["joined_performance_count"] > 0
                for row in event_summary_rows
            ),
            sum(
                row["joined_performance_count"] == 0
                for row in event_summary_rows
            ),
            0,
        )
        add_check(
            checks,
            "all_eligible_rows_classified",
            (
                total_primary_parseable
                + total_primary_unrecognized
                + total_primary_status
                + total_primary_blank
                == joined_count
            ),
            (
                total_primary_parseable
                + total_primary_unrecognized
                + total_primary_status
                + total_primary_blank
            ),
            joined_count,
        )

        format_rows: list[dict[str, Any]] = []
        for (code, mark_field, parser_class), count in sorted(
            format_counts.items(),
            key=lambda item: (
                item[0][0],
                item[0][1],
                -item[1],
                item[0][2],
            ),
        ):
            registry = registry_by_code[code]
            format_rows.append(
                {
                    "canonical_event_code": code,
                    "canonical_event_name": registry[
                        "canonical_event_name"
                    ],
                    "event_family": registry["event_family"],
                    "mark_type": registry["mark_type"],
                    "mark_field": mark_field,
                    "parser_class": parser_class,
                    "performance_count": count,
                }
            )

        status_rows: list[dict[str, Any]] = []
        for (code, mark_field, parser_class), count in sorted(
            status_counts.items(),
            key=lambda item: (
                item[0][0],
                item[0][1],
                -item[1],
                item[0][2],
            ),
        ):
            status_rows.append(
                {
                    "canonical_event_code": code,
                    "canonical_event_name": registry_by_code[code][
                        "canonical_event_name"
                    ],
                    "mark_field": mark_field,
                    "status_code": parser_class.removeprefix("status:"),
                    "performance_count": count,
                }
            )

        failure_rows: list[dict[str, Any]] = []
        for code, candidates in failure_candidates.items():
            candidates.sort(
                key=lambda row: (
                    -int(row["performance_count"]),
                    row["mark"],
                    row["secondary_mark"],
                )
            )
            failure_rows.extend(candidates[:30])

        paired_rows: list[dict[str, Any]] = []
        for (code, parser_pair), examples in sorted(
            paired_examples.items()
        ):
            paired_rows.append(
                {
                    "canonical_event_code": code,
                    "canonical_event_name": registry_by_code[code][
                        "canonical_event_name"
                    ],
                    "parser_class_pair": parser_pair,
                    "examples": " || ".join(examples),
                }
            )

        event_summary_fields = [
            "canonical_event_code",
            "canonical_event_name",
            "event_family",
            "event_subfamily",
            "mark_type",
            "performance_direction",
            "registry_performance_count",
            "joined_performance_count",
            "primary_blank_count",
            "primary_status_count",
            "primary_parseable_count",
            "primary_unrecognized_count",
            "primary_annotation_count",
            "primary_parse_rate_excluding_blank_status",
            "primary_unrecognized_rate_total",
            "unique_primary_mark_values",
            "secondary_present_count",
            "secondary_parseable_count",
            "secondary_unrecognized_count",
            "secondary_annotation_count",
            "unique_secondary_mark_values",
            "registry_count_matches_join",
        ]

        write_csv(
            output_dir / "event_mark_summary.csv",
            event_summary_rows,
            event_summary_fields,
        )
        write_csv(
            output_dir / "mark_format_profile.csv",
            format_rows,
            [
                "canonical_event_code",
                "canonical_event_name",
                "event_family",
                "mark_type",
                "mark_field",
                "parser_class",
                "performance_count",
            ],
        )
        write_csv(
            output_dir / "status_code_summary.csv",
            status_rows,
            [
                "canonical_event_code",
                "canonical_event_name",
                "mark_field",
                "status_code",
                "performance_count",
            ],
        )
        write_csv(
            output_dir / "unrecognized_mark_samples.csv",
            failure_rows,
            [
                "canonical_event_code",
                "canonical_event_name",
                "event_family",
                "mark_type",
                "event_id",
                "raw_event_label",
                "mark",
                "secondary_mark",
                "primary_parser_class",
                "normalized_primary_token",
                "performance_count",
            ],
        )
        write_csv(
            output_dir / "primary_secondary_examples.csv",
            paired_rows,
            [
                "canonical_event_code",
                "canonical_event_name",
                "parser_class_pair",
                "examples",
            ],
        )

        manifest_after = [
            manifest_row(name, path, "after")
            for name, path in inputs.items()
        ]
        before_by_name = {
            row["input_name"]: row
            for row in manifest_before
        }
        for row in manifest_after:
            before = before_by_name[row["input_name"]]
            unchanged = (
                row["size_bytes"] == before["size_bytes"]
                and row["mtime_epoch_ns"] == before["mtime_epoch_ns"]
                and row["sha256"] == before["sha256"]
            )
            add_check(
                checks,
                f"{row['input_name']}_unchanged",
                unchanged,
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

        failed = [
            check for check in checks
            if check["status"] == "FAIL"
        ]

        parse_attempts = (
            joined_count - total_primary_blank - total_primary_status
        )
        overall_parse_rate = (
            total_primary_parseable / parse_attempts
            if parse_attempts
            else 0.0
        )

        events_with_unrecognized = sum(
            row["primary_unrecognized_count"] > 0
            for row in event_summary_rows
        )

        report_lines = [
            "MILESTONE 5 PHASE 2A — ELIGIBLE MARK-FORMAT AUDIT",
            "=" * 78,
            f"Finished UTC: {utc_now()}",
            f"Profile version: {PROFILE_VERSION}",
            "",
            "INPUT SCALE",
            "-" * 78,
            f"Canonical eligible events: {canonical_event_count:,}",
            f"Included raw event labels: {included_label_count:,}",
            f"Eligible performances joined: {joined_count:,}",
            "",
            "PRIMARY MARK CLASSIFICATION",
            "-" * 78,
            f"Parseable candidates: {total_primary_parseable:,}",
            f"Status results: {total_primary_status:,}",
            f"Blank marks: {total_primary_blank:,}",
            f"Unrecognized candidates: {total_primary_unrecognized:,}",
            (
                "Candidate parse rate excluding blank/status: "
                f"{overall_parse_rate:.6%}"
            ),
            (
                "Events with at least one unrecognized primary mark: "
                f"{events_with_unrecognized:,}"
            ),
            "",
            "INTERPRETATION",
            "-" * 78,
            "This is a parser-design audit, not the production parsed table.",
            "Unrecognized marks are preserved in a focused sample file.",
            "Primary and secondary marks are profiled separately.",
            "No parse failure has been silently converted to a numeric value.",
            "",
            "HARD CHECK SUMMARY",
            "-" * 78,
            f"PASS: {sum(c['status'] == 'PASS' for c in checks)}",
            f"FAIL: {len(failed)}",
            "",
            "PHASE GATE",
            "-" * 78,
            (
                "PASS — Eligible mark formats are profiled for parser construction."
                if not failed
                else "FAIL — Correct input-contract or accounting errors."
            ),
            "",
            "OUTPUTS",
            "-" * 78,
            "event_mark_summary.csv",
            "mark_format_profile.csv",
            "status_code_summary.csv",
            "unrecognized_mark_samples.csv",
            "primary_secondary_examples.csv",
            "input_manifest.csv",
            "disk_space.csv",
            "hard_checks.csv",
        ]

        (output_dir / "mark_profile_report.txt").write_text(
            "\n".join(report_lines) + "\n",
            encoding="utf-8",
        )

        print()
        print(f"Eligible performances joined: {joined_count:,}")
        print(f"Parseable primary candidates: {total_primary_parseable:,}")
        print(f"Unrecognized primary candidates: {total_primary_unrecognized:,}")
        print(
            "Candidate parse rate excluding blank/status: "
            f"{overall_parse_rate:.6%}"
        )
        print()
        print("Created:")
        for filename in [
            "mark_profile_report.txt",
            "event_mark_summary.csv",
            "mark_format_profile.csv",
            "status_code_summary.csv",
            "unrecognized_mark_samples.csv",
            "primary_secondary_examples.csv",
            "input_manifest.csv",
            "disk_space.csv",
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
        print("Stop here and inspect unrecognized mark formats.")
        return 0

    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
