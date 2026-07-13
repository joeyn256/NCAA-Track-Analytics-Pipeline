import pandas as pd

import sys
from pathlib import Path

import random
import time


sys.path.append(
    str(Path(__file__).resolve().parents[1])
)


from config import RAW_FOLDER
from scraper.tfrrs_utils import get_page


ATHLETE_FILE = (
    RAW_FOLDER /
    "unique_athletes.csv"
)


OUTPUT_FOLDER = (
    RAW_FOLDER /
    "athlete_pages"
)


FAILED_FILE = (
    RAW_FOLDER /
    "failed_athletes_adaptive.csv"
)


OUTPUT_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


MAX_RETRIES = 3

REPORT_INTERVAL = 300  # 5 minutes


MIN_ALLOWED_DELAY = 0.10
MAX_ALLOWED_DELAY = 1.00


START_MIN_DELAY = 0.25
START_MAX_DELAY = 0.26

def format_duration(seconds):

    if seconds is None:
        return "Calculating..."

    seconds = max(
        0,
        int(seconds)
    )

    days, remainder = divmod(
        seconds,
        86400
    )

    hours, remainder = divmod(
        remainder,
        3600
    )

    minutes, seconds = divmod(
        remainder,
        60
    )

    parts = []

    if days:
        parts.append(
            f"{days}d"
        )

    if hours or days:
        parts.append(
            f"{hours}h"
        )

    if minutes or hours or days:
        parts.append(
            f"{minutes}m"
        )

    parts.append(
        f"{seconds}s"
    )

    return " ".join(parts)


def save_failed_athlete(
        athlete_id,
        athlete_name,
        athlete_url,
        error
):

    failed_record = pd.DataFrame(
        [
            {
                "athlete_id": athlete_id,
                "athlete_name": athlete_name,
                "athlete_url": athlete_url,
                "error": str(error)
            }
        ]
    )

    failed_record.to_csv(
        FAILED_FILE,
        mode="a",
        header=not FAILED_FILE.exists(),
        index=False
    )


