#!/usr/bin/env python3
"""
Milestone 5 Phase 0 — read-only preflight and input contract.

This script:
- verifies repository state and immutable input paths;
- records SHA-256, size, and modification time before and after inspection;
- opens each DuckDB database in read-only mode;
- inventories tables, columns, declared constraints, row counts, and candidate keys;
- identifies likely source-performance, canonical-person, canonical-performance,
  school-stint, and performance-to-stint mapping tables;
- profiles event labels, mark formats, gender, season type, season year, school,
  and event-by-season coverage;
- verifies the Milestone 4 scale and the performance-to-stint input contract;
- writes all outputs under data/processed/milestone5/preflight_v1/.

No input database is modified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import duckdb
except ImportError as exc:
    raise SystemExit(
        "DuckDB is not installed in the active environment. "
        "Run: python -m pip install duckdb"
    ) from exc


EXPECTED = {
    "canonical_people": 192_561,
    "canonical_person_performances": 6_376_667,
    "d1_stint_performances": 6_376_505,
    "people_with_d1_stints": 170_655,
    "school_stints": 174_429,
}

DATABASES = {
    "source": Path("data/database/ncaa_track_analytics.duckdb"),
    "canonical_person": Path(
        "data/processed/milestone4/canonical_person_layer_v1_1/"
        "canonical_person_layer_v1_1.duckdb"
    ),
    "school_stint": Path(
        "data/processed/milestone4/final_school_stints_v1_1/"
        "final_school_stints_v1_1.duckdb"
    ),
}

PERFORMANCE_ID_CANDIDATES = (
    "canonical_person_performance_id",
    "performance_id",
    "result_id",
)
PERSON_ID_CANDIDATES = (
    "canonical_person_id",
    "person_id",
    "athlete_id",
)
STINT_ID_CANDIDATES = (
    "school_stint_id",
    "stint_id",
)
EVENT_CANDIDATES = (
    "raw_event",
    "event",
    "event_name",
    "canonical_event_name",
)
MARK_CANDIDATES = (
    "raw_mark",
    "mark",
    "performance_mark",
    "result_mark",
    "primary_mark",
)
GENDER_CANDIDATES = (
    "canonical_gender_code",
    "dominant_gender_code",
    "gender",
    "sex",
)
SEASON_TYPE_CANDIDATES = (
    "season_type",
    "season",
    "sport_season",
)
SEASON_YEAR_CANDIDATES = (
    "season_year",
    "year",
)
SCHOOL_CANDIDATES = (
    "canonical_school_name",
    "school_name",
    "school",
    "team_name",
)
TEAM_ID_CANDIDATES = (
    "canonical_team_id",
    "team_id",
    "school_id",
)
MEET_ID_CANDIDATES = (
    "meet_id",
)
DATE_CANDIDATES = (
    "meet_date",
    "performance_date",
    "meet_date_text",
)

PROFILE_COLUMN_GROUPS = {
    "performance_id": PERFORMANCE_ID_CANDIDATES,
    "person_id": PERSON_ID_CANDIDATES,
    "school_stint_id": STINT_ID_CANDIDATES,
    "event": EVENT_CANDIDATES,
    "mark": MARK_CANDIDATES,
    "gender": GENDER_CANDIDATES,
    "season_type": SEASON_TYPE_CANDIDATES,
    "season_year": SEASON_YEAR_CANDIDATES,
    "school": SCHOOL_CANDIDATES,
    "team_id": TEAM_ID_CANDIDATES,
    "meet_id": MEET_ID_CANDIDATES,
    "date": DATE_CANDIDATES,
}

ALLOWED_NEW_PATH_PREFIXES = (
    "src/analysis/milestone5/",
    "src/analysis/milestone5/inspect_milestone5_inputs.py",
    "data/processed/milestone5/preflight_v1/",
)


@dataclass(frozen=True)
class TableRef:
    database_key: str
    schema: str
    table: str
    table_type: str
    row_count: int | None

    @property
    def label(self) -> str:
        return f"{self.database_key}:{self.schema}.{self.table}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def qident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def qliteral(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def qualified_name(schema: str, table: str) -> str:
    return f"{qident(schema)}.{qident(table)}"


def attached_name(alias: str, schema: str, table: str) -> str:
    return f"{qident(alias)}.{qident(schema)}.{qident(table)}"


def run_git(project_root: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
    text = (proc.stdout or proc.stderr).strip()
    return proc.returncode, text


def parse_porcelain_paths(status_text: str) -> list[str]:
    paths: list[str] = []
    for line in status_text.splitlines():
        if not line.strip():
            continue
        payload = line[3:] if len(line) >= 4 else line
        if " -> " in payload:
            payload = payload.split(" -> ", 1)[1]
        paths.append(payload.strip().strip('"'))
    return paths


def is_allowed_new_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(
        normalized == prefix.rstrip("/") or normalized.startswith(prefix)
        for prefix in ALLOWED_NEW_PATH_PREFIXES
    )


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def file_manifest_row(database_key: str, path: Path, phase: str) -> dict[str, Any]:
    exists = path.exists()
    row: dict[str, Any] = {
        "database_key": database_key,
        "phase": phase,
        "path": str(path),
        "exists": exists,
        "size_bytes": None,
        "size_gib": None,
        "mtime_epoch_ns": None,
        "mtime_utc": None,
        "sha256": None,
    }
    if exists:
        stat = path.stat()
        row.update(
            {
                "size_bytes": stat.st_size,
                "size_gib": round(stat.st_size / (1024**3), 6),
                "mtime_epoch_ns": stat.st_mtime_ns,
                "mtime_utc": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(timespec="seconds"),
                "sha256": sha256_file(path),
            }
        )
    return row


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def first_matching_column(
    actual_columns: Iterable[str], candidates: Iterable[str]
) -> str | None:
    lookup = {column.lower(): column for column in actual_columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    return None


def all_matching_columns(
    actual_columns: Iterable[str], candidates: Iterable[str]
) -> list[str]:
    lookup = {column.lower(): column for column in actual_columns}
    return [lookup[c.lower()] for c in candidates if c.lower() in lookup]


def safe_scalar(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> tuple[Any, str | None]:
    try:
        value = con.execute(sql, params or []).fetchone()
        return (value[0] if value else None), None
    except Exception as exc:  # diagnostic script: preserve error text
        return None, f"{type(exc).__name__}: {exc}"


def safe_rows(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> tuple[list[tuple[Any, ...]], str | None]:
    try:
        return con.execute(sql, params or []).fetchall(), None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def add_check(
    checks: list[dict[str, Any]],
    name: str,
    status: str,
    observed: Any,
    expected: Any,
    details: str = "",
) -> None:
    checks.append(
        {
            "check_name": name,
            "status": status,
            "observed": observed,
            "expected": expected,
            "details": details,
        }
    )


def status_equal(observed: Any, expected: Any) -> str:
    return "PASS" if observed == expected else "FAIL"


def classify_mark(mark: str | None) -> str:
    if mark is None:
        return "NULL_OR_BLANK"
    value = str(mark).strip()
    if not value:
        return "NULL_OR_BLANK"

    upper = value.upper()
    status_tokens = {
        "DNF", "DNS", "DQ", "DSQ", "NM", "NH", "NT", "SCR",
        "FOUL", "PASS", "N/A", "NA", "--", "-", "XDQ",
    }
    if upper in status_tokens:
        return "STATUS_TOKEN"
    if re.fullmatch(r"\d{1,2}:\d{2}:\d{2}(?:\.\d+)?", value):
        return "TIME_HH_MM_SS"
    if re.fullmatch(r"\d{1,3}:\d{2}(?:\.\d+)?", value):
        return "TIME_MM_SS"
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
        return "PLAIN_NUMERIC"
    if re.search(r"(?:\d+\s*['′]\s*\d+(?:\.\d+)?\s*(?:[\"″])?)", value):
        return "FEET_INCHES"
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?\s*(?:m|cm|mm)", value, flags=re.I):
        return "METRIC_WITH_UNIT"
    if re.match(r"^[+-]?\d", value) and re.search(r"[A-Za-z*#@()]", value):
        return "ANNOTATED_NUMERIC"
    if re.match(r"^[+-]?\d", value):
        return "NUMERIC_WITH_SYMBOLS"
    return "OTHER_TEXT"


def table_column_map(
    column_rows: list[dict[str, Any]]
) -> dict[tuple[str, str, str], list[str]]:
    result: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for row in column_rows:
        key = (row["database_key"], row["table_schema"], row["table_name"])
        result[key].append(row["column_name"])
    return result


def table_row_map(
    table_rows: list[dict[str, Any]]
) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {
        (r["database_key"], r["table_schema"], r["table_name"]): r
        for r in table_rows
    }


def choose_role_table(
    database_key: str,
    role: str,
    table_rows: list[dict[str, Any]],
    columns_by_table: dict[tuple[str, str, str], list[str]],
) -> TableRef | None:
    candidates: list[tuple[float, TableRef]] = []

    role_target = {
        "source_performance": 6_594_540,
        "canonical_people": EXPECTED["canonical_people"],
        "canonical_performance": EXPECTED["canonical_person_performances"],
        "school_stints": EXPECTED["school_stints"],
        "stint_performance_map": EXPECTED["d1_stint_performances"],
    }[role]

    for row in table_rows:
        if row["database_key"] != database_key:
            continue
        key = (database_key, row["table_schema"], row["table_name"])
        columns = columns_by_table.get(key, [])
        performance_id = first_matching_column(columns, PERFORMANCE_ID_CANDIDATES)
        person_id = first_matching_column(columns, PERSON_ID_CANDIDATES)
        stint_id = first_matching_column(columns, STINT_ID_CANDIDATES)
        event_col = first_matching_column(columns, EVENT_CANDIDATES)
        mark_col = first_matching_column(columns, MARK_CANDIDATES)
        row_count = row.get("row_count")
        if row_count is None:
            continue

        required = False
        feature_score = 0.0

        if role == "source_performance":
            required = bool(performance_id and event_col and mark_col)
            feature_score += 6 * bool(performance_id)
            feature_score += 6 * bool(event_col)
            feature_score += 6 * bool(mark_col)
            feature_score += 1 * bool(first_matching_column(columns, SEASON_YEAR_CANDIDATES))
            feature_score += 1 * bool(first_matching_column(columns, SEASON_TYPE_CANDIDATES))
        elif role == "canonical_people":
            required = bool(person_id)
            feature_score += 8 * bool(person_id)
            feature_score -= 4 * bool(performance_id)
            feature_score -= 2 * bool(stint_id)
        elif role == "canonical_performance":
            required = bool(person_id and performance_id)
            feature_score += 7 * bool(person_id)
            feature_score += 7 * bool(performance_id)
            feature_score += 2 * bool(event_col)
            feature_score += 2 * bool(mark_col)
        elif role == "school_stints":
            required = bool(person_id and stint_id)
            feature_score += 7 * bool(person_id)
            feature_score += 7 * bool(stint_id)
            feature_score -= 2 * bool(performance_id)
        elif role == "stint_performance_map":
            required = bool(stint_id and performance_id)
            feature_score += 8 * bool(stint_id)
            feature_score += 8 * bool(performance_id)
            feature_score += 2 * bool(person_id)

        if not required:
            continue

        exact_bonus = 30.0 if row_count == role_target else 0.0
        relative_error = abs(row_count - role_target) / max(role_target, 1)
        count_score = max(0.0, 15.0 - 15.0 * min(relative_error, 1.0))
        name_text = f"{row['table_schema']}.{row['table_name']}".lower()
        name_bonus = 0.0
        for token in role.split("_"):
            if token in name_text:
                name_bonus += 0.5

        total = feature_score + exact_bonus + count_score + name_bonus
        candidates.append(
            (
                total,
                TableRef(
                    database_key=database_key,
                    schema=row["table_schema"],
                    table=row["table_name"],
                    table_type=row["table_type"],
                    row_count=row_count,
                ),
            )
        )

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1].row_count or 0), reverse=True)
    return candidates[0][1]


def profile_dimension(
    con: duckdb.DuckDBPyConnection,
    table: TableRef,
    column: str,
    database_path: str,
    dimension: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    table_sql = qualified_name(table.schema, table.table)
    limit_sql = f" LIMIT {int(limit)}" if limit else ""
    sql = f"""
        SELECT
            CAST({qident(column)} AS VARCHAR) AS dimension_value,
            COUNT(*) AS row_count
        FROM {table_sql}
        GROUP BY 1
        ORDER BY row_count DESC, dimension_value
        {limit_sql}
    """
    rows, error = safe_rows(con, sql)
    if error:
        return [
            {
                "section": "dimension_profile_error",
                "database_key": table.database_key,
                "database_path": database_path,
                "table_schema": table.schema,
                "table_name": table.table,
                "dimension": dimension,
                "value_1": None,
                "value_2": None,
                "row_count": None,
                "distinct_performance_count": None,
                "details": error,
            }
        ]
    return [
        {
            "section": "dimension_profile",
            "database_key": table.database_key,
            "database_path": database_path,
            "table_schema": table.schema,
            "table_name": table.table,
            "dimension": dimension,
            "value_1": value,
            "value_2": None,
            "row_count": count,
            "distinct_performance_count": None,
            "details": "",
        }
        for value, count in rows
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
        help="Repository root. Defaults to the project root inferred from this script.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory override.",
    )
    args = parser.parse_args()

    project_root = args.project_root.expanduser().resolve()
    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else project_root / "data/processed/milestone5/preflight_v1"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    started_at = utc_now()
    checks: list[dict[str, Any]] = []
    report_lines: list[str] = []

    report_lines.extend(
        [
            "MILESTONE 5 PHASE 0 — READ-ONLY PREFLIGHT AND INPUT CONTRACT",
            "=" * 72,
            f"Started UTC: {started_at}",
            f"Project root: {project_root}",
            f"Output directory: {output_dir}",
            f"Python: {sys.version.split()[0]}",
            f"DuckDB: {duckdb.__version__}",
            "",
        ]
    )

    # Repository state.
    branch_rc, branch = run_git(project_root, "branch", "--show-current")
    status_rc, porcelain = run_git(project_root, "status", "--porcelain")
    unexpected_paths = [
        path for path in parse_porcelain_paths(porcelain)
        if not is_allowed_new_path(path)
    ]
    add_check(
        checks,
        "git_repository_accessible",
        "PASS" if branch_rc == 0 and status_rc == 0 else "FAIL",
        f"branch_rc={branch_rc}; status_rc={status_rc}",
        "both return codes are 0",
    )
    add_check(
        checks,
        "git_branch_is_milestone_5",
        status_equal(branch, "milestone-5"),
        branch,
        "milestone-5",
    )
    add_check(
        checks,
        "no_unexpected_repository_changes",
        "PASS" if not unexpected_paths else "FAIL",
        "; ".join(unexpected_paths) if unexpected_paths else "none",
        "none, excluding the Phase 0 script and preflight outputs",
    )

    report_lines.extend(
        [
            "REPOSITORY STATE",
            "-" * 72,
            f"Branch: {branch or '<unavailable>'}",
            "Git status --porcelain:",
            porcelain or "<clean>",
            f"Unexpected paths: {unexpected_paths or 'none'}",
            "",
        ]
    )

    # Input paths and before manifest.
    absolute_db_paths = {
        key: (project_root / rel_path).resolve()
        for key, rel_path in DATABASES.items()
    }
    before_manifest = [
        file_manifest_row(key, path, "before")
        for key, path in absolute_db_paths.items()
    ]

    for row in before_manifest:
        add_check(
            checks,
            f"{row['database_key']}_database_exists",
            "PASS" if row["exists"] else "FAIL",
            row["exists"],
            True,
            row["path"],
        )

    # Inventory.
    table_rows: list[dict[str, Any]] = []
    column_rows: list[dict[str, Any]] = []
    constraint_lookup: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    read_only_open_status: dict[str, bool] = {}
    connections: dict[str, duckdb.DuckDBPyConnection] = {}

    for database_key, path in absolute_db_paths.items():
        if not path.exists():
            read_only_open_status[database_key] = False
            continue

        try:
            con = duckdb.connect(str(path), read_only=True)
            connections[database_key] = con
            read_only_open_status[database_key] = True
        except Exception as exc:
            read_only_open_status[database_key] = False
            report_lines.append(
                f"ERROR opening {database_key} read-only: {type(exc).__name__}: {exc}"
            )
            continue

        table_metadata, table_error = safe_rows(
            con,
            """
            SELECT table_schema, table_name, table_type
            FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name
            """,
        )
        if table_error:
            report_lines.append(
                f"ERROR inventorying tables in {database_key}: {table_error}"
            )
            continue

        constraints, constraint_error = safe_rows(
            con,
            """
            SELECT
                tc.table_schema,
                tc.table_name,
                tc.constraint_type,
                kcu.column_name
            FROM information_schema.table_constraints AS tc
            LEFT JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_catalog = kcu.constraint_catalog
             AND tc.constraint_schema = kcu.constraint_schema
             AND tc.constraint_name = kcu.constraint_name
            WHERE tc.table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY tc.table_schema, tc.table_name, tc.constraint_type, kcu.ordinal_position
            """,
        )
        if not constraint_error:
            for schema, table, constraint_type, column in constraints:
                if column is not None:
                    constraint_lookup[
                        (database_key, schema, table, column)
                    ].append(constraint_type)

        for schema, table, table_type in table_metadata:
            table_sql = qualified_name(schema, table)
            row_count, count_error = safe_scalar(
                con, f"SELECT COUNT(*) FROM {table_sql}"
            )
            cols, col_error = safe_rows(
                con,
                """
                SELECT
                    ordinal_position,
                    column_name,
                    data_type,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_schema = ? AND table_name = ?
                ORDER BY ordinal_position
                """,
                [schema, table],
            )
            actual_columns = [c[1] for c in cols]
            detected = {
                group: first_matching_column(actual_columns, candidates)
                for group, candidates in PROFILE_COLUMN_GROUPS.items()
            }
            suggested_roles = []
            if detected["performance_id"] and detected["event"] and detected["mark"]:
                suggested_roles.append("source_or_analytical_performance")
            if detected["person_id"] and detected["performance_id"]:
                suggested_roles.append("canonical_person_performance")
            if detected["person_id"] and detected["school_stint_id"] and not detected["performance_id"]:
                suggested_roles.append("school_stint")
            if detected["performance_id"] and detected["school_stint_id"]:
                suggested_roles.append("performance_to_stint_map")

            table_rows.append(
                {
                    "database_key": database_key,
                    "database_path": str(path),
                    "table_schema": schema,
                    "table_name": table,
                    "table_type": table_type,
                    "row_count": row_count,
                    "column_count": len(cols),
                    "count_status": "OK" if count_error is None else "ERROR",
                    "count_error": count_error or "",
                    "has_performance_id": bool(detected["performance_id"]),
                    "performance_id_column": detected["performance_id"],
                    "has_canonical_person_id": bool(
                        first_matching_column(actual_columns, ("canonical_person_id",))
                    ),
                    "person_id_column": detected["person_id"],
                    "has_school_stint_id": bool(detected["school_stint_id"]),
                    "school_stint_id_column": detected["school_stint_id"],
                    "event_column": detected["event"],
                    "mark_column": detected["mark"],
                    "gender_column": detected["gender"],
                    "season_type_column": detected["season_type"],
                    "season_year_column": detected["season_year"],
                    "school_column": detected["school"],
                    "team_id_column": detected["team_id"],
                    "meet_id_column": detected["meet_id"],
                    "date_column": detected["date"],
                    "suggested_roles": "|".join(suggested_roles),
                }
            )

            if col_error:
                report_lines.append(
                    f"ERROR inventorying columns in {database_key}:{schema}.{table}: {col_error}"
                )
                continue

            for ordinal, column, data_type, is_nullable, column_default in cols:
                is_candidate_key = any(
                    column.lower() in {c.lower() for c in candidates}
                    for candidates in (
                        PERFORMANCE_ID_CANDIDATES,
                        PERSON_ID_CANDIDATES,
                        STINT_ID_CANDIDATES,
                        TEAM_ID_CANDIDATES,
                        MEET_ID_CANDIDATES,
                    )
                )
                is_profile_dimension = any(
                    column.lower() in {c.lower() for c in candidates}
                    for candidates in PROFILE_COLUMN_GROUPS.values()
                )

                null_count = None
                distinct_count = None
                duplicate_count = None
                profile_status = "NOT_PROFILED"

                if is_candidate_key and row_count is not None:
                    profile_sql = f"""
                        SELECT
                            COUNT(*) FILTER (WHERE {qident(column)} IS NULL) AS null_count,
                            COUNT(DISTINCT {qident(column)}) AS distinct_count
                        FROM {table_sql}
                    """
                    profile_row, profile_error = safe_rows(con, profile_sql)
                    if profile_error:
                        profile_status = f"ERROR: {profile_error}"
                    elif profile_row:
                        null_count, distinct_count = profile_row[0]
                        duplicate_count = (
                            row_count - null_count - distinct_count
                            if row_count is not None
                            and null_count is not None
                            and distinct_count is not None
                            else None
                        )
                        profile_status = "OK"

                declared_constraints = "|".join(
                    constraint_lookup.get(
                        (database_key, schema, table, column), []
                    )
                )
                column_rows.append(
                    {
                        "database_key": database_key,
                        "database_path": str(path),
                        "table_schema": schema,
                        "table_name": table,
                        "ordinal_position": ordinal,
                        "column_name": column,
                        "data_type": data_type,
                        "is_nullable": is_nullable,
                        "column_default": column_default,
                        "declared_constraints": declared_constraints,
                        "is_candidate_key": is_candidate_key,
                        "is_profile_dimension": is_profile_dimension,
                        "null_count": null_count,
                        "distinct_count": distinct_count,
                        "duplicate_count": duplicate_count,
                        "profile_status": profile_status,
                    }
                )

    for database_key, opened in read_only_open_status.items():
        add_check(
            checks,
            f"{database_key}_opens_read_only",
            "PASS" if opened else "FAIL",
            opened,
            True,
        )

    columns_by_table = table_column_map(column_rows)
    rows_by_table = table_row_map(table_rows)

    # Identify authoritative candidate tables.
    role_tables: dict[str, TableRef | None] = {
        "source_performance": choose_role_table(
            "source", "source_performance", table_rows, columns_by_table
        ),
        "canonical_people": choose_role_table(
            "canonical_person", "canonical_people", table_rows, columns_by_table
        ),
        "canonical_performance": choose_role_table(
            "canonical_person", "canonical_performance", table_rows, columns_by_table
        ),
        "school_stints": choose_role_table(
            "school_stint", "school_stints", table_rows, columns_by_table
        ),
        "stint_performance_map": choose_role_table(
            "school_stint", "stint_performance_map", table_rows, columns_by_table
        ),
    }

    report_lines.extend(
        [
            "SELECTED ROLE TABLES",
            "-" * 72,
        ]
    )
    for role, table in role_tables.items():
        report_lines.append(
            f"{role}: {table.label if table else '<not identified>'}"
            + (f" [rows={table.row_count:,}]" if table and table.row_count is not None else "")
        )
        add_check(
            checks,
            f"{role}_table_identified",
            "PASS" if table else "FAIL",
            table.label if table else None,
            "one unambiguous candidate table",
        )
    report_lines.append("")

    # Validate expected table sizes.
    size_expectations = {
        "canonical_people": EXPECTED["canonical_people"],
        "canonical_performance": EXPECTED["canonical_person_performances"],
        "school_stints": EXPECTED["school_stints"],
        "stint_performance_map": EXPECTED["d1_stint_performances"],
    }
    for role, expected_count in size_expectations.items():
        table = role_tables.get(role)
        observed = table.row_count if table else None
        add_check(
            checks,
            f"{role}_row_count",
            status_equal(observed, expected_count),
            observed,
            expected_count,
            table.label if table else "table not identified",
        )

    # Exact key checks for selected tables.
    role_key_results: dict[str, dict[str, Any]] = {}
    for role, table in role_tables.items():
        if not table:
            continue
        con = connections[table.database_key]
        columns = columns_by_table[
            (table.database_key, table.schema, table.table)
        ]
        performance_col = first_matching_column(columns, PERFORMANCE_ID_CANDIDATES)
        person_col = first_matching_column(columns, PERSON_ID_CANDIDATES)
        stint_col = first_matching_column(columns, STINT_ID_CANDIDATES)
        role_key_results[role] = {}

        for key_name, column in (
            ("performance_id", performance_col),
            ("person_id", person_col),
            ("school_stint_id", stint_col),
        ):
            if not column:
                continue
            sql = f"""
                SELECT
                    COUNT(*) AS row_count,
                    COUNT(*) FILTER (WHERE {qident(column)} IS NULL) AS null_count,
                    COUNT(DISTINCT {qident(column)}) AS distinct_count
                FROM {qualified_name(table.schema, table.table)}
            """
            result, error = safe_rows(con, sql)
            if error or not result:
                role_key_results[role][key_name] = {"error": error}
                continue
            row_count, null_count, distinct_count = result[0]
            role_key_results[role][key_name] = {
                "column": column,
                "row_count": row_count,
                "null_count": null_count,
                "distinct_count": distinct_count,
                "duplicate_count": row_count - null_count - distinct_count,
            }

    canonical_perf_result = role_key_results.get(
        "canonical_performance", {}
    ).get("performance_id", {})
    if canonical_perf_result and "error" not in canonical_perf_result:
        add_check(
            checks,
            "canonical_performance_distinct_ids",
            status_equal(
                canonical_perf_result["distinct_count"],
                EXPECTED["canonical_person_performances"],
            ),
            canonical_perf_result["distinct_count"],
            EXPECTED["canonical_person_performances"],
            f"column={canonical_perf_result['column']}",
        )
        add_check(
            checks,
            "canonical_performance_id_duplicates",
            status_equal(canonical_perf_result["duplicate_count"], 0),
            canonical_perf_result["duplicate_count"],
            0,
            f"column={canonical_perf_result['column']}",
        )

    map_perf_result = role_key_results.get(
        "stint_performance_map", {}
    ).get("performance_id", {})
    map_stint_result = role_key_results.get(
        "stint_performance_map", {}
    ).get("school_stint_id", {})
    if map_perf_result and "error" not in map_perf_result:
        add_check(
            checks,
            "stint_map_distinct_eligible_performance_ids",
            status_equal(
                map_perf_result["distinct_count"],
                EXPECTED["d1_stint_performances"],
            ),
            map_perf_result["distinct_count"],
            EXPECTED["d1_stint_performances"],
            f"column={map_perf_result['column']}",
        )
        add_check(
            checks,
            "stint_map_duplicate_performance_assignments",
            status_equal(map_perf_result["duplicate_count"], 0),
            map_perf_result["duplicate_count"],
            0,
            f"column={map_perf_result['column']}",
        )
        add_check(
            checks,
            "stint_map_null_performance_ids",
            status_equal(map_perf_result["null_count"], 0),
            map_perf_result["null_count"],
            0,
            f"column={map_perf_result['column']}",
        )

    if map_stint_result and "error" not in map_stint_result:
        add_check(
            checks,
            "stint_map_null_school_stint_ids",
            status_equal(map_stint_result["null_count"], 0),
            map_stint_result["null_count"],
            0,
            f"column={map_stint_result['column']}",
        )

    school_stint_person_result = role_key_results.get(
        "school_stints", {}
    ).get("person_id", {})
    if school_stint_person_result and "error" not in school_stint_person_result:
        add_check(
            checks,
            "people_with_d1_stints",
            status_equal(
                school_stint_person_result["distinct_count"],
                EXPECTED["people_with_d1_stints"],
            ),
            school_stint_person_result["distinct_count"],
            EXPECTED["people_with_d1_stints"],
            f"column={school_stint_person_result['column']}",
        )

    # Determine join keys and validate joins across attached read-only databases.
    join_details: list[str] = []
    source_table = role_tables.get("source_performance")
    canonical_table = role_tables.get("canonical_performance")
    map_table = role_tables.get("stint_performance_map")

    source_map_row = rows_by_table.get(
        ("canonical_person", "main", "canonical_person_performance_map")
    )
    source_map_table = None
    if source_map_row is not None:
        source_map_table = TableRef(
            database_key="canonical_person",
            schema="main",
            table="canonical_person_performance_map",
            table_type=source_map_row["table_type"],
            row_count=source_map_row.get("row_count"),
        )

    source_to_map_key = None
    map_to_canonical_key = None
    canonical_to_map_key = None

    if source_table and source_map_table:
        source_columns = columns_by_table[
            (source_table.database_key, source_table.schema, source_table.table)
        ]
        source_map_columns = columns_by_table[
            (source_map_table.database_key, source_map_table.schema, source_map_table.table)
        ]
        left = first_matching_column(source_columns, ("performance_id",))
        right = first_matching_column(source_map_columns, ("performance_id",))
        if left and right:
            source_to_map_key = (left, right)

    if source_map_table and canonical_table:
        source_map_columns = columns_by_table[
            (source_map_table.database_key, source_map_table.schema, source_map_table.table)
        ]
        canonical_columns = columns_by_table[
            (canonical_table.database_key, canonical_table.schema, canonical_table.table)
        ]
        left = first_matching_column(
            source_map_columns, ("canonical_person_performance_id",)
        )
        right = first_matching_column(
            canonical_columns, ("canonical_person_performance_id",)
        )
        if left and right:
            map_to_canonical_key = (left, right)

    if canonical_table and map_table:
        canonical_columns = columns_by_table[
            (canonical_table.database_key, canonical_table.schema, canonical_table.table)
        ]
        map_columns = columns_by_table[
            (map_table.database_key, map_table.schema, map_table.table)
        ]
        for candidate in PERFORMANCE_ID_CANDIDATES:
            left = first_matching_column(canonical_columns, (candidate,))
            right = first_matching_column(map_columns, (candidate,))
            if left and right:
                canonical_to_map_key = (left, right)
                break

    add_check(
        checks,
        "source_to_canonical_join_key_identified",
        "PASS" if source_to_map_key and map_to_canonical_key else "FAIL",
        (source_to_map_key, map_to_canonical_key),
        "source.performance_id -> canonical map.performance_id -> canonical_person_performance_id",
    )
    add_check(
        checks,
        "canonical_to_stint_map_join_key_identified",
        "PASS" if canonical_to_map_key else "FAIL",
        canonical_to_map_key,
        "shared performance identifier",
    )

    if source_to_map_key and map_to_canonical_key:
        join_details.append(
            f"source -> canonical map: "
            f"{source_table.label}.{source_to_map_key[0]} = "
            f"{source_map_table.label}.{source_to_map_key[1]}"
        )
        join_details.append(
            f"canonical map -> canonical performance: "
            f"{source_map_table.label}.{map_to_canonical_key[0]} = "
            f"{canonical_table.label}.{map_to_canonical_key[1]}"
        )
    if canonical_to_map_key:
        join_details.append(
            f"canonical -> school-stint map: "
            f"{canonical_table.label}.{canonical_to_map_key[0]} = "
            f"{map_table.label}.{canonical_to_map_key[1]}"
        )

    if (source_to_map_key and map_to_canonical_key) or canonical_to_map_key:
        try:
            join_con = duckdb.connect(":memory:")
            aliases = {
                "source": "srcdb",
                "canonical_person": "cpdb",
                "school_stint": "stintdb",
            }
            for db_key, alias in aliases.items():
                path = absolute_db_paths[db_key]
                join_con.execute(
                    f"ATTACH {qliteral(str(path))} AS {qident(alias)} (READ_ONLY)"
                )

            if (
                source_to_map_key
                and map_to_canonical_key
                and source_table
                and source_map_table
                and canonical_table
            ):
                src_ref = attached_name(
                    aliases[source_table.database_key],
                    source_table.schema,
                    source_table.table,
                )
                source_map_ref = attached_name(
                    aliases[source_map_table.database_key],
                    source_map_table.schema,
                    source_map_table.table,
                )
                cp_ref = attached_name(
                    aliases[canonical_table.database_key],
                    canonical_table.schema,
                    canonical_table.table,
                )
                source_col, source_map_col = source_to_map_key
                source_map_cp_col, cp_col = map_to_canonical_key
                overlap_sql = f"""
                    SELECT COUNT(DISTINCT sm.{qident(source_map_cp_col)})
                    FROM {src_ref} AS s
                    INNER JOIN {source_map_ref} AS sm
                      ON s.{qident(source_col)} = sm.{qident(source_map_col)}
                    INNER JOIN {cp_ref} AS c
                      ON sm.{qident(source_map_cp_col)} = c.{qident(cp_col)}
                """
                overlap, error = safe_scalar(join_con, overlap_sql)
                join_details.append(
                    f"distinct canonical performance IDs reached from source: "
                    f"{overlap if error is None else error}"
                )
                add_check(
                    checks,
                    "source_join_path_reaches_all_canonical_performances",
                    status_equal(
                        overlap if error is None else None,
                        EXPECTED["canonical_person_performances"],
                    ),
                    overlap if error is None else error,
                    EXPECTED["canonical_person_performances"],
                )

            if canonical_to_map_key and canonical_table and map_table:
                cp_ref = attached_name(
                    aliases[canonical_table.database_key],
                    canonical_table.schema,
                    canonical_table.table,
                )
                map_ref = attached_name(
                    aliases[map_table.database_key],
                    map_table.schema,
                    map_table.table,
                )
                left_col, right_col = canonical_to_map_key
                overlap_sql = f"""
                    SELECT COUNT(DISTINCT m.{qident(right_col)})
                    FROM {map_ref} AS m
                    INNER JOIN {cp_ref} AS c
                      ON c.{qident(left_col)} = m.{qident(right_col)}
                """
                overlap, error = safe_scalar(join_con, overlap_sql)
                add_check(
                    checks,
                    "all_stint_mapped_performances_join_to_canonical",
                    status_equal(
                        overlap if error is None else None,
                        EXPECTED["d1_stint_performances"],
                    ),
                    overlap if error is None else error,
                    EXPECTED["d1_stint_performances"],
                )
                join_details.append(
                    f"distinct mapped IDs matched to canonical: "
                    f"{overlap if error is None else error}"
                )
            join_con.close()
        except Exception as exc:
            join_details.append(
                f"cross-database join audit error: {type(exc).__name__}: {exc}"
            )
            add_check(
                checks,
                "cross_database_join_audit",
                "FAIL",
                f"{type(exc).__name__}: {exc}",
                "successful read-only attached-database join audit",
            )
        else:
            add_check(
                checks,
                "cross_database_join_audit",
                "PASS",
                "completed",
                "completed",
            )

    report_lines.extend(
        [
            "JOIN CONTRACT",
            "-" * 72,
            *(join_details or ["No complete join path identified."]),
            "",
        ]
    )

    # Event inventory and mark-format inventory across every relevant table.
    event_inventory_rows: list[dict[str, Any]] = []
    mark_inventory_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []

    for table_row in table_rows:
        db_key = table_row["database_key"]
        con = connections.get(db_key)
        if con is None:
            continue

        key = (db_key, table_row["table_schema"], table_row["table_name"])
        columns = columns_by_table.get(key, [])
        table = TableRef(
            database_key=db_key,
            schema=table_row["table_schema"],
            table=table_row["table_name"],
            table_type=table_row["table_type"],
            row_count=table_row["row_count"],
        )
        path = str(absolute_db_paths[db_key])

        event_columns = all_matching_columns(columns, EVENT_CANDIDATES)
        for event_column in event_columns:
            sql = f"""
                SELECT
                    CAST({qident(event_column)} AS VARCHAR) AS raw_event,
                    COUNT(*) AS row_count
                FROM {qualified_name(table.schema, table.table)}
                GROUP BY 1
                ORDER BY row_count DESC, raw_event
            """
            rows, error = safe_rows(con, sql)
            if error:
                event_inventory_rows.append(
                    {
                        "database_key": db_key,
                        "database_path": path,
                        "table_schema": table.schema,
                        "table_name": table.table,
                        "event_column": event_column,
                        "raw_event": None,
                        "row_count": None,
                        "profile_status": "ERROR",
                        "details": error,
                    }
                )
            else:
                for raw_event, row_count in rows:
                    event_inventory_rows.append(
                        {
                            "database_key": db_key,
                            "database_path": path,
                            "table_schema": table.schema,
                            "table_name": table.table,
                            "event_column": event_column,
                            "raw_event": raw_event,
                            "row_count": row_count,
                            "profile_status": "OK",
                            "details": "",
                        }
                    )

        mark_columns = all_matching_columns(columns, MARK_CANDIDATES)
        for mark_column in mark_columns:
            sql = f"""
                SELECT
                    CAST({qident(mark_column)} AS VARCHAR) AS raw_mark,
                    COUNT(*) AS row_count
                FROM {qualified_name(table.schema, table.table)}
                GROUP BY 1
                ORDER BY row_count DESC, raw_mark
            """
            rows, error = safe_rows(con, sql)
            if error:
                mark_inventory_rows.append(
                    {
                        "database_key": db_key,
                        "database_path": path,
                        "table_schema": table.schema,
                        "table_name": table.table,
                        "mark_column": mark_column,
                        "mark_format": "ERROR",
                        "raw_mark_example": None,
                        "row_count": None,
                        "distinct_raw_marks": None,
                        "profile_status": "ERROR",
                        "details": error,
                    }
                )
                continue

            format_counts: dict[str, int] = defaultdict(int)
            format_examples: dict[str, list[str]] = defaultdict(list)
            format_distinct: dict[str, int] = defaultdict(int)
            for raw_mark, row_count in rows:
                category = classify_mark(raw_mark)
                format_counts[category] += int(row_count)
                format_distinct[category] += 1
                if len(format_examples[category]) < 10:
                    format_examples[category].append(
                        "<NULL>" if raw_mark is None else str(raw_mark)
                    )

            for category in sorted(format_counts):
                mark_inventory_rows.append(
                    {
                        "database_key": db_key,
                        "database_path": path,
                        "table_schema": table.schema,
                        "table_name": table.table,
                        "mark_column": mark_column,
                        "mark_format": category,
                        "raw_mark_example": " | ".join(format_examples[category]),
                        "row_count": format_counts[category],
                        "distinct_raw_marks": format_distinct[category],
                        "profile_status": "OK",
                        "details": "",
                    }
                )

    # Select the richest performance table for coverage profiling.
    profile_candidates: list[tuple[int, int, TableRef]] = []
    for row in table_rows:
        key = (row["database_key"], row["table_schema"], row["table_name"])
        columns = columns_by_table.get(key, [])
        if not (
            first_matching_column(columns, EVENT_CANDIDATES)
            and first_matching_column(columns, MARK_CANDIDATES)
        ):
            continue
        richness = sum(
            bool(first_matching_column(columns, candidates))
            for candidates in (
                PERFORMANCE_ID_CANDIDATES,
                PERSON_ID_CANDIDATES,
                STINT_ID_CANDIDATES,
                GENDER_CANDIDATES,
                SEASON_TYPE_CANDIDATES,
                SEASON_YEAR_CANDIDATES,
                SCHOOL_CANDIDATES,
                TEAM_ID_CANDIDATES,
                MEET_ID_CANDIDATES,
            )
        )
        db_preference = {
            "school_stint": 3,
            "canonical_person": 2,
            "source": 1,
        }[row["database_key"]]
        profile_candidates.append(
            (
                richness * 10 + db_preference,
                row["row_count"] or 0,
                TableRef(
                    row["database_key"],
                    row["table_schema"],
                    row["table_name"],
                    row["table_type"],
                    row["row_count"],
                ),
            )
        )

    primary_profile_table = None
    if profile_candidates:
        profile_candidates.sort(
            key=lambda item: (item[0], item[1]), reverse=True
        )
        primary_profile_table = profile_candidates[0][2]

    add_check(
        checks,
        "primary_profile_table_identified",
        "PASS" if primary_profile_table else "FAIL",
        primary_profile_table.label if primary_profile_table else None,
        "table containing event and mark plus analytical dimensions",
    )

    if primary_profile_table:
        con = connections[primary_profile_table.database_key]
        key = (
            primary_profile_table.database_key,
            primary_profile_table.schema,
            primary_profile_table.table,
        )
        columns = columns_by_table[key]
        path = str(absolute_db_paths[primary_profile_table.database_key])

        selected_dimensions = {
            group: first_matching_column(columns, candidates)
            for group, candidates in PROFILE_COLUMN_GROUPS.items()
        }

        for required_dimension in (
            "event",
            "mark",
            "gender",
            "season_type",
            "season_year",
        ):
            add_check(
                checks,
                f"primary_profile_has_{required_dimension}",
                "PASS" if selected_dimensions[required_dimension] else "FAIL",
                selected_dimensions[required_dimension],
                f"a recognized {required_dimension} column",
                primary_profile_table.label,
            )

        for dimension in (
            "gender",
            "season_type",
            "season_year",
            "school",
            "team_id",
        ):
            column = selected_dimensions.get(dimension)
            if column:
                coverage_rows.extend(
                    profile_dimension(
                        con,
                        primary_profile_table,
                        column,
                        path,
                        dimension,
                    )
                )

        event_col = selected_dimensions.get("event")
        season_type_col = selected_dimensions.get("season_type")
        season_year_col = selected_dimensions.get("season_year")
        perf_col = selected_dimensions.get("performance_id")

        if event_col and season_type_col and season_year_col:
            distinct_perf_expr = (
                f"COUNT(DISTINCT {qident(perf_col)})"
                if perf_col
                else "NULL"
            )
            sql = f"""
                SELECT
                    CAST({qident(event_col)} AS VARCHAR) AS event_value,
                    CAST({qident(season_type_col)} AS VARCHAR) AS season_type_value,
                    CAST({qident(season_year_col)} AS VARCHAR) AS season_year_value,
                    COUNT(*) AS row_count,
                    {distinct_perf_expr} AS distinct_performance_count
                FROM {qualified_name(primary_profile_table.schema, primary_profile_table.table)}
                GROUP BY 1, 2, 3
                ORDER BY 1, 2, 3
            """
            rows, error = safe_rows(con, sql)
            if error:
                coverage_rows.append(
                    {
                        "section": "event_by_season_error",
                        "database_key": primary_profile_table.database_key,
                        "database_path": path,
                        "table_schema": primary_profile_table.schema,
                        "table_name": primary_profile_table.table,
                        "dimension": "event_by_season",
                        "value_1": None,
                        "value_2": None,
                        "row_count": None,
                        "distinct_performance_count": None,
                        "details": error,
                    }
                )
            else:
                for (
                    event_value,
                    season_type_value,
                    season_year_value,
                    row_count,
                    distinct_performance_count,
                ) in rows:
                    coverage_rows.append(
                        {
                            "section": "event_by_season",
                            "database_key": primary_profile_table.database_key,
                            "database_path": path,
                            "table_schema": primary_profile_table.schema,
                            "table_name": primary_profile_table.table,
                            "dimension": "event_by_season",
                            "value_1": event_value,
                            "value_2": (
                                f"{season_type_value}|{season_year_value}"
                            ),
                            "row_count": row_count,
                            "distinct_performance_count": distinct_performance_count,
                            "details": "",
                        }
                    )

        report_lines.extend(
            [
                "PRIMARY COVERAGE PROFILE SOURCE",
                "-" * 72,
                f"Table: {primary_profile_table.label}",
                f"Rows: {primary_profile_table.row_count:,}",
                "Detected columns:",
            ]
        )
        for dimension, column in selected_dimensions.items():
            report_lines.append(f"  {dimension}: {column or '<not found>'}")
        report_lines.append("")

    # Close all input connections before final file checks.
    for con in connections.values():
        con.close()

    after_manifest = [
        file_manifest_row(key, path, "after")
        for key, path in absolute_db_paths.items()
    ]
    before_by_key = {row["database_key"]: row for row in before_manifest}
    after_by_key = {row["database_key"]: row for row in after_manifest}

    for database_key in DATABASES:
        before = before_by_key[database_key]
        after = after_by_key[database_key]
        for field in ("size_bytes", "mtime_epoch_ns", "sha256"):
            add_check(
                checks,
                f"{database_key}_{field}_unchanged",
                status_equal(before[field], after[field]),
                after[field],
                before[field],
                str(absolute_db_paths[database_key]),
            )

    manifest_rows = before_manifest + after_manifest

    # Disk space.
    disk = shutil.disk_usage(project_root)
    coverage_rows.extend(
        [
            {
                "section": "disk_space",
                "database_key": None,
                "database_path": str(project_root),
                "table_schema": None,
                "table_name": None,
                "dimension": "disk_total_bytes",
                "value_1": disk.total,
                "value_2": None,
                "row_count": None,
                "distinct_performance_count": None,
                "details": "",
            },
            {
                "section": "disk_space",
                "database_key": None,
                "database_path": str(project_root),
                "table_schema": None,
                "table_name": None,
                "dimension": "disk_used_bytes",
                "value_1": disk.used,
                "value_2": None,
                "row_count": None,
                "distinct_performance_count": None,
                "details": "",
            },
            {
                "section": "disk_space",
                "database_key": None,
                "database_path": str(project_root),
                "table_schema": None,
                "table_name": None,
                "dimension": "disk_free_bytes",
                "value_1": disk.free,
                "value_2": None,
                "row_count": None,
                "distinct_performance_count": None,
                "details": "",
            },
        ]
    )

    # Final report summary.
    pass_count = sum(check["status"] == "PASS" for check in checks)
    fail_count = sum(check["status"] == "FAIL" for check in checks)
    other_count = len(checks) - pass_count - fail_count
    finished_at = utc_now()

    report_lines.extend(
        [
            "EXPECTED MILESTONE 4 SCALE",
            "-" * 72,
            *(f"{name}: {value:,}" for name, value in EXPECTED.items()),
            "",
            "HARD CHECK SUMMARY",
            "-" * 72,
            f"PASS: {pass_count}",
            f"FAIL: {fail_count}",
            f"OTHER: {other_count}",
            f"Overall status: {'PASS' if fail_count == 0 else 'FAIL'}",
            "",
            "INPUT IMMUTABILITY",
            "-" * 72,
        ]
    )
    for database_key in DATABASES:
        before = before_by_key[database_key]
        after = after_by_key[database_key]
        report_lines.extend(
            [
                f"{database_key}:",
                f"  path: {before['path']}",
                f"  size before/after: {before['size_bytes']} / {after['size_bytes']}",
                f"  mtime ns before/after: "
                f"{before['mtime_epoch_ns']} / {after['mtime_epoch_ns']}",
                f"  SHA-256 before: {before['sha256']}",
                f"  SHA-256 after:  {after['sha256']}",
            ]
        )
    report_lines.extend(
        [
            "",
            f"Finished UTC: {finished_at}",
            "",
            "PHASE GATE",
            "-" * 72,
            (
                "PASS — Phase 0 input contract is ready for review."
                if fail_count == 0
                else "FAIL — Do not begin event normalization. Review failed checks."
            ),
            "",
        ]
    )

    # Output files.
    write_csv(
        output_dir / "database_manifest.csv",
        manifest_rows,
        [
            "database_key",
            "phase",
            "path",
            "exists",
            "size_bytes",
            "size_gib",
            "mtime_epoch_ns",
            "mtime_utc",
            "sha256",
        ],
    )
    write_csv(
        output_dir / "table_inventory.csv",
        table_rows,
        [
            "database_key",
            "database_path",
            "table_schema",
            "table_name",
            "table_type",
            "row_count",
            "column_count",
            "count_status",
            "count_error",
            "has_performance_id",
            "performance_id_column",
            "has_canonical_person_id",
            "person_id_column",
            "has_school_stint_id",
            "school_stint_id_column",
            "event_column",
            "mark_column",
            "gender_column",
            "season_type_column",
            "season_year_column",
            "school_column",
            "team_id_column",
            "meet_id_column",
            "date_column",
            "suggested_roles",
        ],
    )
    write_csv(
        output_dir / "column_inventory.csv",
        column_rows,
        [
            "database_key",
            "database_path",
            "table_schema",
            "table_name",
            "ordinal_position",
            "column_name",
            "data_type",
            "is_nullable",
            "column_default",
            "declared_constraints",
            "is_candidate_key",
            "is_profile_dimension",
            "null_count",
            "distinct_count",
            "duplicate_count",
            "profile_status",
        ],
    )
    write_csv(
        output_dir / "event_inventory.csv",
        event_inventory_rows,
        [
            "database_key",
            "database_path",
            "table_schema",
            "table_name",
            "event_column",
            "raw_event",
            "row_count",
            "profile_status",
            "details",
        ],
    )
    write_csv(
        output_dir / "mark_inventory.csv",
        mark_inventory_rows,
        [
            "database_key",
            "database_path",
            "table_schema",
            "table_name",
            "mark_column",
            "mark_format",
            "raw_mark_example",
            "row_count",
            "distinct_raw_marks",
            "profile_status",
            "details",
        ],
    )
    write_csv(
        output_dir / "coverage_summary.csv",
        coverage_rows,
        [
            "section",
            "database_key",
            "database_path",
            "table_schema",
            "table_name",
            "dimension",
            "value_1",
            "value_2",
            "row_count",
            "distinct_performance_count",
            "details",
        ],
    )
    write_csv(
        output_dir / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )
    (output_dir / "milestone5_input_report.txt").write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    print("\n".join(report_lines[-18:]))
    print("Created:")
    for filename in (
        "milestone5_input_report.txt",
        "database_manifest.csv",
        "table_inventory.csv",
        "column_inventory.csv",
        "event_inventory.csv",
        "mark_inventory.csv",
        "coverage_summary.csv",
        "hard_checks.csv",
    ):
        print(f"  {output_dir / filename}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
