# Milestone 6 — Seasonal Development Rankings and Explorer

## Status

**Complete**

## Objective

Extend the frozen Milestone 5 athlete-development model into:

- season-by-season NCAA Division I development rankings;
- event-balanced development-production rankings;
- broad, frontier, elite, national-elite, and championship-caliber cohorts;
- final model validation and sensitivity testing;
- a local Streamlit ranking explorer;
- one frozen final Milestone 6 publication.

Milestone 6 preserves the validated Milestone 5 value-added model. It does
not replace the original athlete-development calculation with a separate
unrelated model.

---

## Final model hierarchy

### Official primary model

**Enhanced Balanced Production**

This answers:

> How much reliable athlete development did a program produce?

The official model uses:

```text
original athlete value added
× support reliability
→ equal positive event pools
→ bounded negative event pools
→ athlete contributions summed to schools
```

Parameters:

```text
support reliability = sqrt(n / (n + 191))
positive event budget = 100,000
positive group budget = 100,000
negative event cap = 100,000
extra elite multiplier = none
```

The original athlete signal remains:

```text
observed improvement
− cross-fitted expected improvement
```

### Balanced-production companion

**Original Balanced Production v4.1**

This preserves the exact validated Phase 6D v4.1 formula:

- no support-reliability adjustment;
- 100,000 positive points per publishable event;
- uncapped linear negative points;
- athlete-school-event contributions summed to schools.

### Efficiency companion

**Average Athlete Development**

This answers:

> How well did the typical athlete develop?

Two time views are retained:

- **All Time — Frozen Milestone 5**
- **Single Season — Milestone 6**

The frozen all-time overall ranking remains led by Air Force, LSU, and
Kentucky.

---

## Phase 6A — Seasonal Average-Development Rankings

### Season definition

A ranking labeled `2025 Indoor` includes development trajectories whose
endpoint stable period is the 2025 indoor season.

The season label represents when development was realized. It is not a
randomized causal estimate and is not necessarily a strict one-calendar-year
change.

### Published scopes

1. Combined overall
2. Men's overall
3. Women's overall
4. Gender-specific individual event
5. Combined-gender individual event
6. Gender-specific coaching group
7. Combined-gender coaching group

### Completed results

```text
Endpoint seasons: 40
Endpoint years: 2007–2026
Season-athlete units: 141,635
Season-event units: 189,703
Season-group units: 219,278
Official ranking rows: 10,336
```

The Phase 6A gate passed with frozen Milestone 5 inputs, unchanged input
hashes, unique contribution identifiers, valid posterior scores and
confidence intervals, threshold reconciliation, at least five eligible
schools per published partition, and versioned outputs.

---

## Phase 6B — Development Cohorts

Milestone 6 expanded the seasonal rankings into five cohorts:

| Cohort | Definition |
|---|---|
| Broad | All eligible athletes |
| Frontier | Baseline level 70+ |
| Elite | Baseline level 80+ |
| National Elite Finishers | Endpoint level 90+ |
| Championship-Caliber Finishers | Endpoint level 95+ |

The cohorts use the same underlying development model and publication gates.

---

## Phase 6C — Event-Fairness Audit

The initial model gave high-volume events substantially more total influence.

Examples from the audit:

```text
800m influence: approximately 15,307
400m influence: approximately 12,135
200m influence: approximately 10,139
10,000m influence: approximately 789
combined events: approximately 52–108
```

Direct trajectory-count reweighting was rejected because it changed rankings
too aggressively. The final policy instead gives every publishable
championship event an equal positive opportunity before school aggregation.

---

## Phase 6D — Athlete-Level Event-Balanced Points

### Analytical unit

```text
athlete × school × event × ranking period
```

Multiple eligible trajectories for the same athlete-school-event unit are
averaged before point allocation.

For every publishable event partition:

```text
positive event pool = 100,000
```

Regression receives separate negative points and does not consume the positive
pool.

Completed results:

```text
Athlete-point rows: 392,682
School-event rows: 68,575
Event partitions: 449
Negative athlete rows: 193,725
Group partitions: 401
Single-season combined rows: 13,882
```

All positive event and group budgets reconcile to 100,000. School-event totals
reconcile to athlete contributions. There is no top-eight cutoff.

---

## Phase 6E — Enhanced and Original Model Variants

Two balanced-production formulas were published together:

1. Enhanced Balanced Production
2. Original Balanced Production v4.1

Enhancements added empirical support reliability, a bounded negative event
pool, concentration diagnostics, roster-size diagnostics, elite reward
diagnostics, and model comparisons.

```text
Athlete-model rows: 785,364
Event-model partitions: 898
Enhanced capped negative partitions: 171
Mean enhanced/original rank correlation: 0.980486
```