def main():

    athletes = pd.read_csv(
        ATHLETE_FILE
    )

    total_athletes = len(
        athletes
    )

    existing_pages = {
        file.stem
        for file in OUTPUT_FOLDER.glob(
            "*.html"
        )
    }

    total_existing_at_start = sum(
        str(athlete_id) in existing_pages
        for athlete_id in athletes[
            "athlete_id"
        ]
    )

    total_pending = (
        total_athletes -
        total_existing_at_start
    )

    current_min_delay = (
        START_MIN_DELAY
    )

    current_max_delay = (
        START_MAX_DELAY
    )

    print(
        "ADAPTIVE PRODUCTION MODE"
    )

    print(
        f"Total athletes:      {total_athletes:,}"
    )

    print(
        f"Already downloaded:  {total_existing_at_start:,}"
    )

    print(
        f"Remaining downloads: {total_pending:,}"
    )

    print(
        f"Starting delay:      "
        f"{current_min_delay:.2f}–"
        f"{current_max_delay:.2f} seconds"
    )

    print(
        "Status and speed adjustments will occur "
        "every 5 minutes.\n",
        flush=True
    )

    run_start = time.time()

    window_start = run_start

    total_examined = 0
    total_attempted = 0
    total_saved = 0
    total_skipped = 0
    total_failed = 0

    total_request_attempts = 0
    total_request_errors = 0

    window_attempted = 0
    window_saved = 0
    window_failed = 0

    window_request_attempts = 0
    window_request_errors = 0

    for _, athlete in athletes.iterrows():

        total_examined += 1

        athlete_id = str(
            athlete["athlete_id"]
        )

        athlete_name = str(
            athlete["athlete_name"]
        )

        athlete_url = (
            "https://www.tfrrs.org/athletes/"
            f"{athlete_id}.html"
        )

        output_file = (
            OUTPUT_FOLDER /
            f"{athlete_id}.html"
        )

        if output_file.exists():

            total_skipped += 1

        else:

            total_attempted += 1
            window_attempted += 1

            success = False
            final_error = None

            for attempt in range(
                1,
                MAX_RETRIES + 1
            ):

                total_request_attempts += 1
                window_request_attempts += 1

                try:

                    html = get_page(
                        athlete_url
                    )

                    if not html.strip():

                        raise ValueError(
                            "Downloaded page was empty."
                        )

                    with open(
                        output_file,
                        "w",
                        encoding="utf-8"
                    ) as file:

                        file.write(
                            html
                        )

                    total_saved += 1
                    window_saved += 1

                    success = True

                    break

                except Exception as error:

                    final_error = error

                    total_request_errors += 1
                    window_request_errors += 1

                    if attempt < MAX_RETRIES:

                        retry_delay = (
                            random.uniform(
                                5,
                                10
                            )
                        )

                        time.sleep(
                            retry_delay
                        )

            if not success:

                total_failed += 1
                window_failed += 1

                save_failed_athlete(
                    athlete_id,
                    athlete_name,
                    athlete_url,
                    final_error
                )

            else:

                time.sleep(
                    random.uniform(
                        current_min_delay,
                        current_max_delay
                    )
                )

        current_time = time.time()

        if (
            current_time -
            window_start
            >= REPORT_INTERVAL
        ):

            window_elapsed = (
                current_time -
                window_start
            )

            total_elapsed = (
                current_time -
                run_start
            )

            window_speed = 0.0

            if window_elapsed > 0:

                window_speed = (
                    window_attempted /
                    (window_elapsed / 60)
                )

            overall_speed = 0.0

            if total_elapsed > 0:

                overall_speed = (
                    total_attempted /
                    (total_elapsed / 60)
                )

            if window_request_attempts > 0:

                request_error_rate = (
                    window_request_errors /
                    window_request_attempts
                )

            else:

                request_error_rate = 0.0

            remaining = max(
                0,
                total_pending -
                total_attempted
            )

            eta_seconds = None

            if overall_speed > 0:

                eta_seconds = (
                    remaining /
                    overall_speed
                ) * 60

            completion_percent = (
                total_examined /
                total_athletes *
                100
            )

            old_min_delay = (
                current_min_delay
            )

            old_max_delay = (
                current_max_delay
            )

            if (
                window_request_attempts == 0
            ):

                adjustment = (
                    "No new requests in this window"
                )

            elif request_error_rate == 0:

                current_min_delay = max(
                    MIN_ALLOWED_DELAY,
                    current_min_delay - 0.025
                )

                current_max_delay = max(
                    current_min_delay,
                    current_max_delay - 0.025
                )

                adjustment = (
                    "Zero errors: speeding up slightly"
                )

            elif request_error_rate < 0.005:

                adjustment = (
                    "Low error rate: maintaining speed"
                )

            elif request_error_rate < 0.02:

                current_min_delay = min(
                    MAX_ALLOWED_DELAY,
                    current_min_delay + 0.10
                )

                current_max_delay = min(
                    MAX_ALLOWED_DELAY,
                    current_max_delay + 0.10
                )

                adjustment = (
                    "Elevated errors: slowing down"
                )

            else:

                current_min_delay = min(
                    MAX_ALLOWED_DELAY,
                    current_min_delay + 0.25
                )

                current_max_delay = min(
                    MAX_ALLOWED_DELAY,
                    current_max_delay + 0.25
                )

                adjustment = (
                    "High error rate: slowing down "
                    "significantly"
                )

            print(
                "\n"
                "=================================================="
            )

            print(
                "5 MINUTE ADAPTIVE REPORT"
            )

            print(
                "=================================================="
            )

            print(
                f"Dataset progress:   "
                f"{total_examined:,} / "
                f"{total_athletes:,} "
                f"({completion_percent:.2f}%)"
            )

            print(
                f"Pages attempted:    {total_attempted:,}"
            )

            print(
                f"Pages saved:        {total_saved:,}"
            )

            print(
                f"Existing skipped:   {total_skipped:,}"
            )

            print(
                f"Permanent failures: {total_failed:,}"
            )

            print(
                "--------------------------------------------------"
            )

            print(
                f"Window attempted:   {window_attempted:,}"
            )

            print(
                f"Window saved:       {window_saved:,}"
            )

            print(
                f"Window failed:      {window_failed:,}"
            )

            print(
                f"Request attempts:   "
                f"{window_request_attempts:,}"
            )

            print(
                f"Request errors:     "
                f"{window_request_errors:,}"
            )

            print(
                f"Request error rate: "
                f"{request_error_rate * 100:.2f}%"
            )

            print(
                f"Window speed:       "
                f"{window_speed:.2f} pages/min"
            )

            print(
                f"Overall speed:      "
                f"{overall_speed:.2f} pages/min"
            )

            print(
                f"Remaining downloads:{remaining:>12,}"
            )

            print(
                f"Estimated time left: "
                f"{format_duration(eta_seconds)}"
            )

            print(
                f"Elapsed time:        "
                f"{format_duration(total_elapsed)}"
            )

            print(
                "--------------------------------------------------"
            )

            print(
                f"Previous delay:     "
                f"{old_min_delay:.3f}–"
                f"{old_max_delay:.3f}s"
            )

            print(
                f"Decision:           {adjustment}"
            )

            print(
                f"New delay:          "
                f"{current_min_delay:.3f}–"
                f"{current_max_delay:.3f}s"
            )
            time.sleep(
            random.uniform(
                1,2)
            )
            print('1 Second Refresh')

            print(
                "==================================================\n",
                flush=True
            )

            window_start = time.time()

            window_attempted = 0
            window_saved = 0
            window_failed = 0

            window_request_attempts = 0
            window_request_errors = 0

    total_elapsed = (
        time.time() -
        run_start
    )

    overall_error_rate = 0.0

    if total_request_attempts > 0:

        overall_error_rate = (
            total_request_errors /
            total_request_attempts
        )

    print(
        "\n"
        "=================================================="
    )

    print(
        "ADAPTIVE DOWNLOAD COMPLETE"
    )

    print(
        "=================================================="
    )

    print(
        f"Total athletes:       {total_athletes:,}"
    )

    print(
        f"Pages attempted:      {total_attempted:,}"
    )

    print(
        f"Pages saved:          {total_saved:,}"
    )

    print(
        f"Existing skipped:     {total_skipped:,}"
    )

    print(
        f"Permanent failures:   {total_failed:,}"
    )

    print(
        f"Request attempts:     {total_request_attempts:,}"
    )

    print(
        f"Request errors:       {total_request_errors:,}"
    )

    print(
        f"Overall error rate:   "
        f"{overall_error_rate * 100:.2f}%"
    )

    print(
        f"Final delay:          "
        f"{current_min_delay:.3f}–"
        f"{current_max_delay:.3f}s"
    )

    print(
        f"Total runtime:        "
        f"{format_duration(total_elapsed)}"
    )

    print(
        "=================================================="
    )


if __name__ == "__main__":
    main()