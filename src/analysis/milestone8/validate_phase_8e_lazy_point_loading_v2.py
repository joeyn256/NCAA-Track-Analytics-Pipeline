#!/usr/bin/env python3
"""Validate lazy point loading across default and heavy point views."""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
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

MANIFEST_PATH: Final = (
    DATABASE_PATH.parent / "deployment_manifest.json"
)

OUTPUT_DIR: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8e_lazy_point_loading_validation"
)

MEMORY_BUDGET_BYTES: Final = int(
    2.5 * 1024**3
)
TRIALS_PER_SCENARIO: Final = 3

SCENARIOS: Final = (
    ("default", None),
    (
        "athlete_contributions",
        "Athlete Contributions",
    ),
    (
        "individual_event",
        "Individual Event",
    ),
)

CHILD_PROGRAM: Final = r"""
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

from streamlit.testing.v1 import AppTest


def current_rss_bytes():
    completed = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(os.getpid())],
        text=True,
        capture_output=True,
        check=True,
    )
    return int(completed.stdout.strip()) * 1024


def maximum_rss_bytes():
    raw = resource.getrusage(
        resource.RUSAGE_SELF
    ).ru_maxrss
    return int(
        raw
        if sys.platform == "darwin"
        else raw * 1024
    )


app_path = Path(
    os.environ["PROFILE_APP_PATH"]
)
requested_view = (
    os.environ.get("PROFILE_POINTS_VIEW")
    or None
)

started = time.perf_counter()
app_test = AppTest.from_file(
    str(app_path)
)
app_test.run(timeout=180)

if requested_view is not None:
    candidates = [
        selectbox
        for selectbox in app_test.selectbox
        if getattr(
            selectbox,
            "label",
            None,
        )
        == "Points view"
    ]

    if len(candidates) != 1:
        raise RuntimeError(
            "Expected exactly one Points view selectbox; "
            f"found {len(candidates)}."
        )

    candidates[0].set_value(
        requested_view
    )
    app_test.run(timeout=180)

cold_seconds = (
    time.perf_counter() - started
)

started = time.perf_counter()
app_test.run(timeout=180)
warm_seconds = (
    time.perf_counter() - started
)

payload = {
    "requested_view": requested_view,
    "cold_seconds": round(
        cold_seconds,
        6,
    ),
    "warm_seconds": round(
        warm_seconds,
        6,
    ),
    "current_rss_bytes": (
        current_rss_bytes()
    ),
    "maximum_rss_bytes": (
        maximum_rss_bytes()
    ),
    "exceptions": len(
        app_test.exception
    ),
    "errors": len(
        app_test.error
    ),
    "warnings": len(
        app_test.warning
    ),
    "dataframes": len(
        app_test.dataframe
    ),
}

print(
    "LAZY_POINT_TRIAL_JSON="
    + json.dumps(
        payload,
        sort_keys=True,
    )
)
"""


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest."""

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(
            8 * 1024 * 1024
        ):
            digest.update(chunk)

    return digest.hexdigest()


def run_trial(
    scenario: str,
    requested_view: str | None,
    trial_number: int,
) -> dict[str, Any]:
    """Run one isolated AppTest scenario."""

    environment = os.environ.copy()
    environment[
        "PROFILE_APP_PATH"
    ] = str(APP_PATH)
    environment[
        "NCAA_TRACK_PUBLIC_DB"
    ] = str(DATABASE_PATH)

    if requested_view is None:
        environment.pop(
            "PROFILE_POINTS_VIEW",
            None,
        )
    else:
        environment[
            "PROFILE_POINTS_VIEW"
        ] = requested_view

    started = time.perf_counter()

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            CHILD_PROGRAM,
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
    )

    process_seconds = (
        time.perf_counter() - started
    )
    payload_line = None

    for line in completed.stdout.splitlines():
        if line.startswith(
            "LAZY_POINT_TRIAL_JSON="
        ):
            payload_line = line.removeprefix(
                "LAZY_POINT_TRIAL_JSON="
            )

    if (
        completed.returncode != 0
        or payload_line is None
    ):
        return {
            "scenario": scenario,
            "trial": trial_number,
            "passed_execution": False,
            "returncode": (
                completed.returncode
            ),
            "process_seconds": round(
                process_seconds,
                6,
            ),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    payload = json.loads(
        payload_line
    )
    payload.update(
        {
            "scenario": scenario,
            "trial": trial_number,
            "passed_execution": True,
            "process_seconds": round(
                process_seconds,
                6,
            ),
            "under_memory_budget": (
                int(
                    payload[
                        "maximum_rss_bytes"
                    ]
                )
                <= MEMORY_BUDGET_BYTES
            ),
            "clean": (
                int(
                    payload["exceptions"]
                )
                == 0
                and int(
                    payload["errors"]
                )
                == 0
                and int(
                    payload["warnings"]
                )
                == 0
            ),
            "stderr": completed.stderr,
        }
    )

    return payload


def summarize(
    trials: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize successful trials."""

    successful = [
        trial
        for trial in trials
        if trial["passed_execution"]
    ]

    if not successful:
        return {
            "successful_trials": 0,
            "all_clean": False,
            "all_under_memory_budget": False,
        }

    memory_values = [
        int(
            trial[
                "maximum_rss_bytes"
            ]
        )
        for trial in successful
    ]

    return {
        "successful_trials": len(
            successful
        ),
        "all_clean": all(
            bool(trial["clean"])
            for trial in successful
        ),
        "all_under_memory_budget": all(
            bool(
                trial[
                    "under_memory_budget"
                ]
            )
            for trial in successful
        ),
        "minimum_rss_bytes": min(
            memory_values
        ),
        "median_rss_bytes": int(
            statistics.median(
                memory_values
            )
        ),
        "maximum_rss_bytes": max(
            memory_values
        ),
    }


