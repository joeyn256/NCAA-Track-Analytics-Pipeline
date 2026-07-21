"""Deterministic tests for the public deployment verifier."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
import sys

import pytest
import requests


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_public_deployment.py"
MODULE_NAME = "verify_public_deployment_under_test"

APP_URL = "https://example.streamlit.app/"
ASSET_URL = "https://example.streamlit.app/-/build/assets/index.js"
HEALTH_URL = "https://example.streamlit.app/_stcore/health"

STREAMLIT_SHELL = """<!doctype html>
<html>
  <head>
    <title>Example Explorer</title>
    <script src="/-/build/assets/index.js"></script>
  </head>
  <body>
    <div id="root"></div>
    <span>Streamlit</span>
  </body>
</html>
"""


def load_verifier() -> ModuleType:
    """Load the script as an isolated importable module."""

    sys.modules.pop(MODULE_NAME, None)

    spec = importlib.util.spec_from_file_location(
        MODULE_NAME,
        SCRIPT_PATH,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load deployment verifier.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)

    return module


class FakeResponse:
    """Minimal requests.Response substitute for deterministic tests."""

    def __init__(
        self,
        url: str,
        *,
        status_code: int = 200,
        text: str = "",
        content_type: str = "text/html; charset=utf-8",
        history: list[Any] | None = None,
    ) -> None:
        self.url = url
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"content-type": content_type}
        self.history = history or []

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {self.status_code}",
            )


class FakeSession:
    """Return predefined responses for requested URLs."""

    def __init__(
        self,
        responses: dict[str, FakeResponse | Exception],
    ) -> None:
        self.responses = responses
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []

    def get(
        self,
        url: str,
        **_: Any,
    ) -> FakeResponse:
        self.calls.append(url)

        response = self.responses[url]

        if isinstance(response, Exception):
            raise response

        return response


def install_fake_session(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    responses: dict[str, FakeResponse | Exception],
) -> FakeSession:
    session = FakeSession(responses)

    monkeypatch.setattr(
        module.requests,
        "Session",
        lambda: session,
    )

    return session


def test_shell_parser_extracts_title_and_scripts() -> None:
    module = load_verifier()
    parser = module.ShellParser()

    parser.feed(STREAMLIT_SHELL)

    assert parser.title == "Example Explorer"
    assert parser.script_sources == [
        "/-/build/assets/index.js",
    ]


def test_choose_script_asset_requires_same_host() -> None:
    module = load_verifier()

    selected = module._choose_script_asset(
        APP_URL,
        [
            "https://cdn.example.com/external.js",
            "/-/build/assets/index.js",
        ],
    )

    assert selected == ASSET_URL

    with pytest.raises(
        ValueError,
        match="No same-host JavaScript asset",
    ):
        module._choose_script_asset(
            APP_URL,
            ["https://cdn.example.com/external.js"],
        )


def test_verify_community_cloud_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_verifier()

    session = install_fake_session(
        monkeypatch,
        module,
        {
            APP_URL: FakeResponse(
                APP_URL,
                text=STREAMLIT_SHELL,
                history=[
                    FakeResponse(
                        "https://share.streamlit.io/-/auth/app",
                        status_code=303,
                    )
                ],
            ),
            ASSET_URL: FakeResponse(
                ASSET_URL,
                text="x" * 1_500,
                content_type="text/javascript",
            ),
            HEALTH_URL: FakeResponse(
                HEALTH_URL,
                text=STREAMLIT_SHELL,
            ),
        },
    )

    result = module.verify_public_deployment(
        APP_URL,
        5.0,
    )

    assert result.passed is True
    assert result.status_code == 200
    assert result.redirect_count == 1
    assert result.title == "Example Explorer"
    assert result.script_asset_url == ASSET_URL
    assert result.script_body_bytes == 1_500
    assert result.health_status_code == 200
    assert (
        result.health_response_kind
        == "community-cloud-shell"
    )
    assert result.blocking_markers == ()
    assert session.calls == [
        APP_URL,
        ASSET_URL,
        HEALTH_URL,
    ]


def test_verify_direct_health_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_verifier()

    install_fake_session(
        monkeypatch,
        module,
        {
            APP_URL: FakeResponse(
                APP_URL,
                text=STREAMLIT_SHELL,
            ),
            ASSET_URL: FakeResponse(
                ASSET_URL,
                text="x" * 1_500,
                content_type="application/javascript",
            ),
            HEALTH_URL: FakeResponse(
                HEALTH_URL,
                text="ok",
                content_type="text/plain",
            ),
        },
    )

    result = module.verify_public_deployment(
        APP_URL,
        5.0,
    )

    assert result.health_response_kind == "direct-health"


def test_verify_rejects_unexpected_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_verifier()

    install_fake_session(
        monkeypatch,
        module,
        {
            APP_URL: FakeResponse(
                "https://unexpected.example/",
                text=STREAMLIT_SHELL,
            ),
        },
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected hostname",
    ):
        module.verify_public_deployment(
            APP_URL,
            5.0,
        )


def test_verify_rejects_blocking_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_verifier()

    blocked_shell = (
        STREAMLIT_SHELL
        + "<p>You do not have access to this private app.</p>"
    )

    install_fake_session(
        monkeypatch,
        module,
        {
            APP_URL: FakeResponse(
                APP_URL,
                text=blocked_shell,
            ),
        },
    )

    with pytest.raises(
        RuntimeError,
        match="blocking or error markers",
    ):
        module.verify_public_deployment(
            APP_URL,
            5.0,
        )


def test_verify_rejects_invalid_script_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_verifier()

    install_fake_session(
        monkeypatch,
        module,
        {
            APP_URL: FakeResponse(
                APP_URL,
                text=STREAMLIT_SHELL,
            ),
            ASSET_URL: FakeResponse(
                ASSET_URL,
                text="too small",
                content_type="text/javascript",
            ),
        },
    )

    with pytest.raises(
        RuntimeError,
        match="JavaScript asset response was not valid",
    ):
        module.verify_public_deployment(
            APP_URL,
            5.0,
        )


def test_main_json_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_verifier()

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: SimpleNamespace(
            url=APP_URL,
            timeout=5.0,
            json=True,
        ),
    )

    def fail_verification(
        app_url: str,
        timeout: float,
    ) -> None:
        del app_url
        del timeout
        raise RuntimeError("synthetic verification failure")

    monkeypatch.setattr(
        module,
        "verify_public_deployment",
        fail_verification,
    )

    assert module.main() == 1

    output = json.loads(capsys.readouterr().out)

    assert output == {
        "error": "synthetic verification failure",
        "passed": False,
    }
