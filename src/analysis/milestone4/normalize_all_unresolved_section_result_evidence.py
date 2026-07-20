#!/usr/bin/env python3
"""
Milestone 4: normalize full unresolved-section result-page evidence.

This script does not fetch pages and does not modify any prior outputs. It
normalizes track/cross-country team URLs to one entity key, compares sampled
result-page entities with the consistent original source team, and isolates
sections requiring full performance-level result resolution.

Outputs
-------
data/processed/milestone4/normalized_unresolved_section_evidence/
    normalization_report.txt
    hard_checks.csv
    normalized_section_evidence.csv
    evidence_status_summary.csv
    single_entity_disagreement_queue.csv
    genuine_multi_entity_section_queue.csv
    original_team_only_queue.csv
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]

PARSED_ROWS_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "all_unresolved_section_result_page_evidence/"
    / "parsed_result_page_rows.csv"
)

SECTION_EVIDENCE_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "section_source_team_evidence/"
    / "section_source_team_evidence.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "normalized_unresolved_section_evidence"
)

NORMALIZATION_VERSION = (
    "m4_normalized_unresolved_section_evidence_v1.1"
)

EXPECTED_SECTION_ROWS = 1_987


def clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split()).strip()


def normalize_text(value: object) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "",
        clean(value).casefold(),
    )


def split_pipe_values(value: object) -> list[str]:
    return [
        clean(part)
        for part in clean(value).split("|")
        if clean(part)
    ]


def canonical_team_key_from_url(
    value: object,
) -> str:
    url = clean(value)

    if not url:
        return ""

    parsed = urlparse(url)
    path = parsed.path

    tfrrs_match = re.search(
        r"/teams/(?:tf|xc)/([^/]+?)(?:\.html)?$",
        path,
        flags=re.IGNORECASE,
    )
    if tfrrs_match:
        slug = tfrrs_match.group(1)
        return f"TFRRS:{slug}"

    direct_match = re.search(
        r"/teams/(?:track|cross-country)/(\d+)(?:\.html)?$",
        path,
        flags=re.IGNORECASE,
    )
    if direct_match:
        return (
            "DIRECTATHLETICS:"
            f"{direct_match.group(1)}"
        )

    normalized_host = parsed.netloc.casefold()
    normalized_path = path.rstrip("/").casefold()

    return f"URL:{normalized_host}{normalized_path}"


def canonical_team_key_from_source_id(
    value: object,
) -> str:
    source_id = clean(value)

    if not source_id:
        return ""

    if source_id.startswith(
        (
            "http://",
            "https://",
        )
    ):
        return canonical_team_key_from_url(
            source_id
        )

    return f"TFRRS:{source_id}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--replace-output",
        action="store_true",
    )
    return parser.parse_args()


def require_inputs() -> None:
    for path in [
        PARSED_ROWS_CSV,
        SECTION_EVIDENCE_CSV,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    parsed = pd.read_csv(
        PARSED_ROWS_CSV,
        dtype=str,
        keep_default_na=False,
    )

    evidence = pd.read_csv(
        SECTION_EVIDENCE_CSV,
        dtype=str,
        keep_default_na=False,
    )

    for frame in [
        parsed,
        evidence,
    ]:
        frame["athlete_id"] = pd.to_numeric(
            frame["athlete_id"],
            errors="coerce",
        ).astype("Int64")
        frame["section_index"] = pd.to_numeric(
            frame["section_index"],
            errors="coerce",
        ).astype("Int64")

    evidence["observed_performance_count"] = (
        pd.to_numeric(
            evidence[
                "observed_performance_count"
            ],
            errors="coerce",
        )
        .fillna(0)
        .astype("int64")
    )

    evidence = evidence.loc[
        evidence["source_evidence_status"]
        .eq("CONSISTENT_SOURCE_TEAM")
    ].copy()

    return parsed, evidence


def explode_result_entities(
    parsed: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for record in parsed.itertuples(
        index=False,
    ):
        urls = split_pipe_values(
            getattr(
                record,
                "parsed_team_url",
                "",
            )
        )
        names = split_pipe_values(
            getattr(
                record,
                "parsed_team_name",
                "",
            )
        )

        pair_count = max(
            len(urls),
            len(names),
        )

        if pair_count == 0:
            continue

        for index in range(pair_count):
            url = (
                urls[index]
                if index < len(urls)
                else ""
            )
            name = (
                names[index]
                if index < len(names)
                else ""
            )

            rows.append(
                {
                    "athlete_id": (
                        record.athlete_id
                    ),
                    "section_index": (
                        record.section_index
                    ),
                    "performance_id": clean(
                        getattr(
                            record,
                            "performance_id",
                            "",
                        )
                    ),
                    "sample_position": clean(
                        getattr(
                            record,
                            "sample_position",
                            "",
                        )
                    ),
                    "team_parse_status": clean(
                        getattr(
                            record,
                            "team_parse_status",
                            "",
                        )
                    ),
                    "parsed_team_name": name,
                    "parsed_team_url": url,
                    "canonical_result_team_key": (
                        canonical_team_key_from_url(
                            url
                        )
                    ),
                    "normalized_result_team_name": (
                        normalize_text(name)
                    ),
                }
            )

    return pd.DataFrame(rows)


def build_entity_components(
    group: pd.DataFrame,
) -> list[dict[str, object]]:
    records = [
        {
            "name": clean(row.parsed_team_name),
            "normalized_name": clean(
                row.normalized_result_team_name
            ),
            "url": clean(row.parsed_team_url),
            "key": clean(
                row.canonical_result_team_key
            ),
        }
        for row in group.itertuples(
            index=False
        )
        if (
            clean(row.parsed_team_name)
            or clean(row.parsed_team_url)
        )
    ]

    if not records:
        return []

    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[
                parent[index]
            ]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)

        if root_left != root_right:
            parent[root_right] = root_left

    for left in range(len(records)):
        for right in range(
            left + 1,
            len(records),
        ):
            same_name = (
                records[left]["normalized_name"]
                and records[left]["normalized_name"]
                == records[right][
                    "normalized_name"
                ]
            )
            same_key = (
                records[left]["key"]
                and records[left]["key"]
                == records[right]["key"]
            )

            if same_name or same_key:
                union(left, right)

    components: dict[
        int,
        list[dict[str, str]],
    ] = {}

    for index, record in enumerate(records):
        root = find(index)
        components.setdefault(
            root,
            [],
        ).append(record)

    output: list[dict[str, object]] = []

    for component_rows in components.values():
        names = sorted(
            {
                row["name"]
                for row in component_rows
                if row["name"]
            }
        )
        normalized_names = sorted(
            {
                row["normalized_name"]
                for row in component_rows
                if row["normalized_name"]
            }
        )
        urls = sorted(
            {
                row["url"]
                for row in component_rows
                if row["url"]
            }
        )
        keys = sorted(
            {
                row["key"]
                for row in component_rows
                if row["key"]
            }
        )

        output.append(
            {
                "component_names": " | ".join(
                    names
                ),
                "component_normalized_names": (
                    " | ".join(
                        normalized_names
                    )
                ),
                "component_urls": " | ".join(
                    urls
                ),
                "component_keys": " | ".join(
                    keys
                ),
            }
        )

    return output


def build_section_summary(
    parsed: pd.DataFrame,
    evidence: pd.DataFrame,
) -> pd.DataFrame:
    entities = explode_result_entities(
        parsed
    )

    parsed_page_summary = (
        parsed.groupby(
            [
                "athlete_id",
                "section_index",
            ],
            dropna=False,
        )
        .agg(
            sampled_page_count=(
                "performance_id",
                "size",
            ),
            successful_team_page_count=(
                "team_parse_status",
                lambda values: sum(
                    value
                    in {
                        "TEAM_LINK_FOUND",
                        "MULTIPLE_DISTINCT_TEAM_LINKS",
                    }
                    for value in values
                ),
            ),
            page_parse_exception_count=(
                "team_parse_status",
                lambda values: sum(
                    value
                    not in {
                        "TEAM_LINK_FOUND",
                        "MULTIPLE_DISTINCT_TEAM_LINKS",
                    }
                    for value in values
                ),
            ),
        )
        .reset_index()
    )

    component_rows: list[
        dict[str, object]
    ] = []

    if not entities.empty:
        for (
            athlete_id,
            section_index,
        ), group in entities.groupby(
            [
                "athlete_id",
                "section_index",
            ],
            dropna=False,
        ):
            components = (
                build_entity_components(group)
            )

            component_rows.append(
                {
                    "athlete_id": athlete_id,
                    "section_index": (
                        section_index
                    ),
                    "distinct_result_entity_count": (
                        len(components)
                    ),
                    "result_entity_components": (
                        " || ".join(
                            component[
                                "component_names"
                            ]
                            for component in components
                        )
                    ),
                    "result_entity_keys": (
                        " || ".join(
                            component[
                                "component_keys"
                            ]
                            for component in components
                        )
                    ),
                    "result_team_names": (
                        " | ".join(
                            sorted(
                                {
                                    clean(value)
                                    for value in group[
                                        "parsed_team_name"
                                    ]
                                    if clean(value)
                                }
                            )
                        )
                    ),
                    "result_team_urls": (
                        " | ".join(
                            sorted(
                                {
                                    clean(value)
                                    for value in group[
                                        "parsed_team_url"
                                    ]
                                    if clean(value)
                                }
                            )
                        )
                    ),
                }
            )

    entity_summary = pd.DataFrame(
        component_rows
    )

    keep_columns = [
        "athlete_id",
        "section_index",
        "athlete_name",
        "source_section_name",
        "candidate_normalized_name",
        "observed_performance_count",
        "consistent_source_team_id",
        "consistent_source_school_id",
        "consistent_source_school_name",
        "consistent_core_team_name",
        "consistent_core_team_division",
        "consistent_core_team_gender_code",
        "first_season_year",
        "last_season_year",
    ]

    available_columns = [
        column
        for column in keep_columns
        if column in evidence.columns
    ]

    summary = evidence[
        available_columns
    ].copy()

    summary = summary.merge(
        parsed_page_summary,
        on=[
            "athlete_id",
            "section_index",
        ],
        how="left",
        validate="one_to_one",
    )

    if not entity_summary.empty:
        summary = summary.merge(
            entity_summary,
            on=[
                "athlete_id",
                "section_index",
            ],
            how="left",
            validate="one_to_one",
        )
    else:
        for column in [
            "distinct_result_entity_count",
            "result_entity_components",
            "result_entity_keys",
            "result_team_names",
            "result_team_urls",
        ]:
            summary[column] = ""

    for column in [
        "sampled_page_count",
        "successful_team_page_count",
        "page_parse_exception_count",
        "distinct_result_entity_count",
    ]:
        summary[column] = (
            pd.to_numeric(
                summary[column],
                errors="coerce",
            )
            .fillna(0)
            .astype("int64")
        )

    for column in [
        "result_entity_components",
        "result_entity_keys",
        "result_team_names",
        "result_team_urls",
    ]:
        summary[column] = (
            summary[column]
            .fillna("")
            .astype(str)
        )

    summary["canonical_original_team_key"] = (
        summary[
            "consistent_source_team_id"
        ].map(
            canonical_team_key_from_source_id
        )
    )

    summary[
        "normalized_source_section_name"
    ] = summary[
        "source_section_name"
    ].map(normalize_text)

    def classify(
        row: pd.Series,
    ) -> str:
        entity_count = int(
            row[
                "distinct_result_entity_count"
            ]
        )
        original_key = clean(
            row[
                "canonical_original_team_key"
            ]
        )

        all_component_keys = set()

        for component in clean(
            row["result_entity_keys"]
        ).split("||"):
            all_component_keys.update(
                split_pipe_values(component)
            )

        if entity_count == 0:
            return (
                "ORIGINAL_TEAM_ONLY_"
                "NO_RESULT_ENTITY"
            )

        if entity_count == 1:
            if (
                original_key
                and original_key
                in all_component_keys
            ):
                return (
                    "SINGLE_RESULT_ENTITY_"
                    "MATCHES_ORIGINAL"
                )

            return (
                "SINGLE_RESULT_ENTITY_"
                "DIFFERS_FROM_ORIGINAL"
            )

        if (
            original_key
            and original_key
            in all_component_keys
        ):
            return (
                "MULTIPLE_RESULT_ENTITIES_"
                "ORIGINAL_INCLUDED"
            )

        return (
            "MULTIPLE_RESULT_ENTITIES_"
            "ORIGINAL_EXCLUDED"
        )

    summary["normalized_evidence_status"] = (
        summary.apply(
            classify,
            axis=1,
        )
    )

    summary["recommended_next_action"] = (
        "KEEP_ORIGINAL_SOURCE_TEAM"
    )

    summary.loc[
        summary[
            "normalized_evidence_status"
        ].eq(
            "ORIGINAL_TEAM_ONLY_"
            "NO_RESULT_ENTITY"
        ),
        "recommended_next_action",
    ] = (
        "KEEP_ORIGINAL_WITH_"
        "LOWER_CONFIDENCE"
    )

    summary.loc[
        summary[
            "normalized_evidence_status"
        ].eq(
            "SINGLE_RESULT_ENTITY_"
            "DIFFERS_FROM_ORIGINAL"
        ),
        "recommended_next_action",
    ] = (
        "USE_RESULT_ENTITY_AS_"
        "SECTION_IDENTITY"
    )

    summary.loc[
        summary[
            "normalized_evidence_status"
        ].str.startswith(
            "MULTIPLE_RESULT_ENTITIES_"
        ),
        "recommended_next_action",
    ] = (
        "FULL_PERFORMANCE_RESULT_"
        "RESOLUTION_REQUIRED"
    )

    summary["normalization_version"] = (
        NORMALIZATION_VERSION
    )

    return summary


def build_checks(
    summary: pd.DataFrame,
) -> pd.DataFrame:
    duplicate_keys = int(
        summary.duplicated(
            [
                "athlete_id",
                "section_index",
            ]
        ).sum()
    )

    blank_section_names = int(
        summary[
            "source_section_name"
        ].map(clean).eq("").sum()
    )

    blank_original_teams = int(
        summary[
            "canonical_original_team_key"
        ].map(clean).eq("").sum()
    )

    allowed_statuses = {
        "ORIGINAL_TEAM_ONLY_NO_RESULT_ENTITY",
        "SINGLE_RESULT_ENTITY_MATCHES_ORIGINAL",
        "SINGLE_RESULT_ENTITY_DIFFERS_FROM_ORIGINAL",
        "MULTIPLE_RESULT_ENTITIES_ORIGINAL_INCLUDED",
        "MULTIPLE_RESULT_ENTITIES_ORIGINAL_EXCLUDED",
    }

    invalid_statuses = int(
        (
            ~summary[
                "normalized_evidence_status"
            ].isin(
                allowed_statuses
            )
        ).sum()
    )

    rows = [
        (
            "section_rows",
            abs(
                len(summary)
                - EXPECTED_SECTION_ROWS
            ),
            len(summary),
            EXPECTED_SECTION_ROWS,
        ),
        (
            "duplicate_section_keys",
            duplicate_keys,
            duplicate_keys,
            0,
        ),
        (
            "blank_source_section_names",
            blank_section_names,
            blank_section_names,
            0,
        ),
        (
            "blank_original_team_keys",
            blank_original_teams,
            blank_original_teams,
            0,
        ),
        (
            "invalid_normalized_statuses",
            invalid_statuses,
            invalid_statuses,
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
    summary: pd.DataFrame,
    checks: pd.DataFrame,
) -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary.to_csv(
        OUTPUT_DIR
        / "normalized_section_evidence.csv",
        index=False,
    )

    status_summary = (
        summary.groupby(
            [
                "normalized_evidence_status",
                "recommended_next_action",
            ],
            dropna=False,
        )
        .agg(
            section_count=(
                "section_index",
                "size",
            ),
            athlete_count=(
                "athlete_id",
                "nunique",
            ),
            performance_count=(
                "observed_performance_count",
                "sum",
            ),
        )
        .reset_index()
        .sort_values(
            [
                "performance_count",
                "section_count",
            ],
            ascending=False,
        )
    )

    status_summary.to_csv(
        OUTPUT_DIR
        / "evidence_status_summary.csv",
        index=False,
    )

    summary.loc[
        summary[
            "normalized_evidence_status"
        ].eq(
            "SINGLE_RESULT_ENTITY_"
            "DIFFERS_FROM_ORIGINAL"
        )
    ].sort_values(
        "observed_performance_count",
        ascending=False,
    ).to_csv(
        OUTPUT_DIR
        / "single_entity_disagreement_queue.csv",
        index=False,
    )

    summary.loc[
        summary[
            "normalized_evidence_status"
        ].str.startswith(
            "MULTIPLE_RESULT_ENTITIES_"
        )
    ].sort_values(
        "observed_performance_count",
        ascending=False,
    ).to_csv(
        OUTPUT_DIR
        / "genuine_multi_entity_section_queue.csv",
        index=False,
    )

    summary.loc[
        summary[
            "normalized_evidence_status"
        ].eq(
            "ORIGINAL_TEAM_ONLY_"
            "NO_RESULT_ENTITY"
        )
    ].sort_values(
        "observed_performance_count",
        ascending=False,
    ).to_csv(
        OUTPUT_DIR
        / "original_team_only_queue.csv",
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

    count_by_status = {
        row.normalized_evidence_status: (
            int(row.section_count),
            int(row.performance_count),
        )
        for row in status_summary.itertuples(
            index=False
        )
    }

    def status_count(
        status: str,
        index: int,
    ) -> int:
        return count_by_status.get(
            status,
            (0, 0),
        )[index]

    represented_performances = int(
        summary[
            "observed_performance_count"
        ].sum()
    )

    matching_sections = status_count(
        "SINGLE_RESULT_ENTITY_MATCHES_ORIGINAL",
        0,
    )
    matching_performances = status_count(
        "SINGLE_RESULT_ENTITY_MATCHES_ORIGINAL",
        1,
    )

    differing_sections = status_count(
        "SINGLE_RESULT_ENTITY_DIFFERS_FROM_ORIGINAL",
        0,
    )
    differing_performances = status_count(
        "SINGLE_RESULT_ENTITY_DIFFERS_FROM_ORIGINAL",
        1,
    )

    multiple_sections = (
        status_count(
            "MULTIPLE_RESULT_ENTITIES_ORIGINAL_INCLUDED",
            0,
        )
        + status_count(
            "MULTIPLE_RESULT_ENTITIES_ORIGINAL_EXCLUDED",
            0,
        )
    )
    multiple_performances = (
        status_count(
            "MULTIPLE_RESULT_ENTITIES_ORIGINAL_INCLUDED",
            1,
        )
        + status_count(
            "MULTIPLE_RESULT_ENTITIES_ORIGINAL_EXCLUDED",
            1,
        )
    )

    original_only_sections = status_count(
        "ORIGINAL_TEAM_ONLY_NO_RESULT_ENTITY",
        0,
    )
    original_only_performances = status_count(
        "ORIGINAL_TEAM_ONLY_NO_RESULT_ENTITY",
        1,
    )

    report = f"""MILESTONE 4 NORMALIZED UNRESOLVED-SECTION EVIDENCE