def main() -> None:
    """Run source, interaction, memory, and checksum validation."""

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    for path in (
        APP_PATH,
        DATABASE_PATH,
        MANIFEST_PATH,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)

    manifest = json.loads(
        MANIFEST_PATH.read_text(
            encoding="utf-8"
        )
    )
    expected_hash = str(
        manifest["database"]["sha256"]
    )

    hash_before = sha256_file(
        DATABASE_PATH
    )

    source = APP_PATH.read_text(
        encoding="utf-8"
    )
    compile(
        source,
        str(APP_PATH),
        "exec",
    )

    source_checks = {
        "start_marker_once": (
            source.count(
                "# BEGIN MILESTONE 8 LAZY POINT LOADING"
            )
            == 1
        ),
        "end_marker_once": (
            source.count(
                "# END MILESTONE 8 LAZY POINT LOADING"
            )
            == 1
        ),
        "filtered_loader_present": (
            "def load_point_resource_for_model_cohort("
            in source
        ),
        "metadata_loader_present": (
            "def load_point_time_metadata("
            in source
            and "SELECT DISTINCT"
            in source
        ),
        "existing_time_filter_retained": (
            "frame = filter_point_time("
            in source
        ),
        "early_model_cohort_filters_present": (
            "WHERE model_key = ? AND cohort_key = ?"
            in source
        ),
    }

    trials: list[dict[str, Any]] = []

    for scenario, requested_view in SCENARIOS:
        for trial_number in range(
            1,
            TRIALS_PER_SCENARIO + 1,
        ):
            trials.append(
                run_trial(
                    scenario,
                    requested_view,
                    trial_number,
                )
            )

    scenario_summaries = {
        scenario: summarize(
            [
                trial
                for trial in trials
                if trial["scenario"]
                == scenario
            ]
        )
        for scenario, _ in SCENARIOS
    }

    hash_after = sha256_file(
        DATABASE_PATH
    )

    scenario_checks = {}

    for scenario, summary in (
        scenario_summaries.items()
    ):
        scenario_checks[
            f"{scenario}_all_trials_executed"
        ] = (
            summary["successful_trials"]
            == TRIALS_PER_SCENARIO
        )
        scenario_checks[
            f"{scenario}_all_app_tests_clean"
        ] = bool(
            summary["all_clean"]
        )
        scenario_checks[
            f"{scenario}_all_under_2_5_gib"
        ] = bool(
            summary[
                "all_under_memory_budget"
            ]
        )

    hard_checks = {
        **source_checks,
        **scenario_checks,
        "deployment_hash_matches_manifest": (
            hash_before
            == expected_hash
        ),
        "deployment_hash_unchanged": (
            hash_before
            == hash_after
        ),
    }

    report = {
        "memory_budget_bytes": (
            MEMORY_BUDGET_BYTES
        ),
        "trials_per_scenario": (
            TRIALS_PER_SCENARIO
        ),
        "source_checks": (
            source_checks
        ),
        "scenario_summaries": (
            scenario_summaries
        ),
        "trials": trials,
        "database_sha256_before": (
            hash_before
        ),
        "database_sha256_after": (
            hash_after
        ),
        "hard_checks": hard_checks,
        "passed": all(
            hard_checks.values()
        ),
    }

    (
        OUTPUT_DIR
        / "validation_summary.json"
    ).write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("=" * 76)
    print(
        "PHASE 8E LAZY POINT LOADING V2 VALIDATION"
    )
    print("=" * 76)

    for name, passed in (
        hard_checks.items()
    ):
        print(f"{name}: {passed}")

    print()
    print("Scenario memory:")

    for scenario, summary in (
        scenario_summaries.items()
    ):
        if (
            "median_rss_bytes"
            not in summary
        ):
            print(
                f"  {scenario}: "
                "no successful trials"
            )
            continue

        print(
            f"  {scenario}: "
            f"median="
            f"{summary['median_rss_bytes']:,} bytes "
            f"({summary['median_rss_bytes'] / 1024**3:.3f} GiB), "
            f"max="
            f"{summary['maximum_rss_bytes']:,} bytes "
            f"({summary['maximum_rss_bytes'] / 1024**3:.3f} GiB)"
        )

    print()
    print(
        "Deployment hash unchanged: "
        f"{hash_before == hash_after}"
    )
    print(
        f"Output directory: {OUTPUT_DIR}"
    )

    if not report["passed"]:
        raise SystemExit(
            "FAIL — lazy point loading did not pass "
            "every interaction and memory gate."
        )

    print()
    print(
        "PASS — default and heavy point views remain clean "
        "and stay below the 2.5 GiB memory budget."
    )


if __name__ == "__main__":
    main()
