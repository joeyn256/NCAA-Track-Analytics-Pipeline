# NCAA Division I Athlete Development Analytics

A production-scale data engineering and statistical modeling project that ranks NCAA Division I track and field programs by how effectively athletes improve while at each school.

The system processes **6.59 million performances**, reconstructs transfer-aware school histories, estimates expected improvement without using the evaluated school’s data, and publishes uncertainty-adjusted development rankings for **361 programs**.

---

## Featured Results

### Overall Athlete Development Rankings

| Rank | School | Athlete-school units | Posterior score |
|---:|---|---:|---:|
| 1 | Air Force | 374 | 1.2442 |
| 2 | LSU | 304 | 1.1119 |
| 3 | Kentucky | 248 | 0.9874 |
| 4 | Ohio State | 337 | 0.8917 |
| 5 | Arkansas | 305 | 0.8500 |
| 6 | Minnesota | 421 | 0.8309 |
| 7 | Wisconsin | 272 | 0.8175 |
| 8 | Arizona | 299 | 0.7961 |
| 9 | Florida | 252 | 0.7546 |
| 10 | Indiana | 318 | 0.7453 |

The primary ranking includes **353 officially ranked schools** and retains **8 additional schools as insufficient-data programs** rather than assigning unreliable ranks.

### Additional Ranking Leaders

| Analysis | Current leader |
|---|---|
| Development consistency | Air Force |
| Elite/frontier development | Air Force |
| Developing baseline tier | Northern Iowa |
| Competitive baseline tier | LSU |
| Advanced baseline tier | Arkansas |
| Elite baseline tier | Air Force |
| Breakout rate | Mercer |
| Balanced program | LSU |
| Development efficiency | UC San Diego |
| Ranking robustness | Air Force |
| Inbound transfer development | Florida |

The project also publishes rankings for **30 individual events**, men’s and women’s programs, indoor and outdoor event partitions, and 10 coaching-oriented event groups.

---

## What This Project Demonstrates

- Large-scale web collection and resilient parsing
- Relational data modeling in DuckDB
- Identity resolution across duplicate athlete profiles
- Transfer-aware chronological school attribution
- Event-specific normalization across times, distances, and heights
- School-grouped cross-validation
- Expected-improvement modeling
- Multi-event-neutral athlete aggregation
- Empirical-Bayes shrinkage
- Confidence intervals and reliability thresholds
- Sensitivity and outlier analysis
- Reproducible, versioned analytical pipelines

---

<!-- TECHNICAL_DOCUMENTATION_START -->
## Technical Documentation

The root README is the project overview. Detailed engineering,
attribution, modeling, and validation evidence is organized in the
[milestone documentation index](milestones/README.md).

Recommended technical deep dives:

- [Milestone 4 — Canonical Athlete Identity and D1 School Stints](milestones/milestone_04_canonical_identity_and_school_stints.md)
- [Milestone 5 — Athlete Development Rankings](milestones/milestone_05_athlete_development_rankings.md)
<!-- TECHNICAL_DOCUMENTATION_END -->

## Core Methodology

The central metric is:

```text
athlete value added
= observed normalized improvement
− school-held-out expected improvement
```

### 1. Normalize performances

Each eligible mark is mapped to an event-, gender-, and season-specific performance level using approved collegiate record anchors:

```text
performance level
= 100 × min(1, anchor ratio)²
```

The nonlinear scale gives greater value to equivalent raw improvements made closer to the human-performance frontier.

### 2. Build stable athlete periods

A single personal best is not treated as a complete season.

Stable athlete-event-period levels are constructed from multiple meets, with documented minimum-meet thresholds and sparse-event exceptions.

### 3. Measure observed development

Development trajectories remain specific to:

```text
canonical athlete
× school
× gender
× season type
× event
```

This prevents one school from receiving credit for development that occurred before or after a transfer.

### 4. Estimate expected improvement

Expected improvement is learned from comparable trajectories using deterministic five-fold school-grouped cross-fitting.

The evaluated school is excluded from the training fold used to generate its expectations.

### 5. Aggregate athletes fairly

Trajectories are first averaged within event families and then across families so that every athlete-school unit contributes one total school vote.

A multi-event athlete does not count as several independent athletes.

### 6. Stabilize school rankings

School means are adjusted with empirical-Bayes shrinkage:

```text
posterior score
= national mean
+ shrinkage weight × (raw school score − national mean)
```

Small samples receive more shrinkage, while large samples remain closer to their raw values.

---

## Model Performance and Reliability

### Expected-improvement benchmark

Selected model:

```text
resolution_raw_mean
```

