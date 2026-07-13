import hashlib


PERFORMANCE_COLUMNS = [
    "performance_id",
    "athlete_id",
    "athlete_name",
    "athlete_class",
    "school",
    "team_id",
    "season_year",
    "season_type",
    "season_label",
    "meet_id",
    "result_id",
    "meet_name",
    "meet_date_text",
    "event",
    "mark",
    "secondary_mark",
    "wind",
    "place",
    "competition_round",
    "raw_place",
    "meet_url",
    "result_url",
    "highlighted",
    "source_file"
]


PERFORMANCE_ID_FIELDS = [
    "athlete_id",
    "meet_id",
    "result_id",
    "result_url",
    "season_year",
    "season_type",
    "event",
    "mark",
    "secondary_mark",
    "wind",
    "place",
    "competition_round",
    "raw_place"
]


def normalize_id_value(value):

    if value is None:
        return ""

    return str(
        value
    ).strip()


def build_performance_id(
        performance
):

    canonical_values = [
        normalize_id_value(
            performance.get(
                field,
                ""
            )
        )
        for field in PERFORMANCE_ID_FIELDS
    ]

    canonical_text = "\x1f".join(
        canonical_values
    )

    full_hash = hashlib.sha256(
        canonical_text.encode(
            "utf-8"
        )
    ).hexdigest()

    # 32 hexadecimal characters provide a
    # deterministic 128-bit identifier.
    return full_hash[:32]


def prepare_performance(
        performance
):

    prepared = dict(
        performance
    )

    prepared["performance_id"] = (
        build_performance_id(
            prepared
        )
    )

    return {
        column: prepared.get(
            column,
            ""
        )
        for column in PERFORMANCE_COLUMNS
    }