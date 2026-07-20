#!/usr/bin/env python3
"""
NCAA Division I Seasonal Athlete Development Explorer

Run from the repository root:

    streamlit run src/apps/seasonal_development_explorer.py

The app reads the frozen Milestone 5 all-time average-development publication and the final Milestone 6 seasonal and event-balanced publications.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pandas as pd
import streamlit as st


APP_TITLE: Final = "NCAA Division I Athlete Development Explorer"

ROOT = Path(__file__).resolve().parents[2]

BROAD_DATA_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "seasonal_development_rankings_v1/"
      "phase_6a_seasonal_rankings"
)
ELITE_DATA_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "seasonal_elite_development_v1/"
      "phase_6b_seasonal_elite_rankings"
)
ALL_TIME_AVERAGE_DATA_DIR = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5i_publication_freeze"
)
POINTS_DATA_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "final_development_rankings_v1/"
      "phase_6g_final_publication"
)

POINTS_FILES = {
    "model_registry": "model_registry.csv",
    "athlete_rows": "athlete_model_points.csv",
    "event_rows": "event_balanced_point_rows.csv",
    "overall_gender": "event_balanced_overall_gender.csv",
    "overall_combined": "event_balanced_overall_combined.csv",
    "group_gender": "group_balanced_points_gender.csv",
    "group_combined": "group_balanced_points_combined.csv",
    "group_overall_gender": "group_balanced_overall_gender.csv",
    "group_overall_combined": "group_balanced_overall_combined.csv",
    "event_budget_audit": "event_budget_audit.csv",
    "group_budget_audit": "group_budget_audit.csv",
    "concentration": "event_concentration_diagnostics.csv",
    "roster_dependence": "roster_size_dependence.csv",
    "elite_reward": "elite_reward_audit.csv",
    "elite_reward_summary":
        "elite_reward_monotonicity_summary.csv",
    "rank_comparison": "model_rank_comparison_summary.csv",
    "rank_comparison_school":
        "model_rank_comparison_school.csv",
    "final_decision": "final_model_decision.csv",
    "final_scorecard": "final_model_scorecard.csv",
}

ALL_TIME_AVERAGE_FILES = {
    "Overall": "all_school_rankings.csv",
    "Men": "mens_rankings.csv",
    "Women": "womens_rankings.csv",
    "Event Family": "event_family_rankings.csv",
}

POINT_COHORT_KEYS = {
    "Broad — All Athletes": "broad_all_athletes",
    "Frontier — Baseline 70+": "frontier_70_plus",
    "Elite — Baseline 80+": "elite_80_plus",
    "National Elite Finishers — Endpoint 90+":
        "national_elite_endpoint_90_plus",
    "Championship-Caliber Finishers — Endpoint 95+":
        "championship_endpoint_95_plus",
}

BROAD_FILES = {
    "Overall": "season_overall_rankings.csv",
    "Overall by Gender": "season_gender_rankings.csv",
    "Individual Event by Gender":
        "season_individual_event_rankings.csv",
    "Individual Event — Combined":
        "season_combined_gender_event_rankings.csv",
    "Event Group by Gender":
        "season_event_group_rankings.csv",
    "Event Group — Combined":
        "season_combined_gender_group_rankings.csv",
}

ELITE_FILES = {
    "Overall": "elite_season_overall_rankings.csv",
    "Overall by Gender": "elite_season_gender_rankings.csv",
    "Individual Event by Gender":
        "elite_season_event_gender_rankings.csv",
    "Individual Event — Combined":
        "elite_season_event_combined_rankings.csv",
    "Event Group by Gender":
        "elite_season_group_gender_rankings.csv",
    "Event Group — Combined":
        "elite_season_group_combined_rankings.csv",
}

COHORTS = {
    "Broad — All Athletes": {
        "cohort_key": None,
        "data_dir": BROAD_DATA_DIR,
        "files": BROAD_FILES,
        "overall_file": "season_overall_rankings.csv",
        "coverage_file": "season_coverage_summary.csv",
        "partition_file": "season_partition_summary.csv",
        "description": (
            "Primary ranking. Every eligible athlete-school unit receives "
            "one total vote."
        ),
    },
    "Frontier — Baseline 70+": {
        "cohort_key": "frontier_70_plus",
        "data_dir": ELITE_DATA_DIR,
        "files": ELITE_FILES,
        "overall_file": "elite_season_overall_rankings.csv",
        "coverage_file": "elite_season_coverage.csv",
        "partition_file": "elite_partition_summary.csv",
        "description": (
            "Athletes whose trajectory began at normalized performance "
            "level 70 or higher."
        ),
    },
    "Elite — Baseline 80+": {
        "cohort_key": "elite_80_plus",
        "data_dir": ELITE_DATA_DIR,
        "files": ELITE_FILES,
        "overall_file": "elite_season_overall_rankings.csv",
        "coverage_file": "elite_season_coverage.csv",
        "partition_file": "elite_partition_summary.csv",
        "description": (
            "Athletes whose trajectory began at normalized performance "
            "level 80 or higher."
        ),
    },
    "National Elite Finishers — Endpoint 90+": {
        "cohort_key": "national_elite_endpoint_90_plus",
        "data_dir": ELITE_DATA_DIR,
        "files": ELITE_FILES,
        "overall_file": "elite_season_overall_rankings.csv",
        "coverage_file": "elite_season_coverage.csv",
        "partition_file": "elite_partition_summary.csv",
        "description": (
            "Athletes whose trajectory ended at normalized performance "
            "level 90 or higher. This emphasizes development into "
            "nationally elite performance."
        ),
    },
    "Championship-Caliber Finishers — Endpoint 95+": {
        "cohort_key": "championship_endpoint_95_plus",
        "data_dir": ELITE_DATA_DIR,
        "files": ELITE_FILES,
        "overall_file": "elite_season_overall_rankings.csv",
        "coverage_file": "elite_season_coverage.csv",
        "partition_file": "elite_partition_summary.csv",
        "description": (
            "Athletes whose trajectory ended at normalized performance "
            "level 95 or higher. This is extremely selective and should "
            "be treated as an exploratory development view."
        ),
    },
}


def configure_page() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )


@st.cache_data(show_spinner=False)
def load_csv(
    path: str,
    modified_ns: int,
    size_bytes: int,
) -> pd.DataFrame:
    # modified_ns and size_bytes are deliberate cache-key inputs.
    # Rebuilding a publication at the same path now invalidates the cache.
    del modified_ns, size_bytes

    frame = pd.read_csv(path)
    for column in (
        "official_rank_eligible",
        "sample_eligible",
        "partition_publishable",
    ):
        if column in frame.columns:
            frame[column] = (
                frame[column]
                .astype(str)
                .str.lower()
                .map({"true": True, "false": False})
                .fillna(False)
            )
    return frame


def load_csv_file(path: Path) -> pd.DataFrame:
    stat = path.stat()
    return load_csv(
        str(path),
        stat.st_mtime_ns,
        stat.st_size,
    )


def require_data() -> None:
    required: set[Path] = set()

    for config in COHORTS.values():
        data_dir = config["data_dir"]
        required.update(
            data_dir / filename
            for filename in config["files"].values()
        )
        required.add(data_dir / config["coverage_file"])
        required.add(data_dir / config["partition_file"])

    required.update(
        POINTS_DATA_DIR / filename
        for filename in POINTS_FILES.values()
    )
    required.update(
        ALL_TIME_AVERAGE_DATA_DIR / filename
        for filename in ALL_TIME_AVERAGE_FILES.values()
    )

    missing = sorted(str(path) for path in required if not path.exists())

    if missing:
        st.error(
            "The explorer could not find the required Milestone 5 "
            "all-time publication or Milestone 6 publication files."
        )
        st.code("\n".join(missing))
        st.info(
            "Confirm the frozen Milestone 5 publication and final "
            "Milestone 6 publication exist, then refresh this page."
        )
        st.stop()


def cohort_frame(
    cohort_label: str,
    filename: str,
) -> pd.DataFrame:
    config = COHORTS[cohort_label]
    frame = load_csv_file(config["data_dir"] / filename)
    cohort_key = config["cohort_key"]

    if cohort_key is not None and "cohort_key" in frame.columns:
        frame = frame[frame["cohort_key"] == cohort_key].copy()

    return frame


def select_cohort(
    *,
    key: str,
) -> tuple[str, dict[str, object]]:
    cohort_label = st.selectbox(
        "Development cohort",
        list(COHORTS),
        key=key,
        help=(
            "Broad is the primary all-athlete ranking. Baseline cohorts "
            "select athletes by starting level; endpoint cohorts select "
            "athletes by the level they reached."
        ),
    )
    config = COHORTS[cohort_label]
    st.caption(config["description"])

    cohort_key = config["cohort_key"]
    if cohort_key == "national_elite_endpoint_90_plus":
        st.info(
            "Provisional national-elite view: reduced sample thresholds are "
            "used because this endpoint-selected cohort is much smaller "
            "than the primary broad ranking."
        )
    elif cohort_key == "championship_endpoint_95_plus":
        st.warning(
            "Exploratory extreme-elite view: a school may be published with "
            "one qualifying athlete. Use this as a championship-caliber "
            "spotlight, not as a stable whole-program estimate."
        )

    return cohort_label, config


def safe_number(value: object, digits: int = 3) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def official_mask(frame: pd.DataFrame) -> pd.Series:
    if "official_rank_eligible" not in frame.columns:
        return pd.Series(True, index=frame.index)
    return frame["official_rank_eligible"].fillna(False)


def prepare_relative_score(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    if "season_centered_posterior_score" not in frame.columns:
        if {
            "posterior_school_score",
            "global_athlete_mean",
        }.issubset(frame.columns):
            frame["season_centered_posterior_score"] = (
                frame["posterior_school_score"]
                - frame["global_athlete_mean"]
            )
        else:
            frame["season_centered_posterior_score"] = pd.NA
    return frame


def ranking_controls(
    frame: pd.DataFrame,
    view_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    frame = prepare_relative_score(frame)

    left, middle, right = st.columns(3)

    years = sorted(
        frame["season_year"].dropna().astype(int).unique(),
        reverse=True,
    )
    with left:
        year = st.selectbox(
            "Season year",
            years,
            index=0,
            help="The endpoint year of the development trajectory.",
        )

    year_frame = frame[frame["season_year"].astype(int) == year]

    season_types = sorted(
        year_frame["season_type"].dropna().unique(),
        key=lambda value: (value != "indoor", value),
    )
    with middle:
        season_type = st.selectbox(
            "Season type",
            season_types,
            format_func=lambda value: str(value).title(),
        )

    filtered = year_frame[
        year_frame["season_type"] == season_type
    ].copy()

    if "gender_scope" in filtered.columns:
        genders = [
            value
            for value in filtered["gender_scope"].dropna().unique()
            if value != "all"
        ]
        if genders:
            with right:
                gender = st.selectbox(
                    "Gender",
                    sorted(genders),
                    format_func=lambda value: {
                        "m": "Men",
                        "f": "Women",
                    }.get(value, str(value)),
                )
            filtered = filtered[
                filtered["gender_scope"] == gender
            ]
        else:
            right.metric("Gender", "Combined")
    else:
        right.metric("Gender", "Combined")

    if (
        "ranking_label" in filtered.columns
        and filtered["ranking_label"].nunique() > 1
    ):
        labels = sorted(
            filtered["ranking_label"].dropna().unique()
        )
        selected_label = st.selectbox(
            "Event or group",
            labels,
            help=(
                "Choose an individual event or coaching-oriented group."
            ),
        )
        filtered = filtered[
            filtered["ranking_label"] == selected_label
        ]

    partition_frame = filtered.copy()

    st.markdown("#### Refine results")
    search_col, sample_col, official_col, sort_col = st.columns(
        [2.2, 1.2, 1.2, 1.5]
    )

    with search_col:
        school_search = st.text_input(
            "Search school",
            placeholder="Type Arkansas, Air Force, Texas…",
            key=f"school_search_{view_name}",
        )

    maximum_sample = int(
        max(filtered.get("athlete_unit_count", pd.Series([0])).max(), 0)
    )
    with sample_col:
        minimum_sample = st.number_input(
            "Minimum athletes",
            min_value=0,
            max_value=maximum_sample,
            value=0,
            step=1,
            key=f"minimum_sample_{view_name}",
        )

    with official_col:
        official_only = st.checkbox(
            "Published ranks only",
            value=True,
            key=f"official_only_{view_name}",
        )

    sort_options = {
        "Official rank": "official_rank",
        "Season-relative score":
            "season_centered_posterior_score",
        "Posterior score": "posterior_school_score",
        "Sample size": "athlete_unit_count",
    }
    with sort_col:
        sort_label = st.selectbox(
            "Sort by",
            list(sort_options),
            key=f"sort_{view_name}",
        )

    evidence_values = sorted(
        partition_frame.get(
            "evidence_category",
            pd.Series(dtype=str),
        )
        .dropna()
        .unique()
    )
    if evidence_values:
        selected_evidence = st.multiselect(
            "Evidence categories",
            evidence_values,
            default=evidence_values,
            key=f"evidence_{view_name}",
        )
        filtered = filtered[
            filtered["evidence_category"].isin(selected_evidence)
        ]

    if school_search:
        filtered = filtered[
            filtered["school_name"]
            .astype(str)
            .str.contains(
                school_search,
                case=False,
                regex=False,
                na=False,
            )
        ]

    if "athlete_unit_count" in filtered.columns:
        filtered = filtered[
            filtered["athlete_unit_count"] >= minimum_sample
        ]

    if official_only:
        filtered = filtered[official_mask(filtered)]

    sort_column = sort_options[sort_label]
    ascending = sort_column == "official_rank"
    if sort_column in filtered.columns:
        filtered = filtered.sort_values(
            sort_column,
            ascending=ascending,
            na_position="last",
        )

    return filtered, partition_frame, official_only


def show_partition_warning(frame: pd.DataFrame) -> None:
    if frame.empty:
        return

    if (
        "variance_status" in frame.columns
        and (
            frame["variance_status"]
            == "no_detectable_between_school_variance"
        ).all()
    ):
        st.warning(
            "No statistically detectable between-school separation was "
            "found in this partition. The schools should be treated as "
            "tied rather than assigned a meaningful leader."
        )



def show_empty_ranking_state(
    partition_frame: pd.DataFrame,
    official_only: bool,
) -> None:
    if partition_frame.empty:
        st.info("No data exists for this season and ranking selection.")
        return

    variance_status = (
        partition_frame["variance_status"].iloc[0]
        if "variance_status" in partition_frame.columns
        else None
    )
    official_count = int(official_mask(partition_frame).sum())
    eligible_count = int(
        partition_frame.get(
            "sample_eligible",
            pd.Series(False, index=partition_frame.index),
        )
        .fillna(False)
        .sum()
    )
    minimum_sample = (
        int(partition_frame["minimum_sample"].iloc[0])
        if "minimum_sample" in partition_frame.columns
        else None
    )

    if (
        variance_status
        == "no_detectable_between_school_variance"
    ):
        st.warning(
            "No official ranking is published for this partition because "
            "the model found no statistically detectable between-school "
            "separation. Uncheck **Published ranks only** to inspect the "
            "tied diagnostic rows."
        )
        return

    if official_only and official_count == 0:
        threshold_text = (
            f" The minimum is {minimum_sample} athlete units per school."
            if minimum_sample is not None
            else ""
        )
        st.info(
            "No school received a published rank in this partition."
            f" {eligible_count} school(s) met the sample threshold."
            f"{threshold_text} Uncheck **Published ranks only** to inspect "
            "insufficient-data rows."
        )
        return

    st.info(
        "No rows match the school search, sample-size filter, or selected "
        "evidence categories."
    )

def ranking_table(
    frame: pd.DataFrame,
    partition_frame: pd.DataFrame,
    official_only: bool,
) -> None:
    if frame.empty:
        show_empty_ranking_state(
            partition_frame,
            official_only,
        )
        return

    show_partition_warning(frame)

    official_count = int(official_mask(frame).sum())
    represented_count = int(frame["school_name"].nunique())
    athlete_total = int(
        frame.get("athlete_unit_count", pd.Series([0])).sum()
    )
    between_variance = (
        frame["between_school_variance"].iloc[0]
        if "between_school_variance" in frame.columns
        else None
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Schools shown", represented_count)
    c2.metric("Published rows shown", official_count)
    c3.metric("Athlete units shown", f"{athlete_total:,}")
    c4.metric(
        "School variance",
        safe_number(between_variance, 4),
    )

    frame = frame.copy()
    frame["Rank"] = frame.get("official_rank")
    if "variance_status" in frame.columns:
        frame.loc[
            frame["variance_status"]
            == "no_detectable_between_school_variance",
            "Rank",
        ] = pd.NA
    frame["Rank"] = frame["Rank"].apply(
        lambda value: (
            "—"
            if pd.isna(value)
            else str(int(float(value)))
        )
    )

    frame["Season-relative score"] = frame[
        "season_centered_posterior_score"
    ]
    frame["Posterior score"] = frame["posterior_school_score"]
    frame["CI lower"] = frame["posterior_ci95_lower"]
    frame["CI upper"] = frame["posterior_ci95_upper"]
    frame["Athletes"] = frame["athlete_unit_count"]
    frame["Evidence"] = frame["evidence_category"]

    display_columns = [
        "Rank",
        "school_name",
        "Season-relative score",
        "Posterior score",
        "CI lower",
        "CI upper",
        "Athletes",
    ]

    if {
        "mean_baseline_level",
        "mean_endpoint_level",
    }.issubset(frame.columns):
        frame["Baseline level"] = frame["mean_baseline_level"]
        frame["Endpoint level"] = frame["mean_endpoint_level"]
        display_columns.extend(
            ["Baseline level", "Endpoint level"]
        )

    if "publication_tier" in frame.columns:
        frame["Publication tier"] = frame["publication_tier"]
        display_columns.append("Publication tier")

    display_columns.append("Evidence")

    display = frame[display_columns].rename(
        columns={"school_name": "School"}
    )

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_config={
            "Rank": st.column_config.TextColumn(
                help=(
                    "Published rank. An em dash means the school or "
                    "partition is not officially ranked."
                ),
            ),
            "Season-relative score": st.column_config.NumberColumn(
                format="%.4f",
                help=(
                    "Posterior score minus the season/scope national mean."
                ),
            ),
            "Posterior score": st.column_config.NumberColumn(
                format="%.4f",
            ),
            "CI lower": st.column_config.NumberColumn(
                format="%.3f",
            ),
            "CI upper": st.column_config.NumberColumn(
                format="%.3f",
            ),
            "Athletes": st.column_config.NumberColumn(
                format="%d",
            ),
            "Baseline level": st.column_config.NumberColumn(
                format="%.2f",
                help="Mean starting normalized performance level.",
            ),
            "Endpoint level": st.column_config.NumberColumn(
                format="%.2f",
                help="Mean ending normalized performance level.",
            ),
        },
    )

    csv_bytes = display.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download filtered table",
        data=csv_bytes,
        file_name="filtered_seasonal_rankings.csv",
        mime="text/csv",
    )



def normalize_points_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()

    lowercase_columns = (
        "cohort_key",
        "time_scope",
        "season_type",
        "gender_scope",
        "scoring_status",
        "development_direction",
    )
    for column in lowercase_columns:
        if column in frame.columns:
            frame[column] = (
                frame[column]
                .astype("string")
                .str.strip()
                .str.lower()
            )

    label_columns = (
        "cohort_label",
        "season_key",
        "season_label",
        "canonical_event_name",
        "balanced_group_key",
        "balanced_group_label",
        "school_name",
        "athlete_name",
    )
    for column in label_columns:
        if column in frame.columns:
            frame[column] = (
                frame[column]
                .astype("string")
                .str.strip()
            )

    if "season_year" in frame.columns:
        frame["season_year"] = pd.to_numeric(
            frame["season_year"],
            errors="coerce",
        )

    return frame


def points_frame(file_key: str) -> pd.DataFrame:
    path = POINTS_DATA_DIR / POINTS_FILES[file_key]
    return normalize_points_frame(load_csv_file(path))


def model_registry_frame() -> pd.DataFrame:
    frame = points_frame("model_registry")
    if "is_primary" in frame.columns:
        frame["is_primary"] = (
            frame["is_primary"]
            .astype(str)
            .str.lower()
            .map({"true": True, "false": False})
            .fillna(False)
        )
    return frame.sort_values(
        ["is_primary", "model_label"],
        ascending=[False, True],
    )


def model_options() -> dict[str, str]:
    registry = model_registry_frame()
    return dict(
        zip(
            registry["model_label"],
            registry["model_key"],
        )
    )


def model_description(model_key: str) -> str:
    registry = model_registry_frame()
    matched = registry[registry["model_key"] == model_key]
    if matched.empty:
        return ""
    return str(matched.iloc[0]["model_description"])


def final_decision_frame() -> pd.DataFrame:
    return points_frame("final_decision")


def official_model_key() -> str:
    decision = final_decision_frame()
    if decision.empty:
        return "enhanced_balanced_production"
    return str(decision.iloc[0]["selected_model_key"])


def format_gender(value: str) -> str:
    return {
        "m": "Men",
        "f": "Women",
        "all": "Combined",
    }.get(str(value), str(value))


POINT_VIEW_FILES = {
    "Overall — Combined": "overall_combined",
    "Overall — By Gender": "overall_gender",
    "Individual Event": "event_rows",
    "Athlete Contributions": "athlete_rows",
    "Coaching Group — Combined": "group_combined",
    "Coaching Group — By Gender": "group_gender",
    "Group-Balanced Overall — Combined":
        "group_overall_combined",
    "Group-Balanced Overall — By Gender":
        "group_overall_gender",
}


def point_time_options(model_key: str, cohort_key: str) -> list[str]:
    audit = points_frame("event_budget_audit")
    audit = audit[
        (audit["model_key"] == model_key)
        & (audit["cohort_key"] == cohort_key)
    ].copy()

    options: list[str] = []

    if (audit["time_scope"] == "single_season").any():
        options.append("Single Season")

    if (audit["time_scope"] == "all_time").any():
        options.append("All Time")

    season_type_frame = audit[
        audit["time_scope"] == "all_time_season_type"
    ]
    if (season_type_frame["season_type"] == "indoor").any():
        options.append("All-Time Indoor")
    if (season_type_frame["season_type"] == "outdoor").any():
        options.append("All-Time Outdoor")

    return options


def filter_point_time(
    frame: pd.DataFrame,
    time_label: str,
) -> pd.DataFrame:
    if time_label == "Single Season":
        return frame[frame["time_scope"] == "single_season"].copy()

    if time_label == "All Time":
        # Do not require season_type == "all". The time_scope itself is
        # authoritative and this remains compatible with prior publications.
        return frame[frame["time_scope"] == "all_time"].copy()

    if time_label == "All-Time Indoor":
        return frame[
            (frame["time_scope"] == "all_time_season_type")
            & (frame["season_type"] == "indoor")
        ].copy()

    if time_label == "All-Time Outdoor":
        return frame[
            (frame["time_scope"] == "all_time_season_type")
            & (frame["season_type"] == "outdoor")
        ].copy()

    return frame.iloc[0:0].copy()


def available_point_views(
    model_key: str,
    cohort_key: str,
    time_label: str,
) -> list[str]:
    views: list[str] = []

    # Checking the selected files also protects the interface from schema or
    # publication differences between broad and sparse elite cohorts.
    for view_name, file_key in POINT_VIEW_FILES.items():
        frame = points_frame(file_key)
        frame = frame[
            (frame["model_key"] == model_key)
            & (frame["cohort_key"] == cohort_key)
        ].copy()
        frame = filter_point_time(frame, time_label)
        if not frame.empty:
            views.append(view_name)

    return views


def existing_columns(
    frame: pd.DataFrame,
    requested: list[str],
) -> list[str]:
    return [column for column in requested if column in frame.columns]


def event_balanced_points_page() -> None:
    st.subheader("Event-Balanced Development Points")
    st.caption(
        "Every publishable NCAA championship event distributes exactly "
        "100,000 positive points to individual athlete development "
        "contributions. Regression receives separate negative points."
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Event budget", "100,000")
    c2.metric("Group budget", "100,000")
    c3.metric("Unit", "Athlete–school–event")

    st.info(
        "Steeplechase is included in Distance. The 500m, 600m, and 1000m "
        "do not affect the primary championship-event ranking."
    )

    if st.button(
        "Reload generated data",
        key="reload_event_balanced_data",
        help=(
            "Clear the explorer cache after rebuilding Phase 6D files."
        ),
    ):
        st.cache_data.clear()
        st.rerun()

    available_models = model_options()
    model_labels = list(available_models)
    frozen_model_key = official_model_key()
    default_model_index = next(
        (
            index
            for index, label in enumerate(model_labels)
            if available_models[label] == frozen_model_key
        ),
        0,
    )

    model_label = st.selectbox(
        "Scoring model",
        model_labels,
        index=default_model_index,
        key="points_model",
    )
    model_key = available_models[model_label]

    description = model_description(model_key)
    if description:
        st.caption(description)

    if model_key == frozen_model_key:
        st.success(
            "Official Milestone 6 primary model — frozen after support, "
            "negative-pool, rank-stability, concentration, roster-size, "
            "and matched elite validation."
        )
    else:
        st.warning(
            "Preserved balanced-production companion — exact Phase 6D "
            "v4.1 allocation without support reliability or a "
            "negative-pool cap."
        )

    cohort_label = st.selectbox(
        "Development cohort",
        list(POINT_COHORT_KEYS),
        key=f"points_cohort_{model_key}",
    )
    cohort_key = POINT_COHORT_KEYS[cohort_label]

    time_options = point_time_options(model_key, cohort_key)
    if not time_options:
        st.warning(
            "This cohort has no event-balanced publication rows."
        )
        return

    time_label = st.selectbox(
        "Time view",
        time_options,
        key=f"points_time_{model_key}_{cohort_key}",
    )

    views = available_point_views(model_key, cohort_key, time_label)
    if not views:
        st.warning(
            "No point views are available for this cohort and time period."
        )
        return

    view = st.selectbox(
        "Points view",
        views,
        key=f"points_view_{model_key}_{cohort_key}_{time_label}",
    )

    file_key = POINT_VIEW_FILES[view]
    frame = points_frame(file_key)
    frame = frame[
        (frame["model_key"] == model_key)
        & (frame["cohort_key"] == cohort_key)
    ].copy()
    frame = filter_point_time(frame, time_label)

    if frame.empty:
        st.warning(
            "No rows remain after the cohort and time filters."
        )
        return

    selected_period = f"{model_key}_{time_label}"

    if time_label == "Single Season":
        years = sorted(
            frame["season_year"].dropna().astype(int).unique(),
            reverse=True,
        )
        if not years:
            st.warning("No endpoint years are available.")
            return

        year = st.selectbox(
            "Endpoint year",
            years,
            key=f"points_year_{cohort_key}_{view}",
        )

        year_frame = frame[
            frame["season_year"].astype("Int64") == int(year)
        ].copy()

        season_types = sorted(
            year_frame["season_type"].dropna().unique(),
            key=lambda value: (value != "indoor", value),
        )
        if not season_types:
            st.warning("No season types are available for this year.")
            return

        season_type = st.selectbox(
            "Season type",
            season_types,
            format_func=lambda value: str(value).title(),
            key=f"points_season_{cohort_key}_{view}_{year}",
        )

        frame = year_frame[
            year_frame["season_type"] == season_type
        ].copy()
        selected_period = f"{model_key}_{year}_{str(season_type).title()}"

    gender_views = {
        "Overall — By Gender",
        "Individual Event",
        "Athlete Contributions",
        "Coaching Group — By Gender",
        "Group-Balanced Overall — By Gender",
    }
    if "gender_scope" in frame.columns and view in gender_views:
        genders = sorted(frame["gender_scope"].dropna().unique())
        if not genders:
            st.warning("No genders are available for this selection.")
            return

        gender = st.selectbox(
            "Gender",
            genders,
            format_func=format_gender,
            key=f"points_gender_{cohort_key}_{view}_{selected_period}",
        )
        frame = frame[frame["gender_scope"] == gender].copy()

    if view in {"Individual Event", "Athlete Contributions"}:
        events = sorted(
            frame["canonical_event_name"].dropna().unique()
        )
        if not events:
            st.warning("No championship events are available.")
            return

        event = st.selectbox(
            "Championship event",
            events,
            key=(
                f"points_event_{cohort_key}_{view}_"
                f"{selected_period}"
            ),
        )
        frame = frame[
            frame["canonical_event_name"] == event
        ].copy()

    if view in {
        "Coaching Group — Combined",
        "Coaching Group — By Gender",
    }:
        groups = sorted(
            frame["balanced_group_label"].dropna().unique()
        )
        if not groups:
            st.warning("No coaching groups are available.")
            return

        group = st.selectbox(
            "Coaching group",
            groups,
            key=(
                f"points_group_{cohort_key}_{view}_"
                f"{selected_period}"
            ),
        )
        frame = frame[
            frame["balanced_group_label"] == group
        ].copy()

    school_search = st.text_input(
        "School search",
        placeholder="Optional school name",
        key=(
            f"points_school_{cohort_key}_{view}_"
            f"{selected_period}"
        ),
    )
    if school_search and "school_name" in frame.columns:
        frame = frame[
            frame["school_name"]
            .astype(str)
            .str.contains(school_search, case=False, na=False)
        ].copy()

    if view == "Athlete Contributions":
        athlete_search = st.text_input(
            "Athlete search",
            placeholder="Optional athlete name",
            key=(
                f"points_athlete_{cohort_key}_{view}_"
                f"{selected_period}"
            ),
        )
        if athlete_search:
            frame = frame[
                frame["athlete_name"]
                .astype(str)
                .str.contains(
                    athlete_search,
                    case=False,
                    na=False,
                )
            ].copy()

    positive_filter_views = {
        "Individual Event",
        "Athlete Contributions",
        "Coaching Group — Combined",
        "Coaching Group — By Gender",
    }
    if view in positive_filter_views:
        positive_only = st.checkbox(
            "Positive development only",
            value=False,
            key=(
                f"points_positive_{cohort_key}_{view}_"
                f"{selected_period}"
            ),
        )
        if positive_only:
            if view == "Athlete Contributions":
                frame = frame[
                    frame["athlete_positive_points"] > 0
                ].copy()
            elif view == "Individual Event":
                frame = frame[
                    frame["positive_event_points"] > 0
                ].copy()
            else:
                frame = frame[
                    frame["positive_group_points"] > 0
                ].copy()

    if frame.empty:
        st.info("No rows match the selected filters.")
        return

    if view in {
        "Overall — Combined",
        "Overall — By Gender",
    }:
        frame = frame.sort_values(
            ["event_balanced_rank", "school_name"]
        )
        columns = existing_columns(
            frame,
            [
                "event_balanced_rank",
                "school_name",
                "total_positive_event_points",
                "total_negative_event_points",
                "total_event_balanced_points",
                "positive_share_of_available_points",
                "percent_of_available_points",
                "athlete_event_unit_count",
                "scoring_event_count",
                "publishable_event_count",
                "represented_event_count",
                "men_event_balanced_points",
                "women_event_balanced_points",
            ],
        )
        display = frame[columns].rename(
            columns={
                "event_balanced_rank": "Rank",
                "school_name": "School",
                "total_positive_event_points": "Positive points",
                "total_negative_event_points": "Negative points",
                "total_event_balanced_points":
                    "Net development points",
                "positive_share_of_available_points":
                    "Positive share of available points",
                "percent_of_available_points":
                    "Net share of available points",
                "athlete_event_unit_count":
                    "Athlete-event units",
                "scoring_event_count": "Point-earning events",
                "publishable_event_count": "Available events",
                "represented_event_count": "Represented events",
                "men_event_balanced_points": "Men's net points",
                "women_event_balanced_points": "Women's net points",
            }
        )

    elif view == "Individual Event":
        frame = frame.sort_values(["source_rank", "school_name"])
        columns = existing_columns(
            frame,
            [
                "source_rank",
                "school_name",
                "positive_event_points",
                "negative_event_points",
                "net_event_points",
                "positive_event_point_share",
                "event_point_share",
                "athlete_unit_count",
                "positive_athlete_count",
                "negative_athlete_count",
                "school_mean_original_signal",
                "school_mean_model_signal",
                "mean_reliability_factor",
                "raw_negative_to_positive_ratio",
                "negative_pool_was_capped",
                "mean_baseline_level",
                "mean_endpoint_level",
                "evidence_category",
                "reliability_tier",
            ],
        )
        display = frame[columns].rename(
            columns={
                "source_rank": "Event rank",
                "school_name": "School",
                "positive_event_points": "Positive points",
                "negative_event_points": "Negative points",
                "net_event_points": "Net event points",
                "positive_event_point_share":
                    "Positive event share",
                "event_point_share": "Net event share",
                "athlete_unit_count": "Athletes",
                "positive_athlete_count": "Positive athletes",
                "negative_athlete_count": "Regressing athletes",
                "school_mean_original_signal":
                    "Mean original signal",
                "school_mean_model_signal":
                    "Mean model signal",
                "mean_reliability_factor":
                    "Mean reliability factor",
                "raw_negative_to_positive_ratio":
                    "Raw negative/positive ratio",
                "negative_pool_was_capped":
                    "Negative pool capped",
                "mean_baseline_level": "Mean baseline level",
                "mean_endpoint_level": "Mean endpoint level",
                "evidence_category": "Evidence",
                "reliability_tier": "Reliability",
            }
        )

    elif view == "Athlete Contributions":
        frame = frame.sort_values(
            ["athlete_net_points", "athlete_name"],
            ascending=[False, True],
        )
        columns = existing_columns(
            frame,
            [
                "athlete_name",
                "school_name",
                "original_development_signal",
                "model_development_signal",
                "reliability_factor",
                "evidence_support_n",
                "mean_observed_improvement",
                "mean_expected_improvement",
                "athlete_positive_points",
                "athlete_negative_points",
                "athlete_net_points",
                "positive_event_point_share",
                "net_event_point_share",
                "mean_baseline_level",
                "mean_endpoint_level",
                "trajectory_count",
                "development_direction",
            ],
        )
        display = frame[columns].rename(
            columns={
                "athlete_name": "Athlete",
                "school_name": "School",
                "original_development_signal":
                    "Original development signal",
                "model_development_signal":
                    "Model development signal",
                "reliability_factor": "Reliability factor",
                "evidence_support_n": "Evidence support",
                "mean_observed_improvement":
                    "Observed improvement",
                "mean_expected_improvement":
                    "Expected improvement",
                "athlete_positive_points": "Positive points",
                "athlete_negative_points": "Negative points",
                "athlete_net_points": "Net athlete points",
                "positive_event_point_share":
                    "Positive event share",
                "net_event_point_share": "Net event share",
                "mean_baseline_level": "Baseline level",
                "mean_endpoint_level": "Endpoint level",
                "trajectory_count": "Trajectories",
                "development_direction": "Direction",
            }
        )

    elif view in {
        "Coaching Group — Combined",
        "Coaching Group — By Gender",
    }:
        frame = frame.sort_values(
            ["group_source_rank", "school_name"]
        )
        columns = existing_columns(
            frame,
            [
                "group_source_rank",
                "school_name",
                "positive_group_points",
                "negative_group_points",
                "group_balanced_points",
                "positive_group_point_share",
                "group_point_share",
                "athlete_event_unit_count",
                "group_event_count",
                "group_scoring_event_count",
                "group_represented_event_count",
                "available_gender_count",
            ],
        )
        display = frame[columns].rename(
            columns={
                "group_source_rank": "Group rank",
                "school_name": "School",
                "positive_group_points": "Positive group points",
                "negative_group_points": "Negative group points",
                "group_balanced_points": "Net group points",
                "positive_group_point_share":
                    "Positive group share",
                "group_point_share": "Net group share",
                "athlete_event_unit_count":
                    "Athlete-event units",
                "group_event_count": "Available group events",
                "group_scoring_event_count":
                    "Point-earning events",
                "group_represented_event_count":
                    "Represented events",
                "available_gender_count":
                    "Available genders",
            }
        )

    else:
        frame = frame.sort_values(
            ["group_balanced_rank", "school_name"]
        )
        columns = existing_columns(
            frame,
            [
                "group_balanced_rank",
                "school_name",
                "total_positive_group_points",
                "total_negative_group_points",
                "total_group_balanced_points",
                "positive_share_of_available_group_points",
                "percent_of_available_group_points",
                "athlete_event_unit_count",
                "scoring_group_count",
                "publishable_group_count",
                "represented_group_count",
            ],
        )
        display = frame[columns].rename(
            columns={
                "group_balanced_rank": "Rank",
                "school_name": "School",
                "total_positive_group_points":
                    "Positive group points",
                "total_negative_group_points":
                    "Negative group points",
                "total_group_balanced_points":
                    "Net group-balanced points",
                "positive_share_of_available_group_points":
                    "Positive share of available group points",
                "percent_of_available_group_points":
                    "Net share of available group points",
                "athlete_event_unit_count":
                    "Athlete-event units",
                "scoring_group_count": "Point-earning groups",
                "publishable_group_count": "Available groups",
                "represented_group_count":
                    "Represented groups",
            }
        )

    metric_columns = st.columns(4)
    metric_columns[0].metric("Rows shown", f"{len(display):,}")

    if "Positive points" in display.columns:
        metric_columns[1].metric(
            "Positive points shown",
            f"{display['Positive points'].sum():,.2f}",
        )
    elif "Positive group points" in display.columns:
        metric_columns[1].metric(
            "Positive group points shown",
            f"{display['Positive group points'].sum():,.2f}",
        )
    else:
        metric_columns[1].metric("Positive points shown", "—")

    if "Negative points" in display.columns:
        metric_columns[2].metric(
            "Negative points shown",
            f"{display['Negative points'].sum():,.2f}",
        )
    elif "Negative group points" in display.columns:
        metric_columns[2].metric(
            "Negative group points shown",
            f"{display['Negative group points'].sum():,.2f}",
        )
    else:
        metric_columns[2].metric("Negative points shown", "—")

    metric_columns[3].metric(
        "Model",
        (
            "Enhanced"
            if model_key == "enhanced_balanced_production"
            else "Original v4.1"
        ),
    )

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_config={
            "Positive points":
                st.column_config.NumberColumn(format="%.2f"),
            "Negative points":
                st.column_config.NumberColumn(format="%.2f"),
            "Net development points":
                st.column_config.NumberColumn(format="%.2f"),
            "Net event points":
                st.column_config.NumberColumn(format="%.2f"),
            "Net athlete points":
                st.column_config.NumberColumn(format="%.2f"),
            "Positive group points":
                st.column_config.NumberColumn(format="%.2f"),
            "Negative group points":
                st.column_config.NumberColumn(format="%.2f"),
            "Net group points":
                st.column_config.NumberColumn(format="%.2f"),
            "Net group-balanced points":
                st.column_config.NumberColumn(format="%.2f"),
            "Positive share of available points":
                st.column_config.NumberColumn(format="%.3f%%"),
            "Net share of available points":
                st.column_config.NumberColumn(format="%.3f%%"),
            "Positive event share":
                st.column_config.NumberColumn(format="%.3f%%"),
            "Net event share":
                st.column_config.NumberColumn(format="%.3f%%"),
            "Positive group share":
                st.column_config.NumberColumn(format="%.3f%%"),
            "Net group share":
                st.column_config.NumberColumn(format="%.3f%%"),
            "Positive share of available group points":
                st.column_config.NumberColumn(format="%.3f%%"),
            "Net share of available group points":
                st.column_config.NumberColumn(format="%.3f%%"),
        },
    )

    st.download_button(
        "Download filtered points CSV",
        display.to_csv(index=False).encode("utf-8"),
        file_name="event_balanced_points.csv",
        mime="text/csv",
        key=(
            f"download_points_{cohort_key}_{view}_"
            f"{selected_period}"
        ),
    )




def all_time_average_frame(view_name: str) -> pd.DataFrame:
    filename = ALL_TIME_AVERAGE_FILES[view_name]
    frame = load_csv_file(ALL_TIME_AVERAGE_DATA_DIR / filename).copy()

    rank_columns = {
        "Overall": (
            "official_overall_rank",
            "all_school_posterior_rank",
        ),
        "Men": (
            "official_gender_rank",
            "all_school_gender_rank",
        ),
        "Women": (
            "official_gender_rank",
            "all_school_gender_rank",
        ),
        "Event Family": (
            "official_event_family_rank",
            "all_school_family_rank",
        ),
    }
    sample_columns = {
        "Overall": "athlete_school_unit_count",
        "Men": "athlete_school_unit_count",
        "Women": "athlete_school_unit_count",
        "Event Family": "athlete_family_unit_count",
    }

    official_rank_column, diagnostic_rank_column = rank_columns[view_name]
    sample_column = sample_columns[view_name]

    frame["official_rank"] = pd.to_numeric(
        frame.get(official_rank_column),
        errors="coerce",
    )
    frame["diagnostic_rank"] = pd.to_numeric(
        frame.get(diagnostic_rank_column),
        errors="coerce",
    )
    frame["athlete_unit_count"] = pd.to_numeric(
        frame.get(sample_column),
        errors="coerce",
    ).fillna(0)

    if "official_rank_eligible" in frame.columns:
        frame["official_rank_eligible"] = (
            frame["official_rank_eligible"]
            .astype(str)
            .str.lower()
            .map({"true": True, "false": False})
            .fillna(False)
        )
    else:
        frame["official_rank_eligible"] = (
            frame["official_rank"].notna()
        )

    numeric_columns = (
        "posterior_school_score",
        "posterior_ci95_lower",
        "posterior_ci95_upper",
        "raw_school_score",
        "posterior_standard_error",
        "shrinkage_weight",
        "above_expected_athlete_share",
    )
    for column in numeric_columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(
                frame[column],
                errors="coerce",
            )

    return frame


def all_time_average_controls(
    frame: pd.DataFrame,
    view_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    frame = frame.copy()

    if view_name == "Event Family":
        left, right = st.columns(2)

        genders = sorted(
            frame["canonical_gender_code"].dropna().unique()
        )
        with left:
            gender = st.selectbox(
                "Gender",
                genders,
                format_func=lambda value: {
                    "m": "Men",
                    "f": "Women",
                }.get(str(value), str(value)),
                key="all_time_average_event_gender",
            )
        frame = frame[
            frame["canonical_gender_code"] == gender
        ].copy()

        families = sorted(frame["event_family"].dropna().unique())
        with right:
            event_family = st.selectbox(
                "Event family",
                families,
                key="all_time_average_event_family",
            )
        frame = frame[
            frame["event_family"] == event_family
        ].copy()

    partition_frame = frame.copy()

    st.markdown("#### Refine results")
    search_col, sample_col, official_col, sort_col = st.columns(
        [2.2, 1.2, 1.2, 1.5]
    )

    with search_col:
        school_search = st.text_input(
            "Search school",
            placeholder="Type Air Force, LSU, Kentucky…",
            key=f"all_time_school_search_{view_name}",
        )

    maximum_sample = int(
        max(frame["athlete_unit_count"].max(), 0)
    )
    with sample_col:
        minimum_sample = st.number_input(
            "Minimum athlete units",
            min_value=0,
            max_value=maximum_sample,
            value=0,
            step=1,
            key=f"all_time_minimum_sample_{view_name}",
        )

    with official_col:
        official_only = st.checkbox(
            "Published ranks only",
            value=True,
            key=f"all_time_official_only_{view_name}",
        )

    sort_options = {
        "Official rank": "official_rank",
        "Posterior score": "posterior_school_score",
        "Raw school score": "raw_school_score",
        "Sample size": "athlete_unit_count",
    }
    available_sort_options = {
        label: column
        for label, column in sort_options.items()
        if column in frame.columns
    }

    with sort_col:
        sort_label = st.selectbox(
            "Sort by",
            list(available_sort_options),
            key=f"all_time_sort_{view_name}",
        )

    evidence_values = sorted(
        frame.get(
            "evidence_category",
            pd.Series(dtype=str),
        )
        .dropna()
        .unique()
    )
    if evidence_values:
        selected_evidence = st.multiselect(
            "Evidence categories",
            evidence_values,
            default=evidence_values,
            key=f"all_time_evidence_{view_name}",
        )
        frame = frame[
            frame["evidence_category"].isin(selected_evidence)
        ]

    if school_search:
        frame = frame[
            frame["school_name"]
            .astype(str)
            .str.contains(
                school_search,
                case=False,
                regex=False,
                na=False,
            )
        ]

    frame = frame[
        frame["athlete_unit_count"] >= minimum_sample
    ]

    if official_only:
        frame = frame[frame["official_rank_eligible"]]

    sort_column = available_sort_options[sort_label]
    ascending = sort_column == "official_rank"
    frame = frame.sort_values(
        sort_column,
        ascending=ascending,
        na_position="last",
    )

    return frame, partition_frame, official_only


def all_time_average_table(
    frame: pd.DataFrame,
    partition_frame: pd.DataFrame,
    official_only: bool,
    view_name: str,
) -> None:
    if frame.empty:
        published_count = int(
            partition_frame["official_rank_eligible"].sum()
        )
        if official_only and published_count == 0:
            st.info(
                "No officially published rankings are available for this "
                "selection."
            )
        else:
            st.info("No rows match the selected filters.")
        return

    published_rows = int(frame["official_rank_eligible"].sum())
    school_count = int(frame["school_name"].nunique())
    athlete_units = int(frame["athlete_unit_count"].sum())
    top_score = frame["posterior_school_score"].max()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Schools shown", f"{school_count:,}")
    c2.metric("Published rows shown", f"{published_rows:,}")
    c3.metric("Athlete-school units shown", f"{athlete_units:,}")
    c4.metric("Highest posterior score", safe_number(top_score, 4))

    display = frame.copy()
    display["Rank"] = display["official_rank"].apply(
        lambda value: (
            "—" if pd.isna(value) else str(int(float(value)))
        )
    )
    display["School"] = display["school_name"]
    display["Athlete-school units"] = display["athlete_unit_count"]
    display["Posterior score"] = display["posterior_school_score"]
    display["CI lower"] = display["posterior_ci95_lower"]
    display["CI upper"] = display["posterior_ci95_upper"]
    display["Evidence"] = display.get(
        "evidence_category",
        pd.Series("", index=display.index),
    )

    columns = [
        "Rank",
        "School",
        "Athlete-school units",
        "Posterior score",
        "CI lower",
        "CI upper",
    ]

    if "raw_school_score" in display.columns:
        display["Raw school score"] = display["raw_school_score"]
        columns.append("Raw school score")

    if "shrinkage_weight" in display.columns:
        display["Shrinkage weight"] = display["shrinkage_weight"]
        columns.append("Shrinkage weight")

    if "above_expected_athlete_share" in display.columns:
        display["Above-expected share"] = (
            display["above_expected_athlete_share"]
        )
        columns.append("Above-expected share")

    if view_name == "Event Family":
        display["Gender"] = display["gender_label"]
        display["Event family"] = display["event_family"]
        columns[2:2] = ["Gender", "Event family"]

    columns.append("Evidence")
    display = display[columns]

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_config={
            "Rank": st.column_config.TextColumn(
                help=(
                    "Official frozen Milestone 5 rank. An em dash marks an "
                    "insufficient-data row."
                ),
            ),
            "Athlete-school units":
                st.column_config.NumberColumn(format="%d"),
            "Posterior score":
                st.column_config.NumberColumn(format="%.4f"),
            "CI lower":
                st.column_config.NumberColumn(format="%.3f"),
            "CI upper":
                st.column_config.NumberColumn(format="%.3f"),
            "Raw school score":
                st.column_config.NumberColumn(format="%.4f"),
            "Shrinkage weight":
                st.column_config.NumberColumn(format="%.3f"),
            "Above-expected share":
                st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

    st.download_button(
        "Download filtered all-time ranking",
        display.to_csv(index=False).encode("utf-8"),
        file_name=(
            "all_time_average_athlete_development_"
            f"{view_name.lower().replace(' ', '_')}.csv"
        ),
        mime="text/csv",
        key=f"download_all_time_average_{view_name}",
    )


def all_time_average_page() -> None:
    st.caption(
        "Frozen Milestone 5 school-average rankings across the complete "
        "development dataset. Each athlete contributes one total vote per "
        "school, independent of endpoint season."
    )

    view_name = st.selectbox(
        "All-time ranking view",
        list(ALL_TIME_AVERAGE_FILES),
        key="all_time_average_view",
    )

    frame = all_time_average_frame(view_name)
    filtered, partition_frame, official_only = (
        all_time_average_controls(frame, view_name)
    )
    all_time_average_table(
        filtered,
        partition_frame,
        official_only,
        view_name,
    )


def rankings_page() -> None:
    st.subheader("Average Athlete Development")
    st.caption(
        "Use the frozen all-time Milestone 5 ranking or inspect the "
        "season-specific Milestone 6 school-average rankings."
    )

    time_view = st.radio(
        "Time view",
        [
            "All Time — Frozen Milestone 5",
            "Single Season — Milestone 6",
        ],
        index=0,
        horizontal=True,
        key="average_development_time_view",
    )

    if time_view == "All Time — Frozen Milestone 5":
        st.info(
            "This is the original school-average ranking led by Air Force, "
            "LSU, and Kentucky. It answers how well the typical athlete "
            "developed across the full dataset."
        )
        all_time_average_page()
        return

    st.caption(
        "Seasonal view: filter by development cohort, endpoint season, "
        "gender, event or event group, school, sample size, and evidence "
        "category."
    )

    cohort_label, config = select_cohort(
        key="rankings_cohort",
    )

    view_name = st.selectbox(
        "Seasonal ranking view",
        list(config["files"]),
        key=f"ranking_view_{cohort_label}",
    )

    frame = cohort_frame(
        cohort_label,
        config["files"][view_name],
    )
    filtered, partition_frame, official_only = ranking_controls(
        frame,
        f"{cohort_label}_{view_name}",
    )
    ranking_table(
        filtered,
        partition_frame,
        official_only,
    )



def school_profile_page() -> None:
    st.subheader("School Profile")

    cohort_label, config = select_cohort(
        key="school_profile_cohort",
    )

    overall = prepare_relative_score(
        cohort_frame(
            cohort_label,
            config["overall_file"],
        )
    )
    schools = sorted(overall["school_name"].dropna().unique())

    school_query = st.text_input(
        "Find a school",
        placeholder="Start typing a school name",
        key=f"school_query_{cohort_label}",
    )
    matching = [
        school
        for school in schools
        if school_query.lower() in school.lower()
    ] if school_query else schools

    if not matching:
        st.info("No school matched that search.")
        return

    selected_school = st.selectbox(
        "School",
        matching,
        key=f"school_select_{cohort_label}",
    )

    school_overall = overall[
        overall["school_name"] == selected_school
    ].copy()
    school_overall["Season"] = (
        school_overall["season_year"].astype(int).astype(str)
        + " "
        + school_overall["season_type"].str.title()
    )
    school_overall = school_overall.sort_values(
        ["season_year", "season_type"]
    )

    c1, c2, c3 = st.columns(3)
    official_rows = school_overall[
        official_mask(school_overall)
    ]
    c1.metric(
        "Published seasonal ranks",
        len(official_rows),
    )
    c2.metric(
        "Best published rank",
        (
            int(official_rows["official_rank"].min())
            if not official_rows.empty
            else "—"
        ),
    )
    c3.metric(
        "Latest relative score",
        (
            safe_number(
                school_overall[
                    "season_centered_posterior_score"
                ].iloc[-1],
                4,
            )
            if not school_overall.empty
            else "—"
        ),
    )

    st.markdown("#### Development trend")
    trend = school_overall[
        [
            "Season",
            "season_centered_posterior_score",
        ]
    ].dropna()
    if not trend.empty:
        st.line_chart(
            trend.set_index("Season"),
            y="season_centered_posterior_score",
            y_label="Season-relative development score",
        )

    st.markdown("#### Overall seasonal history")
    history_columns = [
        "Season",
        "official_rank",
        "season_centered_posterior_score",
        "posterior_school_score",
        "posterior_ci95_lower",
        "posterior_ci95_upper",
        "athlete_unit_count",
    ]

    if {
        "mean_baseline_level",
        "mean_endpoint_level",
    }.issubset(school_overall.columns):
        history_columns.extend(
            ["mean_baseline_level", "mean_endpoint_level"]
        )

    history_columns.extend(
        ["evidence_category", "variance_status"]
    )

    history = school_overall[history_columns].rename(
        columns={
            "official_rank": "Rank",
            "season_centered_posterior_score":
                "Season-relative score",
            "posterior_school_score": "Posterior score",
            "posterior_ci95_lower": "CI lower",
            "posterior_ci95_upper": "CI upper",
            "athlete_unit_count": "Athletes",
            "mean_baseline_level": "Baseline level",
            "mean_endpoint_level": "Endpoint level",
            "evidence_category": "Evidence",
            "variance_status": "Variance status",
        }
    )
    st.dataframe(
        history,
        width="stretch",
        hide_index=True,
    )

    st.markdown("#### Season detail")
    seasons = list(reversed(school_overall["Season"].tolist()))
    if not seasons:
        st.info("No overall seasonal rows are available.")
        return

    selected_season = st.selectbox(
        "Choose season",
        seasons,
        key=f"school_season_{cohort_label}",
    )
    season_year, season_type = selected_season.split(" ", 1)
    season_type = season_type.lower()

    detail_frames = []
    for view_name, filename in config["files"].items():
        if view_name in {"Overall", "Overall by Gender"}:
            continue

        frame = prepare_relative_score(
            cohort_frame(cohort_label, filename)
        )
        frame = frame[
            (frame["school_name"] == selected_school)
            & (frame["season_year"].astype(int) == int(season_year))
            & (frame["season_type"] == season_type)
        ].copy()

        if frame.empty:
            continue

        frame["View"] = view_name
        detail_frames.append(frame)

    if detail_frames:
        detail = pd.concat(detail_frames, ignore_index=True)
        detail = detail.sort_values(
            "season_centered_posterior_score",
            ascending=False,
        )

        detail_columns = [
            "View",
            "gender_scope",
            "ranking_label",
            "official_rank",
            "season_centered_posterior_score",
            "athlete_unit_count",
        ]

        if {
            "mean_baseline_level",
            "mean_endpoint_level",
        }.issubset(detail.columns):
            detail_columns.extend(
                ["mean_baseline_level", "mean_endpoint_level"]
            )

        detail_columns.append("evidence_category")

        detail_display = detail[detail_columns].rename(
            columns={
                "gender_scope": "Gender",
                "ranking_label": "Event or group",
                "official_rank": "Rank",
                "season_centered_posterior_score":
                    "Season-relative score",
                "athlete_unit_count": "Athletes",
                "mean_baseline_level": "Baseline level",
                "mean_endpoint_level": "Endpoint level",
                "evidence_category": "Evidence",
            }
        )
        st.dataframe(
            detail_display,
            width="stretch",
            hide_index=True,
        )
    else:
        st.info(
            "No event or event-group rows are available for this school, "
            "season, and cohort."
        )


def season_summary_page() -> None:
    st.subheader("Season and Coverage Summary")

    cohort_label, config = select_cohort(
        key="coverage_cohort",
    )

    coverage = cohort_frame(
        cohort_label,
        config["coverage_file"],
    )
    coverage = coverage.sort_values(
        ["season_year", "season_type"],
        ascending=[False, True],
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Endpoint seasons", len(coverage))
    c2.metric(
        "Earliest year",
        int(coverage["season_year"].min()),
    )
    c3.metric(
        "Latest year",
        int(coverage["season_year"].max()),
    )
    c4.metric(
        "Total trajectories",
        f"{int(coverage['trajectory_count'].sum()):,}",
    )

    st.dataframe(
        coverage,
        width="stretch",
        hide_index=True,
    )

    st.markdown("#### Ranking partition coverage")
    partitions = cohort_frame(
        cohort_label,
        config["partition_file"],
    )

    scope = st.selectbox(
        "Scope",
        sorted(partitions["ranking_scope"].unique()),
        key=f"coverage_scope_{cohort_label}",
    )
    filtered = partitions[
        partitions["ranking_scope"] == scope
    ].copy()

    only_publishable = st.checkbox(
        "Show publishable partitions only",
        value=True,
        key=f"coverage_publishable_{cohort_label}",
    )
    if only_publishable:
        filtered = filtered[
            filtered["officially_ranked_school_count"] > 0
        ]

    st.dataframe(
        filtered.sort_values(
            ["season_year", "season_type", "ranking_label"],
            ascending=[False, True, True],
        ),
        width="stretch",
        hide_index=True,
    )



def model_diagnostics_page() -> None:
    st.subheader("Model Fairness Diagnostics")
    st.caption(
        "Compare the enhanced primary model with the exact Phase 6D v4.1 "
        "allocation and inspect concentration, roster-size dependence, "
        "elite reward patterns, and negative-pool behavior."
    )

    decision = final_decision_frame()
    if not decision.empty:
        row = decision.iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Official model",
            str(row["selected_model_label"]),
        )
        c2.metric(
            "Original v4.1 rank correlation",
            f"{float(row['rank_correlation_to_original_v4_1']):.3f}",
        )
        c3.metric(
            "Matched elite advantage",
            f"{float(row['elite_advantage_share']):.1%}",
        )
        c4.metric(
            "P95 largest athlete share",
            f"{float(row['p95_largest_athlete_share']):.1%}",
        )

        st.info(
            "No additional elite multiplier is applied. Higher-baseline "
            "difficulty remains inside the nonlinear performance scale and "
            "cross-fitted expected-improvement model."
        )

    registry = model_registry_frame()
    st.dataframe(
        registry[
            [
                "model_label",
                "is_primary",
                "uses_support_reliability",
                "caps_negative_event_pool",
                "model_description",
            ]
        ].rename(
            columns={
                "model_label": "Model",
                "is_primary": "Primary",
                "uses_support_reliability":
                    "Support reliability",
                "caps_negative_event_pool":
                    "Negative pool cap",
                "model_description": "Description",
            }
        ),
        width="stretch",
        hide_index=True,
    )

    tab_compare, tab_negative, tab_concentration, tab_roster, tab_elite = (
        st.tabs(
            [
                "Rank Comparison",
                "Negative Pools",
                "Concentration",
                "Roster Size",
                "Elite Reward",
            ]
        )
    )

    with tab_compare:
        frame = points_frame("rank_comparison")
        cohort_labels = sorted(
            frame["cohort_label"].dropna().unique()
        )
        cohort = st.selectbox(
            "Comparison cohort",
            cohort_labels,
            key="diag_compare_cohort",
        )
        filtered = frame[frame["cohort_label"] == cohort].copy()

        time_scopes = sorted(filtered["time_scope"].dropna().unique())
        time_scope = st.selectbox(
            "Comparison time scope",
            time_scopes,
            key="diag_compare_time",
        )
        filtered = filtered[
            filtered["time_scope"] == time_scope
        ].copy()

        if time_scope == "single_season":
            years = sorted(
                filtered["season_year"].dropna().astype(int).unique(),
                reverse=True,
            )
            year = st.selectbox(
                "Comparison year",
                years,
                key="diag_compare_year",
            )
            filtered = filtered[
                filtered["season_year"].astype("Int64") == year
            ].copy()

        filtered = filtered.sort_values(
            ["season_year", "season_type"],
            ascending=[False, True],
        )
        st.dataframe(
            filtered.rename(
                columns={
                    "rank_correlation": "Rank correlation",
                    "score_correlation": "Score correlation",
                    "mean_absolute_rank_shift":
                        "Mean absolute rank shift",
                    "median_absolute_rank_shift":
                        "Median absolute rank shift",
                    "maximum_absolute_rank_shift":
                        "Maximum absolute rank shift",
                    "top_10_overlap_share": "Top-10 overlap",
                    "top_25_overlap_share": "Top-25 overlap",
                    "top_50_overlap_share": "Top-50 overlap",
                }
            ),
            width="stretch",
            hide_index=True,
        )

    with tab_negative:
        frame = points_frame("event_budget_audit")
        models = sorted(frame["model_label"].dropna().unique())
        model = st.selectbox(
            "Negative-pool model",
            models,
            key="diag_negative_model",
        )
        filtered = frame[frame["model_label"] == model].copy()

        capped_series = (
            filtered["negative_pool_was_capped"]
            .astype(str)
            .str.lower()
            .map({"true": True, "false": False})
            .fillna(False)
        )

        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Event partitions",
            f"{len(filtered):,}",
        )
        c2.metric(
            "Capped partitions",
            f"{int(capped_series.sum()):,}",
        )
        c3.metric(
            "Largest negative/positive ratio",
            f"{filtered['negative_pool_to_positive_budget_ratio'].max():.3f}",
        )

        display = filtered.sort_values(
            "negative_pool_to_positive_budget_ratio",
            ascending=False,
        ).head(100)
        st.dataframe(
            display[
                existing_columns(
                    display,
                    [
                        "cohort_label",
                        "time_scope",
                        "season_year",
                        "season_type",
                        "gender_scope",
                        "canonical_event_name",
                        "athlete_unit_count",
                        "distributed_positive_event_points",
                        "distributed_negative_event_points",
                        "distributed_net_event_points",
                        "raw_negative_to_positive_ratio",
                        "negative_pool_was_capped",
                    ],
                )
            ],
            width="stretch",
            hide_index=True,
        )

    with tab_concentration:
        frame = points_frame("concentration")
        models = sorted(frame["model_label"].dropna().unique())
        model = st.selectbox(
            "Concentration model",
            models,
            key="diag_concentration_model",
        )
        filtered = frame[frame["model_label"] == model].copy()

        concentration_flags = sorted(
            filtered["athlete_concentration_flag"]
            .dropna()
            .unique()
        )
        selected_flags = st.multiselect(
            "Athlete concentration flags",
            concentration_flags,
            default=concentration_flags,
            key="diag_concentration_flags",
        )
        filtered = filtered[
            filtered["athlete_concentration_flag"].isin(
                selected_flags
            )
        ].copy()

        filtered = filtered.sort_values(
            "largest_athlete_positive_share",
            ascending=False,
        )
        st.dataframe(
            filtered[
                existing_columns(
                    filtered,
                    [
                        "cohort_label",
                        "time_scope",
                        "season_year",
                        "season_type",
                        "gender_scope",
                        "canonical_event_name",
                        "positive_athlete_count",
                        "largest_athlete_positive_share",
                        "top_five_athlete_positive_share",
                        "effective_positive_athlete_count",
                        "positive_school_count",
                        "largest_school_positive_share",
                        "effective_positive_school_count",
                        "athlete_concentration_flag",
                        "school_concentration_flag",
                    ],
                )
            ].head(200),
            width="stretch",
            hide_index=True,
        )

    with tab_roster:
        frame = points_frame("roster_dependence")
        models = sorted(frame["model_label"].dropna().unique())
        model = st.selectbox(
            "Roster audit model",
            models,
            key="diag_roster_model",
        )
        filtered = frame[frame["model_label"] == model].copy()

        st.dataframe(
            filtered[
                existing_columns(
                    filtered,
                    [
                        "cohort_label",
                        "time_scope",
                        "season_year",
                        "season_type",
                        "ranked_school_count",
                        "net_points_roster_size_correlation",
                        "positive_points_roster_size_correlation",
                        "net_points_positive_athlete_correlation",
                        "net_points_efficiency_correlation",
                        "mean_athlete_event_unit_count",
                        "median_athlete_event_unit_count",
                    ],
                )
            ].sort_values(
                ["time_scope", "season_year", "season_type"],
                ascending=[True, False, True],
            ),
            width="stretch",
            hide_index=True,
        )

    with tab_elite:
        frame = points_frame("elite_reward")
        models = sorted(frame["model_label"].dropna().unique())
        model = st.selectbox(
            "Elite-reward model",
            models,
            key="diag_elite_model",
        )
        filtered = frame[frame["model_label"] == model].copy()
        filtered = filtered.sort_values("baseline_band_order")

        st.dataframe(
            filtered[
                existing_columns(
                    filtered,
                    [
                        "baseline_band",
                        "athlete_unit_count",
                        "mean_baseline_level",
                        "mean_observed_improvement",
                        "mean_original_development_signal",
                        "mean_model_development_signal",
                        "mean_original_signal_per_observed_unit",
                        "mean_model_signal_per_observed_unit",
                        "mean_positive_points_per_positive_athlete",
                    ],
                )
            ],
            width="stretch",
            hide_index=True,
        )

        summary = points_frame("elite_reward_summary")
        summary = summary[summary["model_label"] == model].copy()
        if not summary.empty:
            st.markdown("#### Monotonicity summary")
            st.dataframe(
                summary,
                width="stretch",
                hide_index=True,
            )

        st.info(
            "This audit is descriptive. Elite difficulty is already part "
            "of the original nonlinear performance scale and the "
            "cross-fitted expected-improvement model. No extra elite bonus "
            "is applied."
        )



def methodology_page() -> None:
    st.subheader("How to Read the Rankings")

    st.markdown(
        """
