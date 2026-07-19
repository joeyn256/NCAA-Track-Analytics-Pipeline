# NCAA Track Analytics Pipeline

A large-scale, end-to-end data engineering and sports analytics project for collecting, validating, reconstructing, and analyzing historical NCAA Division I Track & Field and Cross Country data from TFRRS.

The project now includes:

- a reproducible historical data-collection pipeline;
- a resumable performance parser;
- a fully audited relational DuckDB database;
- transfer-aware historical team attribution;
- canonical athlete identity resolution;
- person-level performance deduplication;
- chronological NCAA Division I school stints;
- complete source-performance provenance.

The next phase will normalize events and marks, measure athlete development, and rank NCAA Division I programs by how effectively their athletes improve.

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

### Canonical identity and school-stint layer

| Metric | Final value |
|---|---:|
| Canonical people | 192,561 |
| High-confidence multi-profile people | 1,352 |
| Source profiles in merged identity components | 2,752 |
| School-stint-eligible source performance rows | 6,474,538 |
| Deduplicated canonical-person performances | 6,376,667 |
| Duplicate source performance rows removed | 97,871 |
| D1-eligible performances mapped to school stints | 6,376,505 |
| Person-meet team assignments | 3,867,249 |
| Canonical people with D1 school stints | 170,655 |
| Final D1 school stints | 174,429 |
| People represented by multiple school stints | 3,612 |
| People returning to a previous team | 44 |
| Person-performance team conflicts resolved | 35,694 |
| Remaining person-performance team conflicts | 0 |
| Remaining unreviewed chronology islands | 0 |

### Validation status

- 0 production parsing failures
- 0 duplicate source performance IDs
- 0 relational orphan records
- 0 missing D1 performance-to-stint assignments
- 0 duplicate final school-stint IDs
- 0 duplicate final performance-map IDs
- 0 unreviewed chronology exceptions
- Milestone 1 final audit: **PASS**
- Milestone 2 final audit: **PASS**
- Milestone 3 production build and independent validation: **PASS**
- Milestone 4 canonical identity and school-stint validation: **PASS**

---

## Current Pipeline

```text
NCAA Division I Directory
            │
            ▼
        School Teams
            │
            ▼
     Historical Seasons
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
 Relational DuckDB Database
            │
            ▼
 Transfer-Aware Attribution
            │
            ▼
 Canonical Athlete Identity
            │
            ▼
 Person-Level Deduplication
            │
            ▼
 Chronological D1 School Stints
            │
            ▼
 Event and Mark Normalization
            │
            ▼
 Athlete Development Scoring
            │
            ▼
 D1 Program Development Rankings
```

---

## Completed Work

### Milestone 1 — Historical Data Collection

The collection pipeline identified NCAA Division I programs, discovered historical seasons, downloaded historical rosters, consolidated nearly one million roster records, and collected more than 193,000 athlete profile pages.

Key results:

- 714 NCAA Division I team entries
- 34,334 historical roster files
- 992,774 historical roster records
- 193,961 source athlete profiles
- 193,954 available athlete pages
- 7 confirmed unavailable athlete pages
- 99.9964% athlete-page collection success
- final collection audit: **PASS**

---

### Milestone 2 — Performance Parsing

The parsing pipeline transformed locally stored athlete HTML pages into structured performance records.

Key results:

- 193,954 athlete pages processed
- 172,204 athletes with performances
- 21,750 athlete pages with no recorded meet results
- 6,594,540 unique performance records
- 194 resumable performance chunks
- 194 parser-status chunks
- 0 athlete-page parsing failures
- 0 missing season classifications
- 0 duplicate performance IDs after cleanup
- Indoor, Outdoor, and Cross Country support
- final performance audit: **PASS**

The parser preserves:

- athlete and source-school information;
- season year and season type;
- meet names and dates;
- raw event names;
- marks and secondary marks;
- wind readings;
- placements;
- competition rounds;
- result and meet URLs;
- source filenames;
- deterministic performance identifiers.

---

### Milestone 3 — Relational Database Construction

Milestone 3 converted the audited collection and performance outputs into a reproducible DuckDB analytical database.

The production database is generated locally at:

```text
data/database/ncaa_track_analytics.duckdb
```

Final database results:

- 703,868,928 bytes
- 6,594,540 performance facts
- 6,594,540 distinct performance IDs
- 990,681 unique historical athlete affiliations
- 193,961 athletes
- 973 teams
- 554 institutions
- 71 seasons
- 32,416 meets
- 378 raw event labels
- 1,105 registered canonical source files
- 35 mandatory integrity checks passed
- 0 failed hard checks
- 0 relational orphan records

