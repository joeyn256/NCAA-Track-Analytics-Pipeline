#!/usr/bin/env python3
"""
Milestone 4: full result-page evidence for unresolved section entities.

Purpose
-------
Expand the validated result-page parser to every one of the 1,987 profile
sections that had no exact core or validated-alias candidate.

For each section, the script selects representative earliest and latest result
pages, preferring individual events over relays and combined-event component
pages. It parses the exact athlete row and exact team link, then validates
section-level consistency and agreement with the profile section name.

The script is resumable through an on-disk page cache. It does not modify the
Milestone 3 database or any prior Milestone 4 database/output.

Outputs
-------
data/processed/milestone4/all_unresolved_section_result_page_evidence/
    evidence_report.txt
    hard_checks.csv
    selected_sections.csv
    requested_result_pages.csv
    parsed_result_page_rows.csv
    section_result_team_summary.csv
    normalized_name_entity_summary.csv
    resolved_section_entity_candidates.csv
    page_parse_exception_queue.csv
    section_no_team_queue.csv
    section_multiple_team_queue.csv
    section_name_disagreement_queue.csv
    page_cache/
"""

from __future__ import annotations

import argparse
import hashlib
from difflib import SequenceMatcher
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import duckdb
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup, Tag


PROJECT_ROOT = Path(__file__).resolve().parents[3]

COVERAGE_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "multi_section_attribution_coverage/"
    / "multi_section_attribution_coverage.duckdb"
)

CANDIDATE_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "full_section_entity_resolution/"
    / "section_resolution_candidates.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "all_unresolved_section_result_page_evidence"
)

CACHE_DIR = OUTPUT_DIR / "page_cache"

PROTOTYPE_CACHE_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "unresolved_section_result_page_prototype/"
    / "page_cache"
)

EVIDENCE_VERSION = (
    "m4_all_unresolved_section_result_page_evidence_v1.0"
)

EXPECTED_SECTION_ROWS = 1_987


def clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split()).strip()


def normalize_name(value: object) -> str:
    text = clean(value)
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )
    text = text.casefold()
    text = text.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "", text)


def normalize_person_name(value: object) -> str:
    text = clean(value)
    if not text:
        return ""

    if "," in text:
        parts = [
            clean(part)
            for part in text.split(",", 1)
        ]
        text = " ".join(reversed(parts))

    return normalize_name(text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.40,
        help="Delay between uncached requests. Default: 0.40.",
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
        help="HTTP retries for transient failures. Default: 4.",
    )
    parser.add_argument(
        "--replace-output",
        action="store_true",
    )

    return parser.parse_args()


def require_inputs() -> None:
    for path in [
        COVERAGE_DB,
        CANDIDATE_CSV,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )


def select_sections() -> pd.DataFrame:
    candidates = pd.read_csv(
        CANDIDATE_CSV,
        dtype=str,
        keep_default_na=False,
    )

    selected = candidates.loc[
        candidates[
            "candidate_resolution_status"
        ].eq("NO_EXACT_CANDIDATE")
    ].copy()

    selected["athlete_id"] = pd.to_numeric(
        selected["athlete_id"],
        errors="coerce",
    ).astype("Int64")
    selected["section_index"] = pd.to_numeric(
        selected["section_index"],
        errors="coerce",
    ).astype("Int64")
    selected["performance_count"] = (
        pd.to_numeric(
            selected["performance_count"],
            errors="coerce",
        )
        .fillna(0)
        .astype("int64")
    )

    selected = selected.sort_values(
        [
            "performance_count",
            "candidate_normalized_name",
            "athlete_id",
            "section_index",
        ],
        ascending=[
            False,
            True,
            True,
            True,
        ],
    ).reset_index(drop=True)

    selected["evidence_version"] = (
        EVIDENCE_VERSION
    )

    return selected


