#!/usr/bin/env python3
"""
Milestone 4: duplicate-athlete identity preflight v1.1.

This is a read-only audit. It searches D1 school-stint-eligible performances
for separate TFRRS athlete IDs that repeatedly share exact INDIVIDUAL-event
performance signatures.

Important safeguards
--------------------
1. Relay and medley events are excluded because the same team result may be
   copied onto multiple athlete profiles.
2. Candidate pairs must have the same normalized athlete name.
3. High-confidence pairs must have the same known gender.
4. No profiles are merged and no performance rows are removed.
5. Candidate person components are provisional audit outputs only.

Outputs
-------
data/processed/milestone4/duplicate_athlete_identity_preflight_v1_1/
    identity_report.txt
    hard_checks.csv
    candidate_profile_pairs.csv
    high_confidence_profile_pairs.csv
    review_profile_pairs.csv
    candidate_component_members.csv
    candidate_components.csv
    candidate_pair_examples.csv
    known_pair_validation.csv
    excluded_relay_event_summary.csv
    shared_signature_summary.csv
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]

SOURCE_DB = (
    PROJECT_ROOT
    / "data/database/"
    / "ncaa_track_analytics.duckdb"
)

ATTRIBUTION_DB = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "canonical_performance_attribution_v1_1/"
    / "canonical_performance_attribution_v1_1.duckdb"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data/processed/milestone4/"
    / "duplicate_athlete_identity_preflight_v1_1"
)

PREFLIGHT_VERSION = (
    "m4_duplicate_athlete_identity_preflight_v1.2"
)

EXPECTED_SOURCE_ROWS = 6_594_540
EXPECTED_SOURCE_ATHLETES = 193_961
EXPECTED_ELIGIBLE_ROWS = 6_474_538

KNOWN_PAIRS = [
    {
        "pair_name": "Emily Venters",
        "athlete_id_1": "6550332",
        "athlete_id_2": "7905593",
    },
    {
        "pair_name": "Daniella Hubble",
        "athlete_id_1": "7913457",
        "athlete_id_2": "8932241",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--replace-output",
        action="store_true",
    )

    return parser.parse_args()


def sql_path(path: Path) -> str:
    return (
        path.resolve()
        .as_posix()
        .replace("'", "''")
    )


def require_inputs() -> None:
    for path in [
        SOURCE_DB,
        ATTRIBUTION_DB,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required input not found: {path}"
            )


def prepare_output(
    replace_output: bool,
) -> None:
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    generated = [
        OUTPUT_DIR / "identity_report.txt",
        OUTPUT_DIR / "hard_checks.csv",
        OUTPUT_DIR / "candidate_profile_pairs.csv",
        OUTPUT_DIR / "high_confidence_profile_pairs.csv",
        OUTPUT_DIR / "review_profile_pairs.csv",
        OUTPUT_DIR / "candidate_component_members.csv",
        OUTPUT_DIR / "candidate_components.csv",
        OUTPUT_DIR / "candidate_pair_examples.csv",
        OUTPUT_DIR / "known_pair_validation.csv",
        OUTPUT_DIR / "excluded_relay_event_summary.csv",
        OUTPUT_DIR / "shared_signature_summary.csv",
    ]

    existing = [
        path
        for path in generated
        if path.exists()
    ]

    if existing and not replace_output:
        raise FileExistsError(
            "Existing v1.1 identity-preflight outputs "
            "were found. Use --replace-output only after "
            "reviewing them."
        )

    if replace_output:
        for path in existing:
            path.unlink()


def file_state(
    path: Path,
) -> dict[str, int]:
    stat = path.stat()

    return {
        "size_bytes": int(stat.st_size),
        "modified_ns": int(stat.st_mtime_ns),
    }


def scalar(
    con: duckdb.DuckDBPyConnection,
    query: str,
) -> int:
    return int(
        con.execute(query).fetchone()[0]
    )


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def add(
        self,
        value: str,
    ) -> None:
        if value not in self.parent:
            self.parent[value] = value
            self.rank[value] = 0

    def find(
        self,
        value: str,
    ) -> str:
        self.add(value)

        if self.parent[value] != value:
            self.parent[value] = self.find(
                self.parent[value]
            )

        return self.parent[value]

    def union(
        self,
        left: str,
        right: str,
    ) -> None:
        left_root = self.find(left)
        right_root = self.find(right)

        if left_root == right_root:
            return

        if self.rank[left_root] < self.rank[right_root]:
            self.parent[left_root] = right_root
        elif self.rank[left_root] > self.rank[right_root]:
            self.parent[right_root] = left_root
        else:
            self.parent[right_root] = left_root
            self.rank[left_root] += 1


def candidate_person_id(
    athlete_ids: list[str],
) -> str:
    joined = "|".join(
        sorted(athlete_ids)
    )

    digest = hashlib.sha1(
        joined.encode("utf-8")
    ).hexdigest()[:16]

    return f"m4person_candidate_{digest}"


def build_components(
    high_confidence_pairs: pd.DataFrame,
    profile_lookup: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    member_columns = [
        "candidate_person_id",
        "athlete_id",
        "component_size",
        "athlete_name",
        "normalized_name",
        "current_school_name",
        "current_team_id",
        "dominant_gender_code",
        "total_individual_signatures",
        "first_performance_year",
        "last_performance_year",
    ]

    component_columns = [
        "candidate_person_id",
        "component_size",
        "profile_ids",
        "profile_names",
        "normalized_name",
        "current_schools",
        "current_teams",
        "dominant_gender_code",
        "minimum_shared_signatures",
        "maximum_shared_signatures",
        "pair_edge_count",
    ]

    if high_confidence_pairs.empty:
        return (
            pd.DataFrame(columns=member_columns),
            pd.DataFrame(columns=component_columns),
        )

    union_find = UnionFind()

    for row in high_confidence_pairs.itertuples(
        index=False
    ):
        union_find.union(
            str(row.athlete_id_1),
            str(row.athlete_id_2),
        )

    groups: dict[str, list[str]] = {}

    for athlete_id in union_find.parent:
        root = union_find.find(athlete_id)

        groups.setdefault(
            root,
            [],
        ).append(athlete_id)

    lookup = (
        profile_lookup
        .set_index("athlete_id")
        .to_dict(orient="index")
    )

    member_rows: list[dict[str, object]] = []
    component_rows: list[dict[str, object]] = []

    for members in groups.values():
        members = sorted(set(members))
        person_id = candidate_person_id(members)

        component_pairs = high_confidence_pairs[
            high_confidence_pairs[
                "athlete_id_1"
            ].isin(members)
            & high_confidence_pairs[
                "athlete_id_2"
            ].isin(members)
        ]

        names: list[str] = []
        normalized_names: list[str] = []
        schools: list[str] = []
        teams: list[str] = []
        genders: list[str] = []

        for athlete_id in members:
            profile = lookup.get(
                athlete_id,
                {},
            )

            athlete_name = str(
                profile.get("athlete_name", "")
                or ""
            )
            normalized_name = str(
                profile.get("normalized_name", "")
                or ""
            )
            school = str(
                profile.get("current_school_name", "")
                or ""
            )
            team = str(
                profile.get("current_team_id", "")
                or ""
            )
            gender = str(
                profile.get("dominant_gender_code", "")
                or ""
            )

            if athlete_name:
                names.append(athlete_name)
            if normalized_name:
                normalized_names.append(
                    normalized_name
                )
            if school:
                schools.append(school)
            if team:
                teams.append(team)
            if gender:
                genders.append(gender)

            member_rows.append(
                {
                    "candidate_person_id": person_id,
                    "athlete_id": athlete_id,
                    "component_size": len(members),
                    "athlete_name": athlete_name,
                    "normalized_name": normalized_name,
                    "current_school_name": school,
                    "current_team_id": team,
                    "dominant_gender_code": gender,
                    "total_individual_signatures": (
                        profile.get(
                            "total_individual_signatures",
                            0,
                        )
                    ),
                    "first_performance_year": (
                        profile.get(
                            "first_performance_year"
                        )
                    ),
                    "last_performance_year": (
                        profile.get(
                            "last_performance_year"
                        )
                    ),
                }
            )

        component_rows.append(
            {
                "candidate_person_id": person_id,
                "component_size": len(members),
                "profile_ids": " | ".join(members),
                "profile_names": " | ".join(
                    sorted(set(names))
                ),
                "normalized_name": " | ".join(
                    sorted(set(normalized_names))
                ),
                "current_schools": " | ".join(
                    sorted(set(schools))
                ),
                "current_teams": " | ".join(
                    sorted(set(teams))
                ),
                "dominant_gender_code": " | ".join(
                    sorted(set(genders))
                ),
                "minimum_shared_signatures": int(
                    component_pairs[
                        "shared_signature_count"
                    ].min()
                ),
                "maximum_shared_signatures": int(
                    component_pairs[
                        "shared_signature_count"
                    ].max()
                ),
                "pair_edge_count": len(
                    component_pairs
                ),
            }
        )

    members_df = pd.DataFrame(
        member_rows,
        columns=member_columns,
    ).sort_values(
        [
            "candidate_person_id",
            "athlete_id",
        ]
    )

    components_df = pd.DataFrame(
        component_rows,
        columns=component_columns,
    ).sort_values(
        [
            "component_size",
            "candidate_person_id",
        ],
        ascending=[
            False,
            True,
        ],
    )

    return members_df, components_df


def main() -> None:
    args = parse_args()

    require_inputs()
    prepare_output(
        replace_output=args.replace_output,
    )

    source_before = file_state(SOURCE_DB)
    attribution_before = file_state(
        ATTRIBUTION_DB
    )

    con = duckdb.connect()

    try:
        con.execute("PRAGMA threads=4")
        con.execute(
            "PRAGMA preserve_insertion_order=false"
        )

        con.execute(
            f"""
            ATTACH '{sql_path(SOURCE_DB)}'
            AS source
            (READ_ONLY)
            """
        )

        con.execute(
            f"""
            ATTACH '{sql_path(ATTRIBUTION_DB)}'
            AS attribution
            (READ_ONLY)
            """
        )

        print(
            "Building D1-eligible performance scope..."
        )

        con.execute(
            """
            CREATE TEMP TABLE eligible AS
            SELECT
                p.performance_id,
                p.athlete_id,
                p.athlete_name,
                p.season_id,
                p.season_year,
                p.season_type,
                p.meet_id,
                p.meet_name,
                p.meet_date_text,
                p.event,
                p.mark,
                p.secondary_mark,
                p.wind,
                p.place,
                p.competition_round,
                p.raw_place,
                p.result_url,

                a.canonical_gender_code,

                CASE
                    WHEN lower(
                        trim(
                            COALESCE(p.event, '')
                        )
                    ) LIKE '4x%'
                    THEN TRUE

                    WHEN lower(
                        COALESCE(p.event, '')
                    ) LIKE '%relay%'
                    THEN TRUE

                    WHEN lower(
                        trim(
                            COALESCE(p.event, '')
                        )
                    ) IN (
                        'dmr',
                        'smr'
                    )
                    THEN TRUE

                    WHEN lower(
                        COALESCE(p.event, '')
                    ) LIKE '%medley%'
                    THEN TRUE

                    ELSE FALSE
                END AS is_relay_event

            FROM source.core.performances p

            JOIN attribution.main
                .canonical_performance_attribution a
              ON p.performance_id = a.performance_id

            WHERE a.school_stint_eligible
            """
        )

        relay_summary = con.execute(
            """
            SELECT
                event,
                COUNT(*) AS performance_rows,
                COUNT(DISTINCT athlete_id)
                    AS athlete_count,
                COUNT(
                    DISTINCT season_id
                        || '|'
                        || meet_id
                ) AS meet_instance_count

            FROM eligible

            WHERE is_relay_event

            GROUP BY event

            ORDER BY
                performance_rows DESC,
                event
            """
        ).fetchdf()

        print(
            "Building individual-event signatures..."
        )

        con.execute(
            """
            CREATE TEMP TABLE athlete_signatures AS
            SELECT
                athlete_id,

                md5(
                    COALESCE(season_id, '')
                    || chr(31)
                    || COALESCE(meet_id, '')
                    || chr(31)
                    || COALESCE(event, '')
                    || chr(31)
                    || COALESCE(mark, '')
                    || chr(31)
                    || COALESCE(
                        secondary_mark,
                        ''
                    )
                    || chr(31)
                    || COALESCE(wind, '')
                    || chr(31)
                    || COALESCE(place, '')
                    || chr(31)
                    || COALESCE(
                        competition_round,
                        ''
                    )
                    || chr(31)
                    || COALESCE(raw_place, '')
                    || chr(31)
                    || COALESCE(result_url, '')
                ) AS performance_signature,

                MIN(performance_id)
                    AS example_performance_id,

                MIN(athlete_name)
                    AS example_athlete_name,

                MIN(season_id)
                    AS season_id,

                MIN(season_year)
                    AS season_year,

                MIN(season_type)
                    AS season_type,

                MIN(meet_id)
                    AS meet_id,

                MIN(meet_name)
                    AS meet_name,

                MIN(meet_date_text)
                    AS meet_date_text,

                MIN(event)
                    AS event,

                MIN(mark)
                    AS mark,

                MIN(place)
                    AS place,

                MIN(result_url)
                    AS result_url,

                COUNT(*) AS source_row_count

            FROM eligible

            WHERE NOT is_relay_event

            GROUP BY
                athlete_id,
                performance_signature
            """
        )

        con.execute(
            """
            CREATE TEMP TABLE dominant_gender AS
            WITH counts AS (
                SELECT
                    athlete_id,
                    canonical_gender_code,
                    COUNT(*) AS performance_rows

                FROM eligible

                WHERE NULLIF(
                    canonical_gender_code,
                    ''
                ) IS NOT NULL

                GROUP BY
                    athlete_id,
                    canonical_gender_code
            )
            SELECT
                athlete_id,

                arg_max(
                    canonical_gender_code,
                    performance_rows
                ) AS dominant_gender_code

            FROM counts

            GROUP BY athlete_id
            """
        )

        con.execute(
            """
            CREATE TEMP TABLE profile_stats AS
            WITH signature_counts AS (
                SELECT
                    athlete_id,

                    COUNT(*)
                        AS total_individual_signatures,

                    SUM(source_row_count)
                        AS total_individual_source_rows,

                    MIN(season_year)
                        AS first_performance_year,

                    MAX(season_year)
                        AS last_performance_year

                FROM athlete_signatures

                GROUP BY athlete_id
            )
            SELECT
                a.athlete_id,
                a.athlete_name,

                regexp_replace(
                    lower(
                        CASE
                            WHEN position(
                                ',' IN COALESCE(
                                    a.athlete_name,
                                    ''
                                )
                            ) > 0
                            THEN
                                trim(
                                    split_part(
                                        a.athlete_name,
                                        ',',
                                        2
                                    )
                                )
                                || ' '
                                || trim(
                                    split_part(
                                        a.athlete_name,
                                        ',',
                                        1
                                    )
                                )
                            ELSE COALESCE(
                                a.athlete_name,
                                ''
                            )
                        END
                    ),
                    '[^a-z0-9]+',
                    '',
                    'g'
                ) AS normalized_name,

                a.current_school_name,
                a.current_team_id,
                g.dominant_gender_code,

                COALESCE(
                    s.total_individual_signatures,
                    0
                ) AS total_individual_signatures,

                COALESCE(
                    s.total_individual_source_rows,
                    0
                ) AS total_individual_source_rows,

                s.first_performance_year,
                s.last_performance_year

            FROM source.core.athletes a

            LEFT JOIN signature_counts s
              ON a.athlete_id = s.athlete_id

            LEFT JOIN dominant_gender g
              ON a.athlete_id = g.athlete_id
            """
        )

        print(
            "Finding individual signatures shared "
            "across profiles..."
        )

        con.execute(
            """
            CREATE TEMP TABLE shared_signatures AS
            SELECT
                performance_signature,
                COUNT(DISTINCT athlete_id)
                    AS profile_count

            FROM athlete_signatures

            GROUP BY performance_signature

            HAVING COUNT(
                DISTINCT athlete_id
            ) > 1
            """
        )

        shared_signature_summary = con.execute(
            """
            SELECT
                profile_count,
                COUNT(*) AS signature_count

            FROM shared_signatures

            GROUP BY profile_count

            ORDER BY profile_count
            """
        ).fetchdf()

        print(
            "Aggregating same-name candidate pairs..."
        )

        con.execute(
            """
            CREATE TEMP TABLE pair_shared AS
            SELECT
                a.athlete_id
                    AS athlete_id_1,

                b.athlete_id
                    AS athlete_id_2,

                COUNT(*)
                    AS shared_signature_count,

                COUNT(
                    DISTINCT a.season_id
                ) AS shared_season_count,

                COUNT(
                    DISTINCT a.season_id
                        || '|'
                        || a.meet_id
                ) AS shared_meet_instance_count,

                MIN(a.season_year)
                    AS first_shared_year,

                MAX(a.season_year)
                    AS last_shared_year

            FROM athlete_signatures a

            JOIN shared_signatures shared
              ON a.performance_signature
                    = shared.performance_signature

            JOIN athlete_signatures b
              ON a.performance_signature
                    = b.performance_signature
             AND a.athlete_id
                    < b.athlete_id

            JOIN profile_stats p1
              ON a.athlete_id = p1.athlete_id

            JOIN profile_stats p2
              ON b.athlete_id = p2.athlete_id

            WHERE NULLIF(
                    p1.normalized_name,
                    ''
                  ) IS NOT NULL
              AND p1.normalized_name
                    = p2.normalized_name

            GROUP BY
                a.athlete_id,
                b.athlete_id
            """
        )

        con.execute(
            """
            CREATE TEMP TABLE candidate_pairs AS
            SELECT
                pair.athlete_id_1,
                pair.athlete_id_2,

                p1.athlete_name
                    AS athlete_name_1,

                p2.athlete_name
                    AS athlete_name_2,

                p1.normalized_name,

                p1.current_school_name
                    AS current_school_name_1,

                p2.current_school_name
                    AS current_school_name_2,

                p1.current_team_id
                    AS current_team_id_1,

                p2.current_team_id
                    AS current_team_id_2,

                p1.dominant_gender_code
                    AS dominant_gender_code_1,

                p2.dominant_gender_code
                    AS dominant_gender_code_2,

                p1.total_individual_signatures
                    AS total_individual_signatures_1,

                p2.total_individual_signatures
                    AS total_individual_signatures_2,

                pair.shared_signature_count,
                pair.shared_season_count,
                pair.shared_meet_instance_count,
                pair.first_shared_year,
                pair.last_shared_year,

                ROUND(
                    pair.shared_signature_count
                    / NULLIF(
                        LEAST(
                            p1.total_individual_signatures,
                            p2.total_individual_signatures
                        ),
                        0
                    ),
                    6
                ) AS overlap_ratio_smaller_profile,

                ROUND(
                    pair.shared_signature_count
                    / NULLIF(
                        GREATEST(
                            p1.total_individual_signatures,
                            p2.total_individual_signatures
                        ),
                        0
                    ),
                    6
                ) AS overlap_ratio_larger_profile,

                CASE
                    WHEN NULLIF(
                            p1.dominant_gender_code,
                            ''
                         ) IS NOT NULL
                     AND p1.dominant_gender_code
                            = p2.dominant_gender_code
                     AND pair.shared_signature_count >= 2
                     AND (
                            pair.shared_signature_count
                            / NULLIF(
                                LEAST(
                                    p1.total_individual_signatures,
                                    p2.total_individual_signatures
                                ),
                                0
                            )
                         ) >= 0.25
                    THEN
                        'HIGH_CONFIDENCE_INDIVIDUAL_OVERLAP'

                    WHEN NULLIF(
                            p1.dominant_gender_code,
                            ''
                         ) IS NULL
                      OR NULLIF(
                            p2.dominant_gender_code,
                            ''
                         ) IS NULL
                    THEN
                        'REVIEW_MISSING_GENDER'

                    WHEN p1.dominant_gender_code
                            != p2.dominant_gender_code
                    THEN
                        'REJECT_GENDER_MISMATCH'

                    ELSE
                        'REVIEW_LOW_OVERLAP'
                END AS candidate_tier

            FROM pair_shared pair

            JOIN profile_stats p1
              ON pair.athlete_id_1
                    = p1.athlete_id

            JOIN profile_stats p2
              ON pair.athlete_id_2
                    = p2.athlete_id
            """
        )

        candidate_pairs = con.execute(
            """
            SELECT *
            FROM candidate_pairs

            ORDER BY
                CASE candidate_tier
                    WHEN
                    'HIGH_CONFIDENCE_INDIVIDUAL_OVERLAP'
                    THEN 1
                    WHEN
                    'REVIEW_LOW_OVERLAP'
                    THEN 2
                    WHEN
                    'REVIEW_MISSING_GENDER'
                    THEN 3
                    ELSE 4
                END,
                shared_signature_count DESC,
                overlap_ratio_smaller_profile DESC,
                athlete_id_1,
                athlete_id_2
            """
        ).fetchdf()

        high_confidence = candidate_pairs.loc[
            candidate_pairs[
                "candidate_tier"
            ].eq(
                "HIGH_CONFIDENCE_INDIVIDUAL_OVERLAP"
            )
        ].copy()

        review_pairs = candidate_pairs.loc[
            ~candidate_pairs[
                "candidate_tier"
            ].eq(
                "HIGH_CONFIDENCE_INDIVIDUAL_OVERLAP"
            )
        ].copy()

        profile_lookup = con.execute(
            """
            SELECT *
            FROM profile_stats
            """
        ).fetchdf()

        (
            component_members,
            components,
        ) = build_components(
            high_confidence_pairs=high_confidence,
            profile_lookup=profile_lookup,
        )

        pair_examples = con.execute(
            """
            WITH examples AS (
                SELECT
                    pair.athlete_id_1,
                    pair.athlete_id_2,

                    a.example_performance_id
                        AS performance_id_1,

                    b.example_performance_id
                        AS performance_id_2,

                    a.season_id,
                    a.season_year,
                    a.season_type,
                    a.meet_id,
                    a.meet_name,
                    a.meet_date_text,
                    a.event,
                    a.mark,
                    a.place,
                    a.result_url,

                    ROW_NUMBER()
                        OVER (
                            PARTITION BY
                                pair.athlete_id_1,
                                pair.athlete_id_2
                            ORDER BY
                                a.season_year,
                                a.season_id,
                                a.meet_id,
                                a.event,
                                a.mark
                        ) AS example_number

                FROM candidate_pairs pair

                JOIN athlete_signatures a
                  ON pair.athlete_id_1
                        = a.athlete_id

                JOIN athlete_signatures b
                  ON pair.athlete_id_2
                        = b.athlete_id
                 AND a.performance_signature
                        = b.performance_signature
            )
            SELECT *
            EXCLUDE (example_number)

            FROM examples

            WHERE example_number <= 5

            ORDER BY
                athlete_id_1,
                athlete_id_2,
                season_year,
                season_id,
                meet_id
            """
        ).fetchdf()

        known_pairs_df = pd.DataFrame(
            KNOWN_PAIRS
        )

        con.register(
            "known_pairs_df",
            known_pairs_df,
        )

        known_validation = con.execute(
            """
            SELECT
                known.pair_name,
                known.athlete_id_1,
                known.athlete_id_2,

                COALESCE(
                    pair.shared_signature_count,
                    0
                ) AS observed_individual_shared_signatures,

                pair.shared_season_count,
                pair.shared_meet_instance_count,
                pair.overlap_ratio_smaller_profile,
                pair.overlap_ratio_larger_profile,
                pair.candidate_tier,

                CASE
                    WHEN pair.candidate_tier
                        =
                        'HIGH_CONFIDENCE_INDIVIDUAL_OVERLAP'
                    THEN TRUE
                    ELSE FALSE
                END AS validation_passed

            FROM known_pairs_df known

            LEFT JOIN candidate_pairs pair
              ON known.athlete_id_1
                    = pair.athlete_id_1
             AND known.athlete_id_2
                    = pair.athlete_id_2

            ORDER BY known.pair_name
            """
        ).fetchdf()

        source_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM source.core.performances
            """,
        )

        source_athletes = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM source.core.athletes
            """,
        )

        eligible_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM eligible
            """,
        )

        distinct_eligible_ids = scalar(
            con,
            """
            SELECT COUNT(
                DISTINCT performance_id
            )
            FROM eligible
            """,
        )

        relay_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM eligible
            WHERE is_relay_event
            """,
        )

        individual_rows = scalar(
            con,
            """
            SELECT COUNT(*)
            FROM eligible
            WHERE NOT is_relay_event
            """,
        )

        duplicate_pairs = int(
            len(candidate_pairs)
            - candidate_pairs[
                [
                    "athlete_id_1",
                    "athlete_id_2",
                ]
            ]
            .drop_duplicates()
            .shape[0]
        )

        self_pairs = int(
            (
                candidate_pairs["athlete_id_1"]
                == candidate_pairs["athlete_id_2"]
            ).sum()
        )

        high_gender_mismatch = int(
            (
                high_confidence[
                    "dominant_gender_code_1"
                ]
                != high_confidence[
                    "dominant_gender_code_2"
                ]
            ).sum()
            if not high_confidence.empty
            else 0
        )

        high_name_mismatch = int(
            (
                high_confidence[
                    "normalized_name"
                ].isna()
                | high_confidence[
                    "normalized_name"
                ].eq("")
            ).sum()
            if not high_confidence.empty
            else 0
        )

        athlete_multiple_components = int(
            (
                component_members.groupby(
                    "athlete_id"
                )["candidate_person_id"]
                .nunique()
                > 1
            ).sum()
            if not component_members.empty
            else 0
        )

        component_multiple_names = int(
            components[
                "normalized_name"
            ].fillna("")
            .str.contains(
                r"\|",
                regex=True,
            )
            .sum()
            if not components.empty
            else 0
        )

        source_after = file_state(SOURCE_DB)
        attribution_after = file_state(
            ATTRIBUTION_DB
        )

        check_rows: list[
            tuple[str, int, object, object]
        ] = [
            (
                "source_performance_rows",
                abs(
                    source_rows
                    - EXPECTED_SOURCE_ROWS
                ),
                source_rows,
                EXPECTED_SOURCE_ROWS,
            ),
            (
                "source_athlete_rows",
                abs(
                    source_athletes
                    - EXPECTED_SOURCE_ATHLETES
                ),
                source_athletes,
                EXPECTED_SOURCE_ATHLETES,
            ),
            (
                "eligible_performance_rows",
                abs(
                    eligible_rows
                    - EXPECTED_ELIGIBLE_ROWS
                ),
                eligible_rows,
                EXPECTED_ELIGIBLE_ROWS,
            ),
            (
                "distinct_eligible_performance_ids",
                abs(
                    distinct_eligible_ids
                    - EXPECTED_ELIGIBLE_ROWS
                ),
                distinct_eligible_ids,
                EXPECTED_ELIGIBLE_ROWS,
            ),
            (
                "relay_plus_individual_rows",
                abs(
                    relay_rows
                    + individual_rows
                    - eligible_rows
                ),
                relay_rows + individual_rows,
                eligible_rows,
            ),
            (
                "duplicate_candidate_pairs",
                duplicate_pairs,
                duplicate_pairs,
                0,
            ),
            (
                "self_candidate_pairs",
                self_pairs,
                self_pairs,
                0,
            ),
            (
                "high_confidence_gender_mismatches",
                high_gender_mismatch,
                high_gender_mismatch,
                0,
            ),
            (
                "high_confidence_name_mismatches",
                high_name_mismatch,
                high_name_mismatch,
                0,
            ),
            (
                "athletes_in_multiple_components",
                athlete_multiple_components,
                athlete_multiple_components,
                0,
            ),
            (
                "components_with_multiple_normalized_names",
                component_multiple_names,
                component_multiple_names,
                0,
            ),
            (
                "source_size_unchanged",
                abs(
                    source_after["size_bytes"]
                    - source_before["size_bytes"]
                ),
                source_after["size_bytes"],
                source_before["size_bytes"],
            ),
            (
                "source_modified_time_unchanged",
                abs(
                    source_after["modified_ns"]
                    - source_before["modified_ns"]
                ),
                source_after["modified_ns"],
                source_before["modified_ns"],
            ),
            (
                "attribution_size_unchanged",
                abs(
                    attribution_after["size_bytes"]
                    - attribution_before[
                        "size_bytes"
                    ]
                ),
                attribution_after["size_bytes"],
                attribution_before["size_bytes"],
            ),
            (
                "attribution_modified_time_unchanged",
                abs(
                    attribution_after["modified_ns"]
                    - attribution_before[
                        "modified_ns"
                    ]
                ),
                attribution_after["modified_ns"],
                attribution_before["modified_ns"],
            ),
        ]

        for row in known_validation.itertuples(
            index=False
        ):
            check_rows.append(
                (
                    "known_pair_"
                    + str(row.pair_name)
                    .lower()
                    .replace(" ", "_"),
                    0 if row.validation_passed else 1,
                    row.candidate_tier,
                    (
                        "HIGH_CONFIDENCE_"
                        "INDIVIDUAL_OVERLAP"
                    ),
                )
            )

        checks = pd.DataFrame(
            check_rows,
            columns=[
                "check_name",
                "failed_row_count",
                "observed_value",
                "expected_value",
            ],
        )

        candidate_pairs.to_csv(
            OUTPUT_DIR
            / "candidate_profile_pairs.csv",
            index=False,
        )

        high_confidence.to_csv(
            OUTPUT_DIR
            / "high_confidence_profile_pairs.csv",
            index=False,
        )

        review_pairs.to_csv(
            OUTPUT_DIR
            / "review_profile_pairs.csv",
            index=False,
        )

        component_members.to_csv(
            OUTPUT_DIR
            / "candidate_component_members.csv",
            index=False,
        )

        components.to_csv(
            OUTPUT_DIR
            / "candidate_components.csv",
            index=False,
        )

        pair_examples.to_csv(
            OUTPUT_DIR
            / "candidate_pair_examples.csv",
            index=False,
        )

        known_validation.to_csv(
            OUTPUT_DIR
            / "known_pair_validation.csv",
            index=False,
        )

        relay_summary.to_csv(
            OUTPUT_DIR
            / "excluded_relay_event_summary.csv",
            index=False,
        )

        shared_signature_summary.to_csv(
            OUTPUT_DIR
            / "shared_signature_summary.csv",
            index=False,
        )

        checks.to_csv(
            OUTPUT_DIR
            / "hard_checks.csv",
            index=False,
        )

        failed = int(
            (
                checks["failed_row_count"] > 0
            ).sum()
        )

        component_profiles = int(
            component_members[
                "athlete_id"
            ].nunique()
            if not component_members.empty
            else 0
        )

        report = f"""MILESTONE 4 DUPLICATE-ATHLETE IDENTITY PREFLIGHT V1.1
