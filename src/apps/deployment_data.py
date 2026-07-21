"""Shared compact-publication data access for the Streamlit explorer."""

from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Final
from urllib.request import urlopen

import duckdb
import pandas as pd


ROOT: Final = Path(__file__).resolve().parents[2]

DEFAULT_PUBLIC_DATABASE_PATH: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8b_compact_publication"
    / "ncaa_track_public_explorer_v1.duckdb"
)

DEFAULT_CACHE_DIRECTORY: Final = (
    ROOT / ".cache/ncaa_track_analytics"
)

DATABASE_FILENAME: Final = (
    "ncaa_track_public_explorer_v1.duckdb"
)

EXPECTED_DATABASE_SHA256: Final = "7ab85809ab11b24ba98b0d5878f41242cfad53e1a1cbd4008dde36ec0f046de4"
EXPECTED_GZIP_SHA256: Final = "2a4aa9fd321dce96313d24cf532fbb8200d22847f6b6257138e0b49eed86432c"

CSV_RESOURCE_TABLES: Final = {'data/processed/milestone5/athlete_development_v1/phase_5i_publication_freeze/all_school_rankings.csv': ('average',
                                                                                                          'all_school_rankings'),
 'data/processed/milestone5/athlete_development_v1/phase_5i_publication_freeze/event_family_rankings.csv': ('average',
                                                                                                            'event_family_rankings'),
 'data/processed/milestone5/athlete_development_v1/phase_5i_publication_freeze/mens_rankings.csv': ('average',
                                                                                                    'mens_rankings'),
 'data/processed/milestone5/athlete_development_v1/phase_5i_publication_freeze/womens_rankings.csv': ('average',
                                                                                                      'womens_rankings'),
 'data/processed/milestone5/athlete_development_v1/phase_5k_supplemental_development_rankings/balanced_program_rankings.csv': ('average_supplemental',
                                                                                                                               'balanced_program_rankings'),
 'data/processed/milestone5/athlete_development_v1/phase_5k_supplemental_development_rankings/baseline_tier_rankings.csv': ('average_supplemental',
                                                                                                                            'baseline_tier_rankings'),
 'data/processed/milestone5/athlete_development_v1/phase_5k_supplemental_development_rankings/breakout_rate_rankings.csv': ('average_supplemental',
                                                                                                                            'breakout_rate_rankings'),
 'data/processed/milestone5/athlete_development_v1/phase_5k_supplemental_development_rankings/development_consistency_rankings.csv': ('average_supplemental',
                                                                                                                                      'development_consistency_rankings'),
 'data/processed/milestone5/athlete_development_v1/phase_5k_supplemental_development_rankings/development_efficiency_rankings.csv': ('average_supplemental',
                                                                                                                                     'development_efficiency_rankings'),
 'data/processed/milestone5/athlete_development_v1/phase_5k_supplemental_development_rankings/elite_development_rankings.csv': ('average_supplemental',
                                                                                                                                'elite_development_rankings'),
 'data/processed/milestone5/athlete_development_v1/phase_5k_supplemental_development_rankings/ranking_robustness_rankings.csv': ('average_supplemental',
                                                                                                                                 'ranking_robustness_rankings'),
 'data/processed/milestone5/athlete_development_v1/phase_5k_supplemental_development_rankings/transfer_development_rankings.csv': ('average_supplemental',
                                                                                                                                   'transfer_development_rankings'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/athlete_model_points.csv': ('official',
                                                                                                                 'athlete_model_points'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/elite_reward_audit.csv': ('official',
                                                                                                               'elite_reward_audit'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/elite_reward_monotonicity_summary.csv': ('official',
                                                                                                                              'elite_reward_monotonicity_summary'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/event_balanced_overall_combined.csv': ('official',
                                                                                                                            'event_balanced_overall_combined'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/event_balanced_overall_gender.csv': ('official',
                                                                                                                          'event_balanced_overall_gender'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/event_balanced_point_rows.csv': ('official',
                                                                                                                      'event_balanced_point_rows'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/event_budget_audit.csv': ('official',
                                                                                                               'event_budget_audit'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/event_concentration_diagnostics.csv': ('official',
                                                                                                                            'event_concentration_diagnostics'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/final_model_decision.csv': ('official',
                                                                                                                 'final_model_decision'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/final_model_scorecard.csv': ('official',
                                                                                                                  'final_model_scorecard'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/group_balanced_overall_combined.csv': ('official',
                                                                                                                            'group_balanced_overall_combined'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/group_balanced_overall_gender.csv': ('official',
                                                                                                                          'group_balanced_overall_gender'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/group_balanced_points_combined.csv': ('official',
                                                                                                                           'group_balanced_points_combined'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/group_balanced_points_gender.csv': ('official',
                                                                                                                         'group_balanced_points_gender'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/group_budget_audit.csv': ('official',
                                                                                                               'group_budget_audit'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/model_rank_comparison_school.csv': ('official',
                                                                                                                         'model_rank_comparison_school'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/model_rank_comparison_summary.csv': ('official',
                                                                                                                          'model_rank_comparison_summary'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/model_registry.csv': ('official',
                                                                                                           'model_registry'),
 'data/processed/milestone6/final_development_rankings_v1/phase_6g_final_publication/roster_size_dependence.csv': ('official',
                                                                                                                   'roster_size_dependence'),
 'data/processed/milestone6/seasonal_development_rankings_v1/phase_6a_seasonal_rankings/season_combined_gender_event_rankings.csv': ('average_seasonal_broad',
                                                                                                                                     'season_combined_gender_event_rankings'),
 'data/processed/milestone6/seasonal_development_rankings_v1/phase_6a_seasonal_rankings/season_combined_gender_group_rankings.csv': ('average_seasonal_broad',
                                                                                                                                     'season_combined_gender_group_rankings'),
 'data/processed/milestone6/seasonal_development_rankings_v1/phase_6a_seasonal_rankings/season_coverage_summary.csv': ('average_seasonal_broad',
                                                                                                                       'season_coverage_summary'),
 'data/processed/milestone6/seasonal_development_rankings_v1/phase_6a_seasonal_rankings/season_event_group_rankings.csv': ('average_seasonal_broad',
                                                                                                                           'season_event_group_rankings'),
 'data/processed/milestone6/seasonal_development_rankings_v1/phase_6a_seasonal_rankings/season_gender_rankings.csv': ('average_seasonal_broad',
                                                                                                                      'season_gender_rankings'),
 'data/processed/milestone6/seasonal_development_rankings_v1/phase_6a_seasonal_rankings/season_individual_event_rankings.csv': ('average_seasonal_broad',
                                                                                                                                'season_individual_event_rankings'),
 'data/processed/milestone6/seasonal_development_rankings_v1/phase_6a_seasonal_rankings/season_overall_rankings.csv': ('average_seasonal_broad',
                                                                                                                       'season_overall_rankings'),
 'data/processed/milestone6/seasonal_development_rankings_v1/phase_6a_seasonal_rankings/season_partition_summary.csv': ('average_seasonal_broad',
                                                                                                                        'season_partition_summary'),
 'data/processed/milestone6/seasonal_elite_development_v1/phase_6b_seasonal_elite_rankings/elite_partition_summary.csv': ('average_seasonal_elite',
                                                                                                                          'elite_partition_summary'),
 'data/processed/milestone6/seasonal_elite_development_v1/phase_6b_seasonal_elite_rankings/elite_season_coverage.csv': ('average_seasonal_elite',
                                                                                                                        'elite_season_coverage'),
 'data/processed/milestone6/seasonal_elite_development_v1/phase_6b_seasonal_elite_rankings/elite_season_event_combined_rankings.csv': ('average_seasonal_elite',
                                                                                                                                       'elite_season_event_combined_rankings'),
 'data/processed/milestone6/seasonal_elite_development_v1/phase_6b_seasonal_elite_rankings/elite_season_event_gender_rankings.csv': ('average_seasonal_elite',
                                                                                                                                     'elite_season_event_gender_rankings'),
 'data/processed/milestone6/seasonal_elite_development_v1/phase_6b_seasonal_elite_rankings/elite_season_gender_rankings.csv': ('average_seasonal_elite',
                                                                                                                               'elite_season_gender_rankings'),
 'data/processed/milestone6/seasonal_elite_development_v1/phase_6b_seasonal_elite_rankings/elite_season_group_combined_rankings.csv': ('average_seasonal_elite',
                                                                                                                                       'elite_season_group_combined_rankings'),
 'data/processed/milestone6/seasonal_elite_development_v1/phase_6b_seasonal_elite_rankings/elite_season_group_gender_rankings.csv': ('average_seasonal_elite',
                                                                                                                                     'elite_season_group_gender_rankings'),
 'data/processed/milestone6/seasonal_elite_development_v1/phase_6b_seasonal_elite_rankings/elite_season_overall_rankings.csv': ('average_seasonal_elite',
                                                                                                                                'elite_season_overall_rankings')}

