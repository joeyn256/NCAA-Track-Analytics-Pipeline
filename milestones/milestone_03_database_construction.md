# Milestone 3 — Relational Database Construction

<!-- RECRUITER_SUMMARY_START -->
## At a Glance

**Status:** Complete

### Executive Summary

Converted the audited flat-file collection into a reproducible DuckDB analytical warehouse with relational dimensions, facts, historical roster affiliations, source manifests, and an audit schema. Publication is transactional: the final database is released only after mandatory integrity checks pass.

### Headline Results

| Metric | Final result |
|---|---:|
| Database size | 703,868,928 bytes |
| Performance facts | 6,594,540 |
| Historical affiliations | 990,681 |
| Athletes | 193,961 |
| Teams | 973 |
| Institutions | 554 |
| Meets | 32,416 |
| Mandatory integrity checks | 35 passed |

### What This Milestone Demonstrates

- relational and dimensional schema design;
- DuckDB and SQL implementation at multi-million-row scale;
- transactional staging and atomic publication;
- source-file registration with SHA-256 lineage;
- separation of source-faithful, analytical, and audit schemas.

### Related Documentation

- [Construction and architecture](milestone_03_database_construction.md)
- [Independent production audit](milestone_03_database_audit.md)

[Previous: Milestone 2](milestone_02_performance_parsing.md) · [Back to the milestone index](README.md) · [Next: Milestone 4](milestone_04_canonical_identity_and_school_stints.md)

---
<!-- RECRUITER_SUMMARY_END -->

---

## Overview

Milestone 3 transformed the raw and processed NCAA Division I Track & Field and Cross Country datasets into a structured analytical database.

The database connects:

- Athletes
- Schools
- Teams
- Historical roster affiliations
- Seasons
- Meets
- Events
- Performances
- Source files
- Pipeline audit records

The primary database engine is **DuckDB**.

The completed database supports efficient SQL analysis while preserving the original raw values and source references collected during Milestones 1 and 2.

---

## Starting Dataset

The database was constructed from the completed and audited outputs of the first two milestones.

### Historical Collection Data

- **714** NCAA Division I team entries
- **34,334** historical roster files
- **992,774** historical roster records
- **193,961** unique athletes
- **193,954** collected athlete profile pages
- **7** confirmed unavailable athlete pages

### Performance Data

- **193,954** athlete pages processed
- **172,204** athletes with recorded performances
- **21,750** athletes with no recorded meet results
- **6,594,540** unique performance records
- **194** performance chunks
- **0** failed athlete pages
- **0** duplicate performance IDs
- Final production audit: **PASS**

---

## Goal

Build a reproducible relational database that:

1. Loads the complete historical roster and performance datasets.
2. Preserves all raw source values.
3. Creates stable relationships between athletes, teams, seasons, meets, events, and performances.
4. Represents historical athlete-school affiliations.
5. Supports efficient analytical SQL queries.
6. Validates all row counts, keys, and relationships.
7. Can be rebuilt from source files with one command.
8. Remains excluded from GitHub while all database-building code is version controlled.

---

## Database Engine

The database uses:

```text
DuckDB
```

The local database file is:

```text
data/database/ncaa_track.duckdb
```

The database file is not uploaded to GitHub.

The repository contains:

- Database-building Python scripts
- SQL schema files
- Validation scripts
- Tests
- Schema documentation
- Example analytical queries
- Milestone documentation

---

## Architectural Layers

The database will use four logical schemas.

```text
raw
core
analytics
audit
```

### `raw`

Contains source-aligned staging tables.

These tables will preserve the original source fields with minimal transformation.

### `core`

Contains cleaned, typed, and relational tables.

These tables will define the primary database model.

### `analytics`

Contains reusable views for common queries.

These views will simplify future analysis without changing the underlying source data.

### `audit`

Contains database-build metadata, source-file counts, validation results, and rejected-record information.

---

## Planned Database Model

```text
core.schools
      │
      └──< core.teams
                 │
                 └──< core.athlete_affiliations >── core.athletes
                                                      │
                                                      └──< core.performances
                                                                 │
                    core.seasons ────────────────────────────────┤
                                                                 │
                    core.meets ──────────────────────────────────┤
                                                                 │
                    core.events ─────────────────────────────────┘
```

---

## Planned Tables

### `raw.schools`

Source-aligned school and team directory records.

Expected source fields include:

- School ID
- TFRRS team ID
- School name
- Team slug
- Team URL
- Division
- Gender
- Sport
- Conference
- State

---

### `raw.rosters`

