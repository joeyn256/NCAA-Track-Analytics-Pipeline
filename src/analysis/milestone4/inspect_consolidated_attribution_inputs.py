#!/usr/bin/env python3
"""
Milestone 4 consolidated-attribution preflight.

Purpose
-------
Inventory the exact inputs needed to build the final one-row-per-performance
attribution layer across all 6,594,540 source performances.

This script is read-only with respect to:
- data/database/ncaa_track_analytics.duckdb
- all_profile_staging.duckdb
- prior Milestone 4 outputs
- raw HTML

It writes only diagnostic reports under:
data/processed/milestone4/consolidated_attribution_preflight/
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]

SOURCE_DB = (
    PROJECT_ROOT / "data/database/ncaa_track_analytics.duckdb"
)
STAGING_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/all_profile_staging"
    / "all_profile_staging.duckdb"
)

TRANSFER_LAYER_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4"
    / "transfer_candidate_analytical_layer"
)
BLOCKING_LAYER_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4"
    / "blocking_profile_result_resolution"
)
CLASSIFICATION_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4"
    / "profile_section_classification"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4"
    / "consolidated_attribution_preflight"
)


def clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split()).strip()


def quote_path(path: Path) -> str:
    return str(path).replace("'", "''")


def csv_header(path: Path) -> list[str]:
    with path.open(
        "r",
        encoding="utf-8-sig",
        errors="replace",
        newline="",
    ) as handle:
        reader = csv.reader(handle)
        return next(reader, [])


def list_duckdb_tables(
    con: duckdb.DuckDBPyConnection,
    database_label: str,
) -> pd.DataFrame:
    tables = con.execute(
        """
        SELECT
            table_schema,
            table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema NOT IN (
              'information_schema',
              'pg_catalog'
          )
        ORDER BY
            table_schema,
            table_name
        """
    ).fetchdf()

    rows: list[dict[str, Any]] = []

    for record in tables.to_dict("records"):
        schema = clean(record["table_schema"])
        table = clean(record["table_name"])
        qualified = (
            f'"{schema.replace(chr(34), chr(34) * 2)}".'
            f'"{table.replace(chr(34), chr(34) * 2)}"'
        )

        try:
            count = int(
                con.execute(
                    f"SELECT COUNT(*) FROM {qualified}"
                ).fetchone()[0]
            )
            count_error = ""
        except Exception as exc:
            count = -1
            count_error = (
                f"{type(exc).__name__}: {clean(exc)}"
            )

        columns = con.execute(
            """
            SELECT
                column_name,
                data_type,
                is_nullable,
                ordinal_position
            FROM information_schema.columns
            WHERE table_schema = ?
              AND table_name = ?
            ORDER BY ordinal_position
            """,
            [schema, table],
        ).fetchdf()

        column_text = " | ".join(
            f"{row.column_name}:{row.data_type}"
            for row in columns.itertuples(index=False)
        )

        rows.append(
            {
                "database": database_label,
                "schema_name": schema,
                "table_name": table,
                "row_count": count,
                "column_count": len(columns),
                "columns": column_text,
                "count_error": count_error,
            }
        )

    return pd.DataFrame(rows)


def inventory_csv_directory(
    con: duckdb.DuckDBPyConnection,
    directory: Path,
    source_label: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    if not directory.exists():
        return pd.DataFrame(
            [
                {
                    "source_label": source_label,
                    "relative_path": "",
                    "size_bytes": 0,
                    "row_count": -1,
                    "column_count": 0,
                    "columns": "",
                    "has_performance_id": False,
                    "count_error": (
                        f"Directory not found: {directory}"
                    ),
                }
            ]
        )

    for path in sorted(directory.rglob("*.csv")):
        header = csv_header(path)
        escaped = quote_path(path)

        try:
            count = int(
                con.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM read_csv_auto(
                        '{escaped}',
                        header = true,
                        all_varchar = true,
                        sample_size = -1
                    )
                    """
                ).fetchone()[0]
            )
            count_error = ""
        except Exception as exc:
            count = -1
            count_error = (
                f"{type(exc).__name__}: {clean(exc)}"
            )

        rows.append(
            {
                "source_label": source_label,
                "relative_path": str(
                    path.relative_to(PROJECT_ROOT)
                ),
                "size_bytes": path.stat().st_size,
                "row_count": count,
                "column_count": len(header),
                "columns": " | ".join(header),
                "has_performance_id": (
                    "performance_id" in header
                ),
                "count_error": count_error,
            }
        )

    return pd.DataFrame(rows)


