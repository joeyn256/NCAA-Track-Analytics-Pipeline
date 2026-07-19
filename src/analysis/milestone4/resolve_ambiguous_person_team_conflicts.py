#!/usr/bin/env python3
"""
Milestone 4: resolve ambiguous canonical-person team conflicts from result pages.

This is a targeted read-only evidence audit for the 162 conflict groups
classified as ONE_SOURCE_TEAM_BUT_NO_UNIQUE_MATCH.

It:
- reads the canonical-person database and conflict-audit CSV;
- fetches each distinct TFRRS result page once;
- finds the exact athlete row;
- extracts the team link and team name from that row;
- maps the parsed team back to source.core.teams when possible;
- writes evidence and unresolved queues.

It does not modify any database or apply corrections.

Outputs
-------
data/processed/milestone4/ambiguous_person_result_evidence/
    result_evidence_report.txt
    hard_checks.csv
    ambiguous_result_page_evidence.csv
    resolution_status_summary.csv
    resolved_team_summary.csv
    unresolved_groups.csv
    fetch_summary.csv
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
    / "canonical_person_layer/"
    / "canonical_person_layer.duckdb"
)

CONFLICT_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_person_team_conflict_audit/"
    / "conflict_group_summary.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "ambiguous_person_result_evidence"
)

CACHE_DIR = OUTPUT_DIR / "html_cache"

AUDIT_VERSION = (
    "m4_ambiguous_person_result_evidence_v1.1"
)

EXPECTED_TARGET_GROUPS = 162
EXPECTED_TARGET_PEOPLE = 8


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


def safe_text(
    value: object,
) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return str(value).strip()


def normalize_text(
    value: object,
) -> str:
    text = unicodedata.normalize(
        "NFKD",
        safe_text(value),
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


def normalize_url(
    value: object,
) -> str:
    text = safe_text(value)

    if not text:
        return ""

    parsed = urlparse(text)

    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    path = re.sub(
        r"/+",
        "/",
        parsed.path,
    ).rstrip("/")

    return f"{scheme}://{host}{path}"


def team_id_from_url(
    value: object,
) -> str:
    text = safe_text(value)

    if not text:
        return ""

    path = urlparse(text).path
    basename = Path(path).name

    if basename.endswith(".html"):
        basename = basename[:-5]

    return basename


def cache_path_for_url(
    url: str,
) -> Path:
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
        allowed_methods=[
            "GET",
        ],
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
                (
                    response.text[:500]
                    if response.text
                    else ""
                ),
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


def is_athlete_link(
    href: str,
) -> bool:
    lowered = href.lower()

    return (
        "/athletes/" in lowered
        or "athletes/" in lowered
    )


def is_team_link(
    href: str,
) -> bool:
    lowered = href.lower()

    return (
        "/teams/" in lowered
        or "/teams/tf/" in lowered
        or "teams/tf/" in lowered
    )


def candidate_rows_for_name(
    soup: BeautifulSoup,
    athlete_name: str,
) -> list[dict[str, object]]:
    target = normalize_text(
        athlete_name
    )

    candidates: list[
        dict[str, object]
    ] = []

    for athlete_link in soup.find_all(
        "a",
        href=True,
    ):
        href = str(
            athlete_link.get("href", "")
        )

        if not is_athlete_link(href):
            continue

        link_name = athlete_link.get_text(
            " ",
            strip=True,
        )

        if normalize_text(link_name) != target:
            continue

        row = athlete_link.find_parent(
            "tr"
        )

        if row is None:
            continue

        team_links = []

        for link in row.find_all(
            "a",
            href=True,
        ):
            team_href = str(
                link.get("href", "")
            )

            if not is_team_link(
                team_href
            ):
                continue

            team_links.append(
                {
                    "team_name": (
                        link.get_text(
                            " ",
                            strip=True,
                        )
                    ),
                    "team_url": team_href,
                }
            )

        unique_links: dict[
            tuple[str, str],
            dict[str, str],
        ] = {}

        for team in team_links:
            key = (
                normalize_text(
                    team["team_name"]
                ),
                str(team["team_url"]),
            )

            unique_links[key] = team

        candidates.append(
            {
                "athlete_link_name": (
                    link_name
                ),
                "athlete_href": href,
                "row_text": row.get_text(
                    " ",
                    strip=True,
                ),
                "team_links": list(
                    unique_links.values()
                ),
            }
        )

    return candidates


def choose_candidate_row(
    candidates: list[dict[str, object]],
    mark: object,
    place: object,
) -> tuple[
    dict[str, object] | None,
    str,
]:
    if not candidates:
        return (
            None,
            "ATHLETE_ROW_NOT_FOUND",
        )

    if len(candidates) == 1:
        return (
            candidates[0],
            "EXACT_NAME_SINGLE_ROW",
        )

    normalized_mark = normalize_text(
        mark
    )
    normalized_place = normalize_text(
        place
    )

    scored = []

    for candidate in candidates:
        row_text = normalize_text(
            candidate["row_text"]
        )

        score = 0

        if (
            normalized_mark
            and normalized_mark
            in row_text
        ):
            score += 2

        if (
            normalized_place
            and normalized_place
            in row_text
        ):
            score += 1

        scored.append(
            (
                score,
                candidate,
            )
        )

    scored.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    top_score = scored[0][0]

    top = [
        candidate
        for score, candidate in scored
        if score == top_score
    ]

    if (
        top_score > 0
        and len(top) == 1
    ):
        return (
            top[0],
            "EXACT_NAME_MARK_PLACE_ROW",
        )

    team_keys = set()

    for candidate in candidates:
        for team in candidate[
            "team_links"
        ]:
            team_keys.add(
                (
                    normalize_text(
                        team["team_name"]
                    ),
                    str(
                        team["team_url"]
                    ),
                )
            )

    if len(team_keys) == 1:
        return (
            candidates[0],
            "EXACT_NAME_MULTIPLE_ROWS_SAME_TEAM",
        )

    return (
        None,
        "MULTIPLE_MATCHING_ATHLETE_ROWS",
    )


def map_team(
    team_name: str,
    team_url: str,
    page_url: str,
    gender_code: str,
    teams_by_id: dict[str, dict[str, object]],
    teams_by_url: dict[str, dict[str, object]],
    teams_by_name_gender: dict[
        tuple[str, str],
        list[dict[str, object]],
    ],
) -> dict[str, object]:
    absolute_url = urljoin(
        page_url,
        team_url,
    )

    parsed_id = team_id_from_url(
        absolute_url
    )

    if parsed_id in teams_by_id:
        team = teams_by_id[
            parsed_id
        ].copy()

        team[
            "team_mapping_method"
        ] = "TEAM_ID_FROM_URL"

        team[
            "parsed_team_url"
        ] = absolute_url

        team[
            "parsed_team_name"
        ] = team_name

        return team

    normalized_absolute = normalize_url(
        absolute_url
    )

    if normalized_absolute in teams_by_url:
        team = teams_by_url[
            normalized_absolute
        ].copy()

        team[
            "team_mapping_method"
        ] = "EXACT_TEAM_URL"

        team[
            "parsed_team_url"
        ] = absolute_url

        team[
            "parsed_team_name"
        ] = team_name

        return team

    key = (
        normalize_text(team_name),
        str(gender_code or "").lower(),
    )

    name_matches = teams_by_name_gender.get(
        key,
        [],
    )

    if len(name_matches) == 1:
        team = name_matches[0].copy()

        team[
            "team_mapping_method"
        ] = "UNIQUE_TEAM_NAME_GENDER"

        team[
            "parsed_team_url"
        ] = absolute_url

        team[
            "parsed_team_name"
        ] = team_name

        return team

    return {
        "team_id": "",
        "team_name": team_name,
        "school_id": "",
        "gender_code": gender_code,
        "division": "",
        "in_division_i_directory": None,
        "team_url": "",
        "team_mapping_method": (
            "PARSED_TEAM_LINK_UNMAPPED"
        ),
        "parsed_team_url": absolute_url,
        "parsed_team_name": team_name,
    }


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
        / "result_evidence_report.txt",
        OUTPUT_DIR
        / "hard_checks.csv",
        OUTPUT_DIR
        / "ambiguous_result_page_evidence.csv",
        OUTPUT_DIR
        / "resolution_status_summary.csv",
        OUTPUT_DIR
        / "resolved_team_summary.csv",
        OUTPUT_DIR
        / "unresolved_groups.csv",
        OUTPUT_DIR
        / "fetch_summary.csv",
    ]

    existing = [
        path
        for path in generated
        if path.exists()
    ]

    if existing and not replace_output:
        raise FileExistsError(
            "Result-evidence outputs already exist. "
            "Use --replace-output only after reviewing "
            "the current files."
        )

    if replace_output:
        for path in existing:
            path.unlink()


def main() -> None:
    args = parse_args()

    for path in [
        SOURCE_DB,
        PERSON_DB,
        CONFLICT_CSV,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )

    prepare_output(
        replace_output=args.replace_output,
    )

    conflicts = pd.read_csv(
        CONFLICT_CSV,
        dtype={
            "canonical_person_id": str,
            "canonical_person_performance_id": str,
            "season_id": str,
            "meet_id": str,
        },
    )

    targets = conflicts.loc[
        conflicts[
            "evidence_resolution_class"
        ].eq(
            "ONE_SOURCE_TEAM_BUT_NO_UNIQUE_MATCH"
        ),
        [
            "canonical_person_id",
            "canonical_person_performance_id",
            "athlete_name",
            "season_id",
            "season_year",
            "season_type",
            "meet_id",
            "meet_name",
            "meet_date_text",
            "event",
            "mark",
            "place",
            "result_url",
            "canonical_team_ids",
            "canonical_school_names",
            "source_team_ids",
            "source_schools",
        ],
    ].copy()

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

        con.register(
            "targets_input",
            targets,
        )

        target_metadata = con.execute(
            """
            SELECT
                t.*,
                MIN(
                    m.canonical_gender_code
                ) AS canonical_gender_code,
                COUNT(*)
                    AS mapped_source_rows,
                COUNT(
                    DISTINCT m.athlete_id
                ) AS mapped_profile_count

            FROM targets_input t

            JOIN person
                .canonical_person_performance_map m
              ON t.canonical_person_performance_id
                    =
                    m.canonical_person_performance_id

            GROUP BY ALL
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
        try:
            con.unregister(
                "targets_input"
            )
        except Exception:
            pass

        con.close()

    # Keep one row per target conflict group.
    target_metadata = (
        target_metadata
        .drop_duplicates(
            subset=[
                "canonical_person_performance_id"
            ]
        )
        .copy()
    )

    teams_by_id: dict[
        str,
        dict[str, object],
    ] = {}

    teams_by_url: dict[
        str,
        dict[str, object],
    ] = {}

    teams_by_name_gender: dict[
        tuple[str, str],
        list[dict[str, object]],
    ] = {}

    for row in teams.to_dict(
        orient="records"
    ):
        team_id = safe_text(
            row.get("team_id", "")
        )

        if team_id:
            teams_by_id[team_id] = row

        team_url = normalize_url(
            row.get("team_url", "")
        )

        if team_url:
            teams_by_url[
                team_url
            ] = row

        key = (
            normalize_text(
                row.get("team_name", "")
            ),
            safe_text(
                row.get(
                    "gender_code",
                    "",
                )
            ).lower(),
        )

        teams_by_name_gender.setdefault(
            key,
            [],
        ).append(row)

    session = build_session()

    fetch_cache: dict[
        str,
        tuple[str, str, str],
    ] = {}

    evidence_rows: list[
        dict[str, object]
    ] = []

    print(
        "Resolving ambiguous conflict groups "
        "from result pages..."
    )

    for index, target in enumerate(
        target_metadata.to_dict(
            orient="records"
        ),
        start=1,
    ):
        result_url = safe_text(
            target.get("result_url", "")
        )

        if not result_url:
            evidence_rows.append(
                {
                    **target,
                    "fetch_status": (
                        "BLANK_RESULT_URL"
                    ),
                    "fetch_error": "",
                    "row_match_status": (
                        "NOT_ATTEMPTED"
                    ),
                    "athlete_link_name": "",
                    "athlete_href": "",
                    "parsed_team_name": "",
                    "parsed_team_url": "",
                    "parsed_team_id": "",
                    "parsed_school_id": "",
                    "parsed_division": "",
                    "parsed_in_d1_directory": (
                        None
                    ),
                    "team_mapping_method": "",
                    "resolution_status": (
                        "UNRESOLVED"
                    ),
                }
            )
            continue

        if result_url not in fetch_cache:
            fetch_cache[
                result_url
            ] = fetch_html(
                session=session,
                url=result_url,
                refresh_cache=(
                    args.refresh_cache
                ),
                request_delay=(
                    args.request_delay
                ),
            )

        html, fetch_status, fetch_error = (
            fetch_cache[result_url]
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
                    "parsed_team_name": "",
                    "parsed_team_url": "",
                    "parsed_team_id": "",
                    "parsed_school_id": "",
                    "parsed_division": "",
                    "parsed_in_d1_directory": (
                        None
                    ),
                    "team_mapping_method": "",
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

        candidates = candidate_rows_for_name(
            soup=soup,
            athlete_name=safe_text(
                target.get(
                    "athlete_name",
                    "",
                )
            ),
        )

        chosen, row_status = (
            choose_candidate_row(
                candidates=candidates,
                mark=target.get("mark"),
                place=target.get("place"),
            )
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
                    "parsed_team_name": "",
                    "parsed_team_url": "",
                    "parsed_team_id": "",
                    "parsed_school_id": "",
                    "parsed_division": "",
                    "parsed_in_d1_directory": (
                        None
                    ),
                    "team_mapping_method": "",
                    "resolution_status": (
                        "UNRESOLVED"
                    ),
                }
            )
            continue

        team_links = chosen[
            "team_links"
        ]

        distinct_team_keys = {
            (
                normalize_text(
                    team["team_name"]
                ),
                str(team["team_url"]),
            )
            for team in team_links
        }

        if len(distinct_team_keys) != 1:
            evidence_rows.append(
                {
                    **base,
                    "row_match_status": (
                        "TEAM_LINK_COUNT_"
                        f"{len(distinct_team_keys)}"
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
                    "parsed_team_name": "",
                    "parsed_team_url": "",
                    "parsed_team_id": "",
                    "parsed_school_id": "",
                    "parsed_division": "",
                    "parsed_in_d1_directory": (
                        None
                    ),
                    "team_mapping_method": "",
                    "resolution_status": (
                        "UNRESOLVED"
                    ),
                }
            )
            continue

        team_link = team_links[0]

        mapped = map_team(
            team_name=str(
                team_link["team_name"]
            ),
            team_url=str(
                team_link["team_url"]
            ),
            page_url=result_url,
            gender_code=safe_text(
                target.get(
                    "canonical_gender_code",
                    "",
                )
            ),
            teams_by_id=teams_by_id,
            teams_by_url=teams_by_url,
            teams_by_name_gender=(
                teams_by_name_gender
            ),
        )

        parsed_team_id = safe_text(
            mapped.get(
                "team_id",
                "",
            )
        )

        resolution_status = (
            "RESOLVED_EXACT_RESULT_ROW"
            if parsed_team_id
            else
            "PARSED_TEAM_LINK_UNMAPPED"
        )

        evidence_rows.append(
            {
                **base,
                "row_match_status": row_status,
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
                "parsed_team_name": (
                    mapped[
                        "parsed_team_name"
                    ]
                ),
                "parsed_team_url": (
                    mapped[
                        "parsed_team_url"
                    ]
                ),
                "parsed_team_id": (
                    parsed_team_id
                ),
                "parsed_school_id": (
                    mapped.get(
                        "school_id",
                        "",
                    )
                ),
                "parsed_division": (
                    mapped.get(
                        "division",
                        "",
                    )
                ),
                "parsed_in_d1_directory": (
                    mapped.get(
                        "in_division_i_directory"
                    )
                ),
                "team_mapping_method": (
                    mapped[
                        "team_mapping_method"
                    ]
                ),
                "resolution_status": (
                    resolution_status
                ),
            }
        )

        if (
            index % 25 == 0
            or index == len(
                target_metadata
            )
        ):
            print(
                f"Processed {index:,} / "
                f"{len(target_metadata):,}"
            )

    evidence = pd.DataFrame(
        evidence_rows
    )

    evidence.to_csv(
        OUTPUT_DIR
        / "ambiguous_result_page_evidence.csv",
        index=False,
    )

    unresolved = evidence.loc[
        ~evidence[
            "resolution_status"
        ].eq(
            "RESOLVED_EXACT_RESULT_ROW"
        )
    ].copy()

    unresolved.to_csv(
        OUTPUT_DIR
        / "unresolved_groups.csv",
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
            conflict_group_count=(
                "canonical_person_performance_id",
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
                "conflict_group_count",
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

    resolved_team_summary = (
        evidence.loc[
            evidence[
                "resolution_status"
            ].eq(
                "RESOLVED_EXACT_RESULT_ROW"
            )
        ]
        .groupby(
            [
                "parsed_team_id",
                "parsed_team_name",
                "parsed_school_id",
                "parsed_division",
                "parsed_in_d1_directory",
            ],
            dropna=False,
        )
        .agg(
            conflict_group_count=(
                "canonical_person_performance_id",
                "nunique",
            ),
            canonical_person_count=(
                "canonical_person_id",
                "nunique",
            ),
            first_season_year=(
                "season_year",
                "min",
            ),
            last_season_year=(
                "season_year",
                "max",
            ),
        )
        .reset_index()
        .sort_values(
            [
                "conflict_group_count",
                "parsed_team_id",
            ],
            ascending=[
                False,
                True,
            ],
        )
    )

    resolved_team_summary.to_csv(
        OUTPUT_DIR
        / "resolved_team_summary.csv",
        index=False,
    )

    fetch_summary = pd.DataFrame(
        [
            {
                "fetch_status": status,
                "result_url_count": sum(
                    1
                    for (
                        _html,
                        current_status,
                        _error,
                    ) in fetch_cache.values()
                    if current_status == status
                ),
            }
            for status in sorted(
                {
                    status
                    for (
                        _html,
                        status,
                        _error,
                    ) in fetch_cache.values()
                }
            )
        ]
    )

    fetch_summary.to_csv(
        OUTPUT_DIR
        / "fetch_summary.csv",
        index=False,
    )

    target_groups = int(
        evidence[
            "canonical_person_performance_id"
        ].nunique()
    )

    target_people = int(
        evidence[
            "canonical_person_id"
        ].nunique()
    )

    duplicate_target_ids = int(
        len(evidence)
        - evidence[
            "canonical_person_performance_id"
        ].nunique()
    )

    blank_result_urls = int(
        evidence[
            "result_url"
        ].fillna("")
        .eq("")
        .sum()
    )

    fetch_error_rows = int(
        (
            ~evidence[
                "fetch_status"
            ].isin(
                [
                    "FETCHED",
                    "CACHE_HIT",
                ]
            )
        ).sum()
    )

    resolved_rows = int(
        evidence[
            "resolution_status"
        ].eq(
            "RESOLVED_EXACT_RESULT_ROW"
        )
        .sum()
    )

    unresolved_rows = int(
        len(evidence)
        - resolved_rows
    )

    checks = pd.DataFrame(
        [
            (
                "target_conflict_groups",
                abs(
                    target_groups
                    - EXPECTED_TARGET_GROUPS
                ),
                target_groups,
                EXPECTED_TARGET_GROUPS,
            ),
            (
                "target_canonical_people",
                abs(
                    target_people
                    - EXPECTED_TARGET_PEOPLE
                ),
                target_people,
                EXPECTED_TARGET_PEOPLE,
            ),
            (
                "duplicate_target_group_ids",
                duplicate_target_ids,
                duplicate_target_ids,
                0,
            ),
            (
                "blank_result_urls",
                blank_result_urls,
                blank_result_urls,
                0,
            ),
            (
                "fetch_error_rows",
                fetch_error_rows,
                fetch_error_rows,
                0,
            ),
            (
                "unresolved_result_page_groups",
                unresolved_rows,
                unresolved_rows,
                0,
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
        OUTPUT_DIR
        / "hard_checks.csv",
        index=False,
    )

    failed = int(
        (
            checks[
                "failed_row_count"
            ] > 0
        ).sum()
    )

    resolved_d1 = int(
        evidence.loc[
            evidence[
                "resolution_status"
            ].eq(
                "RESOLVED_EXACT_RESULT_ROW"
            ),
            "parsed_in_d1_directory",
        ]
        .fillna(False)
        .astype(bool)
        .sum()
    )

    resolved_non_d1 = (
        resolved_rows - resolved_d1
    )

    report = f"""MILESTONE 4 AMBIGUOUS PERSON RESULT-PAGE EVIDENCE
============================================================
Audit version: {AUDIT_VERSION}
Source database modified: no
Canonical-person database modified: no
Conflict-audit outputs modified: no
Correction rules applied: no

SCOPE
- Target conflict groups: {target_groups:,}
- Target canonical people: {target_people:,}
- Distinct result URLs fetched or cached:
  {len(fetch_cache):,}

RESULTS
- Exact result-row team resolutions:
  {resolved_rows:,}
- Resolved to D1 directory teams:
  {resolved_d1:,}
- Resolved outside D1 directory:
  {resolved_non_d1:,}
- Unresolved result-page groups:
  {unresolved_rows:,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

INTERPRETATION
This audit uses the exact athlete row on each TFRRS result page. It does not
select a team from profile-section precedence, current source-team metadata,
or surrounding chronology. Any unresolved rows remain blocking and must be
reviewed before the canonical-person layer is rebuilt.
"""

    (
        OUTPUT_DIR
        / "result_evidence_report.txt"
    ).write_text(
        report,
        encoding="utf-8",
    )

    print(
        "Ambiguous person result-page evidence "
        "audit complete."
    )
    print(f"Outputs: {OUTPUT_DIR}")
    print(f"Resolved groups: {resolved_rows:,}")
    print(f"Unresolved groups: {unresolved_rows:,}")
    print(f"Failed checks: {failed:,}.")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
