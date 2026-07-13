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


AUDIT_FOLDER = (
    PROCESSED_FOLDER /
    "parser_audit"
)


AUDIT_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


DUPLICATE_ROWS_FILE = (
    AUDIT_FOLDER /
    "duplicate_performance_id_rows.csv"
)


DUPLICATE_GROUPS_FILE = (
    AUDIT_FOLDER /
    "duplicate_performance_id_groups.csv"
)


DUPLICATE_REPORT_FILE = (
    AUDIT_FOLDER /
    "duplicate_performance_id_report.md"
)


def main():

    performance_files = sorted(
        PERFORMANCE_FOLDER.glob(
            "performances_*.csv"
        )
    )

    if not performance_files:

        raise FileNotFoundError(
            "No performance chunk files were found in "
            f"{PERFORMANCE_FOLDER}"
        )

    duplicate_frames = []
    group_summaries = []

    files_with_duplicates = 0
    total_duplicate_group_rows = 0

    print(
        "\nDUPLICATE PERFORMANCE ID INSPECTION"
    )

    print(
        "Performance chunks found:",
        f"{len(performance_files):,}"
    )

    for file_index, performance_file in enumerate(
        performance_files,
        start=1
    ):

        dataframe = pd.read_csv(
            performance_file,
            dtype=str,
            keep_default_na=False
        )

        if "performance_id" not in dataframe.columns:

            raise ValueError(
                f"{performance_file.name} does not contain "
                "a performance_id column."
            )

        performance_ids = (
            dataframe[
                "performance_id"
            ]
            .astype(str)
            .str.strip()
        )

        duplicate_mask = (
            performance_ids.ne("")
            &
            dataframe.duplicated(
                subset=[
                    "performance_id"
                ],
                keep=False
            )
        )

        duplicate_rows = dataframe[
            duplicate_mask
        ].copy()

        if not duplicate_rows.empty:

            files_with_duplicates += 1

            duplicate_rows.insert(
                0,
                "chunk_file",
                performance_file.name
            )

            duplicate_frames.append(
                duplicate_rows
            )

            comparison_columns = [
                column
                for column in dataframe.columns
                if column != "performance_id"
            ]

            for performance_id, group in (
                duplicate_rows.groupby(
                    "performance_id",
                    sort=False
                )
            ):

                differing_fields = [
                    column
                    for column in comparison_columns
                    if group[
                        column
                    ].nunique(
                        dropna=False
                    ) > 1
                ]

                exact_duplicate = (
                    len(
                        differing_fields
                    )
                    == 0
                )

                first_row = group.iloc[0]

                group_summaries.append(
                    {
                        "chunk_file":
                            performance_file.name,
                        "performance_id":
                            performance_id,
                        "row_count":
                            len(group),
                        "extra_row_count":
                            len(group) - 1,
                        "exact_duplicate":
                            exact_duplicate,
                        "differing_fields":
                            " | ".join(
                                differing_fields
                            ),
                        "athlete_id":
                            first_row.get(
                                "athlete_id",
                                ""
                            ),
                        "athlete_name":
                            first_row.get(
                                "athlete_name",
                                ""
                            ),
                        "season_type":
                            first_row.get(
                                "season_type",
                                ""
                            ),
                        "meet_id":
                            first_row.get(
                                "meet_id",
                                ""
                            ),
                        "meet_name":
                            first_row.get(
                                "meet_name",
                                ""
                            ),
                        "event":
                            first_row.get(
                                "event",
                                ""
                            ),
                        "mark":
                            first_row.get(
                                "mark",
                                ""
                            ),
                        "competition_round":
                            first_row.get(
                                "competition_round",
                                ""
                            ),
                        "result_id":
                            first_row.get(
                                "result_id",
                                ""
                            ),
                        "source_file":
                            first_row.get(
                                "source_file",
                                ""
                            )
                    }
                )

            total_duplicate_group_rows += len(
                duplicate_rows
            )

        if (
            file_index == 1
            or file_index % 20 == 0
            or file_index == len(
                performance_files
            )
        ):

            print(
                f"Inspected chunk "
                f"{file_index:05d}/"
                f"{len(performance_files):05d}"
            )

    if duplicate_frames:

        all_duplicate_rows = pd.concat(
            duplicate_frames,
            ignore_index=True
        )

    else:

        all_duplicate_rows = pd.DataFrame()

    duplicate_groups = pd.DataFrame(
        group_summaries
    )

    all_duplicate_rows.to_csv(
        DUPLICATE_ROWS_FILE,
        index=False
    )

    duplicate_groups.to_csv(
        DUPLICATE_GROUPS_FILE,
        index=False
    )

    duplicate_group_count = len(
        duplicate_groups
    )

    repeated_row_count = 0
    exact_group_count = 0
    nonexact_group_count = 0
    exact_extra_rows = 0
    nonexact_extra_rows = 0

    if not duplicate_groups.empty:

        repeated_row_count = int(
            duplicate_groups[
                "extra_row_count"
            ]
            .astype(int)
            .sum()
        )

        exact_group_mask = (
            duplicate_groups[
                "exact_duplicate"
            ]
            .astype(bool)
        )

        exact_group_count = int(
            exact_group_mask.sum()
        )

        nonexact_group_count = int(
            (
                ~exact_group_mask
            ).sum()
        )

        exact_extra_rows = int(
            duplicate_groups.loc[
                exact_group_mask,
                "extra_row_count"
            ]
            .astype(int)
            .sum()
        )

        nonexact_extra_rows = int(
            duplicate_groups.loc[
                ~exact_group_mask,
                "extra_row_count"
            ]
            .astype(int)
            .sum()
        )

    differing_field_patterns = []

    if not duplicate_groups.empty:

        differing_field_patterns = (
            duplicate_groups.loc[
                ~duplicate_groups[
                    "exact_duplicate"
                ].astype(bool),
                "differing_fields"
            ]
            .replace(
                "",
                "[none]"
            )
            .value_counts()
            .head(20)
        )

    report_lines = [
        "# Duplicate Performance ID Inspection",
        "",
        "## Summary",
        "",
        (
            f"- Performance chunks inspected: "
            f"**{len(performance_files):,}**"
        ),
        (
            f"- Chunks containing repeated IDs: "
            f"**{files_with_duplicates:,}**"
        ),
        (
            f"- Duplicate ID groups: "
            f"**{duplicate_group_count:,}**"
        ),
        (
            f"- Additional repeated rows: "
            f"**{repeated_row_count:,}**"
        ),
        (
            f"- Exact duplicate groups: "
            f"**{exact_group_count:,}**"
        ),
        (
            f"- Exact additional rows: "
            f"**{exact_extra_rows:,}**"
        ),
        (
            f"- Nonexact duplicate groups: "
            f"**{nonexact_group_count:,}**"
        ),
        (
            f"- Nonexact additional rows: "
            f"**{nonexact_extra_rows:,}**"
        ),
        "",
        "## Most Common Differing-Field Patterns",
        ""
    ]

    if len(
        differing_field_patterns
    ) == 0:

        report_lines.append(
            "- None"
        )

    else:

        for pattern, count in (
            differing_field_patterns.items()
        ):

            report_lines.append(
                f"- `{pattern}`: **{count:,}**"
            )

    report_lines.extend(
        [
            "",
            "## Output Files",
            "",
            "- `duplicate_performance_id_rows.csv`",
            "- `duplicate_performance_id_groups.csv`",
            ""
        ]
    )

    DUPLICATE_REPORT_FILE.write_text(
        "\n".join(
            report_lines
        ),
        encoding="utf-8"
    )

    print(
        "\nDUPLICATE INSPECTION COMPLETE"
    )

    print(
        "Chunks containing repeated IDs:",
        f"{files_with_duplicates:,}"
    )

    print(
        "Duplicate ID groups:",
        f"{duplicate_group_count:,}"
    )

    print(
        "Additional repeated rows:",
        f"{repeated_row_count:,}"
    )

    print(
        "Exact duplicate groups:",
        f"{exact_group_count:,}"
    )

    print(
        "Exact additional rows:",
        f"{exact_extra_rows:,}"
    )

    print(
        "Nonexact duplicate groups:",
        f"{nonexact_group_count:,}"
    )

    print(
        "Nonexact additional rows:",
        f"{nonexact_extra_rows:,}"
    )

    if len(
        differing_field_patterns
    ) > 0:

        print(
            "\nMost common differing-field patterns:"
        )

        print(
            differing_field_patterns.to_string()
        )

    print(
        "\nSaved report:"
    )

    print(
        DUPLICATE_REPORT_FILE
    )

    print(
        "\nSaved duplicate rows:"
    )

    print(
        DUPLICATE_ROWS_FILE
    )

    print(
        "\nSaved duplicate groups:"
    )

    print(
        DUPLICATE_GROUPS_FILE
    )


if __name__ == "__main__":
    main()