Historical athlete roster records.

Expected source information includes:

- Athlete ID
- Athlete name
- Athlete URL
- School
- Team
- Roster year
- Source roster file

The exact source schema will be confirmed during the profiling phase.

---

### `raw.performances`

The complete parsed performance dataset.

Expected rows:

```text
6,594,540
```

This staging table will preserve the fields produced during Milestone 2.

---

### `core.schools`

One row per institution.

Planned fields:

| Field | Purpose |
|---|---|
| `school_id` | Stable school identifier |
| `school_name` | Canonical institution name |
| `state` | State or location code |
| `conference` | Conference when available |
| `division` | NCAA division |
| `created_at` | Database load timestamp |

Men's and women's programs will connect to the same school when they represent the same institution.

---

### `core.teams`

One row per TFRRS team entry.

Planned fields:

| Field | Purpose |
|---|---|
| `team_id` | TFRRS team identifier |
| `school_id` | Related school |
| `gender` | Men's or women's team |
| `sport` | Team sport classification |
| `slug` | TFRRS team slug |
| `source_url` | Original team URL |
| `active_flag` | Whether the team appears in the collected directory |

Expected team entries:

```text
714
```

---

### `core.athletes`

One row per unique athlete.

Planned fields:

| Field | Purpose |
|---|---|
| `athlete_id` | TFRRS athlete identifier |
| `athlete_name` | Canonical athlete name |
| `athlete_url` | Athlete profile URL |
| `profile_collected` | Whether an HTML profile was collected |
| `profile_school` | School shown in the profile header |
| `profile_team_id` | Team shown in the profile header |
| `profile_class` | Class shown in the profile header |
| `source_file` | Athlete profile filename |

Expected athletes:

```text
193,961
```

The seven unavailable profiles will remain in the athlete table with:

```text
profile_collected = False
```

---

### `core.seasons`

One row per season-year and season-type combination.

Planned fields:

| Field | Purpose |
|---|---|
| `season_id` | Stable season identifier |
| `season_year` | Competition year |
| `season_type` | Indoor, Outdoor, or Cross Country |
| `season_label` | Original season label |

Example season keys:

```text
2024|Indoor
2024|Outdoor
2024|Cross Country
```

---

### `core.meets`

One row per distinct competition.

Planned fields:

| Field | Purpose |
|---|---|
| `meet_key` | Stable internal meet identifier |
| `meet_id` | TFRRS meet identifier |
| `meet_name` | Meet name |
| `meet_date` | Parsed date when available |
| `meet_date_text` | Original date text |
| `season_id` | Related season |
| `meet_url` | Source meet URL |

The stable meet key may include:

- Meet ID
- Season type
- Meet date
- Meet URL

This prevents collisions between Track & Field and Cross Country URL formats.

---

### `core.events`

One row per distinct source event name during Milestone 3.

Planned fields:

| Field | Purpose |
|---|---|
| `event_key` | Stable event identifier |
| `event_name_raw` | Original event name |
| `event_name_clean` | Whitespace-cleaned event name |
| `event_category` | Optional broad category when reliably known |

Full event canonicalization will be completed during the data-cleaning and feature-engineering milestone.

Examples that may remain separate during Milestone 3 include:

```text
Mile
1 Mile
1500
1500m
```

No uncertain event mappings will be fabricated.

---

### `core.athlete_affiliations`

Historical athlete-team membership derived from roster records.

Planned fields:

| Field | Purpose |
|---|---|
| `affiliation_id` | Stable affiliation identifier |
| `athlete_id` | Related athlete |
| `team_id` | Historical team |
| `school_id` | Historical school |
| `roster_year` | Roster year |
| `source_file` | Historical roster source |
| `athlete_name_raw` | Name from the roster record |

This table will serve as the source of historical team affiliation.

The school and team shown in an athlete profile header will not automatically be treated as the athlete's school for every historical performance.

---

### `core.performances`

The primary fact table.

Expected rows:

```text
6,594,540
```

Planned fields include:

| Field | Purpose |
|---|---|
| `performance_id` | Deterministic performance identifier |
| `athlete_id` | Related athlete |
| `season_id` | Related season |
| `meet_key` | Related meet |
| `event_key` | Related event |
| `team_id_profile` | Profile-level team snapshot |
| `mark_raw` | Original mark or time |
| `secondary_mark_raw` | Alternate source measurement |
| `wind_raw` | Original wind value |
| `place_raw` | Original placement text |
| `place_numeric` | Numeric place when safely parsed |
| `competition_round` | Preliminary, final, or other round |
| `highlighted` | TFRRS highlighted-result flag |
| `result_id` | TFRRS result identifier |
| `result_url` | TFRRS result URL |
| `source_file` | Athlete HTML source |

