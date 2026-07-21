# Demo Script and Walkthrough Recording Guide

## Recommended recording length

Target **3–5 minutes**. Keep the browser zoom near 100%, close unrelated tabs,
hide bookmarks containing personal information, and use the live public
application.

## 30-second opening

> I built an end-to-end NCAA Division I track-and-field analytics platform
> covering nearly 194,000 athletes and 6.59 million standardized performances.
> The pipeline resolves athlete identity and transfers, models improvement
> relative to starting level, creates event-balanced school rankings, and
> publishes the results through a tested Streamlit explorer backed by a
> checksum-verified DuckDB release. The rankings are observational, and the
> application exposes the methodology, uncertainty, and coverage limitations.

## Walkthrough sequence

### 1. Public-facing homepage — 30 seconds

Show the project title, headline scale metrics, public model hierarchy, and
official ranking table.

Say:

> Enhanced Balanced Production is the official model. Original Balanced
> Production v4.1 is preserved as a robustness companion, while Average Athlete
> Development answers the efficiency-oriented typical-athlete question.

### 2. Official rankings — 45 seconds

Demonstrate model, cohort, time, and points-view controls. Show Endpoint 90+ and
note that Endpoint 95+ remains hidden from the normal selector because it is a
sparse audit cohort.

Say:

> Positive opportunity is balanced within publishable championship events, so
> high-volume events do not automatically dominate the school ranking.

### 3. Trends — 45 seconds

Open Program Trends, choose a school, and show the seasonal chart and history
table.

Say:

> Trends use observed seasons only. The project explicitly preserves missing
> 2020 Outdoor data rather than interpolating a result.

### 4. Compare — 45 seconds

Open Program Comparison and choose two schools. Show the summary, comparable
percentile profile, and indoor/outdoor history.

Say:

> The comparison surface uses the same frozen model and methodology as the
> official ranking rather than creating a separate ad hoc score.

### 5. Methodology and limitations — 45 seconds

Open Methodology and point to the observed-minus-expected concept, event
balancing, model hierarchy, and interpretation warnings.

Say:

> These rankings describe patterns in recorded collegiate performances. They do
> not prove that a coaching staff caused the observed development.

### 6. Engineering close — 30 seconds

Briefly show the GitHub repository, CI workflow, tests, and immutable release.

Say:

> The public application runs from a compact DuckDB with exact source-to-
> deployment parity. CI uses synthetic fixtures, the deployment is checked
> daily, and future releases are semantic-versioned and dry-run-first.

## Recording checklist

- Use the public app, not a local development URL.
- Avoid displaying email, bookmarks, terminal history, or personal folders.
- Use a school with enough seasonal history for the trends page.
- Pause briefly after navigation changes so tables and charts are visible.
- Keep the cursor away from important labels.
- Do not claim causal coaching impact, prediction accuracy, user traffic, or
  adoption.
- End on the live app or README public-project section.
