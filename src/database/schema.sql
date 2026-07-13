-- Milestone 3 relational schema for the NCAA Track Analytics Pipeline.
--
-- The build script will create raw-schema views because their source paths
-- depend on the local project location.
--
-- Large-table logical uniqueness is enforced by audit queries rather than
-- physical indexes:
--
--   core.athlete_affiliations
--   core.performances

CREATE SCHEMA raw;
CREATE SCHEMA core;
CREATE SCHEMA analytics;
CREATE SCHEMA audit;


-- ============================================================================
-- AUDIT TABLES
-- ============================================================================

CREATE TABLE audit.schema_versions (
    version_id VARCHAR PRIMARY KEY,
    milestone INTEGER NOT NULL,
    description VARCHAR NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duckdb_version VARCHAR NOT NULL
);


CREATE TABLE audit.build_runs (
    build_run_id VARCHAR PRIMARY KEY,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,

    status VARCHAR NOT NULL
        CHECK (
            status IN (
                'running',
                'pass',
                'fail'
            )
        ),

    project_root VARCHAR NOT NULL,
    database_path VARCHAR NOT NULL,
    python_version VARCHAR NOT NULL,
    duckdb_version VARCHAR NOT NULL,

    expected_performance_rows BIGINT NOT NULL,
    actual_performance_rows BIGINT,

    notes VARCHAR
);


CREATE TABLE audit.source_files (
    build_run_id VARCHAR NOT NULL,
    source_group VARCHAR NOT NULL,
    source_path VARCHAR NOT NULL,
    source_filename VARCHAR NOT NULL,

    file_size_bytes UBIGINT NOT NULL,
    modified_time_ns BIGINT,
    sha256 VARCHAR,
    row_count BIGINT,

    is_empty BOOLEAN NOT NULL,

    load_status VARCHAR NOT NULL
        CHECK (
            load_status IN (
                'registered',
                'loaded',
                'empty',
                'skipped',
                'failed'
            )
        ),

    error_message VARCHAR,

    PRIMARY KEY (
        build_run_id,
        source_path
    )
);


