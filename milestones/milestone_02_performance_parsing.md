# Milestone 2 — Athlete Performance Parsing Pipeline

---

## Overview

This milestone marks the completion of the performance-parsing phase for the **NCAA Track Analytics Pipeline**.

The goal of this phase was to transform locally stored TFRRS athlete profile pages into a structured historical performance dataset suitable for database construction, statistical analysis, visualization, and predictive modeling.

The completed parser supports:

- Indoor Track & Field
- Outdoor Track & Field
- Cross Country
- Sprints and hurdles
- Distance events
- Relays
- Jumps
- Throws
- Combined events
- Preliminary and final rounds
- Wind readings
- Nonstandard results such as `DNS`, `DNF`, `DQ`, `NM`, `NH`, and `NT`

---

## Highlights

- **193,954** athlete profile pages processed
- **172,204** athletes with recorded performances
- **21,750** athlete pages with no meet-result records
- **6,594,540** unique structured performance records
- **194** resumable production chunks
- **0** athlete-page parsing failures
- **0** missing season classifications
- **0** duplicate performance IDs after cleanup
- Indoor, Outdoor, and Cross Country results supported
- Final production audit result: **PASS**

---

## Objectives

The primary objectives for this milestone were:

1. Parse athlete identity and profile information.
2. Extract meet names and competition dates.
3. Extract event names, marks, and times.
4. Extract placements and competition rounds.
5. Extract wind readings when available.
6. Classify performances as Indoor, Outdoor, or Cross Country.
7. Preserve raw source values and URLs.
8. Support unusual or incomplete result codes.
9. Create deterministic performance identifiers.
10. Build a resumable production parser.
11. Validate the full production dataset.
12. Remove duplicate records without discarding legitimate performances.

---

## Input Data

The parser used the athlete profile pages collected during Milestone 1.

```text
data/raw/athlete_pages/
├── 21390.html
├── 27913.html
├── 42051.html
└── ...
```

The official athlete manifest was:

```text
data/raw/unique_athletes.csv
```

The manifest contained:

```text
193,961 unique athletes
```

Seven unavailable athlete pages documented during Milestone 1 were excluded, leaving:

```text
193,954 available athlete pages
```

Using the manifest as the official source prevented unrelated, stale, or temporary HTML files from entering the production dataset.

---

## Performance Parsing Pipeline

```text
unique_athletes.csv
        │
        ▼
Athlete HTML Manifest
        │
        ▼
Local Athlete Profile Pages
        │
        ▼
Athlete Header Parser
        │
        ├── Athlete ID
        ├── Athlete Name
        ├── Athlete Class
        ├── School
        └── Team ID
        │
        ▼
Season History Parser
        │
        ├── Season Year
        ├── Season Type
        └── Season Label
        │
        ▼
Meet Results Parser
        │
        ├── Meet
        ├── Date
        ├── Event
        ├── Mark
        ├── Wind
        ├── Place
        └── Round
        │
        ▼
Performance ID Generation
        │
        ▼
1,000-Athlete Output Chunks
        │
        ▼
Production Audit and Deduplication
        │
        ▼
6,594,540 Unique Performance Records
```

---

## Output Schema

Each performance record contains:

| Column | Description |
|---|---|
| `performance_id` | Deterministic identifier for the performance |
| `athlete_id` | TFRRS athlete identifier |
| `athlete_name` | Athlete name from the profile header |
| `athlete_class` | Athlete class displayed by TFRRS |
| `school` | School displayed on the athlete profile |
| `team_id` | TFRRS team identifier |
| `season_year` | Year associated with the performance |
| `season_type` | Indoor, Outdoor, or Cross Country |
| `season_label` | Original season heading |
| `meet_id` | TFRRS meet identifier |
| `result_id` | TFRRS result-page identifier when available |
| `meet_name` | Competition name |
| `meet_date_text` | Original competition-date text |
| `event` | Event name or abbreviation |
| `mark` | Primary result value |
| `secondary_mark` | Alternate measurement or annotation |
| `wind` | Wind reading when available |
| `place` | Finishing place |
| `competition_round` | Preliminary, final, or other round |
| `raw_place` | Original placement text |
| `meet_url` | Source meet URL |
| `result_url` | Source result URL |
| `highlighted` | Whether TFRRS highlighted the result |
| `source_file` | Original athlete HTML filename |

---

## Deterministic Performance IDs

Each performance receives a deterministic `performance_id` generated from identifying record fields.

The identifier includes information such as:

- Athlete ID
- Meet ID
- Result ID
- Result URL
- Season
- Event
- Mark
- Secondary mark
- Wind
- Placement
- Competition round

This design ensures that:

