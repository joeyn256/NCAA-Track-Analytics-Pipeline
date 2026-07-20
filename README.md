# NCAA Track Analytics Pipeline

A reproducible data-engineering and analytics platform for historical NCAA Division I track and field performance data.

The project collects athlete and roster history, parses millions of performances, constructs a relational DuckDB warehouse, resolves transfers and duplicate athlete identities, and ranks programs by how effectively their athletes improve relative to a school-held-out expectation benchmark.

---

## Project by the Numbers

### Source collection and database

| Metric | Final value |
|---|---:|
| NCAA Division I team directory entries | 714 |
| Current Division I institutions | 363 |
| Historical roster files | 34,334 |
| Raw historical roster records | 992,774 |
| Unique historical athlete affiliations | 990,681 |
| Source athlete profiles | 193,961 |
| Athlete pages collected | 193,954 |
| Athletes with recorded performances | 172,204 |
| Athlete pages with no recorded meet results | 21,750 |
| Unique source performance records | 6,594,540 |
| Meets | 32,416 |
| Raw event labels | 378 |
| Teams represented in the source database | 973 |
| Institutions represented in the source database | 554 |
| Season records | 71 |
| Performance-data chunks | 194 |
| Canonical source files registered with SHA-256 hashes | 1,105 |

### Canonical identity and school attribution

| Metric | Final value |
|---|---:|
| Canonical people | 192,561 |
| High-confidence multi-profile people | 1,352 |
| Deduplicated canonical-person performances | 6,376,667 |
| Duplicate profile-level performance rows removed | 97,871 |
| D1 performances mapped to school stints | 6,376,505 |
| Canonical people with D1 school stints | 170,655 |
| Final D1 school stints | 174,429 |
| People represented by multiple school stints | 3,612 |
| Person-performance team conflicts resolved | 35,694 |
| Remaining team conflicts | 0 |
| Remaining unreviewed chronology islands | 0 |

### Athlete-development analytics

| Metric | Final value |
|---|---:|
| Approved collegiate record anchors | 82 |
| Eligible normalized performance rows | 4,664,041 |
| Stable athlete-event periods | 1,628,956 |
| Observed development trajectories | 189,839 |
| Primary modeling trajectories | 189,703 |
| Athletes in expected-improvement cohort | 79,535 |
| Schools in expected-improvement cohort | 361 |
| Athlete-event-family units | 98,888 |
| Athlete-school units | 80,077 |
| Officially ranked schools | 353 |
| Insufficient-data schools retained | 8 |
| Canonical individual events ranked | 30 |
| Coaching-oriented event groups | 10 |
| Official event/group ranking rows | 25,619 |
| Supplemental ranking products | 8 |

### Validation status

- 0 production parsing failures
- 0 duplicate source performance IDs
- 0 relational orphan records
- 0 missing D1 performance-to-stint assignments
- 0 unresolved person-performance team conflicts
- 0 invalid final school-ranking rows
- 0 failed ranking sensitivity variants
- Milestones 1–5 final phase gates: **PASS**

---

## Current Pipeline

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
   Production Data Audit
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

---

## Completed Milestones

### Milestone 1 — Historical Data Collection

- 714 NCAA Division I team entries
- 34,334 historical roster files
- 992,774 historical roster records
- 193,954 athlete pages collected
- 99.9964% athlete-page collection success
- final audit: **PASS**

### Milestone 2 — Performance Parsing

- 193,954 athlete pages processed
- 172,204 athletes with performances
- 6,594,540 unique performance records
- 194 resumable chunks
- 0 parser failures
- Indoor, Outdoor, and Cross Country source support
- final audit: **PASS**

### Milestone 3 — Relational Database Construction

The production DuckDB warehouse contains:

- 6,594,540 performance facts
- 990,681 historical athlete affiliations
- 193,961 source athlete profiles
- 973 teams
- 554 institutions
- 71 seasons
- 32,416 meets
- 378 raw event labels
- 1,105 source files registered with hashes
- 35 mandatory integrity checks passed
- 0 relational orphan records

