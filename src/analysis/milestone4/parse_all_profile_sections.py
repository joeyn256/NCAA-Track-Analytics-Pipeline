#!/usr/bin/env python3
"""
Milestone 4: checkpointed all-profile section parser.

This is Phase 1 of the full-scale Milestone 4 reconstruction. It parses all
saved TFRRS athlete profiles into a separate staging DuckDB database.

READ-ONLY SOURCE GUARANTEE
--------------------------
This script does not modify:
- data/database/ncaa_track_analytics.duckdb
- raw athlete HTML
- prior Milestone 4 outputs

It writes only to:
    data/processed/milestone4/all_profile_staging/

DEFAULT RESUME BEHAVIOR
-----------------------
The parser skips every athlete already recorded in profile_parse_status.
A stopped run can therefore be restarted with the same command.

To retry prior failures:
    --retry-errors

To erase the staging database and begin again:
    --reset

SMOKE TEST
----------
    python src/analysis/milestone4/parse_all_profile_sections.py --limit 100

FULL RUN
--------
    python src/analysis/milestone4/parse_all_profile_sections.py

OUTPUT DATABASE TABLES
----------------------
- parser_runs
- profile_parse_status
- profile_sections
- section_url_keys
- parser_batch_checkpoints

SPACE-SAVING DESIGN
-------------------
The parser stores SHA-256 keys for normalized TFRRS result URLs rather than
repeating the full URL text for millions of links. The later attribution phase
will normalize and hash core.performances.result_url with the identical rule.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import time
import traceback
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import duckdb
import pandas as pd
from bs4 import BeautifulSoup, Tag


PROJECT_ROOT = Path(__file__).resolve().parents[3]

SOURCE_DB_PATH = (
    PROJECT_ROOT / "data/database/ncaa_track_analytics.duckdb"
)
ATHLETE_PAGE_DIR = PROJECT_ROOT / "data/raw/athlete_pages"

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/all_profile_staging"
)
STAGING_DB_PATH = OUTPUT_DIR / "all_profile_staging.duckdb"
REPORT_PATH = OUTPUT_DIR / "profile_parse_report.txt"

TFRRS_BASE_URL = "https://www.tfrrs.org/"
PARSER_VERSION = "m4_all_profile_parser_v1.0"

WHITESPACE_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
TRANSFER_RE = re.compile(
    r"Competing\s+for\s+(.+?)(?:\s*[↓▼]+\s*)?$",
    re.IGNORECASE,
)
RESULT_DETAIL_RE = re.compile(
    r"^/results/\d+/\d+(?:/|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedSection:
    athlete_id: int
    section_index: int
    source_section_name: str
    normalized_section_name: str
    marker_text: str
    attribution_method: str
    is_current_section: bool


@dataclass(frozen=True)
class ParsedUrlKey:
    athlete_id: int
    section_index: int
    url_sha256: str
    url_kind: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def clean_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return WHITESPACE_RE.sub(" ", str(value)).strip()


def normalize_school_name(value: object) -> str:
    text = clean_text(value).lower()
    text = text.replace("&amp;", "and")
    text = text.replace("&", "and")
    return NON_ALNUM_RE.sub("", text)


def clean_transfer_school(marker_text: str) -> str:
    text = clean_text(marker_text)
    match = TRANSFER_RE.search(text)

    if not match:
        return text.strip("↓▼ ").strip()

    return clean_text(match.group(1)).strip("↓▼ ").strip()


def normalize_url(value: object) -> str:
    text = clean_text(value)

    if not text:
        return ""

    # Defensive cleanup for malformed concatenated absolute URLs.
    text = text.replace(
        "https://www.tfrrs.orghttps://",
        "https://",
    ).replace(
        "https://tfrrs.orghttps://",
        "https://",
    )

    absolute = urljoin(TFRRS_BASE_URL, text)
    split = urlsplit(absolute)

    path = split.path.rstrip("/") or "/"

    return urlunsplit(
        (
            split.scheme.lower(),
            split.netloc.lower(),
            path,
            split.query,
            "",
        )
    )


def url_sha256(normalized_url: str) -> str:
    return hashlib.sha256(
        normalized_url.encode("utf-8")
    ).hexdigest()


def file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def stable_section_id(
    athlete_id: int,
    section_index: int,
    source_section_name: str,
) -> str:
    raw = (
        f"{athlete_id}|{section_index}|"
        f"{clean_text(source_section_name)}"
    )
    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:20]
    return f"m4sec_{digest}"


def classify_url_kind(normalized_url: str) -> str:
    path = urlsplit(normalized_url).path

    if path.lower().startswith("/results/xc/"):
        return "XC_RESULT_OR_MEET"

    if RESULT_DETAIL_RE.search(path):
        return "RESULT_DETAIL"

    if path.lower().startswith("/results/"):
        return "MEET_OR_RESULTS_PAGE"

    return "OTHER"


def is_transfer_marker(tag: Tag) -> bool:
    classes = set(tag.get("class", []))
    text = clean_text(tag.get_text(" ", strip=True))

    return (
        tag.name == "div"
        and "transfer" in classes
        and bool(TRANSFER_RE.search(text))
    )


def extract_current_school(
    soup: BeautifulSoup,
    candidate_schools: list[str],
) -> dict[str, Any]:
    candidate_map: dict[str, str] = {}

    for school in candidate_schools:
        normalized = normalize_school_name(school)

        if normalized and normalized not in candidate_map:
            candidate_map[normalized] = clean_text(school)

    lines: list[str] = []

    for raw_line in soup.get_text("\n", strip=True).splitlines():
        line = clean_text(raw_line)

        if not line:
            continue
        if line.lower() == "college bests":
            break
        if TRANSFER_RE.search(line):
            break

        lines.append(line)

        if len(lines) >= 150:
            break

    matches: list[tuple[int, str, str]] = []

    for index, line in enumerate(lines):
        lowered = line.lower()

        if "previously at" in lowered:
            continue
        if "competing for" in lowered:
            continue
        if lowered.startswith("high school:"):
            continue

        normalized = normalize_school_name(line)

        if normalized in candidate_map:
            matches.append(
                (
                    index,
                    candidate_map[normalized],
                    line,
                )
            )

    if not matches:
        return {
            "current_school": "",
            "status": "NO_HEADER_SCHOOL_MATCH",
            "header_line_index": None,
            "header_candidate_lines": " | ".join(
                lines[:40]
            ),
        }

    line_index, canonical_school, _raw = matches[0]
    unique_matches = {
        normalize_school_name(item[1])
        for item in matches
    }

    status = "UNIQUE_HEADER_SCHOOL_MATCH"

    if len(unique_matches) > 1:
        status = "FIRST_OF_MULTIPLE_HEADER_SCHOOL_MATCHES"

    return {
        "current_school": canonical_school,
        "status": status,
        "header_line_index": line_index,
        "header_candidate_lines": " | ".join(
            f"{item[0]}:{item[2]}"
            for item in matches
        ),
    }


def parse_profile(
    athlete_id: int,
    html_bytes: bytes,
    candidate_schools: list[str],
) -> tuple[
    list[ParsedSection],
    list[ParsedUrlKey],
    dict[str, Any],
]:
    html = html_bytes.decode(
        "utf-8",
        errors="ignore",
    )
    soup = BeautifulSoup(html, "html.parser")

    current = extract_current_school(
        soup=soup,
        candidate_schools=candidate_schools,
    )
    current_school = clean_text(
        current.get("current_school")
    )

    panel = soup.find(id="meet-results")

    if not isinstance(panel, Tag):
        return (
            [],
            [],
            {
                **current,
                "parse_status": "MEET_RESULTS_PANEL_NOT_FOUND",
            },
        )

    initial_school = (
        current_school
        or "[UNRESOLVED CURRENT SCHOOL]"
    )

    sections: list[ParsedSection] = [
        ParsedSection(
            athlete_id=athlete_id,
            section_index=0,
            source_section_name=initial_school,
            normalized_section_name=normalize_school_name(
                initial_school
            ),
            marker_text="",
            attribution_method="PROFILE_CURRENT_SCHOOL",
            is_current_section=True,
        )
    ]
    url_keys: list[ParsedUrlKey] = []

    active_section_index = 0
    active_school = initial_school

    seen_url_keys: set[tuple[int, str]] = set()

    def walk(node: Tag) -> None:
        nonlocal active_section_index, active_school

        for child in node.children:
            if not isinstance(child, Tag):
                continue

            if is_transfer_marker(child):
                marker_text = clean_text(
                    child.get_text(" ", strip=True)
                )
                active_school = clean_transfer_school(
                    marker_text
                )
                active_section_index += 1

                sections.append(
                    ParsedSection(
                        athlete_id=athlete_id,
                        section_index=active_section_index,
                        source_section_name=active_school,
                        normalized_section_name=(
                            normalize_school_name(
                                active_school
                            )
                        ),
                        marker_text=marker_text,
                        attribution_method=(
                            "PROFILE_TRANSFER_MARKER"
                        ),
                        is_current_section=False,
                    )
                )
                continue

            if child.name == "a" and child.get("href"):
                normalized_url = normalize_url(
                    child.get("href")
                )

                if (
                    normalized_url
                    and "/results/" in normalized_url.lower()
                ):
                    digest = url_sha256(normalized_url)
                    dedupe_key = (
                        active_section_index,
                        digest,
                    )

                    if dedupe_key not in seen_url_keys:
                        seen_url_keys.add(dedupe_key)

                        url_keys.append(
                            ParsedUrlKey(
                                athlete_id=athlete_id,
                                section_index=(
                                    active_section_index
                                ),
                                url_sha256=digest,
                                url_kind=classify_url_kind(
                                    normalized_url
                                ),
                            )
                        )

            walk(child)

    walk(panel)

    return (
        sections,
        url_keys,
        {
            **current,
            "parse_status": "OK",
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N pending athlete profiles.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=250,
        help="Checkpoint batch size. Default: 250.",
    )
    parser.add_argument(
        "--athlete-ids",
        nargs="*",
        type=int,
        default=None,
        help="Process only these athlete IDs.",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Retry prior non-OK parse records.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the staging output directory first.",
    )

    return parser.parse_args()


def initialize_staging(
    con: duckdb.DuckDBPyConnection,
) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS parser_runs (
            run_id VARCHAR PRIMARY KEY,
            parser_version VARCHAR NOT NULL,
            source_database VARCHAR NOT NULL,
            staging_database VARCHAR NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ,
            requested_limit BIGINT,
            batch_size BIGINT NOT NULL,
            retry_errors BOOLEAN NOT NULL,
            run_status VARCHAR NOT NULL,
            athlete_rows_attempted BIGINT DEFAULT 0,
            athlete_rows_succeeded BIGINT DEFAULT 0,
            athlete_rows_failed BIGINT DEFAULT 0,
            section_rows_written BIGINT DEFAULT 0,
            url_key_rows_written BIGINT DEFAULT 0
        )
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS profile_parse_status (
            athlete_id BIGINT PRIMARY KEY,
            athlete_name VARCHAR,
            source_html_file VARCHAR,
            source_html_sha256 VARCHAR,
            source_file_size_bytes BIGINT,
            current_school VARCHAR,
            current_school_status VARCHAR,
            header_line_index BIGINT,
            header_candidate_lines VARCHAR,
            parse_status VARCHAR NOT NULL,
            section_count BIGINT NOT NULL,
            url_key_count BIGINT NOT NULL,
            error_type VARCHAR,
            error_message VARCHAR,
            parser_version VARCHAR NOT NULL,
            last_run_id VARCHAR NOT NULL,
            processed_at TIMESTAMPTZ NOT NULL
        )
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS profile_sections (
            profile_section_id VARCHAR PRIMARY KEY,
            athlete_id BIGINT NOT NULL,
            section_index BIGINT NOT NULL,
            source_section_name VARCHAR NOT NULL,
            normalized_section_name VARCHAR NOT NULL,
            marker_text VARCHAR,
            attribution_method VARCHAR NOT NULL,
            is_current_section BOOLEAN NOT NULL,
            source_html_sha256 VARCHAR NOT NULL,
            parser_version VARCHAR NOT NULL,
            last_run_id VARCHAR NOT NULL,
            UNIQUE (athlete_id, section_index)
        )
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS section_url_keys (
            athlete_id BIGINT NOT NULL,
            section_index BIGINT NOT NULL,
            url_sha256 VARCHAR NOT NULL,
            url_kind VARCHAR NOT NULL,
            parser_version VARCHAR NOT NULL,
            last_run_id VARCHAR NOT NULL,
            PRIMARY KEY (
                athlete_id,
                section_index,
                url_sha256
            )
        )
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS parser_batch_checkpoints (
            run_id VARCHAR NOT NULL,
            batch_number BIGINT NOT NULL,
            first_athlete_id BIGINT,
            last_athlete_id BIGINT,
            athlete_count BIGINT NOT NULL,
            succeeded_count BIGINT NOT NULL,
            failed_count BIGINT NOT NULL,
            section_count BIGINT NOT NULL,
            url_key_count BIGINT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ NOT NULL,
            elapsed_seconds DOUBLE NOT NULL,
            PRIMARY KEY (run_id, batch_number)
        )
        """
    )