### Official primary ranking: Enhanced Balanced Production

Milestone 6 freezes this as the official primary model after sensitivity,
rank-stability, concentration, roster-size, negative-pool, and matched
elite-development validation.

Every publishable NCAA championship event distributes exactly **100,000
positive points** to individual athlete-school-event contributions.

The enhanced primary model applies a moderate empirical support adjustment:

```text
reliability = sqrt(n / (n + empirical median support))
```

It also bounds the magnitude of each event's negative pool at 100,000 points.
Until the negative signal reaches the positive signal, the penalty is exactly
the same as the original linear formula. The cap only prevents one event's
regression tail from exceeding another event's entire positive opportunity.

### Preserved alternatives

**Original Balanced Production v4.1** is available from the Scoring model
selector and reproduces the validated Phase 6D v4.1 points exactly.

**Average Athlete Development** remains a separate page with two time
views. **All Time** restores the frozen Milestone 5 school-average ranking;
**Single Season** contains the Phase 6A/6B endpoint-season rankings. These
answer how well the typical athlete developed, while the balanced-production
models answer how much total development the program produced.

Every publishable NCAA championship event distributes exactly **100,000
positive points** to individual athlete-school-event contributions.

```text
athlete development signal
= observed improvement
− cross-fitted expected improvement

positive conversion
= 100,000
÷ sum of positive athlete development signals

athlete points
= athlete development signal × positive conversion
```

