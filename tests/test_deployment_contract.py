from __future__ import annotations

import ast
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR_PATH = ROOT / "deployment/public_deployment_v1.json"
LOADER_PATH = ROOT / "src/apps/deployment_data.py"
README_PATH = ROOT / "README.md"
STREAMLIT_GUIDE_PATH = ROOT / "deployment/STREAMLIT_COMMUNITY_CLOUD.md"
PUBLISH_SCRIPT_PATH = (
    ROOT / "deployment/github/publish_public_deployment_v1.sh"
)


def load_descriptor() -> dict[str, object]:
    return json.loads(DESCRIPTOR_PATH.read_text())


def literal_python_constants(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text())
    constants: dict[str, object] = {}

    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name):
            continue
        try:
            constants[node.target.id] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            continue

    return constants


def shell_assignment(source: str, name: str) -> str:
    match = re.search(
        rf'^{re.escape(name)}="([^"]+)"$',
        source,
        flags=re.MULTILINE,
    )
    assert match is not None, f"Missing shell assignment: {name}"
    return match.group(1)


def test_descriptor_urls_and_referenced_paths() -> None:
    descriptor = load_descriptor()
    artifact = descriptor["artifact"]
    github = descriptor["github"]
    streamlit = descriptor["streamlit"]

    assert descriptor["publication_version"] == "public_deployment_v1"
    assert artifact["filename"].endswith(".duckdb.gz")
    assert github["slug"] == (
        f'{github["owner"]}/{github["repository"]}'
    )
    assert github["release_page"] == (
        f'{github["origin"]}/releases/tag/{github["release_tag"]}'
    )
    assert github["release_asset_url"] == (
        f'{github["origin"]}/releases/download/'
        f'{github["release_tag"]}/{artifact["filename"]}'
    )
    assert streamlit["python_version"] == "3.12"

    for key in (
        "config_path",
        "entrypoint",
        "secrets_example_path",
    ):
        assert (ROOT / streamlit[key]).is_file()


def test_loader_and_streamlit_secrets_match_descriptor() -> None:
    descriptor = load_descriptor()
    artifact = descriptor["artifact"]
    github = descriptor["github"]
    streamlit = descriptor["streamlit"]
    constants = literal_python_constants(LOADER_PATH)

    assert constants["DATABASE_FILENAME"] == (
        artifact["filename"].removesuffix(".gz")
    )
    assert constants["EXPECTED_DATABASE_SHA256"] == (
        artifact["database_sha256"]
    )
    assert constants["EXPECTED_GZIP_SHA256"] == artifact["sha256"]

    secrets_text = (
        ROOT / streamlit["secrets_example_path"]
    ).read_text()
    assert (
        f'NCAA_TRACK_PUBLIC_DB_URL = '
        f'"{github["release_asset_url"]}"'
    ) in secrets_text


def test_release_files_and_public_docs_match_descriptor() -> None:
    descriptor = load_descriptor()
    artifact = descriptor["artifact"]
    github = descriptor["github"]

    publish_script = PUBLISH_SCRIPT_PATH.read_text()
    assert shell_assignment(
        publish_script,
        "TAG",
    ) == github["release_tag"]
    assert shell_assignment(
        publish_script,
        "ASSET",
    ) == artifact["path"]

    notes_path = ROOT / shell_assignment(
        publish_script,
        "NOTES",
    )
    assert notes_path.is_file()
    release_notes = notes_path.read_text()

    database_size = f'{artifact["database_size_bytes"]:,}'
    gzip_size = f'{artifact["size_bytes"]:,}'

    for expected in (
        gzip_size,
        database_size,
        artifact["sha256"],
        artifact["database_sha256"],
        github["release_page"],
    ):
        assert expected in release_notes

    readme = README_PATH.read_text()
    for expected in (
        github["release_page"],
        database_size,
        gzip_size,
        descriptor["publication_version"],
    ):
        assert expected in readme

    streamlit_guide = STREAMLIT_GUIDE_PATH.read_text()
    for expected in (
        github["release_tag"],
        artifact["filename"],
        database_size,
        gzip_size,
        github["release_asset_url"],
    ):
        assert expected in streamlit_guide