Historical affiliations were constructed from roster evidence rather than assuming that an athlete's current profile school applied to every season.

All source-faithful marks, dates, placements, event labels, URLs, and filenames remain preserved.

---

### Milestone 4 — Canonical Athlete Identity and D1 School Stints

Milestone 4 reconstructed athlete identity and historical team membership so that development can be credited to the correct NCAA Division I program.

This phase addressed several issues that could not be solved safely from current profile metadata alone:

- athletes with multiple TFRRS profile IDs;
- transfers across NCAA programs;
- stale profile-school labels;
- historical performances listed under several team sections;
- duplicate performances repeated across profiles;
- conflicting team assignments for the same person-performance;
- later performances at non-D1 institutions;
- isolated but legitimate chronology patterns.

#### Canonical athlete identity

The identity layer mapped:

```text
193,961 source athlete profiles
        ↓
192,561 canonical people
```

Only validated high-confidence components were merged.

Identity candidates required:

- matching normalized names;
- compatible gender;
- repeated exact individual-performance signatures;
- sufficient overlap across the smaller profile;
- relay and medley exclusions during identity discovery.

Final identity results:

| Metric | Value |
|---|---:|
| High-confidence multi-profile people | 1,352 |
| Profiles in merged components | 2,752 |
| Components containing multiple normalized names | 0 |
| Profiles assigned to more than one canonical person | 0 |

#### Person-performance deduplication

Duplicate performances were removed analytically within each canonical person while preserving every source performance ID in a bridge table.

The deduplication signature used:

- season;
- meet;
- event;
- primary mark;
- secondary mark;
- wind;
- place;
- competition round;
- raw place;
- result URL.

Final deduplication results:

| Category | Canonical rows | Source rows | Rows removed |
|---|---:|---:|---:|
| Multi-profile duplicate signatures | 94,089 | 191,960 | 97,871 |
| Single-profile signatures | 6,282,578 | 6,282,578 | 0 |
| **Total** | **6,376,667** | **6,474,538** | **97,871** |

#### Person-level team conflict resolution

Duplicate profiles sometimes attributed the same exact performance to different teams.

All 35,694 person-performance conflicts were resolved:

| Resolution method | Conflict groups |
|---|---:|
| Canonical team uniquely matched the source team | 34,285 |
| Unique strongest attribution evidence | 1,247 |
| Exact result-page team evidence | 158 |
| Constrained person-season continuity evidence | 4 |
| **Total** | **35,694** |

Remaining person-performance team conflicts: **0**

The constrained continuity rule was used only when:

- the exact result row could not provide a unique team;
- one team was directly established for the same person in the immediately preceding indoor season of the same calendar year;
- the unresolved source team or school agreed with that team.

It was not used as a general current-team or chronology fallback.

#### Final D1 school stints

The validated canonical-person performances were ordered chronologically and collapsed into consecutive school-team runs.

The final process:

1. reduced performances to one team assignment per canonical person and meet;
2. parsed every meet date;
3. ordered each person's appearances chronologically;
4. collapsed consecutive appearances for the same team;
5. preserved legitimate returns to a previous school as separate stints;
6. mapped every eligible canonical performance to exactly one stint.

Final school-stint results:

| Metric | Value |
|---|---:|
| D1-eligible canonical performances | 6,376,505 |
| Person-meet assignments | 3,867,249 |
| Canonical people with D1 stints | 170,655 |
| Final school stints | 174,429 |
| People with multiple stints | 3,612 |
| People returning to a previous team | 44 |
| Missing performance-to-stint assignments | 0 |
| Duplicate school-stint IDs | 0 |
| Duplicate performance-map IDs | 0 |

#### Reviewed chronology exceptions

Two single-meet A→B→A patterns remained after final stint construction.

Exact TFRRS result-page evidence confirmed that the middle-team assignments were valid:

| Athlete | Meet | Accepted team |
|---|---|---|
| Emily Venters | 2018 Nuttycombe Wisconsin Invitational | Colorado |
| Daniella Hubble | 2023 Wisconsin Badger Classic | Illinois |

These cases are retained and registered explicitly as reviewed chronology exceptions.

They were not silently overwritten, and no unreviewed chronology islands remain.

The complete Milestone 4 report is available in:

```text
milestones/milestone_04_canonical_identity_and_school_stints.md
```

---

## Analytical Databases

Generated databases remain local and are excluded from Git.

### Milestone 3 source database

```text
data/database/ncaa_track_analytics.duckdb
```

This is the immutable relational source database.

### Final canonical-person database

