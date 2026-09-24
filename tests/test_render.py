"""Checks the book the device will actually open."""

import contextlib
import io
import json
import re
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


SOURCE = {
    "name": "Leipzig Corpora Collection",
    "licence": "CC BY 4.0",
    "licence_url": "https://creativecommons.org/licenses/by/4.0/",
    "attribution": "D. Goldhahn et al., LREC 2012.",
    "changes": "Modified: filtered & ranked.",
    "material": "https://example.org/spa_news.tar.gz",
}


class BuildEpub(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.entries = [render.Entry(w) for w in ("casa", "árbol", "zona", "banco")]
        self.path = render.build_epub(self.entries, self.tmp / "b.epub", "T", [SOURCE])
        self.zf = zipfile.ZipFile(self.path)

    def test_mimetype_is_first_and_stored(self):
        # A deflated mimetype is a malformed EPUB that many readers still open,
        # which is the worst kind of broken.
        info = self.zf.infolist()[0]
        self.assertEqual(info.filename, "mimetype")
        self.assertEqual(info.compress_type, zipfile.ZIP_STORED)

    def test_one_xhtml_file_per_word_because_that_is_the_page_break(self):
        opf = self.zf.read("OEBPS/content.opf").decode()
        entries = re.findall(r'<itemref idref="e\d+"', opf)
        self.assertEqual(len(entries), len(self.entries))

    def test_the_attribution_page_comes_last_in_the_spine(self):
        opf = self.zf.read("OEBPS/content.opf").decode()
        self.assertEqual(re.findall(r'<itemref idref="([^"]+)"', opf)[-1], "sources")

    def test_the_table_of_contents_reaches_the_attribution_page(self):
        nav = self.zf.read("OEBPS/nav.xhtml").decode()
        self.assertIn('href="sources.xhtml"', nav)

    def test_the_package_names_the_material_as_its_source(self):
        opf = self.zf.read("OEBPS/content.opf").decode()
        self.assertIn(f"<dc:source>{SOURCE['material']}</dc:source>", opf)

    def test_every_spine_item_exists_in_the_archive(self):
        names = set(self.zf.namelist())
        entry_files = [n for n in names if n.startswith("OEBPS/entries/")]
        self.assertEqual(len(entry_files), len(self.entries))

    def test_entries_are_alphabetical_not_frequency_ordered(self):
        opf = self.zf.read("OEBPS/content.opf").decode()
        order = re.findall(r'href="(entries/[^"]+)"', opf)
        self.assertEqual(order, sorted(order))

    def test_table_of_contents_holds_letters_not_words(self):
        nav = self.zf.read("OEBPS/nav.xhtml").decode()
        # arbol, banco, casa, zona -> A B C Z
        self.assertEqual(nav.count('href="entries/'), 4)


class SourcesPage(unittest.TestCase):
    def page(self) -> str:
        return render.sources_xhtml([SOURCE])

    def test_cites_the_work(self):
        self.assertIn("D. Goldhahn et al., LREC 2012.", self.page())

    def test_links_the_licence(self):
        self.assertIn(f'<a href="{SOURCE["licence_url"]}">CC BY 4.0</a>', self.page())

    def test_links_the_material(self):
        self.assertIn(f'href="{SOURCE["material"]}"', self.page())

    def test_says_what_was_changed(self):
        self.assertIn("Modified: filtered &amp; ranked.", self.page())

    def test_uses_only_tags_the_engine_recognises(self):
        tags = set(re.findall(r"<([a-z0-9]+)[\s>/]", self.page()))
        allowed = {"html", "head", "title", "link", "body", "h1", "h2", "p", "a"}
        self.assertEqual(tags - allowed, set())

    def test_a_quote_in_a_link_cannot_break_the_attribute(self):
        source = dict(SOURCE, material='https://example.org/a"b')
        page = render.sources_xhtml([source])
        self.assertIn('href="https://example.org/a&quot;b"', page)

    def test_a_book_without_a_source_is_refused(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with self.assertRaisesRegex(ValueError, "attribution"):
            render.build_epub([render.Entry("casa")], tmp / "b.epub", "T", [])


class Main(unittest.TestCase):
    def build(self, *rows: dict, size: int = 3000, extra_args: list[str] = ()) -> str:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        headwords = tmp / "headwords.jsonl"
        headwords.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        out = tmp / "book.epub"
        self.enterContext(unittest.mock.patch.object(render, "BOOK_SIZE", size))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        render.main(
            ["--entries", str(tmp / "none.jsonl"), "--headwords", str(headwords)]
            + ["--out", str(out)]
            + list(extra_args)
        )
        with zipfile.ZipFile(out) as zf:
            return "".join(
                zf.read(name).decode() for name in zf.namelist() if name != "mimetype"
            )

    def test_without_definitions_the_book_is_built_from_the_headwords(self):
        book = self.build({"lemma": "decir", "pos": "verbo", "forms": ["dijo"]})
        self.assertIn("decir", book)

    def test_a_headword_shows_the_placeholder_definition(self):
        book = self.build({"lemma": "decir", "pos": "verbo", "forms": ["dijo"]})
        self.assertIn(render.PLACEHOLDER, book)

    def test_an_extra_source_is_credited_alongside_the_corpus(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        extra = tmp / "tatoeba.source.json"
        extra.write_text(
            json.dumps({"source": dict(SOURCE, name="Tatoeba")}), encoding="utf-8"
        )
        book = self.build(
            {"lemma": "decir", "pos": "verbo", "forms": []},
            extra_args=["--source-json", str(extra)],
        )
        self.assertEqual(
            ("Leipzig Corpora Collection" in book, "Tatoeba" in book), (True, True)
        )

    def test_the_book_stops_at_book_size(self):
        rows = [{"lemma": f"w{n}", "pos": "", "forms": []} for n in range(5)]
        book = self.build(*rows, size=3)
        self.assertEqual(len(re.findall(r'<itemref idref="e\d+"', book)), 3)


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
