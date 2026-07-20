#!/usr/bin/env python3
"""
Milestone 4: build the canonical profile-section entity registry.

This is a read-only consolidation step. It combines previously validated
Milestone 4 outputs using explicit precedence:

1. Performance-level mixed-section marker
2. Result-page section identity / original-team fallback
3. Gender-based exact-match correction
4. Full exact/alias section candidate

The nine mixed sections remain one registry row each but are intentionally not
flattened to one team. Their 120 performance assignments are written to a
separate canonical override table.

Outputs
-------
data/processed/milestone4/canonical_section_registry/
    registry_report.txt
    hard_checks.csv
    canonical_profile_section_registry.csv
    canonical_performance_team_overrides.csv
    resolution_method_summary.csv
    confidence_summary.csv
    mixed_section_summary.csv
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]

BASE_SECTION_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "full_section_entity_resolution/"
    / "section_resolution_candidates.csv"
)

GENDER_OVERRIDE_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "final_section_resolution_audit/"
    / "gender_ambiguous_resolution_candidates.csv"
)

RESULT_EVIDENCE_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "normalized_unresolved_section_evidence/"
    / "normalized_section_evidence.csv"
)

PERFORMANCE_OVERRIDE_CSV = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "multi_entity_performance_resolution/"
    / "performance_resolution_candidates.csv"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_section_registry"
)

REGISTRY_VERSION = (
    "m4_canonical_profile_section_registry_v1.0"
)

EXPECTED_SECTION_ROWS = 12_311
EXPECTED_GENDER_OVERRIDE_ROWS = 16
EXPECTED_RESULT_EVIDENCE_ROWS = 1_987
EXPECTED_MIXED_SECTION_ROWS = 9
EXPECTED_PERFORMANCE_OVERRIDE_ROWS = 120


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--replace-output",
        action="store_true",
    )
    return parser.parse_args()


def require_inputs() -> None:
    for path in [
        BASE_SECTION_CSV,
        GENDER_OVERRIDE_CSV,
        RESULT_EVIDENCE_CSV,
        PERFORMANCE_OVERRIDE_CSV,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )


def read_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
    )

    for column in [
        "athlete_id",
        "section_index",
    ]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(
                frame[column],
                errors="coerce",
            ).astype("Int64")

    return frame


def canonical_team_id_from_url(
    value: object,
) -> str:
    url = clean(value)

    if not url:
        return ""

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    match = re.search(
        r"/teams/(?:tf|xc)/([^/]+?)(?:\.html)?$",
        path,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(1)

    direct_match = re.search(
        r"/teams/(?:track|cross-country)/(\d+)(?:\.html)?$",
        path,
        flags=re.IGNORECASE,
    )

    if direct_match:
        return (
            "directathletics_"
            f"{direct_match.group(1)}"
        )

    return ""


def school_id_from_team_id(
    value: object,
) -> str:
    team_id = clean(value)

    if not team_id:
        return ""

    match = re.match(
        r"^([A-Za-z]{2}_(?:college|jcollege))_([mf])_(.+)$",
        team_id,
    )

    if match:
        return (
            f"{match.group(1)}_"
            f"{match.group(3)}"
        )

    return ""


def canonical_external_entity_id(
    team_id: str,
    team_url: str,
    team_name: str,
) -> str:
    if team_id:
        return f"team:{team_id}"

    if team_url:
        return f"url:{team_url}"

    if team_name:
        return (
            "name:"
            f"{normalize_text(team_name)}"
        )

    return ""


def initialize_registry(
    base: pd.DataFrame,
) -> pd.DataFrame:
    registry = pd.DataFrame(
        {
            "athlete_id": base["athlete_id"],
            "section_index": base["section_index"],
            "profile_section_id": (
                base["profile_section_id"]
            ),
            "athlete_name": base["athlete_name"],
            "source_section_name": (
                base["source_section_name"]
            ),
            "normalized_section_name": (
                base["normalized_section_name"]
            ),
            "marker_text": base["marker_text"],
            "performance_count": (
                pd.to_numeric(
                    base["performance_count"],
                    errors="coerce",
                )
                .fillna(0)
                .astype("int64")
            ),
            "meet_count": (
                pd.to_numeric(
                    base["meet_count"],
                    errors="coerce",
                )
                .fillna(0)
                .astype("int64")
            ),
            "first_season_year": (
                base["first_season_year"]
            ),
            "last_season_year": (
                base["last_season_year"]
            ),
            "section_gender_code": (
                base["section_gender_code"]
            ),
            "canonical_entity_type": (
                base["entity_type"]
            ),
            "canonical_analytical_entity_id": (
                base["analytical_entity_id"]
            ),
            "canonical_team_id": (
                base["resolved_team_id"]
            ),
            "canonical_school_id": (
                base["resolved_school_id"]
            ),
            "canonical_entity_name": (
                base["resolved_school_name"]
            ),
            "canonical_team_name": (
                base["matched_entity_name"]
            ),
            "canonical_team_url": "",
            "canonical_gender_code": (
                base["gender_code"]
            ),
            "canonical_division": (
                base["division"]
            ),
            "canonical_resolution_status": (
                "RESOLVED_SECTION_ENTITY"
            ),
            "canonical_resolution_method": (
                "FULL_SECTION_EXACT_OR_ALIAS"
            ),
            "canonical_resolution_confidence": (
                "HIGH"
            ),
            "requires_performance_override": False,
            "performance_override_count": 0,
            "evidence_source": (
                base["resolution_version"]
            ),
            "registry_version": (
                REGISTRY_VERSION
            ),
        }
    )

    registry.loc[
        registry[
            "canonical_analytical_entity_id"
        ].map(clean).eq(""),
        "canonical_analytical_entity_id",
    ] = registry.loc[
        registry[
            "canonical_analytical_entity_id"
        ].map(clean).eq(""),
        "canonical_team_id",
    ].map(
        lambda value: (
            f"team:{clean(value)}"
            if clean(value)
            else ""
        )
    )

    return registry


def apply_gender_overrides(
    registry: pd.DataFrame,
    gender: pd.DataFrame,
) -> pd.DataFrame:
    override = gender[
        [
            "athlete_id",
            "section_index",
            "resolved_team_id",
            "resolved_school_id",
            "resolved_school_name",
            "resolved_team_name",
            "gender_code",
            "division",
            "audit_version",
        ]
    ].copy()

    override = override.rename(
        columns={
            "resolved_team_id": (
                "gender_team_id"
            ),
            "resolved_school_id": (
                "gender_school_id"
            ),
            "resolved_school_name": (
                "gender_school_name"
            ),
            "resolved_team_name": (
                "gender_team_name"
            ),
            "gender_code": (
                "gender_override_code"
            ),
            "division": (
                "gender_division"
            ),
            "audit_version": (
                "gender_audit_version"
            ),
        }
    )

    registry = registry.merge(
        override,
        on=[
            "athlete_id",
            "section_index",
        ],
        how="left",
        validate="one_to_one",
    )

    mask = registry[
        "gender_team_id"
    ].map(clean).ne("")

    registry.loc[
        mask,
        "canonical_entity_type",
    ] = "school_team"
    registry.loc[
        mask,
        "canonical_team_id",
    ] = registry.loc[
        mask,
        "gender_team_id",
    ]
    registry.loc[
        mask,
        "canonical_school_id",
    ] = registry.loc[
        mask,
        "gender_school_id",
    ]
    registry.loc[
        mask,
        "canonical_entity_name",
    ] = registry.loc[
        mask,
        "gender_school_name",
    ]
    registry.loc[
        mask,
        "canonical_team_name",
    ] = registry.loc[
        mask,
        "gender_team_name",
    ]
    registry.loc[
        mask,
        "canonical_gender_code",
    ] = registry.loc[
        mask,
        "gender_override_code",
    ]
    registry.loc[
        mask,
        "canonical_division",
    ] = registry.loc[
        mask,
        "gender_division",
    ]
    registry.loc[
        mask,
        "canonical_analytical_entity_id",
    ] = registry.loc[
        mask,
        "gender_school_id",
    ]
    registry.loc[
        mask,
        "canonical_resolution_method",
    ] = "SOLE_AFFILIATION_GENDER"
    registry.loc[
        mask,
        "canonical_resolution_confidence",
    ] = "HIGH"
    registry.loc[
        mask,
        "evidence_source",
    ] = registry.loc[
        mask,
        "gender_audit_version",
    ]

    return registry.drop(
        columns=[
            "gender_team_id",
            "gender_school_id",
            "gender_school_name",
            "gender_team_name",
            "gender_override_code",
            "gender_division",
            "gender_audit_version",
        ]
    )


def result_entity_fields(
    row: pd.Series,
) -> dict[str, str]:
    status = clean(
        row["normalized_evidence_status"]
    )

    result_name = clean(
        row["result_team_names"]
    )
    result_url = clean(
        row["result_team_urls"]
    )

    original_team_id = clean(
        row["consistent_source_team_id"]
    )
    original_school_id = clean(
        row["consistent_source_school_id"]
    )
    original_school_name = clean(
        row[
            "consistent_source_school_name"
        ]
    )
    original_team_name = clean(
        row["consistent_core_team_name"]
    )
    original_gender = clean(
        row[
            "consistent_core_team_gender_code"
        ]
    )
    original_division = clean(
        row[
            "consistent_core_team_division"
        ]
    )

    if status == (
        "SINGLE_RESULT_ENTITY_"
        "DIFFERS_FROM_ORIGINAL"
    ):
        team_id = canonical_team_id_from_url(
            result_url
        )
        school_id = school_id_from_team_id(
            team_id
        )
        analytical_id = (
            school_id
            or canonical_external_entity_id(
                team_id=team_id,
                team_url=result_url,
                team_name=result_name,
            )
        )

        return {
            "entity_type": (
                "school_team"
                if school_id
                else "external_team"
            ),
            "analytical_entity_id": (
                analytical_id
            ),
            "team_id": team_id,
            "school_id": school_id,
            "entity_name": result_name,
            "team_name": result_name,
            "team_url": result_url,
            "gender_code": (
                original_gender
            ),
            "division": "",
            "resolution_status": (
                "RESOLVED_SECTION_ENTITY"
            ),
            "resolution_method": (
                "RESULT_PAGE_SECTION_ENTITY"
            ),
            "confidence": "HIGH",
            "requires_override": False,
        }

    if status == (
        "SINGLE_RESULT_ENTITY_"
        "MATCHES_ORIGINAL"
    ):
        return {
            "entity_type": "school_team",
            "analytical_entity_id": (
                original_school_id
                or original_team_id
            ),
            "team_id": original_team_id,
            "school_id": original_school_id,
            "entity_name": (
                original_school_name
            ),
            "team_name": (
                original_team_name
                or original_school_name
            ),
            "team_url": result_url,
            "gender_code": original_gender,
            "division": original_division,
            "resolution_status": (
                "RESOLVED_SECTION_ENTITY"
            ),
            "resolution_method": (
                "RESULT_PAGE_CONFIRMED_ORIGINAL"
            ),
            "confidence": "HIGH",
            "requires_override": False,
        }

    if status == (
        "ORIGINAL_TEAM_ONLY_"
        "NO_RESULT_ENTITY"
    ):
        return {
            "entity_type": "school_team",
            "analytical_entity_id": (
                original_school_id
                or original_team_id
            ),
            "team_id": original_team_id,
            "school_id": original_school_id,
            "entity_name": (
                original_school_name
            ),
            "team_name": (
                original_team_name
                or original_school_name
            ),
            "team_url": "",
            "gender_code": original_gender,
            "division": original_division,
            "resolution_status": (
                "RESOLVED_SECTION_ENTITY_"
                "LOWER_CONFIDENCE"
            ),
            "resolution_method": (
                "CONSISTENT_ORIGINAL_TEAM_FALLBACK"
            ),
            "confidence": "MEDIUM",
            "requires_override": False,
        }

    if status.startswith(
        "MULTIPLE_RESULT_ENTITIES_"
    ):
        return {
            "entity_type": (
                "mixed_performance_entities"
            ),
            "analytical_entity_id": "",
            "team_id": "",
            "school_id": "",
            "entity_name": clean(
                row["source_section_name"]
            ),
            "team_name": "",
            "team_url": "",
            "gender_code": original_gender,
            "division": "",
            "resolution_status": (
                "MIXED_SECTION_RESOLVED_BY_"
                "PERFORMANCE_OVERRIDE"
            ),
            "resolution_method": (
                "PERFORMANCE_LEVEL_RESULT_TEAM"
            ),
            "confidence": "HIGH",
            "requires_override": True,
        }

    raise ValueError(
        "Unexpected normalized evidence status: "
        f"{status}"
    )


def apply_result_evidence(
    registry: pd.DataFrame,
    evidence: pd.DataFrame,
) -> pd.DataFrame:
    fields = evidence.apply(
        result_entity_fields,
        axis=1,
        result_type="expand",
    )

    override = evidence[
        [
            "athlete_id",
            "section_index",
            "normalization_version",
        ]
    ].copy()

    override = pd.concat(
        [
            override.reset_index(drop=True),
            fields.reset_index(drop=True),
        ],
        axis=1,
    )

    registry = registry.merge(
        override,
        on=[
            "athlete_id",
            "section_index",
        ],
        how="left",
        validate="one_to_one",
    )

    mask = registry[
        "resolution_method"
    ].map(clean).ne("")

    mappings = {
        "canonical_entity_type": (
            "entity_type"
        ),
        "canonical_analytical_entity_id": (
            "analytical_entity_id"
        ),
        "canonical_team_id": "team_id",
        "canonical_school_id": "school_id",
        "canonical_entity_name": (
            "entity_name"
        ),
        "canonical_team_name": (
            "team_name"
        ),
        "canonical_team_url": "team_url",
        "canonical_gender_code": (
            "gender_code"
        ),
        "canonical_division": "division",
        "canonical_resolution_status": (
            "resolution_status"
        ),
        "canonical_resolution_method": (
            "resolution_method"
        ),
        "canonical_resolution_confidence": (
            "confidence"
        ),
        "requires_performance_override": (
            "requires_override"
        ),
    }

    for target, source in mappings.items():
        registry.loc[
            mask,
            target,
        ] = registry.loc[
            mask,
            source,
        ]

    registry.loc[
        mask,
        "evidence_source",
    ] = registry.loc[
        mask,
        "normalization_version",
    ]

    return registry.drop(
        columns=[
            "normalization_version",
            "entity_type",
            "analytical_entity_id",
            "team_id",
            "school_id",
            "entity_name",
            "team_name",
            "team_url",
            "gender_code",
            "division",
            "resolution_status",
            "resolution_method",
            "confidence",
            "requires_override",
        ]
    )


def build_performance_overrides(
    performance: pd.DataFrame,
) -> pd.DataFrame:
    frame = performance.copy()

    frame["canonical_team_id"] = (
        frame["resolved_team_url"].map(
            canonical_team_id_from_url
        )
    )
    frame["canonical_school_id"] = (
        frame["canonical_team_id"].map(
            school_id_from_team_id
        )
    )
    frame[
        "canonical_analytical_entity_id"
    ] = frame.apply(
        lambda row: (
            clean(
                row["canonical_school_id"]
            )
            or canonical_external_entity_id(
                team_id=clean(
                    row["canonical_team_id"]
                ),
                team_url=clean(
                    row["resolved_team_url"]
                ),
                team_name=clean(
                    row["resolved_team_name"]
                ),
            )
        ),
        axis=1,
    )

    frame["canonical_entity_type"] = (
        frame["canonical_school_id"].map(
            clean
        ).ne("").map(
            {
                True: "school_team",
                False: "external_team",
            }
        )
    )

    output = pd.DataFrame(
        {
            "performance_id": (
                frame["performance_id"]
            ),
            "athlete_id": (
                frame["athlete_id"]
            ),
            "section_index": (
                frame["section_index"]
            ),
            "athlete_name": (
                frame["athlete_name"]
            ),
            "source_section_name": (
                frame["source_section_name"]
            ),
            "season_year": (
                frame["season_year"]
            ),
            "season_type": (
                frame["season_type"]
            ),
            "meet_id": frame["meet_id"],
            "meet_name": frame["meet_name"],
            "event": frame["event"],
            "mark": frame["mark"],
            "result_url": (
                frame["result_url"]
            ),
            "canonical_entity_type": (
                frame["canonical_entity_type"]
            ),
            "canonical_analytical_entity_id": (
                frame[
                    "canonical_analytical_entity_id"
                ]
            ),
            "canonical_team_id": (
                frame["canonical_team_id"]
            ),
            "canonical_school_id": (
                frame["canonical_school_id"]
            ),
            "canonical_team_name": (
                frame["resolved_team_name"]
            ),
            "canonical_team_url": (
                frame["resolved_team_url"]
            ),
            "gender_code": (
                frame["gender_code"]
            ),
            "resolution_status": (
                frame[
                    "performance_resolution_status"
                ]
            ),
            "resolution_method": (
                frame["resolution_method"]
            ),
            "resolution_confidence": (
                frame["resolution_confidence"]
            ),
            "evidence_source": (
                frame["resolution_version"]
            ),
            "registry_version": (
                REGISTRY_VERSION
            ),
        }
    )

    return output


def attach_override_counts(
    registry: pd.DataFrame,
    overrides: pd.DataFrame,
) -> pd.DataFrame:
    counts = (
        overrides.groupby(
            [
                "athlete_id",
                "section_index",
            ]
        )
        .size()
        .rename(
            "observed_override_count"
        )
        .reset_index()
    )

    registry = registry.merge(
        counts,
        on=[
            "athlete_id",
            "section_index",
        ],
        how="left",
        validate="one_to_one",
    )

    registry[
        "observed_override_count"
    ] = (
        pd.to_numeric(
            registry[
                "observed_override_count"
            ],
            errors="coerce",
        )
        .fillna(0)
        .astype("int64")
    )

    mixed_mask = registry[
        "requires_performance_override"
    ].astype(bool)

    registry.loc[
        mixed_mask,
        "performance_override_count",
    ] = registry.loc[
        mixed_mask,
        "observed_override_count",
    ]

    return registry.drop(
        columns=[
            "observed_override_count"
        ]
    )


def build_checks(
    base: pd.DataFrame,
    gender: pd.DataFrame,
    evidence: pd.DataFrame,
    registry: pd.DataFrame,
    overrides: pd.DataFrame,
) -> pd.DataFrame:
    mixed = registry.loc[
        registry[
            "requires_performance_override"
        ].astype(bool)
    ]

    override_keys = overrides[
        [
            "athlete_id",
            "section_index",
        ]
    ].drop_duplicates()

    missing_mixed_override_keys = int(
        len(
            mixed[
                [
                    "athlete_id",
                    "section_index",
                ]
            ].merge(
                override_keys,
                on=[
                    "athlete_id",
                    "section_index",
                ],
                how="left",
                indicator=True,
            ).query(
                "_merge != 'both'"
            )
        )
    )

    nonmixed_override_keys = int(
        len(
            override_keys.merge(
                mixed[
                    [
                        "athlete_id",
                        "section_index",
                    ]
                ],
                on=[
                    "athlete_id",
                    "section_index",
                ],
                how="left",
                indicator=True,
            ).query(
                "_merge != 'both'"
            )
        )
    )

    blank_status_rows = int(
        registry[
            "canonical_resolution_status"
        ].map(clean).eq("").sum()
    )

    blank_confidence_rows = int(
        registry[
            "canonical_resolution_confidence"
        ].map(clean).eq("").sum()
    )

    mixed_with_section_team = int(
        (
            mixed[
                "canonical_team_id"
            ].map(clean).ne("")
        ).sum()
    )

    mixed_count_mismatch = int(
        (
            mixed[
                "performance_override_count"
            ]
            != mixed[
                "performance_count"
            ]
        ).sum()
    )

    rows = [
        (
            "base_section_rows",
            abs(
                len(base)
                - EXPECTED_SECTION_ROWS
            ),
            len(base),
            EXPECTED_SECTION_ROWS,
        ),
        (
            "gender_override_rows",
            abs(
                len(gender)
                - EXPECTED_GENDER_OVERRIDE_ROWS
            ),
            len(gender),
            EXPECTED_GENDER_OVERRIDE_ROWS,
        ),
        (
            "result_evidence_rows",
            abs(
                len(evidence)
                - EXPECTED_RESULT_EVIDENCE_ROWS
            ),
            len(evidence),
            EXPECTED_RESULT_EVIDENCE_ROWS,
        ),
        (
            "canonical_registry_rows",
            abs(
                len(registry)
                - EXPECTED_SECTION_ROWS
            ),
            len(registry),
            EXPECTED_SECTION_ROWS,
        ),
        (
            "duplicate_base_section_keys",
            int(
                base.duplicated(
                    [
                        "athlete_id",
                        "section_index",
                    ]
                ).sum()
            ),
            int(
                base.duplicated(
                    [
                        "athlete_id",
                        "section_index",
                    ]
                ).sum()
            ),
            0,
        ),
        (
            "duplicate_registry_section_keys",
            int(
                registry.duplicated(
                    [
                        "athlete_id",
                        "section_index",
                    ]
                ).sum()
            ),
            int(
                registry.duplicated(
                    [
                        "athlete_id",
                        "section_index",
                    ]
                ).sum()
            ),
            0,
        ),
        (
            "performance_override_rows",
            abs(
                len(overrides)
                - EXPECTED_PERFORMANCE_OVERRIDE_ROWS
            ),
            len(overrides),
            EXPECTED_PERFORMANCE_OVERRIDE_ROWS,
        ),
        (
            "duplicate_override_performance_ids",
            int(
                overrides[
                    "performance_id"
                ].duplicated().sum()
            ),
            int(
                overrides[
                    "performance_id"
                ].duplicated().sum()
            ),
            0,
        ),
        (
            "mixed_section_rows",
            abs(
                len(mixed)
                - EXPECTED_MIXED_SECTION_ROWS
            ),
            len(mixed),
            EXPECTED_MIXED_SECTION_ROWS,
        ),
        (
            "mixed_sections_missing_overrides",
            missing_mixed_override_keys,
            missing_mixed_override_keys,
            0,
        ),
        (
            "override_keys_not_mixed_sections",
            nonmixed_override_keys,
            nonmixed_override_keys,
            0,
        ),
        (
            "mixed_sections_with_section_team_id",
            mixed_with_section_team,
            mixed_with_section_team,
            0,
        ),
        (
            "mixed_section_override_count_mismatches",
            mixed_count_mismatch,
            mixed_count_mismatch,
            0,
        ),
        (
            "blank_resolution_status_rows",
            blank_status_rows,
            blank_status_rows,
            0,
        ),
        (
            "blank_resolution_confidence_rows",
            blank_confidence_rows,
            blank_confidence_rows,
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
    registry: pd.DataFrame,
    overrides: pd.DataFrame,
    checks: pd.DataFrame,
) -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    registry = registry.sort_values(
        [
            "athlete_id",
            "section_index",
        ]
    )

    overrides = overrides.sort_values(
        [
            "athlete_id",
            "section_index",
            "season_year",
            "performance_id",
        ]
    )

    registry.to_csv(
        OUTPUT_DIR
        / "canonical_profile_section_registry.csv",
        index=False,
    )

    overrides.to_csv(
        OUTPUT_DIR
        / "canonical_performance_team_overrides.csv",
        index=False,
    )

    resolution_summary = (
        registry.groupby(
            [
                "canonical_resolution_method",
                "canonical_resolution_confidence",
                "canonical_resolution_status",
            ],
            dropna=False,
        )
        .agg(
            section_count=(
                "profile_section_id",
                "size",
            ),
            athlete_count=(
                "athlete_id",
                "nunique",
            ),
            performance_count=(
                "performance_count",
                "sum",
            ),
        )
        .reset_index()
        .sort_values(
            [
                "section_count",
                "performance_count",
            ],
            ascending=False,
        )
    )

    resolution_summary.to_csv(
        OUTPUT_DIR
        / "resolution_method_summary.csv",
        index=False,
    )

    confidence_summary = (
        registry.groupby(
            [
                "canonical_resolution_confidence",
            ],
            dropna=False,
        )
        .agg(
            section_count=(
                "profile_section_id",
                "size",
            ),
            athlete_count=(
                "athlete_id",
                "nunique",
            ),
            performance_count=(
                "performance_count",
                "sum",
            ),
        )
        .reset_index()
        .sort_values(
            "section_count",
            ascending=False,
        )
    )

    confidence_summary.to_csv(
        OUTPUT_DIR
        / "confidence_summary.csv",
        index=False,
    )

    mixed_summary = registry.loc[
        registry[
            "requires_performance_override"
        ].astype(bool)
    ].copy()

    mixed_summary.to_csv(
        OUTPUT_DIR
        / "mixed_section_summary.csv",
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

    method_counts = (
        registry[
            "canonical_resolution_method"
        ]
        .value_counts()
        .to_dict()
    )

    report = f"""MILESTONE 4 CANONICAL PROFILE-SECTION REGISTRY