Positive athlete points sum to exactly 100,000 in every event. Athletes with
negative regression receive negative points using the same conversion.
Those negative points are reported separately and do not consume the
100,000 positive pool.

One athlete is counted once per school and event in a ranking partition.
Multiple underlying trajectories are averaged before points are allocated.
School event points are direct sums of athlete contributions. There is no
top-eight cutoff and no school-rank point simulation.

Overall rankings sum equal event pools. Coaching-group rankings average the
equal event pools in each group and therefore distribute exactly 100,000
positive points per group.

Steeplechase belongs to **Distance**. It is not a standalone group. The
500m, 600m, and 1000m remain available in legacy analysis but do not affect
the primary championship-event ranking.

The explorer derives cohort, time, season, gender, event, and group choices
from the rows that are actually published. Rebuilding Phase 6D invalidates
the file cache automatically; the **Reload generated data** button is also
available for an immediate manual refresh.

### Development cohorts

The explorer contains three related but distinct views:

| Cohort | Definition | Purpose |
|---|---|---|
| Broad | All eligible athletes | Primary measure of whole-program development |
| Frontier | Baseline level 70+ | Development near the performance frontier |
| Elite | Baseline level 80+ | Development among athletes beginning at an elite level |
| National Elite Finishers | Endpoint level 90+ | Development into nationally elite performance |
| Championship-Caliber Finishers | Endpoint level 95+ | Development among the most extreme finishers |

