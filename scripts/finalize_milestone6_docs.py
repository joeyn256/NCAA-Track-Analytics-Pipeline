#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path.cwd()
MILESTONES_DIR = ROOT / "milestones"
README_PATH = ROOT / "README.md"
REQUIREMENTS_PATH = ROOT / "requirements.txt"
README_START = "<!-- MILESTONE_6_SUMMARY_START -->"
README_END = "<!-- MILESTONE_6_SUMMARY_END -->"

MILESTONE_DOCUMENT = "# Milestone 6 — Seasonal Development Rankings and Explorer\n\n## Status\n\n**Complete**\n\n## Objective\n\nExtend the frozen Milestone 5 athlete-development model into:\n\n- season-by-season NCAA Division I development rankings;\n- event-balanced development-production rankings;\n- broad, frontier, elite, national-elite, and championship-caliber cohorts;\n- final model validation and sensitivity testing;\n- a local Streamlit ranking explorer;\n- one frozen final Milestone 6 publication.\n\nMilestone 6 preserves the validated Milestone 5 value-added model. It does\nnot replace the original athlete-development calculation with a separate\nunrelated model.\n\n---\n\n## Final model hierarchy\n\n### Official primary model\n\n**Enhanced Balanced Production**\n\nThis answers:\n\n> How much reliable athlete development did a program produce?\n\nThe official model uses:\n\n```text\noriginal athlete value added\n× support reliability\n→ equal positive event pools\n→ bounded negative event pools\n→ athlete contributions summed to schools\n```\n\nParameters:\n\n```text\nsupport reliability = sqrt(n / (n + 191))\npositive event budget = 100,000\npositive group budget = 100,000\nnegative event cap = 100,000\nextra elite multiplier = none\n```\n\nThe original athlete signal remains:\n\n```text\nobserved improvement\n− cross-fitted expected improvement\n```\n\n### Balanced-production companion\n\n**Original Balanced Production v4.1**\n\nThis preserves the exact validated Phase 6D v4.1 formula:\n\n- no support-reliability adjustment;\n- 100,000 positive points per publishable event;\n- uncapped linear negative points;\n- athlete-school-event contributions summed to schools.\n\n### Efficiency companion\n\n**Average Athlete Development**\n\nThis answers:\n\n> How well did the typical athlete develop?\n\nTwo time views are retained:\n\n- **All Time — Frozen Milestone 5**\n- **Single Season — Milestone 6**\n\nThe frozen all-time overall ranking remains led by Air Force, LSU, and\nKentucky.\n\n---\n\n## Phase 6A — Seasonal Average-Development Rankings\n\n### Season definition\n\nA ranking labeled `2025 Indoor` includes development trajectories whose\nendpoint stable period is the 2025 indoor season.\n\nThe season label represents when development was realized. It is not a\nrandomized causal estimate and is not necessarily a strict one-calendar-year\nchange.\n\n### Published scopes\n\n1. Combined overall\n2. Men's overall\n3. Women's overall\n4. Gender-specific individual event\n5. Combined-gender individual event\n6. Gender-specific coaching group\n7. Combined-gender coaching group\n\n### Completed results\n\n```text\nEndpoint seasons: 40\nEndpoint years: 2007–2026\nSeason-athlete units: 141,635\nSeason-event units: 189,703\nSeason-group units: 219,278\nOfficial ranking rows: 10,336\n```\n\nThe Phase 6A gate passed with frozen Milestone 5 inputs, unchanged input\nhashes, unique contribution identifiers, valid posterior scores and\nconfidence intervals, threshold reconciliation, at least five eligible\nschools per published partition, and versioned outputs.\n\n---\n\n## Phase 6B — Development Cohorts\n\nMilestone 6 expanded the seasonal rankings into five cohorts:\n\n| Cohort | Definition |\n|---|---|\n| Broad | All eligible athletes |\n| Frontier | Baseline level 70+ |\n| Elite | Baseline level 80+ |\n| National Elite Finishers | Endpoint level 90+ |\n| Championship-Caliber Finishers | Endpoint level 95+ |\n\nThe cohorts use the same underlying development model and publication gates.\n\n---\n\n## Phase 6C — Event-Fairness Audit\n\nThe initial model gave high-volume events substantially more total influence.\n\nExamples from the audit:\n\n```text\n800m influence: approximately 15,307\n400m influence: approximately 12,135\n200m influence: approximately 10,139\n10,000m influence: approximately 789\ncombined events: approximately 52–108\n```\n\nDirect trajectory-count reweighting was rejected because it changed rankings\ntoo aggressively. The final policy instead gives every publishable\nchampionship event an equal positive opportunity before school aggregation.\n\n---\n\n## Phase 6D — Athlete-Level Event-Balanced Points\n\n### Analytical unit\n\n```text\nathlete × school × event × ranking period\n```\n\nMultiple eligible trajectories for the same athlete-school-event unit are\naveraged before point allocation.\n\nFor every publishable event partition:\n\n```text\npositive event pool = 100,000\n```\n\nRegression receives separate negative points and does not consume the positive\npool.\n\nCompleted results:\n\n```text\nAthlete-point rows: 392,682\nSchool-event rows: 68,575\nEvent partitions: 449\nNegative athlete rows: 193,725\nGroup partitions: 401\nSingle-season combined rows: 13,882\n```\n\nAll positive event and group budgets reconcile to 100,000. School-event totals\nreconcile to athlete contributions. There is no top-eight cutoff.\n\n---\n\n## Phase 6E — Enhanced and Original Model Variants\n\nTwo balanced-production formulas were published together:\n\n1. Enhanced Balanced Production\n2. Original Balanced Production v4.1\n\nEnhancements added empirical support reliability, a bounded negative event\npool, concentration diagnostics, roster-size diagnostics, elite reward\ndiagnostics, and model comparisons.\n\n```text\nAthlete-model rows: 785,364\nEvent-model partitions: 898\nEnhanced capped negative partitions: 171\nMean enhanced/original rank correlation: 0.980486\n```\n\nOriginal v4.1 was reproduced to numerical tolerance.\n\n---\n\n## Phase 6F — Final Model Validation\n\nTen controlled variants tested support values `k = 0, 50, 100, 191, 300,\n500`, negative caps of `0.5×`, `1.0×`, and `1.5×`, uncapped negative points,\nand exact Original v4.1 behavior.\n\nFinal evidence:\n\n```text\nEnhanced versus Original v4.1 rank correlation: 0.980708\nMean top-10 overlap: 0.917\nMean top-25 overlap: 0.940\nP95 largest-athlete share: 0.3041\nMean effective positive athletes: 260.98\nMean absolute roster correlation: 0.2412\nMean positive-athlete-count correlation: 0.6007\nMatched nonnegative elite slope share: 0.950\nMatched elite advantage share: 0.979\nMedian matched elite advantage: 0.5821\n```\n\nMatched elite testing compared athletes within the same gender, event, and\nsimilar observed-improvement range. No additional elite multiplier was added.\n\n---\n\n## Phase 6G — Final Freeze and Publication\n\nThe final publication passed all hard checks.\n\n```text\nOfficial athlete-point rows: 392,682\nOfficial school-event rows: 68,575\nOfficial event partitions: 449\nOfficial single-season combined rows: 13,882\n```\n\nFrozen model:\n\n```text\nPrimary model: Enhanced Balanced Production\nSupport k: 191\nPositive event budget: 100,000\nNegative event cap: 100,000\nExtra elite multiplier: none\n```\n\nLatest broad leaders:\n\n### 2026 Indoor\n\n| Rank | School | Net points |\n|---:|---|---:|\n| 1 | Charlotte | 11,775.98 |\n| 2 | Navy | 11,728.34 |\n| 3 | Montana State | 11,719.40 |\n\n### 2026 Outdoor\n\n| Rank | School | Net points |\n|---:|---|---:|\n| 1 | Air Force | 13,132.29 |\n| 2 | UC Santa Barbara | 11,939.57 |\n| 3 | Montana | 11,199.94 |\n\n---\n\n## Explorer\n\nRun:\n\n```bash\nsource .venv/bin/activate\nstreamlit run src/apps/seasonal_development_explorer.py\n```\n\nPages:\n\n- Event-Balanced Points\n- Model Diagnostics\n- Average Development\n- School Profile\n- Season Coverage\n- Methodology\n\nThe explorer preserves Enhanced Balanced Production, Original v4.1, the\nfrozen all-time Average Athlete Development ranking, and seasonal\nAverage Athlete Development rankings.\n\n---\n\n## Event taxonomy\n\n- Individual NCAA championship events\n- 10 coaching-oriented groups\n- Steeplechase belongs to Distance\n- No standalone steeplechase group\n- 500m, 600m, and 1000m excluded from the primary championship ranking\n- Relays and cross-country excluded from individual athlete-development scoring\n\n---\n\n## Final output\n\n```text\ndata/processed/milestone6/\n└── final_development_rankings_v1/\n    └── phase_6g_final_publication/\n        ├── final_development_rankings_v1.duckdb\n        ├── final_model_decision.csv\n        ├── final_model_scorecard.csv\n        ├── model_registry.csv\n        ├── athlete_model_points.csv\n        ├── event_balanced_point_rows.csv\n        ├── event_balanced_overall_gender.csv\n        ├── event_balanced_overall_combined.csv\n        ├── group_balanced_points_gender.csv\n        ├── group_balanced_points_combined.csv\n        ├── group_balanced_overall_gender.csv\n        ├── group_balanced_overall_combined.csv\n        ├── average_development_seasonal_rankings.csv\n        ├── average_development_elite_rankings.csv\n        ├── official_season_overall_gender.csv\n        ├── official_season_overall_combined.csv\n        ├── hard_checks.csv\n        ├── input_manifest.csv\n        ├── phase_6g_report.txt\n        └── terminal_output.txt\n```\n\n---\n\n## Interpretation\n\n**Enhanced Balanced Production** measures reliable total development\nproduction. It reflects both development quality and breadth.\n\n**Original Balanced Production v4.1** preserves the exact original\nathlete-level balanced formula.\n\n**Average Athlete Development** measures how well the typical athlete\ndeveloped and is the preferred efficiency-oriented companion.\n\n---\n\n## Limitations\n\n- Rankings are observational, not randomized causal estimates.\n- A season refers to the trajectory endpoint season.\n- Trajectories can span more than one year.\n- Early seasons can have lower coverage.\n- Sparse elite cohorts can be concentrated.\n- Athlete points are allocated inside separate event pools.\n- Relays and cross-country are excluded.\n- Production rankings intentionally reflect quality and breadth.\n- Average Athlete Development should accompany comparisons of differently\n  sized programs.\n\n---\n\n## Dependencies\n\nPhase 6G CSV export requires:\n\n```text\npytz>=2026.2\n```\n\n---\n\n## Completion gate\n\nMilestone 6 is complete because all upstream model gates passed, hashes stayed\nunchanged, seasonal products were published, event and group budgets\nreconciled, negative caps were respected, athlete contributions reconciled to\nschool totals, companion models were preserved, sensitivity and matched elite\ntesting passed, final parameters were frozen, the publication gate passed,\nand the Streamlit explorer reads the frozen publication.\n\n**Milestone 6 status: COMPLETE**\n"
README_SECTION = '<!-- MILESTONE_6_SUMMARY_START -->\n## Milestone 6 — Seasonal Development Rankings and Explorer\n\n**Status: Complete**\n\nMilestone 6 extends the frozen Milestone 5 athlete-development model into\nseasonal rankings, equal-event development-production rankings, elite cohorts,\nmodel diagnostics, and a Streamlit explorer.\n\n### Final model hierarchy\n\n- **Official primary:** Enhanced Balanced Production\n- **Balanced companion:** Original Balanced Production v4.1\n- **Efficiency companion:** Average Athlete Development\n\nThe official model uses the original observed-minus-expected athlete signal,\nsupport reliability with `k=191`, a `100,000` positive budget for every\npublishable championship event, and a `100,000` negative event cap.\n\n```text\nOfficial athlete-point rows: 392,682\nOfficial school-event rows: 68,575\nOfficial event partitions: 449\nOfficial single-season combined rows: 13,882\n```\n\nValidation against Original v4.1 produced a `0.980708` rank correlation,\n`91.7%` top-10 overlap, and `94.0%` top-25 overlap.\n\nMatched elite testing showed greater credit for comparable high-baseline\nimprovement in `97.9%` of matched cells. No additional elite multiplier is\nused.\n\nRun the explorer:\n\n```bash\nsource .venv/bin/activate\nstreamlit run src/apps/seasonal_development_explorer.py\n```\n\nFinal publication:\n\n```text\ndata/processed/milestone6/final_development_rankings_v1/\n└── phase_6g_final_publication/\n    └── final_development_rankings_v1.duckdb\n```\n\nSee the Milestone 6 document in `milestones/` for full methodology,\nvalidation, outputs, and interpretation limits.\n<!-- MILESTONE_6_SUMMARY_END -->'


