# Milestone 8 — Public Deployment and Recruiter Experience

## Status

**Complete — public deployment live**

Milestone 8 converts the local NCAA Division I Athlete Development Explorer
into a portable, recruiter-accessible web application.

The controlled Git merge, immutable GitHub Release, Streamlit Community
Cloud deployment, clean cloud-runtime validation, anonymous-browser smoke test,
and final URL documentation are complete.

**Live application:** https://ncaa-d1-track-analytics-pipeline-explorer.streamlit.app/

Enhanced Balanced Production remains the official primary model.

Original Balanced Production v4.1 remains a robustness companion. Average
Development remains a separate empirical-Bayes companion and is not presented
as the official ranking.

## Release candidate summary

| Measure | Validated result |
|---|---:|
| Public resource tables | 81 |
| Deployment metadata tables | 5 |
| Validated resource rows | 2,918,594 |
| Compact DuckDB size | 352,858,112 bytes |
| Compressed release asset | 236,994,168 bytes |
| Exact parity tables | 81 of 81 |
| Final regression validators | 7 of 7 passed |
| Recruiter-readiness score | 100 of 100 |
| Default-page maximum memory | 0.290 GiB |
| Heaviest tested view maximum memory | 1.684 GiB |
| Failed hard checks | 0 |

## Frozen source publications

Milestone 8 reads but does not modify:

```text
data/processed/milestone6/final_development_rankings_v1/
└── phase_6g_final_publication/
    └── final_development_rankings_v1.duckdb

data/processed/milestone7/seasonal_program_trends_v1/
├── phase_7d_final_publication/
│   └── seasonal_program_trends_v1.duckdb
└── phase_7e2_event_balanced_specialized_rankings/
    └── event_balanced_specialized_rankings_v2.duckdb
```

### Frozen source fingerprints

| Publication | Bytes | MiB | SHA-256 |
|---|---:|---:|---|
| Milestone 6 final | 245,379,072 | 234.012 | `ecbf2c754c9388f60e2373dbf9c260a07098e8a541a9663154bf96ba9de926da` |
| Milestone 7 trends | 132,395,008 | 126.262 | `b5551b43b91da489785b5ced07f548f2a725148d0520adbd11c97a589c105ba1` |
| Milestone 7 specialized | 58,994,688 | 56.262 | `353f5c1e328991566045e6edd4fc9551a9fe336e6f3b93e29ad94a45486a67a3` |

Every validation phase preserved these hashes.

## Phase 8A — Deployment preflight

**Status: Complete**

The preflight was run from:

```text
main commit 58e8a77
Python 3.12.13
Streamlit 1.59.1
DuckDB 1.5.4
pandas 3.0.3
Altair 6.2.2
```

### Initial application data surface

The local explorer registered:

- 47 required CSV resources;
- 1,347,512,603 CSV bytes;
- 14 Milestone 7 trend tables;
- 611,563 trend rows;
- 12 specialized analyses;
- 9 specialized physical result tables;
- approximately 1,538,902,299 bytes of direct runtime data.

The application also lacked one complete deployment dependency declaration and
did not yet support remote artifact retrieval, checksum validation, atomic
decompression, or a deployment cache.

### Initial runtime baseline

| Run | Time | Process RSS | Exceptions | Streamlit errors |
|---|---:|---:|---:|---:|
| Cold AppTest | 12.159 seconds | 819,200 KiB | 0 | 0 |
| Warm AppTest | 1.514 seconds | 1,477,360 KiB | 0 | 0 |

The benchmark reported:

```text
Maximum resident set size: 2,044,690,432 bytes
Peak memory footprint:    3,660,163,008 bytes
```

This established compact publication and lazy loading as release requirements.

### Explorer state improvement

The application dropdowns were converted to durable Streamlit session state.
Selections now persist while visitors move between schools and explorer
sections, and a visible reset-filter control restores the defaults.

## Phase 8B — Compact deployment publication

**Status: Complete**

Phase 8B mapped every application resource to an authoritative frozen source
and produced one versioned DuckDB publication.

### Publication contents

| Resource group | Tables |
|---|---:|
| Average Development core | 4 |
| Average Development seasonal broad | 8 |
| Average Development seasonal elite | 8 |
| Average Development supplemental | 8 |
| Official Event-Balanced publication | 19 |
| Specialized rankings | 20 |
| Program trends | 14 |
| **Total resource tables** | **81** |