============================================================
Normalization version: {NORMALIZATION_VERSION}
Source files modified: no
Prior Milestone 4 outputs modified: no

SCOPE
- Sections normalized: {len(summary):,}
- Performances represented: {represented_performances:,}

NORMALIZED RESULTS
- Single result entity matching original team:
  Sections: {matching_sections:,}
  Performances: {matching_performances:,}

- Single result entity differing from original team:
  Sections: {differing_sections:,}
  Performances: {differing_performances:,}

- Multiple genuine result entities:
  Sections: {multiple_sections:,}
  Performances: {multiple_performances:,}

- Original-team-only sections without parsed result entity:
  Sections: {original_only_sections:,}
  Performances: {original_only_performances:,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

NEXT GATE
Use the single differing result entity as the profile-section identity. Run
full performance-level result-page resolution only for sections listed in
genuine_multi_entity_section_queue.csv. Original-team-only rows remain
lower-confidence evidence and should retain an explicit review flag.
"""

    (
        OUTPUT_DIR
        / "normalization_report.txt"
    ).write_text(
        report,
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    require_inputs()

    if OUTPUT_DIR.exists() and not args.replace_output:
        existing = list(
            OUTPUT_DIR.glob("*.csv")
        ) + list(
            OUTPUT_DIR.glob("*.txt")
        )
        if existing:
            raise FileExistsError(
                "Existing normalization outputs found. "
                "Use --replace-output after review."
            )

    parsed, evidence = load_inputs()
    summary = build_section_summary(
        parsed=parsed,
        evidence=evidence,
    )
    checks = build_checks(summary)

    write_outputs(
        summary=summary,
        checks=checks,
    )

    failed = int(
        (
            checks["failed_row_count"] > 0
        ).sum()
    )

    print(
        "Normalized unresolved-section evidence "
        "audit complete."
    )
    print(f"Outputs: {OUTPUT_DIR}")
    print(f"Failed checks: {failed:,}.")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
