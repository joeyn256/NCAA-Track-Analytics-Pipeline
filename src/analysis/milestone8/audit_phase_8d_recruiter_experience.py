#!/usr/bin/env python3
"""Audit the first-load recruiter experience of the Streamlit explorer."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Final

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

OUTPUT_DIR: Final = (
    ROOT
    / "data/processed/milestone8/public_deployment_v1"
    / "phase_8d_recruiter_experience_audit"
)

ELEMENT_TYPES: Final = (
    "title",
    "header",
    "subheader",
    "caption",
    "markdown",
    "text",
    "info",
    "success",
    "warning",
    "error",
    "metric",
    "button",
    "link_button",
    "selectbox",
    "multiselect",
    "radio",
    "checkbox",
    "toggle",
    "slider",
    "tabs",
    "dataframe",
    "table",
    "altair_chart",
    "plotly_chart",
    "line_chart",
    "bar_chart",
    "area_chart",
)

EARLY_TEXT_LIMIT: Final = 18


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest."""

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def normalize_text(value: Any) -> str:
    """Return compact printable text for an AppTest element value."""

    if value is None:
        return ""

    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()

    if isinstance(value, (list, tuple)):
        return " | ".join(
            normalize_text(item)
            for item in value
            if normalize_text(item)
        )

    return str(value).strip()


def element_snapshot(
    element_type: str,
    element: Any,
    index: int,
) -> dict[str, Any]:
    """Extract stable, useful fields from one AppTest element."""

    fields = (
        "value",
        "label",
        "body",
        "help",
        "url",
        "icon",
        "key",
        "options",
    )

    snapshot: dict[str, Any] = {
        "element_type": element_type,
        "index": index,
    }

    for field in fields:
        if not hasattr(element, field):
            continue

        try:
            value = getattr(element, field)
        except Exception:
            continue

        normalized = normalize_text(value)

        if normalized:
            snapshot[field] = normalized

    return snapshot


def collect_elements(app_test: AppTest) -> list[dict[str, Any]]:
    """Collect supported visible elements in a deterministic order."""

    rows: list[dict[str, Any]] = []

    for element_type in ELEMENT_TYPES:
        collection = getattr(
            app_test,
            element_type,
            None,
        )

        if collection is None:
            continue

        try:
            elements = list(collection)
        except TypeError:
            continue

        for index, element in enumerate(elements):
            rows.append(
                element_snapshot(
                    element_type,
                    element,
                    index,
                )
            )

    return rows


def source_inventory(source: str) -> dict[str, Any]:
    """Inventory page-config, links, and visible Streamlit calls."""

    tree = ast.parse(
        source,
        filename=str(APP_PATH),
    )

    streamlit_calls: list[dict[str, Any]] = []
    urls = sorted(
        set(
            re.findall(
                r"https?://[^\s'\"<>)]*",
                source,
            )
        )
    )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        function = node.func
        dotted_name = ""

        if isinstance(function, ast.Attribute):
            parts: list[str] = []
            cursor: ast.expr = function

            while isinstance(cursor, ast.Attribute):
                parts.append(cursor.attr)
                cursor = cursor.value

            if isinstance(cursor, ast.Name):
                parts.append(cursor.id)

            dotted_name = ".".join(
                reversed(parts)
            )

        elif isinstance(function, ast.Name):
            dotted_name = function.id

        if not dotted_name.startswith("st."):
            continue

        streamlit_calls.append(
            {
                "line_number": getattr(
                    node,
                    "lineno",
                    None,
                ),
                "call": dotted_name,
                "argument_count": len(node.args),
                "keyword_names": [
                    keyword.arg
                    for keyword in node.keywords
                    if keyword.arg
                ],
            }
        )

    return {
        "line_count": len(source.splitlines()),
        "urls": urls,
        "streamlit_call_count": len(
            streamlit_calls
        ),
        "streamlit_calls": streamlit_calls,
        "has_page_config": (
            "st.set_page_config" in source
        ),
        "has_github_url": any(
            "github.com" in url.lower()
            for url in urls
        ),
        "has_link_button": (
            "st.link_button" in source
        ),
    }


def text_from_snapshot(
    row: dict[str, Any],
) -> str:
    """Choose the most meaningful printable text for one row."""

    for field in (
        "value",
        "label",
        "body",
        "url",
        "options",
    ):
        text = normalize_text(row.get(field))

        if text:
            return text

    return ""


def contains_any(
    text: str,
    patterns: tuple[str, ...],
) -> bool:
    """Return whether lowercased text contains any supplied pattern."""

    lowered = text.lower()
    return any(pattern in lowered for pattern in patterns)


