# Milestone 6 — Seasonal Rankings and Exploratory Analytics

## Status

**In Progress**

## Objective

Extend the frozen Milestone 5 athlete-development model into season-by-season
analytical products and recruiter-friendly visualizations.

The first goal is to publish rankings for every available indoor and outdoor
endpoint season, such as:

- 2024 Indoor
- 2024 Outdoor
- 2025 Indoor
- 2025 Outdoor
- 2026 Indoor
- 2026 Outdoor, when represented in the frozen trajectory data

The rankings reuse the validated Milestone 5 value-added scores rather than
creating a second development model.

---

## Phase 6A — Season-by-Season Development Rankings

### Season definition

A ranking labeled `2025 Indoor` includes development trajectories whose
endpoint stable period is the 2025 indoor season.

This measures development realized by that endpoint season. It is not
described as a randomized causal estimate or as a strict one-calendar-year
change.

### Published ranking scopes

1. Combined-gender overall rankings
2. Men's overall rankings
3. Women's overall rankings
4. Gender-specific individual-event rankings
5. Combined-gender individual-event rankings
6. Gender-specific event-group rankings
7. Combined-gender event-group rankings

### Athlete weighting

#### Overall rankings

1. Average trajectories within athlete, school, endpoint season, and event
   family.
2. Average event families within the athlete-school-season.
3. Give each athlete-school-season one total vote.

#### Individual-event rankings

Each athlete receives one vote per:

```text
school
× endpoint season
× gender
× canonical event
```

Repeated same-school analytical stints are consolidated.

#### Event-group rankings

Individual-event values are averaged within the athlete-school-season-group.

A 100m/200m/400m athlete therefore receives one total sprint-group vote rather
than three independent votes.

### Ranking model

Phase 6A reuses the Milestone 5 uncertainty model:

- stabilized within-school variance;
- 20-degree-of-freedom pooled variance prior;
- method-of-moments between-school variance;
- empirical-Bayes posterior score;
- 95% posterior interval;
- minimum school sample;
- at least five eligible schools per ranking partition.

### Minimum samples

| Scope | Minimum athlete units per school |
|---|---:|
| Combined overall | 15 |
| Men's or women's overall | 10 |
| Gender-specific event | 5 |
| Combined-gender event | 8 |
| Gender-specific core group | 8 |
| Gender-specific special group | 5 |
| Combined-gender core group | 12 |
| Combined-gender special group | 8 |

Schools below the threshold remain visible as insufficient-data rows.

### Event taxonomy

Phase 6A imports the frozen Milestone 5 taxonomy:

- 30 canonical individual events;
- 10 coaching-oriented event groups;
- no relay or cross-country scoring;
- no duplicate Track or Endurance umbrella groups.

### Planned Phase 6A outputs

```text
season_coverage_summary.csv
season_overall_rankings.csv
season_gender_rankings.csv
season_individual_event_rankings.csv
season_combined_gender_event_rankings.csv
season_event_group_rankings.csv
season_combined_gender_group_rankings.csv
season_partition_summary.csv
season_ranking_leaders.csv
seasonal_ranking_methodology.csv
seasonal_development_rankings_v1.duckdb
```

---

## Phase 6B — Seasonal Trend Analysis

After Phase 6A passes:

- identify programs rising or falling over time;
- measure year-to-year rank movement;
- calculate multi-season consistency;
- compare indoor and outdoor development;
- identify event-group trend leaders;
- flag large changes driven by small samples;
- separate posterior score movement from rank movement.

---

## Phase 6C — Recruiter-Friendly Visualizations

Planned visual products:

- overall ranking table;
- school score and interval chart;
- school development trend chart;
- event-group heatmap;
- men's-versus-women's comparison;
- baseline-tier profile;
- robustness profile;
- season-over-season rank movement;
- program comparison view.

---

## Phase 6D — Public Ranking Explorer

Potential implementation:

- Streamlit or similar Python application;
- school, season, gender, event, and group filters;
- uncertainty intervals visible by default;
- links back to methodology;
- downloadable filtered tables;
- local-first deployment with a public demo option.

---

## Validation requirements

Phase 6A is complete only when:

- all Milestone 5 input gates pass;
- source database hashes remain unchanged;
- all available indoor and outdoor endpoint seasons are registered;
- contribution identifiers are unique;
- posterior scores remain between the raw score and global mean;
- confidence intervals are valid;
- official eligibility reconciles with thresholds;
- every published partition contains at least five eligible schools;
- all generated files are versioned and registered in a manifest.

---

## Interpretation limits

Seasonal rankings inherit the Milestone 5 limitations.

Additional seasonal limitations:

- the season label refers to the trajectory endpoint season;
- trajectories can span more than one year;
- early seasons may have lower coverage;
- smaller event partitions may shrink to ties;
- rankings are observational and should retain uncertainty intervals.

A later extension may construct true consecutive-season transition rankings
after separately validating and freezing that modeling grain.

---

## Current phase

**Phase 6A — Season-by-Season Development Rankings**
