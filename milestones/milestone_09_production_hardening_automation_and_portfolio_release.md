# Milestone 9 — Production Hardening, Automation, and Portfolio Release

## Status

**In progress**

Milestone 9 converts the completed public analytics application into a
maintainable, tested, reproducible, and professionally presented v1.0 portfolio
product.

The production ranking methodology remains frozen. This milestone focuses on
software quality, release controls, user experience, documentation, and
portfolio presentation rather than analytical-model redesign.

## Production baseline

| Item | Frozen baseline |
|---|---|
| Production branch | `main` |
| Milestone 9 starting commit | `b763e0d23cd41e95e4c2dc5b4b43534e098a0b05` |
| Streamlit entrypoint | `src/apps/seasonal_development_explorer.py` |
| Python version | `3.12` |
| Public release tag | `public-deployment-v1` |
| Public application | `https://ncaa-d1-track-analytics-pipeline-explorer.streamlit.app/` |
| Standardized performances | 6,594,540 |
| Athletes | 193,961 |
| Institutions | 554 |
| Public resource tables | 81 |
| Public deployment rows | 2,918,594 |
| Source-to-deployment parity | 81 of 81 tables |
| Failed Milestone 8 release checks | 0 |

The annotated `public-deployment-v1` tag resolves to the frozen Milestone 8
release-candidate commit. It must not be moved, deleted, recreated, or reused.

## Frozen analytical contract

Milestone 9 preserves all established methodology and interpretation rules:

- Enhanced Balanced Production is the official primary model.
- Original Balanced Production v4.1 is a robustness companion.
- Average Development is a separate secondary model.
- Collegiate records remain versioned elite-ceiling anchors where appropriate.
- No additional elite multiplier is applied.
- Endpoint 90+ is the supported National Elite Finishers analysis.
- Endpoint 95+ remains in the publication for auditability but is hidden from
  the public explorer because it is too sparse for stable comparisons.
- Eligible post-season performances remain included within the relevant
  collegiate school stint or eligibility period.
- Missing seasons remain missing.
- No 2020 Outdoor production data may be fabricated, interpolated, carried
  forward, or replaced with neighboring seasons.
- Inbound-transfer development remains unavailable where the prior-school
  evidence contract is insufficient.
- Rankings are observational development measures, not causal coaching
  estimates, recruiting guarantees, current-roster strength ratings, or
  projected NCAA championship points.

## Phase 9A — Repository and production baseline

**Status: Complete**

The initial read-only audit confirmed:

- local and remote `main` were synchronized at the starting commit;
- the working tree was clean;
- the immutable release tag remained intact;
- no GitHub Actions workflow existed;
- all 150 tracked Python files parsed successfully;
- no tracked oversized production artifacts were present;
- local secrets, raw data, processed data, databases, logs, and caches were
  excluded from version control;
- the production loader failed cleanly when neither a database nor download URL
  was available;
- the existing Milestone 8 release-readiness suite required ignored local
  artifacts and was not directly suitable for public CI;
- the existing automated-test surface was minimal.

### Baseline risks

1. The compact-publication loader resolves and verifies its database during
   module import.
2. The Streamlit application therefore also requires a valid database
   configuration during import.
3. The current repository has no public CI workflow.
4. The current test suite does not cover the production loader or explorer.
5. The manual athlete scraper is stored in the test directory but is not a
   deterministic automated test.
6. Ruff, pytest, and Coverage are not declared as development dependencies.
7. `.ruff_cache/` is not explicitly ignored.
8. The development container uses Python 3.11 rather than production Python
   3.12 and performs broad environment updates.
9. Historical Milestone 8 release scripts are release-specific and must not be
   reused to recreate `public-deployment-v1`.
10. Some repository documentation and helper files contain stale references.

## Phase 9B — Deterministic tests and continuous integration

**Status: Complete**

Completed work includes:

- reproducible pytest, Ruff, and Coverage development dependencies;
- deterministic compact-publication loader tests independent of ignored local data;
- checksum, download, decompression, cleanup, cache, and failure-path coverage;
- 100% statement and branch coverage for `src/apps/deployment_data.py`;
- Python 3.12 GitHub Actions CI for pushes and pull requests;
- tracked-Python compilation, automated tests, targeted Ruff checks, dependency checks,
  tracked-file size checks, and forbidden-artifact checks;
- successful CI validation using Node.js 24-compatible GitHub Actions.

The current deterministic baseline is 30 passing tests.

## Phase 9C — Public deployment verification and monitoring

**Status: Complete**

The repository now includes `scripts/verify_public_deployment.py`, which validates:

