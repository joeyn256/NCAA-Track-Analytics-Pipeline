# Case Study — NCAA Division I Athlete Development Analytics

## Project summary

I built an end-to-end analytics system that converts historical NCAA Division I
track-and-field results into school-level athlete-development rankings,
seasonal trends, program comparisons, and a publicly accessible Streamlit
explorer.

The project began as a web-scraping and database exercise and evolved into a
production-style analytical pipeline with canonical athlete identity,
school-stint attribution, model validation, compact deployment data,
continuous integration, live health checks, and guarded release automation.

## The problem

Raw collegiate performance data is not immediately suitable for evaluating
athlete development. The source data contains duplicate athlete profiles,
transfers, stale school labels, repeated performances, unequal event scales,
different starting levels, sparse cohorts, and uneven historical coverage.

A useful system therefore needed to answer several engineering and modeling
questions:

1. Which records represent the same athlete?
2. Which school should receive credit for each performance?
3. How can performances from different events be compared?
4. How much improvement should be expected from an athlete's starting level?
5. How can schools be compared without allowing high-volume events to dominate?
6. How can the analytical results be deployed without publishing private or
   oversized source files?

## Data scale

| Measure | Result |
|---|---:|
| NCAA Division I team entries collected | 714 |
| Unique athletes | 193,961 |
| Standardized performance records | 6,594,540 |
| Deduplicated canonical performances | 6,376,667 |
| Public deployment rows | 2,918,594 |
| Public resource tables | 81 |
| Public metadata tables | 5 |

## Technical approach

### 1. Collection and parsing

Python scrapers collected team, roster, athlete, meet, and performance data.
The parser produced chunked, resumable outputs with logging, checkpoints, and
audit summaries.

### 2. DuckDB analytical foundation

The parsed data was loaded into DuckDB with separate raw, core, analytics, and
audit schemas. Relational checks, natural-key checks, source registration, and
row-count reconciliation established a reproducible analytical base.

### 3. Canonical identity and school attribution

Duplicate athlete profiles were resolved into canonical people. Performance
rows were deduplicated within each canonical athlete, and chronological
Division I school stints were constructed so development credit follows the
athlete's actual school history.

### 4. Athlete-development modeling

Performance marks were mapped onto event-, gender-, and season-aware scales
anchored to collegiate record references. Stable athlete-event levels were
constructed, and observed development was compared with cross-fitted expected
improvement.

The underlying athlete signal is:

```text
observed improvement − expected improvement
```

This approach accounts for starting level: the same raw time improvement can
represent substantially different development depending on the athlete's
initial performance level and event.

### 5. School ranking models

The official model is **Enhanced Balanced Production**. It applies support
reliability to athlete development signals, distributes equal positive point
budgets within publishable championship events, caps negative event pools, and
aggregates athlete-school-event contributions to programs.

Two companion models remain available:

- **Original Balanced Production v4.1** for robustness comparison;
- **Average Athlete Development** for a typical-athlete efficiency view.

Enhanced Balanced Production and Original v4.1 retained a final all-partition
rank correlation of **0.980708**, with strong top-10 and top-25 overlap.

### 6. Trends and comparisons

The system adds seasonal rankings, rolling windows, year-over-year comparisons,
indoor/outdoor comparisons, program trajectories, event-group trends, and
specialized rankings. Missing seasons such as 2020 Outdoor remain explicit and
are never interpolated or fabricated.

### 7. Public deployment

A compact DuckDB publication contains exactly **2,918,594** source and
deployment rows across **81** resource tables. The released database and gzip
artifact are checksum-verified.

The Streamlit application downloads the immutable release artifact when
necessary, verifies both checksums, opens the database read-only, and exposes
rankings, trends, comparisons, diagnostics, coverage, and methodology.

## Production hardening

The repository includes:

- Python 3.12 GitHub Actions CI;
- deterministic loader tests;
- a synthetic DuckDB-backed Streamlit regression test;
- deployment-descriptor consistency tests;
- daily public deployment health monitoring;
- exact artifact verification;
- forbidden-secret and oversized-file checks;
- semantic-version release preparation;
- dry-run-first publication tooling that cannot overwrite an existing release.

The current automated suite contains **47 tests** before the portfolio contract
tests added with this package.

## Key engineering challenges

### Canonical athlete identity

**Challenge:** Athlete IDs and profile pages could appear under multiple school
contexts, while transfers and stale labels could misattribute performances.

**Solution:** Build canonical-person mappings, person-meet team assignments,
chronological school stints, and provenance tables before calculating
development.

### Event fairness

**Challenge:** High-volume events could dominate total school influence.

**Solution:** Allocate equal positive point opportunity inside each publishable
championship event before aggregating school totals.

### Deployment size and memory

**Challenge:** The full analytical workspace was too large and too dependent on
ignored local outputs for a public cloud deployment.

**Solution:** Build one compact, versioned DuckDB publication; preserve exact
row parity; move the app to lazy cached loaders; and release the compressed
artifact separately from Git.

### Reproducibility without private production data

**Challenge:** CI could not depend on multi-gigabyte local databases.

**Solution:** Use deterministic temporary DuckDB fixtures for loader and
Streamlit tests, and enforce a descriptor contract across code and
documentation.

## Results

The finished project provides:

- a live recruiter-accessible explorer;
- an official production ranking and two companion models;
- program trend and comparison tools;
- transparent methodology and limitations;
- a versioned, checksum-verified public dataset;
- automated testing and health monitoring;
- guarded future release tooling.

## Interpretation and limitations

The rankings are observational rather than causal. They describe development
patterns in the available collegiate performance records and should not be
read as proof that a coaching staff caused an athlete's improvement.

Additional limitations include historical coverage differences, sparse elite
cohorts, uncertainty between closely ranked schools, exclusion of relays and
cross-country from individual scoring, and unavailable inbound-transfer
analysis where the required evidence is insufficient.