def choose_primary_performance_csv(
    inventory: pd.DataFrame,
    source_label: str,
) -> Path | None:
    candidates = inventory.loc[
        (inventory["source_label"] == source_label)
        & inventory["has_performance_id"].eq(True)
        & inventory["row_count"].ge(0)
    ].copy()

    if candidates.empty:
        return None

    candidates = candidates.sort_values(
        ["row_count", "size_bytes"],
        ascending=[False, False],
    )

    return PROJECT_ROOT / candidates.iloc[0][
        "relative_path"
    ]


def build_overlap_checks(
    con: duckdb.DuckDBPyConnection,
    transfer_csv: Path | None,
    blocking_csv: Path | None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    core_total = int(
        con.execute(
            "SELECT COUNT(*) FROM core.performances"
        ).fetchone()[0]
    )
    core_distinct = int(
        con.execute(
            """
            SELECT COUNT(DISTINCT performance_id)
            FROM core.performances
            """
        ).fetchone()[0]
    )

    rows.extend(
        [
            {
                "check_name": "core_performance_rows",
                "observed_value": core_total,
                "expected_value": 6_594_540,
                "status": (
                    "PASS"
                    if core_total == 6_594_540
                    else "REVIEW"
                ),
                "details": "",
            },
            {
                "check_name": (
                    "core_distinct_performance_ids"
                ),
                "observed_value": core_distinct,
                "expected_value": core_total,
                "status": (
                    "PASS"
                    if core_distinct == core_total
                    else "FAIL"
                ),
                "details": "",
            },
        ]
    )

    if transfer_csv is None:
        rows.append(
            {
                "check_name": (
                    "transfer_primary_performance_file"
                ),
                "observed_value": 0,
                "expected_value": 1,
                "status": "FAIL",
                "details": "No CSV with performance_id found.",
            }
        )
    else:
        transfer_path = quote_path(transfer_csv)

        transfer_counts = con.execute(
            f"""
            SELECT
                COUNT(*) AS row_count,
                COUNT(
                    DISTINCT performance_id
                ) AS distinct_count
            FROM read_csv_auto(
                '{transfer_path}',
                header = true,
                all_varchar = true,
                sample_size = -1
            )
            """
        ).fetchone()

        transfer_missing_core = int(
            con.execute(
                f"""
                SELECT COUNT(*)
                FROM (
                    SELECT DISTINCT performance_id
                    FROM read_csv_auto(
                        '{transfer_path}',
                        header = true,
                        all_varchar = true,
                        sample_size = -1
                    )
                ) x
                LEFT JOIN core.performances p
                  ON CAST(p.performance_id AS VARCHAR)
                   = x.performance_id
                WHERE p.performance_id IS NULL
                """
            ).fetchone()[0]
        )

        rows.extend(
            [
                {
                    "check_name": (
                        "transfer_candidate_rows"
                    ),
                    "observed_value": int(
                        transfer_counts[0]
                    ),
                    "expected_value": 164_964,
                    "status": (
                        "PASS"
                        if int(transfer_counts[0])
                        == 164_964
                        else "REVIEW"
                    ),
                    "details": str(
                        transfer_csv.relative_to(
                            PROJECT_ROOT
                        )
                    ),
                },
                {
                    "check_name": (
                        "transfer_candidate_duplicate_"
                        "performance_ids"
                    ),
                    "observed_value": int(
                        transfer_counts[0]
                        - transfer_counts[1]
                    ),
                    "expected_value": 0,
                    "status": (
                        "PASS"
                        if transfer_counts[0]
                        == transfer_counts[1]
                        else "FAIL"
                    ),
                    "details": "",
                },
                {
                    "check_name": (
                        "transfer_candidate_ids_missing_"
                        "from_core"
                    ),
                    "observed_value": (
                        transfer_missing_core
                    ),
                    "expected_value": 0,
                    "status": (
                        "PASS"
                        if transfer_missing_core == 0
                        else "FAIL"
                    ),
                    "details": "",
                },
            ]
        )

    if blocking_csv is None:
        rows.append(
            {
                "check_name": (
                    "blocking_primary_performance_file"
                ),
                "observed_value": 0,
                "expected_value": 1,
                "status": "FAIL",
                "details": "No CSV with performance_id found.",
            }
        )
    else:
        blocking_path = quote_path(blocking_csv)

        blocking_counts = con.execute(
            f"""
            SELECT
                COUNT(*) AS row_count,
                COUNT(
                    DISTINCT performance_id
                ) AS distinct_count
            FROM read_csv_auto(
                '{blocking_path}',
                header = true,
                all_varchar = true,
                sample_size = -1
            )
            """
        ).fetchone()

        blocking_missing_core = int(
            con.execute(
                f"""
                SELECT COUNT(*)
                FROM (
                    SELECT DISTINCT performance_id
                    FROM read_csv_auto(
                        '{blocking_path}',
                        header = true,
                        all_varchar = true,
                        sample_size = -1
                    )
                ) x
                LEFT JOIN core.performances p
                  ON CAST(p.performance_id AS VARCHAR)
                   = x.performance_id
                WHERE p.performance_id IS NULL
                """
            ).fetchone()[0]
        )

        rows.extend(
            [
                {
                    "check_name": (
                        "blocking_resolution_rows"
                    ),
                    "observed_value": int(
                        blocking_counts[0]
                    ),
                    "expected_value": 1_134,
                    "status": (
                        "PASS"
                        if int(blocking_counts[0])
                        == 1_134
                        else "REVIEW"
                    ),
                    "details": str(
                        blocking_csv.relative_to(
                            PROJECT_ROOT
                        )
                    ),
                },
                {
                    "check_name": (
                        "blocking_resolution_duplicate_"
                        "performance_ids"
                    ),
                    "observed_value": int(
                        blocking_counts[0]
                        - blocking_counts[1]
                    ),
                    "expected_value": 0,
                    "status": (
                        "PASS"
                        if blocking_counts[0]
                        == blocking_counts[1]
                        else "FAIL"
                    ),
                    "details": "",
                },
                {
                    "check_name": (
                        "blocking_resolution_ids_missing_"
                        "from_core"
                    ),
                    "observed_value": (
                        blocking_missing_core
                    ),
                    "expected_value": 0,
                    "status": (
                        "PASS"
                        if blocking_missing_core == 0
                        else "FAIL"
                    ),
                    "details": "",
                },
            ]
        )

    if (
        transfer_csv is not None
        and blocking_csv is not None
    ):
        transfer_path = quote_path(transfer_csv)
        blocking_path = quote_path(blocking_csv)

        overlap = int(
            con.execute(
                f"""
                WITH transfer_ids AS (
                    SELECT DISTINCT performance_id
                    FROM read_csv_auto(
                        '{transfer_path}',
                        header = true,
                        all_varchar = true,
                        sample_size = -1
                    )
                ),
                blocking_ids AS (
                    SELECT DISTINCT performance_id
                    FROM read_csv_auto(
                        '{blocking_path}',
                        header = true,
                        all_varchar = true,
                        sample_size = -1
                    )
                )
                SELECT COUNT(*)
                FROM transfer_ids t
                JOIN blocking_ids b
                  USING (performance_id)
                """
            ).fetchone()[0]
        )

        rows.append(
            {
                "check_name": (
                    "transfer_blocking_performance_overlap"
                ),
                "observed_value": overlap,
                "expected_value": (
                    "informational"
                ),
                "status": "INFO",
                "details": (
                    "Determines precedence required in "
                    "the consolidated layer."
                ),
            }
        )

    return pd.DataFrame(rows)


def main() -> None:
    for path in [SOURCE_DB, STAGING_DB]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required database not found: {path}"
            )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_con = duckdb.connect(
        str(SOURCE_DB),
        read_only=True,
    )
    staging_con = duckdb.connect(
        str(STAGING_DB),
        read_only=True,
    )

    try:
        source_inventory = list_duckdb_tables(
            source_con,
            "source_database",
        )
        staging_inventory = list_duckdb_tables(
            staging_con,
            "all_profile_staging",
        )

        csv_inventories = []

        for directory, label in [
            (
                TRANSFER_LAYER_DIR,
                "transfer_candidate_layer",
            ),
            (
                BLOCKING_LAYER_DIR,
                "blocking_profile_resolution",
            ),
            (
                CLASSIFICATION_DIR,
                "profile_section_classification",
            ),
        ]:
            csv_inventories.append(
                inventory_csv_directory(
                    source_con,
                    directory,
                    label,
                )
            )

        csv_inventory = pd.concat(
            csv_inventories,
            ignore_index=True,
        )

        transfer_csv = (
            choose_primary_performance_csv(
                csv_inventory,
                "transfer_candidate_layer",
            )
        )
        blocking_csv = (
            choose_primary_performance_csv(
                csv_inventory,
                "blocking_profile_resolution",
            )
        )

        overlap_checks = build_overlap_checks(
            source_con,
            transfer_csv,
            blocking_csv,
        )

    finally:
        source_con.close()
        staging_con.close()

    source_inventory.to_csv(
        OUTPUT_DIR
        / "source_database_table_inventory.csv",
        index=False,
    )
    staging_inventory.to_csv(
        OUTPUT_DIR
        / "staging_database_table_inventory.csv",
        index=False,
    )
    csv_inventory.to_csv(
        OUTPUT_DIR / "milestone4_csv_inventory.csv",
        index=False,
    )
    overlap_checks.to_csv(
        OUTPUT_DIR / "attribution_input_checks.csv",
        index=False,
    )

    fail_count = int(
        overlap_checks["status"].eq("FAIL").sum()
    )
    review_count = int(
        overlap_checks["status"].eq(
            "REVIEW"
        ).sum()
    )

    transfer_display = (
        str(
            transfer_csv.relative_to(
                PROJECT_ROOT
            )
        )
        if transfer_csv is not None
        else "NOT FOUND"
    )
    blocking_display = (
        str(
            blocking_csv.relative_to(
                PROJECT_ROOT
            )
        )
        if blocking_csv is not None
        else "NOT FOUND"
    )

    report = f"""MILESTONE 4 CONSOLIDATED ATTRIBUTION PREFLIGHT
============================================================
Source database modified: no
Staging database modified: no
Prior Milestone 4 outputs modified: no

PRIMARY INPUTS
- Source database: {SOURCE_DB}
- All-profile staging database: {STAGING_DB}
- Transfer performance file: {transfer_display}
- Blocking performance file: {blocking_display}

INVENTORY
- Source database tables: {len(source_inventory):,}
- Staging database tables: {len(staging_inventory):,}
- Milestone 4 CSV files inventoried: {len(csv_inventory):,}

VALIDATION
- Failed checks: {fail_count:,}
- Review checks: {review_count:,}

NEXT GATE
Use the table schemas, CSV schemas, and overlap count from this report
to define deterministic precedence for one final attribution row per
core performance_id. Do not write to the Milestone 3 source database.
"""

    (
        OUTPUT_DIR / "preflight_report.txt"
    ).write_text(
        report,
        encoding="utf-8",
    )

    print(
        "Consolidated-attribution preflight complete."
    )
    print(f"Outputs: {OUTPUT_DIR}")
    print(
        f"Failed checks: {fail_count:,}; "
        f"review checks: {review_count:,}."
    )


if __name__ == "__main__":
    main()
