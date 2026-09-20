"""Generates the passages the published fit measurements are taken over.

The numbers in docs/device-constraints.md are only evidence if someone else
can reproduce them, so the input is generated here from the committed
frequency list with a fixed seed rather than described in prose.

    python3 tools/fit/probe.py | ./build/fit/fit --size 16
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

SEED = 7
SAMPLES_PER_LENGTH = 40


def passages(frequency_list: Path, lengths: range, pool_size: int) -> list[str]:
    words = [
        w.strip()
        for w in frequency_list.read_text(encoding="utf-8").splitlines()
        if w.strip()
    ]
    # Definition vocabulary lives at the top of the list, so draw from there
    # rather than from the 3,000th word, which no definition would use.
    pool = words[:pool_size]
    rng = random.Random(SEED)
    out = []
    for target in lengths:
        for _ in range(SAMPLES_PER_LENGTH):
            text = ""
            while len(text) < target:
                text += (" " if text else "") + rng.choice(pool)
            out.append(text[:target].rstrip())
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--frequency-list", type=Path, default=Path("data/es/frequency.txt")
    )
    parser.add_argument("--min-chars", type=int, default=30)
    parser.add_argument("--max-chars", type=int, default=160)
    parser.add_argument("--step", type=int, default=5)
    parser.add_argument("--pool-size", type=int, default=1000)
    args = parser.parse_args()

    lengths = range(args.min_chars, args.max_chars + 1, args.step)
    for passage in passages(args.frequency_list, lengths, args.pool_size):
        print(passage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
