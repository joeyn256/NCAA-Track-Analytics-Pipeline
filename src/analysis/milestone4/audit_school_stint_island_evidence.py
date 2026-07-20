#!/usr/bin/env python3
"""
Milestone 4: audit the final two single-meet A-B-A school-stint islands.

The audit targets only the islands produced by the final school-stint v1.0
diagnostic build. For each middle performance it:

- reads the exact canonical-person performance;
- preserves all source-profile attribution evidence;
- fetches the TFRRS result page;
- locates the athlete's exact result row using name, mark, and place;
- extracts or infers the team from that row;
- verifies whether the result-page team equals both surrounding stint teams.

No database or prior output is modified.

Outputs
-------
data/processed/milestone4/school_stint_island_evidence/
    island_result_evidence.csv
    island_source_attribution_rows.csv
    resolution_status_summary.csv
    hard_checks.csv
    island_evidence_report.txt
    html_cache/
"""

from __future__ import annotations

import argparse
import hashlib
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

import duckdb
import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_ROOT = Path(__file__).resolve().parents[3]

SOURCE_DB = (
    PROJECT_ROOT
    / "data/database/"
    / "ncaa_track_analytics.duckdb"
)

PERSON_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_person_layer_v1_1/"
    / "canonical_person_layer_v1_1.duckdb"
)

STINT_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "final_school_stints/"
    / "final_school_stints.duckdb"
)

STINT_CHECKS = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "final_school_stints/"
    / "hard_checks.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "school_stint_island_evidence"
)

CACHE_DIR = OUTPUT_DIR / "html_cache"

AUDIT_VERSION = (
    "m4_school_stint_island_evidence_v1.0"
)

EXPECTED_ISLANDS = 2
EXPECTED_PEOPLE = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--replace-output",
        action="store_true",
    )

    parser.add_argument(
        "--refresh-cache",
        action="store_true",
    )

    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.25,
    )

    return parser.parse_args()


def sql_path(path: Path) -> str:
    return (
        path.resolve()
        .as_posix()
        .replace("'", "''")
    )


def file_state(path: Path) -> dict[str, int]:
    stat = path.stat()

    return {
        "size_bytes": int(stat.st_size),
        "modified_ns": int(stat.st_mtime_ns),
    }


def normalize_text(value: object) -> str:
    text = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(
            character
        )
    )

    return re.sub(
        r"[^a-z0-9]+",
        "",
        text.lower(),
    )


def name_keys(value: object) -> set[str]:
    raw = str(value or "").strip()

    if not raw:
        return set()

    variants = {normalize_text(raw)}

    if "," in raw:
        parts = [
            part.strip()
            for part in raw.split(",")
            if part.strip()
        ]

        if len(parts) == 2:
            variants.add(
                normalize_text(
                    f"{parts[1]} {parts[0]}"
                )
            )

    tokens = re.findall(
        r"[A-Za-z0-9]+",
        unicodedata.normalize(
            "NFKD",
            raw,
        ),
    )

    if tokens:
        variants.add(
            "".join(
                sorted(
                    token.lower()
                    for token in tokens
                )
            )
        )

    return {
        value
        for value in variants
        if value
    }


def names_match(
    left: object,
    right: object,
) -> bool:
    return bool(
        name_keys(left)
        & name_keys(right)
    )


def normalize_url(value: object) -> str:
    text = str(value or "").strip()

    if not text:
        return ""

    parsed = urlparse(text)

    path = re.sub(
        r"/+",
        "/",
        parsed.path,
    ).rstrip("/")

    return (
        f"{parsed.scheme.lower()}://"
        f"{parsed.netloc.lower()}{path}"
    )


def team_id_from_url(value: object) -> str:
    path = urlparse(
        str(value or "")
    ).path

    basename = Path(path).name

    if basename.endswith(".html"):
        basename = basename[:-5]

    return basename


def is_athlete_link(href: str) -> bool:
    lowered = href.lower()

    return (
        "/athletes/" in lowered
        or "athletes/" in lowered
    )


def is_team_link(href: str) -> bool:
    lowered = href.lower()

    return (
        "/teams/" in lowered
        or "teams/tf/" in lowered
    )


def cache_path_for_url(url: str) -> Path:
    digest = hashlib.sha1(
        url.encode("utf-8")
    ).hexdigest()

    return CACHE_DIR / f"{digest}.html"