| Metric | Out-of-sample result |
|---|---:|
| MAE | 3.3919 |
| RMSE | 4.5327 |
| Calibration slope | 0.9704 |
| Prediction correlation | 0.4517 |
| R² | 0.2038 |

The selected model improved MAE by approximately **9.7%** and RMSE by approximately **10.8%** relative to the naive held-out-fold benchmark.

### Ranking stability

Seven approved ranking variants tested alternative variance priors, winsorization, median aggregation, and removal of each school’s best or worst athlete.

| Stability measure | Result |
|---|---:|
| Minimum alternative rank correlation | 0.9979 |
| Minimum top-10 overlap | 90% |
| Minimum top-25 overlap | 92% |
| Maximum median rank movement | 3 |
| Failed sensitivity variants | 0 |

Air Force ranked first under every approved robustness variant.

---

## Project Scale

| Layer | Final value |
|---|---:|
| Historical roster files | 34,334 |
| Raw roster records | 992,774 |
| Source athlete profiles | 193,961 |
| Athlete pages collected | 193,954 |
| Unique source performances | 6,594,540 |
| Meets | 32,416 |
| Raw event labels | 378 |
| Canonical people | 192,561 |
| Deduplicated canonical-person performances | 6,376,667 |
| Final D1 school stints | 174,429 |
| Eligible normalized performance rows | 4,664,041 |
| Stable athlete-event periods | 1,628,956 |
| Observed development trajectories | 189,839 |
| Primary modeling trajectories | 189,703 |
| Athlete-event-family units | 98,888 |
| Athlete-school units | 80,077 |
| Schools represented | 361 |
| Officially ranked schools | 353 |

---

## Ranking Products

### Primary publication

- Overall program rankings
- Men’s rankings
- Women’s rankings
- Reliability tiers
- Posterior confidence intervals
- Insufficient-data classifications
- School score components

### Individual-event rankings

The project ranks schools separately for 30 canonical events, including:

- 60m, 100m, 200m, and 400m
- 500m, 600m, 800m, 1000m, 1500m, and mile
- 3000m, 5000m, and 10000m
- Hurdles and steeplechase
- High jump, pole vault, long jump, and triple jump
- Shot put, discus, hammer, weight throw, and javelin
- Pentathlon, heptathlon, and decathlon

### Coaching-oriented groups

- Sprints
- Middle Distance
- Distance
- Hurdles
- Steeplechase
- Jumps
- Throws
- Combined Events
- Field
- Special Events

### Supplemental analyses

- Development consistency
- Elite/frontier development
- Four baseline-performance tiers
- Breakout rate
- Balanced program index
- Annualized development efficiency
- Ranking robustness
- Inbound transfer development

---

## Pipeline Architecture

```text
NCAA Division I Directory
            │
            ▼
     Historical Rosters
            │
            ▼
       Athlete Profiles
            │
            ▼
     Performance Parser
            │
            ▼
 Relational DuckDB Warehouse
            │
            ▼
 Canonical Athlete Identity
            │
            ▼
 Transfer-Aware School Stints
            │
            ▼
 Event and Mark Normalization
            │
            ▼
 Collegiate Record Anchors
            │
            ▼
 Stable Athlete-Event Periods
            │
            ▼
 Observed Development Trajectories
            │
            ▼
 School-Held-Out Expected Improvement
            │
            ▼
 Athlete Value Added
            │
            ▼
 Multi-Event-Neutral Aggregation
            │
            ▼
 Empirical-Bayes School Rankings
            │
            ▼
 Event, Group, and Supplemental Rankings
```

Every major phase:

- attaches upstream databases read-only;
- writes to a versioned output directory;
- records input and output manifests;
- calculates SHA-256 hashes;
- executes hard validation checks;
- publishes only after its phase gate passes.

---

## Repository Structure

```text
NCAA Track Analytics Pipeline/
├── data/
│   ├── raw/
│   ├── processed/
│   ├── database/
│   └── reference/
│       └── collegiate_records/
├── milestones/
│   ├── README.md
│   ├── milestone_01_data_collection.md
│   ├── milestone_02_performance_parsing.md
│   ├── milestone_03_database_construction.md
│   ├── milestone_03_database_audit.md
│   ├── milestone_04_canonical_identity_and_school_stints.md
│   └── milestone_05_athlete_development_rankings.md
├── src/
│   ├── analysis/
│   │   ├── milestone4/
│   │   └── milestone5/
│   ├── database/
│   ├── parser/
│   ├── processing/
│   └── scraper/
├── tests/
├── README.md
├── requirements.txt
└── requirements-milestone3.txt
```

---

## Analytical Databases

Generated databases remain local and are excluded from Git.

### Source warehouse

```text
data/database/ncaa_track_analytics.duckdb
```

