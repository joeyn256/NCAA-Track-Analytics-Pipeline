#!/usr/bin/env python3
"""
Milestone 4 full transfer-aware performance-attribution pass.

READ-ONLY GUARANTEE
-------------------
This script does not modify:
- the Milestone 3 DuckDB database;
- raw athlete HTML;
- raw roster CSVs.

It writes derived CSV and text reports under:

    data/processed/milestone4/transfer_attribution_full/

PURPOSE
-------
Milestone 2 assigned one team from unique_athletes.csv to every historical
performance on an athlete profile. TFRRS preserves one athlete_id across
verified transfers and labels historical sections with:

    <div class="col-lg-12 transfer">
        <span>↓Competing for SCHOOL ↓</span>
    </div>

This script reconstructs historical performance teams for every athlete whose
roster-derived affiliations include more than one school.

METHOD
------
1. Select multi-school athlete IDs from core.athlete_affiliations.
2. Extract current school from the saved TFRRS profile header.
3. Parse only the #meet-results panel.
4. Walk the panel in document order.
5. Change active school at each transfer marker.
6. Assign each result/meet link to the active school section.
7. Resolve section school names to team IDs using historical roster evidence,
   with a same-gender core-team fallback.
8. Match profile sections to core.performances by result_url, then meet_url.
9. Preserve original and reconstructed team/school fields.
10. Produce full coverage, disagreement, and unresolved audits.

USAGE
-----
From the repository root:

    python src/analysis/milestone4/build_transfer_attribution_full.py

Optional test limit:

    python src/analysis/milestone4/build_transfer_attribution_full.py --limit 50

Optional explicit athlete IDs:

    python src/analysis/milestone4/build_transfer_attribution_full.py \
        --athlete-ids 6093853 6418102 6544920
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
    / "data/processed/milestone4/transfer_attribution_full"
)

TFRRS_BASE_URL = "https://www.tfrrs.org/"
ATTRIBUTION_VERSION = "m4_transfer_attribution_v1.0"

WHITESPACE_RE = re.compile(r"\s+")
TRANSFER_RE = re.compile(
    r"Competing\s+for\s+(.+?)(?:\s*[↓▼]+\s*)?$",
    re.IGNORECASE,
)
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

MANUAL_FIXTURES = {
    6093853: ["Texas Tech", "Minnesota", "Michigan State"],
    6418102: ["Baylor", "New Mexico", "Xavier (Ohio)"],
    6544920: ["Kentucky", "Texas State", "Louisiana Tech"],
}


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

        if matched.empty:
            continue

        matched["athlete_id"] = pd.to_numeric(
            matched["athlete_id"],
            errors="raise",
        ).astype("int64")
        chunks.append(matched)

    if not chunks:
        return pd.DataFrame()

    return pd.concat(chunks, ignore_index=True)


def current_unique_lookup(
    unique_athletes: pd.DataFrame,
) -> dict[int, dict[str, str]]:
    lookup: dict[int, dict[str, str]] = {}

    if unique_athletes.empty:
        return lookup

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


def extract_profile_current_school(
    athlete_id: int,
    roster_mapping: dict[int, dict[str, list[dict[str, str]]]],
) -> dict[str, object]:
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

        if "previously at" in lowered or "competing for" in lowered:
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

    index, canonical_school, _raw_line = matches[0]

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

    initial_school = current_school or "[UNRESOLVED CURRENT SCHOOL]"

    sections: list[SchoolSection] = [
        SchoolSection(
            athlete_id=athlete_id,
            section_index=0,
            school_name_raw=initial_school,
            school_name_clean=initial_school,
            marker_text="",
            attribution_method="PROFILE_CURRENT_SCHOOL",
        )
    ]
    links: list[SectionLink] = []

    active_section_index = 0
    active_school = initial_school
    seen_links: set[tuple[int, str]] = set()

    def walk(node: Tag) -> None:
        nonlocal active_section_index, active_school

        for child in node.children:
            if not isinstance(child, Tag):
                continue

            if is_transfer_marker(child):
                marker_text = clean_text(
                    child.get_text(" ", strip=True)
                )
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


def build_core_team_maps(
    con: duckdb.DuckDBPyConnection,
) -> tuple[
    dict[str, dict[str, object]],
    dict[tuple[str, str], list[str]],
]:
    dataframe = con.execute(
        """
        SELECT
            t.team_id,
            t.school_id,
            s.school_name,
            t.gender_code,
            t.division,
            t.sport
        FROM core.teams t
        LEFT JOIN core.schools s
          ON t.school_id = s.school_id
        """
    ).fetchdf()

    by_team: dict[str, dict[str, object]] = {}
    by_school_gender: dict[tuple[str, str], list[str]] = defaultdict(list)

    for row in dataframe.to_dict("records"):
        team_id = clean_text(row.get("team_id"))
        school_name = clean_text(row.get("school_name"))
        gender = clean_text(row.get("gender_code"))

        by_team[team_id] = {
            "team_id": team_id,
            "school_id": clean_text(row.get("school_id")),
            "school_name": school_name,
            "gender_code": gender,
            "division": clean_text(row.get("division")),
            "sport": clean_text(row.get("sport")),
        }

        key = (normalize_school_name(school_name), gender)
        by_school_gender[key].append(team_id)

    return by_team, by_school_gender


def athlete_gender_lookup(
    con: duckdb.DuckDBPyConnection,
    athlete_ids: list[int],
) -> dict[int, str]:
    placeholders = ", ".join("?" for _ in athlete_ids)
    dataframe = con.execute(
        f"""
        SELECT
            p.athlete_id,
            MIN(t.gender_code) AS gender_code
        FROM core.performances p
        JOIN core.teams t
          ON p.team_id = t.team_id
        WHERE p.athlete_id IN ({placeholders})
        GROUP BY p.athlete_id
        """,
        athlete_ids,
    ).fetchdf()

    return {
        int(row["athlete_id"]): clean_text(row["gender_code"])
        for row in dataframe.to_dict("records")
    }


def resolve_section_team(
    athlete_id: int,
    school_name: str,
    athlete_gender: str,
    roster_mapping: dict[int, dict[str, list[dict[str, str]]]],
    core_by_school_gender: dict[tuple[str, str], list[str]],
) -> dict[str, object]:
    normalized = normalize_school_name(school_name)
    roster_candidates = roster_mapping.get(
        athlete_id,
        {},
    ).get(
        normalized,
        [],
    )

    roster_team_ids = sorted(
        {
            clean_text(candidate.get("team_id"))
            for candidate in roster_candidates
            if clean_text(candidate.get("team_id"))
        }
    )

    if len(roster_team_ids) == 1:
        return {
            "resolved_team_id": roster_team_ids[0],
            "team_match_status": "UNIQUE_ROSTER_TEAM_MATCH",
            "resolution_method": "ATHLETE_ROSTER_HISTORY",
            "candidate_team_ids": " | ".join(roster_team_ids),
            "roster_evidence_rows": len(roster_candidates),
            "roster_seasons": " | ".join(
                sorted(
                    {
                        clean_text(candidate.get("season"))
                        for candidate in roster_candidates
                        if clean_text(candidate.get("season"))
                    }
                )
            ),
        }

    if len(roster_team_ids) > 1:
        return {
            "resolved_team_id": "",
            "team_match_status": "MULTIPLE_ROSTER_TEAM_MATCHES",
            "resolution_method": "UNRESOLVED",
            "candidate_team_ids": " | ".join(roster_team_ids),
            "roster_evidence_rows": len(roster_candidates),
            "roster_seasons": " | ".join(
                sorted(
                    {
                        clean_text(candidate.get("season"))
                        for candidate in roster_candidates
                        if clean_text(candidate.get("season"))
                    }
                )
            ),
        }

    core_candidates = sorted(
        set(
            core_by_school_gender.get(
                (normalized, athlete_gender),
                [],
            )
        )
    )

    if len(core_candidates) == 1:
        return {
            "resolved_team_id": core_candidates[0],
            "team_match_status": "UNIQUE_CORE_SCHOOL_GENDER_MATCH",
            "resolution_method": "CORE_SCHOOL_GENDER_FALLBACK",
            "candidate_team_ids": " | ".join(core_candidates),
            "roster_evidence_rows": 0,
            "roster_seasons": "",
        }

    status = "NO_TEAM_MATCH"
    if len(core_candidates) > 1:
        status = "MULTIPLE_CORE_SCHOOL_GENDER_MATCHES"

    return {
        "resolved_team_id": "",
        "team_match_status": status,
        "resolution_method": "UNRESOLVED",
        "candidate_team_ids": " | ".join(core_candidates),
        "roster_evidence_rows": 0,
        "roster_seasons": "",
    }


def load_candidate_athletes(
    con: duckdb.DuckDBPyConnection,
    limit: int | None,
    explicit_ids: list[int] | None,
) -> pd.DataFrame:
    affiliation_cte = """
        WITH affiliation_summary AS (
            SELECT
                a.athlete_id,
                COUNT(*) AS affiliation_rows,
                COUNT(DISTINCT t.school_id)
                    AS roster_distinct_schools,
                COUNT(DISTINCT a.season_id)
                    AS roster_season_count
            FROM core.athlete_affiliations a
            JOIN core.teams t
              ON a.team_id = t.team_id
            GROUP BY a.athlete_id
        ),
        performance_summary AS (
            SELECT
                athlete_id,
                COUNT(*) AS performance_count
            FROM core.performances
            GROUP BY athlete_id
        )
    """

    if explicit_ids:
        placeholders = ", ".join("?" for _ in explicit_ids)
        return con.execute(
            affiliation_cte
            + f"""
            SELECT
                a.athlete_id,
                a.affiliation_rows,
                a.roster_distinct_schools,
                a.roster_season_count,
                COALESCE(p.performance_count, 0)
                    AS performance_count
            FROM affiliation_summary a
            LEFT JOIN performance_summary p
              ON a.athlete_id = p.athlete_id
            WHERE a.athlete_id IN ({placeholders})
            ORDER BY a.athlete_id
            """,
            explicit_ids,
        ).fetchdf()

    limit_sql = f"LIMIT {int(limit)}" if limit else ""

    return con.execute(
        affiliation_cte
        + f"""
        SELECT
            a.athlete_id,
            a.affiliation_rows,
            a.roster_distinct_schools,
            a.roster_season_count,
            COALESCE(p.performance_count, 0)
                AS performance_count
        FROM affiliation_summary a
        LEFT JOIN performance_summary p
          ON a.athlete_id = p.athlete_id
        WHERE a.roster_distinct_schools > 1
        ORDER BY
            a.roster_distinct_schools DESC,
            a.affiliation_rows DESC,
            a.athlete_id
        {limit_sql}
        """
    ).fetchdf()


def load_core_performances(
    con: duckdb.DuckDBPyConnection,
    athlete_ids: list[int],
) -> pd.DataFrame:
    placeholders = ", ".join("?" for _ in athlete_ids)

    dataframe = con.execute(
        f"""
        SELECT
            p.performance_id,
            p.athlete_id,
            p.season_id,
            p.season_year,
            p.season_type,
            p.meet_id,
            p.meet_name,
            p.event_id,
            p.event,
            p.mark,
            p.secondary_mark,
            p.wind,
            p.place,
            p.competition_round,
            p.team_id AS original_team_id,
            t.school_id AS original_school_id,
            s.school_name AS original_school_name,
            t.gender_code,
            t.division,
            t.sport,
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
        """,
        athlete_ids,
    ).fetchdf()

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
        "--limit",
        type=int,
        default=None,
        help="Process only the first N multi-school athletes.",
    )
    parser.add_argument(
        "--athlete-ids",
        nargs="*",
        type=int,
        default=None,
        help="Process only these athlete IDs.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        candidates = load_candidate_athletes(
            con=con,
            limit=args.limit,
            explicit_ids=args.athlete_ids,
        )

        if candidates.empty:
            raise RuntimeError("No candidate athletes were selected.")

        athlete_ids = [
            int(value)
            for value in candidates["athlete_id"].tolist()
        ]
        athlete_id_set = set(athlete_ids)

        unique_rows = read_filtered_csv(
            UNIQUE_ATHLETES_PATH,
            athlete_id_set,
        )
        roster_rows = read_filtered_csv(
            ALL_ROSTER_RECORDS_PATH,
            athlete_id_set,
        )

        unique_lookup = current_unique_lookup(unique_rows)
        roster_mapping = roster_school_mapping(roster_rows)
        core_team_map, core_by_school_gender = build_core_team_maps(con)
        gender_lookup = athlete_gender_lookup(con, athlete_ids)

        candidates.to_csv(
            OUTPUT_DIR / "candidate_athletes.csv",
            index=False,
        )

        all_sections: list[SchoolSection] = []
        all_links: list[SectionLink] = []
        profile_audit_rows: list[dict[str, object]] = []

        total_candidates = len(athlete_ids)

        for position, athlete_id in enumerate(athlete_ids, start=1):
            unique = unique_lookup.get(athlete_id, {})
            header = extract_profile_current_school(
                athlete_id=athlete_id,
                roster_mapping=roster_mapping,
            )

            profile_current_school = clean_text(
                header.get("profile_current_school")
            )
            unique_school = clean_text(unique.get("school"))

            sections, links, parse_status = parse_profile_sections(
                athlete_id=athlete_id,
                current_school=profile_current_school,
            )

            all_sections.extend(sections)
            all_links.extend(links)

            if not profile_current_school:
                comparison = "PROFILE_CURRENT_SCHOOL_UNRESOLVED"
            elif (
                normalize_school_name(profile_current_school)
                == normalize_school_name(unique_school)
            ):
                comparison = "PROFILE_MATCHES_UNIQUE_ATHLETES"
            else:
                comparison = "PROFILE_DISAGREES_WITH_UNIQUE_ATHLETES"

            profile_audit_rows.append(
                {
                    "athlete_id": athlete_id,
                    "athlete_name": clean_text(
                        unique.get("athlete_name")
                    ),
                    "unique_athletes_school": unique_school,
                    "unique_athletes_team_id": clean_text(
                        unique.get("team_id")
                    ),
                    "profile_current_school": profile_current_school,
                    "school_comparison_status": comparison,
                    "profile_current_school_status": clean_text(
                        header.get("profile_current_school_status")
                    ),
                    "header_line_index": header.get(
                        "header_line_index"
                    ),
                    "header_candidate_lines": clean_text(
                        header.get("header_candidate_lines")
                    ),
                    "profile_parse_status": parse_status,
                    "section_count": len(sections),
                    "section_link_count": len(links),
                    "html_path": str(
                        ATHLETE_PAGE_DIR / f"{athlete_id}.html"
                    ),
                }
            )

            if position % 100 == 0 or position == total_candidates:
                print(
                    f"Parsed profiles: {position:,}/"
                    f"{total_candidates:,}"
                )

        profile_audit = pd.DataFrame(profile_audit_rows)
        profile_audit.to_csv(
            OUTPUT_DIR / "profile_parse_audit.csv",
            index=False,
        )

        section_rows: list[dict[str, object]] = []
        mapping_by_section: dict[
            tuple[int, int],
            dict[str, object],
        ] = {}

        for section in all_sections:
            athlete_gender = gender_lookup.get(section.athlete_id, "")

            mapping = resolve_section_team(
                athlete_id=section.athlete_id,
                school_name=section.school_name_clean,
                athlete_gender=athlete_gender,
                roster_mapping=roster_mapping,
                core_by_school_gender=core_by_school_gender,
            )

            resolved_team_id = clean_text(
                mapping.get("resolved_team_id")
            )
            core_team = core_team_map.get(resolved_team_id, {})

            section_row = {
                "athlete_id": section.athlete_id,
                "section_index": section.section_index,
                "school_name_raw": section.school_name_raw,
                "school_name_clean": section.school_name_clean,
                "normalized_school_name": normalize_school_name(
                    section.school_name_clean
                ),
                "marker_text": section.marker_text,
                "section_attribution_method": (
                    section.attribution_method
                ),
                "athlete_gender": athlete_gender,
                **mapping,
                "resolved_school_id": clean_text(
                    core_team.get("school_id")
                ),
                "resolved_school_name": clean_text(
                    core_team.get("school_name")
                ),
                "resolved_division": clean_text(
                    core_team.get("division")
                ),
                "resolved_sport": clean_text(
                    core_team.get("sport")
                ),
                "attribution_version": ATTRIBUTION_VERSION,
            }

            section_rows.append(section_row)
            mapping_by_section[
                (section.athlete_id, section.section_index)
            ] = section_row

        section_mapping = pd.DataFrame(section_rows)
        section_mapping.to_csv(
            OUTPUT_DIR / "school_section_mapping.csv",
            index=False,
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

        performances = load_core_performances(con, athlete_ids)
        link_index = build_link_section_index(all_links)

        attribution_rows: list[dict[str, object]] = []

        for row in performances.to_dict("records"):
            athlete_id = int(row["athlete_id"])

            match_status, matches = choose_section_match(
                athlete_id=athlete_id,
                result_url=clean_text(
                    row.get("normalized_result_url")
                ),
                meet_url=clean_text(
                    row.get("normalized_meet_url")
                ),
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
            else:
                section_index = None
                parsed_school_name = ""
                mapping = {}

            analytical_team_id = clean_text(
                mapping.get("resolved_team_id")
            )
            analytical_school_id = clean_text(
                mapping.get("resolved_school_id")
            )
            analytical_school_name = clean_text(
                mapping.get("resolved_school_name")
            )
            original_team_id = clean_text(
                row.get("original_team_id")
            )

            if not analytical_team_id:
                comparison_status = "ANALYTICAL_TEAM_UNRESOLVED"
            elif analytical_team_id == original_team_id:
                comparison_status = "ORIGINAL_TEAM_MATCH"
            else:
                comparison_status = "ORIGINAL_TEAM_DISAGREEMENT"

            if match_status == "RESULT_URL_MATCH":
                confidence = "HIGH"
                attribution_method = (
                    "PROFILE_RESULT_URL_SECTION"
                )
            elif match_status == "MEET_URL_MATCH":
                confidence = "MEDIUM"
                attribution_method = "PROFILE_MEET_URL_SECTION"
            else:
                confidence = "UNRESOLVED"
                attribution_method = "UNRESOLVED"

            attribution_rows.append(
                {
                    **row,
                    "profile_match_status": match_status,
                    "matched_section_count": len(unique_sections),
                    "profile_section_index": section_index,
                    "parsed_school_name": parsed_school_name,
                    "analytical_team_id": analytical_team_id,
                    "analytical_school_id": analytical_school_id,
                    "analytical_school_name": analytical_school_name,
                    "section_team_match_status": clean_text(
                        mapping.get("team_match_status")
                    ),
                    "team_resolution_method": clean_text(
                        mapping.get("resolution_method")
                    ),
                    "attribution_method": attribution_method,
                    "attribution_confidence": confidence,
                    "comparison_status": comparison_status,
                    "attribution_version": ATTRIBUTION_VERSION,
                }
            )

        attribution = pd.DataFrame(attribution_rows)
        attribution.to_csv(
            OUTPUT_DIR / "performance_attribution_candidates.csv",
            index=False,
        )

        overrides = attribution.loc[
            attribution["comparison_status"]
            == "ORIGINAL_TEAM_DISAGREEMENT"
        ].copy()
        overrides.to_csv(
            OUTPUT_DIR / "performance_attribution_overrides.csv",
            index=False,
        )

        unresolved = attribution.loc[
            (
                attribution["profile_match_status"].isin(
                    [
                        "NO_URL_MATCH",
                        "AMBIGUOUS_RESULT_URL_MATCH",
                        "AMBIGUOUS_MEET_URL_MATCH",
                    ]
                )
            )
            | (
                attribution["comparison_status"]
                == "ANALYTICAL_TEAM_UNRESOLVED"
            )
        ].copy()
        unresolved.to_csv(
            OUTPUT_DIR / "unresolved_performances.csv",
            index=False,
        )

        audit = (
            attribution.groupby(
                [
                    "profile_match_status",
                    "comparison_status",
                    "attribution_confidence",
                ],
                dropna=False,
            )
            .agg(
                performance_count=("performance_id", "count"),
                athlete_count=("athlete_id", "nunique"),
                meet_count=("meet_id", "nunique"),
                season_count=("season_id", "nunique"),
            )
            .reset_index()
            .sort_values(
                [
                    "profile_match_status",
                    "comparison_status",
                ]
            )
        )
        audit.to_csv(
            OUTPUT_DIR / "performance_attribution_audit.csv",
            index=False,
        )

        school_history = (
            attribution.loc[
                attribution["analytical_team_id"].fillna("") != ""
            ]
            .groupby(
                [
                    "athlete_id",
                    "analytical_school_id",
                    "analytical_school_name",
                    "analytical_team_id",
                ],
                dropna=False,
            )
            .agg(
                performance_count=("performance_id", "count"),
                first_season_year=("season_year", "min"),
                last_season_year=("season_year", "max"),
                distinct_seasons=("season_id", "nunique"),
                distinct_meets=("meet_id", "nunique"),
                original_team_match_count=(
                    "comparison_status",
                    lambda values: int(
                        (
                            values == "ORIGINAL_TEAM_MATCH"
                        ).sum()
                    ),
                ),
                original_team_disagreement_count=(
                    "comparison_status",
                    lambda values: int(
                        (
                            values
                            == "ORIGINAL_TEAM_DISAGREEMENT"
                        ).sum()
                    ),
                ),
            )
            .reset_index()
            .sort_values(
                [
                    "athlete_id",
                    "first_season_year",
                    "analytical_school_name",
                ]
            )
        )
        school_history.to_csv(
            OUTPUT_DIR / "athlete_school_history.csv",
            index=False,
        )

        fixture_rows: list[dict[str, object]] = []

        for athlete_id, expected_schools in MANUAL_FIXTURES.items():
            if athlete_id not in athlete_id_set:
                continue

            actual_schools = (
                section_mapping.loc[
                    section_mapping["athlete_id"] == athlete_id,
                    "school_name_clean",
                ]
                .astype(str)
                .tolist()
            )

            fixture_rows.append(
                {
                    "athlete_id": athlete_id,
                    "expected_school_sequence": " → ".join(
                        expected_schools
                    ),
                    "actual_school_sequence": " → ".join(
                        actual_schools
                    ),
                    "fixture_status": (
                        "PASS"
                        if [
                            normalize_school_name(value)
                            for value in actual_schools
                        ]
                        == [
                            normalize_school_name(value)
                            for value in expected_schools
                        ]
                        else "FAIL"
                    ),
                }
            )

        fixture_validation = pd.DataFrame(fixture_rows)
        fixture_validation.to_csv(
            OUTPUT_DIR / "manual_fixture_validation.csv",
            index=False,
        )

        hard_checks = [
            {
                "check_name": "candidate_athletes_selected",
                "failed_row_count": (
                    0 if len(candidates) > 0 else 1
                ),
                "observed_value": len(candidates),
            },
            {
                "check_name": "missing_html_profiles",
                "failed_row_count": int(
                    (
                        profile_audit["profile_parse_status"]
                        == "HTML_NOT_FOUND"
                    ).sum()
                ),
                "observed_value": int(
                    (
                        profile_audit["profile_parse_status"]
                        == "HTML_NOT_FOUND"
                    ).sum()
                ),
            },
            {
                "check_name": "missing_meet_results_panels",
                "failed_row_count": int(
                    (
                        profile_audit["profile_parse_status"]
                        == "MEET_RESULTS_PANEL_NOT_FOUND"
                    ).sum()
                ),
                "observed_value": int(
                    (
                        profile_audit["profile_parse_status"]
                        == "MEET_RESULTS_PANEL_NOT_FOUND"
                    ).sum()
                ),
            },
            {
                "check_name": "unresolved_profile_current_schools",
                "failed_row_count": int(
                    (
                        profile_audit[
                            "profile_current_school"
                        ].fillna("")
                        == ""
                    ).sum()
                ),
                "observed_value": int(
                    (
                        profile_audit[
                            "profile_current_school"
                        ].fillna("")
                        == ""
                    ).sum()
                ),
            },
            {
                "check_name": "unresolved_school_sections",
                "failed_row_count": int(
                    (
                        section_mapping[
                            "resolved_team_id"
                        ].fillna("")
                        == ""
                    ).sum()
                ),
                "observed_value": int(
                    (
                        section_mapping[
                            "resolved_team_id"
                        ].fillna("")
                        == ""
                    ).sum()
                ),
            },
            {
                "check_name": "unmatched_or_ambiguous_performances",
                "failed_row_count": int(
                    (
                        ~attribution["profile_match_status"].isin(
                            [
                                "RESULT_URL_MATCH",
                                "MEET_URL_MATCH",
                            ]
                        )
                    ).sum()
                ),
                "observed_value": int(
                    (
                        ~attribution["profile_match_status"].isin(
                            [
                                "RESULT_URL_MATCH",
                                "MEET_URL_MATCH",
                            ]
                        )
                    ).sum()
                ),
            },
            {
                "check_name": "analytical_team_unresolved",
                "failed_row_count": int(
                    (
                        attribution["comparison_status"]
                        == "ANALYTICAL_TEAM_UNRESOLVED"
                    ).sum()
                ),
                "observed_value": int(
                    (
                        attribution["comparison_status"]
                        == "ANALYTICAL_TEAM_UNRESOLVED"
                    ).sum()
                ),
            },
            {
                "check_name": "manual_fixture_failures",
                "failed_row_count": int(
                    (
                        fixture_validation.get(
                            "fixture_status",
                            pd.Series(dtype=str),
                        )
                        == "FAIL"
                    ).sum()
                ),
                "observed_value": int(
                    (
                        fixture_validation.get(
                            "fixture_status",
                            pd.Series(dtype=str),
                        )
                        == "FAIL"
                    ).sum()
                ),
            },
        ]

        hard_check_frame = pd.DataFrame(hard_checks)
        hard_check_frame.to_csv(
            OUTPUT_DIR / "hard_checks.csv",
            index=False,
        )

        total_performances = len(attribution)
        matched_performances = int(
            attribution["profile_match_status"].isin(
                ["RESULT_URL_MATCH", "MEET_URL_MATCH"]
            ).sum()
        )
        result_url_matches = int(
            (
                attribution["profile_match_status"]
                == "RESULT_URL_MATCH"
            ).sum()
        )
        disagreements = len(overrides)
        unresolved_count = len(unresolved)
        failed_hard_checks = int(
            (
                hard_check_frame["failed_row_count"] > 0
            ).sum()
        )

        summary = f"""MILESTONE 4 FULL TRANSFER-AWARE ATTRIBUTION
