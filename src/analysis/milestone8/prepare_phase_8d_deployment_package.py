#!/usr/bin/env python3
"""Prepare the Milestone 8 GitHub Release and Streamlit deployment package."""

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
MANIFEST_PATH: Final = PUBLICATION_DIR / "deployment_manifest.json"

STREAMLIT_DIR: Final = ROOT / ".streamlit"
DEPLOYMENT_DIR: Final = ROOT / "deployment"
GITHUB_DIR: Final = DEPLOYMENT_DIR / "github"
STREAMLIT_DEPLOYMENT_DIR: Final = DEPLOYMENT_DIR / "streamlit"

CONFIG_PATH: Final = STREAMLIT_DIR / "config.toml"
SECRETS_EXAMPLE_PATH: Final = (
    STREAMLIT_DEPLOYMENT_DIR / "secrets.toml.example"
)
RELEASE_NOTES_PATH: Final = (
    GITHUB_DIR / "public_deployment_v1_release_notes.md"
)
PUBLISH_SCRIPT_PATH: Final = (
    GITHUB_DIR / "publish_public_deployment_v1.sh"
)
DEPLOYMENT_DOC_PATH: Final = (
    DEPLOYMENT_DIR / "STREAMLIT_COMMUNITY_CLOUD.md"
)
DEPLOYMENT_DESCRIPTOR_PATH: Final = (
    DEPLOYMENT_DIR / "public_deployment_v1.json"
)
GITIGNORE_PATH: Final = ROOT / ".gitignore"

RELEASE_TAG: Final = "public-deployment-v1"
RELEASE_NAME: Final = "NCAA Track Explorer — Public Deployment v1"
ENTRYPOINT: Final = "src/apps/seasonal_development_explorer.py"
PYTHON_VERSION: Final = "3.12"


def run_command(arguments: list[str]) -> str:
    """Run one repository command and return stripped stdout."""

    completed = subprocess.run(
        arguments,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(arguments)}\n"
            f"STDOUT:\n{completed.stdout}\n"
            f"STDERR:\n{completed.stderr}"
        )

    return completed.stdout.strip()


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest."""

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def repository_slug(remote_url: str) -> str:
    """Extract OWNER/REPO from common GitHub origin URL forms."""

    normalized = remote_url.strip().removesuffix(".git")

    patterns = (
        r"^https://github\.com/(?P<slug>[^/]+/[^/]+)$",
        r"^http://github\.com/(?P<slug>[^/]+/[^/]+)$",
        r"^git@github\.com:(?P<slug>[^/]+/[^/]+)$",
        r"^ssh://git@github\.com/(?P<slug>[^/]+/[^/]+)$",
    )

    for pattern in patterns:
        match = re.match(pattern, normalized)

        if match:
            return match.group("slug")

    raise RuntimeError(
        "Could not derive a GitHub OWNER/REPO slug from origin: "
        f"{remote_url}"
    )


def update_gitignore() -> None:
    """Ensure local secrets and downloaded cache are excluded."""

    existing = (
        GITIGNORE_PATH.read_text(encoding="utf-8")
        if GITIGNORE_PATH.is_file()
        else ""
    )

    required_lines = (
        ".streamlit/secrets.toml",
        ".cache/ncaa_track_analytics/",
    )

    lines = existing.splitlines()
    changed = False

    for required in required_lines:
        if required not in lines:
            lines.append(required)
            changed = True

    if changed:
        GITIGNORE_PATH.write_text(
            "\n".join(lines).rstrip() + "\n",
            encoding="utf-8",
        )


def main() -> None:
    """Create deterministic deployment configuration and documentation."""

    for path in (
        DATABASE_PATH,
        GZIP_PATH,
        MANIFEST_PATH,
        GITIGNORE_PATH,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)

    manifest = json.loads(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )

    database_hash = sha256_file(DATABASE_PATH)
    gzip_hash = sha256_file(GZIP_PATH)

    if database_hash != str(manifest["database"]["sha256"]):
        raise RuntimeError(
            "Database checksum does not match deployment manifest."
        )

    if gzip_hash != str(manifest["gzip"]["sha256"]):
        raise RuntimeError(
            "Gzip checksum does not match deployment manifest."
        )

    origin = run_command(
        ["git", "remote", "get-url", "origin"]
    )
    slug = repository_slug(origin)
    owner, repository = slug.split("/", 1)

    asset_name = GZIP_PATH.name
    release_url = (
        f"https://github.com/{slug}/releases/download/"
        f"{RELEASE_TAG}/{asset_name}"
    )
    release_page = (
        f"https://github.com/{slug}/releases/tag/{RELEASE_TAG}"
    )

    STREAMLIT_DIR.mkdir(parents=True, exist_ok=True)
    GITHUB_DIR.mkdir(parents=True, exist_ok=True)
    STREAMLIT_DEPLOYMENT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    CONFIG_PATH.write_text(
        """[client]
