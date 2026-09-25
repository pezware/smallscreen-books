"""Checks how frequency-list forms become the book's headwords."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import headwords  # noqa: E402
import validate  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data" / "es"


def mapped(form, lemma, pos="verbo", skip=False):
    return headwords.Mapping(form, lemma, pos, skip, "sha256:x", "m")


def falling(forms):
    """Counts that fall with rank, as frequency.txt's do: 100, 99, 98..."""
    return {form: 100 - i for i, form in enumerate(forms)}


class ParseAnswer(unittest.TestCase):
    def answer(self, *items):
        return {"forms": [dict(item) for item in items]}

    def test_reads_lemma_and_pos(self):
        answer = self.answer({"form": "dijo", "lemma": "decir", "pos": "verbo"})
        (row,) = headwords.parse_answer(answer, ["dijo"])
        self.assertEqual((row["lemma"], row["pos"]), ("decir", "verbo"))

    def test_an_answer_for_a_different_form_fails(self):
        answer = self.answer({"form": "dice", "lemma": "decir", "pos": "verbo"})
        with self.assertRaisesRegex(headwords.MappingError, "dijo"):
            headwords.parse_answer(answer, ["dijo"])

    def test_a_missing_item_fails(self):
        with self.assertRaisesRegex(headwords.MappingError, "2 forms"):
            headwords.parse_answer(self.answer(), ["dijo", "dice"])

    def test_an_unknown_part_of_speech_fails(self):
        answer = self.answer({"form": "dijo", "lemma": "decir", "pos": "verb"})
        with self.assertRaisesRegex(headwords.MappingError, "verb"):
            headwords.parse_answer(answer, ["dijo"])

    def test_a_lemma_that_is_not_one_word_fails(self):
        answer = self.answer({"form": "dijo", "lemma": "decir algo", "pos": "verbo"})
        with self.assertRaisesRegex(headwords.MappingError, "decir algo"):
            headwords.parse_answer(answer, ["dijo"])

    def test_a_skipped_form_needs_no_lemma(self):
        answer = self.answer({"form": "uu", "lemma": "", "pos": "", "skip": True})
        (row,) = headwords.parse_answer(answer, ["uu"])
        self.assertTrue(row["skip"])

    def test_a_skip_that_is_not_a_boolean_fails(self):
        answer = self.answer(
            {"form": "de", "lemma": "de", "pos": "preposición", "skip": "false"}
        )
        with self.assertRaisesRegex(headwords.MappingError, "skip"):
            headwords.parse_answer(answer, ["de"])

    def test_the_lemma_is_lowercased(self):
        answer = self.answer({"form": "dijo", "lemma": "Decir", "pos": "verbo"})
        self.assertEqual(headwords.parse_answer(answer, ["dijo"])[0]["lemma"], "decir")


class FormHash(unittest.TestCase):
    def test_is_stable(self):
        self.assertEqual(
            headwords.form_hash("dijo", "m", "p"), headwords.form_hash("dijo", "m", "p")
        )

    def test_changes_with_the_prompt_text(self):
        self.assertNotEqual(
            headwords.form_hash("dijo", "m", "p"), headwords.form_hash("dijo", "m", "q")
        )

    def test_changes_with_the_model(self):
        self.assertNotEqual(
            headwords.form_hash("dijo", "m", "p"), headwords.form_hash("dijo", "n", "p")
        )


