from pathlib import Path
from collections import Counter, defaultdict
import csv
import json
import os


PROJECT_ROOT = Path(
    "/Users/joeyn256/Projects/NCAA Track Analytics Pipeline"
)

TARGETS = {
    "raw": PROJECT_ROOT / "data/raw",
    "performance_chunks": (
        PROJECT_ROOT / "data/processed/performance_chunks"
    ),
    "chunk_status": (
        PROJECT_ROOT
        / "data/processed/parser_checkpoints/chunk_status"
    ),
}


def relative_path(path: Path) -> str:
    """Return a project-relative path for readable reports."""
    return str(path.relative_to(PROJECT_ROOT))


def format_size(size_bytes: int) -> str:
    """Convert a byte count to a readable size."""
    value = float(size_bytes)

    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:,.2f} {unit}"
        value /= 1024

    raise RuntimeError("Unable to format file size.")


def main() -> None:
    csv_schemas = defaultdict(
        lambda: {
            "count": 0,
            "bytes": 0,
            "roots": Counter(),
            "examples": [],
        }
    )

    json_schemas = defaultdict(
        lambda: {
            "count": 0,
            "bytes": 0,
            "roots": Counter(),
            "examples": [],
        }
    )

    errors = []

    print("MILESTONE 3 INPUT PREFLIGHT")
    print("=" * 80)
    print(f"Project root: {PROJECT_ROOT}")
    print(
        "Inspection mode: file metadata, CSV/TSV headers, "
        "and JSON top-level keys"
    )
    print("No DuckDB database or table is created.")

    for label, target in TARGETS.items():
        print()
        print(f"[{label}] {relative_path(target)}")

        if not target.exists():
            print("MISSING")
            continue

        suffix_counts = Counter()
        parent_counts = Counter()

        total_bytes = 0
        file_count = 0
        largest_files = []

        for directory, _, filenames in os.walk(target):
            parent = Path(directory)

            for filename in filenames:
                path = parent / filename

                try:
                    size_bytes = path.stat().st_size
                except OSError as exc:
                    errors.append(
                        f"{relative_path(path)}: stat failed: {exc}"
                    )
                    continue

                suffix = path.suffix.lower() or "<none>"

                file_count += 1
                total_bytes += size_bytes

                suffix_counts[suffix] += 1
                parent_counts[relative_path(path.parent)] += 1
                largest_files.append(
                    (size_bytes, relative_path(path))
                )

                if suffix in {".csv", ".tsv"}:
                    delimiter = "\t" if suffix == ".tsv" else ","

                    try:
                        with path.open(
                            "r",
                            encoding="utf-8-sig",
                            errors="replace",
                            newline="",
                        ) as handle:
                            reader = csv.reader(
                                handle,
                                delimiter=delimiter,
                            )
                            header = tuple(next(reader, []))

                        schema_key = (delimiter, header)
                        group = csv_schemas[schema_key]

                        group["count"] += 1
                        group["bytes"] += size_bytes
                        group["roots"][label] += 1

                        if len(group["examples"]) < 5:
                            group["examples"].append(
                                relative_path(path)
                            )

                    except (OSError, csv.Error) as exc:
                        errors.append(
                            f"{relative_path(path)}: "
                            f"CSV header error: {exc}"
                        )

                elif suffix == ".json":
                    try:
                        with path.open(
                            "r",
                            encoding="utf-8-sig",
                            errors="replace",
                        ) as handle:
                            value = json.load(handle)

                        if isinstance(value, dict):
                            keys = tuple(
                                sorted(str(key) for key in value)
                            )
                        else:
                            keys = (
                                f"<top-level:{type(value).__name__}>",
                            )

                        group = json_schemas[keys]

                        group["count"] += 1
                        group["bytes"] += size_bytes
                        group["roots"][label] += 1

                        if len(group["examples"]) < 5:
                            group["examples"].append(
                                relative_path(path)
                            )

                    except (OSError, json.JSONDecodeError) as exc:
                        errors.append(
                            f"{relative_path(path)}: "
                            f"JSON error: {exc}"
                        )

        print(f"Files: {file_count:,}")
        print(
            f"Size: {total_bytes:,} bytes "
            f"({format_size(total_bytes)})"
        )

        print("Extensions:")
        for suffix, count in sorted(
            suffix_counts.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            print(f"  {suffix}: {count:,}")

        print("Ten largest files:")
        for size_bytes, path in sorted(
            largest_files,
            reverse=True,
        )[:10]:
            print(
                f"  {format_size(size_bytes):>12}  {path}"
            )

        print("Largest file-containing directories:")
        for parent, count in parent_counts.most_common(15):
            print(f"  {count:>8,} files  {parent}")

    print()
    print("CSV/TSV HEADER SCHEMAS")
    print("=" * 80)

    sorted_csv_schemas = sorted(
        csv_schemas.items(),
        key=lambda item: -item[1]["count"],
    )

    if not sorted_csv_schemas:
        print("No CSV or TSV files found.")

    for number, ((delimiter, header), group) in enumerate(
        sorted_csv_schemas,
        start=1,
    ):
        displayed_delimiter = (
            "\\t" if delimiter == "\t" else delimiter
        )

        roots = ", ".join(
            f"{name}={count:,}"
            for name, count in sorted(group["roots"].items())
        )

        print()
        print(f"Schema {number}")
        print(f"Files: {group['count']:,}")
        print(
            f"Size: {group['bytes']:,} bytes "
            f"({format_size(group['bytes'])})"
        )
        print(f"Delimiter: {displayed_delimiter!r}")
        print(f"Roots: {roots}")
        print(f"Columns ({len(header)}):")

        for position, column in enumerate(header, start=1):
            print(f"  {position:>2}. {column!r}")

        print("Examples:")
        for example in group["examples"]:
            print(f"  {example}")

    print()
    print("JSON TOP-LEVEL SCHEMAS")
    print("=" * 80)

    sorted_json_schemas = sorted(
        json_schemas.items(),
        key=lambda item: -item[1]["count"],
    )

    if not sorted_json_schemas:
        print("No JSON files found.")

    for number, (keys, group) in enumerate(
        sorted_json_schemas,
        start=1,
    ):
        roots = ", ".join(
            f"{name}={count:,}"
            for name, count in sorted(group["roots"].items())
        )

        print()
        print(f"Schema {number}")
        print(f"Files: {group['count']:,}")
        print(
            f"Size: {group['bytes']:,} bytes "
            f"({format_size(group['bytes'])})"
        )
        print(f"Roots: {roots}")
        print("Keys/type:")

        for key in keys:
            print(f"  {key}")

        print("Examples:")
        for example in group["examples"]:
            print(f"  {example}")

    print()
    print("ERRORS")
    print("=" * 80)

    if errors:
        for error in errors:
            print(error)
    else:
        print("None")

    print()
    print("No DuckDB database or table was created.")


if __name__ == "__main__":
    main()
