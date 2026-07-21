#!/usr/bin/env python3
"""Validate Milestone 8 release-candidate documentation consistency."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Final


ROOT: Final = Path(__file__).resolve().parents[3]

README: Final = ROOT / "README.md"
MILESTONE: Final = (
    ROOT
    / "milestones/milestone_08_public_deployment_and_recruiter_experience.md"
)
GUIDE: Final = ROOT / "deployment/STREAMLIT_COMMUNITY_CLOUD.md"
DESCRIPTOR: Final = ROOT / "deployment/public_deployment_v1.json"
RELEASE_NOTES: Final = (
    ROOT / "deployment/github/public_deployment_v1_release_notes.md"
)
SECRETS_FILE: Final = ROOT / ".streamlit/secrets.toml"
READINESS_REPORT: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8e_release_readiness/release_readiness.json"
)
OUTPUT_DIR: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8f_documentation_validation"
)

EXPECTED_DESCRIPTOR_SHA256: Final = (
    "3b740b610d3b365c7d59c0ae818bd3a51e6e31974857bf53de36c77a06abab88"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def contains_all(text: str, fragments: tuple[str, ...]) -> bool:
    return all(fragment in text for fragment in fragments)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    required_files = (
        README,
        MILESTONE,
        GUIDE,
        DESCRIPTOR,
        RELEASE_NOTES,
        READINESS_REPORT,
    )

    for path in required_files:
        if not path.is_file():
            raise FileNotFoundError(path)

    readme = README.read_text(encoding="utf-8")
    milestone = MILESTONE.read_text(encoding="utf-8")
    guide = GUIDE.read_text(encoding="utf-8")
    notes = RELEASE_NOTES.read_text(encoding="utf-8")
    descriptor = json.loads(
        DESCRIPTOR.read_text(encoding="utf-8")
    )
    readiness = json.loads(
        READINESS_REPORT.read_text(encoding="utf-8")
    )

    compressed_hash = descriptor["artifact"]["sha256"]
    database_hash = descriptor["artifact"]["database_sha256"]
    compressed_size = descriptor["artifact"]["size_bytes"]
    database_size = descriptor["artifact"]["database_size_bytes"]
    release_tag = descriptor["github"]["release_tag"]
    release_asset = descriptor["artifact"]["filename"]

    checks = {
        "descriptor_unchanged": (
            sha256_file(DESCRIPTOR) == EXPECTED_DESCRIPTOR_SHA256
        ),
        "release_readiness_report_passed": (
            readiness.get("passed") is True
            and len(readiness.get("validators", [])) == 7
            and all(
                item.get("passed") is True
                for item in readiness.get("validators", [])
            )
        ),
        "readme_public_explorer_section": contains_all(
            readme,
            (
                "## Public Explorer",
                "release candidate has passed every",
                "validated public URL will be added here",
            ),
        ),
        "readme_scale_metrics": contains_all(
            readme,
            (
                "6,594,540",
                "193,961",
                "554 institutions",
                "2,918,594",
            ),
        ),
        "readme_deployment_architecture": contains_all(
            readme,
            (
                "### Public deployment architecture",
                "81",
                "236,994,168 bytes",
                "Large point views are loaded lazily",
            ),
        ),
        "readme_validation_metrics": contains_all(
            readme,
            (
                "7 of 7 passed",
                "100 of 100",
                "0.290 GiB",
                "1.684 GiB",
                "1.368 seconds",
                "0.097 seconds",
            ),
        ),
        "readme_milestone8_links": contains_all(
            readme,
            (
                "milestone_08_public_deployment_and_recruiter_experience.md",
                "deployment/STREAMLIT_COMMUNITY_CLOUD.md",
            ),
        ),
        "readme_does_not_claim_live_url": (
            "share.streamlit.io" not in readme
            and "streamlit.app" not in readme
        ),
        "milestone_release_candidate_status": contains_all(
            milestone,
            (
                "**Release candidate validated — public deployment pending**",
                "## Release candidate summary",
                "## Phase 8F — Documentation and controlled public release",
                "**Status: In progress**",
            ),
        ),
        "milestone_completed_phases": all(
            f"## Phase 8{letter}" in milestone
            for letter in "ABCDE"
        ) and milestone.count("**Status: Complete**") >= 5,
        "milestone_no_stale_phase8b_status": (
            "## Phase 8B — Compact Deployment Publication\n\n"
            "**Status: In progress**"
            not in milestone
        ),
        "milestone_parity_and_runtime": contains_all(
            milestone,
            (
                "81 of 81 exact table comparisons",
                "2,918,594 source resource rows",
                "Default page | 0.289 GiB | 0.290 GiB",
                "Athlete Contributions | 1.681 GiB | 1.684 GiB",
            ),
        ),
        "milestone_scope_contract": contains_all(
            milestone,
            (
                "2020 Outdoor is not fabricated",
                "inbound transfer development remains explicitly unavailable",
                "Endpoint 95+ remains in the publication but hidden",
            ),
        ),
        "guide_readiness_and_sequence": contains_all(
            guide,
            (
                "7 of 7 regression validators passed",
                "publish_public_deployment_v1.sh",
                "Run the production smoke test",
                "Add the validated public URL",
            ),
        ),
        "guide_smoke_test_complete": contains_all(
            guide,
            (
                "Athlete Contributions loads successfully",
                "Program Trends loads",
                "filter selections persist across navigation",
                "page refresh reuses the cached artifact",
            ),
        ),
        "release_notes_validation_current": contains_all(
            notes,
            (
                "7 of 7 full release-readiness validators",
                "default-page maximum memory of 0.290 GiB",
                "Athlete Contributions maximum memory of 1.684 GiB",
                "recruiter-readiness score of 100 out of 100",
            ),
        ),
        "compressed_hash_consistent": all(
            compressed_hash in text
            for text in (milestone, guide, notes)
        ),
        "database_hash_consistent": all(
            database_hash in text
            for text in (milestone, guide, notes)
        ),
        "artifact_sizes_consistent": (
            f"{compressed_size:,}" in milestone
            and f"{compressed_size:,}" in guide
            and f"{compressed_size:,}" in notes
            and f"{database_size:,}" in milestone
            and f"{database_size:,}" in notes
        ),
        "release_identity_consistent": all(
            release_tag in text
            for text in (milestone, guide, notes)
        ) and all(
            release_asset in text
            for text in (milestone, guide, notes)
        ),
        "actual_secrets_file_absent": not SECRETS_FILE.exists(),
    }

    diff_check = subprocess.run(
        ["git", "diff", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    checks["git_diff_check_passed"] = diff_check.returncode == 0

    report = {
        "passed": all(checks.values()),
        "checks": checks,
        "descriptor": {
            "publication_version": descriptor["publication_version"],
            "release_tag": release_tag,
            "release_asset": release_asset,
            "compressed_sha256": compressed_hash,
            "database_sha256": database_hash,
        },
        "git_diff_check_stdout": diff_check.stdout,
        "git_diff_check_stderr": diff_check.stderr,
    }

    (
        OUTPUT_DIR / "validation_summary.json"
    ).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("=" * 76)
    print("PHASE 8F DOCUMENTATION CONSISTENCY VALIDATION")
    print("=" * 76)

    for name, passed in checks.items():
        print(f"{name}: {passed}")

    print()
    print(f"Output directory: {OUTPUT_DIR}")

    if not report["passed"]:
        raise SystemExit(
            "FAIL — Milestone 8 documentation is not internally consistent."
        )

    print()
    print(
        "PASS — the release-candidate documentation is current, "
        "internally consistent, checksum-aligned, and honest about "
        "the pending public deployment."
    )


if __name__ == "__main__":
    main()
