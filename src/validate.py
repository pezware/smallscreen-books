"""Checks a generated definition before it is allowed into a wordbook.

The definitions come from an LLM, so they are consistent in register but not
guaranteed correct. These checks catch the failure mode that hurts a learner
most: a definition written in words they do not know yet, or one that explains
the word with the word itself.

Neither check proves a definition is true. Only review does that, and the
`checked` flag in the data file records it.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# A definition longer than this spills the first screen on a 480x800 panel at
# the target font size, pushing the first example onto a continuation page.
MAX_DEFINITION_CHARS = 90

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


_COMBINING_TILDE = "̃"


def normalise(word: str) -> str:
    """Lowercase and strip accents, so 'Rápido' and 'rapido' compare equal.

    N-tilde is kept. It is a separate letter in Spanish, not an accented n, and
    folding it would make 'año' and 'ano' the same word.
    """
    folded = unicodedata.normalize("NFD", word.casefold())
    out: list[str] = []
    for char in folded:
        is_enye = char == _COMBINING_TILDE and out and out[-1] == "n"
        if is_enye or unicodedata.category(char) != "Mn":
            out.append(char)
    return unicodedata.normalize("NFC", "".join(out))


def _composed(text: str) -> str:
    """NFC, so a decomposed ñ is one letter before the text is split into words.

    `_WORD` does not match a combining mark, so "an" + U+0303 + "o" would
    otherwise tokenise as "an" and "o".
    """
    return unicodedata.normalize("NFC", text)


def load_known_forms(path: Path | str) -> set[str]:
    """Read a frequency list as a set of normalised surface forms.

    One surface form per line, most frequent first, as written by
    `frequency.py`. This is not the vocabulary definitions are checked
    against; that is `load_headword_forms`.
    """
    with open(path, encoding="utf-8") as handle:
        return {normalise(line.strip()) for line in handle if line.strip()}


def load_headword_forms(path: Path | str) -> set[str]:
    """Read the learner's vocabulary: every headword and every form it lists.

    A definition may use a word when the book has an entry for it, so the
    reader can always look it up (docs/plan.md, decided 2026-09-24). Reads the
    JSONL of the data contract; only `lemma` and `forms` matter here. The
    words are normalised on the way in so that callers never have to remember
    to do it.
    """
    known: set[str] = set()
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            entry = json.loads(line)
            if "forms" not in entry:
                raise ValueError(f"{path}:{number}: entry has no forms")
            known.add(normalise(entry["lemma"]))
            known.update(normalise(form) for form in entry["forms"])
    return known


def unknown_words(definition: str, known_forms: set[str]) -> set[str]:
    """Return the definition's words that fall outside the learner's vocabulary.

    `known_forms` holds normalised surface forms (`load_headword_forms`), so a
    conjugated verb only counts as known when an entry lists that exact form.
    The check therefore over-reports on rare inflections.
    """
    return {
        w
        for w in (normalise(m.group()) for m in _WORD.finditer(_composed(definition)))
        if w not in known_forms
    }


def is_circular(definition: str, lemma: str) -> bool:
    """True when the definition explains the word with the word itself."""
    target = normalise(lemma)
    words = _WORD.finditer(_composed(definition))
    return any(normalise(m.group()) == target for m in words)


@dataclass
class Verdict:
    accepted: bool
    reason: str = ""


def uses_own_form(definition: str, entry: dict) -> bool:
    """True when the definition uses the headword or any form its entry lists.

    Wider than `is_circular`: "Persona de la especie humana" defines `humano`
    with one of its own forms, which a learner cannot look up anywhere else.
    """
    own = {normalise(w) for w in (entry["lemma"], *entry.get("forms", ()))}
    words = _WORD.finditer(_composed(definition))
    return any(normalise(m.group()) in own for m in words)


def accept_definition(entry: dict, known_forms: set[str]) -> Verdict:
    """Decide whether this definition may enter the book (docs/plan.md).

    A reviewed entry (`checked: true`) is accepted as it stands: someone read
    it, so these rules no longer apply. That is also how a definition that
    needs a word the book lacks, such as a place name, gets in.

    Otherwise the rule is strict: every word must be one the book defines, the
    definition must not use its own headword or forms, and it must fit
    MAX_DEFINITION_CHARS. `unknown_words` compares exact forms, so it also
    rejects an unlisted form of a headword ("oye" for `oír`); a repair or a
    review fixes that, rather than a looser rule that would need Wiktionary,
    which never enters the repository, to tell the two cases apart.
    """
    if entry.get("checked"):
        return Verdict(True, "checked")
    definition = entry.get("definition") or ""
    if not definition.strip():
        return Verdict(False, "no definition")
    if len(definition) > MAX_DEFINITION_CHARS:
        return Verdict(
            False, f"{len(definition)} characters, over {MAX_DEFINITION_CHARS}"
        )
    if uses_own_form(definition, entry):
        return Verdict(False, "uses the headword or one of its forms")
    unknown = sorted(unknown_words(definition, known_forms))
    if unknown:
        return Verdict(False, "not in the book: " + ", ".join(unknown))
    return Verdict(True)
