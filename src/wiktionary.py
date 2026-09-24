"""Extracts form-to-lemma pairs from Wiktionary, to check the LLM's lemmas.

Stage 1b maps every frequency-list form to a lemma with an LLM (docs/plan.md).
An LLM is consistent but not reliable, and a wrong lemma is expensive: it
decides which entry a definition is generated for. Wiktionary is the second
opinion.

Wiktionary is CC BY-SA, and share-alike would decide the book's outgoing
licence before Andy does (README). So its data is only ever read here, on the
machine that runs the check. The pairs this writes go to `data/**/raw/`, which
is gitignored, and nothing derived from them is committed except a human's
decision in the overrides file.

Input is the kaikki.org extract of English Wiktionary's Spanish entries, one
JSON object per line. The file is 1 GB, so it is streamed and filtered on the
way in rather than stored:

    python3 src/wiktionary.py --words data/es/raw/spa_news_2011_1M-words.txt

Two kinds of evidence give a pair:

  * a sense that is a form of another word (`dijo` is a form of `decir`), and
  * an entry that is a lemma in its own right (`casa`, noun).

Inflection tables are not read. Tables list forms the corpus never uses and
carry template noise, and a form that matters has its own form-of entry.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections.abc import Iterable, Iterator
from pathlib import Path

KAIKKI_URL = "https://kaikki.org/dictionary/Spanish/kaikki.org-dictionary-Spanish.jsonl"


def pairs(entry: dict) -> Iterator[tuple[str, str, str]]:
    """Yield (form, lemma, pos) for one Wiktionary entry, forms case-folded.

    A sense with `form_of` yields the form and each lemma it names. A sense
    without one is a lemma sense, and yields the word as its own lemma. An
    entry can hold both: `vino` is a noun and a form of `venir`.
    """
    word = entry.get("word", "")
    pos = entry.get("pos", "")
    if not word or " " in word:
        return
    form = word.casefold()
    seen: set[tuple[str, str]] = set()
    for sense in entry.get("senses", ()):
        targets = [t.get("word", "") for t in sense.get("form_of", ())]
        lemmas = [t for t in targets if t and " " not in t] if targets else [word]
        for lemma in lemmas:
            key = (lemma.casefold(), pos)
            if key not in seen:
                seen.add(key)
                yield form, key[0], pos


def extract(lines: Iterable[str], wanted: set[str]) -> Iterator[tuple[str, str, str]]:
    """Pairs for every entry whose form is in `wanted`, skipping bad lines."""
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("word", "").casefold() in wanted:
            yield from pairs(entry)


def corpus_forms(words_file: Path) -> set[str]:
    """Every case-folded form in a Leipzig word file, the filter for extract."""
    forms = set()
    with words_file.open(encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) == 3:
                forms.add(fields[1].casefold())
    return forms


def _lines(source: str) -> Iterator[str]:
    """Lines of a local JSONL file, or of the URL streamed without saving it."""
    if Path(source).exists():
        with Path(source).open(encoding="utf-8") as handle:
            yield from handle
        return
    with urllib.request.urlopen(source, timeout=60) as response:
        for raw in response:
            yield raw.decode("utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--words", type=Path, required=True, help="Leipzig words file")
    parser.add_argument("--source", default=KAIKKI_URL, help="URL or local JSONL path")
    parser.add_argument(
        "--out", type=Path, default=Path("data/es/raw/wiktionary-lemmas.tsv")
    )
    args = parser.parse_args(argv)

    wanted = corpus_forms(args.words)
    lines = _lines(args.source)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    partial = args.out.with_suffix(".partial")
    count = 0
    with partial.open("w", encoding="utf-8") as out:
        for form, lemma, pos in extract(lines, wanted):
            out.write(f"{form}\t{lemma}\t{pos}\n")
            count += 1
    # Renamed only when complete, so a dropped connection never leaves a
    # truncated table that looks finished.
    partial.replace(args.out)
    print(
        f"{count} pairs for {len(wanted)} corpus forms -> {args.out}", file=sys.stderr
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
