import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from bs4 import BeautifulSoup


# Add src/ to Python's import path.
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


ATHLETE_PAGES_FOLDER = (
    RAW_FOLDER /
    "athlete_pages"
)


PROCESSED_FOLDER = (
    RAW_FOLDER.parent /
    "processed"
)


PARSER_TEST_FOLDER = (
    PROCESSED_FOLDER /
    "parser_tests"
)


PARSER_TEST_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


TEST_ATHLETE_ID = "9250451"


def clean_text(element):

    if element is None:
        return ""

    return " ".join(
        element.get_text(
            " ",
            strip=True
        ).split()
    )


def normalize_url_key(url):

    if not url:
        return ""

    return (
        urlparse(str(url))
        .path
        .rstrip("/")
    )


def extract_team_id(team_url):

    if not team_url:
        return ""

    filename = (
        urlparse(str(team_url))
        .path
        .rstrip("/")
        .split("/")[-1]
    )

    return filename.replace(
        ".html",
        ""
    )


def extract_result_ids(result_url):

    meet_id = ""
    result_id = ""

    path_parts = [
        part
        for part in (
            urlparse(str(result_url))
            .path
            .split("/")
        )
        if part
    ]

    try:

        results_index = path_parts.index(
            "results"
        )

    except ValueError:

        return meet_id, result_id

    first_value_index = (
        results_index + 1
    )

    if len(path_parts) <= first_value_index:

        return meet_id, result_id

    first_value = path_parts[
        first_value_index
    ]

    # Cross Country URLs use:
    # /results/xc/{meet_id}/...
    if first_value.lower() == "xc":

        meet_id_index = (
            results_index + 2
        )

        if len(path_parts) > meet_id_index:

            possible_meet_id = path_parts[
                meet_id_index
            ]

            if possible_meet_id.isdigit():

                meet_id = possible_meet_id

        # XC athlete pages normally do not provide
        # a separate individual result ID.
        return meet_id, result_id

    # Track & Field URLs use:
    # /results/{meet_id}/{result_id}/...
    if first_value.isdigit():

        meet_id = first_value

    result_id_index = (
        results_index + 2
    )

    if len(path_parts) > result_id_index:

        possible_result_id = path_parts[
            result_id_index
        ]

        if possible_result_id.isdigit():

            result_id = possible_result_id

    return meet_id, result_id

def extract_year_from_date_text(
        meet_date_text
):

    year_match = re.search(
        r"\b(?:19|20)\d{2}\b",
        str(meet_date_text)
    )

    if year_match:

        return year_match.group(0)

    return ""


def parse_athlete_header(soup):

    athlete_name = ""
    athlete_class = ""
    school_name = ""
    team_id = ""

    name_heading = soup.select_one(
        "h3.large-title"
    )

    heading_text = clean_text(
        name_heading
    )

    heading_match = re.match(
        r"^(.*?)\s*\(([^()]*)\)\s*$",
        heading_text
    )

    if heading_match:

        athlete_name = (
            heading_match
            .group(1)
            .strip()
            .title()
        )

        athlete_class = (
            heading_match
            .group(2)
            .strip()
        )

    else:

        athlete_name = (
            heading_text
            .strip()
            .title()
        )

    team_link = soup.select_one(
        'a[href*="/teams/tf/"]'
    )

    if team_link:

        school_name = clean_text(
            team_link
        ).title()

        team_id = extract_team_id(
            team_link.get(
                "href",
                ""
            )
        )

    return {
        "athlete_name": athlete_name,
        "athlete_class": athlete_class,
        "school": school_name,
        "team_id": team_id
    }

def identify_season_type(
        heading_text,
        heading_classes
):

    text_lower = (
        str(heading_text)
        .lower()
        .strip()
    )

    classes_lower = {
        str(value)
        .lower()
        .strip()
        for value in heading_classes
    }

    if (
        "outdoors" in classes_lower
        or "outdoor" in classes_lower
        or "outdoor" in text_lower
    ):
        return "Outdoor"

    if (
        "indoors" in classes_lower
        or "indoor" in classes_lower
        or "indoor" in text_lower
    ):
        return "Indoor"

    if (
        "xc" in classes_lower
        or "cross-country" in classes_lower
        or "cross_country" in classes_lower
        or "cross country" in text_lower
        or "cross-country" in text_lower
        or re.search(
            r"\bxc\b",
            text_lower
        )
    ):
        return "Cross Country"

    return ""