def score_recruiter_experience(
    elements: list[dict[str, Any]],
    source_details: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """Score concrete recruiter-facing first-load characteristics."""

    visible_texts = [
        text_from_snapshot(row)
        for row in elements
        if text_from_snapshot(row)
    ]

    early_text = "\n".join(
        visible_texts[:EARLY_TEXT_LIMIT]
    )
    all_text = "\n".join(visible_texts)

    checks = [
        {
            "dimension": "clear_project_purpose",
            "passed": (
                contains_any(
                    early_text,
                    (
                        "athlete development",
                        "program development",
                        "ncaa division i",
                    ),
                )
                and contains_any(
                    early_text,
                    (
                        "rank",
                        "compare",
                        "explore",
                    ),
                )
            ),
            "weight": 15,
            "recommendation": (
                "Open with a one-sentence explanation of what the "
                "explorer measures and who it is for."
            ),
        },
        {
            "dimension": "official_model_prominent",
            "passed": contains_any(
                early_text,
                (
                    "enhanced balanced production",
                    "official model",
                ),
            ),
            "weight": 15,
            "recommendation": (
                "Label Enhanced Balanced Production as the official "
                "ranking model above the first interactive controls."
            ),
        },
        {
            "dimension": "scale_and_technical_depth_visible",
            "passed": (
                bool(
                    re.search(
                        r"\b(6[,.]?5\d{2}[,.]?\d{3}|"
                        r"2[,.]?9\d{2}[,.]?\d{3}|"
                        r"193[,.]?\d{3}|"
                        r"81 tables|"
                        r"millions?)\b",
                        all_text,
                        flags=re.IGNORECASE,
                    )
                )
            ),
            "weight": 15,
            "recommendation": (
                "Show concise scale metrics such as 6.59M performances, "
                "193K athletes, and 81 deployment tables."
            ),
        },
        {
            "dimension": "guided_first_action",
            "passed": contains_any(
                early_text,
                (
                    "start here",
                    "try this",
                    "how to use",
                    "choose",
                    "select a",
                ),
            ),
            "weight": 10,
            "recommendation": (
                "Give recruiters a two-step suggested path through the "
                "app instead of requiring them to infer the workflow."
            ),
        },
        {
            "dimension": "github_or_project_link",
            "passed": (
                source_details["has_github_url"]
                or source_details[
                    "has_link_button"
                ]
            ),
            "weight": 15,
            "recommendation": (
                "Add a visible GitHub/project link near the top of the "
                "page or in an About section."
            ),
        },
        {
            "dimension": "methodology_context",
            "passed": contains_any(
                all_text,
                (
                    "methodology",
                    "how the model works",
                    "model design",
                    "event-balanced",
                    "human limit",
                ),
            ),
            "weight": 10,
            "recommendation": (
                "Include a short methodology summary and a clear route "
                "to deeper model documentation."
            ),
        },
        {
            "dimension": "limitations_or_scope",
            "passed": contains_any(
                all_text,
                (
                    "limitation",
                    "scope",
                    "unavailable",
                    "not available",
                    "coverage",
                    "2020 outdoor",
                ),
            ),
            "weight": 10,
            "recommendation": (
                "Surface scope and known limitations, including explicit "
                "unavailable analyses and 2020 Outdoor handling."
            ),
        },
        {
            "dimension": "immediate_visual_or_table",
            "passed": any(
                row["element_type"]
                in {
                    "dataframe",
                    "table",
                    "altair_chart",
                    "plotly_chart",
                    "line_chart",
                    "bar_chart",
                    "area_chart",
                }
                for row in elements
            ),
            "weight": 10,
            "recommendation": (
                "Ensure the default view immediately displays a useful "
                "ranking table or chart."
            ),
        },
    ]

    score = sum(
        int(check["weight"])
        for check in checks
        if bool(check["passed"])
    )

    return checks, score


def markdown_report(
    summary: dict[str, Any],
) -> str:
    """Render a human-readable audit report."""

    lines = [
        "# Phase 8D recruiter-experience audit",
        "",
        f"- Technical pass: `{summary['technical_passed']}`",
        f"- Recruiter-readiness score: **{summary['recruiter_score']}/100**",
        f"- AppTest seconds: `{summary['app_test']['seconds']}`",
        f"- Exceptions: `{summary['app_test']['exceptions']}`",
        f"- Errors: `{summary['app_test']['errors']}`",
        f"- Warnings: `{summary['app_test']['warnings']}`",
        "",
        "## First visible text",
        "",
    ]

    for index, text in enumerate(
        summary["first_visible_text"],
        start=1,
    ):
        lines.append(f"{index}. {text}")

    lines.extend(
        [
            "",
            "## Recruiter checks",
            "",
            "| Dimension | Passed | Weight | Recommendation |",
            "|---|---:|---:|---|",
        ]
    )

    for check in summary["recruiter_checks"]:
        lines.append(
            "| "
            + str(check["dimension"])
            + " | "
            + ("Yes" if check["passed"] else "No")
            + " | "
            + str(check["weight"])
            + " | "
            + str(check["recommendation"])
            + " |"
        )

    lines.extend(
        [
            "",
            "## Element counts",
            "",
            "| Element | Count |",
            "|---|---:|",
        ]
    )

    for element_type, count in sorted(
        summary["element_counts"].items()
    ):
        lines.append(
            f"| {element_type} | {count} |"
        )

    lines.extend(
        [
            "",
            "## Recommended next changes",
            "",
        ]
    )

    failed = [
        check
        for check in summary[
            "recruiter_checks"
        ]
        if not check["passed"]
    ]

    if failed:
        for check in failed:
            lines.append(
                "- " + str(
                    check["recommendation"]
                )
            )
    else:
        lines.append(
            "- No automated recruiter-experience gaps were detected."
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    """Run a technical and recruiter-facing first-load audit."""

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
        MANIFEST_PATH.read_text(encoding="utf-8")
    )

    expected_hash = str(
        manifest["database"]["sha256"]
    )
    observed_hash = sha256_file(
        DATABASE_PATH
    )

    if observed_hash != expected_hash:
        raise RuntimeError(
            "Deployment database checksum does not match manifest."
        )

    source = APP_PATH.read_text(
        encoding="utf-8"
    )
    source_details = source_inventory(
        source
    )

    previous_database = os.environ.get(
        "NCAA_TRACK_PUBLIC_DB"
    )
    os.environ[
        "NCAA_TRACK_PUBLIC_DB"
    ] = str(DATABASE_PATH)

    try:
        started = time.perf_counter()
        app_test = AppTest.from_file(
            str(APP_PATH)
        )
        app_test.run(timeout=180)
        seconds = time.perf_counter() - started

        elements = collect_elements(
            app_test
        )

        app_test_details = {
            "seconds": round(
                seconds,
                6,
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

    element_counts: dict[str, int] = {}

    for row in elements:
        element_type = str(
            row["element_type"]
        )
        element_counts[element_type] = (
            element_counts.get(
                element_type,
                0,
            )
            + 1
        )

    visible_text = [
        text_from_snapshot(row)
        for row in elements
        if text_from_snapshot(row)
    ]

    recruiter_checks, recruiter_score = (
        score_recruiter_experience(
            elements,
            source_details,
        )
    )

    technical_checks = {
        "app_test_has_no_exceptions": (
            app_test_details[
                "exceptions"
            ]
            == 0
        ),
        "app_test_has_no_errors": (
            app_test_details["errors"]
            == 0
        ),
        "page_config_present": (
            source_details[
                "has_page_config"
            ]
        ),
        "title_present": (
            element_counts.get(
                "title",
                0,
            )
            > 0
        ),
        "default_output_present": any(
            element_counts.get(
                element_type,
                0,
            )
            > 0
            for element_type in (
                "dataframe",
                "table",
                "altair_chart",
                "plotly_chart",
                "line_chart",
                "bar_chart",
                "area_chart",
            )
        ),
        "deployment_hash_matches": (
            observed_hash
            == expected_hash
        ),
    }

    summary = {
        "publication_version": (
            "public_deployment_v1"
        ),
        "app_test": app_test_details,
        "technical_checks": technical_checks,
        "technical_passed": all(
            technical_checks.values()
        ),
        "recruiter_score": recruiter_score,
        "recruiter_checks": (
            recruiter_checks
        ),
        "first_visible_text": (
            visible_text[
                :EARLY_TEXT_LIMIT
            ]
        ),
        "element_counts": (
            element_counts
        ),
        "elements": elements,
        "source_inventory": (
            source_details
        ),
        "database_sha256": (
            observed_hash
        ),
    }

    (
        OUTPUT_DIR / "audit_summary.json"
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
        OUTPUT_DIR
        / "recruiter_experience_audit.md"
    ).write_text(
        markdown_report(summary),
        encoding="utf-8",
    )

    print("=" * 76)
    print("PHASE 8D RECRUITER-EXPERIENCE AUDIT")
    print("=" * 76)

    for name, passed in technical_checks.items():
        print(f"{name}: {passed}")

    print()
    print(
        "Recruiter-readiness score: "
        f"{recruiter_score}/100"
    )
    print(
        "Visible elements collected: "
        f"{len(elements):,}"
    )
    print(
        "AppTest seconds: "
        f"{app_test_details['seconds']:.6f}"
    )
    print(
        "AppTest exceptions: "
        f"{app_test_details['exceptions']}"
    )
    print(
        "AppTest errors: "
        f"{app_test_details['errors']}"
    )
    print(
        "AppTest warnings: "
        f"{app_test_details['warnings']}"
    )
    print(f"Output directory: {OUTPUT_DIR}")
    print()
    print("First visible text:")

    for index, text in enumerate(
        visible_text[:EARLY_TEXT_LIMIT],
        start=1,
    ):
        print(f"  {index:02d}. {text}")

    print()
    print("Recruiter checks:")

    for check in recruiter_checks:
        print(
            f"  {check['dimension']}: "
            f"{check['passed']} "
            f"({check['weight']} points)"
        )

    if not summary["technical_passed"]:
        raise SystemExit(
            "FAIL — the default application view did not pass "
            "the technical recruiter-audit gate."
        )

    print()
    print(
        "PASS — technical recruiter audit completed. "
        "Review the score and identified UX gaps before patching."
    )


if __name__ == "__main__":
    main()
