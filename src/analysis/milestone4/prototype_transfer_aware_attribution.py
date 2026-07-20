#!/usr/bin/env python3
"""
Milestone 4 transfer-aware performance attribution prototype v0.2.

This script is READ-ONLY with respect to the production DuckDB database and
all raw source files. It writes diagnostic CSVs only.

Prototype athletes
------------------
6093853  Noah Burton
6418102  Annamaria Kostarellis
6544920  Myles Anders

What it does
------------
1. Reads the saved TFRRS athlete HTML.
2. Uses only the #meet-results panel.
3. Starts with the athlete's current school from unique_athletes.csv.
4. Walks the panel in document order.
5. Changes the active school whenever it encounters:
       <div class="col-lg-12 transfer">
           <span>↓Competing for SCHOOL ↓</span>
       </div>
6. Assigns links beneath each section to the active school.
7. Matches those links against core.performances.result_url and meet_url.
8. Maps section school names to historical roster team IDs.
9. Produces coverage, disagreement, ambiguity, and unresolved audits.

It does NOT update core.performances and does NOT create database tables.

Run from the repository root:
    python src/analysis/milestone4/prototype_transfer_aware_attribution.py

Optional custom athlete IDs:
    python src/analysis/milestone4/prototype_transfer_aware_attribution.py \
        6093853 6418102 6544920
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

import duckdb
import pandas as pd
from bs4 import BeautifulSoup, Tag


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "data/database/ncaa_track_analytics.duckdb"

ATHLETE_PAGE_DIR = PROJECT_ROOT / "data/raw/athlete_pages"
UNIQUE_ATHLETES_PATH = PROJECT_ROOT / "data/raw/unique_athletes.csv"
ALL_ROSTER_RECORDS_PATH = PROJECT_ROOT / "data/raw/all_roster_records.csv"

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/prototype_transfer_attribution"
)

TFRRS_BASE_URL = "https://www.tfrrs.org/"
DEFAULT_ATHLETE_IDS = [6093853, 6418102, 6544920]

WHITESPACE_RE = re.compile(r"\s+")
TRANSFER_RE = re.compile(
    r"Competing\s+for\s+(.+?)(?:\s*[↓▼]+\s*)?$",
    re.IGNORECASE,
)
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class SchoolSection:
    athlete_id: int
    section_index: int
    school_name_raw: str
    school_name_clean: str
    marker_text: str
    attribution_method: str


@dataclass(frozen=True)
class SectionLink:
    athlete_id: int
    section_index: int
    school_name: str
    href_raw: str
    href_normalized: str
    anchor_text: str


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return WHITESPACE_RE.sub(" ", str(value)).strip()


def normalize_school_name(value: object) -> str:
    text = clean_text(value).lower()
    text = text.replace("&amp;", "and")
    text = text.replace("&", "and")
    text = NON_ALNUM_RE.sub("", text)
    return text


def clean_transfer_school(marker_text: str) -> str:
    text = clean_text(marker_text)
    match = TRANSFER_RE.search(text)
    if not match:
        return text.strip("↓▼ ").strip()
    return clean_text(match.group(1)).strip("↓▼ ").strip()


def extract_profile_current_school(
    athlete_id: int,
    roster_mapping: dict[int, dict[str, list[dict[str, str]]]],
) -> dict[str, object]:
    """
    Extract the current school from the visible profile header.

    TFRRS renders the profile header before "College Bests" and the
    #meet-results panel. The current school appears as a standalone line,
    followed by optional "* previously at ..." lines.

    Candidate schools are limited to schools already observed for the athlete
    in the historical roster records. This prevents unrelated page text from
    being treated as a school.
    """
    page_path = ATHLETE_PAGE_DIR / f"{athlete_id}.html"
    if not page_path.exists():
        return {
            "profile_current_school": "",
            "profile_current_school_status": "HTML_NOT_FOUND",
            "header_line_index": None,
            "header_candidate_lines": "",
        }

    html = page_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    candidate_map: dict[str, str] = {}
    for normalized, rows in roster_mapping.get(athlete_id, {}).items():
        for row in rows:
            school = clean_text(row.get("school"))
            if school and normalized not in candidate_map:
                candidate_map[normalized] = school

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
            "profile_current_school": "",
            "profile_current_school_status": "NO_HEADER_SCHOOL_MATCH",
            "header_line_index": None,
            "header_candidate_lines": " | ".join(lines[:40]),
        }

    # The first standalone roster-school match in the profile header is the
    # current school.
    index, canonical_school, raw_line = matches[0]

    status = "UNIQUE_HEADER_SCHOOL_MATCH"
    if len({normalize_school_name(item[1]) for item in matches}) > 1:
        status = "FIRST_OF_MULTIPLE_HEADER_SCHOOL_MATCHES"

    return {
        "profile_current_school": canonical_school,
        "profile_current_school_status": status,
        "header_line_index": index,
        "header_candidate_lines": " | ".join(
            f"{item[0]}:{item[2]}" for item in matches
        ),
    }


def normalize_url(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""

    absolute = urljoin(TFRRS_BASE_URL, text)
    split = urlsplit(absolute)

    # Strip fragments and normalize trailing slash while preserving query text.
    path = split.path.rstrip("/") or "/"
    normalized = urlunsplit(
        (
            split.scheme.lower(),
            split.netloc.lower(),
            path,
            split.query,
            "",
        )
    )
    return normalized


def write_csv(
    path: Path,
    header: Iterable[str],
    rows: Iterable[Iterable[object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def read_filtered_csv(
    path: Path,
    athlete_ids: set[int],
) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")

    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        path,
        dtype=str,
        chunksize=250_000,
        keep_default_na=False,
    ):
        if "athlete_id" not in chunk.columns:
            raise ValueError(f"athlete_id column not found in {path}")
        athlete_numeric = pd.to_numeric(
            chunk["athlete_id"],
            errors="coerce",
        )
        matched = chunk[athlete_numeric.isin(athlete_ids)].copy()
        if not matched.empty:
            matched["athlete_id"] = pd.to_numeric(
                matched["athlete_id"],
                errors="raise",
            ).astype("int64")
            chunks.append(matched)

    if not chunks:
        return pd.DataFrame()

    return pd.concat(chunks, ignore_index=True)


def current_school_lookup(
    unique_athletes: pd.DataFrame,
) -> dict[int, dict[str, str]]:
    lookup: dict[int, dict[str, str]] = {}
    for row in unique_athletes.to_dict("records"):
        athlete_id = int(row["athlete_id"])
        lookup[athlete_id] = {
            "athlete_name": clean_text(row.get("athlete_name")),
            "school": clean_text(row.get("school")),
            "team_id": clean_text(row.get("team_id")),
            "athlete_url": clean_text(row.get("athlete_url")),
        }
    return lookup


def roster_school_mapping(
    roster_rows: pd.DataFrame,
) -> dict[int, dict[str, list[dict[str, str]]]]:
    mapping: dict[int, dict[str, list[dict[str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    if roster_rows.empty:
        return mapping

    for row in roster_rows.to_dict("records"):
        athlete_id = int(row["athlete_id"])
        school = clean_text(row.get("school"))
        normalized = normalize_school_name(school)

        mapping[athlete_id][normalized].append(
            {
                "school": school,
                "team_id": clean_text(row.get("team_id")),
                "season": clean_text(row.get("season")),
                "year": clean_text(row.get("year")),
                "config_hnd": clean_text(row.get("config_hnd")),
            }
        )

    return mapping


def is_transfer_marker(tag: Tag) -> bool:
    classes = set(tag.get("class", []))
    text = clean_text(tag.get_text(" ", strip=True))

    return (
        tag.name == "div"
        and "transfer" in classes
        and bool(TRANSFER_RE.search(text))
    )


def parse_profile_sections(
    athlete_id: int,
    current_school: str,
) -> tuple[list[SchoolSection], list[SectionLink], str]:
    page_path = ATHLETE_PAGE_DIR / f"{athlete_id}.html"
    if not page_path.exists():
        return [], [], "HTML_NOT_FOUND"

    html = page_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    panel = soup.find(id="meet-results")

    if not isinstance(panel, Tag):
        return [], [], "MEET_RESULTS_PANEL_NOT_FOUND"

    sections: list[SchoolSection] = [
        SchoolSection(
            athlete_id=athlete_id,
            section_index=0,
            school_name_raw=current_school,
            school_name_clean=current_school,
            marker_text="",
            attribution_method="PROFILE_CURRENT_SCHOOL",
        )
    ]
    links: list[SectionLink] = []

    active_section_index = 0
    active_school = current_school
    seen_links: set[tuple[int, str]] = set()

    def walk(node: Tag) -> None:
        nonlocal active_section_index, active_school

        for child in node.children:
            if not isinstance(child, Tag):
                continue

            if is_transfer_marker(child):
                marker_text = clean_text(child.get_text(" ", strip=True))
                active_school = clean_transfer_school(marker_text)
                active_section_index += 1

                sections.append(
                    SchoolSection(
                        athlete_id=athlete_id,
                        section_index=active_section_index,
                        school_name_raw=marker_text,
                        school_name_clean=active_school,
                        marker_text=marker_text,
                        attribution_method="PROFILE_TRANSFER_MARKER",
                    )
                )

                # Do not recurse into the marker itself.
                continue

            if child.name == "a" and child.get("href"):
                href_raw = clean_text(child.get("href"))
                href_normalized = normalize_url(href_raw)
                key = (active_section_index, href_normalized)

                if href_normalized and key not in seen_links:
                    seen_links.add(key)
                    links.append(
                        SectionLink(
                            athlete_id=athlete_id,
                            section_index=active_section_index,
                            school_name=active_school,
                            href_raw=href_raw,
                            href_normalized=href_normalized,
                            anchor_text=clean_text(
                                child.get_text(" ", strip=True)
                            ),
                        )
                    )

            walk(child)

    walk(panel)
    return sections, links, "OK"


def resolve_section_team(
    athlete_id: int,
    school_name: str,
    current_lookup: dict[int, dict[str, str]],
    roster_mapping: dict[int, dict[str, list[dict[str, str]]]],
) -> dict[str, object]:
    normalized = normalize_school_name(school_name)
    candidates = roster_mapping.get(athlete_id, {}).get(normalized, [])

    unique_team_ids = sorted(
        {
            clean_text(candidate.get("team_id"))
            for candidate in candidates
            if clean_text(candidate.get("team_id"))
        }
    )

    if len(unique_team_ids) == 1:
        status = "UNIQUE_TEAM_MATCH"
        resolved_team_id = unique_team_ids[0]
    elif len(unique_team_ids) == 0:
        status = "NO_TEAM_MATCH"
        resolved_team_id = ""
    else:
        status = "MULTIPLE_TEAM_MATCHES"
        resolved_team_id = ""

    return {
        "athlete_id": athlete_id,
        "school_name": school_name,
        "normalized_school_name": normalized,
        "resolved_team_id": resolved_team_id,
        "team_match_status": status,
        "candidate_team_ids": " | ".join(unique_team_ids),
        "roster_evidence_rows": len(candidates),
        "roster_seasons": " | ".join(
            sorted(
                {
                    clean_text(candidate.get("season"))
                    for candidate in candidates
                    if clean_text(candidate.get("season"))
                }
            )
        ),
    }


def load_core_performances(
    con: duckdb.DuckDBPyConnection,
    athlete_ids: list[int],
) -> pd.DataFrame:
    placeholders = ", ".join("?" for _ in athlete_ids)
    query = f"""
        SELECT
            p.performance_id,
            p.athlete_id,
            p.season_id,
            p.season_year,
            p.season_type,
            p.meet_id,
            p.meet_name,
            p.event,
            p.mark,
            p.secondary_mark,
            p.wind,
            p.place,
            p.competition_round,
            p.team_id AS original_team_id,
            t.school_id AS original_school_id,
            s.school_name AS original_school_name,
            p.affiliation_id,
            p.result_url,
            p.meet_url,
            p.source_file
        FROM core.performances p
        LEFT JOIN core.teams t
          ON p.team_id = t.team_id
        LEFT JOIN core.schools s
          ON t.school_id = s.school_id
        WHERE p.athlete_id IN ({placeholders})
        ORDER BY p.athlete_id, p.performance_id
    """
    dataframe = con.execute(query, athlete_ids).fetchdf()

    dataframe["normalized_result_url"] = dataframe["result_url"].map(
        normalize_url
    )
    dataframe["normalized_meet_url"] = dataframe["meet_url"].map(
        normalize_url
    )
    return dataframe


def build_link_section_index(
    links: list[SectionLink],
) -> dict[tuple[int, str], list[SectionLink]]:
    index: dict[tuple[int, str], list[SectionLink]] = defaultdict(list)
    for link in links:
        index[(link.athlete_id, link.href_normalized)].append(link)
    return index


def choose_section_match(
    athlete_id: int,
    result_url: str,
    meet_url: str,
    link_index: dict[tuple[int, str], list[SectionLink]],
) -> tuple[str, list[SectionLink]]:
    result_matches = (
        link_index.get((athlete_id, result_url), [])
        if result_url
        else []
    )
    meet_matches = (
        link_index.get((athlete_id, meet_url), [])
        if meet_url
        else []
    )

    if result_matches:
        unique_sections = {
            (item.section_index, item.school_name)
            for item in result_matches
        }
        if len(unique_sections) == 1:
            return "RESULT_URL_MATCH", result_matches
        return "AMBIGUOUS_RESULT_URL_MATCH", result_matches

    if meet_matches:
        unique_sections = {
            (item.section_index, item.school_name)
            for item in meet_matches
        }
        if len(unique_sections) == 1:
            return "MEET_URL_MATCH", meet_matches
        return "AMBIGUOUS_MEET_URL_MATCH", meet_matches

    return "NO_URL_MATCH", []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "athlete_ids",
        nargs="*",
        type=int,
        default=DEFAULT_ATHLETE_IDS,
        help="TFRRS athlete IDs to process.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    athlete_ids = args.athlete_ids or DEFAULT_ATHLETE_IDS
    athlete_id_set = set(athlete_ids)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    unique_rows = read_filtered_csv(
        UNIQUE_ATHLETES_PATH,
        athlete_id_set,
    )
    roster_rows = read_filtered_csv(
        ALL_ROSTER_RECORDS_PATH,
        athlete_id_set,
    )

    current_lookup = current_school_lookup(unique_rows)
    roster_mapping = roster_school_mapping(roster_rows)

    all_sections: list[SchoolSection] = []
    all_links: list[SectionLink] = []
    page_status_rows: list[tuple] = []

    header_audit_rows: list[dict[str, object]] = []

    for athlete_id in athlete_ids:
        current = current_lookup.get(athlete_id, {})
        header = extract_profile_current_school(
            athlete_id=athlete_id,
            roster_mapping=roster_mapping,
        )

        profile_current_school = clean_text(
            header.get("profile_current_school")
        )
        unique_file_school = clean_text(current.get("school"))

        if not profile_current_school:
            page_status_rows.append(
                (
                    athlete_id,
                    clean_text(current.get("athlete_name")),
                    unique_file_school,
                    "",
                    clean_text(
                        header.get("profile_current_school_status")
                    ),
                    "CURRENT_SCHOOL_NOT_FOUND",
                    0,
                    0,
                )
            )
            header_audit_rows.append(
                {
                    "athlete_id": athlete_id,
                    "athlete_name": clean_text(
                        current.get("athlete_name")
                    ),
                    "profile_current_school": "",
                    "unique_athletes_school": unique_file_school,
                    "school_comparison_status": "PROFILE_UNRESOLVED",
                    **header,
                }
            )
            continue

        sections, links, status = parse_profile_sections(
            athlete_id=athlete_id,
            current_school=profile_current_school,
        )
        all_sections.extend(sections)
        all_links.extend(links)

        if (
            normalize_school_name(profile_current_school)
            == normalize_school_name(unique_file_school)
        ):
            comparison = "PROFILE_MATCHES_UNIQUE_ATHLETES"
        else:
            comparison = "PROFILE_DISAGREES_WITH_UNIQUE_ATHLETES"

        header_audit_rows.append(
            {
                "athlete_id": athlete_id,
                "athlete_name": clean_text(
                    current.get("athlete_name")
                ),
                "profile_current_school": profile_current_school,
                "unique_athletes_school": unique_file_school,
                "school_comparison_status": comparison,
                **header,
            }
        )

        page_status_rows.append(
            (
                athlete_id,
                clean_text(current.get("athlete_name")),
                unique_file_school,
                profile_current_school,
                clean_text(
                    header.get("profile_current_school_status")
                ),
                status,
                len(sections),
                len(links),
            )
        )

    write_csv(
        OUTPUT_DIR / "profile_parse_status.csv",
        [
            "athlete_id",
            "athlete_name",
            "unique_athletes_school",
            "profile_current_school",
            "profile_current_school_status",
            "profile_parse_status",
            "section_count",
            "unique_section_link_count",
        ],
        page_status_rows,
    )

    pd.DataFrame(header_audit_rows).to_csv(
        OUTPUT_DIR / "profile_current_school_audit.csv",
        index=False,
    )

    write_csv(
        OUTPUT_DIR / "school_sections.csv",
        [
            "athlete_id",
            "section_index",
            "school_name_raw",
            "school_name_clean",
            "marker_text",
            "attribution_method",
        ],
        [
            (
                section.athlete_id,
                section.section_index,
                section.school_name_raw,
                section.school_name_clean,
                section.marker_text,
                section.attribution_method,
            )
            for section in all_sections
        ],
    )

    write_csv(
        OUTPUT_DIR / "section_links.csv",
        [
            "athlete_id",
            "section_index",
            "school_name",
            "href_raw",
            "href_normalized",
            "anchor_text",
        ],
        [
            (
                link.athlete_id,
                link.section_index,
                link.school_name,
                link.href_raw,
                link.href_normalized,
                link.anchor_text,
            )
            for link in all_links
        ],
    )

    mapping_rows: list[dict[str, object]] = []
    mapping_by_section: dict[tuple[int, int], dict[str, object]] = {}

    for section in all_sections:
        mapping = resolve_section_team(
            athlete_id=section.athlete_id,
            school_name=section.school_name_clean,
            current_lookup=current_lookup,
            roster_mapping=roster_mapping,
        )
        mapping["section_index"] = section.section_index
        mapping["attribution_method"] = section.attribution_method
        mapping_by_section[
            (section.athlete_id, section.section_index)
        ] = mapping
        mapping_rows.append(mapping)

    mapping_columns = [
        "athlete_id",
        "section_index",
        "school_name",
        "normalized_school_name",
        "resolved_team_id",
        "team_match_status",
        "candidate_team_ids",
        "roster_evidence_rows",
        "roster_seasons",
        "attribution_method",
    ]
    pd.DataFrame(mapping_rows, columns=mapping_columns).to_csv(
        OUTPUT_DIR / "section_team_mapping.csv",
        index=False,
    )

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        performances = load_core_performances(con, athlete_ids)
    finally:
        con.close()

    link_index = build_link_section_index(all_links)
    attribution_rows: list[dict[str, object]] = []

    for row in performances.to_dict("records"):
        athlete_id = int(row["athlete_id"])
        match_status, matches = choose_section_match(
            athlete_id=athlete_id,
            result_url=clean_text(row["normalized_result_url"]),
            meet_url=clean_text(row["normalized_meet_url"]),
            link_index=link_index,
        )

        unique_sections = sorted(
            {
                (item.section_index, item.school_name)
                for item in matches
            }
        )

        if len(unique_sections) == 1:
            section_index, parsed_school_name = unique_sections[0]
            mapping = mapping_by_section.get(
                (athlete_id, section_index),
                {},
            )
            analytical_team_id = clean_text(
                mapping.get("resolved_team_id")
            )
            team_match_status = clean_text(
                mapping.get("team_match_status")
            )
        else:
            section_index = None
            parsed_school_name = ""
            analytical_team_id = ""
            team_match_status = ""

        original_team_id = clean_text(row.get("original_team_id"))
        if not analytical_team_id:
            comparison_status = "ANALYTICAL_TEAM_UNRESOLVED"
        elif analytical_team_id == original_team_id:
            comparison_status = "ORIGINAL_TEAM_MATCH"
        else:
            comparison_status = "ORIGINAL_TEAM_DISAGREEMENT"

        attribution_rows.append(
            {
                **row,
                "profile_match_status": match_status,
                "matched_section_count": len(unique_sections),
                "profile_section_index": section_index,
                "parsed_school_name": parsed_school_name,
                "analytical_team_id": analytical_team_id,
                "section_team_match_status": team_match_status,
                "comparison_status": comparison_status,
                "attribution_version": "prototype_v0.2",
            }
        )

    attribution = pd.DataFrame(attribution_rows)
    attribution.to_csv(
        OUTPUT_DIR / "prototype_performance_attribution.csv",
        index=False,
    )

    coverage = (
        attribution.groupby(
            [
                "athlete_id",
                "profile_match_status",
                "comparison_status",
            ],
            dropna=False,
        )
        .agg(
            performance_count=("performance_id", "count"),
            distinct_meets=("meet_id", "nunique"),
            distinct_seasons=("season_id", "nunique"),
        )
        .reset_index()
        .sort_values(
            [
                "athlete_id",
                "profile_match_status",
                "comparison_status",
            ]
        )
    )
    coverage.to_csv(
        OUTPUT_DIR / "prototype_match_audit.csv",
        index=False,
    )

    school_summary = (
        attribution.groupby(
            [
                "athlete_id",
                "parsed_school_name",
                "analytical_team_id",
                "comparison_status",
            ],
            dropna=False,
        )
        .agg(
            performance_count=("performance_id", "count"),
            first_season_year=("season_year", "min"),
            last_season_year=("season_year", "max"),
            distinct_seasons=("season_id", "nunique"),
            distinct_meets=("meet_id", "nunique"),
        )
        .reset_index()
        .sort_values(
            [
                "athlete_id",
                "first_season_year",
                "parsed_school_name",
            ]
        )
    )
    school_summary.to_csv(
        OUTPUT_DIR / "prototype_school_history_summary.csv",
        index=False,
    )

    total_performances = len(attribution)
    matched_performances = int(
        attribution["profile_match_status"].isin(
            ["RESULT_URL_MATCH", "MEET_URL_MATCH"]
        ).sum()
    )
    disagreements = int(
        (attribution["comparison_status"] == "ORIGINAL_TEAM_DISAGREEMENT").sum()
    )
    unresolved = int(
        (attribution["comparison_status"] == "ANALYTICAL_TEAM_UNRESOLVED").sum()
    )

    summary = f"""MILESTONE 4 TRANSFER-AWARE ATTRIBUTION PROTOTYPE
