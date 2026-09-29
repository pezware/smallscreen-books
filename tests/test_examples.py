"""Checks how Tatoeba sentences become each entry's two examples (stage 3)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import examples  # noqa: E402
import render  # noqa: E402

KNOWN = {
    "yo",
    "bebo",
    "agua",
    "el",
    "bebe",
    "vino",
    "que",
    "es",
    "eso",
    "hacia",
    "voy",
    "casa",
    "la",
    "mi",
    "tu",
    "grande",
    "de",
    "una",
    "vive",
    "en",
}


def line(sid, text, by="ana", lang="spa"):
    return f"{sid}\t{lang}\t{text}\t{by}\t\\N\t2020-01-01\n"


def entry(lemma, forms, rank=1, pos="verbo"):
    return {"lemma": lemma, "pos": pos, "rank": rank, "forms": forms}


def sentences(*rows):
    return [s for s in (examples.parse_line(line(*r)) for r in rows) if s]


class ParseLine(unittest.TestCase):
    def test_keeps_a_short_sentence_with_its_contributor(self):
        s = examples.parse_line(line(7, "Yo bebo agua fría."))
        self.assertEqual((s.id, s.by, s.text), (7, "ana", "Yo bebo agua fría."))

    def test_drops_a_sentence_without_a_contributor(self):
        self.assertIsNone(examples.parse_line(line(7, "Yo bebo agua fría.", "\\N")))

    def test_drops_digits_other_languages_and_extremes(self):
        self.assertIsNone(examples.parse_line(line(1, "Tengo 18 años hoy.")))
        self.assertIsNone(
            examples.parse_line(line(1, "I drink water now.", lang="eng"))
        )
        self.assertIsNone(examples.parse_line(line(1, "Bebo agua.")))
        self.assertIsNone(examples.parse_line(line(1, " ".join(["agua"] * 17) + ".")))

    def test_keeps_accents_for_matching_but_folds_them_for_the_vocabulary(self):
        s = examples.parse_line(line(1, "¿Qué es eso ahora?"))
        self.assertIn("qué", s.tokens)
        self.assertIn("que", s.words)


class ReadSentences(unittest.TestCase):
    def test_the_lowest_id_wins_a_duplicate_wording(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = tmp / "s.tsv"
        path.write_text(
            line(9, "Yo bebo agua fría.") + line(3, "yo bebo agua fría"), "utf-8"
        )
        self.assertEqual([s.id for s in examples.read_sentences(path)], [3])


class Candidates(unittest.TestCase):
    def test_an_accented_form_does_not_match_the_unaccented_word(self):
        pool = examples.candidates(
            [entry("que", ["que"]), entry("qué", ["qué"])],
            sentences((1, "¿Qué es eso ahora?")),
            KNOWN | {"ahora"},
        )
        self.assertEqual(pool["que"], [])
        self.assertEqual([s.id for s, _ in pool["qué"]], [1])

    def test_fewer_unknown_words_rank_first_then_shorter(self):
        pool = examples.candidates(
            [entry("beber", ["bebo"])],
            sentences(
                (1, "Yo bebo agua de mi casa grande."),
                (2, "Yo bebo agua fría."),
                (3, "Yo bebo agua."),
                (4, "Yo bebo mucha agua."),
            ),
            KNOWN,
        )
        # 3 is too short to parse; 1 keeps to the book, 2 and 4 have one
        # unknown word each and 2 is shorter.
        self.assertEqual([s.id for s, _ in pool["beber"]], [1, 2, 4])

    def test_a_long_sentence_ranks_below_every_short_one(self):
        long = "Yo bebo agua de mi casa grande en una casa de la casa de mi."
        pool = examples.candidates(
            [entry("beber", ["bebo"])],
            sentences((1, long), (2, "Yo bebo agua fría.")),
            KNOWN,
        )
        self.assertEqual([s.id for s, _ in pool["beber"]], [2, 1])

    def test_more_unknown_words_than_the_long_limit_is_no_candidate(self):
        pool = examples.candidates(
            [entry("beber", ["bebo"])],
            sentences((1, "Yo bebo zumo frío y helado.")),
            KNOWN,
        )
        self.assertEqual(pool["beber"], [])


class Pick(unittest.TestCase):
    def test_two_examples_preferring_a_second_form(self):
        chosen = examples.pick(
            [entry("beber", ["bebo", "bebe"])],
            sentences(
                (1, "Yo bebo agua de mi casa."),
                (2, "Yo bebo agua en mi casa grande."),
                (3, "Él bebe agua de tu casa."),
            ),
            KNOWN | {"él"},
        )
        self.assertEqual([s.id for s in chosen["beber"]], [1, 3])

    def test_a_sentence_is_used_once_and_the_scarcer_entry_chooses_first(self):
        chosen = examples.pick(
            [entry("casa", ["casa"], rank=1), entry("vivir", ["vive"], rank=2)],
            sentences(
                (1, "Ella vive en una casa grande."),
                (2, "Esa es mi casa grande."),
                (3, "La casa de tu vino."),
            ),
            KNOWN | {"ella", "esa"},
        )
        self.assertEqual([s.id for s in chosen["vivir"]], [1])
        self.assertNotIn(1, [s.id for s in chosen["casa"]])

    def test_an_entry_with_two_examples_is_left_alone(self):
        full = {**entry("beber", ["bebo"]), "examples": ["a", "b"]}
        chosen = examples.pick([full], sentences((1, "Yo bebo agua fría.")), KNOWN)
        self.assertEqual(chosen, {})

    def test_a_reviewed_entry_is_never_refilled(self):
        reviewed = {**entry("beber", ["bebo"]), "examples_reviewed_by": "agent"}
        chosen = examples.pick([reviewed], sentences((1, "Yo bebo agua fría.")), KNOWN)
        self.assertEqual(chosen, {})

    def test_a_near_copy_of_the_first_is_not_the_second(self):
        chosen = examples.pick(
            [entry("beber", ["bebo"])],
            sentences((1, "Yo bebo agua de mi casa."), (2, "Yo bebo agua de tu casa.")),
            KNOWN,
        )
        self.assertEqual([s.id for s in chosen["beber"]], [1])


class ApplyAndChoose(unittest.TestCase):
    def test_apply_records_the_id_and_contributor(self):
        s = sentences((5, "Yo bebo agua fría.", "luis"))
        (out,) = examples.apply([entry("beber", ["bebo"])], {"beber": s})
        self.assertEqual(out["examples"], ["Yo bebo agua fría."])
        self.assertEqual(out["source"]["examples"], [{"id": 5, "by": "luis"}])

    def test_choose_replaces_the_examples_and_records_the_reviewer(self):
        s = {
            x.key: x for x in sentences((5, "Yo bebo agua fría."), (6, "Él bebe agua."))
        }
        start = {**entry("beber", ["bebo"]), "examples": ["Otra frase."]}
        (out,), problems = examples.choose([start], {"beber": ["5"]}, s, "agent")
        self.assertEqual(
            (out["examples"], out["examples_reviewed_by"], problems),
            (["Yo bebo agua fría."], "agent", []),
        )

    def test_choose_with_no_ids_leaves_no_example(self):
        start = {**entry("beber", ["bebo"]), "examples": ["Mal ejemplo."]}
        (out,), _ = examples.choose([start], {"beber": []}, {}, "agent")
        self.assertEqual(out["examples"], [])

    def test_choose_refuses_an_unknown_id(self):
        start = entry("beber", ["bebo"])
        (out,), problems = examples.choose([start], {"beber": ["99"]}, {}, "agent")
        self.assertEqual(out, start)
        self.assertIn("99", problems[0])

    def test_read_choices(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (tmp / "c.tsv").write_text(
            "# lemma\tids\tnote\nbeber\t5, leipzig:6\tok\nvino\t\tnone fits\n",
            "utf-8",
        )
        self.assertEqual(
            examples.read_choices(tmp / "c.tsv"),
            {"beber": ["5", "leipzig:6"], "vino": []},
        )

    def test_read_choices_refuses_an_id_that_is_not_one(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (tmp / "c.tsv").write_text("beber\tabc\t\n", "utf-8")
        with self.assertRaisesRegex(ValueError, "not a sentence id"):
            examples.read_choices(tmp / "c.tsv")


class News(unittest.TestCase):
    def test_a_leipzig_row_becomes_a_news_sentence(self):
        s = examples.parse_news_line("42\tYo bebo agua de mi casa.\n")
        self.assertEqual((s.corpus, s.id, s.key), ("leipzig", 42, "leipzig:42"))
        self.assertEqual(s.ref(), {"corpus": "leipzig", "id": 42})

    def test_tatoeba_ranks_above_any_news_sentence(self):
        news = examples.parse_news_line("1\tYo bebo agua de mi casa.\n")
        tat = sentences((2, "Yo bebo agua fría en la casa grande."))
        pool = examples.candidates([entry("beber", ["bebo"])], [news, *tat], KNOWN)
        self.assertEqual([s.corpus for s, _ in pool["beber"]], ["tatoeba", "leipzig"])

    def test_a_news_sentence_fills_a_word_tatoeba_lacks(self):
        news = examples.parse_news_line("7\tYo bebo agua de mi casa.\n")
        chosen = examples.pick([entry("beber", ["bebo"])], [news], KNOWN)
        self.assertEqual([s.key for s in chosen["beber"]], ["leipzig:7"])

    def test_the_same_id_in_both_corpora_is_two_sentences(self):
        news = examples.parse_news_line("5\tYo bebo agua de mi casa.\n")
        (tat,) = sentences((5, "Él bebe agua de tu casa."))
        self.assertNotEqual(news.key, tat.key)

    def test_a_news_sentence_names_no_contributor(self):
        rows = [{"source": {"examples": [{"corpus": "leipzig", "id": 1}]}}]
        self.assertEqual(examples.contributors(rows), [])


class Credits(unittest.TestCase):
    def test_contributors_are_named_once_in_order(self):
        rows = [
            {"source": {"examples": [{"id": 1, "by": "zoe"}, {"id": 2, "by": "Ana"}]}},
            {"source": {"examples": [{"id": 3, "by": "zoe"}]}},
        ]
        self.assertEqual(examples.contributors(rows), ["Ana", "zoe"])

    def test_the_credits_page_names_the_contributors(self):
        page = render.sources_xhtml([{**examples.LICENCE, "contributors": ["ana"]}])
        self.assertIn("Colaboradores: ana.", page)
        self.assertIn("creativecommons.org/licenses/by/2.0/fr/", page)


class Report(unittest.TestCase):
    def test_names_short_entries_unknown_words_and_long_examples(self):
        long = "Yo bebo agua de mi casa grande en una casa de la casa."
        rows = examples.report(
            [
                {**entry("beber", ["bebo"]), "examples": ["Yo bebo zumo.", long]},
                entry("vino", ["vino"]),
            ],
            KNOWN,
        )
        problems = {(lemma, problem) for lemma, problem, _ in rows}
        self.assertEqual(
            problems,
            {
                ("beber", "word not in the book"),
                ("beber", "long example"),
                ("vino", "0 of 2"),
            },
        )


if __name__ == "__main__":
    unittest.main()