def choose_milestone_path() -> Path:
    MILESTONES_DIR.mkdir(parents=True, exist_ok=True)
    preferred = MILESTONES_DIR / "milestone_06_seasonal_rankings.md"
    if preferred.exists():
        return preferred
    candidates = sorted(MILESTONES_DIR.glob("milestone_06*.md"))
    return candidates[0] if candidates else preferred


def update_readme() -> str:
    current = (
        README_PATH.read_text(encoding="utf-8")
        if README_PATH.exists()
        else "# NCAA Track Analytics Pipeline\n"
    )
    pattern = re.compile(
        re.escape(README_START) + r".*?" + re.escape(README_END),
        flags=re.DOTALL,
    )
    if pattern.search(current):
        updated = pattern.sub(README_SECTION, current)
        action = "replaced existing bounded Milestone 6 section"
    else:
        updated = current.rstrip() + "\n\n" + README_SECTION + "\n"
        action = "appended bounded Milestone 6 section"
    README_PATH.write_text(updated, encoding="utf-8")
    return action


def update_requirements() -> str:
    dependency = "pytz>=2026.2"
    if not REQUIREMENTS_PATH.exists():
        return "requirements.txt not present; no dependency file changed"

    lines = REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
    normalized = [
        line.strip().lower()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if any(
        line == "pytz"
        or line.startswith("pytz==")
        or line.startswith("pytz>=")
        or line.startswith("pytz~=")
        for line in normalized
    ):
        return "pytz already present in requirements.txt"

    if lines and lines[-1].strip():
        lines.append("")
    lines.extend([
        "# Required by DuckDB timestamp export in Milestone 6",
        dependency,
    ])
    REQUIREMENTS_PATH.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    return f"added {dependency} to requirements.txt"


def main() -> None:
    milestone_path = choose_milestone_path()
    milestone_path.write_text(
        MILESTONE_DOCUMENT.rstrip() + "\n",
        encoding="utf-8",
    )
    print("Milestone 6 documentation finalized.")
    print(f"Milestone document: {milestone_path}")
    print(f"README: {update_readme()}")
    print(f"Dependencies: {update_requirements()}")


if __name__ == "__main__":
    main()