CREATE TABLE audit.table_counts (
    build_run_id VARCHAR NOT NULL,
    table_schema VARCHAR NOT NULL,
    table_name VARCHAR NOT NULL,

    actual_row_count BIGINT NOT NULL,
    expected_row_count BIGINT,

    passed BOOLEAN NOT NULL,

    recorded_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE audit.integrity_checks (
    build_run_id VARCHAR NOT NULL,
    check_name VARCHAR NOT NULL,

    severity VARCHAR NOT NULL
        CHECK (
            severity IN (
                'hard',
                'warning',
                'info'
            )
        ),

    actual_value VARCHAR,
    expected_value VARCHAR,

    passed BOOLEAN NOT NULL,
    details VARCHAR,

    checked_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE audit.roster_duplicate_groups (
    build_run_id VARCHAR NOT NULL,

    athlete_id VARCHAR NOT NULL,
    athlete_name VARCHAR,
    athlete_class VARCHAR,

    school_name VARCHAR,
    team_id VARCHAR NOT NULL,

    roster_season_label VARCHAR NOT NULL,
    config_hnd VARCHAR NOT NULL,

    source_occurrences INTEGER NOT NULL
        CHECK (
            source_occurrences >= 2
        ),

    duplicate_excess_rows INTEGER NOT NULL
        CHECK (
            duplicate_excess_rows >= 1
        )
);


CREATE TABLE audit.affiliation_coverage (
    build_run_id VARCHAR NOT NULL,
    match_class VARCHAR NOT NULL,

    distinct_performance_keys BIGINT NOT NULL,
    performance_rows BIGINT NOT NULL,

    recorded_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE audit.dimension_conflicts (
    build_run_id VARCHAR NOT NULL,

    dimension_name VARCHAR NOT NULL,
    business_key VARCHAR NOT NULL,
    attribute_name VARCHAR NOT NULL,

    distinct_value_count INTEGER NOT NULL,
    selected_value VARCHAR,
    details VARCHAR,

    recorded_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================================
-- CORE DIMENSIONS
-- ============================================================================

CREATE TABLE core.schools (
    -- Stable institution key derived by removing the gender component
    -- from a TFRRS team ID.
    school_id VARCHAR PRIMARY KEY,

    school_name VARCHAR NOT NULL,
    state VARCHAR,

    directory_team_count INTEGER NOT NULL
        CHECK (
            directory_team_count >= 0
        ),

    total_team_count INTEGER NOT NULL
        CHECK (
            total_team_count >= 1
        ),

    is_division_i_directory_school BOOLEAN NOT NULL,

    source_method VARCHAR NOT NULL
        CHECK (
            source_method IN (
                'directory',
                'performance_only',
                'mixed'
            )
        )
);


CREATE TABLE core.teams (
    -- Original TFRRS gender-specific team identifier.
    team_id VARCHAR PRIMARY KEY,

    -- Logical relation to core.schools.school_id.
    school_id VARCHAR NOT NULL,

    -- The source school_id from data/raw/schools.csv.
    -- Diagnostics showed that this identifies a directory row/team rather
    -- than an institution shared between men's and women's teams.
    source_school_id VARCHAR,

    team_name VARCHAR NOT NULL,

    gender_code VARCHAR NOT NULL
        CHECK (
            gender_code IN (
                'f',
                'm',
                'unknown'
            )
        ),

    division VARCHAR,
    sport VARCHAR,
    conference VARCHAR,
    state VARCHAR,

    slug VARCHAR,
    team_url VARCHAR,

    in_division_i_directory BOOLEAN NOT NULL,
    seen_in_rosters BOOLEAN NOT NULL,
    seen_in_performances BOOLEAN NOT NULL
);


CREATE TABLE core.athletes (
    athlete_id VARCHAR PRIMARY KEY,

    athlete_name VARCHAR,

    -- These are current-profile attributes only.
    -- They must never be used as historical affiliation assignments.
    current_school_name VARCHAR,
    current_team_id VARCHAR,

    athlete_url VARCHAR,

    has_parser_status BOOLEAN NOT NULL,
    has_performances BOOLEAN NOT NULL
);


CREATE TABLE core.seasons (
    -- Deterministic format:
    --
    --   2026_indoor
    --   2026_outdoor
    --   2025_cross_country
    season_id VARCHAR PRIMARY KEY,

    season_year INTEGER NOT NULL,

    season_type VARCHAR NOT NULL
        CHECK (
            season_type IN (
                'indoor',
                'outdoor',
                'cross_country'
            )
        ),

    -- Performance label such as "2026 Indoors".
    performance_season_label VARCHAR,

    -- Roster label such as "2025-2026 NCAA Indoor".
    roster_season_label VARCHAR,

    -- TFRRS historical-roster season configuration identifier.
    config_hnd VARCHAR,

    roster_start_year INTEGER,
    roster_end_year INTEGER,

    has_performance_data BOOLEAN NOT NULL,
    has_roster_data BOOLEAN NOT NULL,

    UNIQUE (
        season_year,
        season_type
    )
);


CREATE TABLE core.meets (
    meet_id VARCHAR PRIMARY KEY,

    -- Representative values selected deterministically during the build.
    -- Every original value remains preserved in core.performances.
    canonical_meet_name VARCHAR,
    canonical_meet_date_text VARCHAR,
    canonical_meet_url VARCHAR,

    meet_name_variant_count INTEGER NOT NULL
        CHECK (
            meet_name_variant_count >= 0
        ),

    meet_date_variant_count INTEGER NOT NULL
        CHECK (
            meet_date_variant_count >= 0
        ),

    meet_url_variant_count INTEGER NOT NULL
        CHECK (
            meet_url_variant_count >= 0
        ),

    performance_count BIGINT NOT NULL
        CHECK (
            performance_count >= 0
        )
);


CREATE TABLE core.events (
    -- Deterministic integer assigned by alphabetical raw event label.
    event_id INTEGER PRIMARY KEY,

    -- No Milestone 4 event normalization is applied.
    event_label VARCHAR NOT NULL UNIQUE,

    performance_count BIGINT NOT NULL
        CHECK (
            performance_count >= 0
        )
);


-- ============================================================================
-- CORE HISTORICAL AFFILIATIONS
-- ============================================================================

CREATE TABLE core.athlete_affiliations (
    -- Deterministic row number assigned during the build.
    -- Logical uniqueness is audited rather than physically indexed.
    affiliation_id BIGINT NOT NULL,

    athlete_id VARCHAR NOT NULL,
    team_id VARCHAR NOT NULL,
    season_id VARCHAR NOT NULL,

    config_hnd VARCHAR NOT NULL,
    roster_season_label VARCHAR NOT NULL,

    athlete_class VARCHAR,
    roster_athlete_name VARCHAR,
    roster_school_name VARCHAR,

    -- Number of identical rows in the raw roster aggregate.
    source_occurrences INTEGER NOT NULL
        CHECK (
            source_occurrences >= 1
        ),

    duplicate_excess_rows INTEGER NOT NULL
        CHECK (
            duplicate_excess_rows >= 0
        )
);


-- ============================================================================
-- CORE PERFORMANCE FACT TABLE
-- ============================================================================

CREATE TABLE core.performances (
    -- Must contain exactly 6,594,540 unique nonblank values.
    -- Logical uniqueness is enforced by the Milestone 3 audit.
    performance_id VARCHAR NOT NULL,

    athlete_id VARCHAR NOT NULL,

    -- Source-faithful athlete fields.
    athlete_name VARCHAR,
    athlete_class VARCHAR,

    -- Source-faithful school value from the performance record.
    school VARCHAR,

    -- Nullable: 479 source performance records have no team ID.
    team_id VARCHAR,

    season_id VARCHAR NOT NULL,
    season_year INTEGER NOT NULL,

    season_type VARCHAR NOT NULL
        CHECK (
            season_type IN (
                'indoor',
                'outdoor',
                'cross_country'
            )
        ),

    -- Original performance season label.
    season_label VARCHAR NOT NULL,

    meet_id VARCHAR NOT NULL,
    result_id VARCHAR,

    -- Original meet values remain preserved here.
    meet_name VARCHAR,
    meet_date_text VARCHAR NOT NULL,

    event_id INTEGER NOT NULL,

    -- Original event text.
    event VARCHAR NOT NULL,

    -- No Milestone 4 mark normalization is applied.
    mark VARCHAR NOT NULL,
    secondary_mark VARCHAR,
    wind VARCHAR,

    -- Original place-related fields.
    place VARCHAR,
    competition_round VARCHAR,
    raw_place VARCHAR,

    -- Original URLs.
    meet_url VARCHAR,
    result_url VARCHAR,

    highlighted VARCHAR,

    -- Nullable when no exact historical roster affiliation exists.
    affiliation_id BIGINT,

    -- Original athlete HTML source field from the parser.
    source_file VARCHAR,

    -- Performance chunk that physically supplied this row.
    source_chunk_file VARCHAR NOT NULL
);
