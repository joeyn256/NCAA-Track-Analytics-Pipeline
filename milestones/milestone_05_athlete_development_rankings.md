# Milestone 5 — Athlete Development Rankings

<!-- RECRUITER_SUMMARY_START -->
## At a Glance

**Status:** Complete

### Executive Summary

Built a school-held-out athlete-development model and uncertainty-adjusted NCAA Division I program rankings. The final system combines record-anchored event normalization, stable multi-meet periods, cross-fitted expected improvement, equal-athlete aggregation, empirical-Bayes shrinkage, and extensive sensitivity testing.

### Headline Results

| Metric | Final result |
|---|---:|
| Primary modeling trajectories | 189,703 |
| Athletes | 79,535 |
| Athlete-school units | 80,077 |
| Schools represented | 361 |
| Officially ranked schools | 353 |
| Canonical events ranked | 30 |
| Coaching groups | 10 |
| Minimum alternative rank correlation | 0.9979 |
| Failed sensitivity variants | 0 |
| Overall leader | **Air Force** |

### What This Milestone Demonstrates

- nonlinear event-specific feature engineering;
- school-grouped cross-validation and expected-value modeling;
- hierarchical and multi-event-neutral aggregation;
- empirical-Bayes shrinkage and uncertainty quantification;
- outlier, threshold, and remove-best/remove-worst sensitivity analysis;
- publication-ready ranking and supplemental analytical products.

### Project Evolution

The initial draft considered direct headroom formulas and explicit elite-maintenance bonuses. The final production design replaced those provisional rules with record-anchored performance levels and cross-fitted expected improvement, producing a less arbitrary and more defensible value-added model.

[Previous: Milestone 4](milestone_04_canonical_identity_and_school_stints.md) · [Back to the milestone index](README.md)

---
<!-- RECRUITER_SUMMARY_END -->

## Objective

Build a reproducible system that answers:

1. How much did an athlete improve while attributed to a specific school?
2. How much improvement should have been expected from a comparable athlete?
3. Which programs most consistently produce improvement above expectation?
4. Which conclusions remain stable after multi-event deduplication, shrinkage, alternative aggregation, and outlier sensitivity tests?
5. How do results differ by gender, event, event group, starting level, transfer status, and development profile?

---

## Final design decision

The initial Milestone 5 planning draft considered direct headroom-closure formulas, explicit elite-maintenance bonuses, and separate nonlinear regression penalties.

The production methodology replaced those provisional rules with a more defensible design:

1. Convert each eligible performance to an event-specific, record-anchored level.
2. Construct stable multi-meet athlete-event-period levels.
3. Measure observed improvement across school-attributed trajectories.
4. Estimate expected improvement from comparable trajectories using school-grouped cross-fitting.
5. Define athlete value added as the residual above or below expectation.
6. Aggregate event families so each athlete-school unit receives one total vote.
7. Apply empirical-Bayes shrinkage and publish uncertainty intervals.

This approach rewards improvement near the performance frontier through the nonlinear performance-level scale while avoiding manually assigned maintenance bonuses.

---

## Data lineage

Milestone 5 begins from the validated Milestone 4 analytical layer:

```text
6,594,540 source performances
        ↓
canonical people and transfer-aware school stints
        ↓
eligible individual track-and-field performances
        ↓
record-anchored normalized performance levels
        ↓
stable athlete-event-season periods
        ↓
observed school-attributed trajectories
        ↓
school-held-out expected improvement
        ↓
athlete value added
        ↓
equal-family, equal-athlete aggregation
        ↓
uncertainty-adjusted school rankings
```

Primary upstream inputs:

- `data/database/ncaa_track_analytics.duckdb`
- Milestone 4 canonical-person and school-stint databases
- versioned collegiate record reference files in `data/reference/collegiate_records/`

Generated analytical databases remain local and are excluded from Git.

---

## 1. Event and performance foundation

