"""Checks the vocabulary the definition rules are measured against."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import validate  # noqa: E402


class LoadKnownForms(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def written(self, text: str) -> Path:
        path = self.tmp / "frequency.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def test_reads_one_form_per_line(self):
        self.assertEqual(
            validate.load_known_forms(self.written("de\nla\nque\n")),
            {"de", "la", "que"},
        )

    def test_normalises_so_an_accented_definition_word_matches(self):
        known = validate.load_known_forms(self.written("más\n"))
        self.assertEqual(validate.unknown_words("Más casa", known), {"casa"})

    def test_ignores_blank_lines(self):
        self.assertEqual(validate.load_known_forms(self.written("de\n\n")), {"de"})

    def test_knowing_año_does_not_make_ano_known(self):
        known = validate.load_known_forms(self.written("año\n"))
        self.assertEqual(validate.unknown_words("ano", known), {"ano"})


class Normalise(unittest.TestCase):
    def test_enye_is_a_letter_not_an_accented_n(self):
        self.assertNotEqual(validate.normalise("año"), validate.normalise("ano"))

    def test_enye_survives_case_folding(self):
        self.assertEqual(validate.normalise("AÑO"), "año")

    def test_decomposed_enye_equals_precomposed(self):
        self.assertEqual(validate.normalise("año"), "año")

    def test_stress_accents_still_fold(self):
        self.assertEqual(validate.normalise("Rápido"), "rapido")


if __name__ == "__main__":
    unittest.main()
