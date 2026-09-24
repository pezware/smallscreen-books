# AGENTS.md

A generator that builds EPUB books for a 4.3" e-ink reader: Xteink X4 Pro,
480x800, running CrossPoint Reader firmware. The first book is a Spanish
wordbook of the top 3,000 words. See `README.md` for status and licences.

## Read before you change anything

- `docs/device-constraints.md` — what the firmware actually renders, read from
  its source. Binding for any change to markup, CSS or pagination.
- `docs/plan.md` — the stages, the data contract, and the decisions already
  taken. Do not re-open a decision listed there without asking Andy.

## Commands

The toolchain is pinned in `mise.toml` (Python 3.12, uv, CMake). CI runs the
same tasks.

```sh
mise run test      # unittest, stdlib only
mise run lint      # ruff format --check + ruff check
mise run fmt       # ruff format
mise run book      # build/es-wordbook.epub
mise run build     # rebuild data/es/frequency.txt (needs the corpus in data/es/raw/)
uv run python tools/check_epub.py build/es-wordbook.epub   # structural EPUB check
```

Without mise: `python3 -m unittest discover -s tests -t tests`. Run one test
with `python3 -m unittest discover -s tests -t tests -p test_render.py`.

`mise run fit` and `mise run fit-entry` build the C++ tools in `tools/fit/`.
Both need `CROSSPOINT_ROOT` set to a crosspoint-reader checkout.

## Layout

```
src/frequency.py   corpus -> data/es/frequency.txt (+ .excluded.txt, .source.json)
src/render.py      entries -> EPUB, one XHTML file per word
src/validate.py    checks a generated definition against the book's headwords
tools/check_epub.py  structural EPUB checks (no JVM here, so no epubcheck)
tools/fit/         host build of the firmware's line breaker and parser
data/<lang>/       source of truth for book content
tests/             one test file per module
```

## Rules that are easy to break

**The runtime is stdlib only.** `pyproject.toml` has no dependencies on
purpose: a book must build from a checkout and a corpus, with no package index.
Only dev tools (ruff) go in the `dev` group. Do not add a runtime dependency.

**The device ignores most CSS, silently.** Use only the properties listed in
`docs/device-constraints.md`: no `font-size`, `color`, `line-height`,
`page-break-*` or `@font-face`. Selectors are limited to `tag`, `.class`,
`tag.class`, and comma groups of those. No descendant, child or
pseudo-class selectors.

**Every entry must read correctly with CSS off.** The reader can disable the
book's stylesheet, so structure goes in the markup and CSS only adjusts
spacing.

**A new page means a new XHTML file inside the EPUB.** The output is still one
`.epub`, but the engine ignores `page-break-*` and always starts a spine item
(a section) on a fresh page. So the archive holds one XHTML file per word, about
3,000 in the spine. The TOC has one entry per letter, not per word.

**"Fits" only means something at a stated font size.** The reader chooses the
font size. Fit is measured with `tools/fit` through the firmware's real code,
never estimated with arithmetic. `docs/device-constraints.md` explains why.
`MAX_DEFINITION_CHARS = 90` was settled that way.

**`data/es/frequency.txt` is a committed build output.** Change it only by
running `src/frequency.py` against the real corpus, and commit its
`.excluded.txt` and `.source.json` siblings with it. The
`frequency-list.yml` workflow rebuilds it from scratch and fails on any byte of
drift. Never hand-edit it.

**`validate.accept_definition` stays unimplemented.** It raises
`NotImplementedError` on purpose, because Andy owns the strictness rule. Build
around it and leave the function alone.

**Record provenance for every piece of content.** Each entry's `source` field
names where its definition and examples came from, and that attribution goes
into the built book. Do not add data from a share-alike source (such as
OpenSubtitles) without asking, because it would decide the book's licence.

**Spanish sorting is not ASCII sorting.** `ñ` is its own letter, filed after
`n`. Accents do not change a word's alphabetical position. Use
`render.sort_key` and `render.initial`, not an ad-hoc sort.

## Conventions

- Tests use `unittest` and import modules by putting `src/` on `sys.path` (see
  the top of any file in `tests/`). No pytest.
- Every module opens with a docstring that explains why it exists and what
  constraint shapes it. Comments explain reasons, not mechanics. Keep that
  density in new code.
- Commit subjects are lowercase and describe the change in plain words
  ("measure a whole entry through the device's parser"). Larger work is
  labelled by stage number ("stage 4: ...").
- Build output goes in `build/`, and downloaded corpora go in `data/**/raw/`.
  Both are gitignored.
- CI accepts only actions owned by GitHub or pezware. Use the local
  `.github/actions/setup-mise` action, not a third-party one.
