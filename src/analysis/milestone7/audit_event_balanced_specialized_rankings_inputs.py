#!/usr/bin/env python3
"""Audit frozen Milestone 6 inputs for Event-Balanced Specialized Rankings.

This script does not modify the source database. It inventories tables and
scores likely athlete-level inputs needed for:
- development consistency;
- frontier/elite development;
- four baseline tiers;
- breakout rate;
- balanced program strength;
- development efficiency;
- ranking robustness;
- inbound transfer development.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import duckdb
import pandas as pd


DEFAULT_SOURCE = Path(
    "data/processed/milestone6/final_development_rankings_v1/"
    "phase_6g_final_publication/final_development_rankings_v1.duckdb"
)
DEFAULT_OUTPUT = Path(
    "data/processed/milestone7/seasonal_program_trends_v1/"
    "phase_7e2_event_balanced_specialized_rankings_preflight"
)

KEYWORD_GROUPS = {
    "athlete": {
        "athlete_id",
        "athlete_key",
        "resolved_athlete_id",
        "athlete_school_unit_id",
    },
    "school": {
        "school_id",
        "resolved_school_id",
        "school_name",
        "destination_school_id",
    },
    "event": {
        "event_key",
        "canonical_event_key",
        "canonical_event_name",
        "balanced_event_key",
        "balanced_group_key",
    },
    "season": {
        "season_key",
        "season_year",
        "season_type",
        "endpoint_year",
    },
    "gender": {"gender", "gender_scope", "sex"},
    "baseline": {
        "baseline_level",
        "baseline_normalized_level",
        "baseline_score",
        "baseline_tier",
    },
    "development": {
        "value_added",
        "development_value",
        "normalized_improvement",
        "posterior_value_added",
    },
    "points": {
        "positive_points",
        "negative_points",
        "net_points",
        "development_points",
        "enhanced_points",
        "primary_metric_value",
    },
    "model": {
        "model_key",
        "model_label",
        "support_reliability",
        "reliability_weight",
    },
    "transfer": {
        "transfer_status",
        "inbound_transfer",
        "origin_school_id",
        "destination_school_id",
        "school_sequence",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    output_dir = args.output_dir.resolve()

    if not source.exists():
        raise FileNotFoundError(f"Source database not found: {source}")

    output_dir.mkdir(parents=True, exist_ok=True)
    hash_before = sha256(source)

    connection = duckdb.connect(str(source), read_only=True)

    tables = connection.execute(
        """
        SELECT
            table_schema,
            table_name,
            table_type
        FROM information_schema.tables
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
        ORDER BY table_schema, table_name
        """
    ).df()

    columns = connection.execute(
        """
        SELECT
            table_schema,
            table_name,
            column_name,
            data_type,
            ordinal_position
        FROM information_schema.columns
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
        ORDER BY table_schema, table_name, ordinal_position
        """
    ).df()

    inventory_rows = []
    candidate_rows = []

    for table in tables.itertuples(index=False):
        schema = str(table.table_schema)
        name = str(table.table_name)
        qualified = f'"{schema}"."{name}"'

        try:
            row_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {qualified}"
                ).fetchone()[0]
            )
        except Exception:
            row_count = -1

        table_columns = columns[
            (columns["table_schema"] == schema)
            & (columns["table_name"] == name)
        ]["column_name"].astype(str).tolist()
        normalized = {column.lower() for column in table_columns}

        group_matches: dict[str, list[str]] = {}
        score = 0
        for group_name, keywords in KEYWORD_GROUPS.items():
            matches = sorted(normalized.intersection(keywords))
            group_matches[group_name] = matches
            if matches:
                score += 1

        inventory_rows.append(
            {
                "table_schema": schema,
                "table_name": name,
                "table_type": table.table_type,
                "row_count": row_count,
                "column_count": len(table_columns),
                "columns": ", ".join(table_columns),
            }
        )

        if score >= 3:
            candidate_rows.append(
                {
                    "table_schema": schema,
                    "table_name": name,
                    "row_count": row_count,
                    "candidate_score": score,
                    **{
                        f"{group}_matches": ", ".join(matches)
                        for group, matches in group_matches.items()
                    },
                }
            )

    connection.close()
    hash_after = sha256(source)

    inventory = pd.DataFrame(inventory_rows).sort_values(
        ["table_schema", "table_name"]
    )
    candidates = pd.DataFrame(candidate_rows)
    if not candidates.empty:
        candidates = candidates.sort_values(
            ["candidate_score", "row_count", "table_name"],
            ascending=[False, False, True],
        )

    inventory.to_csv(output_dir / "table_inventory.csv", index=False)
    columns.to_csv(output_dir / "column_inventory.csv", index=False)
    candidates.to_csv(output_dir / "candidate_tables.csv", index=False)

    report_lines = [
        "MILESTONE 7 — EVENT-BALANCED SPECIALIZED RANKINGS PREFLIGHT",
        "=" * 78,
        f"Source database: {source}",
        f"Source SHA256 before: {hash_before}",
        f"Source SHA256 after:  {hash_after}",
        f"Source unchanged: {hash_before == hash_after}",
        f"Tables inventoried: {len(inventory):,}",
        f"Candidate tables: {len(candidates):,}",
        "",
        "TOP CANDIDATE TABLES",
        "-" * 78,
    ]

    if candidates.empty:
        report_lines.append("No candidate table matched three keyword groups.")
    else:
        for row in candidates.head(20).itertuples(index=False):
            report_lines.append(
                f"{row.table_schema}.{row.table_name} | "
                f"rows={row.row_count:,} | score={row.candidate_score}"
            )

    report_lines.extend(
        [
            "",
            "REQUIRED DESIGN PRODUCTS",
            "-" * 78,
            "1. Development consistency",
            "2. Frontier/elite development",
            "3. Developing baseline tier",
            "4. Competitive baseline tier",
            "5. Advanced baseline tier",
            "6. Elite baseline tier",
            "7. Breakout rate",
            "8. Balanced program",
            "9. Development efficiency",
            "10. Ranking robustness",
            "11. Inbound transfer development",
        ]
    )

    report = "\n".join(report_lines) + "\n"
    (output_dir / "preflight_report.txt").write_text(
        report,
        encoding="utf-8",
    )

    print(report)
    print(f"Output directory: {output_dir}")

    return 0 if hash_before == hash_after else 1


if __name__ == "__main__":
    raise SystemExit(main())
