from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest


MODULE_NAME = "src.apps.deployment_data"


def build_fixture_database(path: Path) -> Path:
    connection = duckdb.connect(str(path))

    try:
        connection.execute("CREATE SCHEMA official")
        connection.execute("CREATE SCHEMA average")
        connection.execute("CREATE SCHEMA deployment_meta")

        connection.execute(
            """
            CREATE TABLE official.event_balanced_overall_combined (
                school_name VARCHAR,
                total_event_balanced_points DOUBLE,
                event_balanced_rank BIGINT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO official.event_balanced_overall_combined
            VALUES
                ('Example University', 12345.5, 1),
                ('Sample State', 9876.0, 2)
            """
        )

        connection.execute(
            """
            CREATE TABLE average.all_school_rankings (
                school_name VARCHAR,
                posterior_mean DOUBLE,
                rank BIGINT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO average.all_school_rankings
            VALUES
                ('Example University', 1.25, 1)
            """
        )

        connection.execute(
            """
            CREATE TABLE deployment_meta.publication_registry (
                publication_version VARCHAR,
                official_model VARCHAR,
                resource_table_count BIGINT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO deployment_meta.publication_registry
            VALUES (
                'synthetic-test-v1',
                'Enhanced Balanced Production',
                81
            )
            """
        )
    finally:
        connection.close()

    return path


def import_loader(
    monkeypatch: pytest.MonkeyPatch,
    database_path: Path,
    *,
    expected_sha256: str = "",
):
    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_DB",
        str(database_path),
    )
    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_DB_URL",
        "",
    )
    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_CACHE_DIR",
        str(database_path.parent / "cache"),
    )
    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_DB_SHA256",
        expected_sha256,
    )
    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_GZIP_SHA256",
        "",
    )

    sys.modules.pop(MODULE_NAME, None)

    return importlib.import_module(MODULE_NAME)


def test_sha256_file(tmp_path: Path) -> None:
    file_path = tmp_path / "example.bin"
    content = b"ncaa-track-analytics"
    file_path.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()

    from src.apps import deployment_data

    assert deployment_data.sha256_file(file_path) == expected


def test_quote_identifier_escapes_double_quotes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = build_fixture_database(tmp_path / "fixture.duckdb")
    loader = import_loader(monkeypatch, database)

    assert loader.quote_identifier("official") == '"official"'
    assert loader.quote_identifier('a"b') == '"a""b"'


def test_configured_database_path_uses_environment_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = build_fixture_database(tmp_path / "fixture.duckdb")
    loader = import_loader(monkeypatch, database)

    assert loader._configured_database_path() == database.resolve()


def test_import_accepts_matching_checksum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = build_fixture_database(tmp_path / "fixture.duckdb")
    expected = hashlib.sha256(database.read_bytes()).hexdigest()

    loader = import_loader(
        monkeypatch,
        database,
        expected_sha256=expected,
    )

    assert loader.PUBLIC_DATABASE_PATH == database.resolve()


def test_import_rejects_checksum_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = build_fixture_database(tmp_path / "fixture.duckdb")

    with pytest.raises(
        RuntimeError,
        match="Compact publication checksum mismatch",
    ):
        import_loader(
            monkeypatch,
            database,
            expected_sha256="0" * 64,
        )


def test_missing_database_without_url_raises_file_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_database = tmp_path / "missing.duckdb"

    with pytest.raises(
        FileNotFoundError,
        match="Compact publication database not found",
    ):
        import_loader(
            monkeypatch,
            missing_database,
        )

    assert not missing_database.exists()
    assert not (tmp_path / "cache").exists()


