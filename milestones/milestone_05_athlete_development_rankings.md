# Milestone 5 — Athlete Development Methodology and NCAA Division I School Rankings

## Objective

Measure how effectively NCAA Division I programs develop and sustain athlete performance while accounting for event difficulty, starting level, proximity to the human performance frontier, regression, multi-event participation, roster size, and sample reliability.

Milestone 5 begins only after the Milestone 4 analytical dataset passes its reconstruction and cleaning audits.

---

## Core methodology

### Robust athlete-event-season level

For each athlete, school stint, canonical event, gender, season type, and season:

1. Retain eligible individual performances.
2. Rank marks in the correct performance direction.
3. Select the best three valid marks.
4. Use the median of those marks.
5. Require sufficient marks and distinct meets.

### Development gain

Measure movement toward an event-specific performance frontier.

For lower-is-better events:

```text
start_gap = starting_level - frontier
end_gap   = ending_level - frontier
```

For higher-is-better events:

```text
start_gap = frontier - starting_level
end_gap   = frontier - ending_level
```

Candidate measures include:

```text
headroom_fraction_closed = 1 - end_gap / start_gap
log_headroom_gain        = ln(start_gap / end_gap)
```

### Elite-maintenance credit

An athlete who begins near the frontier and sustains that level should earn positive credit even without a large personal best.

Maintenance credit depends on:

- Proximity to the event frontier
- Retention of elite performance
- Number of eligible seasons
- Reliability of the athlete-season estimates

### Severe-regression rule

Significant regression must produce a strongly negative score.

Elite-maintenance credit cannot rescue a materially regressing athlete. Once event-normalized regression exceeds the defined tolerance:

- Maintenance credit is removed or sharply suppressed.
- A nonlinear regression penalty is applied.
- Larger regression produces increasingly negative results.

The score must distinguish between:

- Elite maintenance
- Minor normal variation
- Significant regression
- Severe regression

---

## Frontier construction

Frontiers are estimated by:

```text
canonical event
× gender
× season type
× season year
```

The method must avoid using a single raw best mark as the frontier.

Candidate methodology includes:

- One representative mark per athlete
- Smoothed elite percentiles
- Adjacent-season pooling
- Long-run event shrinkage
- Minimum sample-size rules
- Safety margins beyond the observed elite boundary
- Pandemic-season handling
- Stored frontier diagnostics

---

## Multi-event athletes

An athlete must not count as several independent athletes merely because they compete in related events.

The methodology will:

1. Score each eligible event.
2. Group correlated events into event families.
3. Weight by reliability.
4. Normalize event weights within the athlete-school stint.
5. Produce one capped athlete-stint contribution.

---

## School aggregation

School outputs should include:

```text
development_score
elite_maintenance_score
regression_score
combined_program_score
eligible_athlete_count
eligible_stint_count
event_family_coverage
sample_reliability
```

The development-only score must remain visible even when a combined score is published.

School aggregation must address:

- Roster size
- Depth versus stars
- Minimum athlete counts
- Event-family balance
- Transfer stints
- Unequal data coverage
- Outlier influence
- Shrinkage for small samples

---

## Validation

Required validation includes:

- Alternative frontier definitions
- Alternative endpoint definitions
- Alternative maintenance weights
- Alternative regression thresholds
- Excluding disrupted seasons
- Including and excluding hand times
- Including and excluding team-only attribution
- School rank stability
- Athlete-level reasonableness checks
- Manual review of extreme positive and negative scores

---

## Completion criteria

Milestone 5 is complete when:

- Athlete development scores are reproducible.
- Elite maintenance earns positive credit.
- Significant regression is strongly negative.
- Multi-event athletes are not double counted.
- School rankings include transparent components and uncertainty.
- Sensitivity analysis demonstrates reasonable stability.
- Rankings and methodology are documented and published.
