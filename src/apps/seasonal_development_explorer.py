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

import math

import altair as alt
import duckdb
import pandas as pd
import streamlit as st


APP_TITLE: Final = "NCAA Division I Athlete Development Explorer"

ROOT = Path(__file__).resolve().parents[2]

EVENT_BALANCED_SPECIALIZED_DB: Final = (
    ROOT
    / "data/processed/milestone7/"
      "seasonal_program_trends_v1/"
      "phase_7e2_event_balanced_specialized_rankings/"
      "event_balanced_specialized_rankings_v2.duckdb"
)

EVENT_BALANCED_SPECIALIZED_ANALYSES: Final = {
    "Development consistency": {
        "table": "development_consistency_rankings",
        "metric": "consistency_index",
        "metric_label": "Consistency index",
        "filter_column": None,
        "filter_value": None,
        "columns": [
            "season_count",
            "mean_rank_strength",
            "rank_strength_sd",
            "stability_percentile",
            "total_net_points",
            "athlete_event_unit_count",
        ],
    },
    "Elite/frontier development": {
        "table": "elite_frontier_development_rankings",
        "metric": "elite_frontier_index",
        "metric_label": "Elite/frontier index",
        "filter_column": None,
        "filter_value": None,
        "columns": [
            "frontier_season_count",
            "elite_season_count",
            "frontier_mean_rank_strength",
            "elite_mean_rank_strength",
            "total_net_points",
            "athlete_event_unit_count",
        ],
    },
    "Developing baseline tier": {
        "table": "baseline_tier_rankings",
        "metric": "net_points",
        "metric_label": "Net Event-Balanced points",
        "filter_column": "baseline_tier_key",
        "filter_value": "developing",
        "columns": [
            "athlete_school_unit_count",
            "athlete_event_unit_count",
            "season_count",
            "mean_baseline_level",
            "mean_endpoint_level",
            "net_points_per_event_unit",
        ],
    },
    "Competitive baseline tier": {
        "table": "baseline_tier_rankings",
        "metric": "net_points",
        "metric_label": "Net Event-Balanced points",
        "filter_column": "baseline_tier_key",
        "filter_value": "competitive",
        "columns": [
            "athlete_school_unit_count",
            "athlete_event_unit_count",
            "season_count",
            "mean_baseline_level",
            "mean_endpoint_level",
            "net_points_per_event_unit",
        ],
    },
    "Advanced baseline tier": {
        "table": "baseline_tier_rankings",
        "metric": "net_points",
        "metric_label": "Net Event-Balanced points",
        "filter_column": "baseline_tier_key",
        "filter_value": "advanced",
        "columns": [
            "athlete_school_unit_count",
            "athlete_event_unit_count",
            "season_count",
            "mean_baseline_level",
            "mean_endpoint_level",
            "net_points_per_event_unit",
        ],
    },
    "Elite baseline tier": {
        "table": "baseline_tier_rankings",
        "metric": "net_points",
        "metric_label": "Net Event-Balanced points",
        "filter_column": "baseline_tier_key",
        "filter_value": "elite",
        "columns": [
            "athlete_school_unit_count",
            "athlete_event_unit_count",
            "season_count",
            "mean_baseline_level",
            "mean_endpoint_level",
            "net_points_per_event_unit",
        ],
    },
    "Breakout rate": {
        "table": "breakout_rate_rankings",
        "metric": "stabilized_breakout_rate",
        "metric_label": "Stabilized breakout rate",
        "filter_column": None,
        "filter_value": None,
        "columns": [
            "athlete_school_unit_count",
            "breakout_count",
            "raw_breakout_rate",
            "net_points",
            "athlete_event_unit_count",
        ],
    },
    "Balanced program": {
        "table": "balanced_program_rankings",
        "metric": "balanced_program_index",
        "metric_label": "Balanced program index",
        "filter_column": None,
        "filter_value": None,
        "columns": [
            "covered_cell_count",
            "men_cell_count",
            "women_cell_count",
            "mean_cell_strength_percentile",
            "cell_strength_sd",
            "gender_strength_gap",
            "total_group_points",
        ],
    },
    "Development efficiency": {
        "table": "development_efficiency_rankings",
        "metric": "net_points_per_event_unit",
        "metric_label": "Net points per athlete-event unit",
        "filter_column": None,
        "filter_value": None,
        "columns": [
            "athlete_event_unit_count",
            "distinct_athlete_count",
            "season_count",
            "positive_points_per_event_unit",
            "net_points",
        ],
    },
    "Ranking robustness": {
        "table": "ranking_robustness_rankings",
        "metric": "robustness_index",
        "metric_label": "Robustness index",
        "filter_column": None,
        "filter_value": None,
        "columns": [
            "compared_partition_count",
            "mean_enhanced_rank_strength",
            "mean_absolute_rank_shift",
            "within_five_rank_share",
            "rank_stability_percentile",
        ],
    },
    "Inbound transfer development": {
        "table": "inbound_transfer_development_rankings",
        "metric": "net_points",
        "metric_label": "Inbound net Event-Balanced points",
        "filter_column": None,
        "filter_value": None,
        "columns": [],
    },
    "National elite finishers — Endpoint 90+": {
        "table": "national_elite_endpoint90_rankings",
        "metric": "national_elite_rank_strength_index",
        "metric_label": "National elite rank-strength index",
        "filter_column": None,
        "filter_value": None,
        "columns": [
            "season_count",
            "calendar_year_count",
            "median_rank_strength",
            "total_net_points",
            "athlete_event_unit_count",
        ],
    },
}

EVENT_BALANCED_PERCENT_COLUMNS: Final = {
    "consistency_index",
    "mean_rank_strength",
    "stability_percentile",
    "elite_frontier_index",
    "frontier_mean_rank_strength",
    "elite_mean_rank_strength",
    "stabilized_breakout_rate",
    "raw_breakout_rate",
    "balanced_program_index",
    "mean_cell_strength_percentile",
    "mean_enhanced_rank_strength",
    "within_five_rank_share",
    "rank_stability_percentile",
    "robustness_index",
    "national_elite_rank_strength_index",
    "median_rank_strength",
}

SUPPLEMENTAL_DATA_DIR: Final = (
    ROOT
    / "data/processed/milestone5/"
      "athlete_development_v1/"
      "phase_5k_supplemental_development_rankings"
)

SUPPLEMENTAL_FILES: Final = {
    "consistency": "development_consistency_rankings.csv",
    "elite": "elite_development_rankings.csv",
    "baseline": "baseline_tier_rankings.csv",
    "breakout": "breakout_rate_rankings.csv",
    "balanced": "balanced_program_rankings.csv",
    "efficiency": "development_efficiency_rankings.csv",
    "robustness": "ranking_robustness_rankings.csv",
    "transfer": "transfer_development_rankings.csv",
}

