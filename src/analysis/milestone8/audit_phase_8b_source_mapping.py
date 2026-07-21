#!/usr/bin/env python3
"""Audit authoritative sources for the Milestone 8 deployment publication."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Final

import duckdb
import pandas as pd


ROOT: Final = Path(__file__).resolve().parents[3]
APP_PATH: Final = ROOT / "src/apps/seasonal_development_explorer.py"

OUTPUT_DIR: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8b_source_mapping"
)

M6_DB: Final = (
    ROOT
    / "data/processed/milestone6/final_development_rankings_v1"
    / "phase_6g_final_publication"
    / "final_development_rankings_v1.duckdb"
)

M7_TRENDS_DB: Final = (
    ROOT
    / "data/processed/milestone7/seasonal_program_trends_v1"
    / "phase_7d_final_publication"
    / "seasonal_program_trends_v1.duckdb"
)

M7_SPECIALIZED_DB: Final = (
    ROOT
    / "data/processed/milestone7/seasonal_program_trends_v1"
    / "phase_7e2_event_balanced_specialized_rankings"
    / "event_balanced_specialized_rankings_v2.duckdb"
)

DATABASES: Final = {
    "milestone6_final": M6_DB,
    "milestone7_trends": M7_TRENDS_DB,
    "milestone7_specialized": M7_SPECIALIZED_DB,
}

EXPECTED_SOURCE_HASHES: Final = {
    "milestone6_final": (
        "ecbf2c754c9388f60e2373dbf9c260a07098e8a541a9663154bf96ba9de926da"
    ),
    "milestone7_trends": (
        "b5551b43b91da489785b5ced07f548f2a725148d0520adbd11c97a589c105ba1"
    ),
    "milestone7_specialized": (
        "353f5c1e328991566045e6edd4fc9551a9fe336e6f3b93e29ad94a45486a67a3"
    ),
}

APP_ASSIGNMENTS: Final = {
    "ROOT",
    "EVENT_BALANCED_SPECIALIZED_DB",
    "EVENT_BALANCED_SPECIALIZED_ANALYSES",
    "SUPPLEMENTAL_DATA_DIR",
    "SUPPLEMENTAL_FILES",
    "BROAD_DATA_DIR",
    "BROAD_FILES",
    "ELITE_DATA_DIR",
    "ELITE_FILES",
    "ALL_TIME_AVERAGE_DATA_DIR",
    "ALL_TIME_AVERAGE_FILES",
    "POINTS_DATA_DIR",
    "POINTS_FILES",
    "MILESTONE7_DATA_DIR",
    "MILESTONE7_DB",
    "MILESTONE7_TABLES",
    "COHORTS",
}


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest."""

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def normalize_name(value: str) -> str:
    """Normalize publication names for conservative matching."""

    return re.sub(r"[^a-z0-9]+", "", value.lower())


def quote_identifier(value: str) -> str:
    """Quote a DuckDB identifier."""

    return '"' + value.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    """Quote a DuckDB string literal."""

    return "'" + value.replace("'", "''") + "'"


def evaluate_app_constants() -> dict[str, object]:
    """Evaluate only the app's declarative publication constants."""

    source = APP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(APP_PATH))

    environment: dict[str, object] = {
        "Path": Path,
        "Final": Final,
        "frozenset": frozenset,
        "__file__": str(APP_PATH),
    }

    unresolved = set(APP_ASSIGNMENTS)

    for _ in range(10):
        made_progress = False

        for node in tree.body:
            name: str | None = None
            value_node: ast.expr | None = None

            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                name = node.targets[0].id
                value_node = node.value

            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
            ):
                name = node.target.id
                value_node = node.value

            if name not in unresolved or value_node is None:
                continue

            try:
                compiled = compile(
                    ast.Expression(value_node),
                    str(APP_PATH),
                    "eval",
                )
                environment[name] = eval(
                    compiled,
                    {"__builtins__": {}},
                    environment,
                )
            except (NameError, TypeError):
                continue

            unresolved.remove(name)
            made_progress = True

        if not made_progress:
            break

    if unresolved:
        raise RuntimeError(
            "Unable to evaluate required app constants: "
            + ", ".join(sorted(unresolved))
        )

    return environment


