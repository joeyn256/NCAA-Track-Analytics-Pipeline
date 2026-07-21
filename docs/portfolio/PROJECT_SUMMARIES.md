# Project Summaries and Engineering Notes

## Contribution highlights

- Built an end-to-end NCAA Division I track-and-field analytics pipeline in
  Python and DuckDB, standardizing 6.59 million performance records across
  193,961 athletes and publishing an interactive Streamlit explorer.
- Resolved duplicate athlete profiles, transfers, repeated results, and
  chronological school attribution, producing 6.38 million deduplicated
  canonical performances with source-to-output provenance.
- Developed an observed-minus-expected athlete-development model and an
  event-balanced school-ranking framework with explicit uncertainty, coverage,
  and non-causal interpretation limits.
- Engineered a checksum-verified 2.92 million-row public DuckDB publication
  containing 81 resource tables with exact source-to-deployment parity.
- Added Python 3.12 CI, deterministic DuckDB and Streamlit tests, deployment
  monitoring, documentation contracts, and guarded semantic-version release
  automation.

## Short project overview

The NCAA Track Analytics Pipeline is a production-style analytics platform for
historical NCAA Division I track-and-field data. It resolves athlete identity
and school stints, estimates development relative to starting level, creates
event-balanced program rankings and seasonal trends, and serves the results
through a public Streamlit explorer.

The deployment uses a checksum-verified DuckDB release, automated tests,
GitHub Actions CI, daily health checks, and dry-run-first release tooling.
Rankings are observational and include explicit methodology and coverage
limitations.

## Detailed project overview

The project began with the question of how NCAA Division I programs could be
compared using athlete-development patterns rather than raw performance alone.

The source data required substantial preparation. Athlete profiles could be
duplicated, transfers complicated school attribution, repeated performances
needed to be reconciled, and performances from different events could not be
compared directly.

The pipeline collects and parses historical results, stores the data in
DuckDB, resolves canonical athletes and chronological school stints, and
standardizes 6.59 million performances. Stable athlete-event levels are then
used with cross-fitted expected improvement to estimate observed-minus-expected
development.

Enhanced Balanced Production is the official school-ranking model. It applies
support reliability, gives each publishable championship event equal positive
point opportunity, bounds negative event pools, and aggregates
athlete-school-event contributions. Original Balanced Production v4.1 and
Average Athlete Development remain available as companion views.

The final public application includes rankings, trends, school comparisons,
diagnostics, coverage, and methodology. It runs from a checksum-verified
2.92 million-row DuckDB release and is supported by deterministic tests,
continuous integration, deployment monitoring, and guarded release tooling.

## Engineering examples

### Canonical athlete identity and school attribution

Source profiles and school labels could duplicate athletes or assign
performances to the wrong institution. The solution combined canonical-person
mappings, person-meet team assignments, chronological Division I school
stints, performance deduplication, reviewed exceptions, and preserved
provenance.

The resulting analytical layer contains 6,376,667 deduplicated canonical
performances with stable school ownership.

### Event fairness

Events with more athletes and trajectories could otherwise dominate total
school influence. Event-level audits were used to reject overly aggressive
trajectory-count weighting and implement equal positive point budgets inside
each publishable championship event, with separately bounded negative pools.

The official model retained a 0.980708 rank correlation with the validated
Original Balanced Production v4.1 companion.

### Public deployment

The full analytical workspace depended on large local files that were
unsuitable for a public cloud runtime or repository-based CI.

A compact DuckDB publication was created with exact source-to-deployment row
parity, checksum-verified release artifacts, a portable read-only loader, lazy
cached application queries, synthetic CI fixtures, and automated health
checks.

The deployed explorer is backed by 81 resource tables and 2,918,594 published
rows without committing production databases or secrets to Git.
