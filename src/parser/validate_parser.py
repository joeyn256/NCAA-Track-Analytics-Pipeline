import random
import re
import sys
from pathlib import Path

import pandas as pd


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
from parser.parse_performances import (
    ATHLETE_PAGES_FOLDER,
    parse_athlete_page
)


VALIDATION_FOLDER = (
    RAW_FOLDER.parent /
    "processed" /
    "parser_validation"
)


VALIDATION_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


TARGET_PAGE_COUNT = 20
MAX_FILES_TO_SCAN = 5000
RANDOM_SEED = 42


TARGET_CATEGORIES = {
    "cross_country",
    "distance",
    "sprint_or_hurdles",
    "relay",
    "jumps",
    "throws",
    "combined_events",
    "wind_reading",
    "status_code",
    "multiple_seasons"
}


def normalize_event(event):

    return re.sub(
        r"\s+",
        "",
        str(event).upper()
    )


def classify_page(performances_df):

    categories = set()

    events = [
        normalize_event(event)
        for event in performances_df[
            "event"
        ].fillna("")
    ]

    season_types = {
        str(value).strip()
        for value in performances_df[
            "season_type"
        ].fillna("")
        if str(value).strip()
    }

    if "Cross Country" in season_types:

        categories.add(
            "cross_country"
        )

    if any(
        re.search(
            r"^(800|1000|1500|3000|5000|10000|MILE|3000S|STEEPLE)",
            event
        )
        for event in events
    ):

        categories.add(
            "distance"
        )

    if any(
        re.search(
            r"^(55|60|100|200|300|400)(H|MH|M)?$",
            event
        )
        or "HURDLE" in event
        for event in events
    ):

        categories.add(
            "sprint_or_hurdles"
        )

    if any(
        (
            "RELAY" in event
            or event.startswith("4X")
            or event in {
                "DMR",
                "SMR"
            }
        )
        for event in events
    ):

        categories.add(
            "relay"
        )

    if any(
        event in {
            "HJ",
            "LJ",
            "TJ",
            "PV"
        }
        or any(
            keyword in event
            for keyword in {
                "HIGHJUMP",
                "LONGJUMP",
                "TRIPLEJUMP",
                "POLEVAULT"
            }
        )
        for event in events
    ):

        categories.add(
            "jumps"
        )

    if any(
        event in {
            "SP",
            "WT",
            "DT",
            "HT",
            "JT"
        }
        or any(
            keyword in event
            for keyword in {
                "SHOTPUT",
                "WEIGHTTHROW",
                "DISCUS",
                "HAMMER",
                "JAVELIN"
            }
        )
        for event in events
    ):

        categories.add(
            "throws"
        )

    if any(
        event in {
            "HEP",
            "PENT",
            "DEC"
        }
        or any(
            keyword in event
            for keyword in {
                "HEPTATHLON",
                "PENTATHLON",
                "DECATHLON"
            }
        )
        for event in events
    ):

        categories.add(
            "combined_events"
        )

    wind_values = (
        performances_df["wind"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    if wind_values.ne("").any():

        categories.add(
            "wind_reading"
        )

    status_text = (
        performances_df[
            [
                "mark",
                "secondary_mark",
                "place",
                "raw_place"
            ]
        ]
        .fillna("")
        .astype(str)
        .agg(
            " ".join,
            axis=1
        )
        .str.upper()
    )

    if status_text.str.contains(
        r"\b(?:DNS|DNF|DQ|NM|NH|NT)\b",
        regex=True
    ).any():

        categories.add(
            "status_code"
        )

    season_year_count = (
        performances_df[
            "season_year"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace(
            "",
            pd.NA
        )
        .dropna()
        .nunique()
    )

    if season_year_count > 1:

        categories.add(
            "multiple_seasons"
        )

    return categories


def build_page_summary(
        source_file,
        performances_df,
        categories
):

    athlete_id = (
        performances_df[
            "athlete_id"
        ].iloc[0]
    )

    athlete_name = (
        performances_df[
            "athlete_name"
        ].iloc[0]
    )

    school = (
        performances_df[
            "school"
        ].iloc[0]
    )

    return {
        "source_file": source_file,
        "athlete_id": athlete_id,
        "athlete_name": athlete_name,
        "school": school,
        "performance_rows":
            len(performances_df),
        "season_types":
            " | ".join(
                sorted(
                    {
                        str(value)
                        for value in performances_df[
                            "season_type"
                        ].fillna("")
                        if str(value).strip()
                    }
                )
            ),
        "events":
            " | ".join(
                sorted(
                    {
                        str(value)
                        for value in performances_df[
                            "event"
                        ].fillna("")
                        if str(value).strip()
                    }
                )
            ),
        "categories":
            " | ".join(
                sorted(
                    categories
                )
            )
    }


def write_report(
        selected_pages_df,
        performances_df,
        issues_df,
        files_scanned,
        covered_categories
):

    season_counts = (
        performances_df[
            "season_type"
        ]
        .fillna(
            "[missing]"
        )
        .replace(
            "",
            "[missing]"
        )
        .value_counts()
        .to_dict()
    )

    unique_events = sorted(
        {
            str(value)
            for value in performances_df[
                "event"
            ].fillna("")
            if str(value).strip()
        }
    )

    missing_season_count = (
        performances_df[
            "season_type"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
        .eq("")
        .sum()
    )

    result_ids = (
        performances_df[
            "result_id"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    duplicate_result_mask = (
        result_ids.ne("")
        &
        performances_df.assign(
            normalized_result_id=result_ids
        ).duplicated(
            subset=[
                "athlete_id",
                "normalized_result_id"
            ],
            keep=False
        )
    )

    duplicate_result_count = int(
        duplicate_result_mask.sum()
    )

    zero_result_count = 0
    failure_count = 0

    if not issues_df.empty:

        zero_result_count = int(
            (
                issues_df["issue_type"]
                == "zero_results"
            ).sum()
        )

        failure_count = int(
            (
                issues_df["issue_type"]
                == "parse_failure"
            ).sum()
        )

    missing_categories = sorted(
        TARGET_CATEGORIES
        -
        covered_categories
    )

    report_lines = [
        "# Parser Validation Report",
        "",
        "## Summary",
        "",
        f"- Candidate files scanned: **{files_scanned:,}**",
        f"- Validation pages selected: **{len(selected_pages_df):,}**",
        f"- Performance rows parsed: **{len(performances_df):,}**",
        f"- Zero-result pages encountered: **{zero_result_count:,}**",
        f"- Parsing failures encountered: **{failure_count:,}**",
        f"- Missing season classifications: **{missing_season_count:,}**",
        f"- Duplicate athlete/result ID rows: **{duplicate_result_count:,}**",
        f"- Unique events found: **{len(unique_events):,}**",
        "",
        "## Season Counts",
        ""
    ]

    for season_type, count in season_counts.items():

        report_lines.append(
            f"- {season_type}: **{count:,}**"
        )

    report_lines.extend(
        [
            "",
            "## Validation Categories Covered",
            ""
        ]
    )

    for category in sorted(
        covered_categories
    ):

        report_lines.append(
            f"- [x] {category}"
        )

    for category in missing_categories:

        report_lines.append(
            f"- [ ] {category}"
        )

    report_lines.extend(
        [
            "",
            "## Unique Events",
            ""
        ]
    )

    for event in unique_events:

        report_lines.append(
            f"- {event}"
        )

    report_lines.extend(
        [
            "",
            "## Output Files",
            "",
            "- `validation_performances.csv`",
            "- `validation_pages.csv`",
            "- `validation_issues.csv`",
            ""
        ]
    )

    report_file = (
        VALIDATION_FOLDER /
        "validation_report.md"
    )

    report_file.write_text(
        "\n".join(
            report_lines
        ),
        encoding="utf-8"
    )

    return (
        report_file,
        missing_season_count,
        duplicate_result_count,
        missing_categories
    )


def main():

    athlete_files = list(
        ATHLETE_PAGES_FOLDER.glob(
            "*.html"
        )
    )

    if not athlete_files:

        raise FileNotFoundError(
            "No athlete HTML files were found in "
            f"{ATHLETE_PAGES_FOLDER}"
        )

    random_generator = random.Random(
        RANDOM_SEED
    )

    random_generator.shuffle(
        athlete_files
    )

    selected_pages = []
    selected_file_names = set()
    filler_pages = []
    issues = []
    covered_categories = set()
    files_scanned = 0

    scan_limit = min(
        MAX_FILES_TO_SCAN,
        len(athlete_files)
    )

    print(
    f"Searching up to {scan_limit:,} athlete pages..."
    )

    for input_file in athlete_files[
        :scan_limit
    ]:

        files_scanned += 1

        if (
            files_scanned == 1
            or files_scanned % 250 == 0
        ):

            print(
                f"Scanned "
                f"{files_scanned:,}/"
                f"{scan_limit:,} "
                f"candidate pages..."
            )

        athlete_id = input_file.stem

        try:

            html = input_file.read_text(
                encoding="utf-8"
            )

            performances = (
                parse_athlete_page(
                    athlete_id,
                    html,
                    source_file=input_file.name
                )
            )

        except Exception as error:

            issues.append(
                {
                    "source_file":
                        input_file.name,
                    "athlete_id":
                        athlete_id,
                    "issue_type":
                        "parse_failure",
                    "details":
                        str(error)
                }
            )

            continue

        if not performances:

            issues.append(
                {
                    "source_file":
                        input_file.name,
                    "athlete_id":
                        athlete_id,
                    "issue_type":
                        "zero_results",
                    "details":
                        "No meet-result rows parsed."
                }
            )

            continue

        performances_df = pd.DataFrame(
            performances
        )

        categories = classify_page(
            performances_df
        )

        candidate = {
            "source_file":
                input_file.name,
            "performances_df":
                performances_df,
            "categories":
                categories
        }

        new_categories = (
            categories
            -
            covered_categories
        )

        if new_categories:

            selected_pages.append(
                candidate
            )

            selected_file_names.add(
                input_file.name
            )

            covered_categories.update(
                categories
            )

        elif len(filler_pages) < 100:

            filler_pages.append(
                candidate
            )

        enough_candidates = (
            len(selected_pages)
            +
            len(filler_pages)
            >= TARGET_PAGE_COUNT
        )

        all_categories_found = (
            covered_categories
            >= TARGET_CATEGORIES
        )

        if (
            enough_candidates
            and all_categories_found
        ):

            break

    for candidate in filler_pages:

        if len(selected_pages) >= (
            TARGET_PAGE_COUNT
        ):

            break

        if candidate[
            "source_file"
        ] in selected_file_names:

            continue

        selected_pages.append(
            candidate
        )

        selected_file_names.add(
            candidate[
                "source_file"
            ]
        )

        covered_categories.update(
            candidate[
                "categories"
            ]
        )

    if not selected_pages:

        raise ValueError(
            "No athlete pages could be parsed."
        )

    selected_pages = selected_pages[
        :TARGET_PAGE_COUNT
    ]

    performance_frames = [
        candidate[
            "performances_df"
        ]
        for candidate in selected_pages
    ]

    combined_performances_df = pd.concat(
        performance_frames,
        ignore_index=True
    )

    page_summaries = [
        build_page_summary(
            candidate[
                "source_file"
            ],
            candidate[
                "performances_df"
            ],
            candidate[
                "categories"
            ]
        )
        for candidate in selected_pages
    ]

    selected_pages_df = pd.DataFrame(
        page_summaries
    )

    issues_df = pd.DataFrame(
        issues,
        columns=[
            "source_file",
            "athlete_id",
            "issue_type",
            "details"
        ]
    )

    performances_file = (
        VALIDATION_FOLDER /
        "validation_performances.csv"
    )

    pages_file = (
        VALIDATION_FOLDER /
        "validation_pages.csv"
    )

    issues_file = (
        VALIDATION_FOLDER /
        "validation_issues.csv"
    )

    combined_performances_df.to_csv(
        performances_file,
        index=False
    )

    selected_pages_df.to_csv(
        pages_file,
        index=False
    )

    issues_df.to_csv(
        issues_file,
        index=False
    )

    (
        report_file,
        missing_season_count,
        duplicate_result_count,
        missing_categories
    ) = write_report(
        selected_pages_df,
        combined_performances_df,
        issues_df,
        files_scanned,
        covered_categories
    )

    print(
        "\nPARSER VALIDATION COMPLETE"
    )

    print(
        "Candidate files scanned:",
        f"{files_scanned:,}"
    )

    print(
        "Validation pages selected:",
        f"{len(selected_pages_df):,}"
    )

    print(
        "Performance rows parsed:",
        f"{len(combined_performances_df):,}"
    )

    print(
        "Missing season classifications:",
        f"{missing_season_count:,}"
    )

    print(
        "Duplicate athlete/result rows:",
        f"{duplicate_result_count:,}"
    )

    print(
        "Categories covered:",
        ", ".join(
            sorted(
                covered_categories
            )
        )
    )

    if missing_categories:

        print(
            "Categories not found:",
            ", ".join(
                missing_categories
            )
        )

    else:

        print(
            "Categories not found: None"
        )

    print(
        "\nSaved report:"
    )

    print(
        report_file
    )


if __name__ == "__main__":
    main()