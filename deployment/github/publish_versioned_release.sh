#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

usage() {
  echo "Usage:"
  echo "  $0 VERSION PACKAGE_DIR ARTIFACT [--publish]"
  echo
  echo "Without --publish, this command performs a mutation-free dry run."
}

if [[ "$#" -lt 3 || "$#" -gt 4 ]]; then
  usage
  exit 2
fi

VERSION="$1"
PACKAGE_DIR="$2"
ARTIFACT="$3"
MODE="${4:-}"
DESCRIPTOR="$PACKAGE_DIR/release_descriptor.json"
NOTES="$PACKAGE_DIR/release_notes.md"
HISTORICAL_TAG="public-deployment-v1"
HISTORICAL_COMMIT="ee97cefe9db382468a231eff03299f5a3342a504"
PUBLISH=false

if [[ "$MODE" == "--publish" ]]; then
  PUBLISH=true
elif [[ -n "$MODE" ]]; then
  usage
  exit 2
fi

if [[ ! "$VERSION" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
  echo "ERROR — VERSION must use strict vMAJOR.MINOR.PATCH form."
  exit 1
fi

if [[ "$VERSION" == "$HISTORICAL_TAG" ]]; then
  echo "ERROR — $HISTORICAL_TAG is immutable and cannot be reused."
  exit 1
fi

if [[ "$VERSION" == "v1.0.0" && "${ALLOW_FINAL_V1_RELEASE:-0}" != "1" ]]; then
  echo "ERROR — v1.0.0 is blocked until every Milestone 9 gate passes."
  exit 1
fi

if [[ "$(git branch --show-current)" != "main" ]]; then
  echo "ERROR — release publishing requires main."
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR — working tree must be clean."
  exit 1
fi

if [[ ! -f "$DESCRIPTOR" || ! -f "$NOTES" || ! -f "$ARTIFACT" ]]; then
  echo "ERROR — descriptor, notes, and artifact must exist."
  exit 1
fi

LOCAL_HISTORICAL="$(git rev-parse "${HISTORICAL_TAG}^{}")"
REMOTE_HISTORICAL="$(
  git ls-remote --tags origin "${HISTORICAL_TAG}^{}" \
    | awk '{print $1}'
)"

if [[ "$LOCAL_HISTORICAL" != "$HISTORICAL_COMMIT" || \
      "$REMOTE_HISTORICAL" != "$HISTORICAL_COMMIT" ]]; then
  echo "ERROR — immutable historical tag validation failed."
  exit 1
fi

if git rev-parse "$VERSION" >/dev/null 2>&1; then
  echo "ERROR — local tag $VERSION already exists."
  exit 1
fi

if [[ -n "$(git ls-remote --tags origin "refs/tags/$VERSION")" ]]; then
  echo "ERROR — remote tag $VERSION already exists."
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR — GitHub CLI is required."
  exit 1
fi

if gh release view "$VERSION" >/dev/null 2>&1; then
  echo "ERROR — GitHub release $VERSION already exists."
  exit 1
fi

python - "$VERSION" "$DESCRIPTOR" "$ARTIFACT" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

version = sys.argv[1]
descriptor_path = Path(sys.argv[2])
artifact_path = Path(sys.argv[3])
descriptor = json.loads(descriptor_path.read_text())

if descriptor["release_version"] != version:
    raise SystemExit("ERROR — descriptor version mismatch.")

if descriptor["artifact"]["filename"] != artifact_path.name:
    raise SystemExit("ERROR — descriptor artifact filename mismatch.")

digest = hashlib.sha256()
with artifact_path.open("rb") as handle:
    while chunk := handle.read(8 * 1024 * 1024):
        digest.update(chunk)

if digest.hexdigest() != descriptor["artifact"]["sha256"]:
    raise SystemExit("ERROR — artifact checksum mismatch.")

if artifact_path.stat().st_size != descriptor["artifact"]["size_bytes"]:
    raise SystemExit("ERROR — artifact size mismatch.")

if descriptor["publication"]["parity_status"] != "PASS":
    raise SystemExit("ERROR — publication parity is not PASS.")

if not descriptor["application"][
    "verified_against_exact_artifact"
]:
    raise SystemExit(
        "ERROR — exact-artifact application verification is missing."
    )

print("PASS — descriptor, artifact, and publication gates agree.")
PY

if [[ "$PUBLISH" != true ]]; then
  echo
  echo "PASS — dry run complete. No tag or release was created."
  echo "Publishing remains blocked unless --publish is explicitly supplied."
  exit 0
fi

gh auth status

git tag -a "$VERSION" -m "NCAA Track Explorer $VERSION"
git push origin "$VERSION"

gh release create "$VERSION" \
  "$ARTIFACT#Compact public DuckDB publication (gzip)" \
  --title "NCAA Track Explorer $VERSION" \
  --notes-file "$NOTES" \
  --verify-tag

echo
echo "PASS — immutable GitHub Release published."
echo "https://github.com/joeyn256/NCAA-Track-Analytics-Pipeline/releases/tag/$VERSION"