The cohort views do not add bonus points to the broad score. They restrict
the analyzed trajectories and rerun the same uncertainty-adjusted school
ranking framework.

The 95+ cohort is especially sparse. It is useful for exploratory comparison
with championship-level programs, but it is not itself a projected NCAA team
points ranking.

### Primary question

The explorer answers:

> Which schools developed the selected athlete cohort more than expected
> by the endpoint season?

It does not estimate championship points or current roster strength.

### Score

```text
athlete value added
= observed normalized improvement
− expected normalized improvement
```

The school score is an empirical-Bayes average of equal-weight
athlete-school contributions.

### Season-relative score

```text
season-relative score
= posterior school score
− national mean for the same season, scope, and cohort
```

This is the preferred score for comparing a school across different
seasons.

### Published ranks

A school receives a published rank only when:

- its sample reaches the cohort- and scope-specific minimum;
- at least five schools qualify in the partition;
- detectable between-school variance remains after uncertainty
  adjustment.

When no separation is detectable, the explorer reports a tie/no-separation
condition instead of presenting false co-leaders.

### Development versus championship strength

Even the Elite view measures improvement relative to expectation. A future
championship-strength product will instead emphasize current national-caliber
marks, qualifying probability, relays, and likely NCAA scoring.
        """
    )


def main() -> None:
    configure_page()
    require_data()

    st.title(APP_TITLE)
    st.caption(
        "Official Milestone 6 NCAA Division I development rankings, "
        "preserved companion models, and final fairness diagnostics."
    )

    loaded_versions: list[str] = []
    for label, config in COHORTS.items():
        coverage = cohort_frame(
            label,
            config["coverage_file"],
        )
        versions = sorted(
            coverage.get(
                "dataset_version",
                pd.Series(dtype=str),
            )
            .dropna()
            .astype(str)
            .unique()
        )
        loaded_versions.extend(versions)

    points_versions = (
        points_frame("overall_combined")
        .get("dataset_version", pd.Series(dtype=str))
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )
    loaded_versions.extend(points_versions)

    loaded_versions = sorted(set(loaded_versions))
    if loaded_versions:
        st.caption(
            "Loaded datasets: " + ", ".join(loaded_versions)
        )

    with st.sidebar:
        st.header("Explore")
        page = st.radio(
            "Page",
            [
                "Event-Balanced Points",
                "Model Diagnostics",
                "Average Development",
                "School Profile",
                "Season Coverage",
                "Methodology",
            ],
        )
        st.divider()
        st.markdown(
            """
**Official Milestone 6 ranking:** Enhanced Balanced Production is
frozen as the primary model. Original v4.1 remains selectable, and Average
Development remains the efficiency-oriented companion page. Steeplechase is
included in Distance.

These remain development rankings, not projected NCAA championship points.
Endpoint 90+ is provisional; Endpoint 95+ is exploratory.
            """
        )

    if page == "Event-Balanced Points":
        event_balanced_points_page()
    elif page == "Model Diagnostics":
        model_diagnostics_page()
    elif page == "Average Development":
        rankings_page()
    elif page == "School Profile":
        school_profile_page()
    elif page == "Season Coverage":
        season_summary_page()
    else:
        methodology_page()


if __name__ == "__main__":
    main()
