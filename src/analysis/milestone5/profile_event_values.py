#!/usr/bin/env python3
"""Milestone 5 Phase 1A: read-only event-value profiling."""
from __future__ import annotations

import csv
import hashlib
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb

EXPECTED_CANONICAL_PERFORMANCES = 6_376_667
EXPECTED_STINT_MAPPED_PERFORMANCES = 6_376_505
EXPECTED_RAW_EVENT_LABELS = 378
OUTPUT_VERSION = "profile_v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(block_size):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_row(name: str, path: Path, stage: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "database_name": name,
        "stage": stage,
        "path": str(path),
        "size_bytes": stat.st_size,
        "mtime_epoch_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_event_text(value: str | None) -> str:
    text = "" if value is None else value.strip().lower()
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s*-\s*", "-", text)


def candidate_family(event: str) -> tuple[str, str]:
    t = normalize_event_text(event)
    if not t:
        return "missing", "blank label"
    if re.search(r"\brelay\b|4x\d+|distance medley|sprint medley|\bdmr\b|\bsmr\b", t):
        return "relay", "relay/medley keyword"
    if re.search(r"cross country|\bxc\b", t):
        return "cross_country_candidate", "cross-country keyword"
    if re.search(r"decathlon|heptathlon|pentathlon|triathlon", t):
        return "combined_events", "combined-event keyword"
    if re.search(r"race ?walk|\bwalk\b", t):
        return "race_walk", "walk keyword"
    if "steeple" in t:
        return "steeplechase", "steeple keyword"
    if "hurdle" in t:
        return "hurdles", "hurdle keyword"
    if re.search(r"pole vault|high jump", t):
        return "vertical_jumps", "vertical-jump keyword"
    if re.search(r"long jump|triple jump", t):
        return "horizontal_jumps", "horizontal-jump keyword"
    if re.search(r"shot put|discus|hammer|javelin|weight throw", t):
        return "throws", "throw keyword"
    if re.search(r"\b\d+(?:\.\d+)?\s*(?:m|meter|metre|yd|yard|mile|km|k)\b", t):
        return "running_event_candidate", "distance-unit keyword"
    if re.search(r"team score|overall|administrative|unknown", t):
        return "administrative_candidate", "administrative keyword"
    return "unclassified", "manual review required"


def candidate_mark_type(event: str) -> tuple[str, str]:
    t = normalize_event_text(event)
    if re.search(r"decathlon|heptathlon|pentathlon|triathlon", t):
        return "points", "combined-event keyword"
    if re.search(r"pole vault|high jump|long jump|triple jump|shot put|discus|hammer|javelin|weight throw", t):
        return "distance", "field-event keyword"
    if re.search(r"relay|medley|steeple|hurdle|walk|\b\d+(?:\.\d+)?\s*(?:m|meter|metre|yd|yard|mile|km|k)\b", t):
        return "time", "running-event keyword"
    return "unknown", "manual review required"


def mark_shape(mark: str | None) -> str:
    if mark is None or not str(mark).strip():
        return "blank"
    value = str(mark).strip().upper()
    if value in {"DNF", "DNS", "DQ", "DSQ", "NM", "NH", "NT", "SCR", "FS", "FOUL"}:
        return f"status:{value}"
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
        return "plain_numeric"
    if re.fullmatch(r"\d{1,2}:\d{2}(?:\.\d+)?", value):
        return "minutes_seconds"
    if re.fullmatch(r"\d{1,2}:\d{2}:\d{2}(?:\.\d+)?", value):
        return "hours_minutes_seconds"
    if re.search(r"\d+\s*['′]\s*\d+(?:\.\d+)?\s*[\"″]?", value):
        return "feet_inches"
    if re.search(r"\d+(?:\.\d+)?\s*M\b", value):
        return "metric_with_unit"
    if re.search(r"[A-Z*+#@()]", value):
        return "annotated_or_symbolic"
    return "other"


def add_check(checks: list[dict[str, Any]], name: str, ok: bool, observed: Any, expected: Any, details: str = "") -> None:
    checks.append({
        "check_name": name,
        "status": "PASS" if ok else "FAIL",
        "observed": observed,
        "expected": expected,
        "details": details,
    })


