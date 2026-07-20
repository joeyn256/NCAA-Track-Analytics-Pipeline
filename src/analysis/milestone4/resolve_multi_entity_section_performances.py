#!/usr/bin/env python3
"""
Milestone 4: resolve genuine multi-entity sections at performance level.

Purpose
-------
Fetch and parse every unique result page represented by the nine genuine
multi-entity profile sections identified by the normalized section-evidence
audit.

Each performance receives its own result-page team entity. This prevents a
single profile section from being assigned wholesale to one school when the
section contains multiple career stages.

The script:
- reads only prior Milestone 4 outputs;
- reuses cached result pages from the full unresolved-section evidence run;
- fetches only pages not already cached;
- does not modify the Milestone 3 database;
- does not apply final attribution.

Outputs
-------
data/processed/milestone4/multi_entity_performance_resolution/
    resolution_report.txt
    hard_checks.csv
    target_sections.csv
    target_performances.csv
    parsed_performance_result_teams.csv
    performance_resolution_candidates.csv
    section_resolution_summary.csv
    unresolved_performance_queue.csv
    section_team_transition_summary.csv
    page_cache/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import duckdb
import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_ROOT = Path(__file__).resolve().parents[3]

COVERAGE_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "multi_section_attribution_coverage/"
    / "multi_section_attribution_coverage.duckdb"
)

TARGET_SECTION_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "normalized_unresolved_section_evidence/"
    / "genuine_multi_entity_section_queue.csv"
)

FULL_EVIDENCE_CACHE = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "all_unresolved_section_result_page_evidence/"
    / "page_cache"
)

PROTOTYPE_CACHE = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "unresolved_section_result_page_prototype/"
    / "page_cache"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "multi_entity_performance_resolution"
)

CACHE_DIR = OUTPUT_DIR / "page_cache"

RESOLUTION_VERSION = (
    "m4_multi_entity_performance_resolution_v1.0"
)

EXPECTED_SECTION_ROWS = 9
EXPECTED_PERFORMANCE_ROWS = 120


def clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split()).strip()


def normalize_name(value: object) -> str:
    text = clean(value)

    if not text:
        return ""

    text = unicodedata.normalize(
        "NFKD",
        text,
    )
    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )
    text = text.casefold()
    text = text.replace("&", " and ")
    return re.sub(
        r"[^a-z0-9]+",
        "",
        text,
    )


def normalize_person_name(
    value: object,
) -> str:
    text = clean(value)

    if not text:
        return ""

    if "," in text:
        parts = [
            clean(part)
            for part in text.split(",", 1)
        ]
        text = " ".join(
            reversed(parts)
        )

    return normalize_name(text)


def split_person_name(
    value: object,
) -> tuple[str, str]:
    text = clean(value)

    if not text:
        return "", ""

    if "," in text:
        last_name, first_name = [
            clean(part)
            for part in text.split(",", 1)
        ]
    else:
        parts = text.split()

        if len(parts) == 1:
            return (
                normalize_name(parts[0]),
                "",
            )

        first_name = parts[0]
        last_name = parts[-1]

    return (
        normalize_name(first_name),
        normalize_name(last_name),
    )


def normalize_mark_token(
    value: object,
) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "",
        clean(value).casefold(),
    )


def similarity(
    left: str,
    right: str,
) -> float:
    if not left or not right:
        return 0.0

    return SequenceMatcher(
        None,
        left,
        right,
    ).ratio()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.40,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=4,
    )
    parser.add_argument(
        "--replace-output",
        action="store_true",
    )

    return parser.parse_args()


def require_inputs() -> None:
    for path in [
        COVERAGE_DB,
        TARGET_SECTION_CSV,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )


def load_target_sections() -> pd.DataFrame:
    frame = pd.read_csv(
        TARGET_SECTION_CSV,
        dtype=str,
        keep_default_na=False,
    )

    frame["athlete_id"] = pd.to_numeric(
        frame["athlete_id"],
        errors="coerce",
    ).astype("Int64")
    frame["section_index"] = pd.to_numeric(
        frame["section_index"],
        errors="coerce",
    ).astype("Int64")

    frame[
        "observed_performance_count"
    ] = (
        pd.to_numeric(
            frame[
                "observed_performance_count"
            ],
            errors="coerce",
        )
        .fillna(0)
        .astype("int64")
    )

    frame["resolution_version"] = (
        RESOLUTION_VERSION
    )

    return frame


def load_target_performances(
    sections: pd.DataFrame,
) -> pd.DataFrame:
    con = duckdb.connect(
        str(COVERAGE_DB),
        read_only=True,
    )

    try:
        con.register(
            "target_sections_df",
            sections[
                [
                    "athlete_id",
                    "section_index",
                    "athlete_name",
                    "source_section_name",
                    "observed_performance_count",
                    "consistent_source_team_id",
                    "result_team_names",
                    "result_entity_components",
                ]
            ],
        )

        frame = con.execute(
            """
            SELECT
                s.athlete_id,
                s.section_index,
                s.athlete_name,
                s.source_section_name,
                s.observed_performance_count
                    AS section_performance_count,
                s.consistent_source_team_id,
                s.result_team_names
                    AS sampled_result_team_names,
                s.result_entity_components,
                c.performance_id,
                c.season_year,
                c.season_type,
                c.meet_id,
                c.meet_name,
                c.event,
                c.mark,
                c.result_url,
                c.original_team_id,
                c.original_school_id,
                c.original_school_name,
                c.gender_code
            FROM target_sections_df s
            JOIN multi_section_performance_coverage c
              ON s.athlete_id = c.athlete_id
             AND s.section_index
               = c.matched_section_index
            ORDER BY
                s.athlete_id,
                s.section_index,
                TRY_CAST(
                    c.season_year AS INTEGER
                ),
                c.result_url,
                c.performance_id
            """
        ).fetchdf()

    finally:
        con.close()

    frame["resolution_version"] = (
        RESOLUTION_VERSION
    )

    return frame


def cache_path(
    url: str,
    directory: Path,
) -> Path:
    digest = hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()

    return directory / f"{digest}.html"


def fetch_page(
    session: requests.Session,
    url: str,
    timeout_seconds: float,
    sleep_seconds: float,
) -> tuple[str, str, str]:
    local_path = cache_path(
        url,
        CACHE_DIR,
    )

    if local_path.exists():
        return (
            local_path.read_text(
                encoding="utf-8",
                errors="replace",
            ),
            "CACHE_HIT",
            "",
        )

    for source_dir, status in [
        (
            FULL_EVIDENCE_CACHE,
            "FULL_EVIDENCE_CACHE_HIT",
        ),
        (
            PROTOTYPE_CACHE,
            "PROTOTYPE_CACHE_HIT",
        ),
    ]:
        source_path = cache_path(
            url,
            source_dir,
        )

        if source_path.exists():
            html = source_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
            local_path.write_text(
                html,
                encoding="utf-8",
            )
            return html, status, ""

    try:
        response = session.get(
            url,
            timeout=timeout_seconds,
        )
        response.raise_for_status()

        html = response.text
        local_path.write_text(
            html,
            encoding="utf-8",
        )
        time.sleep(sleep_seconds)

        return html, "FETCHED", ""

    except Exception as exc:
        return "", "FETCH_ERROR", repr(exc)


def unique_rows(
    rows: list[Tag],
) -> list[Tag]:
    output: list[Tag] = []
    seen: set[int] = set()

    for row in rows:
        identity = id(row)

        if identity in seen:
            continue

        seen.add(identity)
        output.append(row)

    return output


def is_athlete_link(
    href: object,
) -> bool:
    return (
        "/athletes/"
        in clean(href).casefold()
    )


def is_team_link(
    href: object,
) -> bool:
    normalized = clean(
        href
    ).casefold()

    return (
        "/teams/" in normalized
        or "/team/" in normalized
    )


def find_athlete_rows(
    soup: BeautifulSoup,
    athlete_id: int,
    athlete_name: str,
    performance_mark: str,
) -> tuple[list[Tag], str]:
    athlete_id_pattern = re.compile(
        rf"/athletes/{athlete_id}(?:/|$)",
        flags=re.IGNORECASE,
    )

    id_rows: list[Tag] = []

    for link in soup.find_all(
        "a",
        href=True,
    ):
        href = clean(
            link.get("href")
        )

        if not athlete_id_pattern.search(
            href
        ):
            continue

        row = link.find_parent("tr")

        if row is not None:
            id_rows.append(row)

    id_rows = unique_rows(id_rows)

    if id_rows:
        return (
            id_rows,
            "ATHLETE_ID_LINK_ROWS",
        )

    normalized_target = (
        normalize_person_name(
            athlete_name
        )
    )

    exact_rows: list[Tag] = []
    athlete_links: list[Tag] = []

    for link in soup.find_all(
        "a",
        href=True,
    ):
        if not is_athlete_link(
            link.get("href")
        ):
            continue

        athlete_links.append(link)

        link_name = (
            normalize_person_name(
                link.get_text(
                    " ",
                    strip=True,
                )
            )
        )

        if link_name != normalized_target:
            continue

        row = link.find_parent("tr")

        if row is not None:
            exact_rows.append(row)

    exact_rows = unique_rows(
        exact_rows
    )

    if exact_rows:
        return (
            exact_rows,
            "EXACT_ATHLETE_NAME_LINK_ROWS",
        )

    target_first, target_last = (
        split_person_name(
            athlete_name
        )
    )
    target_mark = normalize_mark_token(
        performance_mark
    )

    candidates: list[
        tuple[
            float,
            str,
            Tag,
        ]
    ] = []

    for link in athlete_links:
        candidate_name = clean(
            link.get_text(
                " ",
                strip=True,
            )
        )
        candidate_first, candidate_last = (
            split_person_name(
                candidate_name
            )
        )

        row = link.find_parent("tr")

        if row is None:
            continue

        row_token = normalize_mark_token(
            row.get_text(
                " ",
                strip=True,
            )
        )

        mark_matches = (
            bool(target_mark)
            and target_mark in row_token
        )

        first_score = similarity(
            target_first,
            candidate_first,
        )
        last_score = similarity(
            target_last,
            candidate_last,
        )

        plausible_name = (
            last_score >= 0.80
            and first_score >= 0.40
        )

        if not (
            mark_matches
            and plausible_name
        ):
            continue

        candidates.append(
            (
                (
                    0.60 * last_score
                    + 0.40 * first_score
                ),
                normalize_person_name(
                    candidate_name
                ),
                row,
            )
        )

    if not candidates:
        return [], "ATHLETE_ROW_NOT_FOUND"

    best_score = max(
        item[0]
        for item in candidates
    )

    best = [
        item
        for item in candidates
        if abs(
            item[0] - best_score
        ) < 1e-9
    ]

    if len(
        {
            item[1]
            for item in best
        }
    ) != 1:
        return (
            [],
            "AMBIGUOUS_FUZZY_NAME_MARK_ROWS",
        )

    return (
        unique_rows(
            [
                item[2]
                for item in best
            ]
        ),
        "FUZZY_NAME_AND_EXACT_MARK_ROWS",
    )


def extract_team_from_rows(
    rows: list[Tag],
    result_url: str,
) -> tuple[
    str,
    str,
    str,
    int,
    str,
]:
    candidates: dict[
        str,
        tuple[str, str],
    ] = {}

    row_debug: list[
        dict[str, Any]
    ] = []

    for row in rows:
        row_debug.append(
            {
                "text": clean(
                    row.get_text(
                        " ",
                        strip=True,
                    )
                ),
                "html": str(row),
            }
        )

        for link in row.find_all(
            "a",
            href=True,
        ):
            href = clean(
                link.get("href")
            )
            name = clean(
                link.get_text(
                    " ",
                    strip=True,
                )
            )

            if not name:
                continue
            if not is_team_link(href):
                continue

            url = urljoin(
                result_url,
                href,
            )
            key = normalize_name(name)

            if key:
                candidates[key] = (
                    name,
                    url,
                )

    if not candidates:
        return (
            "",
            "",
            "TEAM_LINK_NOT_FOUND",
            0,
            json.dumps(
                row_debug,
                ensure_ascii=False,
            ),
        )

    ordered = sorted(
        candidates.items(),
        key=lambda item: item[0],
    )

    if len(ordered) > 1:
        return (
            " | ".join(
                value[0]
                for _, value in ordered
            ),
            " | ".join(
                value[1]
                for _, value in ordered
            ),
            "MULTIPLE_DISTINCT_TEAM_LINKS",
            len(ordered),
            json.dumps(
                row_debug,
                ensure_ascii=False,
            ),
        )

    _, (
        team_name,
        team_url,
    ) = ordered[0]

    return (
        team_name,
        team_url,
        "TEAM_LINK_FOUND",
        1,
        json.dumps(
            row_debug,
            ensure_ascii=False,
        ),
    )


def parse_performances(
    performances: pd.DataFrame,
    args: argparse.Namespace,
) -> pd.DataFrame:
    CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    retry_policy = Retry(
        total=args.max_retries,
        connect=args.max_retries,
        read=args.max_retries,
        status=args.max_retries,
        backoff_factor=0.8,
        status_forcelist=[
            429,
            500,
            502,
            503,
            504,
        ],
        allowed_methods=frozenset(
            ["GET"]
        ),
        raise_on_status=False,
    )

    session = requests.Session()
    adapter = HTTPAdapter(
        max_retries=retry_policy,
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
                "(compatible; NCAA Track Analytics "
                "Milestone 4 research audit)"
            )
        }
    )

    unique_pages = (
        performances.sort_values(
            [
                "athlete_id",
                "section_index",
                "result_url",
                "performance_id",
            ]
        )
        .drop_duplicates(
            [
                "athlete_id",
                "section_index",
                "result_url",
                "mark",
            ],
            keep="first",
        )
        .copy()
    )

    page_results: list[
        dict[str, Any]
    ] = []

    for index, record in enumerate(
        unique_pages.itertuples(
            index=False
        ),
        start=1,
    ):
        print(
            f"[{index:,}/{len(unique_pages):,}] "
            f"{record.athlete_id} "
            f"{record.source_section_name} "
            f"{record.season_year} "
            f"{record.event}"
        )

        result_url = clean(
            record.result_url
        )

        html, fetch_status, fetch_error = (
            fetch_page(
                session=session,
                url=result_url,
                timeout_seconds=(
                    args.timeout_seconds
                ),
                sleep_seconds=(
                    args.sleep_seconds
                ),
            )
        )

        output = {
            "athlete_id": (
                record.athlete_id
            ),
            "section_index": (
                record.section_index
            ),
            "result_url": result_url,
            "mark": clean(record.mark),
            "fetch_status": fetch_status,
            "fetch_error": fetch_error,
            "row_match_method": "",
            "matched_athlete_row_count": 0,
            "team_parse_status": "",
            "parsed_team_name": "",
            "parsed_team_url": "",
            "normalized_parsed_team_name": "",
            "matched_team_link_count": 0,
            "row_debug_json": "",
            "resolution_version": (
                RESOLUTION_VERSION
            ),
        }

        if not html:
            page_results.append(output)
            continue

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        athlete_rows, method = (
            find_athlete_rows(
                soup=soup,
                athlete_id=int(
                    record.athlete_id
                ),
                athlete_name=(
                    record.athlete_name
                ),
                performance_mark=(
                    record.mark
                ),
            )
        )

        output[
            "row_match_method"
        ] = method
        output[
            "matched_athlete_row_count"
        ] = len(athlete_rows)

        if not athlete_rows:
            output[
                "team_parse_status"
            ] = "ATHLETE_ROW_UNRESOLVED"
            page_results.append(output)
            continue

        (
            team_name,
            team_url,
            parse_status,
            link_count,
            debug_json,
        ) = extract_team_from_rows(
            rows=athlete_rows,
            result_url=result_url,
        )

        output.update(
            {
                "team_parse_status": (
                    parse_status
                ),
                "parsed_team_name": (
                    team_name
                ),
                "parsed_team_url": (
                    team_url
                ),
                "normalized_parsed_team_name": (
                    normalize_name(
                        team_name
                    )
                ),
                "matched_team_link_count": (
                    link_count
                ),
                "row_debug_json": (
                    debug_json
                ),
            }
        )

        page_results.append(output)

    page_frame = pd.DataFrame(
        page_results
    )

    merged = performances.merge(
        page_frame,
        on=[
            "athlete_id",
            "section_index",
            "result_url",
            "mark",
        ],
        how="left",
        validate="many_to_one",
        suffixes=("", "_parsed"),
    )

    return merged


def build_candidates(
    parsed: pd.DataFrame,
) -> pd.DataFrame:
    frame = parsed.copy()

    frame["resolved_team_name"] = (
        frame["parsed_team_name"]
    )
    frame["resolved_team_url"] = (
        frame["parsed_team_url"]
    )
    frame["performance_resolution_status"] = (
        "RESULT_PAGE_TEAM_RESOLVED"
    )
    frame["resolution_confidence"] = (
        "HIGH"
    )
    frame["resolution_method"] = (
        "EXACT_RESULT_PAGE_ATHLETE_ROW"
    )

    unresolved_mask = (
        ~frame["team_parse_status"]
        .eq("TEAM_LINK_FOUND")
    )

    frame.loc[
        unresolved_mask,
        "resolved_team_name",
    ] = ""

    frame.loc[
        unresolved_mask,
        "resolved_team_url",
    ] = ""

    frame.loc[
        unresolved_mask,
        "performance_resolution_status",
    ] = "UNRESOLVED_RESULT_PAGE_TEAM"

    frame.loc[
        unresolved_mask,
        "resolution_confidence",
    ] = "UNRESOLVED"

    frame.loc[
        unresolved_mask,
        "resolution_method",
    ] = frame.loc[
        unresolved_mask,
        "team_parse_status",
    ]

    frame["resolution_version"] = (
        RESOLUTION_VERSION
    )

    return frame


def build_section_summary(
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    return (
        candidates.groupby(
            [
                "athlete_id",
                "section_index",
                "athlete_name",
                "source_section_name",
                "section_performance_count",
            ],
            dropna=False,
        )
        .agg(
            performance_rows=(
                "performance_id",
                "size",
            ),
            resolved_performance_rows=(
                "performance_resolution_status",
                lambda values: sum(
                    value
                    == "RESULT_PAGE_TEAM_RESOLVED"
                    for value in values
                ),
            ),
            unresolved_performance_rows=(
                "performance_resolution_status",
                lambda values: sum(
                    value
                    != "RESULT_PAGE_TEAM_RESOLVED"
                    for value in values
                ),
            ),
            distinct_resolved_team_count=(
                "normalized_parsed_team_name",
                lambda values: len(
                    {
                        clean(value)
                        for value in values
                        if clean(value)
                    }
                ),
            ),
            resolved_team_names=(
                "resolved_team_name",
                lambda values: " | ".join(
                    sorted(
                        {
                            clean(value)
                            for value in values
                            if clean(value)
                        }
                    )
                ),
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
    )


def build_transition_summary(
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    resolved = candidates.loc[
        candidates[
            "performance_resolution_status"
        ].eq(
            "RESULT_PAGE_TEAM_RESOLVED"
        )
    ].copy()

    return (
        resolved.groupby(
            [
                "athlete_id",
                "section_index",
                "athlete_name",
                "source_section_name",
                "resolved_team_name",
                "resolved_team_url",
            ],
            dropna=False,
        )
        .agg(
            performance_count=(
                "performance_id",
                "size",
            ),
            first_season_year=(
                "season_year",
                "min",
            ),
            last_season_year=(
                "season_year",
                "max",
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
                "section_index",
                "first_season_year",
                "resolved_team_name",
            ]
        )
    )


def build_checks(
    sections: pd.DataFrame,
    performances: pd.DataFrame,
    candidates: pd.DataFrame,
    summary: pd.DataFrame,
) -> pd.DataFrame:
    duplicate_performance_ids = int(
        candidates["performance_id"]
        .duplicated()
        .sum()
    )

    missing_candidate_rows = int(
        (
            candidates[
                "performance_resolution_status"
            ]
            .fillna("")
            .eq("")
        ).sum()
    )

    section_count_mismatches = int(
        (
            summary[
                "performance_rows"
            ]
            != summary[
                "section_performance_count"
            ]
        ).sum()
    )

    unresolved_rows = int(
        candidates[
            "performance_resolution_status"
        ].ne(
            "RESULT_PAGE_TEAM_RESOLVED"
        ).sum()
    )

    single_team_sections = int(
        summary[
            "distinct_resolved_team_count"
        ].lt(2).sum()
    )

    rows = [
        (
            "target_section_rows",
            abs(
                len(sections)
                - EXPECTED_SECTION_ROWS
            ),
            len(sections),
            EXPECTED_SECTION_ROWS,
        ),
        (
            "target_performance_rows",
            abs(
                len(performances)
                - EXPECTED_PERFORMANCE_ROWS
            ),
            len(performances),
            EXPECTED_PERFORMANCE_ROWS,
        ),
        (
            "candidate_performance_rows",
            abs(
                len(candidates)
                - len(performances)
            ),
            len(candidates),
            len(performances),
        ),
        (
            "duplicate_performance_ids",
            duplicate_performance_ids,
            duplicate_performance_ids,
            0,
        ),
        (
            "missing_candidate_status_rows",
            missing_candidate_rows,
            missing_candidate_rows,
            0,
        ),
        (
            "section_performance_count_mismatches",
            section_count_mismatches,
            section_count_mismatches,
            0,
        ),
        (
            "unresolved_performance_rows",
            unresolved_rows,
            unresolved_rows,
            0,
        ),
        (
            "sections_with_fewer_than_two_resolved_teams",
            single_team_sections,
            single_team_sections,
            0,
        ),
    ]

    return pd.DataFrame(
        rows,
        columns=[
            "check_name",
            "failed_row_count",
            "observed_value",
            "expected_value",
        ],
    )


def write_outputs(
    sections: pd.DataFrame,
    performances: pd.DataFrame,
    parsed: pd.DataFrame,
    candidates: pd.DataFrame,
    summary: pd.DataFrame,
    transitions: pd.DataFrame,
    checks: pd.DataFrame,
) -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    sections.to_csv(
        OUTPUT_DIR / "target_sections.csv",
        index=False,
    )
    performances.to_csv(
        OUTPUT_DIR / "target_performances.csv",
        index=False,
    )
    parsed.to_csv(
        OUTPUT_DIR
        / "parsed_performance_result_teams.csv",
        index=False,
    )
    candidates.to_csv(
        OUTPUT_DIR
        / "performance_resolution_candidates.csv",
        index=False,
    )
    summary.to_csv(
        OUTPUT_DIR
        / "section_resolution_summary.csv",
        index=False,
    )
    transitions.to_csv(
        OUTPUT_DIR
        / "section_team_transition_summary.csv",
        index=False,
    )

    candidates.loc[
        candidates[
            "performance_resolution_status"
        ].ne(
            "RESULT_PAGE_TEAM_RESOLVED"
        )
    ].to_csv(
        OUTPUT_DIR
        / "unresolved_performance_queue.csv",
        index=False,
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
    resolved_rows = int(
        candidates[
            "performance_resolution_status"
        ].eq(
            "RESULT_PAGE_TEAM_RESOLVED"
        ).sum()
    )
    unresolved_rows = int(
        len(candidates) - resolved_rows
    )

    report = f"""MILESTONE 4 MULTI-ENTITY PERFORMANCE RESOLUTION