def load_source_athletes(
    source_con: duckdb.DuckDBPyConnection,
    explicit_ids: list[int] | None,
) -> pd.DataFrame:
    if explicit_ids:
        placeholders = ", ".join(
            "?" for _ in explicit_ids
        )
        return source_con.execute(
            f"""
            SELECT
                athlete_id,
                athlete_name
            FROM core.athletes
            WHERE athlete_id IN ({placeholders})
            ORDER BY athlete_id
            """,
            explicit_ids,
        ).fetchdf()

    return source_con.execute(
        """
        SELECT
            athlete_id,
            athlete_name
        FROM core.athletes
        ORDER BY athlete_id
        """
    ).fetchdf()


def load_completed_ids(
    staging_con: duckdb.DuckDBPyConnection,
    retry_errors: bool,
) -> set[int]:
    if retry_errors:
        query = """
            SELECT athlete_id
            FROM profile_parse_status
            WHERE parse_status = 'OK'
        """
    else:
        query = """
            SELECT athlete_id
            FROM profile_parse_status
        """

    rows = staging_con.execute(query).fetchall()
    return {int(row[0]) for row in rows}


def load_candidate_context(
    source_con: duckdb.DuckDBPyConnection,
    athlete_ids: list[int],
) -> dict[int, dict[str, Any]]:
    placeholders = ", ".join(
        "?" for _ in athlete_ids
    )

    rows = source_con.execute(
        f"""
        SELECT DISTINCT
            af.athlete_id,
            s.school_name,
            t.team_id,
            t.gender_code
        FROM core.athlete_affiliations af
        JOIN core.teams t
          ON af.team_id = t.team_id
        LEFT JOIN core.schools s
          ON t.school_id = s.school_id
        WHERE af.athlete_id IN ({placeholders})
        ORDER BY
            af.athlete_id,
            s.school_name,
            t.team_id
        """,
        athlete_ids,
    ).fetchdf()

    context: dict[int, dict[str, Any]] = defaultdict(
        lambda: {
            "candidate_schools": [],
            "team_ids": [],
            "genders": [],
        }
    )

    for row in rows.to_dict("records"):
        athlete_id = int(row["athlete_id"])
        school = clean_text(row.get("school_name"))
        team_id = clean_text(row.get("team_id"))
        gender = clean_text(row.get("gender_code"))

        if (
            school
            and school
            not in context[athlete_id][
                "candidate_schools"
            ]
        ):
            context[athlete_id][
                "candidate_schools"
            ].append(school)

        if (
            team_id
            and team_id
            not in context[athlete_id]["team_ids"]
        ):
            context[athlete_id][
                "team_ids"
            ].append(team_id)

        if (
            gender
            and gender
            not in context[athlete_id]["genders"]
        ):
            context[athlete_id][
                "genders"
            ].append(gender)

    return context


