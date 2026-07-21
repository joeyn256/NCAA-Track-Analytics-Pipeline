# Milestone 7 — Program Trends, Comparisons, and Specialized Rankings

## Status

**Complete**

## Objective

Milestone 7 extends the frozen Milestone 6 development-ranking publication
into a longitudinal program-analysis system.

The milestone answers four related questions:

1. How has a school's development performance changed across seasons?
2. Is recent movement sustained, volatile, or driven by a single season?
3. How does a school compare nationally and within its conference?
4. Which programs lead specialized Enhanced Balanced Production analyses?

Milestone 7 does not refit the official athlete-development model. It treats
the frozen Milestone 6 publication as immutable input and builds audited trend,
comparison, specialized-ranking, and explorer products around it.

---

## Official model hierarchy

The explorer preserves three clearly separated analytical families.

### Official primary model

**Enhanced Balanced Production** is the official production ranking.

Its frozen settings include:

- 27 event-specific scoring budgets;
- seven registered event groups;
- 100,000 positive points per eligible event partition;
- a 100,000 negative-point cap;
- support-reliability shrinkage with `k = 191`;
- event-, gender-, season-, and cohort-specific scoring;
- no interpolation or fabricated seasons.

### Official companion model

**Original Balanced Production v4.1** remains available for robustness
comparisons but is not the official primary ranking.

### Secondary companion model

**Average Development** remains available as a separate empirical-Bayes
posterior model. Its rankings, school profile, and supplemental analyses are
presented under their own explorer section and are not relabeled as Enhanced
Balanced Production.

---

## Frozen temporal methodology

### Same-season comparisons

Year-over-year comparisons require the exact previous calendar year and the
same season type.

Examples:

- 2026 Outdoor may compare with 2025 Outdoor;
- 2026 Indoor may compare with 2025 Indoor;
- Indoor never substitutes for Outdoor;
- the nearest available year is never substituted.

### Explicit missing seasons

Missing seasons remain explicit gaps.

The production data do not contain 2020 Outdoor. Milestone 7 does not create,
interpolate, zero-fill, carry forward, or nearest-match a 2020 Outdoor season.

### Rolling windows

Three- and five-year windows use calendar-year boundaries rather than the last
three or five observed rows.

A slope-based trend requires at least three eligible observations. One- and
two-season histories remain visible but are labeled insufficient for audited
trajectory classification.

### Post-season performances

Post-season performances remain included when the athlete is still within the
relevant collegiate school stint or eligibility period, consistent with the
frozen Milestone 5 development decision.

---

## Phase 7A — Seasonal trend foundations

### Phase 7A.1: overall trends

The overall trend builder publishes:

- school-season ranking history;
- exact year-over-year comparisons;
- indoor/outdoor comparison rows;
- three- and five-calendar-year windows.

Validated row counts:

| Publication | Rows |
|---|---:|
| Overall seasonal base | 32,632 |
| Comparable year-over-year rows | 17,763 |
| Indoor/outdoor rows | 10,577 |
| Multi-season window rows | 65,264 |

All hard checks passed.

### Phase 7A.2: event and event-group trends

The event and event-group builder publishes seasonal, year-over-year, and
rolling-window products at both grains.

Validated row counts:

| Publication | Rows |
|---|---:|
| Event seasonal base | 36,576 |
| Event year-over-year | 7,346 |
| Event windows | 73,152 |
| Event-group seasonal base | 50,561 |
| Event-group year-over-year | 18,098 |
| Event-group windows | 101,122 |

The frozen taxonomy contains seven registered groups:

- Combined Events
- Distance
- Hurdles
- Jumps
- Middle Distance
- Sprints
- Throws

The 3000m steeplechase is classified as Distance. The 500m, 600m, and 1000m
remain excluded from the production taxonomy.

---

## Phase 7B — Program trajectory

Phase 7B converts seasonal histories into program-level trajectory products.

Published products include:

- trajectory windows;
- rise/fall classifications;
- latest program snapshots;
- trajectory leaderboards;
- event-group profiles;
- event profiles;
- comparison snapshots.

Validated row counts:

| Publication | Rows |
|---|---:|
| Program trajectory | 65,264 |
| Rise/fall classifications | 12,434 |
| Latest snapshots | 6,217 |
| Trajectory leaderboard | 11,008 |
| Group profiles | 11,008 |
| Event profiles | 6,722 |
| Comparison snapshots | 11,008 |

Trajectory labels distinguish:

- `rising_aligned`
- `falling_aligned`
- `score_up_rank_down`
- `score_down_rank_up`
- `mixed`
- `insufficient_history`

All 15 hard checks passed.

---

## Phase 7C — Program comparison

Phase 7C adds peer and conference context.

Published products include:

- national peer context;
- conference leaderboards;
- latest indoor/outdoor comparisons;
- indoor/outdoor history;
- long-form comparison metrics;
- enriched comparison rows;
- validated comparison partitions.

Validated row counts:

| Publication | Rows |
|---|---:|
| Peer context | 11,008 |
| Conference leaderboard | 11,008 |
| Latest indoor/outdoor | 2,686 |
| Indoor/outdoor history | 2,686 |
| Long-form metrics | 88,064 |
| Enriched comparison rows | 11,008 |
| Comparison partitions | 56 |

All 18 hard checks passed.

---

## Phase 7D — Final trend publication

Phase 7D consolidates the Milestone 7 trend and comparison products into:

