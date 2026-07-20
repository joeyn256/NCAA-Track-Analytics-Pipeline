#!/usr/bin/env python3
"""
Milestone 5 Phase 4B — Calibrate the Normalized Performance-Level Function

This phase profiles candidate nonlinear transformations. It does NOT freeze
the final exponent.

Core transformation
-------------------
For lower-is-better events:
    performance_ratio = anchor_value / performance_value

For higher-is-better events:
    performance_ratio = performance_value / anchor_value

For candidate exponent p:
    performance_level = 100 * min(1, performance_ratio) ** p

Properties:
- the collegiate-eligibility anchor scores 100;
- better-than-anchor rows are capped at 100 and separately audited;
- with p > 1, an equal raw improvement is worth more near the frontier;
- the same formula supports running, field, and combined events.

Outputs profile six candidate exponents across the complete official-event
scoring population. The next phase selects and freezes the exponent after
reviewing empirical score distributions and anchor exceedances.
"""

from __future__ import annotations

import csv
import hashlib
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


ROOT = Path.cwd()

FOUNDATION_DB = (
    ROOT
    / "data/processed/milestone5/"
      "track_performance_foundation_v1/final_v1/"
      "track_performance_foundation_v1.duckdb"
)

ANCHOR_CSV = (
    ROOT
    / "data/reference/collegiate_records/v1/"
      "final_eligibility_v1_1/"
      "active_collegiate_eligibility_anchors.csv"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4b_performance_level_calibration"
)

CALIBRATION_VERSION = "performance_level_calibration_v1_1"

EXPECTED_FOUNDATION_ROWS = 4_697_418
EXPECTED_OFFICIAL_SCORING_ROWS = 4_664_090
EXPECTED_ANCHOR_ROWS = 82
EXPECTED_OFFICIAL_COMBINATIONS = 82
EXPECTED_EXCLUDED_COMBINATIONS = 44

CANDIDATE_EXPONENTS = [1.25, 1.50, 1.75, 2.00, 2.50, 3.00]

