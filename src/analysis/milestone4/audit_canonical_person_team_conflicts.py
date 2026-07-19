#!/usr/bin/env python3
"""
Milestone 4: audit canonical-person performance team conflicts.

Reads the failed canonical-person v1.0 output in read-only mode and summarizes
why exact duplicate performances for one provisional person received different
canonical-team assignments.

This script does not modify or rebuild any database.

Outputs
-------
data/processed/milestone4/canonical_person_team_conflict_audit/
    conflict_audit_report.txt
    hard_checks.csv
    team_count_summary.csv
    attribution_pattern_summary.csv
    evidence_resolution_summary.csv
    conflict_group_summary.csv
    person_conflict_summary.csv
    top_conflict_people.csv
    conflict_detail_sample.csv
    known_person_conflicts.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]

PERSON_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_person_layer/"
    / "canonical_person_layer.duckdb"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_person_team_conflict_audit"
)

AUDIT_VERSION = (
    "m4_canonical_person_team_conflict_audit_v1.0"
)

EXPECTED_CONFLICT_GROUPS = 35_694
EXPECTED_MAP_ROWS = 6_474_538
EXPECTED_DEDUP_ROWS = 6_376_667

KNOWN_PROFILE_IDS = [
    "6550332",
    "7905593",
    "7913457",
    "8932241",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--replace-output",
        action="store_true",
    )

    return parser.parse_args()


def sql_path(path: Path) -> str:
    return (
        path.resolve()
        .as_posix()
        .replace("'", "''")
    )


def prepare_output(
    replace_output: bool,
) -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    generated = [
        OUTPUT_DIR / "conflict_audit_report.txt",
        OUTPUT_DIR / "hard_checks.csv",
        OUTPUT_DIR / "team_count_summary.csv",
        OUTPUT_DIR / "attribution_pattern_summary.csv",
        OUTPUT_DIR / "evidence_resolution_summary.csv",
        OUTPUT_DIR / "conflict_group_summary.csv",
        OUTPUT_DIR / "person_conflict_summary.csv",
        OUTPUT_DIR / "top_conflict_people.csv",
        OUTPUT_DIR / "conflict_detail_sample.csv",
        OUTPUT_DIR / "known_person_conflicts.csv",
    ]

    existing = [
        path
        for path in generated
        if path.exists()
    ]

    if existing and not replace_output:
        raise FileExistsError(
            "Conflict-audit outputs already exist. "
            "Use --replace-output only after reviewing "
            "the current files."
        )

    if replace_output:
        for path in existing:
            path.unlink()


def scalar(
    con: duckdb.DuckDBPyConnection,
    query: str,
) -> int:
    return int(
        con.execute(query).fetchone()[0]
    )


def main() -> None:
    args = parse_args()

    if not PERSON_DB.exists():
        raise FileNotFoundError(
            f"Canonical-person database not found: "
            f"{PERSON_DB}"
        )

    prepare_output(
        replace_output=args.replace_output,
    )

    con = duckdb.connect()

    try:
        con.execute("PRAGMA threads=4")
        con.execute(
            f"""
            ATTACH '{sql_path(PERSON_DB)}'
            AS person
            (READ_ONLY)
            """
        )

        print(
            "Building conflicting person-performance "
            "group summary..."
        )

        con.execute(
            """
            CREATE TEMP TABLE conflict_ids AS
            SELECT
                canonical_person_performance_id
            FROM person.canonical_person_performance_map
            GROUP BY canonical_person_performance_id
            HAVING COUNT(
                DISTINCT canonical_team_id
            ) > 1
            """
        )

        con.execute(
            """
            CREATE TEMP TABLE conflict_rows AS
            SELECT
                m.*,

                CASE m.attribution_precedence
                    WHEN 'PERFORMANCE_LEVEL_OVERRIDE'
                    THEN 1
                    WHEN 'RESULT_PAGE_SOURCE_FALLBACK'
                    THEN 2
                    WHEN 'CANONICAL_PROFILE_SECTION'
                    THEN 3
                    WHEN 'TRANSFER_FINAL_TEAM'
                    THEN 4
                    WHEN 'ORIGINAL_SOURCE_TEAM'
                    THEN 5
                    ELSE 9
                END AS evidence_rank

            FROM person
                .canonical_person_performance_map m

            JOIN conflict_ids c
              ON m.canonical_person_performance_id
                    =
                    c.canonical_person_performance_id
            """
        )

        con.execute(
            """
            CREATE TEMP TABLE conflict_team_evidence AS
            SELECT
                canonical_person_id,
                canonical_person_performance_id,
                canonical_team_id,
                canonical_school_id,
                canonical_school_name,

                MIN(evidence_rank)
                    AS best_evidence_rank,

                COUNT(*) AS source_row_count,

                COUNT(
                    DISTINCT athlete_id
                ) AS source_profile_count,

                STRING_AGG(
                    DISTINCT attribution_precedence,
                    ' | '
                    ORDER BY attribution_precedence
                ) AS attribution_precedences,

                STRING_AGG(
                    DISTINCT attribution_method,
                    ' | '
                    ORDER BY attribution_method
                ) AS attribution_methods,

                STRING_AGG(
                    DISTINCT evidence_source,
                    ' | '
                    ORDER BY evidence_source
                ) AS evidence_sources,

                SUM(
                    CASE
                        WHEN source_team_id
                            = canonical_team_id
                        THEN 1
                        ELSE 0
                    END
                ) AS rows_matching_source_team,

                SUM(
                    CASE
                        WHEN affiliation_id
                            IS NOT NULL
                        THEN 1
                        ELSE 0
                    END
                ) AS rows_with_affiliation

            FROM conflict_rows

            GROUP BY
                canonical_person_id,
                canonical_person_performance_id,
                canonical_team_id,
                canonical_school_id,
                canonical_school_name
            """
        )

        con.execute(
            """
            CREATE TEMP TABLE conflict_group_summary AS
            WITH group_base AS (
                SELECT
                    canonical_person_id,
                    canonical_person_performance_id,

                    COUNT(*) AS source_row_count,

                    COUNT(
                        DISTINCT athlete_id
                    ) AS source_profile_count,

                    COUNT(
                        DISTINCT canonical_team_id
                    ) AS canonical_team_count,

                    COUNT(
                        DISTINCT NULLIF(
                            source_team_id,
                            ''
                        )
                    ) AS nonblank_source_team_count,

                    COUNT(
                        DISTINCT attribution_precedence
                    ) AS attribution_precedence_count,

                    COUNT(
                        DISTINCT attribution_method
                    ) AS attribution_method_count,

                    MIN(evidence_rank)
                        AS best_evidence_rank,

                    STRING_AGG(
                        DISTINCT athlete_id,
                        ' | '
                        ORDER BY athlete_id
                    ) AS athlete_ids,

                    STRING_AGG(
                        DISTINCT canonical_team_id,
                        ' | '
                        ORDER BY canonical_team_id
                    ) AS canonical_team_ids,

                    STRING_AGG(
                        DISTINCT canonical_school_name,
                        ' | '
                        ORDER BY canonical_school_name
                    ) AS canonical_school_names,

                    STRING_AGG(
                        DISTINCT NULLIF(
                            source_team_id,
                            ''
                        ),
                        ' | '
                        ORDER BY NULLIF(
                            source_team_id,
                            ''
                        )
                    ) AS source_team_ids,

                    STRING_AGG(
                        DISTINCT NULLIF(
                            source_school,
                            ''
                        ),
                        ' | '
                        ORDER BY NULLIF(
                            source_school,
                            ''
                        )
                    ) AS source_schools,

                    STRING_AGG(
                        DISTINCT attribution_precedence,
                        ' | '
                        ORDER BY attribution_precedence
                    ) AS attribution_precedences,

                    STRING_AGG(
                        DISTINCT attribution_method,
                        ' | '
                        ORDER BY attribution_method
                    ) AS attribution_methods,

                    MIN(athlete_name)
                        AS athlete_name,

                    MIN(season_id)
                        AS season_id,

                    MIN(season_year)
                        AS season_year,

                    MIN(season_type)
                        AS season_type,

                    MIN(meet_id)
                        AS meet_id,

                    MIN(meet_name)
                        AS meet_name,

                    MIN(meet_date_text)
                        AS meet_date_text,

                    MIN(event)
                        AS event,

                    MIN(mark)
                        AS mark,

                    MIN(place)
                        AS place,

                    MIN(result_url)
                        AS result_url

                FROM conflict_rows

                GROUP BY
                    canonical_person_id,
                    canonical_person_performance_id
            ),

            best_team_counts AS (
                SELECT
                    canonical_person_id,
                    canonical_person_performance_id,

                    MIN(best_evidence_rank)
                        AS best_evidence_rank,

                    COUNT(*)
                        FILTER (
                            WHERE best_evidence_rank
                                = group_min_rank
                        )
                        AS teams_at_best_rank

                FROM (
                    SELECT
                        e.*,

                        MIN(best_evidence_rank)
                            OVER (
                                PARTITION BY
                                    canonical_person_id,
                                    canonical_person_performance_id
                            ) AS group_min_rank

                    FROM conflict_team_evidence e
                )

                GROUP BY
                    canonical_person_id,
                    canonical_person_performance_id
            ),

            source_match AS (
                SELECT
                    canonical_person_id,
                    canonical_person_performance_id,

                    COUNT(*)
                        FILTER (
                            WHERE rows_matching_source_team
                                > 0
                        )
                        AS canonical_teams_matching_source,

                    SUM(rows_matching_source_team)
                        AS total_rows_matching_source,

                    SUM(rows_with_affiliation)
                        AS rows_with_affiliation

                FROM conflict_team_evidence

                GROUP BY
                    canonical_person_id,
                    canonical_person_performance_id
            )

            SELECT
                g.*,
                b.teams_at_best_rank,
                s.canonical_teams_matching_source,
                s.total_rows_matching_source,
                s.rows_with_affiliation,

                CASE
                    WHEN b.teams_at_best_rank = 1
                    THEN
                        'UNIQUE_BEST_ATTRIBUTION_EVIDENCE'

                    WHEN
                        s.canonical_teams_matching_source
                            = 1
                    THEN
                        'UNIQUE_CANONICAL_TEAM_MATCHES_SOURCE'

                    WHEN
                        g.nonblank_source_team_count
                            = 1
                    THEN
                        'ONE_SOURCE_TEAM_BUT_NO_UNIQUE_MATCH'

                    WHEN
                        g.nonblank_source_team_count
                            = 0
                    THEN
                        'NO_SOURCE_TEAM_EVIDENCE'

                    ELSE
                        'AMBIGUOUS_MULTIPLE_EVIDENCE'
                END AS evidence_resolution_class

            FROM group_base g

            JOIN best_team_counts b
              USING (
                canonical_person_id,
                canonical_person_performance_id
              )

            JOIN source_match s
              USING (
                canonical_person_id,
                canonical_person_performance_id
              )
            """
        )

        group_summary = con.execute(
            """
            SELECT *
            FROM conflict_group_summary
            ORDER BY
                evidence_resolution_class,
                canonical_team_count DESC,
                source_profile_count DESC,
                canonical_person_id,
                canonical_person_performance_id
            """
        ).fetchdf()

        print(
            "Building conflict pattern summaries..."
        )

        team_count_summary = con.execute(
            """
            SELECT
                canonical_team_count,
                COUNT(*) AS conflict_group_count,
                SUM(source_row_count)
                    AS source_row_count,
                COUNT(
                    DISTINCT canonical_person_id
                ) AS canonical_person_count

            FROM conflict_group_summary

            GROUP BY canonical_team_count

            ORDER BY canonical_team_count
            """
        ).fetchdf()

        attribution_pattern_summary = con.execute(
            """
            SELECT
                attribution_precedences,
                attribution_methods,
                COUNT(*) AS conflict_group_count,
                SUM(source_row_count)
                    AS source_row_count,
                COUNT(
                    DISTINCT canonical_person_id
                ) AS canonical_person_count

            FROM conflict_group_summary

            GROUP BY
                attribution_precedences,
                attribution_methods

            ORDER BY
                conflict_group_count DESC,
                attribution_precedences,
                attribution_methods
            """
        ).fetchdf()

        evidence_resolution_summary = con.execute(
            """
            SELECT
                evidence_resolution_class,
                COUNT(*) AS conflict_group_count,
                SUM(source_row_count)
                    AS source_row_count,
                COUNT(
                    DISTINCT canonical_person_id
                ) AS canonical_person_count,

                SUM(
                    CASE
                        WHEN rows_with_affiliation > 0
                        THEN 1
                        ELSE 0
                    END
                ) AS groups_with_affiliation_evidence

            FROM conflict_group_summary

            GROUP BY evidence_resolution_class

            ORDER BY
                conflict_group_count DESC,
                evidence_resolution_class
            """
        ).fetchdf()

        person_conflict_summary = con.execute(
            """
            SELECT
                g.canonical_person_id,
                p.profile_count,
                p.athlete_ids,
                p.athlete_names,
                p.current_school_names,
                p.current_team_ids,
                p.normalized_name,
                p.dominant_gender_code,

                COUNT(*)
                    AS conflict_group_count,

                SUM(g.source_row_count)
                    AS conflicting_source_rows,

                COUNT(
                    DISTINCT g.canonical_team_ids
                ) AS distinct_team_set_count,

                MIN(g.season_year)
                    AS first_conflict_year,

                MAX(g.season_year)
                    AS last_conflict_year

            FROM conflict_group_summary g

            JOIN person.canonical_people p
              ON g.canonical_person_id
                    = p.canonical_person_id

            GROUP BY
                g.canonical_person_id,
                p.profile_count,
                p.athlete_ids,
                p.athlete_names,
                p.current_school_names,
                p.current_team_ids,
                p.normalized_name,
                p.dominant_gender_code

            ORDER BY
                conflict_group_count DESC,
                conflicting_source_rows DESC,
                g.canonical_person_id
            """
        ).fetchdf()

        top_conflict_people = (
            person_conflict_summary
            .head(100)
            .copy()
        )

        detail_sample = con.execute(
            """
            SELECT
                r.canonical_person_id,
                r.canonical_person_performance_id,
                r.performance_id,
                r.athlete_id,
                r.athlete_name,
                r.season_id,
                r.meet_id,
                r.meet_name,
                r.meet_date_text,
                r.event,
                r.mark,
                r.place,
                r.source_school,
                r.source_team_id,
                r.affiliation_id,
                r.canonical_team_id,
                r.canonical_school_name,
                r.attribution_precedence,
                r.attribution_method,
                r.attribution_confidence,
                r.evidence_source,
                g.evidence_resolution_class

            FROM conflict_rows r

            JOIN conflict_group_summary g
              USING (
                canonical_person_id,
                canonical_person_performance_id
              )

            WHERE r.canonical_person_id IN (
                SELECT canonical_person_id
                FROM (
                    SELECT
                        canonical_person_id,
                        COUNT(*) AS conflict_count
                    FROM conflict_group_summary
                    GROUP BY canonical_person_id
                    ORDER BY conflict_count DESC
                    LIMIT 25
                )
            )

            ORDER BY
                r.canonical_person_id,
                r.season_year,
                r.season_id,
                r.meet_id,
                r.event,
                r.performance_id

            LIMIT 2_000
            """
        ).fetchdf()

        known_ids_df = pd.DataFrame(
            {
                "athlete_id": KNOWN_PROFILE_IDS
            }
        )

        con.register(
            "known_ids",
            known_ids_df,
        )

        known_conflicts = con.execute(
            """
            WITH known_people AS (
                SELECT DISTINCT
                    b.canonical_person_id

                FROM person
                    .canonical_person_bridge b

                JOIN known_ids k
                  ON b.athlete_id = k.athlete_id
            )
            SELECT
                g.*

            FROM conflict_group_summary g

            JOIN known_people k
              ON g.canonical_person_id
                    = k.canonical_person_id

            ORDER BY
                g.canonical_person_id,
                g.season_year,
                g.season_id,
                g.meet_id,
                g.event
            """
        ).fetchdf()

        group_summary.to_csv(
            OUTPUT_DIR
            / "conflict_group_summary.csv",
            index=False,
        )

        team_count_summary.to_csv(
            OUTPUT_DIR
            / "team_count_summary.csv",
            index=False,
        )

        attribution_pattern_summary.to_csv(
            OUTPUT_DIR
            / "attribution_pattern_summary.csv",
            index=False,
        )

        evidence_resolution_summary.to_csv(
            OUTPUT_DIR
            / "evidence_resolution_summary.csv",
            index=False,
        )

        person_conflict_summary.to_csv(
            OUTPUT_DIR
            / "person_conflict_summary.csv",
            index=False,
        )

        top_conflict_people.to_csv(
            OUTPUT_DIR
            / "top_conflict_people.csv",
            index=False,
        )

        detail_sample.to_csv(
            OUTPUT_DIR
            / "conflict_detail_sample.csv",
            index=False,
        )

        known_conflicts.to_csv(
            OUTPUT_DIR
            / "known_person_conflicts.csv",
            index=False,
        )

        conflict_groups = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM conflict_ids
            """,
        )

        conflict_source_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM conflict_rows
            """,
        )

        conflict_people = scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT canonical_person_id
            )
            FROM conflict_rows
            """,
        )

        map_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM person
                .canonical_person_performance_map
            """,
        )

        dedup_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM person
                .canonical_person_performances
            """,
        )

        blank_team_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM conflict_rows
            WHERE NULLIF(
                canonical_team_id,
                ''
            ) IS NULL
            """,
        )

        conflict_groups_recount = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM conflict_group_summary
            """,
        )

        detail_groups_missing = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM conflict_ids c
            LEFT JOIN conflict_group_summary g
              USING (
                canonical_person_performance_id
              )
            WHERE
                g.canonical_person_performance_id
                    IS NULL
            """,
        )

        checks = pd.DataFrame(
            [
                (
                    "person_performance_map_rows",
                    abs(
                        map_rows
                        - EXPECTED_MAP_ROWS
                    ),
                    map_rows,
                    EXPECTED_MAP_ROWS,
                ),
                (
                    "deduplicated_person_performance_rows",
                    abs(
                        dedup_rows
                        - EXPECTED_DEDUP_ROWS
                    ),
                    dedup_rows,
                    EXPECTED_DEDUP_ROWS,
                ),
                (
                    "expected_conflict_groups",
                    abs(
                        conflict_groups
                        - EXPECTED_CONFLICT_GROUPS
                    ),
                    conflict_groups,
                    EXPECTED_CONFLICT_GROUPS,
                ),
                (
                    "conflict_group_summary_rows",
                    abs(
                        conflict_groups_recount
                        - conflict_groups
                    ),
                    conflict_groups_recount,
                    conflict_groups,
                ),
                (
                    "conflict_groups_missing_from_summary",
                    detail_groups_missing,
                    detail_groups_missing,
                    0,
                ),
                (
                    "blank_canonical_team_rows_in_conflicts",
                    blank_team_rows,
                    blank_team_rows,
                    0,
                ),
            ],
            columns=[
                "check_name",
                "failed_row_count",
                "observed_value",
                "expected_value",
            ],
        )

        checks.to_csv(
            OUTPUT_DIR / "hard_checks.csv",
            index=False,
        )

        failed = int(
            (
                checks["failed_row_count"] > 0
            ).sum()
        )

        unique_best_groups = int(
            group_summary[
                "evidence_resolution_class"
            ].eq(
                "UNIQUE_BEST_ATTRIBUTION_EVIDENCE"
            ).sum()
        )

        unique_source_match_groups = int(
            group_summary[
                "evidence_resolution_class"
            ].eq(
                "UNIQUE_CANONICAL_TEAM_MATCHES_SOURCE"
            ).sum()
        )

        ambiguous_groups = int(
            group_summary[
                "evidence_resolution_class"
            ].isin(
                [
                    "ONE_SOURCE_TEAM_BUT_NO_UNIQUE_MATCH",
                    "NO_SOURCE_TEAM_EVIDENCE",
                    "AMBIGUOUS_MULTIPLE_EVIDENCE",
                ]
            ).sum()
        )

        report = f"""MILESTONE 4 CANONICAL-PERSON TEAM-CONFLICT AUDIT