Original v4.1 was reproduced to numerical tolerance.

---

## Phase 6F — Final Model Validation

Ten controlled variants tested support values `k = 0, 50, 100, 191, 300,
500`, negative caps of `0.5×`, `1.0×`, and `1.5×`, uncapped negative points,
and exact Original v4.1 behavior.

Final evidence:

```text
Enhanced versus Original v4.1 rank correlation: 0.980708
Mean top-10 overlap: 0.917
Mean top-25 overlap: 0.940
P95 largest-athlete share: 0.3041
Mean effective positive athletes: 260.98
Mean absolute roster correlation: 0.2412
Mean positive-athlete-count correlation: 0.6007
Matched nonnegative elite slope share: 0.950
Matched elite advantage share: 0.979
Median matched elite advantage: 0.5821
```

Matched elite testing compared athletes within the same gender, event, and
similar observed-improvement range. No additional elite multiplier was added.

---

## Phase 6G — Final Freeze and Publication

The final publication passed all hard checks.

```text
Official athlete-point rows: 392,682
Official school-event rows: 68,575
Official event partitions: 449
Official single-season combined rows: 13,882
```

Frozen model:

```text
Primary model: Enhanced Balanced Production
Support k: 191
Positive event budget: 100,000
Negative event cap: 100,000
Extra elite multiplier: none
```

Latest broad leaders:

### 2026 Indoor

| Rank | School | Net points |
|---:|---|---:|
| 1 | Charlotte | 11,775.98 |
| 2 | Navy | 11,728.34 |
| 3 | Montana State | 11,719.40 |

### 2026 Outdoor

| Rank | School | Net points |
|---:|---|---:|
| 1 | Air Force | 13,132.29 |
| 2 | UC Santa Barbara | 11,939.57 |
| 3 | Montana | 11,199.94 |

---

## Explorer

Run:

```bash
source .venv/bin/activate
streamlit run src/apps/seasonal_development_explorer.py
```

Pages:

- Event-Balanced Points
- Model Diagnostics
- Average Development
- School Profile
- Season Coverage
- Methodology

The explorer preserves Enhanced Balanced Production, Original v4.1, the
frozen all-time Average Athlete Development ranking, and seasonal
Average Athlete Development rankings.

---

## Event taxonomy

- Individual NCAA championship events
- 10 coaching-oriented groups
- Steeplechase belongs to Distance
- No standalone steeplechase group
- 500m, 600m, and 1000m excluded from the primary championship ranking
- Relays and cross-country excluded from individual athlete-development scoring

---

## Final output

```text
data/processed/milestone6/
└── final_development_rankings_v1/
    └── phase_6g_final_publication/
        ├── final_development_rankings_v1.duckdb
        ├── final_model_decision.csv
        ├── final_model_scorecard.csv
        ├── model_registry.csv
        ├── athlete_model_points.csv
        ├── event_balanced_point_rows.csv
        ├── event_balanced_overall_gender.csv
        ├── event_balanced_overall_combined.csv
        ├── group_balanced_points_gender.csv
        ├── group_balanced_points_combined.csv
        ├── group_balanced_overall_gender.csv
        ├── group_balanced_overall_combined.csv
        ├── average_development_seasonal_rankings.csv
        ├── average_development_elite_rankings.csv
        ├── official_season_overall_gender.csv
        ├── official_season_overall_combined.csv
        ├── hard_checks.csv
        ├── input_manifest.csv
        ├── phase_6g_report.txt
        └── terminal_output.txt
```

---

## Interpretation

**Enhanced Balanced Production** measures reliable total development
production. It reflects both development quality and breadth.

**Original Balanced Production v4.1** preserves the exact original
athlete-level balanced formula.

**Average Athlete Development** measures how well the typical athlete
developed and is the preferred efficiency-oriented companion.

---

## Limitations

- Rankings are observational, not randomized causal estimates.
- A season refers to the trajectory endpoint season.
- Trajectories can span more than one year.
- Early seasons can have lower coverage.
- Sparse elite cohorts can be concentrated.
- Athlete points are allocated inside separate event pools.
- Relays and cross-country are excluded.
- Production rankings intentionally reflect quality and breadth.
- Average Athlete Development should accompany comparisons of differently
  sized programs.

---

## Dependencies

Phase 6G CSV export requires:

```text
pytz>=2026.2
```

---

## Completion gate

Milestone 6 is complete because all upstream model gates passed, hashes stayed
unchanged, seasonal products were published, event and group budgets
reconciled, negative caps were respected, athlete contributions reconciled to
school totals, companion models were preserved, sensitivity and matched elite
testing passed, final parameters were frozen, the publication gate passed,
and the Streamlit explorer reads the frozen publication.

**Milestone 6 status: COMPLETE**