=================================================
Database: {DB_PATH}
Connection mode: read-only
Raw files modified: no
Database objects created or modified: no
Attribution version: {ATTRIBUTION_VERSION}

CANDIDATES
- Multi-school athlete profiles processed: {len(candidates):,}
- Parsed school sections: {len(section_mapping):,}
- Parsed section links: {len(all_links):,}

PERFORMANCES
- Candidate performances inspected: {total_performances:,}
- Matched to exactly one profile section: {matched_performances:,}
- Result-URL matches: {result_url_matches:,}
- Original/analytical team disagreements: {disagreements:,}
- Unresolved or ambiguous performances: {unresolved_count:,}

VALIDATION
- Manual fixture rows: {len(fixture_validation):,}
- Failed hard checks: {failed_hard_checks:,}

PRIMARY OUTPUTS
- candidate_athletes.csv
- profile_parse_audit.csv
- school_section_mapping.csv
- section_links.csv
- performance_attribution_candidates.csv
- performance_attribution_overrides.csv
- unresolved_performances.csv
- performance_attribution_audit.csv
- athlete_school_history.csv
- manual_fixture_validation.csv
- hard_checks.csv

NEXT DECISION
Only after reviewing this audit should the project create versioned
analytics.m4_performance_attribution and audit.m4_transfer_attribution tables.
The Milestone 3 core tables remain unchanged.
"""

        (OUTPUT_DIR / "transfer_attribution_summary.txt").write_text(
            summary,
            encoding="utf-8",
        )

        print("Full transfer-aware attribution pass complete.")
        print(f"Outputs: {OUTPUT_DIR}")
        print(
            f"Candidate athletes: {len(candidates):,}; "
            f"candidate performances: {total_performances:,}; "
            f"overrides: {disagreements:,}; "
            f"unresolved: {unresolved_count:,}."
        )
        print("Database connection was read-only.")

    finally:
        con.close()


if __name__ == "__main__":
    main()
