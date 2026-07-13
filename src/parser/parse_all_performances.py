import argparse
import math
import os
import sys
import time
from pathlib import Path

import pandas as pd


SRC_FOLDER = (
    Path(__file__)
    .resolve()
    .parents[1]
)

sys.path.insert(
    0,
    str(SRC_FOLDER)
)


from config import RAW_FOLDER
from parser.parse_performances import (
    ATHLETE_PAGES_FOLDER,
    parse_athlete_page
)
from parser.performance_schema import (
    PERFORMANCE_COLUMNS,
    prepare_performance
)


PROCESSED_FOLDER = (
    RAW_FOLDER.parent /
    "processed"
)


PERFORMANCE_CHUNKS_FOLDER = (
    PROCESSED_FOLDER /
    "performance_chunks"
)


CHECKPOINT_FOLDER = (
    PROCESSED_FOLDER /
    "parser_checkpoints"
)

ATHLETE_MANIFEST_FILE = (
    RAW_FOLDER /
    "unique_athletes.csv"
)


CHUNK_STATUS_FOLDER = (
    CHECKPOINT_FOLDER /
    "chunk_status"
)


PERFORMANCE_CHUNKS_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


CHUNK_STATUS_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


CHUNK_SIZE = 1000


STATUS_COLUMNS = [
    "chunk_number",
    "athlete_id",
    "source_file",
    "status",
    "performance_rows",
    "error_type",
    "error_message"
]


def parse_arguments():

    parser = argparse.ArgumentParser(
        description=(
            "Parse locally stored TFRRS athlete "
            "HTML pages into performance chunks."
        )
    )

    parser.add_argument(
        "--start-chunk",
        type=int,
        default=1,
        help=(
            "One-based chunk number at which "
            "processing should begin."
        )
    )

    parser.add_argument(
        "--max-chunks",
        type=int,
        default=None,
        help=(
            "Maximum number of chunks to process "
            "during this run."
        )
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Reprocess chunks that already have "
            "complete output files."
        )
    )

    return parser.parse_args()


def athlete_file_sort_key(
        input_file
):

    athlete_id = input_file.stem

    if athlete_id.isdigit():

        return (
            0,
            int(athlete_id)
        )

    return (
        1,
        athlete_id
    )


def format_duration(
        total_seconds
):

    total_seconds = int(
        total_seconds
    )

    hours, remainder = divmod(
        total_seconds,
        3600
    )

    minutes, seconds = divmod(
        remainder,
        60
    )

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{seconds:02d}"
    )


def atomic_write_csv(
        dataframe,
        output_file
):

    temporary_file = output_file.with_name(
        output_file.name +
        ".tmp"
    )

    dataframe.to_csv(
        temporary_file,
        index=False
    )

    os.replace(
        temporary_file,
        output_file
    )


def remove_partial_chunk_files(
        performance_file,
        status_file
):

    files_to_remove = [
        performance_file,
        status_file,
        performance_file.with_name(
            performance_file.name +
            ".tmp"
        ),
        status_file.with_name(
            status_file.name +
            ".tmp"
        )
    ]

    for file_path in files_to_remove:

        if file_path.exists():

            file_path.unlink()


def chunk_output_files(
        chunk_number
):

    performance_file = (
        PERFORMANCE_CHUNKS_FOLDER /
        (
            f"performances_"
            f"{chunk_number:05d}.csv"
        )
    )

    status_file = (
        CHUNK_STATUS_FOLDER /
        (
            f"status_"
            f"{chunk_number:05d}.csv"
        )
    )

    return (
        performance_file,
        status_file
    )


def chunk_is_complete(
        performance_file,
        status_file
):

    return (
        performance_file.exists()
        and status_file.exists()
    )


