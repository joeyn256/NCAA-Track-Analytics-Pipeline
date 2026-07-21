from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import duckdb


HISTORICAL_RELEASE_TAG = "public-deployment-v1"
HISTORICAL_RELEASE_COMMIT = (
    "ee97cefe9db382468a231eff03299f5a3342a504"
)
RESERVED_FINAL_TAG = "v1.0.0"
SEMVER_PATTERN = re.compile(
    r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)
MAX_TRACKED_BYTES = 10 * 1024 * 1024
APP_PATH = Path("src/apps/seasonal_development_explorer.py")
APPLICATION_URL = (
    "https://ncaa-d1-track-analytics-pipeline-explorer.streamlit.app/"
)
REPOSITORY_SLUG = "joeyn256/NCAA-Track-Analytics-Pipeline"

FORBIDDEN_NAMES = {".coverage", "secrets.toml"}
FORBIDDEN_SUFFIXES = {
    ".duckdb",
    ".duckdb.gz",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pyc",
}
FORBIDDEN_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}


class ReleasePreparationError(RuntimeError):
    """Raised when a release preparation gate fails."""


@dataclass(frozen=True)
class PublicationSummary:
    registry_table: str
    resource_table_count: int
    metadata_table_count: int
    deployment_row_count: int
    source_row_count: int | None
    parity_status: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_release_version(
    version: str,
    *,
    existing_tags: Iterable[str] = (),
    allow_final_v1: bool = False,
) -> str:
    if version == HISTORICAL_RELEASE_TAG:
        raise ReleasePreparationError(
            f"{HISTORICAL_RELEASE_TAG} is immutable and cannot be reused."
        )
    if not SEMVER_PATTERN.fullmatch(version):
        raise ReleasePreparationError(
            "Release version must use strict semantic-version tag form "
            "vMAJOR.MINOR.PATCH."
        )
    if version == RESERVED_FINAL_TAG and not allow_final_v1:
        raise ReleasePreparationError(
            "v1.0.0 remains reserved until every Milestone 9 gate passes."
        )
    if version in set(existing_tags):
        raise ReleasePreparationError(
            f"Release tag {version} already exists and cannot be overwritten."
        )
    return version


def _run(
    command: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def tracked_repository_files(root: Path) -> list[Path]:
    output = _run(
        ["git", "ls-files", "-z"],
        cwd=root,
    ).stdout
    return [
        root / item
        for item in output.split("\0")
        if item
    ]


def validate_tracked_files(root: Path) -> None:
    violations: list[str] = []
    for path in tracked_repository_files(root):
        relative = path.relative_to(root)
        if not path.is_file():
            continue
        if path.stat().st_size > MAX_TRACKED_BYTES:
            violations.append(
                f"oversized tracked file: {relative} "
                f"({path.stat().st_size} bytes)"
            )
            continue
        if relative.name in FORBIDDEN_NAMES:
            if relative != Path(
                "deployment/streamlit/secrets.toml.example"
            ):
                violations.append(f"forbidden tracked file: {relative}")
            continue
        if any(
            str(relative).endswith(suffix)
            for suffix in FORBIDDEN_SUFFIXES
        ):
            violations.append(f"forbidden tracked artifact: {relative}")
            continue
        if FORBIDDEN_PARTS.intersection(relative.parts):
            violations.append(f"tracked cache path: {relative}")

    if violations:
        raise ReleasePreparationError("\n".join(violations))


def validate_repository_state(root: Path) -> str:
    branch = _run(
        ["git", "branch", "--show-current"],
        cwd=root,
    ).stdout.strip()
    if branch != "main":
        raise ReleasePreparationError("Release preparation requires main.")

    status = _run(
        ["git", "status", "--porcelain"],
        cwd=root,
    ).stdout.strip()
    if status:
        raise ReleasePreparationError(
            "Working tree must be clean before release preparation."
        )

    local_target = _run(
        ["git", "rev-parse", f"{HISTORICAL_RELEASE_TAG}^{{}}"],
        cwd=root,
    ).stdout.strip()
    if local_target != HISTORICAL_RELEASE_COMMIT:
        raise ReleasePreparationError(
            "The immutable public-deployment-v1 tag moved locally."
        )

    validate_tracked_files(root)

    return _run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
    ).stdout.strip()