def build_session() -> requests.Session:
    session = requests.Session()

    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=0.8,
        status_forcelist=[
            429,
            500,
            502,
            503,
            504,
        ],
        allowed_methods=["GET"],
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry
    )

    session.mount(
        "https://",
        adapter,
    )
    session.mount(
        "http://",
        adapter,
    )

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/150.0 Safari/537.36"
            )
        }
    )

    return session


def fetch_html(
    session: requests.Session,
    url: str,
    refresh_cache: bool,
    request_delay: float,
) -> tuple[str, str, str]:
    cache_path = cache_path_for_url(
        url
    )

    if (
        cache_path.exists()
        and not refresh_cache
    ):
        return (
            cache_path.read_text(
                encoding="utf-8",
                errors="replace",
            ),
            "CACHE_HIT",
            "",
        )

    try:
        response = session.get(
            url,
            timeout=45,
        )

        if response.status_code != 200:
            return (
                "",
                f"HTTP_{response.status_code}",
                response.text[:500],
            )

        html = response.text

        cache_path.write_text(
            html,
            encoding="utf-8",
        )

        if request_delay > 0:
            time.sleep(request_delay)

        return (
            html,
            "FETCHED",
            "",
        )

    except requests.RequestException as exc:
        return (
            "",
            "REQUEST_ERROR",
            str(exc),
        )


