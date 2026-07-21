#!/usr/bin/env python3
"""Validate the prepared GitHub Release and Streamlit deployment package."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
from pathlib import Path
from typing import Final


ROOT: Final = Path(__file__).resolve().parents[3]

PUBLICATION_DIR: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8b_compact_publication"
)

DATABASE_PATH: Final = (
    PUBLICATION_DIR / "ncaa_track_public_explorer_v1.duckdb"
)
GZIP_PATH: Final = Path(str(DATABASE_PATH) + ".gz")

CONFIG_PATH: Final = ROOT / ".streamlit/config.toml"
SECRETS_EXAMPLE_PATH: Final = (
    ROOT / "deployment/streamlit/secrets.toml.example"
)
RELEASE_NOTES_PATH: Final = (
    ROOT
    / "deployment/github/public_deployment_v1_release_notes.md"
)
PUBLISH_SCRIPT_PATH: Final = (
    ROOT
    / "deployment/github/publish_public_deployment_v1.sh"
)
DEPLOYMENT_GUIDE_PATH: Final = (
    ROOT / "deployment/STREAMLIT_COMMUNITY_CLOUD.md"
)
DESCRIPTOR_PATH: Final = (
    ROOT / "deployment/public_deployment_v1.json"
)
GITIGNORE_PATH: Final = ROOT / ".gitignore"

EXPECTED_ENTRYPOINT: Final = (
    "src/apps/seasonal_development_explorer.py"
)
EXPECTED_PYTHON_VERSION: Final = "3.12"
EXPECTED_TAG: Final = "public-deployment-v1"


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest."""

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def shell_syntax_passes(path: Path) -> bool:
    """Return whether bash accepts the generated release script."""

    completed = subprocess.run(
        ["bash", "-n", str(path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    return completed.returncode == 0


def main() -> None:
    """Run static, checksum, safety, and configuration validation."""

    required_paths = (
        DATABASE_PATH,
        GZIP_PATH,
        CONFIG_PATH,
        SECRETS_EXAMPLE_PATH,
        RELEASE_NOTES_PATH,
        PUBLISH_SCRIPT_PATH,
        DEPLOYMENT_GUIDE_PATH,
        DESCRIPTOR_PATH,
        GITIGNORE_PATH,
    )

    for path in required_paths:
        if not path.is_file():
            raise FileNotFoundError(path)

    descriptor = json.loads(
        DESCRIPTOR_PATH.read_text(encoding="utf-8")
    )

    database_hash = sha256_file(DATABASE_PATH)
    gzip_hash = sha256_file(GZIP_PATH)

    secrets_text = SECRETS_EXAMPLE_PATH.read_text(
        encoding="utf-8"
    )
    config_text = CONFIG_PATH.read_text(
        encoding="utf-8"
    )
    publish_text = PUBLISH_SCRIPT_PATH.read_text(
        encoding="utf-8"
    )
    gitignore_text = GITIGNORE_PATH.read_text(
        encoding="utf-8"
    )

    release_url = str(
        descriptor["github"]["release_asset_url"]
    )
    expected_release_pattern = (
        r"^https://github\.com/[^/]+/[^/]+/releases/download/"
        + re.escape(EXPECTED_TAG)
        + r"/ncaa_track_public_explorer_v1\.duckdb\.gz$"
    )

    checks = {
        "descriptor_tag": (
            descriptor["github"]["release_tag"]
            == EXPECTED_TAG
        ),
        "descriptor_entrypoint": (
            descriptor["streamlit"]["entrypoint"]
            == EXPECTED_ENTRYPOINT
        ),
        "descriptor_python_version": (
            descriptor["streamlit"]["python_version"]
            == EXPECTED_PYTHON_VERSION
        ),
        "release_url_shape": bool(
            re.match(
                expected_release_pattern,
                release_url,
            )
        ),
        "descriptor_database_hash": (
            descriptor["artifact"]["database_sha256"]
            == database_hash
        ),
        "descriptor_gzip_hash": (
            descriptor["artifact"]["sha256"]
            == gzip_hash
        ),
        "secrets_contains_release_url": (
            release_url in secrets_text
        ),
        "secrets_contains_database_hash": (
            database_hash in secrets_text
        ),
        "secrets_contains_gzip_hash": (
            gzip_hash in secrets_text
        ),
        "config_hides_error_details": (
            'showErrorDetails = "none"'
            in config_text
        ),
        "config_uses_minimal_toolbar": (
            'toolbarMode = "minimal"'
            in config_text
        ),
        "publish_script_is_executable": bool(
            PUBLISH_SCRIPT_PATH.stat().st_mode
            & stat.S_IXUSR
        ),
        "publish_script_shell_syntax": (
            shell_syntax_passes(PUBLISH_SCRIPT_PATH)
        ),
        "publish_script_requires_main": (
            'git branch --show-current)" != "main"'
            in publish_text
        ),
        "publish_script_requires_clean_tree": (
            "git status --porcelain"
            in publish_text
        ),
        "publish_script_verifies_checksum": (
            "shasum -a 256"
            in publish_text
        ),
        "publish_script_does_not_clobber": (
            "--clobber" not in publish_text
        ),
        "secrets_file_is_ignored": (
            ".streamlit/secrets.toml"
            in gitignore_text.splitlines()
        ),
        "download_cache_is_ignored": (
            ".cache/ncaa_track_analytics/"
            in gitignore_text.splitlines()
        ),
    }

    summary = {
        "descriptor": descriptor,
        "checks": checks,
        "passed": all(checks.values()),
    }

    output_path = (
        ROOT
        / "data/processed/milestone8/public_deployment_v1"
        / "phase_8d_deployment_package_validation"
        / "validation_summary.json"
    )
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    output_path.write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("=" * 76)
    print("PHASE 8D DEPLOYMENT PACKAGE VALIDATION")
    print("=" * 76)

    for name, passed in checks.items():
        print(f"{name}: {passed}")

    print()
    print(f"Release asset URL: {release_url}")
    print(f"Output: {output_path.relative_to(ROOT)}")

    if not summary["passed"]:
        raise SystemExit(
            "FAIL — deployment package validation failed."
        )

    print()
    print(
        "PASS — the GitHub Release and Streamlit deployment "
        "package is internally consistent and safe to commit."
    )
    print(
        "No release was created and no network write action occurred."
    )


if __name__ == "__main__":
    main()