toolbarMode = "minimal"
showErrorDetails = "none"
showErrorLinks = false

[browser]
gatherUsageStats = false

[server]
headless = true
""",
        encoding="utf-8",
    )

    SECRETS_EXAMPLE_PATH.write_text(
        f"""# Paste these root-level values into Streamlit Community Cloud's
# Advanced settings > Secrets field. Root-level Streamlit secrets are
# exposed to the app as environment variables.

NCAA_TRACK_PUBLIC_DB_URL = "{release_url}"
NCAA_TRACK_PUBLIC_DB_SHA256 = "{database_hash}"
NCAA_TRACK_PUBLIC_GZIP_SHA256 = "{gzip_hash}"
NCAA_TRACK_PUBLIC_CACHE_DIR = "/tmp/ncaa_track_analytics"
""",
        encoding="utf-8",
    )

    RELEASE_NOTES_PATH.write_text(
        f"""# {RELEASE_NAME}

This release publishes the compact, read-only data artifact used by the
NCAA Division I Athlete Development Explorer.

## Artifact

- File: `{asset_name}`
- Compressed size: {GZIP_PATH.stat().st_size:,} bytes
- Uncompressed size: {DATABASE_PATH.stat().st_size:,} bytes
- Compressed SHA-256: `{gzip_hash}`
- Database SHA-256: `{database_hash}`

## Publication contents

- 81 resource tables
- 5 deployment metadata tables
- 2,918,594 validated resource rows
- Enhanced Balanced Production official rankings
- Original Balanced Production robustness companion outputs
- Average Development companion outputs
- Seasonal trend explorer tables
- Specialized ranking publications

## Validation

The artifact passed:

- exact source-to-deployment value parity for all 81 tables;
- bidirectional duplicate-preserving reconciliation;
- frozen-source checksum preservation;
- fresh-environment download and atomic decompression;
- Streamlit AppTest with zero exceptions and errors;
- cold and warm runtime budgets;
- provisional Community Cloud memory budget.

Release page: {release_page}
""",
        encoding="utf-8",
    )

    publish_script = f"""#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

TAG="{RELEASE_TAG}"
ASSET="{GZIP_PATH.relative_to(ROOT).as_posix()}"
NOTES="{RELEASE_NOTES_PATH.relative_to(ROOT).as_posix()}"
EXPECTED_GZIP_SHA256="{gzip_hash}"

if [[ "$(git branch --show-current)" != "main" ]]; then
  echo "ERROR — publish only from main."
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR — working tree must be clean before publishing."
  git status -sb
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR — GitHub CLI (gh) is required."
  exit 1
fi

gh auth status

OBSERVED_GZIP_SHA256="$(shasum -a 256 "$ASSET" | awk '{{print $1}}')"

if [[ "$OBSERVED_GZIP_SHA256" != "$EXPECTED_GZIP_SHA256" ]]; then
  echo "ERROR — release artifact checksum mismatch."
  exit 1
fi

if gh release view "$TAG" >/dev/null 2>&1; then
  echo "ERROR — release $TAG already exists."
  echo "Use a new immutable release tag rather than replacing the asset."
  exit 1
fi

git tag -a "$TAG" -m "{RELEASE_NAME}"
git push origin "$TAG"

gh release create "$TAG" \
  "$ASSET#Compact public DuckDB publication (gzip)" \
  --title "{RELEASE_NAME}" \
  --notes-file "$NOTES" \
  --verify-tag