Five additional metadata tables preserve the deployment contract, source
mapping, schemas, row counts, and checksums.

### Artifact

| Artifact | Bytes | MiB | SHA-256 |
|---|---:|---:|---|
| DuckDB publication | 352,858,112 | 336.512 | `7ab85809ab11b24ba98b0d5878f41242cfad53e1a1cbd4008dde36ec0f046de4` |
| Gzip release asset | 236,994,168 | 226.015 | `2a4aa9fd321dce96313d24cf532fbb8200d22847f6b6257138e0b49eed86432c` |

The compressed-to-uncompressed ratio is approximately `0.6716`.

### Exact parity contract

The publication passed:

- 81 of 81 exact table comparisons;
- 2,918,594 source resource rows;
- 2,918,594 deployment resource rows;
- zero source-minus-deployment rows;
- zero deployment-minus-source rows;
- exact agreement across all validated schemas;
- duplicate-preserving, bidirectional reconciliation;
- preservation of all three frozen source hashes.

The unavailable inbound-transfer analysis remained unavailable, and no 2020
Outdoor production data was fabricated.

## Phase 8C — Portable deployment loader

**Status: Complete**

The Streamlit application was migrated from direct CSV and source-database
access to `src/apps/deployment_data.py`.

### Loader contract

The loader contains:

- 47 static CSV-to-table mappings;
- 14 trend-table mappings;
- 20 specialized contract mappings;
- read-only DuckDB connections;
- schema-aware table access;
- environment-variable configuration;
- atomic remote download and decompression;
- compressed and uncompressed SHA-256 validation;
- deployment cache reuse.

Supported environment variables:

```text
NCAA_TRACK_PUBLIC_DB
NCAA_TRACK_PUBLIC_DB_SHA256
NCAA_TRACK_PUBLIC_DB_URL
NCAA_TRACK_PUBLIC_CACHE_DIR
NCAA_TRACK_PUBLIC_GZIP_SHA256
```

The primary requirements file now includes `duckdb==1.5.4`.

### Fresh-environment bootstrap

A clean destination successfully:

1. downloaded the artifact;
2. verified the compressed checksum;
3. decompressed atomically;
4. verified the database checksum;
5. queried representative tables;
6. removed all temporary download files.

Validated bootstrap result:

```text
Bootstrap time: 1.874 seconds
Downloaded bytes: 352,858,112
Temporary download files remaining: 0
```

The application no longer requires local Milestone 6 or Milestone 7 paths at
runtime.

## Phase 8D — Deployment package and recruiter experience

**Status: Complete**

### Deployment package

Milestone 8 created:

```text
.streamlit/config.toml
deployment/STREAMLIT_COMMUNITY_CLOUD.md
deployment/public_deployment_v1.json
deployment/github/public_deployment_v1_release_notes.md
deployment/github/publish_public_deployment_v1.sh
deployment/streamlit/secrets.toml.example
```

The guarded release script requires:

- the `main` branch;
- a clean working tree;
- an authenticated GitHub CLI;
- the expected gzip SHA-256;
- an absent local tag;
- an absent remote release.

It does not overwrite an existing tag or release.

### Recruiter-facing homepage

The first recruiter audit scored `50/100`. The final homepage added:

- visible project scale;
- a two-step suggested exploration path;
- a GitHub project link;
- explicit scope and limitations;
- clear Enhanced Balanced Production prominence;
- visible technical implementation context.

The final recruiter-readiness score is `100/100`, with zero AppTest exceptions,
errors, or warnings.

## Phase 8E — Runtime optimization and release readiness

**Status: Complete**

### Memory diagnosis

The first compact runtime profile occasionally exceeded the provisional
2.5 GiB memory budget. Five isolated runs confirmed that the issue was real:

```text
Median maximum RSS: 2.903 GiB
Maximum RSS:        3.077 GiB
Runs below 2.5 GiB: 2 of 5
```

Changing DataFrame caching from `st.cache_data` to `st.cache_resource` increased
memory and was rejected.

A loader-footprint audit identified the cause:

