import sys
from pathlib import Path

import pandas as pd
import time
import random


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


SRC_FOLDER = (
    PROJECT_ROOT /
    "src"
)


sys.path.insert(
    0,
    str(SRC_FOLDER)
)


from config import RAW_FOLDER
from scraper.tfrrs_utils import get_page


ATHLETE_FILE = (
    RAW_FOLDER /
    "unique_athletes.csv"
)


OUTPUT_FOLDER = (
    RAW_FOLDER /
    "athlete_pages"
)


OUTPUT_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


TEST_LIMIT = 5


def main():

    athletes = pd.read_csv(
        ATHLETE_FILE
    )


    print(
        "Total athletes available:",
        len(athletes)
    )


    athletes = athletes.head(
        TEST_LIMIT
    )


    print(
        "TEST MODE: Downloading",
        len(athletes),
        "athlete pages"
    )


    for index, (_, athlete) in enumerate(
        athletes.iterrows(),
        start=1
    ):

        athlete_id = str(
            athlete["athlete_id"]
        )


        athlete_name = str(
            athlete["athlete_name"]
        )


        athlete_url = (
            "https://www.tfrrs.org/athletes/"
            f"{athlete_id}.html"
        )


        output_file = (
            OUTPUT_FOLDER /
            f"{athlete_id}.html"
        )


        print(
            f"[{index}/{len(athletes)}]",
            athlete_name,
            athlete_id
        )


        if output_file.exists():

            print(
                "Already downloaded. SKIP"
            )

            continue


        try:

            html = get_page(
                athlete_url
            )


            if not html.strip():

                raise ValueError(
                    "Downloaded page was empty."
                )


            with open(
                output_file,
                "w",
                encoding="utf-8"
            ) as file:

                file.write(
                    html
                )


            print(
                "SAVED"
            )


        except Exception as error:

            print(
                "FAILED:",
                athlete_name,
                error
            )


        time.sleep(
            random.uniform(
                0.5,
                0.75
            )
        )


    print(
        "\nTEST COMPLETE"
    )


if __name__ == "__main__":
    main()