#!/usr/bin/env python3
"""Profile compact-publication Streamlit startup time and memory."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Final


ROOT: Final = Path(__file__).resolve().parents[3]
APP_PATH: Final = ROOT / "src/apps/seasonal_development_explorer.py"
DATABASE_PATH: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8b_compact_publication"
    / "ncaa_track_public_explorer_v1.duckdb"
)
MANIFEST_PATH: Final = DATABASE_PATH.parent / "deployment_manifest.json"
OUTPUT_DIR: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8c_runtime_profile"
)

COLD_SECONDS_BUDGET: Final = 30.0
WARM_SECONDS_BUDGET: Final = 8.0
MEMORY_BUDGET_BYTES: Final = int(2.5 * 1024**3)
GITHUB_RELEASE_ASSET_LIMIT_BYTES: Final = 2 * 1024**3

CHILD_PROGRAM: Final = '\nimport json\nimport os\nimport resource\nimport sys\nimport time\nfrom pathlib import Path\n\nfrom streamlit.testing.v1 import AppTest\n\napp_path = Path(os.environ["PROFILE_APP_PATH"])\ndatabase_path = Path(os.environ["NCAA_TRACK_PUBLIC_DB"])\n\n\ndef rss_bytes():\n    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n    return int(raw if sys.platform == "darwin" else raw * 1024)\n\n\nstarted = time.perf_counter()\napp_test = AppTest.from_file(str(app_path))\napp_test.run(timeout=180)\ncold_seconds = time.perf_counter() - started\ncold_rss = rss_bytes()\n\nstarted = time.perf_counter()\napp_test.run(timeout=180)\nwarm_seconds = time.perf_counter() - started\nwarm_rss = rss_bytes()\n\npayload = {\n    "cold_seconds": round(cold_seconds, 6),\n    "warm_seconds": round(warm_seconds, 6),\n    "cold_max_rss_bytes": cold_rss,\n    "warm_process_max_rss_bytes": warm_rss,\n    "exceptions": len(app_test.exception),\n    "errors": len(app_test.error),\n    "warnings": len(app_test.warning),\n    "database_exists": database_path.is_file(),\n}\n\nprint("PROFILE_JSON=" + json.dumps(payload, sort_keys=True))\n'


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest."""

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def run_profile() -> tuple[dict[str, Any], str, str]:
    """Run the profiler in a clean child process."""

    environment = os.environ.copy()
    environment["PROFILE_APP_PATH"] = str(APP_PATH)
    environment["NCAA_TRACK_PUBLIC_DB"] = str(DATABASE_PATH)

    completed = subprocess.run(
        [sys.executable, "-c", CHILD_PROGRAM],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=240,
    )

    profile_line = None

    for line in completed.stdout.splitlines():
        if line.startswith("PROFILE_JSON="):
            profile_line = line.removeprefix("PROFILE_JSON=")

    if completed.returncode != 0 or profile_line is None:
        raise RuntimeError(
            "Runtime profiler child process failed.\n"
            f"Return code: {completed.returncode}\n"
            f"STDOUT:\n{completed.stdout}\n"
            f"STDERR:\n{completed.stderr}"
        )

    return (
        json.loads(profile_line),
        completed.stdout,
        completed.stderr,
    )


def main() -> None:
    """Profile startup, rerun, memory, and artifact fit."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for path in (
        APP_PATH,
        DATABASE_PATH,
        MANIFEST_PATH,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)

    manifest = json.loads(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )

    database_hash_before = sha256_file(DATABASE_PATH)
    expected_database_hash = str(
        manifest["database"]["sha256"]
    )

    if database_hash_before != expected_database_hash:
        raise RuntimeError(
            "Deployment database checksum does not match manifest."
        )

    gzip_path = ROOT / str(manifest["gzip"]["path"])

    if not gzip_path.is_file():
        raise FileNotFoundError(gzip_path)

    profile, child_stdout, child_stderr = run_profile()

    database_hash_after = sha256_file(DATABASE_PATH)
    gzip_size = int(gzip_path.stat().st_size)

    hard_checks = {
        "app_test_has_no_exceptions": (
            int(profile["exceptions"]) == 0
        ),
        "app_test_has_no_errors": (
            int(profile["errors"]) == 0
        ),
        "database_exists": bool(profile["database_exists"]),
        "cold_start_within_30_seconds": (
            float(profile["cold_seconds"])
            <= COLD_SECONDS_BUDGET
        ),
        "warm_rerun_within_8_seconds": (
            float(profile["warm_seconds"])
            <= WARM_SECONDS_BUDGET
        ),
        "max_rss_within_2_5_gib_budget": (
            int(profile["warm_process_max_rss_bytes"])
            <= MEMORY_BUDGET_BYTES
        ),
        "gzip_fits_github_release_asset_limit": (
            gzip_size < GITHUB_RELEASE_ASSET_LIMIT_BYTES
        ),
        "deployment_hash_unchanged": (
            database_hash_before == database_hash_after
        ),
    }

    summary = {
        "publication_version": "public_deployment_v1",
        "budgets": {
            "cold_seconds": COLD_SECONDS_BUDGET,
            "warm_seconds": WARM_SECONDS_BUDGET,
            "memory_bytes": MEMORY_BUDGET_BYTES,
            "github_release_asset_limit_bytes": (
                GITHUB_RELEASE_ASSET_LIMIT_BYTES
            ),
        },
        "profile": profile,
        "artifact": {
            "database_size_bytes": DATABASE_PATH.stat().st_size,
            "gzip_size_bytes": gzip_size,
            "database_sha256_before": database_hash_before,
            "database_sha256_after": database_hash_after,
        },
        "hard_checks": hard_checks,
        "passed": all(hard_checks.values()),
        "child_stderr": child_stderr,
    }

    (OUTPUT_DIR / "runtime_profile.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    (OUTPUT_DIR / "child_stdout.txt").write_text(
        child_stdout,
        encoding="utf-8",
    )

    (OUTPUT_DIR / "child_stderr.txt").write_text(
        child_stderr,
        encoding="utf-8",
    )

    print("=" * 76)
    print("PHASE 8C COMPACT RUNTIME PROFILE")
    print("=" * 76)

    for name, passed in hard_checks.items():
        print(f"{name}: {passed}")

    print()
    print(
        "Cold AppTest seconds: "
        f"{float(profile['cold_seconds']):.6f}"
    )
    print(
        "Warm AppTest seconds: "
        f"{float(profile['warm_seconds']):.6f}"
    )
    print(
        "Cold max RSS: "
        f"{int(profile['cold_max_rss_bytes']):,} bytes "
        f"({int(profile['cold_max_rss_bytes']) / 1024**3:.3f} GiB)"
    )
    print(
        "Warm-process max RSS: "
        f"{int(profile['warm_process_max_rss_bytes']):,} bytes "
        f"({int(profile['warm_process_max_rss_bytes']) / 1024**3:.3f} GiB)"
    )
    print(
        "Gzip release asset: "
        f"{gzip_size:,} bytes "
        f"({gzip_size / 1024**2:.3f} MiB)"
    )
    print(f"Output directory: {OUTPUT_DIR}")

    if not summary["passed"]:
        raise SystemExit(
            "FAIL — compact runtime profile exceeded a deployment budget."
        )

    print()
    print(
        "PASS — the compact explorer meets the provisional "
        "startup, memory, and release-asset budgets."
    )


if __name__ == "__main__":
    main()
