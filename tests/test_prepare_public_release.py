from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path

import duckdb
import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts/prepare_public_release.py"
)
SPEC = importlib.util.spec_from_file_location(
    "prepare_public_release",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)


def build_publication(path: Path, *, mismatch: bool = False) -> Path:
    connection = duckdb.connect(str(path))
    try:
        connection.execute("CREATE SCHEMA official")
        connection.execute("CREATE SCHEMA trends")
        connection.execute("CREATE SCHEMA deployment_meta")
        connection.execute(
            "CREATE TABLE official.rankings AS "
            "SELECT * FROM (VALUES (1), (2)) AS rows(value)"
        )
        connection.execute(
            "CREATE TABLE trends.series AS "
            "SELECT * FROM (VALUES (10), (20), (30)) AS rows(value)"
        )
        connection.execute(
            """
            CREATE TABLE deployment_meta.resource_registry (
                destination_schema VARCHAR,
                destination_table VARCHAR,
                source_row_count BIGINT,
                deployment_row_count BIGINT,
                deployment_column_count BIGINT,
                row_count_difference BIGINT,
                validation_status VARCHAR
            )
            """
        )
        expected_second = 4 if mismatch else 3
        status_second = "FAIL" if mismatch else "PASS"
        connection.execute(
            """
            INSERT INTO deployment_meta.resource_registry
            VALUES
                ('official', 'rankings', 2, 2, 1, 0, 'PASS'),
                ('trends', 'series', ?, ?, 1, ?, ?)
            """,
            [
                expected_second,
                expected_second,
                expected_second - 3,
                status_second,
            ],
        )
    finally:
        connection.close()
    return path


def gzip_file(source: Path, destination: Path) -> Path:
    with source.open("rb") as input_handle:
        with destination.open("wb") as raw_output:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw_output,
                mtime=0,
            ) as output_handle:
                output_handle.write(input_handle.read())
    return destination


def test_validate_release_version_accepts_new_semver() -> None:
    assert release.validate_release_version("v1.2.3") == "v1.2.3"


@pytest.mark.parametrize(
    "value",
    [
        "1.2.3",
        "v1.2",
        "v01.2.3",
        "public-deployment-v1",
    ],
)
def test_validate_release_version_rejects_invalid_values(
    value: str,
) -> None:
    with pytest.raises(release.ReleasePreparationError):
        release.validate_release_version(value)


def test_validate_release_version_reserves_v1_0_0() -> None:
    with pytest.raises(release.ReleasePreparationError):
        release.validate_release_version("v1.0.0")

    assert release.validate_release_version(
        "v1.0.0",
        allow_final_v1=True,
    ) == "v1.0.0"


def test_validate_release_version_rejects_existing_tag() -> None:
    with pytest.raises(release.ReleasePreparationError):
        release.validate_release_version(
            "v1.2.3",
            existing_tags={"v1.2.3"},
        )


def test_sha256_file(tmp_path: Path) -> None:
    path = tmp_path / "value.bin"
    path.write_bytes(b"release-contract")
    assert release.sha256_file(path) == (
        "88d94e02c334d242f29aca2985e9934d6ef825924c2e2c6ee"
        "3b8d49c91741682"
    )


def test_inspect_publication_validates_live_parity(
    tmp_path: Path,
) -> None:
    database = build_publication(tmp_path / "publication.duckdb")
    summary = release.inspect_publication(database)

    assert summary.registry_table == "resource_registry"
    assert summary.resource_table_count == 2
    assert summary.metadata_table_count == 1
    assert summary.source_row_count == 5
    assert summary.deployment_row_count == 5
    assert summary.parity_status == "PASS"


def test_inspect_publication_rejects_failed_parity(
    tmp_path: Path,
) -> None:
    database = build_publication(
        tmp_path / "bad.duckdb",
        mismatch=True,
    )
    with pytest.raises(release.ReleasePreparationError):
        release.inspect_publication(database)


def test_release_package_is_reproducible(tmp_path: Path) -> None:
    database = build_publication(tmp_path / "publication.duckdb")
    artifact = gzip_file(
        database,
        tmp_path / "publication.duckdb.gz",
    )
    summary = release.inspect_publication(database)

    descriptor = release.build_descriptor(
        version="v1.2.3",
        artifact_path=artifact,
        artifact_sha256=release.sha256_file(artifact),
        artifact_size=artifact.stat().st_size,
        database_sha256=release.sha256_file(database),
        database_size=database.stat().st_size,
        source_commit="a" * 40,
        summary=summary,
        app_verified=True,
    )

    first_descriptor, first_notes = release.write_release_package(
        tmp_path / "first",
        descriptor,
    )
    second_descriptor, second_notes = release.write_release_package(
        tmp_path / "second",
        descriptor,
    )

    assert first_descriptor.read_bytes() == second_descriptor.read_bytes()
    assert first_notes.read_bytes() == second_notes.read_bytes()

    payload = json.loads(first_descriptor.read_text())
    assert payload["release_version"] == "v1.2.3"
    assert payload["publication"]["parity_status"] == "PASS"
    assert "Explorer startup against this exact artifact: PASS" in (
        first_notes.read_text()
    )


def test_release_package_does_not_overwrite(
    tmp_path: Path,
) -> None:
    summary = release.PublicationSummary(
        registry_table="resource_registry",
        resource_table_count=1,
        metadata_table_count=1,
        deployment_row_count=2,
        source_row_count=2,
        parity_status="PASS",
    )
    descriptor = release.build_descriptor(
        version="v1.2.3",
        artifact_path=tmp_path / "artifact.duckdb.gz",
        artifact_sha256="a" * 64,
        artifact_size=1,
        database_sha256="b" * 64,
        database_size=2,
        source_commit="c" * 40,
        summary=summary,
        app_verified=True,
    )
    release.write_release_package(tmp_path / "output", descriptor)

    with pytest.raises(release.ReleasePreparationError):
        release.write_release_package(
            tmp_path / "output",
            descriptor,
        )


def test_versioned_publish_script_has_immutable_guards() -> None:
    publish_script = (
        Path(__file__).resolve().parents[1]
        / "deployment/github/publish_versioned_release.sh"
    ).read_text()

    required = (
        "public-deployment-v1",
        "ALLOW_FINAL_V1_RELEASE",
        "gh release view",
        "git ls-remote",
        "--publish",
        "release_descriptor.json",
    )
    for value in required:
        assert value in publish_script
