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

Andy took the next three on 2026-09-23 (issues #8, #10, #5).

**A headword is a lemma, and its forms share one entry.** `dice`, `dijo` and
`decir` are one entry, `decir`. The entry's `rank` is the best rank among its
forms. Slots freed by merging go to the next words in the list, so the book
still holds 3,000 distinct lemmas. Homographs such as `vino` (noun) and `vino`
(from `venir`) are not split into separate entries.

Consequence: `data/es/frequency.txt` stays a list of surface forms, because
the vocabulary check compares surface forms. Filling 3,000 lemmas takes more
than 3,000 forms, so the book's headword list is derived from it rather than
being it.

**Every entry carries two examples.** The second example may push an entry
onto a continuation page, which the first decision already accepts. Examples
come from Tatoeba only. When Tatoeba cannot supply two, the entry is reported,
not padded with a generated sentence that has no source.

**Frequency counts only lowercase uses.** A form that survives the proper-noun
cut is ranked by its lowercase occurrences, not by its total. Place-name uses
no longer lift `china` or `granada` above real vocabulary.

## Data contract

One JSON object per line, in `data/<lang>/words.jsonl`. See
`data/es/words.sample.jsonl`.

```json
{"lemma": "decir", "pos": "verbo", "rank": 37, "forms": ["dijo", "dice", "decir"],
 "definition": "Usar palabras para dar a otra persona una idea.",
 "examples": ["¿Qué dice tu madre?", "No me dijo nada."],
 "source": {"definition": "llm:v1", "examples": ["tatoeba:3456789", "tatoeba:4567890"]},
 "generation": {"input_hash": "sha256:9f2c…", "model": "claude-sonnet-5", "prompt": "v1"},
 "checked": true}
```

`source` carries provenance for the licence note in each built book. `rank`
gives the frequency position, which also drives the vocabulary check. `forms`
lists the frequency-list forms merged into this entry, most frequent first.

`generation` is the cache identity. `input_hash` is the SHA-256 of the
canonical JSON (sorted keys, no whitespace) of everything the generator reads
for this entry: `lemma`, `pos`, `forms`, `model` and the prompt text, not just
its version label. The generator uses it this way:

- same hash: the entry is current. Skip it.
- different hash, `checked: false`: regenerate.
- different hash, `checked: true`: report it and leave it alone. A reviewed
  entry changes only when someone clears `checked`.

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

1b. **Headwords.** Map surface forms to lemmas and part of speech, merge ranks,
   and write the 3,000 headwords with their `forms`. The lemma source is not
   chosen yet, and it carries its own licence question.
   Done when: 3,000 distinct lemmas, each listing its forms, and no form is
   claimed by two entries.

2. **Definitions.** Generate, cache by `generation.input_hash`, validate, write
   `data/es/words.jsonl`.
   Done when: every entry has a definition that `accept_definition` admits, and
   a second run regenerates nothing.

3. **Examples.** Mine Tatoeba. Prefer short sentences whose other words all sit
   inside the top 3,000.
   Done when: every entry carries two examples, each with its Tatoeba id, and
   any entry Tatoeba cannot fill is listed in a report.

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
