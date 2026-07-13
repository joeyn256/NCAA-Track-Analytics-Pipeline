# NCAA Track Analytics Pipeline

A large-scale, end-to-end data engineering and analytics project that collects, validates, structures, and analyzes historical NCAA Division I Track & Field and Cross Country data from TFRRS.

The project currently includes a reproducible collection pipeline, a resumable performance parser, a fully audited dataset, and a relational DuckDB analytical database containing more than 6.5 million performance records.

The long-term goal is to build an analytical and machine learning platform for studying athlete progression, comparing collegiate performance trends, and predicting future results.

---

## Project by the Numbers

* **714** NCAA Division I team directory entries
* **363** current Division I institutions
* **34,334** historical roster files
* **992,774** raw historical roster records
* **990,681** unique historical athlete affiliations
* **193,961** unique athletes
* **193,954** athlete profiles collected
* **172,204** athletes with recorded performances
* **21,750** athletes with no recorded meet results
* **6,594,540** unique performance records
* **32,416** meets
* **378** raw event labels
* **973** total teams represented in the database
* **554** total institutions represented in the database
* **71** season records
* **194** resumable performance-data chunks
* **1,105** canonical source files registered with SHA-256 hashes
* **35** mandatory database integrity checks passed
* **0** production parsing failures
* **0** duplicate performance IDs
* **0** relational orphan records
* **99.9964%** athlete-page collection success

Final Milestone 3 production build and independent validation: **PASS**

---

## Current Pipeline

```text
NCAA Division I Directory
            │
            ▼
        Schools
            │
            ▼
    Historical Seasons
            │
            ▼
    Historical Rosters
            │
            ▼
      Unique Athletes
            │
            ▼
      Athlete Pages
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
 Data Cleaning and Features
            │
            ▼
 Analytics and Modeling
```

---

## Completed Work

### Milestone 1 — Historical Data Collection

The collection pipeline identified NCAA Division I programs, discovered historical seasons, downloaded historical rosters, consolidated nearly one million roster records, and collected more than 193,000 athlete profile pages.

Key results:

* **714** NCAA Division I team entries
* **34,334** historical roster files
* **992,774** historical roster records
* **193,961** unique athletes
* **193,954** available athlete pages
* **7** confirmed unavailable athlete pages
* **99.9964%** athlete-page collection success
* Final collection audit: **PASS**

---

### Milestone 2 — Performance Parsing

The parsing pipeline transformed locally stored athlete HTML pages into structured performance records.

Key results:

* **193,954** athlete pages processed
* **172,204** athletes with performances
* **21,750** athlete pages with no recorded meet results
* **6,594,540** unique performance records
* **194** resumable performance chunks
* **194** parser-status chunks
* **0** athlete-page parsing failures
* **0** missing season classifications
* **0** duplicate performance IDs after cleanup
* Indoor, Outdoor, and Cross Country support
* Final performance audit: **PASS**

The parser preserves:

* Athlete and school information
* Season year and season type
* Meet names and dates
* Event names
* Marks and secondary marks
* Wind readings
* Placements
* Competition rounds
* Result and meet URLs
* Source filenames
* Deterministic performance identifiers

---

### Milestone 3 — Relational Database Construction

Milestone 3 converted the audited collection and performance outputs into a reproducible DuckDB analytical database.

The production database is generated locally at:

```text
data/database/ncaa_track_analytics.duckdb
```

Final database results:

* **703,868,928 bytes** in the completed database
* **6,594,540** performance facts
* **6,594,540** distinct performance IDs
* **990,681** unique historical athlete affiliations
* **193,961** athletes
* **973** teams
* **554** institutions
* **71** seasons
* **32,416** meets
* **378** raw event labels
* **1,105** registered canonical source files
* **35** hard integrity checks passed
* **0** failed hard checks
* **0** relational orphan records

Historical affiliations were constructed from roster records rather than assuming that an athlete’s current profile school applied to every season.

All raw marks, dates, places, URLs, event labels, and source filenames remain preserved. Full mark and event normalization is deferred until Milestone 4.

The completed build was reopened through a separate read-only validation process, and every independent production check passed.

---

## Database Architecture

The DuckDB database contains four schemas:

| Schema      | Purpose                                                                |
| ----------- | ---------------------------------------------------------------------- |
| `raw`       | Source-faithful views over canonical CSV inputs                        |
| `core`      | Relational dimensions, historical affiliations, and performance facts  |
| `analytics` | Reserved for normalized analytical tables, features, and views         |
| `audit`     | Build runs, source hashes, row counts, conflicts, and integrity checks |

### Core Tables

| Table                       | Purpose                                                     |
| --------------------------- | ----------------------------------------------------------- |
| `core.schools`              | Institution-level school records                            |
| `core.teams`                | Gender-specific and historical team records                 |
| `core.athletes`             | Unique athlete records and current profile information      |
| `core.seasons`              | Indoor, Outdoor, and Cross Country seasons                  |
| `core.meets`                | Distinct meet records                                       |
| `core.events`               | Source-faithful event labels                                |
| `core.athlete_affiliations` | Historical roster-derived athlete-team-season relationships |
| `core.performances`         | Complete performance fact table                             |

### Audit Tables

The database records:

* Build metadata
* Schema versions
* Source-file paths
* File sizes
* SHA-256 hashes
* Source row counts
* Core table counts
* Integrity checks
* Historical roster duplicate groups
* Affiliation coverage
* Dimension conflicts

