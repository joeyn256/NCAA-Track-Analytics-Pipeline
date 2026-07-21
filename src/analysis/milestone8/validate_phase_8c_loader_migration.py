#!/usr/bin/env python3
"""Validate the Phase 8C compact-database loader migration."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any, Final

from streamlit.testing.v1 import AppTest


ROOT: Final = Path(__file__).resolve().parents[3]
APP_PATH: Final = ROOT / "src/apps/seasonal_development_explorer.py"
MODULE_PATH: Final = ROOT / "src/apps/deployment_data.py"
DEPLOYMENT_DB: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8b_compact_publication"
    / "ncaa_track_public_explorer_v1.duckdb"
)
DEPLOYMENT_MANIFEST: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8b_compact_publication"
    / "deployment_manifest.json"
)
OUTPUT_DIR: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8c_loader_migration_validation"
)
REQUIREMENTS_PATH: Final = ROOT / "requirements.txt"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def dotted_call_name(call: ast.Call) -> str:
    node = call.func
    pieces = []

    while isinstance(node, ast.Attribute):
        pieces.append(node.attr)
        node = node.value

    if isinstance(node, ast.Name):
        pieces.append(node.id)

    return ".".join(reversed(pieces))


def function_node(
    tree: ast.Module,
    name: str,
) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == name
    ]

    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one function named {name}; "
            f"found {len(matches)}."
        )

    return matches[0]


def import_deployment_module():
    spec = importlib.util.spec_from_file_location(
        "deployment_data_validation",
        MODULE_PATH,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            "Could not import deployment_data.py."
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for path in (
        APP_PATH,
        MODULE_PATH,
        DEPLOYMENT_DB,
        DEPLOYMENT_MANIFEST,
        REQUIREMENTS_PATH,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)

    manifest = json.loads(
        DEPLOYMENT_MANIFEST.read_text(encoding="utf-8")
    )
    expected_hash = str(
        manifest["database"]["sha256"]
    )
    before_hash = sha256_file(DEPLOYMENT_DB)

    if before_hash != expected_hash:
        raise RuntimeError(
            "Deployment database hash does not match manifest."
        )

    app_source = APP_PATH.read_text(encoding="utf-8")
    module_source = MODULE_PATH.read_text(encoding="utf-8")

    compile(app_source, str(APP_PATH), "exec")
    compile(module_source, str(MODULE_PATH), "exec")

    tree = ast.parse(
        app_source,
        filename=str(APP_PATH),
    )

    load_csv = function_node(tree, "load_csv")
    load_specialized = function_node(
        tree,
        "load_event_balanced_specialized_table",
    )
    load_trends = function_node(
        tree,
        "load_milestone7_table",
    )

    loader_checks: dict[str, Any] = {
        "load_csv_has_no_pd_read_csv": not any(
            isinstance(child, ast.Call)
            and dotted_call_name(child) == "pd.read_csv"
            for child in ast.walk(load_csv)
        ),
        "specialized_loader_has_no_direct_connect": not any(
            isinstance(child, ast.Call)
            and dotted_call_name(child) == "duckdb.connect"
            for child in ast.walk(load_specialized)
        ),
        "trend_loader_has_no_direct_connect": not any(
            isinstance(child, ast.Call)
            and dotted_call_name(child) == "duckdb.connect"
            for child in ast.walk(load_trends)
        ),
        "app_imports_deployment_module": (
            "from src.apps.deployment_data import ("
            in app_source
        ),
        "app_uses_public_database_path": (
            "PUBLIC_DATABASE_PATH" in app_source
        ),
        "requirements_declares_duckdb": any(
            line.strip().lower().startswith("duckdb")
            for line in REQUIREMENTS_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
        ),
    }

    previous_path = os.environ.get(
        "NCAA_TRACK_PUBLIC_DB"
    )
    os.environ["NCAA_TRACK_PUBLIC_DB"] = str(
        DEPLOYMENT_DB
    )

    try:
        module = import_deployment_module()

        mapping_checks = {
            "csv_mapping_count": (
                len(module.CSV_RESOURCE_TABLES) == 47
            ),
            "trend_mapping_count": (
                len(module.TREND_RESOURCE_TABLES) == 14
            ),
            "specialized_mapping_count": (
                len(
                    module.SPECIALIZED_RESOURCE_TABLES
                )
                == 20
            ),
            "resolved_database_path": (
                Path(module.PUBLIC_DATABASE_PATH)
                == DEPLOYMENT_DB
            ),
        }

        representative = [
            ("average", "all_school_rankings", 361),
            (
                "official",
                "event_balanced_overall_combined",
                27764,
            ),
            ("trends", "explorer_program_index", 352),
            (
                "specialized",
                "specialized_ranking_leaders",
                11,
            ),
        ]

        query_rows = []
        connection = module.connect_public_db()

        try:
            for schema, table, expected_rows in representative:
                started = time.perf_counter()
                observed_rows = int(
                    connection.execute(
                        f'SELECT COUNT(*) FROM '
                        f'"{schema}"."{table}"'
                    ).fetchone()[0]
                )
                elapsed = time.perf_counter() - started

                query_rows.append(
                    {
                        "schema": schema,
                        "table": table,
                        "expected_rows": expected_rows,
                        "observed_rows": observed_rows,
                        "seconds": round(elapsed, 6),
                        "passed": (
                            expected_rows == observed_rows
                        ),
                    }
                )
        finally:
            connection.close()

        started = time.perf_counter()
        app_test = AppTest.from_file(str(APP_PATH))
        app_test.run(timeout=180)
        app_test_seconds = time.perf_counter() - started

        app_test_checks = {
            "exceptions": len(app_test.exception),
            "errors": len(app_test.error),
            "warnings": len(app_test.warning),
            "passed": (
                len(app_test.exception) == 0
                and len(app_test.error) == 0
            ),
            "seconds": round(app_test_seconds, 6),
        }
    finally:
        if previous_path is None:
            os.environ.pop(
                "NCAA_TRACK_PUBLIC_DB",
                None,
            )
        else:
            os.environ[
                "NCAA_TRACK_PUBLIC_DB"
            ] = previous_path

    after_hash = sha256_file(DEPLOYMENT_DB)

    hard_checks = {
        **loader_checks,
        **mapping_checks,
        "representative_queries_pass": all(
            bool(row["passed"])
            for row in query_rows
        ),
        "app_test_passed": bool(
            app_test_checks["passed"]
        ),
        "deployment_hash_unchanged": (
            before_hash == after_hash
        ),
    }

    summary = {
        "loader_checks": loader_checks,
        "mapping_checks": mapping_checks,
        "representative_queries": query_rows,
        "app_test": app_test_checks,
        "deployment_hash_before": before_hash,
        "deployment_hash_after": after_hash,
        "hard_checks": hard_checks,
        "passed": all(hard_checks.values()),
    }

    (
        OUTPUT_DIR / "validation_summary.json"
    ).write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("=" * 76)
    print("PHASE 8C LOADER-MIGRATION VALIDATION")
    print("=" * 76)

    for name, passed in hard_checks.items():
        print(f"{name}: {passed}")

    print()
    print(
        "AppTest seconds: "
        f"{app_test_checks['seconds']:.6f}"
    )
    print(
        "AppTest exceptions: "
        f"{app_test_checks['exceptions']}"
    )
    print(
        "AppTest errors: "
        f"{app_test_checks['errors']}"
    )
    print(
        "AppTest warnings: "
        f"{app_test_checks['warnings']}"
    )
    print(
        "Deployment hash unchanged: "
        f"{before_hash == after_hash}"
    )
    print(f"Output directory: {OUTPUT_DIR}")

    if not summary["passed"]:
        raise SystemExit(
            "FAIL — Phase 8C loader migration validation failed."
        )

    print()
    print(
        "PASS — the Streamlit explorer now loads from the "
        "compact deployment database."
    )


if __name__ == "__main__":
    main()