def select_result_pages(
    selected: pd.DataFrame,
) -> pd.DataFrame:
    con = duckdb.connect(
        str(COVERAGE_DB),
        read_only=True,
    )

    try:
        con.register(
            "selected_sections_df",
            selected[
                [
                    "athlete_id",
                    "section_index",
                    "athlete_name",
                    "source_section_name",
                    "candidate_normalized_name",
                    "performance_count",
                ]
            ],
        )

        frame = con.execute(
            """
            WITH eligible AS (
                SELECT
                    s.athlete_id,
                    s.section_index,
                    s.athlete_name,
                    s.source_section_name,
                    s.candidate_normalized_name,
                    s.performance_count
                        AS section_performance_count,
                    c.performance_id,
                    c.season_year,
                    c.season_type,
                    c.meet_id,
                    c.meet_name,
                    c.event,
                    c.mark,
                    c.result_url,
                    CASE
                        WHEN regexp_matches(
                            lower(
                                COALESCE(
                                    c.result_url,
                                    ''
                                )
                            ),
                            (
                                'relay|4-x-|4x|'
                                'distance-medley|'
                                'sprint-medley|'
                                'heptathlon|'
                                'decathlon|'
                                'pentathlon'
                            )
                        )
                            THEN 1
                        WHEN regexp_matches(
                            lower(
                                COALESCE(
                                    c.event,
                                    ''
                                )
                            ),
                            (
                                '^(4x|dmr|smr|'
                                'pent|hept|dec)'
                            )
                        )
                            THEN 1
                        ELSE 0
                    END AS complex_event_priority
                FROM selected_sections_df s
                JOIN multi_section_performance_coverage c
                  ON s.athlete_id = c.athlete_id
                 AND s.section_index
                   = c.matched_section_index
            ),
            ranked AS (
                SELECT
                    *,
                    row_number() OVER (
                        PARTITION BY
                            athlete_id,
                            section_index
                        ORDER BY
                            complex_event_priority,
                            TRY_CAST(
                                season_year AS INTEGER
                            ),
                            result_url,
                            performance_id
                    ) AS first_rank,
                    row_number() OVER (
                        PARTITION BY
                            athlete_id,
                            section_index
                        ORDER BY
                            complex_event_priority,
                            TRY_CAST(
                                season_year AS INTEGER
                            ) DESC,
                            result_url DESC,
                            performance_id DESC
                    ) AS last_rank
                FROM eligible
            )
            SELECT
                *,
                CASE
                    WHEN first_rank = 1
                     AND last_rank = 1
                        THEN 'ONLY'
                    WHEN first_rank = 1
                        THEN 'EARLIEST'
                    ELSE 'LATEST'
                END AS sample_position
            FROM ranked
            WHERE first_rank = 1
               OR last_rank = 1
            ORDER BY
                section_performance_count DESC,
                athlete_id,
                section_index,
                sample_position
            """
        ).fetchdf()

    finally:
        con.close()

    frame = frame.drop_duplicates(
        [
            "athlete_id",
            "section_index",
            "performance_id",
        ]
    ).copy()

    frame["evidence_version"] = (
        EVIDENCE_VERSION
    )

    return frame