### Event registry and eligibility

Raw TFRRS labels were mapped to canonical individual events, event families, gender, season type, mark direction, and analytical eligibility.

Relays were intentionally excluded from the individual athlete-development model because a relay mark belongs to a lineup and school team rather than one athlete. Cross country was also deferred because course, terrain, distance, and meet-condition comparability require a separate team-performance methodology.

Final publication event coverage:

- **30 canonical individual events**
- **10 coaching-oriented event groups**
- indoor and outdoor season-specific rankings
- gender-specific and combined-gender ranking products

Final coaching groups:

- Sprints
- Middle Distance
- Distance
- Hurdles
- Steeplechase
- Jumps
- Throws
- Combined Events
- Field
- Special Events

`Track` and `Endurance` umbrella labels were removed because they duplicated the existing Sprints and Distance products.

### Collegiate record anchors

Versioned collegiate record pages were imported locally and audited before use.

Final anchor results:

- **82 approved record anchors**
- **8 pending candidates promoted after review**
- **5 outside-season candidates retained outside the scoring scope**
- all required scoring events covered

Reference provenance includes:

- source HTML snapshots;
- candidate registries;
- eligibility decisions;
- manual-policy registries;
- source manifests;
- SHA-256 hashes;
- hard-check outputs.

### Performance-level function

Eligible marks are transformed to a direction-aware record-anchor ratio and then scored using:

```text
performance_level
= 100 × min(1, anchor_ratio)²
```

The square increases the value of equivalent improvement as an athlete approaches the collegiate performance frontier.

Examples of the intended behavior:

- improving a weak mark by a fixed raw amount earns less normalized movement;
- improving an already strong mark by the same raw amount earns more;
- performances beyond the approved anchor are capped for scoring and audited separately.

Materialized scoring results:

| Metric | Value |
|---|---:|
| Eligible performance-level rows | 4,664,041 |
| Quarantined anchor exceedances | 49 |
| Tolerance-only exceedances | 2 |
| Hard scoring checks | PASS |

---

## 2. Stable athlete-event-period levels

A single personal best is too noisy to represent a season. Milestone 5 therefore builds stable athlete-event-period levels from multiple meets.

Primary policy:

- normally require three qualifying meets;
- use a stable statistic across the strongest qualifying observations;
- retain explicitly approved two-meet exceptions for sparse events;
- pool selected unsupported event labels through documented family rules;
- preserve season type rather than casually merging indoor and outdoor periods.

Approved two-meet exceptions:

- men’s and women’s outdoor 3000m;
- men’s and women’s indoor 600m.

Final period results:

| Metric | Value |
|---|---:|
| Source eligible performances | 4,664,041 |
| Distinct meet observations | 4,407,132 |
| Stable athlete-event periods | 1,628,956 |
| Standalone-primary periods | 713,556 |
| Added two-meet exception periods | 6,671 |
| Family-pool supporting periods | 1,744 |
| Trajectory-ready segments | 189,839 |
| Athletes represented | 79,551 |
| Schools represented | 361 |

---

## 3. Observed development trajectories

Trajectory grain:

```text
canonical person
× school
× gender
× season type
× canonical event
```

The trajectory remains school-specific so transfers do not transfer credit between institutions.

Observed improvement:

```text
observed improvement
= endpoint stable performance level
− baseline stable performance level
```

Stored diagnostics include:

- baseline and endpoint seasons;
- elapsed duration;
- annualized improvement;
- first-to-peak improvement;
- slope;
- consecutive transition statistics;
- number of stable periods;
- distinct meets;
- reliability and support flags.

Final observed trajectory results:

| Metric | Value |
|---|---:|
| Observed trajectories | 189,839 |
| Primary 1–5 season modeling candidates | 189,703 |
| Explicit 6+ season exclusions | 136 |
| Athletes in modeling cohort | 79,535 |
| Schools in modeling cohort | 361 |
| Mean observed improvement | 2.5805 |
| Improved trajectories | approximately 70.2% |

