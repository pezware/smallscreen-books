"""Checks a generated definition before it is allowed into a wordbook.

The definitions come from an LLM, so they are consistent in register but not
guaranteed correct. These checks catch the failure mode that hurts a learner
most: a definition written in words they do not know yet, or one that explains
the word with the word itself.

Neither check proves a definition is true. Only review does that, and the
`checked` flag in the data file records it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# A definition longer than this spills the first screen on a 480x800 panel at
# the target font size, pushing the first example onto a continuation page.
MAX_DEFINITION_CHARS = 90

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def normalise(word: str) -> str:
    """Lowercase and strip accents, so 'Rápido' and 'rapido' compare equal."""
    folded = unicodedata.normalize("NFD", word.casefold())
    return "".join(c for c in folded if unicodedata.category(c) != "Mn")


def load_known_forms(path: Path | str) -> set[str]:
    """Read a frequency list into the vocabulary the checks compare against.

    One surface form per line, most frequent first, as written by
    `frequency.py`. The forms are normalised on the way in so that callers
    never have to remember to do it.
    """
    with open(path, encoding="utf-8") as handle:
        return {normalise(line.strip()) for line in handle if line.strip()}


def unknown_words(definition: str, known_forms: set[str]) -> set[str]:
    """Return the definition's words that fall outside the learner's vocabulary.

    `known_forms` holds normalised surface forms from the frequency list, not
    lemmas, so a conjugated verb only counts as known when that exact form
    appears in the list. The check therefore over-reports on inflected Spanish.
    """
    return {
        w
        for w in (normalise(m.group()) for m in _WORD.finditer(definition))
        if w not in known_forms
    }


def is_circular(definition: str, lemma: str) -> bool:
    """True when the definition explains the word with the word itself."""
    target = normalise(lemma)
    return any(normalise(m.group()) == target for m in _WORD.finditer(definition))


@dataclass
class Verdict:
    accepted: bool
    reason: str = ""


def accept_definition(entry: dict, known_forms: set[str]) -> Verdict:
    """Decide whether this generated definition may enter the book.

    Unimplemented on purpose. Andy owns this rule; see docs/plan.md, "Open
    decision". The inputs you have are:

        entry["lemma"], entry["definition"], entry["checked"]
        unknown_words(entry["definition"], known_forms)  -> set[str]
        is_circular(entry["definition"], entry["lemma"]) -> bool
        len(entry["definition"]) > MAX_DEFINITION_CHARS  -> bool

    The trade-off is strictness against convergence. Rejecting every
    out-of-vocabulary word is pedagogically pure, but `unknown_words` over-reports
    on inflected forms, so a strict rule sends good definitions back to the
    generator in a loop. Allowing a small number lets a few unknown words through
    and trusts the surrounding sentence to carry them.

    Worth deciding too: does a `checked` entry bypass these rules? You reviewed
    it, so the generator's opinion no longer applies.
    """
    raise NotImplementedError
