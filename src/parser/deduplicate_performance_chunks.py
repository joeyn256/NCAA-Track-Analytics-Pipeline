import argparse
import os
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


REMOVED_ROWS_FILE = (
    AUDIT_FOLDER /
    "removed_duplicate_performance_rows.csv"
)


DEDUPLICATION_REPORT_FILE = (
    AUDIT_FOLDER /
    "performance_deduplication_report.md"
)


ALLOWED_DIFFERING_FIELDS = {
    "highlighted"
}


TRUTHY_VALUES = {
    "true",
    "1",
    "yes",
    "y",
    "t"
}


def parse_arguments():

    parser = argparse.ArgumentParser(
        description=(
            "Inspect and safely remove duplicate "
            "performance IDs from production chunks."
        )
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Rewrite performance and status chunks. "
            "Without this flag, only a dry-run analysis "
            "is performed."
        )
    )

    return parser.parse_args()


def extract_chunk_number(
        file_path
):

    return int(
        file_path
        .stem
        .split("_")[-1]
    )


def atomic_write_csv(
        dataframe,
        output_file
):

    temporary_file = output_file.with_name(
        output_file.name +
        ".tmp"
    )

    dataframe.to_csv(
        temporary_file,
        index=False
    )

    os.replace(
        temporary_file,
        output_file
    )


def normalize_highlighted(
        series
):

    return (
        series
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(
            TRUTHY_VALUES
        )
    )


def inspect_chunk(
        dataframe
):

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
    ]

    exact_groups = 0
    exact_extra_rows = 0

    highlighted_groups = 0
    highlighted_extra_rows = 0

    unexpected_groups = []

    resolution_by_id = {}

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

        extra_rows = (
            len(group) - 1
        )

        if not differing_fields:

            exact_groups += 1
            exact_extra_rows += (
                extra_rows
            )

            resolution_by_id[
                performance_id
            ] = "exact_duplicate"

        elif set(
            differing_fields
        ).issubset(
            ALLOWED_DIFFERING_FIELDS
        ):

            highlighted_groups += 1
            highlighted_extra_rows += (
                extra_rows
            )

            resolution_by_id[
                performance_id
            ] = "highlighted_merged"

        else:

            unexpected_groups.append(
                {
                    "performance_id":
                        performance_id,
                    "differing_fields":
                        " | ".join(
                            differing_fields
                        ),
                    "row_count":
                        len(group)
                }
            )

    return {
        "duplicate_mask":
            duplicate_mask,
        "resolution_by_id":
            resolution_by_id,
        "exact_groups":
            exact_groups,
        "exact_extra_rows":
            exact_extra_rows,
        "highlighted_groups":
            highlighted_groups,
        "highlighted_extra_rows":
            highlighted_extra_rows,
        "unexpected_groups":
            unexpected_groups
    }


def update_status_counts(
        status_dataframe,
        performance_dataframe
):

    performance_counts = (
        performance_dataframe
        .groupby(
            "athlete_id"
        )
        .size()
    )

    status_dataframe = (
        status_dataframe.copy()
    )

    status_dataframe[
        "athlete_id"
    ] = (
        status_dataframe[
            "athlete_id"
        ]
        .astype(str)
        .str.strip()
    )

    status_dataframe[
        "performance_rows"
    ] = (
        status_dataframe[
            "athlete_id"
        ]
        .map(
            performance_counts
        )
        .fillna(0)
        .astype(int)
    )

    not_failed = (
        status_dataframe[
            "status"
        ] != "failed"
    )

    has_performances = (
        status_dataframe[
            "performance_rows"
        ] > 0
    )

    status_dataframe.loc[
        not_failed
        &
        has_performances,
        "status"
    ] = "parsed"

    status_dataframe.loc[
        not_failed
        &
        ~has_performances,
        "status"
    ] = "empty"

    return status_dataframe


