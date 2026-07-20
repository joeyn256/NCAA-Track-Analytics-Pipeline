#!/usr/bin/env python3
"""
Milestone 5 Phase 3C-R2 — Import Browser-Saved T&FN Record Pages

Corrected importer for Chrome "Webpage, HTML Only" saves.

Key fix:
T&FN record pages are laid out as HTML tables. Event, mark, athlete, school,
location, and date may occupy separate cells. This importer parses <tr>/<td>
rows first, joins those cells into one logical record row, and uses a
stateful text fallback only when needed.

No network requests are made.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from bs4 import BeautifulSoup


VERSION = "collegiate_records_v1"
IMPORTER_VERSION = "local_tfn_importer_v2"

ROOT = Path.cwd()
SOURCE_DIR = ROOT / "data/reference/collegiate_records/source_html"
OUTPUT_DIR = ROOT / "data/reference/collegiate_records/v1"

SCOPE_CSV = (
    ROOT
    / "data/processed/milestone5/collegiate_record_anchors_v1/"
      "scope_v1/primary_record_anchor_requirements.csv"
)

SOURCES = [
    {
        "source_key": "men_absolute",
        "filename": "mens_collegiate_records.html",
        "season_type": "outdoor",
        "gender": "m",
        "source_url": (
            "https://trackandfieldnews.com/records/"
            "mens-collegiate-records/"
        ),
    },
    {
        "source_key": "women_absolute",
        "filename": "womens_collegiate_records.html",
        "season_type": "outdoor",
        "gender": "f",
        "source_url": (
            "https://trackandfieldnews.com/records/"
            "womens-collegiate-records/"
        ),
    },
    {
        "source_key": "men_indoor",
        "filename": "mens_indoor_collegiate_records.html",
        "season_type": "indoor",
        "gender": "m",
        "source_url": (
            "https://trackandfieldnews.com/records/"
            "mens-indoor-collegiate-records/"
        ),
    },
    {
        "source_key": "women_indoor",
        "filename": "womens_indoor_collegiate_records.html",
        "season_type": "indoor",
        "gender": "f",
        "source_url": (
            "https://trackandfieldnews.com/records/"
            "womens-indoor-collegiate-records/"
        ),
    },
]

EVENT_ALIASES = {
    "50M": ["50"],
    "55M": ["55"],
    "60M": ["60"],
    "100M": ["100"],
    "200M": ["200"],
    "300M": ["300"],
    "400M": ["400"],
    "500M": ["500"],
    "600M": ["600"],
    "800M": ["800"],
    "1000M": ["1000"],
    "1500M": ["1500"],
    "MILE": ["MILE"],
    "2000M": ["2000"],
    "3000M": ["3000"],
    "2MILE": ["2 MILES"],
    "5000M": ["5000"],
    "10000M": ["10,000", "10000"],
    "50H": ["50 HURDLES"],
    "55H": ["55 HURDLES"],
    "60H": ["60 HURDLES"],
    "100H": ["100 HURDLES"],
    "110H": ["110 HURDLES"],
    "400H": ["400 HURDLES"],
    "3000SC": ["STEEPLE", "3000 STEEPLECHASE"],
    "HJ": ["HIGH JUMP"],
    "PV": ["POLE VAULT"],
    "LJ": ["LONG JUMP"],
    "TJ": ["TRIPLE JUMP"],
    "SP": ["SHOT", "SHOT PUT"],
    "DT": ["DISCUS"],
    "HT": ["HAMMER"],
    "JT": ["JAVELIN"],
    "WT": ["WEIGHT", "WEIGHT THROW"],
    "PENT": ["PENTATHLON"],
    "HEP": ["HEPTATHLON"],
    "DEC": ["DECATHLON"],
}

SECTION_NAMES = {
    "TRACK EVENTS": "track",
    "TRACK EVENT": "track",
    "RELAY EVENTS": "relay",
    "RELAY EVENT": "relay",
    "FIELD EVENTS": "field",
    "FIELD EVENT": "field",
    "MULTI EVENT": "multi",
    "MULTI-EVENT": "multi",
    "MULTI EVENTS": "multi",
}

SECONDARY_PHRASES = (
    "AMERICAN CR",
    "AMERICAN C",
    "LOW-ALTITUDE",
    "LOW ALTITUDE",
    "LO-ALT",
    "NAIA",
    "NCAA II",
    "NCAA III",
    "JUCO",
)

MARK_RE = re.compile(
    r"(?P<mark>"
    r"\d{1,2}:\d{2}(?:\.\d+)?"
    r"|"
    r"\d+(?:\.\d+)?"
    r")(?P<flags>(?:\(A\)|[ipyw])*)",
    re.IGNORECASE,
)

DATE_RE = re.compile(
    r"(\d{1,2}/\d{1,2}(?:-\d{1,2})?/\d{2,4})$"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: str) -> str:
    value = (
        value.replace("\xa0", " ")
        .replace("‑", "-")
        .replace("–", "-")
        .replace("—", "-")
    )
    return re.sub(r"\s+", " ", value).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(
    path: Path,
    rows: Iterable[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def normalize_event_text(value: str) -> str:
    return clean_text(value).upper().rstrip(":")


def identify_event(value: str) -> str | None:
    upper = normalize_event_text(value)

    # Exact event-cell matching is preferred.
    for code, aliases in EVENT_ALIASES.items():
        for alias in aliases:
            if upper == alias:
                return code

    # Joined-row fallback: event at the beginning of a logical row.
    for code, aliases in EVENT_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            if re.match(rf"^{re.escape(alias)}(?:\s|$)", upper):
                return code

    return None


def strip_event_prefix(value: str, event_code: str) -> str:
    upper = normalize_event_text(value)
    aliases = sorted(
        EVENT_ALIASES[event_code],
        key=len,
        reverse=True,
    )
    for alias in aliases:
        match = re.match(rf"^{re.escape(alias)}(?:\s+|$)", upper)
        if match:
            return value[match.end():].strip()
    return value


def find_mark(value: str) -> tuple[str, str, int, int] | None:
    match = MARK_RE.search(value)
    if not match:
        return None
    return (
        match.group("mark"),
        match.group("flags") or "",
        match.start(),
        match.end(),
    )


def numeric_mark(raw_mark: str) -> float:
    if ":" in raw_mark:
        minutes, seconds = raw_mark.split(":", 1)
        return int(minutes) * 60.0 + float(seconds)
    return float(raw_mark)


def extract_date(value: str) -> str:
    match = DATE_RE.search(value)
    return match.group(1) if match else ""


def holder_and_school(value: str) -> tuple[str, str]:
    school_match = re.search(r"\(([^()]*)\)", value)
    school = school_match.group(1).strip() if school_match else ""

    holder = value
    if school_match:
        holder = value[: school_match.start()].strip()

    # The holder is the text before the parenthesized school. For rows
    # without a school, remove trailing location/date conservatively.
    holder = re.sub(
        r"\s+[A-Z][A-Za-zÀ-ÿ .'-]+,\s+"
        r"[A-Z][A-Za-zÀ-ÿ .'-]+\s+"
        r"\d{1,2}/\d{1,2}(?:-\d{1,2})?/\d{2,4}$",
        "",
        holder,
    ).strip()

    return holder, school


def soup_for(path: Path) -> BeautifulSoup:
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    return soup


def source_as_of(soup: BeautifulSoup) -> str:
    text = clean_text(soup.get_text(" "))
    match = re.search(
        r"\bas of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else ""


def table_logical_rows(soup: BeautifulSoup) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for table_index, table in enumerate(soup.find_all("table"), start=1):
        section = ""
        outside = False
        current_event = ""

        # Determine nearby heading context.
        previous_heading = table.find_previous(
            ["h1", "h2", "h3", "h4", "strong", "p"]
        )
        if previous_heading:
            heading_text = normalize_event_text(
                previous_heading.get_text(" ", strip=True)
            )
            if "OUTSIDE REGULAR COLLEGIATE SEASON" in heading_text:
                outside = True
            for label, normalized in SECTION_NAMES.items():
                if label in heading_text:
                    section = normalized

        for row_index, tr in enumerate(table.find_all("tr"), start=1):
            cells = [
                clean_text(cell.get_text(" ", strip=True))
                for cell in tr.find_all(["th", "td"])
            ]
            cells = [cell for cell in cells if cell]
            if not cells:
                continue

            joined = clean_text(" ".join(cells))
            joined_upper = joined.upper()

            if joined_upper in SECTION_NAMES:
                section = SECTION_NAMES[joined_upper]
                current_event = ""
                continue

            if "MARKS MADE OUTSIDE REGULAR COLLEGIATE SEASON" in joined_upper:
                outside = True
                current_event = ""
                continue

            event_code = identify_event(cells[0])
            if event_code:
                current_event = event_code
            else:
                event_code = identify_event(joined) or current_event

            rows.append(
                {
                    "table_index": table_index,
                    "row_index": row_index,
                    "section": section,
                    "outside_regular_collegiate_season": outside,
                    "cells": cells,
                    "joined": joined,
                    "event_code": event_code or "",
                }
            )

    return rows


def fallback_logical_rows(soup: BeautifulSoup) -> list[dict[str, Any]]:
    container = (
        soup.find("main")
        or soup.find("article")
        or soup.find(class_=re.compile(r"entry-content|post-content"))
        or soup.body
        or soup
    )
    lines = [
        clean_text(line)
        for line in container.get_text("\n").splitlines()
        if clean_text(line)
    ]

    rows: list[dict[str, Any]] = []
    section = ""
    outside = False
    current_event = ""
    pending_parts: list[str] = []

    def flush() -> None:
        nonlocal pending_parts
        if not pending_parts or not current_event:
            pending_parts = []
            return
        joined = clean_text(" ".join(pending_parts))
        if find_mark(joined):
            rows.append(
                {
                    "table_index": 0,
                    "row_index": len(rows) + 1,
                    "section": section,
                    "outside_regular_collegiate_season": outside,
                    "cells": pending_parts[:],
                    "joined": joined,
                    "event_code": current_event,
                }
            )
        pending_parts = []

    for line in lines:
        upper = normalize_event_text(line)

        if upper in SECTION_NAMES:
            flush()
            section = SECTION_NAMES[upper]
            current_event = ""
            continue

        if "MARKS MADE OUTSIDE REGULAR COLLEGIATE SEASON" in upper:
            flush()
            outside = True
            current_event = ""
            continue

        new_event = identify_event(line)
        if new_event:
            flush()
            current_event = new_event
            pending_parts = [line]
            if find_mark(strip_event_prefix(line, new_event)):
                flush()
            continue

        if not current_event:
            continue

        # A new mark-only line starts a tied/pending/secondary listing for
        # the current event.
        if find_mark(line) and pending_parts:
            flush()
            pending_parts = [line]
        else:
            pending_parts.append(line)

        # A date usually completes a logical record.
        if extract_date(line):
            flush()

    flush()
    return rows


def candidate_from_row(
    row: dict[str, Any],
    source: dict[str, str],
    as_of: str,
    html_hash: str,
) -> dict[str, Any] | None:
    event_code = row["event_code"]
    if not event_code:
        return None

    joined = row["joined"]
    remainder = strip_event_prefix(joined, event_code)
    mark_data = find_mark(remainder)

    if not mark_data:
        # In table mode the first cell may be event-only and second mark-only.
        remainder = clean_text(
            " ".join(row["cells"][1:])
            if len(row["cells"]) > 1
            else row["joined"]
        )
        mark_data = find_mark(remainder)

    if not mark_data:
        return None

    raw_mark, flags, _, mark_end = mark_data
    detail = remainder[mark_end:].strip()
    holder, school = holder_and_school(detail)

    upper = joined.upper()
    secondary = any(
        phrase in upper for phrase in SECONDARY_PHRASES
    )
    pending = "P" in flags.upper()
    indoor_flag = "I" in flags.upper()
    altitude = "(A)" in flags.upper()

    return {
        "version": VERSION,
        "importer_version": IMPORTER_VERSION,
        "source_key": source["source_key"],
        "season_type": source["season_type"],
        "canonical_gender_code": source["gender"],
        "canonical_event_code": event_code,
        "section": row["section"],
        "source_table_index": row["table_index"],
        "source_row_index": row["row_index"],
        "source_cells": " || ".join(row["cells"]),
        "source_line": joined,
        "raw_mark": raw_mark,
        "normalized_mark": numeric_mark(raw_mark),
        "mark_flags": flags,
        "pending_ratification": pending,
        "indoor_mark_flag": indoor_flag,
        "altitude_flag": altitude,
        "secondary_listing": secondary,
        "outside_regular_collegiate_season": row[
            "outside_regular_collegiate_season"
        ],
        "holder": holder,
        "school": school,
        "record_date_text": extract_date(joined),
        "source_as_of": as_of,
        "source_url": source["source_url"],
        "local_html_sha256": html_hash,
    }


def main() -> int:
    print("MILESTONE 5 PHASE 3C-R2 — IMPORT LOCAL T&FN RECORD PAGES")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Dataset version: {VERSION}")
    print(f"Importer version: {IMPORTER_VERSION}")
    print(f"Source directory: {SOURCE_DIR}")
    print(f"Output directory: {OUTPUT_DIR}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    parser_diagnostics: list[dict[str, Any]] = []

    def add_check(
        name: str,
        passed: bool,
        observed: Any,
        expected: Any,
        details: str = "",
    ) -> None:
        checks.append(
            {
                "check_name": name,
                "status": "PASS" if passed else "FAIL",
                "observed": observed,
                "expected": expected,
                "details": details,
            }
        )

    missing = [
        source["filename"]
        for source in SOURCES
        if not (SOURCE_DIR / source["filename"]).exists()
    ]

    add_check(
        "primary_anchor_scope_exists",
        SCOPE_CSV.exists(),
        SCOPE_CSV.exists(),
        True,
        str(SCOPE_CSV),
    )
    add_check(
        "all_four_local_html_files_exist",
        not missing,
        len(missing),
        0,
        "; ".join(missing),
    )

    if not SCOPE_CSV.exists() or missing:
        write_csv(
            OUTPUT_DIR / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Missing required local inputs.")
        return 1

    with SCOPE_CSV.open(newline="", encoding="utf-8") as handle:
        scope_rows = list(csv.DictReader(handle))

    add_check(
        "primary_anchor_requirement_count",
        len(scope_rows) == 81,
        len(scope_rows),
        81,
    )

    seen_candidate_keys: set[tuple[Any, ...]] = set()

    for source in SOURCES:
        path = SOURCE_DIR / source["filename"]
        html_hash = sha256_file(path)
        soup = soup_for(path)
        as_of = source_as_of(soup)

        table_rows = table_logical_rows(soup)
        fallback_rows = fallback_logical_rows(soup)

        source_candidates: list[dict[str, Any]] = []

        for parser_name, rows in [
            ("table", table_rows),
            ("fallback", fallback_rows),
        ]:
            accepted = 0
            for row in rows:
                candidate = candidate_from_row(
                    row,
                    source,
                    as_of,
                    html_hash,
                )
                if not candidate:
                    continue

                dedupe_key = (
                    candidate["source_key"],
                    candidate["canonical_event_code"],
                    candidate["raw_mark"],
                    candidate["holder"],
                    candidate["record_date_text"],
                    candidate["secondary_listing"],
                    candidate["outside_regular_collegiate_season"],
                )
                if dedupe_key in seen_candidate_keys:
                    continue

                seen_candidate_keys.add(dedupe_key)
                candidate["parser_method"] = parser_name
                source_candidates.append(candidate)
                accepted += 1

            parser_diagnostics.append(
                {
                    "source_key": source["source_key"],
                    "parser_method": parser_name,
                    "logical_row_count": len(rows),
                    "accepted_candidate_count": accepted,
                }
            )

        candidates.extend(source_candidates)

        manifest.append(
            {
                "version": VERSION,
                "importer_version": IMPORTER_VERSION,
                "source_key": source["source_key"],
                "season_type": source["season_type"],
                "canonical_gender_code": source["gender"],
                "source_url": source["source_url"],
                "local_html_path": str(path),
                "sha256": html_hash,
                "size_bytes": path.stat().st_size,
                "source_as_of": as_of,
                "imported_utc": utc_now(),
                "table_count": len(soup.find_all("table")),
                "candidate_count": len(source_candidates),
            }
        )

    add_check(
        "candidate_rows_extracted",
        len(candidates) >= 100,
        len(candidates),
        "at least 100",
        "Includes ratified, pending, secondary, and post-season listings.",
    )

    scope_by_key = {
        (
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
        ): row
        for row in scope_rows
    }

    candidates_by_key: dict[
        tuple[str, str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)

    for row in candidates:
        candidates_by_key[
            (
                row["season_type"],
                row["canonical_gender_code"],
                row["canonical_event_code"],
            )
        ].append(row)

    selected: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []

    for key, scope_row in sorted(scope_by_key.items()):
        rows = candidates_by_key.get(key, [])

        ratified_main = [
            row
            for row in rows
            if not row["pending_ratification"]
            and not row["secondary_listing"]
            and not row["outside_regular_collegiate_season"]
        ]
        pending_main = [
            row
            for row in rows
            if row["pending_ratification"]
            and not row["secondary_listing"]
            and not row["outside_regular_collegiate_season"]
        ]

        # T&FN places the active record first. Multiple ratified main rows
        # can exist for ties or altitude/low-altitude variants.
        active = ratified_main[0] if ratified_main else None

        coverage.append(
            {
                "season_type": key[0],
                "canonical_gender_code": key[1],
                "canonical_event_code": key[2],
                "performance_count": scope_row["performance_count"],
                "ratified_main_candidate_count": len(ratified_main),
                "pending_main_candidate_count": len(pending_main),
                "active_candidate_selected": bool(active),
                "coverage_status": (
                    "active_candidate_selected"
                    if active
                    else "manual_anchor_policy_required"
                ),
            }
        )

        if active:
            selected.append(
                {
                    **active,
                    "anchor_status": "ratified_active_candidate",
                    "selection_policy": (
                        "first ratified non-secondary regular-season "
                        "record listing"
                    ),
                    "performance_count": scope_row["performance_count"],
                }
            )

    manual = [
        row for row in coverage
        if not row["active_candidate_selected"]
    ]

    add_check(
        "all_primary_requirements_profiled",
        len(coverage) == 81,
        len(coverage),
        81,
    )
    add_check(
        "majority_primary_requirements_have_active_candidate",
        len(selected) >= 73,
        len(selected),
        "at least 73",
        (
            "Expected unresolved cases are primarily 55m/55H and events "
            "not maintained by T&FN."
        ),
    )

    candidate_fields = [
        "version",
        "importer_version",
        "source_key",
        "season_type",
        "canonical_gender_code",
        "canonical_event_code",
        "section",
        "source_table_index",
        "source_row_index",
        "source_cells",
        "source_line",
        "raw_mark",
        "normalized_mark",
        "mark_flags",
        "pending_ratification",
        "indoor_mark_flag",
        "altitude_flag",
        "secondary_listing",
        "outside_regular_collegiate_season",
        "holder",
        "school",
        "record_date_text",
        "source_as_of",
        "source_url",
        "local_html_sha256",
        "parser_method",
    ]

    write_csv(
        OUTPUT_DIR / "source_manifest.csv",
        manifest,
        [
            "version",
            "importer_version",
            "source_key",
            "season_type",
            "canonical_gender_code",
            "source_url",
            "local_html_path",
            "sha256",
            "size_bytes",
            "source_as_of",
            "imported_utc",
            "table_count",
            "candidate_count",
        ],
    )
    write_csv(
        OUTPUT_DIR / "parser_diagnostics.csv",
        parser_diagnostics,
        [
            "source_key",
            "parser_method",
            "logical_row_count",
            "accepted_candidate_count",
        ],
    )
    write_csv(
        OUTPUT_DIR / "all_record_candidates.csv",
        candidates,
        candidate_fields,
    )
    write_csv(
        OUTPUT_DIR / "active_record_candidates.csv",
        selected,
        candidate_fields
        + [
            "anchor_status",
            "selection_policy",
            "performance_count",
        ],
    )
    write_csv(
        OUTPUT_DIR / "pending_record_candidates.csv",
        [
            row for row in candidates
            if row["pending_ratification"]
        ],
        candidate_fields,
    )
    write_csv(
        OUTPUT_DIR / "primary_anchor_coverage.csv",
        coverage,
        [
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "performance_count",
            "ratified_main_candidate_count",
            "pending_main_candidate_count",
            "active_candidate_selected",
            "coverage_status",
        ],
    )
    write_csv(
        OUTPUT_DIR / "manual_anchor_policy_required.csv",
        manual,
        [
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "performance_count",
            "ratified_main_candidate_count",
            "pending_main_candidate_count",
            "active_candidate_selected",
            "coverage_status",
        ],
    )
    write_csv(
        OUTPUT_DIR / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [row for row in checks if row["status"] == "FAIL"]
    pending_count = sum(
        bool(row["pending_ratification"]) for row in candidates
    )

    report = [
        "MILESTONE 5 PHASE 3C-R2 — LOCAL COLLEGIATE RECORD IMPORT",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Dataset version: {VERSION}",
        f"Importer version: {IMPORTER_VERSION}",
        "",
        "RESULTS",
        "-" * 78,
        f"Local source pages: {len(manifest):,}",
        f"Extracted record candidates: {len(candidates):,}",
        f"Active ratified candidates selected: {len(selected):,}",
        f"Pending candidates preserved: {pending_count:,}",
        f"Primary combinations requiring manual policy: {len(manual):,}",
        "",
        "PARSER POLICY",
        "-" * 78,
        "HTML table rows are parsed before flattened page text.",
        "Adjacent table cells are joined into one logical record row.",
        "A stateful text parser provides fallback coverage.",
        "Pending, secondary, and post-season marks remain non-active.",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Local collegiate record candidates imported."
            if not failed
            else "FAIL — Review parser diagnostics and unresolved checks."
        ),
    ]
    (OUTPUT_DIR / "import_report.txt").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Extracted record candidates: {len(candidates):,}")
    print(f"Active ratified candidates selected: {len(selected):,}")
    print(f"Pending candidates preserved: {pending_count:,}")
    print(f"Primary combinations requiring manual policy: {len(manual):,}")
    print()
    print(f"Output: {OUTPUT_DIR}")

    if failed:
        print()
        print("PHASE GATE: FAIL")
        for row in failed:
            print(
                f"  {row['check_name']}: "
                f"observed={row['observed']} "
                f"expected={row['expected']}"
            )
        return 1

    print()
    print("PHASE GATE: PASS")
    print("Next: validate active anchors against the performance database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
