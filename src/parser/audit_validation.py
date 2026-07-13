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


VALIDATION_FOLDER = (
    RAW_FOLDER.parent /
    "processed" /
    "parser_validation"
)


PERFORMANCES_FILE = (
    VALIDATION_FOLDER /
    "validation_performances.csv"
)


def main():

    if not PERFORMANCES_FILE.exists():

        raise FileNotFoundError(
            f"Validation file not found: "
            f"{PERFORMANCES_FILE}"
        )

    performances = pd.read_csv(
        PERFORMANCES_FILE,
        dtype=str
    ).fillna("")

    missing_season_rows = performances[
        performances[
            "season_type"
        ]
        .str.strip()
        .eq("")
    ].copy()

    repeated_result_mask = (
        performances[
            "result_id"
        ]
        .str.strip()
        .ne("")
        &
        performances.duplicated(
            subset=[
                "athlete_id",
                "result_id"
            ],
            keep=False
        )
    )

    repeated_result_rows = performances[
        repeated_result_mask
    ].copy()

    exact_duplicate_mask = (
        performances.duplicated(
            keep=False
        )
    )

    exact_duplicate_rows = performances[
        exact_duplicate_mask
    ].copy()

    repeated_result_rows = (
        repeated_result_rows.sort_values(
            by=[
                "athlete_id",
                "result_id",
                "event",
                "meet_date_text"
            ]
        )
    )

    missing_season_file = (
        VALIDATION_FOLDER /
        "missing_season_rows.csv"
    )

    repeated_result_file = (
        VALIDATION_FOLDER /
        "repeated_result_id_rows.csv"
    )

    exact_duplicate_file = (
        VALIDATION_FOLDER /
        "exact_duplicate_rows.csv"
    )

    missing_season_rows.to_csv(
        missing_season_file,
        index=False
    )

    repeated_result_rows.to_csv(
        repeated_result_file,
        index=False
    )

    exact_duplicate_rows.to_csv(
        exact_duplicate_file,
        index=False
    )

    print(
        "\nVALIDATION AUDIT COMPLETE"
    )

    print(
        "Total performance rows:",
        f"{len(performances):,}"
    )

    print(
        "Missing season rows:",
        f"{len(missing_season_rows):,}"
    )

    print(
        "Repeated athlete/result ID rows:",
        f"{len(repeated_result_rows):,}"
    )

    print(
        "Exact duplicate rows:",
        f"{len(exact_duplicate_rows):,}"
    )

    if not missing_season_rows.empty:

        print(
            "\nMissing season labels:"
        )

        print(
            missing_season_rows[
                "season_label"
            ]
            .replace(
                "",
                "[missing]"
            )
            .value_counts()
            .to_string()
        )

    if not repeated_result_rows.empty:

        print(
            "\nFirst repeated result-ID rows:"
        )

        columns_to_display = [
            "athlete_id",
            "athlete_name",
            "season_type",
            "meet_name",
            "event",
            "mark",
            "place",
            "competition_round",
            "result_id"
        ]

        print(
            repeated_result_rows[
                columns_to_display
            ]
            .head(30)
            .to_string(
                index=False
            )
        )

    print(
        "\nSaved:"
    )

    print(
        missing_season_file
    )

    print(
        repeated_result_file
    )

    print(
        exact_duplicate_file
    )


if __name__ == "__main__":
    main()