- the final application hostname after redirects;
- the public Streamlit application shell;
- blocking, authentication, sleep, and visible error markers;
- a same-host Streamlit JavaScript asset;
- asset response status and minimum content size;
- direct-server or Community Cloud health diagnostics;
- human-readable and JSON output;
- nonzero failure exit behavior.

Eight deterministic tests cover the verifier’s primary success and failure paths.
The live deployment passed verification on July 21, 2026.

The separate public deployment health workflow runs daily at 13:17 UTC and
supports manual execution. Its first manual production run, GitHub Actions run
`29868630162`, completed successfully against commit
`c6f8bafbe280e5d7583da2ba119f5051083f89bb`.

## Phase 9D — Explorer regression coverage

**Status: Complete**

The repository now includes a deterministic Streamlit `AppTest` backed by a
synthetic temporary DuckDB fixture. The test runs without private datasets,
ignored production databases, or Milestone 5 and Milestone 6 CSV files.

The regression test verifies:

- the application starts successfully with the safe compact fixture;
- the recruiter-facing homepage and default Official Rankings page render;
- Enhanced Balanced Production is selected and labeled as the official model;
- all required top-level navigation destinations remain available;
- Endpoint 90+ remains selectable while sparse Endpoint 95+ remains hidden;
- missing 2020 Outdoor handling remains explicit;
- inbound-transfer development remains explicitly unavailable;
- the default all-time combined ranking table renders without exceptions.

The first Phase 9D CI validation, GitHub Actions run `29869694068`, completed
successfully against commit
`4e362d02cfaf200a71c1e88c7c10938716d59995`.

## Phase 9E — Deployment contract consistency

**Status: Complete**

The repository now includes deterministic tests that treat
`deployment/public_deployment_v1.json` as the canonical public deployment
contract and verify consistency across:

- compact-publication loader checksums and database filename;
- GitHub release tag, page, and asset URL;
- release publication script paths and immutable v1 configuration;
- Streamlit secrets example and deployment documentation;
- compressed and uncompressed artifact sizes;
- release notes and README publication metadata;
- Python version, Streamlit entrypoint, and referenced configuration paths.

The first Phase 9E CI validation, GitHub Actions run `29870082072`, completed
successfully against commit
`4e842d904781f9cb82810d817b30e7ada6cfac45`.

## Phase 9F — Guarded release automation

**Status: Complete**

The repository now includes guarded, dry-run-first tooling for preparing
future semantic-version releases without modifying the immutable
`public-deployment-v1` release.

The release preparation workflow:

- validates semantic release versions and rejects reused versions;
- blocks reuse of `public-deployment-v1`;
- blocks `v1.0.0` until an explicit final-release gate is supplied;
- calculates compressed and uncompressed artifact hashes and sizes;
- validates all 81 published resource tables;
- confirms 2,918,594 source and deployment rows;
- requires source-to-deployment parity to pass;
- starts the explorer against the exact decompressed artifact;
- generates reproducible JSON metadata and Markdown release notes;
- refuses to overwrite an existing package, tag, or GitHub release;
- performs no publishing unless `--publish` is supplied explicitly.

The `v0.9.0` dry run completed without creating a tag or GitHub Release.
GitHub Actions run `29870894706` passed against commit
`ec9fec366e2495cc22919f0884acf3e0de9e5d7e`.

## Phase 9G — Performance, accessibility, and user experience

**Status: Complete**

The production explorer received a measured runtime, caching, presentation,
and practical accessibility review.

Findings:

- cold startup, warm rerun, memory use, and default-page query behavior were measured;
- the compact DuckDB and lazy cached loaders remain appropriate for production;
- no additional query refactor was justified by the measured results;
- tables use responsive full-width layouts, hidden indexes, and readable formatting;
- charts include explicit axis labels and informative tooltips;
- primary controls include understandable labels, help text, or formatting;
- all major pages passed desktop and approximately 390-pixel viewport review;
- wide tables scroll horizontally without breaking the page;
- keyboard navigation using Tab, Shift+Tab, Enter, and Space remained usable;
- focus indicators, alerts, text, tables, and chart labels remained readable.

The visual review was completed against the live public Streamlit explorer.

## Phase 9H — Portfolio and career package

**Status: Complete**

Recruiter-facing materials now include:

- a concise project case study;
- Mermaid system, deployment, and analytical data-flow visuals;
- a three-to-five-minute demo and recording guide;
- technical and nontechnical project summaries;
- defensible résumé bullets;
- LinkedIn and portfolio descriptions;
- graduate-school application language;
- 30-second and two-minute interview explanations;
- STAR-format examples covering identity resolution, event fairness, and
  production deployment;
