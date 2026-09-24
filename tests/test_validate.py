"""Checks the vocabulary the definition rules are measured against."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import validate  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "es" / "words.sample.jsonl"


class LoadHeadwordForms(unittest.TestCase):
    """The vocabulary is every word the book has an entry for (docs/plan.md)."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def written(self, *lines: str) -> Path:
        path = self.tmp / "words.jsonl"
        path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
        return path

    def test_a_listed_form_is_known(self):
        known = validate.load_headword_forms(SAMPLE)
        self.assertEqual(validate.unknown_words("Hablan mucho", known), {"mucho"})

    def test_the_headword_is_known_even_when_its_forms_omit_it(self):
        path = self.written('{"lemma": "decir", "forms": ["dijo"]}')
        self.assertIn("decir", validate.load_headword_forms(path))

    def test_forms_are_normalised(self):
        path = self.written('{"lemma": "hablar", "forms": ["Habló"]}')
        self.assertIn(validate.normalise("habló"), validate.load_headword_forms(path))

    def test_ignores_blank_lines(self):
        path = self.written('{"lemma": "de", "forms": ["de"]}', "")
        self.assertEqual(validate.load_headword_forms(path), {"de"})

    def test_an_entry_without_forms_fails_loudly_with_its_line(self):
        path = self.written('{"lemma": "de", "forms": ["de"]}', '{"lemma": "casa"}')
        with self.assertRaisesRegex(ValueError, r"words\.jsonl:2"):
            validate.load_headword_forms(path)


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