def test_connect_public_db_is_read_only_and_schema_aware(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = build_fixture_database(tmp_path / "fixture.duckdb")
    loader = import_loader(monkeypatch, database)

    connection = loader.connect_public_db(default_schema="official")

    try:
        assert (
            connection.execute(
                "SELECT current_schema()"
            ).fetchone()[0]
            == "official"
        )

        with pytest.raises(duckdb.InvalidInputException):
            connection.execute(
                "CREATE TABLE forbidden_write(value INTEGER)"
            )
    finally:
        connection.close()


def test_connect_public_db_rejects_unsupported_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = build_fixture_database(tmp_path / "fixture.duckdb")
    loader = import_loader(monkeypatch, database)

    with pytest.raises(
        ValueError,
        match="Unsupported compact-publication schema",
    ):
        loader.connect_public_db(default_schema="private")


def test_load_table_returns_dataframe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = build_fixture_database(tmp_path / "fixture.duckdb")
    loader = import_loader(monkeypatch, database)

    frame = loader.load_table(
        "official",
        "event_balanced_overall_combined",
    )

    assert isinstance(frame, pd.DataFrame)
    assert frame.shape == (2, 3)
    assert frame["school_name"].tolist() == [
        "Example University",
        "Sample State",
    ]
    assert frame["event_balanced_rank"].tolist() == [1, 2]


def test_load_table_rejects_unsupported_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = build_fixture_database(tmp_path / "fixture.duckdb")
    loader = import_loader(monkeypatch, database)

    with pytest.raises(
        ValueError,
        match="Unsupported compact-publication schema",
    ):
        loader.load_table("private", "anything")


def test_load_csv_resource_uses_historical_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = build_fixture_database(tmp_path / "fixture.duckdb")
    loader = import_loader(monkeypatch, database)

    frame = loader.load_csv_resource(
        "data/processed/milestone5/athlete_development_v1/"
        "phase_5i_publication_freeze/all_school_rankings.csv"
    )

    assert frame.shape == (1, 3)
    assert frame.iloc[0]["school_name"] == "Example University"
    assert frame.iloc[0]["rank"] == 1


def test_load_csv_resource_rejects_unknown_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = build_fixture_database(tmp_path / "fixture.duckdb")
    loader = import_loader(monkeypatch, database)

    with pytest.raises(
        KeyError,
        match="No compact-publication mapping",
    ):
        loader.load_csv_resource(
            "data/processed/unknown/not_registered.csv"
        )


def test_mapping_counts_and_allowed_schemas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = build_fixture_database(tmp_path / "fixture.duckdb")
    loader = import_loader(monkeypatch, database)

    assert len(loader.CSV_RESOURCE_TABLES) == 47
    assert len(loader.TREND_RESOURCE_TABLES) == 14
    assert len(loader.SPECIALIZED_RESOURCE_TABLES) == 20

    assert loader.ALLOWED_SCHEMAS == frozenset(
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


def test_configured_database_path_uses_cache_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = build_fixture_database(tmp_path / "fixture.duckdb")
    loader = import_loader(monkeypatch, database)

    monkeypatch.delenv("NCAA_TRACK_PUBLIC_DB", raising=False)
    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_CACHE_DIR",
        str(tmp_path / "custom-cache"),
    )
    monkeypatch.setattr(
        loader,
        "DEFAULT_PUBLIC_DATABASE_PATH",
        tmp_path / "not-present.duckdb",
    )

    assert loader._configured_database_path() == (
        tmp_path
        / "custom-cache"
        / loader.DATABASE_FILENAME
    )


def test_download_database_accepts_direct_duckdb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_database = build_fixture_database(
        tmp_path / "source.duckdb"
    )
    source_bytes = source_database.read_bytes()
    expected_database_sha256 = hashlib.sha256(
        source_bytes
    ).hexdigest()

    destination = tmp_path / "cache" / "downloaded.duckdb"

    loader = import_loader(monkeypatch, source_database)

    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_DB_URL",
        "https://example.invalid/publication.duckdb",
    )
    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_DB_SHA256",
        expected_database_sha256,
    )

    class Response:
        def __enter__(self):
            from io import BytesIO

            self.handle = BytesIO(source_bytes)
            return self.handle

        def __exit__(self, exc_type, exc_value, traceback):
            self.handle.close()
            return False

    monkeypatch.setattr(
        loader,
        "urlopen",
        lambda url, timeout: Response(),
    )

    loader._download_database(destination)

    assert destination.read_bytes() == source_bytes
    assert loader.sha256_file(destination) == (
        expected_database_sha256
    )
    assert not list(destination.parent.glob("*.download"))
    assert not list(destination.parent.glob("*.download.duckdb"))


