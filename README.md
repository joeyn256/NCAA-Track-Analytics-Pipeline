# NCAA Track Analytics Pipeline

A large-scale, end-to-end data engineering and analytics project that collects, structures, and analyzes historical NCAA Division I Track & Field and Cross Country data from TFRRS.

The long-term goal is to build an analytical and machine learning platform for studying athlete progression, comparing collegiate performance trends, and predicting future results.

---

## Project By the Numbers

- **714** NCAA Division I team entries
- **34,334** historical roster files
- **992,774** historical roster records
- **193,961** unique athletes identified
- **193,954** athlete profiles collected
- **172,204** athletes with recorded performances
- **6,594,540** unique structured performance records
- **194** resumable performance-data chunks
- **0** production parsing failures
- **0** duplicate performance IDs after cleanup
- **99.9964%** athlete-page collection success
- Final production audit: **PASS**

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
  Relational Database
            │
            ▼
 Analytics and Modeling
```

---

## Completed Work

### Milestone 1 — Historical Data Collection

The collection pipeline identified NCAA Division I programs, discovered historical seasons, downloaded historical rosters, consolidated nearly one million roster records, and collected more than 193,000 athlete profile pages.

Key results:

- **714** NCAA Division I team entries
- **34,334** historical roster files
- **992,774** historical roster records
- **193,961** unique athletes
- **193,954** available athlete pages
- **7** confirmed unavailable pages
- **99.9964%** collection success

### Milestone 2 — Performance Parsing

The parsing pipeline transformed locally stored athlete HTML pages into structured performance records.

Key results:

- **193,954** athlete pages processed
- **172,204** athletes with performances
- **21,750** athlete pages with no recorded meet results
- **6,594,540** unique performance records
- **194** resumable output chunks
- **0** athlete-page parsing failures
- **0** missing season classifications
- **0** duplicate performance IDs after cleanup
- Indoor, Outdoor, and Cross Country support
- Final audit result: **PASS**

The parser preserves meet information, event names, marks, times, wind readings, placements, competition rounds, result URLs, source files, and deterministic performance identifiers.

---

## Data Quality and Auditing

The initial production parse created **6,600,607** rows.

A full production audit identified:

- **5,170** exact duplicate rows
- **897** additional rows differing only in the TFRRS `highlighted` flag
- **0** duplicate groups differing in meaningful performance data

The duplicate cleanup preserved one row per deterministic performance ID and retained `highlighted=True` whenever any duplicate copy was highlighted.

Final audited performance total:

```text
6,594,540 unique performance records
```

The final production audit confirmed:

- All **194** performance chunks exist
- All **194** status chunks exist
- Row totals match
- No missing performance IDs
- No duplicate performance IDs
- No missing athlete IDs
- No missing season types
- No invalid season types
- No missing event names
- No missing marks
- No missing source files
- No athlete-page parsing failures

---

## Current Status

**Milestone 2 is complete.**

The project now contains an audited and deduplicated historical performance dataset covering approximately two decades of NCAA Division I Track & Field and Cross Country.

The next phase is the construction of a normalized relational database connecting:

- Athletes
- Schools and teams
- Historical affiliations
- Seasons
- Meets
- Events
- Performances

---

## Technology Stack

- Python
- Pandas
- BeautifulSoup
- Requests
- pathlib
- Regular expressions
- Git
- GitHub

Database and analytical technologies will be added during later milestones.

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
├── notebooks/
├── src/
│   ├── analysis/
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
└── requirements.txt
```

Large raw and processed datasets are stored locally and excluded from GitHub.

---

## Engineering Features

- Modular scraping and parsing architecture
- Centralized project configuration
- Retry and failure handling
- Adaptive request pacing
- Manifest-based input processing
- Resumable production runs
- Atomic output-file creation
- Chunked large-scale processing
- Deterministic performance identifiers
- Validation across event categories
- Production data auditing
- Safe duplicate cleanup
- Raw source-value preservation
- Persistent status and checkpoint files

---

## Milestones

- ✅ [Milestone 1 — Historical NCAA Data Collection](milestones/milestone_01_data_collection.md)
- ✅ [Milestone 2 — Athlete Performance Parsing](milestones/milestone_02_performance_parsing.md)
- ⏳ [Milestone 3 — Relational Database Construction](milestones/milestone_03_database_construction.md)
- ⏳ Milestone 4 — Data Cleaning and Feature Engineering
- ⏳ Milestone 5 — Exploratory Analytics and Visualization
- ⏳ Milestone 6 — Predictive Modeling

---

## Data Availability

The repository contains source code and project documentation but does not include the complete raw or processed datasets because they contain millions of records and several gigabytes of locally collected files.

The pipeline is designed so that each stage can be reproduced from the documented source data and processing scripts.

---

## Project Goals

The completed platform will support questions such as:

- How do NCAA athletes progress across collegiate seasons?
- Which performance patterns are associated with future improvement?
- How do progression trends differ by event, gender, school, and season?
- How accurately can future performances be predicted from historical results?
- Which athletes are improving faster than comparable competitors?