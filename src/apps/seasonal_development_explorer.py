#!/usr/bin/env python3
"""
NCAA Division I Seasonal Athlete Development Explorer

Run from the repository root:

    streamlit run src/apps/seasonal_development_explorer.py

The app reads locally generated Milestone 6 Phase 6A CSV outputs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pandas as pd
import streamlit as st


APP_TITLE: Final = "NCAA Division I Athlete Development Explorer"

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = (
    ROOT
    / "data/processed/milestone6/"
      "seasonal_development_rankings_v1/"
      "phase_6a_seasonal_rankings"
)

FILES = {
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

OVERALL_FILE = DATA_DIR / "season_overall_rankings.csv"
COVERAGE_FILE = DATA_DIR / "season_coverage_summary.csv"
PARTITION_FILE = DATA_DIR / "season_partition_summary.csv"


def configure_page() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )


@st.cache_data(show_spinner=False)
def load_csv(path: str) -> pd.DataFrame:
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


def require_data() -> None:
    missing = [
        str(DATA_DIR / filename)
        for filename in FILES.values()
        if not (DATA_DIR / filename).exists()
    ]
    missing.extend(
        str(path)
        for path in (COVERAGE_FILE, PARTITION_FILE)
        if not path.exists()
    )

    if missing:
        st.error(
            "The explorer could not find the Phase 6A publication files."
        )
        st.code("\n".join(missing))
        st.info(
            "Run the seasonal ranking builder from the repository root, "
            "then refresh this page."
        )
        st.stop()


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
            "Official ranks only",
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
            "separation. Uncheck **Official ranks only** to inspect the "
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
            "No school received an official rank in this partition."
            f" {eligible_count} school(s) met the sample threshold."
            f"{threshold_text} Uncheck **Official ranks only** to inspect "
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
    c2.metric("Official rows shown", official_count)
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
        "Evidence",
    ]

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
                    "Official rank. An em dash means the school or "
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
        },
    )

    csv_bytes = display.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download filtered table",
        data=csv_bytes,
        file_name="filtered_seasonal_rankings.csv",
        mime="text/csv",
    )


def rankings_page() -> None:
    st.subheader("Ranking Explorer")
    st.caption(
        "Filter by endpoint season, gender, event or event group, school, "
        "sample size, and evidence category."
    )

    view_name = st.selectbox(
        "Ranking view",
        list(FILES),
    )

    frame = load_csv(str(DATA_DIR / FILES[view_name]))
    filtered, partition_frame, official_only = ranking_controls(
        frame,
        view_name,
    )
    ranking_table(
        filtered,
        partition_frame,
        official_only,
    )


def school_profile_page() -> None:
    st.subheader("School Profile")

    overall = prepare_relative_score(
        load_csv(str(OVERALL_FILE))
    )
    schools = sorted(overall["school_name"].dropna().unique())

    school_query = st.text_input(
        "Find a school",
        placeholder="Start typing a school name",
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
        "Official seasonal ranks",
        len(official_rows),
    )
    c2.metric(
        "Best official rank",
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
    history = school_overall[
        [
            "Season",
            "official_rank",
            "season_centered_posterior_score",
            "posterior_school_score",
            "posterior_ci95_lower",
            "posterior_ci95_upper",
            "athlete_unit_count",
            "evidence_category",
            "variance_status",
        ]
    ].rename(
        columns={
            "official_rank": "Rank",
            "season_centered_posterior_score":
                "Season-relative score",
            "posterior_school_score": "Posterior score",
            "posterior_ci95_lower": "CI lower",
            "posterior_ci95_upper": "CI upper",
            "athlete_unit_count": "Athletes",
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
    )
    season_year, season_type = selected_season.split(" ", 1)
    season_type = season_type.lower()

    detail_frames = []
    for view_name, filename in FILES.items():
        if view_name in {"Overall", "Overall by Gender"}:
            continue
        frame = prepare_relative_score(
            load_csv(str(DATA_DIR / filename))
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
        detail_display = detail[
            [
                "View",
                "gender_scope",
                "ranking_label",
                "official_rank",
                "season_centered_posterior_score",
                "athlete_unit_count",
                "evidence_category",
            ]
        ].rename(
            columns={
                "gender_scope": "Gender",
                "ranking_label": "Event or group",
                "official_rank": "Rank",
                "season_centered_posterior_score":
                    "Season-relative score",
                "athlete_unit_count": "Athletes",
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
            "No event or event-group rows are available for this school "
            "and season."
        )


def season_summary_page() -> None:
    st.subheader("Season and Coverage Summary")

    coverage = load_csv(str(COVERAGE_FILE))
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
    partitions = load_csv(str(PARTITION_FILE))

    scope = st.selectbox(
        "Scope",
        sorted(partitions["ranking_scope"].unique()),
    )
    filtered = partitions[
        partitions["ranking_scope"] == scope
    ].copy()

    only_publishable = st.checkbox(
        "Show publishable partitions only",
        value=True,
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


def methodology_page() -> None:
    st.subheader("How to Read the Rankings")

    st.markdown(
        """
### Primary question

The explorer answers:

> Which schools developed athletes more than expected by the endpoint
> season?

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
− national mean for the same season and scope
```

This is the preferred score for comparing a school across different
seasons.

### Official ranks

A school receives an official rank only when:

- its sample reaches the scope-specific minimum;
- at least five schools qualify in the partition;
- detectable between-school variance remains after uncertainty
  adjustment.

When no separation is detectable, the explorer reports a tie/no-separation
condition instead of presenting dozens of false co-leaders.

### Development versus championship strength

The primary development ranking gives every athlete-school unit one total
vote. A future championship-strength product will instead emphasize current
national-caliber marks, qualifying probability, relays, and likely NCAA
scoring.
        """
    )


def main() -> None:
    configure_page()
    require_data()

    st.title(APP_TITLE)
    st.caption(
        "Searchable season-by-season NCAA Division I athlete-development "
        "rankings with uncertainty and sample-size controls."
    )

    coverage = load_csv(str(COVERAGE_FILE))
    dataset_versions = sorted(
        coverage.get(
            "dataset_version",
            pd.Series(dtype=str),
        )
        .dropna()
        .astype(str)
        .unique()
    )
    if dataset_versions:
        st.caption(
            "Loaded dataset: " + ", ".join(dataset_versions)
        )

    with st.sidebar:
        st.header("Explore")
        page = st.radio(
            "Page",
            [
                "Rankings",
                "School Profile",
                "Season Coverage",
                "Methodology",
            ],
        )
        st.divider()
        st.markdown(
            """
**Important:** These are development rankings, not championship-strength
predictions. Use the season-relative score for comparisons across years.
            """
        )

    if page == "Rankings":
        rankings_page()
    elif page == "School Profile":
        school_profile_page()
    elif page == "Season Coverage":
        season_summary_page()
    else:
        methodology_page()


if __name__ == "__main__":
    main()