QUANTILES = [
    ("q01", 0.01),
    ("q05", 0.05),
    ("q10", 0.10),
    ("q25", 0.25),
    ("q50", 0.50),
    ("q75", 0.75),
    ("q90", 0.90),
    ("q95", 0.95),
    ("q99", 0.99),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def sha256_file(
    path: Path,
    block_size: int = 8 * 1024 * 1024,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(block_size):
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


def fetch_dicts(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
) -> list[dict[str, Any]]:
    result = connection.execute(sql)
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


def score_value(
    anchor: float,
    performance: float,
    direction: str,
    exponent: float,
) -> float:
    if direction == "lower_is_better":
        ratio = anchor / performance
    elif direction == "higher_is_better":
        ratio = performance / anchor
    else:
        raise ValueError(f"Unsupported direction: {direction}")

    bounded = min(1.0, max(0.0, ratio))
    return 100.0 * bounded ** exponent


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 4B — PERFORMANCE-LEVEL CALIBRATION")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Calibration version: {CALIBRATION_VERSION}")
    print(f"Foundation DB: {FOUNDATION_DB}")
    print(f"Anchor registry: {ANCHOR_CSV}")
    print(f"Output: {OUTPUT_DIR}")

    add_check(
        checks,
        "foundation_database_exists",
        FOUNDATION_DB.exists(),
        FOUNDATION_DB.exists(),
        True,
    )
    add_check(
        checks,
        "anchor_registry_exists",
        ANCHOR_CSV.exists(),
        ANCHOR_CSV.exists(),
        True,
    )

    if not FOUNDATION_DB.exists() or not ANCHOR_CSV.exists():
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Required input missing.")
        return 1

    foundation_stat_before = FOUNDATION_DB.stat()
    anchor_hash_before = sha256_file(ANCHOR_CSV)

    with ANCHOR_CSV.open(newline="", encoding="utf-8") as handle:
        anchor_rows = list(csv.DictReader(handle))

    add_check(
        checks,
        "anchor_registry_row_count",
        len(anchor_rows) == EXPECTED_ANCHOR_ROWS,
        len(anchor_rows),
        EXPECTED_ANCHOR_ROWS,
    )

    anchor_keys = {
        (
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
        )
        for row in anchor_rows
    }
    add_check(
        checks,
        "anchor_keys_unique",
        len(anchor_keys) == len(anchor_rows),
        len(anchor_rows) - len(anchor_keys),
        0,
    )

    invalid_anchor_values = []
    invalid_directions = []

    for row in anchor_rows:
        try:
            value = float(row["record_mark_normalized"])
            if not math.isfinite(value) or value <= 0:
                invalid_anchor_values.append(row)
        except (TypeError, ValueError):
            invalid_anchor_values.append(row)

        if row["selection_direction"] not in {
            "lower_is_better",
            "higher_is_better",
        }:
            invalid_directions.append(row)

    add_check(
        checks,
        "all_anchor_values_positive_numeric",
        not invalid_anchor_values,
        len(invalid_anchor_values),
        0,
    )
    add_check(
        checks,
        "all_anchor_directions_valid",
        not invalid_directions,
        len(invalid_directions),
        0,
    )

    anchor_lookup = {
        (
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
        ): row
        for row in anchor_rows
    }

    connection = duckdb.connect(str(FOUNDATION_DB), read_only=True)

    try:
        connection.execute("PRAGMA threads=4")
        connection.execute("PRAGMA enable_progress_bar=false")

        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                """
            ).fetchall()
        }

        add_check(
            checks,
            "track_scoring_table_exists",
            "track_scoring_performances" in tables,
            "track_scoring_performances" in tables,
            True,
        )

        if "track_scoring_performances" not in tables:
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
            print("PHASE GATE: FAIL — Scoring table missing.")
            return 1

        # Use the stable PRAGMA tuple interface for compatibility across
        # DuckDB versions. The returned columns are:
        # cid, name, type, notnull, dflt_value, pk.
        raw_schema = connection.execute(
            "PRAGMA table_info('main.track_scoring_performances')"
        ).fetchall()

        schema_rows = [
            {
                "column_order": row[0],
                "column_name": row[1],
                "data_type": row[2],
                "not_null": row[3],
                "default_value": row[4],
                "primary_key": row[5],
            }
            for row in raw_schema
        ]

        write_csv(
            OUTPUT_DIR / "scoring_table_schema.csv",
            schema_rows,
            [
                "column_order",
                "column_name",
                "data_type",
                "not_null",
                "default_value",
                "primary_key",
            ],
        )

        available_columns = {
            row["column_name"] for row in schema_rows
        }

        required_columns = {
            "canonical_person_performance_id",
            "canonical_person_id",
            "canonical_gender_code",
            "season_type",
            "season_year",
            "canonical_event_code",
            "canonical_event_name",
            "performance_direction",
            "primary_parsed_value",
            "resolved_school_id",
            "school_stint_id",
        }

        missing_columns = sorted(required_columns - available_columns)
        add_check(
            checks,
            "required_scoring_columns_present",
            not missing_columns,
            ",".join(missing_columns),
            "none missing",
        )

        if missing_columns:
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
            print(
                "PHASE GATE: FAIL — Missing scoring columns: "
                + ", ".join(missing_columns)
            )
            return 1

        connection.execute(
            f"""
            CREATE TEMP TABLE calibration_anchors AS
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                canonical_event_name,
                CAST(record_mark_normalized AS DOUBLE)
                    AS anchor_value,
                selection_direction,
                anchor_status,
                pending_ratification,
                outside_regular_collegiate_season,
                holder AS anchor_holder,
                school AS anchor_school,
                source_as_of
            FROM read_csv_auto(
                '{sql_path(ANCHOR_CSV)}',
                HEADER = TRUE,
                ALL_VARCHAR = TRUE
            )
            """
        )

        connection.execute(
            """
            CREATE TEMP VIEW scored_base AS
            SELECT
                p.canonical_person_performance_id,
                p.canonical_person_id,
                p.athlete_name,
                p.canonical_gender_code,
                p.season_type,
                p.season_year,
                p.season_id,
                p.performance_date,
                p.meet_name,
                p.canonical_event_code,
                p.canonical_event_name,
                p.performance_direction,
                p.primary_parsed_value AS performance_value,
                p.normalized_unit,
                p.raw_mark,
                p.resolved_school_id,
                p.resolved_team_id,
                p.school_stint_id,
                a.anchor_value,
                a.selection_direction AS anchor_direction,
                a.anchor_status,
                a.anchor_holder,
                a.anchor_school,
                CASE
                    WHEN a.selection_direction = 'lower_is_better'
                        THEN a.anchor_value
                             / p.primary_parsed_value
                    WHEN a.selection_direction = 'higher_is_better'
                        THEN p.primary_parsed_value
                             / a.anchor_value
                    ELSE NULL
                END AS raw_performance_ratio,
                LEAST(
                    1.0,
                    GREATEST(
                        0.0,
                        CASE
                            WHEN a.selection_direction =
                                'lower_is_better'
                                THEN a.anchor_value
                                     / p.primary_parsed_value
                            WHEN a.selection_direction =
                                'higher_is_better'
                                THEN p.primary_parsed_value
                                     / a.anchor_value
                            ELSE NULL
                        END
                    )
                ) AS bounded_performance_ratio
            FROM main.track_scoring_performances p
            JOIN calibration_anchors a
              USING (
                season_type,
                canonical_gender_code,
                canonical_event_code
              )
            """
        )

        foundation_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM main.track_scoring_performances
            """
        ).fetchone()[0]

        joined_count = connection.execute(
            "SELECT COUNT(*) FROM scored_base"
        ).fetchone()[0]

        joined_combination_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT
                    season_type,
                    canonical_gender_code,
                    canonical_event_code
                FROM scored_base
            )
            """
        ).fetchone()[0]

        excluded_rows = fetch_dicts(
            connection,
            """
            SELECT
                p.season_type,
                p.canonical_gender_code,
                p.canonical_event_code,
                ANY_VALUE(p.canonical_event_name)
                    AS canonical_event_name,
                COUNT(*) AS performance_count,
                COUNT(DISTINCT p.canonical_person_id)
                    AS athlete_count,
                COUNT(DISTINCT p.resolved_school_id)
                    AS school_count,
                'no_official_collegiate_eligibility_anchor'
                    AS exclusion_reason
            FROM main.track_scoring_performances p
            LEFT JOIN calibration_anchors a
              USING (
                season_type,
                canonical_gender_code,
                canonical_event_code
              )
            WHERE a.canonical_event_code IS NULL
            GROUP BY
                p.season_type,
                p.canonical_gender_code,
                p.canonical_event_code
            ORDER BY
                p.season_type,
                p.canonical_gender_code,
                p.canonical_event_code
            """,
        )

        excluded_performance_count = sum(
            int(row["performance_count"])
            for row in excluded_rows
        )

        write_csv(
            OUTPUT_DIR / "nonofficial_scoring_combinations.csv",
            excluded_rows,
            [
                "season_type",
                "canonical_gender_code",
                "canonical_event_code",
                "canonical_event_name",
                "performance_count",
                "athlete_count",
                "school_count",
                "exclusion_reason",
            ],
        )

        direction_mismatch_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM scored_base
            WHERE performance_direction <> anchor_direction
               OR performance_direction IS NULL
               OR anchor_direction IS NULL
            """
        ).fetchone()[0]

        invalid_ratio_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM scored_base
            WHERE raw_performance_ratio IS NULL
               OR NOT isfinite(raw_performance_ratio)
               OR raw_performance_ratio <= 0
            """
        ).fetchone()[0]

        ratio_overall = fetch_dicts(
            connection,
            """
            SELECT
                COUNT(*) AS performance_count,
                COUNT(*) FILTER (
                    WHERE raw_performance_ratio > 1.000000001
                ) AS anchor_exceedance_count,
                COUNT(*) FILTER (
                    WHERE raw_performance_ratio > 1.000000001
                )::DOUBLE / NULLIF(COUNT(*), 0)
                    AS anchor_exceedance_rate,
                MAX(raw_performance_ratio) AS max_raw_ratio,
                MIN(raw_performance_ratio) AS min_raw_ratio,
                AVG(raw_performance_ratio) AS mean_raw_ratio
            FROM scored_base
            """
        )[0]

        anchor_exceedance_summary = fetch_dicts(
            connection,
            """
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(anchor_value) AS anchor_value,
                ANY_VALUE(anchor_direction) AS anchor_direction,
                COUNT(*) AS performance_count,
                COUNT(*) FILTER (
                    WHERE raw_performance_ratio > 1.000000001
                ) AS anchor_exceedance_count,
                COUNT(*) FILTER (
                    WHERE raw_performance_ratio > 1.000000001
                )::DOUBLE / NULLIF(COUNT(*), 0)
                    AS anchor_exceedance_rate,
                MAX(raw_performance_ratio) AS max_raw_ratio,
                CASE
                    WHEN ANY_VALUE(anchor_direction) =
                        'lower_is_better'
                        THEN MIN(performance_value)
                    ELSE MAX(performance_value)
                END AS best_observed_performance_value
            FROM scored_base
            GROUP BY
                season_type,
                canonical_gender_code,
                canonical_event_code
            ORDER BY
                anchor_exceedance_count DESC,
                max_raw_ratio DESC,
                season_type,
                canonical_gender_code,
                canonical_event_code
            """,
        )

        write_csv(
            OUTPUT_DIR / "anchor_exceedance_summary.csv",
            anchor_exceedance_summary,
            [
                "season_type",
                "canonical_gender_code",
                "canonical_event_code",
                "canonical_event_name",
                "anchor_value",
                "anchor_direction",
                "performance_count",
                "anchor_exceedance_count",
                "anchor_exceedance_rate",
                "max_raw_ratio",
                "best_observed_performance_value",
            ],
        )

        anchor_exceedance_samples = fetch_dicts(
            connection,
            """
            WITH ranked AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            season_type,
                            canonical_gender_code,
                            canonical_event_code
                        ORDER BY raw_performance_ratio DESC
                    ) AS event_rank
                FROM scored_base
                WHERE raw_performance_ratio > 1.000000001
            )
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                canonical_event_name,
                event_rank,
                raw_performance_ratio,
                anchor_value,
                performance_value,
                raw_mark,
                canonical_person_id,
                athlete_name,
                resolved_school_id,
                school_stint_id,
                season_year,
                season_id,
                performance_date,
                meet_name,
                anchor_holder,
                anchor_school
            FROM ranked
            WHERE event_rank <= 25
            ORDER BY
                season_type,
                canonical_gender_code,
                canonical_event_code,
                event_rank
            """,
        )

        write_csv(
            OUTPUT_DIR / "anchor_exceedance_samples.csv",
            anchor_exceedance_samples,
            [
                "season_type",
                "canonical_gender_code",
                "canonical_event_code",
                "canonical_event_name",
                "event_rank",
                "raw_performance_ratio",
                "anchor_value",
                "performance_value",
                "raw_mark",
                "canonical_person_id",
                "athlete_name",
                "resolved_school_id",
                "school_stint_id",
                "season_year",
                "season_id",
                "performance_date",
                "meet_name",
                "anchor_holder",
                "anchor_school",
            ],
        )

        quantile_sql = ",\n".join(
            (
                f"approx_quantile("
                f"bounded_performance_ratio, {value}"
                f") AS ratio_{name}"
            )
            for name, value in QUANTILES
        )

        ratio_profiles = fetch_dicts(
            connection,
            f"""
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                ANY_VALUE(anchor_value) AS anchor_value,
                ANY_VALUE(anchor_direction) AS anchor_direction,
                COUNT(*) AS performance_count,
                COUNT(DISTINCT canonical_person_id)
                    AS athlete_count,
                MIN(bounded_performance_ratio) AS ratio_min,
                {quantile_sql},
                AVG(bounded_performance_ratio) AS ratio_mean,
                MAX(bounded_performance_ratio) AS ratio_max
            FROM scored_base
            GROUP BY
                season_type,
                canonical_gender_code,
                canonical_event_code
            ORDER BY
                season_type,
                canonical_gender_code,
                canonical_event_code
            """,
        )

        ratio_fields = [
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "canonical_event_name",
            "anchor_value",
            "anchor_direction",
            "performance_count",
            "athlete_count",
            "ratio_min",
        ] + [f"ratio_{name}" for name, _ in QUANTILES] + [
            "ratio_mean",
            "ratio_max",
        ]

        write_csv(
            OUTPUT_DIR / "event_ratio_profiles.csv",
            ratio_profiles,
            ratio_fields,
        )

        candidate_profiles: list[dict[str, Any]] = []
        global_profiles: list[dict[str, Any]] = []

        for exponent in CANDIDATE_EXPONENTS:
            score_expression = (
                f"100.0 * POWER("
                f"bounded_performance_ratio, {exponent}"
                f")"
            )

            score_quantile_sql = ",\n".join(
                (
                    f"approx_quantile("
                    f"{score_expression}, {value}"
                    f") AS score_{name}"
                )
                for name, value in QUANTILES
            )

            event_rows = fetch_dicts(
                connection,
                f"""
                SELECT
                    season_type,
                    canonical_gender_code,
                    canonical_event_code,
                    ANY_VALUE(canonical_event_name)
                        AS canonical_event_name,
                    {exponent}::DOUBLE AS exponent,
                    COUNT(*) AS performance_count,
                    COUNT(DISTINCT canonical_person_id)
                        AS athlete_count,
                    MIN({score_expression}) AS score_min,
                    {score_quantile_sql},
                    AVG({score_expression}) AS score_mean,
                    MAX({score_expression}) AS score_max
                FROM scored_base
                GROUP BY
                    season_type,
                    canonical_gender_code,
                    canonical_event_code
                ORDER BY
                    season_type,
                    canonical_gender_code,
                    canonical_event_code
                """,
            )
            candidate_profiles.extend(event_rows)

            global_row = fetch_dicts(
                connection,
                f"""
                SELECT
                    {exponent}::DOUBLE AS exponent,
                    COUNT(*) AS performance_count,
                    COUNT(DISTINCT canonical_person_id)
                        AS athlete_count,
                    MIN({score_expression}) AS score_min,
                    {score_quantile_sql},
                    AVG({score_expression}) AS score_mean,
                    MAX({score_expression}) AS score_max
                FROM scored_base
                """,
            )[0]
            global_profiles.append(global_row)

        score_fields = [
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "canonical_event_name",
            "exponent",
            "performance_count",
            "athlete_count",
            "score_min",
        ] + [f"score_{name}" for name, _ in QUANTILES] + [
            "score_mean",
            "score_max",
        ]

        write_csv(
            OUTPUT_DIR / "candidate_exponent_event_profiles.csv",
            candidate_profiles,
            score_fields,
        )

        global_fields = [
            "exponent",
            "performance_count",
            "athlete_count",
            "score_min",
        ] + [f"score_{name}" for name, _ in QUANTILES] + [
            "score_mean",
            "score_max",
        ]

        write_csv(
            OUTPUT_DIR / "candidate_exponent_global_profiles.csv",
            global_profiles,
            global_fields,
        )

        consistency_rows: list[dict[str, Any]] = []
        for exponent in CANDIDATE_EXPONENTS:
            rows = [
                row
                for row in candidate_profiles
                if float(row["exponent"]) == exponent
            ]

            consistency_row: dict[str, Any] = {
                "exponent": exponent,
                "event_combination_count": len(rows),
            }

            for field in [
                "score_q25",
                "score_q50",
                "score_q75",
                "score_q90",
                "score_q95",
                "score_q99",
            ]:
                values = [
                    float(row[field])
                    for row in rows
                    if row[field] is not None
                ]
                consistency_row[f"{field}_event_mean"] = (
                    statistics.mean(values)
                    if values else None
                )
                consistency_row[f"{field}_event_sd"] = (
                    statistics.pstdev(values)
                    if len(values) > 1 else 0.0
                )
                consistency_row[f"{field}_event_min"] = (
                    min(values) if values else None
                )
                consistency_row[f"{field}_event_max"] = (
                    max(values) if values else None
                )

            consistency_rows.append(consistency_row)

        consistency_fields = [
            "exponent",
            "event_combination_count",
        ]
        for field in [
            "score_q25",
            "score_q50",
            "score_q75",
            "score_q90",
            "score_q95",
            "score_q99",
        ]:
            consistency_fields.extend(
                [
                    f"{field}_event_mean",
                    f"{field}_event_sd",
                    f"{field}_event_min",
                    f"{field}_event_max",
                ]
            )

        write_csv(
            OUTPUT_DIR / "candidate_exponent_event_consistency.csv",
            consistency_rows,
            consistency_fields,
        )

        # Demonstrate the intended nonlinear behavior using the original 5K
        # example and a corresponding long-jump example.
        men_5k = anchor_lookup[("outdoor", "m", "5000M")]
        men_lj = anchor_lookup[("outdoor", "m", "LJ")]

        men_5k_anchor = float(men_5k["record_mark_normalized"])
        men_lj_anchor = float(men_lj["record_mark_normalized"])

        example_rows: list[dict[str, Any]] = []
        time_gain_checks: list[bool] = []
        field_gain_checks: list[bool] = []

        for exponent in CANDIDATE_EXPONENTS:
            slow_start = score_value(
                men_5k_anchor,
                17 * 60,
                "lower_is_better",
                exponent,
            )
            slow_finish = score_value(
                men_5k_anchor,
                16 * 60 + 50,
                "lower_is_better",
                exponent,
            )
            elite_start = score_value(
                men_5k_anchor,
                14 * 60,
                "lower_is_better",
                exponent,
            )
            elite_finish = score_value(
                men_5k_anchor,
                13 * 60 + 50,
                "lower_is_better",
                exponent,
            )

            slow_gain = slow_finish - slow_start
            elite_gain = elite_finish - elite_start
            time_gain_checks.append(elite_gain > slow_gain)

            example_rows.extend(
                [
                    {
                        "event_code": "5000M",
                        "direction": "lower_is_better",
                        "exponent": exponent,
                        "scenario": "developmental_17:00_to_16:50",
                        "start_mark": 1020.0,
                        "finish_mark": 1010.0,
                        "start_score": slow_start,
                        "finish_score": slow_finish,
                        "score_gain": slow_gain,
                    },
                    {
                        "event_code": "5000M",
                        "direction": "lower_is_better",
                        "exponent": exponent,
                        "scenario": "elite_14:00_to_13:50",
                        "start_mark": 840.0,
                        "finish_mark": 830.0,
                        "start_score": elite_start,
                        "finish_score": elite_finish,
                        "score_gain": elite_gain,
                    },
                ]
            )

            field_start_low = score_value(
                men_lj_anchor,
                7.00,
                "higher_is_better",
                exponent,
            )
            field_finish_low = score_value(
                men_lj_anchor,
                7.10,
                "higher_is_better",
                exponent,
            )
            field_start_high = score_value(
                men_lj_anchor,
                8.00,
                "higher_is_better",
                exponent,
            )
            field_finish_high = score_value(
                men_lj_anchor,
                8.10,
                "higher_is_better",
                exponent,
            )

            low_gain = field_finish_low - field_start_low
            high_gain = field_finish_high - field_start_high
            field_gain_checks.append(high_gain > low_gain)

            example_rows.extend(
                [
                    {
                        "event_code": "LJ",
                        "direction": "higher_is_better",
                        "exponent": exponent,
                        "scenario": "developmental_7.00_to_7.10",
                        "start_mark": 7.00,
                        "finish_mark": 7.10,
                        "start_score": field_start_low,
                        "finish_score": field_finish_low,
                        "score_gain": low_gain,
                    },
                    {
                        "event_code": "LJ",
                        "direction": "higher_is_better",
                        "exponent": exponent,
                        "scenario": "elite_8.00_to_8.10",
                        "start_mark": 8.00,
                        "finish_mark": 8.10,
                        "start_score": field_start_high,
                        "finish_score": field_finish_high,
                        "score_gain": high_gain,
                    },
                ]
            )

        write_csv(
            OUTPUT_DIR / "design_examples.csv",
            example_rows,
            [
                "event_code",
                "direction",
                "exponent",
                "scenario",
                "start_mark",
                "finish_mark",
                "start_score",
                "finish_score",
                "score_gain",
            ],
        )

        formula_rows = [
            {
                "component": "lower_is_better_ratio",
                "definition": "anchor_value / performance_value",
                "purpose": "Running, hurdles, and steeplechase",
            },
            {
                "component": "higher_is_better_ratio",
                "definition": "performance_value / anchor_value",
                "purpose": "Jumps, throws, and combined events",
            },
            {
                "component": "bounded_ratio",
                "definition": "min(1, max(0, performance_ratio))",
                "purpose": (
                    "Anchor and better performances cap at 1; "
                    "exceedances remain separately audited"
                ),
            },
            {
                "component": "performance_level",
                "definition": "100 * bounded_ratio ** exponent",
                "purpose": (
                    "Nonlinear, unitless event-independent performance level"
                ),
            },
            {
                "component": "development",
                "definition": "later_level - earlier_level",
                "purpose": (
                    "Not calculated until trajectory and baseline phases"
                ),
            },
        ]

        write_csv(
            OUTPUT_DIR / "formula_definition.csv",
            formula_rows,
            ["component", "definition", "purpose"],
        )

        join_coverage_rows = [
            {
                "metric": "all_track_scoring_performances",
                "value": foundation_count,
            },
            {
                "metric": "official_event_performances_with_anchor",
                "value": joined_count,
            },
            {
                "metric": "nonofficial_event_performances_without_anchor",
                "value": excluded_performance_count,
            },
            {
                "metric": "official_event_performance_coverage",
                "value": joined_count / foundation_count,
            },
            {
                "metric": "official_anchor_combinations_joined",
                "value": joined_combination_count,
            },
            {
                "metric": "nonofficial_combinations_excluded",
                "value": len(excluded_rows),
            },
        ]

        write_csv(
            OUTPUT_DIR / "anchor_join_coverage.csv",
            join_coverage_rows,
            ["metric", "value"],
        )

        add_check(
            checks,
            "foundation_row_count",
            foundation_count == EXPECTED_FOUNDATION_ROWS,
            foundation_count,
            EXPECTED_FOUNDATION_ROWS,
        )
        add_check(
            checks,
            "official_scoring_row_count",
            joined_count == EXPECTED_OFFICIAL_SCORING_ROWS,
            joined_count,
            EXPECTED_OFFICIAL_SCORING_ROWS,
        )
        add_check(
            checks,
            "official_combination_count",
            joined_combination_count
            == EXPECTED_OFFICIAL_COMBINATIONS,
            joined_combination_count,
            EXPECTED_OFFICIAL_COMBINATIONS,
        )
        add_check(
            checks,
            "excluded_combination_count",
            len(excluded_rows) == EXPECTED_EXCLUDED_COMBINATIONS,
            len(excluded_rows),
            EXPECTED_EXCLUDED_COMBINATIONS,
        )
        add_check(
            checks,
            "joined_and_excluded_rows_reconcile",
            joined_count + excluded_performance_count
            == foundation_count,
            joined_count + excluded_performance_count,
            foundation_count,
        )
        add_check(
            checks,
            "no_direction_mismatches",
            direction_mismatch_count == 0,
            direction_mismatch_count,
            0,
        )
        add_check(
            checks,
            "no_invalid_performance_ratios",
            invalid_ratio_count == 0,
            invalid_ratio_count,
            0,
        )
        add_check(
            checks,
            "candidate_exponent_count",
            len(CANDIDATE_EXPONENTS) == 6,
            len(CANDIDATE_EXPONENTS),
            6,
        )
        add_check(
            checks,
            "candidate_event_profile_row_count",
            len(candidate_profiles)
            == EXPECTED_OFFICIAL_COMBINATIONS
            * len(CANDIDATE_EXPONENTS),
            len(candidate_profiles),
            (
                EXPECTED_OFFICIAL_COMBINATIONS
                * len(CANDIDATE_EXPONENTS)
            ),
        )
        add_check(
            checks,
            "time_example_rewards_elite_improvement_more",
            all(time_gain_checks),
            time_gain_checks,
            "all True",
        )
        add_check(
            checks,
            "field_example_rewards_elite_improvement_more",
            all(field_gain_checks),
            field_gain_checks,
            "all True",
        )

        exceedance_rate = float(
            ratio_overall["anchor_exceedance_rate"] or 0.0
        )
        max_raw_ratio = float(
            ratio_overall["max_raw_ratio"] or 0.0
        )

        add_check(
            checks,
            "anchor_exceedance_rate_below_half_percent",
            exceedance_rate <= 0.005,
            exceedance_rate,
            "at most 0.005",
            (
                "Better-than-anchor rows are capped at 100 and "
                "must be reviewed for wind, legality, or metadata."
            ),
        )
        add_check(
            checks,
            "no_extreme_anchor_exceedance",
            max_raw_ratio <= 1.20,
            max_raw_ratio,
            "at most 1.20",
        )

    finally:
        connection.close()

    foundation_stat_after = FOUNDATION_DB.stat()
    anchor_hash_after = sha256_file(ANCHOR_CSV)

    foundation_unchanged = (
        foundation_stat_before.st_size
        == foundation_stat_after.st_size
        and foundation_stat_before.st_mtime_ns
        == foundation_stat_after.st_mtime_ns
    )

    add_check(
        checks,
        "foundation_database_unchanged",
        foundation_unchanged,
        {
            "size": foundation_stat_after.st_size,
            "mtime_ns": foundation_stat_after.st_mtime_ns,
        },
        {
            "size": foundation_stat_before.st_size,
            "mtime_ns": foundation_stat_before.st_mtime_ns,
        },
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
                "input_name": "track_performance_foundation",
                "path": str(FOUNDATION_DB),
                "size_before": foundation_stat_before.st_size,
                "size_after": foundation_stat_after.st_size,
                "mtime_ns_before": foundation_stat_before.st_mtime_ns,
                "mtime_ns_after": foundation_stat_after.st_mtime_ns,
                "sha256_before": "",
                "sha256_after": "",
            },
            {
                "input_name": "eligibility_anchor_registry",
                "path": str(ANCHOR_CSV),
                "size_before": ANCHOR_CSV.stat().st_size,
                "size_after": ANCHOR_CSV.stat().st_size,
                "mtime_ns_before": ANCHOR_CSV.stat().st_mtime_ns,
                "mtime_ns_after": ANCHOR_CSV.stat().st_mtime_ns,
                "sha256_before": anchor_hash_before,
                "sha256_after": anchor_hash_after,
            },
        ],
        [
            "input_name",
            "path",
            "size_before",
            "size_after",
            "mtime_ns_before",
            "mtime_ns_after",
            "sha256_before",
            "sha256_after",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 5 PHASE 4B — PERFORMANCE-LEVEL CALIBRATION",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Calibration version: {CALIBRATION_VERSION}",
        "",
        "FORMULA",
        "-" * 78,
        "Lower-is-better ratio: anchor / performance",
        "Higher-is-better ratio: performance / anchor",
        "Candidate level: 100 × min(1, ratio)^p",
        "Better-than-anchor rows are capped at 100 and audited.",
        "",
        "SCORING SCOPE",
        "-" * 78,
        f"All track scoring performances: {foundation_count:,}",
        f"Official-event performances with anchors: {joined_count:,}",
        f"Official-event coverage: {joined_count / foundation_count:.6%}",
        f"Official event combinations: {joined_combination_count:,}",
        f"Nonofficial combinations excluded: {len(excluded_rows):,}",
        "",
        "ANCHOR EXCEEDANCE AUDIT",
        "-" * 78,
        f"Rows better than anchor: "
        f"{int(ratio_overall['anchor_exceedance_count']):,}",
        f"Exceedance rate: {exceedance_rate:.6%}",
        f"Maximum raw ratio: {max_raw_ratio:.6f}",
        "",
        "CANDIDATE EXPONENTS",
        "-" * 78,
        ", ".join(str(value) for value in CANDIDATE_EXPONENTS),
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Candidate nonlinear scales are ready for review."
            if not failed
            else (
                "FAIL — Review anchor exceedances, schema, or "
                "join reconciliation before selecting an exponent."
            )
        ),
    ]

    (OUTPUT_DIR / "phase_4b_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"All scoring performances: {foundation_count:,}")
    print(f"Official-event performances: {joined_count:,}")
    print(
        "Official-event coverage: "
        f"{joined_count / foundation_count:.6%}"
    )
    print(
        "Rows better than anchor: "
        f"{int(ratio_overall['anchor_exceedance_count']):,}"
    )
    print(f"Anchor exceedance rate: {exceedance_rate:.6%}")
    print(f"Maximum raw ratio: {max_raw_ratio:.6f}")
    print(
        "Candidate exponents: "
        + ", ".join(str(value) for value in CANDIDATE_EXPONENTS)
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
    print("Next: review distributions and freeze the exponent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
