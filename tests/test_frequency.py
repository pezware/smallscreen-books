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

    def test_the_definition_checks_can_load_it(self):
        import validate

        self.assertIn("casa", validate.load_known_forms(self.LIST))


if __name__ == "__main__":
    unittest.main()
