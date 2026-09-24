"""Structural checks an EPUB must pass before anyone puts it on a device.

Not a substitute for epubcheck, which needs a JVM this box does not have. This
covers the failures that actually bite here: a mimetype that is compressed or
not first, a spine that references something the archive does not contain, and
a manifest item with no file behind it. Each of those produces a book that
opens in some readers and not others, which is harder to diagnose than a book
that opens in none.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree


def problems(path: Path) -> list[str]:
    found: list[str] = []
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        infos = zf.infolist()

        if not infos or infos[0].filename != "mimetype":
            found.append("mimetype is not the first archive entry")
        elif infos[0].compress_type != zipfile.ZIP_STORED:
            found.append("mimetype is compressed; it must be stored")
        elif zf.read("mimetype") != b"application/epub+zip":
            found.append("mimetype contents are wrong")

        if "META-INF/container.xml" not in names:
            found.append("META-INF/container.xml is missing")
            return found

        container = zf.read("META-INF/container.xml").decode("utf-8")
        match = re.search(r'full-path="([^"]+)"', container)
        if not match:
            found.append("container.xml names no rootfile")
            return found

        opf_path = match.group(1)
        if opf_path not in names:
            found.append(f"rootfile {opf_path} is not in the archive")
            return found

        opf = zf.read(opf_path).decode("utf-8")
        base = opf_path.rsplit("/", 1)[0]
        ids = dict(re.findall(r'<item id="([^"]+)"[^>]*href="([^"]+)"', opf))
        for item_id, href in ids.items():
            if f"{base}/{href}" not in names:
                found.append(f"manifest item {item_id} points at missing {href}")
        for idref in re.findall(r'<itemref idref="([^"]+)"', opf):
            if idref not in ids:
                found.append(f"spine references unknown manifest id {idref}")
        found.extend(_attribution_problems(zf, opf, base))
        if not re.search(r'properties="nav"', opf):
            found.append("no navigation document declared")
    return found


_OPF = "{http://www.idpf.org/2007/opf}"
_XHTML = "{http://www.w3.org/1999/xhtml}"


def _attribution_problems(zf: zipfile.ZipFile, opf: str, base: str) -> list[str]:
    """The corpus is CC BY: a book that lost its credit may not be shared.

    Parsed as XML rather than matched as text, so a commented-out spine entry
    or an empty page does not pass for the real thing.
    """
    try:
        package = ElementTree.fromstring(opf)
    except ElementTree.ParseError as error:
        return [f"package document is not well-formed XML: {error}"]
    items = {item.get("href"): item.get("id") for item in package.iter(f"{_OPF}item")}
    spine = {ref.get("idref") for ref in package.iter(f"{_OPF}itemref")}
    page_id = items.get("sources.xhtml")
    if page_id is None or page_id not in spine:
        return ["the attribution page is not in the spine"]
    try:
        page = ElementTree.fromstring(zf.read(f"{base}/sources.xhtml"))
    except (KeyError, ElementTree.ParseError) as error:
        return [f"the attribution page cannot be read: {error}"]
    links = [a.get("href", "") for a in page.iter(f"{_XHTML}a")]
    if not any("creativecommons.org/licenses/" in href for href in links):
        return ["the attribution page links no licence"]
    return []


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_epub.py <book.epub>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    found = problems(path)
    if found:
        print(f"{path}: {len(found)} problem(s)", file=sys.stderr)
        for problem in found:
            print(f"  {problem}", file=sys.stderr)
        return 1
    with zipfile.ZipFile(path) as zf:
        spine = zf.read(
            re.search(
                r'full-path="([^"]+)"',
                zf.read("META-INF/container.xml").decode("utf-8"),
            ).group(1)
        ).decode("utf-8")
    print(f"{path}: ok, {spine.count('<itemref ')} spine items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