Production database:

```text
data/database/ncaa_track_analytics.duckdb
```

### Milestone 4 — Canonical Identity and D1 School Stints

Milestone 4 resolved duplicate profiles, transfers, stale current-school labels, repeated performances, and person-level team conflicts.

Final results:

- 192,561 canonical people
- 6,376,667 deduplicated canonical-person performances
- 97,871 analytical duplicates removed
- 35,694 team conflicts resolved
- 174,429 chronological D1 school stints
- 6,376,505 performances mapped to exactly one school stint
- 0 unresolved conflicts
- validation: **PASS**

Detailed report:

```text
milestones/milestone_04_canonical_identity_and_school_stints.md
```

### Milestone 5 — Athlete Development Rankings

Milestone 5 measures development using:

```text
athlete value added
= observed normalized improvement
− school-held-out expected improvement
```

Key design features:

- event-specific record anchors;
- nonlinear performance levels that reward improvement near the frontier;
- stable multi-meet athlete-event periods;
- transfer-aware school attribution;
- five-fold school-grouped cross-fitting;
- equal-family, equal-athlete aggregation;
- empirical-Bayes shrinkage;
- 95% uncertainty intervals;
- minimum-sample publication rules;
- outlier and sensitivity audits.

Selected expected-improvement model:

```text
resolution_raw_mean
```

Out-of-sample metrics:

| Metric | Value |
|---|---:|
| MAE | 3.3919 |
| RMSE | 4.5327 |
| Calibration slope | 0.9704 |
| Prediction correlation | 0.4517 |
| R² | 0.2038 |

Primary publication results:

| Metric | Value |
|---|---:|
| Athlete-school units | 80,077 |
| Schools represented | 361 |
| Officially ranked schools | 353 |
| Insufficient-data schools | 8 |
| Mean shrinkage weight | 0.793 |
| Minimum alternative rank correlation | 0.9979 |
| Minimum top-10 overlap | 90% |
| Minimum top-25 overlap | 92% |
| Failed sensitivity variants | 0 |

#### Official overall top 10

| Rank | School | Athletes | Posterior score |
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

#### Event and group products

The project publishes rankings for:

- 30 canonical individual events;
- indoor and outdoor event partitions;
- men, women, and combined-gender scopes;
- Sprints;
- Middle Distance;
- Distance;
- Hurdles;
- Steeplechase;
- Jumps;
- Throws;
- Combined Events;
- Field;
- Special Events.

#### Supplemental products

| Product | Current leader |
|---|---|
| Development Consistency | Air Force |
| Elite / Frontier Development | Air Force |
| Developing baseline tier | Northern Iowa |
| Competitive baseline tier | LSU |
| Advanced baseline tier | Arkansas |
| Elite baseline tier | Air Force |
| Breakout Rate | Mercer |
| Balanced Program | LSU |
| Development Efficiency | UC San Diego |
| Ranking Robustness | Air Force |
| Inbound Transfer Development | Florida |

Detailed methodology:

```text
milestones/milestone_05_athlete_development_rankings.md
```

---

## Analytical Databases

Generated databases remain local and are excluded from Git.

### Source warehouse

```text
data/database/ncaa_track_analytics.duckdb
```

### Milestone 4 canonical-person layer

```text
data/processed/milestone4/canonical_person_layer_v1_1/
canonical_person_layer_v1_1.duckdb
```

### Milestone 4 school-stint layer

```text
data/processed/milestone4/final_school_stints_v1_1/
final_school_stints_v1_1.duckdb
```

### Milestone 5 primary publication

```text
data/processed/milestone5/athlete_development_v1/
phase_5i_publication_freeze/
ncaa_d1_athlete_development_rankings_v1.duckdb
```

### Milestone 5 event and group rankings

```text
data/processed/milestone5/athlete_development_v1/
phase_5j_event_and_group_rankings/
ncaa_d1_event_development_rankings_v1.duckdb
```

