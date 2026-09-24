"""Checks stage 2's cache, repair loop and review order against a scripted LLM."""

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import definitions  # noqa: E402
import llm  # noqa: E402

MODEL = "m"

HEADWORDS = [
    {"lemma": "casa", "pos": "sustantivo", "rank": 1, "forms": ["casa", "casas"]},
    {"lemma": "lugar", "pos": "sustantivo", "rank": 2, "forms": ["lugar"]},
    {"lemma": "vivir", "pos": "verbo", "rank": 3, "forms": ["vive", "vivir"]},
    {"lemma": "persona", "pos": "sustantivo", "rank": 4, "forms": ["persona"]},
    {"lemma": "donde", "pos": "adverbio", "rank": 5, "forms": ["donde"]},
    {"lemma": "una", "pos": "determinante", "rank": 6, "forms": ["una"]},
    {"lemma": "en", "pos": "preposición", "rank": 7, "forms": ["en"]},
    {"lemma": "un", "pos": "determinante", "rank": 8, "forms": ["un"]},
    {"lemma": "que", "pos": "pronombre", "rank": 9, "forms": ["que"]},
]

GOOD = {
    "casa": "Lugar donde vive una persona.",
    "lugar": "Donde vive una persona.",
    "vivir": "Una persona en un lugar.",
    "persona": "Una que vive en un lugar.",
    "donde": "En un lugar.",
    "una": "Un.",
    "en": "Donde.",
    "un": "Una.",
    "que": "Un lugar en donde.",
}


