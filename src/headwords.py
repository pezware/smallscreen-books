"""Turns the ranked frequency list into the book's 3,000 headwords (stage 1b).

A headword is a lemma, and its forms share one entry: `dijo`, `dice` and
`decir` are the entry `decir`, ranked by its best form (docs/plan.md). The
frequency list holds surface forms, so each form has to be mapped to a lemma
and a part of speech first. An LLM does that; Wiktionary checks it.

Three steps, so that the expensive one runs once:

    map    ask the LLM for every form that has no current mapping, and write
           data/es/forms.jsonl. That file is the cache: each mapping records
           the hash of the form, model and prompt that produced it, so a rerun
           sends nothing unless one of those changed.
    build  derive data/es/headwords.jsonl from frequency.txt, forms.jsonl and
           forms.overrides.tsv, with no LLM. A test rebuilds it, so the
           committed file cannot drift from its inputs.
    check  compare every headword's forms with Wiktionary, and write a review
           report to build/. Wiktionary is CC BY-SA and never redistributed
           (wiktionary.py), so the report stays local; a reviewer's decision
           goes into forms.overrides.tsv, which is our own data.

A form with two readings, such as `vino`, belongs to the entry of its more
common reading, and only that entry lists it. The prompt asks for that
reading; an override corrects it.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import llm
import validate

BOOK_SIZE = 3000
BATCH = 100

POS = frozenset(
    {
        "sustantivo",
        "verbo",
        "adjetivo",
        "adverbio",
        "pronombre",
        "determinante",
        "preposición",
        "conjunción",
        "interjección",
        "numeral",
    }
)

PROMPT = f"""You map Spanish word forms, taken from a news frequency list, to \
their dictionary lemma and part of speech.
For each form give: "form" (exactly as given), "lemma" (the dictionary form, \
lowercase, accents kept), "pos" (one of: {", ".join(sorted(POS))}), and "skip" \
(true only when the form is not a Spanish word: a name, an abbreviation \
fragment, a foreign word).
When a form has more than one reading, choose the reading most common in \
general Spanish and give only that one.
Contractions (del, al) map to the preposition. A verb form with attached \
clitics maps to the verb.
Answer with a JSON object {{"forms": [...]}} in the same order as the input, \
one item per form, nothing else."""

_ONE_WORD = re.compile(r"^[^\W\d_]+$")

Chat = Callable[[str, str, str], dict]


class MappingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Mapping:
    """One form's lemma, and the identity of the call that produced it."""

    form: str
    lemma: str
    pos: str
    skip: bool
    input_hash: str
    model: str


