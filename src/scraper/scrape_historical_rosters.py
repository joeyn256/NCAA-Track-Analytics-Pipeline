from bs4 import BeautifulSoup
import pandas as pd

import sys
from pathlib import Path

import time
import random


sys.path.append(
    str(Path(__file__).resolve().parents[1])
)


from config import RAW_FOLDER, SEASONS_FOLDER
from scraper.tfrrs_utils import get_page


HISTORICAL_ROSTER_FOLDER = (
    RAW_FOLDER /
    "historical_rosters"
)


HISTORICAL_ROSTER_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)



def clean_filename(name):

    return (
        name
        .replace("/", "_")
        .replace(" ", "_")
        .replace("-", "_")
    )



def scrape_roster(
        html,
        school_name,
        team_id,
        season_name,
        config_hnd
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    athletes = []


    tables = soup.find_all("table")


    for table in tables:

        headers = table.find_all("th")


        if headers and "NAME" in headers[0].text.upper():

            rows = table.find_all("tr")[1:]


            for row in rows:

                cols = row.find_all("td")


                if len(cols) >= 2:

                    link = cols[0].find("a")


                    if link:

                        href = link.get("href")


                        athletes.append(
                            {
                                "athlete_id":
                                    href.split("/")[2],

                                "athlete_name":
                                    link.text.strip(),

                                "year":
                                    cols[1].text.strip(),

                                "school":
                                    school_name,

                                "team_id":
                                    team_id,

                                "season":
                                    season_name,

                                "config_hnd":
                                    config_hnd
                            }
                        )


    return athletes




def main():


    schools = pd.read_csv(
        RAW_FOLDER /
        "schools.csv"
    )


    total = len(schools)


    for index, (_, school) in enumerate(
        schools.iterrows(),
        start=1
    ):


        print(
            f"\n[{index}/{total}] {school['school_name']}"
        )


        season_folder = (
            HISTORICAL_ROSTER_FOLDER /
            school["tfrrs_team_id"]
        )


        season_folder.mkdir(
            parents=True,
            exist_ok=True
        )



        season_file = (
            RAW_FOLDER /
            "seasons" /
            f"{school['tfrrs_team_id']}_seasons.csv"
        )


        if not season_file.exists():

            print(
                "NO SEASONS FILE"
            )

            continue



        seasons = pd.read_csv(
            season_file
        )



        for _, season in seasons.iterrows():


            filename = clean_filename(
                season["season_name"]
            )


            roster_file = (
                season_folder /
                f"{filename}.csv"
            )


            empty_file = (
                season_folder /
                f"{filename}_EMPTY.csv"
            )



            if roster_file.exists():

                print(
                    "SKIP:",
                    season["season_name"]
                )

                continue



            if empty_file.exists():

                print(
                    "SKIP EMPTY:",
                    season["season_name"]
                )

                continue



            url = (
                school["url"]
                +
                "?config_hnd="
                +
                str(
                    season["config_hnd"]
                )
            )


            try:

                html = get_page(
                    url
                )


                athletes = scrape_roster(
                    html,
                    school["school_name"],
                    school["tfrrs_team_id"],
                    season["season_name"],
                    season["config_hnd"]
                )



                if len(athletes) == 0:


                    empty_file.touch()


                    print(
                        season["season_name"],
                        "EMPTY SAVED"
                    )


                else:


                    pd.DataFrame(
                        athletes
                    ).to_csv(
                        roster_file,
                        index=False
                    )


                    print(
                        season["season_name"],
                        len(athletes),
                        "athletes SAVED"
                    )



            except Exception as e:


                print(
                    "FAILED",
                    season["season_name"],
                    e
                )



            time.sleep(
                random.uniform(
                    0.10,
                    0.15
                )
            )


        # LONG BREAK EVERY 25 SCHOOLS
        if index % 100 == 0:

            print(
                "Taking a longer break..."
            )

            time.sleep(
                0
            )




if __name__ == "__main__":
    main()