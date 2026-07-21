#!/usr/bin/env python3
"""Run the complete Milestone 8 pre-release regression and hygiene audit."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Final


ROOT: Final = Path(__file__).resolve().parents[3]

OUTPUT_DIR: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8e_release_readiness"
)

PUBLICATION_DIR: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8b_compact_publication"
)

DEPLOYMENT_DB: Final = (
    PUBLICATION_DIR / "ncaa_track_public_explorer_v1.duckdb"
)
DEPLOYMENT_GZIP: Final = Path(str(DEPLOYMENT_DB) + ".gz")
DEPLOYMENT_MANIFEST: Final = (
    PUBLICATION_DIR / "deployment_manifest.json"
)

FROZEN_SOURCES: Final = {
    (
        "milestone6_final_rankings"
    ): (
        ROOT
        / "data/processed/milestone6/final_development_rankings_v1"
        / "phase_6g_final_publication"
        / "final_development_rankings_v1.duckdb",
        (
            "ecbf2c754c9388f60e2373dbf9c260a07098e8a541a966315"
            "4bf96ba9de926da"
        ),
    ),
    (
        "milestone7_seasonal_trends"
    ): (
        ROOT
        / "data/processed/milestone7/seasonal_program_trends_v1"
        / "phase_7d_final_publication"
        / "seasonal_program_trends_v1.duckdb",
        (
            "b5551b43b91da489785b5ced07f548f2a725148d0520adbd1"
            "1c97a589c105ba1"
        ),
    ),
    (
        "milestone7_specialized_rankings"
    ): (
        ROOT
        / "data/processed/milestone7/seasonal_program_trends_v1"
        / "phase_7e2_event_balanced_specialized_rankings"
        / "event_balanced_specialized_rankings_v2.duckdb",
        (
            "353f5c1e328991566045e6edd4fc9551a9fe336e6f3b93e2"
            "9ad94a45486a67a3"
        ),
    ),
}

VALIDATORS: Final = (
    (
        "phase_8b_exact_parity",
        "src/analysis/milestone8/validate_phase_8b_exact_parity.py",
        600,
    ),
    (
        "phase_8c_loader_migration",
        "src/analysis/milestone8/validate_phase_8c_loader_migration.py",
        300,
    ),
    (
        "phase_8c_fresh_bootstrap",
        "src/analysis/milestone8/validate_phase_8c_fresh_bootstrap.py",
        300,
    ),
    (
        "phase_8c_runtime_profile",
        "src/analysis/milestone8/profile_phase_8c_compact_runtime.py",
        300,
    ),
    (
        "phase_8e_lazy_point_loading",
        "src/analysis/milestone8/validate_phase_8e_lazy_point_loading_v2.py",
        900,
    ),
    (
        "phase_8d_deployment_package",
        "src/analysis/milestone8/validate_phase_8d_deployment_package.py",
        180,
    ),
    (
        "phase_8d_recruiter_homepage",
        "src/analysis/milestone8/validate_phase_8d_recruiter_homepage.py",
        300,
    ),
)

PRODUCTION_FILES: Final = (
    ROOT / "src/apps/deployment_data.py",
    ROOT / "src/apps/seasonal_development_explorer.py",
    ROOT / "requirements.txt",
    ROOT / ".streamlit/config.toml",
    ROOT / "deployment/public_deployment_v1.json",
    ROOT / "deployment/STREAMLIT_COMMUNITY_CLOUD.md",
    ROOT / "deployment/streamlit/secrets.toml.example",
    ROOT / "deployment/github/public_deployment_v1_release_notes.md",
    ROOT / "deployment/github/publish_public_deployment_v1.sh",
)

LARGE_TRACKED_FILE_LIMIT: Final = 95 * 1024 * 1024


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest."""

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def run_command(
    arguments: list[str],
    *,
    timeout: int = 120,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run one command from the repository root."""

    completed = subprocess.run(
        arguments,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )

    if check and completed.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(arguments)}\n"
            f"STDOUT:\n{completed.stdout}\n"
            f"STDERR:\n{completed.stderr}"
        )

    return completed


def compile_python_sources() -> dict[str, Any]:
    """Compile the app and all Milestone 8 Python files."""

    paths = [
        ROOT / "src/apps/deployment_data.py",
        ROOT / "src/apps/seasonal_development_explorer.py",
        *sorted(
            (
                ROOT / "src/analysis/milestone8"
            ).glob("*.py")
        ),
    ]

    completed = run_command(
        [
            sys.executable,
            "-m",
            "py_compile",
            *[
                str(path.relative_to(ROOT))
                for path in paths
            ],
        ],
        timeout=180,
    )

    return {
        "passed": completed.returncode == 0,
        "file_count": len(paths),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def run_validator(
    name: str,
    relative_path: str,
    timeout: int,
) -> dict[str, Any]:
    """Run one existing validator and capture its output."""

    path = ROOT / relative_path

    if not path.is_file():
        return {
            "name": name,
            "path": relative_path,
            "passed": False,
            "returncode": None,
            "seconds": 0.0,
            "stdout": "",
            "stderr": f"Missing validator: {path}",
        }

    started = time.perf_counter()

    completed = run_command(
        [sys.executable, relative_path],
        timeout=timeout,
    )

    seconds = time.perf_counter() - started

    return {
        "name": name,
        "path": relative_path,
        "passed": completed.returncode == 0,
        "returncode": completed.returncode,
        "seconds": round(seconds, 6),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def git_repository_checks() -> dict[str, Any]:
    """Inspect branch, formatting, staging, ignored artifacts, and size."""

    branch_result = run_command(
        ["git", "branch", "--show-current"],
    )
    branch = branch_result.stdout.strip()

    diff_check = run_command(
        ["git", "diff", "--check"],
    )

    staged_check = run_command(
        ["git", "diff", "--cached", "--quiet"],
    )

    status = run_command(
        ["git", "status", "--porcelain=v1"],
    )

    tracked = run_command(
        ["git", "ls-files"],
        check=True,
    ).stdout.splitlines()

    oversized_tracked: list[dict[str, Any]] = []

    for relative in tracked:
        path = ROOT / relative

        if not path.is_file():
            continue

        size = path.stat().st_size

        if size > LARGE_TRACKED_FILE_LIMIT:
            oversized_tracked.append(
                {
                    "path": relative,
                    "size_bytes": size,
                }
            )

    ignored_artifacts: dict[str, Any] = {}

    for label, path in (
        ("deployment_database", DEPLOYMENT_DB),
        ("deployment_gzip", DEPLOYMENT_GZIP),
    ):
        result = run_command(
            [
                "git",
                "check-ignore",
                "-v",
                str(path.relative_to(ROOT)),
            ],
        )
        ignored_artifacts[label] = {
            "passed": result.returncode == 0,
            "detail": result.stdout.strip(),
        }

    local_tag = run_command(
        ["git", "tag", "--list", "public-deployment-v1"],
    ).stdout.strip()

    return {
        "branch": branch,
        "branch_is_milestone_8": branch == "milestone-8",
        "diff_check_passed": diff_check.returncode == 0,
        "diff_check_stdout": diff_check.stdout,
        "diff_check_stderr": diff_check.stderr,
        "nothing_staged": staged_check.returncode == 0,
        "status_porcelain": status.stdout.splitlines(),
        "tracked_file_count": len(tracked),
        "oversized_tracked_files": oversized_tracked,
        "no_oversized_tracked_files": not oversized_tracked,
        "ignored_artifacts": ignored_artifacts,
        "deployment_artifacts_ignored": all(
            bool(item["passed"])
            for item in ignored_artifacts.values()
        ),
        "release_tag_absent_locally": not bool(local_tag),
    }


def security_and_portability_checks() -> dict[str, Any]:
    """Check secrets, local paths, and production-file availability."""

    missing_files = [
        str(path.relative_to(ROOT))
        for path in PRODUCTION_FILES
        if not path.is_file()
    ]

    local_secrets = ROOT / ".streamlit/secrets.toml"

    forbidden_fragments = (
        "/Users/joeyn256",
        "/Users/",
        "MacBookPro",
    )

    forbidden_hits: list[dict[str, Any]] = []

    for path in PRODUCTION_FILES:
        if not path.is_file():
            continue

        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        for fragment in forbidden_fragments:
            if fragment in text:
                forbidden_hits.append(
                    {
                        "path": str(
                            path.relative_to(ROOT)
                        ),
                        "fragment": fragment,
                    }
                )

    secret_like_patterns = (
        "ghp_",
        "github_pat_",
        "sk-",
        "AKIA",
        "BEGIN PRIVATE KEY",
    )

    secret_hits: list[dict[str, Any]] = []

    for path in PRODUCTION_FILES:
        if not path.is_file():
            continue

        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        for pattern in secret_like_patterns:
            if pattern in text:
                secret_hits.append(
                    {
                        "path": str(
                            path.relative_to(ROOT)
                        ),
                        "pattern": pattern,
                    }
                )

    return {
        "missing_production_files": missing_files,
        "all_production_files_present": not missing_files,
        "local_secrets_file_absent": not local_secrets.exists(),
        "forbidden_local_path_hits": forbidden_hits,
        "no_forbidden_local_paths": not forbidden_hits,
        "secret_like_hits": secret_hits,
        "no_secret_like_values": not secret_hits,
    }


def artifact_checks() -> dict[str, Any]:
    """Verify frozen-source and deployment-publication checksums."""

    missing: list[str] = []
    frozen_results: dict[str, Any] = {}

    for label, (path, expected_hash) in (
        FROZEN_SOURCES.items()
    ):
        if not path.is_file():
            missing.append(
                str(path.relative_to(ROOT))
            )
            frozen_results[label] = {
                "passed": False,
                "path": str(
                    path.relative_to(ROOT)
                ),
                "expected_sha256": expected_hash,
                "observed_sha256": None,
            }
            continue

        observed_hash = sha256_file(path)

        frozen_results[label] = {
            "passed": observed_hash == expected_hash,
            "path": str(path.relative_to(ROOT)),
            "expected_sha256": expected_hash,
            "observed_sha256": observed_hash,
        }

    for path in (
        DEPLOYMENT_DB,
        DEPLOYMENT_GZIP,
        DEPLOYMENT_MANIFEST,
    ):
        if not path.is_file():
            missing.append(
                str(path.relative_to(ROOT))
            )

    deployment: dict[str, Any] = {
        "passed": False,
    }

    if not any(
        path in missing
        for path in (
            str(DEPLOYMENT_DB.relative_to(ROOT)),
            str(DEPLOYMENT_GZIP.relative_to(ROOT)),
            str(DEPLOYMENT_MANIFEST.relative_to(ROOT)),
        )
    ):
        manifest = json.loads(
            DEPLOYMENT_MANIFEST.read_text(
                encoding="utf-8"
            )
        )

        database_hash = sha256_file(
            DEPLOYMENT_DB
        )
        gzip_hash = sha256_file(
            DEPLOYMENT_GZIP
        )

        expected_database_hash = str(
            manifest["database"]["sha256"]
        )
        expected_gzip_hash = str(
            manifest["gzip"]["sha256"]
        )

        deployment = {
            "passed": (
                database_hash
                == expected_database_hash
                and gzip_hash
                == expected_gzip_hash
            ),
            "database_sha256": database_hash,
            "expected_database_sha256": (
                expected_database_hash
            ),
            "gzip_sha256": gzip_hash,
            "expected_gzip_sha256": (
                expected_gzip_hash
            ),
            "database_size_bytes": (
                DEPLOYMENT_DB.stat().st_size
            ),
            "gzip_size_bytes": (
                DEPLOYMENT_GZIP.stat().st_size
            ),
        }

    return {
        "missing_artifacts": missing,
        "frozen_sources": frozen_results,
        "all_frozen_hashes_pass": all(
            bool(result["passed"])
            for result in frozen_results.values()
        ),
        "deployment_publication": deployment,
        "deployment_hashes_pass": bool(
            deployment["passed"]
        ),
    }


def markdown_report(
    summary: dict[str, Any],
) -> str:
    """Render a compact human-readable release-readiness report."""

    lines = [
        "# Milestone 8 pre-release readiness",
        "",
        f"- Overall pass: `{summary['passed']}`",
        f"- Completed validators: "
        f"`{sum(1 for item in summary['validators'] if item['passed'])}"
        f"/{len(summary['validators'])}`",
        f"- Branch: `{summary['git']['branch']}`",
        f"- Nothing staged: `{summary['git']['nothing_staged']}`",
        f"- Diff check passed: `{summary['git']['diff_check_passed']}`",
        f"- Frozen hashes passed: "
        f"`{summary['artifacts']['all_frozen_hashes_pass']}`",
        f"- Deployment hashes passed: "
        f"`{summary['artifacts']['deployment_hashes_pass']}`",
        "",
        "## Validators",
        "",
        "| Validator | Passed | Seconds |",
        "|---|---:|---:|",
    ]

    for item in summary["validators"]:
        lines.append(
            f"| {item['name']} | "
            f"{'Yes' if item['passed'] else 'No'} | "
            f"{item['seconds']:.3f} |"
        )

    lines.extend(
        [
            "",
            "## Repository changes awaiting final documentation and commit",
            "",
        ]
    )

    for line in summary["git"]["status_porcelain"]:
        lines.append(f"- `{line}`")

    lines.extend(
        [
            "",
            "## Hard checks",
            "",
        ]
    )

    for name, passed in summary[
        "hard_checks"
    ].items():
        lines.append(
            f"- {'PASS' if passed else 'FAIL'} — `{name}`"
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    """Run the complete local pre-release gate."""

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    compile_result = compile_python_sources()
    git_result = git_repository_checks()
    security_result = (
        security_and_portability_checks()
    )
    artifact_result = artifact_checks()

    validator_results = [
        run_validator(name, path, timeout)
        for name, path, timeout in VALIDATORS
    ]

    hard_checks = {
        "python_compilation_passed": bool(
            compile_result["passed"]
        ),
        "all_regression_validators_passed": all(
            bool(item["passed"])
            for item in validator_results
        ),
        "working_branch_is_milestone_8": bool(
            git_result["branch_is_milestone_8"]
        ),
        "git_diff_check_passed": bool(
            git_result["diff_check_passed"]
        ),
        "nothing_is_staged": bool(
            git_result["nothing_staged"]
        ),
        "no_oversized_tracked_files": bool(
            git_result[
                "no_oversized_tracked_files"
            ]
        ),
        "deployment_artifacts_are_ignored": bool(
            git_result[
                "deployment_artifacts_ignored"
            ]
        ),
        "release_tag_absent_locally": bool(
            git_result[
                "release_tag_absent_locally"
            ]
        ),
        "all_production_files_present": bool(
            security_result[
                "all_production_files_present"
            ]
        ),
        "local_secrets_file_absent": bool(
            security_result[
                "local_secrets_file_absent"
            ]
        ),
        "no_forbidden_local_paths": bool(
            security_result[
                "no_forbidden_local_paths"
            ]
        ),
        "no_secret_like_values": bool(
            security_result[
                "no_secret_like_values"
            ]
        ),
        "frozen_source_hashes_pass": bool(
            artifact_result[
                "all_frozen_hashes_pass"
            ]
        ),
        "deployment_publication_hashes_pass": bool(
            artifact_result[
                "deployment_hashes_pass"
            ]
        ),
    }

    summary = {
        "publication_version": (
            "public_deployment_v1"
        ),
        "compile": compile_result,
        "validators": validator_results,
        "git": git_result,
        "security_and_portability": (
            security_result
        ),
        "artifacts": artifact_result,
        "hard_checks": hard_checks,
        "passed": all(hard_checks.values()),
    }

    (
        OUTPUT_DIR / "release_readiness.json"
    ).write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    (
        OUTPUT_DIR / "release_readiness.md"
    ).write_text(
        markdown_report(summary),
        encoding="utf-8",
    )

    for item in validator_results:
        log_path = (
            OUTPUT_DIR
            / f"{item['name']}.log"
        )
        log_path.write_text(
            "STDOUT\n"
            "======\n"
            + item["stdout"]
            + "\n\nSTDERR\n"
            "======\n"
            + item["stderr"],
            encoding="utf-8",
        )

    print("=" * 76)
    print("PHASE 8E FULL RELEASE-READINESS AUDIT")
    print("=" * 76)

    for name, passed in hard_checks.items():
        print(f"{name}: {passed}")

    print()
    print("Regression validators:")

    for item in validator_results:
        print(
            f"  {item['name']}: "
            f"{item['passed']} "
            f"({item['seconds']:.3f}s)"
        )

    print()
    print(
        "Working-tree entries: "
        f"{len(git_result['status_porcelain'])}"
    )
    print(
        "Tracked files over 95 MiB: "
        f"{len(git_result['oversized_tracked_files'])}"
    )
    print(
        "Frozen source hashes passed: "
        f"{artifact_result['all_frozen_hashes_pass']}"
    )
    print(
        "Deployment hashes passed: "
        f"{artifact_result['deployment_hashes_pass']}"
    )
    print(f"Output directory: {OUTPUT_DIR}")

    if not summary["passed"]:
        print()
        print(
            "Inspect release_readiness.json and the individual "
            "validator logs for the failing gate."
        )
        raise SystemExit(
            "FAIL — Milestone 8 is not yet ready for final "
            "documentation and commit."
        )

    print()
    print(
        "PASS — all Milestone 8 regression, checksum, portability, "
        "security, and repository-hygiene gates passed."
    )
    print(
        "The branch is ready for final documentation review; "
        "nothing was staged, committed, tagged, pushed, or released."
    )


if __name__ == "__main__":
    main()