def process_chunk(
        chunk_number,
        athlete_files
):

    chunk_start_time = time.time()

    performance_records = []
    status_records = []

    athlete_count = len(
        athlete_files
    )

    print(
        "\n"
        f"Starting chunk {chunk_number:05d}: "
        f"{athlete_count:,} athlete pages"
    )

    for athlete_index, input_file in enumerate(
        athlete_files,
        start=1
    ):

        if (
            athlete_index == 1
            or athlete_index % 100 == 0
            or athlete_index == athlete_count
        ):

            print(
                f"  Chunk {chunk_number:05d}: "
                f"{athlete_index:,}/"
                f"{athlete_count:,} pages"
            )

        athlete_id = input_file.stem

        try:

            html = input_file.read_text(
                encoding="utf-8",
                errors="replace"
            )

            performances = parse_athlete_page(
                athlete_id,
                html,
                source_file=input_file.name
            )

            if performances:

                prepared_performances = [
                    prepare_performance(
                        performance
                    )
                    for performance in performances
                ]

                performance_records.extend(
                    prepared_performances
                )

                status = "parsed"
                performance_count = len(
                    prepared_performances
                )

            else:

                status = "empty"
                performance_count = 0

            status_records.append(
                {
                    "chunk_number":
                        chunk_number,
                    "athlete_id":
                        athlete_id,
                    "source_file":
                        input_file.name,
                    "status":
                        status,
                    "performance_rows":
                        performance_count,
                    "error_type":
                        "",
                    "error_message":
                        ""
                }
            )

        except Exception as error:

            status_records.append(
                {
                    "chunk_number":
                        chunk_number,
                    "athlete_id":
                        athlete_id,
                    "source_file":
                        input_file.name,
                    "status":
                        "failed",
                    "performance_rows":
                        0,
                    "error_type":
                        type(error).__name__,
                    "error_message":
                        str(error)[:1000]
                }
            )

    performances_df = pd.DataFrame(
        performance_records,
        columns=PERFORMANCE_COLUMNS
    )

    status_df = pd.DataFrame(
        status_records,
        columns=STATUS_COLUMNS
    )

    performance_file, status_file = (
        chunk_output_files(
            chunk_number
        )
    )

    atomic_write_csv(
        performances_df,
        performance_file
    )

    atomic_write_csv(
        status_df,
        status_file
    )

    parsed_count = int(
        (
            status_df["status"]
            == "parsed"
        ).sum()
    )

    empty_count = int(
        (
            status_df["status"]
            == "empty"
        ).sum()
    )

    failed_count = int(
        (
            status_df["status"]
            == "failed"
        ).sum()
    )

    chunk_runtime = (
        time.time()
        -
        chunk_start_time
    )

    print(
        f"Completed chunk {chunk_number:05d}"
    )

    print(
        "  Parsed athletes:",
        f"{parsed_count:,}"
    )

    print(
        "  Empty athletes:",
        f"{empty_count:,}"
    )

    print(
        "  Failed athletes:",
        f"{failed_count:,}"
    )

    print(
        "  Performance rows:",
        f"{len(performances_df):,}"
    )

    print(
        "  Runtime:",
        format_duration(
            chunk_runtime
        )
    )

    print(
        "  Saved:",
        performance_file
    )

    return {
        "athlete_pages":
            athlete_count,
        "parsed_athletes":
            parsed_count,
        "empty_athletes":
            empty_count,
        "failed_athletes":
            failed_count,
        "performance_rows":
            len(performances_df),
        "runtime_seconds":
            chunk_runtime
    }