def build_season_map(soup):

    season_map = {}

    season_section = soup.find(
        id="session-history"
    )

    if season_section is None:
        return season_map

    headings = season_section.find_all(
        "h3"
    )

    for heading in headings:

        season_label = clean_text(
            heading
        )

        year_match = re.search(
            r"\b(?:19|20)\d{2}\b",
            season_label
        )

        season_year = (
            year_match.group(0)
            if year_match
            else ""
        )

        season_type = identify_season_type(
            season_label,
            heading.get(
                "class",
                []
            )
        )

        season_content = (
            heading.find_next_sibling(
                "div"
            )
        )

        if season_content is None:
            continue

        result_links = season_content.find_all(
            "a",
            href=True
        )

        for link in result_links:

            href = link.get(
                "href",
                ""
            )

            if "/results/" not in href:
                continue

            season_map[
                normalize_url_key(
                    href
                )
            ] = {
                "season_year": season_year,
                "season_type": season_type,
                "season_label": season_label
            }

    return season_map


def parse_mark_details(mark_cell):

    details = []

    for span in mark_cell.find_all(
        "span"
    ):

        text = clean_text(
            span
        )

        if text:
            details.append(
                text
            )

    wind = ""
    secondary_mark_parts = []

    for detail in details:

        wind_match = re.fullmatch(
            r"\(([+-]?\d+(?:\.\d+)?)\)",
            detail
        )

        if wind_match:

            wind = wind_match.group(1)

        else:

            secondary_mark_parts.append(
                detail
            )

    secondary_mark = " | ".join(
        secondary_mark_parts
    )

    return wind, secondary_mark


def parse_place_and_round(place_cell):

    place_text = clean_text(
        place_cell
    )

    round_match = re.search(
        r"\(([^()]*)\)",
        place_text
    )

    competition_round = (
        round_match.group(1).strip()
        if round_match
        else ""
    )

    place = re.sub(
        r"\([^()]*\)",
        "",
        place_text
    ).strip()

    return (
        place,
        competition_round,
        place_text
    )