class MapForms(unittest.TestCase):
    def fake(self):
        calls = []

        def chat(system, user, model):
            forms = json.loads(user)
            calls.append(forms)
            return {"forms": [{"form": f, "lemma": f, "pos": "verbo"} for f in forms]}

        return chat, calls

    def test_sends_forms_in_batches(self):
        chat, calls = self.fake()
        headwords.map_forms(["a", "b", "c"], {}, chat, "m", batch=2)
        self.assertEqual(calls, [["a", "b"], ["c"]])

    def test_a_second_run_sends_nothing(self):
        chat, calls = self.fake()
        first = headwords.map_forms(["a", "b"], {}, chat, "m", batch=2)
        calls.clear()
        headwords.map_forms(["a", "b"], first, chat, "m", batch=2)
        self.assertEqual(calls, [])

    def test_a_changed_model_maps_again(self):
        chat, calls = self.fake()
        first = headwords.map_forms(["a"], {}, chat, "m", batch=2)
        calls.clear()
        headwords.map_forms(["a"], first, chat, "n", batch=2)
        self.assertEqual(calls, [["a"]])

    def test_a_form_no_longer_in_the_list_is_dropped(self):
        chat, _ = self.fake()
        first = headwords.map_forms(["a", "b"], {}, chat, "m", batch=2)
        self.assertEqual(set(headwords.map_forms(["a"], first, chat, "m")), {"a"})

    def test_saves_after_every_batch(self):
        chat, _ = self.fake()
        saved = []
        headwords.map_forms(
            ["a", "b", "c"], {}, chat, "m", batch=2, save=lambda m: saved.append(len(m))
        )
        self.assertEqual(saved, [2, 3])


class Build(unittest.TestCase):
    def test_forms_of_one_lemma_share_one_entry(self):
        entries = headwords.build(
            ["dijo", "dice", "decir"],
            {f: mapped(f, "decir") for f in ["dijo", "dice", "decir"]},
            {},
            falling(["dijo", "dice", "decir"]),
            size=1,
        )
        self.assertEqual(entries[0]["forms"], ["dijo", "dice", "decir"])

    def test_a_lemma_is_ranked_by_the_sum_of_its_forms(self):
        # "limpia" and "limpio" each trail "cumbre", but together they lead it.
        entries = headwords.build(
            ["cumbre", "limpia", "limpio"],
            {
                "cumbre": mapped("cumbre", "cumbre", "sustantivo"),
                **{f: mapped(f, "limpio", "adjetivo") for f in ["limpia", "limpio"]},
            },
            {},
            {"cumbre": 50, "limpia": 30, "limpio": 25},
            size=1,
        )
        self.assertEqual(entries[0]["lemma"], "limpio")

    def test_the_rank_is_the_lemma_s_position(self):
        entries = headwords.build(
            ["de", "dijo", "decir"],
            {
                "de": mapped("de", "de"),
                **{f: mapped(f, "decir") for f in ["dijo", "decir"]},
            },
            {},
            {"de": 100, "dijo": 10, "decir": 9},
            size=2,
        )
        self.assertEqual(
            [(e["lemma"], e["rank"]) for e in entries], [("de", 1), ("decir", 2)]
        )

    def test_a_tie_goes_to_the_better_best_form(self):
        entries = headwords.build(
            ["a", "b", "c"],
            {"a": mapped("a", "x"), "b": mapped("b", "y"), "c": mapped("c", "x")},
            {},
            {"a": 5, "b": 10, "c": 5},
            size=2,
        )
        self.assertEqual([e["lemma"] for e in entries], ["x", "y"])

    def test_a_form_without_a_count_fails_loudly(self):
        with self.assertRaisesRegex(headwords.MappingError, "no count"):
            headwords.build(["a"], {"a": mapped("a", "a")}, {}, {}, size=1)

    def test_the_part_of_speech_comes_from_the_best_ranked_form(self):
        entries = headwords.build(
            ["bajo", "baja"],
            {
                "bajo": mapped("bajo", "bajo", "preposición"),
                "baja": mapped("baja", "bajo", "adjetivo"),
            },
            {},
            falling(["bajo", "baja"]),
            size=1,
        )
        self.assertEqual(entries[0]["pos"], "preposición")

    def test_a_skipped_form_makes_no_entry(self):
        entries = headwords.build(
            ["uu", "de"],
            {"uu": mapped("uu", "", "", skip=True), "de": mapped("de", "de")},
            {},
            falling(["uu", "de"]),
            size=1,
        )
        self.assertEqual([e["lemma"] for e in entries], ["de"])

    def test_an_override_replaces_the_llm_lemma(self):
        entries = headwords.build(
            ["vino"],
            {"vino": mapped("vino", "vino", "sustantivo")},
            {"vino": ("venir", "verbo")},
            falling(["vino"]),
            size=1,
        )
        self.assertEqual((entries[0]["lemma"], entries[0]["pos"]), ("venir", "verbo"))

    def test_an_override_can_skip_a_form(self):
        entries = headwords.build(
            ["uu", "de"],
            {"uu": mapped("uu", "uu"), "de": mapped("de", "de")},
            {"uu": None},
            falling(["uu", "de"]),
            size=1,
        )
        self.assertEqual([e["lemma"] for e in entries], ["de"])

    def test_stops_at_the_book_size(self):
        entries = headwords.build(
            ["a", "b", "c"],
            {f: mapped(f, f) for f in "abc"},
            {},
            falling("abc"),
            size=2,
        )
        self.assertEqual(len(entries), 2)

    def test_too_few_lemmas_fails_loudly(self):
        with self.assertRaisesRegex(headwords.MappingError, "1 lemmas"):
            headwords.build(["a"], {"a": mapped("a", "a")}, {}, {"a": 1}, size=2)

    def test_an_unmapped_form_fails_loudly(self):
        with self.assertRaisesRegex(headwords.MappingError, "b"):
            headwords.build(
                ["a", "b"], {"a": mapped("a", "a")}, {}, falling("ab"), size=1
            )


