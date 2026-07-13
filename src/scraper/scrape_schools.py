import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1])
)

from bs4 import BeautifulSoup
import pandas as pd

from config import (
    ROSTER_FOLDER,
    RAW_FOLDER,
    SEASONS_FOLDER
)

from scraper.tfrrs_utils import get_page

URL = "https://www.tfrrs.org/leagues/49.html"


def parse_school_directory(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    schools = []

    links = soup.find_all("a")

    school_id = 1



    for link in links:

        href = link.get("href")

        name = link.text.strip()


        if not href:
            continue


        if "/teams/tf/" in href:

            team_id = (
                href
                .split("/")[-1]
                .replace(".html", "")
            )


            state = team_id.split("_")[0]


            slug = (
                team_id
                .split("_college_")[-1]
                .replace("m_", "")
                .replace("f_", "")
            )


            gender = (
                "Men"
                if "_m_" in team_id
                else "Women"
            )


            if href.startswith("http"):
                full_url = href
            else:
                full_url = (
                    "https://www.tfrrs.org"
                    + href
                )


            schools.append(
                {
                    "school_id": school_id,
                    "tfrrs_team_id": team_id,
                    "school_name": name,
                    "slug": slug,
                    "url": full_url,
                    "division": "D1",
                    "gender": gender,
                    "sport": "Track & Field",
                    "conference": "",
                    "state": state
                }
            )

            school_id += 1


    return schools



def main():

    html = get_page(URL)

    schools = parse_school_directory(
        html
    )


    df = pd.DataFrame(
        schools
    )


    print(df.head())

    print(
        "Total teams:",
        len(df)
    )


    df.to_csv(
        "data/raw/schools.csv",
        index=False
    )



if __name__ == "__main__":
    main()