============================================================
Preflight version: {PREFLIGHT_VERSION}
Source database modified: no
Attribution database modified: no
Profiles merged: no
Performance rows removed: no
Canonical-person IDs finalized: no

SCOPE
- Source performance rows: {source_rows:,}
- Source athlete profiles: {source_athletes:,}
- D1 school-stint-eligible rows: {eligible_rows:,}
- Relay/medley rows excluded from identity evidence:
  {relay_rows:,}
- Individual-event rows retained:
  {individual_rows:,}
- Distinct athlete individual-event signatures:
  {scalar(con, "SELECT COUNT(*) FROM athlete_signatures"):,}
- Individual signatures shared across profiles:
  {scalar(con, "SELECT COUNT(*) FROM shared_signatures"):,}

STRICT SAME-NAME CANDIDATES
- Candidate profile pairs: {len(candidate_pairs):,}
- High-confidence individual-overlap pairs:
  {len(high_confidence):,}
- Review pairs: {len(review_pairs):,}

PROVISIONAL COMPONENTS
- Candidate person components: {len(components):,}
- Athlete profiles represented: {component_profiles:,}
- Components containing more than two profiles:
  {int((components["component_size"] > 2).sum()) if not components.empty else 0:,}
- Components with multiple normalized names:
  {component_multiple_names:,}

