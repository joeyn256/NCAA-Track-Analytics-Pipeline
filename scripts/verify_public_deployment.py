#!/usr/bin/env python3
"""Verify the public NCAA Track Analytics Streamlit deployment."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
import json
import sys
from typing import Final
from urllib.parse import urljoin, urlparse

import requests


DEFAULT_APP_URL: Final = (
    "https://ncaa-d1-track-analytics-pipeline-explorer."
    "streamlit.app/"
)
DEFAULT_TIMEOUT_SECONDS: Final = 45.0
USER_AGENT: Final = (
    "NCAA-Track-Analytics-Public-Deployment-Verifier/1.0"
)


class ShellParser(HTMLParser):
    """Extract basic metadata from a Streamlit HTML shell."""

    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.script_sources: list[str] = []
        self.in_title = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)

        if tag == "title":
            self.in_title = True

        if tag == "script":
            source = attributes.get("src")
            if source:
                self.script_sources.append(source)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()


@dataclass(frozen=True)
class VerificationResult:
    """Structured result for a public deployment verification."""

    app_url: str
    final_url: str
    status_code: int
    body_bytes: int
    redirect_count: int
    title: str
    script_asset_url: str
    script_status_code: int
    script_body_bytes: int
    script_content_type: str
    shell_markers: tuple[str, ...]
    blocking_markers: tuple[str, ...]
    health_status_code: int | None
    health_response_kind: str
    passed: bool


def _markers_found(
    text: str,
    markers: tuple[str, ...],
) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(
        marker
        for marker in markers
        if marker in lowered
    )


def _choose_script_asset(
    app_url: str,
    sources: list[str],
) -> str:
    for source in sources:
        candidate = urljoin(app_url, source)
        parsed = urlparse(candidate)

        if parsed.hostname == urlparse(app_url).hostname:
            return candidate

    raise ValueError(
        "No same-host JavaScript asset was found in the app shell."
    )


def verify_public_deployment(
    app_url: str,
    timeout: float,
) -> VerificationResult:
    """Verify the Streamlit shell and a same-host JavaScript asset."""

    normalized_url = app_url.rstrip("/") + "/"
    expected_host = urlparse(normalized_url).hostname

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    shell = session.get(
        normalized_url,
        timeout=(10, timeout),
        allow_redirects=True,
    )
    shell.raise_for_status()

    final_host = urlparse(shell.url).hostname
    if final_host != expected_host:
        raise RuntimeError(
            "Application redirected to an unexpected hostname: "
            f"{final_host!r}"
        )

    parser = ShellParser()
    parser.feed(shell.text)

    shell_markers = _markers_found(
        shell.text,
        (
            "streamlit",
            'id="root"',
            "/-/build/assets/",
        ),
    )

    blocking_markers = _markers_found(
        shell.text,
        (
            "you do not have access",
            "request access",
            "private app",
            "application error",
            "internal server error",
            "app is asleep",
            "wake this app",
        ),
    )

    if not shell_markers:
        raise RuntimeError(
            "Response did not contain recognized Streamlit shell "
            "markers."
        )

    if blocking_markers:
        raise RuntimeError(
            "Response contained blocking or error markers: "
            + ", ".join(blocking_markers)
        )

    script_asset_url = _choose_script_asset(
        normalized_url,
        parser.script_sources,
    )

    script = session.get(
        script_asset_url,
        timeout=(10, timeout),
        allow_redirects=True,
    )
    script.raise_for_status()

    script_content_type = script.headers.get(
        "content-type",
        "",
    )

    script_looks_valid = (
        len(script.content) >= 1_000
        and (
            "javascript" in script_content_type.lower()
            or script_asset_url.lower().endswith(".js")
        )
    )

    if not script_looks_valid:
        raise RuntimeError(
            "Streamlit JavaScript asset response was not valid."
        )

    health_url = urljoin(
        normalized_url,
        "_stcore/health",
    )

    health_status_code: int | None = None
    health_response_kind = "unavailable"

    try:
        health = session.get(
            health_url,
            timeout=(10, timeout),
            allow_redirects=True,
        )
        health_status_code = health.status_code
        health_text = health.text.strip().lower()

        if health_text in {"ok", "healthy", "running"}:
            health_response_kind = "direct-health"
        elif (
            "<!doctype html" in health_text
            and "streamlit" in health_text
        ):
            health_response_kind = "community-cloud-shell"
        else:
            health_response_kind = "unexpected"
    except requests.RequestException:
        health_response_kind = "unavailable"

    return VerificationResult(
        app_url=normalized_url,
        final_url=shell.url,
        status_code=shell.status_code,
        body_bytes=len(shell.content),
        redirect_count=len(shell.history),
        title=parser.title,
        script_asset_url=script_asset_url,
        script_status_code=script.status_code,
        script_body_bytes=len(script.content),
        script_content_type=script_content_type,
        shell_markers=shell_markers,
        blocking_markers=blocking_markers,
        health_status_code=health_status_code,
        health_response_kind=health_response_kind,
        passed=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the public NCAA Track Analytics Streamlit "
            "deployment."
        )
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_APP_URL,
        help="Public Streamlit application URL.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Read timeout in seconds.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the result as JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        result = verify_public_deployment(
            args.url,
            args.timeout,
        )
    except (
        requests.RequestException,
        RuntimeError,
        ValueError,
    ) as exc:
        if args.json:
            print(
                json.dumps(
                    {
                        "passed": False,
                        "error": str(exc),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(
                f"FAIL — public deployment verification failed: "
                f"{exc}",
                file=sys.stderr,
            )
        return 1

    if args.json:
        print(
            json.dumps(
                asdict(result),
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print("PASS — public deployment verification succeeded.")
        print(f"Application:       {result.final_url}")
        print(f"HTTP status:      {result.status_code}")
        print(f"Shell bytes:      {result.body_bytes}")
        print(f"Redirects:        {result.redirect_count}")
        print(f"Script asset:     {result.script_asset_url}")
        print(f"Script status:    {result.script_status_code}")
        print(f"Script bytes:     {result.script_body_bytes}")
        print(
            "Health diagnostic: "
            f"{result.health_response_kind}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