| Loaded resource | Deep DataFrame memory |
|---|---:|
| `athlete_model_points` | 627.495 MiB |
| `event_balanced_point_rows` | 93.337 MiB |
| All 13 eagerly loaded resources | 0.812 GiB |

The application was loading every point view to determine availability before a
visitor selected a view.

### Lazy point loading

The final implementation:

- checks view availability from distinct time metadata;
- queries only the chosen model and cohort;
- preserves the existing time-filter implementation;
- avoids materializing unrelated point tables;
- retains `st.cache_data`, which performed best in controlled testing.

Validated memory results:

| Scenario | Median maximum RSS | Maximum RSS |
|---|---:|---:|
| Default page | 0.289 GiB | 0.290 GiB |
| Athlete Contributions | 1.681 GiB | 1.684 GiB |
| Individual Event | 0.392 GiB | 0.393 GiB |

All nine scenario trials completed with zero exceptions, errors, or warnings.

### Final runtime profile

```text
Cold AppTest: 1.368 seconds
Warm AppTest: 0.097 seconds
Cold maximum RSS: 0.281 GiB
Warm-process maximum RSS: 0.290 GiB
```

### Full release-readiness audit

The final audit on July 21, 2026 passed all seven validators:

1. Phase 8B exact parity
2. Phase 8C loader migration
3. Phase 8C fresh bootstrap
4. Phase 8C compact runtime profile
5. Phase 8E lazy point loading
6. Phase 8D deployment package
7. Phase 8D recruiter homepage

Repository and security checks also passed:

- correct `milestone-8` branch;
- clean diff formatting;
- nothing staged;
- no tracked files above 95 MiB;
- generated deployment artifacts ignored;
- release tag absent;
- all production files present;
- no committed local secrets;
- no forbidden local paths;
- no secret-like values;
- frozen source hashes unchanged;
- compact publication hashes unchanged.

## Phase 8F — Documentation and controlled public release

**Status: Complete**

Phase 8F completed the controlled production release:

1. committed and merged Milestone 8 into `main`;
2. published the immutable `public-deployment-v1` GitHub Release;
3. uploaded and independently checksum-verified the compressed release asset;
4. independently checksum-verified the uncompressed compact DuckDB;
5. deployed the explorer through Streamlit Community Cloud using Python 3.12;
6. corrected legacy local-publication checks exposed by the clean cloud runtime;
7. validated startup using only the released compact DuckDB;
8. completed the public anonymous/incognito-browser production smoke test;
9. documented the validated public application URL.

**Validated public URL:** https://ncaa-d1-track-analytics-pipeline-explorer.streamlit.app/

## Deployment configuration

| Setting | Value |
|---|---|
| GitHub repository | `joeyn256/NCAA-Track-Analytics-Pipeline` |
| Deployment branch | `main` |
| Streamlit entrypoint | `src/apps/seasonal_development_explorer.py` |
| Python version | `3.12` |
| Live application | `https://ncaa-d1-track-analytics-pipeline-explorer.streamlit.app/` |
| Release tag | `public-deployment-v1` |
| Release asset | `ncaa_track_public_explorer_v1.duckdb.gz` |

Community Cloud secrets are supplied through Advanced settings from:

```text
deployment/streamlit/secrets.toml.example
```

`.streamlit/secrets.toml` must never be committed.

## Scope and interpretation

The public explorer preserves the frozen analytical contracts:

- Enhanced Balanced Production is the official model;
- Original Balanced Production v4.1 is a robustness companion;
- Average Development is a separate empirical-Bayes companion;
- 2020 Outdoor is not fabricated or interpolated;
- inbound transfer development remains explicitly unavailable;
- Endpoint 90+ is retained as the supported national elite-finisher analysis;
- Endpoint 95+ remains in the publication but hidden from the public explorer;
- rankings are observational development measures, not causal coaching
  estimates, championship projections, or recruiting guarantees.

## Completion criteria

**All completion criteria were satisfied on July 21, 2026.**

Milestone 8 is complete because:

- the implementation is committed and merged to `main`;
- the GitHub Release asset is published and checksum-verified;
- Streamlit Community Cloud deploys successfully;
- the public application passes the production smoke test;
- the live URL is documented;
- the final post-deployment repository state is clean and pushed.
