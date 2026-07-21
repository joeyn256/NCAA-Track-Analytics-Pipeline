#!/usr/bin/env python3
"""Build and validate the compact Milestone 8 deployment publication."""

from __future__ import annotations

import csv
import gzip
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

import duckdb
import pandas as pd

from audit_phase_8b_source_mapping import DATABASES, EXPECTED_SOURCE_HASHES, ROOT, sha256_file

VERSION: Final = "public_deployment_v1"
CONTRACT_DIR: Final = ROOT / "data/processed/milestone8" / VERSION / "phase_8b_publication_contract"
OUTPUT_DIR: Final = ROOT / "data/processed/milestone8" / VERSION / "phase_8b_compact_publication"
CONTRACT_PATH: Final = CONTRACT_DIR / "deployment_resource_contract.tsv"
ANALYSIS_PATH: Final = CONTRACT_DIR / "specialized_analysis_registry.tsv"
FINAL_DB: Final = OUTPUT_DIR / "ncaa_track_public_explorer_v1.duckdb"
TEMP_DB: Final = OUTPUT_DIR / "ncaa_track_public_explorer_v1.building.duckdb"
FINAL_GZ: Final = Path(str(FINAL_DB) + ".gz")
TEMP_GZ: Final = Path(str(FINAL_GZ) + ".building")

EXPECTED = {
    "resources": 81,
    "csv": 47,
    "trends": 14,
    "specialized_tables": 20,
    "specialized_analyses": 12,
    "specialized_result_tables": 9,
}


def qi(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def ql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def qname(schema: str, table: str) -> str:
    return f"{qi(schema)}.{qi(table)}"


def source_hashes() -> dict[str, str]:
    return {label: sha256_file(path) for label, path in DATABASES.items()}


def ordered_columns(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> list[str]:
    return [
        row[0]
        for row in con.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = ? AND table_name = ?
            ORDER BY ordinal_position
            """,
            [schema, table],
        ).fetchall()
    ]


def row_count(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> int:
    return int(con.execute(f"SELECT COUNT(*) FROM {qname(schema, table)}").fetchone()[0])


def distinct_row_count(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> int:
    return int(
        con.execute(
            f"SELECT COUNT(*) FROM (SELECT DISTINCT * FROM {qname(schema, table)})"
        ).fetchone()[0]
    )


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def attach_sources(con: duckdb.DuckDBPyConnection) -> None:
    aliases = {
        "milestone6_final": "m6",
        "milestone7_trends": "m7_trends",
        "milestone7_specialized": "m7_specialized",
    }
    for label, path in DATABASES.items():
        con.execute(f"ATTACH {ql(str(path))} AS {qi(aliases[label])} (READ_ONLY)")


def find_2020_outdoor(con: duckdb.DuckDBPyConnection, resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    year_names = {"year", "season_year", "calendar_year", "season_end_year"}
    season_names = {"season", "season_type", "season_name", "competition_season"}
    violations: list[dict[str, Any]] = []

    for resource in resources:
        schema = str(resource["deployment_schema"])
        table = str(resource["deployment_table"])
        columns = set(ordered_columns(con, schema, table))

        for year_col in sorted(columns & year_names):
            for season_col in sorted(columns & season_names):
                count = int(
                    con.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM {qname(schema, table)}
                        WHERE TRY_CAST({qi(year_col)} AS INTEGER) = 2020
                          AND LOWER(CAST({qi(season_col)} AS VARCHAR)) LIKE '%outdoor%'
                        """
                    ).fetchone()[0]
                )
                if count:
                    violations.append(
                        {
                            "schema": schema,
                            "table": table,
                            "year_column": year_col,
                            "season_column": season_col,
                            "rows": count,
                        }
                    )

    return violations


def specialized_text_evidence(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    inbound = 0
    unavailable = 0
    evidence_tables: list[str] = []

    tables = con.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE' AND table_schema = 'specialized'
        ORDER BY table_name
        """
    ).fetchall()

    for (table,) in tables:
        string_columns = [
            row[0]
            for row in con.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'specialized'
                  AND table_name = ?
                  AND data_type IN ('VARCHAR', 'CHAR', 'TEXT')
                ORDER BY ordinal_position
                """,
                [table],
            ).fetchall()
        ]
        if not string_columns:
            continue

        parts = [f"COALESCE(CAST({qi(col)} AS VARCHAR), '')" for col in string_columns]
        text_expr = "LOWER(CONCAT_WS(' ', " + ", ".join(parts) + "))"
        inbound_count = int(
            con.execute(
                f"SELECT COUNT(*) FROM specialized.{qi(table)} "
                f"WHERE {text_expr} LIKE '%inbound%' AND {text_expr} LIKE '%transfer%'"
            ).fetchone()[0]
        )
        unavailable_count = int(
            con.execute(
                f"SELECT COUNT(*) FROM specialized.{qi(table)} "
                f"WHERE {text_expr} LIKE '%unavailable%'"
            ).fetchone()[0]
        )
        if inbound_count or unavailable_count:
            evidence_tables.append(f"specialized.{table}")
        inbound += inbound_count
        unavailable += unavailable_count

    return {
        "inbound_transfer_text_matches": inbound,
        "unavailable_text_matches": unavailable,
        "evidence_tables": evidence_tables,
    }


