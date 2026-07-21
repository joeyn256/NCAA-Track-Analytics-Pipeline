from __future__ import annotations

from pathlib import Path
import struct


ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = ROOT / "docs" / "portfolio" / "screenshots"
PORTFOLIO_README = ROOT / "docs" / "portfolio" / "README.md"


def test_publishable_portfolio_screenshots() -> None:
    required = (
        "explorer_official_rankings.png",
        "explorer_program_trends.png",
    )
    readme = PORTFOLIO_README.read_text()

    for filename in required:
        path = SCREENSHOTS / filename
        assert path.is_file()
        assert path.stat().st_size <= 2 * 1024 * 1024

        data = path.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

        width, height = struct.unpack(">II", data[16:24])
        assert width >= 1200
        assert height >= 650
        assert f"screenshots/{filename}" in readme