def _local_and_remote_tags(root: Path) -> set[str]:
    local = {
        line.strip()
        for line in _run(
            ["git", "tag", "--list"],
            cwd=root,
        ).stdout.splitlines()
        if line.strip()
    }

    remote_result = _run(
        ["git", "ls-remote", "--tags", "origin"],
        cwd=root,
    )
    remote: set[str] = set()
    historical_target: str | None = None
    for line in remote_result.stdout.splitlines():
        commit, reference = line.split("\t", 1)
        tag = reference.removeprefix("refs/tags/")
        if tag.endswith("^{}"):
            peeled = tag[:-3]
            remote.add(peeled)
            if peeled == HISTORICAL_RELEASE_TAG:
                historical_target = commit
        else:
            remote.add(tag)

    if historical_target != HISTORICAL_RELEASE_COMMIT:
        raise ReleasePreparationError(
            "The immutable public-deployment-v1 tag moved remotely."
        )

    return local | remote


def _github_release_exists(root: Path, version: str) -> bool:
    if shutil.which("gh") is None:
        raise ReleasePreparationError(
            "GitHub CLI is required for remote release checks."
        )
    auth = _run(
        ["gh", "auth", "status"],
        cwd=root,
        check=False,
    )
    if auth.returncode != 0:
        raise ReleasePreparationError(
            "GitHub CLI authentication is required for remote checks."
        )
    result = _run(
        ["gh", "release", "view", version],
        cwd=root,
        check=False,
    )
    return result.returncode == 0


def _table_columns(
    connection: duckdb.DuckDBPyConnection,
    table: str,
) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'deployment_meta'
              AND table_name = ?
            ORDER BY ordinal_position
            """,
            [table],
        ).fetchall()
    ]


def _first_present(
    columns: set[str],
    candidates: tuple[str, ...],
) -> str | None:
    return next(
        (candidate for candidate in candidates if candidate in columns),
        None,
    )


def inspect_publication(database_path: Path) -> PublicationSummary:
    connection = duckdb.connect(
        str(database_path),
        read_only=True,
    )
    try:
        metadata_tables = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'deployment_meta'
                ORDER BY table_name
                """
            ).fetchall()
        ]
        if not metadata_tables:
            raise ReleasePreparationError(
                "No deployment_meta tables were found."
            )

        registry_table: str | None = None
        registry_columns: list[str] = []
        schema_column: str | None = None
        table_column: str | None = None
        for table in metadata_tables:
            columns = _table_columns(connection, table)
            column_set = set(columns)
            candidate_schema = _first_present(
                column_set,
                (
                    "destination_schema",
                    "deployment_schema",
                    "target_schema",
                    "schema_name",
                ),
            )
            candidate_table = _first_present(
                column_set,
                (
                    "destination_table",
                    "deployment_table",
                    "target_table",
                    "table_name",
                ),
            )
            if candidate_schema and candidate_table:
                registry_table = table
                registry_columns = columns
                schema_column = candidate_schema
                table_column = candidate_table
                break

        if (
            registry_table is None
            or schema_column is None
            or table_column is None
        ):
            raise ReleasePreparationError(
                "No deployment resource registry was found."
            )

        column_set = set(registry_columns)
        deployment_count_column = _first_present(
            column_set,
            (
                "deployment_row_count",
                "target_row_count",
                "observed_row_count",
            ),
        )
        source_count_column = _first_present(
            column_set,
            (
                "source_row_count",
                "expected_row_count",
                "row_count",
            ),
        )
        status_column = _first_present(
            column_set,
            (
                "validation_status",
                "parity_status",
                "check_status",
                "status",
            ),
        )

        selected = [
            schema_column,
            table_column,
        ]
        for optional in (
            source_count_column,
            deployment_count_column,
            status_column,
        ):
            if optional and optional not in selected:
                selected.append(optional)

        quoted = ", ".join(f'"{column}"' for column in selected)
        rows = connection.execute(
            f'SELECT {quoted} FROM '
            f'deployment_meta."{registry_table}" '
            f'ORDER BY "{schema_column}", "{table_column}"'
        ).fetchall()

        if not rows:
            raise ReleasePreparationError(
                "The deployment resource registry is empty."
            )

        index = {
            column: position
            for position, column in enumerate(selected)
        }
        total_live = 0
        total_source = 0
        source_available = source_count_column is not None

        for row in rows:
            schema = str(row[index[schema_column]])
            table = str(row[index[table_column]])
            observed = int(
                connection.execute(
                    f'SELECT COUNT(*) FROM '
                    f'"{schema.replace(chr(34), chr(34) * 2)}".'
                    f'"{table.replace(chr(34), chr(34) * 2)}"'
                ).fetchone()[0]
            )
            total_live += observed

            if deployment_count_column:
                expected = int(
                    row[index[deployment_count_column]]
                )
                if observed != expected:
                    raise ReleasePreparationError(
                        f"Row parity failed for {schema}.{table}: "
                        f"expected {expected}, observed {observed}."
                    )

            if source_count_column:
                total_source += int(row[index[source_count_column]])

            if status_column:
                status = str(row[index[status_column]]).upper()
                if status != "PASS":
                    raise ReleasePreparationError(
                        f"Registry status for {schema}.{table} "
                        f"is {status}, not PASS."
                    )

        if source_available and total_source != total_live:
            raise ReleasePreparationError(
                "Source-to-deployment row parity failed: "
                f"{total_source} source rows versus "
                f"{total_live} deployment rows."
            )

        return PublicationSummary(
            registry_table=registry_table,
            resource_table_count=len(rows),
            metadata_table_count=len(metadata_tables),
            deployment_row_count=total_live,
            source_row_count=(
                total_source if source_available else None
            ),
            parity_status="PASS",
        )
    finally:
        connection.close()


