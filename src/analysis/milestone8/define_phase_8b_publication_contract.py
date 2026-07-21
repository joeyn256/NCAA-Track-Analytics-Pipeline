#!/usr/bin/env python3
"""Define the versioned Phase 8B compact-publication contract."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Final

import duckdb
import pandas as pd

from audit_phase_8b_source_mapping import (
    APP_PATH,
    DATABASES,
    EXPECTED_SOURCE_HASHES,
    M7_SPECIALIZED_DB,
    M7_TRENDS_DB,
    ROOT,
    evaluate_app_constants,
    register_csv_resources,
    sha256_file,
)


PUBLICATION_VERSION: Final = "public_deployment_v1"

SOURCE_MAPPING_DIR: Final = (
    ROOT
    / "data/processed/milestone8"
    / PUBLICATION_VERSION
    / "phase_8b_source_mapping"
)

OUTPUT_DIR: Final = (
    ROOT
    / "data/processed/milestone8"
    / PUBLICATION_VERSION
    / "phase_8b_publication_contract"
)

EXPECTED_COUNTS: Final = {
    "csv_resources": 47,
    "trend_tables": 14,
    "specialized_analyses": 12,
    "specialized_unique_result_tables": 9,
    "specialized_source_tables": 20,
}


def normalize_identifier(value: str) -> str:
    """Return a deterministic DuckDB-safe identifier."""

    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")

    if not normalized:
        raise ValueError(f"Could not normalize identifier: {value!r}")

    if normalized[0].isdigit():
        normalized = f"t_{normalized}"

    return normalized


def classify_csv_resource(
    relative_path: str,
    logical_uses: list[str],
) -> tuple[str, str, str]:
    """Assign one stable deployment schema, table, and model family."""

    source_path = Path(relative_path)
    stem = normalize_identifier(source_path.stem)
    use_prefixes = {use.split(":", 1)[0] for use in logical_uses}

    if use_prefixes == {"average"}:
        return "average", stem, "Average Development"

    if use_prefixes == {"supplemental"}:
        return "average_supplemental", stem, "Average Development"

    if use_prefixes == {"points"}:
        return "official", stem, "Enhanced Balanced Production"

    if use_prefixes == {"cohort"}:
        if any(use.startswith("cohort:Broad") for use in logical_uses):
            return "average_seasonal_broad", stem, "Average Development"

        return "average_seasonal_elite", stem, "Average Development"

    raise RuntimeError(
        "Unable to classify CSV resource "
        f"{relative_path!r} with uses {logical_uses!r}."
    )


def table_inventory(
    database_path: Path,
) -> list[dict[str, Any]]:
    """Return deterministic base-table inventory from a read-only database."""

    connection = duckdb.connect(str(database_path), read_only=True)

    try:
        rows = connection.execute(
            """
            SELECT
                t.table_schema,
                t.table_name,
                COUNT(c.column_name) AS column_count
            FROM information_schema.tables AS t
            LEFT JOIN information_schema.columns AS c
              ON c.table_schema = t.table_schema
             AND c.table_name = t.table_name
            WHERE t.table_type = 'BASE TABLE'
              AND t.table_schema NOT IN (
                  'information_schema',
                  'pg_catalog'
              )
            GROUP BY t.table_schema, t.table_name
            ORDER BY t.table_schema, t.table_name
            """
        ).fetchall()

        inventory: list[dict[str, Any]] = []

        for table_schema, table_name, column_count in rows:
            qualified = (
                '"' + str(table_schema).replace('"', '""') + '".'
                '"' + str(table_name).replace('"', '""') + '"'
            )

            row_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {qualified}"
                ).fetchone()[0]
            )

            columns = [
                {
                    "name": column_name,
                    "type": data_type,
                    "ordinal_position": ordinal_position,
                }
                for column_name, data_type, ordinal_position in connection.execute(
                    """
                    SELECT column_name, data_type, ordinal_position
                    FROM information_schema.columns
                    WHERE table_schema = ?
                      AND table_name = ?
                    ORDER BY ordinal_position
                    """,
                    [table_schema, table_name],
                ).fetchall()
            ]

            inventory.append(
                {
                    "source_schema": table_schema,
                    "source_table": table_name,
                    "row_count": row_count,
                    "column_count": int(column_count),
                    "columns": columns,
                }
            )

        return inventory
    finally:
        connection.close()


def write_tsv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    """Write a deterministic tab-separated file."""

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def json_safe(value: Any) -> Any:
    """Convert nested publication configuration into JSON-safe values."""

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item) for item in value]

    return value


def main() -> None:
    """Create the Phase 8B publication contract without building a database."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    mapping_path = SOURCE_MAPPING_DIR / "csv_to_milestone6_mapping.tsv"

    if not mapping_path.is_file():
        raise FileNotFoundError(
            "Run audit_phase_8b_source_mapping.py first. Missing: "
            f"{mapping_path}"
        )

    observed_hashes = {
        label: sha256_file(path)
        for label, path in DATABASES.items()
    }

    if observed_hashes != EXPECTED_SOURCE_HASHES:
        raise RuntimeError(
            "Frozen database hash mismatch before contract creation:\n"
            + json.dumps(
                {
                    "expected": EXPECTED_SOURCE_HASHES,
                    "observed": observed_hashes,
                },
                indent=2,
                sort_keys=True,
            )
        )

    constants = evaluate_app_constants()
    registered_csvs = register_csv_resources(constants)

    mapping = pd.read_csv(mapping_path, sep="\t")

    if len(mapping) != EXPECTED_COUNTS["csv_resources"]:
        raise RuntimeError(
            f"Expected {EXPECTED_COUNTS['csv_resources']} mapped CSVs; "
            f"found {len(mapping)}."
        )

    csv_rows: list[dict[str, Any]] = []

    for record in mapping.sort_values("csv_path").to_dict("records"):
        relative_path = str(record["csv_path"])
        absolute_path = ROOT / relative_path

        if not absolute_path.is_file():
            raise FileNotFoundError(absolute_path)

        resource_uses = sorted(
            registered_csvs[absolute_path]
        )

        deployment_schema, deployment_table, model_family = (
            classify_csv_resource(relative_path, resource_uses)
        )

        csv_rows.append(
            {
                "resource_kind": "csv",
                "source_label": "frozen_app_csv",
                "source_path": relative_path,
                "source_schema": "",
                "source_table": "",
                "deployment_schema": deployment_schema,
                "deployment_table": deployment_table,
                "model_family": model_family,
                "logical_uses": "|".join(resource_uses),
                "row_count": int(record["csv_row_count"]),
                "column_count": int(record["csv_column_count"]),
                "columns": str(record["csv_columns"]),
                "source_bytes": int(record["size_bytes"]),
                "source_sha256": sha256_file(absolute_path),
                "mapping_status": str(record["mapping_status"]),
                "include_reason": (
                    "Preserve the exact app-facing grain and schema. "
                    "The current explorer loads this publication directly."
                ),
            }
        )

    deployment_targets = [
        (
            row["deployment_schema"],
            row["deployment_table"],
        )
        for row in csv_rows
    ]

    if len(deployment_targets) != len(set(deployment_targets)):
        duplicates = sorted(
            {
                target
                for target in deployment_targets
                if deployment_targets.count(target) > 1
            }
        )
        raise RuntimeError(
            f"Duplicate CSV deployment targets: {duplicates}"
        )

    trend_registry = constants["MILESTONE7_TABLES"]

    if not isinstance(trend_registry, dict):
        raise TypeError("MILESTONE7_TABLES must be a dictionary.")

    trend_inventory = {
        item["source_table"]: item
        for item in table_inventory(M7_TRENDS_DB)
    }

    trend_rows: list[dict[str, Any]] = []

    for logical_name, source_table in sorted(trend_registry.items()):
        table = trend_inventory.get(str(source_table))

        if table is None:
            raise RuntimeError(
                f"Missing curated trend table: {source_table}"
            )

        trend_rows.append(
            {
                "resource_kind": "duckdb_table",
                "source_label": "milestone7_trends",
                "source_path": str(M7_TRENDS_DB.relative_to(ROOT)),
                "source_schema": table["source_schema"],
                "source_table": table["source_table"],
                "deployment_schema": "trends",
                "deployment_table": normalize_identifier(
                    str(table["source_table"])
                ),
                "model_family": "Enhanced Balanced Production",
                "logical_uses": str(logical_name),
                "row_count": table["row_count"],
                "column_count": table["column_count"],
                "columns": "|".join(
                    column["name"]
                    for column in table["columns"]
                ),
                "source_bytes": "",
                "source_sha256": observed_hashes[
                    "milestone7_trends"
                ],
                "mapping_status": "direct",
                "include_reason": (
                    "Curated Milestone 7 explorer table registered "
                    "by the production app."
                ),
            }
        )

    specialized_analyses = constants[
        "EVENT_BALANCED_SPECIALIZED_ANALYSES"
    ]

    if not isinstance(specialized_analyses, dict):
        raise TypeError(
            "EVENT_BALANCED_SPECIALIZED_ANALYSES must be a dictionary."
        )

    specialized_result_tables = {
        str(configuration["table"])
        for configuration in specialized_analyses.values()
        if configuration.get("table")
    }

    specialized_inventory = table_inventory(M7_SPECIALIZED_DB)

    specialized_source_names = {
        item["source_table"]
        for item in specialized_inventory
    }

    missing_result_tables = sorted(
        specialized_result_tables - specialized_source_names
    )

    if missing_result_tables:
        raise RuntimeError(
            "Specialized result tables missing from publication: "
            + ", ".join(missing_result_tables)
        )

    specialized_rows: list[dict[str, Any]] = []

    for table in specialized_inventory:
        source_table = str(table["source_table"])
        is_result_table = source_table in specialized_result_tables

        specialized_rows.append(
            {
                "resource_kind": "duckdb_table",
                "source_label": "milestone7_specialized",
                "source_path": str(
                    M7_SPECIALIZED_DB.relative_to(ROOT)
                ),
                "source_schema": table["source_schema"],
                "source_table": source_table,
                "deployment_schema": "specialized",
                "deployment_table": normalize_identifier(source_table),
                "model_family": "Enhanced Balanced Production",
                "logical_uses": (
                    "registered_result_table"
                    if is_result_table
                    else "publication_registry_or_validation"
                ),
                "row_count": table["row_count"],
                "column_count": table["column_count"],
                "columns": "|".join(
                    column["name"]
                    for column in table["columns"]
                ),
                "source_bytes": "",
                "source_sha256": observed_hashes[
                    "milestone7_specialized"
                ],
                "mapping_status": "direct",
                "include_reason": (
                    "Registered specialized-analysis result table."
                    if is_result_table
                    else (
                        "Preserve the specialized publication registry, "
                        "availability status, validation metadata, and "
                        "inbound-transfer unavailable contract."
                    )
                ),
            }
        )

    analysis_rows: list[dict[str, Any]] = []

    for analysis_key, configuration in sorted(
        specialized_analyses.items()
    ):
        analysis_rows.append(
            {
                "analysis_key": analysis_key,
                "source_table": str(
                    configuration.get("table", "")
                ),
                "configuration_json": json.dumps(
                    json_safe(configuration),
                    sort_keys=True,
                ),
            }
        )

    all_resource_rows = csv_rows + trend_rows + specialized_rows

    summary = {
        "publication_version": PUBLICATION_VERSION,
        "app_path": str(APP_PATH.relative_to(ROOT)),
        "architecture_decision": {
            "app_facing_csvs": (
                "Ingest all 47 current CSV resources directly into "
                "DuckDB to preserve exact grains, schemas, and results."
            ),
            "milestone7_trends": (
                "Copy only the 14 curated explorer tables."
            ),
            "milestone7_specialized": (
                "Copy all 20 specialized publication tables. "
                "Nine are unique physical result tables used by "
                "12 registered analyses; the remaining tables preserve "
                "registries, availability status, and validation metadata."
            ),
            "milestone6_database": (
                "Attach read-only during the builder for frozen-source "
                "hash and registry validation. Do not coerce the 30 "
                "non-equivalent CSV resources into mismatched tables."
            ),
        },
        "counts": {
            "csv_resources": len(csv_rows),
            "trend_tables": len(trend_rows),
            "specialized_analyses": len(analysis_rows),
            "specialized_unique_result_tables": len(
                specialized_result_tables
            ),
            "specialized_source_tables": len(
                specialized_rows
            ),
            "deployment_tables_before_metadata": len(
                all_resource_rows
            ),
        },
        "source_bytes": {
            "csv_resources": sum(
                int(row["source_bytes"])
                for row in csv_rows
            ),
            "milestone7_trends_database": (
                M7_TRENDS_DB.stat().st_size
            ),
            "milestone7_specialized_database": (
                M7_SPECIALIZED_DB.stat().st_size
            ),
        },
        "source_database_hashes": observed_hashes,
        "hard_checks": {
            key: (
                len(csv_rows)
                if key == "csv_resources"
                else len(trend_rows)
                if key == "trend_tables"
                else len(analysis_rows)
                if key == "specialized_analyses"
                else len(specialized_result_tables)
                if key == "specialized_unique_result_tables"
                else len(specialized_rows)
            )
            == expected
            for key, expected in EXPECTED_COUNTS.items()
        },
    }

    if not all(summary["hard_checks"].values()):
        raise RuntimeError(
            "Publication-contract count check failed:\n"
            + json.dumps(
                summary["hard_checks"],
                indent=2,
                sort_keys=True,
            )
        )

    write_tsv(
        OUTPUT_DIR / "deployment_resource_contract.tsv",
        all_resource_rows,
        [
            "resource_kind",
            "source_label",
            "source_path",
            "source_schema",
            "source_table",
            "deployment_schema",
            "deployment_table",
            "model_family",
            "logical_uses",
            "row_count",
            "column_count",
            "columns",
            "source_bytes",
            "source_sha256",
            "mapping_status",
            "include_reason",
        ],
    )

    write_tsv(
        OUTPUT_DIR / "specialized_analysis_registry.tsv",
        analysis_rows,
        [
            "analysis_key",
            "source_table",
            "configuration_json",
        ],
    )

    contract = {
        "summary": summary,
        "resources": all_resource_rows,
        "specialized_analyses": analysis_rows,
    }

    (OUTPUT_DIR / "publication_contract_v1.json").write_text(
        json.dumps(
            contract,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    (OUTPUT_DIR / "contract_summary.json").write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("=" * 76)
    print("PHASE 8B PUBLICATION CONTRACT")
    print("=" * 76)
    print(f"CSV resources:                    {len(csv_rows):,}")
    print(f"Curated trend tables:             {len(trend_rows):,}")
    print(f"Registered specialized analyses: {len(analysis_rows):,}")
    print(
        "Unique specialized result tables: "
        f"{len(specialized_result_tables):,}"
    )
    print(
        "Specialized publication tables:    "
        f"{len(specialized_rows):,}"
    )
    print(
        "Deployment tables before metadata: "
        f"{len(all_resource_rows):,}"
    )
    print(
        "CSV source bytes:                  "
        f"{summary['source_bytes']['csv_resources']:,}"
    )
    print(f"Output directory: {OUTPUT_DIR}")
    print("PASS — publication contract is complete.")
    print(
        "No deployment database was created and no frozen source "
        "was modified."
    )


if __name__ == "__main__":
    main()