- a safe screenshot capture guide with three required application views.

All written claims preserve the frozen project metrics and explicitly avoid
causal, traffic, adoption, revenue, or accuracy claims that the evidence does
not support.

The remaining Phase 9H task is to capture and review the three current public
application screenshots listed in `docs/portfolio/SCREENSHOT_GUIDE.md`.

## Milestone 9 acceptance checklist

### Repository safety

- [ ] `main` is synchronized with `origin/main`.
- [ ] The working tree is clean at the final release point.
- [ ] `public-deployment-v1` still resolves to its original frozen commit.
- [ ] No secrets, raw data, processed data, databases, caches, temporary
      downloads, or large release assets are tracked.
- [ ] Generated tooling caches are explicitly ignored.
- [ ] Stale files are removed only after usage and documentation references are
      verified.

### Automated testing and CI

- [x] A focused GitHub Actions workflow runs without private datasets or local
      production databases.
- [x] CI uses Python 3.12.
- [x] All tracked production Python files pass syntax compilation.
- [x] Deterministic unit tests cover the compact-publication loader.
- [x] Streamlit smoke tests use safe fixtures or controlled mocks.
- [x] Deployment-descriptor and documentation consistency checks pass.
- [x] Secret-pattern and oversized-file checks pass.
- [x] The CI workflow is fast enough for normal pull requests and pushes.

### Explorer regression coverage

- [x] The application starts with a safe compact database fixture.
- [x] The default recruiter-facing page renders without exceptions.
- [x] Enhanced Balanced Production is identified as the official model.
- [x] Required navigation destinations remain available.
- [x] Endpoint 90+ and Endpoint 95+ wording remains correct.
- [x] Missing 2020 Outdoor handling remains explicit.
- [x] Unavailable inbound-transfer handling remains explicit.
- [x] Loader cache, checksum, download, and failure behavior are tested.
- [x] Runtime has no dependency on ignored Milestone 5 or Milestone 6 CSV files.

### Release automation

- [x] Future release tooling uses a new semantic version and cannot overwrite
      an existing release.
- [x] Artifact hashes and sizes are calculated and recorded.
- [x] Source-to-deployment table and row parity are validated.
- [x] Release metadata and notes can be generated reproducibly.
- [x] The application can be verified against the exact release artifact.
- [x] The process prevents accidental secret or oversized-file commits.
- [x] No `v1.0.0` tag or release is created before all acceptance gates pass.

### Performance, accessibility, and user experience

- [x] Startup, warm-load, memory, and expensive-query behavior are reviewed.
- [x] Caching behavior is documented and regression-tested where practical.
- [x] Major pages are reviewed at desktop and narrow viewport widths.
- [x] Navigation and table presentation are understandable to a first-time
      visitor.
- [x] Chart labels and interpretation language are clear.
- [x] Contrast and keyboard accessibility receive a practical review.
- [x] Every change is supported by a documented finding.

### Portfolio package

- [x] A concise case study is available.
- [x] Architecture and data-flow visuals are available.
- [x] Selected application screenshots are current and safe to publish.
- [x] A short demo script and walkthrough-recording guide are available.
- [x] Technical and nontechnical summaries are accurate.
- [x] Engineering challenges, solutions, methodology, and limitations are
      documented.
- [x] Public links are prominent and correct.

### Career materials

- [x] Résumé bullets are accurate and defensible.
- [x] LinkedIn and portfolio descriptions are complete.
- [x] Graduate-school application language is complete.
- [x] Interview talking points include a 30-second and two-minute explanation.
- [x] STAR-format project examples are documented.
- [x] No claims exaggerate causality, accuracy, traffic, adoption, or business
      impact.

### Final recruiter test and release

- [ ] A new visitor can understand the project from the README.
- [ ] The live application opens from the prominent project link.
- [ ] The official model and companion models are understandable.
- [ ] Rankings, trends, methodology, and limitations are discoverable.
- [ ] Technical scale, architecture, testing, and reproducibility are visible.
- [ ] Individual technical contributions are clearly stated.
- [ ] Portfolio and résumé language is easy to locate.
- [ ] All automated and manual release gates pass.
- [ ] The final release commit is clean, synchronized, and documented.
- [ ] Only then may a new `v1.0.0` tag and GitHub Release be considered.

## Completion rule

Milestone 9 is complete only when every applicable acceptance item is either
passed or explicitly documented as not applicable with a defensible reason.

Creating a `v1.0.0` tag is a final release action, not evidence by itself that
the milestone is complete.
