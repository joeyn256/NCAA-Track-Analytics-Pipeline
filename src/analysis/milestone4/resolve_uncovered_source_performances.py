#!/usr/bin/env python3
"""
Milestone 4: resolve uncovered source performances from result-page evidence.

This is a targeted, read-only audit for source performances that remained
unresolved after the canonical attribution build because they had no team_id,
school, affiliation_id, or coverage-layer row.

The script:
- reads the existing canonical attribution staging database;
- finds rows with attribution_precedence = 'UNRESOLVED';
- reads source performance and athlete metadata;
- reuses existing Milestone 4 page caches where available;
- fetches only uncached result pages;
- parses the athlete's team directly from each result page;
- writes evidence only and does not modify any database.

Outputs
-------
data/processed/milestone4/uncovered_source_result_evidence/
    evidence_report.txt
    hard_checks.csv
    performance_result_evidence.csv
    resolved_team_summary.csv
    unresolved_result_page_queue.csv
    page_cache/
"""

from __future__ import annotations

import argparse
import hashlib
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

SOURCE_DB = (
    PROJECT_ROOT
    / "data/database/"
    / "ncaa_track_analytics.duckdb"
)

ATTRIBUTION_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_performance_attribution/"
    / "canonical_performance_attribution.duckdb"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "uncovered_source_result_evidence"
)

CACHE_DIR = OUTPUT_DIR / "page_cache"

EXISTING_CACHE_DIRS = [
    (
        PROJECT_ROOT
        / "data/processed/milestone4/"
        / "all_unresolved_section_result_page_evidence/"
        / "page_cache"
    ),
    (
        PROJECT_ROOT
        / "data/processed/milestone4/"
        / "multi_entity_performance_resolution/"
        / "page_cache"
    ),
    (
        PROJECT_ROOT
        / "data/processed/milestone4/"
        / "unresolved_section_result_page_prototype/"
        / "page_cache"
    ),
]

EVIDENCE_VERSION = (
    "m4_uncovered_source_result_evidence_v1.0"
)

EXPECTED_PERFORMANCE_ROWS = 18
EXPECTED_ATHLETE_COUNT = 1


def clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split()).strip()


def normalize_text(value: object) -> str:
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
    return re.sub(
        r"[^a-z0-9]+",
        "",
        text.casefold(),
    )


def normalize_person_name(
    value: object,
) -> str:
    text = clean(value)

    if not text:
        return ""

    if "," in text:
        last_name, first_name = [
            clean(part)
            for part in text.split(",", 1)
        ]
        text = f"{first_name} {last_name}"

    return normalize_text(text)


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
                normalize_text(parts[0]),
                "",
            )

        first_name = parts[0]
        last_name = parts[-1]

    return (
        normalize_text(first_name),
        normalize_text(last_name),
    )


def normalize_mark(
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
        SOURCE_DB,
        ATTRIBUTION_DB,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
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
        OUTPUT_DIR / "evidence_report.txt",
        OUTPUT_DIR / "hard_checks.csv",
        OUTPUT_DIR
        / "performance_result_evidence.csv",
        OUTPUT_DIR / "resolved_team_summary.csv",
        OUTPUT_DIR
        / "unresolved_result_page_queue.csv",
    ]

    existing = [
        path
        for path in generated
        if path.exists()
    ]

    if existing and not replace_output:
        raise FileExistsError(
            "Existing evidence outputs found. "
            "Use --replace-output after review."
        )

    if replace_output:
        for path in existing:
            path.unlink()


def sql_path(path: Path) -> str:
    return (
        path.resolve()
        .as_posix()
        .replace("'", "''")
    )


