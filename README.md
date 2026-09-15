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

Early. The data contract and the definition checks exist. The generator does
not yet.

`src/validate.py:accept_definition` is unimplemented on purpose. It decides how
strict the vocabulary rule is, and Andy owns that call. See `docs/plan.md`.

## Licences

The book data comes from sources that need attribution. Record the source of
every definition and every sentence in the data file, and carry the attribution
into each built book:

- Frequency lists — Leipzig Corpora (CC BY 4.0) or OpenSubtitles (CC BY-SA 4.0)
- Example sentences — [Tatoeba](https://tatoeba.org), CC BY 2.0 FR
- Definitions checked against [Wiktionary](https://kaikki.org) (CC BY-SA)

CC BY-SA and CC BY combine awkwardly in one redistributed book. Decide the
outgoing licence before the first book leaves the device.
