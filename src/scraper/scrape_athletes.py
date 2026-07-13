import pandas as pd

import sys
from pathlib import Path

import random
import time


sys.path.append(
    str(Path(__file__).resolve().parents[1])
)


from config import RAW_FOLDER, SEASONS_FOLDER
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
    "failed_athletes.csv"
)


OUTPUT_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


MAX_RETRIES = 3

REPORT_INTERVAL = 300  # 5 minutes

MIN_DELAY = 0.25
MAX_DELAY = 0.35


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


def print_report(
        total_athletes,
        total_pending,
        total_examined,
        total_attempted,
        total_saved,
        total_skipped,
        total_failed,
        window_attempted,
        window_saved,
        window_failed,
        window_start,
        run_start
):

    current_time = time.time()

    window_elapsed = (
        current_time -
        window_start
    )

    total_elapsed = (
        current_time -
        run_start
    )

    window_rate = 0.0

    if window_elapsed > 0:

        window_rate = (
            window_attempted /
            (window_elapsed / 60)
        )

    overall_rate = 0.0

    if total_elapsed > 0:

        overall_rate = (
            total_attempted /
            (total_elapsed / 60)
        )

    remaining = max(
        0,
        total_pending -
        total_attempted
    )

    eta_seconds = None

    if overall_rate > 0:

        eta_seconds = (
            remaining /
            overall_rate
        ) * 60

    completion_percent = (
        total_examined /
        total_athletes *
        100
    )

    print(
        "\n"
        "=================================================="
    )

    print(
        "5 MINUTE PRODUCTION REPORT"
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
        f"Window speed:       "
        f"{window_rate:.2f} pages/min"
    )

    print(
        f"Overall speed:      "
        f"{overall_rate:.2f} pages/min"
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
        f"Fixed delay:         "
        f"{MIN_DELAY:.2f}–{MAX_DELAY:.2f}s"
    )

    print(
        "==================================================\n",
        flush=True
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

    print(
        "FIXED-DELAY PRODUCTION MODE"
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
        f"Delay range:         "
        f"{MIN_DELAY:.2f}–{MAX_DELAY:.2f} seconds"
    )

    print(
        "Status will print every 5 minutes.\n",
        flush=True
    )

    run_start = time.time()

    window_start = run_start

    total_examined = 0
    total_attempted = 0
    total_saved = 0
    total_skipped = 0
    total_failed = 0

    window_attempted = 0
    window_saved = 0
    window_failed = 0

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
                        MIN_DELAY,
                        MAX_DELAY
                    )
                )

        current_time = time.time()

        if (
            current_time -
            window_start
            >= REPORT_INTERVAL
        ):

            print_report(
                total_athletes=total_athletes,
                total_pending=total_pending,
                total_examined=total_examined,
                total_attempted=total_attempted,
                total_saved=total_saved,
                total_skipped=total_skipped,
                total_failed=total_failed,
                window_attempted=window_attempted,
                window_saved=window_saved,
                window_failed=window_failed,
                window_start=window_start,
                run_start=run_start
            )

            window_start = time.time()

            window_attempted = 0
            window_saved = 0
            window_failed = 0

    total_elapsed = (
        time.time() -
        run_start
    )

    print(
        "\n"
        "=================================================="
    )

    print(
        "FIXED-DELAY DOWNLOAD COMPLETE"
    )

    print(
        "=================================================="
    )

    print(
        f"Total athletes:      {total_athletes:,}"
    )

    print(
        f"Pages attempted:     {total_attempted:,}"
    )

    print(
        f"Pages saved:         {total_saved:,}"
    )

    print(
        f"Existing skipped:    {total_skipped:,}"
    )

    print(
        f"Permanent failures:  {total_failed:,}"
    )

    print(
        f"Total runtime:       "
        f"{format_duration(total_elapsed)}"
    )

    print(
        "=================================================="
    )

if __name__ == "__main__":
    main()