### Primary ranking publication

```text
data/processed/milestone5/athlete_development_v1/
phase_5i_publication_freeze/
ncaa_d1_athlete_development_rankings_v1.duckdb
```

### Event and group rankings

```text
data/processed/milestone5/athlete_development_v1/
phase_5j_event_and_group_rankings/
ncaa_d1_event_development_rankings_v1.duckdb
```

### Supplemental rankings

```text
data/processed/milestone5/athlete_development_v1/
phase_5k_supplemental_development_rankings/
supplemental_development_rankings_v1.duckdb
```

---

## Reproduction

Activate the environment:

```bash
source .venv/bin/activate
```

Build and validate the source database:

```bash
python src/database/build_database.py --preflight-only

set -o pipefail

python src/database/build_database.py \
    --build \
    2>&1 | tee data/database/milestone3_build.log

python src/database/validate_production_database.py \
    | tee data/database/milestone3_production_validation.txt
```

Milestone-specific scripts are stored in:

```text
src/analysis/milestone4/
src/analysis/milestone5/
```

For the complete ordered methodology and phase results, see:

- [`milestones/milestone_04_canonical_identity_and_school_stints.md`](milestones/milestone_04_canonical_identity_and_school_stints.md)
- [`milestones/milestone_05_athlete_development_rankings.md`](milestones/milestone_05_athlete_development_rankings.md)

---

## Technology Stack

- Python 3.12
- DuckDB
- SQL
- Pandas
- NumPy
- BeautifulSoup
- Requests
- CSV and HTML
- Git and GitHub

---

## Interpretation and Limitations

The rankings estimate school-associated athlete development. They are not randomized causal estimates of coaching quality.

Important limitations:

- results depend on available TFRRS performance coverage;
- sparse event contexts may use broader expected-model fallbacks;
- adjacent ranks may not be statistically distinguishable;
- transfer status is inferred from observed school chronology;
- some small event partitions collapse to ties after shrinkage;
- relays require lineup-aware team modeling;
- cross country requires course- and condition-aware modeling.

Relays and cross country are planned extensions rather than unfinished Milestone 5 work.

---

## Milestones

- ✅ [Milestone 1 — Historical NCAA Data Collection](milestones/milestone_01_data_collection.md)
- ✅ [Milestone 2 — Athlete Performance Parsing](milestones/milestone_02_performance_parsing.md)
- ✅ [Milestone 3 — Relational Database Construction](milestones/milestone_03_database_construction.md)
- ✅ [Milestone 3 — Production Database Audit](milestones/milestone_03_database_audit.md)
- ✅ [Milestone 4 — Canonical Athlete Identity and D1 School Stints](milestones/milestone_04_canonical_identity_and_school_stints.md)
- ✅ [Milestone 5 — Athlete Development Rankings](milestones/milestone_05_athlete_development_rankings.md)
- ⏳ Milestone 6 — Exploratory Analytics and Visualization
- ⏳ Milestone 7 — Predictive Modeling

---

## Current Status

**Milestone 5 is complete.**

The next phase will turn the analytical outputs into recruiter-friendly visualizations, interactive school profiles, and a public ranking explorer.

<!-- MILESTONE_6_SUMMARY_START -->
## Milestone 6 — Seasonal Development Rankings and Explorer

**Status: Complete**

Milestone 6 extends the frozen Milestone 5 athlete-development model into
seasonal rankings, equal-event development-production rankings, elite cohorts,
model diagnostics, and a Streamlit explorer.

### Final model hierarchy

- **Official primary:** Enhanced Balanced Production
- **Balanced companion:** Original Balanced Production v4.1
- **Efficiency companion:** Average Athlete Development

The official model uses the original observed-minus-expected athlete signal,
support reliability with `k=191`, a `100,000` positive budget for every
publishable championship event, and a `100,000` negative event cap.

```text
Official athlete-point rows: 392,682
Official school-event rows: 68,575
Official event partitions: 449
Official single-season combined rows: 13,882
```

Validation against Original v4.1 produced a `0.980708` rank correlation,
`91.7%` top-10 overlap, and `94.0%` top-25 overlap.

Matched elite testing showed greater credit for comparable high-baseline
improvement in `97.9%` of matched cells. No additional elite multiplier is
used.

Run the explorer:

```bash
source .venv/bin/activate
streamlit run src/apps/seasonal_development_explorer.py
```

Final publication:

```text
data/processed/milestone6/final_development_rankings_v1/
└── phase_6g_final_publication/
    └── final_development_rankings_v1.duckdb
```

See the Milestone 6 document in `milestones/` for full methodology,
validation, outputs, and interpretation limits.
<!-- MILESTONE_6_SUMMARY_END -->