Raw values will be retained even when typed versions are created.

---

### `audit.source_files`

One row per source file included in the build.

Planned fields:

- Source filename
- Source type
- Expected row count
- Loaded row count
- File size
- Build timestamp
- Load status

---

### `audit.etl_runs`

One row per database build.

Planned fields:

- ETL run ID
- Start timestamp
- End timestamp
- Build status
- Database path
- Source row totals
- Loaded row totals
- Error message
- Git commit when available

---

### `audit.quality_checks`

One row per database validation test.

Planned fields:

- ETL run ID
- Check name
- Expected result
- Actual result
- Pass or fail
- Details

---

### `audit.rejected_rows`

Rows that cannot be loaded or related safely will be preserved here rather than silently discarded.

Planned fields:

- Source table
- Source file
- Source row identifier
- Rejection reason
- Raw record data
- ETL run ID

The target is:

```text
0 unexplained rejected rows
```

---

## Proposed Repository Structure

```text
src/
└── database/
    ├── __init__.py
    ├── database_config.py
    ├── connection.py
    ├── profile_sources.py
    ├── build_database.py
    ├── load_raw_tables.py
    ├── build_dimensions.py
    ├── build_affiliations.py
    ├── build_performances.py
    ├── create_views.py
    ├── validate_database.py
    └── sql/
        ├── 001_create_schemas.sql
        ├── 002_create_audit_tables.sql
        ├── 003_create_raw_tables.sql
        ├── 004_create_core_tables.sql
        ├── 005_create_analytics_views.sql
        └── 006_validation_queries.sql

tests/
└── database/
    ├── test_database_connection.py
    ├── test_schema_creation.py
    ├── test_dimension_builds.py
    ├── test_performance_load.py
    └── test_database_validation.py
```

The structure may be simplified when implementation begins, but responsibilities will remain separated.

---

# Implementation Phases

## Phase 0 — Preflight and Storage Check

Before creating the database:

- [ ] Confirm current free disk space
- [ ] Confirm all 194 performance chunks exist
- [ ] Confirm all 194 status chunks exist
- [ ] Confirm the final parser audit still passes
- [ ] Confirm historical roster files and manifests exist
- [ ] Confirm the database directory is ignored by Git
- [ ] Record current source row counts
- [ ] Create a backup plan before database generation

Because the source data already occupies several gigabytes, the system should ideally have at least approximately 15–20 GB of free space before beginning a full database build.

---

## Phase 1 — Dependency and Connection Setup

- [ ] Add `duckdb` to `requirements.txt`
- [ ] Install DuckDB in the virtual environment
- [ ] Add the database path to `src/config.py`
- [ ] Create a reusable database connection function
- [ ] Create a connection health-check script
- [ ] Confirm the database file remains ignored by Git

Target command:

```bash
python src/database/check_connection.py
```

---

## Phase 2 — Source Schema Profiling

Before finalizing the database schema, inspect every input dataset.

Profile:

- [ ] `schools.csv`
- [ ] `unique_athletes.csv`
- [ ] Consolidated historical roster records
- [ ] Historical roster files
- [ ] Performance chunk headers
- [ ] Performance status files

For each source, record:

- Column names
- Row counts
- Data types
- Missing-value counts
- Distinct-value counts
- Duplicate-key counts
- Example records
- Source-file naming patterns

Deliverables:

```text
data/processed/database_profiling/source_profile_summary.csv
data/processed/database_profiling/source_profile_report.md
```

These generated reports will remain local.

---

## Phase 3 — Final Schema Design

After source profiling:

- [ ] Confirm all table names
- [ ] Confirm primary keys
- [ ] Confirm foreign-key relationships
- [ ] Confirm deterministic key-generation rules
- [ ] Decide which fields remain raw strings
- [ ] Decide which fields receive typed versions
- [ ] Create a schema diagram
- [ ] Write SQL table definitions
- [ ] Document all table and column definitions

No full data load should begin until the schema is reviewed.

---

## Phase 4 — Raw Staging Load

Load source data into the `raw` schema.

Planned raw tables:

```text
raw.schools
raw.unique_athletes
raw.rosters
raw.performances
raw.parser_status
```

Requirements:

- [ ] Preserve original source columns
- [ ] Include source filenames
- [ ] Record row counts per source file
- [ ] Load the 194 performance chunks directly
- [ ] Do not combine chunks into another large CSV
- [ ] Store all staging data in the database
- [ ] Validate raw database counts against source counts

