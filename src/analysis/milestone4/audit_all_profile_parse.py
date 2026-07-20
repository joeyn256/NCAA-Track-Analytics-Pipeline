#!/usr/bin/env python3
"""
Read-only audit for the Milestone 4 all-profile parser.

Outputs:
  data/processed/milestone4/all_profile_audit/
    audit_report.txt
    hard_checks.csv
    missing_html_profiles.csv
    orphan_html_files.csv
    unresolved_current_school_profiles.csv
    exact_html_duplicate_profiles.csv
    same_name_duplicate_id_inventory.csv
    same_name_exact_url_signature_groups.csv
    same_name_high_url_overlap_pairs.csv

This script never merges athlete IDs automatically.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_DB = PROJECT_ROOT / "data/database/ncaa_track_analytics.duckdb"
STAGING_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/all_profile_staging"
    / "all_profile_staging.duckdb"
)
HTML_DIR = PROJECT_ROOT / "data/raw/athlete_pages"
OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/all_profile_audit"
)
AUDIT_VERSION = "m4_all_profile_audit_v1.1"

NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def clean(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split()).strip()


def normalize_name(value: object) -> str:
    return NON_ALNUM_RE.sub("", clean(value).lower())


def normalize_id_column(
    frame: pd.DataFrame,
    column: str,
) -> pd.DataFrame:
    """Return a copy with an athlete-ID column normalized to int64."""
    if column not in frame.columns:
        return frame

    result = frame.copy()
    numeric = pd.to_numeric(
        result[column],
        errors="raise",
    )
    result[column] = numeric.astype("int64")
    return result


def load_source_summary(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(
        """
        WITH perf AS (
            SELECT
                athlete_id,
                COUNT(*) AS performance_count,
                COUNT(DISTINCT result_url) AS distinct_result_url_count,
                MIN(season_year) AS first_season_year,
                MAX(season_year) AS last_season_year
            FROM core.performances
            GROUP BY athlete_id
        ),
        aff AS (
            SELECT
                athlete_id,
                COUNT(*) AS affiliation_row_count,
                COUNT(DISTINCT team_id) AS affiliation_team_count
            FROM core.athlete_affiliations
            GROUP BY athlete_id
        ),
        school_values AS (
            SELECT DISTINCT
                af.athlete_id,
                s.school_name
            FROM core.athlete_affiliations af
            JOIN core.teams t
              ON af.team_id = t.team_id
            LEFT JOIN core.schools s
              ON t.school_id = s.school_id
            WHERE s.school_name IS NOT NULL
        ),
        school_summary AS (
            SELECT
                athlete_id,
                string_agg(
                    school_name,
                    ' | '
                    ORDER BY school_name
                ) AS affiliation_schools
            FROM school_values
            GROUP BY athlete_id
        )
        SELECT
            a.athlete_id,
            a.athlete_name,
            COALESCE(p.performance_count, 0) AS performance_count,
            COALESCE(
                p.distinct_result_url_count,
                0
            ) AS distinct_result_url_count,
            p.first_season_year,
            p.last_season_year,
            COALESCE(aff.affiliation_row_count, 0)
                AS affiliation_row_count,
            COALESCE(aff.affiliation_team_count, 0)
                AS affiliation_team_count,
            COALESCE(s.affiliation_schools, '')
                AS affiliation_schools
        FROM core.athletes a
        LEFT JOIN perf p
          ON a.athlete_id = p.athlete_id
        LEFT JOIN aff
          ON a.athlete_id = aff.athlete_id
        LEFT JOIN school_summary s
          ON a.athlete_id = s.athlete_id
        ORDER BY a.athlete_id
        """
    ).fetchdf()


def html_id_sets() -> tuple[set[int], list[str]]:
    ids: set[int] = set()
    invalid: list[str] = []

    for path in HTML_DIR.glob("*.html"):
        try:
            ids.add(int(path.stem))
        except ValueError:
            invalid.append(path.name)

    return ids, sorted(invalid)


def build_same_name_audits(
    con: duckdb.DuckDBPyConnection,
    status: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    names = status[
        [
            "athlete_id",
            "athlete_name",
            "current_school",
            "section_count",
            "url_key_count",
        ]
    ].copy()
    names = normalize_id_column(
        names,
        "athlete_id",
    )

    names["normalized_athlete_name"] = (
        names["athlete_name"].map(normalize_name)
    )

    counts = (
        names[names["normalized_athlete_name"] != ""]
        .groupby("normalized_athlete_name")["athlete_id"]
        .transform("count")
    )

    names["same_name_id_count"] = 1
    names.loc[
        names["normalized_athlete_name"] != "",
        "same_name_id_count",
    ] = counts

    inventory = names[
        names["same_name_id_count"] > 1
    ].copy()

    inventory = inventory.sort_values(
        ["normalized_athlete_name", "athlete_id"]
    )

    if inventory.empty:
        return (
            inventory,
            pd.DataFrame(),
            pd.DataFrame(),
        )

    con.register(
        "_same_name_ids",
        inventory[
            [
                "athlete_id",
                "athlete_name",
                "normalized_athlete_name",
                "current_school",
            ]
        ],
    )

    try:
        signatures = con.execute(
            """
            WITH distinct_urls AS (
                SELECT DISTINCT
                    n.athlete_id,
                    n.normalized_athlete_name,
                    u.url_sha256
                FROM _same_name_ids n
                JOIN section_url_keys u
                  ON n.athlete_id = u.athlete_id
            )
            SELECT
                athlete_id,
                normalized_athlete_name,
                COUNT(*) AS distinct_url_count,
                md5(
                    string_agg(
                        url_sha256,
                        '|'
                        ORDER BY url_sha256
                    )
                ) AS url_set_signature
            FROM distinct_urls
            GROUP BY
                athlete_id,
                normalized_athlete_name
            """
        ).fetchdf()
        signatures = normalize_id_column(
            signatures,
            "athlete_id",
        )

        details = inventory.merge(
            signatures,
            how="left",
            on=["athlete_id", "normalized_athlete_name"],
        )

        grouped = (
            details.dropna(subset=["url_set_signature"])
            .groupby(
                [
                    "normalized_athlete_name",
                    "url_set_signature",
                ],
                dropna=False,
            )
            .filter(lambda frame: len(frame) > 1)
        )

        if grouped.empty:
            exact_groups = pd.DataFrame()
        else:
            exact_groups = (
                grouped.groupby(
                    [
                        "normalized_athlete_name",
                        "url_set_signature",
                    ],
                    dropna=False,
                )
                .agg(
                    candidate_id_count=(
                        "athlete_id",
                        "nunique",
                    ),
                    athlete_ids=(
                        "athlete_id",
                        lambda values: " | ".join(
                            str(int(v))
                            for v in sorted(set(values))
                        ),
                    ),
                    athlete_names=(
                        "athlete_name",
                        lambda values: " | ".join(
                            sorted(set(values))
                        ),
                    ),
                    current_schools=(
                        "current_school",
                        lambda values: " | ".join(
                            sorted(
                                {
                                    clean(v)
                                    for v in values
                                    if clean(v)
                                }
                            )
                        ),
                    ),
                    url_key_count=(
                        "distinct_url_count",
                        "max",
                    ),
                )
                .reset_index()
                .sort_values(
                    ["candidate_id_count", "url_key_count"],
                    ascending=[False, False],
                )
            )

        overlap = con.execute(
            """
            WITH distinct_urls AS (
                SELECT DISTINCT
                    n.normalized_athlete_name,
                    n.athlete_id,
                    u.url_sha256
                FROM _same_name_ids n
                JOIN section_url_keys u
                  ON n.athlete_id = u.athlete_id
            ),
            url_counts AS (
                SELECT
                    normalized_athlete_name,
                    athlete_id,
                    COUNT(*) AS url_count
                FROM distinct_urls
                GROUP BY
                    normalized_athlete_name,
                    athlete_id
            ),
            shared AS (
                SELECT
                    a.normalized_athlete_name,
                    a.athlete_id AS athlete_id_1,
                    b.athlete_id AS athlete_id_2,
                    COUNT(*) AS shared_url_count
                FROM distinct_urls a
                JOIN distinct_urls b
                  ON a.normalized_athlete_name
                     = b.normalized_athlete_name
                 AND a.athlete_id < b.athlete_id
                 AND a.url_sha256 = b.url_sha256
                GROUP BY
                    a.normalized_athlete_name,
                    a.athlete_id,
                    b.athlete_id
            )
            SELECT
                shared.normalized_athlete_name,
                shared.athlete_id_1,
                shared.athlete_id_2,
                first.url_count AS url_count_1,
                second.url_count AS url_count_2,
                shared.shared_url_count,
                shared.shared_url_count::DOUBLE
                    / LEAST(
                        first.url_count,
                        second.url_count
                    ) AS containment_ratio,
                shared.shared_url_count::DOUBLE
                    / (
                        first.url_count
                        + second.url_count
                        - shared.shared_url_count
                    ) AS jaccard_ratio
            FROM shared
            JOIN url_counts first
              ON shared.normalized_athlete_name
                 = first.normalized_athlete_name
             AND shared.athlete_id_1
                 = first.athlete_id
            JOIN url_counts second
              ON shared.normalized_athlete_name
                 = second.normalized_athlete_name
             AND shared.athlete_id_2
                 = second.athlete_id
            WHERE shared.shared_url_count >= 5
              AND (
                    shared.shared_url_count::DOUBLE
                    / LEAST(
                        first.url_count,
                        second.url_count
                    )
                  ) >= 0.80
            ORDER BY
                containment_ratio DESC,
                jaccard_ratio DESC,
                shared_url_count DESC
            """
        ).fetchdf()
        if not overlap.empty:
            overlap = normalize_id_column(
                overlap,
                "athlete_id_1",
            )
            overlap = normalize_id_column(
                overlap,
                "athlete_id_2",
            )

    finally:
        con.unregister("_same_name_ids")

    if not overlap.empty:
        left = names[
            ["athlete_id", "athlete_name", "current_school"]
        ].rename(
            columns={
                "athlete_id": "athlete_id_1",
                "athlete_name": "athlete_name_1",
                "current_school": "current_school_1",
            }
        )
        right = names[
            ["athlete_id", "athlete_name", "current_school"]
        ].rename(
            columns={
                "athlete_id": "athlete_id_2",
                "athlete_name": "athlete_name_2",
                "current_school": "current_school_2",
            }
        )

        overlap = (
            overlap.merge(left, on="athlete_id_1", how="left")
            .merge(right, on="athlete_id_2", how="left")
        )

        overlap = overlap[
            [
                "normalized_athlete_name",
                "athlete_id_1",
                "athlete_id_2",
                "athlete_name_1",
                "athlete_name_2",
                "current_school_1",
                "current_school_2",
                "url_count_1",
                "url_count_2",
                "shared_url_count",
                "containment_ratio",
                "jaccard_ratio",
            ]
        ]

    return inventory, exact_groups, overlap


def main() -> None:
    for path in [SOURCE_DB, STAGING_DB, HTML_DIR]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    source_con = duckdb.connect(
        str(SOURCE_DB),
        read_only=True,
    )
    staging_con = duckdb.connect(
        str(STAGING_DB),
        read_only=True,
    )

    try:
        print("Loading athlete-level source summary...")
        source = load_source_summary(source_con)
        source = normalize_id_column(
            source,
            "athlete_id",
        )

        status = staging_con.execute(
            """
            SELECT *
            FROM profile_parse_status
            ORDER BY athlete_id
            """
        ).fetchdf()
        status = normalize_id_column(
            status,
            "athlete_id",
        )

        core_ids = {
            int(v) for v in source["athlete_id"].tolist()
        }
        html_ids, invalid_html_names = html_id_sets()

        missing_ids = sorted(core_ids - html_ids)
        orphan_ids = sorted(html_ids - core_ids)

        missing = source[
            source["athlete_id"].isin(missing_ids)
        ].copy()

        missing = missing.merge(
            status[
                [
                    "athlete_id",
                    "parse_status",
                    "error_type",
                    "error_message",
                ]
            ],
            on="athlete_id",
            how="left",
        ).sort_values("athlete_id")

        orphan = pd.DataFrame(
            {
                "athlete_id_from_filename": orphan_ids,
                "source_html_file": [
                    str(HTML_DIR / f"{athlete_id}.html")
                    for athlete_id in orphan_ids
                ],
            }
        )

        unresolved = status[
            status["current_school_status"]
            == "NO_HEADER_SCHOOL_MATCH"
        ].copy()

        # Join by the stable source ID only. Athlete-name formatting can
        # legitimately differ slightly between source layers.
        unresolved = unresolved.merge(
            source.drop(columns=["athlete_name"]),
            on="athlete_id",
            how="left",
            validate="one_to_one",
        ).sort_values(
            ["performance_count", "athlete_id"],
            ascending=[False, True],
        )

        exact_html = staging_con.execute(
            """
            WITH duplicate_hashes AS (
                SELECT source_html_sha256
                FROM profile_parse_status
                WHERE parse_status = 'OK'
                  AND source_html_sha256 <> ''
                GROUP BY source_html_sha256
                HAVING COUNT(DISTINCT athlete_id) > 1
            )
            SELECT
                p.source_html_sha256,
                p.athlete_id,
                p.athlete_name,
                p.current_school,
                p.section_count,
                p.url_key_count,
                p.source_html_file
            FROM profile_parse_status p
            JOIN duplicate_hashes d
              ON p.source_html_sha256
                 = d.source_html_sha256
            ORDER BY
                p.source_html_sha256,
                p.athlete_id
            """
        ).fetchdf()

        if not exact_html.empty:
            exact_html = normalize_id_column(
                exact_html,
                "athlete_id",
            )
            exact_html = exact_html.merge(
                source[
                    [
                        "athlete_id",
                        "performance_count",
                        "affiliation_schools",
                    ]
                ],
                on="athlete_id",
                how="left",
            )

        print(
            "Auditing same-name URL overlap; "
            "this may take a few minutes..."
        )
        inventory, exact_url_groups, overlap_pairs = (
            build_same_name_audits(
                con=staging_con,
                status=status,
            )
        )

        if not inventory.empty:
            inventory = normalize_id_column(
                inventory,
                "athlete_id",
            )
            inventory = inventory.merge(
                source[
                    [
                        "athlete_id",
                        "performance_count",
                        "distinct_result_url_count",
                        "affiliation_schools",
                    ]
                ],
                on="athlete_id",
                how="left",
            )

        missing.to_csv(
            OUTPUT_DIR / "missing_html_profiles.csv",
            index=False,
        )
        orphan.to_csv(
            OUTPUT_DIR / "orphan_html_files.csv",
            index=False,
        )
        unresolved.to_csv(
            OUTPUT_DIR
            / "unresolved_current_school_profiles.csv",
            index=False,
        )
        exact_html.to_csv(
            OUTPUT_DIR
            / "exact_html_duplicate_profiles.csv",
            index=False,
        )
        inventory.to_csv(
            OUTPUT_DIR
            / "same_name_duplicate_id_inventory.csv",
            index=False,
        )
        exact_url_groups.to_csv(
            OUTPUT_DIR
            / "same_name_exact_url_signature_groups.csv",
            index=False,
        )
        overlap_pairs.to_csv(
            OUTPUT_DIR
            / "same_name_high_url_overlap_pairs.csv",
            index=False,
        )

        duplicate_sections = staging_con.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    athlete_id,
                    section_index,
                    COUNT(*) AS row_count
                FROM profile_sections
                GROUP BY athlete_id, section_index
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]

        duplicate_url_keys = staging_con.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT
                    athlete_id,
                    section_index,
                    url_sha256,
                    COUNT(*) AS row_count
                FROM section_url_keys
                GROUP BY
                    athlete_id,
                    section_index,
                    url_sha256
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]

        recorded = len(status)
        missing_with_perf = int(
            (missing["performance_count"] > 0).sum()
        )
        unresolved_with_perf = int(
            (unresolved["performance_count"] > 0).sum()
        )
        exact_html_athletes = (
            int(exact_html["athlete_id"].nunique())
            if not exact_html.empty
            else 0
        )

        checks = pd.DataFrame(
            [
                {
                    "check_name": (
                        "recorded_profiles_match_core_athletes"
                    ),
                    "failed_row_count": (
                        0
                        if recorded == len(source)
                        else abs(recorded - len(source))
                    ),
                    "observed_value": recorded,
                    "expected_value": len(source),
                    "status_type": "BLOCKING",
                },
                {
                    "check_name": (
                        "duplicate_profile_section_keys"
                    ),
                    "failed_row_count": int(
                        duplicate_sections
                    ),
                    "observed_value": int(
                        duplicate_sections
                    ),
                    "expected_value": 0,
                    "status_type": "BLOCKING",
                },
                {
                    "check_name": (
                        "duplicate_section_url_keys"
                    ),
                    "failed_row_count": int(
                        duplicate_url_keys
                    ),
                    "observed_value": int(
                        duplicate_url_keys
                    ),
                    "expected_value": 0,
                    "status_type": "BLOCKING",
                },
                {
                    "check_name": "missing_HTML_profiles",
                    "failed_row_count": len(missing),
                    "observed_value": len(missing),
                    "expected_value": 0,
                    "status_type": "REVIEW",
                },
                {
                    "check_name": (
                        "missing_HTML_profiles_with_performances"
                    ),
                    "failed_row_count": missing_with_perf,
                    "observed_value": missing_with_perf,
                    "expected_value": 0,
                    "status_type": "BLOCKING",
                },
                {
                    "check_name": (
                        "unresolved_current_school_profiles"
                    ),
                    "failed_row_count": len(unresolved),
                    "observed_value": len(unresolved),
                    "expected_value": 0,
                    "status_type": "REVIEW",
                },
                {
                    "check_name": (
                        "unresolved_current_school_with_performances"
                    ),
                    "failed_row_count": unresolved_with_perf,
                    "observed_value": unresolved_with_perf,
                    "expected_value": 0,
                    "status_type": "BLOCKING",
                },
                {
                    "check_name": (
                        "exact_HTML_duplicate_athletes"
                    ),
                    "failed_row_count": exact_html_athletes,
                    "observed_value": exact_html_athletes,
                    "expected_value": 0,
                    "status_type": "REVIEW",
                },
                {
                    "check_name": (
                        "same_name_exact_URL_signature_groups"
                    ),
                    "failed_row_count": len(
                        exact_url_groups
                    ),
                    "observed_value": len(
                        exact_url_groups
                    ),
                    "expected_value": 0,
                    "status_type": "REVIEW",
                },
                {
                    "check_name": (
                        "same_name_high_URL_overlap_pairs"
                    ),
                    "failed_row_count": len(
                        overlap_pairs
                    ),
                    "observed_value": len(
                        overlap_pairs
                    ),
                    "expected_value": 0,
                    "status_type": "REVIEW",
                },
            ]
        )

        checks.to_csv(
            OUTPUT_DIR / "hard_checks.csv",
            index=False,
        )

        blocking_rows = int(
            checks.loc[
                checks["status_type"] == "BLOCKING",
                "failed_row_count",
            ].sum()
        )
        review_rows = int(
            checks.loc[
                checks["status_type"] == "REVIEW",
                "failed_row_count",
            ].sum()
        )

        report = f"""MILESTONE 4 ALL-PROFILE COVERAGE AND IDENTITY AUDIT