Durations of six or more seasons were isolated rather than allowed to distort the primary collegiate-development benchmark.

---

## 4. Expected-improvement model

### Modeling objective

Expected improvement captures how much normalized development is typical for a comparable trajectory before school value added is calculated.

The model uses:

- baseline performance level;
- event or event-family context;
- gender;
- season type;
- duration;
- stable-period and support information;
- approved sparse-event fallback resolution.

The model does **not** use school identity as a predictor.

### Cross-fitting

Schools were assigned deterministically to five folds. Every prediction for a trajectory is generated from training statistics that exclude the trajectory’s school fold.

This prevents a school from helping define the expectation against which that same school is evaluated.

Five-fold cohort totals:

| Fold | Trajectories | Athletes | Schools |
|---:|---:|---:|---:|
| 1 | 38,510 | 15,871 | 73 |
| 2 | 38,261 | 16,151 | 72 |
| 3 | 37,905 | 15,873 | 72 |
| 4 | 37,683 | 16,106 | 72 |
| 5 | 37,344 | 15,971 | 72 |

### Candidate comparison

Five out-of-sample benchmark candidates were compared:

1. `naive_fold_mean`
2. `resolution_raw_mean`
3. `hierarchical_mean_moderate`
4. `hierarchical_mean_strong`
5. `hierarchical_winsorized_moderate`

Selected model:

```text
resolution_raw_mean
```

Selected out-of-sample metrics:

| Metric | Value |
|---|---:|
| MAE | 3.3919 |
| RMSE | 4.5327 |
| Median absolute error | 2.6155 |
| Mean bias | +0.0524 |
| Prediction correlation | 0.4517 |
| Calibration slope | 0.9704 |
| R² | 0.2038 |

The selected model improved MAE by approximately **9.7%** and RMSE by approximately **10.8%** relative to the naive held-out-fold mean.

Global fallback predictions were retained with an explicit sensitivity caveat because their residual bias was larger than event-level predictions.

---

## 5. Athlete value added

For each trajectory:

```text
athlete value added
= observed improvement
− expected improvement
```

Interpretation:

- positive: improved more than expected;
- near zero: developed approximately as expected;
- negative: improved less than expected or regressed relative to expectation.

Frozen trajectory results:

| Metric | Value |
|---|---:|
| Scored trajectories | 189,703 |
| Above-expected trajectories | 95,179 |
| Below-expected trajectories | 94,524 |
| Mean athlete value added | +0.0524 |
| Median athlete value added | +0.0147 |
| Athletes | 79,535 |
| Schools | 361 |

---

## 6. Multi-event-neutral athlete aggregation

An athlete must not receive several full school votes merely because they compete in related events.

Aggregation policy:

1. Average trajectories within athlete, school, and event family.
2. Average the athlete’s event-family values equally.
3. Consolidate repeated analytical stints at the same school.
4. Allow a transfer athlete to contribute once to each distinct school.
5. Give every athlete-school unit total school voting weight exactly **1.0**.

Final aggregation results:

| Metric | Value |
|---|---:|
| Trajectories preserved | 189,703 |
| Athlete-event-family units | 98,888 |
| Athlete-school units | 80,077 |
| Distinct people | 79,535 |
| Schools | 361 |
| Athlete-school units with multiple trajectories | 53,793 |
| Units with multiple event families | 11,449 |
| Athletes represented at multiple schools | 540 |

This policy materially changes rankings relative to raw trajectory weighting:

- score correlation: **0.9660**
- rank correlation: **0.9564**
- mean absolute rank change: **21.8**
- maximum rank change: **119**

The difference confirms that athlete and event deduplication is necessary.

---

## 7. Uncertainty-adjusted school rankings

### Raw school score

```text
raw school score
= mean athlete-school value added
```