---

## Historical Affiliation Handling

The raw historical roster source contains:

```text
992,774 roster rows
990,681 unique affiliation records
2,093 duplicate excess rows
```

The database preserves evidence of the duplicate rows in the audit schema while loading only unique historical affiliations into the core schema.

Indoor roster seasons are linked using the ending year.

For example:

```text
2022-23 Indoor → 2023_indoor
```

Of the 6,594,540 performance records:

* **5,916,703** matched an exact historical roster affiliation
* **479** had a blank source team ID
* **32,776** belonged to performance-only historical teams
* **644,582** belonged to directory teams without an exact roster-season match

Unmatched performance records remain in the database with a null affiliation reference. The build does not invent historical affiliations from current athlete-profile school values.

---

## Data Quality and Auditing

The initial production performance parse created:

```text
6,600,607 rows
```

A full production audit identified:

* **5,170** exact duplicate rows
* **897** additional rows differing only in the TFRRS `highlighted` flag
* **0** duplicate groups differing in meaningful performance data

The duplicate cleanup preserved one row per deterministic performance ID and retained `highlighted=True` whenever any duplicate copy was highlighted.

Final audited performance total:

```text
6,594,540 unique performance records
```

The completed database audit confirmed:

* All **194** performance chunks exist
* All **194** parser-status chunks exist
* Performance totals match parser-status totals
* No missing performance IDs
* No duplicate performance IDs
* No blank athlete IDs
* No missing season types
* No invalid season types
* No missing event names
* No missing raw marks
* No missing meet dates
* No parser failures
* No athlete, team, season, meet, or event orphan records
* No affiliation athlete, team, or season orphan records
* All **1,105** canonical source files have SHA-256 hashes
* All **35** hard database checks passed

---

## Reproducing the Database

### 1. Activate the virtual environment

```bash
source .venv/bin/activate
```

### 2. Install the Milestone 3 dependency

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

---

## Technology Stack

* Python 3.12
* DuckDB 1.5.4
* SQL
* Pandas
* BeautifulSoup
* Requests
* pathlib
* Regular expressions
* CSV
* HTML
* Git
* GitHub

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
│   └── milestone_03_database_audit.md
│
├── notebooks/
├── src/
│   ├── analysis/
│   ├── database/
│   │   ├── build_database.py
│   │   ├── diagnose_milestone3_keys.py
│   │   ├── finalize_milestone3_documentation.py
│   │   ├── inspect_milestone3_inputs.py
│   │   ├── profile_milestone3_sources.py
│   │   ├── schema.sql
│   │   ├── validate_milestone3_schema.py
│   │   ├── validate_production_database.py
│   │   └── verify_duckdb_environment.py
│   │
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

Large raw data, processed performance chunks, athlete HTML pages, generated databases, and build logs are stored locally and excluded from GitHub.

---

## Engineering Features

* Modular scraping, parsing, and database architecture
* Centralized project configuration
* Retry and failure handling
* Adaptive request pacing
* Manifest-based input processing
* Resumable production runs
* Atomic output-file creation
* Chunked large-scale processing
* Deterministic performance identifiers
* Source-faithful raw-value preservation
* Historical roster-derived affiliations
* Transactional database construction
* Staging database publication
* Automatic rollback and cleanup on failure
* Independent read-only production validation
* SHA-256 source-file registration
* Relational orphan detection
* Duplicate roster auditing
* Persistent status and checkpoint files
* Reproducible dependency pinning

---

## Current Status

**Milestone 3 is complete.**

The project now contains an audited and deduplicated historical NCAA performance dataset and a reproducible relational DuckDB analytical database.

The next phase is Milestone 4: cleaning and feature engineering.

Planned work includes:

* Canonical event classification
* Mark and time parsing
* Distance and event-family normalization
* Wind and placement normalization
* Athlete progression features
* Season-over-season improvement metrics
* Analytical views for exploration and modeling

---

## Milestones

* ✅ [Milestone 1 — Historical NCAA Data Collection](milestones/milestone_01_data_collection.md)
* ✅ [Milestone 2 — Athlete Performance Parsing](milestones/milestone_02_performance_parsing.md)
* ✅ [Milestone 3 — Relational Database Construction](milestones/milestone_03_database_construction.md)
* ✅ [Milestone 3 — Production Database Audit](milestones/milestone_03_database_audit.md)
* ⏳ Milestone 4 — Data Cleaning and Feature Engineering
* ⏳ Milestone 5 — Exploratory Analytics and Visualization
* ⏳ Milestone 6 — Predictive Modeling

---

## Data Availability

The repository contains source code, SQL schemas, dependency files, validation tools, and project documentation.

The complete raw and processed datasets are not committed because they contain millions of records and several gigabytes of locally collected files.

The following generated artifacts are also excluded from Git:

* Raw athlete HTML pages
* Historical roster files
* Processed performance chunks
* Parser checkpoints
* DuckDB database files
* Temporary build databases
* Build logs
* Validation logs

The pipeline is designed so that every stage can be reproduced from the documented inputs and processing scripts.

---

## Project Goals

The completed platform will support questions such as:

* How do NCAA athletes progress across collegiate seasons?
* Which performance patterns are associated with future improvement?
* How do progression trends differ by event, gender, school, and season?
* How accurately can future performances be predicted from historical results?
* Which athletes are improving faster than comparable competitors?
* How do transfers and historical team affiliations affect progression?
* Which programs consistently develop athletes beyond expected trends?
