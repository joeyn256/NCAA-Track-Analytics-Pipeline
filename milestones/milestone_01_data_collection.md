# Milestone 1 — Historical NCAA Division I Data Collection Pipeline

<!-- RECRUITER_SUMMARY_START -->
## At a Glance

**Status:** Complete

### Executive Summary

Built the historical NCAA Division I collection layer: program discovery, season discovery, roster collection, athlete-profile collection, retry handling, and source-level audit controls. This milestone created the raw historical evidence used by every later database and modeling phase.

### Headline Results

| Metric | Final result |
|---|---:|
| NCAA Division I team entries | 714 |
| Historical roster files | 34,334 |
| Historical roster records | 992,774 |
| Source athlete profiles | 193,961 |
| Athlete pages collected | 193,954 |
| Confirmed unavailable pages | 7 |
| Collection success rate | 99.9964% |
| Final audit | **PASS** |

### What This Milestone Demonstrates

- large-scale and resilient web scraping;
- adaptive request pacing, retries, and failure handling;
- resumable collection and checkpoint design;
- deterministic source manifests and file organization;
- production validation across nearly 200,000 athlete pages.

[Back to the milestone index](README.md) · [Next: Milestone 2](milestone_02_performance_parsing.md)

---
<!-- RECRUITER_SUMMARY_END -->

---

## Overview

This milestone marks the completion of the data collection phase for the **NCAA Track Analytics Pipeline**.

The objective of this phase was to design and build a scalable, fault-tolerant data collection pipeline capable of downloading historical NCAA Division I Track & Field and Cross Country data from TFRRS.

The completed pipeline collects:

- NCAA Division I men's and women's programs
- Historical indoor, outdoor, and cross-country seasons
- Historical team rosters
- Unique athlete identifiers
- Complete athlete profile pages containing performance histories

This milestone establishes the raw dataset that will be used throughout the remainder of the project for performance parsing, database construction, statistical analysis, visualization, and predictive modeling.

---

# Highlights

- **714** NCAA Division I team entries collected
- **34,334** historical roster files processed
- **992,774** historical roster records collected
- **193,961** unique athletes identified
- **193,954** athlete profile pages downloaded
- **99.9964%** successful athlete-page collection
- **0.02%** production request error rate

---

## Objectives

The primary objectives for this milestone were:

1. Discover every NCAA Division I men's and women's Track & Field program.
2. Collect every available historical season.
3. Download historical rosters for every season.
4. Consolidate all roster data.
5. Identify every unique athlete.
6. Download every available athlete profile page.
7. Create a fully resumable scraping pipeline.
8. Minimize duplicate requests and server load.

---

## Results

| Metric | Result |
|---|---:|
| NCAA Division I team entries | **714** |
| Historical roster files | **34,334** |
| Historical roster records | **992,774** |
| Unique athletes | **193,961** |
| Athlete pages downloaded | **193,954** |
| Unavailable athlete pages | **7** |
| Athlete-page success rate | **99.9964%** |

The seven unavailable athlete pages were manually verified and were not accessible through TFRRS. They were excluded from downstream processing rather than replaced with estimated or fabricated data.

---

## Final Production Run

The adaptive production scraper completed with the following statistics.

```text
Total athletes:       193,961
Pages attempted:      110,026
Pages saved:          110,019
Existing skipped:     83,935
Permanent failures:   7
Request attempts:     110,045
Request errors:       26
Overall error rate:   0.02%
Final delay:          0.100–0.100 seconds
Total runtime:        9h 24m 34s
```

---

## Data Collection Pipeline

```text
TFRRS Division I Directory
            │
            ▼
        schools.csv
            │
            ▼
 Historical Season Discovery
            │
            ▼
      seasons/*.csv
            │
            ▼
 Historical Roster Collection
            │
            ▼
 historical_rosters/
            │
            ▼
 all_roster_records.csv
            │
            ▼
 unique_athletes.csv
            │
            ▼
 Athlete Profile Collection
            │
            ▼
 athlete_pages/
```

---

## Repository Components Used

### Scraping

The `src/scraper/` package contains the scraping pipeline.

```text
src/scraper/
├── scrape_schools.py
├── scrape_seasons.py
├── scrape_roster.py
├── scrape_historical_rosters.py
├── scrape_athletes.py
├── scrape_athletes_adaptive.py
├── tfrrs_utils.py
└── debug_tools/
```

Responsibilities included:

- School discovery
- Historical season discovery
- Historical roster downloads
- Athlete profile downloads
- Adaptive request pacing
- Retry handling
- Failure logging

---

### Processing

