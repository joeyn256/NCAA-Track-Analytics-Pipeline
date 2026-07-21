#!/usr/bin/env python3
"""Build Milestone 7 Phase 7D consolidated final publication.

This publication combines the validated Enhanced Balanced Production products
from Phases 7A.1, 7A.2, 7B, and 7C into one read-only-source, explorer-ready
DuckDB database. It does not retrain models or mutate upstream publications.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import duckdb


DATASET_VERSION = "seasonal_program_trends_v1"
PHASE_VERSION = "phase_7d_final_publication_v1"
MODEL_KEY = "enhanced_balanced_production"
MODEL_LABEL = "Enhanced Balanced Production"

DEFAULT_OVERALL_DB = Path(
    "data/processed/milestone7/seasonal_program_trends_v1/"
    "phase_7a_overall_trends/seasonal_program_trends_v1.duckdb"
)
DEFAULT_DETAIL_DB = Path(
    "data/processed/milestone7/seasonal_program_trends_v1/"
    "phase_7a_event_group_trends/seasonal_program_trends_v1.duckdb"
)
DEFAULT_TRAJECTORY_DB = Path(
    "data/processed/milestone7/seasonal_program_trends_v1/"
    "phase_7b_program_trajectory/seasonal_program_trends_v1.duckdb"
)
DEFAULT_COMPARISON_DB = Path(
    "data/processed/milestone7/seasonal_program_trends_v1/"
    "phase_7c_program_comparison/seasonal_program_trends_v1.duckdb"
)
DEFAULT_OUTPUT_DIR = Path(
    "data/processed/milestone7/seasonal_program_trends_v1/"
    "phase_7d_final_publication"
)
OUTPUT_DB_NAME = "seasonal_program_trends_v1.duckdb"


@dataclass(frozen=True)
class Check:
    check_name: str
    status: str
    observed_value: object
    expected_value: object
    details: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Consolidate validated Milestone 7 Enhanced Balanced Production "
            "trend and comparison products into the final explorer-ready DB."
        )
    )
    parser.add_argument("--overall-db", type=Path, default=DEFAULT_OVERALL_DB)
    parser.add_argument("--detail-db", type=Path, default=DEFAULT_DETAIL_DB)
    parser.add_argument("--trajectory-db", type=Path, default=DEFAULT_TRAJECTORY_DB)
    parser.add_argument("--comparison-db", type=Path, default=DEFAULT_COMPARISON_DB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def scalar(connection: duckdb.DuckDBPyConnection, sql: str) -> object:
    row = connection.execute(sql).fetchone()
    return None if row is None else row[0]


def table_exists(
    connection: duckdb.DuckDBPyConnection,
    catalog_name: str,
    table_name: str,
) -> bool:
    count = scalar(
        connection,
        f"""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_catalog = '{catalog_name}'
          AND table_schema = 'main'
          AND table_name = '{table_name}'
        """,
    )
    return int(count or 0) == 1


def require_tables(
    connection: duckdb.DuckDBPyConnection,
    catalog_name: str,
    table_names: Iterable[str],
) -> None:
    missing = [
        name for name in table_names
        if not table_exists(connection, catalog_name, name)
    ]
    if missing:
        raise RuntimeError(
            f"Missing required tables in {catalog_name}: " + ", ".join(missing)
        )


def add_check(
    checks: list[Check],
    name: str,
    observed: object,
    expected: object,
    passed: bool,
    details: str,
) -> None:
    checks.append(
        Check(
            check_name=name,
            status="PASS" if passed else "FAIL",
            observed_value=observed,
            expected_value=expected,
            details=details,
        )
    )


def copy_table(
    connection: duckdb.DuckDBPyConnection,
    catalog: str,
    source_table: str,
    target_table: str | None = None,
) -> None:
    target = target_table or source_table
    connection.execute(
        f"CREATE TABLE {target} AS SELECT * FROM {catalog}.main.{source_table}"
    )


def create_metadata(connection: duckdb.DuckDBPyConnection, built_at: str) -> None:
    connection.execute(
        """
        CREATE TABLE final_publication_metadata (
            metadata_key VARCHAR,
            metadata_value VARCHAR,
            details VARCHAR
        )
        """
    )
    rows = [
        (
            "dataset_version",
            DATASET_VERSION,
            "Versioned Milestone 7 seasonal trend and program-comparison dataset.",
        ),
        (
            "phase_version",
            PHASE_VERSION,
            "Consolidated final publication for Milestone 7.",
        ),
        (
            "official_model",
            MODEL_KEY,
            "Enhanced Balanced Production is the exclusive published model.",
        ),
        (
            "official_model_label",
            MODEL_LABEL,
            "Human-readable official model label.",
        ),
        (
            "publication_mode",
            "enhanced_primary_only",
            "Original v4.1 and Average Development remain frozen companions upstream.",
        ),
        (
            "built_at_utc",
            built_at,
            "UTC build timestamp for this final publication.",
        ),
        (
            "year_over_year_policy",
            "exact_previous_calendar_year_same_season_type",
            "No interpolation, nearest-year matching, zero fill, or carry-forward.",
        ),
        (
            "indoor_outdoor_policy",
            "exact_same_calendar_year",
            "Outdoor-minus-Indoor comparisons require both exact same-year observations.",
        ),
        (
            "rolling_windows",
            "three_and_five_calendar_years",
            "Missing seasons reduce coverage and are never fabricated.",
        ),
        (
            "interpretation",
            "descriptive_observational",
            "Milestone 7 describes program trajectories and does not establish causality.",
        ),
    ]
    connection.executemany(
        "INSERT INTO final_publication_metadata VALUES (?, ?, ?)", rows
    )

    connection.execute(
        """
        CREATE TABLE final_model_registry AS
        SELECT * FROM (
            VALUES (
                1,
                'enhanced_balanced_production',
                'Enhanced Balanced Production',
                'official_primary',
                TRUE,
                191.0,
                100000.0,
                100000.0,
                'Total reliable athlete development production with support reliability and a symmetric negative cap.'
            )
        ) AS registry(
            display_order,
            model_key,
            model_label,
            model_role,
            is_official,
            support_k,
            positive_event_budget,
            negative_event_cap,
            interpretation
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE final_methodology AS
        SELECT * FROM (
            VALUES
                (1, 'model_scope', 'Enhanced Balanced Production only',
                 'The final Milestone 7 publication contains only the official primary model.'),
                (2, 'year_over_year', 'exact previous calendar year',
                 'Comparisons require the same school, cohort, scope, gender, and season type in year minus one.'),
                (3, 'rank_improvement', 'previous rank minus current rank',
                 'Positive values indicate movement toward rank 1.'),
                (4, 'rank_strength', 'partition-normalized percentile',
                 'Higher values indicate a stronger rank after accounting for changing partition size.'),
                (5, 'rolling_windows', 'three and five calendar years',
                 'Slopes require at least three eligible observations; missing years remain gaps.'),
                (6, 'indoor_outdoor', 'same calendar year only',
                 'Outdoor-minus-Indoor products require exact same-year comparable observations.'),
                (7, 'event_taxonomy', '27 frozen production events',
                 '500m, 600m, and 1000m are excluded; relays and cross country are excluded.'),
                (8, 'group_taxonomy', 'seven frozen production groups',
                 'Steeplechase is included in Distance; unsupported groups remain explicit gaps.'),
                (9, 'head_to_head', 'on-demand comparison-ready rows',
                 'School pairs are computed from compact metric rows instead of a large Cartesian table.'),
                (10, 'source_mutation', 'forbidden',
                 'All Phase 7A through Phase 7C databases are attached read-only and hash-checked.')
        ) AS methodology(
            display_order,
            methodology_key,
            methodology_value,
            explanation
        )
        """
    )


def create_source_registry(
    connection: duckdb.DuckDBPyConnection,
    inputs: list[tuple[str, Path, str]],
) -> None:
    connection.execute(
        """
        CREATE TABLE final_source_phase_registry (
            source_order INTEGER,
            source_phase VARCHAR,
            source_path VARCHAR,
            size_bytes BIGINT,
            sha256 VARCHAR,
            access_mode VARCHAR,
            source_gate_status VARCHAR
        )
        """
    )
    rows = []
    for order, (phase, path, digest) in enumerate(inputs, start=1):
        rows.append(
            (
                order,
                phase,
                str(path.resolve()),
                path.stat().st_size,
                digest,
                "read_only",
                "PASS",
            )
        )
    connection.executemany(
        "INSERT INTO final_source_phase_registry VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def copy_validated_tables(connection: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    copied: list[tuple[str, str]] = []

    groups: dict[str, list[str]] = {
        "overall_src": [
            "trend_season_registry",
            "school_metadata",
            "school_season_overall_base",
            "overall_partition_registry",
            "school_season_overall_movement",
            "school_indoor_outdoor_comparison",
            "school_multiseason_trends",
            "trend_partition_summary",
            "trend_missingness_summary",
            "trend_methodology",
        ],
        "detail_src": [
            "balanced_event_registry",
            "school_season_event_base",
            "school_season_event_movement",
            "school_event_multiseason_trends",
            "school_season_group_base",
            "school_season_group_movement",
            "school_group_multiseason_trends",
            "event_trend_partition_summary",
            "group_trend_partition_summary",
            "trend_comparison_status_summary",
        ],
        "trajectory_src": [
            "program_window_trajectory",
            "program_rise_fall_summary",
            "program_latest_snapshot",
            "program_trajectory_leaderboard",
            "program_group_profile",
            "program_event_profile",
            "program_comparison_snapshot",
            "program_trajectory_methodology",
        ],
        "comparison_src": [
            "program_peer_context",
            "program_conference_leaderboard",
            "program_indoor_outdoor_latest",
            "program_indoor_outdoor_history",
            "program_comparison_metric_long",
            "program_comparison_snapshot_enriched",
            "comparison_partition_registry",
            "program_comparison_methodology",
        ],
    }

    for catalog, tables in groups.items():
        for table in tables:
            copy_table(connection, catalog, table)
            copied.append((catalog, table))
    return copied


def create_explorer_tables(connection: duckdb.DuckDBPyConnection) -> None:
    aliases = [
        ("explorer_program_summary", "program_comparison_snapshot_enriched"),
        ("explorer_program_metric_long", "program_comparison_metric_long"),
        ("explorer_overall_season_series", "school_season_overall_base"),
        ("explorer_overall_yoy_series", "school_season_overall_movement"),
        ("explorer_indoor_outdoor_series", "school_indoor_outdoor_comparison"),
        ("explorer_overall_window_series", "school_multiseason_trends"),
        ("explorer_group_season_series", "school_season_group_base"),
        ("explorer_group_yoy_series", "school_season_group_movement"),
        ("explorer_group_window_series", "school_group_multiseason_trends"),
        ("explorer_event_season_series", "school_season_event_base"),
        ("explorer_event_yoy_series", "school_season_event_movement"),
        ("explorer_event_window_series", "school_event_multiseason_trends"),
    ]
    for target, source in aliases:
        connection.execute(f"CREATE TABLE {target} AS SELECT * FROM {source}")

    connection.execute(
        """
        CREATE TABLE explorer_program_index AS
        SELECT
            resolved_school_id,
            ANY_VALUE(school_name) AS school_name,
            ANY_VALUE(state_code) AS state_code,
            ANY_VALUE(city) AS city,
            ANY_VALUE(conference_name) AS conference_name,
            ANY_VALUE(division_name) AS division_name,
            COUNT(*) AS profile_row_count,
            COUNT(DISTINCT cohort_key) AS cohort_count,
            COUNT(DISTINCT ranking_scope) AS ranking_scope_count,
            COUNT(DISTINCT gender_scope) AS gender_scope_count,
            COUNT(DISTINCT season_type) AS season_type_count,
            COUNT(DISTINCT window_years) AS window_count,
            MIN(endpoint_year) AS first_endpoint_year,
            MAX(endpoint_year) AS latest_endpoint_year
        FROM explorer_program_summary
        GROUP BY resolved_school_id
        ORDER BY school_name, resolved_school_id
        """
    )

    connection.execute(
        """
        CREATE TABLE explorer_latest_program_summary AS
        SELECT * EXCLUDE (latest_row_number)
        FROM (
            SELECT
                summary.*,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        cohort_key,
                        ranking_scope,
                        gender_scope,
                        resolved_school_id,
                        season_type,
                        window_years
                    ORDER BY endpoint_year DESC
                ) AS latest_row_number
            FROM explorer_program_summary summary
        )
        WHERE latest_row_number = 1
        ORDER BY
            cohort_key,
            ranking_scope,
            gender_scope,
            season_type,
            window_years,
            momentum_rank NULLS LAST,
            school_name
        """
    )


def create_table_registry(
    connection: duckdb.DuckDBPyConnection,
    copied: list[tuple[str, str]],
) -> None:
    connection.execute(
        """
        CREATE TABLE final_table_registry (
            table_order INTEGER,
            table_name VARCHAR,
            source_phase VARCHAR,
            row_count BIGINT,
            explorer_surface BOOLEAN,
            purpose VARCHAR
        )
        """
    )

    source_labels = {
        "overall_src": "phase_7a_1_overall_trends",
        "detail_src": "phase_7a_2_event_group_trends",
        "trajectory_src": "phase_7b_program_trajectory",
        "comparison_src": "phase_7c_program_comparison",
    }

    rows: list[tuple[int, str, str, int, bool, str]] = []
    order = 1
    for catalog, table in copied:
        count = int(scalar(connection, f"SELECT COUNT(*) FROM {table}") or 0)
        rows.append(
            (
                order,
                table,
                source_labels[catalog],
                count,
                False,
                "Validated source table retained in the consolidated final publication.",
            )
        )
        order += 1

    explorer_tables = [
        "explorer_program_index",
        "explorer_latest_program_summary",
        "explorer_program_summary",
        "explorer_program_metric_long",
        "explorer_overall_season_series",
        "explorer_overall_yoy_series",
        "explorer_indoor_outdoor_series",
        "explorer_overall_window_series",
        "explorer_group_season_series",
        "explorer_group_yoy_series",
        "explorer_group_window_series",
        "explorer_event_season_series",
        "explorer_event_yoy_series",
        "explorer_event_window_series",
    ]
    for table in explorer_tables:
        count = int(scalar(connection, f"SELECT COUNT(*) FROM {table}") or 0)
        rows.append(
            (
                order,
                table,
                PHASE_VERSION,
                count,
                True,
                "Curated alias or index intended for the Milestone 7 explorer.",
            )
        )
        order += 1

    connection.executemany(
        "INSERT INTO final_table_registry VALUES (?, ?, ?, ?, ?, ?)", rows
    )


def run_checks(
    connection: duckdb.DuckDBPyConnection,
    paths: dict[str, Path],
    hashes_before: dict[str, str],
) -> list[Check]:
    checks: list[Check] = []

    for catalog, label in [
        ("overall_src", "phase_7a_overall_source_passed"),
        ("detail_src", "phase_7a_event_group_source_passed"),
        ("trajectory_src", "phase_7b_source_passed"),
        ("comparison_src", "phase_7c_source_passed"),
    ]:
        failed = int(
            scalar(
                connection,
                f"SELECT COUNT(*) FROM {catalog}.main.hard_checks "
                "WHERE status <> 'PASS'",
            )
            or 0
        )
        add_check(
            checks,
            label,
            failed,
            0,
            failed == 0,
            "Every upstream phase gate must be clean before final publication.",
        )

    reconcile_pairs = [
        ("school_season_overall_base", "overall_src"),
        ("school_season_event_base", "detail_src"),
        ("school_season_group_base", "detail_src"),
        ("program_window_trajectory", "trajectory_src"),
        ("program_comparison_snapshot_enriched", "comparison_src"),
        ("program_comparison_metric_long", "comparison_src"),
    ]
    for table, catalog in reconcile_pairs:
        observed = int(scalar(connection, f"SELECT COUNT(*) FROM {table}") or 0)
        expected = int(
            scalar(connection, f"SELECT COUNT(*) FROM {catalog}.main.{table}") or 0
        )
        add_check(
            checks,
            f"{table}_rows_reconcile",
            observed,
            expected,
            observed == expected,
            "Copied final-publication rows must reconcile exactly to the validated source.",
        )

    model_tables = [
        "school_season_overall_base",
        "school_season_event_base",
        "school_season_group_base",
        "program_comparison_snapshot_enriched",
    ]
    for table in model_tables:
        signature = str(
            scalar(
                connection,
                f"""
                SELECT CAST(COUNT(DISTINCT model_key) AS VARCHAR)
                       || ':' || COALESCE(MIN(model_key), '')
                FROM {table}
                """,
            )
            or ""
        )
        expected = f"1:{MODEL_KEY}"
        add_check(
            checks,
            f"{table}_enhanced_exclusive",
            signature,
            expected,
            signature == expected,
            "The final publication must remain Enhanced Balanced Production only.",
        )

    summary_duplicates = int(
        scalar(
            connection,
            """
            SELECT COUNT(*) FROM (
                SELECT
                    cohort_key, ranking_scope, gender_scope,
                    resolved_school_id, endpoint_year, season_type,
                    window_years, COUNT(*) AS row_count
                FROM explorer_program_summary
                GROUP BY ALL
                HAVING COUNT(*) > 1
            )
            """,
        )
        or 0
    )
    add_check(
        checks,
        "explorer_program_summary_keys_unique",
        summary_duplicates,
        0,
        summary_duplicates == 0,
        "Explorer program-summary keys are unique.",
    )

    index_duplicates = int(
        scalar(
            connection,
            """
            SELECT COUNT(*) FROM (
                SELECT resolved_school_id, COUNT(*) AS row_count
                FROM explorer_program_index
                GROUP BY resolved_school_id
                HAVING COUNT(*) > 1
            )
            """,
        )
        or 0
    )
    add_check(
        checks,
        "explorer_program_index_keys_unique",
        index_duplicates,
        0,
        index_duplicates == 0,
        "Each school appears once in the explorer program index.",
    )

    latest_duplicates = int(
        scalar(
            connection,
            """
            SELECT COUNT(*) FROM (
                SELECT
                    cohort_key, ranking_scope, gender_scope,
                    resolved_school_id, season_type, window_years,
                    COUNT(*) AS row_count
                FROM explorer_latest_program_summary
                GROUP BY ALL
                HAVING COUNT(*) > 1
            )
            """,
        )
        or 0
    )
    add_check(
        checks,
        "explorer_latest_program_summary_keys_unique",
        latest_duplicates,
        0,
        latest_duplicates == 0,
        "The latest explorer summary has one endpoint per school partition.",
    )

    metric_expected = int(
        scalar(connection, "SELECT COUNT(*) FROM explorer_program_summary") or 0
    ) * 8
    metric_observed = int(
        scalar(connection, "SELECT COUNT(*) FROM explorer_program_metric_long") or 0
    )
    add_check(
        checks,
        "explorer_metric_long_row_count",
        metric_observed,
        metric_expected,
        metric_observed == metric_expected,
        "The explorer comparison table retains eight metrics per program profile.",
    )

    registered_groups = int(
        scalar(
            connection,
            "SELECT COUNT(DISTINCT balanced_group_key) "
            "FROM balanced_event_registry",
        )
        or 0
    )
    add_check(
        checks,
        "exactly_seven_groups_registered",
        registered_groups,
        7,
        registered_groups == 7,
        "The final publication retains the frozen seven-group taxonomy registry.",
    )

    fabricated_2020 = int(
        scalar(
            connection,
            f"""
            SELECT COUNT(*)
            FROM school_season_overall_base
            WHERE model_key = '{MODEL_KEY}'
              AND season_year = 2020
              AND LOWER(season_type) = 'outdoor'
            """,
        )
        or 0
    )
    add_check(
        checks,
        "production_2020_outdoor_not_fabricated",
        fabricated_2020,
        0,
        fabricated_2020 == 0,
        "The known missing 2020 Outdoor production season remains absent.",
    )

    explorer_table_count = int(
        scalar(
            connection,
            "SELECT COUNT(*) FROM final_table_registry WHERE explorer_surface",
        )
        or 0
    )
    add_check(
        checks,
        "explorer_table_registry_complete",
        explorer_table_count,
        14,
        explorer_table_count == 14,
        "All fourteen curated explorer tables are registered.",
    )

    invalid_registry_rows = int(
        scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM final_table_registry
            WHERE row_count < 0
               OR table_name IS NULL
               OR source_phase IS NULL
            """,
        )
        or 0
    )
    add_check(
        checks,
        "final_table_registry_valid",
        invalid_registry_rows,
        0,
        invalid_registry_rows == 0,
        "The final table registry contains valid nonnegative table records.",
    )

    for catalog, path in paths.items():
        after = sha256_file(path)
        before = hashes_before[catalog]
        add_check(
            checks,
            f"{catalog}_input_unchanged",
            after,
            before,
            after == before,
            "The attached source database remains byte-identical after publication.",
        )

    return checks


