import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1])
)

from bs4 import BeautifulSoup
import pandas as pd
import time
import random

from config import (
    ROSTER_FOLDER,
    RAW_FOLDER,
    SEASONS_FOLDER
)

from scraper.tfrrs_utils import get_page


def scrape_roster(html, school_name):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    athletes = []

    tables = soup.find_all("table")

    for table in tables:

        headers = table.find_all("th")

        if headers and "NAME" in headers[0].text:

            rows = table.find_all("tr")[1:]

            for row in rows:

                cols = row.find_all("td")

                if len(cols) >= 2:

                    link = row.find("a")

                    if link:

                        href = link.get("href")

                        athletes.append(
                            {
                                "name": link.text.strip(),
                                "athlete_id": href.split("/")[2],
                                "athlete_url": "https://www.tfrrs.org" + href,
                                "year": cols[1].text.strip(),
                                "school": school_name
                            }
                        )

    return athletes


def scrape_school_roster(
        school_name,
        tfrrs_team_id,
        url
):

    html = get_page(url)

    roster = scrape_roster(
        html,
        school_name
    )

    df = pd.DataFrame(roster)

    output_file = (
        ROSTER_FOLDER /
        f"{tfrrs_team_id}_roster.csv"
    )

    df.to_csv(
        output_file,
        index=False
    )

    return len(df)


def main():

    schools_file = (
        RAW_FOLDER /
        "schools.csv"
    )

    schools = pd.read_csv(
        schools_file
    )

    total_schools = len(schools)

    failures = []

    print(
        f"Starting roster scrape: {total_schools} schools"
    )


    for i, (_, school) in enumerate(
        schools.iterrows(),
        start=1
    ):

        school_name = school["school_name"]

        try:

            athlete_count = scrape_school_roster(
                school_name,
                school["tfrrs_team_id"],
                school["url"]
            )

            print(
                f"Finished {i}/{total_schools}: "
                f"{school_name} "
                f"({athlete_count} athletes)"
            )

        except Exception as e:

            print(
                f"FAILED {i}/{total_schools}: "
                f"{school_name} -> {e}"
            )

            failures.append(
                {
                    "school": school_name,
                    "url": school["url"],
                    "error": str(e)
                }
            )


        time.sleep(
    random.uniform(0.25, 0.75)
    )


    if failures:

        failure_df = pd.DataFrame(
            failures
        )

        failure_file = (
            RAW_FOLDER /
            "roster_failures.csv"
        )

        failure_df.to_csv(
            failure_file,
            index=False
        )

        print(
            f"Completed with {len(failures)} failures."
        )

        print(
            f"Saved failure log: {failure_file}"
        )

    else:

        print(
            "Completed successfully with no failures!"
        )


if __name__ == "__main__":
    main()