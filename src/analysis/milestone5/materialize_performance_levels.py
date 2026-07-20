#!/usr/bin/env python3
"""
Milestone 5 Phase 4E — Materialize Normalized Performance Levels

Creates a versioned DuckDB artifact containing every official-event scoring
performance joined to its collegiate-eligibility anchor and transformed under
the frozen square-law policy.

Primary formula
---------------
Lower-is-better:
    ratio = anchor_value / performance_value

Higher-is-better:
    ratio = performance_value / anchor_value

Performance level:
    100 * min(1, max(0, ratio)) ** 2

Exceedance overrides
--------------------
- 49 unresolved exceedances remain in the table but are marked ineligible
  and receive NULL performance_level values.
- 2 rounding-tolerance exceedances remain eligible and receive a score of 100.
- All other official-event rows are eligible.

No source database or registry is modified.
"""

from __future__ import annotations

import csv
import hashlib
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

PHASE_4C_AUDIT = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4c_anchor_exceedance_audit/"
      "anchor_exceedance_audit.csv"
)

PHASE_4D_POLICY = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4d_frozen_performance_level_policy/"
      "performance_level_policy.csv"
)

OUTPUT_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_4e_materialized_performance_levels"
)

OUTPUT_DB = OUTPUT_DIR / "performance_levels_v1.duckdb"

DATASET_VERSION = "performance_levels_v1"
POLICY_VERSION = "performance_level_policy_v1"
SELECTED_EXPONENT = 2.0