def register_csv_resources(
    constants: dict[str, object],
) -> dict[Path, set[str]]:
    """Return every distinct CSV resource referenced by the app."""

    resources: dict[Path, set[str]] = defaultdict(set)

    cohorts = constants["COHORTS"]

    if not isinstance(cohorts, dict):
        raise TypeError("COHORTS must be a dictionary.")

    for cohort_label, configuration in cohorts.items():
        data_directory = Path(configuration["data_dir"])

        for logical_key, filename in configuration["files"].items():
            resources[data_directory / filename].add(
                f"cohort:{cohort_label}:file:{logical_key}"
            )

        resources[
            data_directory / configuration["coverage_file"]
        ].add(f"cohort:{cohort_label}:coverage")

        resources[
            data_directory / configuration["partition_file"]
        ].add(f"cohort:{cohort_label}:partition")

    registry_specs = [
        ("POINTS_DATA_DIR", "POINTS_FILES", "points"),
        (
            "ALL_TIME_AVERAGE_DATA_DIR",
            "ALL_TIME_AVERAGE_FILES",
            "average",
        ),
        (
            "SUPPLEMENTAL_DATA_DIR",
            "SUPPLEMENTAL_FILES",
            "supplemental",
        ),
    ]

    for directory_name, registry_name, family_name in registry_specs:
        directory = Path(constants[directory_name])
        registry = constants[registry_name]

        if not isinstance(registry, dict):
            raise TypeError(f"{registry_name} must be a dictionary.")

        for logical_key, filename in registry.items():
            resources[directory / filename].add(
                f"{family_name}:{logical_key}"
            )

    return resources