class Stale(unittest.TestCase):
    def test_a_mapping_from_another_prompt_is_stale(self):
        old = headwords.Mapping("de", "de", "preposición", False, "sha256:old", "m")
        self.assertEqual(headwords.stale_forms(["de"], {"de": old}), ["de"])

    def test_a_current_mapping_is_not_stale(self):
        current = headwords.Mapping(
            "de",
            "de",
            "preposición",
            False,
            headwords.form_hash("de", "m", headwords.PROMPT),
            "m",
        )
        self.assertEqual(headwords.stale_forms(["de"], {"de": current}), [])


class Provenance(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.entries = self.tmp / "headwords.jsonl"
        self.entries.write_text('{"lemma": "de"}\n', encoding="utf-8")
        self.source = self.tmp / "headwords.source.json"

    def check(self):
        return json.loads(self.source.read_text(encoding="utf-8"))["check"]

    def test_a_build_records_no_check_until_one_runs(self):
        headwords.write_source(self.source, "m", 1, 0, self.entries)
        self.assertIsNone(self.check())

    def test_a_check_is_stamped_with_the_headwords_it_saw(self):
        headwords.write_source(self.source, "m", 1, 0, self.entries)
        headwords.stamp_check(self.source, self.entries, {"agree": 1})
        self.assertEqual(
            self.check()["headwords_sha256"], headwords.file_sha256(self.entries)
        )

    def test_rebuilding_the_same_headwords_keeps_the_check(self):
        headwords.write_source(self.source, "m", 1, 0, self.entries)
        headwords.stamp_check(self.source, self.entries, {"agree": 1})
        headwords.write_source(self.source, "m", 1, 0, self.entries)
        self.assertIsNotNone(self.check())

    def test_changed_headwords_drop_the_check(self):
        headwords.write_source(self.source, "m", 1, 0, self.entries)
        headwords.stamp_check(self.source, self.entries, {"agree": 1})
        self.entries.write_text('{"lemma": "la"}\n', encoding="utf-8")
        headwords.write_source(self.source, "m", 1, 0, self.entries)
        self.assertIsNone(self.check())


class Review(unittest.TestCase):
    def test_a_row_shows_the_form_s_own_rank_and_part_of_speech(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        wiktionary = tmp / "w.tsv"
        wiktionary.write_text("bajo\tbajo\tprep\nbaja\tbajar\tverb\n", encoding="utf-8")
        report = tmp / "review.tsv"
        entry = {
            "lemma": "bajo",
            "pos": "preposición",
            "rank": 1,
            "forms": ["bajo", "baja"],
        }
        mappings = {
            "bajo": mapped("bajo", "bajo", "preposición"),
            "baja": mapped("baja", "bajo", "adjetivo"),
        }
        headwords.write_review(
            report, [entry], mappings, {}, ["bajo", "baja"], wiktionary
        )
        row = report.read_text(encoding="utf-8").splitlines()[1].split("\t")
        self.assertEqual((row[0], row[1], row[3]), ("2", "baja", "adjetivo"))


class Overrides(unittest.TestCase):
    def test_reads_lemma_pos_and_skip_lines(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = tmp / "o.tsv"
        path.write_text("# comment\nvino\tvenir\tverbo\nuu\t-\n", encoding="utf-8")
        self.assertEqual(
            headwords.load_overrides(path), {"vino": ("venir", "verbo"), "uu": None}
        )

    def test_a_malformed_line_fails_with_its_number(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = tmp / "o.tsv"
        path.write_text("vino\tvenir\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "o.tsv:1"):
            headwords.load_overrides(path)


class Check(unittest.TestCase):
    def status(self, lemma, wiktionary):
        return headwords.check_status(lemma, wiktionary)

    def test_agrees_when_wiktionary_names_the_lemma(self):
        self.assertEqual(self.status("decir", ["decir"]), "agree")

    def test_stress_accents_do_not_count_as_disagreement(self):
        self.assertEqual(self.status("este", ["éste"]), "agree")

    def test_several_wiktionary_readings_are_flagged(self):
        self.assertEqual(self.status("vino", ["vino", "venir"]), "ambiguous")

    def test_a_different_lemma_disagrees(self):
        self.assertEqual(self.status("de", ["del"]), "disagree")

    def test_a_lemma_one_form_of_step_away_agrees(self):
        """Wiktionary files realizada under the participle realizado, which is
        itself a form of realizar; that is the same word."""
        self.assertEqual(
            headwords.check_status(
                "realizar", ["realizado"], {"realizado": ["realizar"]}
            ),
            "agree",
        )

    def test_a_form_wiktionary_lacks_has_no_evidence(self):
        self.assertEqual(self.status("dar", []), "no evidence")


class ShippedHeadwords(unittest.TestCase):
    """The committed artifact, which stage 2 reads."""

    def entries(self):
        with (DATA / "headwords.jsonl").open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def test_is_what_the_committed_inputs_build(self):
        rebuilt = headwords.build(
            headwords.read_frequency(DATA / "frequency.txt"),
            headwords.load_mappings(DATA / "forms.jsonl"),
            headwords.load_overrides(DATA / "forms.overrides.tsv"),
            headwords.read_counts(DATA / "frequency.txt"),
        )
        self.assertEqual(rebuilt, self.entries())

    def test_every_mapping_is_current(self):
        forms = headwords.read_frequency(DATA / "frequency.txt")
        mappings = headwords.load_mappings(DATA / "forms.jsonl")
        self.assertEqual(headwords.stale_forms(forms, mappings), [])

    def test_the_recorded_check_saw_these_headwords(self):
        source = json.loads((DATA / "headwords.source.json").read_text("utf-8"))
        self.assertEqual(
            source["check"]["headwords_sha256"],
            headwords.file_sha256(DATA / "headwords.jsonl"),
        )

    def test_holds_the_book_size(self):
        self.assertEqual(len(self.entries()), headwords.BOOK_SIZE)

    def test_no_form_belongs_to_two_entries(self):
        forms = [f for e in self.entries() for f in e["forms"]]
        self.assertEqual(len(forms), len(set(forms)))

    def test_the_vocabulary_check_can_load_it(self):
        known = validate.load_headword_forms(DATA / "headwords.jsonl")
        self.assertIn("decir", known)


if __name__ == "__main__":
    unittest.main()