def _decompress_database(
    artifact_path: Path,
    destination: Path,
) -> Path:
    if artifact_path.suffix == ".gz":
        with gzip.open(artifact_path, "rb") as source:
            with destination.open("wb") as target:
                shutil.copyfileobj(
                    source,
                    target,
                    length=8 * 1024 * 1024,
                )
        return destination

    shutil.copy2(artifact_path, destination)
    return destination


def verify_app_with_database(
    root: Path,
    database_path: Path,
    database_sha256: str,
) -> None:
    from streamlit.testing.v1 import AppTest

    environment = {
        "NCAA_TRACK_PUBLIC_DB": str(database_path),
        "NCAA_TRACK_PUBLIC_DB_URL": "",
        "NCAA_TRACK_PUBLIC_DB_SHA256": database_sha256,
        "NCAA_TRACK_PUBLIC_GZIP_SHA256": "",
        "NCAA_TRACK_PUBLIC_CACHE_DIR": str(
            database_path.parent / "app-cache"
        ),
    }
    previous = {
        key: os.environ.get(key)
        for key in environment
    }
    try:
        os.environ.update(environment)
        for name in (
            "src.apps.seasonal_development_explorer",
            "src.apps.deployment_data",
            "deployment_data",
        ):
            sys.modules.pop(name, None)

        app = AppTest.from_file(
            str(root / APP_PATH),
            default_timeout=45,
        ).run()
        if app.exception:
            raise ReleasePreparationError(
                "The explorer failed against the exact release artifact: "
                + "; ".join(str(item.value) for item in app.exception)
            )
        if not app.title:
            raise ReleasePreparationError(
                "The explorer rendered no title against the release artifact."
            )
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def build_descriptor(
    *,
    version: str,
    artifact_path: Path,
    artifact_sha256: str,
    artifact_size: int,
    database_sha256: str,
    database_size: int,
    source_commit: str,
    summary: PublicationSummary,
    app_verified: bool,
) -> dict[str, object]:
    filename = artifact_path.name
    release_page = (
        f"https://github.com/{REPOSITORY_SLUG}/releases/tag/{version}"
    )
    asset_url = (
        f"https://github.com/{REPOSITORY_SLUG}/releases/download/"
        f"{version}/{filename}"
    )
    return {
        "application": {
            "entrypoint": str(APP_PATH),
            "public_url": APPLICATION_URL,
            "verified_against_exact_artifact": app_verified,
        },
        "artifact": {
            "database_sha256": database_sha256,
            "database_size_bytes": database_size,
            "filename": filename,
            "sha256": artifact_sha256,
            "size_bytes": artifact_size,
        },
        "git": {
            "source_commit": source_commit,
        },
        "github": {
            "release_asset_url": asset_url,
            "release_page": release_page,
            "release_tag": version,
            "repository": REPOSITORY_SLUG,
        },
        "publication": {
            "deployment_row_count": summary.deployment_row_count,
            "metadata_table_count": summary.metadata_table_count,
            "parity_status": summary.parity_status,
            "registry_table": summary.registry_table,
            "resource_table_count": summary.resource_table_count,
            "source_row_count": summary.source_row_count,
        },
        "release_version": version,
    }