def test_download_database_decompresses_gzip_by_extension(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gzip
    from io import BytesIO

    source_database = build_fixture_database(
        tmp_path / "source.duckdb"
    )
    source_bytes = source_database.read_bytes()

    compressed = BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb") as handle:
        handle.write(source_bytes)

    gzip_bytes = compressed.getvalue()
    expected_database_sha256 = hashlib.sha256(
        source_bytes
    ).hexdigest()
    expected_gzip_sha256 = hashlib.sha256(
        gzip_bytes
    ).hexdigest()

    destination = tmp_path / "cache" / "downloaded.duckdb"

    loader = import_loader(monkeypatch, source_database)

    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_DB_URL",
        "https://example.invalid/publication.duckdb.gz",
    )
    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_DB_SHA256",
        expected_database_sha256,
    )
    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_GZIP_SHA256",
        expected_gzip_sha256,
    )

    class Response:
        def __enter__(self):
            self.handle = BytesIO(gzip_bytes)
            return self.handle

        def __exit__(self, exc_type, exc_value, traceback):
            self.handle.close()
            return False

    monkeypatch.setattr(
        loader,
        "urlopen",
        lambda url, timeout: Response(),
    )

    loader._download_database(destination)

    assert destination.read_bytes() == source_bytes
    assert not list(destination.parent.glob("*.download"))
    assert not list(destination.parent.glob("*.download.duckdb"))


def test_download_database_detects_gzip_magic_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gzip
    from io import BytesIO

    source_database = build_fixture_database(
        tmp_path / "source.duckdb"
    )
    source_bytes = source_database.read_bytes()

    compressed = BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb") as handle:
        handle.write(source_bytes)

    gzip_bytes = compressed.getvalue()
    expected_database_sha256 = hashlib.sha256(
        source_bytes
    ).hexdigest()

    destination = tmp_path / "cache" / "downloaded.duckdb"

    loader = import_loader(monkeypatch, source_database)

    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_DB_URL",
        "https://example.invalid/download?id=123",
    )
    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_DB_SHA256",
        expected_database_sha256,
    )
    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_GZIP_SHA256",
        "",
    )

    class Response:
        def __enter__(self):
            self.handle = BytesIO(gzip_bytes)
            return self.handle

        def __exit__(self, exc_type, exc_value, traceback):
            self.handle.close()
            return False

    monkeypatch.setattr(
        loader,
        "urlopen",
        lambda url, timeout: Response(),
    )

    loader._download_database(destination)

    assert destination.read_bytes() == source_bytes


def test_download_database_rejects_gzip_checksum_and_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gzip
    from io import BytesIO

    source_database = build_fixture_database(
        tmp_path / "source.duckdb"
    )
    source_bytes = source_database.read_bytes()

    compressed = BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb") as handle:
        handle.write(source_bytes)

    gzip_bytes = compressed.getvalue()
    destination = tmp_path / "cache" / "downloaded.duckdb"

    loader = import_loader(monkeypatch, source_database)

    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_DB_URL",
        "https://example.invalid/publication.duckdb.gz",
    )
    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_DB_SHA256",
        hashlib.sha256(source_bytes).hexdigest(),
    )
    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_GZIP_SHA256",
        "0" * 64,
    )

    class Response:
        def __enter__(self):
            self.handle = BytesIO(gzip_bytes)
            return self.handle

        def __exit__(self, exc_type, exc_value, traceback):
            self.handle.close()
            return False

    monkeypatch.setattr(
        loader,
        "urlopen",
        lambda url, timeout: Response(),
    )

    with pytest.raises(
        RuntimeError,
        match="Downloaded gzip checksum mismatch",
    ):
        loader._download_database(destination)

    assert not destination.exists()
    assert destination.parent.is_dir()
    assert not list(destination.parent.glob("*.download"))
    assert not list(destination.parent.glob("*.download.duckdb"))


def test_download_database_cleans_up_after_network_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_database = build_fixture_database(
        tmp_path / "source.duckdb"
    )
    destination = tmp_path / "cache" / "downloaded.duckdb"

    loader = import_loader(monkeypatch, source_database)

    monkeypatch.setenv(
        "NCAA_TRACK_PUBLIC_DB_URL",
        "https://example.invalid/failure.duckdb",
    )

    def fail_download(url, timeout):
        raise OSError("synthetic network failure")

    monkeypatch.setattr(
        loader,
        "urlopen",
        fail_download,
    )

    with pytest.raises(
        OSError,
        match="synthetic network failure",
    ):
        loader._download_database(destination)

    assert not destination.exists()
    assert destination.parent.is_dir()
    assert not list(destination.parent.glob("*.download"))
    assert not list(destination.parent.glob("*.download.duckdb"))


def test_source_key_preserves_external_absolute_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = build_fixture_database(tmp_path / "fixture.duckdb")
    loader = import_loader(monkeypatch, database)

    external_path = (
        tmp_path
        / "outside"
        / "external_resource.csv"
    ).resolve()

    assert loader._source_key(external_path) == (
        external_path.as_posix()
    )