Expected raw performance count:

```text
6,594,540
```

---

## Phase 5 — Dimension Construction

Build:

- [ ] `core.schools`
- [ ] `core.teams`
- [ ] `core.athletes`
- [ ] `core.seasons`
- [ ] `core.meets`
- [ ] `core.events`

Checks:

- [ ] One row per primary key
- [ ] No duplicate dimension keys
- [ ] No unexplained null primary keys
- [ ] All raw dimension values represented
- [ ] Seven unavailable athlete profiles retained
- [ ] Source values remain traceable

---

## Phase 6 — Historical Affiliation Construction

Build:

```text
core.athlete_affiliations
```

Tasks:

- [ ] Connect historical roster records to athletes
- [ ] Connect roster records to teams
- [ ] Connect teams to schools
- [ ] Preserve roster year
- [ ] Preserve source roster filename
- [ ] Detect duplicate roster memberships
- [ ] Identify athletes appearing for multiple schools
- [ ] Identify athletes transferring between programs
- [ ] Audit unmatched roster records

Historical roster affiliations will be used instead of assuming that an athlete's current profile school applies to every season.

---

## Phase 7 — Performance Fact Load

Build:

```text
core.performances
```

Tasks:

- [ ] Load all 6,594,540 performance records
- [ ] Enforce one row per `performance_id`
- [ ] Connect every performance to an athlete
- [ ] Connect every performance to a season
- [ ] Connect every performance to a meet
- [ ] Connect every performance to an event
- [ ] Parse meet dates when reliable
- [ ] Parse numeric placements when reliable
- [ ] Preserve raw marks, dates, places, and wind values
- [ ] Preserve all source URLs and filenames
- [ ] Track rows that cannot be related

Full time and field-mark normalization will remain outside the scope of Milestone 3.

---

## Phase 8 — Analytical Views

Create reusable views such as:

```text
analytics.performance_detail
analytics.athlete_history
analytics.athlete_affiliation_history
analytics.meet_results
analytics.season_event_counts
analytics.data_coverage
```

These views will support common SQL queries while keeping the core tables normalized.

---

## Phase 9 — Validation and Quality Assurance

The database must pass a full audit.

### Required Count Checks

- [ ] Teams match the collected team directory
- [ ] Athletes equal **193,961**
- [ ] Performance rows equal **6,594,540**
- [ ] Performance IDs are unique
- [ ] Raw and core row counts reconcile
- [ ] Source-file row totals reconcile

### Required Relationship Checks

- [ ] No orphaned performance athlete IDs
- [ ] No orphaned season IDs
- [ ] No orphaned meet keys
- [ ] No orphaned event keys
- [ ] No unexplained team references
- [ ] No unexplained affiliation athlete IDs

### Required Data Checks

- [ ] No missing performance IDs
- [ ] No duplicate performance IDs
- [ ] No missing athlete IDs in performances
- [ ] No missing event keys
- [ ] No missing season keys
- [ ] Indoor, Outdoor, and Cross Country remain represented
- [ ] Raw marks remain unchanged
- [ ] Source filenames remain available
- [ ] Removed duplicate rows do not reappear

### Required Operational Checks

- [ ] Database closes and reopens successfully
- [ ] Database can be opened in read-only mode
- [ ] Database can be rebuilt from scratch
- [ ] Repeated builds produce the same key counts
- [ ] Failed builds do not replace a valid database
- [ ] Final database audit returns `PASS`

---

## Phase 10 — Query Testing

Create and document example SQL queries.

Planned examples:

1. Count performances by season type.
2. Count athletes by school and year.
3. Show an athlete's complete performance history.
4. Show an athlete's historical school affiliations.
5. Count performances by event.
6. Find meets with the largest result counts.
7. Identify athletes appearing for multiple schools.
8. Compare Indoor, Outdoor, and Cross Country coverage.
9. Trace a performance to its source athlete file.
10. Trace a roster affiliation to its source roster file.

These queries will confirm that the database model supports real analytical use cases.

---

## Phase 11 — Build Automation

The completed database should be created with one command:

```bash
python -u src/database/build_database.py
```

The build process should:

1. Run preflight checks.
2. Create a temporary database.
3. Create database schemas and tables.
4. Load raw source tables.
5. Build dimensions.
6. Build historical affiliations.
7. Build the performance fact table.
8. Create analytical views.
9. Run validation.
10. Replace the final database only after all checks pass.
11. Save a build report.

