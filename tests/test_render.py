"""Checks the book the device will actually open."""

import contextlib
import io
import sys
import tempfile
import unittest
import unittest.mock
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import render  # noqa: E402


class SortKey(unittest.TestCase):
    def test_accents_do_not_change_alphabetical_place(self):
        self.assertEqual(render.sort_key("médico"), render.sort_key("medico"))

    def test_enye_sorts_after_every_n_word_and_before_o(self):
        # A separate letter in Spanish, not an accented n. Stripping the tilde
        # would file 'año' among the 'an-' words.
        self.assertLess(render.sort_key("anual"), render.sort_key("año"))
        self.assertLess(render.sort_key("año"), render.sort_key("aorta"))

    def test_case_is_ignored(self):
        self.assertEqual(render.sort_key("Casa"), render.sort_key("casa"))


class EntryXhtml(unittest.TestCase):
    def test_carries_structure_so_it_reads_without_the_stylesheet(self):
        # The reader can switch embedded CSS off; the markup has to stand alone.
        xhtml = render.entry_xhtml(render.Entry("casa", "sustantivo", "Un lugar."))
        self.assertIn("<h1>casa</h1>", xhtml)

    def test_escapes_markup_in_content(self):
        xhtml = render.entry_xhtml(render.Entry("a<b", definition="x & y"))
        self.assertIn("a&lt;b", xhtml)
        self.assertIn("x &amp; y", xhtml)

    def test_examples_each_get_their_own_paragraph(self):
        xhtml = render.entry_xhtml(render.Entry("casa", examples=("Uno.", "Dos.")))
        self.assertEqual(xhtml.count('class="example"'), 2)


class BuildEpub(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.entries = [render.Entry(w) for w in ("casa", "árbol", "zona", "banco")]
        self.path = render.build_epub(self.entries, self.tmp / "b.epub", "T", "test")
        self.zf = zipfile.ZipFile(self.path)

    def test_mimetype_is_first_and_stored(self):
        # A deflated mimetype is a malformed EPUB that many readers still open,
        # which is the worst kind of broken.
        info = self.zf.infolist()[0]
        self.assertEqual(info.filename, "mimetype")
        self.assertEqual(info.compress_type, zipfile.ZIP_STORED)

    def test_one_xhtml_file_per_word_because_that_is_the_page_break(self):
        opf = self.zf.read("OEBPS/content.opf").decode()
        self.assertEqual(opf.count("<itemref "), len(self.entries))

    def test_every_spine_item_exists_in_the_archive(self):
        names = set(self.zf.namelist())
        entry_files = [n for n in names if n.startswith("OEBPS/entries/")]
        self.assertEqual(len(entry_files), len(self.entries))

    def test_entries_are_alphabetical_not_frequency_ordered(self):
        opf = self.zf.read("OEBPS/content.opf").decode()
        import re

        order = re.findall(r'href="(entries/[^"]+)"', opf)
        self.assertEqual(order, sorted(order))

    def test_table_of_contents_holds_letters_not_words(self):
        nav = self.zf.read("OEBPS/nav.xhtml").decode()
        # arbol, banco, casa, zona -> A B C Z
        self.assertEqual(nav.count("<li>"), 4)


class Main(unittest.TestCase):
    def test_a_longer_frequency_list_still_builds_a_book_of_book_size(self):
        """The ranked list runs past the book, because merging forms into
        lemmas consumes them; the stub book must not grow with it."""
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        forms = tmp / "frequency.txt"
        forms.write_text("".join(f"w{n}\n" for n in range(5)), encoding="utf-8")
        out = tmp / "book.epub"
        self.enterContext(unittest.mock.patch.object(render, "BOOK_SIZE", 3))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        render.main(
            [
                "--entries",
                str(tmp / "none.jsonl"),
                "--frequency-list",
                str(forms),
                "--out",
                str(out),
            ]
        )
        with zipfile.ZipFile(out) as zf:
            opf = zf.read("OEBPS/content.opf").decode()
        self.assertEqual(opf.count("<itemref "), 3)


class StylesheetStaysInsideTheEngineSubset(unittest.TestCase):
    # The engine ignores anything outside its subset silently, so a property it
    # does not know is not a style that fails to apply -- it is a style nobody
    # notices is missing.
    ALLOWED = {
        "text-align",
        "font-style",
        "font-weight",
        "text-decoration",
        "text-indent",
        "margin-top",
        "margin-bottom",
        "margin-left",
        "margin-right",
        "padding-top",
        "padding-bottom",
        "padding-left",
        "padding-right",
        "width",
        "height",
        "display",
        "direction",
        "vertical-align",
        "list-style-type",
    }

    def test_uses_no_property_the_engine_drops(self):
        import re

        used = set(re.findall(r"^\s*([a-z-]+):", render.STYLESHEET, re.MULTILINE))
        self.assertEqual(used - self.ALLOWED, set())

    def test_uses_no_selector_the_parser_rejects(self):
        # CssParser.cpp:690 rejects any selector containing + > [ : # ~ * or a
        # space, so the grammar is tag, .class, tag.class and comma-separated
        # groups of those. A descendant selector never reaches the renderer.
        selectors = [
            chunk.split("{", 1)[0].strip()
            for chunk in render.STYLESHEET.split("}")
            if "{" in chunk
        ]
        bad = [s for s in selectors if any(c in s for c in "+>[:#~* ")]
        self.assertEqual(bad, [], f"selectors the engine rejects: {bad}")


if __name__ == "__main__":
    unittest.main()
