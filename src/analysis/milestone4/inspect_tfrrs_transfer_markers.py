#!/usr/bin/env python3
"""
Inspect TFRRS transfer markers in saved athlete-profile HTML.

This is a read-only Milestone 4 diagnostic. It does not modify the DuckDB
database or any raw HTML files.

Purpose
-------
Confirm how TFRRS encodes school transitions such as:

    Competing for Minnesota
    Competing for Michigan State

The output reveals the marker's HTML tag, attributes, parent structure,
nearby siblings, and nearby table rows. That evidence will be used to build
a deterministic parser that assigns each performance to the correct school.

Run from the repository root:

    python src/analysis/milestone4/inspect_tfrrs_transfer_markers.py

Optional custom athlete IDs:

    python src/analysis/milestone4/inspect_tfrrs_transfer_markers.py \
        6093853 6418102 6544920
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup, Tag


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ATHLETE_PAGE_DIR = PROJECT_ROOT / "data/raw/athlete_pages"
OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/transfer_marker_inspection"
)

DEFAULT_ATHLETE_IDS = [6093853, 6418102, 6544920]

WHITESPACE_RE = re.compile(r"\s+")
MARKER_RE = re.compile(r"\bCompeting\s+for\s+(.+?)\s*$", re.IGNORECASE)
PREVIOUS_RE = re.compile(r"\bpreviously\s+at\s+(.+?)\s*$", re.IGNORECASE)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return WHITESPACE_RE.sub(" ", value).strip()


def safe_attrs(tag: Tag) -> str:
    parts: list[str] = []
    for key, value in tag.attrs.items():
        if isinstance(value, list):
            rendered = " ".join(str(item) for item in value)
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return " | ".join(parts)


def concise_tag_text(tag: Tag | None, limit: int = 500) -> str:
    if tag is None:
        return ""
    text = clean_text(tag.get_text(" ", strip=True))
    return text[:limit]


def nearest_parent_table(tag: Tag) -> Tag | None:
    parent = tag
    while parent is not None:
        if isinstance(parent, Tag) and parent.name == "table":
            return parent
        parent = parent.parent
    return None


def nearest_parent_row(tag: Tag) -> Tag | None:
    parent = tag
    while parent is not None:
        if isinstance(parent, Tag) and parent.name == "tr":
            return parent
        parent = parent.parent
    return None


def nearby_siblings(tag: Tag, radius: int = 4) -> list[tuple[str, str, str]]:
    parent = tag.parent
    if not isinstance(parent, Tag):
        return []

    siblings = [
        child
        for child in parent.children
        if isinstance(child, Tag) and clean_text(child.get_text(" ", strip=True))
    ]

    try:
        index = siblings.index(tag)
    except ValueError:
        # The marker may be nested inside a larger sibling.
        containing_index = None
        for idx, sibling in enumerate(siblings):
            if tag in sibling.descendants:
                containing_index = idx
                break
        if containing_index is None:
            return []
        index = containing_index

    output: list[tuple[str, str, str]] = []
    start = max(0, index - radius)
    end = min(len(siblings), index + radius + 1)

    for idx in range(start, end):
        sibling = siblings[idx]
        relation = "marker"
        if idx < index:
            relation = f"before_{index - idx}"
        elif idx > index:
            relation = f"after_{idx - index}"

        output.append(
            (
                relation,
                sibling.name or "",
                concise_tag_text(sibling),
            )
        )
    return output


def table_rows_around_marker(tag: Tag, radius: int = 5) -> list[tuple[str, str]]:
    table = nearest_parent_table(tag)
    if table is None:
        # Some pages put marker divs between tables. Inspect adjacent tables.
        return []

    rows = [
        row
        for row in table.find_all("tr")
        if clean_text(row.get_text(" ", strip=True))
    ]
    marker_row = nearest_parent_row(tag)

    if marker_row is None or marker_row not in rows:
        return [
            (f"table_row_{idx + 1}", concise_tag_text(row))
            for idx, row in enumerate(rows[: radius * 2 + 1])
        ]

    index = rows.index(marker_row)
    start = max(0, index - radius)
    end = min(len(rows), index + radius + 1)

    output: list[tuple[str, str]] = []
    for idx in range(start, end):
        relation = "marker_row"
        if idx < index:
            relation = f"row_before_{index - idx}"
        elif idx > index:
            relation = f"row_after_{idx - index}"
        output.append((relation, concise_tag_text(rows[idx])))
    return output


def candidate_marker_tags(soup: BeautifulSoup) -> list[Tag]:
    """
    Return the smallest meaningful tags containing 'Competing for'.

    We avoid returning every ancestor by retaining tags whose direct string or
    compact child structure contains the marker.
    """
    candidates: list[Tag] = []

    for text_node in soup.find_all(string=re.compile(r"Competing\s+for", re.I)):
        parent = text_node.parent
        if not isinstance(parent, Tag):
            continue

        tag = parent

        # Prefer a compact semantic ancestor when the text is inside a span.
        while (
            isinstance(tag.parent, Tag)
            and tag.parent.name in {"span", "strong", "b", "em", "a"}
            and len(clean_text(tag.parent.get_text(" ", strip=True))) < 200
        ):
            tag = tag.parent

        if tag not in candidates:
            candidates.append(tag)

    return candidates


def extract_header_signals(
    soup: BeautifulSoup,
    athlete_id: int,
) -> list[tuple[int, str, str]]:
    page_text_lines = [
        clean_text(line)
        for line in soup.get_text("\n", strip=True).splitlines()
        if clean_text(line)
    ]

    rows: list[tuple[int, str, str]] = []

    for line in page_text_lines[:200]:
        previous_match = PREVIOUS_RE.search(line.lstrip("* ").strip())
        if previous_match:
            rows.append(
                (
                    athlete_id,
                    "previous_school",
                    clean_text(previous_match.group(1)),
                )
            )

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if title:
        rows.append((athlete_id, "html_title", clean_text(title)))

    return rows


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


def inspect_athlete(
    athlete_id: int,
) -> tuple[list[tuple], list[tuple], list[tuple], list[tuple]]:
    page_path = ATHLETE_PAGE_DIR / f"{athlete_id}.html"

    page_rows: list[tuple] = []
    marker_rows: list[tuple] = []
    sibling_rows: list[tuple] = []
    table_rows: list[tuple] = []

    if not page_path.exists():
        page_rows.append(
            (
                athlete_id,
                str(page_path),
                0,
                None,
                0,
                "FILE_NOT_FOUND",
            )
        )
        return page_rows, marker_rows, sibling_rows, table_rows

    html = page_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    markers = candidate_marker_tags(soup)

    page_rows.append(
        (
            athlete_id,
            str(page_path),
            1,
            page_path.stat().st_size,
            len(markers),
            "OK",
        )
    )

    for marker_index, marker in enumerate(markers, start=1):
        marker_text = clean_text(marker.get_text(" ", strip=True))
        marker_match = MARKER_RE.search(marker_text)
        school_name = clean_text(marker_match.group(1)) if marker_match else ""

        parent = marker.parent if isinstance(marker.parent, Tag) else None
        grandparent = (
            parent.parent
            if isinstance(parent, Tag) and isinstance(parent.parent, Tag)
            else None
        )

        marker_rows.append(
            (
                athlete_id,
                marker_index,
                school_name,
                marker_text,
                marker.name,
                safe_attrs(marker),
                parent.name if isinstance(parent, Tag) else "",
                safe_attrs(parent) if isinstance(parent, Tag) else "",
                grandparent.name if isinstance(grandparent, Tag) else "",
                safe_attrs(grandparent) if isinstance(grandparent, Tag) else "",
                concise_tag_text(parent),
                concise_tag_text(grandparent),
            )
        )

        for relation, tag_name, text in nearby_siblings(marker):
            sibling_rows.append(
                (
                    athlete_id,
                    marker_index,
                    school_name,
                    relation,
                    tag_name,
                    text,
                )
            )

        for relation, text in table_rows_around_marker(marker):
            table_rows.append(
                (
                    athlete_id,
                    marker_index,
                    school_name,
                    relation,
                    text,
                )
            )

    header_rows = extract_header_signals(soup, athlete_id)
    return page_rows, marker_rows, sibling_rows, table_rows, header_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "athlete_ids",
        nargs="*",
        type=int,
        default=DEFAULT_ATHLETE_IDS,
        help="TFRRS athlete IDs to inspect.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    athlete_ids = args.athlete_ids or DEFAULT_ATHLETE_IDS
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_page_rows: list[tuple] = []
    all_marker_rows: list[tuple] = []
    all_sibling_rows: list[tuple] = []
    all_table_rows: list[tuple] = []
    all_header_rows: list[tuple] = []

    for athlete_id in athlete_ids:
        results = inspect_athlete(athlete_id)

        # Backward-compatible unpacking in case a missing file returned only
        # the first four result groups.
        if len(results) == 4:
            page_rows, marker_rows, sibling_rows, table_rows = results
            header_rows = []
        else:
            (
                page_rows,
                marker_rows,
                sibling_rows,
                table_rows,
                header_rows,
            ) = results

        all_page_rows.extend(page_rows)
        all_marker_rows.extend(marker_rows)
        all_sibling_rows.extend(sibling_rows)
        all_table_rows.extend(table_rows)
        all_header_rows.extend(header_rows)

    write_csv(
        OUTPUT_DIR / "page_summary.csv",
        [
            "athlete_id",
            "page_path",
            "page_exists",
            "page_size_bytes",
            "marker_count",
            "status",
        ],
        all_page_rows,
    )

    write_csv(
        OUTPUT_DIR / "transfer_markers.csv",
        [
            "athlete_id",
            "marker_index",
            "school_name",
            "marker_text",
            "marker_tag",
            "marker_attributes",
            "parent_tag",
            "parent_attributes",
            "grandparent_tag",
            "grandparent_attributes",
            "parent_text",
            "grandparent_text",
        ],
        all_marker_rows,
    )

    write_csv(
        OUTPUT_DIR / "marker_sibling_context.csv",
        [
            "athlete_id",
            "marker_index",
            "school_name",
            "relation",
            "tag_name",
            "text",
        ],
        all_sibling_rows,
    )

    write_csv(
        OUTPUT_DIR / "marker_table_context.csv",
        [
            "athlete_id",
            "marker_index",
            "school_name",
            "relation",
            "row_text",
        ],
        all_table_rows,
    )

    write_csv(
        OUTPUT_DIR / "header_school_signals.csv",
        ["athlete_id", "signal_type", "signal_value"],
        all_header_rows,
    )

    summary = f"""MILESTONE 4 TFRRS TRANSFER-MARKER INSPECTION
=================================================
Athlete pages inspected: {len(athlete_ids)}
Athlete IDs: {", ".join(str(value) for value in athlete_ids)}
Raw HTML directory: {ATHLETE_PAGE_DIR}

OUTPUTS
- page_summary.csv
- transfer_markers.csv
- marker_sibling_context.csv
- marker_table_context.csv
- header_school_signals.csv

PURPOSE
The next parser will use the discovered DOM structure to assign historical
performance rows to the correct school while preserving the source athlete ID.

NO RAW FILES OR DATABASE OBJECTS WERE MODIFIED.
"""
    (OUTPUT_DIR / "inspection_summary.txt").write_text(
        summary,
        encoding="utf-8",
    )

    print("TFRRS transfer-marker inspection complete.")
    print(f"Outputs: {OUTPUT_DIR}")
    print("No raw files or database objects were modified.")


if __name__ == "__main__":
    main()
