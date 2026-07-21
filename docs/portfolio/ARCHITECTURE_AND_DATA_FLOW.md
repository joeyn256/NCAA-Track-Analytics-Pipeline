# Architecture and Data Flow

## System architecture

```mermaid
flowchart LR
    A[TFRRS team and athlete pages] --> B[Python collection layer]
    B --> C[Raw HTML and parsed CSV chunks]
    C --> D[DuckDB raw and core schemas]
    D --> E[Canonical athlete identity]
    E --> F[Chronological D1 school stints]
    F --> G[Performance scaling and stable levels]
    G --> H[Observed minus expected development]
    H --> I[Enhanced Balanced Production]
    H --> J[Original Balanced Production v4.1]
    H --> K[Average Athlete Development]
    I --> L[Seasonal trends and comparisons]
    J --> L
    K --> L
    L --> M[Compact public DuckDB]
    M --> N[Portable checksum-verified loader]
    N --> O[Streamlit explorer]
    O --> P[Public user experience]
```

## Deployment architecture

```mermaid
flowchart TD
    A[GitHub repository] --> B[GitHub Actions CI]
    B --> C[Compilation, Ruff, pytest, coverage]
    B --> D[Secret and oversized-file guards]
    E[Immutable GitHub Release] --> F[Compressed public DuckDB]
    F --> G[Streamlit Community Cloud]
    G --> H[Download when cache is absent]
    H --> I[Verify gzip SHA-256]
    I --> J[Decompress atomically]
    J --> K[Verify DuckDB SHA-256]
    K --> L[Read-only DuckDB connection]
    L --> M[Lazy cached page queries]
    M --> N[Rankings, trends, compare, diagnostics]
    O[Daily GitHub Actions health check] --> G
    P[Guarded semantic release tooling] --> E
```

## Analytical data flow

```mermaid
flowchart TD
    A[6,594,540 standardized performances] --> B[Eligibility and event taxonomy]
    B --> C[Canonical-person performance deduplication]
    C --> D[6,376,667 canonical performances]
    D --> E[Athlete × school × event stable levels]
    E --> F[Observed development trajectories]
    F --> G[Cross-fitted expected improvement]
    G --> H[Observed minus expected value added]
    H --> I[Support reliability]
    I --> J[Equal positive event budgets]
    J --> K[Bounded negative event pools]
    K --> L[School development-production rankings]
    H --> M[Empirical-Bayes average development]
    L --> N[Seasonal and specialized analyses]
    M --> N
    N --> O[2,918,594-row public publication]
```

## Primary components

| Layer | Main responsibility | Representative technology |
|---|---|---|
| Collection | Retrieve rosters, profiles, meets, and results | Python, Requests, BeautifulSoup |
| Parsing | Normalize source pages into resumable chunks | Python, Pandas |
| Storage | Maintain relational and analytical data | DuckDB |
| Identity | Resolve people, duplicates, teams, and school stints | SQL, Python |
| Modeling | Estimate observed and expected development | Pandas, NumPy, scikit-learn |
| Publication | Freeze rankings, audits, and metadata | DuckDB, CSV |
| Application | Interactive public exploration | Streamlit, Altair |
| Quality | Test logic, deployment, and documentation contracts | pytest, Ruff, Coverage |
| Operations | CI, health checks, immutable releases | GitHub Actions, GitHub Releases |

## Design principles

1. Preserve source-to-output provenance.
2. Resolve identity and school ownership before modeling.
3. Keep missing data explicit.
4. Separate the official production model from companion views.
5. Treat rankings as observational estimates.
6. Use immutable, checksum-verified deployment artifacts.
7. Test production behavior using safe synthetic fixtures.
8. Prefer dry-run-first release processes.
