# Career Materials

## Résumé bullets

- Built an end-to-end NCAA Division I track-and-field analytics pipeline in
  Python and DuckDB, standardizing **6.59 million performance records** across
  **193,961 athletes** and publishing an interactive Streamlit explorer.
- Resolved duplicate athlete profiles, transfers, repeated results, and
  chronological school attribution, producing **6.38 million deduplicated
  canonical performances** with source-to-output provenance.
- Developed an observed-minus-expected athlete-development model and an
  event-balanced school ranking framework; preserved validated companion models
  and documented uncertainty, coverage, and non-causal interpretation limits.
- Engineered a checksum-verified **2.92 million-row** public DuckDB publication
  with **81 resource tables**, exact source/deployment parity, lazy cached
  loading, and an immutable GitHub Release.
- Added Python 3.12 CI, deterministic DuckDB and Streamlit tests, 100% branch
  coverage for the deployment loader, daily health monitoring, documentation
  contracts, and guarded semantic-version release automation.

## LinkedIn project description

Built a production-style NCAA Division I track-and-field analytics platform
covering 193,961 athletes and 6.59 million standardized performances. The
pipeline resolves athlete identity and school stints, estimates development
relative to starting level, publishes event-balanced program rankings and
seasonal trends, and serves the results through a public Streamlit explorer.
The deployment uses a checksum-verified DuckDB release, automated tests,
GitHub Actions CI, daily health checks, and dry-run-first release tooling.
Rankings are observational and include explicit methodology and coverage
limitations.

## Portfolio description

The NCAA Track Analytics Pipeline is an end-to-end data engineering, modeling,
and deployment project. It converts historical collegiate results into
auditable athlete-development metrics and program rankings while solving
identity resolution, transfer attribution, event comparability, expected
improvement, uncertainty, deployment size, and reproducibility. The finished
system includes a public interactive explorer, a compact immutable data
release, CI and regression testing, health monitoring, and recruiter-facing
documentation.

## Graduate-school application language

I designed the NCAA Track Analytics Pipeline to bridge data engineering,
statistical modeling, and production analytics. Working with millions of
historical performance records required me to move beyond a simple ranking
script: I built canonical identity and school-stint layers, developed a
cross-fitted expected-improvement framework, audited model sensitivity and
event fairness, and deployed a compact reproducible publication through a
public application. The project strengthened my interest in graduate study
because it showed how careful data design, statistical assumptions, and
software engineering must work together to produce analysis that is both
useful and defensible.

## Interview explanations

### 30-second explanation

I built a public NCAA Division I track-and-field analytics platform using
Python, DuckDB, and Streamlit. It processes 6.59 million performances, resolves
athlete identity and transfers, measures improvement relative to starting
level, and creates event-balanced school rankings and trends. I also production-
hardened it with CI, synthetic regression tests, checksum-verified releases,
daily health checks, and guarded release automation.

### Two-minute explanation

I started with the question of which NCAA Division I programs develop athletes
most effectively. The raw data could not answer that directly because athlete
profiles were duplicated, transfers complicated school credit, events used
different scales, and athletes starting near elite levels had less raw room to
improve.

I built a Python collection and parsing pipeline, loaded the data into DuckDB,
resolved canonical athletes and chronological school stints, and standardized
6.59 million performances. I then created stable athlete-event levels and used
cross-fitted expected improvement to calculate observed-minus-expected
development.

For the official school ranking, I created Enhanced Balanced Production. It
adds support reliability, gives every publishable championship event equal
positive point opportunity, bounds negative pools, and aggregates athlete-
school-event contributions. I preserved Original Balanced Production v4.1 and
Average Athlete Development as companion views.

The final public application includes rankings, trends, school comparisons,
diagnostics, coverage, and methodology. It runs from a checksum-verified
2.92 million-row DuckDB release. The repository includes Python 3.12 CI,
deterministic DuckDB and Streamlit tests, daily deployment monitoring, and
dry-run-first release tooling. I am careful to describe the rankings as
observational rather than causal.

## STAR examples

### Identity resolution and transfer attribution

**Situation:** Source profiles and school labels could duplicate athletes or
assign performances to the wrong institution.

**Task:** Create a defensible athlete and school ownership layer before any
development ranking was calculated.

**Action:** Built canonical-person mappings, deduplicated performances within
canonical athletes, resolved person-meet team assignments, constructed
chronological Division I school stints, and preserved provenance and reviewed
exceptions.

**Result:** Produced 6,376,667 deduplicated canonical performances and a stable
school-stint foundation for downstream modeling.

### Event fairness

**Situation:** Events with more athletes and trajectories could dominate total
school influence.

**Task:** Preserve athlete-level development information while giving
championship events comparable ranking opportunity.

**Action:** Audited event influence, rejected aggressive trajectory-count
reweighting, and implemented equal positive point budgets inside each
publishable event with separately bounded negative pools.

**Result:** Published an official event-balanced production model while
retaining a 0.980708 rank correlation with the original validated companion
model.

### Public production deployment

**Situation:** The analytical workspace depended on large ignored local files
and was unsuitable for Streamlit Community Cloud or public CI.

**Task:** Create a portable, reproducible, safe deployment.

**Action:** Built a compact DuckDB, validated exact source/deployment row
parity, released it as a checksum-verified immutable artifact, implemented a
portable loader, added lazy caching, and created synthetic CI fixtures and
health checks.

**Result:** Deployed a public explorer backed by 81 resource tables and
2,918,594 rows without committing production databases or secrets to Git.
