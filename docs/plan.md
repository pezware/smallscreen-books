# Build plan

## Decisions already taken

Andy took both on 2026-09-14. Do not re-open them without asking him.

**An entry may run to a continuation page.** When a word, its definition and
its examples do not fit one screen, the extra examples flow to a second page.
No content is dropped. Page turning becomes irregular, and that is accepted.

Consequence: the fit measurement reports a spill rate. It does not fail the
build.

**An LLM writes the definitions; Wiktionary checks them.** Definitions use a
graded register — at most 12 simple Spanish words, drawn from the book's own
headwords (amended 2026-09-24, below). This
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
still holds 3,000 distinct lemmas. Homographs are not split: a form with two
analyses, such as `vino` (noun) and `vino` (from `venir`), belongs to the entry
of its more common analysis, and only that entry lists it.

Consequence: `data/es/frequency.txt` stays a ranked list of surface forms,
and becomes the input to the ranking only. Merging means 3,000 forms yield
fewer than 3,000 lemmas, so stage 1b reads a longer ranked list and stops at
the 3,000th lemma.

Andy took one more on 2026-09-24.

**The vocabulary is the book's own headwords.** A definition may use a word
when the book has an entry for it: any headword, or any form an entry lists
(`validate.load_headword_forms`). The rule a reader can act on is "every word
in a definition can be looked up in this book". It is wider than the top 3,000
forms, which would reject a headword such as `decir` whose infinitive ranks
below its conjugations, and it makes a strict `accept_definition` workable.
A form no entry lists, such as a rare conjugation, is still unknown.

**Every entry carries two examples.** The second example may push an entry
onto a continuation page, which the first decision already accepts. Examples
come from Tatoeba only. When Tatoeba cannot supply two, the entry is reported,
not padded with a generated sentence that has no source.

**Frequency counts only lowercase uses.** A form that survives the proper-noun
cut is ranked by its total count scaled by its share of lowercase uses, not by
the total alone. Place-name uses no longer lift `china` or `granada` above real
vocabulary.

## Data contract

One JSON object per line, in `data/<lang>/words.jsonl`. See
`data/es/words.sample.jsonl`.

Shortened here: a real entry's `forms` lists every form the list holds for that
lemma.

```json
{"lemma": "decir", "pos": "verbo", "rank": 37, "forms": ["dijo", "dice", "decir"],
 "definition": "Usar palabras para dar a otra persona una idea.",
 "examples": ["¿Qué dice tu madre?", "No me dijo nada."],
 "source": {"definition": "llm:grok-4.20-0309-non-reasoning", "examples": ["tatoeba:3456789", "tatoeba:4567890"]},
 "generation": {"input_hash": "sha256:9f2c…", "model": "grok-4.20-0309-non-reasoning", "prompt": "v1", "repairs": 0},
 "checked": true}
```

`source` carries provenance for the licence note in each built book. `rank`
gives the frequency position, which also drives the vocabulary check. `forms`
lists the frequency-list forms merged into this entry, most frequent first.

`generation` is the cache identity; `repairs` counts the repair rounds the
definition needed. `input_hash` is the SHA-256 of the
canonical JSON (sorted keys, no whitespace) of everything the generator reads
for this entry: `lemma`, `pos`, `forms`, `model` and the prompt text, not just
its version label. The generator uses it this way:

- same hash: the entry is current. Skip it.
- different hash, `checked: false`: regenerate.
- different hash, `checked: true`: report it and leave it alone. A reviewed
  entry changes only when someone clears `checked`.

The hash decides only whether to call the generator. Validation is not cached:
every run re-checks every entry, cache hits included, against the current
vocabulary and `accept_definition`, because a rebuilt frequency list can make a
once-valid definition fail. A failure is reported, never silently kept.

## The definition rule

Andy took this on 2026-09-24, after a 50-word pilot against Grok
(`tools/pilot_definitions.py`).

