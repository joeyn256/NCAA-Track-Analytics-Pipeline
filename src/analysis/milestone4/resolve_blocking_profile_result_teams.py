#!/usr/bin/env python3
"""
Milestone 4: full result-page team resolution for the 27 blocking profiles.

This is a selective, read-only reconstruction pass. It resolves the team shown
on the athlete's exact TFRRS result-page row for every distinct result URL
belonging to the 27 profiles whose current school could not be inferred safely
during the all-profile parse.

It does NOT modify:
- data/database/ncaa_track_analytics.duckdb
- all_profile_staging.duckdb
- raw athlete HTML
- any prior attribution output

Inputs
------
- data/processed/milestone4/all_profile_audit/
    unresolved_current_school_profiles.csv
- data/processed/milestone4/current_school_repair/
    current_school_repair_candidates.csv
- data/database/ncaa_track_analytics.duckdb

Outputs
-------
data/processed/milestone4/blocking_profile_result_resolution/
    result_page_team_resolution.csv
    performance_team_resolution.csv
    athlete_team_season_summary.csv
    team_resolution_summary.csv
    unresolved_result_page_queue.csv
    core_team_alias_review_queue.csv
    fetch_status.csv
    hard_checks.csv
    resolution_report.txt
    page_cache/

Resolution hierarchy
--------------------
1. Find the exact athlete link on the result page.
2. Read the team link from the same result-table row.
3. Normalize the resolved team name.
4. Exact-match that name to a core school and the performance gender.
5. Leave non-core institutions as explicit non-core team evidence.
6. Never use fuzzy matching as automatic merge evidence.

Pages already fetched by the three-athlete prototype are reused from its cache.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import duckdb
import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_ROOT = Path(__file__).resolve().parents[3]

SOURCE_DB = (
    PROJECT_ROOT / "data/database/ncaa_track_analytics.duckdb"
)
UNRESOLVED_INPUT = (
    PROJECT_ROOT
    / "data/processed/milestone4/all_profile_audit"
    / "unresolved_current_school_profiles.csv"
)
HEADER_CANDIDATE_INPUT = (
    PROJECT_ROOT
    / "data/processed/milestone4/current_school_repair"
    / "current_school_repair_candidates.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "blocking_profile_result_resolution"
)
CACHE_DIR = OUTPUT_DIR / "page_cache"
PROTOTYPE_CACHE_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "result_team_resolution_prototype/page_cache"
)

BASE_URL = "https://www.tfrrs.org/"
RESOLUTION_VERSION = "m4_blocking_result_resolution_v1.3"

NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
TEAM_HREF_RE = re.compile(
    r"/teams?(?:/|$)|/team/",
    re.IGNORECASE,
)

FIXTURE_EXPECTATIONS = {
    6134984: {"Jackson State"},
    6907335: {"Tulsa", "Missouri Southern"},
    8716406: {"Marywood"},
}

# Exact, manually documented result-page name variants.
# These aliases are scoped to a stable athlete ID and are never inferred
# from name similarity alone.
ATHLETE_NAME_ALIASES = {
    8322164: {"Calvin Storms"},
}

# Deterministic source aliases observed directly on TFRRS result pages.
# These are exact, documented variants—not fuzzy matches.
TEAM_ALIAS_MAP = {
    "ohiou": "ohio",
    "albany": "ualbany",
}


def clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split()).strip()


def normalize_name(value: object) -> str:
    return NON_ALNUM_RE.sub(
        "",
        clean(value).lower(),
    )


def team_mapping_key(value: object) -> str:
    normalized = normalize_name(value)
    return TEAM_ALIAS_MAP.get(
        normalized,
        normalized,
    )


def is_unattached_team(value: object) -> bool:
    normalized = normalize_name(value)

    return (
        normalized == "unattached"
        or normalized.startswith("unat")
        or normalized.endswith("unattached")
    )


def normalize_url(value: object) -> str:
    text = clean(value)

    if not text:
        return ""

    text = text.replace(
        "https://www.tfrrs.orghttps://",
        "https://",
    ).replace(
        "https://tfrrs.orghttps://",
        "https://",
    )

    absolute = urljoin(BASE_URL, text)
    split = urlsplit(absolute)

    return urlunsplit(
        (
            split.scheme.lower(),
            split.netloc.lower(),
            split.path.rstrip("/") or "/",
            split.query,
            "",
        )
    )


def cache_filename(url: str) -> str:
    return (
        hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()
        + ".html"
    )


def build_session() -> requests.Session:
    session = requests.Session()

    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=4,
        pool_maxsize=4,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update(
        {
            "User-Agent": (
                "NCAA-Track-Analytics-Milestone4/"
                "1.0 (research; respectful rate limiting)"
            )
        }
    )

    return session


def fetch_page(
    session: requests.Session,
    url: str,
    delay_seconds: float,
) -> tuple[str, dict[str, Any]]:
    filename = cache_filename(url)
    local_path = CACHE_DIR / filename
    prototype_path = PROTOTYPE_CACHE_DIR / filename

    if local_path.exists():
        return (
            local_path.read_text(
                encoding="utf-8",
                errors="ignore",
            ),
            {
                "fetch_status": "CACHE_HIT",
                "http_status": 200,
                "cache_file": str(local_path),
                "error_message": "",
            },
        )

    if prototype_path.exists():
        html = prototype_path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
        local_path.write_text(
            html,
            encoding="utf-8",
        )
        return (
            html,
            {
                "fetch_status": "PROTOTYPE_CACHE_HIT",
                "http_status": 200,
                "cache_file": str(local_path),
                "error_message": "",
            },
        )

    response = session.get(
        url,
        timeout=(15, 45),
    )
    status = int(response.status_code)

    if status != 200:
        return (
            "",
            {
                "fetch_status": "HTTP_ERROR",
                "http_status": status,
                "cache_file": "",
                "error_message": (
                    clean(response.reason)
                    or f"HTTP {status}"
                ),
            },
        )

    local_path.write_text(
        response.text,
        encoding="utf-8",
    )
    time.sleep(delay_seconds)

    return (
        response.text,
        {
            "fetch_status": "FETCHED",
            "http_status": status,
            "cache_file": str(local_path),
            "error_message": "",
        },
    )


def athlete_name_variants(
    value: str,
    athlete_id: int | None = None,
) -> set[str]:
    raw = clean(value)
    variants = {normalize_name(raw)}

    if "," in raw:
        last, first = raw.split(",", 1)
        variants.add(
            normalize_name(
                f"{clean(first)} {clean(last)}"
            )
        )

    if athlete_id is not None:
        for alias in ATHLETE_NAME_ALIASES.get(
            int(athlete_id),
            set(),
        ):
            variants.add(normalize_name(alias))

    return {
        variant
        for variant in variants
        if variant
    }


def team_anchor_candidates(row: Tag) -> list[Tag]:
    candidates: list[Tag] = []

    for anchor in row.find_all(
        "a",
        href=True,
    ):
        href = urlsplit(
            normalize_url(
                anchor.get("href")
            )
        ).path
        text = clean(
            anchor.get_text(
                " ",
                strip=True,
            )
        )

        if text and TEAM_HREF_RE.search(href):
            candidates.append(anchor)

    return candidates


def direct_cells(row: Tag) -> list[Tag]:
    return [
        cell
        for cell in row.find_all(
            ["td", "th"],
            recursive=False,
        )
        if isinstance(cell, Tag)
    ]


def find_team_column_index(row: Tag) -> int | None:
    table = row.find_parent("table")
    prior = row.find_previous("tr")

    while isinstance(prior, Tag):
        if prior.find_parent("table") is not table:
            break

        labels = [
            clean(
                cell.get_text(
                    " ",
                    strip=True,
                )
            ).upper()
            for cell in direct_cells(prior)
        ]

        if "TEAM" in labels:
            return labels.index("TEAM")

        prior = prior.find_previous("tr")

    return None


def extract_plain_team_from_row(
    row: Tag,
    athlete_anchor: Tag,
) -> str:
    cells = direct_cells(row)

    if not cells:
        return ""

    athlete_cell = athlete_anchor.find_parent(
        ["td", "th"]
    )

    team_index = find_team_column_index(row)

    if (
        team_index is not None
        and team_index < len(cells)
    ):
        candidate = clean(
            cells[team_index].get_text(
                " ",
                strip=True,
            )
        )

        if candidate:
            return candidate

    if isinstance(athlete_cell, Tag):
        try:
            athlete_index = cells.index(
                athlete_cell
            )
        except ValueError:
            athlete_index = -1

        # Standard individual layout:
        # PL | NAME | YEAR | TEAM | MARK
        if (
            athlete_index >= 0
            and athlete_index + 2 < len(cells)
        ):
            candidate = clean(
                cells[
                    athlete_index + 2
                ].get_text(
                    " ",
                    strip=True,
                )
            )

            if candidate:
                return candidate

        # Relay layout:
        # PL | TEAM | SQUAD | ATHLETES | MARK
        if (
            athlete_index >= 2
            and athlete_index - 2 < len(cells)
        ):
            candidate = clean(
                cells[
                    athlete_index - 2
                ].get_text(
                    " ",
                    strip=True,
                )
            )

            if candidate:
                return candidate

    # Some relay layouts split the team/squad and athlete names across
    # adjacent rows. Inspect up to two preceding rows within the same table.
    table = row.find_parent("table")
    prior = row.find_previous_sibling("tr")
    inspected = 0

    while (
        isinstance(prior, Tag)
        and inspected < 2
    ):
        if prior.find_parent("table") is not table:
            break

        prior_cells = direct_cells(prior)

        if (
            team_index is not None
            and team_index < len(prior_cells)
        ):
            candidate = clean(
                prior_cells[
                    team_index
                ].get_text(
                    " ",
                    strip=True,
                )
            )

            if candidate:
                return candidate

        prior = prior.find_previous_sibling(
            "tr"
        )
        inspected += 1

    return ""


def extract_team_from_result_page(
    html: str,
    athlete_id: int,
    athlete_name: str,
) -> dict[str, Any]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    athlete_href_re = re.compile(
        rf"/athletes/{athlete_id}(?:/|$)",
        re.IGNORECASE,
    )
    variants = athlete_name_variants(
        athlete_name,
        athlete_id=athlete_id,
    )

    athlete_anchors: list[Tag] = []

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        href = urlsplit(
            normalize_url(
                anchor.get("href")
            )
        ).path
        anchor_text = normalize_name(
            anchor.get_text(
                " ",
                strip=True,
            )
        )

        # Prefer the exact TFRRS athlete ID, but accept an exact rendered
        # athlete-name match for DirectAthletics-linked historical rows.
        if athlete_href_re.search(href):
            athlete_anchors.append(anchor)
        elif anchor_text in variants:
            athlete_anchors.append(anchor)

    observations: list[dict[str, str]] = []

    for athlete_anchor in athlete_anchors:
        row = athlete_anchor.find_parent("tr")

        if not isinstance(row, Tag):
            continue

        team_anchors = [
            anchor
            for anchor in team_anchor_candidates(row)
            if anchor is not athlete_anchor
        ]

        linked_teams = list(
            dict.fromkeys(
                clean(
                    anchor.get_text(
                        " ",
                        strip=True,
                    )
                )
                for anchor in team_anchors
                if clean(
                    anchor.get_text(
                        " ",
                        strip=True,
                    )
                )
            )
        )

        teams_for_row = linked_teams

        if not teams_for_row:
            plain_team = (
                extract_plain_team_from_row(
                    row=row,
                    athlete_anchor=athlete_anchor,
                )
            )

            if plain_team:
                teams_for_row = [plain_team]

        for team in teams_for_row:
            observations.append(
                {
                    "resolved_team": team,
                    "row_text": clean(
                        row.get_text(
                            " ",
                            strip=True,
                        )
                    )[:1000],
                }
            )

    teams = list(
        dict.fromkeys(
            observation["resolved_team"]
            for observation in observations
            if observation["resolved_team"]
        )
    )

    if len(teams) == 1:
        resolution_status = (
            "EXACT_ATHLETE_ROW_TEAM"
        )
        resolved_team = teams[0]
    elif len(teams) > 1:
        resolution_status = (
            "CONFLICTING_TEAM_ROWS"
        )
        resolved_team = ""
    elif athlete_anchors:
        resolution_status = (
            "ATHLETE_FOUND_TEAM_NOT_FOUND"
        )
        resolved_team = ""
    else:
        resolution_status = (
            "ATHLETE_NOT_FOUND"
        )
        resolved_team = ""

    normalized_team = normalize_name(
        resolved_team
    )

    return {
        "resolution_status": resolution_status,
        "resolved_team": resolved_team,
        "resolved_team_normalized": (
            normalized_team
        ),
        "resolved_team_mapping_key": (
            team_mapping_key(
                resolved_team
            )
        ),
        "team_alias_applied": (
            bool(normalized_team)
            and team_mapping_key(
                resolved_team
            )
            != normalized_team
        ),
        "is_unattached": (
            is_unattached_team(
                resolved_team
            )
        ),
        "athlete_anchor_count": len(
            athlete_anchors
        ),
        "team_observation_count": len(
            observations
        ),
        "observed_teams": " | ".join(
            teams
        ),
        "sample_row_text": (
            observations[0]["row_text"]
            if observations
            else ""
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--delay",
        type=float,
        default=0.75,
        help=(
            "Delay after each newly fetched page. "
            "Default: 0.75 seconds."
        ),
    )
    parser.add_argument(
        "--limit-pages",
        type=int,
        default=None,
        help=(
            "Optional smoke-test limit on distinct "
            "athlete/result-page pairs."
        ),
    )

    return parser.parse_args()


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    unresolved = pd.read_csv(
        UNRESOLVED_INPUT,
        dtype=str,
        keep_default_na=False,
    )
    candidates = pd.read_csv(
        HEADER_CANDIDATE_INPUT,
        dtype=str,
        keep_default_na=False,
    )

    for frame in [
        unresolved,
        candidates,
    ]:
        frame["athlete_id"] = (
            pd.to_numeric(
                frame["athlete_id"],
                errors="raise",
            )
            .astype("int64")
        )

    return unresolved, candidates


def load_performances(
    con: duckdb.DuckDBPyConnection,
    athlete_ids: list[int],
) -> pd.DataFrame:
    placeholders = ", ".join(
        "?" for _ in athlete_ids
    )

    frame = con.execute(
        f"""
        WITH affiliation_gender AS (
            SELECT
                af.athlete_id,
                CASE
                    WHEN COUNT(
                        DISTINCT t.gender_code
                    ) = 1
                    THEN MIN(t.gender_code)
                    ELSE NULL
                END AS affiliation_gender_code
            FROM core.athlete_affiliations af
            JOIN core.teams t
              ON af.team_id = t.team_id
            WHERE af.athlete_id IN ({placeholders})
            GROUP BY af.athlete_id
        )
        SELECT
            p.performance_id,
            p.athlete_id,
            a.athlete_name,
            p.meet_id,
            p.season_id,
            p.season_year,
            p.season_type,
            p.meet_name,
            p.meet_date_text,
            p.event,
            p.mark,
            p.result_url,
            p.team_id AS original_team_id,
            t.gender_code AS original_gender_code,
            ag.affiliation_gender_code,
            COALESCE(
                t.gender_code,
                ag.affiliation_gender_code
            ) AS gender_code,
            s.school_name AS original_school
        FROM core.performances p
        JOIN core.athletes a
          ON p.athlete_id = a.athlete_id
        LEFT JOIN core.teams t
          ON p.team_id = t.team_id
        LEFT JOIN core.schools s
          ON t.school_id = s.school_id
        LEFT JOIN affiliation_gender ag
          ON p.athlete_id = ag.athlete_id
        WHERE p.athlete_id IN ({placeholders})
        ORDER BY
            p.athlete_id,
            p.performance_id
        """,
        [
            *athlete_ids,
            *athlete_ids,
        ],
    ).fetchdf()

    frame["athlete_id"] = (
        pd.to_numeric(
            frame["athlete_id"],
            errors="raise",
        )
        .astype("int64")
    )
    frame["normalized_result_url"] = (
        frame["result_url"].map(
            normalize_url
        )
    )

    return frame


def load_core_team_map(
    con: duckdb.DuckDBPyConnection,
) -> pd.DataFrame:
    frame = con.execute(
        """
        SELECT
            t.team_id AS resolved_core_team_id,
            t.gender_code,
            s.school_id AS resolved_core_school_id,
            s.school_name AS resolved_core_school_name
        FROM core.teams t
        JOIN core.schools s
          ON t.school_id = s.school_id
        """
    ).fetchdf()

    frame[
        "resolved_team_mapping_key"
    ] = frame[
        "resolved_core_school_name"
    ].map(team_mapping_key)

    counts = (
        frame.groupby(
            [
                "resolved_team_mapping_key",
                "gender_code",
            ]
        )["resolved_core_team_id"]
        .transform("count")
    )

    frame["core_team_match_count"] = counts

    return frame


def main() -> None:
    args = parse_args()

    if args.delay < 0:
        raise ValueError(
            "--delay cannot be negative."
        )

    for path in [
        SOURCE_DB,
        UNRESOLVED_INPUT,
        HEADER_CANDIDATE_INPUT,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    unresolved, candidates = load_inputs()
    athlete_ids = sorted(
        unresolved["athlete_id"]
        .astype(int)
        .unique()
        .tolist()
    )

    con = duckdb.connect(
        str(SOURCE_DB),
        read_only=True,
    )

    try:
        performances = load_performances(
            con=con,
            athlete_ids=athlete_ids,
        )
        core_team_map = load_core_team_map(
            con
        )
    finally:
        con.close()

    candidate_columns = candidates[
        [
            "athlete_id",
            "proposed_current_school",
            "candidate_method",
            "candidate_confidence",
        ]
    ].rename(
        columns={
            "proposed_current_school": (
                "profile_header_school"
            ),
            "candidate_method": (
                "profile_header_method"
            ),
            "candidate_confidence": (
                "profile_header_confidence"
            ),
        }
    )

    performances = performances.merge(
        candidate_columns,
        how="left",
        on="athlete_id",
        validate="many_to_one",
    )

    missing_url_mask = (
        performances[
            "normalized_result_url"
        ].eq("")
    )

    page_pairs = (
        performances.loc[
            ~missing_url_mask,
            [
                "athlete_id",
                "athlete_name",
                "normalized_result_url",
            ],
        ]
        .drop_duplicates()
        .sort_values(
            [
                "athlete_id",
                "normalized_result_url",
            ]
        )
        .reset_index(drop=True)
    )

    if args.limit_pages is not None:
        page_pairs = page_pairs.head(
            args.limit_pages
        )

    session = build_session()
    page_rows: list[dict[str, Any]] = []
    fetch_rows: list[dict[str, Any]] = []

    total_pages = len(page_pairs)

    for index, source in enumerate(
        page_pairs.to_dict("records"),
        start=1,
    ):
        athlete_id = int(
            source["athlete_id"]
        )
        athlete_name = clean(
            source["athlete_name"]
        )
        result_url = clean(
            source[
                "normalized_result_url"
            ]
        )

        try:
            html, fetch = fetch_page(
                session=session,
                url=result_url,
                delay_seconds=args.delay,
            )

            fetch_rows.append(
                {
                    "athlete_id": athlete_id,
                    "athlete_name": athlete_name,
                    "result_url": result_url,
                    **fetch,
                }
            )

            if html:
                resolution = (
                    extract_team_from_result_page(
                        html=html,
                        athlete_id=athlete_id,
                        athlete_name=athlete_name,
                    )
                )
            else:
                resolution = {
                    "resolution_status": (
                        "PAGE_NOT_AVAILABLE"
                    ),
                    "resolved_team": "",
                    "resolved_team_normalized": "",
                    "resolved_team_mapping_key": "",
                    "team_alias_applied": False,
                    "is_unattached": False,
                    "athlete_anchor_count": 0,
                    "team_observation_count": 0,
                    "observed_teams": "",
                    "sample_row_text": "",
                }

        except Exception as exc:
            fetch = {
                "fetch_status": "ERROR",
                "http_status": None,
                "cache_file": "",
                "error_message": (
                    f"{type(exc).__name__}: "
                    f"{clean(exc)}"
                ),
            }
            resolution = {
                "resolution_status": "ERROR",
                "resolved_team": "",
                "resolved_team_normalized": "",
                "athlete_anchor_count": 0,
                "team_observation_count": 0,
                "observed_teams": "",
                "sample_row_text": "",
            }

            fetch_rows.append(
                {
                    "athlete_id": athlete_id,
                    "athlete_name": athlete_name,
                    "result_url": result_url,
                    **fetch,
                }
            )

        page_rows.append(
            {
                "athlete_id": athlete_id,
                "athlete_name": athlete_name,
                "result_url": result_url,
                "fetch_status": fetch[
                    "fetch_status"
                ],
                "http_status": fetch[
                    "http_status"
                ],
                "cache_file": fetch[
                    "cache_file"
                ],
                "fetch_error_message": fetch[
                    "error_message"
                ],
                **resolution,
                "resolution_version": (
                    RESOLUTION_VERSION
                ),
            }
        )

        if (
            index % 25 == 0
            or index == total_pages
        ):
            print(
                f"Resolved pages: "
                f"{index:,}/{total_pages:,}"
            )

    pages = pd.DataFrame(page_rows)
    fetch_status = pd.DataFrame(
        fetch_rows
    )

    # Exact normalized school-name + gender mapping only.
    core_exact = core_team_map.loc[
        core_team_map[
            "core_team_match_count"
        ]
        == 1
    ].copy()

    performance_resolution = (
        performances.merge(
            pages[
                [
                    "athlete_id",
                    "result_url",
                    "resolution_status",
                    "resolved_team",
                    "resolved_team_normalized",
                    "resolved_team_mapping_key",
                    "team_alias_applied",
                    "is_unattached",
                    "fetch_status",
                    "fetch_error_message",
                    "resolution_version",
                ]
            ],
            how="left",
            left_on=[
                "athlete_id",
                "normalized_result_url",
            ],
            right_on=[
                "athlete_id",
                "result_url",
            ],
            validate="many_to_one",
            suffixes=("", "_page"),
        )
        .drop(
            columns=["result_url_page"],
            errors="ignore",
        )
    )

    performance_resolution = (
        performance_resolution.merge(
            core_exact[
                [
                    "resolved_team_mapping_key",
                    "gender_code",
                    "resolved_core_team_id",
                    "resolved_core_school_id",
                    "resolved_core_school_name",
                ]
            ],
            how="left",
            on=[
                "resolved_team_mapping_key",
                "gender_code",
            ],
            validate="many_to_one",
        )
    )

    ambiguous_core_keys = (
        core_team_map.loc[
            core_team_map[
                "core_team_match_count"
            ]
            > 1,
            [
                "resolved_team_mapping_key",
                "gender_code",
            ],
        ]
        .drop_duplicates()
    )

    if ambiguous_core_keys.empty:
        performance_resolution[
            "core_team_match_ambiguous"
        ] = False
    else:
        ambiguous_core_keys[
            "core_team_match_ambiguous"
        ] = True

        performance_resolution = (
            performance_resolution.merge(
                ambiguous_core_keys,
                how="left",
                on=[
                    "resolved_team_mapping_key",
                    "gender_code",
                ],
            )
        )
        performance_resolution[
            "core_team_match_ambiguous"
        ] = performance_resolution[
            "core_team_match_ambiguous"
        ].fillna(False)

    performance_resolution[
        "resolved_matches_original_school"
    ] = (
        performance_resolution[
            "resolved_team_mapping_key"
        ]
        == performance_resolution[
            "original_school"
        ].map(team_mapping_key)
    )

    performance_resolution[
        "resolved_matches_profile_header"
    ] = (
        performance_resolution[
            "resolved_team_mapping_key"
        ]
        == performance_resolution[
            "profile_header_school"
        ].map(team_mapping_key)
    )

    def attribution_status(
        row: pd.Series,
    ) -> str:
        if clean(
            row.get("normalized_result_url")
        ) == "":
            return "MISSING_RESULT_URL"

        if clean(
            row.get("resolution_status")
        ) != "EXACT_ATHLETE_ROW_TEAM":
            return "RESULT_PAGE_UNRESOLVED"

        if bool(
            row.get(
                "is_unattached",
                False,
            )
        ):
            return "RESOLVED_UNATTACHED"

        if bool(
            row.get(
                "core_team_match_ambiguous",
                False,
            )
        ):
            return "CORE_TEAM_MATCH_AMBIGUOUS"

        if clean(
            row.get(
                "resolved_core_team_id"
            )
        ):
            if bool(
                row.get(
                    "resolved_matches_original_school",
                    False,
                )
            ):
                return "RESOLVED_CORE_TEAM_MATCHES_ORIGINAL"

            return "RESOLVED_CORE_TEAM_CORRECTION"

        return "RESOLVED_NON_CORE_TEAM"

    performance_resolution[
        "final_resolution_status"
    ] = performance_resolution.apply(
        attribution_status,
        axis=1,
    )

    page_summary = (
        performance_resolution.groupby(
            [
                "athlete_id",
                "athlete_name",
                "profile_header_school",
                "resolved_team",
                "resolved_core_school_name",
                "final_resolution_status",
            ],
            dropna=False,
        )
        .agg(
            performance_count=(
                "performance_id",
                "nunique",
            ),
            result_page_count=(
                "normalized_result_url",
                "nunique",
            ),
            meet_count=(
                "meet_id",
                "nunique",
            ),
            earliest_season=(
                "season_year",
                "min",
            ),
            latest_season=(
                "season_year",
                "max",
            ),
        )
        .reset_index()
        .sort_values(
            [
                "athlete_id",
                "earliest_season",
                "resolved_team",
            ]
        )
    )

    season_summary = (
        performance_resolution.groupby(
            [
                "athlete_id",
                "athlete_name",
                "season_year",
                "season_type",
                "resolved_team",
                "resolved_core_team_id",
                "resolved_core_school_name",
                "final_resolution_status",
            ],
            dropna=False,
        )
        .agg(
            performance_count=(
                "performance_id",
                "nunique",
            ),
            result_page_count=(
                "normalized_result_url",
                "nunique",
            ),
            meet_count=(
                "meet_id",
                "nunique",
            ),
        )
        .reset_index()
        .sort_values(
            [
                "athlete_id",
                "season_year",
                "season_type",
                "resolved_team",
            ]
        )
    )

    unresolved_pages = pages.loc[
        pages["resolution_status"]
        != "EXACT_ATHLETE_ROW_TEAM"
    ].copy()

    alias_review = (
        performance_resolution.loc[
            (
                performance_resolution[
                    "resolution_status"
                ]
                == "EXACT_ATHLETE_ROW_TEAM"
            )
            & ~performance_resolution[
                "is_unattached"
            ].fillna(False)
            & performance_resolution[
                "resolved_core_team_id"
            ].isna()
            & performance_resolution[
                "resolved_team"
            ].fillna("").ne(""),
            [
                "resolved_team",
                "resolved_team_normalized",
                "resolved_team_mapping_key",
                "team_alias_applied",
                "gender_code",
                "profile_header_school",
                "athlete_id",
                "athlete_name",
                "season_year",
                "original_school",
            ],
        ]
        .drop_duplicates()
        .sort_values(
            [
                "resolved_team",
                "gender_code",
                "athlete_id",
                "season_year",
            ]
        )
    )

    pages.to_csv(
        OUTPUT_DIR
        / "result_page_team_resolution.csv",
        index=False,
    )
    performance_resolution.to_csv(
        OUTPUT_DIR
        / "performance_team_resolution.csv",
        index=False,
    )
    season_summary.to_csv(
        OUTPUT_DIR
        / "athlete_team_season_summary.csv",
        index=False,
    )
    page_summary.to_csv(
        OUTPUT_DIR
        / "team_resolution_summary.csv",
        index=False,
    )
    unresolved_pages.to_csv(
        OUTPUT_DIR
        / "unresolved_result_page_queue.csv",
        index=False,
    )
    alias_review.to_csv(
        OUTPUT_DIR
        / "core_team_alias_review_queue.csv",
        index=False,
    )
    fetch_status.to_csv(
        OUTPUT_DIR / "fetch_status.csv",
        index=False,
    )

    performance_count = len(
        performance_resolution
    )
    source_performance_count = len(
        performances
    )

    duplicate_performance_ids = int(
        performance_resolution.duplicated(
            ["performance_id"]
        ).sum()
    )
    missing_result_urls = int(
        missing_url_mask.sum()
    )
    fetch_errors = int(
        (~fetch_status["fetch_status"].isin(
            [
                "FETCHED",
                "CACHE_HIT",
                "PROTOTYPE_CACHE_HIT",
            ]
        )).sum()
    )
    unresolved_page_count = len(
        unresolved_pages
    )
    performance_without_page_resolution = int(
        (
            ~missing_url_mask
            & performance_resolution[
                "resolution_status"
            ].fillna("").eq("")
        ).sum()
    )
    ambiguous_core_matches = int(
        performance_resolution[
            "core_team_match_ambiguous"
        ].sum()
    )
    unattached_performances = int(
        performance_resolution[
            "is_unattached"
        ].fillna(False).sum()
    )
    alias_applied_performances = int(
        performance_resolution[
            "team_alias_applied"
        ].fillna(False).sum()
    )
    affiliation_gender_fallbacks = int(
        (
            performance_resolution[
                "original_gender_code"
            ].fillna("").eq("")
            & performance_resolution[
                "gender_code"
            ].fillna("").ne("")
        ).sum()
    )

    fixture_check_rows: list[
        dict[str, Any]
    ] = []

    for athlete_id, expected_teams in (
        FIXTURE_EXPECTATIONS.items()
    ):
        observed = {
            clean(value)
            for value in performance_resolution.loc[
                performance_resolution[
                    "athlete_id"
                ]
                == athlete_id,
                "resolved_team",
            ].tolist()
            if clean(value)
        }

        missing_expected = sorted(
            expected_teams - observed
        )

        fixture_check_rows.append(
            {
                "check_name": (
                    f"fixture_{athlete_id}_"
                    "expected_teams_observed"
                ),
                "failed_row_count": len(
                    missing_expected
                ),
                "observed_value": (
                    " | ".join(
                        sorted(observed)
                    )
                ),
                "expected_value": (
                    " | ".join(
                        sorted(expected_teams)
                    )
                ),
            }
        )

    checks = pd.DataFrame(
        [
            {
                "check_name": (
                    "input_athlete_count"
                ),
                "failed_row_count": (
                    0
                    if len(athlete_ids) == 27
                    else abs(
                        len(athlete_ids) - 27
                    )
                ),
                "observed_value": len(
                    athlete_ids
                ),
                "expected_value": 27,
            },
            {
                "check_name": (
                    "performance_row_count_reconciles"
                ),
                "failed_row_count": (
                    0
                    if performance_count
                    == source_performance_count
                    else abs(
                        performance_count
                        - source_performance_count
                    )
                ),
                "observed_value": (
                    performance_count
                ),
                "expected_value": (
                    source_performance_count
                ),
            },
            {
                "check_name": (
                    "duplicate_performance_ids"
                ),
                "failed_row_count": (
                    duplicate_performance_ids
                ),
                "observed_value": (
                    duplicate_performance_ids
                ),
                "expected_value": 0,
            },
            {
                "check_name": (
                    "missing_result_URLs"
                ),
                "failed_row_count": (
                    missing_result_urls
                ),
                "observed_value": (
                    missing_result_urls
                ),
                "expected_value": 0,
            },
            {
                "check_name": (
                    "page_fetch_errors"
                ),
                "failed_row_count": (
                    fetch_errors
                ),
                "observed_value": (
                    fetch_errors
                ),
                "expected_value": 0,
            },
            {
                "check_name": (
                    "unresolved_result_pages"
                ),
                "failed_row_count": (
                    unresolved_page_count
                ),
                "observed_value": (
                    unresolved_page_count
                ),
                "expected_value": 0,
            },
            {
                "check_name": (
                    "performances_without_page_resolution"
                ),
                "failed_row_count": (
                    performance_without_page_resolution
                ),
                "observed_value": (
                    performance_without_page_resolution
                ),
                "expected_value": 0,
            },
            {
                "check_name": (
                    "ambiguous_core_team_matches"
                ),
                "failed_row_count": (
                    ambiguous_core_matches
                ),
                "observed_value": (
                    ambiguous_core_matches
                ),
                "expected_value": 0,
            },
            *fixture_check_rows,
        ]
    )

    checks.to_csv(
        OUTPUT_DIR / "hard_checks.csv",
        index=False,
    )

    failed_checks = int(
        (
            checks["failed_row_count"]
            > 0
        ).sum()
    )

    status_counts = (
        performance_resolution[
            "final_resolution_status"
        ]
        .value_counts(dropna=False)
        .to_dict()
    )

    report_lines = [
        (
            "MILESTONE 4 BLOCKING-PROFILE "
            "RESULT RESOLUTION"
        ),
        "=" * 60,
        (
            f"Resolution version: "
            f"{RESOLUTION_VERSION}"
        ),
        "Source database modified: no",
        "Staging database modified: no",
        "Raw HTML modified: no",
        "",
        "SCOPE",
        (
            f"- Blocking athletes: "
            f"{len(athlete_ids):,}"
        ),
        (
            f"- Source performances: "
            f"{source_performance_count:,}"
        ),
        (
            f"- Distinct athlete/result pages: "
            f"{total_pages:,}"
        ),
        "",
        "PAGE RESOLUTION",
        (
            f"- Fetch errors: "
            f"{fetch_errors:,}"
        ),
        (
            f"- Unresolved result pages: "
            f"{unresolved_page_count:,}"
        ),
        (
            f"- Performances missing result URL: "
            f"{missing_result_urls:,}"
        ),
        (
            f"- Unattached performances resolved: "
            f"{unattached_performances:,}"
        ),
        (
            f"- Alias-normalized performances: "
            f"{alias_applied_performances:,}"
        ),
        (
            f"- Affiliation-gender fallbacks: "
            f"{affiliation_gender_fallbacks:,}"
        ),
        "",
        "PERFORMANCE RESOLUTION",
    ]

    for status, count in sorted(
        status_counts.items(),
        key=lambda item: str(item[0]),
    ):
        report_lines.append(
            f"- {status}: {int(count):,}"
        )

    report_lines.extend(
        [
            "",
            "VALIDATION",
            (
                f"- Hard checks: "
                f"{len(checks):,}"
            ),
            (
                f"- Failed hard checks: "
                f"{failed_checks:,}"
            ),
            (
                f"- Core-team alias review rows: "
                f"{len(alias_review):,}"
            ),
            "",
            "NEXT GATE",
            (
                "Review only unresolved_result_page_queue.csv "
                "and core_team_alias_review_queue.csv. "
                "No attribution override should be applied "
                "until the hard checks and required alias "
                "classifications are resolved."
            ),
        ]
    )

    (
        OUTPUT_DIR / "resolution_report.txt"
    ).write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )

    print(
        "Blocking-profile result resolution complete."
    )
    print(f"Outputs: {OUTPUT_DIR}")
    print(
        f"Athletes: {len(athlete_ids):,}; "
        f"performances: "
        f"{source_performance_count:,}; "
        f"pages: {total_pages:,}; "
        f"failed checks: {failed_checks:,}."
    )


if __name__ == "__main__":
    main()