============================================================
Registry version: {REGISTRY_VERSION}
Source database modified: no
Prior Milestone 4 outputs modified: no

SCOPE
- Canonical profile sections: {len(registry):,}
- Canonical performance overrides: {len(overrides):,}
- Mixed sections using performance overrides: {len(mixed_summary):,}

RESOLUTION PRECEDENCE
- Exact or alias section entities:
  {method_counts.get('FULL_SECTION_EXACT_OR_ALIAS', 0):,}
- Gender-corrected exact entities:
  {method_counts.get('SOLE_AFFILIATION_GENDER', 0):,}
- Result-page section entities:
  {method_counts.get('RESULT_PAGE_SECTION_ENTITY', 0):,}
- Result-page-confirmed original entities:
  {method_counts.get('RESULT_PAGE_CONFIRMED_ORIGINAL', 0):,}
- Consistent-original-team fallbacks:
  {method_counts.get('CONSISTENT_ORIGINAL_TEAM_FALLBACK', 0):,}
- Mixed sections resolved by performance:
  {method_counts.get('PERFORMANCE_LEVEL_RESULT_TEAM', 0):,}

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

INTERPRETATION
canonical_profile_section_registry.csv contains exactly one row per profile
section. Mixed sections intentionally have no single canonical team ID.
canonical_performance_team_overrides.csv supplies the team entity for each of
their 120 performances and has higher attribution precedence than section-level
evidence.
"""

    (
        OUTPUT_DIR / "registry_report.txt"
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
                "Existing registry outputs found. "
                "Use --replace-output after review."
            )

    base = read_csv(BASE_SECTION_CSV)
    gender = read_csv(GENDER_OVERRIDE_CSV)
    evidence = read_csv(RESULT_EVIDENCE_CSV)
    performance = read_csv(
        PERFORMANCE_OVERRIDE_CSV
    )

    registry = initialize_registry(base)
    registry = apply_gender_overrides(
        registry=registry,
        gender=gender,
    )
    registry = apply_result_evidence(
        registry=registry,
        evidence=evidence,
    )

    overrides = build_performance_overrides(
        performance
    )
    registry = attach_override_counts(
        registry=registry,
        overrides=overrides,
    )

    checks = build_checks(
        base=base,
        gender=gender,
        evidence=evidence,
        registry=registry,
        overrides=overrides,
    )

    write_outputs(
        registry=registry,
        overrides=overrides,
        checks=checks,
    )

    failed = int(
        (
            checks["failed_row_count"] > 0
        ).sum()
    )

    print(
        "Canonical profile-section registry "
        "build complete."
    )
    print(f"Outputs: {OUTPUT_DIR}")
    print(f"Failed checks: {failed:,}.")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