```text
data/processed/milestone7/seasonal_program_trends_v1/
phase_7d_final_publication/
seasonal_program_trends_v1.duckdb
```

The final publication contains:

- 50 registered tables;
- 14 curated explorer tables;
- 352 programs in the explorer index;
- 11,008 latest program-summary rows;
- 11,008 explorer program-summary rows;
- 88,064 explorer comparison-metric rows.

All 26 hard checks passed.

The four upstream source databases were verified byte-identical before and
after publication.

---

## Phase 7E — Event-Balanced specialized rankings

### Input preflight

The frozen Milestone 6 database exposed 38 tables and 21 viable candidate
tables for specialized analysis.

Key input tables included:

| Table | Rows |
|---|---:|
| `athlete_model_points` | 785,364 |
| `official_athlete_points` | 392,682 |
| `school_event_model_points` | 137,150 |
| `official_school_event_points` | 68,575 |
| `group_balanced_points_gender` | 55,648 |
| `official_group_points_gender` | 27,824 |

The source database remained byte-identical.

### Specialized publication

The final v2 specialized-ranking publication registers 12 analyses:

1. Development consistency
2. Elite/frontier development
3. Developing baseline tier
4. Competitive baseline tier
5. Advanced baseline tier
6. Elite baseline tier
7. Breakout rate
8. Balanced program
9. Development efficiency
10. Ranking robustness
11. Inbound transfer development
12. National elite finishers — Endpoint 90+

Current publishable leaders:

| Analysis | Leader |
|---|---|
| Development consistency | Michigan State |
| Elite/frontier development | N. Carolina A&T |
| Developing baseline tier | Colorado St. |
| Competitive baseline tier | Navy |
| Advanced baseline tier | Montana State |
| Elite baseline tier | Arkansas |
| Breakout rate | LSU |
| Balanced program | Navy |
| Development efficiency | Mercer |
| Ranking robustness | N. Carolina A&T |
| National elite finishers — Endpoint 90+ | Coastal Carolina |

Inbound transfer development is registered but not published under the frozen
Broad coverage because no school satisfies the validated destination-school
support contract. The explorer reports this status explicitly and does not
fabricate a leaderboard.

The publication contains:

- 12 registered analyses;
- 11 publishable leaders;
- one explicit unavailable status;
- 22 hard checks;
- zero failed checks.

---

## Explorer

The production explorer is:

```text
src/apps/seasonal_development_explorer.py
```

Run it with:

```bash
streamlit run src/apps/seasonal_development_explorer.py
```

### Navigation

The top-level explorer navigation is:

- Rankings
- Trends
- Compare
- Average Development
- Diagnostics
- Coverage
- Methodology

### Rankings hierarchy

```text
Rankings
├── Official Rankings
└── Specialized Rankings
```

Official Rankings uses Enhanced Balanced Production.

Specialized Rankings displays the audited Phase 7E Event-Balanced products.

### Average Development hierarchy

```text
Average Development
├── Rankings
├── School Profile
└── Supplemental Rankings
```

These views use the preserved Average Development/posterior framework.

### Trend coverage behavior

The explorer:

- defaults Program Trends to Outdoor;
- hides Endpoint 95+ from user selectors while preserving it in audited data;
- shows only trend cohorts with sufficient registered seasonal coverage;
- labels cohort and school choices with available season counts;
- displays points rather than false lines for single-observation histories;
- reports missing momentum and consistency as unavailable rather than `nan`;
- keeps missing production seasons explicit.

Broad — All Athletes Indoor currently contains only the 2026 season, so it is
not presented as a multi-season trend cohort.

---

## Production source files

```text
src/analysis/milestone7/
├── audit_event_balanced_specialized_rankings_inputs.py
├── build_phase_7a_event_group_trends.py
├── build_phase_7a_overall_trends.py
├── build_phase_7b_program_trajectory.py
├── build_phase_7c_program_comparison.py
├── build_phase_7d_final_publication.py
└── build_phase_7e2_event_balanced_specialized_rankings.py
```

---

## Validation summary

Milestone 7 completion requires:

- exact previous-year same-season comparisons;
- explicit missing-season handling;
- no fabricated 2020 Outdoor production;
- calendar-year rolling windows;
- frozen event and group taxonomy;
- Enhanced Balanced Production as the official primary model;
- Average Development kept separate;
- immutable upstream source databases;
- unique publication keys;
- explicit support and eligibility rules;
- no fabricated inbound-transfer leaderboard;
- successful explorer compilation;
- no deprecated Streamlit width arguments;
- clean Git whitespace validation.

All production gates passed.

---

## Interpretation limits

1. Rankings are observational, not causal estimates of coaching quality.
2. Program movement can reflect roster composition, event coverage, and data
   availability in addition to athlete development.
3. Early seasons and narrow cohorts may have reduced support.
4. Rank movement depends on the strength and number of competing schools.
5. Inbound transfer status is inferred from observed school chronology and is
   not an external transfer-registry classification.
6. Missing seasons remain missing and should not be interpreted as zero
   performance.
7. Specialized rankings answer different questions and should not be combined
   into one undocumented composite score.

---

## Final result

Milestone 7 delivers a reproducible longitudinal program-analysis layer on top
of the frozen NCAA athlete-development publication:

- seasonal program histories;
- exact year-over-year comparisons;
- rolling trajectories;
- national and conference context;
- indoor/outdoor comparisons;
- event and event-group profiles;
- official Event-Balanced specialized rankings;
- a unified Streamlit explorer;
- complete versioned validation and documentation.