def render_release_notes(
    descriptor: dict[str, object],
) -> str:
    artifact = descriptor["artifact"]
    github = descriptor["github"]
    publication = descriptor["publication"]
    git = descriptor["git"]
    app_status = (
        "PASS"
        if descriptor["application"][
            "verified_against_exact_artifact"
        ]
        else "NOT RUN"
    )
    return (
        f"# NCAA Track Explorer {descriptor['release_version']}\n\n"
        "## Immutable artifact\n\n"
        f"- Asset: `{artifact['filename']}`\n"
        f"- Compressed bytes: {artifact['size_bytes']:,}\n"
        f"- Database bytes: {artifact['database_size_bytes']:,}\n"
        f"- Compressed SHA-256: `{artifact['sha256']}`\n"
        f"- Database SHA-256: `{artifact['database_sha256']}`\n"
        f"- Source commit: `{git['source_commit']}`\n\n"
        "## Publication validation\n\n"
        f"- Resource tables: {publication['resource_table_count']}\n"
        f"- Metadata tables: {publication['metadata_table_count']}\n"
        "- Source rows: "
        + (
            f"{publication['source_row_count']:,}\n"
            if publication["source_row_count"] is not None
            else "unavailable\n"
        )
        + f"- Deployment rows: "
        f"{publication['deployment_row_count']:,}\n"
        f"- Source-to-deployment parity: "
        f"{publication['parity_status']}\n"
        f"- Explorer startup against this exact artifact: {app_status}\n\n"
        "## Release links\n\n"
        f"- Release page: {github['release_page']}\n"
        f"- Release asset: {github['release_asset_url']}\n"
        f"- Public explorer: {APPLICATION_URL}\n"
    )


def write_release_package(
    output_dir: Path,
    descriptor: dict[str, object],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    descriptor_path = output_dir / "release_descriptor.json"
    notes_path = output_dir / "release_notes.md"
    if descriptor_path.exists() or notes_path.exists():
        raise ReleasePreparationError(
            "Release package output already exists; use a new directory."
        )

    descriptor_path.write_text(
        json.dumps(
            descriptor,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    notes_path.write_text(render_release_notes(descriptor))
    return descriptor_path, notes_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a deterministic, immutable future public release "
            "without creating a tag or GitHub release."
        )
    )
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--artifact",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--verify-app",
        action="store_true",
    )
    parser.add_argument(
        "--allow-final-v1",
        action="store_true",
    )
    parser.add_argument(
        "--skip-remote-checks",
        action="store_true",
    )
    parser.add_argument(
        "--skip-repository-checks",
        action="store_true",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(
        _run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path.cwd(),
        ).stdout.strip()
    )
    artifact = args.artifact.expanduser().resolve()
    if not artifact.is_file():
        raise ReleasePreparationError(
            f"Release artifact not found: {artifact}"
        )

    source_commit = (
        _run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
        ).stdout.strip()
        if args.skip_repository_checks
        else validate_repository_state(root)
    )

    existing_tags: set[str] = set()
    if not args.skip_remote_checks:
        existing_tags = _local_and_remote_tags(root)

    version = validate_release_version(
        args.version,
        existing_tags=existing_tags,
        allow_final_v1=args.allow_final_v1,
    )

    if (
        not args.skip_remote_checks
        and _github_release_exists(root, version)
    ):
        raise ReleasePreparationError(
            f"GitHub release {version} already exists."
        )

    artifact_sha256 = sha256_file(artifact)
    artifact_size = artifact.stat().st_size

    with tempfile.TemporaryDirectory(
        prefix="ncaa-track-release-"
    ) as temporary:
        database = Path(temporary) / artifact.name.removesuffix(".gz")
        _decompress_database(artifact, database)
        database_sha256 = sha256_file(database)
        database_size = database.stat().st_size
        summary = inspect_publication(database)

        if args.verify_app:
            verify_app_with_database(
                root,
                database,
                database_sha256,
            )

        descriptor = build_descriptor(
            version=version,
            artifact_path=artifact,
            artifact_sha256=artifact_sha256,
            artifact_size=artifact_size,
            database_sha256=database_sha256,
            database_size=database_size,
            source_commit=source_commit,
            summary=summary,
            app_verified=args.verify_app,
        )

    descriptor_path, notes_path = write_release_package(
        args.output_dir.expanduser().resolve(),
        descriptor,
    )

    print("PASS — future release package prepared without publishing.")
    print(f"Version:           {version}")
    print(f"Artifact SHA-256:  {artifact_sha256}")
    print(f"Database SHA-256:  {database_sha256}")
    print(
        "Resource parity:   "
        f"{summary.resource_table_count} tables, "
        f"{summary.deployment_row_count} rows, PASS"
    )
    print(f"Descriptor:        {descriptor_path}")
    print(f"Release notes:     {notes_path}")
    print("No tag or GitHub Release was created.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReleasePreparationError as error:
        print(f"ERROR — {error}", file=sys.stderr)
        raise SystemExit(1) from error
