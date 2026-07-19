#!/usr/bin/env python3
"""
Milestone 5 Phase 1C — Coach Manual Review Preparation

Builds a practical manual-review package for track and field event labels.

Key behavior:
- Removes cross-country course-distance inflation from the track review queue.
- Keeps relays visible in a separate review file.
- Keeps every remaining track/field label visible for coach review.
- Groups obvious aliases under suggested canonical events.
- Does not finalize or overwrite the event registry.
"""

from __future__ import annotations

import csv
import hashlib
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


INPUT_DRAFT = Path(
    "data/processed/milestone5/event_registry_v1/"
    "draft_v1/event_registry_draft.csv"
)
INPUT_MARK_PROFILE = Path(
    "data/processed/milestone5/event_registry_v1/"
    "profile_v1/event_mark_shape_profile.csv"
)
OUTPUT_DIR = Path(
    "data/processed/milestone5/event_registry_v1/"
    "coach_review_v1"
)

REVIEW_VERSION = "coach_review_v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, block_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(block_size):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(value: str | None) -> str:
    if value is None:
        return ""
    text = value.strip()
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    return text


def lower(value: str | None) -> str:
    return normalize(value).lower()


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


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


def is_cross_country_course_label(raw_label: str) -> tuple[bool, str]:
    """
    Identify labels that represent cross-country/road course lengths rather
    than track event names.

    Deliberately preserves exact track labels such as "Mile" and "2 Mile".
    """
    raw = normalize(raw_label)

    if raw in {"Mile", "2 Mile"}:
        return False, ""

    # Typical XC labels: 5k, 6k, 8k, 4.97k, 6.43738k, 5000k, etc.
    if re.fullmatch(r"\d+(?:\.\d+)?k", raw, flags=re.IGNORECASE):
        return True, "course_distance_kilometers"

    # Typical XC mile-course labels: 3M, 3.1M, 4.97M, 5M, 8M, etc.
    # The uppercase M matters; lower-case m is treated as meters.
    if re.fullmatch(r"\d+(?:\.\d+)?M", raw):
        return True, "course_distance_miles"

    # Explicit cross-country text.
    if re.search(r"\b(?:xc|cross[- ]country)\b", raw, flags=re.IGNORECASE):
        return True, "explicit_cross_country_label"

    return False, ""


def is_relay_label(raw_label: str, existing_family: str) -> bool:
    text = lower(raw_label)
    if existing_family == "relays":
        return True
    if text.startswith("4x"):
        return True
    return any(
        token in text
        for token in (
            "relay",
            "dmr",
            "smr",
            "shr",
            "distance medley",
            "sprint medley",
        )
    )


