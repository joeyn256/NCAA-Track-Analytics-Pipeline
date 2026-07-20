#!/usr/bin/env python3
"""
Milestone 5 Phase 4A — Profile Scoring Cohort and Participation Reach

Purpose
-------
Before choosing a non-competition penalty, measure:

- rostered/affiliated athletes with any observed performance;
- athletes with no performance anywhere in the database;
- school-stint/season affiliation units with and without a contextual match;
- participation rates by school/team and, when possible, by season;
- whether the database contains the columns needed for school-stint
  eligibility verification.

Policy
------
A non-competing rostered athlete does NOT receive an invented negative
development score. The athlete counts as "not reached" in a separate
development-reach metric. The eventual program index may apply a capped,
sample-size-aware participation adjustment after this audit.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


ROOT = Path.cwd()

DATABASE_PATH = (
    ROOT / "data/database/ncaa_track_analytics.duckdb"
)

ANCHOR_PATH = (
    ROOT
    / "data/reference/collegiate_records/v1/"
      "final_eligibility_v1_1/"
      "active_collegiate_eligibility_anchors.csv"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/phase_4a_scoring_cohort"
)

VERSION = "milestone5_phase4a_scoring_cohort_v1"

ATHLETE_KEY_CANDIDATES = [
    "athlete_id",
    "athlete_key",
    "athlete_sk",
    "tfrrs_athlete_id",
]
ORGANIZATION_KEY_CANDIDATES = [
    "school_id",
    "institution_id",
    "team_id",
]
SEASON_KEY_CANDIDATES = [
    "season_id",
    "season_year",
    "academic_year",
    "year",
]
PERFORMANCE_DATE_CANDIDATES = [
    "performance_date",
    "meet_date",
    "result_date",
    "date",
]
AFFILIATION_START_CANDIDATES = [
    "affiliation_start_date",
    "start_date",
    "first_date",
    "valid_from",
]
AFFILIATION_END_CANDIDATES = [
    "affiliation_end_date",
    "end_date",
    "last_date",
    "valid_to",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        writer.writerows(rows)


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


def columns_for(
    connection: duckdb.DuckDBPyConnection,
    schema: str,
    table: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"PRAGMA table_info('{schema}.{table}')"
    ).fetchall()

    return [
        {
            "schema_name": schema,
            "table_name": table,
            "column_order": row[0],
            "column_name": row[1],
            "data_type": row[2],
            "not_null": row[3],
            "default_value": row[4],
            "primary_key": row[5],
        }
        for row in rows
    ]


def pick_column(
    columns: list[str],
    candidates: list[str],
) -> str | None:
    normalized = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate.lower() in normalized:
            return normalized[candidate.lower()]
    return None


def fetch_dicts(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
) -> list[dict[str, Any]]:
    relation = connection.execute(sql)
    names = [item[0] for item in relation.description]
    return [
        dict(zip(names, row))
        for row in relation.fetchall()
    ]


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 4A — SCORING COHORT & PARTICIPATION REACH")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Version: {VERSION}")
    print(f"Database: {DATABASE_PATH}")
    print(f"Anchor registry: {ANCHOR_PATH}")
    print(f"Output: {OUTPUT_DIR}")

    add_check(
        checks,
        "database_exists",
        DATABASE_PATH.exists(),
        DATABASE_PATH.exists(),
        True,
    )
    add_check(
        checks,
        "authoritative_anchor_registry_exists",
        ANCHOR_PATH.exists(),
        ANCHOR_PATH.exists(),
        True,
    )

    if not DATABASE_PATH.exists() or not ANCHOR_PATH.exists():
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Required input missing.")
        return 1

    database_hash_before = sha256_file(DATABASE_PATH)
    anchor_hash_before = sha256_file(ANCHOR_PATH)

    with ANCHOR_PATH.open(newline="", encoding="utf-8") as handle:
        anchors = list(csv.DictReader(handle))

    add_check(
        checks,
        "authoritative_anchor_count",
        len(anchors) == 82,
        len(anchors),
        82,
    )

    connection = duckdb.connect(str(DATABASE_PATH), read_only=True)

    try:
        tables = fetch_dicts(
            connection,
            """
            SELECT
                table_schema AS schema_name,
                table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
            ORDER BY table_schema, table_name
            """,
        )

        table_keys = {
            (row["schema_name"], row["table_name"])
            for row in tables
        }

        required_tables = {
            ("core", "athlete_affiliations"),
            ("core", "performances"),
        }

        add_check(
            checks,
            "required_core_tables_exist",
            required_tables.issubset(table_keys),
            sorted(required_tables & table_keys),
            sorted(required_tables),
        )

        if not required_tables.issubset(table_keys):
            write_csv(
                OUTPUT_DIR / "hard_checks.csv",
                checks,
                [
                    "check_name",
                    "status",
                    "observed",
                    "expected",
                    "details",
                ],
            )
            print("PHASE GATE: FAIL — Required core tables missing.")
            return 1

        inventory: list[dict[str, Any]] = []
        for row in tables:
            inventory.extend(
                columns_for(
                    connection,
                    row["schema_name"],
                    row["table_name"],
                )
            )

        write_csv(
            OUTPUT_DIR / "schema_inventory.csv",
            inventory,
            [
                "schema_name",
                "table_name",
                "column_order",
                "column_name",
                "data_type",
                "not_null",
                "default_value",
                "primary_key",
            ],
        )

        affiliation_columns = [
            row["column_name"]
            for row in inventory
            if row["schema_name"] == "core"
            and row["table_name"] == "athlete_affiliations"
        ]
        performance_columns = [
            row["column_name"]
            for row in inventory
            if row["schema_name"] == "core"
            and row["table_name"] == "performances"
        ]

        affiliation_athlete = pick_column(
            affiliation_columns,
            ATHLETE_KEY_CANDIDATES,
        )
        performance_athlete = pick_column(
            performance_columns,
            ATHLETE_KEY_CANDIDATES,
        )

        shared_organization = next(
            (
                candidate
                for candidate in ORGANIZATION_KEY_CANDIDATES
                if candidate in affiliation_columns
                and candidate in performance_columns
            ),
            None,
        )
        shared_season = next(
            (
                candidate
                for candidate in SEASON_KEY_CANDIDATES
                if candidate in affiliation_columns
                and candidate in performance_columns
            ),
            None,
        )

        performance_date = pick_column(
            performance_columns,
            PERFORMANCE_DATE_CANDIDATES,
        )
        affiliation_start = pick_column(
            affiliation_columns,
            AFFILIATION_START_CANDIDATES,
        )
        affiliation_end = pick_column(
            affiliation_columns,
            AFFILIATION_END_CANDIDATES,
        )

        contract_rows = [
            {
                "concept": "affiliation_athlete_key",
                "resolved_column": affiliation_athlete or "",
                "required_for": "rostered athlete denominator",
                "status": "resolved" if affiliation_athlete else "missing",
            },
            {
                "concept": "performance_athlete_key",
                "resolved_column": performance_athlete or "",
                "required_for": "competition observation",
                "status": "resolved" if performance_athlete else "missing",
            },
            {
                "concept": "shared_organization_key",
                "resolved_column": shared_organization or "",
                "required_for": "school/team attribution",
                "status": "resolved" if shared_organization else "missing",
            },
            {
                "concept": "shared_season_key",
                "resolved_column": shared_season or "",
                "required_for": "school-season participation",
                "status": "resolved" if shared_season else "missing",
            },
            {
                "concept": "performance_date",
                "resolved_column": performance_date or "",
                "required_for": "school-stint date validation",
                "status": "resolved" if performance_date else "missing",
            },
            {
                "concept": "affiliation_start_date",
                "resolved_column": affiliation_start or "",
                "required_for": "school-stint date validation",
                "status": "resolved" if affiliation_start else "missing",
            },
            {
                "concept": "affiliation_end_date",
                "resolved_column": affiliation_end or "",
                "required_for": "school-stint date validation",
                "status": "resolved" if affiliation_end else "missing",
            },
        ]

        write_csv(
            OUTPUT_DIR / "input_contract.csv",
            contract_rows,
            [
                "concept",
                "resolved_column",
                "required_for",
                "status",
            ],
        )

        add_check(
            checks,
            "shared_athlete_key_resolved",
            bool(affiliation_athlete and performance_athlete),
            {
                "affiliations": affiliation_athlete,
                "performances": performance_athlete,
            },
            "both resolved",
        )
        add_check(
            checks,
            "organization_context_resolved",
            shared_organization is not None,
            shared_organization or "missing",
            "school_id, institution_id, or team_id",
        )

        if not affiliation_athlete or not performance_athlete:
            write_csv(
                OUTPUT_DIR / "hard_checks.csv",
                checks,
                [
                    "check_name",
                    "status",
                    "observed",
                    "expected",
                    "details",
                ],
            )
            print("PHASE GATE: FAIL — Athlete keys unresolved.")
            return 1

        aff_athlete_q = quote_ident(affiliation_athlete)
        perf_athlete_q = quote_ident(performance_athlete)

        overall_rows = fetch_dicts(
            connection,
            f"""
            WITH affiliation_athletes AS (
                SELECT DISTINCT
                    {aff_athlete_q} AS athlete_id
                FROM core.athlete_affiliations
                WHERE {aff_athlete_q} IS NOT NULL
            ),
            performance_athletes AS (
                SELECT DISTINCT
                    {perf_athlete_q} AS athlete_id
                FROM core.performances
                WHERE {perf_athlete_q} IS NOT NULL
            )
            SELECT
                COUNT(*) AS rostered_athlete_count,
                COUNT(*) FILTER (
                    WHERE p.athlete_id IS NOT NULL
                ) AS athletes_with_any_performance,
                COUNT(*) FILTER (
                    WHERE p.athlete_id IS NULL
                ) AS athletes_with_no_performance,
                COUNT(*) FILTER (
                    WHERE p.athlete_id IS NOT NULL
                )::DOUBLE / NULLIF(COUNT(*), 0)
                    AS any_performance_rate
            FROM affiliation_athletes a
            LEFT JOIN performance_athletes p
                USING (athlete_id)
            """,
        )

        overall = overall_rows[0]

        zero_competition_rows = fetch_dicts(
            connection,
            f"""
            WITH performance_athletes AS (
                SELECT DISTINCT
                    {perf_athlete_q} AS athlete_id
                FROM core.performances
                WHERE {perf_athlete_q} IS NOT NULL
            )
            SELECT
                a.{aff_athlete_q} AS athlete_id,
                COUNT(*) AS affiliation_row_count
            FROM core.athlete_affiliations a
            LEFT JOIN performance_athletes p
                ON a.{aff_athlete_q} = p.athlete_id
            WHERE
                a.{aff_athlete_q} IS NOT NULL
                AND p.athlete_id IS NULL
            GROUP BY a.{aff_athlete_q}
            ORDER BY affiliation_row_count DESC, athlete_id
            """,
        )

        write_csv(
            OUTPUT_DIR / "zero_competition_athletes.csv",
            zero_competition_rows,
            ["athlete_id", "affiliation_row_count"],
        )

        context_keys = [affiliation_athlete]
        perf_context_keys = [performance_athlete]

        if shared_organization:
            context_keys.append(shared_organization)
            perf_context_keys.append(shared_organization)

        if shared_season:
            context_keys.append(shared_season)
            perf_context_keys.append(shared_season)

        aff_select = ", ".join(
            quote_ident(column)
            for column in context_keys
        )
        perf_select = ", ".join(
            quote_ident(column)
            for column in perf_context_keys
        )

        join_terms = [
            (
                f"a.{quote_ident(affiliation_athlete)} "
                f"= p.{quote_ident(performance_athlete)}"
            )
        ]

        if shared_organization:
            quoted = quote_ident(shared_organization)
            join_terms.append(
                f"a.{quoted} IS NOT DISTINCT FROM p.{quoted}"
            )

        if shared_season:
            quoted = quote_ident(shared_season)
            join_terms.append(
                f"a.{quoted} IS NOT DISTINCT FROM p.{quoted}"
            )

        join_sql = " AND ".join(join_terms)

        affiliation_units = fetch_dicts(
            connection,
            f"""
            WITH affiliation_units AS (
                SELECT DISTINCT {aff_select}
                FROM core.athlete_affiliations
                WHERE {aff_athlete_q} IS NOT NULL
            ),
            performance_units AS (
                SELECT DISTINCT {perf_select}
                FROM core.performances
                WHERE {perf_athlete_q} IS NOT NULL
            )
            SELECT
                COUNT(*) AS affiliation_unit_count,
                COUNT(*) FILTER (
                    WHERE p.{perf_athlete_q} IS NOT NULL
                ) AS matched_affiliation_units,
                COUNT(*) FILTER (
                    WHERE p.{perf_athlete_q} IS NULL
                ) AS unmatched_affiliation_units,
                COUNT(*) FILTER (
                    WHERE p.{perf_athlete_q} IS NOT NULL
                )::DOUBLE / NULLIF(COUNT(*), 0)
                    AS contextual_participation_rate
            FROM affiliation_units a
            LEFT JOIN performance_units p
                ON {join_sql}
            """,
        )[0]

        group_dimensions: list[str] = []
        if shared_organization:
            group_dimensions.append(shared_organization)
        if shared_season:
            group_dimensions.append(shared_season)

        participation_summary_rows: list[dict[str, Any]] = []

        if group_dimensions:
            group_select = ", ".join(
                f"a.{quote_ident(column)}"
                for column in group_dimensions
            )
            group_order = ", ".join(
                quote_ident(column)
                for column in group_dimensions
            )

            participation_summary_rows = fetch_dicts(
                connection,
                f"""
                WITH affiliation_units AS (
                    SELECT DISTINCT {aff_select}
                    FROM core.athlete_affiliations
                    WHERE {aff_athlete_q} IS NOT NULL
                ),
                performance_units AS (
                    SELECT DISTINCT {perf_select}
                    FROM core.performances
                    WHERE {perf_athlete_q} IS NOT NULL
                )
                SELECT
                    {group_select},
                    COUNT(*) AS rostered_affiliation_units,
                    COUNT(*) FILTER (
                        WHERE p.{perf_athlete_q} IS NOT NULL
                    ) AS competing_affiliation_units,
                    COUNT(*) FILTER (
                        WHERE p.{perf_athlete_q} IS NULL
                    ) AS noncompeting_affiliation_units,
                    COUNT(*) FILTER (
                        WHERE p.{perf_athlete_q} IS NOT NULL
                    )::DOUBLE / NULLIF(COUNT(*), 0)
                        AS participation_rate
                FROM affiliation_units a
                LEFT JOIN performance_units p
                    ON {join_sql}
                GROUP BY {group_select}
                ORDER BY {group_order}
                """,
            )

            summary_fields = (
                group_dimensions
                + [
                    "rostered_affiliation_units",
                    "competing_affiliation_units",
                    "noncompeting_affiliation_units",
                    "participation_rate",
                ]
            )

            write_csv(
                OUTPUT_DIR / "organization_season_participation.csv",
                participation_summary_rows,
                summary_fields,
            )

        unmatched_select = ", ".join(
            f"a.{quote_ident(column)} AS {quote_ident(column)}"
            for column in context_keys
        )

        unmatched_units = fetch_dicts(
            connection,
            f"""
            WITH affiliation_units AS (
                SELECT DISTINCT {aff_select}
                FROM core.athlete_affiliations
                WHERE {aff_athlete_q} IS NOT NULL
            ),
            performance_units AS (
                SELECT DISTINCT {perf_select}
                FROM core.performances
                WHERE {perf_athlete_q} IS NOT NULL
            )
            SELECT {unmatched_select}
            FROM affiliation_units a
            LEFT JOIN performance_units p
                ON {join_sql}
            WHERE p.{perf_athlete_q} IS NULL
            ORDER BY 1
            LIMIT 10000
            """,
        )

        write_csv(
            OUTPUT_DIR / "unmatched_affiliation_units_sample.csv",
            unmatched_units,
            context_keys,
        )

        metrics_rows = [
            {
                "metric": "rostered_athletes",
                "value": overall["rostered_athlete_count"],
                "definition": (
                    "Distinct athletes present in core.athlete_affiliations"
                ),
            },
            {
                "metric": "athletes_with_any_performance",
                "value": overall["athletes_with_any_performance"],
                "definition": (
                    "Rostered athletes appearing anywhere in core.performances"
                ),
            },
            {
                "metric": "athletes_with_no_performance",
                "value": overall["athletes_with_no_performance"],
                "definition": (
                    "Rostered athletes with no observed performance anywhere"
                ),
            },
            {
                "metric": "any_performance_rate",
                "value": overall["any_performance_rate"],
                "definition": (
                    "Athletes with any performance / rostered athletes"
                ),
            },
            {
                "metric": "affiliation_units",
                "value": affiliation_units["affiliation_unit_count"],
                "definition": (
                    "Distinct athlete plus available organization/season keys"
                ),
            },
            {
                "metric": "matched_affiliation_units",
                "value": affiliation_units["matched_affiliation_units"],
                "definition": (
                    "Affiliation units with a contextual performance match"
                ),
            },
            {
                "metric": "unmatched_affiliation_units",
                "value": affiliation_units["unmatched_affiliation_units"],
                "definition": (
                    "Affiliation units without a contextual performance match"
                ),
            },
            {
                "metric": "contextual_participation_rate",
                "value": affiliation_units[
                    "contextual_participation_rate"
                ],
                "definition": (
                    "Contextually matched affiliation units / all units"
                ),
            },
        ]

        write_csv(
            OUTPUT_DIR / "participation_metrics.csv",
            metrics_rows,
            ["metric", "value", "definition"],
        )

        policy_rows = [
            {
                "policy_component": "athlete_development_score",
                "noncompetitor_treatment": "no fabricated negative score",
                "current_phase": "profile only",
                "rationale": (
                    "No performance does not identify injury, redshirt, "
                    "ability, administrative roster status, or data absence."
                ),
            },
            {
                "policy_component": "development_reach",
                "noncompetitor_treatment": "counts as not reached",
                "current_phase": "approved",
                "rationale": (
                    "Programs should not receive full credit while "
                    "noncompeting rostered athletes disappear from the metric."
                ),
            },
            {
                "policy_component": "future_program_index",
                "noncompetitor_treatment": (
                    "capped sample-size-aware participation adjustment"
                ),
                "current_phase": "weight not yet selected",
                "rationale": (
                    "Audit school distributions before choosing magnitude."
                ),
            },
        ]

        write_csv(
            OUTPUT_DIR / "noncompetitor_policy.csv",
            policy_rows,
            [
                "policy_component",
                "noncompetitor_treatment",
                "current_phase",
                "rationale",
            ],
        )

        add_check(
            checks,
            "participation_metrics_created",
            len(metrics_rows) == 8,
            len(metrics_rows),
            8,
        )
        add_check(
            checks,
            "rostered_athletes_exist",
            int(overall["rostered_athlete_count"]) > 0,
            overall["rostered_athlete_count"],
            "greater than 0",
        )
        add_check(
            checks,
            "zero_competition_population_profiled",
            int(overall["athletes_with_no_performance"]) >= 0,
            overall["athletes_with_no_performance"],
            "at least 0",
        )
        add_check(
            checks,
            "contextual_affiliation_units_profiled",
            int(affiliation_units["affiliation_unit_count"]) > 0,
            affiliation_units["affiliation_unit_count"],
            "greater than 0",
        )

        database_hash_after = sha256_file(DATABASE_PATH)
        anchor_hash_after = sha256_file(ANCHOR_PATH)

        add_check(
            checks,
            "database_unchanged",
            database_hash_before == database_hash_after,
            database_hash_after,
            database_hash_before,
        )
        add_check(
            checks,
            "anchor_registry_unchanged",
            anchor_hash_before == anchor_hash_after,
            anchor_hash_after,
            anchor_hash_before,
        )

        write_csv(
            OUTPUT_DIR / "input_manifest.csv",
            [
                {
                    "input_name": "duckdb_database",
                    "path": str(DATABASE_PATH),
                    "sha256_before": database_hash_before,
                    "sha256_after": database_hash_after,
                },
                {
                    "input_name": "anchor_registry",
                    "path": str(ANCHOR_PATH),
                    "sha256_before": anchor_hash_before,
                    "sha256_after": anchor_hash_after,
                },
            ],
            [
                "input_name",
                "path",
                "sha256_before",
                "sha256_after",
            ],
        )

        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            [
                "check_name",
                "status",
                "observed",
                "expected",
                "details",
            ],
        )

        failed = [
            row for row in checks if row["status"] == "FAIL"
        ]

        report = [
            "MILESTONE 5 PHASE 4A — SCORING COHORT & PARTICIPATION REACH",
            "=" * 78,
            f"Finished UTC: {utc_now()}",
            f"Version: {VERSION}",
            "",
            "POLICY",
            "-" * 78,
            "Noncompeters receive no invented negative development score.",
            "They count as not reached in a separate participation metric.",
            "Penalty magnitude will be chosen after school-level profiling.",
            "",
            "KEY RESOLVED COLUMNS",
            "-" * 78,
            f"Affiliation athlete key: {affiliation_athlete}",
            f"Performance athlete key: {performance_athlete}",
            f"Shared organization key: {shared_organization}",
            f"Shared season key: {shared_season}",
            f"Performance date: {performance_date}",
            f"Affiliation start: {affiliation_start}",
            f"Affiliation end: {affiliation_end}",
            "",
            "PARTICIPATION RESULTS",
            "-" * 78,
            f"Rostered athletes: "
            f"{int(overall['rostered_athlete_count']):,}",
            f"Athletes with any performance: "
            f"{int(overall['athletes_with_any_performance']):,}",
            f"Athletes with no performance: "
            f"{int(overall['athletes_with_no_performance']):,}",
            f"Any-performance rate: "
            f"{float(overall['any_performance_rate']):.6%}",
            f"Affiliation units: "
            f"{int(affiliation_units['affiliation_unit_count']):,}",
            f"Contextually matched units: "
            f"{int(affiliation_units['matched_affiliation_units']):,}",
            f"Unmatched units: "
            f"{int(affiliation_units['unmatched_affiliation_units']):,}",
            f"Contextual participation rate: "
            f"{float(affiliation_units['contextual_participation_rate']):.6%}",
            "",
            "PHASE GATE",
            "-" * 78,
            (
                "PASS — Scoring cohort and participation reach profiled."
                if not failed
                else "FAIL — Correct input-contract or matching issues."
            ),
        ]

        (OUTPUT_DIR / "phase_4a_report.txt").write_text(
            "\n".join(report) + "\n",
            encoding="utf-8",
        )

        print()
        print(
            "Rostered athletes: "
            f"{int(overall['rostered_athlete_count']):,}"
        )
        print(
            "Athletes with no performance: "
            f"{int(overall['athletes_with_no_performance']):,}"
        )
        print(
            "Any-performance rate: "
            f"{float(overall['any_performance_rate']):.6%}"
        )
        print(
            "Contextual participation rate: "
            f"{float(affiliation_units['contextual_participation_rate']):.6%}"
        )
        print()

        if failed:
            print("PHASE GATE: FAIL")
            for row in failed:
                print(
                    f"  {row['check_name']}: "
                    f"observed={row['observed']} "
                    f"expected={row['expected']}"
                )
            return 1

        print("PHASE GATE: PASS")
        print("Next: define the normalized performance-level function.")
        return 0

    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
