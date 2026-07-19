#!/usr/bin/env python3
"""
Milestone 5 Phase 1B — Draft Event Registry

Consumes the Phase 1A event profile and creates a complete, versioned draft
registry for every canonical event label. Standard events are auto-resolved
with explicit rules. Ambiguous, unusual, or nonstandard events are preserved
in a focused review queue rather than silently dropped.

This script does not modify any DuckDB input.
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


REGISTRY_VERSION = "event_registry_draft_v1"
RULESET_VERSION = "event_rules_v1"

PROFILE_RELATIVE_PATH = Path(
    "data/processed/milestone5/event_registry_v1/profile_v1/event_value_profile.csv"
)
COVERAGE_RELATIVE_PATH = Path(
    "data/processed/milestone5/event_registry_v1/profile_v1/"
    "event_coverage_by_gender_season_year.csv"
)
OUTPUT_RELATIVE_DIR = Path(
    "data/processed/milestone5/event_registry_v1/draft_v1"
)

FIELD_EVENTS: dict[str, tuple[str, str, str]] = {
    "lj": ("LJ", "Long Jump", "horizontal_jumps"),
    "long jump": ("LJ", "Long Jump", "horizontal_jumps"),
    "tj": ("TJ", "Triple Jump", "horizontal_jumps"),
    "triple jump": ("TJ", "Triple Jump", "horizontal_jumps"),
    "hj": ("HJ", "High Jump", "vertical_jumps"),
    "high jump": ("HJ", "High Jump", "vertical_jumps"),
    "pv": ("PV", "Pole Vault", "vertical_jumps"),
    "pole vault": ("PV", "Pole Vault", "vertical_jumps"),
    "sp": ("SP", "Shot Put", "throws"),
    "shot put": ("SP", "Shot Put", "throws"),
    "dt": ("DT", "Discus Throw", "throws"),
    "discus": ("DT", "Discus Throw", "throws"),
    "discus throw": ("DT", "Discus Throw", "throws"),
    "ht": ("HT", "Hammer Throw", "throws"),
    "hammer": ("HT", "Hammer Throw", "throws"),
    "hammer throw": ("HT", "Hammer Throw", "throws"),
    "wt": ("WT", "Weight Throw", "throws"),
    "weight": ("WT", "Weight Throw", "throws"),
    "weight throw": ("WT", "Weight Throw", "throws"),
    "jt": ("JT", "Javelin Throw", "throws"),
    "javelin": ("JT", "Javelin Throw", "throws"),
    "javelin throw": ("JT", "Javelin Throw", "throws"),
}

COMBINED_EVENTS: dict[str, tuple[str, str]] = {
    "hep": ("HEP", "Heptathlon"),
    "heptathlon": ("HEP", "Heptathlon"),
    "pent": ("PENT", "Pentathlon"),
    "pentathlon": ("PENT", "Pentathlon"),
    "dec": ("DEC", "Decathlon"),
    "decathlon": ("DEC", "Decathlon"),
}

STANDARD_METRIC_RUNNING_DISTANCES = {
    30, 40, 50, 55, 60, 100, 110, 150, 200, 300, 400, 500, 600,
    800, 1000, 1200, 1500, 2000, 3000, 5000, 10000, 20000,
}
HISTORICAL_OR_DEVELOPMENTAL_DISTANCES = {
    1600, 3200,
}
STANDARD_HURDLE_DISTANCES = {
    55, 60, 100, 110, 200, 300, 400,
}
STANDARD_STEEPLE_DISTANCES = {
    1500, 2000, 3000,
}
STANDARD_RACE_WALK_DISTANCES = {
    1500, 3000, 5000, 10000, 20000,
}
STANDARD_YARD_DISTANCES = {
    40, 50, 55, 60, 100, 110, 220, 300, 400, 440, 600, 800, 880,
    1000, 1320, 1760,
}

RELAY_KEYWORDS = (
    "relay", "dmr", "smr", "shr", "distance medley", "sprint medley",
)
CROSS_COUNTRY_TOKENS = (
    "cross country", "cross-country", "xc",
)
ADMINISTRATIVE_TOKENS = (
    "team score", "team points", "overall score", "other", "unknown",
    "administrative",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, block_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(block_size):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    text = value.strip().lower()
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*-\s*", "-", text)
    return text


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def bool_text(value: bool) -> str:
    return "true" if value else "false"


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


def clean_numeric_label(text: str) -> str:
    return text.replace(",", "").strip()


def canonical_distance_code(
    distance: int,
    suffix: str = "M",
) -> str:
    return f"{distance}{suffix}"


def season_context(
    coverage_by_event: dict[str, dict[str, int]],
    event_id: str,
) -> tuple[set[str], int, int]:
    values = coverage_by_event.get(event_id, {})
    season_types = set(values)
    total = sum(values.values())
    xc = sum(
        count
        for season_type, count in values.items()
        if any(token in normalize_text(season_type) for token in CROSS_COUNTRY_TOKENS)
    )
    return season_types, total, xc


def is_cross_country_context(
    coverage_by_event: dict[str, dict[str, int]],
    event_id: str,
) -> tuple[bool, float]:
    _types, total, xc = season_context(coverage_by_event, event_id)
    share = (xc / total) if total else 0.0
    return share >= 0.50, share


def base_result(row: dict[str, str]) -> dict[str, Any]:
    return {
        "registry_version": REGISTRY_VERSION,
        "ruleset_version": RULESET_VERSION,
        "event_id": row["event_id"],
        "raw_event_label": row["event"],
        "normalized_event_text": normalize_text(row["event"]),
        "canonical_event_code": "",
        "canonical_event_name": "",
        "event_family": "",
        "event_subfamily": "",
        "mark_type": "",
        "performance_direction": "",
        "standard_distance_meters": "",
        "source_unit": "",
        "relay_flag": "false",
        "combined_event_flag": "false",
        "cross_country_flag": "false",
        "indoor_eligible": "unknown",
        "outdoor_eligible": "unknown",
        "development_model_eligible": "false",
        "registry_disposition": "",
        "exclusion_reason": "",
        "classification_confidence": "",
        "classification_rule_id": "",
        "review_status": "",
        "review_notes": "",
        "performance_count": parse_int(row.get("performance_count")),
        "athlete_count": parse_int(row.get("athlete_count")),
        "school_count": parse_int(row.get("school_count")),
        "first_season_year": row.get("first_season_year", ""),
        "last_season_year": row.get("last_season_year", ""),
        "stint_mapped_count": parse_int(row.get("stint_mapped_count")),
    }


def finalize_standard(
    result: dict[str, Any],
    *,
    code: str,
    name: str,
    family: str,
    subfamily: str,
    mark_type: str,
    direction: str,
    rule_id: str,
    distance_meters: int | float | str = "",
    source_unit: str = "",
    indoor: str = "true",
    outdoor: str = "true",
    combined: bool = False,
    cross_country: bool = False,
    confidence: str = "high",
    notes: str = "",
) -> dict[str, Any]:
    result.update(
        {
            "canonical_event_code": code,
            "canonical_event_name": name,
            "event_family": family,
            "event_subfamily": subfamily,
            "mark_type": mark_type,
            "performance_direction": direction,
            "standard_distance_meters": distance_meters,
            "source_unit": source_unit,
            "combined_event_flag": bool_text(combined),
            "cross_country_flag": bool_text(cross_country),
            "indoor_eligible": indoor,
            "outdoor_eligible": outdoor,
            "development_model_eligible": "true",
            "registry_disposition": "include",
            "classification_confidence": confidence,
            "classification_rule_id": rule_id,
            "review_status": "auto_resolved",
            "review_notes": notes,
        }
    )
    return result


def finalize_excluded(
    result: dict[str, Any],
    *,
    family: str,
    disposition: str,
    reason: str,
    rule_id: str,
    code: str = "",
    name: str = "",
    mark_type: str = "",
    direction: str = "",
    relay: bool = False,
    cross_country: bool = False,
    confidence: str = "high",
    review_status: str = "auto_resolved",
    notes: str = "",
) -> dict[str, Any]:
    result.update(
        {
            "canonical_event_code": code,
            "canonical_event_name": name,
            "event_family": family,
            "mark_type": mark_type,
            "performance_direction": direction,
            "relay_flag": bool_text(relay),
            "cross_country_flag": bool_text(cross_country),
            "development_model_eligible": "false",
            "registry_disposition": disposition,
            "exclusion_reason": reason,
            "classification_confidence": confidence,
            "classification_rule_id": rule_id,
            "review_status": review_status,
            "review_notes": notes,
        }
    )
    return result


def classify_event(
    row: dict[str, str],
    coverage_by_event: dict[str, dict[str, int]],
) -> dict[str, Any]:
    result = base_result(row)
    text = result["normalized_event_text"]
    event_id = str(result["event_id"])

    xc_context, xc_share = is_cross_country_context(
        coverage_by_event,
        event_id,
    )

    if not text:
        return finalize_excluded(
            result,
            family="missing",
            disposition="exclude",
            reason="blank_event_label",
            rule_id="R001_BLANK",
        )

    if any(token == text or token in text for token in ADMINISTRATIVE_TOKENS):
        return finalize_excluded(
            result,
            family="administrative",
            disposition="exclude",
            reason="non_performance_or_unclassified_source_event",
            rule_id="R002_ADMIN",
            confidence="medium",
        )

    relay_match = (
        text.startswith("4x")
        or any(token in text for token in RELAY_KEYWORDS)
    )
    if relay_match:
        return finalize_excluded(
            result,
            family="relays",
            disposition="exclude_relay",
            reason="relay_results_not_attributable_to_one_athlete",
            rule_id="R010_RELAY",
            code=f"RELAY_{re.sub(r'[^A-Z0-9]+', '_', row['event'].upper()).strip('_')}",
            name=row["event"],
            mark_type="time",
            direction="lower_is_better",
            relay=True,
        )

    if text in FIELD_EVENTS:
        code, name, family = FIELD_EVENTS[text]
        return finalize_standard(
            result,
            code=code,
            name=name,
            family=family,
            subfamily=family,
            mark_type="distance",
            direction="higher_is_better",
            rule_id="R020_FIELD_EXACT",
            source_unit="distance",
            indoor="true",
            outdoor="true",
        )

    if text in COMBINED_EVENTS:
        code, name = COMBINED_EVENTS[text]
        return finalize_standard(
            result,
            code=code,
            name=name,
            family="combined_events",
            subfamily="combined_total",
            mark_type="points",
            direction="higher_is_better",
            rule_id="R030_COMBINED_EXACT",
            source_unit="points",
            indoor="true" if code == "PENT" else "conditional",
            outdoor="true" if code in {"HEP", "DEC"} else "conditional",
            combined=True,
        )

    if text == "mile":
        return finalize_standard(
            result,
            code="MILE",
            name="Mile",
            family="running",
            subfamily="middle_distance",
            mark_type="time",
            direction="lower_is_better",
            rule_id="R040_MILE",
            distance_meters=1609.344,
            source_unit="mile",
            indoor="true",
            outdoor="true",
        )

    if text == "marathon":
        return finalize_standard(
            result,
            code="MARATHON",
            name="Marathon",
            family="running",
            subfamily="road_distance",
            mark_type="time",
            direction="lower_is_better",
            rule_id="R041_MARATHON",
            distance_meters=42195,
            source_unit="meters",
            indoor="false",
            outdoor="true",
            confidence="medium",
            notes="Preserved as an individual event; later sample rules may exclude it.",
        )

    racewalk_match = re.fullmatch(
        r"(?P<distance>\d+(?:\.\d+)?)\s*(?P<unit>mile|miles|m|km)?\s*rw",
        clean_numeric_label(text),
    )
    if racewalk_match:
        distance_value = float(racewalk_match.group("distance"))
        unit = racewalk_match.group("unit") or "m"
        if unit in {"mile", "miles"}:
            meters = distance_value * 1609.344
            code_distance = str(distance_value).rstrip("0").rstrip(".") + "MI"
        elif unit == "km":
            meters = distance_value * 1000
            code_distance = str(distance_value).rstrip("0").rstrip(".") + "K"
        else:
            meters = distance_value
            code_distance = str(int(distance_value)) if distance_value.is_integer() else str(distance_value)

        standard = int(round(meters)) in STANDARD_RACE_WALK_DISTANCES or unit in {
            "mile", "miles"
        }
        if standard:
            return finalize_standard(
                result,
                code=f"{code_distance}RW",
                name=f"{row['event']} Race Walk",
                family="race_walk",
                subfamily="race_walk",
                mark_type="time",
                direction="lower_is_better",
                rule_id="R050_RACE_WALK",
                distance_meters=round(meters, 3),
                source_unit=unit,
                indoor="conditional",
                outdoor="true",
            )

        return finalize_excluded(
            result,
            family="race_walk",
            disposition="review",
            reason="nonstandard_race_walk_distance",
            rule_id="R051_RACE_WALK_NONSTANDARD",
            code=f"{code_distance}RW",
            name=f"{row['event']} Race Walk",
            mark_type="time",
            direction="lower_is_better",
            confidence="medium",
            review_status="manual_review_required",
        )

    steeple_match = re.fullmatch(
        r"(?P<distance>\d[\d,]*)\s*s",
        text,
    )
    if steeple_match:
        distance = int(clean_numeric_label(steeple_match.group("distance")))
        if distance in STANDARD_STEEPLE_DISTANCES:
            return finalize_standard(
                result,
                code=f"{distance}SC",
                name=f"{distance}m Steeplechase",
                family="steeplechase",
                subfamily="steeplechase",
                mark_type="time",
                direction="lower_is_better",
                rule_id="R060_STEEPLE_STANDARD",
                distance_meters=distance,
                source_unit="meters",
                indoor="false",
                outdoor="true",
            )

        return finalize_excluded(
            result,
            family="steeplechase",
            disposition="review",
            reason="nonstandard_steeplechase_distance",
            rule_id="R061_STEEPLE_NONSTANDARD",
            code=f"{distance}SC",
            name=f"{distance}m Steeplechase",
            mark_type="time",
            direction="lower_is_better",
            confidence="medium",
            review_status="manual_review_required",
        )

    hurdle_match = re.fullmatch(
        r"(?P<distance>\d[\d,]*)(?P<yards>y)?h",
        text,
    )
    if hurdle_match:
        distance = int(clean_numeric_label(hurdle_match.group("distance")))
        yards = bool(hurdle_match.group("yards"))
        standard = (
            distance in STANDARD_HURDLE_DISTANCES
            if not yards
            else distance in {55, 60, 110, 120, 220, 300, 440}
        )
        unit = "yards" if yards else "meters"
        meters = round(distance * 0.9144, 3) if yards else distance
        code = f"{distance}{'Y' if yards else ''}H"

        if standard:
            return finalize_standard(
                result,
                code=code,
                name=f"{distance}{'y' if yards else 'm'} Hurdles",
                family="hurdles",
                subfamily="hurdles",
                mark_type="time",
                direction="lower_is_better",
                rule_id="R070_HURDLE_STANDARD",
                distance_meters=meters,
                source_unit=unit,
                indoor="true" if distance <= 60 else "conditional",
                outdoor="true" if distance >= 100 else "conditional",
            )

        return finalize_excluded(
            result,
            family="hurdles",
            disposition="review",
            reason="nonstandard_hurdle_distance",
            rule_id="R071_HURDLE_NONSTANDARD",
            code=code,
            name=f"{distance}{'y' if yards else 'm'} Hurdles",
            mark_type="time",
            direction="lower_is_better",
            confidence="medium",
            review_status="manual_review_required",
        )

    k_match = re.fullmatch(r"(?P<distance>\d+(?:\.\d+)?)\s*k", text)
    if k_match:
        km = float(k_match.group("distance"))
        meters = km * 1000
        code_value = str(km).rstrip("0").rstrip(".")
        return finalize_excluded(
            result,
            family="cross_country" if xc_context else "road_or_cross_country",
            disposition="separate_cross_country_model",
            reason="cross_country_course_times_not_comparable_to_track_times",
            rule_id="R080_K_DISTANCE",
            code=f"{code_value}K_XC",
            name=f"{code_value}K Cross Country",
            mark_type="time",
            direction="lower_is_better",
            cross_country=True,
            confidence="high" if xc_context else "medium",
            review_status="auto_resolved" if xc_context else "manual_review_required",
            notes=f"Cross-country season share: {xc_share:.3f}",
        )

    yard_match = re.fullmatch(r"(?P<distance>\d[\d,]*)y", text)
    if yard_match:
        distance = int(clean_numeric_label(yard_match.group("distance")))
        meters = round(distance * 0.9144, 3)
        if xc_context:
            return finalize_excluded(
                result,
                family="cross_country",
                disposition="separate_cross_country_model",
                reason="cross_country_course_times_not_comparable_to_track_times",
                rule_id="R081_XC_YARD_CONTEXT",
                code=f"{distance}Y_XC",
                name=f"{distance} Yard Cross Country",
                mark_type="time",
                direction="lower_is_better",
                cross_country=True,
                notes=f"Cross-country season share: {xc_share:.3f}",
            )

        if distance in STANDARD_YARD_DISTANCES:
            return finalize_standard(
                result,
                code=f"{distance}Y",
                name=f"{distance} Yard Run",
                family="running",
                subfamily="legacy_yard_event",
                mark_type="time",
                direction="lower_is_better",
                rule_id="R090_YARD_STANDARD",
                distance_meters=meters,
                source_unit="yards",
                indoor="conditional",
                outdoor="conditional",
                confidence="medium",
                notes="Historical yard event preserved as its own event.",
            )

        return finalize_excluded(
            result,
            family="running",
            disposition="review",
            reason="nonstandard_yard_distance",
            rule_id="R091_YARD_NONSTANDARD",
            code=f"{distance}Y",
            name=f"{distance} Yard Run",
            mark_type="time",
            direction="lower_is_better",
            confidence="medium",
            review_status="manual_review_required",
        )

    numeric_match = re.fullmatch(r"\d[\d,]*", text)
    if numeric_match:
        distance = int(clean_numeric_label(text))

        if xc_context:
            return finalize_excluded(
                result,
                family="cross_country",
                disposition="separate_cross_country_model",
                reason="cross_country_course_times_not_comparable_to_track_times",
                rule_id="R100_XC_NUMERIC_CONTEXT",
                code=f"{distance}M_XC",
                name=f"{distance}m Cross Country",
                mark_type="time",
                direction="lower_is_better",
                cross_country=True,
                confidence="high",
                notes=f"Cross-country season share: {xc_share:.3f}",
            )

        if distance in STANDARD_METRIC_RUNNING_DISTANCES:
            if distance <= 400:
                subfamily = "sprints"
            elif distance <= 1200:
                subfamily = "middle_distance"
            else:
                subfamily = "distance"

            return finalize_standard(
                result,
                code=canonical_distance_code(distance),
                name=f"{distance}m",
                family="running",
                subfamily=subfamily,
                mark_type="time",
                direction="lower_is_better",
                rule_id="R101_METRIC_STANDARD",
                distance_meters=distance,
                source_unit="meters",
                indoor="true" if distance <= 5000 else "conditional",
                outdoor="true",
            )

        if distance in HISTORICAL_OR_DEVELOPMENTAL_DISTANCES:
            return finalize_standard(
                result,
                code=canonical_distance_code(distance),
                name=f"{distance}m",
                family="running",
                subfamily="developmental_distance",
                mark_type="time",
                direction="lower_is_better",
                rule_id="R102_METRIC_DEVELOPMENTAL",
                distance_meters=distance,
                source_unit="meters",
                indoor="conditional",
                outdoor="conditional",
                confidence="medium",
                notes="Valid individual event but not a primary NCAA championship event.",
            )

        return finalize_excluded(
            result,
            family="running_or_course_distance",
            disposition="review",
            reason="nonstandard_numeric_distance_without_clear_context",
            rule_id="R103_NUMERIC_NONSTANDARD",
            code=canonical_distance_code(distance),
            name=f"{distance}m",
            mark_type="time",
            direction="lower_is_better",
            confidence="low",
            review_status="manual_review_required",
            notes=f"Cross-country season share: {xc_share:.3f}",
        )

    if xc_context:
        return finalize_excluded(
            result,
            family="cross_country",
            disposition="separate_cross_country_model",
            reason="cross_country_course_times_not_comparable_to_track_times",
            rule_id="R110_XC_CONTEXT_FALLBACK",
            code=f"XC_{re.sub(r'[^A-Z0-9]+', '_', row['event'].upper()).strip('_')}",
            name=row["event"],
            mark_type="time",
            direction="lower_is_better",
            cross_country=True,
            confidence="medium",
            review_status="manual_review_required",
            notes=f"Cross-country season share: {xc_share:.3f}",
        )

    return finalize_excluded(
        result,
        family="unclassified",
        disposition="review",
        reason="no_curated_event_rule_matched",
        rule_id="R999_UNCLASSIFIED",
        confidence="low",
        review_status="manual_review_required",
    )


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


def main() -> int:
    root = Path.cwd()
    profile_path = root / PROFILE_RELATIVE_PATH
    coverage_path = root / COVERAGE_RELATIVE_PATH
    output_dir = root / OUTPUT_RELATIVE_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    print("MILESTONE 5 PHASE 1B — DRAFT EVENT REGISTRY")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Profile input: {profile_path}")
    print(f"Coverage input: {coverage_path}")
    print(f"Output: {output_dir}")

    checks: list[dict[str, Any]] = []

    add_check(
        checks,
        "event_profile_exists",
        profile_path.exists(),
        profile_path.exists(),
        True,
        str(profile_path),
    )
    add_check(
        checks,
        "event_coverage_exists",
        coverage_path.exists(),
        coverage_path.exists(),
        True,
        str(coverage_path),
    )

    if not profile_path.exists() or not coverage_path.exists():
        write_csv(
            output_dir / "hard_checks.csv",
            checks,
            ["check_name", "status", "observed", "expected", "details"],
        )
        print("PHASE GATE: FAIL — Missing Phase 1A outputs.")
        return 1

    profile_sha_before = sha256_file(profile_path)
    coverage_sha_before = sha256_file(coverage_path)

    with profile_path.open(newline="", encoding="utf-8") as handle:
        profile_rows = list(csv.DictReader(handle))

    coverage_by_event: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    with coverage_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            event_id = str(row["event_id"])
            season_type = row.get("season_type") or ""
            coverage_by_event[event_id][season_type] += parse_int(
                row.get("performance_count")
            )

    registry_rows = [
        classify_event(row, coverage_by_event)
        for row in profile_rows
    ]

    registry_fields = [
        "registry_version",
        "ruleset_version",
        "event_id",
        "raw_event_label",
        "normalized_event_text",
        "canonical_event_code",
        "canonical_event_name",
        "event_family",
        "event_subfamily",
        "mark_type",
        "performance_direction",
        "standard_distance_meters",
        "source_unit",
        "relay_flag",
        "combined_event_flag",
        "cross_country_flag",
        "indoor_eligible",
        "outdoor_eligible",
        "development_model_eligible",
        "registry_disposition",
        "exclusion_reason",
        "classification_confidence",
        "classification_rule_id",
        "review_status",
        "review_notes",
        "performance_count",
        "athlete_count",
        "school_count",
        "first_season_year",
        "last_season_year",
        "stint_mapped_count",
    ]

    review_rows = [
        row
        for row in registry_rows
        if row["review_status"] == "manual_review_required"
    ]

    override_fields = [
        "event_id",
        "raw_event_label",
        "override_canonical_event_code",
        "override_canonical_event_name",
        "override_event_family",
        "override_event_subfamily",
        "override_mark_type",
        "override_performance_direction",
        "override_standard_distance_meters",
        "override_source_unit",
        "override_indoor_eligible",
        "override_outdoor_eligible",
        "override_development_model_eligible",
        "override_registry_disposition",
        "override_exclusion_reason",
        "review_decision",
        "review_notes",
    ]
    override_rows = [
        {
            "event_id": row["event_id"],
            "raw_event_label": row["raw_event_label"],
            "override_canonical_event_code": "",
            "override_canonical_event_name": "",
            "override_event_family": "",
            "override_event_subfamily": "",
            "override_mark_type": "",
            "override_performance_direction": "",
            "override_standard_distance_meters": "",
            "override_source_unit": "",
            "override_indoor_eligible": "",
            "override_outdoor_eligible": "",
            "override_development_model_eligible": "",
            "override_registry_disposition": "",
            "override_exclusion_reason": "",
            "review_decision": "",
            "review_notes": "",
        }
        for row in review_rows
    ]

    disposition_counts = Counter(
        row["registry_disposition"]
        for row in registry_rows
    )
    family_counts = Counter(
        row["event_family"]
        for row in registry_rows
    )
    rule_counts = Counter(
        row["classification_rule_id"]
        for row in registry_rows
    )

    summary_rows: list[dict[str, Any]] = []
    for value, count in sorted(disposition_counts.items()):
        summary_rows.append(
            {
                "summary_type": "registry_disposition",
                "value": value,
                "event_label_count": count,
            }
        )
    for value, count in sorted(family_counts.items()):
        summary_rows.append(
            {
                "summary_type": "event_family",
                "value": value,
                "event_label_count": count,
            }
        )
    for value, count in sorted(rule_counts.items()):
        summary_rows.append(
            {
                "summary_type": "classification_rule_id",
                "value": value,
                "event_label_count": count,
            }
        )

    duplicate_event_ids = len(registry_rows) - len(
        {row["event_id"] for row in registry_rows}
    )
    blank_dispositions = sum(
        not row["registry_disposition"]
        for row in registry_rows
    )
    blank_families = sum(
        not row["event_family"]
        for row in registry_rows
    )
    included_missing_semantics = sum(
        row["registry_disposition"] == "include"
        and (
            not row["canonical_event_code"]
            or not row["canonical_event_name"]
            or not row["mark_type"]
            or row["performance_direction"] not in {
                "lower_is_better",
                "higher_is_better",
            }
        )
        for row in registry_rows
    )
    review_rows_without_reason = sum(
        row["review_status"] == "manual_review_required"
        and not row["exclusion_reason"]
        for row in registry_rows
    )

    add_check(
        checks,
        "registry_row_count_matches_profile",
        len(registry_rows) == len(profile_rows),
        len(registry_rows),
        len(profile_rows),
    )
    add_check(
        checks,
        "registry_event_ids_unique",
        duplicate_event_ids == 0,
        duplicate_event_ids,
        0,
    )
    add_check(
        checks,
        "every_event_has_disposition",
        blank_dispositions == 0,
        blank_dispositions,
        0,
    )
    add_check(
        checks,
        "every_event_has_family",
        blank_families == 0,
        blank_families,
        0,
    )
    add_check(
        checks,
        "included_events_have_complete_semantics",
        included_missing_semantics == 0,
        included_missing_semantics,
        0,
    )
    add_check(
        checks,
        "review_rows_have_explicit_reason",
        review_rows_without_reason == 0,
        review_rows_without_reason,
        0,
    )
    add_check(
        checks,
        "review_queue_is_focused",
        len(review_rows) < len(registry_rows),
        len(review_rows),
        f"less than {len(registry_rows)}",
        "The draft must auto-resolve at least one event.",
    )

    profile_sha_after = sha256_file(profile_path)
    coverage_sha_after = sha256_file(coverage_path)

    add_check(
        checks,
        "event_profile_input_unchanged",
        profile_sha_before == profile_sha_after,
        profile_sha_after,
        profile_sha_before,
    )
    add_check(
        checks,
        "event_coverage_input_unchanged",
        coverage_sha_before == coverage_sha_after,
        coverage_sha_after,
        coverage_sha_before,
    )

    write_csv(
        output_dir / "event_registry_draft.csv",
        registry_rows,
        registry_fields,
    )
    write_csv(
        output_dir / "event_registry_review_queue.csv",
        review_rows,
        registry_fields,
    )
    write_csv(
        output_dir / "event_registry_overrides_template.csv",
        override_rows,
        override_fields,
    )
    write_csv(
        output_dir / "event_registry_summary.csv",
        summary_rows,
        ["summary_type", "value", "event_label_count"],
    )
    write_csv(
        output_dir / "hard_checks.csv",
        checks,
        ["check_name", "status", "observed", "expected", "details"],
    )

    fail_count = sum(check["status"] == "FAIL" for check in checks)
    auto_resolved = len(registry_rows) - len(review_rows)
    included = sum(
        row["registry_disposition"] == "include"
        for row in registry_rows
    )
    relays = sum(row["relay_flag"] == "true" for row in registry_rows)
    cross_country = sum(
        row["cross_country_flag"] == "true"
        for row in registry_rows
    )

    report_lines = [
        "MILESTONE 5 PHASE 1B — DRAFT EVENT REGISTRY",
        "=" * 78,
        f"Finished UTC: {utc_now()}",
        f"Registry version: {REGISTRY_VERSION}",
        f"Ruleset version: {RULESET_VERSION}",
        "",
        "INPUTS",
        "-" * 78,
        f"Event profile: {profile_path}",
        f"Event profile SHA-256: {profile_sha_before}",
        f"Coverage profile: {coverage_path}",
        f"Coverage profile SHA-256: {coverage_sha_before}",
        "",
        "REGISTRY SCALE",
        "-" * 78,
        f"Profiled canonical labels: {len(profile_rows):,}",
        f"Draft registry rows: {len(registry_rows):,}",
        f"Auto-resolved rows: {auto_resolved:,}",
        f"Manual-review rows: {len(review_rows):,}",
        f"Included individual/combined events: {included:,}",
        f"Relay labels excluded: {relays:,}",
        f"Cross-country labels separated: {cross_country:,}",
        "",
        "DISPOSITION COUNTS",
        "-" * 78,
    ]

    for value, count in sorted(disposition_counts.items()):
        report_lines.append(f"{value}: {count:,}")

    report_lines.extend(
        [
            "",
            "IMPORTANT",
            "-" * 78,
            "This is a draft registry, not the frozen Phase 1 registry.",
            "Manual-review rows must be resolved through the override file.",
            "No raw event label has been silently discarded.",
            "Relays are preserved but excluded from individual development scoring.",
            "Cross-country events are preserved for a separate model.",
            "",
            "HARD CHECK SUMMARY",
            "-" * 78,
            f"PASS: {sum(c['status'] == 'PASS' for c in checks)}",
            f"FAIL: {fail_count}",
            "",
            "PHASE GATE",
            "-" * 78,
            (
                "PASS — Draft registry and focused review queue are ready."
                if fail_count == 0
                else "FAIL — Correct draft-registry validation errors."
            ),
            "",
            "OUTPUTS",
            "-" * 78,
            "event_registry_draft.csv",
            "event_registry_review_queue.csv",
            "event_registry_overrides_template.csv",
            "event_registry_summary.csv",
            "hard_checks.csv",
        ]
    )

    (output_dir / "event_registry_report.txt").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"Draft registry rows: {len(registry_rows):,}")
    print(f"Auto-resolved rows: {auto_resolved:,}")
    print(f"Manual-review rows: {len(review_rows):,}")
    print()
    print("Created:")
    for filename in [
        "event_registry_report.txt",
        "event_registry_draft.csv",
        "event_registry_review_queue.csv",
        "event_registry_overrides_template.csv",
        "event_registry_summary.csv",
        "hard_checks.csv",
    ]:
        print(f"  {output_dir / filename}")

    if fail_count:
        print()
        print("PHASE GATE: FAIL")
        return 1

    print()
    print("PHASE GATE: PASS")
    print("Stop here and review the manual-review queue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
