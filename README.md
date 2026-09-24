# smallscreen-books

Build EPUB books that read well on a 4.3" e-ink screen.

The first book is a Spanish wordbook: the top 3,000 words, each with a short
Spanish definition and two example sentences. French and German follow from the
same generator. Poetry and memory cards reuse the renderer with a different
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

## Layout

```
data/<lang>/     word lists, definitions and examples — the source of truth
src/             the generator
docs/            device constraints and the build plan
```

## Status

Early. Stages 1 and 1b have landed. `src/frequency.py` ranks 8,000 word forms
from the corpus into `data/es/frequency.txt`, and `src/headwords.py` merges
them into 3,000 lemmas in `data/es/headwords.jsonl`: an LLM maps each form to
its lemma, and Wiktionary checks the mapping. The renderer (`src/render.py`)
builds a real EPUB from those headwords, one XHTML file per word, with a
letter-level table of contents.

Definitions and examples do not exist yet, so every entry currently reads
`(sin definición)`. That is deliberate: the 3,000-item spine is the design's
largest untested assumption, and it can be tested on the hardware before any
content is generated.

```sh
curl -O https://downloads.wortschatz-leipzig.de/corpora/spa_news_2011_1M.tar.gz
tar xzf spa_news_2011_1M.tar.gz -C data/es/raw/       # gitignored, 266 MB
python3 src/frequency.py                              # writes data/es/frequency.txt
mise run headwords                                    # LLM, cached; see below
mise run book                                         # writes build/es-wordbook.epub
python3 -m unittest discover -s tests -t tests        # stdlib only, no venv
```

The LLM defaults to Grok through the devbox's xAI broker. Set
`SMALLSCREEN_LLM=anthropic` (with `ANTHROPIC_API_KEY` in your shell) to use
Claude instead, or `SMALLSCREEN_LLM=agent` to let a coding agent answer request
files with no network at all. AGENTS.md, "Choosing the LLM", has the details.

`mise run build | test | lint | fmt` are the same commands with the pinned
toolchain. CI runs lint and test on every change; a separate scheduled job
rebuilds `frequency.txt` from the real corpus and fails if the committed
artifact has drifted from what the generator produces.

`src/validate.py:accept_definition` is unimplemented on purpose. It decides how
strict the vocabulary rule is, and Andy owns that call. See `docs/plan.md`.

## Licences

The book data comes from sources that need attribution. Record the source of
every definition and every sentence in the data file, and carry the attribution
into each built book:

- Frequency lists — Leipzig Corpora (CC BY 4.0), recorded per language in
  `data/<lang>/frequency.source.json`. Spanish uses `spa_news_2011_1M`.
  OpenSubtitles (CC BY-SA 4.0) was not used: share-alike would decide the
  outgoing licence before Andy does
- Example sentences — [Tatoeba](https://tatoeba.org), CC BY 2.0 FR
- Definitions, and the lemma of each headword, checked against
  [Wiktionary](https://kaikki.org) (CC BY-SA). It is only compared against,
  locally; no Wiktionary data is committed or put in a book

CC BY-SA and CC BY combine awkwardly in one redistributed book. Decide the
outgoing licence before the first book leaves the device.