### Empirical-Bayes adjustment

Small samples receive stronger shrinkage toward the national athlete mean.

```text
posterior school score
= national mean
+ shrinkage weight × (raw score − national mean)
```

```text
shrinkage weight
= between-school variance
  / (between-school variance + stabilized sampling variance)
```

Within-school variance is stabilized using a pooled prior with 20 degrees of freedom.

Publication thresholds:

| Ranking | Minimum sample |
|---|---:|
| Official overall school rank | 30 athlete-school units |
| Men’s or women’s school rank | 20 same-gender units |
| Individual event rank | 10 athlete-event units |
| Combined-gender event rank | 15 athlete-event units |
| Core gender-specific event group | 20 athlete-group units |
| Special gender-specific event group | 10 athlete-group units |

A ranking partition also requires at least five sample-eligible schools.

Every school remains visible even when it does not qualify for an official rank.

### Final overall publication results

| Metric | Value |
|---|---:|
| Schools represented | 361 |
| Officially ranked schools | 353 |
| Insufficient-data schools | 8 |
| Athlete-school units | 80,077 |
| Estimated between-school variance | 0.3205 |
| Mean shrinkage weight | 0.793 |
| Posterior/raw rank correlation | 0.9874 |
| Mean absolute rank movement from raw | 8.26 |
| Maximum rank movement from raw | 166 |

### Official overall top 10

| Rank | School | Athletes | Posterior score | 95% interval |
|---:|---|---:|---:|---:|
| 1 | Air Force | 374 | 1.2442 | 0.8373 to 1.6511 |
| 2 | LSU | 304 | 1.1119 | 0.6693 to 1.5544 |
| 3 | Kentucky | 248 | 0.9874 | 0.5830 to 1.3918 |
| 4 | Ohio State | 337 | 0.8917 | 0.4858 to 1.2977 |
| 5 | Arkansas | 305 | 0.8500 | 0.4695 to 1.2305 |
| 6 | Minnesota | 421 | 0.8309 | 0.4491 to 1.2127 |
| 7 | Wisconsin | 272 | 0.8175 | 0.3980 to 1.2370 |
| 8 | Arizona | 299 | 0.7961 | 0.3635 to 1.2287 |
| 9 | Florida | 252 | 0.7546 | 0.3095 to 1.1996 |
| 10 | Indiana | 318 | 0.7453 | 0.3864 to 1.1042 |

All ten intervals are above zero.

The model also solved the small-program ranking problem. Stetson’s five-athlete raw score would have ranked first, but shrinkage reduced it to an all-school diagnostic rank of 103 with no official rank.

---

## 8. Final publication sensitivity audit

Seven approved variants were compared on the same 353-school publication population:

- primary variance prior;
- weaker variance stabilization;
- stronger variance stabilization;
- winsorized athlete values;
- family-median athlete values;
- removal of each school’s best athlete;
- removal of each school’s worst athlete.

Final stability results:

| Metric | Result |
|---|---:|
| Minimum alternative rank correlation | 0.9979 |
| Minimum top-10 overlap | 90% |
| Minimum top-25 overlap | 92% |
| Maximum median rank movement | 3 |
| Failed stability variants | 0 |

Removing each school’s best athlete preserved all ten primary top-10 programs. Minimum-sample thresholds of 20, 30, and 50 also preserved the primary top 25.

Evidence categories across all 361 schools:

| Category | Schools |
|---|---:|
| Credibly above expected | 53 |
| Not distinguishable from expected | 231 |
| Credibly below expected | 77 |

A numerical rank does not imply that adjacent schools are statistically distinguishable.

---

## 9. Event and coaching-group rankings

Phase 5J creates:

- gender-specific individual-event rankings;
- combined-gender individual-event rankings;
- indoor/outdoor season-event rankings;
- gender-specific coaching-group rankings;
- combined-gender coaching-group rankings.

Final results:

| Metric | Value |
|---|---:|
| Canonical events | 30 |
| Coaching groups | 10 |
| Official ranking rows | 25,619 |
| Phase gate | PASS |

Event-group aggregation first averages events within each athlete-school-group. A 100m/200m/400m athlete therefore receives one total sprint-group vote rather than three.

Some sparse scopes estimate zero between-school variance. In those cases, empirical-Bayes posterior scores collapse to a common mean and produce ties with wide intervals. Those partitions remain available for transparency but should not be presented as meaningful competitive separation.

---

## 10. Supplemental development rankings

Phase 5K adds eight admissions-ready analytical products without changing the frozen primary ranking.

### Development Consistency

```text
consistency index
= 50% school median value-added percentile
+ 50% stabilized above-expected share percentile
```

Minimum sample: 30 athletes.

Leader: **Air Force**

### Elite / Frontier Development

Uses trajectories beginning at normalized performance level 70 or higher.

Minimum sample: 20 athlete-segment units.

Leader: **Air Force**

### Baseline-tier development

| Tier | Definition | Leader |
|---|---|---|
| Developing | baseline below 50 | Northern Iowa |
| Competitive | 50 to below 65 | LSU |
| Advanced | 65 to below 80 | Arkansas |
| Elite | 80 or higher | Air Force |

### Breakout Rate

A breakout athlete has athlete-school value added of at least 5 points. Rates are stabilized with a beta-binomial prior.

Minimum sample: 30 athletes.

Leader: **Mercer**

### Balanced Program

Uses men’s and women’s posterior scores across:

- Sprints
- Middle Distance
- Distance
- Hurdles
- Jumps
- Throws

The index rewards mean group strength and penalizes:

- group-score dispersion;
- men’s-versus-women’s imbalance;
- missing event-group coverage.

Eligibility requires at least eight of twelve possible gender-group cells, including at least three men’s and three women’s cells.

| Metric | Value |
|---|---:|
| Schools represented | 337 |
| Officially eligible | 158 |
| Leader | LSU |

### Development Efficiency

Ranks posterior mean annualized athlete-school value added.

Minimum sample: 30 athletes.

Leader: **UC San Diego**

### Ranking Robustness

Programs are ordered by their worst rank across all seven approved sensitivity variants, followed by average rank and rank spread.

Schools: 353.

Leader: **Air Force**, ranked first under every approved variant.

### Inbound Transfer Development

A destination-school contribution is identified when the athlete’s first observed year at the school occurs after the athlete’s first observed year at any school.

| Metric | Value |
|---|---:|
| Destination athlete-school units | 542 |
| Schools represented | 145 |
| Minimum official sample | 15 |
| Leader | Florida |

The transfer product is supplemental and should be described as provisional because destination samples are much smaller and “transfer” is inferred from observed school chronology rather than an external transfer registry.

---

## 11. Final publication artifacts

### Primary publication database

```text
data/processed/milestone5/athlete_development_v1/
phase_5i_publication_freeze/
ncaa_d1_athlete_development_rankings_v1.duckdb
```

Primary public files:

- `official_overall_rankings.csv`
- `all_school_rankings.csv`
- `insufficient_data_schools.csv`
- `mens_rankings.csv`
- `womens_rankings.csv`
- `event_family_rankings.csv`
- `school_score_components.csv`
- `school_metadata.csv`
- `PUBLICATION_SUMMARY.md`

### Event and group database

```text
data/processed/milestone5/athlete_development_v1/
phase_5j_event_and_group_rankings/
ncaa_d1_event_development_rankings_v1.duckdb
```

Primary outputs:

- `individual_event_rankings.csv`
- `combined_gender_event_rankings.csv`
- `season_event_rankings.csv`
- `event_group_rankings.csv`
- `combined_gender_group_rankings.csv`
- `event_taxonomy.csv`
- `event_group_membership.csv`

### Supplemental ranking database

