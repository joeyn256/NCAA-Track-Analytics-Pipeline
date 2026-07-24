from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "docs" / "portfolio"
README = ROOT / "README.md"


def read(name: str) -> str:
    return (PORTFOLIO / name).read_text()


def test_required_project_documents_exist() -> None:
    required = {
        "README.md",
        "CASE_STUDY.md",
        "ARCHITECTURE_AND_DATA_FLOW.md",
        "PROJECT_SUMMARIES.md",
    }
    assert required == {
        path.name
        for path in PORTFOLIO.glob("*.md")
    }


def test_case_study_preserves_scale_and_model_contract() -> None:
    text = read("CASE_STUDY.md")
    required = (
        "6,594,540",
        "193,961",
        "6,376,667",
        "2,918,594",
        "81",
        "Enhanced Balanced Production",
        "Original Balanced Production v4.1",
        "Average Athlete Development",
        "0.980708",
        "observational rather than causal",
    )
    for value in required:
        assert value in text


def test_architecture_document_contains_visuals() -> None:
    text = read("ARCHITECTURE_AND_DATA_FLOW.md")
    assert text.count("```mermaid") == 3
    assert "System architecture" in text
    assert "Deployment architecture" in text
    assert "Analytical data flow" in text


def test_project_summaries_are_complete() -> None:
    summaries = read("PROJECT_SUMMARIES.md")

    required = (
        "Contribution highlights",
        "Short project overview",
        "Detailed project overview",
        "Engineering examples",
    )
    for value in required:
        assert value in summaries


def test_project_documents_avoid_exaggerated_impact_claims() -> None:
    corpus = "\n".join(
        path.read_text()
        for path in PORTFOLIO.glob("*.md")
    ).lower()

    forbidden = (
        "millions of users",
        "drove revenue",
        "guaranteed accuracy",
        "proves coaching",
        "caused athlete improvement",
        "industry-leading adoption",
    )
    for phrase in forbidden:
        assert phrase not in corpus


def test_readme_links_to_project_documentation() -> None:
    text = README.read_text()
    assert "## Project resources" in text
    assert "docs/portfolio/CASE_STUDY.md" in text
    assert "docs/portfolio/PROJECT_SUMMARIES.md" in text
    assert (
        "https://ncaa-d1-track-analytics-pipeline-explorer."
        "streamlit.app/"
    ) in text