- Preliminary and final performances remain separate.
- Combined-event components remain separate.
- Reprocessing the same source data creates the same identifier.
- Exact duplicate records can be detected consistently.

---

## Validation Process

Before the production run, the parser was validated against athlete pages representing multiple sports, events, seasons, and page structures.

The validation sample covered:

- Cross Country
- Distance events
- Sprints and hurdles
- Relays
- Jumps
- Throws
- Combined events
- Wind readings
- Multiple seasons
- Nonstandard result codes

### Validation Results

| Metric | Result |
|---|---:|
| Athlete pages selected | **20** |
| Candidate pages scanned | **25** |
| Performance rows parsed | **641** |
| Parsing failures | **0** |
| Missing season classifications | **0** |
| Unique events represented | **39** |
| Required categories covered | **10 of 10** |

### Validation Season Counts

| Season Type | Records |
|---|---:|
| Outdoor | **286** |
| Indoor | **280** |
| Cross Country | **75** |

---

## Cross Country Support

TFRRS uses a different URL structure for Cross Country results.

Track & Field results commonly use:

```text
/results/{meet_id}/{result_id}/
```

Cross Country results commonly use:

```text
/results/xc/{meet_id}/
```

The parser detects the Cross Country structure and assigns:

- `season_type = Cross Country`
- The numeric meet ID
- The competition year from the meet date when necessary
- A season label such as `2023 XC`

This eliminated all missing season classifications during validation and production auditing.

---

## Multiple Rounds and Shared Result IDs

Some TFRRS result pages contain multiple legitimate performances using the same result ID.

Examples include:

- Preliminary and final rounds
- Multiple qualifying rounds
- Combined-event totals and component events
- Multiple attempts recorded under one result page

For this reason, `athlete_id + result_id` is not treated as a unique performance key.

The deterministic performance identifier also includes event, mark, placement, round, wind, and other fields.

---

## Result Values Preserved

The parser preserves raw values before numeric normalization.

Examples include:

```text
12.48
4:08.44
1.62m
21:42.5
NM
NH
NT
DNS
DNF
DQ
```

Metric and imperial field-event measurements remain separate when both are available.

Example:

```text
mark:           1.62m
secondary_mark: 5' 3.75"
```

Raw values will be normalized during a later database and data-cleaning milestone.

---

## Production Architecture

The production parser processed athlete pages in deterministic chunks of 1,000.

```text
data/processed/
├── performance_chunks/
│   ├── performances_00001.csv
│   ├── performances_00002.csv
│   ├── ...
│   └── performances_00194.csv
│
└── parser_checkpoints/
    └── chunk_status/
        ├── status_00001.csv
        ├── status_00002.csv
        ├── ...
        └── status_00194.csv
```

Each performance chunk contains structured records for up to 1,000 athletes.

Each status file records whether an athlete page was:

- Successfully parsed
- Empty
- Failed

---

## Resume and Recovery Design

A chunk is considered complete only when both files exist:

```text
performances_XXXXX.csv
status_XXXXX.csv
```

Completed chunks are skipped automatically during later runs.

This supports recovery from:

- Manual interruption
- Terminal closure
- Computer restart
- Unexpected exceptions
- Partial file creation

Output files are first written to temporary files and then renamed atomically.

---

## Initial Production Results

The first production parse created:

| Metric | Initial Result |
|---|---:|
| Athlete pages processed | **193,954** |
| Athletes with performances | **172,204** |
| Empty athlete pages | **21,750** |
| Failed athlete pages | **0** |
| Initial performance rows | **6,600,607** |
| Performance chunks | **194** |

The main production run completed in approximately **2 hours and 33 minutes**.

---

## Duplicate Investigation

The initial audit identified **6,067 additional rows** sharing a deterministic performance ID.

A detailed inspection found:

| Duplicate Category | Groups | Additional Rows |
|---|---:|---:|
| Exact duplicate records | **3,473** | **5,170** |
| Records differing only in `highlighted` | **667** | **897** |
| Records differing in meaningful performance fields | **0** | **0** |
| Total | **4,140** | **6,067** |

The investigation confirmed that no legitimate performances differed in event, mark, placement, round, wind, meet, athlete, or season information.

---

## Deduplication Process

The deduplication pipeline:

- Kept one record per deterministic `performance_id`
- Removed exact repeated rows
- Merged rows that differed only in `highlighted`
- Preserved `highlighted=True` when any duplicate copy was highlighted
- Updated athlete checkpoint row counts
- Rewrote production chunks atomically
- Preserved removed rows in an audit file

Removed records were saved at:

```text
data/processed/parser_audit/removed_duplicate_performance_rows.csv
```

### Deduplication Results

