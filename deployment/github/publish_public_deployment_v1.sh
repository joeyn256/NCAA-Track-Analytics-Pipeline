#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

TAG="public-deployment-v1"
ASSET="data/processed/milestone8/public_deployment_v1/phase_8b_compact_publication/ncaa_track_public_explorer_v1.duckdb.gz"
NOTES="deployment/github/public_deployment_v1_release_notes.md"
EXPECTED_GZIP_SHA256="2a4aa9fd321dce96313d24cf532fbb8200d22847f6b6257138e0b49eed86432c"

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

OBSERVED_GZIP_SHA256="$(shasum -a 256 "$ASSET" | awk '{print $1}')"

if [[ "$OBSERVED_GZIP_SHA256" != "$EXPECTED_GZIP_SHA256" ]]; then
  echo "ERROR — release artifact checksum mismatch."
  exit 1
fi

if gh release view "$TAG" >/dev/null 2>&1; then
  echo "ERROR — release $TAG already exists."
  echo "Use a new immutable release tag rather than replacing the asset."
  exit 1
fi

git tag -a "$TAG" -m "NCAA Track Explorer — Public Deployment v1"
git push origin "$TAG"

gh release create "$TAG"   "$ASSET#Compact public DuckDB publication (gzip)"   --title "NCAA Track Explorer — Public Deployment v1"   --notes-file "$NOTES"   --verify-tag

echo
echo "PASS — GitHub Release published."
echo "https://github.com/joeyn256/NCAA-Track-Analytics-Pipeline/releases/tag/public-deployment-v1"
echo "https://github.com/joeyn256/NCAA-Track-Analytics-Pipeline/releases/download/public-deployment-v1/ncaa_track_public_explorer_v1.duckdb.gz"
