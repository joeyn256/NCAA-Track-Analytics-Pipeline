#!/usr/bin/env python3
"""Milestone 6 Phase 6C: audit event influence and temporal fairness."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import duckdb


ROOT = Path.cwd()
SOURCE_DIR = ROOT / (
    "data/processed/milestone6/seasonal_development_rankings_v1/"
    "phase_6a_seasonal_rankings"
)
SOURCE_DB = SOURCE_DIR / "seasonal_development_rankings_v1.duckdb"
SOURCE_CHECKS = SOURCE_DIR / "hard_checks.csv"

OUTPUT_DIR = ROOT / (
    "data/processed/milestone6/ranking_fairness_audit_v1/"
    "phase_6c_event_and_time_fairness"
)
OUTPUT_DB = OUTPUT_DIR / "ranking_fairness_audit_v1.duckdb"

INPUT_VERSION = "seasonal_development_rankings_v1_1"
DATASET_VERSION = "ranking_fairness_audit_v1"
EVENT_POINT_TARGET = 5000.0
MIN_SCHOOL_N = 30

EXPECTED_TRAJECTORIES = 189_703
EXPECTED_EVENTS = 30
EXPECTED_SCHOOLS = 361
EXPECTED_ATHLETE_SCHOOL_UNITS = 80_077


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_gate_passed(path: Path) -> bool:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return bool(rows) and all(row["status"] == "PASS" for row in rows)


def copy_csv(con: duckdb.DuckDBPyConnection, table: str, filename: str) -> None:
    path = (OUTPUT_DIR / filename).as_posix().replace("'", "''")
    con.execute(
        f"COPY (SELECT * FROM {table}) TO '{path}' "
        "(HEADER, DELIMITER ',')"
    )


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not SOURCE_DB.exists() or not SOURCE_CHECKS.exists():
        print("PHASE GATE: FAIL — Phase 6A inputs are missing.")
        return 1
    if not csv_gate_passed(SOURCE_CHECKS):
        print("PHASE GATE: FAIL — Phase 6A hard checks are not all PASS.")
        return 1

    before_hashes = {
        str(SOURCE_DB): sha256(SOURCE_DB),
        str(SOURCE_CHECKS): sha256(SOURCE_CHECKS),
    }

    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()

    con = duckdb.connect(str(OUTPUT_DB))
    source_path = SOURCE_DB.as_posix().replace("'", "''")
    con.execute(f"ATTACH '{source_path}' AS src (READ_ONLY)")
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA enable_progress_bar=false")

    metadata = dict(
        con.execute(
            "SELECT metadata_key, metadata_value "
            "FROM src.main.dataset_metadata"
        ).fetchall()
    )
    if metadata.get("dataset_version") != INPUT_VERSION:
        raise RuntimeError(
            "Unexpected Phase 6A version: "
            f"{metadata.get('dataset_version')!r}"
        )

    con.execute(
        "CREATE TABLE school_metadata AS "
        "SELECT * FROM src.main.school_metadata"
    )
    con.execute(
        "CREATE TABLE trajectories AS "
        "SELECT * FROM src.main.trajectory_snapshot"
    )

    # Exact Milestone 5 equal-family/equal-athlete trajectory weights.
    con.execute(
        """
        CREATE TABLE weighted_base AS
        WITH family_counts AS (
            SELECT
                canonical_person_id,
                resolved_school_id,
                COUNT(DISTINCT event_family) AS family_count
            FROM trajectories
            GROUP BY canonical_person_id, resolved_school_id
        ),
        family_rows AS (
            SELECT
                canonical_person_id,
                resolved_school_id,
                event_family,
                COUNT(*) AS rows_in_family
            FROM trajectories
            GROUP BY
                canonical_person_id,
                resolved_school_id,
                event_family
        )
        SELECT
            t.*,
            1.0 / f.family_count / r.rows_in_family
                AS current_effective_weight
        FROM trajectories t
        JOIN family_counts f
          USING (canonical_person_id, resolved_school_id)
        JOIN family_rows r
          USING (
            canonical_person_id,
            resolved_school_id,
            event_family
          )
        """
    )

    # Test 1: total influence by event, scaled to 5,000 average points.
    con.execute(
        f"""
        CREATE TABLE event_influence_audit AS
        WITH totals AS (
            SELECT
                canonical_event_code,
                ANY_VALUE(canonical_event_name) AS canonical_event_name,
                ANY_VALUE(event_family) AS event_family,
                COUNT(*) AS trajectory_count,
                COUNT(DISTINCT canonical_person_id)
                    AS distinct_athlete_count,
                COUNT(DISTINCT
                    canonical_person_id::VARCHAR || '|'
                    || resolved_school_id::VARCHAR
                ) AS athlete_school_count,
                SUM(current_effective_weight)
                    AS current_effective_vote_mass
            FROM weighted_base
            GROUP BY canonical_event_code
        ),
        target AS (
            SELECT
                SUM(current_effective_vote_mass) / COUNT(*)
                    AS equal_target_mass
            FROM totals
        )
        SELECT
            t.*,
            x.equal_target_mass,
            t.current_effective_vote_mass / x.equal_target_mass
                AS influence_ratio_to_equal,
            x.equal_target_mass / t.current_effective_vote_mass
                AS equalization_multiplier,
            {EVENT_POINT_TARGET}
                * t.current_effective_vote_mass / x.equal_target_mass
                AS current_scaled_influence_points,
            {EVENT_POINT_TARGET}::DOUBLE
                AS equalized_influence_points
        FROM totals t
        CROSS JOIN target x
        ORDER BY current_scaled_influence_points DESC
        """
    )

    con.execute(
        """
        CREATE TABLE weighted_trajectories AS
        SELECT
            b.*,
            a.equalization_multiplier,
            b.current_effective_weight * a.equalization_multiplier
                AS event_balanced_weight
        FROM weighted_base b
        JOIN event_influence_audit a USING (canonical_event_code)
        """
    )

    con.execute(
        f"""
        CREATE TABLE event_influence_by_season AS
        WITH totals AS (
            SELECT
                endpoint_season_year AS season_year,
                LOWER(season_type) AS season_type,
                canonical_event_code,
                ANY_VALUE(canonical_event_name) AS canonical_event_name,
                COUNT(*) AS trajectory_count,
                SUM(current_effective_weight) AS vote_mass
            FROM weighted_trajectories
            GROUP BY
                endpoint_season_year,
                LOWER(season_type),
                canonical_event_code
        ),
        targets AS (
            SELECT
                season_year,
                season_type,
                SUM(vote_mass) / COUNT(*) AS equal_target_mass,
                COUNT(*) AS represented_event_count
            FROM totals
            GROUP BY season_year, season_type
        )
        SELECT
            t.*,
            x.equal_target_mass,
            t.vote_mass / x.equal_target_mass
                AS influence_ratio_to_equal,
            {EVENT_POINT_TARGET}
                * t.vote_mass / x.equal_target_mass
                AS current_scaled_influence_points,
            {EVENT_POINT_TARGET}::DOUBLE
                AS equalized_influence_points,
            x.represented_event_count
        FROM totals t
        JOIN targets x USING (season_year, season_type)
        ORDER BY
            season_year,
            season_type,
            current_scaled_influence_points DESC
        """
    )

    con.execute(
        """
        CREATE TABLE event_balance_summary AS
        SELECT
            COUNT(*) AS event_count,
            SUM(current_effective_vote_mass)
                AS total_effective_vote_mass,
            AVG(current_scaled_influence_points)
                AS mean_scaled_points,
            MIN(current_scaled_influence_points)
                AS minimum_scaled_points,
            MAX(current_scaled_influence_points)
                AS maximum_scaled_points,
            MAX(current_scaled_influence_points)
                / MIN(current_scaled_influence_points)
                AS maximum_to_minimum_ratio,
            STDDEV_POP(current_scaled_influence_points)
                / AVG(current_scaled_influence_points)
                AS coefficient_of_variation
        FROM event_influence_audit
        """
    )

    # Test 2: event-year means and time-neutral value added.
    con.execute(
        """
        CREATE TABLE event_year_means AS
        SELECT
            endpoint_season_year AS season_year,
            LOWER(season_type) AS season_type,
            canonical_gender_code,
            canonical_event_code,
            ANY_VALUE(canonical_event_name) AS canonical_event_name,
            COUNT(*) AS trajectory_count,
            SUM(event_balanced_weight * athlete_value_added)
                / SUM(event_balanced_weight)
                AS mean_value_added,
            SUM(event_balanced_weight * observed_improvement)
                / SUM(event_balanced_weight)
                AS mean_observed_improvement,
            SUM(event_balanced_weight * expected_improvement)
                / SUM(event_balanced_weight)
                AS mean_expected_improvement,
            SUM(event_balanced_weight * baseline_stable_level)
                / SUM(event_balanced_weight)
                AS mean_baseline_level,
            SUM(event_balanced_weight * endpoint_stable_level)
                / SUM(event_balanced_weight)
                AS mean_endpoint_level
        FROM weighted_trajectories
        GROUP BY
            endpoint_season_year,
            LOWER(season_type),
            canonical_gender_code,
            canonical_event_code
        """
    )

    con.execute(
        """
        CREATE TABLE time_neutral_trajectories AS
        SELECT
            t.*,
            y.mean_value_added AS event_year_mean_value_added,
            t.athlete_value_added - y.mean_value_added
                AS time_neutral_value_added
        FROM weighted_trajectories t
        JOIN event_year_means y
          ON t.endpoint_season_year = y.season_year
         AND LOWER(t.season_type) = y.season_type
         AND t.canonical_gender_code = y.canonical_gender_code
         AND t.canonical_event_code = y.canonical_event_code
        """
    )

    con.execute(
        """
        CREATE TABLE temporal_drift_by_season AS
        SELECT
            endpoint_season_year AS season_year,
            LOWER(season_type) AS season_type,
            COUNT(*) AS trajectory_count,
            COUNT(DISTINCT canonical_person_id)
                AS distinct_athlete_count,
            COUNT(DISTINCT resolved_school_id)
                AS represented_school_count,
            SUM(current_effective_weight * athlete_value_added)
                / SUM(current_effective_weight)
                AS current_mean_value_added,
            SUM(event_balanced_weight * athlete_value_added)
                / SUM(event_balanced_weight)
                AS event_balanced_mean_value_added,
            SUM(event_balanced_weight * time_neutral_value_added)
                / SUM(event_balanced_weight)
                AS time_neutral_mean_value_added,
            SUM(event_balanced_weight * observed_improvement)
                / SUM(event_balanced_weight)
                AS mean_observed_improvement,
            SUM(event_balanced_weight * expected_improvement)
                / SUM(event_balanced_weight)
                AS mean_expected_improvement,
            SUM(event_balanced_weight * baseline_stable_level)
                / SUM(event_balanced_weight)
                AS mean_baseline_level,
            SUM(event_balanced_weight * endpoint_stable_level)
                / SUM(event_balanced_weight)
                AS mean_endpoint_level
        FROM time_neutral_trajectories
        GROUP BY endpoint_season_year, LOWER(season_type)
        ORDER BY season_year, season_type
        """
    )

    con.execute(
        """
        CREATE TABLE temporal_trend_summary AS
        SELECT
            season_type,
            COUNT(*) AS season_count,
            REGR_SLOPE(current_mean_value_added, season_year)
                AS current_value_added_slope_per_year,
            REGR_SLOPE(event_balanced_mean_value_added, season_year)
                AS event_balanced_value_added_slope_per_year,
            REGR_SLOPE(mean_observed_improvement, season_year)
                AS observed_improvement_slope_per_year,
            REGR_SLOPE(mean_expected_improvement, season_year)
                AS expected_improvement_slope_per_year,
            REGR_SLOPE(mean_baseline_level, season_year)
                AS baseline_level_slope_per_year,
            REGR_SLOPE(mean_endpoint_level, season_year)
                AS endpoint_level_slope_per_year,
            CORR(current_mean_value_added, season_year)
                AS current_value_added_year_correlation,
            CORR(event_balanced_mean_value_added, season_year)
                AS balanced_value_added_year_correlation
        FROM temporal_drift_by_season
        GROUP BY season_type
        ORDER BY season_type
        """
    )

    # School ranking counterfactuals.
    con.execute(
        """
        CREATE TABLE school_score_variants AS
        SELECT
            resolved_school_id,
            COUNT(DISTINCT canonical_person_id)
                AS athlete_count,
            COUNT(DISTINCT canonical_event_code)
                AS represented_event_count,
            SUM(current_effective_weight * athlete_value_added)
                / SUM(current_effective_weight)
                AS current_score,
            SUM(event_balanced_weight * athlete_value_added)
                / SUM(event_balanced_weight)
                AS event_balanced_score,
            SUM(event_balanced_weight * time_neutral_value_added)
                / SUM(event_balanced_weight)
                AS event_and_time_neutral_score
        FROM time_neutral_trajectories
        GROUP BY resolved_school_id
        """
    )

    con.execute(
        f"""
        CREATE TABLE school_ranking_robustness AS
        WITH eligible AS (
            SELECT
                s.*,
                m.school_name,
                m.conference_name
            FROM school_score_variants s
            JOIN school_metadata m USING (resolved_school_id)
            WHERE s.athlete_count >= {MIN_SCHOOL_N}
        ),
        ranked AS (
            SELECT
                *,
                RANK() OVER (ORDER BY current_score DESC)
                    AS current_rank,
                RANK() OVER (ORDER BY event_balanced_score DESC)
                    AS event_balanced_rank,
                RANK() OVER (
                    ORDER BY event_and_time_neutral_score DESC
                ) AS event_and_time_neutral_rank
            FROM eligible
        )
        SELECT
            *,
            event_balanced_rank - current_rank
                AS event_balance_rank_shift,
            event_and_time_neutral_rank - current_rank
                AS event_and_time_rank_shift,
            ABS(event_balanced_rank - current_rank)
                AS absolute_event_balance_rank_shift,
            ABS(event_and_time_neutral_rank - current_rank)
                AS absolute_event_and_time_rank_shift
        FROM ranked
        ORDER BY current_rank
        """
    )

    con.execute(
        """
        CREATE TABLE ranking_robustness_summary AS
        SELECT
            COUNT(*) AS eligible_school_count,
            CORR(current_rank, event_balanced_rank)
                AS event_balanced_rank_correlation,
            CORR(current_rank, event_and_time_neutral_rank)
                AS time_neutral_rank_correlation,
            AVG(absolute_event_balance_rank_shift)
                AS mean_absolute_event_balance_rank_shift,
            MEDIAN(absolute_event_balance_rank_shift)
                AS median_event_balance_rank_shift,
            MAX(absolute_event_balance_rank_shift)
                AS maximum_event_balance_rank_shift,
            AVG(absolute_event_and_time_rank_shift)
                AS mean_absolute_event_and_time_rank_shift,
            MEDIAN(absolute_event_and_time_rank_shift)
                AS median_event_and_time_rank_shift,
            MAX(absolute_event_and_time_rank_shift)
                AS maximum_event_and_time_rank_shift
        FROM school_ranking_robustness
        """
    )

    con.execute(
        """
        CREATE TABLE ranking_top_overlap AS
        WITH thresholds(rank_threshold) AS (
            VALUES (10), (25), (50), (100)
        ),
        counts AS (
            SELECT
                t.rank_threshold,
                COUNT(*) FILTER (
                    WHERE r.current_rank <= t.rank_threshold
                ) AS current_count,
                COUNT(*) FILTER (
                    WHERE r.current_rank <= t.rank_threshold
                      AND r.event_balanced_rank <= t.rank_threshold
                ) AS event_balanced_overlap_count,
                COUNT(*) FILTER (
                    WHERE r.current_rank <= t.rank_threshold
                      AND r.event_and_time_neutral_rank
                            <= t.rank_threshold
                ) AS time_neutral_overlap_count
            FROM school_ranking_robustness r
            CROSS JOIN thresholds t
            GROUP BY t.rank_threshold
        )
        SELECT
            *,
            event_balanced_overlap_count::DOUBLE
                / current_count AS event_balanced_overlap_share,
            time_neutral_overlap_count::DOUBLE
                / current_count AS time_neutral_overlap_share
        FROM counts
        ORDER BY rank_threshold
        """
    )

    # Hard checks.
    checks = []
    trajectory_count = con.execute(
        "SELECT COUNT(*) FROM trajectories"
    ).fetchone()[0]
    event_count = con.execute(
        "SELECT COUNT(*) FROM event_influence_audit"
    ).fetchone()[0]
    school_count = con.execute(
        "SELECT COUNT(*) FROM school_metadata"
    ).fetchone()[0]
    athlete_school_count = con.execute(
        """
        SELECT COUNT(DISTINCT
            canonical_person_id::VARCHAR || '|'
            || resolved_school_id::VARCHAR)
        FROM trajectories
        """
    ).fetchone()[0]
    weight_sum = con.execute(
        "SELECT SUM(current_effective_weight) FROM weighted_base"
    ).fetchone()[0]
    max_center_error = con.execute(
        """
        SELECT MAX(ABS(cell_mean))
        FROM (
            SELECT
                endpoint_season_year,
                LOWER(season_type),
                canonical_gender_code,
                canonical_event_code,
                SUM(event_balanced_weight * time_neutral_value_added)
                    / SUM(event_balanced_weight) AS cell_mean
            FROM time_neutral_trajectories
            GROUP BY
                endpoint_season_year,
                LOWER(season_type),
                canonical_gender_code,
                canonical_event_code
        )
        """
    ).fetchone()[0]

    def add(name: str, passed: bool, observed: Any, expected: Any) -> None:
        checks.append((name, "PASS" if passed else "FAIL", observed, expected))

    add(
        "trajectory_row_count",
        trajectory_count == EXPECTED_TRAJECTORIES,
        trajectory_count,
        EXPECTED_TRAJECTORIES,
    )
    add(
        "canonical_event_count",
        event_count == EXPECTED_EVENTS,
        event_count,
        EXPECTED_EVENTS,
    )
    add(
        "school_metadata_count",
        school_count == EXPECTED_SCHOOLS,
        school_count,
        EXPECTED_SCHOOLS,
    )
    add(
        "athlete_school_unit_count",
        athlete_school_count == EXPECTED_ATHLETE_SCHOOL_UNITS,
        athlete_school_count,
        EXPECTED_ATHLETE_SCHOOL_UNITS,
    )
    add(
        "weights_sum_to_athlete_school_units",
        abs(weight_sum - EXPECTED_ATHLETE_SCHOOL_UNITS) < 1e-6,
        weight_sum,
        EXPECTED_ATHLETE_SCHOOL_UNITS,
    )
    add(
        "event_year_centering_exact",
        max_center_error < 1e-9,
        max_center_error,
        "< 1e-9",
    )

    con.execute(
        """
        CREATE TABLE hard_checks (
            check_name VARCHAR,
            status VARCHAR,
            observed VARCHAR,
            expected VARCHAR
        )
        """
    )
    con.executemany(
        "INSERT INTO hard_checks VALUES (?, ?, ?, ?)",
        [(a, b, str(c), str(d)) for a, b, c, d in checks],
    )

    con.execute(
        f"""
        CREATE TABLE dataset_metadata AS
        SELECT 'dataset_version' AS metadata_key,
               '{DATASET_VERSION}' AS metadata_value
        UNION ALL SELECT 'input_version', '{INPUT_VERSION}'
        UNION ALL SELECT 'event_point_target', '{EVENT_POINT_TARGET}'
        UNION ALL SELECT 'minimum_school_n', '{MIN_SCHOOL_N}'
        """
    )

    for table, filename in [
        ("event_influence_audit", "event_influence_audit.csv"),
        ("event_influence_by_season", "event_influence_by_season.csv"),
        ("event_balance_summary", "event_balance_summary.csv"),
        ("temporal_drift_by_season", "temporal_drift_by_season.csv"),
        ("event_year_means", "temporal_drift_by_event_year.csv"),
        ("temporal_trend_summary", "temporal_trend_summary.csv"),
        ("school_ranking_robustness", "school_ranking_robustness.csv"),
        ("ranking_robustness_summary", "ranking_robustness_summary.csv"),
        ("ranking_top_overlap", "ranking_top_overlap.csv"),
        ("hard_checks", "hard_checks.csv"),
    ]:
        copy_csv(con, table, filename)

    balance = con.execute(
        "SELECT * FROM event_balance_summary"
    ).fetchone()
    robustness = con.execute(
        "SELECT * FROM ranking_robustness_summary"
    ).fetchone()
    trend_rows = con.execute(
        "SELECT * FROM temporal_trend_summary"
    ).fetchall()

    balance_cols = [
        item[0]
        for item in con.execute(
            "SELECT * FROM event_balance_summary"
        ).description
    ]
    robustness_cols = [
        item[0]
        for item in con.execute(
            "SELECT * FROM ranking_robustness_summary"
        ).description
    ]
    trend_cols = [
        item[0]
        for item in con.execute(
            "SELECT * FROM temporal_trend_summary"
        ).description
    ]

    balance_d = dict(zip(balance_cols, balance))
    robust_d = dict(zip(robustness_cols, robustness))
    trends = [dict(zip(trend_cols, row)) for row in trend_rows]

    con.close()

    after_hashes = {
        str(SOURCE_DB): sha256(SOURCE_DB),
        str(SOURCE_CHECKS): sha256(SOURCE_CHECKS),
    }
    inputs_unchanged = before_hashes == after_hashes

    with (OUTPUT_DIR / "input_manifest.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["path", "sha256_before", "sha256_after", "unchanged"]
        )
        for path in required_inputs:
            key = str(path)
            writer.writerow(
                [
                    key,
                    before_hashes[key],
                    after_hashes[key],
                    before_hashes[key] == after_hashes[key],
                ]
            )

    failed = [row for row in checks if row[1] != "PASS"]
    if not inputs_unchanged:
        failed.append(
            ("all_inputs_unchanged", "FAIL", after_hashes, before_hashes)
        )

    report = [
        "MILESTONE 6 PHASE 6C — EVENT BALANCE AND TEMPORAL FAIRNESS AUDIT",
        "=" * 78,
        "",
        "EVENT INFLUENCE",
        "-" * 78,
        f"Events: {balance_d['event_count']}",
        f"Average points: {balance_d['mean_scaled_points']:.2f}",
        f"Minimum points: {balance_d['minimum_scaled_points']:.2f}",
        f"Maximum points: {balance_d['maximum_scaled_points']:.2f}",
        f"Maximum/minimum ratio: "
        f"{balance_d['maximum_to_minimum_ratio']:.3f}",
        f"Coefficient of variation: "
        f"{balance_d['coefficient_of_variation']:.3f}",
        "",
        "RANK ROBUSTNESS",
        "-" * 78,
        f"Eligible schools: {robust_d['eligible_school_count']}",
        f"Current vs event-balanced rank correlation: "
        f"{robust_d['event_balanced_rank_correlation']:.6f}",
        f"Current vs event+time-neutral rank correlation: "
        f"{robust_d['time_neutral_rank_correlation']:.6f}",
        f"Mean absolute event-balance shift: "
        f"{robust_d['mean_absolute_event_balance_rank_shift']:.3f}",
        f"Mean absolute event+time shift: "
        f"{robust_d['mean_absolute_event_and_time_rank_shift']:.3f}",
        "",
        "TEMPORAL SLOPES",
        "-" * 78,
    ]
    for row in trends:
        report.extend(
            [
                f"{row['season_type'].title()}:",
                f"  Current VA slope/year: "
                f"{row['current_value_added_slope_per_year']:.6f}",
                f"  Event-balanced VA slope/year: "
                f"{row['event_balanced_value_added_slope_per_year']:.6f}",
                f"  Baseline-level slope/year: "
                f"{row['baseline_level_slope_per_year']:.6f}",
                f"  Endpoint-level slope/year: "
                f"{row['endpoint_level_slope_per_year']:.6f}",
            ]
        )
    report.extend(
        [
            "",
            "PHASE GATE",
            "-" * 78,
            "PASS" if not failed else "FAIL",
        ]
    )
    (OUTPUT_DIR / "phase_6c_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(
        "Event influence range: "
        f"{balance_d['minimum_scaled_points']:.1f}–"
        f"{balance_d['maximum_scaled_points']:.1f}"
    )
    print(
        "Current vs event-balanced rank correlation: "
        f"{robust_d['event_balanced_rank_correlation']:.6f}"
    )
    print(
        "Current vs event+time-neutral rank correlation: "
        f"{robust_d['time_neutral_rank_correlation']:.6f}"
    )

    if failed:
        print("PHASE GATE: FAIL")
        for row in failed:
            print(row)
        return 1

    print("PHASE GATE: PASS")
    print(f"Output: {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
