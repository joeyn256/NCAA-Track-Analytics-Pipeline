#!/usr/bin/env python3
"""Validate the Milestone 8 recruiter-facing homepage."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Final

from streamlit.testing.v1 import AppTest


ROOT: Final = Path(__file__).resolve().parents[3]

APP_PATH: Final = (
    ROOT / "src/apps/seasonal_development_explorer.py"
)

DATABASE_PATH: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8b_compact_publication"
    / "ncaa_track_public_explorer_v1.duckdb"
)

MANIFEST_PATH: Final = (
    DATABASE_PATH.parent / "deployment_manifest.json"
)

AUDIT_SCRIPT: Final = (
    ROOT
    / "src/analysis/milestone8"
    / "audit_phase_8d_recruiter_experience.py"
)

AUDIT_SUMMARY_PATH: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8d_recruiter_experience_audit"
    / "audit_summary.json"
)

OUTPUT_DIR: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8d_recruiter_homepage_validation"
)

START_MARKER: Final = (
    "# BEGIN MILESTONE 8 RECRUITER HOMEPAGE"
)

END_MARKER: Final = (
    "# END MILESTONE 8 RECRUITER HOMEPAGE"
)


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest."""

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def run_recruiter_audit() -> dict:
    """Run the canonical recruiter audit and return its summary."""

    completed = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=240,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "Recruiter audit failed.\n"
            f"STDOUT:\n{completed.stdout}\n"
            f"STDERR:\n{completed.stderr}"
        )

    if not AUDIT_SUMMARY_PATH.is_file():
        raise FileNotFoundError(
            AUDIT_SUMMARY_PATH
        )

    return json.loads(
        AUDIT_SUMMARY_PATH.read_text(
            encoding="utf-8"
        )
    )


def main() -> None:
    """Validate content, AppTest, canonical audit, and checksum."""

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    for path in (
        APP_PATH,
        DATABASE_PATH,
        MANIFEST_PATH,
        AUDIT_SCRIPT,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)

    manifest = json.loads(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )
    expected_hash = str(
        manifest["database"]["sha256"]
    )
    database_hash_before = sha256_file(
        DATABASE_PATH
    )

    if database_hash_before != expected_hash:
        raise RuntimeError(
            "Deployment database checksum does not match manifest."
        )

    source = APP_PATH.read_text(
        encoding="utf-8"
    )
    compile(
        source,
        str(APP_PATH),
        "exec",
    )

    content_checks = {
        "start_marker_once": (
            source.count(START_MARKER) == 1
        ),
        "end_marker_once": (
            source.count(END_MARKER) == 1
        ),
        "scale_performance_visible": (
            "6,594,540" in source
        ),
        "scale_athletes_visible": (
            "193,961" in source
        ),
        "scale_deployment_tables_visible": (
            '"81"' in source
            and "Deployment tables" in source
        ),
        "guided_start_visible": (
            "**Start here:**" in source
        ),
        "github_link_visible": (
            "https://github.com/joeyn256/"
            "NCAA-Track-Analytics-Pipeline"
            in source
        ),
        "2020_outdoor_scope_visible": (
            "2020 Outdoor" in source
        ),
        "inbound_transfer_scope_visible": (
            "Inbound transfer development"
            in source
        ),
    }

    previous_database = os.environ.get(
        "NCAA_TRACK_PUBLIC_DB"
    )
    os.environ[
        "NCAA_TRACK_PUBLIC_DB"
    ] = str(DATABASE_PATH)

    try:
        app_test = AppTest.from_file(
            str(APP_PATH)
        )
        app_test.run(timeout=180)

        app_test_checks = {
            "app_test_has_no_exceptions": (
                len(app_test.exception) == 0
            ),
            "app_test_has_no_errors": (
                len(app_test.error) == 0
            ),
            "app_test_has_no_warnings": (
                len(app_test.warning) == 0
            ),
        }
    finally:
        if previous_database is None:
            os.environ.pop(
                "NCAA_TRACK_PUBLIC_DB",
                None,
            )
        else:
            os.environ[
                "NCAA_TRACK_PUBLIC_DB"
            ] = previous_database

    audit = run_recruiter_audit()

    recruiter_checks = {
        str(check["dimension"]): bool(
            check["passed"]
        )
        for check in audit[
            "recruiter_checks"
        ]
    }

    audit_checks = {
        "technical_audit_passed": bool(
            audit["technical_passed"]
        ),
        "recruiter_score_is_100": (
            int(audit["recruiter_score"])
            == 100
        ),
        "all_recruiter_checks_pass": all(
            recruiter_checks.values()
        ),
    }

    database_hash_after = sha256_file(
        DATABASE_PATH
    )

    hard_checks = {
        **content_checks,
        **app_test_checks,
        **audit_checks,
        "deployment_hash_unchanged": (
            database_hash_before
            == database_hash_after
        ),
    }

    summary = {
        "content_checks": content_checks,
        "app_test_checks": app_test_checks,
        "audit_checks": audit_checks,
        "recruiter_score": audit[
            "recruiter_score"
        ],
        "recruiter_checks": recruiter_checks,
        "database_sha256_before": (
            database_hash_before
        ),
        "database_sha256_after": (
            database_hash_after
        ),
        "hard_checks": hard_checks,
        "passed": all(hard_checks.values()),
    }

    (
        OUTPUT_DIR / "validation_summary.json"
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
    print("PHASE 8D RECRUITER HOMEPAGE VALIDATION")
    print("=" * 76)

    for name, passed in hard_checks.items():
        print(f"{name}: {passed}")

    print()
    print(
        "Recruiter-readiness score: "
        f"{audit['recruiter_score']}/100"
    )
    print(
        "AppTest exceptions: "
        f"{len(app_test.exception)}"
    )
    print(
        "AppTest errors: "
        f"{len(app_test.error)}"
    )
    print(
        "AppTest warnings: "
        f"{len(app_test.warning)}"
    )
    print(
        "Deployment hash unchanged: "
        f"{database_hash_before == database_hash_after}"
    )
    print(f"Output directory: {OUTPUT_DIR}")

    if not summary["passed"]:
        raise SystemExit(
            "FAIL — recruiter homepage validation failed."
        )

    print()
    print(
        "PASS — the recruiter homepage scores 100/100 "
        "and preserves application behavior."
    )


if __name__ == "__main__":
    main()