=================================================
Database connection: read-only
Raw files modified: no
Database objects created or modified: no

ATHLETES
{", ".join(str(value) for value in athlete_ids)}

COUNTS
- Core performances inspected: {total_performances:,}
- Performances matched to one profile section: {matched_performances:,}
- Original/analytical team disagreements: {disagreements:,}
- Analytical team unresolved: {unresolved:,}

OUTPUTS
- profile_parse_status.csv
- profile_current_school_audit.csv
- school_sections.csv
- section_links.csv
- section_team_mapping.csv
- prototype_performance_attribution.csv
- prototype_match_audit.csv
- prototype_school_history_summary.csv

INTERPRETATION
A team disagreement is expected for historical transfer performances because
Milestone 2 assigned one unique-athlete team across the full profile. The
prototype is successful only if:
1. profile-section coverage is high;
2. school sections match the manually verified histories;
3. the current school is extracted from the profile header;
4. current-school results remain matches;
5. historical-school results become explainable disagreements;
6. section school names map uniquely to roster team IDs.
"""
    (OUTPUT_DIR / "prototype_summary.txt").write_text(
        summary,
        encoding="utf-8",
    )

    print("Transfer-aware attribution prototype complete.")
    print(f"Outputs: {OUTPUT_DIR}")
    print("No raw files or database objects were modified.")


if __name__ == "__main__":
    main()
