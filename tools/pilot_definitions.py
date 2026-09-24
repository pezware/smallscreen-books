"""Pilot for stage 2: can the generator meet a strict vocabulary rule?

Not part of the build, and nothing it writes is committed. It exists to inform
one decision, `validate.accept_definition` (docs/plan.md, "Open decision"):
how many words outside the book a definition may use.

It generates definitions for 50 headwords spread evenly across the ranks,
measures them, then sends every failure back once or twice with its specific
problems named. The question is whether "zero unknown words" converges after a
repair, or whether a looser rule is needed.

    uv run python tools/pilot_definitions.py            # through the xAI broker
    uv run python tools/pilot_definitions.py --vocab none   # without the word list
    uv run python tools/pilot_definitions.py --provider anthropic  # Claude API
    uv run python tools/pilot_definitions.py --provider agent      # see below

With `--provider agent` nothing goes over the network. Each round writes its
requests to build/llm-exchange/requests/ and stops; whoever plays the model,
such as Claude Code, writes each answer file the request names, and the same
command resumes from there.

About 5 calls for the first round and a few more per repair round, at a batch
of 10. Writes build/pilot-definitions-<provider>-<vocab>.jsonl (every attempt) and
build/pilot-unknown-<provider>-<vocab>.tsv (every unknown word, classified),
and prints a summary.

If data/es/raw/wiktionary-lemmas.tsv exists, each unknown word is classified:
an inflection of a headword (the validator over-reports these, since it
compares exact forms) or a word the book does not define at all. Wiktionary is
read locally only, and the report stays in build/, as for `headwords check`.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import llm  # noqa: E402
import validate  # noqa: E402

SAMPLE = 50
BATCH = 10
MAX_WORDS = 12

PROMPT = f"""Eres lexicógrafo. Escribes definiciones para un diccionario \
monolingüe de español para estudiantes de nivel inicial y medio.

Reglas para cada definición:
- Una sola frase en español, completa y gramatical, con punto final. Revisa la \
concordancia y los verbos pronominales: una ventana "se abre", no "abre".
- Como máximo {MAX_WORDS} palabras y {validate.MAX_DEFINITION_CHARS} caracteres, \
espacios incluidos. Más corta es mejor, si queda clara.
- Usa solo palabras que el estudiante puede buscar en este libro. {{vocab}}
- No uses la palabra definida ni ninguna de sus formas.
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
VOCAB_NONE = "Prefiere las palabras más frecuentes y sencillas."

REPAIR = """Estas definiciones no cumplen las reglas. Para cada una se indica \
el problema. Escribe una definición nueva que las cumpla todas."""

Chat = Callable[[str, str], dict]


