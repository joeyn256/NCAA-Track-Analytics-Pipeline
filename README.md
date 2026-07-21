# NCAA Track Analytics Pipeline


## Project resources

- **[Open the live explorer](https://ncaa-d1-track-analytics-pipeline-explorer.streamlit.app/)**
- [Read the project case study](docs/portfolio/CASE_STUDY.md)
- [Review the architecture and data flow](docs/portfolio/ARCHITECTURE_AND_DATA_FLOW.md)
- [View project summaries and engineering notes](docs/portfolio/PROJECT_SUMMARIES.md)
- [See the application images](docs/portfolio/README.md)
- [Use the demo and recording guide](docs/portfolio/DEMO_AND_RECORDING_GUIDE.md)

The official model is **Enhanced Balanced Production**. Original Balanced
Production v4.1 and Average Athlete Development remain companion views. The
rankings are observational and do not establish causal coaching effects.

A production analytics system for measuring how NCAA Division I track and field
programs develop athletes over time.

The project collects and standardizes public collegiate performance data,
builds a relational DuckDB warehouse, estimates athlete development relative to
event-specific expectations, and publishes school rankings, longitudinal
program trends, specialized analyses, and an interactive Streamlit explorer.

## Public Explorer

> [!IMPORTANT]
> **[Launch the live NCAA Division I Athlete Development Explorer →](https://ncaa-d1-track-analytics-pipeline-explorer.streamlit.app/)**
>
> Compare official program rankings, inspect athlete contributions, study
> multi-season trends, and explore event-specific development results.

**Deployment status:** Milestones 1–8 are complete and Milestone 9 production
hardening is in progress. The compact public DuckDB is deployed through
Streamlit Community Cloud, loads from the checksum-verified GitHub Release
asset, and is protected by Python 3.12 CI plus a daily public health check.

### Project scale

| Performances | Athletes | Institutions | Deployment tables |
|---:|---:|---:|---:|
| **6,594,540** | **193,961** | **554** | **81** |

The production warehouse covers **554 institutions** and publishes **81 of 81
validated deployment tables**.

### Selected validated results

| Result | Value |
|---|---:|
| Official ranking model | **Enhanced Balanced Production** |
| Source-to-deployment parity | **81 of 81 tables** |
| Public deployment rows | **2,918,594** |
| Championship event budget | **100,000 positive points per event** |
| Visitor-readiness score | **100/100** |
| Cloud-only startup | **Passed** |

The explorer includes Official Rankings, Athlete Contributions, Individual
Event, Program Trends, Program Comparison, Specialized Rankings, Average
Development, School Profile, and Methodology views.

[View the immutable `public-deployment-v1` release](https://github.com/joeyn256/NCAA-Track-Analytics-Pipeline/releases/tag/public-deployment-v1)

## Current Production Model

### Enhanced Balanced Production

**Enhanced Balanced Production is the official ranking model.**

It is designed to answer a difficult question fairly:

> Which programs create the most athlete development value across different
> events, genders, seasons, and athlete starting levels?

A simple average improvement metric cannot answer that well. Ten seconds of
improvement means something very different in a 5,000m race than in a sprint,
and improvement near the elite frontier is harder than improvement from a
developing baseline.

Enhanced Balanced Production addresses those problems through:

- event-specific performance scales anchored to collegiate record references;
- school-held-out expected-improvement estimates;
- observed-minus-expected athlete development signals;
- support-reliability adjustment with `k = 191`;
- equal positive scoring budgets across eligible championship events;
- capped negative event exposure;
- separate event, gender, season, and cohort partitions;
- explicit missing-season handling with no interpolation or fabricated data.

### Production scoring contract

| Component | Production setting |
|---|---:|
| Official championship events | 27 |
| Registered event groups | 7 |
| Positive budget per eligible event partition | 100,000 points |
| Negative cap per eligible event partition | 100,000 points |
| Support-reliability constant | `k = 191` |
| Official athlete-point rows | 392,682 |
| Official school-event rows | 68,575 |
| Official event partitions | 449 |

The result is a ranking framework that rewards both the quantity and difficulty
of athlete development while preventing high-volume events from dominating the
national leaderboard.

## What the System Publishes

### Official rankings

The official ranking explorer supports:

- combined program rankings;
- men's and women's rankings;
- indoor and outdoor rankings;
- single-season and all-time views;
- event-level rankings;
- event-group rankings;
- baseline and endpoint cohort filters;
- school-level contribution detail.

### Program trends

The longitudinal layer measures how programs change across time using:

- exact previous-calendar-year, same-season comparisons;
- three- and five-calendar-year windows;
- rising, falling, mixed, and insufficient-history classifications;
- national percentile and rank movement;
- conference-relative context;
- indoor-versus-outdoor comparisons;
- event and event-group trajectory profiles.

Missing seasons remain missing. The system does not zero-fill, carry forward,
interpolate, or substitute the nearest available season.

### Specialized Event-Balanced rankings

The official specialized-ranking publication contains 12 registered analyses:

1. Development consistency
2. Elite/frontier development
3. Developing baseline tier
4. Competitive baseline tier
5. Advanced baseline tier
6. Elite baseline tier
7. Breakout rate
8. Balanced program
9. Development efficiency
10. Ranking robustness
11. Inbound transfer development
12. National elite finishers — Endpoint 90+

Eleven analyses currently publish a national leader. Inbound transfer
development remains explicitly unavailable under the frozen Broad coverage
contract rather than publishing an unsupported leaderboard.

### Average Development companion model

Average Development remains available as a separate empirical-Bayes companion
model for efficiency-oriented analysis.

It is intentionally separated from Enhanced Balanced Production in the
explorer:

```text
Rankings
├── Official Rankings
└── Specialized Rankings

Average Development
├── Rankings
├── School Profile
└── Supplemental Rankings
```

Average Development is useful for answering different questions, but it is not
the official production ranking.

## Interactive Explorer

Run the Streamlit application from the repository root:

```bash
source .venv/bin/activate
streamlit run src/apps/seasonal_development_explorer.py
```

The explorer includes:

- **Rankings** — official and specialized Event-Balanced leaderboards;
- **Trends** — longitudinal school development trajectories;
- **Compare** — school-to-school and conference comparisons;
- **Average Development** — separate posterior rankings and profiles;
- **Diagnostics** — model-support and concentration checks;
- **Coverage** — publication availability and missing-season context;
- **Methodology** — definitions, model hierarchy, and interpretation guidance.

### Public deployment architecture

The public application uses one compact, read-only DuckDB publication instead
of loading the larger collection of local CSVs and source databases directly.

| Deployment component | Validated value |
|---|---:|
| Resource tables | 81 |
| Metadata tables | 5 |
| Validated resource rows | 2,918,594 |
| DuckDB size | 352,858,112 bytes |
| Compressed release asset | 236,994,168 bytes |
| Publication version | `public_deployment_v1` |

At startup, the deployment loader can:

1. use a configured local database;
2. download the versioned GitHub Release asset when the database is absent;
3. verify the compressed and uncompressed SHA-256 checksums;
4. decompress through an atomic temporary-file workflow;
5. open DuckDB in read-only mode;
6. reuse the cached publication on later runs.

### Automated production verification

The repository includes deterministic loader and deployment-verifier tests,
a Python 3.12 GitHub Actions CI workflow, and a separate scheduled public
deployment health workflow.

Run the production verifier locally from the repository root:

```bash
python scripts/verify_public_deployment.py
```

Machine-readable output is also available:

```bash
python scripts/verify_public_deployment.py --json
```

The scheduled workflow runs daily and can also be triggered manually from
GitHub Actions. It is separate from normal CI so a temporary Streamlit outage
does not block pull requests.

Large point views are loaded lazily. The application checks view availability
using compact time metadata and queries only the selected model and cohort
before applying the existing time filter.

## Validation

The production system is built around hard publication gates rather than
informal spot checks.

### Enhanced model validation

| Validation result | Value |
|---|---:|
| Rank correlation with Original Balanced Production v4.1 | 0.980708 |
| Top-10 overlap | 91.7% |
| Top-25 overlap | 94.0% |
| Matched elite cells favoring high-baseline improvement | 97.9% |

### Milestone 7 publication gates

| Publication | Result |
|---|---:|
| Final trend-publication hard checks | 26 passed |
| Specialized-ranking hard checks | 22 passed |
| Registered trend-publication tables | 50 |
| Curated explorer tables | 14 |
| Registered specialized analyses | 12 |
| Failed production checks | 0 |

### Milestone 8 deployment gates

The final pre-release audit completed on July 21, 2026.

| Deployment validation | Result |
|---|---:|
| Exact source-to-deployment parity | 81 of 81 tables |
| Source and deployment resource rows | 2,918,594 each |
| Full release-readiness validators | 7 of 7 passed |
| Visitor-readiness score | 100 of 100 |
| Default-page median memory | 0.289 GiB |
| Default-page maximum memory | 0.290 GiB |
| Athlete Contributions maximum memory | 1.684 GiB |
| Individual Event maximum memory | 0.393 GiB |
| Cold AppTest startup | 1.368 seconds |
| Warm AppTest rerun | 0.097 seconds |
| Failed hard checks | 0 |

Additional safeguards include:

- read-only attachment of frozen upstream databases;
- before-and-after source hashes;
- unique publication-key checks;
- duplicate-preserving, bidirectional row reconciliation;
- fresh-environment artifact bootstrap validation;
- atomic download and decompression;
- explicit support thresholds;
- no fabricated 2020 Outdoor production season;
- documented transfer-inference status;
- no committed deployment secrets;
- no oversized tracked data artifacts;
- versioned outputs and reports.

## Architecture

```text
Public collegiate results
        │
        ▼
Collection and HTML archive
        │
        ▼
Performance parsing and normalization
        │
        ▼
DuckDB relational warehouse
        │
        ▼
Canonical athlete identity and school stints
        │
        ▼
Expected-improvement model
        │
        ▼
Enhanced Balanced Production
        │
        ├── Official rankings
        ├── Event and group rankings
        ├── Program trends
        ├── Program comparisons
        └── Specialized rankings
        │
        ▼
Compact public DuckDB publication
        │
        ▼
Versioned GitHub Release asset
        │
        ▼
Streamlit Community Cloud explorer
```

## Repository Structure

```text
deployment/
├── github/               # guarded release publishing script and notes
├── streamlit/            # Community Cloud secrets example
├── STREAMLIT_COMMUNITY_CLOUD.md
└── public_deployment_v1.json

src/
├── analysis/
│   ├── milestone5/       # athlete development model
│   ├── milestone6/       # production ranking publication
│   ├── milestone7/       # trends, comparisons, specialized rankings
│   └── milestone8/       # deployment publication and release validation
├── apps/
│   ├── deployment_data.py
│   └── seasonal_development_explorer.py
├── database/             # DuckDB construction and validation
├── parser/               # performance parsing
└── scraper/              # public-data collection

milestones/
├── milestone_01_data_collection.md
├── milestone_02_performance_parsing.md
├── milestone_03_database_construction.md
├── milestone_03_database_audit.md
├── milestone_04_canonical_identity_and_school_stints.md
├── milestone_05_athlete_development_rankings.md
├── milestone_06_seasonal_rankings_and_exploratory_analytics.md
├── milestone_07_program_trends_and_specialized_rankings.md
└── milestone_08_public_deployment_and_visitor_experience.md
```

Generated raw data, processed publications, caches, and DuckDB databases are
excluded from Git because of their size. The repository contains the
reproducible code, methodology, validation contracts, deployment configuration,
and explorer application.

## Data Foundation

The analytical warehouse is built from public TFRRS pages and currently
contains:

| Data foundation measure | Count |
|---|---:|
| Standardized performance records | 6,594,540 |
| Unique athletes | 193,961 |
| Institutions | 554 |
| Teams | 973 |
| Meets | 32,416 |
| Seasons | 71 |

The source pipeline resolves:

- athletes across seasons and school changes;
- school and team identities;
- event names and event groups;
- indoor and outdoor seasons;
- athlete-school affiliation periods;
- performance-backed school attribution.

Detailed ingestion and database-construction audits are preserved in the
milestone documentation.

## Methodology Principles

1. **Reward difficult improvement.** Development near the elite frontier
   receives appropriate credit.
2. **Compare like with like.** Events, genders, seasons, and cohorts are scored
   within valid partitions.
3. **Balance events.** Each eligible championship event receives the same
   positive scoring opportunity.
4. **Adjust for support.** Small samples are not treated as equally reliable as
   deep program histories.
5. **Avoid school leakage.** Expected improvement is estimated without using
   the target school's own outcomes.
6. **Preserve missingness.** Missing seasons are not invented.
7. **Separate analytical questions.** Official production, robustness, and
   Average Development products are clearly labeled.
8. **Publish only after validation.** Every major phase must pass a versioned
   hard-check contract.

## Interpretation

The rankings are observational measures of athlete development production.
They are not causal estimates of coaching quality.

Results can also reflect:

- roster composition;
- scholarship and recruiting strategy;
- event coverage;
- athlete retention;
- transfer patterns;
- program depth;
- data availability.

The best use of the system is to compare programs across multiple views rather
than treating a single ranking as a complete explanation.

## Documentation

Detailed methodology and audit evidence are available in the milestone files:

- [Milestone 4 — Canonical Athlete Identity and D1 School Stints](milestones/milestone_04_canonical_identity_and_school_stints.md)
- [Milestone 5 — Athlete Development Rankings](milestones/milestone_05_athlete_development_rankings.md)
- [Milestone 6 — Seasonal Rankings and Explorer](milestones/milestone_06_seasonal_rankings_and_exploratory_analytics.md)
- [Milestone 7 — Program Trends, Comparisons, and Specialized Rankings](milestones/milestone_07_program_trends_and_specialized_rankings.md)
- [Milestone 8 — Public Deployment and Visitor Experience](milestones/milestone_08_public_deployment_and_user_experience.md)
- [Milestone 9 — Production Hardening, Automation, and Portfolio Release](milestones/milestone_09_production_hardening_automation_and_portfolio_release.md)
- [Streamlit Community Cloud deployment guide](deployment/STREAMLIT_COMMUNITY_CLOUD.md)

## Project Status

**Milestones 1–8 are complete. Milestone 9 is in progress.**

The production system includes the official Enhanced Balanced Production
rankings, seasonal program trends and comparisons, specialized analyses, the
preserved Average Development companion model, an immutable public data
release, and a live Streamlit explorer.

Milestone 9 has added deterministic deployment-loader tests, Python 3.12
continuous integration, a reusable public deployment verifier, and scheduled
production health monitoring.

**Public application:** https://ncaa-d1-track-analytics-pipeline-explorer.streamlit.app/
