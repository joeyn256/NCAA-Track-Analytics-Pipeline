# Streamlit Community Cloud deployment

## Readiness status

The Milestone 8 release candidate passed the full pre-release audit on
July 21, 2026:

- 7 of 7 regression validators passed;
- exact parity passed for all 81 resource tables;
- frozen-source and compact-publication hashes passed;
- recruiter-readiness scored 100 of 100;
- the default page peaked at 0.290 GiB;
- the heaviest tested point view peaked at 1.684 GiB;
- no secrets, local paths, oversized tracked files, tags, or releases were
  present.

The repository must still complete the controlled Git, GitHub Release,
Streamlit deployment, and public smoke-test sequence below.

## Deployment target

- GitHub repository: `joeyn256/NCAA-Track-Analytics-Pipeline`
- Branch: `main`
- Entrypoint: `src/apps/seasonal_development_explorer.py`
- Python: `3.12`
- Suggested app subdomain: `ncaa-track-development-explorer`
- Release tag: `public-deployment-v1`
- Release asset: `ncaa_track_public_explorer_v1.duckdb.gz`
- Compressed asset size: `236,994,168 bytes`
- Uncompressed DuckDB size: `352,858,112 bytes`

## Required sequence

1. Complete the final documentation consistency gate.
2. Commit the Milestone 8 implementation on `milestone-8`.
3. Push `milestone-8` and review the remote branch.
4. Merge the branch into `main`.
5. Confirm `main` is clean and pushed.
6. Run:

   ```zsh
   deployment/github/publish_public_deployment_v1.sh
   ```

7. Confirm the GitHub Release asset exists and matches:

   ```text
   Compressed SHA-256:
   2a4aa9fd321dce96313d24cf532fbb8200d22847f6b6257138e0b49eed86432c

   Uncompressed database SHA-256:
   7ab85809ab11b24ba98b0d5878f41242cfad53e1a1cbd4008dde36ec0f046de4
   ```

8. Confirm the asset opens at:

   `https://github.com/joeyn256/NCAA-Track-Analytics-Pipeline/releases/download/public-deployment-v1/ncaa_track_public_explorer_v1.duckdb.gz`

9. In Streamlit Community Cloud, create an app using:

   - Repository: `joeyn256/NCAA-Track-Analytics-Pipeline`
   - Branch: `main`
   - Main file path: `src/apps/seasonal_development_explorer.py`
   - Python version: `3.12`

10. Open **Advanced settings** and paste the contents of:

    `deployment/streamlit/secrets.toml.example`

11. Deploy and inspect the build logs.
12. Run the production smoke test against the public URL.
13. Add the validated public URL to:
    - `README.md`;
    - `milestones/milestone_08_public_deployment_and_recruiter_experience.md`.
14. Commit and push the final URL/documentation update.

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
