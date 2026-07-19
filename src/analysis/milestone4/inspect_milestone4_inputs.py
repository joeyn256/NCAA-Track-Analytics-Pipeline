
from __future__ import annotations

from pathlib import Path
import sys

import duckdb
import pandas as pd


DB_RELATIVE_PATH = Path("data/database/ncaa_track_analytics.duckdb")
OUTPUT_RELATIVE_PATH = Path("data/processed/milestone4/inspection")

CORE_TABLES = [
    "schools",
    "teams",
    "athletes",
    "seasons",
    "meets",
    "events",
    "athlete_affiliations",
    "performances",
]


def find_project_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / DB_RELATIVE_PATH).exists():
            return candidate
    raise FileNotFoundError(
        f"Could not find {DB_RELATIVE_PATH} above {start}. "
        "Run this script from inside the NCAA Track Analytics Pipeline repository."
    )


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def qualified_name(schema: str, table: str) -> str:
    return f"{quote_identifier(schema)}.{quote_identifier(table)}"


def get_columns(
    con: duckdb.DuckDBPyConnection,
    schema: str,
    table: str,
) -> list[str]:
    rows = con.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = ? AND table_name = ?
        ORDER BY ordinal_position
        """,
        [schema, table],
    ).fetchall()
    return [row[0] for row in rows]


def pick_column(
    columns: list[str],
    exact_candidates: tuple[str, ...],
    token_candidates: tuple[tuple[str, ...], ...] = (),
) -> str | None:
    by_lower = {column.lower(): column for column in columns}

    for candidate in exact_candidates:
        if candidate.lower() in by_lower:
            return by_lower[candidate.lower()]

    for tokens in token_candidates:
        for column in columns:
            lower = column.lower()
            if all(token in lower for token in tokens):
                return column

    return None


def export_query(
    con: duckdb.DuckDBPyConnection,
    output_dir: Path,
    filename: str,
    sql: str,
    params: list[object] | None = None,
) -> pd.DataFrame:
    dataframe = con.execute(sql, params or []).fetchdf()
    dataframe.to_csv(output_dir / filename, index=False)
    return dataframe


def mark_format_expression(column: str) -> str:
    raw = f"trim(CAST({quote_identifier(column)} AS VARCHAR))"
    upper = f"upper({raw})"
    return f"""
        CASE
            WHEN {quote_identifier(column)} IS NULL THEN 'NULL'
            WHEN {raw} = '' THEN 'BLANK'
            WHEN {upper} IN (
                'DNS', 'DNF', 'DQ', 'DSQ', 'SCR', 'NH', 'NM',
                'ND', 'NT', 'FOUL', 'F', 'PASS', 'P'
            ) THEN 'STATUS'
            WHEN regexp_full_match({raw}, '^[0-9]{{1,3}}:[0-9]{{2}}([.][0-9]+)?$')
                THEN 'TIME_COLON'
            WHEN regexp_full_match({raw}, '^[0-9]{{1,3}}:[0-9]{{2}}([.][0-9]+)?[A-Za-z]+$')
                THEN 'TIME_COLON_WITH_SUFFIX'
            WHEN regexp_full_match({raw}, '^[+-]?[0-9]+([.][0-9]+)?$')
                THEN 'PLAIN_NUMERIC'
            WHEN regexp_full_match({raw}, '^[0-9]+-[0-9]{{1,2}}([.][0-9]+)?$')
                THEN 'IMPERIAL_DASH'
            WHEN regexp_full_match({raw}, '^[+-]?[0-9]+([.][0-9]+)?[mM]$')
                THEN 'METRIC_SUFFIX'
            ELSE 'OTHER'
        END
    """


def main() -> None:
    project_root = find_project_root(Path(__file__).resolve())
    db_path = project_root / DB_RELATIVE_PATH
    output_dir = project_root / OUTPUT_RELATIVE_PATH
    output_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path), read_only=True)

    report_lines: list[str] = [
        "MILESTONE 4 INPUT INSPECTION",
        "========================================",
        f"Database: {db_path}",
        f"DuckDB Python version: {duckdb.__version__}",
        "Connection mode: read-only",
        "",
    ]

    catalog = export_query(
        con,
        output_dir,
        "catalog_tables.csv",
        """
        SELECT table_schema, table_name, table_type
        FROM information_schema.tables
        WHERE table_schema IN ('raw', 'core', 'analytics', 'audit')
        ORDER BY table_schema, table_name
        """,
    )

    export_query(
        con,
        output_dir,
        "catalog_columns.csv",
        """
        SELECT
            table_schema,
            table_name,
            ordinal_position,
            column_name,
            data_type,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema IN ('raw', 'core', 'analytics', 'audit')
        ORDER BY table_schema, table_name, ordinal_position
        """,
    )

    row_counts: list[dict[str, object]] = []
    for table in CORE_TABLES:
        columns = get_columns(con, "core", table)
        if not columns:
            row_counts.append(
                {"table_schema": "core", "table_name": table, "row_count": None}
            )
            continue

        row_count = con.execute(
            f"SELECT count(*) FROM {qualified_name('core', table)}"
        ).fetchone()[0]
        row_counts.append(
            {"table_schema": "core", "table_name": table, "row_count": row_count}
        )

        export_query(
            con,
            output_dir,
            f"describe_core_{table}.csv",
            f"DESCRIBE {qualified_name('core', table)}",
        )

        sample_limit = 1000 if table == "events" else 100
        export_query(
            con,
            output_dir,
            f"sample_core_{table}.csv",
            f"SELECT * FROM {qualified_name('core', table)} LIMIT {sample_limit}",
        )

    row_counts_df = pd.DataFrame(row_counts)
    row_counts_df.to_csv(output_dir / "core_row_counts.csv", index=False)

    report_lines.append("CORE TABLE ROW COUNTS")
    for row in row_counts:
        report_lines.append(f"- core.{row['table_name']}: {row['row_count']:,}" if row["row_count"] is not None else f"- core.{row['table_name']}: NOT FOUND")
    report_lines.append("")

    performance_columns = get_columns(con, "core", "performances")
    event_columns = get_columns(con, "core", "events")
    affiliation_columns = get_columns(con, "core", "athlete_affiliations")

    performance_roles = {
        "performance_id": pick_column(
            performance_columns,
            ("performance_id", "result_id"),
            (("performance", "id"), ("result", "id")),
        ),
        "athlete_id": pick_column(
            performance_columns,
            ("athlete_id",),
            (("athlete", "id"),),
        ),
        "event_id": pick_column(
            performance_columns,
            ("event_id",),
            (("event", "id"),),
        ),
        "affiliation_id": pick_column(
            performance_columns,
            ("affiliation_id",),
            (("affiliation", "id"),),
        ),
        "season_id": pick_column(
            performance_columns,
            ("season_id",),
            (("season", "id"),),
        ),
        "meet_id": pick_column(
            performance_columns,
            ("meet_id",),
            (("meet", "id"),),
        ),
        "raw_event_label": pick_column(
            performance_columns,
            ("raw_event_label", "event_raw", "raw_event", "event"),
            (("raw", "event"), ("event", "label")),
        ),
        "raw_mark": pick_column(
            performance_columns,
            ("mark", "raw_mark", "mark_raw", "performance_mark"),
            (("raw", "mark"),),
        ),
        "secondary_mark": pick_column(
            performance_columns,
            ("secondary_mark", "mark_secondary"),
            (("secondary", "mark"),),
        ),
        "wind": pick_column(
            performance_columns,
            ("wind", "raw_wind"),
            (("wind",),),
        ),
        "place": pick_column(
            performance_columns,
            ("place", "raw_place"),
            (("place",),),
        ),
        "competition_round": pick_column(
            performance_columns,
            ("competition_round", "round"),
            (("competition", "round"),),
        ),
        "source_file": pick_column(
            performance_columns,
            ("source_file", "source_filename"),
            (("source", "file"),),
        ),
    }

    event_roles = {
        "event_id": pick_column(
            event_columns,
            ("event_id",),
            (("event", "id"),),
        ),
        "raw_event_label": pick_column(
            event_columns,
            ("raw_event_label", "event_name", "raw_event_name", "event", "name", "label"),
            (("raw", "event"), ("event", "name"), ("event", "label")),
        ),
    }

    affiliation_roles = {
        "affiliation_id": pick_column(
            affiliation_columns,
            ("affiliation_id",),
            (("affiliation", "id"),),
        ),
        "athlete_id": pick_column(
            affiliation_columns,
            ("athlete_id",),
            (("athlete", "id"),),
        ),
        "team_id": pick_column(
            affiliation_columns,
            ("team_id",),
            (("team", "id"),),
        ),
        "school_id": pick_column(
            affiliation_columns,
            ("school_id", "institution_id"),
            (("school", "id"), ("institution", "id")),
        ),
        "start_date": pick_column(
            affiliation_columns,
            ("start_date", "affiliation_start_date", "stint_start_date"),
            (("start", "date"),),
        ),
        "end_date": pick_column(
            affiliation_columns,
            ("end_date", "affiliation_end_date", "stint_end_date"),
            (("end", "date"),),
        ),
    }

    detected_rows: list[dict[str, object]] = []
    for role, column in performance_roles.items():
        detected_rows.append(
            {"table_name": "core.performances", "analytical_role": role, "column_name": column}
        )
    for role, column in event_roles.items():
        detected_rows.append(
            {"table_name": "core.events", "analytical_role": role, "column_name": column}
        )
    for role, column in affiliation_roles.items():
        detected_rows.append(
            {"table_name": "core.athlete_affiliations", "analytical_role": role, "column_name": column}
        )

    pd.DataFrame(detected_rows).to_csv(
        output_dir / "detected_analysis_columns.csv",
        index=False,
    )

    report_lines.append("DETECTED ANALYTICAL COLUMNS")
    for row in detected_rows:
        report_lines.append(
            f"- {row['table_name']} / {row['analytical_role']}: "
            f"{row['column_name'] or 'NOT DETECTED'}"
        )
    report_lines.append("")

    selected_performance_columns = [
        column
        for column in dict.fromkeys(performance_roles.values())
        if column is not None
    ]
    if selected_performance_columns:
        selection = ", ".join(quote_identifier(column) for column in selected_performance_columns)
        export_query(
            con,
            output_dir,
            "performance_analysis_sample_20000.csv",
            f"""
            SELECT {selection}
            FROM {qualified_name('core', 'performances')}
            USING SAMPLE reservoir(20000 ROWS)
            REPEATABLE (404)
            """,
        )

    field_profile_rows: list[dict[str, object]] = []
    for role, column in performance_roles.items():
        if column is None:
            continue

        quoted = quote_identifier(column)
        profile = con.execute(
            f"""
            SELECT
                count(*) AS total_rows,
                count({quoted}) AS non_null_rows,
                count(*) FILTER (
                    WHERE {quoted} IS NOT NULL
                      AND trim(CAST({quoted} AS VARCHAR)) = ''
                ) AS blank_rows,
                approx_count_distinct({quoted}) AS approximate_distinct_values
            FROM {qualified_name('core', 'performances')}
            """
        ).fetchone()

        field_profile_rows.append(
            {
                "analytical_role": role,
                "column_name": column,
                "total_rows": profile[0],
                "non_null_rows": profile[1],
                "null_rows": profile[0] - profile[1],
                "blank_rows": profile[2],
                "approximate_distinct_values": profile[3],
            }
        )

    pd.DataFrame(field_profile_rows).to_csv(
        output_dir / "performance_field_profile.csv",
        index=False,
    )

    raw_mark_column = performance_roles["raw_mark"]
    secondary_mark_column = performance_roles["secondary_mark"]
    performance_event_id = performance_roles["event_id"]
    event_event_id = event_roles["event_id"]
    event_label = event_roles["raw_event_label"]

    for role_name, mark_column in (
        ("raw_mark", raw_mark_column),
        ("secondary_mark", secondary_mark_column),
    ):
        if mark_column is None:
            continue

        format_expression = mark_format_expression(mark_column)
        raw_text = f"trim(CAST({quote_identifier(mark_column)} AS VARCHAR))"

        export_query(
            con,
            output_dir,
            f"{role_name}_format_profile.csv",
            f"""
            WITH classified AS (
                SELECT
                    {raw_text} AS raw_text,
                    {format_expression} AS format_class
                FROM {qualified_name('core', 'performances')}
            )
            SELECT
                format_class,
                count(*) AS row_count,
                approx_count_distinct(raw_text) AS approximate_distinct_values,
                min(length(raw_text)) AS minimum_length,
                max(length(raw_text)) AS maximum_length
            FROM classified
            GROUP BY format_class
            ORDER BY row_count DESC, format_class
            """,
        )

        export_query(
            con,
            output_dir,
            f"{role_name}_top_examples_by_format.csv",
            f"""
            WITH classified AS (
                SELECT
                    {raw_text} AS raw_text,
                    {format_expression} AS format_class
                FROM {qualified_name('core', 'performances')}
            ),
            counts AS (
                SELECT
                    format_class,
                    raw_text,
                    count(*) AS row_count
                FROM classified
                GROUP BY format_class, raw_text
            ),
            ranked AS (
                SELECT
                    *,
                    row_number() OVER (
                        PARTITION BY format_class
                        ORDER BY row_count DESC, raw_text
                    ) AS format_rank
                FROM counts
            )
            SELECT format_class, format_rank, raw_text, row_count
            FROM ranked
            WHERE format_rank <= 100
            ORDER BY format_class, format_rank
            """,
        )

    if performance_event_id and raw_mark_column:
        format_expression = mark_format_expression(raw_mark_column)
        event_select = [
            f"p.{quote_identifier(performance_event_id)} AS performance_event_id"
        ]
        join_sql = ""
        group_by = ["performance_event_id", "format_class"]

        if event_event_id:
            if event_label:
                event_select.append(
                    f"e.{quote_identifier(event_label)} AS event_label"
                )
                group_by.append("event_label")
            join_sql = f"""
                LEFT JOIN {qualified_name('core', 'events')} AS e
                  ON p.{quote_identifier(performance_event_id)}
                   = e.{quote_identifier(event_event_id)}
            """

        export_query(
            con,
            output_dir,
            "event_mark_format_counts.csv",
            f"""
            SELECT
                {", ".join(event_select)},
                {format_expression} AS format_class,
                count(*) AS row_count
            FROM {qualified_name('core', 'performances')} AS p
            {join_sql}
            GROUP BY {", ".join(group_by)}
            ORDER BY performance_event_id, row_count DESC
            """,
        )

        label_sample_select = ""
        label_sample_join = ""
        if event_event_id and event_label:
            label_sample_select = f", e.{quote_identifier(event_label)} AS event_label"
            label_sample_join = f"""
                LEFT JOIN {qualified_name('core', 'events')} AS e
                  ON s.performance_event_id = e.{quote_identifier(event_event_id)}
            """

        export_query(
            con,
            output_dir,
            "event_mark_examples_sample.csv",
            f"""
            WITH sampled AS (
                SELECT
                    {quote_identifier(performance_event_id)} AS performance_event_id,
                    trim(CAST({quote_identifier(raw_mark_column)} AS VARCHAR)) AS raw_mark
                FROM {qualified_name('core', 'performances')}
                USING SAMPLE reservoir(250000 ROWS)
                REPEATABLE (404)
            ),
            counts AS (
                SELECT
                    performance_event_id,
                    raw_mark,
                    count(*) AS sample_count
                FROM sampled
                GROUP BY performance_event_id, raw_mark
            ),
            ranked AS (
                SELECT
                    *,
                    row_number() OVER (
                        PARTITION BY performance_event_id
                        ORDER BY sample_count DESC, raw_mark
                    ) AS event_rank
                FROM counts
            )
            SELECT
                s.performance_event_id
                {label_sample_select},
                s.event_rank,
                s.raw_mark,
                s.sample_count
            FROM ranked AS s
            {label_sample_join}
            WHERE s.event_rank <= 30
            ORDER BY s.performance_event_id, s.event_rank
            """,
        )

    if event_event_id:
        event_count_join = f"""
            LEFT JOIN (
                SELECT
                    {quote_identifier(performance_event_id)} AS event_id_for_count,
                    count(*) AS performance_count
                FROM {qualified_name('core', 'performances')}
                GROUP BY {quote_identifier(performance_event_id)}
            ) AS p
              ON e.{quote_identifier(event_event_id)} = p.event_id_for_count
        """ if performance_event_id else ""

        performance_count_select = (
            ", coalesce(p.performance_count, 0) AS performance_count"
            if performance_event_id
            else ""
        )

        export_query(
            con,
            output_dir,
            "event_inventory_with_usage.csv",
            f"""
            SELECT
                e.*
                {performance_count_select}
            FROM {qualified_name('core', 'events')} AS e
            {event_count_join}
            ORDER BY {quote_identifier(event_event_id)}
            """,
        )

    affiliation_id = performance_roles["affiliation_id"]
    athlete_id = performance_roles["athlete_id"]
    if affiliation_id:
        distinct_athletes = (
            f", approx_count_distinct({quote_identifier(athlete_id)}) "
            "AS approximate_distinct_athletes"
            if athlete_id
            else ""
        )

        export_query(
            con,
            output_dir,
            "performance_affiliation_coverage.csv",
            f"""
            SELECT
                CASE
                    WHEN {quote_identifier(affiliation_id)} IS NULL
                        THEN 'NULL_AFFILIATION'
                    ELSE 'LINKED_AFFILIATION'
                END AS affiliation_status,
                count(*) AS performance_count
                {distinct_athletes}
            FROM {qualified_name('core', 'performances')}
            GROUP BY affiliation_status
            ORDER BY affiliation_status
            """,
        )

    con.close()

    report_lines.extend(
        [
            "FILES WRITTEN",
            f"- {output_dir}",
            "",
            "NEXT REVIEW TARGETS",
            "- catalog_columns.csv",
            "- detected_analysis_columns.csv",
            "- event_inventory_with_usage.csv",
            "- raw_mark_format_profile.csv",
            "- raw_mark_top_examples_by_format.csv",
            "- event_mark_format_counts.csv",
            "- event_mark_examples_sample.csv",
            "- performance_affiliation_coverage.csv",
        ]
    )

    report_path = output_dir / "inspection_summary.txt"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print("\n".join(report_lines))
    print(f"\nInspection summary written to: {report_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nMilestone 4 inspection failed: {exc}", file=sys.stderr)
        raise
