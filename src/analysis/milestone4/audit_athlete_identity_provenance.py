#!/usr/bin/env python3
"""
Milestone 4 athlete identity and transfer provenance audit.

Read-only with respect to the production DuckDB database. The script only
writes CSV/text reports under data/processed/milestone4/.

Purpose
-------
The current database shows:
- roster-derived affiliations may contain multiple schools per athlete;
- performance.team_id assigns only one school to every athlete_id;
- exact affiliation links agree perfectly with performance.team_id.

This audit traces a sample of multi-school roster athlete IDs back through:
- core.athletes
- core.athlete_affiliations
- core.performances
- data/raw/historical_rosters/all_roster_records.csv
- data/raw/historical_rosters/unique_athletes.csv
- saved athlete-page HTML files

It helps determine whether:
1. TFRRS athlete IDs remain stable across transfers;
2. historical roster parsing created spurious affiliations;
3. unique-athlete deduplication selected one team per athlete;
4. performance parsing propagated that one team across all seasons.

Run from repository root:
    python src/analysis/milestone4/audit_athlete_identity_provenance.py
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "data/database/ncaa_track_analytics.duckdb"
OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/identity_provenance_audit"
)

RAW_ROSTER_CANDIDATES = [
    PROJECT_ROOT / "data/raw/historical_rosters/all_roster_records.csv",
    PROJECT_ROOT / "data/raw/all_roster_records.csv",
]
UNIQUE_ATHLETE_CANDIDATES = [
    PROJECT_ROOT / "data/raw/historical_rosters/unique_athletes.csv",
    PROJECT_ROOT / "data/raw/unique_athletes.csv",
]
ATHLETE_PAGE_DIR = PROJECT_ROOT / "data/raw/athlete_pages"

CANDIDATE_LIMIT = 50


def qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def write_csv(path: Path, header: list[str], rows: Iterable[Iterable[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def export_query(
    con: duckdb.DuckDBPyConnection,
    filename: str,
    sql: str,
    params: list[object] | None = None,
) -> int:
    result = con.execute(sql, params or [])
    header = [column[0] for column in result.description]
    rows = result.fetchall()
    write_csv(OUTPUT_DIR / filename, header, rows)
    print(f"Wrote {filename}: {len(rows):,} rows")
    return len(rows)


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def relation_columns(
    con: duckdb.DuckDBPyConnection,
    relation_sql: str,
) -> list[str]:
    rows = con.execute(f"DESCRIBE SELECT * FROM {relation_sql}").fetchall()
    return [row[0] for row in rows]


def find_column(
    columns: list[str],
    exact: list[str],
    contains: list[str] | None = None,
) -> str | None:
    lower_map = {column.lower(): column for column in columns}
    for candidate in exact:
        match = lower_map.get(candidate.lower())
        if match:
            return match

    for token in contains or []:
        token_lower = token.lower()
        for column in columns:
            if token_lower in column.lower():
                return column

    return None


def sql_list(values: list[int]) -> str:
    if not values:
        return "NULL"
    return ", ".join(str(int(value)) for value in values)


def extract_html_signals(path: Path) -> dict[str, str | int | None]:
    if not path.exists():
        return {
            "page_exists": 0,
            "page_size_bytes": None,
            "html_title": None,
            "school_signal": None,
        }

    text = path.read_text(encoding="utf-8", errors="ignore")
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    title = None
    if title_match:
        title = re.sub(r"\s+", " ", title_match.group(1)).strip()

    # This is deliberately broad. It only provides audit evidence and does not
    # become an analytical field.
    school_match = re.search(
        r"(?:school|team)[^<]{0,40}</[^>]+>\s*<[^>]+>(.*?)</",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    school_signal = None
    if school_match:
        school_signal = re.sub(
            r"<[^>]+>",
            "",
            school_match.group(1),
        )
        school_signal = re.sub(r"\s+", " ", school_signal).strip()

    return {
        "page_exists": 1,
        "page_size_bytes": path.stat().st_size,
        "html_title": title,
        "school_signal": school_signal,
    }


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        # --------------------------------------------------------------
        # 1. Select roster-multischool candidates
        # --------------------------------------------------------------
        candidate_rows = con.execute(
            f"""
            SELECT
                a.athlete_id,
                COUNT(*) AS affiliation_rows,
                COUNT(DISTINCT t.school_id) AS roster_distinct_schools,
                COUNT(DISTINCT a.season_id) AS affiliation_seasons,
                MIN(se.season_year) AS first_affiliation_year,
                MAX(se.season_year) AS last_affiliation_year
            FROM core.athlete_affiliations a
            JOIN core.teams t
              ON a.team_id = t.team_id
            JOIN core.seasons se
              ON a.season_id = se.season_id
            GROUP BY a.athlete_id
            HAVING COUNT(DISTINCT t.school_id) > 1
            ORDER BY
                roster_distinct_schools DESC,
                affiliation_rows DESC,
                a.athlete_id
            LIMIT {CANDIDATE_LIMIT}
            """
        ).fetchall()

        candidate_ids = [int(row[0]) for row in candidate_rows]
        candidate_sql = sql_list(candidate_ids)

        write_csv(
            OUTPUT_DIR / "candidate_athletes.csv",
            [
                "athlete_id",
                "affiliation_rows",
                "roster_distinct_schools",
                "affiliation_seasons",
                "first_affiliation_year",
                "last_affiliation_year",
            ],
            candidate_rows,
        )
        print(f"Wrote candidate_athletes.csv: {len(candidate_rows):,} rows")

        # --------------------------------------------------------------
        # 2. Database lineage
        # --------------------------------------------------------------
        export_query(
            con,
            "candidate_core_athletes.csv",
            f"""
            SELECT *
            FROM core.athletes
            WHERE athlete_id IN ({candidate_sql})
            ORDER BY athlete_id
            """,
        )

        export_query(
            con,
            "candidate_affiliation_history.csv",
            f"""
            SELECT
                a.athlete_id,
                se.season_year,
                se.season_type,
                a.season_id,
                t.school_id,
                s.school_name,
                a.team_id,
                t.gender_code,
                t.division,
                a.affiliation_id
            FROM core.athlete_affiliations a
            JOIN core.teams t
              ON a.team_id = t.team_id
            JOIN core.schools s
              ON t.school_id = s.school_id
            JOIN core.seasons se
              ON a.season_id = se.season_id
            WHERE a.athlete_id IN ({candidate_sql})
            ORDER BY
                a.athlete_id,
                se.season_year,
                CASE se.season_type
                    WHEN 'indoor' THEN 1
                    WHEN 'outdoor' THEN 2
                    WHEN 'cross_country' THEN 3
                    ELSE 4
                END,
                s.school_name
            """,
        )

        export_query(
            con,
            "candidate_performance_team_history.csv",
            f"""
            SELECT
                p.athlete_id,
                se.season_year,
                se.season_type,
                p.season_id,
                p.team_id,
                t.school_id,
                s.school_name,
                COUNT(*) AS performance_count,
                COUNT(DISTINCT p.meet_id) AS meet_count,
                COUNT(*) FILTER (
                    WHERE p.affiliation_id IS NOT NULL
                ) AS exact_affiliation_count,
                COUNT(*) FILTER (
                    WHERE p.affiliation_id IS NULL
                ) AS null_affiliation_count,
                COUNT(DISTINCT p.source_file) AS source_file_count
            FROM core.performances p
            LEFT JOIN core.teams t
              ON p.team_id = t.team_id
            LEFT JOIN core.schools s
              ON t.school_id = s.school_id
            JOIN core.seasons se
              ON p.season_id = se.season_id
            WHERE p.athlete_id IN ({candidate_sql})
            GROUP BY
                p.athlete_id,
                se.season_year,
                se.season_type,
                p.season_id,
                p.team_id,
                t.school_id,
                s.school_name
            ORDER BY
                p.athlete_id,
                se.season_year,
                CASE se.season_type
                    WHEN 'indoor' THEN 1
                    WHEN 'outdoor' THEN 2
                    WHEN 'cross_country' THEN 3
                    ELSE 4
                END,
                performance_count DESC
            """,
        )

        export_query(
            con,
            "candidate_performance_source_files.csv",
            f"""
            SELECT
                p.athlete_id,
                p.team_id,
                p.source_file,
                COUNT(*) AS performance_count,
                MIN(p.season_year) AS minimum_season_year,
                MAX(p.season_year) AS maximum_season_year
            FROM core.performances p
            WHERE p.athlete_id IN ({candidate_sql})
            GROUP BY p.athlete_id, p.team_id, p.source_file
            ORDER BY p.athlete_id, performance_count DESC, p.source_file
            """,
        )

        export_query(
            con,
            "candidate_identity_contradiction_summary.csv",
            f"""
            WITH roster AS (
                SELECT
                    a.athlete_id,
                    COUNT(DISTINCT t.school_id) AS roster_school_count,
                    COUNT(DISTINCT a.team_id) AS roster_team_count,
                    COUNT(DISTINCT a.season_id) AS roster_season_count
                FROM core.athlete_affiliations a
                JOIN core.teams t
                  ON a.team_id = t.team_id
                WHERE a.athlete_id IN ({candidate_sql})
                GROUP BY a.athlete_id
            ),
            performance AS (
                SELECT
                    p.athlete_id,
                    COUNT(DISTINCT t.school_id) AS performance_school_count,
                    COUNT(DISTINCT p.team_id) AS performance_team_count,
                    COUNT(DISTINCT p.season_id) AS performance_season_count,
                    COUNT(*) AS performance_count,
                    COUNT(*) FILTER (
                        WHERE p.affiliation_id IS NOT NULL
                    ) AS exact_link_count,
                    COUNT(*) FILTER (
                        WHERE p.affiliation_id IS NULL
                    ) AS team_only_count
                FROM core.performances p
                LEFT JOIN core.teams t
                  ON p.team_id = t.team_id
                WHERE p.athlete_id IN ({candidate_sql})
                GROUP BY p.athlete_id
            )
            SELECT
                r.athlete_id,
                r.roster_school_count,
                r.roster_team_count,
                r.roster_season_count,
                COALESCE(p.performance_school_count, 0)
                    AS performance_school_count,
                COALESCE(p.performance_team_count, 0)
                    AS performance_team_count,
                COALESCE(p.performance_season_count, 0)
                    AS performance_season_count,
                COALESCE(p.performance_count, 0)
                    AS performance_count,
                COALESCE(p.exact_link_count, 0)
                    AS exact_link_count,
                COALESCE(p.team_only_count, 0)
                    AS team_only_count
            FROM roster r
            LEFT JOIN performance p
              ON r.athlete_id = p.athlete_id
            ORDER BY
                r.roster_school_count DESC,
                r.roster_season_count DESC,
                r.athlete_id
            """,
        )

        # --------------------------------------------------------------
        # 3. Raw CSV lineage
        # --------------------------------------------------------------
        raw_roster_path = first_existing(RAW_ROSTER_CANDIDATES)
        unique_athletes_path = first_existing(UNIQUE_ATHLETE_CANDIDATES)

        raw_file_findings: list[tuple[str, str, str]] = []

        if raw_roster_path:
            roster_relation = (
                f"read_csv_auto('{raw_roster_path.as_posix()}', "
                "header=true, all_varchar=true, ignore_errors=true)"
            )
            roster_columns = relation_columns(con, roster_relation)
            roster_athlete_col = find_column(
                roster_columns,
                ["athlete_id"],
                ["athlete"],
            )

            raw_file_findings.append(
                (
                    "all_roster_records",
                    str(raw_roster_path),
                    ", ".join(roster_columns),
                )
            )

            if roster_athlete_col:
                export_query(
                    con,
                    "candidate_raw_roster_rows.csv",
                    f"""
                    SELECT *
                    FROM {roster_relation}
                    WHERE TRY_CAST({qi(roster_athlete_col)} AS BIGINT)
                          IN ({candidate_sql})
                    ORDER BY
                        TRY_CAST({qi(roster_athlete_col)} AS BIGINT)
                    """,
                )
            else:
                write_csv(
                    OUTPUT_DIR / "candidate_raw_roster_rows.csv",
                    ["error"],
                    [["No athlete ID column detected"]],
                )
        else:
            raw_file_findings.append(
                ("all_roster_records", "NOT FOUND", "")
            )

        if unique_athletes_path:
            unique_relation = (
                f"read_csv_auto('{unique_athletes_path.as_posix()}', "
                "header=true, all_varchar=true, ignore_errors=true)"
            )
            unique_columns = relation_columns(con, unique_relation)
            unique_athlete_col = find_column(
                unique_columns,
                ["athlete_id"],
                ["athlete"],
            )

            raw_file_findings.append(
                (
                    "unique_athletes",
                    str(unique_athletes_path),
                    ", ".join(unique_columns),
                )
            )

            if unique_athlete_col:
                export_query(
                    con,
                    "candidate_unique_athlete_rows.csv",
                    f"""
                    SELECT *
                    FROM {unique_relation}
                    WHERE TRY_CAST({qi(unique_athlete_col)} AS BIGINT)
                          IN ({candidate_sql})
                    ORDER BY
                        TRY_CAST({qi(unique_athlete_col)} AS BIGINT)
                    """,
                )
            else:
                write_csv(
                    OUTPUT_DIR / "candidate_unique_athlete_rows.csv",
                    ["error"],
                    [["No athlete ID column detected"]],
                )
        else:
            raw_file_findings.append(
                ("unique_athletes", "NOT FOUND", "")
            )

        write_csv(
            OUTPUT_DIR / "raw_file_inventory.csv",
            ["logical_file", "path", "detected_columns"],
            raw_file_findings,
        )

        # --------------------------------------------------------------
        # 4. Saved athlete-page existence and basic HTML signals
        # --------------------------------------------------------------
        html_rows = []
        for athlete_id in candidate_ids:
            page_path = ATHLETE_PAGE_DIR / f"{athlete_id}.html"
            signals = extract_html_signals(page_path)
            html_rows.append(
                (
                    athlete_id,
                    str(page_path),
                    signals["page_exists"],
                    signals["page_size_bytes"],
                    signals["html_title"],
                    signals["school_signal"],
                )
            )

        write_csv(
            OUTPUT_DIR / "candidate_athlete_page_signals.csv",
            [
                "athlete_id",
                "page_path",
                "page_exists",
                "page_size_bytes",
                "html_title",
                "school_signal",
            ],
            html_rows,
        )
        print(
            "Wrote candidate_athlete_page_signals.csv: "
            f"{len(html_rows):,} rows"
        )

        # --------------------------------------------------------------
        # 5. Summary
        # --------------------------------------------------------------
        summary = f"""MILESTONE 4 ATHLETE IDENTITY PROVENANCE AUDIT
