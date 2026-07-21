from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "docs" / "portfolio"
README = ROOT / "README.md"


def read(name: str) -> str:
    return (PORTFOLIO / name).read_text()


def test_required_portfolio_documents_exist() -> None:
    required = {
        "README.md",
        "CASE_STUDY.md",
        "ARCHITECTURE_AND_DATA_FLOW.md",
        "DEMO_AND_RECORDING_GUIDE.md",
        "CAREER_MATERIALS.md",
        "SCREENSHOT_GUIDE.md",
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


def test_demo_and_career_materials_are_complete() -> None:
    demo = read("DEMO_AND_RECORDING_GUIDE.md")
    career = read("CAREER_MATERIALS.md")

    assert "30-second opening" in demo
    assert "Walkthrough sequence" in demo
    assert "Recording checklist" in demo

    required = (
        "Résumé bullets",
        "LinkedIn project description",
        "Portfolio description",
        "Graduate-school application language",
        "30-second explanation",
        "Two-minute explanation",
        "STAR examples",
    )
    for value in required:
        assert value in career


def test_screenshot_guide_uses_safe_expected_filenames() -> None:
    text = read("SCREENSHOT_GUIDE.md")
    required = (
        "explorer_official_rankings.png",
        "explorer_program_trends.png",
        "explorer_methodology.png",
        "Crop out browser bookmarks",
        "below 2 MiB",
    )
    for value in required:
        assert value in text


def test_portfolio_avoids_exaggerated_impact_claims() -> None:
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


def test_readme_links_to_portfolio_package() -> None:
    text = README.read_text()
    assert "<!-- PORTFOLIO_PACKAGE_START -->" in text
    assert "docs/portfolio/CASE_STUDY.md" in text
    assert "docs/portfolio/CAREER_MATERIALS.md" in text
    assert (
        "https://ncaa-d1-track-analytics-pipeline-explorer."
        "streamlit.app/"
    ) in text