def inspect_database(
    database_label: str,
    database_path: Path,
) -> list[dict[str, object]]:
    """Inventory every base table using a read-only connection."""

    connection = duckdb.connect(str(database_path), read_only=True)

    try:
        table_rows = connection.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name
            """
        ).fetchall()

        columns_by_table: dict[
            tuple[str, str],
            list[tuple[str, str]],
        ] = defaultdict(list)

        for row in connection.execute(
            """
            SELECT
                table_schema,
                table_name,
                column_name,
                data_type
            FROM information_schema.columns
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name, ordinal_position
            """
        ).fetchall():
            table_schema, table_name, column_name, data_type = row
            columns_by_table[(table_schema, table_name)].append(
                (column_name, data_type)
            )

        inventory: list[dict[str, object]] = []

        for table_schema, table_name in table_rows:
            qualified_name = (
                f"{quote_identifier(table_schema)}."
                f"{quote_identifier(table_name)}"
            )
            row_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {qualified_name}"
                ).fetchone()[0]
            )
            columns_with_types = columns_by_table[
                (table_schema, table_name)
            ]

            inventory.append(
                {
                    "database_label": database_label,
                    "database_path": str(database_path),
                    "table_schema": table_schema,
                    "table_name": table_name,
                    "normalized_table_name": normalize_name(table_name),
                    "row_count": row_count,
                    "column_count": len(columns_with_types),
                    "columns": [
                        column for column, _ in columns_with_types
                    ],
                    "column_types": {
                        column: data_type
                        for column, data_type in columns_with_types
                    },
                }
            )

        return inventory
    finally:
        connection.close()


def inspect_csv(
    path: Path,
    counter: duckdb.DuckDBPyConnection,
) -> dict[str, object]:
    """Inspect one CSV without materializing it as a pandas frame."""

    if not path.is_file():
        return {
            "exists": False,
            "size_bytes": 0,
            "row_count": None,
            "columns": [],
            "column_count": 0,
        }

    columns = pd.read_csv(path, nrows=0).columns.astype(str).tolist()

    row_count = int(
        counter.execute(
            f"""
            SELECT COUNT(*)
            FROM read_csv_auto(
                {quote_literal(str(path))},
                header = true,
                sample_size = -1
            )
            """
        ).fetchone()[0]
    )

    return {
        "exists": True,
        "size_bytes": path.stat().st_size,
        "row_count": row_count,
        "columns": columns,
        "column_count": len(columns),
    }


def score_candidate(
    csv_path: Path,
    csv_metadata: dict[str, object],
    table: dict[str, object],
) -> tuple[float, list[str]]:
    """Score a conservative CSV-to-table source match."""

    score = 0.0
    reasons: list[str] = []

    csv_name = csv_path.stem
    table_name = str(table["table_name"])

    if csv_name == table_name:
        score += 100.0
        reasons.append("exact_table_name")
    elif normalize_name(csv_name) == normalize_name(table_name):
        score += 80.0
        reasons.append("normalized_table_name")

    csv_rows = csv_metadata["row_count"]

    if csv_rows is not None and int(csv_rows) == int(table["row_count"]):
        score += 20.0
        reasons.append("exact_row_count")

    csv_columns = set(csv_metadata["columns"])
    table_columns = set(table["columns"])

    if csv_columns == table_columns and csv_columns:
        score += 40.0
        reasons.append("exact_column_set")
    elif csv_columns and csv_columns.issubset(table_columns):
        score += 25.0
        reasons.append("csv_columns_subset")

    if csv_columns or table_columns:
        union = csv_columns | table_columns
        overlap = csv_columns & table_columns
        jaccard = len(overlap) / len(union)
        score += jaccard * 10.0

        if jaccard >= 0.95:
            reasons.append("column_overlap_95_plus")
        elif jaccard >= 0.75:
            reasons.append("column_overlap_75_plus")

    return score, reasons


def choose_mapping(
    csv_path: Path,
    csv_metadata: dict[str, object],
    m6_tables: list[dict[str, object]],
) -> dict[str, object]:
    """Choose the strongest Milestone 6 source-table candidate."""

    candidates: list[dict[str, object]] = []

    for table in m6_tables:
        score, reasons = score_candidate(csv_path, csv_metadata, table)

        if score <= 0:
            continue

        candidates.append(
            {
                "score": round(score, 6),
                "reasons": reasons,
                "table_schema": table["table_schema"],
                "table_name": table["table_name"],
                "row_count": table["row_count"],
                "columns": table["columns"],
            }
        )

    candidates.sort(
        key=lambda candidate: (
            -float(candidate["score"]),
            str(candidate["table_schema"]),
            str(candidate["table_name"]),
        )
    )

    if not candidates:
        return {
            "mapping_status": "unmapped",
            "candidate_count": 0,
            "best_candidate": None,
            "second_candidate": None,
        }

    best = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    best_score = float(best["score"])
    score_gap = (
        best_score - float(second["score"])
        if second is not None
        else best_score
    )

    exact_contract = (
        "exact_table_name" in best["reasons"]
        and "exact_row_count" in best["reasons"]
        and (
            "exact_column_set" in best["reasons"]
            or "csv_columns_subset" in best["reasons"]
        )
    )

    if exact_contract:
        status = "exact"
    elif best_score >= 100 and score_gap >= 10:
        status = "probable"
    else:
        status = "review"

    return {
        "mapping_status": status,
        "candidate_count": len(candidates),
        "best_candidate": best,
        "second_candidate": second,
    }


def write_tsv(
    path: Path,
    rows: list[dict[str, object]],
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


def main() -> None:
    """Run the read-only Phase 8B source audit."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for label, database_path in DATABASES.items():
        if not database_path.is_file():
            raise FileNotFoundError(f"Missing {label}: {database_path}")

    before_hashes = {
        label: sha256_file(path)
        for label, path in DATABASES.items()
    }

    hash_mismatches = {
        label: {
            "expected": EXPECTED_SOURCE_HASHES[label],
            "observed": observed_hash,
        }
        for label, observed_hash in before_hashes.items()
        if observed_hash != EXPECTED_SOURCE_HASHES[label]
    }

    if hash_mismatches:
        raise RuntimeError(
            "Frozen source hash mismatch before audit:\n"
            + json.dumps(hash_mismatches, indent=2)
        )

    constants = evaluate_app_constants()
    csv_resources = register_csv_resources(constants)

    database_inventory: list[dict[str, object]] = []

    for label, path in DATABASES.items():
        database_inventory.extend(inspect_database(label, path))

    m6_tables = [
        table
        for table in database_inventory
        if table["database_label"] == "milestone6_final"
    ]

    mapping_rows: list[dict[str, object]] = []
    counter = duckdb.connect(":memory:")

    try:
        for csv_path in sorted(csv_resources):
            csv_metadata = inspect_csv(csv_path, counter)
            mapping = choose_mapping(csv_path, csv_metadata, m6_tables)

            best = mapping["best_candidate"] or {}
            second = mapping["second_candidate"] or {}

            mapping_rows.append(
                {
                    "csv_path": str(csv_path.relative_to(ROOT)),
                    "logical_uses": "|".join(
                        sorted(csv_resources[csv_path])
                    ),
                    "exists": csv_metadata["exists"],
                    "size_bytes": csv_metadata["size_bytes"],
                    "csv_row_count": csv_metadata["row_count"],
                    "csv_column_count": csv_metadata["column_count"],
                    "csv_columns": "|".join(csv_metadata["columns"]),
                    "mapping_status": mapping["mapping_status"],
                    "candidate_count": mapping["candidate_count"],
                    "best_schema": best.get("table_schema", ""),
                    "best_table": best.get("table_name", ""),
                    "best_score": best.get("score", ""),
                    "best_reasons": "|".join(
                        best.get("reasons", [])
                    ),
                    "best_row_count": best.get("row_count", ""),
                    "second_schema": second.get("table_schema", ""),
                    "second_table": second.get("table_name", ""),
                    "second_score": second.get("score", ""),
                }
            )
    finally:
        counter.close()

    trend_tables = set(constants["MILESTONE7_TABLES"].values())

    specialized_tables = {
        str(configuration["table"])
        for configuration in constants[
            "EVENT_BALANCED_SPECIALIZED_ANALYSES"
        ].values()
        if configuration.get("table")
    }

    direct_rows: list[dict[str, object]] = []

    for database_label, requested_tables in (
        ("milestone7_trends", trend_tables),
        ("milestone7_specialized", specialized_tables),
    ):
        tables = [
            table
            for table in database_inventory
            if table["database_label"] == database_label
        ]
        by_name = {
            str(table["table_name"]): table
            for table in tables
        }

        for requested_table in sorted(requested_tables):
            table = by_name.get(requested_table)

            direct_rows.append(
                {
                    "database_label": database_label,
                    "requested_table": requested_table,
                    "exists": table is not None,
                    "table_schema": table["table_schema"] if table else "",
                    "row_count": table["row_count"] if table else "",
                    "column_count": table["column_count"] if table else "",
                    "columns": (
                        "|".join(table["columns"])
                        if table
                        else ""
                    ),
                }
            )

    inventory_rows: list[dict[str, object]] = []

    for table in database_inventory:
        inventory_rows.append(
            {
                "database_label": table["database_label"],
                "database_path": str(
                    Path(table["database_path"]).relative_to(ROOT)
                ),
                "table_schema": table["table_schema"],
                "table_name": table["table_name"],
                "row_count": table["row_count"],
                "column_count": table["column_count"],
                "columns": "|".join(table["columns"]),
                "column_types_json": json.dumps(
                    table["column_types"],
                    sort_keys=True,
                ),
            }
        )

    write_tsv(
        OUTPUT_DIR / "source_database_tables.tsv",
        inventory_rows,
        [
            "database_label",
            "database_path",
            "table_schema",
            "table_name",
            "row_count",
            "column_count",
            "columns",
            "column_types_json",
        ],
    )

    write_tsv(
        OUTPUT_DIR / "csv_to_milestone6_mapping.tsv",
        mapping_rows,
        [
            "csv_path",
            "logical_uses",
            "exists",
            "size_bytes",
            "csv_row_count",
            "csv_column_count",
            "csv_columns",
            "mapping_status",
            "candidate_count",
            "best_schema",
            "best_table",
            "best_score",
            "best_reasons",
            "best_row_count",
            "second_schema",
            "second_table",
            "second_score",
        ],
    )

    write_tsv(
        OUTPUT_DIR / "direct_milestone7_tables.tsv",
        direct_rows,
        [
            "database_label",
            "requested_table",
            "exists",
            "table_schema",
            "row_count",
            "column_count",
            "columns",
        ],
    )

    after_hashes = {
        label: sha256_file(path)
        for label, path in DATABASES.items()
    }

    exact_count = sum(
        row["mapping_status"] == "exact"
        for row in mapping_rows
    )
    probable_count = sum(
        row["mapping_status"] == "probable"
        for row in mapping_rows
    )
    review_count = sum(
        row["mapping_status"] == "review"
        for row in mapping_rows
    )
    unmapped_count = sum(
        row["mapping_status"] == "unmapped"
        for row in mapping_rows
    )
    missing_csv_count = sum(
        not bool(row["exists"])
        for row in mapping_rows
    )

    missing_direct_tables = [
        {
            "database_label": row["database_label"],
            "requested_table": row["requested_table"],
        }
        for row in direct_rows
        if not bool(row["exists"])
    ]

    source_hashes_unchanged = before_hashes == after_hashes

    summary = {
        "publication_version": "public_deployment_v1",
        "app_path": str(APP_PATH.relative_to(ROOT)),
        "csv_resource_count": len(mapping_rows),
        "csv_resource_bytes": sum(
            int(row["size_bytes"])
            for row in mapping_rows
        ),
        "csv_exact_milestone6_mappings": exact_count,
        "csv_probable_milestone6_mappings": probable_count,
        "csv_review_mappings": review_count,
        "csv_unmapped_resources": unmapped_count,
        "missing_csv_resources": missing_csv_count,
        "trend_tables_requested": len(trend_tables),
        "specialized_tables_requested": len(specialized_tables),
        "missing_direct_tables": missing_direct_tables,
        "source_database_table_counts": {
            label: sum(
                table["database_label"] == label
                for table in database_inventory
            )
            for label in DATABASES
        },
        "source_hashes_before": before_hashes,
        "source_hashes_after": after_hashes,
        "source_hashes_unchanged": source_hashes_unchanged,
    }

    (OUTPUT_DIR / "source_mapping_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("=" * 72)
    print("PHASE 8B SOURCE-MAPPING AUDIT")
    print("=" * 72)
    print(f"CSV resources registered: {len(mapping_rows):,}")
    print(f"Exact M6 mappings:       {exact_count:,}")
    print(f"Probable M6 mappings:    {probable_count:,}")
    print(f"Review mappings:         {review_count:,}")
    print(f"Unmapped CSV resources:  {unmapped_count:,}")
    print(f"Missing CSV resources:   {missing_csv_count:,}")
    print(f"Trend tables requested:  {len(trend_tables):,}")
    print(f"Specialized tables:      {len(specialized_tables):,}")
    print(f"Missing direct tables:   {len(missing_direct_tables):,}")
    print(f"Source hashes unchanged: {source_hashes_unchanged}")
    print(f"Output directory: {OUTPUT_DIR}")

    if missing_csv_count:
        raise SystemExit(
            "FAIL — one or more registered CSV resources are missing."
        )

    if missing_direct_tables:
        raise SystemExit(
            "FAIL — a required Milestone 7 table is missing."
        )

    if not source_hashes_unchanged:
        raise SystemExit(
            "FAIL — a frozen source database changed during audit."
        )

    print(
        "PASS — source mapping audit completed without modifying "
        "the frozen databases."
    )


if __name__ == "__main__":
    main()
