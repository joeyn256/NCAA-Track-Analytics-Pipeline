#!/usr/bin/env python3
"""
Milestone 4 semantic inspection.

Purpose
-------
Perform a second, read-only inspection of the production DuckDB database before
building the Milestone 4 cleaning, event taxonomy, mark parser, or development
ranking.

This script:
- does NOT create or alter database objects;
- discovers actual column names from information_schema;
- profiles affiliation -> team -> school -> season relationships;
- profiles event labels and raw mark edge cases;
- inventories gender, season, meet-date, wind, round, and placement fields;
- writes reproducible CSV and text reports for methodology design.

Run from the project root:
    python src/analysis/milestone4/inspect_milestone4_semantics.py
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable, Sequence

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "data" / "database" / "ncaa_track_analytics.duckdb"
OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "milestone4"
    / "inspection_semantics"
)

CORE_TABLES = [
    "core.schools",
    "core.teams",
    "core.athletes",
    "core.seasons",
    "core.meets",
    "core.events",
    "core.athlete_affiliations",
    "core.performances",
]


def qi(identifier: str) -> str:
    """Safely quote a SQL identifier."""
    return '"' + identifier.replace('"', '""') + '"'


def split_table(table_name: str) -> tuple[str, str]:
    schema_name, relation_name = table_name.split(".", 1)
    return schema_name, relation_name


def get_columns(con: duckdb.DuckDBPyConnection, table_name: str) -> list[dict]:
    schema_name, relation_name = split_table(table_name)
    rows = con.execute(
        """
        SELECT
            ordinal_position,
            column_name,
            data_type,
            is_nullable
        FROM information_schema.columns
        WHERE table_schema = ?
          AND table_name = ?
        ORDER BY ordinal_position
        """,
        [schema_name, relation_name],
    ).fetchall()
    return [
        {
            "ordinal_position": row[0],
            "column_name": row[1],
            "data_type": row[2],
            "is_nullable": row[3],
        }
        for row in rows
    ]


def column_names(columns: Sequence[dict]) -> list[str]:
    return [c["column_name"] for c in columns]


def find_column(
    columns: Sequence[dict],
    exact_candidates: Iterable[str],
    contains_candidates: Iterable[str] = (),
) -> str | None:
    names = column_names(columns)
    lower_map = {name.lower(): name for name in names}

    for candidate in exact_candidates:
        found = lower_map.get(candidate.lower())
        if found:
            return found

    for token in contains_candidates:
        token_lower = token.lower()
        for name in names:
            if token_lower in name.lower():
                return name

    return None


def table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    schema_name, relation_name = split_table(table_name)
    return bool(
        con.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = ?
              AND table_name = ?
            """,
            [schema_name, relation_name],
        ).fetchone()[0]
    )


