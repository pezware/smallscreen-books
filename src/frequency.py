"""Builds the frequency list that decides which words enter a wordbook.

The list has two jobs, and they pull in different directions:

  * it chooses the 3,000 entries the book will hold, and
  * it is the learner's assumed vocabulary, which `validate.py` checks every
    generated definition against.

Both jobs want common words and neither wants proper nouns, so a slot spent on
`Gadafi` is a slot lost twice over.

Input is a Leipzig Corpora Collection package (CC BY 4.0), which ships a
`-words.txt` of `id<TAB>form<TAB>count` and a `-sentences.txt` of
`id<TAB>sentence`:

    curl -O https://downloads.wortschatz-leipzig.de/corpora/spa_news_2011_1M.tar.gz
    tar xzf spa_news_2011_1M.tar.gz -C data/es/raw/

The word file is a token list, not a word list: it holds punctuation, digits
and every capitalisation separately, so `el` and sentence-initial `El` arrive
as two entries. This module folds case, drops non-words, removes proper nouns
and writes the survivors in frequency order — one form per line, so the line
number is the `rank` of the data contract in docs/plan.md.

Why capitalisation cannot decide a proper noun on its own: Spanish news writes
`Gobierno`, `Universidad` and `Congreso` inside institution names, so a form's
share of lowercase spellings runs from 0.51 (`gobierno`) down through 0.14
(`congreso`) and 0.10 (`republica`) into the genuinely proper `0.007`
(`espana`). Cutting anywhere above PROPER_NOUN_RATIO throws away real
vocabulary. The cut is deliberately low: it removes the unambiguous names and
leaves the argued middle in the book.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
from dataclasses import dataclass
from pathlib import Path

# A form is a word only when it is letters end to end. Same character class as
# validate._WORD: no digits, no underscore, accents kept.
_WORD_ONLY = re.compile(r"^[^\W\d_]+$", re.UNICODE)
_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)

DEFAULT_LIMIT = 3000

# Spanish's only one-letter words. Every other single letter in a news corpus
# is an initial, a list marker or a unit, and costs a slot in the book.
ONE_LETTER_WORDS = frozenset("aeouy")

# Misspellings the corpus carries as separate forms, mapped to the word they
# spell. News drops the accent in all-caps headlines, and `asi` is not a word.
VARIANTS = {"asi": "así"}

# English words and name fragments (`bin` of bin Laden) that rank as tokens.
# A language-identification rule would replace this list; see issue #6.
NOT_SPANISH = frozenset({"the", "of", "in", "bin"})

# Below this share of lowercase use, a form is a name rather than a word.
# See the module docstring for why the cut sits this low.
PROPER_NOUN_RATIO = 0.08

# Case is measured for more forms than the book needs, so that excluding a
# proper noun promotes the next word rather than shortening the list.
CANDIDATE_MULTIPLE = 2


@dataclass(frozen=True)
class Form:
    """One candidate word, with the evidence that placed or excluded it."""

    form: str
    count: int
    lowercase_uses: int
    capitalised_uses: int

    @property
    def lowercase_share(self) -> float:
        """Share of uses that are lowercase, ignoring sentence-initial capitals.

        1.0 when the corpus never shows the form mid-sentence at all, because
        absence of evidence must not read as evidence of a name.
        """
        total = self.lowercase_uses + self.capitalised_uses
        return self.lowercase_uses / total if total else 1.0

    def is_proper_noun(self, ratio: float = PROPER_NOUN_RATIO) -> bool:
        return self.lowercase_share < ratio


def count_words(words_file: Path) -> collections.Counter[str]:
    """Total the corpus token counts per case-folded form, words only.

    Single letters other than ONE_LETTER_WORDS, and NOT_SPANISH, are dropped
    here rather than later, so they never reach the ranking and never spend a
    slot. A VARIANTS misspelling adds its count to the word it spells.
    """
    counts: collections.Counter[str] = collections.Counter()
    with words_file.open(encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 3:
                continue
            _, form, count = fields
            if not _WORD_ONLY.match(form):
                continue
            folded = form.casefold()
            folded = VARIANTS.get(folded, folded)
            if len(folded) == 1 and folded not in ONE_LETTER_WORDS:
                continue
            if folded in NOT_SPANISH:
                continue
            counts[folded] += int(count)
    return counts


def count_case_uses(
    sentences_file: Path, candidates: set[str]
) -> tuple[collections.Counter[str], collections.Counter[str]]:
    """Count lowercase uses, and non-lowercase uses away from a sentence start.

    The first token of a sentence is skipped unless it is plain lowercase,
    because every word is capitalised there and the position carries no
    information about whether the form is a name.

    "Non-lowercase" rather than "initial capital": `iPhone` and `iPad` are
    neither, and counting only initial capitals left them with no evidence at
    all, which `Form.lowercase_share` then reads as a perfectly ordinary word.
    """
    lowercase: collections.Counter[str] = collections.Counter()
    capitalised: collections.Counter[str] = collections.Counter()
    with sentences_file.open(encoding="utf-8") as handle:
        for line in handle:
            _, _, sentence = line.partition("\t")
            for position, match in enumerate(_TOKEN.finditer(sentence)):
                token = match.group()
                folded = token.casefold()
                folded = VARIANTS.get(folded, folded)
                if folded not in candidates:
                    continue
                if token.islower():
                    lowercase[folded] += 1
                elif position > 0:
                    # Any token away from a sentence start that is not plain
                    # lowercase is evidence of a name: Espana, ONU, and the
                    # mixed case of iPhone and YouTube alike.
                    capitalised[folded] += 1
    return lowercase, capitalised


def rank_forms(words_file: Path, sentences_file: Path, limit: int) -> list[Form]:
    """Return candidate forms in frequency order, each carrying its case counts."""
    counts = count_words(words_file)
    candidates = [form for form, _ in counts.most_common(limit * CANDIDATE_MULTIPLE)]
    lowercase, capitalised = count_case_uses(sentences_file, set(candidates))
    return [
        Form(form, counts[form], lowercase[form], capitalised[form])
        for form in candidates
    ]


def select(
    forms: list[Form], limit: int, ratio: float = PROPER_NOUN_RATIO
) -> tuple[list[Form], list[Form]]:
    """Split ranked forms into the book's vocabulary and the names it drops."""
    kept: list[Form] = []
    excluded: list[Form] = []
    for form in forms:
        if len(kept) == limit:
            break
        (excluded if form.is_proper_noun(ratio) else kept).append(form)
    return kept, excluded


