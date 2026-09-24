"""Writes a short Spanish definition for every headword (stage 2).

An LLM writes each definition in the book's own vocabulary, and
`validate.accept_definition` decides whether it may stand (docs/plan.md). The
prompt was tuned on a 50-word pilot (tools/pilot_definitions.py) against three
failures a checker cannot see: a news sense instead of the basic one, a
sentence that is not grammatical, and a repair that passes the check by
deleting meaning.

Two steps, so that the expensive one runs once:

    generate  ask the LLM for every headword whose definition is missing or
              stale, send each rejection back with its problem named for up to
              REPAIR_ROUNDS rounds, and write data/es/words.jsonl. That file is
              the cache: each entry records the hash of what produced it, so a
              rerun sends nothing unless a headword, the model or the prompt
              changed. A reviewed entry (`checked: true`) is never regenerated.
    check     re-validate every entry with no LLM, because validation is not
              cached: a changed headword list can make a once-valid definition
              fail. Writes the review report.

The hash covers the lemma, its part of speech and forms, the model and the
prompt rules, but not the word list pasted into the prompt. That list is the
whole vocabulary, so hashing it would regenerate all 3,000 definitions when one
headword changes; `check` re-validates every entry against the current list
instead.

Both steps write build/definitions-review.tsv: every entry a person should
read, most urgent first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path

import llm
import validate

BATCH = 10
# Headwords generated and repaired together before words.jsonl is saved, so an
# interrupted run loses at most one chunk. Saving mid-repair would record a
# rejected definition as current, and the rerun would skip its repair.
CHUNK = 50
# The pilot's second round rescued one definition in 50 on one run and none on
# another; a third would only resend the same stuck entries.
REPAIR_ROUNDS = 2
MAX_WORDS = 12
PROMPT_VERSION = "v1"

RULES = f"""Eres lexicógrafo. Escribes definiciones para un diccionario \
monolingüe de español para estudiantes de nivel inicial y medio.

Reglas para cada definición:
- Una sola frase en español, completa y gramatical, con punto final. Revisa la \
concordancia y los verbos pronominales: una ventana "se abre", no "abre".
- Como máximo {MAX_WORDS} palabras y {validate.MAX_DEFINITION_CHARS} caracteres, \
espacios incluidos.
- Di qué distingue a esta palabra de otras cercanas. Una definición vaga, que \
serviría también para otra palabra, no sirve.
- Usa solo palabras que el estudiante puede buscar en este libro. {{vocab}}
- No uses la palabra definida ni ninguna de sus formas, ni palabras de su misma \
familia: para "libertad", no "libre".
- Define el sentido básico que un estudiante aprende primero, con la categoría \
gramatical dada, aunque otro sentido sea más frecuente en la prensa: "partido" es \
primero un juego entre dos equipos, no un grupo político.
- No empieces repitiendo la palabra ni con "Palabra que".
- Sin ejemplos, sin comillas, sin paréntesis.

Responde con un objeto JSON {{{{"definitions": [...]}}}}, un elemento por palabra \
y en el mismo orden: {{{{"lemma": "...", "definition": "..."}}}}. Nada más."""

VOCAB_LIST = (
    "La lista completa de palabras permitidas va al final; usa las formas "
    "exactamente como aparecen en ella."
)

REPAIR = """Estas definiciones no cumplen las reglas. Para cada una se indica \
el problema. Escribe una definición nueva que las cumpla todas.
Cambia solo lo necesario: explica con palabras sencillas lo que decía cada \
palabra que falta, y conserva todo el significado. No acortes la definición \
quitando información."""

# A shared prefix this long suggests the same word family (legítimo for
# legitimidad). It only sends a definition to review; it rejects nothing.
FAMILY_PREFIX = 6

Chat = Callable[[str, str], dict]


class DefinitionError(RuntimeError):
    pass


def book_words(headwords: list[dict]) -> list[str]:
    """Every headword and listed form, spelled as the book spells them.

    Not the validator's normalised set: the model copies these forms, and a
    list without accents would teach it to drop them.
    """
    return sorted({w for e in headwords for w in (e["lemma"], *e["forms"])})


def vocabulary(headwords: list[dict]) -> set[str]:
    """The validator's view of book_words: the same words, normalised."""
    return {validate.normalise(w) for w in book_words(headwords)}