TREND_RESOURCE_TABLES: Final = {'explorer_event_season_series': ('trends', 'explorer_event_season_series'),
 'explorer_event_window_series': ('trends', 'explorer_event_window_series'),
 'explorer_event_yoy_series': ('trends', 'explorer_event_yoy_series'),
 'explorer_group_season_series': ('trends', 'explorer_group_season_series'),
 'explorer_group_window_series': ('trends', 'explorer_group_window_series'),
 'explorer_group_yoy_series': ('trends', 'explorer_group_yoy_series'),
 'explorer_indoor_outdoor_series': ('trends', 'explorer_indoor_outdoor_series'),
 'explorer_latest_program_summary': ('trends', 'explorer_latest_program_summary'),
 'explorer_overall_season_series': ('trends', 'explorer_overall_season_series'),
 'explorer_overall_window_series': ('trends', 'explorer_overall_window_series'),
 'explorer_overall_yoy_series': ('trends', 'explorer_overall_yoy_series'),
 'explorer_program_index': ('trends', 'explorer_program_index'),
 'explorer_program_metric_long': ('trends', 'explorer_program_metric_long'),
 'explorer_program_summary': ('trends', 'explorer_program_summary')}

SPECIALIZED_RESOURCE_TABLES: Final = {'balanced_program_rankings': ('specialized', 'balanced_program_rankings'),
 'baseline_tier_rankings': ('specialized', 'baseline_tier_rankings'),
 'breakout_rate_rankings': ('specialized', 'breakout_rate_rankings'),
 'broad_athlete_points': ('specialized', 'broad_athlete_points'),
 'broad_group_gender': ('specialized', 'broad_group_gender'),
 'broad_overall': ('specialized', 'broad_overall'),
 'development_consistency_rankings': ('specialized',
                                      'development_consistency_rankings'),
 'development_efficiency_rankings': ('specialized', 'development_efficiency_rankings'),
 'elite_frontier_development_rankings': ('specialized',
                                         'elite_frontier_development_rankings'),
 'frontier_elite_overall': ('specialized', 'frontier_elite_overall'),
 'hard_checks': ('specialized', 'hard_checks'),
 'inbound_transfer_development_rankings': ('specialized',
                                           'inbound_transfer_development_rankings'),
 'national_elite_endpoint90_rankings': ('specialized',
                                        'national_elite_endpoint90_rankings'),
 'national_elite_overall': ('specialized', 'national_elite_overall'),
 'publication_table_registry': ('specialized', 'publication_table_registry'),
 'ranking_robustness_rankings': ('specialized', 'ranking_robustness_rankings'),
 'school_metadata': ('specialized', 'school_metadata'),
 'specialized_analysis_registry': ('specialized', 'specialized_analysis_registry'),
 'specialized_ranking_leaders': ('specialized', 'specialized_ranking_leaders'),
 'transfer_inference_registry': ('specialized', 'transfer_inference_registry')}

