# Project Milestones

This directory contains the technical record of the NCAA Track Analytics
Pipeline. The root [`README.md`](../README.md) is the visitor-friendly
overview; these pages document the engineering decisions, validation
evidence, and reproducible outputs behind each result.

## Milestone Index

| Milestone | Primary outcome | Scale | Core skills | Status |
|---|---|---:|---|---|
| [1 — Historical Data Collection](milestone_01_data_collection.md) | Historical NCAA roster and athlete-profile collection | 193,954 athlete pages | Web scraping, retries, resumability | Complete |
| [2 — Performance Parsing](milestone_02_performance_parsing.md) | Audited structured performance dataset | 6,594,540 records | HTML parsing, chunking, QA | Complete |
| [3 — Database Construction](milestone_03_database_construction.md) | Relational DuckDB warehouse | 703.9 MB | SQL, schema design, transactional builds | Complete |
| [3 — Independent Audit](milestone_03_database_audit.md) | Read-only production validation | 35 hard checks | Data lineage, reconciliation, integrity testing | Complete |
| [4 — Canonical Identity and School Stints](milestone_04_canonical_identity_and_school_stints.md) | Transfer-aware athlete and school attribution | 174,429 stints | Entity resolution, temporal attribution | Complete |
| [5 — Athlete Development Rankings](milestone_05_athlete_development_rankings.md) | Uncertainty-adjusted program rankings | 361 schools | Modeling, shrinkage, sensitivity analysis | Complete |

## Recommended Reading Paths

### Visitor or admissions review

1. Start with the root [`README.md`](../README.md).
2. Read the **At a Glance** section at the top of each milestone.
3. Open [Milestone 5](milestone_05_athlete_development_rankings.md)
   for the final statistical methodology and ranking validation.
4. Open [Milestone 4](milestone_04_canonical_identity_and_school_stints.md)
   for the entity-resolution and transfer-attribution foundation.

### Data engineering review

1. [Milestone 1](milestone_01_data_collection.md)
2. [Milestone 2](milestone_02_performance_parsing.md)
3. [Milestone 3 construction](milestone_03_database_construction.md)
4. [Milestone 3 audit](milestone_03_database_audit.md)

### Statistical and analytical review

1. [Milestone 4](milestone_04_canonical_identity_and_school_stints.md)
2. [Milestone 5](milestone_05_athlete_development_rankings.md)

## How the Roadmap Evolved

The roadmap changed as source investigation exposed dependencies that were
more important than the original high-level phase labels suggested.

- The original cleaning phase became **Milestone 4: Canonical Athlete
  Identity and D1 School Stints**.
- Athlete development and school rankings became the dedicated
  **Milestone 5**.
- The initial headroom-only scoring concept evolved into a record-anchored,
  school-held-out expected-improvement model.
- Relays and cross country were deferred to later team-performance work
  because they require different analytical units.

These revisions preserved the source warehouse and improved the validity of
every downstream ranking.

## Validation Philosophy

Across the project, a phase is not complete merely because a script runs.
Major phases publish only after:

- deterministic inputs are registered;
- upstream databases are attached read-only;
- row counts and grains reconcile;
- duplicate and orphan checks pass;
- hard checks are written to versioned outputs;
- sensitivity or exception reviews are completed where required.

## Current Status

**Milestones 1–8 are complete. Milestone 9 is in progress.**

- [Milestone 6 — Seasonal Development Rankings and Explorer](milestone_06_seasonal_rankings_and_exploratory_analytics.md)
- [Milestone 7 — Program Trends, Comparisons, and Specialized Rankings](milestone_07_program_trends_and_specialized_rankings.md)
- [Milestone 8 — Public Deployment and Visitor Experience](milestone_08_public_deployment_and_visitor_experience.md)
- [Milestone 9 — Production Hardening, Automation, and Portfolio Release](milestone_09_production_hardening_automation_and_portfolio_release.md)