============================================================
Audit version: {AUDIT_VERSION}
Source database modified: no
Staging database modified: no
Raw HTML modified: no

COVERAGE
- Core athletes: {len(source):,}
- Recorded profile statuses: {recorded:,}
- Successful profile parses: {(status['parse_status'] == 'OK').sum():,}
- Non-OK profile parses: {(status['parse_status'] != 'OK').sum():,}
- Missing core-athlete HTML files: {len(missing):,}
- Orphan numeric HTML files: {len(orphan):,}
- Invalid HTML filenames: {len(invalid_html_names):,}

CURRENT-SCHOOL RESOLUTION
- Unresolved current-school profiles: {len(unresolved):,}
- Unresolved profiles with core performances: {unresolved_with_perf:,}

IDENTITY-CANDIDATE AUDIT
- Athletes in exact HTML duplicate groups: {exact_html_athletes:,}
- Same-name exact URL-signature groups: {len(exact_url_groups):,}
- Same-name high-overlap URL pairs: {len(overlap_pairs):,}
- Same-name multi-ID inventory rows: {len(inventory):,}

VALIDATION
- Blocking failure rows: {blocking_rows:,}
- Review findings: {review_rows:,}

INTERPRETATION
Missing HTML and unresolved current-school records must be evaluated before
full performance attribution. Identity candidates are not automatic merges.
Any canonical athlete mapping must preserve every original TFRRS athlete ID,
the evidence used, resolution confidence, and manual-review status.
"""

        (
            OUTPUT_DIR / "audit_report.txt"
        ).write_text(report, encoding="utf-8")

        print("All-profile audit complete.")
        print(f"Outputs: {OUTPUT_DIR}")
        print(f"Blocking failure rows: {blocking_rows:,}")
        print(f"Review findings: {review_rows:,}")

    finally:
        source_con.close()
        staging_con.close()


if __name__ == "__main__":
    main()
