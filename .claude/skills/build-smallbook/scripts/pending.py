"""Lists the agent provider's requests that still wait for an answer.

`SMALLSCREEN_LLM=agent` leaves one request file per LLM call under
`build/llm-exchange/requests/` and never deletes it, so after a few rounds the
directory mixes answered and open requests. This prints only the open ones,
grouped by system prompt, so whoever plays the model knows what to answer.

    python3 .claude/skills/build-smallbook/scripts/pending.py           # open requests
    python3 .claude/skills/build-smallbook/scripts/pending.py --check   # parse answers

`--check` reads each answer the way `src/llm.py` will and names any that is not
one JSON object, before a rerun trips over it.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

import llm  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--exchange",
        type=Path,
        default=Path(
            os.environ.get("SMALLSCREEN_LLM_EXCHANGE", str(llm.DEFAULT_EXCHANGE))
        ),
    )
    parser.add_argument(
        "--check", action="store_true", help="parse every answer file instead"
    )
    args = parser.parse_args(argv)

    if args.check:
        bad = 0
        answers = sorted((args.exchange / "answers").glob("*.json"))
        for path in answers:
            try:
                llm.parse_json_text(path.read_text(encoding="utf-8"))
            except llm.LLMError as error:
                bad += 1
                print(f"{path}: {error}")
        print(f"{len(answers) - bad} of {len(answers)} answers parse", file=sys.stderr)
        return 1 if bad else 0

    by_system: dict[str, list[Path]] = collections.defaultdict(list)
    for path in sorted((args.exchange / "requests").glob("*.json")):
        request = json.loads(path.read_text(encoding="utf-8"))
        if not Path(request["answer"]).exists():
            by_system[request["system"]].append(path)
    total = sum(len(paths) for paths in by_system.values())
    for system, paths in by_system.items():
        print(f"# system prompt: {system} ({len(paths)} open)")
        for path in paths:
            print(path)
    print(f"{total} requests wait for an answer", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