```text
data/processed/milestone4/canonical_person_layer_v1_1/
canonical_person_layer_v1_1.duckdb
```

Primary objects:

- `canonical_person_bridge`
- `canonical_people`
- `canonical_person_performance_map`
- `canonical_person_performances`
- `conflict_resolution_registry`
- `school_stint_person_performances`

### Final school-stint database

```text
data/processed/milestone4/final_school_stints_v1_1/
final_school_stints_v1_1.duckdb
```

Primary objects:

- `person_meet_team_assignments`
- `canonical_person_school_stints`
- `school_stint_performance_map`
- `chronology_exception_registry`
- `chronology_exception_source_rows`
- `transfer_school_stints`
- `reviewed_chronology_exceptions`
- `analytical_school_stints`

---

## Database Architecture

The Milestone 3 DuckDB database contains four schemas:

| Schema | Purpose |
|---|---|
| `raw` | Source-faithful views over canonical CSV inputs |
| `core` | Relational dimensions, historical affiliations, and performance facts |
| `analytics` | Reserved for normalized analytical tables, features, and views |
| `audit` | Build runs, source hashes, row counts, conflicts, and integrity checks |

### Core tables

| Table | Purpose |
|---|---|
| `core.schools` | Institution-level school records |
| `core.teams` | Gender-specific and historical team records |
| `core.athletes` | Source athlete profiles and current profile metadata |
| `core.seasons` | Indoor, Outdoor, and Cross Country seasons |
| `core.meets` | Distinct meet records |
| `core.events` | Source-faithful event labels |
| `core.athlete_affiliations` | Historical roster-derived athlete-team-season relationships |
| `core.performances` | Complete source performance fact table |

### Audit tables

The source database records:

- build metadata;
- schema versions;
- source-file paths;
- file sizes;
- SHA-256 hashes;
- source row counts;
- core table counts;
- integrity checks;
- historical roster duplicate groups;
- affiliation coverage;
- dimension conflicts.

---

## Historical Affiliation Handling

The raw historical roster source contains:

```text
992,774 roster rows
990,681 unique affiliation records
2,093 duplicate excess rows
```

The source database preserves evidence of duplicate roster rows in the audit schema while loading only unique historical affiliations into the core schema.

Indoor roster seasons are linked using the ending year:

```text
2022-23 Indoor → 2023_indoor
```

Of the 6,594,540 source performance records:

- 5,916,703 matched an exact historical roster affiliation;
- 479 had a blank source team ID;
- 32,776 belonged to performance-only historical teams;
- 644,582 belonged to directory teams without an exact roster-season match.

Milestone 4 added a separate transfer-aware attribution and person-level conflict-resolution layer rather than mutating the original source facts.

---

## Data Quality and Auditing

The initial production parse created:

```text
6,600,607 rows
```

A full production audit identified:

- 5,170 exact duplicate rows;
- 897 additional rows differing only in the TFRRS `highlighted` flag;
- 0 duplicate groups differing in meaningful performance data.

The source-level duplicate cleanup preserved one row per deterministic performance ID and retained `highlighted=True` whenever any duplicate copy was highlighted.

Final audited source performance total:

```text
6,594,540 unique performance records
```

Milestone 4 then removed duplicate performances occurring across multiple profiles for the same canonical person:

```text
97,871 additional analytical duplicate rows removed
```

Every original source performance remains traceable through the canonical-person performance map.

---

## Reproducing the Milestone 3 Database

### 1. Activate the virtual environment

```bash
source .venv/bin/activate
```

### 2. Install the Milestone 3 dependency set

```bash
python -m pip install \
    --requirement requirements-milestone3.txt
```

### 3. Run the production preflight

```bash
python src/database/build_database.py \
    --preflight-only
```

### 4. Build the database

```bash
set -o pipefail

python src/database/build_database.py \
    --build \
    2>&1 | tee data/database/milestone3_build.log
```

The builder uses a temporary staging database and only publishes the final database after every mandatory audit passes.

### 5. Validate the completed database

```bash
python src/database/validate_production_database.py \
    | tee data/database/milestone3_production_validation.txt
```

The validator opens the production database in read-only mode and independently checks table counts, source hashes, performance uniqueness, affiliation coverage, raw views, and relational integrity.

Milestone 4 is reproduced through the ordered scripts in:

```text
src/analysis/milestone4/
```

Each major phase writes to a separate audit directory or DuckDB database and attaches prior databases in read-only mode.

---

## Technology Stack

- Python 3.12
- DuckDB
- SQL
- Pandas
- BeautifulSoup
- Requests
- pathlib
- regular expressions
- CSV
- HTML
- Git
- GitHub

---

## Repository Structure