| Metric | Result |
|---|---:|
| Rows before cleanup | **6,600,607** |
| Rows removed | **6,067** |
| Rows after cleanup | **6,594,540** |
| Unexpected differing groups | **0** |

---

## Final Production Audit

After deduplication, the full production dataset was audited again.

### Final Audit Result

**PASS**

| Quality Check | Result |
|---|---:|
| Performance chunks | **194** |
| Status chunks | **194** |
| Missing performance chunks | **0** |
| Missing status chunks | **0** |
| Athlete pages | **193,954** |
| Parsed athletes | **172,204** |
| Empty athletes | **21,750** |
| Failed athletes | **0** |
| Performance records | **6,594,540** |
| Missing performance IDs | **0** |
| Duplicate performance IDs | **0** |
| Missing athlete IDs | **0** |
| Missing season types | **0** |
| Invalid season types | **0** |
| Missing event names | **0** |
| Missing marks | **0** |
| Missing source files | **0** |
| Status and performance totals match | **True** |
| Audit issues | **0** |

---

## Engineering Challenges Solved

### Different Sport Formats

Indoor Track, Outdoor Track, and Cross Country use different labels and URL structures.

The parser combines season headings, URL patterns, and meet dates to classify each result.

### Historical HTML Variation

The dataset spans approximately two decades, and older TFRRS pages sometimes use different URL formats and mark layouts.

The parser preserves these variations while producing a consistent schema.

### Shared Result Identifiers

Result IDs are not always unique at the individual-performance level.

A more specific deterministic identifier was created instead of relying only on the TFRRS result ID.

### Duplicate Source Records

Some athlete pages contained repeated result rows.

A separate audit and deduplication stage removed exact repeats while preserving legitimate rounds, combined-event components, and highlight information.

### Large-Scale Memory Management

Loading millions of rows into memory at once would be inefficient.

The pipeline processes and writes groups of 1,000 athlete pages independently.

### Empty Athlete Profiles

Some athletes appeared on historical rosters but had no recorded meet results.

These pages were classified as `empty` rather than failed.

---

## Technologies Used

### Programming Language

- Python

### Libraries and Modules

- Pandas
- BeautifulSoup
- pathlib
- hashlib
- argparse
- regular expressions
- time
- os

### Engineering Practices

- Modular parser functions
- Deterministic identifiers
- Chunked data processing
- Atomic file writing
- Manifest-based input control
- Checkpointing
- Resume support
- Validation sampling
- Full production auditing
- Safe deduplication
- Raw-value preservation

---

## Data Quality Decisions

The parser does not fabricate missing marks, placements, wind readings, result IDs, or season values.

Missing values remain empty unless they can be derived reliably from another section of the source page.

Raw marks, URLs, filenames, and identifiers are preserved for traceability.

The profile-level `school`, `team_id`, and `athlete_class` values represent the current athlete-profile header. Historical season-specific affiliations will be derived from roster records during database construction.

---

## Final Outcome

Milestone 2 transformed **193,954 athlete profile pages** into **6,594,540 unique structured performance records**.

The dataset contains approximately two decades of NCAA Division I:

- Indoor Track & Field results
- Outdoor Track & Field results
- Cross Country results
- Athlete identities
- Meet information
- Event marks and times
- Wind readings
- Placements
- Competition rounds
- Source identifiers and URLs

The completed production pipeline is reproducible, resumable, fault tolerant, audited, deduplicated, and ready for relational database construction.

---

## Lessons Learned

The primary lessons from this milestone were:

- Page formats must be validated across sports and event categories.
- Source result IDs are not always unique at the performance level.
- Raw data should be preserved before normalization.
- Large datasets should be processed incrementally.
- Checkpointing makes long production runs safer.
- Empty pages should be distinguished from failed pages.
- Validation should intentionally cover uncommon edge cases.
- A production audit is necessary even when parsing completes without errors.
- Duplicate records should be inspected before being removed.
- Audit files should preserve removed data for traceability.

---

## Milestone Status

**✅ Completed**

The athlete performance parsing pipeline has passed its final production audit.

---

# Next Milestone

## Milestone 3 — Relational Database Construction

The next phase will transform performance chunks and historical roster data into a normalized relational database.

Planned objectives:

- [ ] Design the relational schema
- [ ] Create athlete, school, team, season, meet, event, and performance tables
- [ ] Normalize historical athlete-school affiliations
- [ ] Parse competition dates into standardized date fields
- [ ] Normalize running times into seconds
- [ ] Normalize field-event marks into metric values
- [ ] Preserve original raw source values
- [ ] Create primary and foreign keys
- [ ] Add indexes for analytical queries
- [ ] Load all performance chunks
- [ ] Validate database row counts and relationships