def main():

    arguments = parse_arguments()

    if not ATHLETE_MANIFEST_FILE.exists():

        raise FileNotFoundError(
            "Athlete manifest not found: "
            f"{ATHLETE_MANIFEST_FILE}"
        )


    athlete_manifest = pd.read_csv(
        ATHLETE_MANIFEST_FILE,
        dtype={
            "athlete_id": "string"
        }
    )


    if "athlete_id" not in athlete_manifest.columns:

        raise ValueError(
            "unique_athletes.csv does not contain "
            "an athlete_id column."
        )


    athlete_ids = (
        athlete_manifest[
            "athlete_id"
        ]
        .dropna()
        .astype(str)
        .str.strip()
    )


    athlete_ids = (
        athlete_ids[
            athlete_ids.ne("")
        ]
        .drop_duplicates()
        .tolist()
    )


    athlete_files = []

    missing_input_files = []


    for athlete_id in athlete_ids:

        input_file = (
            ATHLETE_PAGES_FOLDER /
            f"{athlete_id}.html"
        )

        if input_file.exists():

            athlete_files.append(
                input_file
            )

        else:

            missing_input_files.append(
                athlete_id
            )


    athlete_files = sorted(
        athlete_files,
        key=athlete_file_sort_key
    )


    if not athlete_files:

        raise FileNotFoundError(
            "No athlete HTML files listed in the "
            "manifest were found in "
            f"{ATHLETE_PAGES_FOLDER}"
        )

    total_athletes = len(
        athlete_files
    )

    total_chunks = math.ceil(
        total_athletes /
        CHUNK_SIZE
    )

    if arguments.start_chunk < 1:

        raise ValueError(
            "--start-chunk must be at least 1."
        )

    if arguments.start_chunk > total_chunks:

        raise ValueError(
            "--start-chunk is greater than the "
            "number of available chunks."
        )

    first_chunk = arguments.start_chunk

    if arguments.max_chunks is None:

        final_chunk = total_chunks

    else:

        if arguments.max_chunks < 1:

            raise ValueError(
                "--max-chunks must be at least 1."
            )

        final_chunk = min(
            total_chunks,
            first_chunk
            +
            arguments.max_chunks
            -
            1
        )


    print(
        "\nPRODUCTION PERFORMANCE PARSER"
    )  
    
     
    print(
        "Athletes in manifest:",
        f"{len(athlete_ids):,}"
    )


    print(
        "Missing athlete HTML pages:",
        f"{len(missing_input_files):,}"
    )


    if missing_input_files:

        print(
            "Missing athlete IDs:",
            ", ".join(
                missing_input_files[
                    :20
                ]
            )
        )

    print(
        "Athlete pages found:",
        f"{total_athletes:,}"
    )

    print(
        "Chunk size:",
        f"{CHUNK_SIZE:,}"
    )

    print(
        "Total chunks:",
        f"{total_chunks:,}"
    )

    print(
        "Run range:",
        (
            f"{first_chunk:,} "
            f"through "
            f"{final_chunk:,}"
        )
    )

    print(
        "Overwrite existing chunks:",
        arguments.overwrite
    )

    run_start_time = time.time()

    chunks_processed = 0
    chunks_skipped = 0
    total_pages_processed = 0
    total_parsed_athletes = 0
    total_empty_athletes = 0
    total_failed_athletes = 0
    total_performance_rows = 0

    for chunk_number in range(
        first_chunk,
        final_chunk + 1
    ):

        performance_file, status_file = (
            chunk_output_files(
                chunk_number
            )
        )

        complete = chunk_is_complete(
            performance_file,
            status_file
        )

        if (
            complete
            and not arguments.overwrite
        ):

            print(
                "\n"
                f"Chunk {chunk_number:05d} "
                "already complete. SKIP"
            )

            chunks_skipped += 1

            continue

        # Remove incomplete or overwritten output
        # before rebuilding the chunk.
        remove_partial_chunk_files(
            performance_file,
            status_file
        )

        start_index = (
            chunk_number - 1
        ) * CHUNK_SIZE

        end_index = min(
            start_index + CHUNK_SIZE,
            total_athletes
        )

        chunk_files = athlete_files[
            start_index:end_index
        ]

        result = process_chunk(
            chunk_number,
            chunk_files
        )

        chunks_processed += 1
        total_pages_processed += result[
            "athlete_pages"
        ]
        total_parsed_athletes += result[
            "parsed_athletes"
        ]
        total_empty_athletes += result[
            "empty_athletes"
        ]
        total_failed_athletes += result[
            "failed_athletes"
        ]
        total_performance_rows += result[
            "performance_rows"
        ]

        elapsed = (
            time.time()
            -
            run_start_time
        )

        completed_in_range = (
            chunk_number
            -
            first_chunk
            +
            1
        )

        total_in_range = (
            final_chunk
            -
            first_chunk
            +
            1
        )

        average_chunk_time = (
            elapsed /
            max(
                completed_in_range,
                1
            )
        )

        remaining_chunks = (
            total_in_range
            -
            completed_in_range
        )

        estimated_remaining = (
            average_chunk_time
            *
            remaining_chunks
        )

        print(
            "  Estimated run time remaining:",
            format_duration(
                estimated_remaining
            )
        )

    run_runtime = (
        time.time()
        -
        run_start_time
    )

    print(
        "\nPRODUCTION PARSER RUN COMPLETE"
    )

    print(
        "Chunks processed:",
        f"{chunks_processed:,}"
    )

    print(
        "Chunks skipped:",
        f"{chunks_skipped:,}"
    )

    print(
        "Athlete pages processed:",
        f"{total_pages_processed:,}"
    )

    print(
        "Parsed athletes:",
        f"{total_parsed_athletes:,}"
    )

    print(
        "Empty athletes:",
        f"{total_empty_athletes:,}"
    )

    print(
        "Failed athletes:",
        f"{total_failed_athletes:,}"
    )

    print(
        "Performance rows written:",
        f"{total_performance_rows:,}"
    )

    print(
        "Run time:",
        format_duration(
            run_runtime
        )
    )

    print(
        "\nPerformance chunks:"
    )

    print(
        PERFORMANCE_CHUNKS_FOLDER
    )

    print(
        "\nChunk status files:"
    )

    print(
        CHUNK_STATUS_FOLDER
    )


if __name__ == "__main__":
    main()