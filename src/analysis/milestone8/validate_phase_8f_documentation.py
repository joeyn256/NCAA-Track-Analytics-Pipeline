#!/usr/bin/env python3
"""Validate the completed Milestone 8 public deployment."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[3]

README: Final = ROOT / "README.md"
MILESTONE: Final = (
    ROOT
    / "milestones"
    / "milestone_08_public_deployment_and_recruiter_experience.md"
)
GUIDE: Final = ROOT / "deployment/STREAMLIT_COMMUNITY_CLOUD.md"
APP: Final = ROOT / "src/apps/seasonal_development_explorer.py"
DESCRIPTOR: Final = ROOT / "deployment/public_deployment_v1.json"
SECRETS: Final = ROOT / ".streamlit/secrets.toml"

OUTPUT_DIR: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8f_documentation_validation"
)

LIVE_URL: Final = (
    "https://ncaa-d1-track-analytics-pipeline-explorer."
    "streamlit.app/"
)


def contains_all(
    text: str,
    fragments: tuple[str, ...],
) -> bool:
    """Return whether every required fragment is present."""
    return all(fragment in text for fragment in fragments)


def descriptor_at_head() -> bytes:
    """Read the committed frozen deployment descriptor."""
    result = subprocess.run(
        [
            "git",
            "show",
            "HEAD:deployment/public_deployment_v1.json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return result.stdout


def main() -> None:
    """Validate the final public-deployment documentation state."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    required_files = (
        README,
        MILESTONE,
        GUIDE,
        APP,
        DESCRIPTOR,
    )

    for path in required_files:
        if not path.is_file():
            raise FileNotFoundError(path)

    readme = README.read_text(encoding="utf-8")
    milestone = MILESTONE.read_text(encoding="utf-8")
    guide = GUIDE.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")

    checks = {
        "descriptor_unchanged_from_head": (
            DESCRIPTOR.read_bytes() == descriptor_at_head()
        ),
        "readme_completed_deployment": contains_all(
            readme,
            (
                "## Public Explorer",
                "**Deployment status:** Milestone 8 is complete.",
                "**Milestones 1–8 are complete.**",
                LIVE_URL,
                "6,594,540",
                "193,961",
                "554 institutions",
                "81 of 81 tables",
            ),
        ),
        "readme_no_pending_language": (
            "validated public URL will be added" not in readme
            and "Milestones 1–7 are complete" not in readme
        ),
        "milestone_completed_deployment": contains_all(
            milestone,
            (
                "**Complete — public deployment live**",
                "## Phase 8F — Documentation and controlled public release",
                "**Status: Complete**",
                "All completion criteria were satisfied",
                LIVE_URL,
                "public-deployment-v1",
            ),
        ),
        "milestone_no_pending_language": (
            "public deployment pending" not in milestone.lower()
            and "**Status: In progress**" not in milestone
        ),
        "milestone_scope_contract": contains_all(
            milestone,
            (
                "Endpoint 90+ is retained as the supported",
                "Endpoint 95+ remains in the publication but hidden",
                "2020 Outdoor is not fabricated",
                (
                    "inbound transfer development remains "
                    "explicitly unavailable"
                ),
            ),
        ),
        "guide_completed_deployment": contains_all(
            guide,
            (
                "**Deployment complete.**",
                "## Completed deployment sequence",
                "**Result: Passed on July 21, 2026.**",
                LIVE_URL,
                "public-deployment-v1",
                "Public resource tables: 81",
            ),
        ),
        "guide_no_pending_language": (
            "Suggested app subdomain" not in guide
            and "The repository must still complete" not in guide
            and "## Required sequence" not in guide
        ),
        "app_supported_endpoint_wording": contains_all(
            app,
            (
                (
                    "Endpoint 90+ is the supported national "
                    "elite-finisher analysis"
                ),
                "Endpoint 95+ view is retained",
            ),
        ),
        "app_no_provisional_endpoint_wording": (
            "Endpoint 90+ is provisional" not in app
        ),
        "actual_secrets_file_absent": not SECRETS.exists(),
    }

    diff_check = subprocess.run(
        ["git", "diff", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    checks["git_diff_check_passed"] = (
        diff_check.returncode == 0
    )

    report = {
        "passed": all(checks.values()),
        "live_url": LIVE_URL,
        "checks": checks,
        "git_diff_check_stdout": diff_check.stdout,
        "git_diff_check_stderr": diff_check.stderr,
    }

    output_path = OUTPUT_DIR / "validation_summary.json"
    output_path.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("=" * 76)
    print("MILESTONE 8 COMPLETED DEPLOYMENT VALIDATION")
    print("=" * 76)

    for name, passed in checks.items():
        print(f"{name}: {passed}")

    print()
    print(f"Live URL: {LIVE_URL}")
    print(f"Output: {output_path}")

    if not report["passed"]:
        failed = [
            name
            for name, passed in checks.items()
            if not passed
        ]
        print()
        print("Failed checks:")
        for name in failed:
            print(f"- {name}")

        raise SystemExit(
            "FAIL — completed deployment validation did not pass."
        )

    print()
    print(
        "PASS — Milestone 8 is documented as complete, "
        "the public URL is recorded consistently, and the "
        "frozen deployment descriptor remains unchanged."
    )


if __name__ == "__main__":
    main()
