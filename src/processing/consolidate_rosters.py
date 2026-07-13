import pandas as pd

import sys
from pathlib import Path


sys.path.append(
    str(Path(__file__).resolve().parents[1])
)


from config import RAW_FOLDER


HISTORICAL_ROSTER_FOLDER = (
    RAW_FOLDER /
    "historical_rosters"
)


ALL_ROSTERS_FILE = (
    RAW_FOLDER /
    "all_roster_records.csv"
)


UNIQUE_ATHLETES_FILE = (
    RAW_FOLDER /
    "unique_athletes.csv"
)


def main():

    csv_files = list(
        HISTORICAL_ROSTER_FOLDER.rglob("*.csv")
    )


    print(
        "Roster files found:",
        len(csv_files)
    )


    roster_data = []


    for index, file in enumerate(
        csv_files,
        start=1
    ):

        try:

            df = pd.read_csv(
                file
            )


            if len(df) == 0:
                continue


            roster_data.append(
                df
            )


            if index % 1000 == 0:

                print(
                    f"Loaded {index}/{len(csv_files)} files"
                )


        except Exception as e:

            print(
                "FAILED:",
                file,
                e
            )


    if len(roster_data) == 0:

        print(
            "No roster data found."
        )

        return


    print(
        "\nCombining roster records..."
    )


    all_rosters = pd.concat(
        roster_data,
        ignore_index=True
    )


    all_rosters.to_csv(
        ALL_ROSTERS_FILE,
        index=False
    )


    print(
        "Total roster records:",
        len(all_rosters)
    )


    print(
        "\nFinding unique athletes..."
    )


    unique_athletes = (
        all_rosters
        .drop_duplicates(
            subset=[
                "athlete_id"
            ]
        )
        .copy()
    )


    unique_athletes = unique_athletes[
        [
            "athlete_id",
            "athlete_name",
            "school",
            "team_id"
        ]
    ]


    unique_athletes["athlete_url"] = (
        "https://www.tfrrs.org/athletes/"
        +
        unique_athletes[
            "athlete_id"
        ].astype(str)
        +
        ".html"
    )


    unique_athletes.to_csv(
        UNIQUE_ATHLETES_FILE,
        index=False
    )


    print(
        "Unique athletes:",
        len(unique_athletes)
    )


    print(
        "\nSaved:"
    )


    print(
        ALL_ROSTERS_FILE
    )


    print(
        UNIQUE_ATHLETES_FILE
    )


if __name__ == "__main__":
    main()