def cache_path(
    url: str,
    directory: Path = CACHE_DIR,
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
    path = cache_path(url)

    if path.exists():
        return (
            path.read_text(
                encoding="utf-8",
                errors="replace",
            ),
            "CACHE_HIT",
            "",
        )

    prototype_path = cache_path(
        url,
        directory=PROTOTYPE_CACHE_DIR,
    )

    if prototype_path.exists():
        html = prototype_path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        path.write_text(
            html,
            encoding="utf-8",
        )
        return (
            html,
            "PROTOTYPE_CACHE_HIT",
            "",
        )

    try:
        response = session.get(
            url,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        html = response.text
        path.write_text(
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
    return "/athletes/" in clean(href).casefold()


def is_team_link(
    href: object,
) -> bool:
    normalized = clean(href).casefold()
    return (
        "/teams/" in normalized
        or "/team/" in normalized
    )


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
            return normalize_name(parts[0]), ""

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
        href = clean(link.get("href"))

        if not athlete_id_pattern.search(href):
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

    normalized_target = normalize_person_name(
        athlete_name
    )

    if not normalized_target:
        return [], "NO_ATHLETE_IDENTIFIER"

    exact_name_rows: list[Tag] = []

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

        link_name = normalize_person_name(
            link.get_text(
                " ",
                strip=True,
            )
        )

        if link_name != normalized_target:
            continue

        row = link.find_parent("tr")

        if row is not None:
            exact_name_rows.append(row)

    exact_name_rows = unique_rows(
        exact_name_rows
    )

    if exact_name_rows:
        return (
            exact_name_rows,
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

    candidate_records: list[
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

        combined_score = (
            (0.60 * last_score)
            + (0.40 * first_score)
        )

        candidate_records.append(
            (
                combined_score,
                normalize_person_name(
                    candidate_name
                ),
                row,
            )
        )

    if not candidate_records:
        return [], "ATHLETE_ROW_NOT_FOUND"

    best_score = max(
        record[0]
        for record in candidate_records
    )

    best_records = [
        record
        for record in candidate_records
        if abs(
            record[0] - best_score
        ) < 1e-9
    ]

    best_names = {
        record[1]
        for record in best_records
    }

    if len(best_names) != 1:
        return (
            [],
            "AMBIGUOUS_FUZZY_NAME_MARK_ROWS",
        )

    best_rows = unique_rows(
        [
            record[2]
            for record in best_records
        ]
    )

    return (
        best_rows,
        "FUZZY_NAME_AND_EXACT_MARK_ROWS",
    )


def extract_team_from_rows(
    rows: list[Tag],
    result_url: str,
) -> tuple[
    str,
    str,
    str,
    str,
    str,
    int,
]:
    team_candidates: dict[
        str,
        tuple[str, str],
    ] = {}

    row_cell_texts: list[list[str]] = []
    row_html: list[str] = []

    for row in rows:
        cells = row.find_all(
            ["td", "th"],
            recursive=False,
        )

        if not cells:
            cells = row.find_all(
                ["td", "th"],
            )

        row_cell_texts.append(
            [
                clean(
                    cell.get_text(
                        " ",
                        strip=True,
                    )
                )
                for cell in cells
            ]
        )
        row_html.append(str(row))

        for link in row.find_all(
            "a",
            href=True,
        ):
            href = clean(link.get("href"))
            team_name = clean(
                link.get_text(
                    " ",
                    strip=True,
                )
            )

            if not team_name:
                continue
            if not is_team_link(href):
                continue

            normalized_team = normalize_name(
                team_name
            )
            if not normalized_team:
                continue

            team_candidates[
                normalized_team
            ] = (
                team_name,
                urljoin(
                    result_url,
                    href,
                ),
            )

    if not team_candidates:
        return (
            "",
            "",
            "TEAM_LINK_NOT_FOUND",
            json.dumps(
                row_cell_texts,
                ensure_ascii=False,
            ),
            "\n".join(row_html),
            0,
        )

    ordered = sorted(
        team_candidates.items(),
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
            json.dumps(
                row_cell_texts,
                ensure_ascii=False,
            ),
            "\n".join(row_html),
            len(ordered),
        )

    _, (
        team_name,
        team_url,
    ) = ordered[0]

    return (
        team_name,
        team_url,
        "TEAM_LINK_FOUND",
        json.dumps(
            row_cell_texts,
            ensure_ascii=False,
        ),
        "\n".join(row_html),
        1,
    )


def parse_pages(
    pages: pd.DataFrame,
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
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )

    session = requests.Session()
    adapter = HTTPAdapter(
        max_retries=retry_policy,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; NCAA Track Analytics "
                "Milestone 4 research audit)"
            )
        }
    )

    rows: list[dict[str, Any]] = []

    for index, record in enumerate(
        pages.itertuples(index=False),
        start=1,
    ):
        result_url = clean(record.result_url)

        print(
            f"[{index:,}/{len(pages):,}] "
            f"{record.athlete_id} "
            f"{record.source_section_name} "
            f"{record.sample_position}"
        )

        html, fetch_status, fetch_error = (
            fetch_page(
                session=session,
                url=result_url,
                timeout_seconds=args.timeout_seconds,
                sleep_seconds=args.sleep_seconds,
            )
        )

        output = record._asdict()
        output.update(
            {
                "fetch_status": fetch_status,
                "fetch_error": fetch_error,
                "row_match_method": "",
                "matched_athlete_row_count": 0,
                "matched_team_link_count": 0,
                "team_parse_status": "",
                "parsed_team_name": "",
                "parsed_team_url": "",
                "normalized_parsed_team_name": "",
                "section_team_name_matches": False,
                "row_cell_texts_json": "",
                "row_html": "",
                "evidence_version": (
                    EVIDENCE_VERSION
                ),
            }
        )

        if not html:
            rows.append(output)
            continue

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        athlete_rows, row_match_method = (
            find_athlete_rows(
                soup=soup,
                athlete_id=int(
                    record.athlete_id
                ),
                athlete_name=record.athlete_name,
                performance_mark=record.mark,
            )
        )

        output["row_match_method"] = (
            row_match_method
        )
        output[
            "matched_athlete_row_count"
        ] = len(athlete_rows)

        if not athlete_rows:
            output["team_parse_status"] = (
                "ATHLETE_ROW_UNRESOLVED"
            )
            rows.append(output)
            continue

        (
            team_name,
            team_url,
            team_parse_status,
            cell_texts,
            row_html,
            team_link_count,
        ) = extract_team_from_rows(
            rows=athlete_rows,
            result_url=result_url,
        )

        normalized_team = normalize_name(
            team_name
        )
        normalized_section = normalize_name(
            record.source_section_name
        )

        output.update(
            {
                "matched_team_link_count": (
                    team_link_count
                ),
                "team_parse_status": (
                    team_parse_status
                ),
                "parsed_team_name": team_name,
                "parsed_team_url": team_url,
                "normalized_parsed_team_name": (
                    normalized_team
                ),
                "section_team_name_matches": (
                    team_parse_status
                    == "TEAM_LINK_FOUND"
                    and bool(normalized_team)
                    and normalized_team
                    == normalized_section
                ),
                "row_cell_texts_json": (
                    cell_texts
                ),
                "row_html": row_html,
            }
        )

        rows.append(output)

    return pd.DataFrame(rows)


def build_section_summary(
    parsed: pd.DataFrame,
) -> pd.DataFrame:
    accepted_fetch_statuses = {
        "FETCHED",
        "CACHE_HIT",
        "PROTOTYPE_CACHE_HIT",
    }

    grouped = (
        parsed.groupby(
            [
                "athlete_id",
                "section_index",
                "athlete_name",
                "source_section_name",
                "candidate_normalized_name",
                "section_performance_count",
            ],
            dropna=False,
        )
        .agg(
            requested_page_count=(
                "performance_id",
                "size",
            ),
            fetched_page_count=(
                "fetch_status",
                lambda values: sum(
                    value
                    in accepted_fetch_statuses
                    for value in values
                ),
            ),
            parsed_team_page_count=(
                "parsed_team_name",
                lambda values: sum(
                    bool(clean(value))
                    for value in values
                ),
            ),
            distinct_parsed_team_count=(
                "normalized_parsed_team_name",
                lambda values: len(
                    {
                        clean(value)
                        for value in values
                        if clean(value)
                    }
                ),
            ),
            distinct_parsed_team_url_count=(
                "parsed_team_url",
                lambda values: len(
                    {
                        clean(value)
                        for value in values
                        if clean(value)
                    }
                ),
            ),
            parsed_team_names=(
                "parsed_team_name",
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
            parsed_team_urls=(
                "parsed_team_url",
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
            exact_name_match_page_count=(
                "section_team_name_matches",
                "sum",
            ),
            unresolved_page_count=(
                "team_parse_status",
                lambda values: sum(
                    value != "TEAM_LINK_FOUND"
                    for value in values
                ),
            ),
        )
        .reset_index()
    )

    grouped["section_parse_status"] = (
        "PARSED_CONSISTENT_TEAM"
    )

    grouped.loc[
        grouped["parsed_team_page_count"].eq(0),
        "section_parse_status",
    ] = "NO_PARSED_TEAM"

    grouped.loc[
        grouped[
            "distinct_parsed_team_count"
        ].gt(1)
        | grouped[
            "distinct_parsed_team_url_count"
        ].gt(1),
        "section_parse_status",
    ] = "MULTIPLE_PARSED_TEAMS"

    grouped["section_name_agreement_status"] = (
        "PARSED_TEAM_DIFFERS_FROM_SECTION"
    )

    grouped.loc[
        grouped[
            "exact_name_match_page_count"
        ].eq(
            grouped["parsed_team_page_count"]
        )
        & grouped[
            "parsed_team_page_count"
        ].gt(0),
        "section_name_agreement_status",
    ] = "EXACT_NAME_AGREEMENT"

    grouped["evidence_version"] = (
        EVIDENCE_VERSION
    )

    return grouped


def build_name_entity_summary(
    summary: pd.DataFrame,
) -> pd.DataFrame:
    frame = (
        summary.groupby(
            [
                "candidate_normalized_name",
                "source_section_name",
            ],
            dropna=False,
        )
        .agg(
            section_count=(
                "section_index",
                "size",
            ),
            athlete_count=(
                "athlete_id",
                "nunique",
            ),
            performance_count=(
                "section_performance_count",
                "sum",
            ),
            resolved_section_count=(
                "section_parse_status",
                lambda values: sum(
                    value
                    == "PARSED_CONSISTENT_TEAM"
                    for value in values
                ),
            ),
            unresolved_section_count=(
                "section_parse_status",
                lambda values: sum(
                    value
                    != "PARSED_CONSISTENT_TEAM"
                    for value in values
                ),
            ),
            distinct_parsed_team_name_count=(
                "parsed_team_names",
                lambda values: len(
                    {
                        clean(value)
                        for value in values
                        if clean(value)
                    }
                ),
            ),
            distinct_parsed_team_url_count=(
                "parsed_team_urls",
                lambda values: len(
                    {
                        clean(value)
                        for value in values
                        if clean(value)
                    }
                ),
            ),
            parsed_team_names=(
                "parsed_team_names",
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
            parsed_team_urls=(
                "parsed_team_urls",
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
        )
        .reset_index()
    )

    frame["name_entity_status"] = (
        "CONSISTENT_NAME_ENTITY"
    )

    frame.loc[
        frame["unresolved_section_count"].gt(0),
        "name_entity_status",
    ] = "NAME_HAS_UNRESOLVED_SECTIONS"

    frame.loc[
        frame[
            "distinct_parsed_team_name_count"
        ].gt(1)
        | frame[
            "distinct_parsed_team_url_count"
        ].gt(1),
        "name_entity_status",
    ] = "NAME_MAPS_TO_MULTIPLE_ENTITIES"

    frame["evidence_version"] = (
        EVIDENCE_VERSION
    )

    return frame


def build_checks(
    selected: pd.DataFrame,
    parsed: pd.DataFrame,
    summary: pd.DataFrame,
) -> pd.DataFrame:
    selected_rows = len(selected)

    fetch_errors = int(
        parsed["fetch_status"]
        .eq("FETCH_ERROR")
        .sum()
    )
    unresolved_page_rows = int(
        (
            ~parsed["team_parse_status"]
            .eq("TEAM_LINK_FOUND")
        ).sum()
    )
    sections_without_team = int(
        summary["section_parse_status"]
        .eq("NO_PARSED_TEAM")
        .sum()
    )
    sections_with_multiple_teams = int(
        summary["section_parse_status"]
        .eq("MULTIPLE_PARSED_TEAMS")
        .sum()
    )
    name_disagreements = int(
        summary[
            "section_name_agreement_status"
        ].ne("EXACT_NAME_AGREEMENT").sum()
    )
    duplicate_pages = int(
        parsed.duplicated(
            [
                "athlete_id",
                "section_index",
                "performance_id",
            ]
        ).sum()
    )
    duplicate_sections = int(
        summary.duplicated(
            [
                "athlete_id",
                "section_index",
            ]
        ).sum()
    )
    athlete_name_as_team = int(
        sum(
            bool(
                clean(row.parsed_team_name)
            )
            and normalize_person_name(
                row.parsed_team_name
            )
            == normalize_person_name(
                row.athlete_name
            )
            for row in parsed.itertuples(
                index=False
            )
        )
    )

    checks = [
        (
            "selected_section_rows",
            abs(
                selected_rows
                - EXPECTED_SECTION_ROWS
            ),
            selected_rows,
            EXPECTED_SECTION_ROWS,
        ),
        (
            "section_summary_rows",
            abs(
                len(summary)
                - selected_rows
            ),
            len(summary),
            selected_rows,
        ),
        (
            "duplicate_requested_page_keys",
            duplicate_pages,
            duplicate_pages,
            0,
        ),
        (
            "duplicate_section_summary_keys",
            duplicate_sections,
            duplicate_sections,
            0,
        ),
        (
            "fetch_error_rows",
            0,
            fetch_errors,
            "informational",
        ),
        (
            "unresolved_team_parse_rows",
            0,
            unresolved_page_rows,
            "informational",
        ),
        (
            "sections_without_parsed_team",
            sections_without_team,
            sections_without_team,
            0,
        ),
        (
            "sections_with_multiple_parsed_teams",
            sections_with_multiple_teams,
            sections_with_multiple_teams,
            0,
        ),
        (
            "section_team_name_disagreements",
            name_disagreements,
            name_disagreements,
            0,
        ),
        (
            "athlete_name_parsed_as_team",
            athlete_name_as_team,
            athlete_name_as_team,
            0,
        ),
    ]

    return pd.DataFrame(
        checks,
        columns=[
            "check_name",
            "failed_row_count",
            "observed_value",
            "expected_value",
        ],
    )


def write_outputs(
    selected: pd.DataFrame,
    pages: pd.DataFrame,
    parsed: pd.DataFrame,
    summary: pd.DataFrame,
    name_summary: pd.DataFrame,
    checks: pd.DataFrame,
) -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    selected.to_csv(
        OUTPUT_DIR / "selected_sections.csv",
        index=False,
    )
    pages.to_csv(
        OUTPUT_DIR / "requested_result_pages.csv",
        index=False,
    )
    parsed.to_csv(
        OUTPUT_DIR / "parsed_result_page_rows.csv",
        index=False,
    )
    summary.to_csv(
        OUTPUT_DIR / "section_result_team_summary.csv",
        index=False,
    )
    name_summary.to_csv(
        OUTPUT_DIR
        / "normalized_name_entity_summary.csv",
        index=False,
    )
    checks.to_csv(
        OUTPUT_DIR / "hard_checks.csv",
        index=False,
    )

    summary.loc[
        summary["section_parse_status"]
        .eq("PARSED_CONSISTENT_TEAM")
        & summary[
            "section_name_agreement_status"
        ].eq("EXACT_NAME_AGREEMENT")
    ].to_csv(
        OUTPUT_DIR
        / "resolved_section_entity_candidates.csv",
        index=False,
    )

    parsed.loc[
        ~parsed["team_parse_status"]
        .eq("TEAM_LINK_FOUND")
    ].to_csv(
        OUTPUT_DIR
        / "page_parse_exception_queue.csv",
        index=False,
    )

    summary.loc[
        summary["section_parse_status"]
        .eq("NO_PARSED_TEAM")
    ].to_csv(
        OUTPUT_DIR / "section_no_team_queue.csv",
        index=False,
    )

    summary.loc[
        summary["section_parse_status"]
        .eq("MULTIPLE_PARSED_TEAMS")
    ].to_csv(
        OUTPUT_DIR
        / "section_multiple_team_queue.csv",
        index=False,
    )

    summary.loc[
        ~summary[
            "section_name_agreement_status"
        ].eq("EXACT_NAME_AGREEMENT")
    ].to_csv(
        OUTPUT_DIR
        / "section_name_disagreement_queue.csv",
        index=False,
    )

    failed = int(
        (checks["failed_row_count"] > 0).sum()
    )
    exact_agreement_sections = int(
        summary[
            "section_name_agreement_status"
        ].eq("EXACT_NAME_AGREEMENT").sum()
    )
    disagreement_sections = int(
        len(summary) - exact_agreement_sections
    )
    multiple_team_sections = int(
        summary[
            "section_parse_status"
        ].eq(
            "MULTIPLE_PARSED_TEAMS"
        ).sum()
    )
    no_parsed_team_sections = int(
        summary[
            "section_parse_status"
        ].eq(
            "NO_PARSED_TEAM"
        ).sum()
    )
    unresolved_page_rows = int(
        (
            ~parsed["team_parse_status"]
            .eq("TEAM_LINK_FOUND")
        ).sum()
    )
    names_with_multiple_entities = int(
        name_summary[
            "name_entity_status"
        ].eq(
            "NAME_MAPS_TO_MULTIPLE_ENTITIES"
        ).sum()
    )

    report = f"""MILESTONE 4 ALL UNRESOLVED SECTION RESULT-PAGE EVIDENCE
============================================================
Evidence version: {EVIDENCE_VERSION}
Existing databases modified: no
Prior Milestone 4 outputs modified: no

SCOPE
- Unresolved profile sections selected: {len(selected):,}
- Representative result pages requested: {len(pages):,}
- Sections summarized: {len(summary):,}
- Unique normalized section names: {len(name_summary):,}

RESULTS
- Exact section/result-team name agreements: {exact_agreement_sections:,}
- Section/result-team name disagreements: {disagreement_sections:,}
- Sections with multiple parsed result teams: {multiple_team_sections:,}
- Sections without a parsed team: {no_parsed_team_sections:,}
- Individual page parse exceptions: {unresolved_page_rows:,}
- Normalized names mapping to multiple entities: {names_with_multiple_entities:,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

NEXT GATE
If all hard checks pass, resolved_section_entity_candidates.csv provides
deterministic result-page identity evidence for all 1,987 previously unresolved
sections. Individual page exceptions remain audit evidence but do not block a
section when another representative page resolves it consistently.
"""

    (
        OUTPUT_DIR / "evidence_report.txt"
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
                "Existing full-scale outputs found. "
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

    selected = select_sections()
    pages = select_result_pages(selected)
    parsed = parse_pages(
        pages=pages,
        args=args,
    )
    summary = build_section_summary(parsed)
    name_summary = build_name_entity_summary(
        summary
    )
    checks = build_checks(
        selected=selected,
        parsed=parsed,
        summary=summary,
    )

    write_outputs(
        selected=selected,
        pages=pages,
        parsed=parsed,
        summary=summary,
        name_summary=name_summary,
        checks=checks,
    )

    failed = int(
        (checks["failed_row_count"] > 0).sum()
    )

    print(
        "All-unresolved-section result-page evidence "
        "audit complete."
    )
    print(f"Outputs: {OUTPUT_DIR}")
    print(f"Failed checks: {failed:,}.")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