SUPPLEMENTAL_ANALYSES: Final = {
    "Development consistency": {
        "file_key": "consistency",
        "leader": "Air Force",
        "rank_column": "official_consistency_rank",
        "score_column": "consistency_index",
        "sample_column": "athlete_school_unit_count",
        "score_label": "Consistency index",
        "score_format": "%.2f",
        "filter_type": None,
        "filter_key": None,
        "minimum_sample": "30 athlete-school units",
        "interpretation": (
            "Rewards broad, repeatable development using equal weight on "
            "the school median value-added percentile and the stabilized "
            "above-expected athlete-share percentile."
        ),
        "extra_columns": [
            ("median_athlete_value_added", "Median value added", "%.4f"),
            (
                "stabilized_above_expected_share",
                "Above-expected share",
                "%.2f%%",
            ),
        ],
    },
    "Elite/frontier development": {
        "file_key": "elite",
        "leader": "Air Force",
        "rank_column": "official_rank",
        "score_column": "posterior_school_score",
        "sample_column": "athlete_unit_count",
        "score_label": "Posterior value added",
        "score_format": "%.4f",
        "filter_type": "elite_development",
        "filter_key": "baseline_70_plus",
        "minimum_sample": "20 athlete-segment units",
        "interpretation": (
            "Measures development among athletes whose baseline normalized "
            "performance level was at least 70."
        ),
        "extra_columns": [
            ("posterior_ci95_lower", "CI lower", "%.4f"),
            ("posterior_ci95_upper", "CI upper", "%.4f"),
        ],
    },
    "Developing baseline tier": {
        "file_key": "baseline",
        "leader": "Northern Iowa",
        "rank_column": "official_rank",
        "score_column": "posterior_school_score",
        "sample_column": "athlete_unit_count",
        "score_label": "Posterior value added",
        "score_format": "%.4f",
        "filter_type": "baseline_tier",
        "filter_key": "developing",
        "minimum_sample": "20 athlete-segment units",
        "interpretation": (
            "Ranks development for athletes beginning below normalized "
            "performance level 50."
        ),
        "extra_columns": [
            ("posterior_ci95_lower", "CI lower", "%.4f"),
            ("posterior_ci95_upper", "CI upper", "%.4f"),
        ],
    },
    "Competitive baseline tier": {
        "file_key": "baseline",
        "leader": "LSU",
        "rank_column": "official_rank",
        "score_column": "posterior_school_score",
        "sample_column": "athlete_unit_count",
        "score_label": "Posterior value added",
        "score_format": "%.4f",
        "filter_type": "baseline_tier",
        "filter_key": "competitive",
        "minimum_sample": "20 athlete-segment units",
        "interpretation": (
            "Ranks development for athletes beginning from normalized "
            "performance level 50 to below 65."
        ),
        "extra_columns": [
            ("posterior_ci95_lower", "CI lower", "%.4f"),
            ("posterior_ci95_upper", "CI upper", "%.4f"),
        ],
    },
    "Advanced baseline tier": {
        "file_key": "baseline",
        "leader": "Arkansas",
        "rank_column": "official_rank",
        "score_column": "posterior_school_score",
        "sample_column": "athlete_unit_count",
        "score_label": "Posterior value added",
        "score_format": "%.4f",
        "filter_type": "baseline_tier",
        "filter_key": "advanced",
        "minimum_sample": "20 athlete-segment units",
        "interpretation": (
            "Ranks development for athletes beginning from normalized "
            "performance level 65 to below 80."
        ),
        "extra_columns": [
            ("posterior_ci95_lower", "CI lower", "%.4f"),
            ("posterior_ci95_upper", "CI upper", "%.4f"),
        ],
    },
    "Elite baseline tier": {
        "file_key": "baseline",
        "leader": "Air Force",
        "rank_column": "official_rank",
        "score_column": "posterior_school_score",
        "sample_column": "athlete_unit_count",
        "score_label": "Posterior value added",
        "score_format": "%.4f",
        "filter_type": "baseline_tier",
        "filter_key": "elite",
        "minimum_sample": "20 athlete-segment units",
        "interpretation": (
            "Ranks development for athletes beginning at normalized "
            "performance level 80 or higher."
        ),
        "extra_columns": [
            ("posterior_ci95_lower", "CI lower", "%.4f"),
            ("posterior_ci95_upper", "CI upper", "%.4f"),
        ],
    },
    "Breakout rate": {
        "file_key": "breakout",
        "leader": "Mercer",
        "rank_column": "official_breakout_rank",
        "score_column": "posterior_breakout_rate",
        "sample_column": "athlete_school_unit_count",
        "score_label": "Stabilized breakout rate",
        "score_format": "%.2f%%",
        "filter_type": None,
        "filter_key": None,
        "minimum_sample": "30 athlete-school units",
        "interpretation": (
            "Measures the stabilized probability that an athlete-school "
            "unit produced value added of at least five normalized points."
        ),
        "extra_columns": [],
    },
    "Balanced program": {
        "file_key": "balanced",
        "leader": "LSU",
        "rank_column": "official_balanced_program_rank",
        "score_column": "balanced_program_index",
        "sample_column": "summed_group_athlete_units",
        "score_label": "Balanced program index",
        "score_format": "%.4f",
        "filter_type": None,
        "filter_key": None,
        "minimum_sample": (
            "At least 8 of 12 gender-group cells, including at least "
            "3 men's and 3 women's cells"
        ),
        "interpretation": (
            "Rewards strength across men's and women's Sprints, Middle "
            "Distance, Distance, Hurdles, Jumps, and Throws while penalizing "
            "group dispersion, gender imbalance, and missing coverage."
        ),
        "extra_columns": [],
    },
    "Development efficiency": {
        "file_key": "efficiency",
        "leader": "UC San Diego",
        "rank_column": "official_rank",
        "score_column": "posterior_school_score",
        "sample_column": "athlete_unit_count",
        "score_label": "Posterior annualized value added",
        "score_format": "%.4f",
        "filter_type": "development_efficiency",
        "filter_key": "annualized_value_added",
        "minimum_sample": "30 athlete-school units",
        "interpretation": (
            "Measures how quickly athletes developed by ranking posterior "
            "mean annualized athlete-school value added."
        ),
        "extra_columns": [
            ("posterior_ci95_lower", "CI lower", "%.4f"),
            ("posterior_ci95_upper", "CI upper", "%.4f"),
        ],
    },
    "Ranking robustness": {
        "file_key": "robustness",
        "leader": "Air Force",
        "rank_column": "robustness_rank",
        "score_column": "worst_case_rank_percentile",
        "sample_column": "athlete_school_unit_count",
        "score_label": "Worst-case rank percentile",
        "score_format": "%.2f",
        "filter_type": None,
        "filter_key": None,
        "minimum_sample": "All 7 approved sensitivity variants",
        "interpretation": (
            "Rewards schools whose conclusions remain strong under every "
            "approved sensitivity specification, ordered by worst rank and "
            "then average rank."
        ),
        "extra_columns": [
            ("worst_case_rank", "Worst rank", "%d"),
            ("average_rank", "Average rank", "%.2f"),
            ("rank_range", "Rank range", "%d"),
        ],
    },
    "Inbound transfer development": {
        "file_key": "transfer",
        "leader": "Florida",
        "rank_column": "official_rank",
        "score_column": "posterior_school_score",
        "sample_column": "athlete_unit_count",
        "score_label": "Posterior destination value added",
        "score_format": "%.4f",
        "filter_type": "transfer_development",
        "filter_key": "inbound_transfer",
        "minimum_sample": "15 destination athlete-school units",
        "interpretation": (
            "Measures development after athletes arrive at a school beyond "
            "their first observed institution. This is provisional because "
            "transfer status is inferred from observed school chronology."
        ),
        "extra_columns": [
            ("posterior_ci95_lower", "CI lower", "%.4f"),
            ("posterior_ci95_upper", "CI upper", "%.4f"),
        ],
    },
}

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

MILESTONE7_EXPLORER_VERSION: Final = "milestone7_explorer_v6"
MILESTONE7_EXCLUDED_COHORT_KEYS: Final = frozenset(
    {"championship_endpoint_95_plus"}
)
MILESTONE7_TREND_SEASON_COUNTS: Final = {
    "indoor": {
        "frontier_70_plus": 15,
        "elite_80_plus": 12,
        "national_elite_endpoint_90_plus": 16,
        "broad_all_athletes": 1,
    },
    "outdoor": {
        "broad_all_athletes": 5,
        "frontier_70_plus": 15,
        "elite_80_plus": 7,
        "national_elite_endpoint_90_plus": 14,
    },
}
MILESTONE7_NAVIGATION: Final = {
    "Rankings": "Event-Balanced Points",
    "Trends": "Program Trends",
    "Compare": "Program Comparison",
    "Average Development": "Average Development",
    "Diagnostics": "Model Diagnostics",
    "Coverage": "Season Coverage",
    "Methodology": "Methodology",
}
MILESTONE7_DATA_DIR = (
    ROOT
    / "data/processed/milestone7/"
      "seasonal_program_trends_v1/"
      "phase_7d_final_publication"
)
MILESTONE7_DB = MILESTONE7_DATA_DIR / "seasonal_program_trends_v1.duckdb"

MILESTONE7_TABLES = {
    "program_index": "explorer_program_index",
    "latest_summary": "explorer_latest_program_summary",
    "program_summary": "explorer_program_summary",
    "metric_long": "explorer_program_metric_long",
    "overall_season": "explorer_overall_season_series",
    "overall_yoy": "explorer_overall_yoy_series",
    "indoor_outdoor": "explorer_indoor_outdoor_series",
    "overall_window": "explorer_overall_window_series",
    "group_season": "explorer_group_season_series",
    "group_yoy": "explorer_group_yoy_series",
    "group_window": "explorer_group_window_series",
    "event_season": "explorer_event_season_series",
    "event_yoy": "explorer_event_yoy_series",
    "event_window": "explorer_event_window_series",
}

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
        [
            label
            for label, config in COHORTS.items()
            if config["cohort_key"]
            not in MILESTONE7_EXCLUDED_COHORT_KEYS
        ],
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


