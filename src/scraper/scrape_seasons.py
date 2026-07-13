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


def parse_seasons(html, school_name, tfrrs_team_id):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    seasons = []


    # Find dropdown menus
    dropdowns = soup.find_all("select")


    for dropdown in dropdowns:

        options = dropdown.find_all("option")


        for option in options:

            season_name = option.text.strip()
            value = option.get("value")


            if not value:
                continue


            if (
                "Indoor" in season_name
                or "Outdoor" in season_name
                or "Cross Country" in season_name
            ):
                
                seasons.append(
                    {
                        "season_name": season_name,
                        "config_hnd": value,
                        "school_name": school_name,
                        "tfrrs_team_id": tfrrs_team_id
                    }
                )

    return seasons



def scrape_school_seasons(
        school_name,
        tfrrs_team_id,
        url
):

    html = get_page(url)

    seasons = parse_seasons(
    html,
    school_name,
    tfrrs_team_id
    )   


    df = pd.DataFrame(
        seasons
    )


    df["school_name"] = school_name

    df["tfrrs_team_id"] = (
        tfrrs_team_id
    )


    output_file = (
    SEASONS_FOLDER /
    f"{tfrrs_team_id}_seasons.csv"
    )   


    df.to_csv(
        output_file,
        index=False
    )


    print(
        school_name,
        len(df),
        "seasons"
    )



def main():

    schools_file = (
        RAW_FOLDER /
        "schools.csv"
    )


    schools = pd.read_csv(
        schools_file
    )


    total_schools = len(schools)

    for index, (_, school) in enumerate(schools.iterrows(), start=1):

        print(
            f"[{index}/{total_schools}] Scraping {school['school_name']}"
        )

        try:

            scrape_school_seasons(
                school["school_name"],
                school["tfrrs_team_id"],
                school["url"]
            )


        except Exception as e:
                
            print(
                "FAILED:",
                school["school_name"],
                e
            )


        time.sleep(
            random.uniform(0.25, 0.5)
        )

if __name__ == "__main__":
    main()