```text
src/processing/
└── consolidate_rosters.py
```

Responsibilities included:

- Reading every historical roster
- Combining all valid CSV files
- Removing duplicate athletes
- Building the master athlete dataset

---

### Configuration

```text
src/config.py
src/logger.py
```

These modules centralized project configuration and logging.

---

### Tests

```text
tests/
```

Used to validate:

- Imports
- HTML downloads
- Pipeline behavior
- Scraper correctness

---

## Technologies Used

### Programming Language

- Python

### Libraries

- Pandas
- Requests
- BeautifulSoup
- pathlib
- logging
- random
- time

### Development Tools

- Visual Studio Code
- macOS Terminal
- Python Virtual Environments
- Git
- GitHub

---

## Technical Skills Demonstrated

### Web Scraping

- HTML parsing with BeautifulSoup
- Dynamic URL generation
- Historical page discovery
- Request validation
- Retry logic
- Failure logging
- Adaptive request pacing
- Server-error recovery

### Data Engineering

- ETL pipeline development
- Large-scale file processing
- Recursive directory traversal
- CSV consolidation
- Duplicate detection
- Unique identifier management
- Incremental checkpointing
- Raw versus processed data organization

### Software Engineering

- Modular project architecture
- Reusable utility modules
- Centralized configuration
- Exception handling
- Progress monitoring
- Resume and recovery workflows
- Test and production separation
- Debug tool organization

### Performance Optimization

The production athlete scraper dynamically adjusted request delays based on observed error rates.

Features included:

- Automatic speed adjustments
- Five-minute progress reports
- Runtime estimation
- Existing file detection
- Retry handling
- Permanent failure logging

Final production request error rate:

**0.02%**

---

## Engineering Challenges Solved

### Duplicate Athletes

Many athletes appeared in:

- Indoor seasons
- Outdoor seasons
- Cross Country seasons
- Multiple academic years

Although nearly one million roster records were collected, consolidation reduced them to **193,961 unique athletes**, preventing duplicate downloads.

---

### Empty Historical Seasons

Some season configurations existed in TFRRS but contained no roster information.

The pipeline detected these cases and recorded completion without repeatedly requesting empty pages.

---

### Temporary Server Errors

During collection the scraper encountered:

- HTTP 502 Bad Gateway
- HTTP 504 Gateway Timeout
- CloudFront request blocking
- Temporary connection failures

The scraper recovered automatically using:

- Multiple retry attempts
- Increasing retry delays
- Adaptive pacing
- Resume support
- Failure tracking

---

### Long Running Pipeline

The collection process required many hours of execution.

Successful downloads were saved immediately and skipped during future runs, allowing recovery from:

- Internet interruptions
- Server failures
- Manual stops
- Computer restarts
- Temporary rate limiting

---

## Repository Structure

```text
NCAA Track Analytics Pipeline/
├── data/
│   ├── raw/
│   │   ├── athlete_pages/
│   │   ├── historical_rosters/
│   │   ├── meets/
│   │   ├── performances/
│   │   ├── rosters/
│   │   ├── seasons/
│   │   ├── all_roster_records.csv
│   │   ├── schools.csv
│   │   └── unique_athletes.csv
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

---

## Data Quality Decisions

The project does not estimate or fabricate missing information.

The seven unavailable athlete pages remain documented as unavailable and are excluded from downstream analysis to preserve dataset integrity and reproducibility.

---

# Final Outcome

✅ Successfully collected nearly two decades of NCAA Division I Track & Field and Cross Country data.

The completed dataset contains:

- **992,774** historical roster records
- **193,961** unique athletes
- **193,954** locally stored athlete pages
- Men's and women's NCAA Division I programs
- Indoor, outdoor, and cross-country seasons

This milestone demonstrates the ability to design, implement, and execute a large-scale data collection workflow rather than a single-purpose web scraper.

---

## Lessons Learned

The largest lessons from this milestone were:

- Recovery and checkpointing should be designed from the beginning.
- Unique identifiers should be established before downstream collection.
- Saving successful work immediately is essential for long-running jobs.
- Server-side failures should be expected rather than treated as exceptional.
- Adaptive pacing improves both speed and reliability.
- Project organization becomes increasingly important as pipelines grow.
- Raw data should remain separate from processed outputs.
- Missing data should be documented rather than invented.

---

## Milestone Status

**✅ Completed**

Historical NCAA Division I data collection has been successfully completed.

---

## Final Status

**Milestone 1 is complete.**

The collection layer supplied the historical roster and athlete-profile
evidence used by the parser, warehouse, identity, attribution, and
modeling milestones.
