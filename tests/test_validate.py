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


if __name__ == "__main__":
    unittest.main()
