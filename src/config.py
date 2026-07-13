from pathlib import Path
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


DATA_FOLDER = PROJECT_ROOT / "data"

RAW_FOLDER = DATA_FOLDER / "raw"

ROSTER_FOLDER = RAW_FOLDER / "rosters"

ATHLETE_FOLDER = RAW_FOLDER / "athlete_pages"

PERFORMANCE_FOLDER = RAW_FOLDER / "performances"

MEET_FOLDER = RAW_FOLDER / "meets"

SEASONS_FOLDER = RAW_FOLDER / "seasons"

SCHOOLS_FILE = RAW_FOLDER / "schools.csv"


SCHOOLS = pd.read_csv(
    SCHOOLS_FILE
).to_dict("records")


for folder in [
    ROSTER_FOLDER,
    ATHLETE_FOLDER,
    PERFORMANCE_FOLDER,
    MEET_FOLDER
]:
    folder.mkdir(
        parents=True,
        exist_ok=True
    )