**`accept_definition` is strict, and review is the escape hatch.** A
definition is accepted when every word is one the book defines, it uses
neither its headword nor any form the entry lists, and it fits
`MAX_DEFINITION_CHARS`. A `checked: true` entry is accepted as it stands:
someone read it. That is how a definition needing a word the book lacks, a
place name such as `España` included, gets in.

A looser rule was measured and rejected. Allowing an unlisted form of a
headword (`oye` for `oír`) would have saved about one definition in fifty, but
telling that apart from a word the book lacks needs Wiktionary at validation
time, and Wiktionary never enters the repository, so CI and a fresh checkout
could not run the check.

**A rejected definition goes back up to twice, its problem named.** The repair
prompt asks to paraphrase the missing word and keep the meaning. An earlier
prompt that said "shorter is better" bought passes by deleting meaning
(`venganza`: "Daño que se causa por daño"). A definition still rejected after
two repairs is kept and reported, not regenerated.

**Every definition is read before it counts as done.** The checker cannot see
a news sense chosen over the basic one (`formación` as a political formation),
a wrong sense (`sobre`: "posición superior sin contacto"), or a headword that
is not a word on its own (`través`). On one reading of the pilot, about one
definition in eight needed a human edit. `mise run definitions-check` writes
`build/definitions-review.tsv`, most urgent first: rejected, same word family
as the headword, repaired, then the rest.

**An agent review counts, and says so.** Andy asked on 2026-09-24 for review
agents to read the definitions, because checking 3,000 Spanish definitions by
hand is beyond his Spanish. Seven agents read all 3,000 and rewrote 455; a
rewrite was applied only if it passes `accept_definition` and the prompt's
style rules. Every entry they approved carries `reviewed_by: agent`; a
person's approval carries `reviewed_by: human`. Nationality and place words
whose country the book lacks are left for Andy, defined as "De X o de sus
habitantes": the agents' workarounds described countries instead of naming
them, and some did so badly (`sirio` by a war).

**`través` leaves the headword list.** It lives only inside *a través de*, and
every definition the pilot drew for it was wrong. It goes as an override
(`través` → `-` in `forms.overrides.tsv`), so the next lemma takes its slot;
the change needs `mise run headwords-check`, which only runs where the
Wiktionary table is. `set` is a candidate for the same treatment.

## Stages

Each stage lands in the same branch and the same pull request.

1. **Frequency list.** Fetch a Leipzig or OpenSubtitles Spanish list. Write the
   top 8,000 surface forms to `data/es/frequency.txt`, enough to fill 3,000
   lemmas after merging (about 4,800 are needed).
   Done when: the file holds 8,000 lines and the checks in `src/validate.py`
   can load it.

1b. **Headwords.** Map surface forms to lemmas and part of speech, merge ranks,
   and write the 3,000 headwords with their `forms`. It reads a ranked list
   longer than 3,000 forms, because merging consumes forms. Andy chose the
   lemma source on 2026-09-24: an LLM maps each form (`src/headwords.py`,
   through the xAI broker), and Wiktionary checks the result locally without
   ever being committed, because it is CC BY-SA. The mapping is cached per form
   in `forms.jsonl`; human corrections go in `forms.overrides.tsv`; provenance
   goes in `data/<lang>/headwords.source.json`.
   Done when: 3,000 distinct lemmas, each listing its forms, no form is claimed
   by two entries, and the lemma source is recorded.

2. **Definitions.** Generate, cache by `generation.input_hash`, validate, write
   `data/es/words.jsonl` (`src/definitions.py`). The hash leaves out the word
   list pasted into the prompt: it is the whole vocabulary, so one changed
   headword would otherwise regenerate every definition, and `check`
   re-validates every entry against the current list anyway.
   Done when: every entry has a definition that `accept_definition` admits, and
   a second run regenerates nothing. `definitions.py check --strict` exits 1
   until then; without `--strict` a rejection is review work, not a failure.

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
