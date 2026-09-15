# Build plan

## Decisions already taken

Andy took both on 2026-09-14. Do not re-open them without asking him.

**An entry may run to a continuation page.** When a word, its definition and
its examples do not fit one screen, the extra examples flow to a second page.
No content is dropped. Page turning becomes irregular, and that is accepted.

Consequence: the fit measurement reports a spill rate. It does not fail the
build.

**An LLM writes the definitions; Wiktionary checks them.** Definitions use a
graded register — about 12 simple Spanish words, drawn from the top 3,000. This
reads better than a raw Wiktionary gloss and stays consistent across 3,000
entries. It also needs a review pass, because a wrong definition is worse than
an awkward one.

Consequence: generation is cached and versioned, never rerun per build. Each
entry records the input hash that produced it. A reviewed entry carries
`checked: true` and is never silently regenerated.

## Data contract

One JSON object per line, in `data/<lang>/words.jsonl`. See
`data/es/words.sample.jsonl`.

```json
{"lemma": "casa", "pos": "sustantivo", "rank": 152,
 "definition": "Lugar donde vive una persona o una familia.",
 "examples": ["Mi casa esta cerca del parque."],
 "source": {"definition": "llm:v1", "examples": ["tatoeba:3456789"]},
 "checked": true}
```

`source` carries provenance for the licence note in each built book. `rank`
gives the frequency position, which also drives the vocabulary check.

## Open decision, owned by Andy

`src/validate.py:accept_definition` raises `NotImplementedError`. It decides
whether a generated definition may enter the book.

The trade-off: `unknown_words()` compares surface forms, so it flags `dice`
when only `decir` sits in the frequency list. A rule that rejects every
out-of-vocabulary word sends good definitions back to the generator in a loop.
A tolerant rule lets a few unknown words through and trusts the sentence around
them.

Leave this function alone. Build around it.

## Stages

Each stage lands in the same branch and the same pull request.

1. **Frequency list.** Fetch a Leipzig or OpenSubtitles Spanish list. Write the
   top 3,000 surface forms to `data/es/frequency.txt`.
   Done when: the file holds 3,000 lines and the checks in `src/validate.py`
   can load it.

2. **Definitions.** Generate, cache by input hash, validate, write
   `data/es/words.jsonl`.
   Done when: every entry has a definition that `accept_definition` admits, and
   a second run regenerates nothing.

3. **Examples.** Mine Tatoeba. Prefer short sentences whose other words all sit
   inside the top 3,000.
   Done when: every entry carries at least one example with its Tatoeba id.

4. **Render.** One XHTML file per word, letter-level TOC, zip, run epubcheck.
   Read `device-constraints.md` first — the CSS subset binds here.
   Done when: epubcheck passes and the book opens on the device.

5. **Measure fit.** Build the host-side page counter against the real layout
   engine. Report the spill rate.
   Done when: the tool prints how many of the 3,000 entries need two pages.

Stage 5 comes last because it tunes the character budget rather than gating the
build. Move it earlier if the spill rate turns out to matter.

## Later

French and German reuse stages 1 to 4 with different data. Poetry uses pandoc
from Markdown, not this generator. Memory cards reuse the renderer with a
second template.

An EPUB cannot remember which cards the reader failed. Spaced repetition is the
one feature here that would justify writing firmware. Do not start it.