EXPECTED_TOTAL_OFFICIAL_ROWS = 4_664_090
EXPECTED_QUARANTINED_ROWS = 49
EXPECTED_TOLERANCE_ROWS = 2
EXPECTED_ELIGIBLE_ROWS = (
    EXPECTED_TOTAL_OFFICIAL_ROWS - EXPECTED_QUARANTINED_ROWS
)
EXPECTED_ANCHOR_ROWS = 82


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sql_path(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
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


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    inputs = [
        FOUNDATION_DB,
        ANCHOR_CSV,
        PHASE_4C_AUDIT,
        PHASE_4D_POLICY,
    ]

    print("MILESTONE 5 PHASE 4E — MATERIALIZE PERFORMANCE LEVELS")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {DATASET_VERSION}")
    print(f"Policy version: {POLICY_VERSION}")
    print(f"Output database: {OUTPUT_DB}")

    missing = [str(path) for path in inputs if not path.exists()]
    add_check(
        checks,
        "all_required_inputs_exist",
        not missing,
        missing,
        [],
    )

    if missing:
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Required inputs missing.")
        return 1

    input_hashes_before = {
        str(path): sha256_file(path)
        for path in inputs
    }

    with PHASE_4D_POLICY.open(newline="", encoding="utf-8") as handle:
        policy_rows = list(csv.DictReader(handle))

    policy_lookup = {
        row["policy_component"]: row["value"]
        for row in policy_rows
    }

    add_check(
        checks,
        "policy_version_matches",
        policy_lookup.get("policy_version") == POLICY_VERSION,
        policy_lookup.get("policy_version"),
        POLICY_VERSION,
    )
    add_check(
        checks,
        "selected_exponent_matches",
        float(policy_lookup.get("selected_exponent", "nan"))
        == SELECTED_EXPONENT,
        policy_lookup.get("selected_exponent"),
        SELECTED_EXPONENT,
    )

    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()

    connection = duckdb.connect(str(OUTPUT_DB))

    try:
        connection.execute("PRAGMA threads=4")
        connection.execute("PRAGMA enable_progress_bar=false")

        connection.execute(
            f"""
            ATTACH '{sql_path(FOUNDATION_DB)}'
                AS foundation (READ_ONLY)
            """
        )

        connection.execute(
            f"""
            CREATE TABLE anchors AS
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                canonical_event_name,
                CAST(record_mark_normalized AS DOUBLE)
                    AS anchor_value,
                selection_direction AS anchor_direction,
                anchor_status,
                pending_ratification,
                outside_regular_collegiate_season,
                holder AS anchor_holder,
                school AS anchor_school,
                source_as_of,
                registry_version,
                policy_version AS anchor_policy_version
            FROM read_csv_auto(
                '{sql_path(ANCHOR_CSV)}',
                HEADER = TRUE,
                ALL_VARCHAR = TRUE
            )
            """
        )

        connection.execute(
            f"""
            CREATE TABLE exceedance_audit AS
            SELECT
                audit_exceedance_id,
                source_performance_id,
                season_type,
                canonical_gender_code,
                canonical_event_code,
                canonical_person_id,
                athlete_name,
                CAST(performance_value AS DOUBLE)
                    AS performance_value,
                raw_mark,
                resolved_school_id,
                school_stint_id,
                season_id,
                performance_date,
                meet_name,
                scoring_action,
                provisional_classification,
                severity,
                review_priority,
                CAST(raw_performance_ratio AS DOUBLE)
                    AS audited_raw_ratio
            FROM read_csv_auto(
                '{sql_path(PHASE_4C_AUDIT)}',
                HEADER = TRUE,
                ALL_VARCHAR = TRUE
            )
            """
        )

        anchor_count = connection.execute(
            "SELECT COUNT(*) FROM anchors"
        ).fetchone()[0]

        audit_count = connection.execute(
            "SELECT COUNT(*) FROM exceedance_audit"
        ).fetchone()[0]

        add_check(
            checks,
            "anchor_row_count",
            anchor_count == EXPECTED_ANCHOR_ROWS,
            anchor_count,
            EXPECTED_ANCHOR_ROWS,
        )
        add_check(
            checks,
            "audit_row_count",
            audit_count
            == EXPECTED_QUARANTINED_ROWS
            + EXPECTED_TOLERANCE_ROWS,
            audit_count,
            EXPECTED_QUARANTINED_ROWS
            + EXPECTED_TOLERANCE_ROWS,
        )

        connection.execute(
            """
            CREATE TABLE performance_levels AS
            WITH official_rows AS (
                SELECT
                    p.*,
                    a.anchor_value,
                    a.anchor_direction,
                    a.anchor_status,
                    a.pending_ratification,
                    a.outside_regular_collegiate_season,
                    a.anchor_holder,
                    a.anchor_school,
                    a.source_as_of AS anchor_source_as_of,
                    a.registry_version AS anchor_registry_version,
                    a.anchor_policy_version,
                    CASE
                        WHEN a.anchor_direction = 'lower_is_better'
                            THEN a.anchor_value
                                 / p.primary_parsed_value
                        WHEN a.anchor_direction = 'higher_is_better'
                            THEN p.primary_parsed_value
                                 / a.anchor_value
                        ELSE NULL
                    END AS raw_performance_ratio
                FROM foundation.main.track_scoring_performances p
                JOIN anchors a
                  USING (
                    season_type,
                    canonical_gender_code,
                    canonical_event_code
                  )
            ),
            matched AS (
                SELECT
                    o.*,
                    x.audit_exceedance_id,
                    x.scoring_action AS exceedance_scoring_action,
                    x.provisional_classification
                        AS exceedance_classification,
                    x.severity AS exceedance_severity,
                    x.review_priority AS exceedance_review_priority
                FROM official_rows o
                LEFT JOIN exceedance_audit x
                  ON o.season_type = x.season_type
                 AND o.canonical_gender_code =
                     x.canonical_gender_code
                 AND o.canonical_event_code =
                     x.canonical_event_code
                 AND o.canonical_person_id
                     IS NOT DISTINCT FROM x.canonical_person_id
                 AND o.primary_parsed_value
                     IS NOT DISTINCT FROM x.performance_value
                 AND o.raw_mark
                     IS NOT DISTINCT FROM x.raw_mark
                 AND o.resolved_school_id
                     IS NOT DISTINCT FROM x.resolved_school_id
                 AND o.school_stint_id
                     IS NOT DISTINCT FROM x.school_stint_id
                 AND o.season_id
                     IS NOT DISTINCT FROM x.season_id
                 AND CAST(o.performance_date AS VARCHAR)
                     IS NOT DISTINCT FROM x.performance_date
                 AND o.meet_name
                     IS NOT DISTINCT FROM x.meet_name
            )
            SELECT
                *,
                CASE
                    WHEN exceedance_scoring_action =
                        'quarantine_from_primary_scoring'
                        THEN FALSE
                    ELSE TRUE
                END AS primary_scoring_eligible,
                CASE
                    WHEN exceedance_scoring_action =
                        'quarantine_from_primary_scoring'
                        THEN NULL
                    WHEN exceedance_scoring_action =
                        'eligible_capped_at_100'
                        THEN 100.0
                    ELSE
                        100.0 * POWER(
                            LEAST(
                                1.0,
                                GREATEST(
                                    0.0,
                                    raw_performance_ratio
                                )
                            ),
                            2.0
                        )
                END AS performance_level,
                CASE
                    WHEN exceedance_scoring_action =
                        'quarantine_from_primary_scoring'
                        THEN 'quarantined_exceedance'
                    WHEN exceedance_scoring_action =
                        'eligible_capped_at_100'
                        THEN 'rounding_tolerance_cap'
                    ELSE 'standard_formula'
                END AS scoring_path,
                'performance_level_policy_v1'
                    AS performance_level_policy_version,
                'performance_levels_v1'
                    AS performance_level_dataset_version
            FROM matched
            """
        )

        connection.execute(
            """
            CREATE VIEW eligible_performance_levels AS
            SELECT *
            FROM performance_levels
            WHERE primary_scoring_eligible
            """
        )

        connection.execute(
            """
            CREATE VIEW quarantined_performance_levels AS
            SELECT *
            FROM performance_levels
            WHERE NOT primary_scoring_eligible
            """
        )

        connection.execute(
            """
            CREATE TABLE dataset_metadata AS
            SELECT
                'dataset_version' AS metadata_key,
                'performance_levels_v1' AS metadata_value
            UNION ALL
            SELECT
                'policy_version',
                'performance_level_policy_v1'
            UNION ALL
            SELECT
                'selected_exponent',
                '2.0'
            UNION ALL
            SELECT
                'created_at_utc',
                CURRENT_TIMESTAMP::VARCHAR
            """
        )

        counts = fetch_dicts(
            connection,
            """
            SELECT
                COUNT(*) AS total_rows,
                COUNT(*) FILTER (
                    WHERE primary_scoring_eligible
                ) AS eligible_rows,
                COUNT(*) FILTER (
                    WHERE NOT primary_scoring_eligible
                ) AS quarantined_rows,
                COUNT(*) FILTER (
                    WHERE scoring_path =
                        'rounding_tolerance_cap'
                ) AS tolerance_rows,
                COUNT(*) FILTER (
                    WHERE scoring_path =
                        'standard_formula'
                ) AS standard_formula_rows,
                COUNT(*) FILTER (
                    WHERE performance_level IS NULL
                ) AS null_score_rows,
                COUNT(*) FILTER (
                    WHERE performance_level < 0
                       OR performance_level > 100
                ) AS score_out_of_range_rows,
                COUNT(*) FILTER (
                    WHERE primary_scoring_eligible
                      AND performance_level IS NULL
                ) AS eligible_null_score_rows,
                COUNT(*) FILTER (
                    WHERE NOT primary_scoring_eligible
                      AND performance_level IS NOT NULL
                ) AS quarantined_nonnull_score_rows,
                MIN(performance_level) FILTER (
                    WHERE primary_scoring_eligible
                ) AS min_eligible_score,
                MAX(performance_level) FILTER (
                    WHERE primary_scoring_eligible
                ) AS max_eligible_score,
                AVG(performance_level) FILTER (
                    WHERE primary_scoring_eligible
                ) AS mean_eligible_score
            FROM performance_levels
            """
        )[0]

        matched_audit_rows = connection.execute(
            """
            SELECT COUNT(DISTINCT audit_exceedance_id)
            FROM performance_levels
            WHERE audit_exceedance_id IS NOT NULL
            """
        ).fetchone()[0]

        audit_match_multiplicity = fetch_dicts(
            connection,
            """
            SELECT
                audit_exceedance_id,
                COUNT(*) AS matched_row_count
            FROM performance_levels
            WHERE audit_exceedance_id IS NOT NULL
            GROUP BY audit_exceedance_id
            HAVING COUNT(*) <> 1
            ORDER BY matched_row_count DESC, audit_exceedance_id
            """
        )

        add_check(
            checks,
            "materialized_total_row_count",
            counts["total_rows"]
            == EXPECTED_TOTAL_OFFICIAL_ROWS,
            counts["total_rows"],
            EXPECTED_TOTAL_OFFICIAL_ROWS,
        )
        add_check(
            checks,
            "eligible_row_count",
            counts["eligible_rows"] == EXPECTED_ELIGIBLE_ROWS,
            counts["eligible_rows"],
            EXPECTED_ELIGIBLE_ROWS,
        )
        add_check(
            checks,
            "quarantined_row_count",
            counts["quarantined_rows"]
            == EXPECTED_QUARANTINED_ROWS,
            counts["quarantined_rows"],
            EXPECTED_QUARANTINED_ROWS,
        )
        add_check(
            checks,
            "rounding_tolerance_row_count",
            counts["tolerance_rows"]
            == EXPECTED_TOLERANCE_ROWS,
            counts["tolerance_rows"],
            EXPECTED_TOLERANCE_ROWS,
        )
        add_check(
            checks,
            "all_audit_rows_matched_once",
            matched_audit_rows
            == EXPECTED_QUARANTINED_ROWS
            + EXPECTED_TOLERANCE_ROWS
            and not audit_match_multiplicity,
            {
                "distinct_matched_audit_rows": matched_audit_rows,
                "multiplicity_issue_count": len(
                    audit_match_multiplicity
                ),
            },
            {
                "distinct_matched_audit_rows":
                    EXPECTED_QUARANTINED_ROWS
                    + EXPECTED_TOLERANCE_ROWS,
                "multiplicity_issue_count": 0,
            },
        )
        add_check(
            checks,
            "null_scores_only_for_quarantine",
            counts["null_score_rows"]
            == EXPECTED_QUARANTINED_ROWS
            and counts["eligible_null_score_rows"] == 0,
            {
                "null_score_rows": counts["null_score_rows"],
                "eligible_null_score_rows":
                    counts["eligible_null_score_rows"],
            },
            {
                "null_score_rows": EXPECTED_QUARANTINED_ROWS,
                "eligible_null_score_rows": 0,
            },
        )
        add_check(
            checks,
            "quarantined_rows_have_no_scores",
            counts["quarantined_nonnull_score_rows"] == 0,
            counts["quarantined_nonnull_score_rows"],
            0,
        )
        add_check(
            checks,
            "all_eligible_scores_in_range",
            counts["score_out_of_range_rows"] == 0,
            counts["score_out_of_range_rows"],
            0,
        )
        add_check(
            checks,
            "maximum_eligible_score_is_100",
            abs(float(counts["max_eligible_score"]) - 100.0)
            <= 1e-12,
            counts["max_eligible_score"],
            100.0,
        )

        duplicate_source_ids = fetch_dicts(
            connection,
            """
            SELECT
                canonical_person_performance_id,
                COUNT(*) AS row_count
            FROM performance_levels
            GROUP BY canonical_person_performance_id
            HAVING COUNT(*) > 1
            ORDER BY row_count DESC
            LIMIT 100
            """
        )

        add_check(
            checks,
            "canonical_performance_ids_unique",
            not duplicate_source_ids,
            len(duplicate_source_ids),
            0,
        )

        event_profiles = fetch_dicts(
            connection,
            """
            SELECT
                season_type,
                canonical_gender_code,
                canonical_event_code,
                ANY_VALUE(canonical_event_name)
                    AS canonical_event_name,
                COUNT(*) AS total_rows,
                COUNT(*) FILTER (
                    WHERE primary_scoring_eligible
                ) AS eligible_rows,
                COUNT(*) FILTER (
                    WHERE NOT primary_scoring_eligible
                ) AS quarantined_rows,
                COUNT(DISTINCT canonical_person_id)
                    FILTER (
                        WHERE primary_scoring_eligible
                    ) AS eligible_athletes,
                MIN(performance_level)
                    FILTER (
                        WHERE primary_scoring_eligible
                    ) AS min_score,
                APPROX_QUANTILE(
                    performance_level,
                    0.25
                ) FILTER (
                    WHERE primary_scoring_eligible
                ) AS score_q25,
                APPROX_QUANTILE(
                    performance_level,
                    0.50
                ) FILTER (
                    WHERE primary_scoring_eligible
                ) AS score_q50,
                APPROX_QUANTILE(
                    performance_level,
                    0.75
                ) FILTER (
                    WHERE primary_scoring_eligible
                ) AS score_q75,
                APPROX_QUANTILE(
                    performance_level,
                    0.90
                ) FILTER (
                    WHERE primary_scoring_eligible
                ) AS score_q90,
                APPROX_QUANTILE(
                    performance_level,
                    0.99
                ) FILTER (
                    WHERE primary_scoring_eligible
                ) AS score_q99,
                AVG(performance_level)
                    FILTER (
                        WHERE primary_scoring_eligible
                    ) AS mean_score,
                MAX(performance_level)
                    FILTER (
                        WHERE primary_scoring_eligible
                    ) AS max_score
            FROM performance_levels
            GROUP BY
                season_type,
                canonical_gender_code,
                canonical_event_code
            ORDER BY
                season_type,
                canonical_gender_code,
                canonical_event_code
            """
        )

        write_csv(
            OUTPUT_DIR / "event_score_profiles.csv",
            event_profiles,
            [
                "season_type",
                "canonical_gender_code",
                "canonical_event_code",
                "canonical_event_name",
                "total_rows",
                "eligible_rows",
                "quarantined_rows",
                "eligible_athletes",
                "min_score",
                "score_q25",
                "score_q50",
                "score_q75",
                "score_q90",
                "score_q99",
                "mean_score",
                "max_score",
            ],
        )

        season_profiles = fetch_dicts(
            connection,
            """
            SELECT
                season_year,
                season_type,
                COUNT(*) AS total_rows,
                COUNT(*) FILTER (
                    WHERE primary_scoring_eligible
                ) AS eligible_rows,
                COUNT(*) FILTER (
                    WHERE NOT primary_scoring_eligible
                ) AS quarantined_rows,
                COUNT(DISTINCT canonical_person_id)
                    FILTER (
                        WHERE primary_scoring_eligible
                    ) AS eligible_athletes,
                COUNT(DISTINCT resolved_school_id)
                    FILTER (
                        WHERE primary_scoring_eligible
                    ) AS eligible_schools,
                AVG(performance_level)
                    FILTER (
                        WHERE primary_scoring_eligible
                    ) AS mean_score,
                APPROX_QUANTILE(
                    performance_level,
                    0.50
                ) FILTER (
                    WHERE primary_scoring_eligible
                ) AS median_score
            FROM performance_levels
            GROUP BY season_year, season_type
            ORDER BY season_year, season_type
            """
        )

        write_csv(
            OUTPUT_DIR / "season_score_profiles.csv",
            season_profiles,
            [
                "season_year",
                "season_type",
                "total_rows",
                "eligible_rows",
                "quarantined_rows",
                "eligible_athletes",
                "eligible_schools",
                "mean_score",
                "median_score",
            ],
        )

        quarantine_export = fetch_dicts(
            connection,
            """
            SELECT
                audit_exceedance_id,
                canonical_person_performance_id,
                canonical_person_id,
                athlete_name,
                season_type,
                season_year,
                canonical_gender_code,
                canonical_event_code,
                raw_mark,
                primary_parsed_value AS performance_value,
                anchor_value,
                raw_performance_ratio,
                resolved_school_id,
                school_stint_id,
                season_id,
                performance_date,
                meet_name,
                exceedance_classification,
                exceedance_severity,
                exceedance_review_priority,
                scoring_path
            FROM quarantined_performance_levels
            ORDER BY
                raw_performance_ratio DESC,
                season_type,
                canonical_gender_code,
                canonical_event_code
            """
        )

        write_csv(
            OUTPUT_DIR / "materialized_quarantine_registry.csv",
            quarantine_export,
            [
                "audit_exceedance_id",
                "canonical_person_performance_id",
                "canonical_person_id",
                "athlete_name",
                "season_type",
                "season_year",
                "canonical_gender_code",
                "canonical_event_code",
                "raw_mark",
                "performance_value",
                "anchor_value",
                "raw_performance_ratio",
                "resolved_school_id",
                "school_stint_id",
                "season_id",
                "performance_date",
                "meet_name",
                "exceedance_classification",
                "exceedance_severity",
                "exceedance_review_priority",
                "scoring_path",
            ],
        )

        summary_rows = [
            {
                "metric": "total_official_rows",
                "value": counts["total_rows"],
            },
            {
                "metric": "eligible_rows",
                "value": counts["eligible_rows"],
            },
            {
                "metric": "quarantined_rows",
                "value": counts["quarantined_rows"],
            },
            {
                "metric": "rounding_tolerance_rows",
                "value": counts["tolerance_rows"],
            },
            {
                "metric": "standard_formula_rows",
                "value": counts["standard_formula_rows"],
            },
            {
                "metric": "minimum_eligible_score",
                "value": counts["min_eligible_score"],
            },
            {
                "metric": "maximum_eligible_score",
                "value": counts["max_eligible_score"],
            },
            {
                "metric": "mean_eligible_score",
                "value": counts["mean_eligible_score"],
            },
            {
                "metric": "output_database_bytes",
                "value": OUTPUT_DB.stat().st_size,
            },
        ]

        write_csv(
            OUTPUT_DIR / "materialization_summary.csv",
            summary_rows,
            ["metric", "value"],
        )

        if audit_match_multiplicity:
            write_csv(
                OUTPUT_DIR / "audit_match_multiplicity_issues.csv",
                audit_match_multiplicity,
                ["audit_exceedance_id", "matched_row_count"],
            )

        if duplicate_source_ids:
            write_csv(
                OUTPUT_DIR / "duplicate_performance_id_issues.csv",
                duplicate_source_ids,
                [
                    "canonical_person_performance_id",
                    "row_count",
                ],
            )

    finally:
        connection.close()

    input_hashes_after = {
        str(path): sha256_file(path)
        for path in inputs
    }

    add_check(
        checks,
        "all_inputs_unchanged",
        input_hashes_before == input_hashes_after,
        input_hashes_after,
        input_hashes_before,
    )

    output_hash = sha256_file(OUTPUT_DB)

    write_csv(
        OUTPUT_DIR / "input_manifest.csv",
        [
            {
                "input_name": path.name,
                "path": str(path),
                "sha256_before": input_hashes_before[str(path)],
                "sha256_after": input_hashes_after[str(path)],
            }
            for path in inputs
        ],
        [
            "input_name",
            "path",
            "sha256_before",
            "sha256_after",
        ],
    )

    write_csv(
        OUTPUT_DIR / "output_manifest.csv",
        [
            {
                "output_name": OUTPUT_DB.name,
                "path": str(OUTPUT_DB),
                "size_bytes": OUTPUT_DB.stat().st_size,
                "sha256": output_hash,
                "dataset_version": DATASET_VERSION,
                "policy_version": POLICY_VERSION,
            }
        ],
        [
            "output_name",
            "path",
            "size_bytes",
            "sha256",
            "dataset_version",
            "policy_version",
        ],
    )

    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]

    report = [
        "MILESTONE 5 PHASE 4E — MATERIALIZED PERFORMANCE LEVELS",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {DATASET_VERSION}",
        f"Policy version: {POLICY_VERSION}",
        f"Output database: {OUTPUT_DB}",
        "",
        "RESULTS",
        "-" * 78,
        f"Official-event rows: {int(counts['total_rows']):,}",
        f"Primary-scoring eligible rows: "
        f"{int(counts['eligible_rows']):,}",
        f"Quarantined rows retained with NULL score: "
        f"{int(counts['quarantined_rows']):,}",
        f"Rounding-tolerance rows capped at 100: "
        f"{int(counts['tolerance_rows']):,}",
        f"Minimum eligible score: "
        f"{float(counts['min_eligible_score']):.6f}",
        f"Maximum eligible score: "
        f"{float(counts['max_eligible_score']):.6f}",
        f"Mean eligible score: "
        f"{float(counts['mean_eligible_score']):.6f}",
        f"Output size: {OUTPUT_DB.stat().st_size:,} bytes",
        "",
        "TABLES AND VIEWS",
        "-" * 78,
        "performance_levels — all official rows with scoring status",
        "eligible_performance_levels — primary scoring cohort",
        "quarantined_performance_levels — excluded audit rows",
        "anchors — frozen anchor snapshot",
        "exceedance_audit — frozen Phase 4C audit snapshot",
        "dataset_metadata — version and policy metadata",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Normalized performance levels materialized."
            if not failed
            else "FAIL — Do not build athlete trajectories."
        ),
        "",
        "NEXT",
        "-" * 78,
        "Construct stable athlete-event-period performance estimates.",
        "Do not use single first marks or isolated career bests.",
    ]

    (OUTPUT_DIR / "phase_4e_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Official-event rows: {int(counts['total_rows']):,}"
    )
    print(
        "Eligible rows: "
        f"{int(counts['eligible_rows']):,}"
    )
    print(
        "Quarantined rows: "
        f"{int(counts['quarantined_rows']):,}"
    )
    print(
        "Tolerance rows capped at 100: "
        f"{int(counts['tolerance_rows']):,}"
    )
    print(
        "Mean eligible score: "
        f"{float(counts['mean_eligible_score']):.6f}"
    )
    print(f"Output database: {OUTPUT_DB}")
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
    print("Next: build stable athlete-event-period estimates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