def delete_batch_rows(
    con: duckdb.DuckDBPyConnection,
    athlete_ids: list[int],
) -> None:
    placeholders = ", ".join(
        "?" for _ in athlete_ids
    )

    con.execute(
        f"""
        DELETE FROM section_url_keys
        WHERE athlete_id IN ({placeholders})
        """,
        athlete_ids,
    )
    con.execute(
        f"""
        DELETE FROM profile_sections
        WHERE athlete_id IN ({placeholders})
        """,
        athlete_ids,
    )
    con.execute(
        f"""
        DELETE FROM profile_parse_status
        WHERE athlete_id IN ({placeholders})
        """,
        athlete_ids,
    )


def insert_dataframe(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
    frame: pd.DataFrame,
    view_name: str,
) -> None:
    if frame.empty:
        return

    con.register(view_name, frame)

    try:
        con.execute(
            f"""
            INSERT INTO {table_name}
            SELECT * FROM {view_name}
            """
        )
    finally:
        con.unregister(view_name)


def write_report(
    con: duckdb.DuckDBPyConnection,
) -> None:
    counts = con.execute(
        """
        SELECT
            COUNT(*) AS status_rows,
            COUNT(*) FILTER (
                WHERE parse_status = 'OK'
            ) AS ok_rows,
            COUNT(*) FILTER (
                WHERE parse_status <> 'OK'
            ) AS non_ok_rows,
            COUNT(*) FILTER (
                WHERE current_school_status
                    = 'NO_HEADER_SCHOOL_MATCH'
            ) AS unresolved_current_school_rows,
            SUM(section_count) AS reported_sections,
            SUM(url_key_count) AS reported_url_keys
        FROM profile_parse_status
        """
    ).fetchone()

    section_count = con.execute(
        "SELECT COUNT(*) FROM profile_sections"
    ).fetchone()[0]
    url_key_count = con.execute(
        "SELECT COUNT(*) FROM section_url_keys"
    ).fetchone()[0]
    duplicate_section_count = con.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT
                athlete_id,
                section_index,
                COUNT(*) AS row_count
            FROM profile_sections
            GROUP BY athlete_id, section_index
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    duplicate_url_key_count = con.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT
                athlete_id,
                section_index,
                url_sha256,
                COUNT(*) AS row_count
            FROM section_url_keys
            GROUP BY
                athlete_id,
                section_index,
                url_sha256
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]

    staging_size = (
        STAGING_DB_PATH.stat().st_size
        if STAGING_DB_PATH.exists()
        else 0
    )

    report = f"""MILESTONE 4 ALL-PROFILE PARSER STATUS
============================================================
Parser version: {PARSER_VERSION}
Source database modified: no
Raw files modified: no

STAGING DATABASE
- Path: {STAGING_DB_PATH}
- Size bytes: {staging_size:,}

PROFILE STATUS
- Recorded athlete profiles: {int(counts[0] or 0):,}
- Successful profiles: {int(counts[1] or 0):,}
- Non-OK profiles: {int(counts[2] or 0):,}
- Current-school header unresolved: {int(counts[3] or 0):,}

STAGED ROWS
- Profile sections: {int(section_count):,}
- Section URL keys: {int(url_key_count):,}
- Reported section total: {int(counts[4] or 0):,}
- Reported URL-key total: {int(counts[5] or 0):,}

STRUCTURAL CHECKS
- Duplicate athlete-section keys: {int(duplicate_section_count):,}
- Duplicate section URL keys: {int(duplicate_url_key_count):,}

RESUME
Rerun the same command to continue from the existing profile_parse_status
checkpoint. Use --retry-errors only after reviewing the non-OK profile audit.
"""

    REPORT_PATH.write_text(
        report,
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()

    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive.")

    if not SOURCE_DB_PATH.exists():
        raise FileNotFoundError(
            f"Source database not found: {SOURCE_DB_PATH}"
        )

    if args.reset and OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    source_con = duckdb.connect(
        str(SOURCE_DB_PATH),
        read_only=True,
    )
    staging_con = duckdb.connect(
        str(STAGING_DB_PATH),
    )

    run_id = str(uuid.uuid4())
    run_started = utc_now()
    run_status = "RUNNING"

    total_attempted = 0
    total_succeeded = 0
    total_failed = 0
    total_sections = 0
    total_url_keys = 0

    try:
        initialize_staging(staging_con)

        source_athletes = load_source_athletes(
            source_con=source_con,
            explicit_ids=args.athlete_ids,
        )

        completed_ids = load_completed_ids(
            staging_con=staging_con,
            retry_errors=args.retry_errors,
        )

        pending = source_athletes.loc[
            ~source_athletes["athlete_id"].astype(
                "int64"
            ).isin(completed_ids)
        ].copy()

        if args.limit is not None:
            pending = pending.head(args.limit)

        staging_con.execute(
            """
            INSERT INTO parser_runs (
                run_id,
                parser_version,
                source_database,
                staging_database,
                started_at,
                requested_limit,
                batch_size,
                retry_errors,
                run_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                run_id,
                PARSER_VERSION,
                str(SOURCE_DB_PATH),
                str(STAGING_DB_PATH),
                run_started,
                args.limit,
                args.batch_size,
                args.retry_errors,
                run_status,
            ],
        )

        pending_count = len(pending)

        print("Milestone 4 all-profile parser")
        print(f"Pending athlete profiles: {pending_count:,}")
        print(f"Batch size: {args.batch_size:,}")
        print(f"Staging database: {STAGING_DB_PATH}")

        if pending_count == 0:
            run_status = "COMPLETE_NO_PENDING_ROWS"
            write_report(staging_con)
            print("No pending athlete profiles.")
            return

        batch_number = 0

        for start in range(
            0,
            pending_count,
            args.batch_size,
        ):
            batch_number += 1
            batch_started_monotonic = time.monotonic()
            batch_started_at = utc_now()

            batch = pending.iloc[
                start : start + args.batch_size
            ].copy()
            athlete_ids = [
                int(value)
                for value in batch["athlete_id"].tolist()
            ]
            athlete_names = {
                int(row["athlete_id"]): clean_text(
                    row.get("athlete_name")
                )
                for row in batch.to_dict("records")
            }

            context = load_candidate_context(
                source_con=source_con,
                athlete_ids=athlete_ids,
            )

            status_rows: list[dict[str, Any]] = []
            section_rows: list[dict[str, Any]] = []
            url_key_rows: list[dict[str, Any]] = []

            batch_succeeded = 0
            batch_failed = 0

            for athlete_id in athlete_ids:
                html_path = (
                    ATHLETE_PAGE_DIR
                    / f"{athlete_id}.html"
                )
                processed_at = utc_now()

                try:
                    if not html_path.exists():
                        raise FileNotFoundError(
                            f"HTML_NOT_FOUND: {html_path}"
                        )

                    html_bytes = html_path.read_bytes()
                    html_checksum = file_sha256(
                        html_bytes
                    )

                    parsed_sections, parsed_url_keys, audit = (
                        parse_profile(
                            athlete_id=athlete_id,
                            html_bytes=html_bytes,
                            candidate_schools=context.get(
                                athlete_id,
                                {},
                            ).get(
                                "candidate_schools",
                                [],
                            ),
                        )
                    )

                    parse_status = clean_text(
                        audit.get("parse_status")
                    )

                    if parse_status == "OK":
                        batch_succeeded += 1
                    else:
                        batch_failed += 1

                    for section in parsed_sections:
                        section_rows.append(
                            {
                                "profile_section_id": (
                                    stable_section_id(
                                        athlete_id=(
                                            section.athlete_id
                                        ),
                                        section_index=(
                                            section.section_index
                                        ),
                                        source_section_name=(
                                            section
                                            .source_section_name
                                        ),
                                    )
                                ),
                                "athlete_id": (
                                    section.athlete_id
                                ),
                                "section_index": (
                                    section.section_index
                                ),
                                "source_section_name": (
                                    section
                                    .source_section_name
                                ),
                                "normalized_section_name": (
                                    section
                                    .normalized_section_name
                                ),
                                "marker_text": (
                                    section.marker_text
                                ),
                                "attribution_method": (
                                    section
                                    .attribution_method
                                ),
                                "is_current_section": (
                                    section
                                    .is_current_section
                                ),
                                "source_html_sha256": (
                                    html_checksum
                                ),
                                "parser_version": (
                                    PARSER_VERSION
                                ),
                                "last_run_id": run_id,
                            }
                        )

                    for link in parsed_url_keys:
                        url_key_rows.append(
                            {
                                "athlete_id": (
                                    link.athlete_id
                                ),
                                "section_index": (
                                    link.section_index
                                ),
                                "url_sha256": (
                                    link.url_sha256
                                ),
                                "url_kind": link.url_kind,
                                "parser_version": (
                                    PARSER_VERSION
                                ),
                                "last_run_id": run_id,
                            }
                        )

                    status_rows.append(
                        {
                            "athlete_id": athlete_id,
                            "athlete_name": athlete_names.get(
                                athlete_id,
                                "",
                            ),
                            "source_html_file": str(
                                html_path
                            ),
                            "source_html_sha256": (
                                html_checksum
                            ),
                            "source_file_size_bytes": len(
                                html_bytes
                            ),
                            "current_school": clean_text(
                                audit.get("current_school")
                            ),
                            "current_school_status": (
                                clean_text(
                                    audit.get("status")
                                )
                            ),
                            "header_line_index": (
                                audit.get(
                                    "header_line_index"
                                )
                            ),
                            "header_candidate_lines": (
                                clean_text(
                                    audit.get(
                                        "header_candidate_lines"
                                    )
                                )
                            ),
                            "parse_status": parse_status,
                            "section_count": len(
                                parsed_sections
                            ),
                            "url_key_count": len(
                                parsed_url_keys
                            ),
                            "error_type": "",
                            "error_message": "",
                            "parser_version": PARSER_VERSION,
                            "last_run_id": run_id,
                            "processed_at": processed_at,
                        }
                    )

                except Exception as exc:
                    batch_failed += 1

                    error_type = type(exc).__name__
                    error_message = clean_text(str(exc))

                    if "HTML_NOT_FOUND:" in error_message:
                        parse_status = "HTML_NOT_FOUND"
                    else:
                        parse_status = "ERROR"

                    status_rows.append(
                        {
                            "athlete_id": athlete_id,
                            "athlete_name": athlete_names.get(
                                athlete_id,
                                "",
                            ),
                            "source_html_file": str(
                                html_path
                            ),
                            "source_html_sha256": "",
                            "source_file_size_bytes": None,
                            "current_school": "",
                            "current_school_status": (
                                "NOT_AVAILABLE"
                            ),
                            "header_line_index": None,
                            "header_candidate_lines": "",
                            "parse_status": parse_status,
                            "section_count": 0,
                            "url_key_count": 0,
                            "error_type": error_type,
                            "error_message": (
                                error_message[:4000]
                            ),
                            "parser_version": PARSER_VERSION,
                            "last_run_id": run_id,
                            "processed_at": processed_at,
                        }
                    )

                    print(
                        f"Profile error {athlete_id}: "
                        f"{error_type}: {error_message}",
                        file=sys.stderr,
                    )

            status_frame = pd.DataFrame(
                status_rows,
                columns=[
                    "athlete_id",
                    "athlete_name",
                    "source_html_file",
                    "source_html_sha256",
                    "source_file_size_bytes",
                    "current_school",
                    "current_school_status",
                    "header_line_index",
                    "header_candidate_lines",
                    "parse_status",
                    "section_count",
                    "url_key_count",
                    "error_type",
                    "error_message",
                    "parser_version",
                    "last_run_id",
                    "processed_at",
                ],
            )
            section_frame = pd.DataFrame(
                section_rows,
                columns=[
                    "profile_section_id",
                    "athlete_id",
                    "section_index",
                    "source_section_name",
                    "normalized_section_name",
                    "marker_text",
                    "attribution_method",
                    "is_current_section",
                    "source_html_sha256",
                    "parser_version",
                    "last_run_id",
                ],
            )
            url_key_frame = pd.DataFrame(
                url_key_rows,
                columns=[
                    "athlete_id",
                    "section_index",
                    "url_sha256",
                    "url_kind",
                    "parser_version",
                    "last_run_id",
                ],
            )

            batch_completed_at = utc_now()
            elapsed = (
                time.monotonic()
                - batch_started_monotonic
            )

            staging_con.execute("BEGIN TRANSACTION")

            try:
                delete_batch_rows(
                    con=staging_con,
                    athlete_ids=athlete_ids,
                )

                insert_dataframe(
                    con=staging_con,
                    table_name="profile_parse_status",
                    frame=status_frame,
                    view_name="_status_batch",
                )
                insert_dataframe(
                    con=staging_con,
                    table_name="profile_sections",
                    frame=section_frame,
                    view_name="_section_batch",
                )
                insert_dataframe(
                    con=staging_con,
                    table_name="section_url_keys",
                    frame=url_key_frame,
                    view_name="_url_key_batch",
                )

                staging_con.execute(
                    """
                    INSERT INTO parser_batch_checkpoints (
                        run_id,
                        batch_number,
                        first_athlete_id,
                        last_athlete_id,
                        athlete_count,
                        succeeded_count,
                        failed_count,
                        section_count,
                        url_key_count,
                        started_at,
                        completed_at,
                        elapsed_seconds
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                    """,
                    [
                        run_id,
                        batch_number,
                        min(athlete_ids),
                        max(athlete_ids),
                        len(athlete_ids),
                        batch_succeeded,
                        batch_failed,
                        len(section_frame),
                        len(url_key_frame),
                        batch_started_at,
                        batch_completed_at,
                        elapsed,
                    ],
                )

                staging_con.execute(
                    "COMMIT"
                )

            except Exception:
                staging_con.execute(
                    "ROLLBACK"
                )
                raise

            total_attempted += len(athlete_ids)
            total_succeeded += batch_succeeded
            total_failed += batch_failed
            total_sections += len(section_frame)
            total_url_keys += len(url_key_frame)

            processed_through = min(
                start + len(batch),
                pending_count,
            )

            print(
                f"Batch {batch_number:,}: "
                f"{processed_through:,}/{pending_count:,} "
                f"profiles; "
                f"sections={len(section_frame):,}; "
                f"url_keys={len(url_key_frame):,}; "
                f"failed={batch_failed:,}; "
                f"elapsed={elapsed:.1f}s"
            )

            write_report(staging_con)

        run_status = "COMPLETE"

    except KeyboardInterrupt:
        run_status = "INTERRUPTED"
        print(
            "\nInterrupted. Completed batches remain "
            "checkpointed.",
            file=sys.stderr,
        )
        raise

    except Exception:
        run_status = "FAILED"
        print(
            traceback.format_exc(),
            file=sys.stderr,
        )
        raise

    finally:
        completed_at = utc_now()

        try:
            staging_con.execute(
                """
                UPDATE parser_runs
                SET
                    completed_at = ?,
                    run_status = ?,
                    athlete_rows_attempted = ?,
                    athlete_rows_succeeded = ?,
                    athlete_rows_failed = ?,
                    section_rows_written = ?,
                    url_key_rows_written = ?
                WHERE run_id = ?
                """,
                [
                    completed_at,
                    run_status,
                    total_attempted,
                    total_succeeded,
                    total_failed,
                    total_sections,
                    total_url_keys,
                    run_id,
                ],
            )
            write_report(staging_con)
        except Exception:
            pass

        source_con.close()
        staging_con.close()

    print("All requested athlete profiles processed.")
    print(f"Report: {REPORT_PATH}")
    print(f"Staging database: {STAGING_DB_PATH}")


if __name__ == "__main__":
    main()
