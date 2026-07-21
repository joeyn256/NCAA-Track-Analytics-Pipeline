from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pytest
from streamlit.testing.v1 import AppTest


APP_PATH = (
    Path(__file__).resolve().parents[1]
    / "src/apps/seasonal_development_explorer.py"
)
POINT_TABLES = (
    "event_balanced_overall_combined",
    "event_balanced_overall_gender",
    "event_balanced_point_rows",
    "athlete_model_points",
    "group_balanced_points_combined",
    "group_balanced_points_gender",
    "group_balanced_overall_combined",
    "group_balanced_overall_gender",
)
POINT_SCHEMA = """
    model_key VARCHAR,
    cohort_key VARCHAR,
    time_scope VARCHAR,
    season_year BIGINT,
    season_type VARCHAR,
    dataset_version VARCHAR,
    event_balanced_rank BIGINT,
    school_name VARCHAR,
    total_positive_event_points DOUBLE,
    total_negative_event_points DOUBLE,
    total_event_balanced_points DOUBLE
"""


def build_explorer_fixture(path: Path) -> Path:
    connection = duckdb.connect(str(path))
    try:
        for schema in (
            "average_seasonal_broad",
            "average_seasonal_elite",
            "official",
        ):
            connection.execute(f"CREATE SCHEMA {schema}")

        connection.execute(
            """
            CREATE TABLE average_seasonal_broad.season_coverage_summary
            AS SELECT 'synthetic-explorer-v1'::VARCHAR AS dataset_version
            """
        )
        connection.execute(
            """
            CREATE TABLE average_seasonal_elite.elite_season_coverage
            AS SELECT *
            FROM (
                VALUES
                    ('frontier_70_plus', 'synthetic-explorer-v1'),
                    ('elite_80_plus', 'synthetic-explorer-v1'),
                    (
                        'national_elite_endpoint_90_plus',
                        'synthetic-explorer-v1'
                    ),
                    (
                        'championship_endpoint_95_plus',
                        'synthetic-explorer-v1'
                    )
            ) AS rows(cohort_key, dataset_version)
            """
        )
        connection.execute(
            """
            CREATE TABLE official.model_registry AS
            SELECT
                'enhanced_balanced_production'::VARCHAR AS model_key,
                'Enhanced Balanced Production'::VARCHAR AS model_label,
                'Official synthetic regression fixture.'::VARCHAR
                    AS model_description,
                TRUE AS is_primary,
                'synthetic-explorer-v1'::VARCHAR AS dataset_version
            """
        )
        connection.execute(
            """
            CREATE TABLE official.final_model_decision AS
            SELECT
                'enhanced_balanced_production'::VARCHAR
                    AS selected_model_key,
                'synthetic-explorer-v1'::VARCHAR AS dataset_version
            """
        )
        connection.execute(
            """
            CREATE TABLE official.event_budget_audit AS
            SELECT
                'enhanced_balanced_production'::VARCHAR AS model_key,
                'broad_all_athletes'::VARCHAR AS cohort_key,
                'all_time'::VARCHAR AS time_scope,
                NULL::BIGINT AS season_year,
                'all'::VARCHAR AS season_type,
                'synthetic-explorer-v1'::VARCHAR AS dataset_version
            """
        )

        for table in POINT_TABLES:
            connection.execute(
                f"CREATE TABLE official.{table} ({POINT_SCHEMA})"
            )

        connection.execute(
            """
            INSERT INTO official.event_balanced_overall_combined
            VALUES (
                'enhanced_balanced_production',
                'broad_all_athletes',
                'all_time',
                NULL,
                'all',
                'synthetic-explorer-v1',
                1,
                'Example University',
                125000.0,
                -5000.0,
                120000.0
            )
            """
        )
    finally:
        connection.close()

    return path


def visible_text(app: AppTest) -> str:
    collections = (
        "title",
        "subheader",
        "markdown",
        "caption",
        "info",
        "success",
        "warning",
    )
    return "\n".join(
        str(element.value)
        for collection in collections
        for element in getattr(app, collection)
    )


def selectbox(app: AppTest, label: str):
    return next(item for item in app.selectbox if item.label == label)


def test_recruiter_homepage_and_default_rankings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = build_explorer_fixture(tmp_path / "explorer.duckdb")
    environment = {
        "NCAA_TRACK_PUBLIC_DB": str(database),
        "NCAA_TRACK_PUBLIC_DB_URL": "",
        "NCAA_TRACK_PUBLIC_DB_SHA256": "",
        "NCAA_TRACK_PUBLIC_GZIP_SHA256": "",
        "NCAA_TRACK_PUBLIC_CACHE_DIR": str(tmp_path / "cache"),
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)

    for name in (
        "src.apps.seasonal_development_explorer",
        "src.apps.deployment_data",
        "deployment_data",
    ):
        sys.modules.pop(name, None)

    app = AppTest.from_file(str(APP_PATH), default_timeout=20).run()

    assert not app.exception
    assert app.title[0].value == (
        "NCAA Division I Athlete Development Explorer"
    )
    assert app.subheader[0].value == (
        "Event-Balanced Development Points"
    )
    assert len(app.dataframe) == 1

    assert app.radio[0].value == "Rankings"
    assert app.radio[0].options == [
        "Rankings",
        "Trends",
        "Compare",
        "Average Development",
        "Diagnostics",
        "Coverage",
        "Methodology",
    ]
    assert app.radio[1].value == "Official Rankings"

    assert selectbox(app, "Scoring model").value == (
        "Enhanced Balanced Production"
    )
    cohort = selectbox(app, "Development cohort")
    assert cohort.value == "Broad — All Athletes"
    assert "National Elite Finishers — Endpoint 90+" in cohort.options
    assert (
        "Championship-Caliber Finishers — Endpoint 95+"
        not in cohort.options
    )
    assert selectbox(app, "Time view").value == "All Time"
    assert selectbox(app, "Points view").value == "Overall — Combined"

    text = visible_text(app)
    required_text = (
        "2020 Outdoor",
        "does not interpolate, carry forward, or fabricate",
        "Inbound transfer development",
        "explicitly unavailable",
        "Enhanced Balanced Production is the official",
        "Endpoint 90+",
        "Endpoint 95+",
    )
    for value in required_text:
        assert value in text