def official_rankings_page() -> None:
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
        [
            label
            for label, cohort_value in POINT_COHORT_KEYS.items()
            if cohort_value not in MILESTONE7_EXCLUDED_COHORT_KEYS
        ],
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

    display_for_ui = display.copy()
    percentage_columns = [
        "Positive share of available points",
        "Net share of available points",
        "Positive event share",
        "Net event share",
        "Positive group share",
        "Net group share",
        "Positive share of available group points",
        "Net share of available group points",
    ]
    for percentage_column in percentage_columns:
        if percentage_column in display_for_ui.columns:
            display_for_ui[percentage_column] = (
                pd.to_numeric(
                    display_for_ui[percentage_column],
                    errors="coerce",
                )
                * 100.0
            )

    metric_columns = st.columns(4)
    metric_columns[0].metric("Rows shown", f"{len(display):,}")

    if "Positive points" in display.columns:
        metric_columns[1].metric(
            "Positive points shown",
            compact_number(display["Positive points"].sum()),
        )
    elif "Positive group points" in display.columns:
        metric_columns[1].metric(
            "Positive group points shown",
            compact_number(display["Positive group points"].sum()),
        )
    else:
        metric_columns[1].metric("Positive points shown", "—")

    if "Negative points" in display.columns:
        metric_columns[2].metric(
            "Negative points shown",
            compact_number(display["Negative points"].sum()),
        )
    elif "Negative group points" in display.columns:
        metric_columns[2].metric(
            "Negative group points shown",
            compact_number(display["Negative group points"].sum()),
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
        display_for_ui,
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



def supplemental_frame(file_key: str) -> pd.DataFrame:
    path = SUPPLEMENTAL_DATA_DIR / SUPPLEMENTAL_FILES[file_key]
    if not path.exists():
        return pd.DataFrame()
    return load_csv_file(path)


def supplemental_official_mask(frame: pd.DataFrame) -> pd.Series:
    if "official_rank_eligible" not in frame.columns:
        return pd.Series(True, index=frame.index, dtype=bool)

    values = frame["official_rank_eligible"]
    if values.dtype == bool:
        return values.fillna(False)

    return (
        values.astype(str)
        .str.strip()
        .str.lower()
        .map({"true": True, "false": False, "1": True, "0": False})
        .fillna(False)
    )


def prepare_supplemental_analysis(
    analysis_name: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    config = SUPPLEMENTAL_ANALYSES[analysis_name]
    frame = supplemental_frame(str(config["file_key"])).copy()

    if frame.empty:
        return frame, config

    filter_type = config.get("filter_type")
    filter_key = config.get("filter_key")

    if filter_type is not None and "ranking_type" in frame.columns:
        frame = frame[
            frame["ranking_type"].astype(str) == str(filter_type)
        ].copy()

    if filter_key is not None and "ranking_key" in frame.columns:
        frame = frame[
            frame["ranking_key"].astype(str) == str(filter_key)
        ].copy()

    rank_column = str(config["rank_column"])
    score_column = str(config["score_column"])
    sample_column = str(config["sample_column"])

    for column in (rank_column, score_column, sample_column):
        if column in frame.columns:
            frame[column] = pd.to_numeric(
                frame[column],
                errors="coerce",
            )

    frame["_supplemental_official"] = supplemental_official_mask(frame)

    if rank_column in frame.columns:
        frame = frame.sort_values(
            [
                "_supplemental_official",
                rank_column,
                "school_name",
            ],
            ascending=[False, True, True],
            na_position="last",
        )

    return frame, config


def supplemental_overview_table() -> pd.DataFrame:
    rows = []
    for analysis_name, config in SUPPLEMENTAL_ANALYSES.items():
        rows.append(
            {
                "Analysis": analysis_name,
                "Current leader": config["leader"],
                "Minimum support": config["minimum_sample"],
                "What it measures": config["interpretation"],
            }
        )
    return pd.DataFrame(rows)


def additional_rankings_page() -> None:
    st.subheader("Supplemental Rankings")
    st.info(
        "These are frozen Milestone 5 Average Development supplemental "
        "analyses. They use posterior value-added and related companion "
        "metrics, not Enhanced Balanced Production points."
    )

    missing = [
        SUPPLEMENTAL_DATA_DIR / filename
        for filename in SUPPLEMENTAL_FILES.values()
        if not (SUPPLEMENTAL_DATA_DIR / filename).exists()
    ]
    if missing:
        st.error(
            "The supplemental Phase 5K publication files are missing."
        )
        st.code("\n".join(str(path) for path in missing))
        return

    st.markdown("#### Current leaders")
    st.dataframe(
        supplemental_overview_table(),
        width="stretch",
        hide_index=True,
        column_config={
            "What it measures": st.column_config.TextColumn(width="large"),
            "Minimum support": st.column_config.TextColumn(width="medium"),
        },
    )

    st.divider()

    analysis_name = st.selectbox(
        "Additional ranking",
        list(SUPPLEMENTAL_ANALYSES),
        key="supplemental_ranking_analysis_v4",
    )

    frame, config = prepare_supplemental_analysis(analysis_name)
    if frame.empty:
        st.warning("No rows are available for the selected analysis.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Current leader", str(config["leader"]))
    c2.metric(
        "Officially ranked schools",
        f"{int(frame['_supplemental_official'].sum()):,}",
    )
    c3.metric("Minimum support", str(config["minimum_sample"]))

    with st.expander("Methodology and interpretation", expanded=True):
        st.markdown(
            f"""\
**Analysis:** {analysis_name}

**Primary metric:** {config["score_label"]}

**Eligibility/support:** {config["minimum_sample"]}

{config["interpretation"]}
            """
        )
        if analysis_name == "Inbound transfer development":
            st.warning(
                "Transfer status is inferred from the first observed school "
                "chronology rather than an external transfer registry."
            )

    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        official_only = st.checkbox(
            "Show officially ranked schools only",
            value=True,
            key=f"supplemental_official_only_{analysis_name}",
        )
    with filter_col2:
        school_search = st.text_input(
            "Search school",
            value="",
            key=f"supplemental_school_search_{analysis_name}",
        ).strip()

    filtered = frame.copy()
    if official_only:
        filtered = filtered[filtered["_supplemental_official"]].copy()

    if school_search:
        filtered = filtered[
            filtered["school_name"]
            .astype(str)
            .str.contains(school_search, case=False, na=False)
        ].copy()

    rank_column = str(config["rank_column"])
    score_column = str(config["score_column"])
    sample_column = str(config["sample_column"])
    score_label = str(config["score_label"])

    display = pd.DataFrame(index=filtered.index)
    display["Rank"] = filtered.get(rank_column)
    display["School"] = filtered.get("school_name")
    display[score_label] = filtered.get(score_column)
    display["Sample"] = filtered.get(sample_column)

    for source_column, label, _format in config.get("extra_columns", []):
        if source_column in filtered.columns:
            values = pd.to_numeric(
                filtered[source_column],
                errors="coerce",
            )
            if "share" in source_column and (
                values.dropna().empty or values.dropna().max() <= 1.0
            ):
                values = values * 100.0
            display[label] = values

    if analysis_name == "Breakout rate" and score_label in display.columns:
        values = pd.to_numeric(display[score_label], errors="coerce")
        if values.dropna().empty or values.dropna().max() <= 1.0:
            display[score_label] = values * 100.0

    if "conference_name" in filtered.columns:
        display["Conference"] = filtered["conference_name"]
    if "state_code" in filtered.columns:
        display["State"] = filtered["state_code"]

    column_config: dict[str, object] = {
        "Rank": st.column_config.NumberColumn(format="%d"),
        score_label: st.column_config.NumberColumn(
            format=str(config["score_format"])
        ),
        "Sample": st.column_config.NumberColumn(format="%d"),
    }

    for _source_column, label, value_format in config.get(
        "extra_columns",
        [],
    ):
        if label in display.columns:
            column_config[label] = st.column_config.NumberColumn(
                format=value_format
            )

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_config=column_config,
    )

    st.download_button(
        "Download selected additional ranking",
        data=display.to_csv(index=False).encode("utf-8"),
        file_name=(
            analysis_name.lower()
            .replace("/", "_")
            .replace(" ", "_")
            + "_rankings.csv"
        ),
        mime="text/csv",
        key=f"download_supplemental_{analysis_name}",
    )



def rankings_hub_page() -> None:
    ranking_section = st.radio(
        "Rankings section",
        ["Official Rankings", "Specialized Rankings"],
        horizontal=True,
        label_visibility="collapsed",
        key="rankings_section_v6",
    )
    st.divider()

    if ranking_section == "Official Rankings":
        official_rankings_page()
    else:
        event_balanced_specialized_rankings_page()


@st.cache_data(show_spinner=False)
def load_event_balanced_specialized_table(
    table_name: str,
) -> pd.DataFrame:
    if not EVENT_BALANCED_SPECIALIZED_DB.exists():
        return pd.DataFrame()

    connection = duckdb.connect(
        str(EVENT_BALANCED_SPECIALIZED_DB),
        read_only=True,
    )
    try:
        return connection.execute(
            f'SELECT * FROM "{table_name}"'
        ).df()
    finally:
        connection.close()


def event_balanced_specialized_overview() -> pd.DataFrame:
    registry = load_event_balanced_specialized_table(
        "specialized_analysis_registry"
    )
    leaders = load_event_balanced_specialized_table(
        "specialized_ranking_leaders"
    )

    if registry.empty:
        return pd.DataFrame()

    overview = registry[
        [
            "analysis_order",
            "analysis_key",
            "analysis_label",
            "official_metric_label",
            "methodology_summary",
        ]
    ].copy()

    if not leaders.empty:
        overview = overview.merge(
            leaders[
                [
                    "analysis_key",
                    "leader_school",
                    "leader_metric_value",
                ]
            ],
            on="analysis_key",
            how="left",
        )
    else:
        overview["leader_school"] = pd.NA
        overview["leader_metric_value"] = pd.NA

    transfer = load_event_balanced_specialized_table(
        "transfer_inference_registry"
    )
    if not transfer.empty:
        transfer_status = str(transfer.iloc[0]["publication_status"])
        mask = (
            overview["analysis_key"].astype(str)
            == "inbound_transfer_development"
        )
        overview.loc[
            mask & overview["leader_school"].isna(),
            "leader_school",
        ] = "Unavailable"
        overview.loc[
            mask,
            "methodology_summary",
        ] = (
            overview.loc[mask, "methodology_summary"].astype(str)
            + f" Publication status: {transfer_status}."
        )

    return overview.sort_values("analysis_order").rename(
        columns={
            "analysis_label": "Analysis",
            "leader_school": "Current leader",
            "official_metric_label": "Metric",
            "methodology_summary": "What it measures",
        }
    )


def prepare_event_balanced_specialized_analysis(
    analysis_name: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    config = EVENT_BALANCED_SPECIALIZED_ANALYSES[analysis_name]
    frame = load_event_balanced_specialized_table(
        str(config["table"])
    ).copy()

    filter_column = config.get("filter_column")
    filter_value = config.get("filter_value")
    if (
        not frame.empty
        and filter_column is not None
        and filter_column in frame.columns
    ):
        frame = frame[
            frame[filter_column].astype(str) == str(filter_value)
        ].copy()

    if "official_rank" in frame.columns:
        frame["official_rank"] = pd.to_numeric(
            frame["official_rank"],
            errors="coerce",
        )
        frame = frame.sort_values(
            ["official_rank", "school_name"],
            na_position="last",
        )

    return frame, config


def specialized_metric_display(
    value: object,
    column_name: str,
) -> str:
    numeric = pd.to_numeric(
        pd.Series([value]),
        errors="coerce",
    ).iloc[0]
    if pd.isna(numeric):
        return "—"
    if column_name in EVENT_BALANCED_PERCENT_COLUMNS:
        return f"{float(numeric):.1%}"
    return f"{float(numeric):,.2f}"


def specialized_column_label(column_name: str) -> str:
    labels = {
        "season_count": "Seasons",
        "calendar_year_count": "Calendar years",
        "mean_rank_strength": "Mean rank strength",
        "rank_strength_sd": "Rank-strength SD",
        "stability_percentile": "Stability percentile",
        "total_net_points": "Net points",
        "athlete_event_unit_count": "Athlete-event units",
        "frontier_season_count": "Frontier seasons",
        "elite_season_count": "Elite seasons",
        "frontier_mean_rank_strength": "Frontier strength",
        "elite_mean_rank_strength": "Elite strength",
        "athlete_school_unit_count": "Athlete-school units",
        "mean_baseline_level": "Mean baseline",
        "mean_endpoint_level": "Mean endpoint",
        "net_points_per_event_unit": "Net points per unit",
        "breakout_count": "Breakouts",
        "raw_breakout_rate": "Raw breakout rate",
        "net_points": "Net points",
        "covered_cell_count": "Covered cells",
        "men_cell_count": "Men's cells",
        "women_cell_count": "Women's cells",
        "mean_cell_strength_percentile": "Mean cell strength",
        "cell_strength_sd": "Cell-strength SD",
        "gender_strength_gap": "Gender-strength gap",
        "total_group_points": "Group points",
        "distinct_athlete_count": "Athletes",
        "positive_points_per_event_unit": "Positive points per unit",
        "compared_partition_count": "Compared partitions",
        "mean_enhanced_rank_strength": "Enhanced rank strength",
        "mean_absolute_rank_shift": "Mean absolute rank shift",
        "within_five_rank_share": "Within five ranks",
        "rank_stability_percentile": "Rank stability",
        "median_rank_strength": "Median rank strength",
    }
    return labels.get(
        column_name,
        column_name.replace("_", " ").title(),
    )


def event_balanced_specialized_rankings_page() -> None:
    st.subheader("Event-Balanced Specialized Rankings")
    st.info(
        "These leaderboards are recalculated from Enhanced Balanced "
        "Production. The posterior supplemental rankings remain under "
        "Average Development."
    )

    if not EVENT_BALANCED_SPECIALIZED_DB.exists():
        st.error("The Phase 7E.2 specialized-ranking database is missing.")
        st.code(str(EVENT_BALANCED_SPECIALIZED_DB))
        return

    overview = event_balanced_specialized_overview()
    if not overview.empty:
        st.markdown("#### Current leaders")
        st.dataframe(
            overview[
                [
                    "Analysis",
                    "Current leader",
                    "Metric",
                    "What it measures",
                ]
            ],
            width="stretch",
            hide_index=True,
            column_config={
                "What it measures": st.column_config.TextColumn(
                    width="large"
                ),
            },
        )

    st.divider()

    analysis_name = st.selectbox(
        "Specialized ranking",
        list(EVENT_BALANCED_SPECIALIZED_ANALYSES),
        key="event_balanced_specialized_analysis_v6",
    )
    frame, config = prepare_event_balanced_specialized_analysis(
        analysis_name
    )

    if analysis_name == "Inbound transfer development" and frame.empty:
        transfer = load_event_balanced_specialized_table(
            "transfer_inference_registry"
        )
        status = "unavailable"
        if not transfer.empty:
            status = str(transfer.iloc[0]["publication_status"])
        st.warning(
            "Inbound transfer development is not publishable under the "
            "current frozen Broad coverage. No leaderboard is fabricated."
        )
        st.caption(f"Publication status: {status}")
        return

    if frame.empty:
        st.warning("No ranking rows are available for this analysis.")
        return

    metric_column = str(config["metric"])
    metric_label = str(config["metric_label"])
    leader = frame.iloc[0]

    c1, c2, c3 = st.columns(3)
    c1.metric("Current leader", str(leader.get("school_name", "—")))
    c2.metric(
        metric_label,
        specialized_metric_display(
            leader.get(metric_column),
            metric_column,
        ),
    )
    c3.metric("Ranked schools", f"{len(frame):,}")

    registry = load_event_balanced_specialized_table(
        "specialized_analysis_registry"
    )
    method = ""
    if not registry.empty:
        matching = registry[
            registry["analysis_label"].astype(str) == analysis_name
        ]
        if not matching.empty:
            method = str(matching.iloc[0]["methodology_summary"])

    with st.expander("Methodology and interpretation", expanded=True):
        st.write(method)
        st.caption(
            "Official model: Enhanced Balanced Production. "
            "The Phase 7E.2 publication passed all 22 hard checks."
        )

    school_search = st.text_input(
        "Search school",
        value="",
        key=f"event_balanced_specialized_search_{analysis_name}",
    ).strip()
    filtered = frame.copy()
    if school_search:
        filtered = filtered[
            filtered["school_name"]
            .astype(str)
            .str.contains(school_search, case=False, na=False)
        ].copy()

    display = pd.DataFrame(index=filtered.index)
    display["Rank"] = filtered.get("official_rank")
    display["School"] = filtered.get("school_name")
    display[metric_label] = filtered.get(metric_column)

    selected_columns = [
        column
        for column in config.get("columns", [])
        if column in filtered.columns
    ]
    for column in selected_columns:
        display[specialized_column_label(column)] = filtered[column]

    column_config: dict[str, object] = {
        "Rank": st.column_config.NumberColumn(format="%d"),
    }

    for source_column in [metric_column, *selected_columns]:
        label = (
            metric_label
            if source_column == metric_column
            else specialized_column_label(source_column)
        )
        if source_column in EVENT_BALANCED_PERCENT_COLUMNS:
            column_config[label] = st.column_config.NumberColumn(
                format="percent"
            )
        elif (
            "count" in source_column
            or source_column.endswith("_units")
            or source_column.endswith("_seasons")
        ):
            column_config[label] = st.column_config.NumberColumn(
                format="%d"
            )
        else:
            column_config[label] = st.column_config.NumberColumn(
                format="%.2f"
            )

    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_config=column_config,
    )

    st.download_button(
        "Download selected specialized ranking",
        data=display.to_csv(index=False).encode("utf-8"),
        file_name=(
            analysis_name.lower()
            .replace("—", "")
            .replace("+", "plus")
            .replace("/", "_")
            .replace(" ", "_")
            + "_event_balanced_rankings.csv"
        ),
        mime="text/csv",
        key=f"download_event_balanced_specialized_{analysis_name}",
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
    st.caption(
        "Secondary Average Athlete Development profile. This page uses the "
        "empirical-Bayes posterior school score from Milestones 5–6, not "
        "Enhanced Balanced Production points. Use Program Trends for the "
        "official Milestone 7 program trajectory."
    )

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

    st.markdown("#### Average-development seasonal trend")
    trend = school_overall[
        [
            "season_year",
            "season_type",
            "Season",
            "season_centered_posterior_score",
        ]
    ].dropna(subset=["season_centered_posterior_score"])
    if trend.empty:
        st.info("No Average Development seasonal scores are available.")
    else:
        profile_chart = (
            alt.Chart(trend)
            .mark_line(point=True)
            .encode(
                x=alt.X(
                    "season_year:O",
                    title="Endpoint year",
                    axis=alt.Axis(labelAngle=0),
                ),
                y=alt.Y(
                    "season_centered_posterior_score:Q",
                    title="Season-relative Average Development score",
                    scale=alt.Scale(zero=False),
                ),
                color=alt.Color(
                    "season_type:N",
                    title="Season type",
                ),
                tooltip=[
                    alt.Tooltip("Season:N", title="Season"),
                    alt.Tooltip(
                        "season_centered_posterior_score:Q",
                        title="Season-relative score",
                        format=".4f",
                    ),
                ],
            )
            .properties(height=340)
        )
        st.altair_chart(profile_chart, width="stretch")

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
    st.subheader("Methodology and Interpretation")

    st.markdown(
        """
### What the official ranking measures

The official primary model is **Enhanced Balanced Production**. It measures
how much reliable athlete development a school produced across NCAA
championship events. It remains a development product—not a forecast of NCAA
championship points or current roster strength.

### Frozen Enhanced Balanced Production model

- Each publishable championship event has a **100,000-point positive budget**.
- Negative development is scored separately and capped at **100,000 points per
  event partition**.
- Athlete contributions receive a support-reliability adjustment with frozen
  **support k = 191**.
- There is **no additional elite multiplier**. Starting level and proximity to
  the event ceiling are already reflected in the nonlinear development scale.
- The primary taxonomy contains **27 championship events** and **seven event
  groups**. Steeplechase belongs to Distance; the 500m, 600m, and 1000m are
  excluded from the primary production ranking.

### Explorer cohorts

The public explorer shows four useful levels:

1. **Broad — All Athletes** for the widest program-production view.
2. **Frontier — Baseline 70+** for athletes who began at a strong level.
3. **Elite — Baseline 80+** for high-level starting athletes.
4. **National Elite Finishers — Endpoint 90+** for development into nationally
   elite performance.

The Endpoint 95+ cohort remains preserved in the publication for auditability,
but it is hidden from the explorer because it contains too few seasons and
school rows to provide a stable program-comparison view.

### Milestone 7 seasonal trends

- Year-over-year movement compares the **same season type** with the exact
  previous calendar year.
- Score movement is `current score − previous score`.
- Rank improvement is `previous rank − current rank`; positive values move
  toward rank 1.
- Indoor-versus-outdoor comparison is a separate same-calendar-year product.
- Missing seasons remain gaps. There is no interpolation, zero filling,
  nearest-year matching, or carry-forward.
- The missing **2020 Outdoor** production season remains absent.
- Trend windows cover the latest **three or five calendar years**.
- Slope-based momentum and trajectory labels require at least **three eligible
  observations**.

### Program Trends metrics

- **Performance percentile:** national percentile of the program's average
  rank-strength percentile in the selected window.
- **Momentum percentile:** national percentile of its rank-strength slope per
  year.
- **Consistency percentile:** inverse national percentile of seasonal
  variation; higher values indicate more stable results.
- **Trajectory:** compares the direction of the Enhanced score slope with the
  direction of the rank-strength slope.

Every percentile is calculated only within the exact selected cohort, ranking
scope, gender, endpoint year, season type, and trend window.

### Average Development and School Profile

**Average Development** is the preserved earlier empirical-Bayes school-average
model. Its School Profile chart plots:

```text
season-centered posterior score
= posterior school score − national mean for the same season and scope
```

That chart is useful as a secondary efficiency-oriented view, but it is not the
Enhanced Balanced Production trend. Use **Program Trends** for the official
Milestone 7 trajectory and **School Profile** when reviewing the preserved
Average Development model.

### Interpretation limits

The results are observational. Sparse cohorts and partitions can have limited
history, and a high rank movement can reflect changes in both the school and
its national peer set. Always review sample counts, available seasons, and the
underlying event/group tables alongside a headline rank.
        """
    )

@st.cache_data(show_spinner=False)
def load_milestone7_table(
    database_path: str,
    modified_ns: int,
    size_bytes: int,
    table_name: str,
) -> pd.DataFrame:
    """Load one curated Milestone 7 table with cache invalidation."""
    del modified_ns, size_bytes
    allowed = set(MILESTONE7_TABLES.values())
    if table_name not in allowed:
        raise ValueError(f"Unregistered Milestone 7 table: {table_name}")

    connection = duckdb.connect(database_path, read_only=True)
    try:
        return connection.execute(
            f"SELECT * FROM {table_name}"
        ).fetchdf()
    finally:
        connection.close()


def milestone7_table(table_key: str) -> pd.DataFrame:
    if table_key not in MILESTONE7_TABLES:
        raise KeyError(f"Unknown Milestone 7 table key: {table_key}")
    if not MILESTONE7_DB.exists():
        st.error(
            "The final Milestone 7 publication database was not found."
        )
        st.code(str(MILESTONE7_DB))
        st.info(
            "Run the Phase 7D final-publication builder, then refresh."
        )
        st.stop()

    stat = MILESTONE7_DB.stat()
    return load_milestone7_table(
        str(MILESTONE7_DB),
        stat.st_mtime_ns,
        stat.st_size,
        MILESTONE7_TABLES[table_key],
    )


def milestone7_reload_button(key: str) -> None:
    if st.button(
        "Reload Milestone 7 data",
        key=key,
        help="Clear cached tables after rebuilding the Phase 7D database.",
    ):
        st.cache_data.clear()
        st.rerun()


def friendly_scope(value: object) -> str:
    labels = {
        "production_overall_combined": "Overall — Combined",
        "production_overall_gender": "Overall — By Gender",
    }
    return labels.get(str(value), str(value).replace("_", " ").title())


def friendly_direction(value: object) -> str:
    if pd.isna(value):
        return "—"
    labels = {
        "rising_aligned": "Rising",
        "falling_aligned": "Falling",
        "score_up_rank_down": "Score up / rank down",
        "score_down_rank_up": "Score down / rank up",
        "stable": "Stable",
        "mixed": "Mixed signals",
        "insufficient_history": "Insufficient history",
        "unavailable": "Unavailable",
    }
    key = str(value)
    return labels.get(key, key.replace("_", " ").title())


def percentile_text(value: object) -> str:
    if pd.isna(value):
        return "—"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(numeric):
        return "—"
    return f"{100.0 * numeric:.1f}%"


def compact_number(value: object) -> str:
    if pd.isna(value):
        return "—"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(numeric):
        return "—"

    absolute = abs(numeric)
    if absolute >= 1_000_000:
        return f"{numeric / 1_000_000:.2f}M"
    if absolute >= 1_000:
        return f"{numeric / 1_000:.1f}K"
    return f"{numeric:,.2f}"

def select_program_partition(
    frame: pd.DataFrame,
    *,
    key_prefix: str,
    include_endpoint: bool,
    trend_mode: bool = False,
) -> tuple[pd.DataFrame, dict[str, object]]:
    filtered = frame.copy()
    filtered = filtered[
        ~filtered["cohort_key"]
        .astype(str)
        .isin(MILESTONE7_EXCLUDED_COHORT_KEYS)
    ].copy()
    selected: dict[str, object] = {}

    if trend_mode:
        c1, c2, c3 = st.columns(3)
        season_types = sorted(
            filtered["season_type"].dropna().astype(str).unique(),
            key=lambda value: (value != "outdoor", value),
        )
        with c1:
            season_type = st.selectbox(
                "Season type",
                season_types,
                format_func=lambda value: str(value).title(),
                key=f"{key_prefix}_season_type_v3",
            )
        filtered = filtered[
            filtered["season_type"].astype(str) == season_type
        ]
        selected["season_type"] = season_type

        scopes = sorted(filtered["ranking_scope"].dropna().astype(str).unique())
        with c2:
            ranking_scope = st.selectbox(
                "Ranking scope",
                scopes,
                format_func=friendly_scope,
                key=f"{key_prefix}_scope_v3",
            )
        filtered = filtered[
            filtered["ranking_scope"].astype(str) == ranking_scope
        ]
        selected["ranking_scope"] = ranking_scope

        genders = sorted(filtered["gender_scope"].dropna().astype(str).unique())
        with c3:
            gender_scope = st.selectbox(
                "Gender",
                genders,
                format_func=format_gender,
                key=f"{key_prefix}_gender_v3",
            )
        filtered = filtered[
            filtered["gender_scope"].astype(str) == gender_scope
        ]
        selected["gender_scope"] = gender_scope

        counts = MILESTONE7_TREND_SEASON_COUNTS.get(season_type, {})
        cohorts = (
            filtered[["cohort_key", "cohort_label"]]
            .drop_duplicates()
            .copy()
        )
        cohorts["season_count"] = (
            cohorts["cohort_key"].astype(str).map(counts).fillna(0).astype(int)
        )
        cohorts = cohorts[cohorts["season_count"] >= 3].copy()
        priority = (
            [
                "broad_all_athletes",
                "frontier_70_plus",
                "elite_80_plus",
                "national_elite_endpoint_90_plus",
            ]
            if season_type == "outdoor"
            else [
                "frontier_70_plus",
                "elite_80_plus",
                "national_elite_endpoint_90_plus",
            ]
        )
        order = {key: index for index, key in enumerate(priority)}
        cohorts["_order"] = cohorts["cohort_key"].astype(str).map(order).fillna(99)
        cohorts = cohorts.sort_values(["_order", "cohort_label"])
        cohort_keys = cohorts["cohort_key"].astype(str).tolist()
        label_map = {
            str(row.cohort_key): (
                f"{row.cohort_label} · {int(row.season_count)} seasons"
            )
            for row in cohorts.itertuples()
        }
        raw_label_map = {
            str(row.cohort_key): str(row.cohort_label)
            for row in cohorts.itertuples()
        }

        c1, c2, c3 = st.columns(3)
        with c1:
            cohort_key = st.selectbox(
                "Development cohort",
                cohort_keys,
                format_func=lambda value: label_map.get(str(value), str(value)),
                key=f"{key_prefix}_cohort_v3",
            )
        filtered = filtered[
            filtered["cohort_key"].astype(str) == str(cohort_key)
        ]
        selected.update(
            cohort_key=str(cohort_key),
            cohort_label=raw_label_map.get(str(cohort_key), str(cohort_key)),
        )

        windows = sorted(filtered["window_years"].dropna().astype(int).unique())
        with c2:
            window_years = st.selectbox(
                "Trend window",
                windows,
                format_func=lambda value: f"{int(value)} calendar years",
                key=f"{key_prefix}_window_v3",
            )
        filtered = filtered[
            filtered["window_years"].astype(int) == int(window_years)
        ]
        selected["window_years"] = int(window_years)

        with c3:
            st.caption(
                "Trend mode shows only cohorts with at least three "
                "registered seasons. Broad Indoor remains available under "
                "Rankings, but not as a multi-season trend."
            )
        return filtered.copy(), selected

    cohorts = (
        filtered[["cohort_key", "cohort_label"]]
        .drop_duplicates()
        .sort_values("cohort_label")
    )
    cohort_keys = cohorts["cohort_key"].astype(str).tolist()
    label_map = {
        str(row.cohort_key): str(row.cohort_label)
        for row in cohorts.itertuples()
    }

    c1, c2, c3 = st.columns(3)
    with c1:
        cohort_key = st.selectbox(
            "Development cohort",
            cohort_keys,
            format_func=lambda value: label_map.get(str(value), str(value)),
            key=f"{key_prefix}_cohort",
        )
    filtered = filtered[
        filtered["cohort_key"].astype(str) == str(cohort_key)
    ]
    selected.update(
        cohort_key=str(cohort_key),
        cohort_label=label_map.get(str(cohort_key), str(cohort_key)),
    )

    scopes = sorted(filtered["ranking_scope"].dropna().astype(str).unique())
    with c2:
        ranking_scope = st.selectbox(
            "Ranking scope",
            scopes,
            format_func=friendly_scope,
            key=f"{key_prefix}_scope",
        )
    filtered = filtered[
        filtered["ranking_scope"].astype(str) == ranking_scope
    ]
    selected["ranking_scope"] = ranking_scope

    genders = sorted(filtered["gender_scope"].dropna().astype(str).unique())
    with c3:
        gender_scope = st.selectbox(
            "Gender",
            genders,
            format_func=format_gender,
            key=f"{key_prefix}_gender",
        )
    filtered = filtered[
        filtered["gender_scope"].astype(str) == gender_scope
    ]
    selected["gender_scope"] = gender_scope

    c1, c2, c3 = st.columns(3)
    season_types = sorted(
        filtered["season_type"].dropna().astype(str).unique(),
        key=lambda value: (value != "outdoor", value),
    )
    with c1:
        season_type = st.selectbox(
            "Season type",
            season_types,
            format_func=lambda value: str(value).title(),
            key=f"{key_prefix}_season_type",
        )
    filtered = filtered[
        filtered["season_type"].astype(str) == season_type
    ]
    selected["season_type"] = season_type

    windows = sorted(filtered["window_years"].dropna().astype(int).unique())
    with c2:
        window_years = st.selectbox(
            "Trend window",
            windows,
            format_func=lambda value: f"{int(value)} calendar years",
            key=f"{key_prefix}_window",
        )
    filtered = filtered[
        filtered["window_years"].astype(int) == int(window_years)
    ]
    selected["window_years"] = int(window_years)

    if include_endpoint:
        endpoints = sorted(
            filtered["endpoint_year"].dropna().astype(int).unique(),
            reverse=True,
        )
        with c3:
            endpoint_year = st.selectbox(
                "Endpoint year",
                endpoints,
                key=f"{key_prefix}_endpoint",
            )
        filtered = filtered[
            filtered["endpoint_year"].astype(int) == int(endpoint_year)
        ]
        selected["endpoint_year"] = int(endpoint_year)

    return filtered.copy(), selected

def program_trends_page() -> None:
    st.subheader("Program Trends")
    st.caption(
        "Audited Enhanced Balanced Production trajectories using exact "
        "same-season previous-year comparisons and three-/five-calendar-year "
        "windows. Missing seasons remain explicit gaps."
    )
    milestone7_reload_button("reload_milestone7_trends")

    latest = milestone7_table("latest_summary")
    if latest.empty:
        st.info("No Milestone 7 program summaries are available.")
        return

    controls, selected = select_program_partition(
        latest,
        key_prefix="m7_trends",
        include_endpoint=False,
        trend_mode=True,
    )
    schools = (
        controls[["resolved_school_id", "school_name"]]
        .drop_duplicates()
        .sort_values("school_name")
    )
    if schools.empty:
        st.info("No schools are available for this partition.")
        return

    school_name = st.selectbox(
        "School",
        schools["school_name"].astype(str).tolist(),
        key="m7_trends_school",
    )
    school_id = schools.loc[
        schools["school_name"].astype(str) == school_name,
        "resolved_school_id",
    ].iloc[0]
    row = controls[controls["resolved_school_id"] == school_id].iloc[0]

    st.markdown(f"### {school_name}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Latest season", str(row.get("latest_season_label", "—")))
    c2.metric("Latest rank", safe_number(row.get("latest_source_rank"), 0))
    c3.metric("Performance", percentile_text(row.get("performance_percentile")))
    c4.metric(
        f"{int(selected['window_years'])}-year trajectory",
        friendly_direction(row.get("trajectory_direction")),
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Momentum", percentile_text(row.get("momentum_percentile")))
    c2.metric("Consistency", percentile_text(row.get("consistency_percentile")))
    c3.metric(
        "National momentum rank",
        safe_number(row.get("momentum_rank"), 0),
    )
    c4.metric(
        "Recent YoY rank change",
        safe_number(row.get("latest_yoy_rank_improvement"), 0),
    )

    st.caption(
        "Performance compares average rank strength, momentum compares the "
        "rank-strength slope, and consistency rewards lower seasonal "
        "variation within the selected national partition."
    )

    st.markdown("#### Overall seasonal history")
    series = milestone7_table("overall_season")
    series = series[
        (series["model_key"] == "enhanced_balanced_production")
        & (series["cohort_key"].astype(str) == str(selected["cohort_key"]))
        & (series["ranking_scope"].astype(str) == str(selected["ranking_scope"]))
        & (series["gender_scope"].astype(str) == str(selected["gender_scope"]))
        & (series["season_type"].astype(str) == str(selected["season_type"]))
        & (series["resolved_school_id"] == school_id)
    ].copy()
    series = series.sort_values("season_year")

    if series.empty:
        st.info("No overall seasonal history is available.")
    else:
        score_chart = series[
            ["season_year", "rank_strength_percentile"]
        ].dropna(subset=["rank_strength_percentile"])

        if score_chart.empty:
            st.info("No rank-strength observations are available to chart.")
        else:
            seasonal_chart = (
                alt.Chart(score_chart)
                .mark_line(point=True)
                .encode(
                    x=alt.X(
                        "season_year:O",
                        title="Season year",
                        axis=alt.Axis(labelAngle=0),
                    ),
                    y=alt.Y(
                        "rank_strength_percentile:Q",
                        title="National rank-strength percentile",
                        scale=alt.Scale(domain=[0, 1]),
                        axis=alt.Axis(format=".0%"),
                    ),
                    tooltip=[
                        alt.Tooltip("season_year:O", title="Season year"),
                        alt.Tooltip(
                            "rank_strength_percentile:Q",
                            title="Rank strength",
                            format=".1%",
                        ),
                    ],
                )
                .properties(height=360)
            )
            st.altair_chart(seasonal_chart, width="stretch")

            observation_count = len(score_chart)
            if observation_count == 1:
                st.info(
                    "Only one season is available for this exact cohort, "
                    "scope, gender, and season type. The observation is "
                    "shown as a point, but momentum, consistency, and a "
                    "trajectory require at least three eligible seasons. "
                    "For deeper indoor history, try Frontier 70+ or "
                    "National Elite Finishers 90+."
                )
            elif observation_count == 2:
                st.info(
                    "Two seasons are visible, but audited slope-based trend "
                    "labels require at least three eligible observations."
                )

        history_columns = [
            "season_label",
            "source_rank",
            "ranked_school_count",
            "rank_strength_percentile",
            "primary_metric_value",
            "positive_share",
            "net_share",
            "scoring_breadth",
            "athlete_unit_count",
        ]
        history_columns = [
            column for column in history_columns if column in series.columns
        ]
        history = series[history_columns].rename(
            columns={
                "season_label": "Season",
                "source_rank": "Rank",
                "ranked_school_count": "Ranked schools",
                "rank_strength_percentile": "Rank strength",
                "primary_metric_value": "Enhanced points",
                "positive_share": "Positive share",
                "net_share": "Net share",
                "scoring_breadth": "Scoring breadth",
                "athlete_unit_count": "Athlete-event units",
            }
        )
        st.dataframe(
            history,
            width="stretch",
            hide_index=True,
            column_config={
                "Rank strength": st.column_config.NumberColumn(
                    format="percent",
                ),
                "Positive share": st.column_config.NumberColumn(
                    format="percent",
                ),
                "Net share": st.column_config.NumberColumn(
                    format="percent",
                ),
                "Scoring breadth": st.column_config.NumberColumn(
                    format="percent",
                ),
            },
        )

    st.markdown("#### Exact year-over-year movement")
    yoy = milestone7_table("overall_yoy")
    yoy = yoy[
        (yoy["model_key"] == "enhanced_balanced_production")
        & (yoy["cohort_key"].astype(str) == str(selected["cohort_key"]))
        & (yoy["ranking_scope"].astype(str) == str(selected["ranking_scope"]))
        & (yoy["gender_scope"].astype(str) == str(selected["gender_scope"]))
        & (yoy["season_type"].astype(str) == str(selected["season_type"]))
        & (yoy["resolved_school_id"] == school_id)
    ].copy()
    yoy = yoy.sort_values("current_season_year", ascending=False)
    yoy_columns = [
        "current_season_label",
        "previous_season_label",
        "comparison_status",
        "primary_metric_delta",
        "rank_improvement",
        "rank_strength_delta",
        "positive_share_delta",
        "net_share_delta",
        "scoring_breadth_delta",
    ]
    yoy_columns = [column for column in yoy_columns if column in yoy.columns]
    st.dataframe(
        yoy[yoy_columns].head(12),
        width="stretch",
        hide_index=True,
    )

    left, right = st.columns(2)
    with left:
        st.markdown("#### Event-group profile")
        groups = milestone7_table("group_window")
        groups = groups[
            (groups["model_key"] == "enhanced_balanced_production")
            & (groups["cohort_key"].astype(str) == str(selected["cohort_key"]))
            & (groups["gender_scope"].astype(str) == str(selected["gender_scope"]))
            & (groups["season_type"].astype(str) == str(selected["season_type"]))
            & (groups["window_years"].astype(int) == int(selected["window_years"]))
            & (groups["resolved_school_id"] == school_id)
        ].copy()
        if not groups.empty:
            endpoint = int(groups["endpoint_year"].max())
            groups = groups[groups["endpoint_year"].astype(int) == endpoint]
            group_columns = [
                "balanced_group_label",
                "mean_rank_strength_percentile",
                "rank_strength_slope_per_year",
                "eligible_observation_count",
            ]
            group_columns = [c for c in group_columns if c in groups.columns]
            st.dataframe(
                groups[group_columns].sort_values(
                    "mean_rank_strength_percentile",
                    ascending=False,
                    na_position="last",
                ),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No group trend rows are available.")

    with right:
        st.markdown("#### Individual-event profile")
        events = milestone7_table("event_window")
        events = events[
            (events["model_key"] == "enhanced_balanced_production")
            & (events["cohort_key"].astype(str) == str(selected["cohort_key"]))
            & (events["gender_scope"].astype(str) == str(selected["gender_scope"]))
            & (events["season_type"].astype(str) == str(selected["season_type"]))
            & (events["window_years"].astype(int) == int(selected["window_years"]))
            & (events["resolved_school_id"] == school_id)
        ].copy()
        if not events.empty:
            endpoint = int(events["endpoint_year"].max())
            events = events[events["endpoint_year"].astype(int) == endpoint]
            event_columns = [
                "canonical_event_name",
                "balanced_group_label",
                "mean_rank_strength_percentile",
                "rank_strength_slope_per_year",
                "eligible_observation_count",
            ]
            event_columns = [c for c in event_columns if c in events.columns]
            st.dataframe(
                events[event_columns].sort_values(
                    "mean_rank_strength_percentile",
                    ascending=False,
                    na_position="last",
                ).head(15),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No event trend rows are available.")


def program_comparison_page() -> None:
    st.subheader("Program Comparison")
    st.caption(
        "Compare two schools inside the exact same Enhanced Balanced "
        "Production cohort, scope, gender, endpoint, season type, and trend "
        "window. Percentiles are national within that partition."
    )
    milestone7_reload_button("reload_milestone7_comparison")

    summary = milestone7_table("program_summary")
    if summary.empty:
        st.info("No comparison-ready program rows are available.")
        return

    controls, selected = select_program_partition(
        summary,
        key_prefix="m7_compare",
        include_endpoint=True,
    )
    schools = (
        controls[["resolved_school_id", "school_name"]]
        .drop_duplicates()
        .sort_values("school_name")
    )
    school_names = schools["school_name"].astype(str).tolist()
    if len(school_names) < 2:
        st.info("At least two schools are required in this partition.")
        return

    left, right = st.columns(2)
    with left:
        school_a = st.selectbox(
            "School A",
            school_names,
            index=0,
            key="m7_compare_school_a",
        )
    remaining = [name for name in school_names if name != school_a]
    with right:
        school_b = st.selectbox(
            "School B",
            remaining,
            index=0,
            key="m7_compare_school_b",
        )

    selected_rows = controls[
        controls["school_name"].astype(str).isin([school_a, school_b])
    ].copy()
    selected_rows = selected_rows.sort_values("school_name")

    comparison_columns = [
        "school_name",
        "conference_name",
        "latest_season_label",
        "latest_source_rank",
        "performance_percentile",
        "momentum_percentile",
        "consistency_percentile",
        "mean_rank_strength_percentile",
        "rank_strength_slope_per_year",
        "performance_rank",
        "momentum_rank",
        "consistency_rank",
        "conference_performance_rank",
        "conference_momentum_rank",
        "conference_consistency_rank",
        "trajectory_direction",
        "rise_fall_status",
        "strongest_group",
        "fastest_rising_group",
        "strongest_event",
        "fastest_rising_event",
        "indoor_outdoor_profile",
    ]
    comparison_columns = [
        column for column in comparison_columns if column in selected_rows.columns
    ]
    display = selected_rows[comparison_columns].rename(
        columns={
            "school_name": "School",
            "conference_name": "Conference",
            "latest_season_label": "Latest season",
            "latest_source_rank": "Latest rank",
            "performance_percentile": "Performance percentile",
            "momentum_percentile": "Momentum percentile",
            "consistency_percentile": "Consistency percentile",
            "mean_rank_strength_percentile": "Mean rank strength",
            "rank_strength_slope_per_year": "Rank-strength slope",
            "performance_rank": "National performance rank",
            "momentum_rank": "National momentum rank",
            "consistency_rank": "National consistency rank",
            "conference_performance_rank": "Conference performance rank",
            "conference_momentum_rank": "Conference momentum rank",
            "conference_consistency_rank": "Conference consistency rank",
            "trajectory_direction": "Trajectory",
            "rise_fall_status": "Recent rise/fall",
            "strongest_group": "Strongest group",
            "fastest_rising_group": "Fastest-rising group",
            "strongest_event": "Strongest event",
            "fastest_rising_event": "Fastest-rising event",
            "indoor_outdoor_profile": "Indoor/outdoor profile",
        }
    )
    st.dataframe(display, width="stretch", hide_index=True)

    st.markdown("#### Comparable percentile profile")
    metrics = milestone7_table("metric_long")
    metrics = metrics[
        (metrics["cohort_key"].astype(str) == str(selected["cohort_key"]))
        & (metrics["ranking_scope"].astype(str) == str(selected["ranking_scope"]))
        & (metrics["gender_scope"].astype(str) == str(selected["gender_scope"]))
        & (metrics["season_type"].astype(str) == str(selected["season_type"]))
        & (metrics["window_years"].astype(int) == int(selected["window_years"]))
        & (metrics["endpoint_year"].astype(int) == int(selected["endpoint_year"]))
        & metrics["school_name"].astype(str).isin([school_a, school_b])
        & metrics["metric_family"].astype(str).isin(["percentile", "coverage"])
    ].copy()

    if not metrics.empty:
        chart = metrics.pivot_table(
            index="metric_label",
            columns="school_name",
            values="metric_value",
            aggfunc="first",
        )
        st.bar_chart(
            chart,
            horizontal=True,
            x_label="Percentile or coverage rate",
            y_label="Metric",
        )
        st.dataframe(
            chart.reset_index(),
            width="stretch",
            hide_index=True,
        )

    st.markdown("#### Same-year indoor versus outdoor history")
    io = milestone7_table("indoor_outdoor")
    selected_ids = schools[
        schools["school_name"].astype(str).isin([school_a, school_b])
    ]["resolved_school_id"].tolist()
    io = io[
        (io["cohort_key"].astype(str) == str(selected["cohort_key"]))
        & (io["ranking_scope"].astype(str) == str(selected["ranking_scope"]))
        & (io["gender_scope"].astype(str) == str(selected["gender_scope"]))
        & io["resolved_school_id"].isin(selected_ids)
        & io["is_comparable"].fillna(False)
    ].copy()
    io = io.sort_values(["season_year", "school_name"], ascending=[False, True])
    io_columns = [
        "season_year",
        "school_name",
        "indoor_rank",
        "outdoor_rank",
        "outdoor_rank_improvement",
        "outdoor_minus_indoor_rank_strength",
        "outdoor_minus_indoor_primary_metric",
        "outdoor_minus_indoor_scoring_breadth",
    ]
    io_columns = [column for column in io_columns if column in io.columns]
    if io.empty:
        st.info("No exact same-year indoor/outdoor comparisons are available.")
    else:
        st.dataframe(
            io[io_columns],
            width="stretch",
            hide_index=True,
        )

    csv_bytes = display.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download school comparison",
        data=csv_bytes,
        file_name="milestone7_program_comparison.csv",
        mime="text/csv",
    )



def average_development_hub_page() -> None:
    st.subheader("Average Development")
    st.caption(
        "Preserved empirical-Bayes companion model from Milestones 5–6. "
        "These pages are separate from the official Enhanced Balanced "
        "Production rankings."
    )
    view = st.radio(
        "Average Development view",
        ["Rankings", "School Profile", "Supplemental Rankings"],
        horizontal=True,
        label_visibility="collapsed",
        key="average_development_subpage",
    )
    st.divider()

    if view == "Rankings":
        rankings_page()
    elif view == "School Profile":
        school_profile_page()
    else:
        additional_rankings_page()

def main() -> None:
    configure_page()
    require_data()

    st.title(APP_TITLE)
    st.caption(
        "Official NCAA Division I development rankings, Milestone 7 "
        "program trajectories, peer comparisons, and preserved companion "
        "models."
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
        with st.expander("Data version details", expanded=False):
            st.caption(
                "Loaded datasets: " + ", ".join(loaded_versions)
            )

    st.markdown("### Explore")
    navigation_label = st.radio(
        "Explorer page",
        list(MILESTONE7_NAVIGATION),
        horizontal=True,
        label_visibility="collapsed",
        key="top_explorer_navigation",
    )
    page = MILESTONE7_NAVIGATION[navigation_label]

    with st.sidebar:
        st.header("About")
        st.markdown(
            """
**Official model:** Enhanced Balanced Production

Program Trends and Program Comparison use the frozen Milestone 7 publication.
School Profile and Average Development preserve the earlier empirical-Bayes
model as a clearly labeled secondary view.

These are athlete-development rankings, not projected NCAA championship
points. Endpoint 90+ is provisional; the sparse Endpoint 95+ view is retained
in the data publication but hidden from the explorer.
            """
        )

    if page == "Event-Balanced Points":
        rankings_hub_page()
    elif page == "Model Diagnostics":
        model_diagnostics_page()
    elif page == "Program Trends":
        program_trends_page()
    elif page == "Program Comparison":
        program_comparison_page()
    elif page == "Average Development":
        average_development_hub_page()
    elif page == "Season Coverage":
        season_summary_page()
    else:
        methodology_page()


if __name__ == "__main__":
    main()
