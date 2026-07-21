from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
MILESTONE = (
    ROOT
    / "milestones"
    / "milestone_09_production_hardening_automation_and_portfolio_release.md"
)

README_START = "<!-- PORTFOLIO_PACKAGE_START -->"
README_END = "<!-- PORTFOLIO_PACKAGE_END -->"

README_SECTION = f'''{README_START}
## Portfolio and recruiter resources

- **[Open the live explorer](https://ncaa-d1-track-analytics-pipeline-explorer.streamlit.app/)**
- [Read the concise case study](docs/portfolio/CASE_STUDY.md)
- [Review the architecture and data flow](docs/portfolio/ARCHITECTURE_AND_DATA_FLOW.md)
- [Use the demo and recording guide](docs/portfolio/DEMO_AND_RECORDING_GUIDE.md)
- [View résumé, LinkedIn, graduate-school, and interview language](docs/portfolio/CAREER_MATERIALS.md)
- [Portfolio package index](docs/portfolio/README.md)

The official model is **Enhanced Balanced Production**. Original Balanced
Production v4.1 and Average Athlete Development remain companion views. The
rankings are observational and do not establish causal coaching effects.
{README_END}
'''

PHASE_SECTION = '''## Phase 9H — Portfolio and career package

**Status: Written package complete; screenshot capture pending**

Recruiter-facing materials now include:

- a concise project case study;
- Mermaid system, deployment, and analytical data-flow visuals;
- a three-to-five-minute demo and recording guide;
- technical and nontechnical project summaries;
- defensible résumé bullets;
- LinkedIn and portfolio descriptions;
- graduate-school application language;
- 30-second and two-minute interview explanations;
- STAR-format examples covering identity resolution, event fairness, and
  production deployment;
- a safe screenshot capture guide with three required application views.

All written claims preserve the frozen project metrics and explicitly avoid
causal, traffic, adoption, revenue, or accuracy claims that the evidence does
not support.

The remaining Phase 9H task is to capture and review the three current public
application screenshots listed in `docs/portfolio/SCREENSHOT_GUIDE.md`.

'''


def insert_readme_section(text: str) -> str:
    if README_START in text:
        start = text.index(README_START)
        end = text.index(README_END, start) + len(README_END)
        return text[:start] + README_SECTION.rstrip() + text[end:]

    lines = text.splitlines(keepends=True)
    insert_at = 0

    for index, line in enumerate(lines):
        if line.startswith("# "):
            insert_at = index + 1
            while insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
            break

    lines.insert(insert_at, "\n" + README_SECTION + "\n")
    return "".join(lines)


def replace_check(
    text: str,
    item: str,
) -> str:
    unchecked = "- [ ] " + item
    checked = "- [x] " + item
    if checked in text:
        return text
    if unchecked not in text:
        raise RuntimeError(f"Checklist item not found: {item}")
    return text.replace(unchecked, checked, 1)


def main() -> None:
    readme_text = insert_readme_section(README.read_text())
    README.write_text(readme_text)

    milestone_text = MILESTONE.read_text()
    marker = "## Milestone 9 acceptance checklist"

    if "## Phase 9H — Portfolio and career package" not in milestone_text:
        if marker not in milestone_text:
            raise RuntimeError("Milestone 9 checklist marker not found")
        milestone_text = milestone_text.replace(
            marker,
            PHASE_SECTION + marker,
            1,
        )

    items = (
        "A concise case study is available.",
        "Architecture and data-flow visuals are available.",
        "A short demo script and walkthrough-recording guide are available.",
        "Technical and nontechnical summaries are accurate.",
        (
            "Engineering challenges, solutions, methodology, and limitations are\n"
            "      documented."
        ),
        "Public links are prominent and correct.",
        "Résumé bullets are accurate and defensible.",
        "LinkedIn and portfolio descriptions are complete.",
        "Graduate-school application language is complete.",
        (
            "Interview talking points include a 30-second and two-minute "
            "explanation."
        ),
        "STAR-format project examples are documented.",
        (
            "No claims exaggerate causality, accuracy, traffic, adoption, or "
            "business\n      impact."
        ),
    )

    for item in items:
        milestone_text = replace_check(milestone_text, item)

    MILESTONE.write_text(milestone_text)
    print("PASS — Phase 9H written portfolio package installed.")


if __name__ == "__main__":
    main()
