# Milestone 4 — Canonical Athlete Identity and D1 School Stints

## Status

**Complete**

Milestone 4 created the validated analytical foundation required to measure
athlete development by school.

The final system resolves duplicate athlete profiles, deduplicates repeated
performances, assigns every eligible performance to a canonical person, and
maps each performance to exactly one chronological NCAA Division I school
stint.

---

## Final analytical outputs

### Canonical-person database

```text
data/processed/milestone4/canonical_person_layer_v1_1/
canonical_person_layer_v1_1.duckdb
```

### Final school-stint database

```text
data/processed/milestone4/final_school_stints_v1_1/
final_school_stints_v1_1.duckdb
```

These generated databases are analytical build artifacts and should remain
excluded from Git.

---

## Final counts

| Metric | Final value |
|---|---:|
| Source athlete profiles | 193,961 |
| Canonical people | 192,561 |
| High-confidence multi-profile people | 1,352 |
| Profiles in merged identity components | 2,752 |
| School-stint-eligible source performances | 6,474,538 |
| Deduplicated canonical-person performances | 6,376,667 |
| Duplicate source performance rows removed | 97,871 |
| Canonical people with D1 school stints | 170,655 |
| Person-meet assignments | 3,867,249 |
| Final D1 school stints | 174,429 |
| People represented by multiple school stints | 3,612 |
| People returning to a previous team | 44 |

---

## Canonical identity layer

TFRRS occasionally contains multiple athlete profile IDs for the same person.
Milestone 4 created a canonical-person identity layer to prevent those duplicate
profiles from being treated as separate athletes.

Identity candidates were based on:

- normalized athlete name;
- matching gender;
- repeated exact individual-performance signatures;
- minimum shared-performance overlap thresholds;
- relay and medley exclusions during identity discovery.

Only validated high-confidence components were merged. All other athlete
profiles remained single-profile canonical people.

### Identity validation

| Check | Result |
|---|---:|
| Candidate identity components | 1,352 |
| Source profiles inside components | 2,752 |
| Profiles in multiple components | 0 |
| Components containing multiple normalized names | 0 |
| Known Emily Venters duplicate profiles | Passed |
| Known Daniella Hubble duplicate profiles | Passed |

---

## Person-performance deduplication

Repeated performances were deduplicated only within a canonical person.

The deduplication signature included:

- season;
- meet;
- event;
- primary and secondary marks;
- wind;
- place;
- competition round;
- raw place;
- result URL.

The source-performance bridge was preserved so every original performance ID
remains traceable to its canonical-person performance.

### Deduplication result

| Category | Canonical rows | Source rows | Rows removed |
|---|---:|---:|---:|
| Multi-profile duplicate signatures | 94,089 | 191,960 | 97,871 |
| Single-profile signatures | 6,282,578 | 6,282,578 | 0 |
| **Total** | **6,376,667** | **6,474,538** | **97,871** |

---

## Person-level team conflict resolution

Duplicate profiles sometimes assigned the same performance to different teams.
Milestone 4 resolved all 35,694 person-performance team conflicts.

| Resolution method | Conflict groups |
|---|---:|
| Canonical team uniquely matched source team | 34,285 |
| Unique strongest attribution evidence | 1,247 |
| Exact result-page team evidence | 158 |
| Constrained person-season continuity evidence | 4 |
| **Total** | **35,694** |

Remaining person-performance team conflicts: **0**

---

## D1 school-stint construction

School stints were built from the validated canonical-person performance layer.

The process:

1. Reduced performances to one team assignment per canonical person and meet.
2. Parsed meet dates and ordered each person’s career chronologically.
3. Collapsed consecutive appearances for the same team into one school stint.
4. Preserved genuine returns to previous schools as separate stints.
5. Assigned every eligible canonical performance to exactly one stint.

### Final stint validation

| Check | Result |
|---|---:|
| Eligible performance rows | 6,376,505 |
| Distinct performance map IDs | 6,376,505 |
| Person-meet assignments | 3,867,249 |
| School stints | 174,429 |
| Missing stint assignments | 0 |
| Duplicate school-stint IDs | 0 |
| Duplicate performance-map IDs | 0 |
| Same-person, same-meet multi-team groups | 0 |
| Same-day multi-team groups | 0 |
| Synthetic chronology dates | 0 |
| Remaining unreviewed chronology islands | 0 |

---

## Reviewed chronology exceptions

Two single-meet A→B→A patterns remained after final stint construction.

They were retained because exact TFRRS result-page evidence confirmed the
middle-team assignments:

| Athlete | Meet | Accepted team |
|---|---|---|
| Emily Venters | 2018 Nuttycombe Wisconsin Invitational | Colorado |
| Daniella Hubble | 2023 Wisconsin Badger Classic | Illinois |

These cases are stored in the final database as reviewed chronology exceptions.
They are not unresolved errors and were not silently overwritten.

---

## Final database objects

The final school-stint database contains:

### `person_meet_team_assignments`

One canonical team assignment per person, season, and meet.

### `canonical_person_school_stints`

Chronological D1 school stints for each canonical person.

### `school_stint_performance_map`

Maps every eligible canonical-person performance to exactly one school stint.

### `chronology_exception_registry`

Stores reviewed chronology exceptions and supporting result-page evidence.

### `chronology_exception_source_rows`

Preserves the underlying source-profile attribution rows for reviewed
exceptions.

### `transfer_school_stints`

View containing canonical people with more than one school stint.

### `reviewed_chronology_exceptions`

View containing accepted result-page-confirmed chronology exceptions.

### `analytical_school_stints`

Validated school stints with no unreviewed A→B→A chronology cases.

---

## Immutability and provenance

Milestone 4 did not modify:

- the Milestone 3 source DuckDB database;
- raw HTML files;
- raw or processed source CSV files;
- prior diagnostic databases;
- source performance IDs.

Each major phase wrote to a separate database or audit directory.

---

## Scripts

The primary Milestone 4 scripts are located in:

```text
src/analysis/milestone4/
```

Important final-phase scripts include:

```text
preflight_duplicate_athlete_identity.py
build_canonical_person_layer.py
audit_canonical_person_team_conflicts.py
resolve_ambiguous_person_team_conflicts.py
finalize_ambiguous_person_result_evidence.py
build_final_canonical_person_layer.py
build_final_school_stints.py
audit_school_stint_island_evidence.py
finalize_school_stints.py
```

---

## Milestone 4 completion criteria

- [x] Canonical person bridge created
- [x] Duplicate athlete profiles resolved
- [x] Duplicate performances removed analytically
- [x] Source performance provenance preserved
- [x] Person-level team conflicts resolved
- [x] D1 school stints constructed chronologically
- [x] Every eligible performance mapped to one stint
- [x] Transfer and return stints preserved
- [x] Chronology exceptions reviewed and registered
- [x] All final hard checks passed
- [x] Source and prior databases remained unchanged

---

## Next milestone

Milestone 5 will build the athlete-development model.

Initial work will include:

- event-name normalization;
- valid-mark parsing;
- event-family classification;
- comparable-performance selection;
- baseline and endpoint definitions;
- event-specific performance scaling;
- human-limit-aware improvement scoring;
- athlete-level development scores;
- D1 school rankings.
