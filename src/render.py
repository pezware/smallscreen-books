"""Builds an EPUB whose page breaks the device will actually honour.

Two constraints from docs/device-constraints.md shape everything here.

There is no `page-break-after` in this engine. One spine item is one Section
and a Section owns its pages, so a new XHTML file is the only way to start a
new page. Hence one file per word, and hence a 3,000-item spine.

The reader can switch the stylesheet off (`embeddedStyle`), and font size
belongs to the reader rather than the book. So every entry has to read
correctly with no CSS at all: the markup carries the structure, and the
stylesheet only adjusts spacing. Nothing here depends on a rule being applied.

The stylesheet stays inside the engine's subset — roughly a dozen properties,
and selectors no more complex than `tag`, `.class` or `tag.class`. Anything
else is ignored silently, which is worse than rejected, so this file does not
reach for it.
"""

from __future__ import annotations

import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

# Only properties from the engine's accepted set, and only flat selectors.
# No font-size, colour, line-height or page-break: the engine drops them
# without complaint, so writing them would be decoration for a browser that
# will never open this book.
STYLESHEET = """h1 {
  margin-top: 0;
  margin-bottom: 4px;
}

p {
  margin-top: 0;
  margin-bottom: 6px;
  text-indent: 0;
}

p.pos {
  font-style: italic;
  margin-bottom: 8px;
}

p.example {
  margin-left: 12px;
  text-indent: 0;
}
"""


@dataclass(frozen=True)
class Entry:
    """One headword, as the book renders it."""

    lemma: str
    pos: str = ""
    definition: str = ""
    examples: tuple[str, ...] = field(default_factory=tuple)
    # Disambiguates two entries that share a sort key, and keeps filenames
    # stable when the list changes.
    index: int = 0

    @property
    def filename(self) -> str:
        return f"entries/{self.sort_key}-{self.index:04d}.xhtml"

    @property
    def sort_key(self) -> str:
        return sort_key(self.lemma)


def sort_key(lemma: str) -> str:
    """Alphabetical order for a Spanish reader.

    Accents do not change a word's place in the alphabet, so they are stripped
    for ordering only. N-tilde is a separate letter that sorts after n, which
    stripping would destroy, so it is mapped to a digraph that happens to sort
    where the letter belongs.
    """
    folded = unicodedata.normalize("NFD", lemma.casefold())
    out = []
    for char in folded:
        if char == "̃" and out and out[-1] == "n":  # combining tilde on n
            out.append("z")  # 'n' + 'z' sorts after every 'n?' and before 'o'
        elif unicodedata.category(char) != "Mn":
            out.append(char)
    return "".join(out)


def initial(lemma: str) -> str:
    """The letter this entry files under, for a letter-level table of contents."""
    key = sort_key(lemma)
    return key[0].upper() if key else "#"


def entry_xhtml(entry: Entry) -> str:
    """One entry, one file, therefore one page break.

    Structure first: h1, then part of speech, definition, examples. With the
    stylesheet switched off this still reads as a heading and paragraphs.
    """
    parts = [f"    <h1>{escape(entry.lemma)}</h1>"]
    if entry.pos:
        parts.append(f'    <p class="pos">{escape(entry.pos)}</p>')
    if entry.definition:
        parts.append(f'    <p class="definition">{escape(entry.definition)}</p>')
    parts.extend(f'    <p class="example">{escape(ex)}</p>' for ex in entry.examples)
    body = "\n".join(parts)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="es" lang="es">\n'
        "  <head>\n"
        f"    <title>{escape(entry.lemma)}</title>\n"
        '    <link rel="stylesheet" type="text/css" href="../style.css"/>\n'
        "  </head>\n"
        "  <body>\n"
        f"{body}\n"
        "  </body>\n"
        "</html>\n"
    )


def nav_xhtml(entries: list[Entry]) -> str:
    """A table of contents with one entry per letter, not per word.

    docs/device-constraints.md: book.bin stores an inherited tocIndex for spine
    items that carry no TOC entry of their own, so every word still reports the
    right chapter without a 3,000-item navigation list to scroll.
    """
    seen: dict[str, Entry] = {}
    for entry in entries:
        seen.setdefault(initial(entry.lemma), entry)
    links = "\n".join(
        f'        <li><a href="{entry.filename}">{escape(letter)}</a></li>'
        for letter, entry in seen.items()
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="es" lang="es">\n'
        "  <head>\n    <title>Indice</title>\n  </head>\n"
        "  <body>\n"
        '    <nav epub:type="toc" id="toc">\n'
        "      <h1>Indice</h1>\n"
        "      <ol>\n"
        f"{links}\n"
        "      </ol>\n"
        "    </nav>\n"
        "  </body>\n"
        "</html>\n"
    )


