#!/usr/bin/env python3
"""Validate fresh-environment bootstrap of the compact public database."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Final


ROOT: Final = Path(__file__).resolve().parents[3]

MODULE_PATH: Final = ROOT / "src/apps/deployment_data.py"

PUBLICATION_DIR: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8b_compact_publication"
)

SOURCE_DATABASE: Final = (
    PUBLICATION_DIR / "ncaa_track_public_explorer_v1.duckdb"
)

SOURCE_GZIP: Final = Path(str(SOURCE_DATABASE) + ".gz")

MANIFEST_PATH: Final = (
    PUBLICATION_DIR / "deployment_manifest.json"
)

OUTPUT_DIR: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8c_bootstrap_validation"
)


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest."""

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def import_module(module_name: str):
    """Import deployment_data.py under a unique module name."""

    spec = importlib.util.spec_from_file_location(
        module_name,
        MODULE_PATH,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            "Could not load src/apps/deployment_data.py."
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def restore_environment(
    previous: dict[str, str | None],
) -> None:
    """Restore environment variables exactly."""

    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def main() -> None:
    """Run an isolated gzip download/decompression/bootstrap test."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for path in (
        MODULE_PATH,
        SOURCE_DATABASE,
        SOURCE_GZIP,
        MANIFEST_PATH,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)

    manifest = json.loads(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )

    expected_database_hash = str(
        manifest["database"]["sha256"]
    )
    expected_gzip_hash = str(
        manifest["gzip"]["sha256"]
    )

    source_database_hash_before = sha256_file(
        SOURCE_DATABASE
    )
    source_gzip_hash_before = sha256_file(
        SOURCE_GZIP
    )

    if source_database_hash_before != expected_database_hash:
        raise RuntimeError(
            "Source database checksum does not match manifest."
        )

    if source_gzip_hash_before != expected_gzip_hash:
        raise RuntimeError(
            "Source gzip checksum does not match manifest."
        )

    variable_names = (
        "NCAA_TRACK_PUBLIC_DB",
        "NCAA_TRACK_PUBLIC_DB_URL",
        "NCAA_TRACK_PUBLIC_DB_SHA256",
        "NCAA_TRACK_PUBLIC_GZIP_SHA256",
        "NCAA_TRACK_PUBLIC_CACHE_DIR",
    )

    previous_environment = {
        name: os.environ.get(name)
        for name in variable_names
    }

    results: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(
        prefix="ncaa_track_bootstrap_"
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        destination = (
            temporary_root
            / "cache"
            / "ncaa_track_public_explorer_v1.duckdb"
        )

        os.environ["NCAA_TRACK_PUBLIC_DB"] = str(
            destination
        )
        os.environ["NCAA_TRACK_PUBLIC_DB_URL"] = (
            SOURCE_GZIP.resolve().as_uri()
        )
        os.environ["NCAA_TRACK_PUBLIC_DB_SHA256"] = (
            expected_database_hash
        )
        os.environ[
            "NCAA_TRACK_PUBLIC_GZIP_SHA256"
        ] = expected_gzip_hash
        os.environ["NCAA_TRACK_PUBLIC_CACHE_DIR"] = str(
            temporary_root / "unused_cache"
        )

        try:
            existed_before = destination.exists()

            started = time.perf_counter()
            module = import_module(
                "deployment_data_bootstrap_validation"
            )
            bootstrap_seconds = (
                time.perf_counter() - started
            )

            resolved_path = Path(
                module.PUBLIC_DATABASE_PATH
            )

            if not resolved_path.is_file():
                raise RuntimeError(
                    "Bootstrap did not create the local database."
                )

            downloaded_hash = sha256_file(
                resolved_path
            )

            connection = module.connect_public_db()

            try:
                representative_counts = {
                    "average.all_school_rankings": int(
                        connection.execute(
                            """
                            SELECT COUNT(*)
                            FROM average.all_school_rankings
                            """
                        ).fetchone()[0]
                    ),
                    (
                        "official."
                        "event_balanced_overall_combined"
                    ): int(
                        connection.execute(
                            """
                            SELECT COUNT(*)
                            FROM official.
                                event_balanced_overall_combined
                            """
                        ).fetchone()[0]
                    ),
                    "trends.explorer_program_index": int(
                        connection.execute(
                            """
                            SELECT COUNT(*)
                            FROM trends.explorer_program_index
                            """
                        ).fetchone()[0]
                    ),
                    (
                        "specialized."
                        "specialized_ranking_leaders"
                    ): int(
                        connection.execute(
                            """
                            SELECT COUNT(*)
                            FROM specialized.
                                specialized_ranking_leaders
                            """
                        ).fetchone()[0]
                    ),
                }
            finally:
                connection.close()

            expected_counts = {
                "average.all_school_rankings": 361,
                (
                    "official."
                    "event_balanced_overall_combined"
                ): 27764,
                "trends.explorer_program_index": 352,
                (
                    "specialized."
                    "specialized_ranking_leaders"
                ): 11,
            }

            leftover_files = sorted(
                path.name
                for path in destination.parent.glob(
                    "*.download*"
                )
            )

            results = {
                "destination_existed_before": existed_before,
                "destination_created": destination.is_file(),
                "resolved_path_matches_destination": (
                    resolved_path.resolve()
                    == destination.resolve()
                ),
                "bootstrap_seconds": round(
                    bootstrap_seconds,
                    6,
                ),
                "downloaded_database_size_bytes": (
                    resolved_path.stat().st_size
                ),
                "downloaded_database_sha256": (
                    downloaded_hash
                ),
                "expected_database_sha256": (
                    expected_database_hash
                ),
                "database_checksum_matches": (
                    downloaded_hash
                    == expected_database_hash
                ),
                "representative_counts": (
                    representative_counts
                ),
                "expected_counts": expected_counts,
                "representative_counts_match": (
                    representative_counts
                    == expected_counts
                ),
                "temporary_download_files_remaining": (
                    leftover_files
                ),
                "atomic_cleanup_passed": not leftover_files,
            }
        finally:
            restore_environment(
                previous_environment
            )

    source_database_hash_after = sha256_file(
        SOURCE_DATABASE
    )
    source_gzip_hash_after = sha256_file(
        SOURCE_GZIP
    )

    results[
        "source_database_hash_unchanged"
    ] = (
        source_database_hash_before
        == source_database_hash_after
    )
    results["source_gzip_hash_unchanged"] = (
        source_gzip_hash_before
        == source_gzip_hash_after
    )

    hard_checks = {
        "fresh_destination_started_absent": (
            not results["destination_existed_before"]
        ),
        "fresh_destination_created": (
            results["destination_created"]
        ),
        "resolved_path_matches_destination": (
            results[
                "resolved_path_matches_destination"
            ]
        ),
        "database_checksum_matches": (
            results["database_checksum_matches"]
        ),
        "representative_counts_match": (
            results["representative_counts_match"]
        ),
        "atomic_cleanup_passed": (
            results["atomic_cleanup_passed"]
        ),
        "source_database_hash_unchanged": (
            results[
                "source_database_hash_unchanged"
            ]
        ),
        "source_gzip_hash_unchanged": (
            results["source_gzip_hash_unchanged"]
        ),
    }

    summary = {
        "publication_version": (
            "public_deployment_v1"
        ),
        "bootstrap_source_url": (
            SOURCE_GZIP.resolve().as_uri()
        ),
        "results": results,
        "hard_checks": hard_checks,
        "passed": all(hard_checks.values()),
    }

    (
        OUTPUT_DIR / "bootstrap_validation.json"
    ).write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("=" * 76)
    print("PHASE 8C FRESH-ENVIRONMENT BOOTSTRAP")
    print("=" * 76)

    for name, passed in hard_checks.items():
        print(f"{name}: {passed}")

    print()
    print(
        "Bootstrap seconds: "
        f"{results['bootstrap_seconds']:.6f}"
    )
    print(
        "Downloaded bytes: "
        f"{results['downloaded_database_size_bytes']:,}"
    )
    print(
        "Database SHA-256: "
        f"{results['downloaded_database_sha256']}"
    )
    print(
        "Temporary download files remaining: "
        f"{len(results['temporary_download_files_remaining'])}"
    )
    print(f"Output directory: {OUTPUT_DIR}")

    if not summary["passed"]:
        raise SystemExit(
            "FAIL — fresh-environment bootstrap validation failed."
        )

    print()
    print(
        "PASS — a fresh environment can retrieve, verify, "
        "decompress, and query the public database artifact."
    )


if __name__ == "__main__":
    main()