def analyze_files(
        performance_files
):

    totals = {
        "performance_rows_before": 0,
        "duplicate_groups": 0,
        "additional_duplicate_rows": 0,
        "exact_groups": 0,
        "exact_extra_rows": 0,
        "highlighted_groups": 0,
        "highlighted_extra_rows": 0
    }

    unexpected_groups = []

    print(
        "\nDEDUPLICATION SAFETY ANALYSIS"
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

        required_columns = {
            "performance_id",
            "athlete_id",
            "highlighted"
        }

        missing_columns = (
            required_columns
            -
            set(
                dataframe.columns
            )
        )

        if missing_columns:

            raise ValueError(
                f"{performance_file.name} is missing: "
                f"{sorted(missing_columns)}"
            )

        inspection = inspect_chunk(
            dataframe
        )

        exact_groups = inspection[
            "exact_groups"
        ]

        highlighted_groups = inspection[
            "highlighted_groups"
        ]

        exact_extra_rows = inspection[
            "exact_extra_rows"
        ]

        highlighted_extra_rows = inspection[
            "highlighted_extra_rows"
        ]

        totals[
            "performance_rows_before"
        ] += len(
            dataframe
        )

        totals[
            "exact_groups"
        ] += exact_groups

        totals[
            "highlighted_groups"
        ] += highlighted_groups

        totals[
            "exact_extra_rows"
        ] += exact_extra_rows

        totals[
            "highlighted_extra_rows"
        ] += highlighted_extra_rows

        totals[
            "duplicate_groups"
        ] += (
            exact_groups
            +
            highlighted_groups
        )

        totals[
            "additional_duplicate_rows"
        ] += (
            exact_extra_rows
            +
            highlighted_extra_rows
        )

        for unexpected_group in inspection[
            "unexpected_groups"
        ]:

            unexpected_group[
                "chunk_file"
            ] = performance_file.name

            unexpected_groups.append(
                unexpected_group
            )

        if (
            file_index == 1
            or file_index % 20 == 0
            or file_index
            == len(performance_files)
        ):

            print(
                f"Analyzed chunk "
                f"{file_index:05d}/"
                f"{len(performance_files):05d}"
            )

    return (
        totals,
        unexpected_groups
    )


def apply_deduplication(
        performance_files
):

    removed_frames = []

    rows_before = 0
    rows_after = 0

    print(
        "\nAPPLYING DEDUPLICATION"
    )

    for file_index, performance_file in enumerate(
        performance_files,
        start=1
    ):

        chunk_number = extract_chunk_number(
            performance_file
        )

        status_file = (
            STATUS_FOLDER /
            f"status_{chunk_number:05d}.csv"
        )

        if not status_file.exists():

            raise FileNotFoundError(
                f"Status file not found: "
                f"{status_file}"
            )

        dataframe = pd.read_csv(
            performance_file,
            dtype=str,
            keep_default_na=False
        )

        status_dataframe = pd.read_csv(
            status_file,
            dtype=str,
            keep_default_na=False
        )

        inspection = inspect_chunk(
            dataframe
        )

        if inspection[
            "unexpected_groups"
        ]:

            raise ValueError(
                "Unexpected duplicate differences were "
                f"found in {performance_file.name}."
            )

        duplicate_mask = inspection[
            "duplicate_mask"
        ]

        rows_before += len(
            dataframe
        )

        if duplicate_mask.any():

            duplicate_highlighted = (
                normalize_highlighted(
                    dataframe[
                        "highlighted"
                    ]
                )
            )

            merged_highlighted = (
                duplicate_highlighted
                .groupby(
                    dataframe[
                        "performance_id"
                    ]
                )
                .transform(
                    "max"
                )
            )

            dataframe.loc[
                duplicate_mask,
                "highlighted"
            ] = (
                merged_highlighted.loc[
                    duplicate_mask
                ]
                .map(
                    {
                        True: "True",
                        False: "False"
                    }
                )
            )

            keep_mask = (
                ~dataframe.duplicated(
                    subset=[
                        "performance_id"
                    ],
                    keep="first"
                )
            )

            removed_rows = dataframe.loc[
                ~keep_mask
            ].copy()

            removed_rows.insert(
                0,
                "chunk_file",
                performance_file.name
            )

            removed_rows.insert(
                1,
                "duplicate_resolution",
                removed_rows[
                    "performance_id"
                ].map(
                    inspection[
                        "resolution_by_id"
                    ]
                )
            )

            removed_frames.append(
                removed_rows
            )

            deduplicated_dataframe = (
                dataframe.loc[
                    keep_mask
                ]
                .copy()
            )

        else:

            deduplicated_dataframe = (
                dataframe.copy()
            )

        updated_status_dataframe = (
            update_status_counts(
                status_dataframe,
                deduplicated_dataframe
            )
        )

        atomic_write_csv(
            deduplicated_dataframe,
            performance_file
        )

        atomic_write_csv(
            updated_status_dataframe,
            status_file
        )

        rows_after += len(
            deduplicated_dataframe
        )

        if (
            file_index == 1
            or file_index % 20 == 0
            or file_index
            == len(performance_files)
        ):

            print(
                f"Updated chunk "
                f"{file_index:05d}/"
                f"{len(performance_files):05d}"
            )

    if removed_frames:

        removed_rows_dataframe = pd.concat(
            removed_frames,
            ignore_index=True
        )

    else:

        removed_rows_dataframe = pd.DataFrame()

    removed_rows_dataframe.to_csv(
        REMOVED_ROWS_FILE,
        index=False
    )

    return {
        "rows_before":
            rows_before,
        "rows_after":
            rows_after,
        "rows_removed":
            rows_before - rows_after
    }


def write_report(
        totals,
        unexpected_groups,
        apply_result=None
):

    expected_rows_after = (
        totals[
            "performance_rows_before"
        ]
        -
        totals[
            "additional_duplicate_rows"
        ]
    )

    report_lines = [
        "# Performance Deduplication Report",
        "",
        "## Safety Analysis",
        "",
        (
            f"- Performance rows before: "
            f"**{totals['performance_rows_before']:,}**"
        ),
        (
            f"- Duplicate ID groups: "
            f"**{totals['duplicate_groups']:,}**"
        ),
        (
            f"- Additional duplicate rows: "
            f"**{totals['additional_duplicate_rows']:,}**"
        ),
        (
            f"- Exact duplicate groups: "
            f"**{totals['exact_groups']:,}**"
        ),
        (
            f"- Exact duplicate rows removed: "
            f"**{totals['exact_extra_rows']:,}**"
        ),
        (
            f"- Highlight-only groups: "
            f"**{totals['highlighted_groups']:,}**"
        ),
        (
            f"- Highlight-only rows removed: "
            f"**{totals['highlighted_extra_rows']:,}**"
        ),
        (
            f"- Unexpected differing groups: "
            f"**{len(unexpected_groups):,}**"
        ),
        (
            f"- Expected rows after cleanup: "
            f"**{expected_rows_after:,}**"
        ),
        ""
    ]

    if apply_result is None:

        report_lines.extend(
            [
                "## Status",
                "",
                "**Dry run only — no files modified.**",
                ""
            ]
        )

    else:

        report_lines.extend(
            [
                "## Applied Results",
                "",
                (
                    f"- Rows before: "
                    f"**{apply_result['rows_before']:,}**"
                ),
                (
                    f"- Rows after: "
                    f"**{apply_result['rows_after']:,}**"
                ),
                (
                    f"- Rows removed: "
                    f"**{apply_result['rows_removed']:,}**"
                ),
                "",
                (
                    "Rows that were removed are preserved in "
                    "`removed_duplicate_performance_rows.csv`."
                ),
                ""
            ]
        )

    DEDUPLICATION_REPORT_FILE.write_text(
        "\n".join(
            report_lines
        ),
        encoding="utf-8"
    )


def main():

    arguments = parse_arguments()

    performance_files = sorted(
        PERFORMANCE_FOLDER.glob(
            "performances_*.csv"
        )
    )

    if not performance_files:

        raise FileNotFoundError(
            "No performance chunks were found in "
            f"{PERFORMANCE_FOLDER}"
        )

    (
        totals,
        unexpected_groups
    ) = analyze_files(
        performance_files
    )

    print(
        "\nSAFETY ANALYSIS COMPLETE"
    )

    print(
        "Performance rows before:",
        f"{totals['performance_rows_before']:,}"
    )

    print(
        "Duplicate ID groups:",
        f"{totals['duplicate_groups']:,}"
    )

    print(
        "Additional duplicate rows:",
        f"{totals['additional_duplicate_rows']:,}"
    )

    print(
        "Exact duplicate groups:",
        f"{totals['exact_groups']:,}"
    )

    print(
        "Exact additional rows:",
        f"{totals['exact_extra_rows']:,}"
    )

    print(
        "Highlight-only groups:",
        f"{totals['highlighted_groups']:,}"
    )

    print(
        "Highlight-only additional rows:",
        f"{totals['highlighted_extra_rows']:,}"
    )

    print(
        "Unexpected differing groups:",
        f"{len(unexpected_groups):,}"
    )

    expected_rows_after = (
        totals[
            "performance_rows_before"
        ]
        -
        totals[
            "additional_duplicate_rows"
        ]
    )

    print(
        "Expected rows after cleanup:",
        f"{expected_rows_after:,}"
    )

    if unexpected_groups:

        write_report(
            totals,
            unexpected_groups
        )

        raise ValueError(
            "Unexpected duplicate differences were found. "
            "No files were modified."
        )

    if not arguments.apply:

        write_report(
            totals,
            unexpected_groups
        )

        print(
            "\nDRY RUN COMPLETE"
        )

        print(
            "No production files were modified."
        )

        print(
            "Run again with --apply after confirming "
            "the totals above."
        )

        return

    apply_result = apply_deduplication(
        performance_files
    )

    write_report(
        totals,
        unexpected_groups,
        apply_result
    )

    print(
        "\nDEDUPLICATION COMPLETE"
    )

    print(
        "Rows before:",
        f"{apply_result['rows_before']:,}"
    )

    print(
        "Rows after:",
        f"{apply_result['rows_after']:,}"
    )

    print(
        "Rows removed:",
        f"{apply_result['rows_removed']:,}"
    )

    print(
        "\nRemoved rows preserved at:"
    )

    print(
        REMOVED_ROWS_FILE
    )

    print(
        "\nReport saved at:"
    )

    print(
        DEDUPLICATION_REPORT_FILE
    )


if __name__ == "__main__":
    main()