def content_opf(entries: list[Entry], title: str, identifier: str, source: str) -> str:
    """The package document: every entry in the manifest and in the spine.

    The spine order is the reading order, and for a wordbook that is
    alphabetical rather than by frequency -- the reader looks a word up, they
    do not read from `de` to `exportaciones`.
    """
    manifest = "\n".join(
        f'    <item id="e{entry.index:04d}" href="{entry.filename}"'
        ' media-type="application/xhtml+xml"/>'
        for entry in entries
    )
    spine = "\n".join(f'    <itemref idref="e{entry.index:04d}"/>' for entry in entries)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
        ' unique-identifier="pub-id" xml:lang="es">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="pub-id">{escape(identifier)}</dc:identifier>\n'
        f"    <dc:title>{escape(title)}</dc:title>\n"
        "    <dc:language>es</dc:language>\n"
        f"    <dc:source>{escape(source)}</dc:source>\n"
        '    <meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>\n'
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"'
        ' properties="nav"/>\n'
        '    <item id="style" href="style.css" media-type="text/css"/>\n'
        f"{manifest}\n"
        "  </manifest>\n"
        "  <spine>\n"
        f"{spine}\n"
        "  </spine>\n"
        "</package>\n"
    )


def build_epub(entries: list[Entry], out_path: Path, title: str, source: str) -> Path:
    """Write the EPUB. Alphabetical order, one file per word.

    `mimetype` must be the first entry and must be stored rather than
    deflated; a reader is entitled to find it at a fixed offset, and a
    compressed one is a malformed EPUB that some readers still open, which is
    the worst kind of broken.
    """
    ordered = sorted(entries, key=lambda e: (e.sort_key, e.lemma))
    ordered = [
        Entry(e.lemma, e.pos, e.definition, e.examples, index=i)
        for i, e in enumerate(ordered)
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            zipfile.ZipInfo("mimetype"), "application/epub+zip", zipfile.ZIP_STORED
        )
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/style.css", STYLESHEET)
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml(ordered))
        zf.writestr(
            "OEBPS/content.opf",
            content_opf(ordered, title, f"urn:uuid:smallscreen-{len(ordered)}", source),
        )
        for entry in ordered:
            zf.writestr(f"OEBPS/{entry.filename}", entry_xhtml(entry))
    return out_path


# How many entries the book holds. The frequency list is longer than this,
# because merging forms into lemmas consumes forms (docs/plan.md, stage 1b).
BOOK_SIZE = 3000

# Shown until stage 2 writes definitions. Entries need no definition to test
# the spine: 3,000 sections behave the same whether or not each says anything.
PLACEHOLDER = "(sin definición)"


def entries_from_jsonl(path: Path, placeholder: str = "") -> list[Entry]:
    """Entries from a data-contract JSONL file: words.jsonl or headwords.jsonl.

    headwords.jsonl is the same contract before stage 2, lemma and part of
    speech with no definition yet, so it renders through the same path with a
    placeholder in the definition's place.
    """
    import json

    entries = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        row = json.loads(line)
        entries.append(
            Entry(
                lemma=row["lemma"],
                pos=row.get("pos", ""),
                definition=row.get("definition") or placeholder,
                examples=tuple(row.get("examples", ())),
                index=i,
            )
        )
    return entries


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--entries",
        type=Path,
        default=Path("data/es/words.jsonl"),
        help="one JSON entry per line; falls back to the headwords",
    )
    parser.add_argument(
        "--headwords", type=Path, default=Path("data/es/headwords.jsonl")
    )
    parser.add_argument("--out", type=Path, default=Path("build/es-wordbook.epub"))
    parser.add_argument("--title", default="Las 3000 palabras")
    parser.add_argument("--limit", type=int, default=BOOK_SIZE)
    args = parser.parse_args(argv)

    if args.entries.exists():
        entries = entries_from_jsonl(args.entries)
        source = str(args.entries)
    else:
        entries = entries_from_jsonl(args.headwords, PLACEHOLDER)
        source = f"{args.headwords} (no definitions yet; they are stage 2)"

    if args.limit is not None:
        entries = entries[: args.limit]

    path = build_epub(entries, args.out, args.title, source)
    size = path.stat().st_size
    print(f"{len(entries)} entries -> {path} ({size / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
