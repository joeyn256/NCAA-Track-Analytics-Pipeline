# NCAA Track Analytics Pipeline — Portfolio Package

This directory contains recruiter-facing materials for the NCAA Track Analytics
Pipeline.

## Contents

- [Case study](CASE_STUDY.md)
- [Architecture and data flow](ARCHITECTURE_AND_DATA_FLOW.md)
- [Demo and recording guide](DEMO_AND_RECORDING_GUIDE.md)
- [Career materials](CAREER_MATERIALS.md)
- [Screenshot guide](SCREENSHOT_GUIDE.md)

## Public project

- Live explorer: https://ncaa-d1-track-analytics-pipeline-explorer.streamlit.app/
- Source repository: https://github.com/joeyn256/NCAA-Track-Analytics-Pipeline
- Immutable public deployment:
  https://github.com/joeyn256/NCAA-Track-Analytics-Pipeline/releases/tag/public-deployment-v1

## Model hierarchy

- Official primary model: **Enhanced Balanced Production**
- Balanced-production companion: **Original Balanced Production v4.1**
- Efficiency companion: **Average Athlete Development**

The rankings are observational. They measure development patterns in the
recorded collegiate data and do not establish causal coaching effects.

<!-- APP_SCREENSHOTS_START -->
## Application screenshots

### Official Enhanced Balanced Production ranking

The official recruiter-facing view shows the Broad — All Athletes,
Overall — Combined ranking for the 2026 Indoor season.

![Official Enhanced Balanced Production ranking](screenshots/explorer_official_rankings.png)

### Program trends

The trends view shows an audited multi-season trajectory with national
rank-strength percentiles and explicit missing-season handling.

![Arkansas program trend](screenshots/explorer_program_trends.png)
<!-- APP_SCREENSHOTS_END -->