============================================================
Audit version: {AUDIT_VERSION}
Canonical-person database modified: no
Source or attribution databases modified: no
Correction rules applied: no

SCOPE
- Canonical-person performance map rows:
  {map_rows:,}
- Deduplicated person-performance rows:
  {dedup_rows:,}
- Conflicting person-performance groups:
  {conflict_groups:,}
- Source rows inside conflict groups:
  {conflict_source_rows:,}
- Canonical people affected:
  {conflict_people:,}

EVIDENCE CLASSIFICATION
- Groups with one uniquely strongest attribution team:
  {unique_best_groups:,}
- Additional groups with one canonical team matching source:
  {unique_source_match_groups:,}
- Groups still requiring deeper evidence:
  {ambiguous_groups:,}

KNOWN VALIDATION PEOPLE
- Conflict rows for Emily Venters and Daniella Hubble:
  {len(known_conflicts):,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

INTERPRETATION
This audit does not select final schools. It determines whether duplicate
profile rows disagree because one profile has stronger attribution evidence,
because one team uniquely agrees with source evidence, or because the group
remains genuinely ambiguous. Only after reviewing these distributions should
the canonical-person layer be rebuilt with explicit conflict-resolution rules.
"""

        (
            OUTPUT_DIR
            / "conflict_audit_report.txt"
        ).write_text(
            report,
            encoding="utf-8",
        )

        print(
            "Canonical-person team-conflict audit "
            "complete."
        )
        print(f"Outputs: {OUTPUT_DIR}")
        print(f"Failed checks: {failed:,}.")
        print(
            "Conflict groups: "
            f"{conflict_groups:,}"
        )
        print(
            "Canonical people affected: "
            f"{conflict_people:,}"
        )

        if failed:
            raise SystemExit(1)

    finally:
        try:
            con.unregister("known_ids")
        except Exception:
            pass

        con.close()


if __name__ == "__main__":
    main()