def write_checks(
    connection: duckdb.DuckDBPyConnection,
    checks: list[Check],
    output_dir: Path,
) -> None:
    connection.execute(
        """
        CREATE TABLE hard_checks (
            check_name VARCHAR,
            status VARCHAR,
            observed_value VARCHAR,
            expected_value VARCHAR,
            details VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO hard_checks VALUES (?, ?, ?, ?, ?)",
        [
            (
                item.check_name,
                item.status,
                str(item.observed_value),
                str(item.expected_value),
                item.details,
            )
            for item in checks
        ],
    )
    connection.execute(
        f"COPY hard_checks TO '{sql_path(output_dir / 'hard_checks.csv')}' "
        "(HEADER, DELIMITER ',')"
    )


def export_publication_tables(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
) -> list[tuple[str, str, int]]:
    exports = [
        ("explorer_program_index", "explorer_program_index.csv"),
        ("explorer_latest_program_summary", "explorer_latest_program_summary.csv"),
        ("explorer_program_summary", "explorer_program_summary.csv"),
        ("explorer_program_metric_long", "explorer_program_metric_long.csv"),
        ("final_publication_metadata", "final_publication_metadata.csv"),
        ("final_model_registry", "final_model_registry.csv"),
        ("final_methodology", "final_methodology.csv"),
        ("final_source_phase_registry", "final_source_phase_registry.csv"),
        ("final_table_registry", "final_table_registry.csv"),
    ]
    registry: list[tuple[str, str, int]] = []
    for table, filename in exports:
        connection.execute(
            f"COPY {table} TO '{sql_path(output_dir / filename)}' "
            "(HEADER, DELIMITER ',')"
        )
        count = int(scalar(connection, f"SELECT COUNT(*) FROM {table}") or 0)
        registry.append((table, filename, count))
    return registry


def create_output_registry(
    connection: duckdb.DuckDBPyConnection,
    exports: list[tuple[str, str, int]],
    output_dir: Path,
) -> None:
    connection.execute(
        """
        CREATE TABLE output_registry (
            output_order INTEGER,
            table_name VARCHAR,
            file_name VARCHAR,
            row_count BIGINT,
            dataset_version VARCHAR,
            phase_version VARCHAR
        )
        """
    )
    rows = [
        (index, table, filename, count, DATASET_VERSION, PHASE_VERSION)
        for index, (table, filename, count) in enumerate(exports, start=1)
    ]
    connection.executemany(
        "INSERT INTO output_registry VALUES (?, ?, ?, ?, ?, ?)", rows
    )
    connection.execute(
        f"COPY output_registry TO '{sql_path(output_dir / 'output_registry.csv')}' "
        "(HEADER, DELIMITER ',')"
    )


def write_report(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
    output_db: Path,
    checks: list[Check],
) -> None:
    failed = [item for item in checks if item.status != "PASS"]
    report_tables = [
        "explorer_program_index",
        "explorer_latest_program_summary",
        "explorer_program_summary",
        "explorer_program_metric_long",
        "explorer_overall_season_series",
        "explorer_group_season_series",
        "explorer_event_season_series",
        "final_table_registry",
    ]
    lines = [
        "MILESTONE 7 — PHASE 7D FINAL PUBLICATION REPORT",
        "=" * 72,
        f"Dataset version: {DATASET_VERSION}",
        f"Phase version: {PHASE_VERSION}",
        f"Official model: {MODEL_LABEL}",
        f"Output database: {output_db.resolve()}",
        "",
        "KEY ROW COUNTS",
        "-" * 72,
    ]
    for table in report_tables:
        count = int(scalar(connection, f"SELECT COUNT(*) FROM {table}") or 0)
        lines.append(f"{table}: {count:,}")
    lines.extend(
        [
            "",
            "HARD GATE",
            "-" * 72,
            f"Total checks: {len(checks)}",
            f"Failed checks: {len(failed)}",
            f"PHASE GATE: {'PASS' if not failed else 'FAIL'}",
        ]
    )
    (output_dir / "phase_7d_report.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def write_output_manifest(output_dir: Path) -> None:
    rows: list[dict[str, object]] = []
    for path in sorted(output_dir.iterdir()):
        if path.is_file():
            rows.append(
                {
                    "relative_path": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    with (output_dir / "output_manifest.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["relative_path", "size_bytes", "sha256"],
        )
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "output_manifest.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    args = parse_args()
    source_paths = {
        "overall_src": args.overall_db,
        "detail_src": args.detail_db,
        "trajectory_src": args.trajectory_db,
        "comparison_src": args.comparison_db,
    }
    for label, path in source_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"Missing {label} database: {path}")

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_db = output_dir / OUTPUT_DB_NAME
    if output_db.exists():
        output_db.unlink()

    hashes_before = {
        label: sha256_file(path) for label, path in source_paths.items()
    }
    built_at = datetime.now(timezone.utc).isoformat()

    connection = duckdb.connect(str(output_db))
    try:
        for catalog, path in source_paths.items():
            connection.execute(
                f"ATTACH '{sql_path(path)}' AS {catalog} (READ_ONLY)"
            )

        require_tables(
            connection,
            "overall_src",
            [
                "hard_checks",
                "trend_season_registry",
                "school_metadata",
                "school_season_overall_base",
                "overall_partition_registry",
                "school_season_overall_movement",
                "school_indoor_outdoor_comparison",
                "school_multiseason_trends",
                "trend_partition_summary",
                "trend_missingness_summary",
                "trend_methodology",
            ],
        )
        require_tables(
            connection,
            "detail_src",
            [
                "hard_checks",
                "balanced_event_registry",
                "school_season_event_base",
                "school_season_event_movement",
                "school_event_multiseason_trends",
                "school_season_group_base",
                "school_season_group_movement",
                "school_group_multiseason_trends",
                "event_trend_partition_summary",
                "group_trend_partition_summary",
                "trend_comparison_status_summary",
            ],
        )
        require_tables(
            connection,
            "trajectory_src",
            [
                "hard_checks",
                "program_window_trajectory",
                "program_rise_fall_summary",
                "program_latest_snapshot",
                "program_trajectory_leaderboard",
                "program_group_profile",
                "program_event_profile",
                "program_comparison_snapshot",
                "program_trajectory_methodology",
            ],
        )
        require_tables(
            connection,
            "comparison_src",
            [
                "hard_checks",
                "program_peer_context",
                "program_conference_leaderboard",
                "program_indoor_outdoor_latest",
                "program_indoor_outdoor_history",
                "program_comparison_metric_long",
                "program_comparison_snapshot_enriched",
                "comparison_partition_registry",
                "program_comparison_methodology",
            ],
        )

        create_metadata(connection, built_at)
        create_source_registry(
            connection,
            [
                ("phase_7a_1_overall_trends", args.overall_db, hashes_before["overall_src"]),
                ("phase_7a_2_event_group_trends", args.detail_db, hashes_before["detail_src"]),
                ("phase_7b_program_trajectory", args.trajectory_db, hashes_before["trajectory_src"]),
                ("phase_7c_program_comparison", args.comparison_db, hashes_before["comparison_src"]),
            ],
        )
        copied = copy_validated_tables(connection)
        create_explorer_tables(connection)
        create_table_registry(connection, copied)

        checks = run_checks(connection, source_paths, hashes_before)
        write_checks(connection, checks, output_dir)
        exports = export_publication_tables(connection, output_dir)
        create_output_registry(connection, exports, output_dir)
        write_report(connection, output_dir, output_db, checks)

        counts = {
            "program_index": int(
                scalar(connection, "SELECT COUNT(*) FROM explorer_program_index") or 0
            ),
            "latest_summary": int(
                scalar(connection, "SELECT COUNT(*) FROM explorer_latest_program_summary") or 0
            ),
            "program_summary": int(
                scalar(connection, "SELECT COUNT(*) FROM explorer_program_summary") or 0
            ),
            "metric_long": int(
                scalar(connection, "SELECT COUNT(*) FROM explorer_program_metric_long") or 0
            ),
            "registered_tables": int(
                scalar(connection, "SELECT COUNT(*) FROM final_table_registry") or 0
            ),
        }
        failed_count = sum(item.status != "PASS" for item in checks)
    finally:
        connection.close()

    write_output_manifest(output_dir)

    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Phase version: {PHASE_VERSION}")
    print("Publication mode: enhanced_primary_only")
    print(f"Official primary: {MODEL_LABEL}")
    print(f"Output database: {output_db.resolve()}")
    print(f"Explorer program index rows: {counts['program_index']:,}")
    print(f"Latest program summary rows: {counts['latest_summary']:,}")
    print(f"Explorer program summary rows: {counts['program_summary']:,}")
    print(f"Explorer comparison metric rows: {counts['metric_long']:,}")
    print(f"Registered publication tables: {counts['registered_tables']:,}")
    print(f"Failed checks: {failed_count}")
    print()
    if failed_count:
        print("PHASE GATE: FAIL")
        return 1
    print("PHASE GATE: PASS")
    print("Phase 7D consolidated final publication created.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - terminal-facing error path
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