def track_alias_suggestion(
    raw_label: str,
    row: dict[str, str],
) -> dict[str, str]:
    """
    Return a coach-review suggestion. Existing draft semantics are retained
    where useful, then obvious aliases are added.
    """
    raw = normalize(raw_label)
    text = raw.lower()

    suggested = {
        "suggested_canonical_event_code": row.get("canonical_event_code", ""),
        "suggested_canonical_event_name": row.get("canonical_event_name", ""),
        "suggested_event_family": row.get("event_family", ""),
        "suggested_event_subfamily": row.get("event_subfamily", ""),
        "suggested_mark_type": row.get("mark_type", ""),
        "suggested_performance_direction": row.get(
            "performance_direction", ""
        ),
        "suggested_standard_distance_meters": row.get(
            "standard_distance_meters", ""
        ),
        "suggested_registry_disposition": row.get(
            "registry_disposition", ""
        ),
        "suggested_development_model_eligible": row.get(
            "development_model_eligible", ""
        ),
        "suggestion_rule": "carry_forward_draft",
        "suggestion_notes": "",
    }

    # Metric number with optional lower-case m suffix: 100 and 100m.
    metric_match = re.fullmatch(r"(\d[\d,]*)(?:m)?", text)
    if metric_match:
        distance = int(metric_match.group(1).replace(",", ""))
        if distance <= 400:
            subfamily = "sprints"
        elif distance <= 1200:
            subfamily = "middle_distance"
        else:
            subfamily = "distance"

        suggested.update(
            {
                "suggested_canonical_event_code": f"{distance}M",
                "suggested_canonical_event_name": f"{distance}m",
                "suggested_event_family": "running",
                "suggested_event_subfamily": subfamily,
                "suggested_mark_type": "time",
                "suggested_performance_direction": "lower_is_better",
                "suggested_standard_distance_meters": str(distance),
                "suggested_registry_disposition": (
                    "include"
                    if distance
                    in {
                        30, 40, 50, 55, 60, 100, 110, 150, 200, 300,
                        400, 500, 600, 800, 1000, 1200, 1500, 1600,
                        2000, 3000, 3200, 5000, 10000, 20000,
                    }
                    else "coach_review"
                ),
                "suggested_development_model_eligible": (
                    "true"
                    if distance
                    in {
                        30, 40, 50, 55, 60, 100, 110, 150, 200, 300,
                        400, 500, 600, 800, 1000, 1200, 1500, 1600,
                        2000, 3000, 3200, 5000, 10000, 20000,
                    }
                    else "false"
                ),
                "suggestion_rule": "metric_distance_alias",
                "suggestion_notes": (
                    "Standard or common track distance."
                    if distance
                    in {
                        30, 40, 50, 55, 60, 100, 110, 150, 200, 300,
                        400, 500, 600, 800, 1000, 1200, 1500, 1600,
                        2000, 3000, 3200, 5000, 10000, 20000,
                    }
                    else "Nonstandard metric distance; coach decision required."
                ),
            }
        )
        return suggested

    # Hurdles: 60H, 100H, 110H, 400H, 300H, 60yH.
    hurdle_match = re.fullmatch(r"(\d[\d,]*)(y)?h", text)
    if hurdle_match:
        distance = int(hurdle_match.group(1).replace(",", ""))
        yards = bool(hurdle_match.group(2))
        suffix = "YH" if yards else "H"
        unit_name = "yard" if yards else "m"
        suggested.update(
            {
                "suggested_canonical_event_code": f"{distance}{suffix}",
                "suggested_canonical_event_name": (
                    f"{distance} {unit_name} Hurdles"
                ),
                "suggested_event_family": "hurdles",
                "suggested_event_subfamily": "hurdles",
                "suggested_mark_type": "time",
                "suggested_performance_direction": "lower_is_better",
                "suggested_standard_distance_meters": (
                    str(round(distance * 0.9144, 3))
                    if yards
                    else str(distance)
                ),
                "suggested_registry_disposition": "include",
                "suggested_development_model_eligible": "true",
                "suggestion_rule": "hurdle_alias",
                "suggestion_notes": "Coach should confirm standard/legacy hurdle distance.",
            }
        )
        return suggested

    # Steeple labels: 1500S, 2000S, 3000S, unusual legacy distances.
    steeple_match = re.fullmatch(r"(\d[\d,]*)s", text)
    if steeple_match:
        distance = int(steeple_match.group(1).replace(",", ""))
        standard = distance in {1500, 2000, 3000}
        suggested.update(
            {
                "suggested_canonical_event_code": f"{distance}SC",
                "suggested_canonical_event_name": (
                    f"{distance}m Steeplechase"
                ),
                "suggested_event_family": "steeplechase",
                "suggested_event_subfamily": "steeplechase",
                "suggested_mark_type": "time",
                "suggested_performance_direction": "lower_is_better",
                "suggested_standard_distance_meters": str(distance),
                "suggested_registry_disposition": (
                    "include" if standard else "coach_review"
                ),
                "suggested_development_model_eligible": (
                    "true" if standard else "false"
                ),
                "suggestion_rule": "steeple_alias",
                "suggestion_notes": (
                    "Standard steeplechase distance."
                    if standard
                    else "Legacy/nonstandard steeplechase distance."
                ),
            }
        )
        return suggested

    # Race walks.
    race_walk_match = re.fullmatch(
        r"(\d+(?:\.\d+)?)\s*(mile|miles|m|km)?\s*rw",
        text,
    )
    if race_walk_match:
        value = float(race_walk_match.group(1))
        unit = race_walk_match.group(2) or "m"
        if unit in {"mile", "miles"}:
            meters = value * 1609.344
            code = f"{str(value).rstrip('0').rstrip('.')}MI_RW"
        elif unit == "km":
            meters = value * 1000
            code = f"{str(value).rstrip('0').rstrip('.')}K_RW"
        else:
            meters = value
            code = f"{int(value) if value.is_integer() else value}M_RW"

        suggested.update(
            {
                "suggested_canonical_event_code": code,
                "suggested_canonical_event_name": f"{raw} Race Walk",
                "suggested_event_family": "race_walk",
                "suggested_event_subfamily": "race_walk",
                "suggested_mark_type": "time",
                "suggested_performance_direction": "lower_is_better",
                "suggested_standard_distance_meters": str(round(meters, 3)),
                "suggested_registry_disposition": "include",
                "suggested_development_model_eligible": "true",
                "suggestion_rule": "race_walk_alias",
                "suggestion_notes": "Coach should confirm inclusion in primary model.",
            }
        )
        return suggested

    # Yard track events.
    yard_match = re.fullmatch(r"(\d[\d,]*)y", text)
    if yard_match:
        distance = int(yard_match.group(1).replace(",", ""))
        suggested.update(
            {
                "suggested_canonical_event_code": f"{distance}Y",
                "suggested_canonical_event_name": f"{distance} Yard Run",
                "suggested_event_family": "running",
                "suggested_event_subfamily": "legacy_yard_event",
                "suggested_mark_type": "time",
                "suggested_performance_direction": "lower_is_better",
                "suggested_standard_distance_meters": str(
                    round(distance * 0.9144, 3)
                ),
                "suggested_registry_disposition": "coach_review",
                "suggested_development_model_eligible": "false",
                "suggestion_rule": "yard_distance_alias",
                "suggestion_notes": "Legacy yard event; decide whether to preserve or convert.",
            }
        )
        return suggested

    # Common named events and aliases.
    named = {
        "mile": (
            "MILE", "Mile", "running", "middle_distance",
            "time", "lower_is_better", "1609.344",
        ),
        "2 mile": (
            "2MILE", "2 Mile", "running", "distance",
            "time", "lower_is_better", "3218.688",
        ),
        "marathon": (
            "MARATHON", "Marathon", "running", "road_distance",
            "time", "lower_is_better", "42195",
        ),
        "lj": (
            "LJ", "Long Jump", "horizontal_jumps",
            "horizontal_jumps", "distance", "higher_is_better", "",
        ),
        "tj": (
            "TJ", "Triple Jump", "horizontal_jumps",
            "horizontal_jumps", "distance", "higher_is_better", "",
        ),
        "hj": (
            "HJ", "High Jump", "vertical_jumps",
            "vertical_jumps", "distance", "higher_is_better", "",
        ),
        "pv": (
            "PV", "Pole Vault", "vertical_jumps",
            "vertical_jumps", "distance", "higher_is_better", "",
        ),
        "sp": (
            "SP", "Shot Put", "throws",
            "throws", "distance", "higher_is_better", "",
        ),
        "dt": (
            "DT", "Discus Throw", "throws",
            "throws", "distance", "higher_is_better", "",
        ),
        "ht": (
            "HT", "Hammer Throw", "throws",
            "throws", "distance", "higher_is_better", "",
        ),
        "wt": (
            "WT", "Weight Throw", "throws",
            "throws", "distance", "higher_is_better", "",
        ),
        "jt": (
            "JT", "Javelin Throw", "throws",
            "throws", "distance", "higher_is_better", "",
        ),
        "hep": (
            "HEP", "Heptathlon", "combined_events",
            "combined_total", "points", "higher_is_better", "",
        ),
        "pent": (
            "PENT", "Pentathlon", "combined_events",
            "combined_total", "points", "higher_is_better", "",
        ),
        "dec": (
            "DEC", "Decathlon", "combined_events",
            "combined_total", "points", "higher_is_better", "",
        ),
    }
    if text in named:
        (
            code,
            name,
            family,
            subfamily,
            mark_type,
            direction,
            meters,
        ) = named[text]
        suggested.update(
            {
                "suggested_canonical_event_code": code,
                "suggested_canonical_event_name": name,
                "suggested_event_family": family,
                "suggested_event_subfamily": subfamily,
                "suggested_mark_type": mark_type,
                "suggested_performance_direction": direction,
                "suggested_standard_distance_meters": meters,
                "suggested_registry_disposition": "include",
                "suggested_development_model_eligible": "true",
                "suggestion_rule": "named_track_event_alias",
                "suggestion_notes": "Common track-and-field event.",
            }
        )
        return suggested

    # Keep unresolved labels visible rather than silently excluding them.
    suggested.update(
        {
            "suggested_registry_disposition": "coach_review",
            "suggested_development_model_eligible": "false",
            "suggestion_rule": "manual_track_review",
            "suggestion_notes": "No reliable automatic merge target.",
        }
    )
    return suggested


