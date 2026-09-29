# smallscreen-books

[![ci](https://github.com/pezware/smallscreen-books/actions/workflows/ci.yml/badge.svg)](https://github.com/pezware/smallscreen-books/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/pezware/smallscreen-books?sort=semver)](https://github.com/pezware/smallscreen-books/releases/latest)
[![book](https://github.com/pezware/smallscreen-books/actions/workflows/book-release.yml/badge.svg)](https://github.com/pezware/smallscreen-books/actions/workflows/book-release.yml)
[![code: MIT](https://img.shields.io/badge/code-MIT-blue)](LICENSE)
[![book and data: CC BY 4.0](https://img.shields.io/badge/book%20%26%20data-CC%20BY%204.0-lightgrey)](data/LICENSE)

**[Download the latest release](https://github.com/pezware/smallscreen-books/releases/latest)**
and take its `es-wordbook-<version>.epub`. Copy it to the reader over
CrossPoint's web page or WebDAV, and open it. Older editions stay on the
[releases page](https://github.com/pezware/smallscreen-books/releases). For the
newest unreleased changes, the
[development build](https://github.com/pezware/smallscreen-books/releases/download/latest/es-wordbook.epub)
is rebuilt from `main` on every change.

Build EPUB books that read well on a 4.3" e-ink screen.

The first book is a Spanish wordbook: the 3,000 most used words, each on its
own page with a short Spanish definition, written only in words the book itself
defines, and two real example sentences. French and German follow from the same
generator. Poetry and memory cards reuse the renderer with a different
template.

Target device: Xteink X4 Pro running
[CrossPoint Reader](https://github.com/crosspoint-reader/crosspoint-reader),
480x800 pixels.

## Why a generator and not an editor

The wordbook is a database, not a document. 3,000 entries in three languages
need one build command, a diff the reviewer can read, and a repeatable result.
A GUI editor gives none of those.

CrossPoint renders a small CSS subset and ignores the rest. `docs/device-constraints.md`
records what it honours, read from the firmware source. Read that file before
you write a template.

## Status

The Spanish book is complete; opening it on the device is the one step left.

| Stage | What | State |
|---|---|---|
| 1 | Rank 20,000 word forms from the Leipzig news corpus | done |
| 1b | Merge them into 3,000 headwords, ranked by the summed use of their forms | done |
| 2 | A definition for every headword, in the book's own words | done: 3,000 of 3,000 accepted and reviewed |
| 3 | Two example sentences per headword, from Tatoeba or the Leipzig corpus | done: 2,935 have two, 63 one, 2 none |
| 4 | Render one XHTML page per word; open it on the device | rendered and checked; waiting for the device |
| 5 | Measure fit through the firmware's own paginator | done: every entry fits one page at sizes 12-16; 2 spill at 18 |

`docs/plan.md` records each decision and why; `data/es/review/` holds every
review sheet that changed the data.

## Build it

```sh
curl -O https://downloads.wortschatz-leipzig.de/corpora/spa_news_2011_1M.tar.gz
tar xzf spa_news_2011_1M.tar.gz -C data/es/raw/       # gitignored, 266 MB
mise run book                                         # build/es-wordbook.epub from the committed data
mise run test                                         # stdlib unittest, no venv
```

The committed data is enough for `mise run book`; the corpus and the LLM are
only needed to change it:

```sh
mise run build              # rank the forms again: data/es/frequency.txt
mise run headwords-refresh  # map new forms to lemmas (LLM, cached), rebuild and check
mise run definitions        # define new headwords (LLM, cached): data/es/words.jsonl
mise run examples           # fill missing examples from Tatoeba and the corpus
mise run fit-entry && mise run fit-book   # pages per entry, through the firmware's parser
```

The LLM defaults to Grok through the devbox's xAI broker. Set
`SMALLSCREEN_LLM=anthropic` (with `ANTHROPIC_API_KEY` in your shell) to use
Claude instead, or `SMALLSCREEN_LLM=agent` to let a coding agent answer request
files with no network at all. AGENTS.md, "Choosing the LLM", has the details.
In Claude Code, the `build-smallbook` skill (`.claude/skills/`) runs the whole
build that way: ask it to build the book or change a word.

CI runs lint, the tests, and stage 2's gate (`definitions.py check --strict`)
on every change, builds the book and publishes it as the development build
(the `latest` tag) on every push to `main`. Pushing a `v1.2.3` tag, or running
"publish the book" by hand with a version, publishes that edition as its own
release and marks it the latest. A weekly job rebuilds `frequency.txt` from the real corpus and fails if the committed
file has drifted from what the generator produces.

## Layout

```
data/<lang>/     word lists, definitions and examples — the source of truth
src/             the generator
tools/           EPUB checks, the pilot, and the fit measurement
docs/            device constraints and the build plan
```

## Licences

- **Code**: [MIT](LICENSE).
- **Book and data**: [CC BY 4.0](data/LICENSE). Anyone may use them for any
  purpose, including commercially, with credit. That is the most open licence
  the sources allow, since they are CC BY themselves; both licences disclaim
  all warranty.

What the book is built from, each credited on its "Fuentes" page and in its
data files:

- Word frequencies and some example sentences — Leipzig Corpora Collection,
  `spa_news_2011_1M` (CC BY 4.0), recorded in `data/es/frequency.source.json`.
- Example sentences — [Tatoeba](https://tatoeba.org) (CC BY 2.0 FR), each with
  its id and contributor, recorded in `data/es/examples.source.json`. They keep
  their own licence.
- Definitions — written by an LLM and reviewed; released under CC BY 4.0 with
  the rest of the data.
- Headword lemmas were checked against [Wiktionary](https://kaikki.org)
  (CC BY-SA) locally only; no Wiktionary data is committed or put in a book.
