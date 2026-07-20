#!/usr/bin/env python3
"""
Milestone 5 Phase 2B — Build Parsed Performance Layer

Parses marks for all performances covered by the frozen 33-event registry.

Normalized values:
- running/hurdles/steeplechase: seconds
- jumps/throws: meters
- combined events: points

The script parses each distinct raw mark once, then joins that lookup back to
all eligible performances in DuckDB. Original columns and raw marks remain
unchanged. Non-performance statuses never receive numeric values.
"""

from __future__ import annotations

import csv
import hashlib
import math
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb
import pandas as pd


PARSER_VERSION = "mark_parser_v1"
EXPECTED_ROWS = 4_953_801
EXPECTED_EVENTS = 33
MIN_PARSE_RATE = 0.9999

CANONICAL_DB = Path(
    "data/processed/milestone4/canonical_person_layer_v1_1/"
    "canonical_person_layer_v1_1.duckdb"
)
REGISTRY_DB = Path(
    "data/processed/milestone5/event_registry_v1/final_v1/"
    "event_registry_v1.duckdb"
)
OUTPUT_DIR = Path(
    "data/processed/milestone5/mark_parsing_v1/parsed_v1"
)
OUTPUT_DB = OUTPUT_DIR / "parsed_performances_v1.duckdb"

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
    "NP",
    "ENR",
    "PASS",
}

COMMON_ANNOTATION_RE = re.compile(
    r"(?:\s*(?:[*+#@!]|\((?:A|C|H|HT|ALT|CONV)\)|"
    r"(?:ALT|CONV|HT|A|C|H|W)))+$",
    re.IGNORECASE,
)
TIME_HAND_SUFFIX_RE = re.compile(r"\.?h$", re.IGNORECASE)
TIME_SECONDS_RE = re.compile(r"^\d+(?:\.\d+)?$")
TIME_MINUTES_RE = re.compile(
    r"^(?P<minutes>\d{1,3}):(?P<seconds>\d{1,2}(?:\.\d+)?)$"
)
TIME_HOURS_RE = re.compile(
    r"^(?P<hours>\d{1,2}):(?P<minutes>\d{1,2}):"
    r"(?P<seconds>\d{1,2}(?:\.\d+)?)$"
)
METRIC_DISTANCE_RE = re.compile(
    r"^(?P<value>\d+(?:\.\d+)?)\s*"
    r"(?:m|meter|meters|metre|metres)?$",
    re.IGNORECASE,
)
FEET_INCHES_HYPHEN_RE = re.compile(
    r"^(?P<feet>\d{1,3})\s*-\s*"
    r"(?P<inches>\d{1,2}(?:\.\d+)?)$"
)
FEET_INCHES_QUOTES_RE = re.compile(
    r"^(?P<feet>\d{1,3})\s*['′]\s*"
    r"(?P<inches>\d{1,2}(?:\.\d+)?)\s*(?:[\"″])?$"
)
POINTS_RE = re.compile(r"^\d+(?:\.\d+)?$")


@dataclass(frozen=True)
class ParseResult:
    parse_state: str
    parser_class: str
    status_code: str | None
    normalized_token: str
    parsed_value: float | None
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


