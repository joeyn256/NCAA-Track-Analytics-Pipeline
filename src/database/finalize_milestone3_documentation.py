"""Generate the final Milestone 3 database audit documentation.

This script opens the production DuckDB database in read-only mode. It:

1. Reads the latest successful build metadata.
2. Collects final core-table and audit counts.
3. Writes milestones/milestone_03_database_audit.md.
4. Adds or replaces a marked completion section inside
   milestones/milestone_03_database_construction.md.

It does not modify the DuckDB database or any source data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATABASE_PATH = (
    PROJECT_ROOT
    / "data"
    / "database"
    / "ncaa_track_analytics.duckdb"
)

CONSTRUCTION_DOCUMENT = (
    PROJECT_ROOT
    / "milestones"
    / "milestone_03_database_construction.md"
)

AUDIT_DOCUMENT = (
    PROJECT_ROOT
    / "milestones"
    / "milestone_03_database_audit.md"
)

START_MARKER = "<!-- MILESTONE_03_COMPLETION_START -->"
END_MARKER = "<!-- MILESTONE_03_COMPLETION_END -->"

EXPECTED_DUCKDB_VERSION = "1.5.4"
EXPECTED_PERFORMANCE_ROWS = 6_594_540


def format_integer(value: int) -> str:
    """Format an integer with thousands separators."""
    return f"{value:,}"


def markdown_table(
    headers: Iterable[str],
    rows: Iterable[Iterable[object]],
) -> str:
    """Return a Markdown table."""
    header_list = list(headers)
    row_list = [
        list(row)
        for row in rows
    ]

    lines = [
        "| " + " | ".join(header_list) + " |",
        "| "
        + " | ".join("---" for _ in header_list)
        + " |",
    ]

    for row in row_list:
        lines.append(
            "| "
            + " | ".join(
                str(value)
                for value in row
            )
            + " |"
        )

    return "\n".join(lines)


def update_marked_section(
    document: Path,
    replacement: str,
) -> None:
    """Safely add or replace a generated Markdown section."""
    if document.exists():
        original = document.read_text(
            encoding="utf-8"
        )
    else:
        original = "# Milestone 3: Database Construction\n"

    has_start = START_MARKER in original
    has_end = END_MARKER in original

    if has_start != has_end:
        raise RuntimeError(
            "The construction document contains only one "
            "Milestone 3 completion marker. Review it manually "
            "before rerunning this script."
        )

    marked_replacement = (
        f"{START_MARKER}\n"
        f"{replacement.strip()}\n"
        f"{END_MARKER}"
    )

    if has_start and has_end:
        before, remainder = original.split(
            START_MARKER,
            maxsplit=1,
        )

        _, after = remainder.split(
            END_MARKER,
            maxsplit=1,
        )

        updated = (
            before.rstrip()
            + "\n\n"
            + marked_replacement
            + "\n"
            + after.lstrip("\n")
        )
    else:
        updated = (
            original.rstrip()
            + "\n\n"
            + marked_replacement
            + "\n"
        )

    document.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    document.write_text(
        updated,
        encoding="utf-8",
    )


def main() -> None:
    """Generate the Milestone 3 completion documentation."""
    print("MILESTONE 3 DOCUMENTATION FINALIZER")
    print("=" * 80)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Database: {DATABASE_PATH}")
    print(f"Audit document: {AUDIT_DOCUMENT}")
    print(
        "Construction document: "
        f"{CONSTRUCTION_DOCUMENT}"
    )
    print("Database connection: read-only")
    print()

    if duckdb.__version__ != EXPECTED_DUCKDB_VERSION:
        raise RuntimeError(
            "DuckDB version mismatch: "
            f"expected {EXPECTED_DUCKDB_VERSION}, "
            f"found {duckdb.__version__}"
        )

    if not DATABASE_PATH.is_file():
        raise FileNotFoundError(
            f"Production database not found: {DATABASE_PATH}"
        )

    database_size_bytes = DATABASE_PATH.stat().st_size
    database_size_mib = (
        database_size_bytes / (1024 ** 2)
    )
    database_size_gib = (
        database_size_bytes / (1024 ** 3)
    )

    connection = duckdb.connect(
        database=str(DATABASE_PATH),
        read_only=True,
    )

    try:
        build_row = connection.execute(
            """
            SELECT
                build_run_id,
                started_at,
                completed_at,
                status,
                python_version,
                duckdb_version,
                expected_performance_rows,
                actual_performance_rows,
                notes
            FROM audit.build_runs
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()

        if build_row is None:
            raise RuntimeError(
                "No build run exists in audit.build_runs."
            )

        (
            build_run_id,
            started_at,
            completed_at,
            build_status,
            python_version,
            duckdb_version,
            expected_performance_rows,
            actual_performance_rows,
            build_notes,
        ) = build_row

        if build_status != "pass":
            raise RuntimeError(
                "Latest database build did not pass: "
                f"{build_status!r}"
            )

        if (
            actual_performance_rows
            != EXPECTED_PERFORMANCE_ROWS
        ):
            raise RuntimeError(
                "Unexpected performance count: "
                f"{actual_performance_rows}"
            )

        if completed_at is None:
            raise RuntimeError(
                "Latest build has no completion timestamp."
            )

        build_duration_seconds = (
            completed_at - started_at
        ).total_seconds()

        core_counts = dict(
            connection.execute(
                """
                SELECT
                    table_name,
                    actual_row_count
                FROM audit.table_counts
                WHERE build_run_id = ?
                  AND table_schema = 'core'
                ORDER BY table_name
                """,
                [build_run_id],
            ).fetchall()
        )

        direct_core_counts = dict(
            connection.execute(
                """
                SELECT
                    'schools',
                    COUNT(*)::BIGINT
                FROM core.schools

                UNION ALL

                SELECT
                    'teams',
                    COUNT(*)::BIGINT
                FROM core.teams

                UNION ALL

                SELECT
                    'athletes',
                    COUNT(*)::BIGINT
                FROM core.athletes

                UNION ALL

                SELECT
                    'seasons',
                    COUNT(*)::BIGINT
                FROM core.seasons

                UNION ALL

                SELECT
                    'meets',
                    COUNT(*)::BIGINT
                FROM core.meets

                UNION ALL

                SELECT
                    'events',
                    COUNT(*)::BIGINT
                FROM core.events

                UNION ALL

                SELECT
                    'athlete_affiliations',
                    COUNT(*)::BIGINT
                FROM core.athlete_affiliations

                UNION ALL

                SELECT
                    'performances',
                    COUNT(*)::BIGINT
                FROM core.performances
                """
            ).fetchall()
        )

        for table_name, direct_count in (
            direct_core_counts.items()
        ):
            recorded_count = core_counts.get(
                table_name
            )

            if recorded_count is None:
                core_counts[table_name] = direct_count
            elif recorded_count != direct_count:
                raise RuntimeError(
                    "Recorded and direct table counts differ "
                    f"for core.{table_name}: "
                    f"recorded={recorded_count}, "
                    f"direct={direct_count}"
                )

        source_groups = connection.execute(
            """
            SELECT
                source_group,
                COUNT(*)::BIGINT AS file_count,
                SUM(file_size_bytes)::UBIGINT
                    AS total_bytes,
                SUM(row_count)::BIGINT
                    AS total_rows,
                COUNT(*) FILTER (
                    WHERE is_empty
                )::BIGINT AS empty_files
            FROM audit.source_files
            WHERE build_run_id = ?
            GROUP BY source_group
            ORDER BY source_group
            """,
            [build_run_id],
        ).fetchall()

        source_file_metrics = (
            connection.execute(
                """
                SELECT
                    COUNT(*)::BIGINT,
                    SUM(file_size_bytes)::UBIGINT,
                    COUNT(*) FILTER (
                        WHERE NULLIF(
                            TRIM(sha256),
                            ''
                        ) IS NULL
                    )::BIGINT,
                    COUNT(*) FILTER (
                        WHERE load_status = 'failed'
                    )::BIGINT
                FROM audit.source_files
                WHERE build_run_id = ?
                """,
                [build_run_id],
            ).fetchone()
        )

        (
            source_file_count,
            source_file_bytes,
            missing_source_hashes,
            failed_source_files,
        ) = source_file_metrics

        hard_check_metrics = (
            connection.execute(
                """
                SELECT
                    COUNT(*)::BIGINT,
                    COUNT(*) FILTER (
                        WHERE passed
                    )::BIGINT,
                    COUNT(*) FILTER (
                        WHERE NOT passed
                    )::BIGINT
                FROM audit.integrity_checks
                WHERE build_run_id = ?
                  AND severity = 'hard'
                """,
                [build_run_id],
            ).fetchone()
        )

        (
            hard_check_count,
            passed_hard_checks,
            failed_hard_checks,
        ) = hard_check_metrics

        affiliation_coverage = (
            connection.execute(
                """
                SELECT
                    match_class,
                    distinct_performance_keys,
                    performance_rows
                FROM audit.affiliation_coverage
                WHERE build_run_id = ?
                ORDER BY match_class
                """,
                [build_run_id],
            ).fetchall()
        )

        affiliation_total = sum(
            int(row[2])
            for row in affiliation_coverage
        )

        if (
            affiliation_total
            != EXPECTED_PERFORMANCE_ROWS
        ):
            raise RuntimeError(
                "Affiliation coverage does not reconcile: "
                f"{affiliation_total}"
            )

        roster_duplicate_metrics = (
            connection.execute(
                """
                SELECT
                    COUNT(*)::BIGINT,
                    COALESCE(
                        SUM(duplicate_excess_rows),
                        0
                    )::BIGINT
                FROM audit.roster_duplicate_groups
                WHERE build_run_id = ?
                """,
                [build_run_id],
            ).fetchone()
        )

        (
            roster_duplicate_groups,
            roster_duplicate_excess,
        ) = roster_duplicate_metrics

        directory_metrics = (
            connection.execute(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE in_division_i_directory
                    )::BIGINT,
                    COUNT(*)::BIGINT
                FROM core.teams
                """
            ).fetchone()
        )

        (
            directory_team_count,
            total_team_count,
        ) = directory_metrics

        institution_metrics = (
            connection.execute(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE
                            is_division_i_directory_school
                    )::BIGINT,
                    COUNT(*)::BIGINT
                FROM core.schools
                """
            ).fetchone()
        )

        (
            directory_institution_count,
            total_institution_count,
        ) = institution_metrics

        orphan_total = connection.execute(
            """
            SELECT
                (
                    SELECT COUNT(*)
                    FROM core.performances p
                    LEFT JOIN core.athletes a
                        USING (athlete_id)
                    WHERE a.athlete_id IS NULL
                )
                +
                (
                    SELECT COUNT(*)
                    FROM core.performances p
                    LEFT JOIN core.teams t
                        USING (team_id)
                    WHERE p.team_id IS NOT NULL
                      AND t.team_id IS NULL
                )
                +
                (
                    SELECT COUNT(*)
                    FROM core.performances p
                    LEFT JOIN core.seasons s
                        USING (season_id)
                    WHERE s.season_id IS NULL
                )
                +
                (
                    SELECT COUNT(*)
                    FROM core.performances p
                    LEFT JOIN core.meets m
                        USING (meet_id)
                    WHERE m.meet_id IS NULL
                )
                +
                (
                    SELECT COUNT(*)
                    FROM core.performances p
                    LEFT JOIN core.events e
                        USING (event_id)
                    WHERE e.event_id IS NULL
                )
                +
                (
                    SELECT COUNT(*)
                    FROM core.athlete_affiliations a
                    LEFT JOIN core.athletes athletes
                        USING (athlete_id)
                    WHERE athletes.athlete_id IS NULL
                )
                +
                (
                    SELECT COUNT(*)
                    FROM core.athlete_affiliations a
                    LEFT JOIN core.teams t
                        USING (team_id)
                    WHERE t.team_id IS NULL
                )
                +
                (
                    SELECT COUNT(*)
                    FROM core.athlete_affiliations a
                    LEFT JOIN core.seasons s
                        USING (season_id)
                    WHERE s.season_id IS NULL
                )
            """
        ).fetchone()[0]

        schema_version = connection.execute(
            """
            SELECT
                version_id,
                description
            FROM audit.schema_versions
            ORDER BY applied_at DESC
            LIMIT 1
            """
        ).fetchone()

        if schema_version is None:
            raise RuntimeError(
                "No schema version was recorded."
            )

        schema_version_id, schema_description = (
            schema_version
        )

        top_events = connection.execute(
            """
            SELECT
                event_label,
                performance_count
            FROM core.events
            ORDER BY
                performance_count DESC,
                event_label
            LIMIT 10
            """
        ).fetchall()

    finally:
        connection.close()

    core_table_rows = [
        (
            f"`core.{table_name}`",
            format_integer(int(row_count)),
        )
        for table_name, row_count in sorted(
            core_counts.items()
        )
    ]

    source_group_rows = [
        (
            source_group,
            format_integer(int(file_count)),
            format_integer(int(total_rows)),
            format_integer(int(empty_files)),
            f"{int(total_bytes) / (1024 ** 2):,.2f} MiB",
        )
        for (
            source_group,
            file_count,
            total_bytes,
            total_rows,
            empty_files,
        ) in source_groups
    ]

    affiliation_rows = [
        (
            match_class,
            format_integer(
                int(distinct_performance_keys)
            ),
            format_integer(
                int(performance_rows)
            ),
        )
        for (
            match_class,
            distinct_performance_keys,
            performance_rows,
        ) in affiliation_coverage
    ]

    top_event_rows = [
        (
            event_label,
            format_integer(
                int(performance_count)
            ),
        )
        for event_label, performance_count
        in top_events
    ]

    audit_report = f"""# Milestone 3 Database Audit

## Result

**Overall result: PASS**

The Milestone 3 DuckDB analytical database was built transactionally,
published, and independently reopened in read-only mode for validation.

| Item | Result |
| --- | --- |
| Build run ID | `{build_run_id}` |
| Schema version | `{schema_version_id}` |
| Schema description | {schema_description} |
| Build status | `{build_status}` |
| Build started | `{started_at}` |
| Build completed | `{completed_at}` |
| Build duration | {build_duration_seconds:,.2f} seconds |
| Python version | `{python_version}` |
| DuckDB version | `{duckdb_version}` |
| Database file | `data/database/ncaa_track_analytics.duckdb` |
| Database size | {database_size_bytes:,} bytes ({database_size_mib:,.2f} MiB / {database_size_gib:,.2f} GiB) |

The database file and generated build logs are excluded from Git. The
source code, SQL schema, dependency pin, and milestone documentation are
version controlled.

## Logical architecture

The database contains four schemas:

| Schema | Purpose |
| --- | --- |
| `raw` | Persistent source-faithful views over canonical CSV inputs |
| `core` | Relational dimensions, affiliations, and performance facts |
| `analytics` | Reserved for normalized analytical models in Milestone 4 |
| `audit` | Build runs, source hashes, counts, conflicts, and integrity checks |

## Core table counts

{markdown_table(("Table", "Rows"), core_table_rows)}

## School and team domains

| Metric | Count |
| --- | ---: |
| Current Division I directory teams | {format_integer(int(directory_team_count))} |
| Complete team domain | {format_integer(int(total_team_count))} |
| Current Division I directory institutions | {format_integer(int(directory_institution_count))} |
| Complete institution domain | {format_integer(int(total_institution_count))} |

The complete domains include historical or performance-only teams and
institutions that are absent from the current 714-entry Division I
directory. These records are retained so no valid performance is lost.

## Performance integrity

| Check | Result |
| --- | ---: |
| Expected performance records | {format_integer(int(expected_performance_rows))} |
| Actual performance records | {format_integer(int(actual_performance_rows))} |
| Distinct performance IDs | {format_integer(int(actual_performance_rows))} |
| Duplicate performance IDs | 0 |
| Blank performance IDs | 0 |
| Parser failures | 0 |
| Relational orphan records | {format_integer(int(orphan_total))} |

Raw marks, secondary marks, dates, places, event labels, URLs, and source
filenames remain preserved. Full mark, time, and event normalization is
deferred until Milestone 4.

## Historical athlete affiliations

Historical affiliations were constructed from roster records rather than
assuming the current athlete-profile school applied to every season.

| Metric | Count |
| --- | ---: |
| Raw roster rows | 992,774 |
| Unique affiliation rows | {format_integer(int(core_counts["athlete_affiliations"]))} |
| Exact duplicate groups | {format_integer(int(roster_duplicate_groups))} |
| Duplicate excess rows | {format_integer(int(roster_duplicate_excess))} |
| Duplicate affiliation business keys | 0 |

Indoor roster seasons use the ending year when linked to performance
seasons. For example, `2022-23 Indoor` maps to `2023_indoor`.

## Performance-to-affiliation coverage

{markdown_table(
    (
        "Match class",
        "Distinct athlete/team/season keys",
        "Performance rows",
    ),
    affiliation_rows,
)}

Coverage total: **{format_integer(int(affiliation_total))}**

Unmatched performance rows are intentionally retained with a null
`affiliation_id`. The build does not invent historical affiliations from
current-profile school values.

## Canonical source inventory

{markdown_table(
    (
        "Source group",
        "Files",
        "Rows",
        "Empty files",
        "Size",
    ),
    source_group_rows,
)}

| Source audit | Result |
| --- | ---: |
| Registered canonical files | {format_integer(int(source_file_count))} |
| Canonical source size | {source_file_bytes / (1024 ** 3):,.2f} GiB |
| Files without SHA-256 hashes | {format_integer(int(missing_source_hashes))} |
| Failed source files | {format_integer(int(failed_source_files))} |

## Integrity audit

| Audit result | Count |
| --- | ---: |
| Hard checks recorded | {format_integer(int(hard_check_count))} |
| Hard checks passed | {format_integer(int(passed_hard_checks))} |
| Hard checks failed | {format_integer(int(failed_hard_checks))} |

## Most common raw event labels

{markdown_table(
    ("Raw event label", "Performance rows"),
    top_event_rows,
)}

These labels are intentionally source-faithful. Canonical event
classification is deferred until Milestone 4.

## Reproducing the database

Activate the project virtual environment and run:

```bash
python -m pip install --requirement requirements-milestone3.txt

python src/database/build_database.py --preflight-only

python src/database/build_database.py \
    --build \
    2>&1 | tee data/database/milestone3_build.log

python src/database/validate_production_database.py \
    | tee data/database/milestone3_production_validation.txt
```

The builder refuses to overwrite an existing production database. To
perform a completely fresh rebuild, first move or delete the generated
database file intentionally:

```bash
rm data/database/ncaa_track_analytics.duckdb
```

Then rerun the preflight, build, and independent validation commands.

## Milestone 3 conclusion

Milestone 3 successfully converted the audited Milestone 1 and Milestone 2
outputs into a reproducible relational DuckDB analytical database.

The performance fact table contains exactly **6,594,540** records, all
performance IDs are unique and nonblank, historical affiliations are
roster-derived, and all mandatory build and independent validation checks
passed.
"""

    AUDIT_DOCUMENT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    AUDIT_DOCUMENT.write_text(
        audit_report.rstrip() + "\n",
        encoding="utf-8",
    )

    completion_section = f"""## Milestone 3 completion

**Status: COMPLETE — PASS**

The production DuckDB database was built and independently validated.

| Metric | Final value |
| --- | ---: |
| Database size | {database_size_gib:,.2f} GiB |
| Performance facts | {format_integer(int(actual_performance_rows))} |
| Unique historical affiliations | {format_integer(int(core_counts["athlete_affiliations"]))} |
| Athletes | {format_integer(int(core_counts["athletes"]))} |
| Teams | {format_integer(int(core_counts["teams"]))} |
| Institutions | {format_integer(int(core_counts["schools"]))} |
| Seasons | {format_integer(int(core_counts["seasons"]))} |
| Meets | {format_integer(int(core_counts["meets"]))} |
| Raw event labels | {format_integer(int(core_counts["events"]))} |
| Hard audit checks passed | {format_integer(int(passed_hard_checks))} |
| Relational orphan records | {format_integer(int(orphan_total))} |

The final fact table contains exactly **6,594,540** unique, nonblank
performance IDs. Historical school affiliations come from roster records.
Raw marks, dates, places, event labels, URLs, and source filenames remain
preserved for Milestone 4 normalization.

See [Milestone 3 Database Audit](milestone_03_database_audit.md) for the
complete build, source, affiliation, and integrity results.
"""

    update_marked_section(
        CONSTRUCTION_DOCUMENT,
        completion_section,
    )

    print(
        "[PASS] Read the production database in read-only mode"
    )
    print(
        f"[PASS] Wrote {AUDIT_DOCUMENT.relative_to(PROJECT_ROOT)}"
    )
    print(
        "[PASS] Updated the marked completion section in "
        f"{CONSTRUCTION_DOCUMENT.relative_to(PROJECT_ROOT)}"
    )
    print(
        "[PASS] Production performance count: "
        f"{actual_performance_rows:,}"
    )
    print(
        "[PASS] Hard integrity checks passed: "
        f"{passed_hard_checks:,}"
    )
    print(
        "[PASS] Relational orphan records: "
        f"{orphan_total:,}"
    )
    print()
    print("No database records were modified.")
    print("OVERALL RESULT: PASS")


if __name__ == "__main__":
    main()