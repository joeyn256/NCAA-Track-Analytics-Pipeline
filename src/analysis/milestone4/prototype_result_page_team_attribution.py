#!/usr/bin/env python3
"""
Milestone 4 prototype: result-page team attribution.

Purpose
-------
Validate that a TFRRS result page can recover the athlete's team at the
specific meet, even when the athlete profile's current header school differs
from the historical performance team.

Fixtures
--------
- Seth Gipson (6134984): current profile header UNLV, historical result team
  expected to include Jackson State.
- Ryan Riddle (6907335): current profile header Missouri Southern, result team
  expected to include Missouri Southern.
- Milana Straub (8716406): current profile header Marywood, result team
  expected to include Marywood.

This script:
- reads the Milestone 3 database in read-only mode;
- samples up to 12 result URLs per fixture;
- caches fetched pages under processed Milestone 4 outputs;
- never modifies raw HTML or either DuckDB database.

Outputs
-------
data/processed/milestone4/result_team_resolution_prototype/
    result_page_team_resolution.csv
    athlete_team_summary.csv
    fetch_status.csv
    hard_checks.csv
    prototype_report.txt
    page_cache/
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
OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/result_team_resolution_prototype"
)
CACHE_DIR = OUTPUT_DIR / "page_cache"

BASE_URL = "https://www.tfrrs.org/"
PROTOTYPE_VERSION = "m4_result_team_prototype_v1.0"

FIXTURES = {
    6134984: {
        "athlete_name": "Gipson, Seth",
        "profile_header_school": "UNLV",
        "expected_result_school": "Jackson State",
    },
    6907335: {
        "athlete_name": "Riddle, Ryan",
        "profile_header_school": "Missouri Southern",
        "expected_result_school": "Missouri Southern",
    },
    8716406: {
        "athlete_name": "Straub, Milana",
        "profile_header_school": "Marywood",
        "expected_result_school": "Marywood",
    },
}

NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
ATHLETE_HREF_TEMPLATE = r"/athletes/{athlete_id}(?:/|$)"
TEAM_HREF_RE = re.compile(
    r"/teams?(?:/|$)|/team/",
    re.IGNORECASE,
)


def clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split()).strip()


def normalize_name(value: object) -> str:
    return NON_ALNUM_RE.sub("", clean(value).lower())


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


def cache_path(url: str) -> Path:
    digest = hashlib.sha256(
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
    path = cache_path(url)

    if path.exists():
        html = path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
        return (
            html,
            {
                "fetch_status": "CACHE_HIT",
                "http_status": 200,
                "cache_file": str(path),
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

    path.write_text(
        response.text,
        encoding="utf-8",
    )

    time.sleep(delay_seconds)

    return (
        response.text,
        {
            "fetch_status": "FETCHED",
            "http_status": status,
            "cache_file": str(path),
            "error_message": "",
        },
    )


def athlete_name_variants(value: str) -> set[str]:
    raw = clean(value)
    variants = {normalize_name(raw)}

    if "," in raw:
        last, first = raw.split(",", 1)
        variants.add(
            normalize_name(
                f"{clean(first)} {clean(last)}"
            )
        )

    return {item for item in variants if item}


def team_anchor_candidates(row: Tag) -> list[Tag]:
    candidates: list[Tag] = []

    for anchor in row.find_all("a", href=True):
        href = clean(anchor.get("href"))
        text = clean(anchor.get_text(" ", strip=True))

        if (
            text
            and TEAM_HREF_RE.search(
                urlsplit(
                    normalize_url(href)
                ).path
            )
        ):
            candidates.append(anchor)

    return candidates


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
        ATHLETE_HREF_TEMPLATE.format(
            athlete_id=athlete_id
        ),
        re.IGNORECASE,
    )
    variants = athlete_name_variants(
        athlete_name
    )

    athlete_anchors: list[Tag] = []

    for anchor in soup.find_all("a", href=True):
        href = urlsplit(
            normalize_url(anchor.get("href"))
        ).path
        text = normalize_name(
            anchor.get_text(" ", strip=True)
        )

        if athlete_href_re.search(href):
            athlete_anchors.append(anchor)
        elif text in variants and "/athletes/" in href:
            athlete_anchors.append(anchor)

    observations: list[dict[str, str]] = []

    for athlete_anchor in athlete_anchors:
        row = athlete_anchor.find_parent("tr")

        if row is None:
            # Some result layouts use nested divs instead of table rows.
            parent = athlete_anchor.parent

            for _ in range(5):
                if not isinstance(parent, Tag):
                    break

                team_candidates = team_anchor_candidates(
                    parent
                )

                if team_candidates:
                    row = parent
                    break

                parent = parent.parent

        if not isinstance(row, Tag):
            continue

        team_candidates = team_anchor_candidates(
            row
        )

        # Remove the athlete link itself if its URL happens to match a
        # broad team-link pattern in an unusual layout.
        filtered: list[Tag] = []

        for team_anchor in team_candidates:
            if team_anchor is athlete_anchor:
                continue

            text = clean(
                team_anchor.get_text(
                    " ",
                    strip=True,
                )
            )

            if text:
                filtered.append(team_anchor)

        unique_teams = list(
            dict.fromkeys(
                clean(
                    anchor.get_text(
                        " ",
                        strip=True,
                    )
                )
                for anchor in filtered
            )
        )

        for team in unique_teams:
            observations.append(
                {
                    "resolved_team": team,
                    "athlete_link_text": clean(
                        athlete_anchor.get_text(
                            " ",
                            strip=True,
                        )
                    ),
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
        status = "EXACT_ATHLETE_ROW_TEAM"
        resolved_team = teams[0]
    elif len(teams) > 1:
        status = "CONFLICTING_TEAM_ROWS"
        resolved_team = ""
    elif athlete_anchors:
        status = "ATHLETE_FOUND_TEAM_NOT_FOUND"
        resolved_team = ""
    else:
        status = "ATHLETE_NOT_FOUND"
        resolved_team = ""

    return {
        "resolution_status": status,
        "resolved_team": resolved_team,
        "athlete_anchor_count": len(
            athlete_anchors
        ),
        "team_observation_count": len(
            observations
        ),
        "observed_teams": " | ".join(teams),
        "sample_row_text": (
            observations[0]["row_text"]
            if observations
            else ""
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--samples-per-athlete",
        type=int,
        default=12,
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.75,
        help=(
            "Delay after each newly fetched page. "
            "Default: 0.75 seconds."
        ),
    )

    return parser.parse_args()


def load_samples(
    con: duckdb.DuckDBPyConnection,
    samples_per_athlete: int,
) -> pd.DataFrame:
    athlete_ids = list(FIXTURES)
    placeholders = ", ".join(
        "?" for _ in athlete_ids
    )

    frame = con.execute(
        f"""
        WITH source_rows AS (
            SELECT
                p.performance_id,
                p.athlete_id,
                a.athlete_name,
                p.result_url,
                p.event,
                p.mark,
                p.meet_name,
                p.meet_date_text,
                p.season_year,
                p.team_id AS original_team_id,
                s.school_name AS original_school,
                ROW_NUMBER() OVER (
                    PARTITION BY p.athlete_id
                    ORDER BY
                        p.season_year DESC,
                        p.performance_id DESC
                ) AS newest_rank,
                ROW_NUMBER() OVER (
                    PARTITION BY p.athlete_id
                    ORDER BY
                        p.season_year ASC,
                        p.performance_id ASC
                ) AS oldest_rank
            FROM core.performances p
            JOIN core.athletes a
              ON p.athlete_id = a.athlete_id
            LEFT JOIN core.teams t
              ON p.team_id = t.team_id
            LEFT JOIN core.schools s
              ON t.school_id = s.school_id
            WHERE p.athlete_id IN ({placeholders})
              AND p.result_url IS NOT NULL
              AND trim(p.result_url) <> ''
        )
        SELECT *
        FROM source_rows
        WHERE newest_rank <= ?
           OR oldest_rank <= ?
        ORDER BY
            athlete_id,
            season_year,
            performance_id
        """,
        [
            *athlete_ids,
            samples_per_athlete // 2,
            samples_per_athlete // 2,
        ],
    ).fetchdf()

    frame["athlete_id"] = pd.to_numeric(
        frame["athlete_id"],
        errors="raise",
    ).astype("int64")

    frame["normalized_result_url"] = (
        frame["result_url"].map(normalize_url)
    )

    # One fetch per athlete/result URL. Multiple performance rows can
    # legitimately share the same result page.
    frame = frame.drop_duplicates(
        ["athlete_id", "normalized_result_url"]
    ).copy()

    return frame


def main() -> None:
    args = parse_args()

    if args.samples_per_athlete < 2:
        raise ValueError(
            "--samples-per-athlete must be at least 2."
        )
    if args.delay < 0:
        raise ValueError(
            "--delay cannot be negative."
        )
    if not SOURCE_DB.exists():
        raise FileNotFoundError(
            f"Source database not found: {SOURCE_DB}"
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    con = duckdb.connect(
        str(SOURCE_DB),
        read_only=True,
    )

    try:
        samples = load_samples(
            con=con,
            samples_per_athlete=(
                args.samples_per_athlete
            ),
        )
    finally:
        con.close()

    session = build_session()
    result_rows: list[dict[str, Any]] = []
    fetch_rows: list[dict[str, Any]] = []

    total = len(samples)

    for index, source in enumerate(
        samples.to_dict("records"),
        start=1,
    ):
        athlete_id = int(source["athlete_id"])
        athlete_name = clean(
            source["athlete_name"]
        )
        url = clean(
            source["normalized_result_url"]
        )

        try:
            html, fetch = fetch_page(
                session=session,
                url=url,
                delay_seconds=args.delay,
            )

            fetch_rows.append(
                {
                    "athlete_id": athlete_id,
                    "athlete_name": athlete_name,
                    "result_url": url,
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
                    "athlete_anchor_count": 0,
                    "team_observation_count": 0,
                    "observed_teams": "",
                    "sample_row_text": "",
                }

            fixture = FIXTURES[athlete_id]

            result_rows.append(
                {
                    "athlete_id": athlete_id,
                    "athlete_name": athlete_name,
                    "profile_header_school": (
                        fixture[
                            "profile_header_school"
                        ]
                    ),
                    "expected_result_school": (
                        fixture[
                            "expected_result_school"
                        ]
                    ),
                    "performance_id": source[
                        "performance_id"
                    ],
                    "season_year": source[
                        "season_year"
                    ],
                    "meet_name": source[
                        "meet_name"
                    ],
                    "meet_date_text": source[
                        "meet_date_text"
                    ],
                    "event": source["event"],
                    "mark": source["mark"],
                    "original_team_id": source[
                        "original_team_id"
                    ],
                    "original_school": source[
                        "original_school"
                    ],
                    "result_url": url,
                    "fetch_status": fetch[
                        "fetch_status"
                    ],
                    **resolution,
                }
            )

        except Exception as exc:
            fetch_rows.append(
                {
                    "athlete_id": athlete_id,
                    "athlete_name": athlete_name,
                    "result_url": url,
                    "fetch_status": "ERROR",
                    "http_status": None,
                    "cache_file": "",
                    "error_message": (
                        f"{type(exc).__name__}: "
                        f"{clean(exc)}"
                    ),
                }
            )
            result_rows.append(
                {
                    "athlete_id": athlete_id,
                    "athlete_name": athlete_name,
                    "profile_header_school": (
                        FIXTURES[athlete_id][
                            "profile_header_school"
                        ]
                    ),
                    "expected_result_school": (
                        FIXTURES[athlete_id][
                            "expected_result_school"
                        ]
                    ),
                    "performance_id": source[
                        "performance_id"
                    ],
                    "season_year": source[
                        "season_year"
                    ],
                    "meet_name": source[
                        "meet_name"
                    ],
                    "meet_date_text": source[
                        "meet_date_text"
                    ],
                    "event": source["event"],
                    "mark": source["mark"],
                    "original_team_id": source[
                        "original_team_id"
                    ],
                    "original_school": source[
                        "original_school"
                    ],
                    "result_url": url,
                    "fetch_status": "ERROR",
                    "resolution_status": "ERROR",
                    "resolved_team": "",
                    "athlete_anchor_count": 0,
                    "team_observation_count": 0,
                    "observed_teams": "",
                    "sample_row_text": "",
                }
            )

        print(
            f"Resolved pages: {index:,}/{total:,}"
        )

    results = pd.DataFrame(result_rows)
    fetch_status = pd.DataFrame(fetch_rows)

    results["resolved_matches_expected"] = (
        results["resolved_team"].map(
            normalize_name
        )
        == results[
            "expected_result_school"
        ].map(normalize_name)
    )
    results["resolved_matches_original"] = (
        results["resolved_team"].map(
            normalize_name
        )
        == results["original_school"].map(
            normalize_name
        )
    )
    results["resolved_matches_header"] = (
        results["resolved_team"].map(
            normalize_name
        )
        == results[
            "profile_header_school"
        ].map(normalize_name)
    )

    summary = (
        results.groupby(
            [
                "athlete_id",
                "athlete_name",
                "profile_header_school",
                "expected_result_school",
                "resolved_team",
                "resolution_status",
            ],
            dropna=False,
        )
        .agg(
            page_count=("result_url", "nunique"),
            earliest_season=("season_year", "min"),
            latest_season=("season_year", "max"),
            expected_match_count=(
                "resolved_matches_expected",
                "sum",
            ),
            original_match_count=(
                "resolved_matches_original",
                "sum",
            ),
            header_match_count=(
                "resolved_matches_header",
                "sum",
            ),
        )
        .reset_index()
        .sort_values(
            [
                "athlete_id",
                "page_count",
            ],
            ascending=[True, False],
        )
    )

    results.to_csv(
        OUTPUT_DIR
        / "result_page_team_resolution.csv",
        index=False,
    )
    summary.to_csv(
        OUTPUT_DIR / "athlete_team_summary.csv",
        index=False,
    )
    fetch_status.to_csv(
        OUTPUT_DIR / "fetch_status.csv",
        index=False,
    )

    page_errors = int(
        (~fetch_status["fetch_status"].isin(
            ["FETCHED", "CACHE_HIT"]
        )).sum()
    )
    conflicts = int(
        (
            results["resolution_status"]
            == "CONFLICTING_TEAM_ROWS"
        ).sum()
    )
    unresolved_pages = int(
        (
            results["resolution_status"]
            != "EXACT_ATHLETE_ROW_TEAM"
        ).sum()
    )

    fixture_failures = 0
    fixture_check_rows: list[dict[str, Any]] = []

    for athlete_id, fixture in FIXTURES.items():
        athlete_rows = results[
            results["athlete_id"] == athlete_id
        ]
        expected_normalized = normalize_name(
            fixture["expected_result_school"]
        )
        expected_count = int(
            (
                athlete_rows["resolved_team"].map(
                    normalize_name
                )
                == expected_normalized
            ).sum()
        )

        failed = 0 if expected_count > 0 else 1
        fixture_failures += failed

        fixture_check_rows.append(
            {
                "check_name": (
                    f"fixture_{athlete_id}_"
                    "expected_team_observed"
                ),
                "failed_row_count": failed,
                "observed_value": expected_count,
                "expected_value": "> 0",
            }
        )

    checks = pd.DataFrame(
        [
            {
                "check_name": "page_fetch_errors",
                "failed_row_count": page_errors,
                "observed_value": page_errors,
                "expected_value": 0,
            },
            {
                "check_name": (
                    "conflicting_team_rows"
                ),
                "failed_row_count": conflicts,
                "observed_value": conflicts,
                "expected_value": 0,
            },
            {
                "check_name": (
                    "unresolved_result_pages"
                ),
                "failed_row_count": unresolved_pages,
                "observed_value": unresolved_pages,
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
        (checks["failed_row_count"] > 0).sum()
    )

    report = f"""MILESTONE 4 RESULT-PAGE TEAM PROTOTYPE
============================================================
Prototype version: {PROTOTYPE_VERSION}
Source database modified: no
Raw athlete HTML modified: no

SCOPE
- Fixture athletes: {len(FIXTURES):,}
- Sampled result pages: {len(results):,}
- Cache directory: {CACHE_DIR}

VALIDATION
- Page fetch errors: {page_errors:,}
- Conflicting result-page team rows: {conflicts:,}
- Unresolved result pages: {unresolved_pages:,}
- Fixture failures: {fixture_failures:,}
- Failed checks: {failed_checks:,}

INTERPRETATION
A passing prototype demonstrates that profile-header school and
performance-level team must be modeled separately. The result page is used
only as selective attribution evidence and does not replace the immutable
Milestone 3 source data.
"""

    (
        OUTPUT_DIR / "prototype_report.txt"
    ).write_text(
        report,
        encoding="utf-8",
    )

    print("Result-page team prototype complete.")
    print(f"Outputs: {OUTPUT_DIR}")
    print(f"Failed checks: {failed_checks:,}")


if __name__ == "__main__":
    main()