def system_prompt(words: list[str]) -> str:
    return (
        RULES.format(vocab=VOCAB_LIST) + "\n\nPalabras permitidas:\n" + " ".join(words)
    )


def input_hash(headword: dict, model: str) -> str:
    """The cache identity of one definition (docs/plan.md, `generation`)."""
    canonical = json.dumps(
        {
            "lemma": headword["lemma"],
            "pos": headword["pos"],
            "forms": headword["forms"],
            "model": model,
            "prompt": RULES + REPAIR,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def same_family(entry: dict) -> list[str]:
    """Words of the definition that look like the headword's family."""
    lemma = validate.normalise(entry["lemma"])
    if len(lemma) <= FAMILY_PREFIX:
        return []
    own = {validate.normalise(w) for w in (entry["lemma"], *entry["forms"])}
    words = validate._WORD.findall(validate._composed(entry.get("definition", "")))
    stem = lemma[:FAMILY_PREFIX]
    return sorted(
        {w for w in map(validate.normalise, words) if w.startswith(stem)} - own
    )


def problems(entry: dict, known: set[str]) -> str:
    """Why a definition was rejected, in Spanish, for the repair prompt."""
    definition = entry.get("definition", "")
    out = []
    unknown = sorted(validate.unknown_words(definition, known))
    if unknown:
        out.append("palabras que no están en el libro: " + ", ".join(unknown))
    if len(definition) > validate.MAX_DEFINITION_CHARS:
        out.append(
            f"{len(definition)} caracteres, más de {validate.MAX_DEFINITION_CHARS}"
        )
    if validate.uses_own_form(definition, entry):
        out.append("usa la palabra definida o una de sus formas")
    return "; ".join(out) or "no cumple las reglas"


def repair_line(entry: dict, known: set[str]) -> str:
    head = f"{entry['lemma']} ({entry['pos']})"
    return f"{head}: «{entry['definition']}» — {problems(entry, known)}"


def parse_answer(answer: dict, lemmas: list[str]) -> list[str]:
    """The definitions in the order asked, checked item by item.

    Matched by position, not by name: `papa` and `papá` normalise alike, so a
    lookup by lemma could hand one entry the other's definition.
    """
    items = answer.get("definitions")
    if not isinstance(items, list) or len(items) != len(lemmas):
        got = len(items) if isinstance(items, list) else "no"
        raise DefinitionError(f"asked for {len(lemmas)} definitions, got {got}")
    out = []
    for lemma, item in zip(lemmas, items, strict=True):
        if not isinstance(item, dict):
            raise DefinitionError(f"{lemma!r}: item is {item!r}")
        said = str(item.get("lemma", ""))
        if validate.normalise(said) != validate.normalise(lemma):
            raise DefinitionError(f"expected {lemma!r}, got {said!r}")
        definition = " ".join(str(item.get("definition", "")).split())
        if not definition:
            raise DefinitionError(f"{lemma!r}: empty definition")
        out.append(definition)
    return out


class Pending(llm.LLMError):
    """Some batches wait on the agent provider's answer files."""

    def __init__(self, requests: list[llm.PendingAnswer]):
        super().__init__(f"{len(requests)} requests wait for an answer")
        self.requests = requests


def _ask_all(chat: Chat, system: str, batches: list[tuple[str, list[str]]]):
    """Ask every batch, so one round leaves all its pending requests at once."""
    out: dict[str, str] = {}
    pending: list[llm.PendingAnswer] = []
    for user, lemmas in batches:
        try:
            answer = parse_answer(chat(system, user), lemmas)
            out.update(zip(lemmas, answer, strict=True))
        except llm.PendingAnswer as waiting:
            pending.append(waiting)
    if pending:
        raise Pending(pending)
    return out


def _batches(lines: list[tuple[str, str]], prefix: str = "") -> list:
    """Groups of BATCH (lemma, line) pairs as (user message, lemmas)."""
    out = []
    for start in range(0, len(lines), BATCH):
        chunk = lines[start : start + BATCH]
        body = "\n".join(line for _, line in chunk)
        out.append((prefix + body, [lemma for lemma, _ in chunk]))
    return out


def define(
    headwords: list[dict], chat: Chat, model: str, book: list[dict], rounds: int
) -> dict[str, dict]:
    """Generate and repair definitions for these headwords; return new entries.

    A definition still rejected after the last round is kept and reported, not
    dropped: regenerating it would cost the same calls for the same answer, and
    a reviewer can fix it by hand.
    """
    known = vocabulary(book)
    system = system_prompt(book_words(book))
    first = _ask_all(
        chat,
        system,
        _batches([(h["lemma"], f"{h['lemma']} ({h['pos']})") for h in headwords]),
    )
    entries = {h["lemma"]: _entry(h, first[h["lemma"]], model, 0) for h in headwords}
    for number in range(1, rounds + 1):
        failing = [
            e
            for e in entries.values()
            if not validate.accept_definition(e, known).accepted
        ]
        if not failing:
            break
        lines = [(e["lemma"], repair_line(e, known)) for e in failing]
        fixed = _ask_all(chat, system, _batches(lines, REPAIR + "\n\n"))
        for e in failing:
            entries[e["lemma"]] = {
                **e,
                "definition": fixed[e["lemma"]],
                "generation": {**e["generation"], "repairs": number},
            }
    return entries


def _entry(headword: dict, definition: str, model: str, repairs: int) -> dict:
    return {
        "lemma": headword["lemma"],
        "pos": headword["pos"],
        "rank": headword["rank"],
        "forms": headword["forms"],
        "definition": definition,
        "source": {"definition": f"llm:{model}"},
        "generation": {
            "input_hash": input_hash(headword, model),
            "model": model,
            "prompt": PROMPT_VERSION,
            "repairs": repairs,
        },
        "checked": False,
    }


def plan(
    headwords: list[dict], existing: dict[str, dict], model: str
) -> tuple[list[dict], list[dict]]:
    """Split the headwords into those to generate and reviewed entries left alone.

    Returns (todo, stale_checked). An entry is current when its hash matches;
    a reviewed entry whose inputs changed is reported and kept, because only a
    person clears `checked` (docs/plan.md).
    """
    todo, stale_checked = [], []
    for headword in headwords:
        old = existing.get(headword["lemma"])
        if old and old.get("generation", {}).get("input_hash") == input_hash(
            headword, model
        ):
            continue
        if old and old.get("checked"):
            stale_checked.append(old)
            continue
        todo.append(headword)
    return todo, stale_checked


def merge(headwords: list[dict], existing: dict[str, dict]) -> list[dict]:
    """words.jsonl in headword order: every headword, defined or not yet.

    A headword with no definition yet is written as it stands in
    headwords.jsonl, so the book stays whole while generation is partial. An
    entry whose headword left the list is dropped.
    """
    out = []
    for headword in headwords:
        old = existing.get(headword["lemma"])
        if old is None:
            out.append(dict(headword))
        else:
            out.append({**old, "rank": headword["rank"], "forms": headword["forms"]})
    return out


def generate(
    headwords: list[dict],
    existing: dict[str, dict],
    chat: Chat,
    model: str,
    rounds: int = REPAIR_ROUNDS,
    limit: int | None = None,
    save: Callable[[list[dict]], None] = lambda _: None,
) -> tuple[list[dict], list[dict]]:
    """Generate every missing or stale definition; return (entries, stale_checked).

    Saves after each CHUNK of headwords, so an interrupted run resumes where it
    stopped.
    """
    todo, stale_checked = plan(headwords, existing, model)
    if limit is not None:
        todo = todo[:limit]
    current = dict(existing)
    for start in range(0, len(todo), CHUNK):
        chunk = todo[start : start + CHUNK]
        current.update(define(chunk, chat, model, headwords, rounds))
        save(merge(headwords, current))
    return merge(headwords, current), stale_checked


def review(entries: list[dict], known: set[str]) -> list[tuple[int, str, dict]]:
    """Entries a person should read, as (priority, reason), most urgent first.

    0 rejected, 1 same word family, 2 repaired, 3 accepted and not yet checked.
    Reviewed entries are left out.
    """
    rows = []
    for entry in entries:
        if "definition" not in entry or entry.get("checked"):
            continue
        verdict = validate.accept_definition(entry, known)
        family = same_family(entry)
        if not verdict.accepted:
            rows.append((0, verdict.reason, entry))
        elif family:
            rows.append((1, "same family: " + ", ".join(family), entry))
        elif entry.get("generation", {}).get("repairs"):
            rows.append((2, f"repaired ({entry['generation']['repairs']})", entry))
        else:
            rows.append((3, "unchecked", entry))
    return sorted(rows, key=lambda row: (row[0], row[2]["rank"]))


def write_review(path: Path, rows: list[tuple[int, str, dict]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# priority\trank\tlemma\tpos\treason\tdefinition\n"]
    for priority, reason, e in rows:
        lines.append(
            f"{priority}\t{e['rank']}\t{e['lemma']}\t{e['pos']}\t{reason}\t"
            f"{e['definition']}\n"
        )
    path.write_text("".join(lines), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, entries: list[dict]) -> None:
    text = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)
    partial = path.with_suffix(".partial")
    partial.write_text(text, encoding="utf-8")
    partial.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["generate", "check"])
    parser.add_argument("--data", type=Path, default=Path("data/es"))
    parser.add_argument(
        "--provider", choices=llm.PROVIDERS, help="default: $SMALLSCREEN_LLM or xai"
    )
    parser.add_argument("--model", help="default: the provider's default model")
    parser.add_argument("--rounds", type=int, default=REPAIR_ROUNDS)
    parser.add_argument(
        "--limit",
        type=int,
        help="generate at most this many new or stale definitions this run",
    )
    parser.add_argument(
        "--review", type=Path, default=Path("build/definitions-review.tsv")
    )
    args = parser.parse_args(argv)

    headwords = read_jsonl(args.data / "headwords.jsonl")
    words_path = args.data / "words.jsonl"
    existing = {e["lemma"]: e for e in read_jsonl(words_path) if "definition" in e}
    entries = merge(headwords, existing)

    if args.step == "generate":
        provider = llm.provider_name(args.provider)
        model = args.model or llm.default_model(provider)

        def chat(system: str, user: str) -> dict:
            return llm.chat_json(system, user, model=model, provider=provider)

        def save(result: list[dict]) -> None:
            write_jsonl(words_path, result)
            done = sum("definition" in e for e in result)
            print(f"{done}/{len(result)} defined", file=sys.stderr)

        try:
            entries, stale = generate(
                headwords, existing, chat, model, args.rounds, args.limit, save
            )
        except Pending as pending:
            print(f"{pending}; answer these, then run `generate` again:")
            for waiting in pending.requests:
                print(f"  {waiting.request} -> {waiting.answer}")
            return 3
        write_jsonl(words_path, entries)
        for entry in stale:
            print(
                f"{entry['lemma']}: checked, but its inputs changed; left alone",
                file=sys.stderr,
            )

    known = validate.load_headword_forms(args.data / "headwords.jsonl")
    rows = review(entries, known)
    write_review(args.review, rows)
    defined = sum("definition" in e for e in entries)
    rejected = sum(priority == 0 for priority, _, _ in rows)
    checked = sum(bool(e.get("checked")) for e in entries)
    print(
        f"{defined}/{len(entries)} defined, {checked} checked, {rejected} rejected, "
        f"{len(rows)} to review -> {args.review}"
    )
    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
