#!/usr/bin/env python3
"""Validate exact value parity for the Milestone 8 compact publication."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Final

import duckdb
import pandas as pd

from audit_phase_8b_source_mapping import (
    DATABASES,
    EXPECTED_SOURCE_HASHES,
    ROOT,
    sha256_file,
)


PUBLICATION_VERSION: Final = "public_deployment_v1"

CONTRACT_PATH: Final = (
    ROOT
    / "data/processed/milestone8"
    / PUBLICATION_VERSION
    / "phase_8b_publication_contract"
    / "deployment_resource_contract.tsv"
)

DEPLOYMENT_DIR: Final = (
    ROOT
    / "data/processed/milestone8"
    / PUBLICATION_VERSION
    / "phase_8b_compact_publication"
)

DEPLOYMENT_DB: Final = (
    DEPLOYMENT_DIR / "ncaa_track_public_explorer_v1.duckdb"
)

DEPLOYMENT_MANIFEST: Final = (
    DEPLOYMENT_DIR / "deployment_manifest.json"
)

OUTPUT_DIR: Final = (
    ROOT
    / "data/processed/milestone8"
    / PUBLICATION_VERSION
    / "phase_8b_parity_validation"
)

EXPECTED_RESOURCE_COUNT: Final = 81


def quote_identifier(value: str) -> str:
    """Quote a DuckDB identifier."""

    return '"' + value.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    """Quote a DuckDB string literal."""

    return "'" + value.replace("'", "''") + "'"


def qualified_name(
    catalog: str,
    schema: str,
    table: str,
) -> str:
    """Return a quoted catalog.schema.table reference."""

    return ".".join(
        quote_identifier(value)
        for value in (catalog, schema, table)
    )


def sha256_path(path: Path) -> str:
    """Return a streaming SHA-256 digest."""

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def relation_description(
    connection: duckdb.DuckDBPyConnection,
    relation_sql: str,
) -> list[tuple[str, str]]:
    """Return ordered column names and DuckDB types."""

    return [
        (str(row[0]), str(row[1]))
        for row in connection.execute(
            f"DESCRIBE SELECT * FROM {relation_sql}"
        ).fetchall()
    ]


def source_relation(
    resource: dict[str, Any],
) -> str:
    """Return the direct frozen-source relation for one resource."""

    source_label = str(resource["source_label"])

    if source_label == "frozen_app_csv":
        source_path = ROOT / str(resource["source_path"])

        if not source_path.is_file():
            raise FileNotFoundError(source_path)

        return f"""
            read_csv_auto(
                {quote_literal(str(source_path))},
                header = true,
                sample_size = -1,
                ignore_errors = false
            )
        """

    aliases = {
        "milestone7_trends": "m7_trends",
        "milestone7_specialized": "m7_specialized",
    }

    if source_label not in aliases:
        raise RuntimeError(
            f"Unsupported source label: {source_label}"
        )

    return qualified_name(
        aliases[source_label],
        str(resource["source_schema"]),
        str(resource["source_table"]),
    )


def write_tsv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    """Write deterministic tab-separated output."""

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def exact_difference_counts(
    connection: duckdb.DuckDBPyConnection,
    source_sql: str,
    deployment_sql: str,
    ordered_columns: list[str],
) -> tuple[int, int]:
    """Return source-minus-deployment and deployment-minus-source counts."""

    selected_columns = ", ".join(
        quote_identifier(column)
        for column in ordered_columns
    )

    query = f"""
        WITH
        source_rows AS (
            SELECT {selected_columns}
            FROM {source_sql}
        ),
        deployment_rows AS (
            SELECT {selected_columns}
            FROM {deployment_sql}
        ),
        source_minus AS (
            SELECT * FROM source_rows
            EXCEPT ALL
            SELECT * FROM deployment_rows
        ),
        deployment_minus AS (
            SELECT * FROM deployment_rows
            EXCEPT ALL
            SELECT * FROM source_rows
        )
        SELECT
            (SELECT COUNT(*) FROM source_minus),
            (SELECT COUNT(*) FROM deployment_minus)
    """

    source_minus, deployment_minus = (
        connection.execute(query).fetchone()
    )

    return int(source_minus), int(deployment_minus)


def main() -> None:
    """Run exact value, schema, count, and checksum reconciliation."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for path in (
        CONTRACT_PATH,
        DEPLOYMENT_DB,
        DEPLOYMENT_MANIFEST,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)

    contract = pd.read_csv(
        CONTRACT_PATH,
        sep="\t",
        keep_default_na=False,
    )

    if len(contract) != EXPECTED_RESOURCE_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_RESOURCE_COUNT} resources; "
            f"found {len(contract)}."
        )

    manifest = json.loads(
        DEPLOYMENT_MANIFEST.read_text(encoding="utf-8")
    )

    observed_deployment_hash = sha256_path(DEPLOYMENT_DB)
    expected_deployment_hash = str(
        manifest["database"]["sha256"]
    )

    if observed_deployment_hash != expected_deployment_hash:
        raise RuntimeError(
            "Deployment database hash does not match its manifest."
        )

    source_hashes_before = {
        label: sha256_file(path)
        for label, path in DATABASES.items()
    }

    if source_hashes_before != EXPECTED_SOURCE_HASHES:
        raise RuntimeError(
            "Frozen source hash mismatch before parity validation:\n"
            + json.dumps(
                {
                    "expected": EXPECTED_SOURCE_HASHES,
                    "observed": source_hashes_before,
                },
                indent=2,
                sort_keys=True,
            )
        )

    connection = duckdb.connect(":memory:")

    try:
        connection.execute(
            f"""
            ATTACH {quote_literal(str(DEPLOYMENT_DB))}
            AS deployment (READ_ONLY)
            """
        )

        connection.execute(
            f"""
            ATTACH {
                quote_literal(
                    str(DATABASES["milestone7_trends"])
                )
            }
            AS m7_trends (READ_ONLY)
            """
        )

        connection.execute(
            f"""
            ATTACH {
                quote_literal(
                    str(DATABASES["milestone7_specialized"])
                )
            }
            AS m7_specialized (READ_ONLY)
            """
        )

        connection.execute("SET preserve_insertion_order = false")

        parity_rows: list[dict[str, Any]] = []
        schema_summary: dict[
            str,
            dict[str, int],
        ] = defaultdict(
            lambda: {
                "table_count": 0,
                "source_rows": 0,
                "deployment_rows": 0,
                "source_minus_rows": 0,
                "deployment_minus_rows": 0,
            }
        )

        resources = contract.to_dict("records")
        total = len(resources)

        for index, resource in enumerate(
            resources,
            start=1,
        ):
            deployment_schema = str(
                resource["deployment_schema"]
            )
            deployment_table = str(
                resource["deployment_table"]
            )

            source_sql = source_relation(resource)
            deployment_sql = qualified_name(
                "deployment",
                deployment_schema,
                deployment_table,
            )

            print(
                f"[{index:02d}/{total:02d}] "
                f"{deployment_schema}.{deployment_table}"
            )

            source_description = relation_description(
                connection,
                source_sql,
            )

            deployment_description = relation_description(
                connection,
                deployment_sql,
            )

            source_columns = [
                column for column, _ in source_description
            ]

            source_types = [
                data_type for _, data_type in source_description
            ]

            deployment_columns = [
                column for column, _ in deployment_description
            ]

            deployment_types = [
                data_type for _, data_type
                in deployment_description
            ]

            columns_match = (
                source_columns == deployment_columns
            )

            types_match = (
                source_types == deployment_types
            )

            if not columns_match:
                raise RuntimeError(
                    "Column-order mismatch for "
                    f"{deployment_schema}.{deployment_table}.\n"
                    f"Source: {source_columns}\n"
                    f"Deployment: {deployment_columns}"
                )

            source_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {source_sql}"
                ).fetchone()[0]
            )

            deployment_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {deployment_sql}"
                ).fetchone()[0]
            )

            source_minus, deployment_minus = (
                exact_difference_counts(
                    connection,
                    source_sql,
                    deployment_sql,
                    source_columns,
                )
            )

            exact_match = (
                columns_match
                and types_match
                and source_count == deployment_count
                and source_minus == 0
                and deployment_minus == 0
            )

            parity_rows.append(
                {
                    "source_label": resource["source_label"],
                    "source_path": resource["source_path"],
                    "source_schema": resource["source_schema"],
                    "source_table": resource["source_table"],
                    "deployment_schema": deployment_schema,
                    "deployment_table": deployment_table,
                    "model_family": resource["model_family"],
                    "source_row_count": source_count,
                    "deployment_row_count": deployment_count,
                    "column_count": len(source_columns),
                    "columns_match": columns_match,
                    "types_match": types_match,
                    "source_minus_deployment": source_minus,
                    "deployment_minus_source": deployment_minus,
                    "exact_value_match": exact_match,
                }
            )

            summary = schema_summary[deployment_schema]
            summary["table_count"] += 1
            summary["source_rows"] += source_count
            summary["deployment_rows"] += deployment_count
            summary["source_minus_rows"] += source_minus
            summary["deployment_minus_rows"] += (
                deployment_minus
            )

            if not exact_match:
                raise RuntimeError(
                    "Exact parity failed for "
                    f"{deployment_schema}.{deployment_table}."
                )

        metadata_hard_checks = connection.execute(
            """
            SELECT check_name, passed, expected, observed
            FROM deployment.deployment_meta.hard_checks
            ORDER BY check_name
            """
        ).fetchdf()

        failed_metadata_checks = metadata_hard_checks.loc[
            ~metadata_hard_checks["passed"].astype(bool)
        ]

        if not failed_metadata_checks.empty:
            raise RuntimeError(
                "Deployment metadata contains failed hard checks:\n"
                + failed_metadata_checks.to_string(index=False)
            )

    finally:
        connection.close()

    source_hashes_after = {
        label: sha256_file(path)
        for label, path in DATABASES.items()
    }

    deployment_hash_after = sha256_path(DEPLOYMENT_DB)

    source_hashes_unchanged = (
        source_hashes_before == source_hashes_after
    )

    deployment_hash_unchanged = (
        observed_deployment_hash == deployment_hash_after
    )

    schema_rows: list[dict[str, Any]] = []

    for schema, summary in sorted(
        schema_summary.items()
    ):
        schema_rows.append(
            {
                "deployment_schema": schema,
                **summary,
                "exact_schema_match": (
                    summary["source_rows"]
                    == summary["deployment_rows"]
                    and summary["source_minus_rows"] == 0
                    and summary[
                        "deployment_minus_rows"
                    ]
                    == 0
                ),
            }
        )

    exact_matches = sum(
        bool(row["exact_value_match"])
        for row in parity_rows
    )

    summary = {
        "publication_version": PUBLICATION_VERSION,
        "resource_tables_validated": len(parity_rows),
        "exact_value_matches": exact_matches,
        "failed_value_matches": (
            len(parity_rows) - exact_matches
        ),
        "source_rows_total": sum(
            int(row["source_row_count"])
            for row in parity_rows
        ),
        "deployment_rows_total": sum(
            int(row["deployment_row_count"])
            for row in parity_rows
        ),
        "source_minus_deployment_total": sum(
            int(row["source_minus_deployment"])
            for row in parity_rows
        ),
        "deployment_minus_source_total": sum(
            int(row["deployment_minus_source"])
            for row in parity_rows
        ),
        "deployment_database_sha256": (
            observed_deployment_hash
        ),
        "deployment_manifest_sha256": (
            expected_deployment_hash
        ),
        "deployment_hash_unchanged": (
            deployment_hash_unchanged
        ),
        "source_hashes_before": source_hashes_before,
        "source_hashes_after": source_hashes_after,
        "source_hashes_unchanged": (
            source_hashes_unchanged
        ),
        "deployment_hard_checks_passed": True,
    }

    hard_pass = (
        len(parity_rows) == EXPECTED_RESOURCE_COUNT
        and exact_matches == EXPECTED_RESOURCE_COUNT
        and summary["failed_value_matches"] == 0
        and summary[
            "source_minus_deployment_total"
        ]
        == 0
        and summary[
            "deployment_minus_source_total"
        ]
        == 0
        and summary["source_rows_total"]
        == summary["deployment_rows_total"]
        and source_hashes_unchanged
        and deployment_hash_unchanged
    )

    summary["parity_gate_passed"] = hard_pass

    write_tsv(
        OUTPUT_DIR / "resource_value_parity.tsv",
        parity_rows,
        list(parity_rows[0].keys()),
    )

    write_tsv(
        OUTPUT_DIR / "schema_reconciliation.tsv",
        schema_rows,
        list(schema_rows[0].keys()),
    )

    (
        OUTPUT_DIR / "parity_summary.json"
    ).write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print("=" * 76)
    print("PHASE 8B EXACT VALUE PARITY")
    print("=" * 76)
    print(
        "Resource tables validated: "
        f"{len(parity_rows):,}"
    )
    print(
        "Exact value matches:       "
        f"{exact_matches:,}"
    )
    print(
        "Failed value matches:      "
        f"{summary['failed_value_matches']:,}"
    )
    print(
        "Source rows:               "
        f"{summary['source_rows_total']:,}"
    )
    print(
        "Deployment rows:           "
        f"{summary['deployment_rows_total']:,}"
    )
    print(
        "Source-minus-deployment:   "
        f"{summary['source_minus_deployment_total']:,}"
    )
    print(
        "Deployment-minus-source:   "
        f"{summary['deployment_minus_source_total']:,}"
    )
    print(
        "Source hashes unchanged:   "
        f"{source_hashes_unchanged}"
    )
    print(
        "Deployment hash unchanged: "
        f"{deployment_hash_unchanged}"
    )
    print(f"Output directory:         {OUTPUT_DIR}")

    if not hard_pass:
        raise SystemExit(
            "FAIL — compact-publication parity validation failed."
        )

    print(
        "PASS — all 81 deployment resource tables exactly match "
        "their frozen sources."
    )


if __name__ == "__main__":
    main()