ALLOWED_SCHEMAS: Final = frozenset(
    {
        "average",
        "average_supplemental",
        "average_seasonal_broad",
        "average_seasonal_elite",
        "official",
        "trends",
        "specialized",
        "deployment_meta",
    }
)


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest."""

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def quote_identifier(value: str) -> str:
    """Quote a DuckDB identifier."""

    return '"' + value.replace('"', '""') + '"'


def _configured_database_path() -> Path:
    """Resolve the preferred local database path."""

    configured = os.environ.get(
        "NCAA_TRACK_PUBLIC_DB",
        "",
    ).strip()

    if configured:
        return Path(configured).expanduser().resolve()

    if DEFAULT_PUBLIC_DATABASE_PATH.is_file():
        return DEFAULT_PUBLIC_DATABASE_PATH

    cache_root = Path(
        os.environ.get(
            "NCAA_TRACK_PUBLIC_CACHE_DIR",
            str(DEFAULT_CACHE_DIRECTORY),
        )
    ).expanduser()

    return cache_root / DATABASE_FILENAME


def _verify_database(path: Path) -> None:
    """Verify the database artifact against the publication hash."""

    expected = os.environ.get(
        "NCAA_TRACK_PUBLIC_DB_SHA256",
        EXPECTED_DATABASE_SHA256,
    ).strip()

    if not expected:
        return

    observed = sha256_file(path)

    if observed != expected:
        raise RuntimeError(
            "Compact publication checksum mismatch. "
            f"Expected {expected}, observed {observed}."
        )


def _download_database(destination: Path) -> None:
    """Download a database or gzip publication atomically."""

    url = os.environ.get(
        "NCAA_TRACK_PUBLIC_DB_URL",
        "",
    ).strip()

    if not url:
        raise FileNotFoundError(
            "Compact publication database not found. Set "
            "NCAA_TRACK_PUBLIC_DB to a local database path or "
            "NCAA_TRACK_PUBLIC_DB_URL to a published .duckdb or "
            ".duckdb.gz artifact."
        )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=DATABASE_FILENAME + ".",
        suffix=".download",
        dir=str(destination.parent),
    )
    os.close(file_descriptor)

    temporary_download = Path(temporary_name)
    temporary_database = Path(
        str(temporary_download) + ".duckdb"
    )

    try:
        with urlopen(url, timeout=180) as response:
            with temporary_download.open("wb") as handle:
                shutil.copyfileobj(
                    response,
                    handle,
                    length=8 * 1024 * 1024,
                )

        with temporary_download.open("rb") as handle:
            gzip_magic = handle.read(2)

        is_gzip = (
            url.lower().split("?", 1)[0].endswith(".gz")
            or gzip_magic == b"\x1f\x8b"
        )

        if is_gzip:
            expected_gzip = os.environ.get(
                "NCAA_TRACK_PUBLIC_GZIP_SHA256",
                EXPECTED_GZIP_SHA256,
            ).strip()

            if expected_gzip:
                observed_gzip = sha256_file(
                    temporary_download
                )

                if observed_gzip != expected_gzip:
                    raise RuntimeError(
                        "Downloaded gzip checksum mismatch. "
                        f"Expected {expected_gzip}, "
                        f"observed {observed_gzip}."
                    )

            with gzip.open(
                temporary_download,
                "rb",
            ) as source:
                with temporary_database.open("wb") as target:
                    shutil.copyfileobj(
                        source,
                        target,
                        length=8 * 1024 * 1024,
                    )
        else:
            temporary_download.replace(
                temporary_database
            )

        _verify_database(temporary_database)
        os.replace(
            temporary_database,
            destination,
        )
    finally:
        temporary_download.unlink(
            missing_ok=True
        )
        temporary_database.unlink(
            missing_ok=True
        )


def ensure_public_database() -> Path:
    """Return a verified local compact-publication database."""

    path = _configured_database_path()

    if not path.is_file():
        _download_database(path)

    _verify_database(path)
    return path


PUBLIC_DATABASE_PATH: Final = ensure_public_database()


def connect_public_db(
    *,
    default_schema: str | None = None,
) -> duckdb.DuckDBPyConnection:
    """Open the compact publication read-only."""

    if (
        default_schema is not None
        and default_schema not in ALLOWED_SCHEMAS
    ):
        raise ValueError(
            f"Unsupported compact-publication schema: {default_schema}"
        )

    connection = duckdb.connect(
        str(PUBLIC_DATABASE_PATH),
        read_only=True,
    )

    if default_schema is not None:
        connection.execute(
            "SET search_path = " + repr(default_schema)
        )

    return connection


def _source_key(path: str | Path) -> str:
    """Normalize a historical CSV path to its publication key."""

    candidate = Path(path)

    if not candidate.is_absolute():
        candidate = ROOT / candidate

    try:
        return candidate.resolve().relative_to(
            ROOT.resolve()
        ).as_posix()
    except ValueError:
        return candidate.as_posix()


def load_table(
    schema: str,
    table: str,
) -> pd.DataFrame:
    """Load one table from the compact publication."""

    if schema not in ALLOWED_SCHEMAS:
        raise ValueError(
            f"Unsupported compact-publication schema: {schema}"
        )

    connection = connect_public_db()

    try:
        return connection.execute(
            "SELECT * FROM "
            f"{quote_identifier(schema)}."
            f"{quote_identifier(table)}"
        ).fetchdf()
    finally:
        connection.close()


def load_csv_resource(
    path: str | Path,
) -> pd.DataFrame:
    """Load the compact table replacing one historical CSV."""

    key = _source_key(path)

    try:
        schema, table = CSV_RESOURCE_TABLES[key]
    except KeyError as error:
        raise KeyError(
            "No compact-publication mapping for historical CSV: "
            f"{key}"
        ) from error

    return load_table(schema, table)