def candidate_rows(
    soup: BeautifulSoup,
    athlete_name: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    for row in soup.find_all("tr"):
        athlete_links = [
            link
            for link in row.find_all(
                "a",
                href=True,
            )
            if is_athlete_link(
                str(
                    link.get(
                        "href",
                        "",
                    )
                )
            )
        ]

        matching_links = [
            link
            for link in athlete_links
            if names_match(
                athlete_name,
                link.get_text(
                    " ",
                    strip=True,
                ),
            )
        ]

        row_text = row.get_text(
            " ",
            strip=True,
        )

        if not matching_links:
            if not names_match(
                athlete_name,
                row_text,
            ):
                continue

        team_links = []

        for link in row.find_all(
            "a",
            href=True,
        ):
            href = str(
                link.get(
                    "href",
                    "",
                )
            )

            if is_team_link(href):
                team_links.append(
                    {
                        "team_name": (
                            link.get_text(
                                " ",
                                strip=True,
                            )
                        ),
                        "team_url": href,
                    }
                )

        rows.append(
            {
                "row_text": row_text,
                "athlete_link_name": (
                    matching_links[0]
                    .get_text(
                        " ",
                        strip=True,
                    )
                    if matching_links
                    else ""
                ),
                "athlete_href": (
                    str(
                        matching_links[0]
                        .get(
                            "href",
                            "",
                        )
                    )
                    if matching_links
                    else ""
                ),
                "team_links": team_links,
                "cell_texts": [
                    cell.get_text(
                        " ",
                        strip=True,
                    )
                    for cell in row.find_all(
                        ["td", "th"]
                    )
                ],
            }
        )

    return rows


def choose_row(
    rows: list[dict[str, object]],
    mark: object,
    place: object,
) -> tuple[
    dict[str, object] | None,
    str,
]:
    if not rows:
        return (
            None,
            "ATHLETE_ROW_NOT_FOUND",
        )

    if len(rows) == 1:
        return (
            rows[0],
            "EXACT_NAME_SINGLE_ROW",
        )

    normalized_mark = normalize_text(mark)
    normalized_place = normalize_text(
        place
    )

    scored = []

    for row in rows:
        text = normalize_text(
            row["row_text"]
        )

        score = 0

        if (
            normalized_mark
            and normalized_mark in text
        ):
            score += 3

        if (
            normalized_place
            and normalized_place in text
        ):
            score += 1

        if row["athlete_link_name"]:
            score += 1

        scored.append(
            (
                score,
                row,
            )
        )

    scored.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    best_score = scored[0][0]

    best_rows = [
        row
        for score, row in scored
        if score == best_score
    ]

    if len(best_rows) == 1:
        return (
            best_rows[0],
            "EXACT_NAME_MARK_PLACE_ROW",
        )

    unique_row_text = {
        normalize_text(
            row["row_text"]
        )
        for row in best_rows
    }

    if len(unique_row_text) == 1:
        return (
            best_rows[0],
            "DUPLICATE_IDENTICAL_RESULT_ROWS",
        )

    return (
        None,
        "MULTIPLE_MATCHING_ATHLETE_ROWS",
    )


def prepare_output(
    replace_output: bool,
) -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    generated = [
        OUTPUT_DIR
        / "island_result_evidence.csv",
        OUTPUT_DIR
        / "island_source_attribution_rows.csv",
        OUTPUT_DIR
        / "resolution_status_summary.csv",
        OUTPUT_DIR
        / "hard_checks.csv",
        OUTPUT_DIR
        / "island_evidence_report.txt",
    ]

    existing = [
        path
        for path in generated
        if path.exists()
    ]

    if existing and not replace_output:
        raise FileExistsError(
            "Island-evidence outputs already exist. "
            "Use --replace-output only after reviewing "
            "the existing files."
        )

    if replace_output:
        for path in existing:
            path.unlink()


def main() -> None:
    args = parse_args()

    for path in [
        SOURCE_DB,
        PERSON_DB,
        STINT_DB,
        STINT_CHECKS,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )

    prepare_output(
        replace_output=args.replace_output,
    )

    person_before = file_state(PERSON_DB)
    stint_before = file_state(STINT_DB)

    con = duckdb.connect()

    try:
        con.execute(
            f"""
            ATTACH '{sql_path(SOURCE_DB)}'
            AS source
            (READ_ONLY)
            """
        )

        con.execute(
            f"""
            ATTACH '{sql_path(PERSON_DB)}'
            AS person
            (READ_ONLY)
            """
        )

        con.execute(
            f"""
            ATTACH '{sql_path(STINT_DB)}'
            AS stint
            (READ_ONLY)
            """
        )

        targets = con.execute(
            """
            SELECT
                s.school_stint_id,
                s.canonical_person_id,
                s.stint_sequence,
                s.canonical_team_id
                    AS island_team_id,
                s.canonical_team_name
                    AS island_team_name,
                s.prior_stint_team_id,
                s.next_stint_team_id,
                s.first_meet_id
                    AS meet_id,
                s.first_meet_name
                    AS meet_name,

                p.canonical_person_performance_id,
                p.athlete_name,
                p.season_id,
                p.season_year,
                p.season_type,
                p.meet_date_text,
                p.event,
                p.mark,
                p.place,
                p.result_url,
                p.source_profile_count,
                p.source_performance_rows,
                p.representative_performance_id,
                p.representative_athlete_id

            FROM stint
                .canonical_person_school_stints s

            JOIN stint
                .school_stint_performance_map map
              ON s.school_stint_id
                    = map.school_stint_id

            JOIN person
                .canonical_person_performances p
              ON map
                    .canonical_person_performance_id
                    =
                    p.canonical_person_performance_id

            WHERE s.is_single_meet_aba_island

            ORDER BY
                s.canonical_person_id,
                s.stint_sequence,
                p.canonical_person_performance_id
            """
        ).fetchdf()

        source_rows = con.execute(
            """
            SELECT
                t.canonical_person_id,
                t.canonical_person_performance_id,

                m.performance_id,
                m.athlete_id,
                m.athlete_name,
                m.source_school,
                m.source_team_id,
                m.pre_resolution_team_id,
                m.canonical_team_id,
                m.canonical_team_name,
                m.attribution_precedence,
                m.attribution_status,
                m.attribution_method,
                m.attribution_confidence,
                m.evidence_source,
                m.person_team_resolution_applied,
                m.person_team_resolution_method,
                m.person_team_resolution_detail,
                m.result_url

            FROM targets t

            JOIN person
                .canonical_person_performance_map m
              ON t.canonical_person_performance_id
                    =
                    m.canonical_person_performance_id

            ORDER BY
                t.canonical_person_id,
                t.canonical_person_performance_id,
                m.athlete_id,
                m.performance_id
            """
        ).fetchdf()

        teams = con.execute(
            """
            SELECT
                team_id,
                team_name,
                school_id,
                gender_code,
                division,
                in_division_i_directory,
                team_url
            FROM source.core.teams
            """
        ).fetchdf()

    finally:
        con.close()

    source_rows.to_csv(
        OUTPUT_DIR
        / "island_source_attribution_rows.csv",
        index=False,
    )

    teams_by_id = {
        str(row["team_id"]): row
        for row in teams.to_dict(
            orient="records"
        )
    }

    teams_by_url = {
        normalize_url(
            row["team_url"]
        ): row
        for row in teams.to_dict(
            orient="records"
        )
        if normalize_url(
            row["team_url"]
        )
    }

    teams_by_name: dict[
        str,
        list[dict[str, object]],
    ] = {}

    for row in teams.to_dict(
        orient="records"
    ):
        key = normalize_text(
            row["team_name"]
        )

        teams_by_name.setdefault(
            key,
            [],
        ).append(row)

    session = build_session()
    evidence_rows = []

    print(
        "Resolving final single-meet A-B-A "
        "islands from result pages..."
    )

    for target in targets.to_dict(
        orient="records"
    ):
        result_url = str(
            target.get(
                "result_url",
                "",
            )
            or ""
        ).strip()

        html, fetch_status, fetch_error = (
            fetch_html(
                session=session,
                url=result_url,
                refresh_cache=(
                    args.refresh_cache
                ),
                request_delay=(
                    args.request_delay
                ),
            )
            if result_url
            else (
                "",
                "BLANK_RESULT_URL",
                "",
            )
        )

        base = {
            **target,
            "fetch_status": fetch_status,
            "fetch_error": fetch_error,
        }

        if not html:
            evidence_rows.append(
                {
                    **base,
                    "row_match_status": (
                        "NOT_ATTEMPTED"
                    ),
                    "athlete_link_name": "",
                    "athlete_href": "",
                    "parsed_team_id": "",
                    "parsed_team_name": "",
                    "parsed_team_url": "",
                    "team_mapping_method": "",
                    "matches_prior_team": False,
                    "matches_next_team": False,
                    "differs_from_island_team": False,
                    "resolution_status": (
                        "UNRESOLVED"
                    ),
                }
            )
            continue

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        rows = candidate_rows(
            soup=soup,
            athlete_name=str(
                target["athlete_name"]
            ),
        )

        chosen, row_status = choose_row(
            rows=rows,
            mark=target["mark"],
            place=target["place"],
        )

        if chosen is None:
            evidence_rows.append(
                {
                    **base,
                    "row_match_status": (
                        row_status
                    ),
                    "athlete_link_name": "",
                    "athlete_href": "",
                    "parsed_team_id": "",
                    "parsed_team_name": "",
                    "parsed_team_url": "",
                    "team_mapping_method": "",
                    "matches_prior_team": False,
                    "matches_next_team": False,
                    "differs_from_island_team": False,
                    "resolution_status": (
                        "UNRESOLVED"
                    ),
                }
            )
            continue

        mapped_team: dict[
            str,
            object,
        ] | None = None

        unique_team_links = {
            (
                normalize_text(
                    team["team_name"]
                ),
                str(team["team_url"]),
            ): team
            for team in chosen[
                "team_links"
            ]
        }

        if len(unique_team_links) == 1:
            team_link = next(
                iter(
                    unique_team_links.values()
                )
            )

            absolute_url = urljoin(
                result_url,
                str(
                    team_link[
                        "team_url"
                    ]
                ),
            )

            parsed_id = team_id_from_url(
                absolute_url
            )

            if parsed_id in teams_by_id:
                mapped_team = dict(
                    teams_by_id[parsed_id]
                )

                mapped_team[
                    "parsed_team_url"
                ] = absolute_url

                mapped_team[
                    "team_mapping_method"
                ] = "TEAM_ID_FROM_URL"

            elif (
                normalize_url(
                    absolute_url
                )
                in teams_by_url
            ):
                mapped_team = dict(
                    teams_by_url[
                        normalize_url(
                            absolute_url
                        )
                    ]
                )

                mapped_team[
                    "parsed_team_url"
                ] = absolute_url

                mapped_team[
                    "team_mapping_method"
                ] = "EXACT_TEAM_URL"

        if mapped_team is None:
            cell_matches = []

            for cell_text in chosen[
                "cell_texts"
            ]:
                key = normalize_text(
                    cell_text
                )

                matches = teams_by_name.get(
                    key,
                    [],
                )

                if len(matches) == 1:
                    cell_matches.append(
                        matches[0]
                    )

            unique_cell_matches = {
                str(
                    match["team_id"]
                ): match
                for match in cell_matches
            }

            if len(unique_cell_matches) == 1:
                mapped_team = dict(
                    next(
                        iter(
                            unique_cell_matches
                            .values()
                        )
                    )
                )

                mapped_team[
                    "parsed_team_url"
                ] = ""

                mapped_team[
                    "team_mapping_method"
                ] = "UNIQUE_EXACT_TEAM_CELL_TEXT"

        if mapped_team is None:
            evidence_rows.append(
                {
                    **base,
                    "row_match_status": (
                        row_status
                    ),
                    "athlete_link_name": (
                        chosen[
                            "athlete_link_name"
                        ]
                    ),
                    "athlete_href": urljoin(
                        result_url,
                        str(
                            chosen[
                                "athlete_href"
                            ]
                        ),
                    ),
                    "parsed_team_id": "",
                    "parsed_team_name": "",
                    "parsed_team_url": "",
                    "team_mapping_method": "",
                    "matches_prior_team": False,
                    "matches_next_team": False,
                    "differs_from_island_team": False,
                    "resolution_status": (
                        "UNRESOLVED_TEAM"
                    ),
                }
            )
            continue

        parsed_team_id = str(
            mapped_team["team_id"]
        )

        matches_prior = (
            parsed_team_id
            == str(
                target[
                    "prior_stint_team_id"
                ]
            )
        )

        matches_next = (
            parsed_team_id
            == str(
                target[
                    "next_stint_team_id"
                ]
            )
        )

        differs_island = (
            parsed_team_id
            != str(
                target[
                    "island_team_id"
                ]
            )
        )

        resolution_status = (
            "RESOLVED_TO_SURROUNDING_TEAM"
            if (
                matches_prior
                and matches_next
                and differs_island
            )
            else
            "RESOLVED_OTHER_TEAM"
        )

        evidence_rows.append(
            {
                **base,
                "row_match_status": (
                    row_status
                ),
                "athlete_link_name": (
                    chosen[
                        "athlete_link_name"
                    ]
                ),
                "athlete_href": urljoin(
                    result_url,
                    str(
                        chosen[
                            "athlete_href"
                        ]
                    ),
                ),
                "parsed_team_id": (
                    parsed_team_id
                ),
                "parsed_team_name": (
                    mapped_team[
                        "team_name"
                    ]
                ),
                "parsed_team_url": (
                    mapped_team[
                        "parsed_team_url"
                    ]
                ),
                "team_mapping_method": (
                    mapped_team[
                        "team_mapping_method"
                    ]
                ),
                "matches_prior_team": (
                    matches_prior
                ),
                "matches_next_team": (
                    matches_next
                ),
                "differs_from_island_team": (
                    differs_island
                ),
                "resolution_status": (
                    resolution_status
                ),
            }
        )

    evidence = pd.DataFrame(
        evidence_rows
    )

    evidence.to_csv(
        OUTPUT_DIR
        / "island_result_evidence.csv",
        index=False,
    )

    resolution_summary = (
        evidence.groupby(
            [
                "resolution_status",
                "fetch_status",
                "row_match_status",
                "team_mapping_method",
            ],
            dropna=False,
        )
        .agg(
            island_count=(
                "school_stint_id",
                "nunique",
            ),
            canonical_person_count=(
                "canonical_person_id",
                "nunique",
            ),
        )
        .reset_index()
        .sort_values(
            [
                "resolution_status",
                "island_count",
            ],
            ascending=[
                True,
                False,
            ],
        )
    )

    resolution_summary.to_csv(
        OUTPUT_DIR
        / "resolution_status_summary.csv",
        index=False,
    )

    island_count = int(
        evidence[
            "school_stint_id"
        ].nunique()
    )

    person_count = int(
        evidence[
            "canonical_person_id"
        ].nunique()
    )

    performance_count = int(
        evidence[
            "canonical_person_performance_id"
        ].nunique()
    )

    duplicate_profile_targets = int(
        (
            evidence[
                "source_profile_count"
            ] > 1
        ).sum()
    )

    nonblank_urls = int(
        evidence[
            "result_url"
        ].fillna("")
        .ne("")
        .sum()
    )

    fetch_failures = int(
        ~evidence[
            "fetch_status"
        ].isin(
            [
                "FETCHED",
                "CACHE_HIT",
            ]
        )
        .sum()
    )

    surrounding_resolutions = int(
        evidence[
            "resolution_status"
        ].eq(
            "RESOLVED_TO_SURROUNDING_TEAM"
        ).sum()
    )

    unresolved_count = int(
        ~evidence[
            "resolution_status"
        ].eq(
            "RESOLVED_TO_SURROUNDING_TEAM"
        ).sum()
    )

    person_after = file_state(PERSON_DB)
    stint_after = file_state(STINT_DB)

    checks = pd.DataFrame(
        [
            (
                "target_single_meet_aba_islands",
                abs(
                    island_count
                    - EXPECTED_ISLANDS
                ),
                island_count,
                EXPECTED_ISLANDS,
            ),
            (
                "target_canonical_people",
                abs(
                    person_count
                    - EXPECTED_PEOPLE
                ),
                person_count,
                EXPECTED_PEOPLE,
            ),
            (
                "one_performance_per_island",
                abs(
                    performance_count
                    - EXPECTED_ISLANDS
                ),
                performance_count,
                EXPECTED_ISLANDS,
            ),
            (
                "duplicate_profile_target_rows",
                abs(
                    duplicate_profile_targets
                    - EXPECTED_ISLANDS
                ),
                duplicate_profile_targets,
                EXPECTED_ISLANDS,
            ),
            (
                "nonblank_result_urls",
                abs(
                    nonblank_urls
                    - EXPECTED_ISLANDS
                ),
                nonblank_urls,
                EXPECTED_ISLANDS,
            ),
            (
                "fetch_failures",
                fetch_failures,
                fetch_failures,
                0,
            ),
            (
                "resolved_to_surrounding_team",
                abs(
                    surrounding_resolutions
                    - EXPECTED_ISLANDS
                ),
                surrounding_resolutions,
                EXPECTED_ISLANDS,
            ),
            (
                "unresolved_or_other_team",
                unresolved_count,
                unresolved_count,
                0,
            ),
            (
                "person_db_size_unchanged",
                abs(
                    person_after["size_bytes"]
                    - person_before["size_bytes"]
                ),
                person_after["size_bytes"],
                person_before["size_bytes"],
            ),
            (
                "person_db_modified_time_unchanged",
                abs(
                    person_after["modified_ns"]
                    - person_before["modified_ns"]
                ),
                person_after["modified_ns"],
                person_before["modified_ns"],
            ),
            (
                "stint_db_size_unchanged",
                abs(
                    stint_after["size_bytes"]
                    - stint_before["size_bytes"]
                ),
                stint_after["size_bytes"],
                stint_before["size_bytes"],
            ),
            (
                "stint_db_modified_time_unchanged",
                abs(
                    stint_after["modified_ns"]
                    - stint_before["modified_ns"]
                ),
                stint_after["modified_ns"],
                stint_before["modified_ns"],
            ),
        ],
        columns=[
            "check_name",
            "failed_row_count",
            "observed_value",
            "expected_value",
        ],
    )

    checks.to_csv(
        OUTPUT_DIR / "hard_checks.csv",
        index=False,
    )

    failed = int(
        (
            checks["failed_row_count"] > 0
        ).sum()
    )

    resolved_team_summary = (
        " | ".join(
            sorted(
                {
                    (
                        f"{row.parsed_team_name} "
                        f"({row.parsed_team_id})"
                    )
                    for row in evidence.itertuples()
                    if row.parsed_team_id
                }
            )
        )
    )

    report = f"""MILESTONE 4 SCHOOL-STINT ISLAND RESULT EVIDENCE
============================================================
Audit version: {AUDIT_VERSION}
Source database modified: no
Canonical-person database modified: no
Diagnostic school-stint database modified: no
Overrides applied: no

SCOPE
- Target single-meet A-B-A islands:
  {island_count:,}
- Target canonical people:
  {person_count:,}
- Target canonical performances:
  {performance_count:,}
- Multi-profile duplicate performances:
  {duplicate_profile_targets:,}

RESULT-PAGE EVIDENCE
- Resolved to both surrounding teams:
  {surrounding_resolutions:,}
- Unresolved or resolved elsewhere:
  {unresolved_count:,}
- Parsed teams:
  {resolved_team_summary}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

INTERPRETATION
No stint correction has been applied. A successful audit establishes that the
exact TFRRS result row assigns each middle performance to the same team found
on both sides of its single-meet A-B-A sequence. Only then should targeted
canonical-person performance overrides be built.
"""

    (
        OUTPUT_DIR
        / "island_evidence_report.txt"
    ).write_text(
        report,
        encoding="utf-8",
    )

    print(
        "School-stint island evidence audit "
        "complete."
    )
    print(f"Outputs: {OUTPUT_DIR}")
    print(
        "Resolved to surrounding team: "
        f"{surrounding_resolutions:,}"
    )
    print(
        "Unresolved or other team: "
        f"{unresolved_count:,}"
    )
    print(f"Failed checks: {failed:,}.")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
