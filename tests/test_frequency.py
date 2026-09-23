"""Checks that the frequency list holds words, not tokens or names."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import frequency  # noqa: E402


def write(directory: Path, name: str, lines: list[str]) -> Path:
    path = directory / name
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


class CountWords(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_folds_sentence_initial_capitals_into_one_form(self):
        words = write(self.tmp, "w.txt", ["1\tel\t70", "2\tEl\t30"])
        self.assertEqual(frequency.count_words(words)["el"], 100)

    def test_drops_tokens_that_are_not_words(self):
        words = write(self.tmp, "w.txt", ["1\t,\t900", "2\t2011\t80", "3\tcasa\t10"])
        self.assertEqual(list(frequency.count_words(words)), ["casa"])

    def test_drops_single_letters_that_are_not_spanish_words(self):
        words = write(self.tmp, "w.txt", ["1\tp\t900", "2\ty\t800"])
        self.assertEqual(list(frequency.count_words(words)), ["y"])

    def test_keeps_accents(self):
        words = write(self.tmp, "w.txt", ["1\tmás\t5"])
        self.assertIn("más", frequency.count_words(words))

    def test_adds_an_unaccented_variant_to_its_accented_form(self):
        words = write(self.tmp, "w.txt", ["1\tasí\t70", "2\tasi\t30"])
        self.assertEqual(frequency.count_words(words)["así"], 100)

    def test_drops_the_unaccented_variant_itself(self):
        words = write(self.tmp, "w.txt", ["1\tasí\t70", "2\tasi\t30"])
        self.assertNotIn("asi", frequency.count_words(words))

    def test_drops_english_tokens(self):
        words = write(self.tmp, "w.txt", ["1\tthe\t90", "2\tof\t80", "3\tcasa\t10"])
        self.assertEqual(list(frequency.count_words(words)), ["casa"])


class CountCaseUses(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_ignores_the_capital_that_starts_a_sentence(self):
        sentences = write(self.tmp, "s.txt", ["1\tAdemás vino."])
        lowercase, capitalised = frequency.count_case_uses(sentences, {"además"})
        self.assertEqual((lowercase["además"], capitalised["además"]), (0, 0))

    def test_counts_a_mixed_case_brand_inside_a_sentence(self):
        sentences = write(self.tmp, "s.txt", ["1\tCompro un iPhone hoy."])
        _, capitalised = frequency.count_case_uses(sentences, {"iphone"})
        self.assertEqual(capitalised["iphone"], 1)

    def test_counts_a_capital_inside_a_sentence(self):
        sentences = write(self.tmp, "s.txt", ["1\tVivo en España hoy."])
        _, capitalised = frequency.count_case_uses(sentences, {"españa"})
        self.assertEqual(capitalised["españa"], 1)

    def test_credits_a_variant_to_its_accented_form(self):
        sentences = write(self.tmp, "s.txt", ["1\tLo hizo asi."])
        lowercase, _ = frequency.count_case_uses(sentences, {"así"})
        self.assertEqual(lowercase["así"], 1)


class ProperNouns(unittest.TestCase):
    def test_a_name_is_capitalised_away_from_the_sentence_start(self):
        españa = frequency.Form(
            "españa", 13674, lowercase_uses=96, capitalised_uses=12885
        )
        self.assertTrue(españa.is_proper_noun())

    def test_a_word_that_news_capitalises_inside_names_still_counts_as_a_word(self):
        gobierno = frequency.Form(
            "gobierno", 26242, lowercase_uses=13330, capitalised_uses=12864
        )
        self.assertFalse(gobierno.is_proper_noun())

    def test_a_word_seen_only_at_sentence_starts_is_not_called_a_name(self):
        unseen = frequency.Form("asimismo", 6133, lowercase_uses=0, capitalised_uses=0)
        self.assertFalse(unseen.is_proper_noun())


class Select(unittest.TestCase):
    def ranked(self):
        return [
            frequency.Form("de", 100, 100, 0),
            frequency.Form("madrid", 90, 1, 89),
            frequency.Form("casa", 80, 80, 10),
        ]

    def test_an_excluded_name_promotes_the_next_word(self):
        kept, _ = frequency.select(self.ranked(), limit=2)
        self.assertEqual([form.form for form in kept], ["de", "casa"])

    def test_the_dropped_name_is_reported(self):
        _, excluded = frequency.select(self.ranked(), limit=2)
        self.assertEqual([form.form for form in excluded], ["madrid"])

    def test_a_zero_ratio_keeps_every_form(self):
        kept, _ = frequency.select(self.ranked(), limit=3, ratio=0.0)
        self.assertEqual(len(kept), 3)

    def test_name_uses_do_not_lift_a_word_above_common_vocabulary(self):
        """Issue #5: china is a word, but two thirds of its uses are the
        country, and those must not rank it above casa."""
        forms = [
            frequency.Form("de", 100, 100, 0),
            frequency.Form("china", 90, 30, 60),
            frequency.Form("casa", 80, 80, 0),
        ]
        kept, _ = frequency.select(forms, limit=3)
        self.assertEqual([form.form for form in kept], ["de", "casa", "china"])

    def test_a_name_that_would_not_reach_the_cut_is_not_reported(self):
        forms = [
            frequency.Form("de", 100, 100, 0),
            frequency.Form("casa", 80, 80, 0),
            frequency.Form("madrid", 50, 1, 49),
        ]
        _, excluded = frequency.select(forms, limit=2)
        self.assertEqual(excluded, [])


class RankingCount(unittest.TestCase):
    def test_counts_only_the_lowercase_share_of_the_total(self):
        china = frequency.Form("china", 900, lowercase_uses=300, capitalised_uses=600)
        self.assertEqual(china.ranking_count, 300)

    def test_a_form_never_seen_mid_sentence_keeps_its_whole_count(self):
        unseen = frequency.Form("asimismo", 6133, lowercase_uses=0, capitalised_uses=0)
        self.assertEqual(unseen.ranking_count, 6133)


class PoolDepth(unittest.TestCase):
    """Candidates are chosen by total count, then re-ranked by a smaller one."""

    def test_deep_enough_when_the_cut_sits_above_every_uncounted_form(self):
        pool = [frequency.Form("de", 100, 100, 0), frequency.Form("casa", 40, 40, 0)]
        self.assertTrue(frequency.pool_is_deep_enough(pool, kept=pool[:1]))

    def test_too_shallow_when_a_form_outside_the_pool_could_outrank_the_cut(self):
        pool = [frequency.Form("de", 100, 100, 0), frequency.Form("china", 90, 30, 60)]
        self.assertFalse(frequency.pool_is_deep_enough(pool, kept=pool))


class Attribution(unittest.TestCase):
    """CC BY 4.0 wants the licence, the material, and a note of changes (#7)."""

    def setUp(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        corpus_file = write(tmp, "c-words.txt", ["1\tde\t1"])
        out = tmp / "frequency.source.json"
        frequency.write_source(out, "spa_news_2011_1M", [corpus_file], 3000, 1, 0.08)
        import json

        self.source = json.loads(out.read_text(encoding="utf-8"))["source"]

    def test_links_the_licence(self):
        self.assertEqual(
            self.source["licence_url"], "https://creativecommons.org/licenses/by/4.0/"
        )

    def test_links_the_corpus_that_was_used_not_the_collection(self):
        self.assertEqual(
            self.source["material"],
            "https://downloads.wortschatz-leipzig.de/corpora/spa_news_2011_1M.tar.gz",
        )

    def test_says_the_material_was_modified(self):
        self.assertIn("modified", self.source["changes"].lower())


class ShippedList(unittest.TestCase):
    """The artifact in data/es, which every later stage reads."""

    LIST = Path(__file__).resolve().parent.parent / "data" / "es" / "frequency.txt"

    def forms(self) -> list[str]:
        return self.LIST.read_text(encoding="utf-8").splitlines()

    def test_holds_three_thousand_words(self):
        self.assertEqual(len(self.forms()), frequency.DEFAULT_LIMIT)

    def test_every_line_is_a_single_lowercase_word(self):
        odd = [f for f in self.forms() if not f.islower() or not f.isalpha()]
        self.assertEqual(odd, [])

    def test_holds_no_mixed_case_brand_names(self):
        """iPhone and iPad were invisible to the classifier until it counted
        every non-lowercase token, not just initial capitals.

        Windows and YouTube are deliberately not asserted here: they are
        counted correctly and simply sit above the cut, at a lowercase share
        of 0.12, alongside words like dios and navidad.
        """
        self.assertEqual(set(self.forms()) & {"iphone", "ipad"}, set())

    def test_holds_no_stray_single_letters(self):
        strays = [f for f in self.forms() if len(f) == 1]
        self.assertEqual(set(strays) - set(frequency.ONE_LETTER_WORDS), set())

    def test_holds_no_duplicates(self):
        forms = self.forms()
        self.assertEqual(len(set(forms)), len(forms))

    def test_holds_no_known_noise(self):
        """The forms issue #6 found: English, a name fragment, a misspelling."""
        self.assertEqual(set(self.forms()) & {"the", "of", "in", "bin", "asi"}, set())

    def test_the_definition_checks_can_load_it(self):
        import validate

        self.assertIn("casa", validate.load_known_forms(self.LIST))


if __name__ == "__main__":
    unittest.main()