class Script:
    """Answers each batch from a table; a repair gets the `repairs` table."""

    def __init__(self, first: dict, repairs: dict | None = None):
        self.first, self.repairs = first, repairs or {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        repair = user.startswith(definitions.REPAIR)
        lemmas = re.findall(r"^(\S+) \(", user, re.M)
        table = self.repairs if repair else self.first
        return {
            "definitions": [
                {"lemma": lemma, "definition": table.get(lemma, self.first[lemma])}
                for lemma in lemmas
            ]
        }


def generate(existing=None, chat=None, **kwargs):
    chat = chat or Script(GOOD)
    entries, stale = definitions.generate(
        HEADWORDS, existing or {}, chat, MODEL, **kwargs
    )
    return entries, stale, chat


def by_lemma(entries):
    return {e["lemma"]: e for e in entries}


class Generate(unittest.TestCase):
    def test_every_headword_gets_its_definition(self):
        entries, _, _ = generate()
        self.assertEqual([e["lemma"] for e in entries], [h["lemma"] for h in HEADWORDS])
        self.assertEqual(by_lemma(entries)["casa"]["definition"], GOOD["casa"])

    def test_an_entry_carries_its_provenance_and_is_unchecked(self):
        casa = by_lemma(generate()[0])["casa"]
        self.assertEqual(casa["source"], {"definition": "llm:m"})
        self.assertEqual(
            casa["generation"]["input_hash"],
            definitions.input_hash(HEADWORDS[0], MODEL),
        )
        self.assertIs(casa["checked"], False)

    def test_a_second_run_sends_nothing(self):
        entries, _, _ = generate()
        _, _, chat = generate(by_lemma(entries))
        self.assertEqual(chat.calls, [])

    def test_a_new_model_regenerates(self):
        entries, _, _ = generate()
        chat = Script(GOOD)
        definitions.generate(HEADWORDS, by_lemma(entries), chat, "other")
        self.assertTrue(chat.calls)

    def test_a_reviewed_entry_whose_inputs_changed_is_left_alone(self):
        entries, _, _ = generate()
        existing = by_lemma(entries)
        existing["casa"] = {**existing["casa"], "checked": True, "definition": "Mía."}
        changed = [dict(HEADWORDS[0], forms=["casa", "casas", "casita"])]
        changed += HEADWORDS[1:]
        chat = Script(GOOD)
        result, stale = definitions.generate(changed, existing, chat, MODEL)
        self.assertEqual(by_lemma(result)["casa"]["definition"], "Mía.")
        self.assertEqual([e["lemma"] for e in stale], ["casa"])
        self.assertEqual(chat.calls, [])

    def test_an_unreviewed_entry_whose_inputs_changed_is_regenerated(self):
        entries, _, _ = generate()
        changed = [dict(HEADWORDS[0], forms=["casa", "casas", "casita"])]
        chat = Script(GOOD)
        definitions.generate(changed + HEADWORDS[1:], by_lemma(entries), chat, MODEL)
        self.assertEqual(len(chat.calls), 1)
        self.assertIn("casa (sustantivo)", chat.calls[0][1])

    def test_the_word_list_is_in_the_system_prompt_with_accents(self):
        headwords = HEADWORDS + [
            {"lemma": "acción", "pos": "sustantivo", "rank": 8, "forms": ["acción"]}
        ]
        chat = Script({**GOOD, "acción": "Una."})
        definitions.generate(headwords, {}, chat, MODEL)
        self.assertIn("acción", chat.calls[0][0])

    def test_limit_generates_only_that_many(self):
        entries, _, _ = generate(limit=2)
        defined = [e["lemma"] for e in entries if "definition" in e]
        self.assertEqual(defined, ["casa", "lugar"])
        self.assertEqual(len(entries), len(HEADWORDS))

    def test_saves_after_each_chunk(self):
        saved = []
        original = definitions.CHUNK
        definitions.CHUNK = 3
        self.addCleanup(setattr, definitions, "CHUNK", original)
        generate(save=saved.append)
        counts = [sum("definition" in e for e in s) for s in saved]
        self.assertEqual(counts, [3, 6, 9])


class Repair(unittest.TestCase):
    def test_a_rejected_definition_goes_back_with_its_problem_named(self):
        chat = Script(
            {**GOOD, "casa": "Lugar donde vive una familia."},
            {"casa": "Lugar donde vive una persona."},
        )
        entries, _, _ = generate(chat=chat)
        casa = by_lemma(entries)["casa"]
        self.assertEqual(casa["definition"], "Lugar donde vive una persona.")
        self.assertEqual(casa["generation"]["repairs"], 1)
        repair = chat.calls[-1][1]
        self.assertIn("familia", repair)
        self.assertIn("no están en el libro", repair)
        self.assertNotIn("lugar (", repair)

    def test_the_repair_names_a_use_of_the_headword(self):
        chat = Script(
            {**GOOD, "casa": "Lugar como una casa."},
            {"casa": "Lugar donde vive una persona."},
        )
        generate(chat=chat)
        self.assertIn("usa la palabra definida", chat.calls[-1][1])

    def test_a_stuck_definition_is_kept_after_the_last_round(self):
        chat = Script({**GOOD, "casa": "Hogar."}, {"casa": "Hogar."})
        entries, _, _ = generate(chat=chat, rounds=2)
        casa = by_lemma(entries)["casa"]
        self.assertEqual(casa["definition"], "Hogar.")
        self.assertEqual(casa["generation"]["repairs"], 2)
        repairs = [u for _, u in chat.calls if u.startswith(definitions.REPAIR)]
        self.assertEqual(len(repairs), 2)

    def test_no_repair_round_when_everything_passes(self):
        _, _, chat = generate()
        self.assertEqual(len(chat.calls), 1)


class ParseAnswer(unittest.TestCase):
    def test_matches_by_position_so_papa_and_papá_stay_apart(self):
        answer = {
            "definitions": [
                {"lemma": "papa", "definition": "Una planta."},
                {"lemma": "papá", "definition": "Un padre."},
            ]
        }
        self.assertEqual(
            definitions.parse_answer(answer, ["papa", "papá"]),
            ["Una planta.", "Un padre."],
        )

    def test_a_short_answer_fails(self):
        with self.assertRaisesRegex(definitions.DefinitionError, "asked for 2"):
            definitions.parse_answer({"definitions": [{}]}, ["a", "b"])

    def test_an_answer_out_of_order_fails(self):
        answer = {"definitions": [{"lemma": "b", "definition": "x"}]}
        with self.assertRaisesRegex(definitions.DefinitionError, "expected 'a'"):
            definitions.parse_answer(answer, ["a"])

    def test_an_empty_definition_fails(self):
        answer = {"definitions": [{"lemma": "a", "definition": " "}]}
        with self.assertRaisesRegex(definitions.DefinitionError, "empty"):
            definitions.parse_answer(answer, ["a"])

    def test_whitespace_is_collapsed(self):
        answer = {"definitions": [{"lemma": "a", "definition": " Una\n cosa. "}]}
        self.assertEqual(definitions.parse_answer(answer, ["a"]), ["Una cosa."])


class InputHash(unittest.TestCase):
    def test_changes_with_forms_and_model_but_not_with_rank(self):
        base = definitions.input_hash(HEADWORDS[0], MODEL)
        self.assertNotEqual(
            base, definitions.input_hash(dict(HEADWORDS[0], forms=["casa"]), MODEL)
        )
        self.assertNotEqual(base, definitions.input_hash(HEADWORDS[0], "other"))
        self.assertEqual(
            base, definitions.input_hash(dict(HEADWORDS[0], rank=99), MODEL)
        )


class PendingAgent(unittest.TestCase):
    def test_every_pending_batch_of_a_round_is_reported(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

        def chat(system, user):
            return llm.chat_json(
                system, user, model=MODEL, provider="agent", exchange=tmp
            )

        original = definitions.BATCH
        definitions.BATCH = 3
        self.addCleanup(setattr, definitions, "BATCH", original)
        with self.assertRaises(definitions.Pending) as caught:
            definitions.generate(HEADWORDS, {}, chat, MODEL)
        self.assertEqual(len(caught.exception.requests), 3)


class Merge(unittest.TestCase):
    def test_an_entry_whose_headword_left_the_list_is_dropped(self):
        existing = {"gone": {"lemma": "gone", "definition": "x"}}
        merged = definitions.merge(HEADWORDS[:1], existing)
        self.assertEqual([e["lemma"] for e in merged], ["casa"])

    def test_rank_and_forms_follow_the_headwords(self):
        existing = {
            "casa": {"lemma": "casa", "rank": 9, "forms": [], "definition": "x"}
        }
        (casa,) = definitions.merge(HEADWORDS[:1], existing)
        self.assertEqual((casa["rank"], casa["forms"]), (1, ["casa", "casas"]))


class Review(unittest.TestCase):
    def entry(self, lemma, definition, rank, **extra):
        return {
            "lemma": lemma,
            "pos": "sustantivo",
            "rank": rank,
            "forms": [lemma],
            "definition": definition,
            **extra,
        }

    def test_rejected_first_then_family_then_repaired_then_the_rest(self):
        known = {"una", "persona", "justa", "legitimo"}
        entries = [
            self.entry("uno", "Una persona.", 1),
            self.entry("justo", "Una persona.", 2, generation={"repairs": 1}),
            self.entry("legitimidad", "Una legitimo.", 3),
            self.entry("mal", "Hogar.", 4),
            self.entry("bien", "Una persona.", 5, checked=True),
            {"lemma": "nada", "pos": "x", "rank": 6, "forms": ["nada"]},
        ]
        rows = definitions.review(entries, known)
        self.assertEqual(
            [(p, e["lemma"]) for p, _, e in rows],
            [(0, "mal"), (1, "legitimidad"), (2, "justo"), (3, "uno")],
        )

    def test_same_family_ignores_short_headwords(self):
        entry = self.entry("sede", "Sedes.", 1)
        self.assertEqual(definitions.same_family(entry), [])


class Main(unittest.TestCase):
    def test_check_writes_the_review_and_fails_on_a_rejection(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (tmp / "headwords.jsonl").write_text(
            "".join(json.dumps(h, ensure_ascii=False) + "\n" for h in HEADWORDS),
            encoding="utf-8",
        )
        entries, _, _ = generate(chat=Script({**GOOD, "casa": "Hogar."}, {}), rounds=0)
        definitions.write_jsonl(tmp / "words.jsonl", entries)
        review = tmp / "review.tsv"
        argv = ["check", "--data", str(tmp), "--review", str(review)]
        with contextlib.redirect_stdout(io.StringIO()):
            code = definitions.main(argv)
        self.assertEqual(code, 1)
        self.assertIn("casa", review.read_text(encoding="utf-8").splitlines()[1])


if __name__ == "__main__":
    unittest.main()