def review_priority(row: dict[str, Any]) -> str:
    count = parse_int(row.get("performance_count"))
    disposition = row.get("suggested_registry_disposition", "")
    if disposition == "coach_review" and count >= 100:
        return "urgent"
    if count >= 10_000:
        return "high"
    if count >= 1_000:
        return "medium"
    return "low"


def main() -> int:
    root = Path.cwd()
    draft_path = root / INPUT_DRAFT
    mark_path = root / INPUT_MARK_PROFILE
    output_dir = root / OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []

    print("MILESTONE 5 PHASE 1C — COACH MANUAL REVIEW PREPARATION")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Draft input: {draft_path}")
    print(f"Mark profile input: {mark_path}")
    print(f"Output: {output_dir}")

    add_check(
        checks,
        "draft_registry_exists",
        draft_path.exists(),
        draft_path.exists(),
        True,
        str(draft_path),
    )
    add_check(
        checks,
        "mark_profile_exists",
        mark_path.exists(),
        mark_path.exists(),
        True,
        str(mark_path),
    )

    if not draft_path.exists() or not mark_path.exists():
        write_csv(
            output_dir / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Missing required Phase 1 files.")
        return 1

    draft_hash_before = sha256_file(draft_path)
    mark_hash_before = sha256_file(mark_path)

    with draft_path.open(newline="", encoding="utf-8") as handle:
        draft_rows = list(csv.DictReader(handle))

    mark_examples_by_event: dict[str, list[str]] = defaultdict(list)
    with mark_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            event_id = str(row["event_id"])
            examples = row.get("example_marks", "").strip()
            if examples and len(mark_examples_by_event[event_id]) < 3:
                mark_examples_by_event[event_id].append(
                    f"{row.get('mark_shape', '')}: {examples}"
                )

    track_rows: list[dict[str, Any]] = []
    cross_country_rows: list[dict[str, Any]] = []
    relay_rows: list[dict[str, Any]] = []
    administrative_rows: list[dict[str, Any]] = []

    for row in draft_rows:
        raw_label = row["raw_event_label"]
        event_id = str(row["event_id"])
        is_xc, xc_reason = is_cross_country_course_label(raw_label)

        base = {
            "review_version": REVIEW_VERSION,
            "event_id": event_id,
            "raw_event_label": raw_label,
            "performance_count": parse_int(row.get("performance_count")),
            "athlete_count": parse_int(row.get("athlete_count")),
            "school_count": parse_int(row.get("school_count")),
            "first_season_year": row.get("first_season_year", ""),
            "last_season_year": row.get("last_season_year", ""),
            "mark_examples": " || ".join(
                mark_examples_by_event.get(event_id, [])
            ),
            "draft_event_family": row.get("event_family", ""),
            "draft_registry_disposition": row.get(
                "registry_disposition", ""
            ),
            "draft_exclusion_reason": row.get("exclusion_reason", ""),
        }

        if is_xc:
            base.update(
                {
                    "cross_country_reason": xc_reason,
                    "final_model_bucket": "separate_cross_country_model",
                    "coach_review_needed": "false",
                }
            )
            cross_country_rows.append(base)
            continue

        if is_relay_label(raw_label, row.get("event_family", "")):
            base.update(
                {
                    "suggested_registry_disposition": "exclude_relay",
                    "suggested_reason": (
                        "Relay performance cannot be attributed to one athlete."
                    ),
                    "coach_decision": "",
                    "coach_notes": "",
                }
            )
            relay_rows.append(base)
            continue

        if row.get("event_family") == "administrative":
            base.update(
                {
                    "suggested_registry_disposition": "exclude",
                    "suggested_reason": row.get("exclusion_reason", ""),
                }
            )
            administrative_rows.append(base)
            continue

        suggestion = track_alias_suggestion(raw_label, row)
        base.update(suggestion)
        base["review_priority"] = review_priority(base)
        base["coach_decision"] = ""
        base["coach_canonical_event_code"] = ""
        base["coach_canonical_event_name"] = ""
        base["coach_event_family"] = ""
        base["coach_event_subfamily"] = ""
        base["coach_mark_type"] = ""
        base["coach_performance_direction"] = ""
        base["coach_standard_distance_meters"] = ""
        base["coach_registry_disposition"] = ""
        base["coach_development_model_eligible"] = ""
        base["coach_merge_target_event_code"] = ""
        base["coach_notes"] = ""
        track_rows.append(base)

    track_rows.sort(
        key=lambda row: (
            {
                "urgent": 0,
                "high": 1,
                "medium": 2,
                "low": 3,
            }.get(row["review_priority"], 4),
            -parse_int(row["performance_count"]),
            row["raw_event_label"],
        )
    )
    relay_rows.sort(
        key=lambda row: -parse_int(row["performance_count"])
    )
    cross_country_rows.sort(
        key=lambda row: -parse_int(row["performance_count"])
    )

    group_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in track_rows:
        code = row.get("suggested_canonical_event_code", "").strip()
        group_key = code or f"UNRESOLVED::{row['raw_event_label']}"
        group_members[group_key].append(row)

    group_rows: list[dict[str, Any]] = []
    for group_key, members in group_members.items():
        representative = members[0]
        labels = sorted(
            {member["raw_event_label"] for member in members}
        )
        group_rows.append(
            {
                "group_key": group_key,
                "suggested_canonical_event_code": representative.get(
                    "suggested_canonical_event_code", ""
                ),
                "suggested_canonical_event_name": representative.get(
                    "suggested_canonical_event_name", ""
                ),
                "suggested_event_family": representative.get(
                    "suggested_event_family", ""
                ),
                "suggested_event_subfamily": representative.get(
                    "suggested_event_subfamily", ""
                ),
                "raw_label_count": len(labels),
                "raw_labels": " | ".join(labels),
                "performance_count": sum(
                    parse_int(member["performance_count"])
                    for member in members
                ),
                "athlete_count_sum_not_distinct": sum(
                    parse_int(member["athlete_count"])
                    for member in members
                ),
                "suggestion_rules": " | ".join(
                    sorted(
                        {
                            member["suggestion_rule"]
                            for member in members
                        }
                    )
                ),
                "coach_group_decision": "",
                "coach_final_canonical_event_code": "",
                "coach_final_canonical_event_name": "",
                "coach_final_event_family": "",
                "coach_final_event_subfamily": "",
                "coach_group_notes": "",
            }
        )

    group_rows.sort(
        key=lambda row: -parse_int(row["performance_count"])
    )

    track_fields = [
        "review_version",
        "review_priority",
        "event_id",
        "raw_event_label",
        "performance_count",
        "athlete_count",
        "school_count",
        "first_season_year",
        "last_season_year",
        "mark_examples",
        "draft_event_family",
        "draft_registry_disposition",
        "draft_exclusion_reason",
        "suggested_canonical_event_code",
        "suggested_canonical_event_name",
        "suggested_event_family",
        "suggested_event_subfamily",
        "suggested_mark_type",
        "suggested_performance_direction",
        "suggested_standard_distance_meters",
        "suggested_registry_disposition",
        "suggested_development_model_eligible",
        "suggestion_rule",
        "suggestion_notes",
        "coach_decision",
        "coach_canonical_event_code",
        "coach_canonical_event_name",
        "coach_event_family",
        "coach_event_subfamily",
        "coach_mark_type",
        "coach_performance_direction",
        "coach_standard_distance_meters",
        "coach_registry_disposition",
        "coach_development_model_eligible",
        "coach_merge_target_event_code",
        "coach_notes",
    ]

    cross_country_fields = [
        "review_version",
        "event_id",
        "raw_event_label",
        "performance_count",
        "athlete_count",
        "school_count",
        "first_season_year",
        "last_season_year",
        "mark_examples",
        "draft_event_family",
        "draft_registry_disposition",
        "draft_exclusion_reason",
        "cross_country_reason",
        "final_model_bucket",
        "coach_review_needed",
    ]

    relay_fields = [
        "review_version",
        "event_id",
        "raw_event_label",
        "performance_count",
        "athlete_count",
        "school_count",
        "first_season_year",
        "last_season_year",
        "mark_examples",
        "draft_event_family",
        "draft_registry_disposition",
        "draft_exclusion_reason",
        "suggested_registry_disposition",
        "suggested_reason",
        "coach_decision",
        "coach_notes",
    ]

    administrative_fields = [
        "review_version",
        "event_id",
        "raw_event_label",
        "performance_count",
        "athlete_count",
        "school_count",
        "first_season_year",
        "last_season_year",
        "mark_examples",
        "draft_event_family",
        "draft_registry_disposition",
        "draft_exclusion_reason",
        "suggested_registry_disposition",
        "suggested_reason",
    ]

    group_fields = [
        "group_key",
        "suggested_canonical_event_code",
        "suggested_canonical_event_name",
        "suggested_event_family",
        "suggested_event_subfamily",
        "raw_label_count",
        "raw_labels",
        "performance_count",
        "athlete_count_sum_not_distinct",
        "suggestion_rules",
        "coach_group_decision",
        "coach_final_canonical_event_code",
        "coach_final_canonical_event_name",
        "coach_final_event_family",
        "coach_final_event_subfamily",
        "coach_group_notes",
    ]

    write_csv(
        output_dir / "track_event_manual_review.csv",
        track_rows,
        track_fields,
    )
    write_csv(
        output_dir / "track_event_group_summary.csv",
        group_rows,
        group_fields,
    )
    write_csv(
        output_dir / "cross_country_auto_classified.csv",
        cross_country_rows,
        cross_country_fields,
    )
    write_csv(
        output_dir / "relay_manual_review.csv",
        relay_rows,
        relay_fields,
    )
    write_csv(
        output_dir / "administrative_exclusions.csv",
        administrative_rows,
        administrative_fields,
    )

    total_partitioned = (
        len(track_rows)
        + len(cross_country_rows)
        + len(relay_rows)
        + len(administrative_rows)
    )
    duplicate_partition_ids = total_partitioned - len(
        {
            row["event_id"]
            for row in (
                track_rows
                + cross_country_rows
                + relay_rows
                + administrative_rows
            )
        }
    )
    unresolved_track_groups = sum(
        group["group_key"].startswith("UNRESOLVED::")
        for group in group_rows
    )

    add_check(
        checks,
        "all_draft_labels_partitioned",
        total_partitioned == len(draft_rows),
        total_partitioned,
        len(draft_rows),
    )
    add_check(
        checks,
        "partition_event_ids_unique",
        duplicate_partition_ids == 0,
        duplicate_partition_ids,
        0,
    )
    add_check(
        checks,
        "track_review_queue_under_200_labels",
        len(track_rows) < 200,
        len(track_rows),
        "less than 200",
    )
    add_check(
        checks,
        "track_group_summary_smaller_than_label_queue",
        len(group_rows) <= len(track_rows),
        len(group_rows),
        f"at most {len(track_rows)}",
    )
    add_check(
        checks,
        "cross_country_inflation_removed_from_track_queue",
        all(
            not is_cross_country_course_label(
                row["raw_event_label"]
            )[0]
            for row in track_rows
        ),
        sum(
            is_cross_country_course_label(
                row["raw_event_label"]
            )[0]
            for row in track_rows
        ),
        0,
    )
    add_check(
        checks,
        "every_track_label_has_manual_review_fields",
        all("coach_decision" in row for row in track_rows),
        sum("coach_decision" in row for row in track_rows),
        len(track_rows),
    )

    draft_hash_after = sha256_file(draft_path)
    mark_hash_after = sha256_file(mark_path)

    add_check(
        checks,
        "draft_registry_input_unchanged",
        draft_hash_after == draft_hash_before,
        draft_hash_after,
        draft_hash_before,
    )
    add_check(
        checks,
        "mark_profile_input_unchanged",
        mark_hash_after == mark_hash_before,
        mark_hash_after,
        mark_hash_before,
    )

    write_csv(
        output_dir / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    family_counts = Counter(
        row.get("suggested_event_family", "")
        for row in track_rows
    )
    priority_counts = Counter(
        row["review_priority"]
        for row in track_rows
    )

    failed = [
        check for check in checks
        if check["status"] == "FAIL"
    ]

    report_lines = [
        "MILESTONE 5 PHASE 1C — COACH MANUAL REVIEW PACKAGE",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Review version: {REVIEW_VERSION}",
        "",
        "PARTITION COUNTS",
        "-" * 78,
        f"All draft event labels: {len(draft_rows):,}",
        f"Track/field labels for coach review: {len(track_rows):,}",
        f"Suggested track/field canonical groups: {len(group_rows):,}",
        f"Cross-country course labels removed from track queue: {len(cross_country_rows):,}",
        f"Relay labels in separate review: {len(relay_rows):,}",
        f"Administrative exclusions: {len(administrative_rows):,}",
        f"Unresolved track/field suggestion groups: {unresolved_track_groups:,}",
        "",
        "TRACK REVIEW PRIORITIES",
        "-" * 78,
    ]

    for key in ("urgent", "high", "medium", "low"):
        report_lines.append(f"{key}: {priority_counts.get(key, 0):,}")

    report_lines.extend(
        [
            "",
            "SUGGESTED TRACK EVENT FAMILIES",
            "-" * 78,
        ]
    )
    for family, count in sorted(family_counts.items()):
        report_lines.append(
            f"{family or '[blank]'}: {count:,}"
        )

    report_lines.extend(
        [
            "",
            "REVIEW WORKFLOW",
            "-" * 78,
            "1. Start with track_event_group_summary.csv.",
            "2. Approve, rename, merge, or reject each suggested group.",
            "3. Use track_event_manual_review.csv for label-level exceptions.",
            "4. Review relays separately; they remain excluded from individual scoring.",
            "5. Cross-country labels are preserved outside the track model.",
            "",
            "No event-registry decision is finalized by this script.",
            "",
            "HARD CHECK SUMMARY",
            "-" * 78,
            f"PASS: {sum(c['status'] == 'PASS' for c in checks)}",
            f"FAIL: {len(failed)}",
            "",
            "PHASE GATE",
            "-" * 78,
            (
                "PASS — Coach-sized manual-review package is ready."
                if not failed
                else "FAIL — Correct package-validation errors."
            ),
        ]
    )

    (output_dir / "coach_review_report.txt").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Track/field labels for coach review: {len(track_rows):,}")
    print(f"Suggested canonical groups: {len(group_rows):,}")
    print(f"Cross-country labels separated: {len(cross_country_rows):,}")
    print(f"Relay labels separated: {len(relay_rows):,}")
    print(f"Administrative exclusions: {len(administrative_rows):,}")
    print()
    print("Created:")
    for filename in [
        "coach_review_report.txt",
        "track_event_group_summary.csv",
        "track_event_manual_review.csv",
        "relay_manual_review.csv",
        "cross_country_auto_classified.csv",
        "administrative_exclusions.csv",
        "hard_checks.csv",
    ]:
        print(f"  {output_dir / filename}")

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
    print("Stop here for coach review; do not freeze the final registry yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
