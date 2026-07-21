# NCAA Track Explorer — Public Deployment v1

This release publishes the compact, read-only data artifact used by the
NCAA Division I Athlete Development Explorer.

Enhanced Balanced Production is the official ranking model. Original Balanced
Production v4.1 and Average Development remain clearly labeled companion
products.

## Artifact

- File: `ncaa_track_public_explorer_v1.duckdb.gz`
- Compressed size: 236,994,168 bytes
- Uncompressed size: 352,858,112 bytes
- Compressed SHA-256: `2a4aa9fd321dce96313d24cf532fbb8200d22847f6b6257138e0b49eed86432c`
- Database SHA-256: `7ab85809ab11b24ba98b0d5878f41242cfad53e1a1cbd4008dde36ec0f046de4`

## Publication contents

- 81 resource tables
- 5 deployment metadata tables
- 2,918,594 validated resource rows
- Enhanced Balanced Production official rankings
- Original Balanced Production robustness companion outputs
- Average Development companion outputs
- seasonal trend and comparison tables
- specialized ranking publications

## Validation

The release candidate passed:

- exact source-to-deployment value parity for all 81 tables;
- 2,918,594 source rows and 2,918,594 deployment rows;
- bidirectional, duplicate-preserving reconciliation;
- frozen-source checksum preservation;
- fresh-environment download and atomic decompression;
- Streamlit AppTest with zero exceptions, errors, or warnings;
- 7 of 7 full release-readiness validators;
- visitor-readiness score of 100 out of 100;
- default-page maximum memory of 0.290 GiB;
- Athlete Contributions maximum memory of 1.684 GiB;
- Individual Event maximum memory of 0.393 GiB;
- cold AppTest startup of 1.368 seconds;
- warm AppTest rerun of 0.097 seconds;
- repository portability, security, and oversized-file gates.

## Scope notes

- 2020 Outdoor is not fabricated, interpolated, or carried forward.
- Inbound transfer development remains explicitly unavailable under the frozen
  publication contract.
- Endpoint 90+ is the supported national elite-finisher analysis.
- Rankings are observational athlete-development measures, not causal coaching
  estimates, championship projections, or recruiting guarantees.

Release page:
https://github.com/joeyn256/NCAA-Track-Analytics-Pipeline/releases/tag/public-deployment-v1