def query_dicts(
    con: duckdb.DuckDBPyConnection,
    sql: str,
) -> list[dict[str, Any]]:
    result = con.execute(sql)
    columns = [item[0] for item in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


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


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


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
    return re.sub(r"\s+", " ", text)


def normalized_status(value: Any) -> str:
    token = normalize_mark(value).upper().strip().strip(".")
    return re.sub(r"\s+", "", token)


def strip_common_annotations(token: str) -> tuple[str, bool]:
    current = token.strip()
    changed = False
    while current:
        updated = COMMON_ANNOTATION_RE.sub("", current).strip()
        if updated == current:
            break
        current = updated
        changed = True
    return current, changed


def parse_time(value: Any) -> ParseResult:
    original = normalize_mark(value)
    if not original:
        return ParseResult("blank", "blank", None, "", None, False)

    status = normalized_status(original)
    if status in STATUS_CODES:
        return ParseResult(
            "status",
            f"status:{status}",
            status,
            status,
            None,
            False,
        )

    token, annotation_removed = strip_common_annotations(original)

    hand_cleaned = TIME_HAND_SUFFIX_RE.sub("", token).strip()
    if hand_cleaned != token:
        token = hand_cleaned
        annotation_removed = True

    if token.endswith("."):
        token = token[:-1]
        annotation_removed = True

    match = TIME_HOURS_RE.fullmatch(token)
    if match:
        hours = float(match.group("hours"))
        minutes = float(match.group("minutes"))
        seconds = float(match.group("seconds"))
        if minutes < 60 and seconds < 60:
            value_seconds = hours * 3600 + minutes * 60 + seconds
            parser_class = (
                "hours_minutes_seconds_normalized"
                if annotation_removed
                else "hours_minutes_seconds"
            )
            return ParseResult(
                "parsed",
                parser_class,
                None,
                token,
                value_seconds,
                annotation_removed,
            )

    match = TIME_MINUTES_RE.fullmatch(token)
    if match:
        minutes = float(match.group("minutes"))
        seconds = float(match.group("seconds"))
        if seconds < 60:
            value_seconds = minutes * 60 + seconds
            parser_class = (
                "minutes_seconds_normalized"
                if annotation_removed
                else "minutes_seconds"
            )
            return ParseResult(
                "parsed",
                parser_class,
                None,
                token,
                value_seconds,
                annotation_removed,
            )

    if TIME_SECONDS_RE.fullmatch(token):
        seconds = float(token)
        if math.isfinite(seconds):
            parser_class = (
                "numeric_seconds_normalized"
                if annotation_removed
                else "numeric_seconds"
            )
            return ParseResult(
                "parsed",
                parser_class,
                None,
                token,
                seconds,
                annotation_removed,
            )

    return ParseResult(
        "unrecognized",
        "unrecognized",
        None,
        token,
        None,
        annotation_removed,
    )


def parse_distance(value: Any) -> ParseResult:
    original = normalize_mark(value)
    if not original:
        return ParseResult("blank", "blank", None, "", None, False)

    status = normalized_status(original)
    if status in STATUS_CODES:
        return ParseResult(
            "status",
            f"status:{status}",
            status,
            status,
            None,
            False,
        )

    token, annotation_removed = strip_common_annotations(original)

    match = METRIC_DISTANCE_RE.fullmatch(token)
    if match:
        meters = float(match.group("value"))
        parser_class = (
            "metric_distance_normalized"
            if annotation_removed
            else "metric_distance"
        )
        return ParseResult(
            "parsed",
            parser_class,
            None,
            token,
            meters,
            annotation_removed,
        )

    match = FEET_INCHES_HYPHEN_RE.fullmatch(token)
    if match is None:
        match = FEET_INCHES_QUOTES_RE.fullmatch(token)

    if match:
        feet = float(match.group("feet"))
        inches = float(match.group("inches"))
        if 0 <= inches < 12:
            meters = (feet * 12 + inches) * 0.0254
            parser_class = (
                "feet_inches_normalized"
                if annotation_removed
                else "feet_inches"
            )
            return ParseResult(
                "parsed",
                parser_class,
                None,
                token,
                meters,
                annotation_removed,
            )

    return ParseResult(
        "unrecognized",
        "unrecognized",
        None,
        token,
        None,
        annotation_removed,
    )


def parse_points(value: Any) -> ParseResult:
    original = normalize_mark(value)
    if not original:
        return ParseResult("blank", "blank", None, "", None, False)

    status = normalized_status(original)
    if status in STATUS_CODES:
        return ParseResult(
            "status",
            f"status:{status}",
            status,
            status,
            None,
            False,
        )

    token, annotation_removed = strip_common_annotations(original)
    if POINTS_RE.fullmatch(token):
        points = float(token)
        parser_class = (
            "numeric_points_normalized"
            if annotation_removed
            else "numeric_points"
        )
        return ParseResult(
            "parsed",
            parser_class,
            None,
            token,
            points,
            annotation_removed,
        )

    return ParseResult(
        "unrecognized",
        "unrecognized",
        None,
        token,
        None,
        annotation_removed,
    )


def parse_mark(mark_type: str, raw_value: Any) -> ParseResult:
    if mark_type == "time":
        return parse_time(raw_value)
    if mark_type == "distance":
        return parse_distance(raw_value)
    if mark_type == "points":
        return parse_points(raw_value)

    token = normalize_mark(raw_value)
    return ParseResult(
        "unrecognized",
        "unsupported_mark_type",
        None,
        token,
        None,
        False,
    )


def build_lookup(distinct_rows: list[tuple[str, str]]) -> pd.DataFrame:
    parsed_rows: list[dict[str, Any]] = []
    for mark_type, raw_mark_key in distinct_rows:
        result = parse_mark(mark_type, raw_mark_key)
        parsed_rows.append(
            {
                "mark_type": mark_type,
                "raw_mark_key": raw_mark_key,
                "normalized_token": result.normalized_token,
                "parse_state": result.parse_state,
                "status_code": result.status_code,
                "parser_class": result.parser_class,
                "parsed_value": result.parsed_value,
                "annotation_removed": result.annotation_removed,
            }
        )

    return pd.DataFrame(
        parsed_rows,
        columns=[
            "mark_type",
            "raw_mark_key",
            "normalized_token",
            "parse_state",
            "status_code",
            "parser_class",
            "parsed_value",
            "annotation_removed",
        ],
    )


def main() -> int:
    root = Path.cwd()
    canonical_path = root / CANONICAL_DB
    registry_path = root / REGISTRY_DB
    output_dir = root / OUTPUT_DIR
    output_db = root / OUTPUT_DB
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = {
        "canonical_person_database": canonical_path,
        "event_registry_database": registry_path,
    }
    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 2B — BUILD PARSED PERFORMANCE LAYER")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Parser version: {PARSER_VERSION}")
    print(f"Canonical DB: {canonical_path}")
    print(f"Registry DB: {registry_path}")
    print(f"Output DB: {output_db}")

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
    free_gib = disk.free / (1024**3)
    write_csv(
        output_dir / "disk_space.csv",
        [
            {
                "path": str(root),
                "total_bytes": disk.total,
                "used_bytes": disk.used,
                "free_bytes": disk.free,
                "free_gib": round(free_gib, 3),
            }
        ],
        ["path", "total_bytes", "used_bytes", "free_bytes", "free_gib"],
    )
    add_check(
        checks,
        "minimum_free_disk_space",
        free_gib >= 4.0,
        round(free_gib, 3),
        "at least 4.0 GiB",
        "The parsed DuckDB is written as a new compressed database.",
    )

    if output_db.exists():
        output_db.unlink()

    con = duckdb.connect(str(output_db))
    try:
        con.execute("PRAGMA threads=4")
        con.execute("PRAGMA enable_progress_bar=false")
        con.execute(
            f"ATTACH '{sql_path(canonical_path)}' "
            "AS canonical_person (READ_ONLY)"
        )
        con.execute(
            f"ATTACH '{sql_path(registry_path)}' "
            "AS event_registry (READ_ONLY)"
        )

        print("Reading distinct eligible raw marks...")
        distinct_rows = con.execute(
            """
            WITH eligible AS (
                SELECT
                    e.mark_type,
                    coalesce(CAST(p.mark AS VARCHAR), '') AS raw_mark_key,
                    coalesce(CAST(p.secondary_mark AS VARCHAR), '')
                        AS secondary_mark_key
                FROM canonical_person.main.canonical_person_performances AS p
                JOIN event_registry.main.event_label_map AS m
                  ON CAST(p.event_id AS VARCHAR) = m.event_id
                JOIN event_registry.main.canonical_events AS e
                  ON m.canonical_event_code = e.canonical_event_code
                WHERE m.development_model_eligible
            )
            SELECT DISTINCT mark_type, raw_mark_key
            FROM eligible
            UNION
            SELECT DISTINCT mark_type, secondary_mark_key
            FROM eligible
            """
        ).fetchall()

        print(f"Distinct mark/type combinations: {len(distinct_rows):,}")
        lookup_df = build_lookup(distinct_rows)
        con.register("mark_lookup", lookup_df)

        print("Creating parsed performance table...")
        con.execute(
            f"""
            CREATE TABLE main.parsed_performances AS
            SELECT
                p.*,
                '{PARSER_VERSION}'::VARCHAR AS mark_parser_version,
                m.canonical_event_code,
                m.canonical_event_name,
                e.event_family AS canonical_event_family,
                e.event_subfamily AS canonical_event_subfamily,
                e.mark_type,
                e.performance_direction,
                lp.normalized_token AS primary_mark_token,
                lp.parse_state AS primary_parse_state,
                lp.status_code AS primary_status_code,
                lp.parser_class AS primary_parser_class,
                lp.parsed_value AS primary_parsed_value,
                lp.annotation_removed AS primary_annotation_removed,
                CASE
                    WHEN e.mark_type = 'time' THEN 'seconds'
                    WHEN e.mark_type = 'distance' THEN 'meters'
                    WHEN e.mark_type = 'points' THEN 'points'
                    ELSE NULL
                END AS normalized_unit,
                ls.normalized_token AS secondary_mark_token,
                ls.parse_state AS secondary_parse_state,
                ls.status_code AS secondary_status_code,
                ls.parser_class AS secondary_parser_class,
                ls.parsed_value AS secondary_parsed_value,
                ls.annotation_removed AS secondary_annotation_removed
            FROM canonical_person.main.canonical_person_performances AS p
            JOIN event_registry.main.event_label_map AS m
              ON CAST(p.event_id AS VARCHAR) = m.event_id
            JOIN event_registry.main.canonical_events AS e
              ON m.canonical_event_code = e.canonical_event_code
            JOIN mark_lookup AS lp
              ON e.mark_type = lp.mark_type
             AND coalesce(CAST(p.mark AS VARCHAR), '') = lp.raw_mark_key
            JOIN mark_lookup AS ls
              ON e.mark_type = ls.mark_type
             AND coalesce(CAST(p.secondary_mark AS VARCHAR), '')
                 = ls.raw_mark_key
            WHERE m.development_model_eligible
            """
        )

        con.unregister("mark_lookup")

        con.execute(
            """
            CREATE UNIQUE INDEX parsed_performance_id_uq
            ON main.parsed_performances(canonical_person_performance_id)
            """
        )
        con.execute(
            """
            CREATE INDEX parsed_person_event_idx
            ON main.parsed_performances(
                canonical_person_id,
                canonical_event_code
            )
            """
        )

        print("Building parser audit tables...")
        con.execute(
            """
            CREATE TABLE main.event_parse_summary AS
            SELECT
                canonical_event_code,
                canonical_event_name,
                canonical_event_family,
                mark_type,
                normalized_unit,
                COUNT(*) AS performance_count,
                COUNT(*) FILTER (
                    WHERE primary_parse_state = 'parsed'
                ) AS parsed_count,
                COUNT(*) FILTER (
                    WHERE primary_parse_state = 'status'
                ) AS status_count,
                COUNT(*) FILTER (
                    WHERE primary_parse_state = 'blank'
                ) AS blank_count,
                COUNT(*) FILTER (
                    WHERE primary_parse_state = 'unrecognized'
                ) AS unrecognized_count,
                COUNT(*) FILTER (
                    WHERE secondary_parse_state = 'parsed'
                ) AS secondary_parsed_count,
                COUNT(*) FILTER (
                    WHERE secondary_parse_state = 'status'
                ) AS secondary_status_count,
                COUNT(*) FILTER (
                    WHERE secondary_parse_state = 'blank'
                ) AS secondary_blank_count,
                COUNT(*) FILTER (
                    WHERE secondary_parse_state = 'unrecognized'
                ) AS secondary_unrecognized_count,
                COUNT(*) FILTER (
                    WHERE primary_parse_state = 'parsed'
                )::DOUBLE
                /
                NULLIF(
                    COUNT(*) FILTER (
                        WHERE primary_parse_state IN (
                            'parsed', 'unrecognized'
                        )
                    ),
                    0
                ) AS parse_rate_excluding_status_blank,
                MIN(primary_parsed_value) FILTER (
                    WHERE primary_parse_state = 'parsed'
                ) AS min_parsed_value,
                MAX(primary_parsed_value) FILTER (
                    WHERE primary_parse_state = 'parsed'
                ) AS max_parsed_value
            FROM main.parsed_performances
            GROUP BY
                canonical_event_code,
                canonical_event_name,
                canonical_event_family,
                mark_type,
                normalized_unit
            ORDER BY canonical_event_code
            """
        )

        con.execute(
            """
            CREATE TABLE main.parser_class_summary AS
            SELECT
                canonical_event_code,
                primary_parse_state,
                primary_parser_class,
                COUNT(*) AS performance_count
            FROM main.parsed_performances
            GROUP BY
                canonical_event_code,
                primary_parse_state,
                primary_parser_class
            ORDER BY
                canonical_event_code,
                primary_parse_state,
                performance_count DESC
            """
        )

        con.execute(
            """
            CREATE TABLE main.unrecognized_marks AS
            SELECT
                canonical_person_performance_id,
                canonical_person_id,
                event_id,
                event,
                canonical_event_code,
                canonical_event_name,
                mark_type,
                mark,
                secondary_mark,
                primary_mark_token,
                primary_parser_class
            FROM main.parsed_performances
            WHERE primary_parse_state = 'unrecognized'
            ORDER BY canonical_event_code, primary_mark_token
            """
        )

        con.execute(
            """
            CREATE TABLE main.status_summary AS
            SELECT
                canonical_event_code,
                primary_status_code AS status_code,
                COUNT(*) AS performance_count
            FROM main.parsed_performances
            WHERE primary_parse_state = 'status'
            GROUP BY canonical_event_code, primary_status_code
            ORDER BY canonical_event_code, performance_count DESC
            """
        )

        overall = query_dicts(
            con,
            """
            SELECT
                COUNT(*) AS row_count,
                COUNT(DISTINCT canonical_event_code) AS event_count,
                COUNT(DISTINCT canonical_person_performance_id)
                    AS distinct_performance_ids,
                COUNT(*) FILTER (
                    WHERE primary_parse_state = 'parsed'
                ) AS parsed_count,
                COUNT(*) FILTER (
                    WHERE primary_parse_state = 'status'
                ) AS status_count,
                COUNT(*) FILTER (
                    WHERE primary_parse_state = 'blank'
                ) AS blank_count,
                COUNT(*) FILTER (
                    WHERE primary_parse_state = 'unrecognized'
                ) AS unrecognized_count,
                COUNT(*) FILTER (
                    WHERE primary_parse_state = 'parsed'
                      AND (
                        primary_parsed_value IS NULL
                        OR primary_parsed_value <= 0
                      )
                ) AS invalid_parsed_values,
                COUNT(*) FILTER (
                    WHERE primary_parse_state = 'status'
                      AND primary_parsed_value IS NOT NULL
                ) AS statuses_with_numeric_value,
                COUNT(*) FILTER (
                    WHERE primary_parse_state = 'unrecognized'
                      AND primary_parsed_value IS NOT NULL
                ) AS unrecognized_with_numeric_value
            FROM main.parsed_performances
            """,
        )[0]

        attempted = (
            int(overall["parsed_count"])
            + int(overall["unrecognized_count"])
        )
        parse_rate = (
            int(overall["parsed_count"]) / attempted
            if attempted
            else 0.0
        )

        newly_supported_failures = query_dicts(
            con,
            """
            SELECT COUNT(*) AS count
            FROM main.parsed_performances
            WHERE primary_parse_state = 'unrecognized'
              AND upper(regexp_replace(trim(CAST(mark AS VARCHAR)),
                  '[[:space:].]+', '', 'g')) IN ('NP', 'ENR', 'PASS')
            """,
        )[0]["count"]

        trailing_dot_failures = query_dicts(
            con,
            """
            SELECT COUNT(*) AS count
            FROM main.parsed_performances
            WHERE primary_parse_state = 'unrecognized'
              AND (
                  regexp_matches(trim(CAST(mark AS VARCHAR)),
                      '^[0-9]+[.]$')
                  OR regexp_matches(trim(CAST(mark AS VARCHAR)),
                      '^[0-9]{1,3}:[0-9]{1,2}[.]$')
                  OR regexp_matches(trim(CAST(mark AS VARCHAR)),
                      '^[0-9]{1,3}:[0-9]{1,2}[.]h$')
              )
            """,
        )[0]["count"]

        add_check(
            checks,
            "parsed_table_row_count",
            int(overall["row_count"]) == EXPECTED_ROWS,
            overall["row_count"],
            EXPECTED_ROWS,
        )
        add_check(
            checks,
            "parsed_table_event_count",
            int(overall["event_count"]) == EXPECTED_EVENTS,
            overall["event_count"],
            EXPECTED_EVENTS,
        )
        add_check(
            checks,
            "parsed_performance_ids_unique",
            int(overall["distinct_performance_ids"])
            == int(overall["row_count"]),
            int(overall["row_count"])
            - int(overall["distinct_performance_ids"]),
            0,
        )
        add_check(
            checks,
            "primary_parse_state_accounting",
            (
                int(overall["parsed_count"])
                + int(overall["status_count"])
                + int(overall["blank_count"])
                + int(overall["unrecognized_count"])
                == int(overall["row_count"])
            ),
            (
                int(overall["parsed_count"])
                + int(overall["status_count"])
                + int(overall["blank_count"])
                + int(overall["unrecognized_count"])
            ),
            overall["row_count"],
        )
        add_check(
            checks,
            "minimum_primary_parse_rate",
            parse_rate >= MIN_PARSE_RATE,
            f"{parse_rate:.8%}",
            f"at least {MIN_PARSE_RATE:.4%}",
        )
        add_check(
            checks,
            "parsed_values_positive_and_nonnull",
            int(overall["invalid_parsed_values"]) == 0,
            overall["invalid_parsed_values"],
            0,
        )
        add_check(
            checks,
            "statuses_never_receive_numeric_value",
            int(overall["statuses_with_numeric_value"]) == 0,
            overall["statuses_with_numeric_value"],
            0,
        )
        add_check(
            checks,
            "unrecognized_marks_never_receive_numeric_value",
            int(overall["unrecognized_with_numeric_value"]) == 0,
            overall["unrecognized_with_numeric_value"],
            0,
        )
        add_check(
            checks,
            "np_enr_pass_are_recognized_statuses",
            int(newly_supported_failures) == 0,
            newly_supported_failures,
            0,
        )
        add_check(
            checks,
            "trailing_dot_time_formats_are_parsed",
            int(trailing_dot_failures) == 0,
            trailing_dot_failures,
            0,
        )

        event_summary_rows = query_dicts(
            con,
            "SELECT * FROM main.event_parse_summary "
            "ORDER BY canonical_event_code",
        )
        parser_class_rows = query_dicts(
            con,
            "SELECT * FROM main.parser_class_summary "
            "ORDER BY canonical_event_code, primary_parse_state, "
            "performance_count DESC",
        )
        status_rows = query_dicts(
            con,
            "SELECT * FROM main.status_summary "
            "ORDER BY canonical_event_code, performance_count DESC",
        )
        unrecognized_rows = query_dicts(
            con,
            """
            SELECT
                canonical_event_code,
                canonical_event_name,
                mark_type,
                mark,
                secondary_mark,
                primary_mark_token,
                COUNT(*) AS performance_count
            FROM main.parsed_performances
            WHERE primary_parse_state = 'unrecognized'
            GROUP BY
                canonical_event_code,
                canonical_event_name,
                mark_type,
                mark,
                secondary_mark,
                primary_mark_token
            ORDER BY
                performance_count DESC,
                canonical_event_code,
                primary_mark_token
            LIMIT 500
            """,
        )

        write_csv(
            output_dir / "event_parse_summary.csv",
            event_summary_rows,
            list(event_summary_rows[0].keys()),
        )
        write_csv(
            output_dir / "parser_class_summary.csv",
            parser_class_rows,
            list(parser_class_rows[0].keys()),
        )
        write_csv(
            output_dir / "status_summary.csv",
            status_rows,
            (
                list(status_rows[0].keys())
                if status_rows
                else [
                    "canonical_event_code",
                    "status_code",
                    "performance_count",
                ]
            ),
        )
        write_csv(
            output_dir / "unrecognized_mark_summary.csv",
            unrecognized_rows,
            (
                list(unrecognized_rows[0].keys())
                if unrecognized_rows
                else [
                    "canonical_event_code",
                    "canonical_event_name",
                    "mark_type",
                    "mark",
                    "secondary_mark",
                    "primary_mark_token",
                    "performance_count",
                ]
            ),
        )

        manifest_after = [
            manifest_row(name, path, "after")
            for name, path in inputs.items()
        ]
        before_by_name = {
            row["input_name"]: row for row in manifest_before
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

        failed = [check for check in checks if check["status"] == "FAIL"]

        report_lines = [
            "MILESTONE 5 PHASE 2B — PARSED PERFORMANCE LAYER",
            "=" * 78,
            f"Finished UTC: {utc_now()}",
            f"Parser version: {PARSER_VERSION}",
            "",
            "OUTPUT SCALE",
            "-" * 78,
            f"Parsed-layer rows: {int(overall['row_count']):,}",
            f"Canonical events: {int(overall['event_count']):,}",
            f"Parsed primary marks: {int(overall['parsed_count']):,}",
            f"Status results: {int(overall['status_count']):,}",
            f"Blank primary marks: {int(overall['blank_count']):,}",
            f"Unrecognized primary marks: {int(overall['unrecognized_count']):,}",
            f"Parse rate excluding status/blank: {parse_rate:.8%}",
            "",
            "NORMALIZED UNITS",
            "-" * 78,
            "time -> seconds",
            "distance -> meters",
            "combined-event score -> points",
            "",
            "NEWLY SUPPORTED AUDIT FORMATS",
            "-" * 78,
            "NP, ENR, and PASS are explicit statuses.",
            "Times ending in a decimal point are normalized to .0.",
            "Hand-time forms ending in h or .h are normalized and retained.",
            "",
            "PRODUCTION CONTRACT",
            "-" * 78,
            "All raw canonical performance columns are preserved.",
            "Statuses and unrecognized marks never receive numeric values.",
            "Primary and secondary marks have separate parser fields.",
            "",
            "HARD CHECK SUMMARY",
            "-" * 78,
            f"PASS: {sum(c['status'] == 'PASS' for c in checks)}",
            f"FAIL: {len(failed)}",
            "",
            "PHASE GATE",
            "-" * 78,
            (
                "PASS — Parsed performance layer is ready for "
                "plausibility validation."
                if not failed
                else "FAIL — Correct parser or accounting errors."
            ),
        ]

        (output_dir / "parsed_layer_report.txt").write_text(
            "\n".join(report_lines) + "\n",
            encoding="utf-8",
        )

        print()
        print(f"Parsed-layer rows: {int(overall['row_count']):,}")
        print(f"Parsed primary marks: {int(overall['parsed_count']):,}")
        print(f"Status results: {int(overall['status_count']):,}")
        print(
            "Unrecognized primary marks: "
            f"{int(overall['unrecognized_count']):,}"
        )
        print(f"Parse rate excluding status/blank: {parse_rate:.8%}")
        print()
        print("Created:")
        for filename in [
            "parsed_performances_v1.duckdb",
            "parsed_layer_report.txt",
            "event_parse_summary.csv",
            "parser_class_summary.csv",
            "status_summary.csv",
            "unrecognized_mark_summary.csv",
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
        print("Next: event-specific plausibility and outlier validation.")
        return 0

    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