---

## Phase 12 — Documentation and GitHub

Commit to GitHub:

- [ ] Database source code
- [ ] SQL schema files
- [ ] Unit tests
- [ ] Schema diagram
- [ ] Example SQL queries
- [ ] Database data dictionary
- [ ] Milestone 3 documentation
- [ ] Updated README
- [ ] Updated requirements file

Do not commit:

```text
data/database/ncaa_track.duckdb
```

The `.gitignore` will preserve the database locally.

---

## Scope Boundaries

### Included in Milestone 3

- Database schema design
- Source profiling
- Raw staging tables
- Typed relational tables
- Historical affiliations
- Meet-date parsing
- Placement parsing
- Primary and foreign-key relationships
- Analytical SQL views
- Database validation
- Reproducible database construction

### Deferred to Milestone 4

- Complete event-name canonicalization
- Race-time conversion to seconds
- Field-mark conversion to metric values
- Personal-best calculations
- Season-best calculations
- Athlete progression features
- Age or class-based features
- Transfer-impact features
- Modeling-ready feature tables
- Outlier detection

---

## Risks and Controls

### Limited Disk Space

Control:

- Check disk space before building.
- Build into a temporary file.
- Avoid unnecessary duplicate CSV exports.
- Delete only temporary build files after failures.

### Historical School Ambiguity

Control:

- Use roster records for historical affiliations.
- Preserve profile school separately.
- Do not infer missing affiliations without evidence.

### Event Naming Variation

Control:

- Preserve raw event names.
- Perform only minimal cleaning during Milestone 3.
- Defer uncertain mappings.

### Date Parsing Variation

Control:

- Preserve `meet_date_text`.
- Store parsed dates only when reliable.
- Audit unparsed date formats.

### Large Fact-Table Load

Control:

- Load directly from the 194 chunks.
- Use SQL-based transformations.
- Avoid loading the full dataset into a Pandas DataFrame.
- Record progress and row totals.
- Use transactions and temporary database files.

### Unmatched Relationships

Control:

- Store unmatched records in an audit table.
- Do not silently drop rows.
- Require documented explanations before milestone completion.

---

## Completion Criteria

Milestone 3 will be complete when:

- [ ] A DuckDB database is successfully created
- [ ] The build runs from one command
- [ ] All **193,961** athletes are represented
- [ ] All **6,594,540** performance records are represented
- [ ] Historical affiliations are loaded
- [ ] All primary keys are unique
- [ ] All required relationships pass validation
- [ ] No unexplained records are discarded
- [ ] Raw source values remain traceable
- [ ] The database reopens successfully
- [ ] Example analytical queries run successfully
- [ ] The final database audit returns `PASS`
- [ ] Documentation is complete
- [ ] Code and documentation are published to GitHub
- [ ] The generated database remains excluded from GitHub

---

## Planned Final Deliverables

```text
data/database/ncaa_track.duckdb
src/database/
tests/database/
docs/database_schema.md
docs/database_dictionary.md
examples/analytical_queries.sql
milestones/milestone_03_database_construction.md
```

Generated databases and reports will remain local.

Source code and documentation will be version controlled.

---

## Milestone Outcome

At completion, the project will have a reproducible analytical database connecting approximately two decades of NCAA Division I Track & Field and Cross Country roster and performance history.

The database will serve as the foundation for:

- Data cleaning
- Event and mark normalization
- Feature engineering
- Athlete progression analysis
- Visualization
- Predictive modeling

---

## Final Status

**Milestone 3 database construction is complete.**

The published source warehouse remains the immutable relational
foundation for Milestones 4 and 5.

## Milestone 3 completion

**Status: COMPLETE — PASS**

The production DuckDB database was built and independently validated.

| Metric | Final value |
| --- | ---: |
| Database size | 0.66 GiB |
| Performance facts | 6,594,540 |
| Unique historical affiliations | 990,681 |
| Athletes | 193,961 |
| Teams | 973 |
| Institutions | 554 |
| Seasons | 71 |
| Meets | 32,416 |
| Raw event labels | 378 |
| Hard audit checks passed | 35 |
| Relational orphan records | 0 |

The final fact table contains exactly **6,594,540** unique, nonblank
performance IDs. Historical school affiliations come from roster records.
Raw marks, dates, places, event labels, URLs, and source filenames remain
preserved for Milestone 4 normalization.

See [Milestone 3 Database Audit](milestone_03_database_audit.md) for the
complete build, source, affiliation, and integrity results.
<!-- MILESTONE_03_COMPLETION_END -->