VALIDATION CASES
- Emily Venters:
  {int(known_validation.loc[known_validation["pair_name"] == "Emily Venters", "observed_individual_shared_signatures"].iloc[0]):,}
  shared individual signatures
- Daniella Hubble:
  {int(known_validation.loc[known_validation["pair_name"] == "Daniella Hubble", "observed_individual_shared_signatures"].iloc[0]):,}
  shared individual signatures

VALIDATION
- Hard checks: {len(checks):,}
- Failed hard checks: {failed:,}

INTERPRETATION
Version 1.0 incorrectly allowed relay results to connect unrelated teammates
and normalized names after stripping uppercase letters. Version 1.2 excludes
relay and medley events, normalizes names correctly, requires the same
normalized name, requires matching known gender for high-confidence
components, and validates the canonical normalized-name field rather than raw
display-name order. All components remain provisional until audited.
"""

        (
            OUTPUT_DIR
            / "identity_report.txt"
        ).write_text(
            report,
            encoding="utf-8",
        )

        print(
            "Duplicate-athlete identity preflight "
            "v1.1 complete."
        )
        print(f"Outputs: {OUTPUT_DIR}")
        print(f"Failed checks: {failed:,}.")

        if failed:
            raise SystemExit(1)

    finally:
        try:
            con.unregister(
                "known_pairs_df"
            )
        except Exception:
            pass

        con.close()


if __name__ == "__main__":
    main()