echo
echo "PASS — GitHub Release published."
echo "{release_page}"
echo "{release_url}"
"""

    PUBLISH_SCRIPT_PATH.write_text(
        publish_script,
        encoding="utf-8",
    )
    PUBLISH_SCRIPT_PATH.chmod(
        PUBLISH_SCRIPT_PATH.stat().st_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )

    DEPLOYMENT_DOC_PATH.write_text(
        f"""# Streamlit Community Cloud deployment

## Deployment target

- GitHub repository: `{slug}`
- Branch: `main`
- Entrypoint: `{ENTRYPOINT}`
- Python: `{PYTHON_VERSION}`
- Suggested app subdomain: `ncaa-track-development-explorer`
- Release tag: `{RELEASE_TAG}`
- Release asset: `{asset_name}`

## Required sequence

1. Complete all remaining Milestone 8 gates.
2. Commit the Milestone 8 implementation on `milestone-8`.
3. Merge the branch to `main`.
4. Confirm `main` is clean and pushed.
5. Run:

   ```zsh
   deployment/github/publish_public_deployment_v1.sh
   ```

6. Confirm the asset opens at:

   `{release_url}`

7. In Streamlit Community Cloud, create an app using:

   - Repository: `{slug}`
   - Branch: `main`
   - Main file path: `{ENTRYPOINT}`
   - Python version: `{PYTHON_VERSION}`

8. Open **Advanced settings** and paste the contents of:

   `deployment/streamlit/secrets.toml.example`

9. Deploy and inspect the build logs.
10. Validate the public URL with the Milestone 8 production smoke test.

## Important

Do not commit `.streamlit/secrets.toml`. The committed example contains
only the public release URL and publication checksums. The actual Community
Cloud values should be entered through the deployment interface.

The app downloads the gzip artifact only when the local DuckDB file is
missing, verifies both checksums, decompresses atomically, and reuses the
cached DuckDB on subsequent runs.
""",
        encoding="utf-8",
    )

    descriptor = {
        "publication_version": "public_deployment_v1",
        "github": {
            "origin": origin,
            "owner": owner,
            "repository": repository,
            "slug": slug,
            "release_tag": RELEASE_TAG,
            "release_name": RELEASE_NAME,
            "release_page": release_page,
            "release_asset_url": release_url,
        },
        "streamlit": {
            "entrypoint": ENTRYPOINT,
            "python_version": PYTHON_VERSION,
            "suggested_subdomain": (
                "ncaa-track-development-explorer"
            ),
            "config_path": CONFIG_PATH.relative_to(
                ROOT
            ).as_posix(),
            "secrets_example_path": (
                SECRETS_EXAMPLE_PATH.relative_to(ROOT).as_posix()
            ),
        },
        "artifact": {
            "path": GZIP_PATH.relative_to(ROOT).as_posix(),
            "filename": asset_name,
            "size_bytes": GZIP_PATH.stat().st_size,
            "sha256": gzip_hash,
            "database_size_bytes": DATABASE_PATH.stat().st_size,
            "database_sha256": database_hash,
        },
    }

    DEPLOYMENT_DESCRIPTOR_PATH.write_text(
        json.dumps(
            descriptor,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    update_gitignore()

    print("=" * 76)
    print("PHASE 8D DEPLOYMENT PACKAGE")
    print("=" * 76)
    print(f"GitHub repository: {slug}")
    print(f"Release tag:       {RELEASE_TAG}")
    print(f"Release asset:     {asset_name}")
    print(f"Release URL:       {release_url}")
    print(f"Streamlit file:    {ENTRYPOINT}")
    print(f"Python version:    {PYTHON_VERSION}")
    print()
    print(f"Created: {CONFIG_PATH.relative_to(ROOT)}")
    print(f"Created: {SECRETS_EXAMPLE_PATH.relative_to(ROOT)}")
    print(f"Created: {RELEASE_NOTES_PATH.relative_to(ROOT)}")
    print(f"Created: {PUBLISH_SCRIPT_PATH.relative_to(ROOT)}")
    print(f"Created: {DEPLOYMENT_DOC_PATH.relative_to(ROOT)}")
    print(f"Created: {DEPLOYMENT_DESCRIPTOR_PATH.relative_to(ROOT)}")
    print()
    print(
        "PASS — deployment package prepared. "
        "No release was created and nothing was pushed."
    )


if __name__ == "__main__":
    main()