def main() -> int:
    root = Path.cwd()
    dbs = {
        "source": root / "data/database/ncaa_track_analytics.duckdb",
        "canonical_person": root / "data/processed/milestone4/canonical_person_layer_v1_1/canonical_person_layer_v1_1.duckdb",
        "school_stint": root / "data/processed/milestone4/final_school_stints_v1_1/final_school_stints_v1_1.duckdb",
    }
    output_dir = root / "data/processed/milestone5/event_registry_v1" / OUTPUT_VERSION
    output_dir.mkdir(parents=True, exist_ok=True)

    print("MILESTONE 5 PHASE 1A — EVENT VALUE PROFILING")
    print("=" * 78)
    print(f"Started UTC: {utc_now()}")
    print(f"Output: {output_dir}")

    checks: list[dict[str, Any]] = []
    before: list[dict[str, Any]] = []
    for name, path in dbs.items():
        add_check(checks, f"{name}_database_exists", path.exists(), path.exists(), True, str(path))
        if not path.exists():
            print(f"Missing input: {path}", file=sys.stderr)
            return 1
        before.append(manifest_row(name, path, "before"))

    con = duckdb.connect(":memory:")
    try:
        for name, path in dbs.items():
            escaped = str(path).replace("'", "''")
            con.execute(f"ATTACH '{escaped}' AS {name} (READ_ONLY)")

        canonical_count = con.execute("SELECT COUNT(*) FROM canonical_person.main.canonical_person_performances").fetchone()[0]
        stint_count = con.execute("SELECT COUNT(*) FROM school_stint.main.school_stint_performance_map").fetchone()[0]
        add_check(checks, "canonical_performance_row_count", canonical_count == EXPECTED_CANONICAL_PERFORMANCES, canonical_count, EXPECTED_CANONICAL_PERFORMANCES)
        add_check(checks, "stint_mapped_performance_row_count", stint_count == EXPECTED_STINT_MAPPED_PERFORMANCES, stint_count, EXPECTED_STINT_MAPPED_PERFORMANCES)

        rows = con.execute("""
            WITH base AS (
                SELECT p.*,
                       sm.canonical_person_performance_id IS NOT NULL AS is_stint_mapped
                FROM canonical_person.main.canonical_person_performances p
                LEFT JOIN school_stint.main.school_stint_performance_map sm
                  ON p.canonical_person_performance_id = sm.canonical_person_performance_id
            )
            SELECT event_id, event,
                   COUNT(*) AS performance_count,
                   COUNT(DISTINCT canonical_person_performance_id) AS distinct_performance_count,
                   COUNT(DISTINCT canonical_person_id) AS athlete_count,
                   COUNT(DISTINCT canonical_school_id) AS school_count,
                   COUNT(DISTINCT season_year) AS season_year_count,
                   MIN(season_year) AS first_season_year,
                   MAX(season_year) AS last_season_year,
                   COUNT(DISTINCT season_type) AS season_type_count,
                   COUNT(DISTINCT canonical_gender_code) AS gender_count,
                   SUM(CASE WHEN mark IS NULL OR trim(mark) = '' THEN 1 ELSE 0 END) AS blank_mark_count,
                   SUM(CASE WHEN secondary_mark IS NOT NULL AND trim(secondary_mark) <> '' THEN 1 ELSE 0 END) AS secondary_mark_count,
                   SUM(CASE WHEN wind IS NOT NULL AND trim(wind) <> '' THEN 1 ELSE 0 END) AS wind_value_count,
                   SUM(CASE WHEN d1_development_eligible THEN 1 ELSE 0 END) AS d1_eligible_count,
                   SUM(CASE WHEN school_stint_eligible THEN 1 ELSE 0 END) AS school_stint_eligible_count,
                   SUM(CASE WHEN is_stint_mapped THEN 1 ELSE 0 END) AS stint_mapped_count
            FROM base
            GROUP BY event_id, event
            ORDER BY performance_count DESC, event
        """).fetchall()
        cols = [d[0] for d in con.description]

        event_rows: list[dict[str, Any]] = []
        for raw in rows:
            row = dict(zip(cols, raw))
            family, family_reason = candidate_family(row["event"] or "")
            mtype, mtype_reason = candidate_mark_type(row["event"] or "")
            direction = "lower_is_better" if mtype == "time" else "higher_is_better" if mtype in {"distance", "points"} else "unknown"
            row.update({
                "normalized_event_text": normalize_event_text(row["event"]),
                "candidate_event_family": family,
                "candidate_family_reason": family_reason,
                "candidate_mark_type": mtype,
                "candidate_mark_reason": mtype_reason,
                "candidate_performance_direction": direction,
                "review_status": "manual_review_required",
                "registry_decision": "",
                "exclusion_reason": "",
            })
            event_rows.append(row)

        distinct_labels = len(event_rows)
        add_check(checks, "all_expected_event_labels_profiled", distinct_labels == EXPECTED_RAW_EVENT_LABELS, distinct_labels, EXPECTED_RAW_EVENT_LABELS)
        blank_event_rows = sum(int(r["performance_count"]) for r in event_rows if not normalize_event_text(r["event"]))
        add_check(checks, "event_labels_nonblank", blank_event_rows == 0, blank_event_rows, 0)

        event_id_conflicts = con.execute("""
            SELECT COUNT(*) FROM (
                SELECT event_id FROM canonical_person.main.canonical_person_performances
                GROUP BY event_id HAVING COUNT(DISTINCT event) > 1
            )
        """).fetchone()[0]
        label_conflicts = con.execute("""
            SELECT COUNT(*) FROM (
                SELECT event FROM canonical_person.main.canonical_person_performances
                GROUP BY event HAVING COUNT(DISTINCT event_id) > 1
            )
        """).fetchone()[0]
        add_check(checks, "event_id_maps_to_single_raw_label", event_id_conflicts == 0, event_id_conflicts, 0)
        add_check(checks, "raw_label_maps_to_single_event_id", label_conflicts == 0, label_conflicts, 0)

        coverage_raw = con.execute("""
            SELECT event_id, event, canonical_gender_code, season_type, season_year,
                   COUNT(*) AS performance_count,
                   COUNT(DISTINCT canonical_person_id) AS athlete_count,
                   COUNT(DISTINCT canonical_school_id) AS school_count,
                   SUM(CASE WHEN mark IS NULL OR trim(mark) = '' THEN 1 ELSE 0 END) AS blank_mark_count,
                   SUM(CASE WHEN d1_development_eligible THEN 1 ELSE 0 END) AS d1_eligible_count,
                   SUM(CASE WHEN school_stint_eligible THEN 1 ELSE 0 END) AS school_stint_eligible_count
            FROM canonical_person.main.canonical_person_performances
            GROUP BY event_id, event, canonical_gender_code, season_type, season_year
            ORDER BY event, canonical_gender_code, season_type, season_year
        """).fetchall()
        coverage_cols = [d[0] for d in con.description]
        coverage_rows = [dict(zip(coverage_cols, row)) for row in coverage_raw]

        mark_raw = con.execute("""
            SELECT event_id, event, mark, COUNT(*) AS mark_count
            FROM canonical_person.main.canonical_person_performances
            GROUP BY event_id, event, mark
            ORDER BY event_id, mark_count DESC, mark
        """).fetchall()
        shape_counts: dict[tuple[Any, str, str], int] = defaultdict(int)
        examples: dict[tuple[Any, str, str], list[tuple[str, int]]] = defaultdict(list)
        for event_id, event, mark, count in mark_raw:
            shape = mark_shape(mark)
            key = (event_id, event, shape)
            shape_counts[key] += int(count)
            if len(examples[key]) < 12:
                examples[key].append(("" if mark is None else str(mark), int(count)))
        mark_rows = []
        for (event_id, event, shape), count in sorted(shape_counts.items(), key=lambda x: (-x[1], str(x[0][1]), x[0][2])):
            mark_rows.append({
                "event_id": event_id,
                "event": event,
                "mark_shape": shape,
                "performance_count": count,
                "example_marks": " | ".join(f"{value} [{n:,}]" for value, n in examples[(event_id, event, shape)]),
            })

        family_counts = Counter(r["candidate_event_family"] for r in event_rows)
        type_counts = Counter(r["candidate_mark_type"] for r in event_rows)
        summary_rows = ([{"summary_type": "candidate_event_family", "value": k, "event_label_count": v} for k, v in sorted(family_counts.items())] +
                        [{"summary_type": "candidate_mark_type", "value": k, "event_label_count": v} for k, v in sorted(type_counts.items())])

        event_fields = cols + [
            "normalized_event_text", "candidate_event_family", "candidate_family_reason",
            "candidate_mark_type", "candidate_mark_reason", "candidate_performance_direction",
            "review_status", "registry_decision", "exclusion_reason",
        ]
        write_csv(output_dir / "event_value_profile.csv", event_rows, event_fields)
        write_csv(output_dir / "event_coverage_by_gender_season_year.csv", coverage_rows, coverage_cols)
        write_csv(output_dir / "event_mark_shape_profile.csv", mark_rows, ["event_id", "event", "mark_shape", "performance_count", "example_marks"])
        write_csv(output_dir / "candidate_classification_summary.csv", summary_rows, ["summary_type", "value", "event_label_count"])

        disk = shutil.disk_usage(root)
        write_csv(output_dir / "disk_space.csv", [{"path": str(root), "total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free, "free_gib": round(disk.free/(1024**3), 3)}], ["path", "total_bytes", "used_bytes", "free_bytes", "free_gib"])

        after = [manifest_row(name, path, "after") for name, path in dbs.items()]
        write_csv(output_dir / "database_manifest.csv", before + after, ["database_name", "stage", "path", "size_bytes", "mtime_epoch_ns", "sha256"])
        before_map = {r["database_name"]: r for r in before}
        after_map = {r["database_name"]: r for r in after}
        for name in dbs:
            b, a = before_map[name], after_map[name]
            add_check(checks, f"{name}_size_unchanged", b["size_bytes"] == a["size_bytes"], a["size_bytes"], b["size_bytes"])
            add_check(checks, f"{name}_mtime_unchanged", b["mtime_epoch_ns"] == a["mtime_epoch_ns"], a["mtime_epoch_ns"], b["mtime_epoch_ns"])
            add_check(checks, f"{name}_sha256_unchanged", b["sha256"] == a["sha256"], a["sha256"], b["sha256"])

        add_check(checks, "every_profiled_event_has_review_status", all(r["review_status"] for r in event_rows), sum(bool(r["review_status"]) for r in event_rows), distinct_labels)
        add_check(checks, "profile_does_not_finalize_registry", all(not r["registry_decision"] for r in event_rows), sum(bool(r["registry_decision"]) for r in event_rows), 0)
        write_csv(output_dir / "hard_checks.csv", checks, ["check_name", "status", "observed", "expected", "details"])

        unresolved = sum(1 for r in event_rows if r["candidate_event_family"] == "unclassified" or r["candidate_mark_type"] == "unknown")
        failed = [c for c in checks if c["status"] == "FAIL"]
        report = [
            "MILESTONE 5 PHASE 1A — EVENT VALUE PROFILE", "="*78,
            f"Finished UTC: {utc_now()}", f"Output version: {OUTPUT_VERSION}", "",
            "SCALE", "-"*78,
            f"Canonical performances: {canonical_count:,}",
            f"School-stint mapped performances: {stint_count:,}",
            f"Distinct event labels profiled: {distinct_labels:,}",
            f"Conservative heuristic unresolved labels: {unresolved:,}", "",
            "CANDIDATE EVENT FAMILY COUNTS", "-"*78,
        ]
        report += [f"{k}: {v:,}" for k, v in sorted(family_counts.items())]
        report += ["", "CANDIDATE MARK TYPE COUNTS", "-"*78]
        report += [f"{k}: {v:,}" for k, v in sorted(type_counts.items())]
        report += [
            "", "INTERPRETATION", "-"*78,
            "All classifications are diagnostic heuristics only.",
            "No canonical event, eligibility decision, exclusion, parser, or scoring constant is finalized.",
            "Cross country remains separate unless comparability is demonstrated.", "",
            "HARD CHECK SUMMARY", "-"*78,
            f"PASS: {sum(c['status']=='PASS' for c in checks)}",
            f"FAIL: {len(failed)}", "",
            "PHASE GATE", "-"*78,
            "PASS — Event values are ready for registry review." if not failed else "FAIL — Review failed checks before registry construction.",
        ]
        (output_dir / "event_profile_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

        print("\nCreated:")
        for name in ["event_profile_report.txt", "event_value_profile.csv", "event_coverage_by_gender_season_year.csv", "event_mark_shape_profile.csv", "candidate_classification_summary.csv", "database_manifest.csv", "disk_space.csv", "hard_checks.csv"]:
            print(f"  {output_dir / name}")
        if failed:
            print("\nPHASE GATE: FAIL")
            return 1
        print("\nPHASE GATE: PASS")
        print("Stop here and review the profile before building the event registry.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
