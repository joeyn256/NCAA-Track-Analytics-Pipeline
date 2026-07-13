import sys
from pathlib import Path


sys.path.append(
    str(Path(__file__).resolve().parents[2])
)


from scraper.tfrrs_utils import get_page


URL = "https://www.tfrrs.org/leagues/49.html"


html = get_page(URL)


with open(
    "directory_debug.html",
    "w",
    encoding="utf-8"
) as file:

    file.write(html)


print("Saved directory HTML")