CORPUS_LICENCE = {
    "name": "Leipzig Corpora Collection",
    "url": "https://downloads.wortschatz-leipzig.de/corpora/",
    "licence": "CC BY 4.0",
    "attribution": (
        "D. Goldhahn, T. Eckart, U. Quasthoff: Building Large Monolingual "
        "Dictionaries at the Leipzig Corpora Collection, LREC 2012."
    ),
}


def _digest(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_list(path: Path, kept: list[Form]) -> None:
    """One surface form per line, so the line number is the entry's rank."""
    path.write_text("".join(f"{form.form}\n" for form in kept), encoding="utf-8")


def write_excluded(path: Path, excluded: list[Form]) -> None:
    """Record every dropped name with the evidence, so the cut stays reviewable."""
    lines = [
        f"{form.form}\t{form.count}\t{form.lowercase_share:.4f}\n" for form in excluded
    ]
    header = "# form\tcorpus count\tlowercase share\n"
    path.write_text(header + "".join(lines), encoding="utf-8")


def write_source(
    path: Path, corpus: str, inputs: list[Path], kept: int, excluded: int, ratio: float
) -> None:
    """Record provenance, because each built book carries a licence note."""
    path.write_text(
        json.dumps(
            {
                "corpus": corpus,
                "source": CORPUS_LICENCE,
                "inputs": {p.name: _digest(p) for p in inputs},
                "entries": kept,
                "excluded_proper_nouns": excluded,
                "proper_noun_ratio": ratio,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=Path("data/es/raw"),
        help="directory holding the unpacked Leipzig package",
    )
    parser.add_argument(
        "--corpus",
        default="spa_news_2011_1M",
        help="Leipzig package name, used as the input filename prefix",
    )
    parser.add_argument("--out", type=Path, default=Path("data/es/frequency.txt"))
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--proper-noun-ratio",
        type=float,
        default=PROPER_NOUN_RATIO,
        help="lowercase share below which a form counts as a name (0 keeps all)",
    )
    args = parser.parse_args(argv)

    words_file = args.corpus_dir / f"{args.corpus}-words.txt"
    sentences_file = args.corpus_dir / f"{args.corpus}-sentences.txt"
    for required in (words_file, sentences_file):
        if not required.exists():
            parser.error(f"missing corpus file: {required}")

    forms = rank_forms(words_file, sentences_file, args.limit)
    kept, excluded = select(forms, args.limit, args.proper_noun_ratio)
    if len(kept) < args.limit:
        parser.error(
            f"corpus yielded {len(kept)} words, fewer than the {args.limit} asked for"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_list(args.out, kept)
    write_excluded(args.out.with_suffix(".excluded.txt"), excluded)
    write_source(
        args.out.with_suffix(".source.json"),
        args.corpus,
        [words_file, sentences_file],
        len(kept),
        len(excluded),
        args.proper_noun_ratio,
    )
    print(
        f"{len(kept)} words written to {args.out}; "
        f"{len(excluded)} proper nouns excluded"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