=================================================
Database: {DB_PATH}
Connection mode: read-only
Candidate athlete IDs: {len(candidate_ids)}

PURPOSE
- Trace roster-multischool athlete IDs through raw and core data.
- Determine whether team attribution was selected during unique-athlete
  deduplication or performance parsing.
- Determine whether existing raw data is sufficient to reconstruct transfers.
- Decide whether targeted rescraping is necessary.

FILES CHECKED
- all_roster_records: {raw_roster_path or 'NOT FOUND'}
- unique_athletes: {unique_athletes_path or 'NOT FOUND'}
- athlete pages: {ATHLETE_PAGE_DIR}

KEY OUTPUTS
- candidate_identity_contradiction_summary.csv
- candidate_affiliation_history.csv
- candidate_performance_team_history.csv
- candidate_performance_source_files.csv
- candidate_raw_roster_rows.csv
- candidate_unique_athlete_rows.csv
- candidate_athlete_page_signals.csv
- raw_file_inventory.csv

NO DATABASE OBJECTS WERE CREATED OR MODIFIED.
"""
        (OUTPUT_DIR / "audit_summary.txt").write_text(
            summary,
            encoding="utf-8",
        )

        print(f"Outputs: {OUTPUT_DIR}")
        print("Database connection was read-only.")

    finally:
        con.close()


if __name__ == "__main__":
    main()
