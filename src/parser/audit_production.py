import sys
from pathlib import Path

import pandas as pd


SRC_FOLDER = (
    Path(__file__)
    .resolve()
    .parents[1]
)

sys.path.insert(
    0,
    str(SRC_FOLDER)
)


from config import RAW_FOLDER


PROCESSED_FOLDER = (
    RAW_FOLDER.parent /
    "processed"
)


PERFORMANCE_FOLDER = (
    PROCESSED_FOLDER /
    "performance_chunks"
)


STATUS_FOLDER = (
    PROCESSED_FOLDER /
    "parser_checkpoints" /
    "chunk_status"
)


AUDIT_FOLDER = (
    PROCESSED_FOLDER /
    "parser_audit"
)


AUDIT_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


EXPECTED_CHUNKS = 194


VALID_SEASON_TYPES = {
    "Indoor",
    "Outdoor",
    "Cross Country"
}


def extract_chunk_number(
        file_path
):

    return int(
        file_path
        .stem
        .split("_")[-1]
    )


def main():

    performance_files = sorted(
        PERFORMANCE_FOLDER.glob(
            "performances_*.csv"
        )
    )

    status_files = sorted(
        STATUS_FOLDER.glob(
            "status_*.csv"
        )
    )

    performance_chunks = {
        extract_chunk_number(
            file_path
        ): file_path
        for file_path in performance_files
    }

    status_chunks = {
        extract_chunk_number(
            file_path
        ): file_path
        for file_path in status_files
    }

    expected_chunk_numbers = set(
        range(
            1,
            EXPECTED_CHUNKS + 1
        )
    )

    missing_performance_chunks = sorted(
        expected_chunk_numbers
        -
        set(
            performance_chunks
        )
    )

    missing_status_chunks = sorted(
        expected_chunk_numbers
        -
        set(
            status_chunks
        )
    )

    total_pages = 0
    total_parsed = 0
    total_empty = 0
    total_failed = 0
    total_status_performance_rows = 0

    total_performance_rows = 0
    missing_performance_ids = 0
    duplicate_performance_ids = 0
    missing_athlete_ids = 0
    missing_season_types = 0
    invalid_season_types = 0
    missing_events = 0
    missing_marks = 0
    missing_source_files = 0

    chunk_summaries = []
    audit_issues = []

    print(
        "\nPRODUCTION PARSER AUDIT"
    )

    print(
        "Performance chunks found:",
        len(
            performance_files
        )
    )

    print(
        "Status chunks found:",
        len(
            status_files
        )
    )

    for chunk_number in sorted(
        expected_chunk_numbers
    ):

        performance_file = (
            performance_chunks.get(
                chunk_number
            )
        )

        status_file = (
            status_chunks.get(
                chunk_number
            )
        )

        if (
            performance_file is None
            or status_file is None
        ):

            continue

        status_df = pd.read_csv(
            status_file,
            dtype=str
        ).fillna("")

        chunk_pages = len(
            status_df
        )

        chunk_parsed = int(
            (
                status_df["status"]
                == "parsed"
            ).sum()
        )

        chunk_empty = int(
            (
                status_df["status"]
                == "empty"
            ).sum()
        )

        chunk_failed = int(
            (
                status_df["status"]
                == "failed"
            ).sum()
        )

        status_row_total = int(
            pd.to_numeric(
                status_df[
                    "performance_rows"
                ],
                errors="coerce"
            )
            .fillna(0)
            .sum()
        )

        chunk_performance_rows = 0
        chunk_missing_ids = 0
        chunk_duplicate_ids = 0
        chunk_missing_seasons = 0
        chunk_invalid_seasons = 0

        seen_performance_ids = set()

        for dataframe in pd.read_csv(
            performance_file,
            dtype=str,
            chunksize=100000
        ):

            dataframe = dataframe.fillna("")

            chunk_performance_rows += len(
                dataframe
            )

            performance_ids = (
                dataframe[
                    "performance_id"
                ]
                .astype(str)
                .str.strip()
            )

            chunk_missing_ids += int(
                performance_ids
                .eq("")
                .sum()
            )

            for performance_id in performance_ids:

                if not performance_id:

                    continue

                if performance_id in seen_performance_ids:

                    chunk_duplicate_ids += 1

                else:

                    seen_performance_ids.add(
                        performance_id
                    )

            athlete_ids = (
                dataframe[
                    "athlete_id"
                ]
                .astype(str)
                .str.strip()
            )

            season_types = (
                dataframe[
                    "season_type"
                ]
                .astype(str)
                .str.strip()
            )

            events = (
                dataframe[
                    "event"
                ]
                .astype(str)
                .str.strip()
            )

            marks = (
                dataframe[
                    "mark"
                ]
                .astype(str)
                .str.strip()
            )

            source_files = (
                dataframe[
                    "source_file"
                ]
                .astype(str)
                .str.strip()
            )

            missing_athlete_ids += int(
                athlete_ids
                .eq("")
                .sum()
            )

            chunk_missing_seasons += int(
                season_types
                .eq("")
                .sum()
            )

            chunk_invalid_seasons += int(
                (
                    season_types.ne("")
                    &
                    ~season_types.isin(
                        VALID_SEASON_TYPES
                    )
                ).sum()
            )

            missing_events += int(
                events
                .eq("")
                .sum()
            )

            missing_marks += int(
                marks
                .eq("")
                .sum()
            )

            missing_source_files += int(
                source_files
                .eq("")
                .sum()
            )

        row_counts_match = (
            chunk_performance_rows
            == status_row_total
        )

        if not row_counts_match:

            audit_issues.append(
                {
                    "chunk_number":
                        chunk_number,
                    "issue":
                        "performance_row_mismatch",
                    "details":
                        (
                            f"Status files report "
                            f"{status_row_total:,} rows, "
                            f"but performance file contains "
                            f"{chunk_performance_rows:,} rows."
                        )
                }
            )

        if chunk_failed:

            audit_issues.append(
                {
                    "chunk_number":
                        chunk_number,
                    "issue":
                        "failed_athletes",
                    "details":
                        (
                            f"{chunk_failed:,} athlete "
                            f"pages failed."
                        )
                }
            )

        if chunk_missing_ids:

            audit_issues.append(
                {
                    "chunk_number":
                        chunk_number,
                    "issue":
                        "missing_performance_ids",
                    "details":
                        (
                            f"{chunk_missing_ids:,} rows "
                            f"have no performance ID."
                        )
                }
            )

        if chunk_duplicate_ids:

            audit_issues.append(
                {
                    "chunk_number":
                        chunk_number,
                    "issue":
                        "duplicate_performance_ids",
                    "details":
                        (
                            f"{chunk_duplicate_ids:,} repeated "
                            f"performance IDs were found."
                        )
                }
            )

        if chunk_missing_seasons:

            audit_issues.append(
                {
                    "chunk_number":
                        chunk_number,
                    "issue":
                        "missing_season_types",
                    "details":
                        (
                            f"{chunk_missing_seasons:,} rows "
                            f"have no season type."
                        )
                }
            )

        if chunk_invalid_seasons:

            audit_issues.append(
                {
                    "chunk_number":
                        chunk_number,
                    "issue":
                        "invalid_season_types",
                    "details":
                        (
                            f"{chunk_invalid_seasons:,} rows "
                            f"have an unexpected season type."
                        )
                }
            )

        chunk_summaries.append(
            {
                "chunk_number":
                    chunk_number,
                "athlete_pages":
                    chunk_pages,
                "parsed_athletes":
                    chunk_parsed,
                "empty_athletes":
                    chunk_empty,
                "failed_athletes":
                    chunk_failed,
                "status_performance_rows":
                    status_row_total,
                "file_performance_rows":
                    chunk_performance_rows,
                "row_counts_match":
                    row_counts_match,
                "missing_performance_ids":
                    chunk_missing_ids,
                "duplicate_performance_ids":
                    chunk_duplicate_ids,
                "missing_season_types":
                    chunk_missing_seasons,
                "invalid_season_types":
                    chunk_invalid_seasons
            }
        )

        total_pages += chunk_pages
        total_parsed += chunk_parsed
        total_empty += chunk_empty
        total_failed += chunk_failed

        total_status_performance_rows += (
            status_row_total
        )

        total_performance_rows += (
            chunk_performance_rows
        )

        missing_performance_ids += (
            chunk_missing_ids
        )

        duplicate_performance_ids += (
            chunk_duplicate_ids
        )

        missing_season_types += (
            chunk_missing_seasons
        )

        invalid_season_types += (
            chunk_invalid_seasons
        )

        if (
            chunk_number == 1
            or chunk_number % 20 == 0
            or chunk_number == EXPECTED_CHUNKS
        ):

            print(
                f"Audited chunk "
                f"{chunk_number:05d}/"
                f"{EXPECTED_CHUNKS:05d}"
            )

    chunk_summary_df = pd.DataFrame(
        chunk_summaries
    )

    issues_df = pd.DataFrame(
        audit_issues,
        columns=[
            "chunk_number",
            "issue",
            "details"
        ]
    )

    chunk_summary_file = (
        AUDIT_FOLDER /
        "production_chunk_summary.csv"
    )

    issues_file = (
        AUDIT_FOLDER /
        "production_audit_issues.csv"
    )

    report_file = (
        AUDIT_FOLDER /
        "production_parser_audit.md"
    )

    chunk_summary_df.to_csv(
        chunk_summary_file,
        index=False
    )

    issues_df.to_csv(
        issues_file,
        index=False
    )

    audit_passed = (
        not missing_performance_chunks
        and not missing_status_chunks
        and total_failed == 0
        and total_status_performance_rows
        == total_performance_rows
        and missing_performance_ids == 0
        and duplicate_performance_ids == 0
        and missing_athlete_ids == 0
        and missing_season_types == 0
        and invalid_season_types == 0
        and missing_events == 0
        and missing_source_files == 0
    )

    report_lines = [
        "# Production Parser Audit",
        "",
        "## Result",
        "",
        (
            "**PASS**"
            if audit_passed
            else "**REVIEW REQUIRED**"
        ),
        "",
        "## Dataset Totals",
        "",
        (
            f"- Performance chunks: "
            f"**{len(performance_files):,}**"
        ),
        (
            f"- Status chunks: "
            f"**{len(status_files):,}**"
        ),
        (
            f"- Athlete pages: "
            f"**{total_pages:,}**"
        ),
        (
            f"- Parsed athletes: "
            f"**{total_parsed:,}**"
        ),
        (
            f"- Empty athletes: "
            f"**{total_empty:,}**"
        ),
        (
            f"- Failed athletes: "
            f"**{total_failed:,}**"
        ),
        (
            f"- Performance records: "
            f"**{total_performance_rows:,}**"
        ),
        "",
        "## Quality Checks",
        "",
        (
            f"- Missing performance chunks: "
            f"**{len(missing_performance_chunks):,}**"
        ),
        (
            f"- Missing status chunks: "
            f"**{len(missing_status_chunks):,}**"
        ),
        (
            f"- Missing performance IDs: "
            f"**{missing_performance_ids:,}**"
        ),
        (
            f"- Duplicate performance IDs: "
            f"**{duplicate_performance_ids:,}**"
        ),
        (
            f"- Missing athlete IDs: "
            f"**{missing_athlete_ids:,}**"
        ),
        (
            f"- Missing season types: "
            f"**{missing_season_types:,}**"
        ),
        (
            f"- Invalid season types: "
            f"**{invalid_season_types:,}**"
        ),
        (
            f"- Missing event names: "
            f"**{missing_events:,}**"
        ),
        (
            f"- Missing marks: "
            f"**{missing_marks:,}**"
        ),
        (
            f"- Missing source files: "
            f"**{missing_source_files:,}**"
        ),
        (
            f"- Status and performance row totals match: "
            f"**{total_status_performance_rows == total_performance_rows}**"
        ),
        "",
        "## Audit Issues",
        "",
        (
            f"- Issues requiring review: "
            f"**{len(issues_df):,}**"
        ),
        ""
    ]

    report_file.write_text(
        "\n".join(
            report_lines
        ),
        encoding="utf-8"
    )

    print(
        "\nPRODUCTION AUDIT COMPLETE"
    )

    print(
        "Audit result:",
        (
            "PASS"
            if audit_passed
            else "REVIEW REQUIRED"
        )
    )

    print(
        "Athlete pages:",
        f"{total_pages:,}"
    )

    print(
        "Parsed athletes:",
        f"{total_parsed:,}"
    )

    print(
        "Empty athletes:",
        f"{total_empty:,}"
    )

    print(
        "Failed athletes:",
        f"{total_failed:,}"
    )

    print(
        "Performance records:",
        f"{total_performance_rows:,}"
    )

    print(
        "Duplicate performance IDs:",
        f"{duplicate_performance_ids:,}"
    )

    print(
        "Missing season types:",
        f"{missing_season_types:,}"
    )

    print(
        "Audit issues:",
        f"{len(issues_df):,}"
    )

    print(
        "\nSaved report:"
    )

    print(
        report_file
    )


if __name__ == "__main__":
    main()