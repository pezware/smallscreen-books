"""Checks that the EPUB checker fails on books that are actually broken.

A validator nobody has seen reject anything is indistinguishable from one that
returns success unconditionally.
"""

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import check_epub  # noqa: E402

import render  # noqa: E402


class Checker(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.good = render.build_epub(
            [render.Entry("casa"), render.Entry("zona")],
            self.tmp / "good.epub",
            "T",
            "test",
        )

    def test_accepts_a_book_the_renderer_produced(self):
        self.assertEqual(check_epub.problems(self.good), [])

    def rebuilt_with(self, mimetype_compression) -> Path:
        out = self.tmp / "bad.epub"
        with zipfile.ZipFile(self.good) as src, zipfile.ZipFile(out, "w") as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == "mimetype":
                    dst.writestr(
                        zipfile.ZipInfo("mimetype"), data, mimetype_compression
                    )
                else:
                    dst.writestr(info.filename, data)
        return out

    def test_rejects_a_compressed_mimetype(self):
        found = check_epub.problems(self.rebuilt_with(zipfile.ZIP_DEFLATED))
        self.assertTrue(any("compressed" in p for p in found), found)

    def test_rejects_a_spine_item_with_no_file_behind_it(self):
        out = self.tmp / "missing.epub"
        with zipfile.ZipFile(self.good) as src, zipfile.ZipFile(out, "w") as dst:
            for info in src.infolist():
                if info.filename.startswith("OEBPS/entries/"):
                    continue  # drop every entry, keep the manifest referencing them
                dst.writestr(info, src.read(info.filename))
        found = check_epub.problems(out)
        self.assertTrue(any("missing" in p for p in found), found)

    def test_rejects_an_archive_with_no_container(self):
        out = self.tmp / "nocontainer.epub"
        with zipfile.ZipFile(self.good) as src, zipfile.ZipFile(out, "w") as dst:
            for info in src.infolist():
                if info.filename == "META-INF/container.xml":
                    continue
                dst.writestr(info, src.read(info.filename))
        self.assertTrue(any("container" in p for p in check_epub.problems(out)))


if __name__ == "__main__":
    unittest.main()
