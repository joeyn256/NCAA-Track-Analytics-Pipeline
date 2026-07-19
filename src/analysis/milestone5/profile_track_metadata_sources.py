#!/usr/bin/env python3
"""
Milestone 5 Phase 2E-1 — Track Metadata Source Preflight

Inspects the existing Milestone 3–5 databases to determine the authoritative
sources for:
- athlete/team gender;
- indoor versus outdoor season;
- performance date and season year;
- school-stint attribution;
- meet and team metadata.

This is read-only. It does not build the final track scoring table.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


PREFLIGHT_VERSION = "track_metadata_preflight_v1"

PARSED_DB = Path(
    "data/processed/milestone5/mark_parsing_v1/"
    "parsed_v1/parsed_performances_v1.duckdb"
)
VALIDITY_DB = Path(
    "data/processed/milestone5/mark_parsing_v1/"
    "plausibility_v1/performance_validity_v1.duckdb"
)
CANONICAL_DB = Path(
    "data/processed/milestone4/canonical_person_layer_v1_1/"
    "canonical_person_layer_v1_1.duckdb"
)
STINT_DB = Path(
    "data/processed/milestone4/final_school_stints_v1_1/"
    "final_school_stints_v1_1.duckdb"
)
CORE_DB = Path(
    "data/database/ncaa_track_analytics.duckdb"
)
OUTPUT_DIR = Path(
    "data/processed/milestone5/track_metadata_v1/preflight_v1"
)

EXPECTED_PARSED_ROWS = 4_953_801
EXPECTED_VALIDITY_ROWS = 4_953_801

GENDER_KEYWORDS = (
    "gender",
    "sex",
    "men",
    "women",
    "male",
    "female",
)
SEASON_KEYWORDS = (
    "season",
    "indoor",
    "outdoor",
    "sport",
)
DATE_KEYWORDS = (
    "date",
    "year",
)
SCHOOL_KEYWORDS = (
    "school",
    "institution",
    "team",
    "stint",
    "affiliation",
)
MEET_KEYWORDS = (
    "meet",
    "competition",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(block_size):
            digest.update(chunk)
    return digest.hexdigest()


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


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


def contains_keyword(name: str, keywords: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(keyword in lowered for keyword in keywords)


def classify_column(name: str) -> str:
    categories: list[str] = []
    if contains_keyword(name, GENDER_KEYWORDS):
        categories.append("gender")
    if contains_keyword(name, SEASON_KEYWORDS):
        categories.append("season")
    if contains_keyword(name, DATE_KEYWORDS):
        categories.append("date")
    if contains_keyword(name, SCHOOL_KEYWORDS):
        categories.append("school")
    if contains_keyword(name, MEET_KEYWORDS):
        categories.append("meet")
    return "|".join(categories)


def sample_values_sql(
    catalog: str,
    schema: str,
    table: str,
    column: str,
) -> str:
    qcol = '"' + column.replace('"', '""') + '"'
    return f"""
        SELECT
            CAST({qcol} AS VARCHAR) AS value,
            COUNT(*) AS row_count
        FROM {catalog}.{schema}.{table}
        WHERE {qcol} IS NOT NULL
          AND trim(CAST({qcol} AS VARCHAR)) <> ''
        GROUP BY 1
        ORDER BY row_count DESC, value
        LIMIT 20
    """


def main() -> int:
    root = Path.cwd()
    output_dir = root / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    databases = {
        "parsed": root / PARSED_DB,
        "validity": root / VALIDITY_DB,
        "canonical": root / CANONICAL_DB,
        "stints": root / STINT_DB,
        "core": root / CORE_DB,
    }

    checks: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 2E-1 — TRACK METADATA SOURCE PREFLIGHT")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Preflight version: {PREFLIGHT_VERSION}")
    print(f"Output: {output_dir}")

    for name, path in databases.items():
        exists = path.exists()
        add_check(
            checks,
            f"{name}_database_exists",
            exists,
            exists,
            True,
            str(path),
        )
        if exists:
            stat = path.stat()
            manifest_rows.append(
                {
                    "database_name": name,
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "mtime_epoch_ns": stat.st_mtime_ns,
                    "sha256": sha256_file(path),
                }
            )

    if any(not path.exists() for path in databases.values()):
        write_csv(
            output_dir / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — One or more required databases are missing.")
        return 1

    con = duckdb.connect(":memory:")
    try:
        for name, path in databases.items():
            con.execute(
                f"ATTACH '{sql_path(path)}' AS {name} (READ_ONLY)"
            )

        table_rows = query_dicts(
            con,
            """
            SELECT
                table_catalog AS database_name,
                table_schema,
                table_name,
                table_type
            FROM information_schema.tables
            WHERE table_catalog IN (
                'parsed', 'validity', 'canonical', 'stints', 'core'
            )
            ORDER BY
                table_catalog,
                table_schema,
                table_name
            """,
        )
        write_csv(
            output_dir / "database_tables.csv",
            table_rows,
            [
                "database_name",
                "table_schema",
                "table_name",
                "table_type",
            ],
        )

        column_rows = query_dicts(
            con,
            """
            SELECT
                table_catalog AS database_name,
                table_schema,
                table_name,
                ordinal_position,
                column_name,
                data_type,
                is_nullable
            FROM information_schema.columns
            WHERE table_catalog IN (
                'parsed', 'validity', 'canonical', 'stints', 'core'
            )
            ORDER BY
                table_catalog,
                table_schema,
                table_name,
                ordinal_position
            """,
        )

        candidate_columns: list[dict[str, Any]] = []
        for row in column_rows:
            category = classify_column(row["column_name"])
            if not category:
                continue
            candidate_columns.append(
                {
                    **row,
                    "candidate_category": category,
                }
            )

        write_csv(
            output_dir / "metadata_candidate_columns.csv",
            candidate_columns,
            [
                "database_name",
                "table_schema",
                "table_name",
                "ordinal_position",
                "column_name",
                "data_type",
                "is_nullable",
                "candidate_category",
            ],
        )

        # Sample values only for likely categorical/date metadata fields.
        value_profile_rows: list[dict[str, Any]] = []
        profile_errors: list[dict[str, Any]] = []

        for row in candidate_columns:
            database_name = row["database_name"]
            schema = row["table_schema"]
            table = row["table_name"]
            column = row["column_name"]
            category = row["candidate_category"]

            # Skip obviously high-cardinality IDs and names.
            lowered = column.lower()
            if lowered.endswith("_id") or lowered in {
                "school_name",
                "institution_name",
                "team_name",
                "meet_name",
                "competition_name",
            }:
                continue

            try:
                samples = query_dicts(
                    con,
                    sample_values_sql(
                        database_name,
                        schema,
                        table,
                        column,
                    ),
                )
                for sample in samples:
                    value_profile_rows.append(
                        {
                            "database_name": database_name,
                            "table_schema": schema,
                            "table_name": table,
                            "column_name": column,
                            "candidate_category": category,
                            "sample_value": sample["value"],
                            "row_count": sample["row_count"],
                        }
                    )
            except Exception as exc:
                profile_errors.append(
                    {
                        "database_name": database_name,
                        "table_schema": schema,
                        "table_name": table,
                        "column_name": column,
                        "error": str(exc),
                    }
                )

        write_csv(
            output_dir / "metadata_value_profiles.csv",
            value_profile_rows,
            [
                "database_name",
                "table_schema",
                "table_name",
                "column_name",
                "candidate_category",
                "sample_value",
                "row_count",
            ],
        )
        write_csv(
            output_dir / "metadata_profile_errors.csv",
            profile_errors,
            [
                "database_name",
                "table_schema",
                "table_name",
                "column_name",
                "error",
            ],
        )

        parsed_count = con.execute(
            "SELECT COUNT(*) FROM parsed.main.parsed_performances"
        ).fetchone()[0]
        validity_count = con.execute(
            "SELECT COUNT(*) FROM validity.main.performance_validity"
        ).fetchone()[0]
        stint_count = con.execute(
            "SELECT COUNT(*) FROM stints.main.analytical_school_stints"
        ).fetchone()[0]
        stint_map_count = con.execute(
            """
            SELECT COUNT(*)
            FROM stints.main.school_stint_performance_map
            """
        ).fetchone()[0]

        add_check(
            checks,
            "parsed_row_count",
            parsed_count == EXPECTED_PARSED_ROWS,
            parsed_count,
            EXPECTED_PARSED_ROWS,
        )
        add_check(
            checks,
            "validity_row_count",
            validity_count == EXPECTED_VALIDITY_ROWS,
            validity_count,
            EXPECTED_VALIDITY_ROWS,
        )
        add_check(
            checks,
            "school_stints_available",
            stint_count > 0,
            stint_count,
            "greater than 0",
        )
        add_check(
            checks,
            "school_stint_performance_map_available",
            stint_map_count > 0,
            stint_map_count,
            "greater than 0",
        )

        gender_candidates = [
            row for row in candidate_columns
            if "gender" in row["candidate_category"]
        ]
        season_candidates = [
            row for row in candidate_columns
            if "season" in row["candidate_category"]
        ]
        date_candidates = [
            row for row in candidate_columns
            if "date" in row["candidate_category"]
        ]
        school_candidates = [
            row for row in candidate_columns
            if "school" in row["candidate_category"]
        ]
        meet_candidates = [
            row for row in candidate_columns
            if "meet" in row["candidate_category"]
        ]

        add_check(
            checks,
            "gender_metadata_candidates_found",
            len(gender_candidates) > 0,
            len(gender_candidates),
            "greater than 0",
        )
        add_check(
            checks,
            "season_metadata_candidates_found",
            len(season_candidates) > 0,
            len(season_candidates),
            "greater than 0",
        )
        add_check(
            checks,
            "date_metadata_candidates_found",
            len(date_candidates) > 0,
            len(date_candidates),
            "greater than 0",
        )
        add_check(
            checks,
            "school_metadata_candidates_found",
            len(school_candidates) > 0,
            len(school_candidates),
            "greater than 0",
        )
        add_check(
            checks,
            "meet_metadata_candidates_found",
            len(meet_candidates) > 0,
            len(meet_candidates),
            "greater than 0",
        )

        # Join-key inventory for the tables we expect to use next.
        important_tables = {
            ("parsed", "main", "parsed_performances"),
            ("validity", "main", "performance_validity"),
            ("canonical", "main", "canonical_person_performances"),
            ("canonical", "main", "canonical_people"),
            ("stints", "main", "analytical_school_stints"),
            ("stints", "main", "school_stint_performance_map"),
        }
        key_words = (
            "canonical_person_performance_id",
            "canonical_person_id",
            "performance_id",
            "event_id",
            "school_stint",
            "school_id",
            "team_id",
            "meet_id",
            "season_id",
        )
        join_key_rows = [
            row
            for row in column_rows
            if (
                row["database_name"],
                row["table_schema"],
                row["table_name"],
            )
            in important_tables
            and any(
                key in row["column_name"].lower()
                for key in key_words
            )
        ]
        write_csv(
            output_dir / "join_key_inventory.csv",
            join_key_rows,
            [
                "database_name",
                "table_schema",
                "table_name",
                "ordinal_position",
                "column_name",
                "data_type",
                "is_nullable",
            ],
        )

        summary = {
            "preflight_version": PREFLIGHT_VERSION,
            "created_utc": utc_now(),
            "database_count": len(databases),
            "table_count": len(table_rows),
            "column_count": len(column_rows),
            "candidate_column_count": len(candidate_columns),
            "gender_candidate_count": len(gender_candidates),
            "season_candidate_count": len(season_candidates),
            "date_candidate_count": len(date_candidates),
            "school_candidate_count": len(school_candidates),
            "meet_candidate_count": len(meet_candidates),
            "parsed_row_count": parsed_count,
            "validity_row_count": validity_count,
            "school_stint_count": stint_count,
            "school_stint_map_count": stint_map_count,
            "profile_error_count": len(profile_errors),
        }
        (output_dir / "preflight_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        write_csv(
            output_dir / "input_manifest.csv",
            manifest_rows,
            [
                "database_name",
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

        failed = [row for row in checks if row["status"] == "FAIL"]

        report_lines = [
            "MILESTONE 5 PHASE 2E-1 — TRACK METADATA SOURCE PREFLIGHT",
            "=" * 78,
            f"Finished UTC: {utc_now()}",
            f"Preflight version: {PREFLIGHT_VERSION}",
            "",
            "SOURCE SCALE",
            "-" * 78,
            f"Databases inspected: {len(databases):,}",
            f"Tables inspected: {len(table_rows):,}",
            f"Columns inspected: {len(column_rows):,}",
            f"Metadata candidate columns: {len(candidate_columns):,}",
            "",
            "CANDIDATE COVERAGE",
            "-" * 78,
            f"Gender candidates: {len(gender_candidates):,}",
            f"Season candidates: {len(season_candidates):,}",
            f"Date/year candidates: {len(date_candidates):,}",
            f"School/stint candidates: {len(school_candidates):,}",
            f"Meet candidates: {len(meet_candidates):,}",
            "",
            "KEY TABLE SCALE",
            "-" * 78,
            f"Parsed performances: {parsed_count:,}",
            f"Validity rows: {validity_count:,}",
            f"Analytical school stints: {stint_count:,}",
            f"School-stint performance mappings: {stint_map_count:,}",
            "",
            "NEXT DECISION",
            "-" * 78,
            "Select authoritative fields for gender, season type, date/year,",
            "meet identity, and school-stint attribution from the profiles.",
            "Then build the frozen track performance foundation.",
            "",
            "HARD CHECK SUMMARY",
            "-" * 78,
            f"PASS: {sum(row['status'] == 'PASS' for row in checks)}",
            f"FAIL: {len(failed)}",
            "",
            "PHASE GATE",
            "-" * 78,
            (
                "PASS — Metadata sources are inventoried for track freezing."
                if not failed
                else "FAIL — Required source metadata is missing."
            ),
        ]
        (output_dir / "track_metadata_preflight_report.txt").write_text(
            "\n".join(report_lines) + "\n",
            encoding="utf-8",
        )

        print()
        print(f"Tables inspected: {len(table_rows):,}")
        print(f"Columns inspected: {len(column_rows):,}")
        print(f"Gender candidates: {len(gender_candidates):,}")
        print(f"Season candidates: {len(season_candidates):,}")
        print(f"Date candidates: {len(date_candidates):,}")
        print(f"School candidates: {len(school_candidates):,}")
        print(f"Meet candidates: {len(meet_candidates):,}")
        print()
        print("Created:")
        for filename in [
            "track_metadata_preflight_report.txt",
            "preflight_summary.json",
            "database_tables.csv",
            "metadata_candidate_columns.csv",
            "metadata_value_profiles.csv",
            "metadata_profile_errors.csv",
            "join_key_inventory.csv",
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
        print("Stop here and inspect metadata candidates.")
        return 0

    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
