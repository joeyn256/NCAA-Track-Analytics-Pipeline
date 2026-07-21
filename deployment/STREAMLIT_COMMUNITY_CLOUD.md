# Streamlit Community Cloud deployment

## Readiness status

**Deployment complete.** The Milestone 8 release passed the full pre-release
audit, the immutable GitHub Release asset was published and checksum-verified,
the clean Streamlit runtime loaded the compact public DuckDB, and the
application passed its anonymous-browser production smoke test.

- Live application: `https://ncaa-d1-track-analytics-pipeline-explorer.streamlit.app/`
- Release tag: `public-deployment-v1`
- Public resource tables: 81
- Exact source-to-deployment table parity: 81 of 81
- Failed hard checks: 0

## Deployment target

- GitHub repository: `joeyn256/NCAA-Track-Analytics-Pipeline`
- Branch: `main`
- Entrypoint: `src/apps/seasonal_development_explorer.py`
- Python: `3.12`
- Live application: `https://ncaa-d1-track-analytics-pipeline-explorer.streamlit.app/`
- Release tag: `public-deployment-v1`
- Release asset: `ncaa_track_public_explorer_v1.duckdb.gz`
- Compressed asset size: `236,994,168 bytes`
- Uncompressed DuckDB size: `352,858,112 bytes`

## Completed deployment sequence

1. Completed the final pre-release documentation consistency gate.
2. Committed and merged Milestone 8 into `main`.
3. Published and verified release tag `public-deployment-v1`.
4. Uploaded and checksum-verified
   `ncaa_track_public_explorer_v1.duckdb.gz`.
5. Deployed the application from `main` using Python 3.12.
6. Added Community Cloud secrets through the deployment interface.
7. Validated clean startup using only the released compact DuckDB.
8. Completed the production smoke test and anonymous-browser access check.
9. Recorded the live URL in the repository documentation.

## Community Cloud secrets

Do not commit `.streamlit/secrets.toml`.

The Advanced settings secret values are:

```toml
NCAA_TRACK_PUBLIC_DB_URL = "https://github.com/joeyn256/NCAA-Track-Analytics-Pipeline/releases/download/public-deployment-v1/ncaa_track_public_explorer_v1.duckdb.gz"
NCAA_TRACK_PUBLIC_DB_SHA256 = "7ab85809ab11b24ba98b0d5878f41242cfad53e1a1cbd4008dde36ec0f046de4"
NCAA_TRACK_PUBLIC_GZIP_SHA256 = "2a4aa9fd321dce96313d24cf532fbb8200d22847f6b6257138e0b49eed86432c"
NCAA_TRACK_PUBLIC_CACHE_DIR = "/tmp/ncaa_track_analytics"
```

The committed example contains only the public release URL and publication
checksums. Actual Community Cloud values should still be entered through the
deployment interface rather than committed as `.streamlit/secrets.toml`.

## Loader behavior

When the configured DuckDB file is absent, the application:

1. downloads the gzip asset to a temporary file;
2. verifies the gzip SHA-256;
3. decompresses to a temporary DuckDB file;
4. verifies the database SHA-256;
5. atomically moves the verified database into the cache;
6. opens the publication in read-only mode;
7. reuses the cached database on later runs.

Partial downloads and temporary decompression files are removed on failure.

## Production smoke test

**Result: Passed on July 21, 2026.**

**Validated application:** `https://ncaa-d1-track-analytics-pipeline-explorer.streamlit.app/`

The public URL is acceptable only when all of the following pass:

- homepage loads without an exception or visible error;
- Enhanced Balanced Production is clearly identified as the official model;
- the scale metrics and GitHub link are visible;
- Official Rankings loads its default table;
- Athlete Contributions loads successfully;
- Individual Event loads successfully;
- Program Trends loads;
- Program Comparison loads;
- Average Development remains separately labeled;
- scope and limitation notes are visible;
- 2020 Outdoor is not presented as fabricated production data;
- inbound transfer development remains explicitly unavailable;
- filter selections persist across navigation;
- CSV download works for a representative ranking;
- page refresh reuses the cached artifact;
- the public application remains responsive during the test.

Record the final URL and smoke-test result in the Milestone 8 document.

## Failure handling

If release publication fails, do not bypass the checksum, branch, clean-tree, or
existing-release guards. Diagnose the failed guard before retrying.

If Community Cloud cannot retrieve or verify the artifact:

1. inspect the build and application logs;
2. confirm the release asset URL is public;
3. compare both configured checksums with
   `deployment/public_deployment_v1.json`;
4. confirm the cache directory is writable;
5. remove the failed app deployment or clear its cache before retrying.

Do not replace the immutable `public-deployment-v1` asset silently. A changed
artifact requires a new version, new checksums, and a new release tag.
