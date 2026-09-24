"""Checks the Wiktionary pairs the LLM's lemmas are compared against."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import wiktionary  # noqa: E402


def pairs(entry: dict) -> list[tuple[str, str, str]]:
    return list(wiktionary.pairs(entry))


class Pairs(unittest.TestCase):
    def test_a_form_of_sense_names_its_lemma(self):
        entry = {
            "word": "dijo",
            "pos": "verb",
            "senses": [{"form_of": [{"word": "decir"}]}],
        }
        self.assertEqual(pairs(entry), [("dijo", "decir", "verb")])

    def test_a_lemma_sense_names_the_word_itself(self):
        entry = {"word": "casa", "pos": "noun", "senses": [{"glosses": ["house"]}]}
        self.assertEqual(pairs(entry), [("casa", "casa", "noun")])

    def test_a_homograph_yields_both_readings(self):
        noun = {"word": "vino", "pos": "noun", "senses": [{"glosses": ["wine"]}]}
        verb = {
            "word": "vino",
            "pos": "verb",
            "senses": [{"form_of": [{"word": "venir"}]}],
        }
        self.assertEqual(
            pairs(noun) + pairs(verb),
            [("vino", "vino", "noun"), ("vino", "venir", "verb")],
        )

    def test_repeated_senses_yield_one_pair(self):
        sense = {"form_of": [{"word": "decir"}]}
        entry = {"word": "dijo", "pos": "verb", "senses": [sense, sense]}
        self.assertEqual(len(pairs(entry)), 1)

    def test_a_multiword_entry_is_skipped(self):
        entry = {"word": "sin embargo", "pos": "adv", "senses": [{"glosses": ["x"]}]}
        self.assertEqual(pairs(entry), [])

    def test_the_form_is_case_folded(self):
        entry = {
            "word": "Dijo",
            "pos": "verb",
            "senses": [{"form_of": [{"word": "decir"}]}],
        }
        self.assertEqual(pairs(entry)[0][0], "dijo")


class Extract(unittest.TestCase):
    def test_keeps_only_wanted_forms(self):
        lines = [
            json.dumps({"word": "casa", "pos": "noun", "senses": [{}]}),
            json.dumps({"word": "zapato", "pos": "noun", "senses": [{}]}),
        ]
        forms = [p[0] for p in wiktionary.extract(lines, {"casa"})]
        self.assertEqual(forms, ["casa"])

    def test_skips_a_malformed_line(self):
        lines = [
            "{not json",
            json.dumps({"word": "casa", "pos": "noun", "senses": [{}]}),
        ]
        self.assertEqual(len(list(wiktionary.extract(lines, {"casa"}))), 1)


if __name__ == "__main__":
    unittest.main()
