#!/usr/bin/env python3
"""
Milestone 5 Phase 3C — Snapshot Collegiate Record Sources

Downloads and archives the four Track & Field News collegiate record pages:
- Men's absolute collegiate records
- Women's absolute collegiate records
- Men's indoor collegiate records
- Women's indoor collegiate records

Creates reproducible HTML/text snapshots, extracts source lines, and builds a
candidate event-line inventory for the refined primary anchor requirements.

Important:
- This step does NOT activate record values for scoring.
- Pending marks are preserved and labeled.
- Only ratified marks should become active anchors in the next phase.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup


SNAPSHOT_VERSION = "collegiate_record_source_snapshot_v1"
USER_AGENT = (
    "NCAA-Track-Analytics-Pipeline/1.0 "
    "(research record-source snapshot)"
)
REQUEST_TIMEOUT_SECONDS = 45

SCOPE_CSV = Path(
    "data/processed/milestone5/"
    "collegiate_record_anchors_v1/scope_v1/"
    "primary_record_anchor_requirements.csv"
)
OUTPUT_DIR = Path(
    "data/processed/milestone5/"
    "collegiate_record_anchors_v1/source_snapshot_v1"
)

SOURCES = [
    {
        "source_key": "men_absolute",
        "season_type": "outdoor",
        "canonical_gender_code": "m",
        "source_name": "Track & Field News Men's Collegiate Records",
        "url": (
            "https://trackandfieldnews.com/records/"
            "mens-collegiate-records/"
        ),
    },
    {
        "source_key": "women_absolute",
        "season_type": "outdoor",
        "canonical_gender_code": "f",
        "source_name": "Track & Field News Women's Collegiate Records",
        "url": (
            "https://trackandfieldnews.com/records/"
            "womens-collegiate-records/"
        ),
    },
    {
        "source_key": "men_indoor",
        "season_type": "indoor",
        "canonical_gender_code": "m",
        "source_name": "Track & Field News Men's Indoor Collegiate Records",
        "url": (
            "https://trackandfieldnews.com/records/"
            "mens-indoor-collegiate-records/"
        ),
    },
    {
        "source_key": "women_indoor",
        "season_type": "indoor",
        "canonical_gender_code": "f",
        "source_name": "Track & Field News Women's Indoor Collegiate Records",
        "url": (
            "https://trackandfieldnews.com/records/"
            "womens-indoor-collegiate-records/"
        ),
    },
]

EVENT_ALIASES = {
    "55M": ["55", "55 METERS"],
    "60M": ["60", "60 METERS"],
    "100M": ["100", "100 METERS"],
    "200M": ["200", "200 METERS"],
    "300M": ["300", "300 METERS"],
    "400M": ["400", "400 METERS"],
    "500M": ["500", "500 METERS"],
    "600M": ["600", "600 METERS"],
    "800M": ["800", "800 METERS"],
    "1000M": ["1000", "1000 METERS"],
    "1500M": ["1500", "1500 METERS"],
    "MILE": ["MILE"],
    "3000M": ["3000", "3000 METERS"],
    "5000M": ["5000", "5000 METERS"],
    "10000M": ["10,000", "10000", "10,000 METERS"],
    "55H": ["55 HURDLES", "55H"],
    "60H": ["60 HURDLES", "60H"],
    "100H": ["100 HURDLES", "100H"],
    "110H": ["110 HURDLES", "110H"],
    "400H": ["400 HURDLES", "400H"],
    "3000SC": ["STEEPLE", "3000 STEEPLECHASE", "3000SC"],
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

SECTION_HEADERS = {
    "TRACK EVENTS",
    "TRACK EVENT",
    "RELAY EVENTS",
    "RELAY EVENT",
    "FIELD EVENTS",
    "FIELD EVENT",
    "MULTI EVENT",
    "MULTI EVENTS",
    "MARKS MADE OUTSIDE REGULAR COLLEGIATE SEASON",
}

NON_PRIMARY_PREFIXES = (
    "(LOW-ALTITUDE",
    "(AMERICAN",
    "(AMERICAN CR",
    "(AMERICAN C",
    "LOW-ALTITUDE",
    "AMERICAN CR",
    "AMERICAN C",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, block_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(block_size):
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
        for row in rows:
            writer.writerow(row)


def add_check(
    checks: list[dict[str, Any]],
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


def clean_text(value: str) -> str:
    text = value.replace("\xa0", " ")
    text = text.replace("‑", "-")
    text = text.replace("–", "-")
    text = text.replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def extract_content_lines(html: bytes) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")

    for element in soup(["script", "style", "noscript"]):
        element.decompose()

    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find(class_=re.compile(r"entry-content|post-content"))
        or soup.body
        or soup
    )

    lines: list[str] = []
    for raw in main.get_text("\n").splitlines():
        line = clean_text(raw)
        if not line:
            continue
        lines.append(line)

    # Keep the record section only.
    start_index = None
    end_index = None

    for index, line in enumerate(lines):
        upper = line.upper()
        if start_index is None and (
            "COLLEGIATE RECORDS" in upper
            or "INDOOR COLLEGIATE RECORDS" in upper
        ):
            start_index = index
        if start_index is not None and upper.startswith("AS OF "):
            end_index = index + 1
            break

    if start_index is None:
        return lines

    return lines[start_index:end_index]


def line_event_code(line: str) -> str | None:
    upper = line.upper().strip()

    if upper in SECTION_HEADERS:
        return None

    for code, aliases in EVENT_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            pattern = r"^" + re.escape(alias) + r"(?:\s|$)"
            if re.match(pattern, upper):
                return code

    return None


def mark_token_after_alias(
    line: str,
    event_code: str,
) -> str:
    aliases = sorted(
        EVENT_ALIASES[event_code],
        key=len,
        reverse=True,
    )
    upper = line.upper()

    for alias in aliases:
        match = re.match(
            r"^" + re.escape(alias) + r"\s+(.+)$",
            upper,
        )
        if match:
            original_remainder = line[len(line) - len(match.group(1)) :]
            return original_remainder.strip()

    return ""


def extract_first_mark_token(remainder: str) -> str:
    # Time, points, or metric field mark. We deliberately preserve flags
    # such as p, i, and (A) in the raw line for later policy handling.
    patterns = [
        r"^([0-9]{1,2}:[0-9]{2}(?:\.[0-9]+)?[pi]?)",
        r"^([0-9]+(?:\.[0-9]+)?[pi]?(?:\(A\))?)",
    ]
    for pattern in patterns:
        match = re.match(pattern, remainder, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def pending_from_line(line: str, raw_mark_token: str) -> bool:
    if raw_mark_token.lower().endswith("p"):
        return True
    return bool(
        re.search(
            r"(?<![A-Za-z])"
            + re.escape(raw_mark_token)
            + r"p(?:\s|$)",
            line,
            flags=re.IGNORECASE,
        )
    )


def source_as_of(lines: list[str]) -> str:
    for line in reversed(lines):
        match = re.match(
            r"^as of (.+)$",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
    return ""


def main() -> int:
    root = Path.cwd()
    scope_path = root / SCOPE_CSV
    output_dir = root / OUTPUT_DIR
    raw_dir = output_dir / "raw_html"
    text_dir = output_dir / "source_text"
    raw_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 3C — SNAPSHOT COLLEGIATE RECORD SOURCES")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Snapshot version: {SNAPSHOT_VERSION}")
    print(f"Scope input: {scope_path}")
    print(f"Output: {output_dir}")

    exists = scope_path.exists()
    add_check(
        checks,
        "primary_anchor_scope_exists",
        exists,
        exists,
        True,
        str(scope_path),
    )
    if not exists:
        write_csv(
            output_dir / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Primary anchor scope is missing.")
        return 1

    scope_hash_before = sha256_file(scope_path)
    scope_stat_before = scope_path.stat()

    with scope_path.open(newline="", encoding="utf-8") as handle:
        scope_rows = list(csv.DictReader(handle))

    add_check(
        checks,
        "primary_anchor_requirement_count",
        len(scope_rows) == 81,
        len(scope_rows),
        81,
    )

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    manifest_rows: list[dict[str, Any]] = []
    source_line_rows: list[dict[str, Any]] = []
    event_candidate_rows: list[dict[str, Any]] = []
    fetch_errors: list[dict[str, Any]] = []

    for source in SOURCES:
        source_key = source["source_key"]
        print(f"Fetching {source_key}: {source['url']}")

        try:
            response = session.get(
                source["url"],
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except Exception as exc:
            fetch_errors.append(
                {
                    "source_key": source_key,
                    "url": source["url"],
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            continue

        html = response.content
        html_path = raw_dir / f"{source_key}.html"
        html_path.write_bytes(html)

        lines = extract_content_lines(html)
        text_path = text_dir / f"{source_key}.txt"
        text_path.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

        as_of_text = source_as_of(lines)
        fetched_utc = utc_now()

        manifest_rows.append(
            {
                **source,
                "http_status": response.status_code,
                "fetched_utc": fetched_utc,
                "source_as_of_text": as_of_text,
                "html_path": str(html_path),
                "html_size_bytes": len(html),
                "html_sha256": sha256_bytes(html),
                "text_path": str(text_path),
                "text_line_count": len(lines),
                "text_sha256": sha256_file(text_path),
            }
        )

        current_section = ""
        for line_number, line in enumerate(lines, start=1):
            upper = line.upper()
            if upper in SECTION_HEADERS:
                current_section = upper

            code = line_event_code(line)
            raw_remainder = (
                mark_token_after_alias(line, code)
                if code
                else ""
            )
            raw_mark_token = (
                extract_first_mark_token(raw_remainder)
                if raw_remainder
                else ""
            )
            is_pending = (
                pending_from_line(line, raw_mark_token)
                if raw_mark_token
                else False
            )

            source_line_rows.append(
                {
                    "source_key": source_key,
                    "season_type": source["season_type"],
                    "canonical_gender_code": source[
                        "canonical_gender_code"
                    ],
                    "source_name": source["source_name"],
                    "source_url": source["url"],
                    "source_as_of_text": as_of_text,
                    "line_number": line_number,
                    "section": current_section,
                    "source_line": line,
                    "candidate_event_code": code or "",
                    "raw_mark_token": raw_mark_token,
                    "pending_flag": is_pending,
                    "is_primary_record_line_candidate": bool(
                        code
                        and raw_mark_token
                        and not upper.startswith(
                            NON_PRIMARY_PREFIXES
                        )
                    ),
                }
            )

            if code and raw_mark_token:
                event_candidate_rows.append(
                    {
                        "source_key": source_key,
                        "season_type": source["season_type"],
                        "canonical_gender_code": source[
                            "canonical_gender_code"
                        ],
                        "canonical_event_code": code,
                        "source_name": source["source_name"],
                        "source_url": source["url"],
                        "source_as_of_text": as_of_text,
                        "line_number": line_number,
                        "source_line": line,
                        "raw_mark_token": raw_mark_token,
                        "pending_flag": is_pending,
                        "candidate_priority": (
                            "pending_candidate"
                            if is_pending
                            else "ratified_candidate"
                        ),
                    }
                )

    add_check(
        checks,
        "all_four_sources_fetched",
        len(manifest_rows) == 4,
        len(manifest_rows),
        4,
        json.dumps(fetch_errors, ensure_ascii=False),
    )
    add_check(
        checks,
        "no_fetch_errors",
        len(fetch_errors) == 0,
        len(fetch_errors),
        0,
    )
    add_check(
        checks,
        "all_sources_have_record_lines",
        all(
            int(row["text_line_count"]) >= 20
            for row in manifest_rows
        ),
        sum(
            int(row["text_line_count"]) < 20
            for row in manifest_rows
        ),
        0,
    )
    add_check(
        checks,
        "candidate_record_lines_found",
        len(event_candidate_rows) > 0,
        len(event_candidate_rows),
        "greater than 0",
    )

    requirements_by_key = {
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
    ] = {}
    for row in event_candidate_rows:
        key = (
            row["season_type"],
            row["canonical_gender_code"],
            row["canonical_event_code"],
        )
        candidates_by_key.setdefault(key, []).append(row)

    coverage_rows: list[dict[str, Any]] = []
    for key, requirement in sorted(requirements_by_key.items()):
        candidates = candidates_by_key.get(key, [])
        ratified = [
            row for row in candidates
            if not row["pending_flag"]
        ]
        pending = [
            row for row in candidates
            if row["pending_flag"]
        ]

        coverage_rows.append(
            {
                "season_type": key[0],
                "canonical_gender_code": key[1],
                "canonical_event_code": key[2],
                "canonical_event_name": requirement[
                    "canonical_event_name"
                ],
                "performance_count": requirement[
                    "performance_count"
                ],
                "candidate_line_count": len(candidates),
                "ratified_candidate_count": len(ratified),
                "pending_candidate_count": len(pending),
                "source_snapshot_status": (
                    "candidate_found"
                    if candidates
                    else "no_candidate_found"
                ),
                "manual_review_required": True,
                "active_anchor_status": "not_yet_selected",
            }
        )

    missing_coverage = [
        row for row in coverage_rows
        if row["source_snapshot_status"] == "no_candidate_found"
    ]

    # Some nonstandard events may not be present on record pages. The
    # snapshot gate allows missing candidates, but exposes them explicitly.
    add_check(
        checks,
        "every_primary_requirement_profiled",
        len(coverage_rows) == len(scope_rows),
        len(coverage_rows),
        len(scope_rows),
    )

    fields_manifest = [
        "source_key",
        "season_type",
        "canonical_gender_code",
        "source_name",
        "url",
        "http_status",
        "fetched_utc",
        "source_as_of_text",
        "html_path",
        "html_size_bytes",
        "html_sha256",
        "text_path",
        "text_line_count",
        "text_sha256",
    ]
    write_csv(
        output_dir / "source_manifest.csv",
        manifest_rows,
        fields_manifest,
    )
    write_csv(
        output_dir / "source_lines.csv",
        source_line_rows,
        [
            "source_key",
            "season_type",
            "canonical_gender_code",
            "source_name",
            "source_url",
            "source_as_of_text",
            "line_number",
            "section",
            "source_line",
            "candidate_event_code",
            "raw_mark_token",
            "pending_flag",
            "is_primary_record_line_candidate",
        ],
    )
    write_csv(
        output_dir / "record_line_candidates.csv",
        event_candidate_rows,
        [
            "source_key",
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "source_name",
            "source_url",
            "source_as_of_text",
            "line_number",
            "source_line",
            "raw_mark_token",
            "pending_flag",
            "candidate_priority",
        ],
    )
    write_csv(
        output_dir / "primary_anchor_source_coverage.csv",
        coverage_rows,
        [
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "canonical_event_name",
            "performance_count",
            "candidate_line_count",
            "ratified_candidate_count",
            "pending_candidate_count",
            "source_snapshot_status",
            "manual_review_required",
            "active_anchor_status",
        ],
    )
    write_csv(
        output_dir / "missing_record_source_candidates.csv",
        missing_coverage,
        [
            "season_type",
            "canonical_gender_code",
            "canonical_event_code",
            "canonical_event_name",
            "performance_count",
            "candidate_line_count",
            "ratified_candidate_count",
            "pending_candidate_count",
            "source_snapshot_status",
            "manual_review_required",
            "active_anchor_status",
        ],
    )
    write_csv(
        output_dir / "fetch_errors.csv",
        fetch_errors,
        [
            "source_key",
            "url",
            "error_type",
            "error",
        ],
    )

    scope_hash_after = sha256_file(scope_path)
    scope_stat_after = scope_path.stat()
    unchanged = (
        scope_hash_before == scope_hash_after
        and scope_stat_before.st_size == scope_stat_after.st_size
        and scope_stat_before.st_mtime_ns
        == scope_stat_after.st_mtime_ns
    )
    add_check(
        checks,
        "primary_anchor_scope_unchanged",
        unchanged,
        scope_hash_after,
        scope_hash_before,
    )

    write_csv(
        output_dir / "input_manifest.csv",
        [
            {
                "stage": "before",
                "path": str(scope_path),
                "size_bytes": scope_stat_before.st_size,
                "mtime_epoch_ns": scope_stat_before.st_mtime_ns,
                "sha256": scope_hash_before,
            },
            {
                "stage": "after",
                "path": str(scope_path),
                "size_bytes": scope_stat_after.st_size,
                "mtime_epoch_ns": scope_stat_after.st_mtime_ns,
                "sha256": scope_hash_after,
            },
        ],
        [
            "stage",
            "path",
            "size_bytes",
            "mtime_epoch_ns",
            "sha256",
        ],
    )

    write_csv(
        output_dir / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    failed = [
        check for check in checks
        if check["status"] == "FAIL"
    ]

    pending_line_count = sum(
        bool(row["pending_flag"])
        for row in event_candidate_rows
    )

    report_lines = [
        "MILESTONE 5 PHASE 3C — COLLEGIATE RECORD SOURCE SNAPSHOT",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Snapshot version: {SNAPSHOT_VERSION}",
        "",
        "SOURCE POLICY",
        "-" * 78,
        "Four Track & Field News collegiate record pages are archived.",
        "Absolute pages serve outdoor scoring requirements.",
        "Indoor pages serve indoor scoring requirements.",
        "Pending marks are retained but are not active scoring anchors.",
        "Only ratified marks may become active in the next phase.",
        "",
        "SNAPSHOT SCALE",
        "-" * 78,
        f"Sources fetched: {len(manifest_rows):,} / 4",
        f"Extracted source lines: {len(source_line_rows):,}",
        f"Candidate record lines: {len(event_candidate_rows):,}",
        f"Pending candidate lines: {pending_line_count:,}",
        f"Primary requirements profiled: {len(coverage_rows):,}",
        f"Requirements without candidate line: {len(missing_coverage):,}",
        "",
        "NEXT STEP",
        "-" * 78,
        "Review candidate lines and select one ratified active anchor",
        "for each production requirement. Preserve pending marks separately.",
        "",
        "HARD CHECK SUMMARY",
        "-" * 78,
        f"PASS: {sum(c['status'] == 'PASS' for c in checks)}",
        f"FAIL: {len(failed)}",
        "",
        "PHASE GATE",
        "-" * 78,
        (
            "PASS — Record sources are archived for controlled population."
            if not failed
            else "FAIL — Correct source fetch or extraction errors."
        ),
    ]
    (output_dir / "source_snapshot_report.txt").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Sources fetched: {len(manifest_rows):,} / 4")
    print(f"Candidate record lines: {len(event_candidate_rows):,}")
    print(f"Pending candidate lines: {pending_line_count:,}")
    print(
        "Requirements without candidate line: "
        f"{len(missing_coverage):,}"
    )
    print()
    print("Created:")
    for filename in [
        "source_snapshot_report.txt",
        "source_manifest.csv",
        "source_lines.csv",
        "record_line_candidates.csv",
        "primary_anchor_source_coverage.csv",
        "missing_record_source_candidates.csv",
        "fetch_errors.csv",
        "input_manifest.csv",
        "hard_checks.csv",
    ]:
        print(f"  {output_dir / filename}")
    print(f"  {raw_dir}")
    print(f"  {text_dir}")

    if failed:
        print()
        print("PHASE GATE: FAIL")
        for check in failed:
            print(
                f"  {check['check_name']}: "
                f"observed={check['observed']} "
                f"expected={check['expected']}"
            )
        return 1

    print()
    print("PHASE GATE: PASS")
    print("Stop here and review source coverage before selecting anchors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