def form_hash(form: str, model: str, prompt: str) -> str:
    """The cache identity of one form's mapping (docs/plan.md, `generation`).

    The prompt text itself goes in, not a version label, so editing the prompt
    re-maps every form without anyone remembering to bump a number.
    """
    canonical = json.dumps(
        {"form": form, "model": model, "prompt": prompt},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def parse_answer(answer: dict, forms: list[str]) -> list[dict]:
    """Check an LLM answer item by item, and fail on anything malformed.

    A wrong lemma is expensive downstream -- it decides which entry a paid
    definition is generated for -- so nothing is repaired or guessed here.
    """
    items = answer.get("forms")
    if not isinstance(items, list) or len(items) != len(forms):
        got = len(items) if isinstance(items, list) else "no"
        raise MappingError(f"asked for {len(forms)} forms, got {got}")
    rows = []
    for form, item in zip(forms, items, strict=True):
        if _nfc(str(item.get("form", ""))).casefold() != form:
            raise MappingError(f"expected {form!r}, got {item.get('form')!r}")
        skip = bool(item.get("skip", False))
        lemma = _nfc(str(item.get("lemma", ""))).strip().casefold()
        pos = str(item.get("pos", "")).strip()
        if not skip:
            if not _ONE_WORD.match(lemma):
                raise MappingError(f"{form!r}: lemma {lemma!r} is not one word")
            if pos not in POS:
                raise MappingError(f"{form!r}: unknown part of speech {pos!r}")
        rows.append({"form": form, "lemma": lemma, "pos": pos, "skip": skip})
    return rows


def map_forms(
    forms: list[str],
    known: dict[str, Mapping],
    chat: Chat,
    model: str,
    batch: int = BATCH,
    save: Callable[[dict[str, Mapping]], None] = lambda _: None,
) -> dict[str, Mapping]:
    """Map every form whose current mapping is missing or stale.

    Saves after each batch, so an interrupted run resumes where it stopped
    instead of paying for the same batches again.
    """
    result = dict(known)
    todo = [
        f
        for f in forms
        if f not in result or result[f].input_hash != form_hash(f, model, PROMPT)
    ]
    for start in range(0, len(todo), batch):
        chunk = todo[start : start + batch]
        answer = chat(PROMPT, json.dumps(chunk, ensure_ascii=False), model)
        for row in parse_answer(answer, chunk):
            result[row["form"]] = Mapping(
                **row, input_hash=form_hash(row["form"], model, PROMPT), model=model
            )
        save(result)
    return result


def build(
    forms: list[str],
    mappings: dict[str, Mapping],
    overrides: dict[str, tuple[str, str] | None],
    size: int = BOOK_SIZE,
) -> list[dict]:
    """Merge ranked forms into lemmas, and keep the `size` best-ranked lemmas.

    A lemma's rank is the line number of its best form, and its part of speech
    is that form's. Forms are listed most frequent first. An override wins
    over the LLM; `None` drops the form.
    """
    grouped: dict[str, list[tuple[int, str, str]]] = collections.defaultdict(list)
    for rank, form in enumerate(forms, start=1):
        if form in overrides:
            override = overrides[form]
            if override is None:
                continue
            lemma, pos = override
        else:
            if form not in mappings:
                raise MappingError(f"{form!r} has no mapping; run `map` first")
            mapping = mappings[form]
            if mapping.skip:
                continue
            lemma, pos = mapping.lemma, mapping.pos
        grouped[lemma].append((rank, form, pos))

    if len(grouped) < size:
        raise MappingError(
            f"the list yields {len(grouped)} lemmas, fewer than {size}; "
            "raise frequency.DEFAULT_LIMIT"
        )
    ordered = sorted(grouped.items(), key=lambda item: item[1][0][0])[:size]
    return [
        {
            "lemma": lemma,
            "pos": uses[0][2],
            "rank": uses[0][0],
            "forms": [form for _, form, _ in uses],
        }
        for lemma, uses in ordered
    ]


def check_status(
    lemma: str, wiktionary: list[str], lemmas_of: dict[str, list[str]] | None = None
) -> str:
    """Compare one mapping with Wiktionary's lemmas for the same form.

    Stress accents are folded, because the orthography moved (`éste` is now
    written `este`) and that is not a disagreement about the word. One further
    form-of step is followed through `lemmas_of`: Wiktionary files `realizada`
    under the participle `realizado`, itself a form of `realizar`.
    """
    if not wiktionary:
        return "no evidence"
    theirs = {validate.normalise(w) for w in wiktionary}
    further = {
        validate.normalise(w)
        for step in wiktionary
        for w in (lemmas_of or {}).get(step, ())
    }
    if validate.normalise(lemma) not in theirs | further:
        return "disagree"
    return "ambiguous" if len(theirs) > 1 else "agree"


def read_frequency(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_mappings(path: Path) -> dict[str, Mapping]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        rows = (Mapping(**json.loads(line)) for line in handle if line.strip())
        return {row.form: row for row in rows}


def save_mappings(path: Path, forms: list[str], mappings: dict[str, Mapping]) -> None:
    """Write in frequency order, so a diff reads top to bottom by importance."""
    order = {form: i for i, form in enumerate(forms)}
    rows = sorted(mappings.values(), key=lambda m: order.get(m.form, len(order)))
    path.write_text(
        "".join(json.dumps(asdict(m), ensure_ascii=False) + "\n" for m in rows),
        encoding="utf-8",
    )


def load_overrides(path: Path) -> dict[str, tuple[str, str] | None]:
    """Human corrections: `form<TAB>lemma<TAB>pos`, or `form<TAB>-` to drop it."""
    overrides: dict[str, tuple[str, str] | None] = {}
    if not path.exists():
        return overrides
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if fields[1:] == ["-"]:
            overrides[fields[0]] = None
        elif len(fields) == 3 and fields[2] in POS:
            overrides[fields[0]] = (fields[1], fields[2])
        else:
            raise ValueError(f"{path}:{number}: want form, lemma, pos or form, -")
    return overrides


def write_headwords(path: Path, entries: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
        encoding="utf-8",
    )


def write_source(path: Path, model: str, mapped: int, overrides: int) -> None:
    """Provenance for the headword list, as frequency.source.json is for forms."""
    source = {
        "lemmas": {
            "source": f"llm:{model}",
            "prompt_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
            "forms_mapped": mapped,
        },
        "overrides": overrides,
        "checked_against": {
            "name": "English Wiktionary, Spanish entries, via kaikki.org",
            "licence": "CC BY-SA 4.0",
            "use": "local comparison only; no Wiktionary data is redistributed",
        },
        "entries": BOOK_SIZE,
    }
    path.write_text(
        json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_review(
    path: Path, entries: list[dict], mappings: dict, wiktionary_tsv: Path
) -> collections.Counter[str]:
    """Every headword form that Wiktionary does not simply confirm, by rank."""
    theirs: dict[str, list[str]] = collections.defaultdict(list)
    with wiktionary_tsv.open(encoding="utf-8") as handle:
        for line in handle:
            form, lemma, _ = line.rstrip("\n").split("\t")
            if lemma not in theirs[form]:
                theirs[form].append(lemma)
    counts: collections.Counter[str] = collections.Counter()
    lines = ["# rank\tform\tlemma\tpos\tstatus\twiktionary\n"]
    for entry in entries:
        for form in entry["forms"]:
            status = check_status(entry["lemma"], theirs.get(form, []), theirs)
            counts[status] += 1
            if status != "agree":
                lines.append(
                    f"{entry['rank']}\t{form}\t{entry['lemma']}\t{entry['pos']}\t"
                    f"{status}\t{','.join(theirs.get(form, []))}\n"
                )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["map", "build", "check"])
    parser.add_argument("--data", type=Path, default=Path("data/es"))
    parser.add_argument("--model", default=llm.DEFAULT_MODEL)
    parser.add_argument(
        "--wiktionary", type=Path, default=Path("data/es/raw/wiktionary-lemmas.tsv")
    )
    args = parser.parse_args(argv)

    forms = read_frequency(args.data / "frequency.txt")
    mappings_path = args.data / "forms.jsonl"
    mappings = load_mappings(mappings_path)
    overrides = load_overrides(args.data / "forms.overrides.tsv")

    if args.step == "map":

        def chat(system: str, user: str, model: str) -> dict:
            return llm.chat_json(system, user, model=model)

        def save(result: dict[str, Mapping]) -> None:
            save_mappings(mappings_path, forms, result)
            print(f"{len(result)}/{len(forms)} forms mapped", file=sys.stderr)

        mappings = map_forms(forms, mappings, chat, args.model, save=save)
        save_mappings(mappings_path, forms, mappings)
        return 0

    entries = build(forms, mappings, overrides)
    if args.step == "build":
        write_headwords(args.data / "headwords.jsonl", entries)
        models = {m.model for m in mappings.values()}
        if len(models) != 1:
            parser.error(f"forms.jsonl mixes models {sorted(models)}; rerun `map`")
        write_source(
            args.data / "headwords.source.json",
            models.pop(),
            len(mappings),
            len(overrides),
        )
        print(f"{len(entries)} headwords from {len(forms)} forms", file=sys.stderr)
        return 0

    if not args.wiktionary.exists():
        parser.error(f"missing {args.wiktionary}; run src/wiktionary.py first")
    report = Path("build/headwords-review.tsv")
    counts = write_review(report, entries, mappings, args.wiktionary)
    print(f"{dict(counts)} -> {report}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
