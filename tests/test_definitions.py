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


class Retire(unittest.TestCase):
    def test_a_defined_entry_whose_headword_left_is_retired(self):
        existing = {"gone": {"lemma": "gone", "definition": "x"}, "casa": {}}
        self.assertEqual(definitions.retired(HEADWORDS, existing), [existing["gone"]])

    def test_sync_moves_it_out_and_generate_reuses_it_when_it_returns(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        entries, _, _ = generate()
        definitions.write_jsonl(tmp / "words.jsonl", entries)

        def write_headwords(rows):
            text = "".join(json.dumps(h, ensure_ascii=False) + "\n" for h in rows)
            (tmp / "headwords.jsonl").write_text(text, encoding="utf-8")

        argv = ["sync", "--data", str(tmp), "--review", str(tmp / "r.tsv")]
        write_headwords(HEADWORDS[1:])
        with contextlib.redirect_stdout(io.StringIO()):
            definitions.main(argv)
        retired = definitions.read_jsonl(tmp / "words.retired.jsonl")
        self.assertEqual([e["lemma"] for e in retired], ["casa"])
        words = definitions.read_jsonl(tmp / "words.jsonl")
        self.assertNotIn("casa", [e["lemma"] for e in words])

        write_headwords(HEADWORDS)
        with contextlib.redirect_stdout(io.StringIO()):
            definitions.main(argv)
        words = definitions.read_jsonl(tmp / "words.jsonl")
        self.assertEqual(words[0]["definition"], GOOD["casa"])
        self.assertEqual(definitions.read_jsonl(tmp / "words.retired.jsonl"), [])


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

    def test_a_broken_style_rule_is_sent_to_review(self):
        entries = [self.entry("uno", "palabra que cuenta", 1)]
        ((priority, reason, _),) = definitions.review(
            entries, {"palabra", "que", "cuenta"}
        )
        self.assertEqual(priority, 1)
        self.assertIn("lowercase", reason)
        self.assertIn("Palabra que", reason)
        self.assertIn("no final period", reason)

    def test_over_twelve_words_is_a_style_problem(self):
        long = " ".join(["una"] * 13) + "."
        self.assertIn("over 12 words", definitions.style_problems(long))

    def test_a_clean_definition_has_no_style_problem(self):
        self.assertEqual(definitions.style_problems("Una persona."), [])

    def test_same_family_ignores_short_headwords(self):
        entry = self.entry("sede", "Sedes.", 1)
        self.assertEqual(definitions.same_family(entry), [])


class Main(unittest.TestCase):
    def run_check(self, *flags: str, first: dict | None = None) -> tuple[int, Path]:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (tmp / "headwords.jsonl").write_text(
            "".join(json.dumps(h, ensure_ascii=False) + "\n" for h in HEADWORDS),
            encoding="utf-8",
        )
        table = first if first is not None else {**GOOD, "casa": "Hogar."}
        entries, _, _ = generate(chat=Script(table, {}), rounds=0)
        definitions.write_jsonl(tmp / "words.jsonl", entries)
        review = tmp / "review.tsv"
        argv = ["check", "--data", str(tmp), "--review", str(review), *flags]
        with contextlib.redirect_stdout(io.StringIO()):
            return definitions.main(argv), review

    def test_check_puts_a_rejection_first_in_the_review(self):
        _, review = self.run_check()
        self.assertIn("casa", review.read_text(encoding="utf-8").splitlines()[1])

    def test_a_rejection_is_review_work_not_a_failed_run(self):
        self.assertEqual(self.run_check()[0], 0)

    def test_strict_fails_while_a_definition_is_rejected(self):
        self.assertEqual(self.run_check("--strict")[0], 1)

    def test_strict_passes_when_every_definition_is_accepted(self):
        self.assertEqual(self.run_check("--strict", first=GOOD)[0], 0)


class ApplySheet(unittest.TestCase):
    ENTRIES = [
        {"lemma": "casa", "definition": "Hogar.", "source": {"definition": "llm:m"}},
        {"lemma": "lugar", "definition": "Sitio.", "source": {"definition": "llm:m"}},
    ]

    def row(self, lemma, current, suggested, ok="y"):
        return {
            "ok": ok,
            "lemma": lemma,
            "pos": "",
            "rank": "",
            "current": current,
            "suggested": suggested,
            "note": "",
        }

    def test_an_approved_row_is_applied_and_checked(self):
        rows = [self.row("casa", "Hogar.", "Lugar donde vive una persona.")]
        out, applied, skipped = definitions.apply_sheet(self.ENTRIES, rows)
        self.assertEqual(applied, ["casa"])
        self.assertEqual(out[0]["definition"], "Lugar donde vive una persona.")
        self.assertIs(out[0]["checked"], True)
        self.assertEqual(out[0]["source"]["definition"], "review")
        self.assertEqual(out[0]["reviewed_by"], "human")

    def test_the_reviewer_is_recorded(self):
        rows = [self.row("casa", "Hogar.", "Una casa grande.")]
        out, _, _ = definitions.apply_sheet(self.ENTRIES, rows, reviewer="agent")
        self.assertEqual(out[0]["reviewed_by"], "agent")

    def test_an_unmarked_row_is_left_alone(self):
        rows = [self.row("casa", "Hogar.", "Otra.", ok="")]
        out, applied, _ = definitions.apply_sheet(self.ENTRIES, rows)
        self.assertEqual((out, applied), (self.ENTRIES, []))

    def test_a_row_whose_definition_changed_since_is_skipped(self):
        rows = [self.row("casa", "Casa vieja.", "Otra.")]
        out, applied, skipped = definitions.apply_sheet(self.ENTRIES, rows)
        self.assertEqual(applied, [])
        self.assertIn("changed", skipped[0][1])

    def test_an_unknown_lemma_is_skipped(self):
        _, _, skipped = definitions.apply_sheet(self.ENTRIES, [self.row("x", "", "Y.")])
        self.assertEqual(skipped, [("x", "not in words.jsonl")])

    def test_approving_the_current_definition_keeps_its_source(self):
        rows = [self.row("lugar", "Sitio.", "Sitio.", ok="sí")]
        out, _, _ = definitions.apply_sheet(self.ENTRIES, rows)
        self.assertEqual(out[1]["source"]["definition"], "llm:m")
        self.assertIs(out[1]["checked"], True)

    def test_a_sheet_round_trips(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        rows = [self.row("casa", "Hogar.", "Una casa.", ok="")]
        definitions.write_sheet(tmp / "s.tsv", rows)
        self.assertEqual(definitions.read_sheet(tmp / "s.tsv"), rows)

    def test_a_sheet_with_other_columns_fails(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (tmp / "s.tsv").write_text("a\tb\n", encoding="utf-8")
        with self.assertRaisesRegex(definitions.DefinitionError, "columns"):
            definitions.read_sheet(tmp / "s.tsv")


if __name__ == "__main__":
    unittest.main()