```text
NCAA Track Analytics Pipeline/
├── data/
│   ├── raw/
│   ├── processed/
│   └── database/
│
├── logs/
├── milestones/
│   ├── milestone_01_data_collection.md
│   ├── milestone_02_performance_parsing.md
│   ├── milestone_03_database_construction.md
│   ├── milestone_03_database_audit.md
│   └── milestone_04_canonical_identity_and_school_stints.md
│
├── notebooks/
├── src/
│   ├── analysis/
│   │   └── milestone4/
│   ├── database/
│   ├── parser/
│   ├── processing/
│   ├── scraper/
│   ├── config.py
│   ├── logger.py
│   └── main.py
│
├── tests/
├── README.md
├── requirements.txt
└── requirements-milestone3.txt
```

Large raw data, processed performance chunks, athlete HTML pages, generated databases, audit outputs, and build logs are stored locally and excluded from GitHub.

---

## Engineering Features

- modular scraping, parsing, database, attribution, and analytics architecture;
- centralized project configuration;
- retry and failure handling;
- adaptive request pacing;
- manifest-based input processing;
- resumable production runs;
- atomic output-file creation;
- chunked large-scale processing;
- deterministic source performance identifiers;
- source-faithful raw-value preservation;
- historical roster-derived affiliations;
- transfer-aware team attribution;
- canonical athlete identity resolution;
- analytical duplicate-profile merging;
- source-to-canonical provenance bridges;
- person-level team conflict registries;
- exact result-page evidence extraction;
- targeted and documented fallback rules;
- chronological school-stint reconstruction;
- explicit chronology exception registry;
- read-only input database attachments;
- separate versioned analytical databases;
- transactional database construction;
- independent validation;
- SHA-256 source-file registration;
- relational orphan detection;
- persistent status and checkpoint files;
- reproducible dependency pinning.

---

## Current Status

**Milestone 4 is complete.**

The project now has a validated analytical foundation that answers three critical questions for every eligible performance:

1. Which canonical person produced it?
2. Which historical team should receive attribution?
3. Which chronological school stint does it belong to?

The next phase is **Milestone 5 — Athlete Development Rankings**.

Planned work includes:

- canonical event-name normalization;
- mark and time parsing;
- event-family classification;
- indoor/outdoor comparability rules;
- cross-country distance handling;
- valid-performance filtering;
- baseline and endpoint selection;
- event-specific performance scaling;
- human-limit-aware improvement scoring;
- athlete-level development scores;
- school-level aggregation and reliability controls;
- NCAA Division I program rankings.

---

## Milestones

- ✅ [Milestone 1 — Historical NCAA Data Collection](milestones/milestone_01_data_collection.md)
- ✅ [Milestone 2 — Athlete Performance Parsing](milestones/milestone_02_performance_parsing.md)
- ✅ [Milestone 3 — Relational Database Construction](milestones/milestone_03_database_construction.md)
- ✅ [Milestone 3 — Production Database Audit](milestones/milestone_03_database_audit.md)
- ✅ [Milestone 4 — Canonical Athlete Identity and D1 School Stints](milestones/milestone_04_canonical_identity_and_school_stints.md)
- ⏳ Milestone 5 — Athlete Development Rankings
- ⏳ Milestone 6 — Exploratory Analytics and Visualization
- ⏳ Milestone 7 — Predictive Modeling

---

## Data Availability

The repository contains:

- source code;
- SQL schemas;
- dependency files;
- validation tools;
- milestone documentation;
- reproducible build logic.

The complete raw and processed datasets are not committed because they contain millions of records and several gigabytes of locally collected files.

Excluded generated artifacts include:

- raw athlete HTML pages;
- historical roster files;
- processed performance chunks;
- parser checkpoints;
- DuckDB database files;
- temporary and diagnostic databases;
- result-page HTML caches;
- build logs;
- validation logs;
- generated audit CSV files.

The project is structured so that every stage can be reproduced from documented inputs and processing scripts.

---

## Project Goals

The completed platform will support questions such as:

- How do NCAA athletes progress across their collegiate careers?
- Which programs produce the strongest athlete development?
- How should improvement be measured across events with different scales?
- How does starting ability affect the significance of an improvement?
- Which schools improve already-elite athletes most effectively?
- How do transfer athletes develop at each school they attend?
- How do progression trends differ by event, gender, school, and season?
- Which performance patterns are associated with future improvement?
- How accurately can future performances be predicted?
- Which athletes are improving faster than comparable competitors?

The central analytical goal is to distinguish raw talent acquisition from genuine athlete development and produce transparent, evidence-based NCAA Division I program rankings.