def write_rows_csv(
    path: Path,
    header: Sequence[str],
    rows: Iterable[Sequence[object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def export_query(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    output_path: Path,
    params: Sequence[object] | None = None,
) -> int:
    """Execute a query and write its result to CSV. Returns row count."""
    result = con.execute(sql, params or [])
    header = [item[0] for item in result.description]
    rows = result.fetchall()
    write_rows_csv(output_path, header, rows)
    return len(rows)


def scalar(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    params: Sequence[object] | None = None,
) -> object:
    return con.execute(sql, params or []).fetchone()[0]


def mark_format_case(expression: str) -> str:
    """Broad, syntax-only mark classifier. No semantic interpretation yet."""
    cleaned = f"TRIM(CAST({expression} AS VARCHAR))"
    return f"""
        CASE
            WHEN {expression} IS NULL THEN 'NULL'
            WHEN {cleaned} = '' THEN 'BLANK'
            WHEN UPPER({cleaned}) IN (
                'DNS', 'DNF', 'DQ', 'FOUL', 'FS', 'NH', 'NM',
                'NT', 'SCR', 'WD', 'ND'
            ) THEN 'STATUS'
            WHEN regexp_matches(
                {cleaned},
                '^[0-9]+:[0-9]{{2}}(?:\\.[0-9]+)?$'
            ) THEN 'TIME_COLON'
            WHEN regexp_matches(
                {cleaned},
                '^[0-9]+:[0-9]{{2}}(?:\\.[0-9]+)?[^0-9\\s]+$'
            ) THEN 'TIME_COLON_WITH_SUFFIX'
            WHEN regexp_matches(
                {cleaned},
                '^[+-]?[0-9]+(?:\\.[0-9]+)?$'
            ) THEN 'PLAIN_NUMERIC'
            WHEN regexp_matches(
                {cleaned},
                '^[+-]?[0-9]+(?:\\.[0-9]+)?[mM]$'
            ) THEN 'METRIC_SUFFIX'
            WHEN regexp_matches(
                {cleaned},
                '^[0-9]+-[0-9]+(?:\\.[0-9]+)?$'
            ) THEN 'IMPERIAL_DASH'
            ELSE 'OTHER'
        END
    """


def profile_dimension(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
    columns: Sequence[dict],
    candidate_columns: Sequence[str],
    output_path: Path,
) -> list[str]:
    """Write value counts for likely categorical columns."""
    available = set(column_names(columns))
    selected = [name for name in candidate_columns if name in available]

    all_rows: list[tuple] = []
    for col in selected:
        sql = f"""
            SELECT
                ? AS column_name,
                CAST({qi(col)} AS VARCHAR) AS raw_value,
                COUNT(*) AS row_count
            FROM {table_name}
            GROUP BY {qi(col)}
            ORDER BY row_count DESC, raw_value
            LIMIT 500
        """
        all_rows.extend(con.execute(sql, [col]).fetchall())

    write_rows_csv(
        output_path,
        ["column_name", "raw_value", "row_count"],
        all_rows,
    )
    return selected


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}\n"
            "Run this script from the NCAA Track Analytics Pipeline repository."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        table_columns = {
            table: get_columns(con, table)
            for table in CORE_TABLES
            if table_exists(con, table)
        }

        # ------------------------------------------------------------------
        # 1. Core catalog and samples
        # ------------------------------------------------------------------
        catalog_rows: list[tuple] = []
        for table, cols in table_columns.items():
            for col in cols:
                catalog_rows.append(
                    (
                        table,
                        col["ordinal_position"],
                        col["column_name"],
                        col["data_type"],
                        col["is_nullable"],
                    )
                )

        write_rows_csv(
            OUTPUT_DIR / "core_table_columns.csv",
            [
                "table_name",
                "ordinal_position",
                "column_name",
                "data_type",
                "is_nullable",
            ],
            catalog_rows,
        )

        for table in table_columns:
            safe_name = table.replace(".", "__")
            export_query(
                con,
                f"SELECT * FROM {table} LIMIT 25",
                OUTPUT_DIR / f"sample_{safe_name}.csv",
            )

        # ------------------------------------------------------------------
        # 2. Discover key columns
        # ------------------------------------------------------------------
        p_cols = table_columns["core.performances"]
        a_cols = table_columns["core.athlete_affiliations"]
        t_cols = table_columns["core.teams"]
        s_cols = table_columns["core.schools"]
        se_cols = table_columns["core.seasons"]
        m_cols = table_columns["core.meets"]
        e_cols = table_columns["core.events"]

        detected = {
            "performance_id": find_column(p_cols, ["performance_id"]),
            "performance_athlete_id": find_column(p_cols, ["athlete_id"]),
            "performance_event_id": find_column(p_cols, ["event_id"]),
            "performance_affiliation_id": find_column(p_cols, ["affiliation_id"]),
            "performance_team_id": find_column(p_cols, ["team_id"]),
            "performance_season_id": find_column(p_cols, ["season_id"]),
            "performance_meet_id": find_column(p_cols, ["meet_id"]),
            "performance_event_raw": find_column(
                p_cols, ["event", "event_label", "raw_event_label"]
            ),
            "performance_mark": find_column(
                p_cols, ["mark", "raw_mark", "performance_mark"]
            ),
            "performance_secondary_mark": find_column(
                p_cols, ["secondary_mark"]
            ),
            "performance_wind": find_column(p_cols, ["wind"]),
            "performance_place": find_column(p_cols, ["place"]),
            "performance_raw_place": find_column(p_cols, ["raw_place"]),
            "performance_round": find_column(
                p_cols, ["competition_round", "round"]
            ),
            "performance_source_file": find_column(p_cols, ["source_file"]),
            "performance_result_url": find_column(p_cols, ["result_url"]),
            "performance_meet_url": find_column(p_cols, ["meet_url"]),
            "affiliation_id": find_column(a_cols, ["affiliation_id"]),
            "affiliation_athlete_id": find_column(a_cols, ["athlete_id"]),
            "affiliation_team_id": find_column(a_cols, ["team_id"]),
            "affiliation_school_id": find_column(a_cols, ["school_id"]),
            "affiliation_season_id": find_column(a_cols, ["season_id"]),
            "affiliation_year": find_column(
                a_cols,
                ["season_year", "academic_year", "year", "roster_year"],
                ["year"],
            ),
            "affiliation_start": find_column(
                a_cols,
                ["start_date", "affiliation_start_date", "valid_from"],
                ["start"],
            ),
            "affiliation_end": find_column(
                a_cols,
                ["end_date", "affiliation_end_date", "valid_to"],
                ["end"],
            ),
            "team_id": find_column(t_cols, ["team_id"]),
            "team_school_id": find_column(t_cols, ["school_id"]),
            "team_gender": find_column(
                t_cols, ["gender", "sex", "team_gender"], ["gender"]
            ),
            "team_division": find_column(
                t_cols, ["division", "ncaa_division"], ["division"]
            ),
            "team_sport": find_column(t_cols, ["sport"], ["sport"]),
            "team_name": find_column(
                t_cols, ["team_name", "school_name", "name"], ["name"]
            ),
            "school_id": find_column(s_cols, ["school_id"]),
            "school_name": find_column(
                s_cols,
                ["school_name", "institution_name", "name"],
                ["name"],
            ),
            "season_id": find_column(se_cols, ["season_id"]),
            "season_year": find_column(
                se_cols, ["season_year", "year"], ["year"]
            ),
            "season_type": find_column(
                se_cols, ["season_type", "type"], ["type"]
            ),
            "season_label": find_column(
                se_cols, ["season_label", "label", "name"], ["label"]
            ),
            "meet_id": find_column(m_cols, ["meet_id"]),
            "meet_date": find_column(
                m_cols,
                ["meet_date", "start_date", "date"],
                ["date"],
            ),
            "meet_name": find_column(
                m_cols, ["meet_name", "name"], ["name"]
            ),
            "event_id": find_column(e_cols, ["event_id"]),
            "event_label": find_column(
                e_cols, ["event_label", "event", "raw_event_label"]
            ),
        }

        write_rows_csv(
            OUTPUT_DIR / "detected_semantic_columns.csv",
            ["semantic_role", "detected_column"],
            sorted(detected.items()),
        )

        # ------------------------------------------------------------------
        # 3. Dimension value inventories
        # ------------------------------------------------------------------
        team_selected = profile_dimension(
            con,
            "core.teams",
            t_cols,
            [
                name
                for name in [
                    detected["team_gender"],
                    detected["team_division"],
                    detected["team_sport"],
                    "conference",
                    "state",
                ]
                if name
            ],
            OUTPUT_DIR / "team_dimension_value_counts.csv",
        )

        season_selected = profile_dimension(
            con,
            "core.seasons",
            se_cols,
            [
                name
                for name in [
                    detected["season_year"],
                    detected["season_type"],
                    detected["season_label"],
                ]
                if name
            ],
            OUTPUT_DIR / "season_dimension_value_counts.csv",
        )

        profile_dimension(
            con,
            "core.performances",
            p_cols,
            [
                name
                for name in [
                    detected["performance_round"],
                    detected["performance_wind"],
                    detected["performance_place"],
                    detected["performance_raw_place"],
                ]
                if name
            ],
            OUTPUT_DIR / "performance_dimension_value_counts.csv",
        )

        export_query(
            con,
            "SELECT * FROM core.seasons ORDER BY 1",
            OUTPUT_DIR / "season_inventory.csv",
        )

        # ------------------------------------------------------------------
        # 4. Affiliation, transfer, and school-path structure
        # ------------------------------------------------------------------
        affiliation_summary_lines = [
            "MILESTONE 4 AFFILIATION AND SEMANTIC INSPECTION",
            "=" * 56,
            f"Database: {DB_PATH}",
            "Connection mode: read-only",
            "",
            "DETECTED RELATIONSHIP COLUMNS",
        ]

        for key in [
            "affiliation_id",
            "affiliation_athlete_id",
            "affiliation_team_id",
            "affiliation_school_id",
            "affiliation_season_id",
            "affiliation_year",
            "affiliation_start",
            "affiliation_end",
            "team_id",
            "team_school_id",
            "team_gender",
            "team_division",
            "team_sport",
            "school_id",
            "school_name",
            "season_id",
            "season_year",
            "season_type",
            "season_label",
            "performance_team_id",
            "meet_date",
        ]:
            affiliation_summary_lines.append(
                f"- {key}: {detected[key] or 'NOT DETECTED'}"
            )

        a_athlete = detected["affiliation_athlete_id"]
        a_team = detected["affiliation_team_id"]
        a_season = detected["affiliation_season_id"]
        a_aff = detected["affiliation_id"]
        t_team = detected["team_id"]
        t_school = detected["team_school_id"]
        school_id = detected["school_id"]

        if a_athlete and a_team:
            key_parts = [qi(a_athlete), qi(a_team)]
            if a_season:
                key_parts.append(qi(a_season))
            key_sql = ", ".join(key_parts)

            export_query(
                con,
                f"""
                SELECT
                    {key_sql},
                    COUNT(*) AS affiliation_row_count
                FROM core.athlete_affiliations
                GROUP BY {key_sql}
                HAVING COUNT(*) > 1
                ORDER BY affiliation_row_count DESC
                LIMIT 1000
                """,
                OUTPUT_DIR / "duplicate_affiliation_natural_keys.csv",
            )

            export_query(
                con,
                f"""
                SELECT
                    {qi(a_athlete)} AS athlete_id,
                    COUNT(*) AS affiliation_rows,
                    COUNT(DISTINCT {qi(a_team)}) AS distinct_teams
                    {
                        f", COUNT(DISTINCT {qi(a_season)}) AS distinct_seasons"
                        if a_season
                        else ""
                    }
                FROM core.athlete_affiliations
                GROUP BY {qi(a_athlete)}
                ORDER BY distinct_teams DESC, affiliation_rows DESC, athlete_id
                LIMIT 5000
                """,
                OUTPUT_DIR / "athletes_with_multiple_affiliations.csv",
            )

        join_select = ["a.*"]
        joins = []
        school_join_available = bool(
            a_team and t_team and t_school and school_id
        )
        if a_team and t_team:
            joins.append(
                f"""
                LEFT JOIN core.teams t
                  ON a.{qi(a_team)} = t.{qi(t_team)}
                """
            )
            join_select.append("t.*")

        if school_join_available:
            joins.append(
                f"""
                LEFT JOIN core.schools s
                  ON t.{qi(t_school)} = s.{qi(school_id)}
                """
            )
            join_select.append("s.*")

        if a_season and detected["season_id"]:
            joins.append(
                f"""
                LEFT JOIN core.seasons se
                  ON a.{qi(a_season)} = se.{qi(detected["season_id"])}
                """
            )
            join_select.append("se.*")

        if joins:
            export_query(
                con,
                f"""
                SELECT {", ".join(join_select)}
                FROM core.athlete_affiliations a
                {" ".join(joins)}
                LIMIT 500
                """,
                OUTPUT_DIR / "affiliation_join_sample.csv",
            )

        if school_join_available and a_athlete:
            export_query(
                con,
                f"""
                SELECT
                    a.{qi(a_athlete)} AS athlete_id,
                    COUNT(*) AS affiliation_rows,
                    COUNT(DISTINCT t.{qi(t_school)}) AS distinct_schools,
                    COUNT(DISTINCT a.{qi(a_team)}) AS distinct_teams
                FROM core.athlete_affiliations a
                JOIN core.teams t
                  ON a.{qi(a_team)} = t.{qi(t_team)}
                GROUP BY a.{qi(a_athlete)}
                HAVING COUNT(DISTINCT t.{qi(t_school)}) > 1
                ORDER BY distinct_schools DESC, affiliation_rows DESC
                LIMIT 5000
                """,
                OUTPUT_DIR / "transfer_candidate_athletes.csv",
            )

            transfer_count = scalar(
                con,
                f"""
                SELECT COUNT(*)
                FROM (
                    SELECT a.{qi(a_athlete)}
                    FROM core.athlete_affiliations a
                    JOIN core.teams t
                      ON a.{qi(a_team)} = t.{qi(t_team)}
                    GROUP BY a.{qi(a_athlete)}
                    HAVING COUNT(DISTINCT t.{qi(t_school)}) > 1
                )
                """,
            )
            affiliation_summary_lines.extend(
                [
                    "",
                    "TRANSFER STRUCTURE",
                    f"- Athletes linked to more than one institution: {transfer_count:,}",
                ]
            )

        # Orphan checks specifically relevant to Milestone 4 joins.
        relationship_checks: list[tuple[str, int]] = []
        if a_team and t_team:
            relationship_checks.append(
                (
                    "affiliations_without_matching_team",
                    scalar(
                        con,
                        f"""
                        SELECT COUNT(*)
                        FROM core.athlete_affiliations a
                        LEFT JOIN core.teams t
                          ON a.{qi(a_team)} = t.{qi(t_team)}
                        WHERE t.{qi(t_team)} IS NULL
                        """,
                    ),
                )
            )
        if school_join_available:
            relationship_checks.append(
                (
                    "teams_without_matching_school",
                    scalar(
                        con,
                        f"""
                        SELECT COUNT(*)
                        FROM core.teams t
                        LEFT JOIN core.schools s
                          ON t.{qi(t_school)} = s.{qi(school_id)}
                        WHERE s.{qi(school_id)} IS NULL
                        """,
                    ),
                )
            )
        if a_season and detected["season_id"]:
            relationship_checks.append(
                (
                    "affiliations_without_matching_season",
                    scalar(
                        con,
                        f"""
                        SELECT COUNT(*)
                        FROM core.athlete_affiliations a
                        LEFT JOIN core.seasons se
                          ON a.{qi(a_season)} = se.{qi(detected["season_id"])}
                        WHERE se.{qi(detected["season_id"])} IS NULL
                        """,
                    ),
                )
            )

        write_rows_csv(
            OUTPUT_DIR / "milestone4_relationship_checks.csv",
            ["check_name", "failed_row_count"],
            relationship_checks,
        )

        # ------------------------------------------------------------------
        # 5. Meet date coverage
        # ------------------------------------------------------------------
        meet_date = detected["meet_date"]
        if meet_date:
            export_query(
                con,
                f"""
                SELECT
                    COUNT(*) AS meet_rows,
                    COUNT({qi(meet_date)}) AS nonnull_dates,
                    COUNT(*) - COUNT({qi(meet_date)}) AS null_dates,
                    MIN(TRY_CAST({qi(meet_date)} AS DATE)) AS minimum_date,
                    MAX(TRY_CAST({qi(meet_date)} AS DATE)) AS maximum_date,
                    COUNT(*) FILTER (
                        WHERE {qi(meet_date)} IS NOT NULL
                          AND TRY_CAST({qi(meet_date)} AS DATE) IS NULL
                    ) AS unparseable_nonnull_dates
                FROM core.meets
                """,
                OUTPUT_DIR / "meet_date_profile.csv",
            )

            export_query(
                con,
                f"""
                SELECT
                    CAST({qi(meet_date)} AS VARCHAR) AS raw_meet_date,
                    COUNT(*) AS meet_count
                FROM core.meets
                GROUP BY {qi(meet_date)}
                ORDER BY meet_count DESC, raw_meet_date
                LIMIT 1000
                """,
                OUTPUT_DIR / "meet_date_raw_values.csv",
            )

        # ------------------------------------------------------------------
        # 6. Mark syntax edge cases
        # ------------------------------------------------------------------
        raw_mark = detected["performance_mark"]
        secondary_mark = detected["performance_secondary_mark"]
        raw_event = detected["performance_event_raw"]
        p_event_id = detected["performance_event_id"]
        event_id = detected["event_id"]
        event_label = detected["event_label"]

        if not raw_mark:
            raise RuntimeError("Could not detect the primary performance mark column.")

        mark_case = mark_format_case(f"p.{qi(raw_mark)}")

        export_query(
            con,
            f"""
            WITH classified AS (
                SELECT
                    TRIM(CAST(p.{qi(raw_mark)} AS VARCHAR)) AS raw_mark,
                    {mark_case} AS format_class
                FROM core.performances p
            )
            SELECT
                format_class,
                COUNT(*) AS row_count,
                COUNT(DISTINCT raw_mark) AS distinct_values,
                MIN(LENGTH(raw_mark)) AS minimum_length,
                MAX(LENGTH(raw_mark)) AS maximum_length
            FROM classified
            GROUP BY format_class
            ORDER BY row_count DESC
            """,
            OUTPUT_DIR / "primary_mark_format_profile.csv",
        )

        export_query(
            con,
            f"""
            WITH classified AS (
                SELECT
                    TRIM(CAST(p.{qi(raw_mark)} AS VARCHAR)) AS raw_mark,
                    {mark_case} AS format_class
                FROM core.performances p
            )
            SELECT raw_mark, COUNT(*) AS row_count
            FROM classified
            WHERE format_class = 'STATUS'
            GROUP BY raw_mark
            ORDER BY row_count DESC, raw_mark
            """,
            OUTPUT_DIR / "primary_mark_status_values.csv",
        )

        export_query(
            con,
            f"""
            WITH classified AS (
                SELECT
                    TRIM(CAST(p.{qi(raw_mark)} AS VARCHAR)) AS raw_mark,
                    {mark_case} AS format_class
                FROM core.performances p
            )
            SELECT
                raw_mark,
                COUNT(*) AS row_count,
                regexp_extract(raw_mark, '([^0-9.]+)$', 1) AS trailing_token
            FROM classified
            WHERE format_class IN ('OTHER', 'TIME_COLON_WITH_SUFFIX')
            GROUP BY raw_mark
            ORDER BY row_count DESC, raw_mark
            LIMIT 5000
            """,
            OUTPUT_DIR / "primary_mark_edge_values.csv",
        )

        export_query(
            con,
            f"""
            SELECT
                regexp_extract(
                    TRIM(CAST(p.{qi(raw_mark)} AS VARCHAR)),
                    '([^0-9.]+)$',
                    1
                ) AS trailing_token,
                COUNT(*) AS row_count,
                COUNT(DISTINCT TRIM(CAST(p.{qi(raw_mark)} AS VARCHAR)))
                    AS distinct_marks
            FROM core.performances p
            WHERE regexp_matches(
                TRIM(CAST(p.{qi(raw_mark)} AS VARCHAR)),
                '.*[^0-9.]$'
            )
            GROUP BY trailing_token
            ORDER BY row_count DESC, trailing_token
            LIMIT 500
            """,
            OUTPUT_DIR / "primary_mark_trailing_tokens.csv",
        )

        if secondary_mark:
            secondary_case = mark_format_case(f"p.{qi(secondary_mark)}")
            export_query(
                con,
                f"""
                WITH classified AS (
                    SELECT
                        TRIM(CAST(p.{qi(secondary_mark)} AS VARCHAR))
                            AS secondary_mark,
                        {secondary_case} AS format_class
                    FROM core.performances p
                )
                SELECT
                    format_class,
                    COUNT(*) AS row_count,
                    COUNT(DISTINCT secondary_mark) AS distinct_values,
                    MIN(LENGTH(secondary_mark)) AS minimum_length,
                    MAX(LENGTH(secondary_mark)) AS maximum_length
                FROM classified
                GROUP BY format_class
                ORDER BY row_count DESC
                """,
                OUTPUT_DIR / "secondary_mark_format_profile.csv",
            )

            export_query(
                con,
                f"""
                SELECT
                    TRIM(CAST(p.{qi(raw_mark)} AS VARCHAR)) AS raw_mark,
                    TRIM(CAST(p.{qi(secondary_mark)} AS VARCHAR))
                        AS secondary_mark,
                    COUNT(*) AS row_count
                FROM core.performances p
                WHERE p.{qi(secondary_mark)} IS NOT NULL
                GROUP BY raw_mark, secondary_mark
                ORDER BY row_count DESC
                LIMIT 5000
                """,
                OUTPUT_DIR / "primary_secondary_mark_pairs.csv",
            )

        # ------------------------------------------------------------------
        # 7. Event taxonomy reconnaissance
        # ------------------------------------------------------------------
        if p_event_id and event_id and event_label:
            export_query(
                con,
                f"""
                WITH event_formats AS (
                    SELECT
                        p.{qi(p_event_id)} AS event_id,
                        {mark_case} AS format_class,
                        COUNT(*) AS row_count
                    FROM core.performances p
                    GROUP BY p.{qi(p_event_id)}, format_class
                ),
                event_totals AS (
                    SELECT
                        {qi(p_event_id)} AS event_id,
                        COUNT(*) AS total_performances
                    FROM core.performances
                    GROUP BY {qi(p_event_id)}
                )
                SELECT
                    e.{qi(event_id)} AS event_id,
                    e.{qi(event_label)} AS event_label,
                    ef.format_class,
                    ef.row_count,
                    et.total_performances,
                    ROUND(
                        100.0 * ef.row_count / et.total_performances,
                        4
                    ) AS event_format_percent
                FROM event_formats ef
                JOIN event_totals et USING (event_id)
                JOIN core.events e
                  ON ef.event_id = e.{qi(event_id)}
                ORDER BY et.total_performances DESC,
                         e.{qi(event_label)},
                         ef.row_count DESC
                """,
                OUTPUT_DIR / "event_mark_format_matrix.csv",
            )

            export_query(
                con,
                f"""
                WITH ranked AS (
                    SELECT
                        p.{qi(p_event_id)} AS event_id,
                        {mark_case} AS format_class,
                        TRIM(CAST(p.{qi(raw_mark)} AS VARCHAR)) AS raw_mark,
                        COUNT(*) AS mark_count,
                        ROW_NUMBER() OVER (
                            PARTITION BY p.{qi(p_event_id)}, {mark_case}
                            ORDER BY COUNT(*) DESC,
                                     TRIM(CAST(p.{qi(raw_mark)} AS VARCHAR))
                        ) AS example_rank
                    FROM core.performances p
                    GROUP BY
                        p.{qi(p_event_id)},
                        format_class,
                        raw_mark
                )
                SELECT
                    e.{qi(event_id)} AS event_id,
                    e.{qi(event_label)} AS event_label,
                    r.format_class,
                    r.example_rank,
                    r.raw_mark,
                    r.mark_count
                FROM ranked r
                JOIN core.events e
                  ON r.event_id = e.{qi(event_id)}
                WHERE r.example_rank <= 15
                ORDER BY e.{qi(event_label)},
                         r.format_class,
                         r.example_rank
                """,
                OUTPUT_DIR / "event_mark_examples_all_events.csv",
            )

            export_query(
                con,
                f"""
                WITH normalized AS (
                    SELECT
                        {qi(event_id)} AS event_id,
                        {qi(event_label)} AS event_label,
                        LOWER(
                            regexp_replace(
                                TRIM(CAST({qi(event_label)} AS VARCHAR)),
                                '[^a-zA-Z0-9]+',
                                '',
                                'g'
                            )
                        ) AS simple_normalized_key
                    FROM core.events
                )
                SELECT
                    simple_normalized_key,
                    COUNT(*) AS label_count,
                    STRING_AGG(event_label, ' | ' ORDER BY event_label)
                        AS event_labels,
                    STRING_AGG(CAST(event_id AS VARCHAR), ' | ' ORDER BY event_id)
                        AS event_ids
                FROM normalized
                GROUP BY simple_normalized_key
                HAVING COUNT(*) > 1
                ORDER BY label_count DESC, simple_normalized_key
                """,
                OUTPUT_DIR / "event_simple_normalization_collisions.csv",
            )

            # Event-by-gender and event-by-season counts when relationship paths exist.
            p_aff = detected["performance_affiliation_id"]
            if (
                p_aff
                and a_aff
                and a_team
                and t_team
                and detected["team_gender"]
            ):
                gender_col = detected["team_gender"]
                export_query(
                    con,
                    f"""
                    SELECT
                        e.{qi(event_id)} AS event_id,
                        e.{qi(event_label)} AS event_label,
                        CAST(t.{qi(gender_col)} AS VARCHAR) AS gender,
                        COUNT(*) AS performance_count,
                        COUNT(DISTINCT p.{qi(detected["performance_athlete_id"])})
                            AS athlete_count
                    FROM core.performances p
                    JOIN core.events e
                      ON p.{qi(p_event_id)} = e.{qi(event_id)}
                    JOIN core.athlete_affiliations a
                      ON p.{qi(p_aff)} = a.{qi(a_aff)}
                    JOIN core.teams t
                      ON a.{qi(a_team)} = t.{qi(t_team)}
                    GROUP BY
                        e.{qi(event_id)},
                        e.{qi(event_label)},
                        t.{qi(gender_col)}
                    ORDER BY performance_count DESC
                    """,
                    OUTPUT_DIR / "event_usage_by_linked_gender.csv",
                )

            p_season = detected["performance_season_id"]
            season_id_col = detected["season_id"]
            if p_season and season_id_col:
                season_fields = [
                    f"se.{qi(season_id_col)} AS season_id"
                ]
                group_fields = [f"se.{qi(season_id_col)}"]
                for semantic_name in [
                    "season_year",
                    "season_type",
                    "season_label",
                ]:
                    col = detected[semantic_name]
                    if col:
                        season_fields.append(
                            f"CAST(se.{qi(col)} AS VARCHAR) AS {semantic_name}"
                        )
                        group_fields.append(f"se.{qi(col)}")

                export_query(
                    con,
                    f"""
                    SELECT
                        e.{qi(event_id)} AS event_id,
                        e.{qi(event_label)} AS event_label,
                        {", ".join(season_fields)},
                        COUNT(*) AS performance_count,
                        COUNT(DISTINCT p.{qi(detected["performance_athlete_id"])})
                            AS athlete_count
                    FROM core.performances p
                    JOIN core.events e
                      ON p.{qi(p_event_id)} = e.{qi(event_id)}
                    JOIN core.seasons se
                      ON p.{qi(p_season)} = se.{qi(season_id_col)}
                    GROUP BY
                        e.{qi(event_id)},
                        e.{qi(event_label)},
                        {", ".join(group_fields)}
                    ORDER BY performance_count DESC
                    """,
                    OUTPUT_DIR / "event_usage_by_season.csv",
                )

        # ------------------------------------------------------------------
        # 8. Performance attribution paths
        # ------------------------------------------------------------------
        p_aff = detected["performance_affiliation_id"]
        p_team = detected["performance_team_id"]

        attribution_rows: list[tuple] = []
        total_performances = scalar(con, "SELECT COUNT(*) FROM core.performances")
        attribution_rows.append(("all_performances", total_performances))

        if p_aff:
            attribution_rows.extend(
                [
                    (
                        "linked_affiliation_id",
                        scalar(
                            con,
                            f"""
                            SELECT COUNT(*)
                            FROM core.performances
                            WHERE {qi(p_aff)} IS NOT NULL
                            """,
                        ),
                    ),
                    (
                        "null_affiliation_id",
                        scalar(
                            con,
                            f"""
                            SELECT COUNT(*)
                            FROM core.performances
                            WHERE {qi(p_aff)} IS NULL
                            """,
                        ),
                    ),
                ]
            )

        if p_team:
            attribution_rows.extend(
                [
                    (
                        "nonnull_performance_team_id",
                        scalar(
                            con,
                            f"""
                            SELECT COUNT(*)
                            FROM core.performances
                            WHERE {qi(p_team)} IS NOT NULL
                            """,
                        ),
                    ),
                    (
                        "null_affiliation_but_nonnull_performance_team_id",
                        scalar(
                            con,
                            f"""
                            SELECT COUNT(*)
                            FROM core.performances
                            WHERE {qi(p_aff)} IS NULL
                              AND {qi(p_team)} IS NOT NULL
                            """
                            if p_aff
                            else f"""
                            SELECT 0
                            """
                        ),
                    ),
                ]
            )

        write_rows_csv(
            OUTPUT_DIR / "performance_attribution_paths.csv",
            ["attribution_category", "performance_count"],
            attribution_rows,
        )

        # Reproducible linked performance sample with dimensions.
        sample_select = ["p.*"]
        sample_joins = []
        if p_event_id and event_id:
            sample_select.append(
                f"e.{qi(event_label)} AS joined_event_label"
            )
            sample_joins.append(
                f"""
                LEFT JOIN core.events e
                  ON p.{qi(p_event_id)} = e.{qi(event_id)}
                """
            )
        if p_aff and a_aff:
            sample_select.append(
                f"a.{qi(a_team)} AS joined_affiliation_team_id"
                if a_team
                else "NULL AS joined_affiliation_team_id"
            )
            sample_joins.append(
                f"""
                LEFT JOIN core.athlete_affiliations a
                  ON p.{qi(p_aff)} = a.{qi(a_aff)}
                """
            )
            if a_team and t_team:
                if detected["team_gender"]:
                    sample_select.append(
                        f"t.{qi(detected['team_gender'])} AS joined_gender"
                    )
                if t_school:
                    sample_select.append(
                        f"t.{qi(t_school)} AS joined_school_id"
                    )
                sample_joins.append(
                    f"""
                    LEFT JOIN core.teams t
                      ON a.{qi(a_team)} = t.{qi(t_team)}
                    """
                )
        export_query(
            con,
            f"""
            SELECT {", ".join(sample_select)}
            FROM core.performances p
            {" ".join(sample_joins)}
            USING SAMPLE 25000 ROWS (reservoir, 4404)
            """,
            OUTPUT_DIR / "performance_semantic_sample_25000.csv",
        )

        # ------------------------------------------------------------------
        # 9. Human-readable summary
        # ------------------------------------------------------------------
        affiliation_summary_lines.extend(
            [
                "",
                "DIMENSION COLUMNS PROFILED",
                f"- core.teams: {', '.join(team_selected) or 'none detected'}",
                f"- core.seasons: {', '.join(season_selected) or 'none detected'}",
                "",
                "MARK EDGE-CASE OUTPUTS",
                "- primary_mark_status_values.csv",
                "- primary_mark_edge_values.csv",
                "- primary_mark_trailing_tokens.csv",
                "- secondary_mark_format_profile.csv",
                "- primary_secondary_mark_pairs.csv",
                "",
                "EVENT TAXONOMY OUTPUTS",
                "- event_mark_format_matrix.csv",
                "- event_mark_examples_all_events.csv",
                "- event_simple_normalization_collisions.csv",
                "- event_usage_by_linked_gender.csv (when joinable)",
                "- event_usage_by_season.csv (when joinable)",
                "",
                "ATTRIBUTION OUTPUTS",
                "- performance_attribution_paths.csv",
                "- transfer_candidate_athletes.csv (when school join is available)",
                "- affiliation_join_sample.csv",
                "",
                "NO DATABASE OBJECTS WERE CREATED OR MODIFIED.",
            ]
        )

        (OUTPUT_DIR / "semantic_inspection_summary.txt").write_text(
            "\n".join(affiliation_summary_lines) + "\n",
            encoding="utf-8",
        )

        print("Milestone 4 semantic inspection complete.")
        print(f"Database: {DB_PATH}")
        print(f"Outputs:  {OUTPUT_DIR}")
        print("Database connection was read-only.")

    finally:
        con.close()


if __name__ == "__main__":
    main()