def parse_meet_results(
        soup,
        athlete_id,
        athlete_info,
        season_map,
        source_file
):

    performances = []

    results_section = soup.find(
        id="meet-results"
    )

    if results_section is None:
        return performances

    tables = results_section.find_all(
        "table"
    )

    for table in tables:

        table_header = table.find(
            "thead"
        )

        if table_header is None:
            continue

        meet_link = table_header.find(
            "a",
            href=True
        )

        if meet_link is None:
            continue

        meet_name = clean_text(
            meet_link
        )

        meet_url = meet_link.get(
            "href",
            ""
        )

        date_span = table_header.find(
            "span"
        )

        meet_date_text = clean_text(
            date_span
        )

        rows = table.find_all(
            "tr"
        )

        for row in rows:

            cells = row.find_all(
                "td"
            )

            if len(cells) < 3:
                continue

            event = clean_text(
                cells[0]
            )

            mark_cell = cells[1]
            place_cell = cells[2]

            result_link = mark_cell.find(
                "a",
                href=True
            )

            if result_link is None:
                continue

            mark = clean_text(
                result_link
            )

            result_url = result_link.get(
                "href",
                ""
            )

            meet_id, result_id = (
                extract_result_ids(
                    result_url
                )
            )

            if not meet_id:

                meet_id, _ = (
                    extract_result_ids(
                        meet_url
                    )
                )

            wind, secondary_mark = (
                parse_mark_details(
                    mark_cell
                )
            )

            (
                place,
                competition_round,
                raw_place
            ) = parse_place_and_round(
                place_cell
            )

            season_info = (
                season_map.get(
                    normalize_url_key(
                        result_url
                    )
                )
                or season_map.get(
                    normalize_url_key(
                        meet_url
                    )
                )
                or {}
            )


            season_year = season_info.get(
                "season_year",
                ""
            )


            season_type = season_info.get(
                "season_type",
                ""
            )


            season_label = season_info.get(
                "season_label",
                ""
            )


            result_path = normalize_url_key(
                result_url
            ).lower()


            meet_path = normalize_url_key(
                meet_url
            ).lower()


            is_cross_country = (
                "/results/xc/" in result_path
                or "/results/xc/" in meet_path
            )


            if is_cross_country:

                if not season_type:

                    season_type = (
                        "Cross Country"
                    )

                if not season_year:

                    season_year = (
                        extract_year_from_date_text(
                            meet_date_text
                        )
                    )

                if (
                    not season_label
                    and season_year
                ):

                    season_label = (
                        f"{season_year} XC"
                    )

            row_classes = row.get(
                "class",
                []
            )

            performances.append(
                {
                    "athlete_id": athlete_id,
                    "athlete_name":
                        athlete_info["athlete_name"],
                    "athlete_class":
                        athlete_info["athlete_class"],
                    "school":
                        athlete_info["school"],
                    "team_id":
                        athlete_info["team_id"],
                    "season_year": season_year,
                    "season_type": season_type,
                    "season_label": season_label,
                    "meet_id": meet_id,
                    "result_id": result_id,
                    "meet_name": meet_name,
                    "meet_date_text": meet_date_text,
                    "event": event,
                    "mark": mark,
                    "secondary_mark": secondary_mark,
                    "wind": wind,
                    "place": place,
                    "competition_round":
                        competition_round,
                    "raw_place": raw_place,
                    "meet_url": meet_url,
                    "result_url": result_url,
                    "highlighted":
                        "highlight" in row_classes,
                    "source_file": source_file
                }
            )

    return performances


def parse_athlete_page(
        athlete_id,
        html,
        source_file=""
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    athlete_info = parse_athlete_header(
        soup
    )

    season_map = build_season_map(
        soup
    )

    performances = parse_meet_results(
        soup,
        athlete_id,
        athlete_info,
        season_map,
        source_file
    )

    return performances


def main():

    input_file = (
        ATHLETE_PAGES_FOLDER /
        f"{TEST_ATHLETE_ID}.html"
    )

    if not input_file.exists():

        raise FileNotFoundError(
            f"Athlete page not found: {input_file}"
        )

    html = input_file.read_text(
        encoding="utf-8"
    )

    performances = parse_athlete_page(
        TEST_ATHLETE_ID,
        html,
        source_file=input_file.name
    )

    if not performances:

        raise ValueError(
            "No performances were parsed."
        )

    performances_df = pd.DataFrame(
        performances
    )

    output_file = (
        PARSER_TEST_FOLDER /
        f"{TEST_ATHLETE_ID}_performances.csv"
    )

    performances_df.to_csv(
        output_file,
        index=False
    )

    print(
        "Athlete:",
        performances_df[
            "athlete_name"
        ].iloc[0]
    )

    print(
        "School:",
        performances_df[
            "school"
        ].iloc[0]
    )

    print(
        "Performances parsed:",
        len(performances_df)
    )

    print(
        "\nSeason types:"
    )

    print(
        performances_df[
            "season_type"
        ].value_counts(
            dropna=False
        )
    )

    print(
        "\nEvents:"
    )

    print(
        performances_df[
            "event"
        ].value_counts(
            dropna=False
        )
    )

    print(
        "\nFirst records:"
    )

    print(
        performances_df[
            [
                "season_year",
                "season_type",
                "meet_id",
                "result_id",
                "meet_name",
                "meet_date_text",
                "event",
                "mark",
                "wind",
                "place",
                "competition_round"
            ]
        ].head(
            10
        ).to_string(
            index=False
        )
    )

    print(
        "\nSaved:"
    )

    print(
        output_file
    )


if __name__ == "__main__":
    main()