def gzip_file(source: Path, destination: Path) -> None:
    with source.open("rb") as src, destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            shutil.copyfileobj(src, gz, length=8 * 1024 * 1024)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for required in (CONTRACT_PATH, ANALYSIS_PATH):
        if not required.is_file():
            raise FileNotFoundError(required)

    hashes_before = source_hashes()
    if hashes_before != EXPECTED_SOURCE_HASHES:
        raise RuntimeError(
            "Frozen source hash mismatch before build:\n"
            + json.dumps({"expected": EXPECTED_SOURCE_HASHES, "observed": hashes_before}, indent=2)
        )

    contract = pd.read_csv(CONTRACT_PATH, sep="\t", keep_default_na=False)
    analyses = pd.read_csv(ANALYSIS_PATH, sep="\t", keep_default_na=False)

    if len(contract) != EXPECTED["resources"]:
        raise RuntimeError(f"Expected {EXPECTED['resources']} resource tables; found {len(contract)}")
    if len(analyses) != EXPECTED["specialized_analyses"]:
        raise RuntimeError(f"Expected {EXPECTED['specialized_analyses']} analyses; found {len(analyses)}")

    observed_sources = contract["source_label"].value_counts().to_dict()
    expected_sources = {
        "frozen_app_csv": EXPECTED["csv"],
        "milestone7_trends": EXPECTED["trends"],
        "milestone7_specialized": EXPECTED["specialized_tables"],
    }
    if observed_sources != expected_sources:
        raise RuntimeError(
            "Unexpected contract source counts:\n"
            + json.dumps({"expected": expected_sources, "observed": observed_sources}, indent=2)
        )

    for path in (TEMP_DB, FINAL_DB, TEMP_GZ, FINAL_GZ):
        path.unlink(missing_ok=True)

    con = duckdb.connect(str(TEMP_DB))
    manifest_rows: list[dict[str, Any]] = []
    hard_checks: list[dict[str, Any]] = []
    aliases = {
        "milestone7_trends": "m7_trends",
        "milestone7_specialized": "m7_specialized",
    }

    try:
        attach_sources(con)
        for schema in sorted(set(contract["deployment_schema"].astype(str))):
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {qi(schema)}")
        con.execute("CREATE SCHEMA IF NOT EXISTS deployment_meta")

        resources = contract.to_dict("records")
        total = len(resources)

        for index, resource in enumerate(resources, start=1):
            source_label = str(resource["source_label"])
            source_path = str(resource["source_path"])
            source_schema = str(resource["source_schema"])
            source_table = str(resource["source_table"])
            target_schema = str(resource["deployment_schema"])
            target_table = str(resource["deployment_table"])
            expected_rows = int(resource["row_count"])
            expected_cols = str(resource["columns"]).split("|") if str(resource["columns"]) else []

            print(f"[{index:02d}/{total:02d}] {target_schema}.{target_table}")

            if source_label == "frozen_app_csv":
                absolute = ROOT / source_path
                if not absolute.is_file():
                    raise FileNotFoundError(absolute)
                con.execute(
                    f"""
                    CREATE TABLE {qname(target_schema, target_table)} AS
                    SELECT * FROM read_csv_auto(
                        {ql(str(absolute))},
                        header = true,
                        sample_size = -1,
                        ignore_errors = false
                    )
                    """
                )
            elif source_label in aliases:
                source_name = (
                    f"{qi(aliases[source_label])}.{qi(source_schema)}.{qi(source_table)}"
                )
                con.execute(
                    f"CREATE TABLE {qname(target_schema, target_table)} AS SELECT * FROM {source_name}"
                )
            else:
                raise RuntimeError(f"Unsupported source label: {source_label}")

            observed_rows = row_count(con, target_schema, target_table)
            observed_cols = ordered_columns(con, target_schema, target_table)
            if observed_rows != expected_rows:
                raise RuntimeError(
                    f"Row mismatch for {target_schema}.{target_table}: "
                    f"expected {expected_rows}, observed {observed_rows}"
                )
            if observed_cols != expected_cols:
                raise RuntimeError(
                    f"Column mismatch for {target_schema}.{target_table}\n"
                    f"Expected: {expected_cols}\nObserved: {observed_cols}"
                )

            distinct_rows = distinct_row_count(con, target_schema, target_table)
            manifest_rows.append(
                {
                    **resource,
                    "observed_row_count": observed_rows,
                    "observed_column_count": len(observed_cols),
                    "full_row_duplicate_count": observed_rows - distinct_rows,
                    "validation_status": "PASS",
                }
            )

        con.register("_resource_manifest", pd.DataFrame(manifest_rows))
        con.execute("CREATE TABLE deployment_meta.resource_manifest AS SELECT * FROM _resource_manifest")
        con.unregister("_resource_manifest")

        con.register("_analysis_registry", analyses)
        con.execute(
            "CREATE TABLE deployment_meta.specialized_analysis_registry AS SELECT * FROM _analysis_registry"
        )
        con.unregister("_analysis_registry")

        source_registry = pd.DataFrame(
            [
                {
                    "source_label": label,
                    "source_path": str(path.relative_to(ROOT)),
                    "sha256": hashes_before[label],
                    "size_bytes": path.stat().st_size,
                    "attached_read_only": True,
                }
                for label, path in DATABASES.items()
            ]
        )
        con.register("_source_registry", source_registry)
        con.execute(
            "CREATE TABLE deployment_meta.source_database_registry AS SELECT * FROM _source_registry"
        )
        con.unregister("_source_registry")

        publication_registry = pd.DataFrame(
            [
                {
                    "publication_version": VERSION,
                    "database_filename": FINAL_DB.name,
                    "official_model": "Enhanced Balanced Production",
                    "balanced_companion": "Original Balanced Production v4.1",
                    "efficiency_companion": "Average Development",
                    "official_event_count": 27,
                    "registered_event_group_count": 7,
                    "positive_points_per_partition": 100000,
                    "negative_point_cap_per_partition": 100000,
                    "support_reliability_k": 191,
                    "resource_table_count": EXPECTED["resources"],
                    "built_utc": datetime.now(timezone.utc).isoformat(),
                }
            ]
        )
        con.register("_publication_registry", publication_registry)
        con.execute(
            "CREATE TABLE deployment_meta.publication_registry AS SELECT * FROM _publication_registry"
        )
        con.unregister("_publication_registry")

        outdoor_violations = find_2020_outdoor(con, resources)
        outdoor_rows_are_source_preserved = all(
            item["schema"] in {
                "average_seasonal_broad",
                "average_seasonal_elite",
            }
            for item in outdoor_violations
        )
        specialized_evidence = specialized_text_evidence(con)
        observed_resource_tables = len(resources)
        observed_specialized_tables = int(
            con.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_type = 'BASE TABLE' AND table_schema = 'specialized'
                """
            ).fetchone()[0]
        )
        observed_result_tables = int(
            contract.loc[
                (contract["deployment_schema"] == "specialized")
                & (contract["logical_uses"] == "registered_result_table")
            ].shape[0]
        )

        checks = [
            ("resource_table_count", observed_resource_tables == EXPECTED["resources"], EXPECTED["resources"], observed_resource_tables),
            ("specialized_analysis_count", len(analyses) == EXPECTED["specialized_analyses"], EXPECTED["specialized_analyses"], len(analyses)),
            ("specialized_source_table_count", observed_specialized_tables == EXPECTED["specialized_tables"], EXPECTED["specialized_tables"], observed_specialized_tables),
            ("specialized_result_table_count", observed_result_tables == EXPECTED["specialized_result_tables"], EXPECTED["specialized_result_tables"], observed_result_tables),
            (
                "2020_outdoor_rows_preserved_from_frozen_sources",
                outdoor_rows_are_source_preserved,
                (
                    "Any explicit 2020 Outdoor rows must occur only in the "
                    "directly copied Average Development seasonal publications; "
                    "no interpolation, zero filling, carry-forward, or fabricated "
                    "performances are permitted."
                ),
                outdoor_violations,
            ),
            (
                "inbound_transfer_status_evidence",
                specialized_evidence["inbound_transfer_text_matches"] > 0
                and specialized_evidence["unavailable_text_matches"] > 0,
                "inbound-transfer and unavailable text evidence",
                specialized_evidence,
            ),
            ("all_resource_rows_validated", len(manifest_rows) == EXPECTED["resources"], EXPECTED["resources"], len(manifest_rows)),
        ]

        for name, passed, expected, observed in checks:
            hard_checks.append(
                {
                    "check_name": name,
                    "passed": bool(passed),
                    "expected": json.dumps(expected, sort_keys=True)
                    if isinstance(expected, (dict, list))
                    else str(expected),
                    "observed": json.dumps(observed, sort_keys=True)
                    if isinstance(observed, (dict, list))
                    else str(observed),
                }
            )

        con.register("_hard_checks", pd.DataFrame(hard_checks))
        con.execute("CREATE TABLE deployment_meta.hard_checks AS SELECT * FROM _hard_checks")
        con.unregister("_hard_checks")

        failed = [check for check in hard_checks if not check["passed"]]
        if failed:
            raise RuntimeError("Deployment hard checks failed:\n" + json.dumps(failed, indent=2))

        con.execute("CHECKPOINT")
    except Exception:
        con.close()
        TEMP_DB.unlink(missing_ok=True)
        raise
    else:
        con.close()

    os.replace(TEMP_DB, FINAL_DB)

    hashes_after = source_hashes()
    if hashes_after != hashes_before:
        FINAL_DB.unlink(missing_ok=True)
        raise RuntimeError("A frozen source database changed during the build")

    gzip_file(FINAL_DB, TEMP_GZ)
    os.replace(TEMP_GZ, FINAL_GZ)

    database_size = FINAL_DB.stat().st_size
    gzip_size = FINAL_GZ.stat().st_size
    database_sha = sha256_file(FINAL_DB)
    gzip_sha = sha256_file(FINAL_GZ)

    build_manifest = {
        "publication_version": VERSION,
        "database": {
            "path": str(FINAL_DB.relative_to(ROOT)),
            "size_bytes": database_size,
            "size_mib": round(database_size / 1024**2, 3),
            "sha256": database_sha,
        },
        "gzip": {
            "path": str(FINAL_GZ.relative_to(ROOT)),
            "size_bytes": gzip_size,
            "size_mib": round(gzip_size / 1024**2, 3),
            "sha256": gzip_sha,
            "compression_ratio": round(gzip_size / database_size, 6),
        },
        "resource_tables": EXPECTED["resources"],
        "metadata_tables": 5,
        "specialized_analyses": EXPECTED["specialized_analyses"],
        "specialized_unique_result_tables": EXPECTED["specialized_result_tables"],
        "source_hashes_before": hashes_before,
        "source_hashes_after": hashes_after,
        "source_hashes_unchanged": hashes_before == hashes_after,
        "hard_checks": hard_checks,
    }

    (OUTPUT_DIR / "deployment_manifest.json").write_text(
        json.dumps(build_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_tsv(OUTPUT_DIR / "resource_manifest.tsv", manifest_rows, list(manifest_rows[0].keys()))
    write_tsv(
        OUTPUT_DIR / "deployment_hard_checks.tsv",
        hard_checks,
        ["check_name", "passed", "expected", "observed"],
    )
    (OUTPUT_DIR / "artifact_checksums.sha256").write_text(
        f"{database_sha}  {FINAL_DB.name}\n{gzip_sha}  {FINAL_GZ.name}\n",
        encoding="utf-8",
    )

    print()
    print("=" * 78)
    print("PHASE 8B COMPACT DEPLOYMENT PUBLICATION")
    print("=" * 78)
    print(f"Resource tables:      {EXPECTED['resources']}")
    print("Metadata tables:      5")
    print(f"Database size:        {database_size:,} bytes ({database_size / 1024**2:.3f} MiB)")
    print(f"Gzip size:            {gzip_size:,} bytes ({gzip_size / 1024**2:.3f} MiB)")
    print(f"Compression ratio:    {gzip_size / database_size:.4f}")
    print(f"Database SHA-256:     {database_sha}")
    print(f"Gzip SHA-256:         {gzip_sha}")
    print(f"Source hashes intact: {hashes_before == hashes_after}")
    print(f"Output directory:     {OUTPUT_DIR}")
    print("PASS — compact deployment publication built and validated.")


if __name__ == "__main__":
    main()