def sample(entries: list[dict], n: int = SAMPLE) -> list[dict]:
    """Every (len/n)th headword, from the middle of each slice of the ranks."""
    step = len(entries) // n
    return [entries[i * step + step // 2] for i in range(n)]


def book_words(book: list[dict]) -> list[str]:
    """Every headword and listed form, spelled as the book spells them.

    Not the validator's normalised set: the model is told to copy these forms,
    and a list without accents would teach it to drop them.
    """
    return sorted({w for e in book for w in (e["lemma"], *e["forms"])})


def system_prompt(vocab: str, words: list[str]) -> str:
    if vocab == "none":
        return PROMPT.format(vocab=VOCAB_NONE)
    return (
        PROMPT.format(vocab=VOCAB_LIST) + "\n\nPalabras permitidas:\n" + " ".join(words)
    )


def measure(entry: dict, definition: str, known: set[str]) -> dict:
    words = validate._WORD.findall(validate._composed(definition))
    own = {validate.normalise(f) for f in [entry["lemma"], *entry["forms"]]}
    # A word the entry itself lists is "known" to the validator, but using it is
    # the circularity we want to catch, so it is not counted as unknown here.
    unknown = sorted(validate.unknown_words(definition, known) - own)
    return {
        "chars": len(definition),
        "words": len(words),
        "too_long": len(definition) > validate.MAX_DEFINITION_CHARS,
        "circular": validate.is_circular(definition, entry["lemma"]),
        "self_form": any(validate.normalise(w) in own for w in words),
        "unknown": unknown,
    }


def fails_strict(m: dict) -> bool:
    return bool(m["unknown"]) or m["too_long"] or m["self_form"]


def problems(m: dict) -> str:
    out = []
    if m["unknown"]:
        out.append("palabras que no están en el libro: " + ", ".join(m["unknown"]))
    if m["too_long"]:
        out.append(f"{m['chars']} caracteres, más de {validate.MAX_DEFINITION_CHARS}")
    if m["self_form"]:
        out.append("usa la palabra definida o una de sus formas")
    return "; ".join(out)


def ask(chat: Chat, system: str, user: str, lemmas: list[str]) -> dict[str, str]:
    answer = chat(system, user)
    items = answer.get("definitions")
    if not isinstance(items, list):
        raise llm.LLMError(f"no definitions list in {str(answer)[:200]}")
    got = {
        validate.normalise(str(i.get("lemma", ""))): str(i.get("definition", ""))
        for i in items
    }
    missing = [lemma for lemma in lemmas if validate.normalise(lemma) not in got]
    if missing:
        raise llm.LLMError(f"answer skipped {missing}")
    return {lemma: got[validate.normalise(lemma)].strip() for lemma in lemmas}


class Pending(llm.LLMError):
    """Some batches of a round wait on the agent provider's answer files."""

    def __init__(self, requests: list[llm.PendingAnswer]):
        super().__init__(f"{len(requests)} requests wait for an answer")
        self.requests = requests


def ask_all(chat: Chat, system: str, batches: list[tuple[str, list[str]]]):
    """Ask every batch, so one round leaves all its pending requests at once."""
    out: dict[str, str] = {}
    pending: list[llm.PendingAnswer] = []
    for user, lemmas in batches:
        try:
            out.update(ask(chat, system, user, lemmas))
        except llm.PendingAnswer as waiting:
            pending.append(waiting)
    if pending:
        raise Pending(pending)
    return out


def first_round(
    chat: Chat, system: str, entries: list[dict], batch: int
) -> dict[str, str]:
    batches = []
    for start in range(0, len(entries), batch):
        chunk = entries[start : start + batch]
        user = "\n".join(f"{e['lemma']} ({e['pos']})" for e in chunk)
        batches.append((user, [e["lemma"] for e in chunk]))
    return ask_all(chat, system, batches)


def repair_round(
    chat: Chat,
    system: str,
    failing: list[tuple[dict, str, dict]],
    batch: int,
) -> dict[str, str]:
    batches = []
    for start in range(0, len(failing), batch):
        chunk = failing[start : start + batch]
        lines = [
            f"{e['lemma']} ({e['pos']}): «{d}» — {problems(m)}" for e, d, m in chunk
        ]
        user = REPAIR + "\n\n" + "\n".join(lines)
        batches.append((user, [e["lemma"] for e, _, _ in chunk]))
    return ask_all(chat, system, batches)


def run(
    chat: Chat,
    entries: list[dict],
    book: list[dict],
    vocab: str,
    rounds: int,
    batch: int = BATCH,
) -> list[list[dict]]:
    """Every entry's attempt at each round. A passing entry carries forward.

    `entries` are the headwords to define; `book` is every headword, which
    sets the vocabulary.
    """
    known = {validate.normalise(w) for e in book for w in (e["lemma"], *e["forms"])}
    system = system_prompt(vocab, book_words(book))
    defs = first_round(chat, system, entries, batch)
    history = [[_row(e, defs[e["lemma"]], known, 0) for e in entries]]
    for number in range(1, rounds + 1):
        previous = history[-1]
        failing = [
            (e, r["definition"], r)
            for e, r in zip(entries, previous, strict=True)
            if r["fails"]
        ]
        if not failing:
            break
        fixed = repair_round(chat, system, failing, batch)
        history.append(
            [
                _row(e, fixed[e["lemma"]], known, number)
                if e["lemma"] in fixed
                else {**r, "round": number}
                for e, r in zip(entries, previous, strict=True)
            ]
        )
    return history


def _row(entry: dict, definition: str, known: set[str], number: int) -> dict:
    m = measure(entry, definition, known)
    return {
        "lemma": entry["lemma"],
        "pos": entry["pos"],
        "rank": entry["rank"],
        "round": number,
        "definition": definition,
        **m,
        "fails": fails_strict(m),
    }


def load_inflections(path: Path) -> dict[str, set[str]]:
    lemmas: dict[str, set[str]] = collections.defaultdict(set)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            form, lemma, _ = line.rstrip("\n").split("\t")
            lemmas[validate.normalise(form)].add(validate.normalise(lemma))
    return lemmas


def classify(word: str, headwords: set[str], inflections: dict[str, set[str]]):
    if not inflections:
        return "unclassified"
    if inflections.get(word, set()) & headwords:
        return "inflection of a headword"
    return "not in the book"


RULES = {
    "0 unknown": lambda r, _c: not r["unknown"],
    "≤1 unknown": lambda r, _c: len(r["unknown"]) <= 1,
    "≤2 unknown": lambda r, _c: len(r["unknown"]) <= 2,
    "0 unknown, inflections of headwords allowed": lambda r, c: all(
        c(w) == "inflection of a headword" for w in r["unknown"]
    ),
}


def summary(history: list[list[dict]], classify_word) -> str:
    lines = []
    for rows in history:
        n = len(rows)
        number = rows[0]["round"]
        counts = collections.Counter(min(len(r["unknown"]), 3) for r in rows)
        chars = sorted(r["chars"] for r in rows)
        words = sorted(r["words"] for r in rows)
        lines.append(f"round {number} ({n} entries)")
        lines.append(
            "  unknown words per definition: "
            + ", ".join(
                f"{k if k < 3 else '3+'}: {counts[k]}" for k in range(4) if counts[k]
            )
        )
        lines.append(
            f"  over {validate.MAX_DEFINITION_CHARS} chars: "
            f"{sum(r['too_long'] for r in rows)}   "
            f"chars median {chars[n // 2]} max {chars[-1]}   "
            f"words median {words[n // 2]} max {words[-1]}"
        )
        lines.append(
            f"  uses the lemma: {sum(r['circular'] for r in rows)}   "
            f"uses the lemma or one of its forms: {sum(r['self_form'] for r in rows)}"
        )
        for name, rule in RULES.items():
            ok = sum(
                rule(r, classify_word) and not r["too_long"] and not r["self_form"]
                for r in rows
            )
            lines.append(f"  accepted under '{name}' (+ length, self): {ok}/{n}")
    last = history[-1]
    failing = [r for r in last if r["fails"]]
    if failing:
        lines.append(f"still failing after round {last[0]['round']}:")
        lines += [
            f"  {r['lemma']}: «{r['definition']}» — {problems(r)}" for r in failing
        ]
    first = {r["lemma"]: r["definition"] for r in history[0]}
    changed = [r for r in last if r["definition"] != first[r["lemma"]]]
    if changed:
        lines.append("repaired:")
        lines += [
            f"  {r['lemma']}: «{first[r['lemma']]}» -> «{r['definition']}»"
            for r in changed
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path("data/es"))
    parser.add_argument(
        "--provider", choices=llm.PROVIDERS, help="default: $SMALLSCREEN_LLM or xai"
    )
    parser.add_argument("--model", help="default: the provider's default model")
    parser.add_argument("--vocab", choices=["list", "none"], default="list")
    parser.add_argument("--rounds", type=int, default=2, help="repair rounds")
    parser.add_argument("--batch", type=int, default=BATCH)
    parser.add_argument(
        "--wiktionary", type=Path, default=Path("data/es/raw/wiktionary-lemmas.tsv")
    )
    parser.add_argument("--out", type=Path, default=Path("build"))
    args = parser.parse_args(argv)

    headwords_path = args.data / "headwords.jsonl"
    entries = [json.loads(line) for line in headwords_path.open(encoding="utf-8")]
    chosen = sample(entries)
    provider = llm.provider_name(args.provider)
    model = args.model or llm.default_model(provider)

    calls = 0

    def chat(system: str, user: str) -> dict:
        nonlocal calls
        calls += 1
        return llm.chat_json(system, user, model=model, provider=provider)

    try:
        history = run(chat, chosen, entries, args.vocab, args.rounds, args.batch)
    except Pending as pending:
        print(f"{pending}; answer these, then run the same command again:")
        for waiting in pending.requests:
            print(f"  {waiting.request} -> {waiting.answer}")
        return 3

    headwords = {validate.normalise(e["lemma"]) for e in entries}
    inflections = load_inflections(args.wiktionary) if args.wiktionary.exists() else {}

    def classify_word(word: str) -> str:
        return classify(word, headwords, inflections)

    args.out.mkdir(parents=True, exist_ok=True)
    tag = f"{provider}-{args.vocab}"
    with (args.out / f"pilot-definitions-{tag}.jsonl").open("w", encoding="utf-8") as f:
        for rows in history:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (args.out / f"pilot-unknown-{tag}.tsv").open("w", encoding="utf-8") as f:
        f.write("# round\tlemma\tword\tclass\tdefinition\n")
        for rows in history:
            for r in rows:
                for w in r["unknown"]:
                    f.write(
                        f"{r['round']}\t{r['lemma']}\t{w}\t{classify_word(w)}\t"
                        f"{r['definition']}\n"
                    )

    print(f"{provider} {model}, vocab {args.vocab}, {calls} calls", file=sys.stderr)
    if not inflections:
        print(f"no {args.wiktionary}: unknown words left unclassified", file=sys.stderr)
    print(summary(history, classify_word))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
