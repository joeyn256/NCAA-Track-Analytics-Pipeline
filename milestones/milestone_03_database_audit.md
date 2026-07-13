# Milestone 3 Database Audit

## Result

**Overall result: PASS**

The Milestone 3 DuckDB analytical database was built transactionally,
published, and independently reopened in read-only mode for validation.

| Item | Result |
| --- | --- |
| Build run ID | `20260713T034453Z_b8e8c276` |
| Schema version | `milestone_03_v1` |
| Schema description | Initial relational analytical database |
| Build status | `pass` |
| Build started | `2026-07-12 23:44:53.424317` |
| Build completed | `2026-07-12 23:45:49.104998` |
| Build duration | 55.68 seconds |
| Python version | `3.12.13` |
| DuckDB version | `1.5.4` |
| Database file | `data/database/ncaa_track_analytics.duckdb` |
| Database size | 703,868,928 bytes (671.26 MiB / 0.66 GiB) |

The database file and generated build logs are excluded from Git. The
source code, SQL schema, dependency pin, and milestone documentation are
version controlled.

## Logical architecture

The database contains four schemas:

| Schema | Purpose |
| --- | --- |
| `raw` | Persistent source-faithful views over canonical CSV inputs |
| `core` | Relational dimensions, affiliations, and performance facts |
| `analytics` | Reserved for normalized analytical models in Milestone 4 |
| `audit` | Build runs, source hashes, counts, conflicts, and integrity checks |

## Core table counts

| Table | Rows |
| --- | --- |
| `core.athlete_affiliations` | 990,681 |
| `core.athletes` | 193,961 |
| `core.events` | 378 |
| `core.meets` | 32,416 |
| `core.performances` | 6,594,540 |
| `core.schools` | 554 |
| `core.seasons` | 71 |
| `core.teams` | 973 |

## School and team domains

| Metric | Count |
| --- | ---: |
| Current Division I directory teams | 714 |
| Complete team domain | 973 |
| Current Division I directory institutions | 363 |
| Complete institution domain | 554 |

The complete domains include historical or performance-only teams and
institutions that are absent from the current 714-entry Division I
directory. These records are retained so no valid performance is lost.

## Performance integrity

| Check | Result |
| --- | ---: |
| Expected performance records | 6,594,540 |
| Actual performance records | 6,594,540 |
| Distinct performance IDs | 6,594,540 |
| Duplicate performance IDs | 0 |
| Blank performance IDs | 0 |
| Parser failures | 0 |
| Relational orphan records | 0 |

Raw marks, secondary marks, dates, places, event labels, URLs, and source
filenames remain preserved. Full mark, time, and event normalization is
deferred until Milestone 4.

## Historical athlete affiliations

Historical affiliations were constructed from roster records rather than
assuming the current athlete-profile school applied to every season.

| Metric | Count |
| --- | ---: |
| Raw roster rows | 992,774 |
| Unique affiliation rows | 990,681 |
| Exact duplicate groups | 2,093 |
| Duplicate excess rows | 2,093 |
| Duplicate affiliation business keys | 0 |

Indoor roster seasons use the ending year when linked to performance
seasons. For example, `2022-23 Indoor` maps to `2023_indoor`.

## Performance-to-affiliation coverage

| Match class | Distinct athlete/team/season keys | Performance rows |
| --- | --- | --- |
| blank_team_id | 59 | 479 |
| directory_team_without_roster_match | 132,152 | 644,582 |
| matched | 750,115 | 5,916,703 |
| performance_only_team | 4,327 | 32,776 |

Coverage total: **6,594,540**

Unmatched performance rows are intentionally retained with a null
`affiliation_id`. The build does not invent historical affiliations from
current-profile school values.

## Canonical source inventory

| Source group | Files | Rows | Empty files | Size |
| --- | --- | --- | --- | --- |
| athletes | 1 | 193,961 | 0 | 19.47 MiB |
| chunk_status | 194 | 193,954 | 0 | 6.69 MiB |
| performances | 194 | 6,594,540 | 0 | 2,428.66 MiB |
| rosters | 1 | 992,774 | 0 | 81.08 MiB |
| schools | 1 | 714 | 0 | 0.09 MiB |
| seasons | 714 | 34,332 | 0 | 1.87 MiB |

| Source audit | Result |
| --- | ---: |
| Registered canonical files | 1,105 |
| Canonical source size | 2.48 GiB |
| Files without SHA-256 hashes | 0 |
| Failed source files | 0 |

## Integrity audit

| Audit result | Count |
| --- | ---: |
| Hard checks recorded | 35 |
| Hard checks passed | 35 |
| Hard checks failed | 0 |

## Most common raw event labels

| Raw event label | Performance rows |
| --- | --- |
| 4x400 | 510,290 |
| 200 | 426,938 |
| 800 | 388,929 |
| 400 | 343,571 |
| LJ | 329,905 |
| SP | 318,142 |
| HJ | 253,788 |
| 60 | 251,643 |
| 1500 | 249,234 |
| PV | 234,119 |

These labels are intentionally source-faithful. Canonical event
classification is deferred until Milestone 4.

## Reproducing the database

Activate the project virtual environment and run:

```bash
python -m pip install --requirement requirements-milestone3.txt

python src/database/build_database.py --preflight-only

python src/database/build_database.py     --build     2>&1 | tee data/database/milestone3_build.log

python src/database/validate_production_database.py     | tee data/database/milestone3_production_validation.txt
```

The builder refuses to overwrite an existing production database. To
perform a completely fresh rebuild, first move or delete the generated
database file intentionally:

```bash
rm data/database/ncaa_track_analytics.duckdb
```

Then rerun the preflight, build, and independent validation commands.

## Milestone 3 conclusion

Milestone 3 successfully converted the audited Milestone 1 and Milestone 2
outputs into a reproducible relational DuckDB analytical database.

The performance fact table contains exactly **6,594,540** records, all
performance IDs are unique and nonblank, historical affiliations are
roster-derived, and all mandatory build and independent validation checks
passed.