### Milestone 5 supplemental rankings

```text
data/processed/milestone5/athlete_development_v1/
phase_5k_supplemental_development_rankings/
supplemental_development_rankings_v1.duckdb
```

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
├── logs/
├── milestones/
│   ├── milestone_01_data_collection.md
│   ├── milestone_02_performance_parsing.md
│   ├── milestone_03_database_construction.md
│   ├── milestone_03_database_audit.md
│   ├── milestone_04_canonical_identity_and_school_stints.md
│   └── milestone_05_athlete_development_rankings.md
├── notebooks/
├── src/
│   ├── analysis/
│   │   ├── milestone4/
│   │   └── milestone5/
│   ├── database/
│   ├── parser/
│   ├── processing/
│   ├── scraper/
│   ├── config.py
│   ├── logger.py
│   └── main.py
├── tests/
├── README.md
├── requirements.txt
└── requirements-milestone3.txt
```

---

## Technology Stack

- Python 3.12
- DuckDB
- SQL
- Pandas
- NumPy
- BeautifulSoup
- Requests
- pathlib
- regular expressions
- CSV and HTML
- Git and GitHub

---

## Engineering and Statistical Features

- modular scraping, parsing, database, attribution, and modeling architecture;
- adaptive request pacing and resumable collection;
- chunked large-scale processing;
- deterministic identifiers;
- source-faithful raw preservation;
- historical roster-derived affiliations;
- canonical athlete identity resolution;
- transfer-aware chronological school stints;
- source-to-canonical provenance bridges;
- exact result-page evidence extraction;
- versioned analytical databases;
- read-only upstream database attachments;
- record-anchor provenance and manual review;
- event-specific nonlinear performance scaling;
- stable multi-meet period construction;
- school-grouped cross-fitting;
- expected-improvement residual scoring;
- multi-event-neutral athlete weighting;
- empirical-Bayes school shrinkage;
- confidence intervals and evidence categories;
- alternative-model and remove-best/remove-worst sensitivity tests;
- SHA-256 input and output manifests;
- hard phase gates and independent validation.

---

## Reproduction

Activate the project environment:

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

Milestone 4 scripts are stored in:

```text
src/analysis/milestone4/
```

Milestone 5 scripts are stored in:

```text
src/analysis/milestone5/
```

Every major analytical phase writes a versioned DuckDB artifact, manifests, hard checks, and a phase report. Upstream databases are attached read-only.

See the milestone reports for the exact ordered workflow and phase-specific commands.

---

## Data Availability

The repository contains:

- source code;
- SQL and analytical logic;
- dependency files;
- validation tools;
- record-anchor reference metadata;
- milestone documentation;
- reproducible build logic.

Large generated artifacts are not committed:

- athlete HTML pages;
- historical roster files;
- performance chunks;
- parser checkpoints;
- generated DuckDB databases;
- processed ranking CSVs;
- audit outputs;
- result-page caches;
- build and terminal logs.

---

## Interpretation and Limitations

The ranking estimates school-associated athlete development; it is not a randomized causal estimate of coaching quality.

Important limitations:

- results depend on recorded TFRRS coverage;
- sparse contexts may use broader expected-model fallbacks;
- small event partitions may be tied after shrinkage;
- transfer status is inferred from observed school chronology;
- adjacent ranks may not be statistically distinguishable;
- relays require lineup-aware team modeling;
- cross country requires course- and condition-aware modeling.

Relays and cross country are planned future extensions rather than unfinished Milestone 5 requirements.

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

The project now provides:

1. canonical athlete identity;
2. transfer-aware school attribution;
3. record-anchored performance levels;
4. school-held-out expected improvement;
5. athlete value added;
6. uncertainty-adjusted NCAA Division I program rankings;
7. individual-event and coaching-group rankings;
8. supplemental consistency, frontier, baseline-tier, breakout, balance, efficiency, robustness, and transfer analyses.

The next project phase is Milestone 6: exploratory visualization and interactive analytical products.