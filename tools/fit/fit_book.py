"""How many of the book's entries need a continuation page (stage 5).

Unpacks the built EPUB and runs every entry through `fit-entry`, which drives
the firmware's own parser and paginator (docs/device-constraints.md), at each
built-in font size and at the largest one with the widest margin. Fit is only
ever true for a stated size, so it reports one line per setting.

    mise run fit-entry                  # builds build/fit/fit-entry
    python3 tools/fit/fit_book.py       # after `mise run book`
"""

from __future__ import annotations

import argparse
import collections
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SETTINGS = [
    ["--size", "12"],
    ["--size", "14"],
    ["--size", "16"],
    ["--size", "18"],
    ["--size", "18", "--margin", "40"],
]


def pages(tool: Path, files: list[Path], args: list[str]) -> dict[str, int]:
    """Pages per entry file, as fit-entry counts them."""
    out = subprocess.run(
        [str(tool), *args, *map(str, files)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    counts = {}
    for line in out.splitlines():
        if line and not line.startswith("#"):
            count, path = line.split("\t", 1)
            counts[Path(path).name] = int(count)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--book", type=Path, default=Path("build/es-wordbook.epub"))
    parser.add_argument("--tool", type=Path, default=Path("build/fit/fit-entry"))
    args = parser.parse_args(argv)
    for path, hint in ((args.book, "mise run book"), (args.tool, "mise run fit-entry")):
        if not path.exists():
            parser.error(f"missing {path}; run `{hint}` first")

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(args.book) as book:
            book.extractall(tmp)
        files = sorted(Path(tmp).glob("OEBPS/entries/*.xhtml"))
        for setting in SETTINGS:
            counts = pages(args.tool, files, setting)
            spill = sorted(name for name, n in counts.items() if n > 1)
            tally = collections.Counter(counts.values())
            label = " ".join(setting)
            print(
                f"{label:22} {len(spill):4} of {len(counts)} entries need a "
                f"continuation page ({100 * len(spill) / len(counts):.1f}%); "
                + ", ".join(f"{n} pages: {c}" for n, c in sorted(tally.items()))
            )
            if 0 < len(spill) <= 5:
                print(f"{'':22} {', '.join(spill)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