============================================================
Resolution version: {RESOLUTION_VERSION}
Source database modified: no
Prior Milestone 4 outputs modified: no

SCOPE
- Genuine multi-entity sections: {len(sections):,}
- Performances represented: {len(performances):,}

RESULTS
- Resolved performance teams: {resolved_rows:,}
- Unresolved performance teams: {unresolved_rows:,}
- Sections summarized: {len(summary):,}
- Team-transition rows: {len(transitions):,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

NEXT GATE
When all hard checks pass, performance_resolution_candidates.csv provides the
highest-precedence attribution evidence for these 120 performances. The nine
sections must not receive one section-wide team assignment.
"""

    (
        OUTPUT_DIR / "resolution_report.txt"
    ).write_text(
        report,
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    require_inputs()

    if OUTPUT_DIR.exists() and not args.replace_output:
        existing = list(
            OUTPUT_DIR.glob("*.csv")
        ) + list(
            OUTPUT_DIR.glob("*.txt")
        )

        if existing:
            raise FileExistsError(
                "Existing resolution outputs found. "
                "Use --replace-output after review."
            )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    sections = load_target_sections()
    performances = load_target_performances(
        sections
    )
    parsed = parse_performances(
        performances=performances,
        args=args,
    )
    candidates = build_candidates(
        parsed
    )
    summary = build_section_summary(
        candidates
    )
    transitions = build_transition_summary(
        candidates
    )
    checks = build_checks(
        sections=sections,
        performances=performances,
        candidates=candidates,
        summary=summary,
    )

    write_outputs(
        sections=sections,
        performances=performances,
        parsed=parsed,
        candidates=candidates,
        summary=summary,
        transitions=transitions,
        checks=checks,
    )

    failed = int(
        (
            checks["failed_row_count"] > 0
        ).sum()
    )

    print(
        "Multi-entity performance resolution "
        "complete."
    )
    print(f"Outputs: {OUTPUT_DIR}")
    print(f"Failed checks: {failed:,}.")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
