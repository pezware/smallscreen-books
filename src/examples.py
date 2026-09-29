"""Picks two example sentences from Tatoeba for every headword (stage 3).

Tatoeba (CC BY 2.0 FR) is the only source of examples (docs/plan.md): a
sentence with no source is never invented, and an entry Tatoeba cannot fill is
reported, not padded. The Spanish export ships every sentence with its id and
its contributor, which the licence asks us to credit:

    curl -O https://downloads.tatoeba.org/exports/per_language/spa/spa_sentences_detailed.tsv.bz2
    bunzip2 spa_sentences_detailed.tsv.bz2      # into data/es/raw/, gitignored

A good example is short, uses the headword, and is written in words the
learner can look up in this book. So a candidate must contain one of the
entry's own forms, matched with its accents (`qué` is not `que`, `hacia` is not
`hacía`), and candidates are ranked by how many of their words the book lacks,
then by length. A sentence is used once in the whole book, and the entries with
the fewest candidates choose first, so a rare word is not left with nothing
because a common one took its only sentence.

Picking only fills: an entry that already has two examples keeps them, so a
reviewed example survives a newer Tatoeba export.

    pick    fill every entry's missing examples in data/es/words.jsonl, and
            write data/es/examples.source.json for the attribution page
    choose  apply a reviewer's sheet of chosen Tatoeba ids per entry; the
            entry records `examples_reviewed_by`, and `pick` never refills it
    report  write build/examples-report.tsv: entries short of two examples,
            and examples that use a word the book lacks or run long
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import validate

EXAMPLES = 2
MIN_WORDS = 4
MAX_WORDS = 10
# Two examples under a 90-character definition keep most entries on one
# screen at the default font size; a longer sentence pushes the second example
# onto a continuation page, which is accepted but not sought.
MAX_CHARS = 70
# A sentence may use this many words the book lacks, as a fallback when no
# sentence keeps entirely to the book's words. Such examples are reported.
MAX_UNKNOWN = 1
# Looser limits, used only for an entry the strict ones leave short: news
# vocabulary (comicio, vocero) rarely appears in short Tatoeba sentences. A
# long sentence always ranks below every short one.
LONG_WORDS = 16
LONG_CHARS = 110
LONG_UNKNOWN = 2
# Two examples sharing more than this share of their words teach one thing.
MAX_OVERLAP = 0.5

_DIGIT = re.compile(r"\d")

TATOEBA_EXPORT = (
    "https://downloads.tatoeba.org/exports/per_language/spa/"
    "spa_sentences_detailed.tsv.bz2"
)

LICENCE = {
    "name": "Tatoeba",
    "url": "https://tatoeba.org",
    "licence": "CC BY 2.0 FR",
    "licence_url": "https://creativecommons.org/licenses/by/2.0/fr/",
    "attribution": (
        "Example sentences from Tatoeba (tatoeba.org), by the contributors named below."
    ),
    "changes": (
        "Selected, not modified: two short sentences per word, chosen for "
        "using words this book defines."
    ),
    "material": TATOEBA_EXPORT,
}


@dataclass(frozen=True)
class Sentence:
    id: int
    text: str
    by: str
    # Tokens as written, case-folded with accents kept: for matching a form.
    tokens: tuple[str, ...]
    # Tokens normalised as the validator does: for the vocabulary check.
    words: tuple[str, ...]


def _fold(word: str) -> str:
    return unicodedata.normalize("NFC", word).casefold()


def parse_line(line: str) -> Sentence | None:
    """One row of the export, or None when it cannot be a good example.

    Rows are `id, lang, text, username, added, modified`. A sentence without a
    contributor is skipped, because the licence asks for one to be credited.
    """
    cells = line.rstrip("\n").split("\t")
    if len(cells) < 4 or cells[1] != "spa":
        return None
    sid, _, text, by = cells[:4]
    text = " ".join(text.split())
    if by in ("", "\\N") or not sid.isdigit() or _DIGIT.search(text):
        return None
    if len(text) > LONG_CHARS:
        return None
    raw = validate._WORD.findall(validate._composed(text))
    if not MIN_WORDS <= len(raw) <= LONG_WORDS:
        return None
    return Sentence(
        id=int(sid),
        text=text,
        by=by,
        tokens=tuple(_fold(w) for w in raw),
        words=tuple(validate.normalise(w) for w in raw),
    )


def read_sentences(path: Path) -> list[Sentence]:
    """Usable sentences, one per wording: the lowest id wins a duplicate."""
    best: dict[tuple[str, ...], Sentence] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            sentence = parse_line(line)
            if sentence is None:
                continue
            key = sentence.words
            if key not in best or sentence.id < best[key].id:
                best[key] = sentence
    return sorted(best.values(), key=lambda s: s.id)


def unknown_words(sentence: Sentence, known: set[str]) -> int:
    return sum(w not in known for w in sentence.words)


def is_long(sentence: Sentence) -> bool:
    return len(sentence.words) > MAX_WORDS or len(sentence.text) > MAX_CHARS


def overlap(a: Sentence, b: Sentence) -> float:
    x, y = set(a.words), set(b.words)
    return len(x & y) / min(len(x), len(y))


def candidates(
    entries: list[dict], sentences: list[Sentence], known: set[str]
) -> dict[str, list[tuple[Sentence, str]]]:
    """Each entry's usable sentences, best first, with the form each one uses.

    Best is a sentence within the strict limits, then fewest words the book
    lacks, then shortest, then lowest id, so the choice is the same on every
    run.
    """
    owner: dict[str, str] = {}
    for entry in entries:
        for form in (entry["lemma"], *entry["forms"]):
            owner.setdefault(_fold(form), entry["lemma"])
    found: dict[str, list[tuple[int, int, int, int, Sentence, str]]] = {
        e["lemma"]: [] for e in entries
    }
    for sentence in sentences:
        unknown = unknown_words(sentence, known)
        if unknown > LONG_UNKNOWN:
            continue
        long = is_long(sentence) or unknown > MAX_UNKNOWN
        matched: dict[str, str] = {}
        for token in sentence.tokens:
            lemma = owner.get(token)
            if lemma is not None:
                matched.setdefault(lemma, token)
        for lemma, form in matched.items():
            found[lemma].append(
                (int(long), unknown, len(sentence.text), sentence.id, sentence, form)
            )
    return {
        lemma: [(s, form) for *_, s, form in sorted(rows, key=lambda r: r[:4])]
        for lemma, rows in found.items()
    }


def pick(
    entries: list[dict], sentences: list[Sentence], known: set[str]
) -> dict[str, list[Sentence]]:
    """Choose examples for every entry that has fewer than EXAMPLES.

    Entries with the fewest candidates choose first, and a sentence already in
    the book (as another entry's example) is never used again. The second
    example prefers a different form of the word and must not repeat the first.
    """
    pool = candidates(entries, sentences, known)
    used = {
        ref["id"]
        for e in entries
        for ref in e.get("source", {}).get("examples", [])
        if isinstance(ref, dict)
    }
    todo = [
        e
        for e in entries
        if len(e.get("examples", [])) < EXAMPLES and not e.get("examples_reviewed_by")
    ]
    todo.sort(key=lambda e: (len(pool[e["lemma"]]), e["rank"]))
    chosen: dict[str, list[Sentence]] = {}
    for entry in todo:
        free = [(s, f) for s, f in pool[entry["lemma"]] if s.id not in used]
        picked = _choose(free, EXAMPLES - len(entry.get("examples", [])), known)
        used.update(s.id for s in picked)
        chosen[entry["lemma"]] = picked
    return chosen


def _choose(
    free: list[tuple[Sentence, str]], wanted: int, known: set[str]
) -> list[Sentence]:
    """The best sentence, then the best one that does not repeat it.

    For the second, a sentence showing another form of the word wins over one
    showing the same form, as long as it uses no more words the book lacks.
    """
    if not free or wanted <= 0:
        return []
    first, first_form = free[0]
    if wanted == 1:
        return [first]
    rest = [(s, f) for s, f in free[1:] if overlap(s, first) <= MAX_OVERLAP]
    if not rest:
        return [first]
    best, _ = rest[0]
    other_form = next(
        (
            s
            for s, f in rest
            if f != first_form and unknown_words(s, known) <= unknown_words(best, known)
        ),
        None,
    )
    return [first, other_form or best]


def apply(entries: list[dict], chosen: dict[str, list[Sentence]]) -> list[dict]:
    """Add the chosen sentences to their entries, with their provenance."""
    out = []
    for entry in entries:
        new = chosen.get(entry["lemma"], [])
        if not new:
            out.append(entry)
            continue
        source = dict(entry.get("source", {}))
        source["examples"] = [*source.get("examples", [])] + [
            {"id": s.id, "by": s.by} for s in new
        ]
        out.append(
            {
                **entry,
                "examples": [*entry.get("examples", [])] + [s.text for s in new],
                "source": source,
            }
        )
    return out


def read_choices(path: Path) -> dict[str, list[int]]:
    """A reviewer's sheet: `lemma<TAB>id,id<TAB>note`, ids best first.

    An empty id cell means no candidate shows the word's sense: the entry keeps
    no example rather than a wrong one.
    """
    choices = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        cells = line.split("\t")
        ids = [c.strip() for c in cells[1].split(",")] if len(cells) > 1 else []
        if not all(i.isdigit() for i in ids if i):
            raise ValueError(f"{path}:{number}: ids must be numbers: {cells[1]!r}")
        choices[cells[0]] = [int(i) for i in ids if i][:EXAMPLES]
    return choices


def choose(
    entries: list[dict],
    choices: dict[str, list[int]],
    by_id: dict[int, Sentence],
    reviewer: str,
) -> tuple[list[dict], list[str]]:
    """Set each chosen entry's examples to the reviewer's sentences.

    Returns the entries and the problems (an unknown lemma or id), which leave
    that entry as it was.
    """
    lemmas = {e["lemma"] for e in entries}
    problems = [f"{k}: not in words.jsonl" for k in choices if k not in lemmas]
    out = []
    for entry in entries:
        ids = choices.get(entry["lemma"])
        if ids is None:
            out.append(entry)
            continue
        missing = [i for i in ids if i not in by_id]
        if missing:
            problems.append(f"{entry['lemma']}: no usable sentence {missing}")
            out.append(entry)
            continue
        source = {**entry.get("source", {})}
        source["examples"] = [{"id": i, "by": by_id[i].by} for i in ids]
        out.append(
            {
                **entry,
                "examples": [by_id[i].text for i in ids],
                "source": source,
                "examples_reviewed_by": reviewer,
            }
        )
    return out, problems


def contributors(entries: list[dict]) -> list[str]:
    names = {
        ref["by"]
        for e in entries
        for ref in e.get("source", {}).get("examples", [])
        if isinstance(ref, dict)
    }
    return sorted(names, key=str.casefold)


def write_source(path: Path, entries: list[dict], export: Path) -> None:
    """Provenance for the examples, and the Tatoeba block of the credits page."""
    digest = hashlib.sha256(export.read_bytes()).hexdigest() if export.exists() else ""
    data = {
        "source": {**LICENCE, "contributors": contributors(entries)},
        "inputs": {export.name: digest},
        "sentences": sum(len(e.get("examples", [])) for e in entries),
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def report(entries: list[dict], known: set[str]) -> list[tuple[str, str, str]]:
    """(lemma, problem, detail) for every entry a reviewer should look at."""
    rows = []
    for entry in entries:
        examples = entry.get("examples", [])
        if len(examples) < EXAMPLES:
            rows.append((entry["lemma"], f"{len(examples)} of {EXAMPLES}", ""))
        for text in examples:
            lacking = sorted(validate.unknown_words(text, known))
            if lacking:
                rows.append(
                    (entry["lemma"], "word not in the book", ", ".join(lacking))
                )
            words = validate._WORD.findall(validate._composed(text))
            if len(words) > MAX_WORDS or len(text) > MAX_CHARS:
                rows.append((entry["lemma"], "long example", text))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["pick", "choose", "report"])
    parser.add_argument("sheet", nargs="?", type=Path, help="choose: the sheet")
    parser.add_argument(
        "--reviewer", default="human", help="choose: recorded as examples_reviewed_by"
    )
    parser.add_argument("--data", type=Path, default=Path("data/es"))
    parser.add_argument(
        "--tatoeba",
        type=Path,
        default=Path("data/es/raw/spa_sentences_detailed.tsv"),
    )
    parser.add_argument(
        "--report", type=Path, default=Path("build/examples-report.tsv")
    )
    args = parser.parse_args(argv)

    import definitions

    words_path = args.data / "words.jsonl"
    entries = definitions.read_jsonl(words_path)
    known = validate.load_headword_forms(args.data / "headwords.jsonl")

    if args.step in ("pick", "choose"):
        if not args.tatoeba.exists():
            parser.error(f"missing {args.tatoeba}; see the module docstring")
        sentences = read_sentences(args.tatoeba)
        if args.step == "pick":
            chosen = pick(entries, sentences, known)
            entries = apply(entries, chosen)
            added = sum(len(v) for v in chosen.values())
            print(f"{added} examples added from {len(sentences)} usable sentences")
        else:
            if args.sheet is None:
                parser.error("choose needs the sheet")
            by_id = {s.id: s for s in sentences}
            entries, problems = choose(
                entries, read_choices(args.sheet), by_id, args.reviewer
            )
            for problem in problems:
                print(problem, file=sys.stderr)
            print(f"{len(read_choices(args.sheet)) - len(problems)} entries chosen")
        definitions.write_jsonl(words_path, entries)
        write_source(args.data / "examples.source.json", entries, args.tatoeba)

    rows = report(entries, known)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        "# lemma\tproblem\tdetail\n" + "".join("\t".join(r) + "\n" for r in rows),
        encoding="utf-8",
    )
    full = sum(len(e.get("examples", [])) >= EXAMPLES for e in entries)
    short = sum(len(e.get("examples", [])) < EXAMPLES for e in entries)
    print(
        f"{full}/{len(entries)} entries have {EXAMPLES} examples, {short} short; "
        f"{len(rows)} rows -> {args.report}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