def load_targets() -> pd.DataFrame:
    con = duckdb.connect(
        str(ATTRIBUTION_DB),
        read_only=True,
    )

    try:
        con.execute(
            f"""
            ATTACH '{sql_path(SOURCE_DB)}'
            AS source
            (READ_ONLY)
            """
        )

        frame = con.execute(
            """
            SELECT
                a.performance_id,
                a.athlete_id,
                p.athlete_name,
                p.season_year,
                p.season_type,
                p.meet_id,
                p.meet_name,
                p.event,
                p.mark,
                p.result_url,
                p.team_id AS source_team_id,
                p.school AS source_school,
                p.affiliation_id,
                ath.current_school_name,
                ath.current_team_id
            FROM canonical_performance_attribution a
            JOIN source.core.performances p
              ON a.performance_id = p.performance_id
            LEFT JOIN source.core.athletes ath
              ON p.athlete_id = ath.athlete_id
            WHERE a.attribution_precedence
                = 'UNRESOLVED'
            ORDER BY
                p.athlete_id,
                p.season_year,
                p.season_type,
                p.meet_id,
                p.event,
                p.performance_id
            """
        ).fetchdf()

    finally:
        con.close()

    frame["athlete_id"] = (
        frame["athlete_id"]
        .astype(str)
    )
    frame["performance_id"] = (
        frame["performance_id"]
        .astype(str)
    )
    frame["result_url"] = (
        frame["result_url"]
        .fillna("")
        .astype(str)
    )
    frame["evidence_version"] = (
        EVIDENCE_VERSION
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


def build_session(
    max_retries: int,
) -> requests.Session:
    retry_policy = Retry(
        total=max_retries,
        connect=max_retries,
        read=max_retries,
        status=max_retries,
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
                "Milestone 4 evidence audit)"
            )
        }
    )

    return session


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

    for source_dir in EXISTING_CACHE_DIRS:
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
            return (
                html,
                "EXISTING_M4_CACHE_HIT",
                "",
            )

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
    athlete_id: str,
    athlete_name: str,
    performance_mark: str,
) -> tuple[list[Tag], str]:
    athlete_id_pattern = re.compile(
        rf"/athletes/{re.escape(athlete_id)}(?:/|$)",
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

    target_name = normalize_person_name(
        athlete_name
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

        candidate_name = (
            normalize_person_name(
                link.get_text(
                    " ",
                    strip=True,
                )
            )
        )

        if candidate_name != target_name:
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
    target_mark = normalize_mark(
        performance_mark
    )

    candidates: list[
        tuple[float, str, Tag]
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

        row_text = normalize_mark(
            row.get_text(
                " ",
                strip=True,
            )
        )

        mark_matches = (
            bool(target_mark)
            and target_mark in row_text
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
            and first_score >= 0.50
        )

        if not (
            mark_matches
            and plausible_name
        ):
            continue

        score = (
            0.60 * last_score
            + 0.40 * first_score
        )

        candidates.append(
            (
                score,
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


def extract_team(
    rows: list[Tag],
    result_url: str,
) -> tuple[str, str, str, int]:
    candidates: dict[
        str,
        tuple[str, str],
    ] = {}

    for row in rows:
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
            key = normalize_text(name)

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
    )


def team_id_from_url(
    value: object,
) -> str:
    url = clean(value)

    match = re.search(
        r"/teams/(?:tf|xc)/([^/]+?)(?:\.html)?$",
        url,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(1)

    return ""


def parse_targets(
    targets: pd.DataFrame,
    args: argparse.Namespace,
) -> pd.DataFrame:
    session = build_session(
        args.max_retries
    )

    rows: list[dict[str, Any]] = []

    for index, record in enumerate(
        targets.itertuples(
            index=False
        ),
        start=1,
    ):
        print(
            f"[{index:,}/{len(targets):,}] "
            f"{record.athlete_name} "
            f"{record.season_year} "
            f"{record.event}"
        )

        result_url = clean(
            record.result_url
        )

        output = {
            column: getattr(
                record,
                column,
            )
            for column in targets.columns
        }

        output.update(
            {
                "fetch_status": "",
                "fetch_error": "",
                "row_match_method": "",
                "matched_athlete_row_count": 0,
                "team_parse_status": "",
                "parsed_team_name": "",
                "parsed_team_url": "",
                "parsed_team_id": "",
                "parsed_team_matches_current_team": False,
            }
        )

        if not result_url:
            output[
                "fetch_status"
            ] = "MISSING_RESULT_URL"
            output[
                "team_parse_status"
            ] = "UNRESOLVED"
            rows.append(output)
            continue

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

        output["fetch_status"] = (
            fetch_status
        )
        output["fetch_error"] = (
            fetch_error
        )

        if not html:
            output[
                "team_parse_status"
            ] = "UNRESOLVED"
            rows.append(output)
            continue

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        athlete_rows, method = (
            find_athlete_rows(
                soup=soup,
                athlete_id=clean(
                    record.athlete_id
                ),
                athlete_name=clean(
                    record.athlete_name
                ),
                performance_mark=clean(
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
            rows.append(output)
            continue

        (
            team_name,
            team_url,
            parse_status,
            link_count,
        ) = extract_team(
            rows=athlete_rows,
            result_url=result_url,
        )

        team_id = team_id_from_url(
            team_url
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
                "parsed_team_id": (
                    team_id
                ),
                "matched_team_link_count": (
                    link_count
                ),
                "parsed_team_matches_current_team": (
                    bool(team_id)
                    and team_id
                    == clean(
                        record.current_team_id
                    )
                ),
            }
        )

        rows.append(output)

    return pd.DataFrame(rows)


def build_checks(
    evidence: pd.DataFrame,
) -> pd.DataFrame:
    resolved_mask = evidence[
        "team_parse_status"
    ].eq("TEAM_LINK_FOUND")

    resolved = evidence.loc[
        resolved_mask
    ]

    distinct_team_ids = {
        clean(value)
        for value in resolved[
            "parsed_team_id"
        ]
        if clean(value)
    }

    fetch_error_rows = int(
        evidence[
            "fetch_status"
        ].isin(
            [
                "FETCH_ERROR",
                "MISSING_RESULT_URL",
            ]
        ).sum()
    )

    unresolved_rows = int(
        (~resolved_mask).sum()
    )

    multiple_team_rows = int(
        evidence[
            "team_parse_status"
        ].eq(
            "MULTIPLE_DISTINCT_TEAM_LINKS"
        ).sum()
    )

    current_team_mismatch_rows = int(
        (
            resolved_mask
            & ~evidence[
                "parsed_team_matches_current_team"
            ].astype(bool)
        ).sum()
    )

    rows = [
        (
            "target_performance_rows",
            abs(
                len(evidence)
                - EXPECTED_PERFORMANCE_ROWS
            ),
            len(evidence),
            EXPECTED_PERFORMANCE_ROWS,
        ),
        (
            "target_athlete_count",
            abs(
                evidence[
                    "athlete_id"
                ].nunique()
                - EXPECTED_ATHLETE_COUNT
            ),
            evidence[
                "athlete_id"
            ].nunique(),
            EXPECTED_ATHLETE_COUNT,
        ),
        (
            "duplicate_performance_ids",
            int(
                evidence[
                    "performance_id"
                ].duplicated().sum()
            ),
            int(
                evidence[
                    "performance_id"
                ].duplicated().sum()
            ),
            0,
        ),
        (
            "fetch_error_rows",
            fetch_error_rows,
            fetch_error_rows,
            0,
        ),
        (
            "unresolved_team_rows",
            unresolved_rows,
            unresolved_rows,
            0,
        ),
        (
            "multiple_team_rows",
            multiple_team_rows,
            multiple_team_rows,
            0,
        ),
        (
            "distinct_resolved_team_ids",
            abs(
                len(distinct_team_ids) - 1
            ),
            len(distinct_team_ids),
            1,
        ),
        (
            "current_team_mismatch_rows",
            current_team_mismatch_rows,
            current_team_mismatch_rows,
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
    evidence: pd.DataFrame,
    checks: pd.DataFrame,
) -> None:
    evidence.to_csv(
        OUTPUT_DIR
        / "performance_result_evidence.csv",
        index=False,
    )

    resolved = evidence.loc[
        evidence[
            "team_parse_status"
        ].eq("TEAM_LINK_FOUND")
    ].copy()

    team_summary = (
        resolved.groupby(
            [
                "parsed_team_id",
                "parsed_team_name",
                "parsed_team_url",
            ],
            dropna=False,
        )
        .agg(
            performance_rows=(
                "performance_id",
                "size",
            ),
            athlete_count=(
                "athlete_id",
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
            meet_count=(
                "meet_id",
                "nunique",
            ),
        )
        .reset_index()
        .sort_values(
            "performance_rows",
            ascending=False,
        )
    )

    team_summary.to_csv(
        OUTPUT_DIR
        / "resolved_team_summary.csv",
        index=False,
    )

    evidence.loc[
        ~evidence[
            "team_parse_status"
        ].eq("TEAM_LINK_FOUND")
    ].to_csv(
        OUTPUT_DIR
        / "unresolved_result_page_queue.csv",
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
        len(resolved)
    )
    unresolved_rows = int(
        len(evidence) - resolved_rows
    )
    distinct_teams = int(
        resolved[
            "parsed_team_id"
        ].replace(
            "",
            pd.NA,
        ).dropna().nunique()
    )

    report = f"""MILESTONE 4 UNCOVERED SOURCE RESULT-PAGE EVIDENCE
============================================================
Evidence version: {EVIDENCE_VERSION}
Source database modified: no
Attribution database modified: no

SCOPE
- Target performances: {len(evidence):,}
- Target athletes: {evidence['athlete_id'].nunique():,}

RESULTS
- Result-page team resolutions: {resolved_rows:,}
- Unresolved result-page teams: {unresolved_rows:,}
- Distinct resolved team IDs: {distinct_teams:,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

NEXT GATE
If all 18 rows resolve to the same result-page team and all hard checks pass,
that result-page team may be used as a targeted high-confidence fallback in
canonical performance attribution v1.1. The athlete current-team field remains
corroborating evidence only.
"""

    (
        OUTPUT_DIR
        / "evidence_report.txt"
    ).write_text(
        report,
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()

    require_inputs()
    prepare_output(
        replace_output=args.replace_output,
    )

    targets = load_targets()
    evidence = parse_targets(
        targets=targets,
        args=args,
    )
    checks = build_checks(
        evidence
    )

    write_outputs(
        evidence=evidence,
        checks=checks,
    )

    failed = int(
        (
            checks["failed_row_count"] > 0
        ).sum()
    )

    print(
        "Uncovered source result-page "
        "evidence audit complete."
    )
    print(f"Outputs: {OUTPUT_DIR}")
    print(f"Failed checks: {failed:,}.")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