```text
data/processed/milestone5/athlete_development_v1/
phase_5k_supplemental_development_rankings/
supplemental_development_rankings_v1.duckdb
```

Primary outputs:

- `development_consistency_rankings.csv`
- `elite_development_rankings.csv`
- `baseline_tier_rankings.csv`
- `breakout_rate_rankings.csv`
- `balanced_program_rankings.csv`
- `development_efficiency_rankings.csv`
- `ranking_robustness_rankings.csv`
- `transfer_development_rankings.csv`

All generated databases and large analytical outputs remain excluded from Git.

---

## 12. Reproduction order

Milestone 5 scripts are stored in:

```text
src/analysis/milestone5/
```

High-level execution order:

1. Inspect Milestone 4 inputs and profile raw event/mark coverage.
2. Build, review, and freeze the event registry.
3. Parse and validate eligible marks.
4. Snapshot and import collegiate record sources.
5. Finalize record-anchor eligibility and official anchors.
6. Build the scoring cohort and calibrate the performance-level function.
7. Audit anchor exceedances and materialize performance levels.
8. Build stable athlete-event-period levels and freeze eligibility policy.
9. Build observed trajectories and modeling audit.
10. Freeze the expected-improvement cohort.
11. Compare benchmark candidates and freeze the selected model.
12. Build multi-event-neutral athlete contributions.
13. Build uncertainty-adjusted school rankings.
14. Run the final publication sensitivity audit.
15. Freeze the primary publication package.
16. Build event and coaching-group rankings.
17. Build supplemental development rankings.

Every major phase:

- attaches prior databases read-only;
- writes to a versioned output directory;
- records input and output manifests;
- calculates SHA-256 hashes;
- executes hard validation checks;
- publishes only after a phase gate passes.

---

## 13. Limitations

1. **Observational attribution**  
   Value added is associated with a school stint; it is not a randomized causal estimate of coaching effect.

2. **Data availability**  
   Rankings depend on recorded TFRRS performances and historical coverage.

3. **Expected-model fallback**  
   Sparse event contexts may rely on broader family or global expectations.

4. **Small event partitions**  
   Some individual-event or special-event scopes remain uncertainty-heavy or fully tied after shrinkage.

5. **Transfer inference**  
   Inbound transfer status is inferred from observed school chronology, not an external transfer portal.

6. **Relays excluded**  
   Relay marks require lineup-aware, team-level modeling and will be added later.

7. **Cross country deferred**  
   Course and condition comparability require a separate methodology.

8. **Rank interpretation**  
   Adjacent ranks are not necessarily statistically distinguishable; posterior intervals and evidence categories must remain visible.

---

## 14. Future extensions

Planned later work:

- relay team-performance index;
- cross-country program development and team-performance index;
- combined track, relay, and cross-country program composite;
- interactive dashboards and visualizations;
- athlete-level trajectory explorer;
- predictive performance modeling;
- external validation against championships, All-America outcomes, and recruiting indicators.

Relays and cross country are future extensions, not unfinished Milestone 5 requirements.

---

## Completion criteria

| Requirement | Status |
|---|---|
| Reproducible athlete development scores | PASS |
| Frontier-aware event normalization | PASS |
| School-held-out expected improvement | PASS |
| Significant negative development retained | PASS |
| Multi-event athletes not double counted | PASS |
| Transfers credited by school | PASS |
| Transparent uncertainty-adjusted school rankings | PASS |
| Men’s, women’s, event, and group rankings | PASS |
| Sensitivity stability demonstrated | PASS |
| Publication package frozen | PASS |
| Supplemental rankings produced | PASS |
| Methodology documented | PASS |

## Final Status

**Milestone 5 is complete.**

The project now publishes reproducible, transfer-aware,
uncertainty-adjusted athlete-development rankings for NCAA Division I
programs, individual events, coaching groups, and supplemental
development analyses.
