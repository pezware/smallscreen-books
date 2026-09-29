---
name: build-smallbook
description: Build, rebuild or change a smallscreen-books EPUB (the Spanish 3,000-word wordbook for a 4.3" e-ink reader running CrossPoint, such as the Xteink X4) with this repository's generator, using a coding agent as the LLM (SMALLSCREEN_LLM=agent). Use this whenever someone in this repo asks to build the book, make or get the EPUB, put the wordbook on their reader, run the pipeline or a stage (frequency, headwords, definitions, examples, render, fit), add or fix a word, lemma, definition or example sentence, answer the files in build/llm-exchange, or asks how to make another book (another language, poetry, cards) from this repo, even if they never say "skill" or "agent".
---

# Build a smallscreen book

The generator turns word data into an EPUB with one word per page, sized for a
480x800 e-ink screen. Everything it needs to build the finished Spanish book is
already committed in `data/es/`, so **building needs no corpus, no network and
no LLM**. The corpora and an LLM are only needed to change the content.

Read `AGENTS.md` before you change anything under `src/` or `data/`. It holds
the rules that are easy to break. `docs/plan.md` explains why each stage works
the way it does.

## First, work out which job this is

| The person wants | Go to |
|---|---|
| the EPUB, or the book on their reader | [Build the book](#build-the-book) |
| a word's lemma, definition or examples changed, or a definition that went missing | [Change the content](#change-the-content), which uses the agent loop |
| more or different headwords, or a newer corpus | [Change the content](#change-the-content), whole stages |
| a book in another language, or poems or cards | [Another kind of book](#another-kind-of-book) |

If the person only wants the book, the published build may be enough:
`https://github.com/pezware/smallscreen-books/releases/download/latest/es-wordbook.epub`
is rebuilt from `main` on every change.

## Tools

The repo uses mise (`mise install`, then `mise run <task>`). Without mise,
`uv run python …`, or plain `python3 …` from the repo root, does the same,
because the generator uses the standard library only. This skill shows the
plain commands so they work either way. `mise tasks` lists the named tasks.

## Build the book

```sh
python3 src/render.py                                  # -> build/es-wordbook.epub
python3 tools/check_epub.py build/es-wordbook.epub     # structural check
```

`check_epub.py` should print `ok, 3001 spine items`: 3,000 words plus the
sources page. To put the book on the reader, upload the file through
CrossPoint's web page or WebDAV, or copy it to the SD card.

Measuring fit is optional. It needs a checkout of crosspoint-reader and cmake:

```sh
CROSSPOINT_ROOT=/path/to/crosspoint-reader mise run fit-entry   # builds build/fit/fit-entry
python3 tools/fit/fit_book.py                                   # spill count per font size
```

The committed book should measure 0 spills at sizes 12 to 16, 2 at size 18,
and 61 at size 18 with margin 40. If a content change moves those numbers,
report the change.

## The agent loop

With `SMALLSCREEN_LLM=agent`, you are the model. Each LLM call becomes a
request file, and the command stops until the answers exist:

1. Run the command with `export SMALLSCREEN_LLM=agent`. **Exit code 3 means
   "waiting for answers", not failure.** mise reports it as a failed task
   anyway.
2. List the open requests:
   `python3 .claude/skills/build-smallbook/scripts/pending.py`
3. For each request `build/llm-exchange/requests/<key>.json`:
   - Read its `system` file, which holds the instructions and the JSON shape to
     return.
   - Read its `user` text.
   - Write the reply to its `answer` path, as exactly one JSON object and
     nothing else.
4. Check the answers parse: `python3 .claude/skills/build-smallbook/scripts/pending.py --check`
5. Run the same command again. It reads the answers and moves on, and it may
   stop at the next batch or at a repair round. Repeat until it exits 0.

**Answer as the model would.** Write your best answer to the prompt as it is
written. Read the word list the prompt gives you, as a model would, but don't
run code over your draft: no `validate.py`, and no script that checks your
words against the list. The validator's rejections and the repair rounds are
how the pipeline finds weak definitions, and pre-filtering hides them
(`AGENTS.md`, "agent").

**Many requests: fan out.** Answer files are independent, so give subagents
disjoint sets of request paths, and have each one write only the answer files
it was given. Pass each subagent the system prompt text and the rule above.
Spot-check a few answers yourself before you rerun.

**The model name is part of every cache hash.** Two consequences:

- Every entry that passes through a command records `agent` as its model.
- If you switch provider in the middle of a stage, everything that command
  covers is regenerated.

Specifically:

- `src/headwords.py map` would re-map **all 19,999 cached forms**, which is
  200 requests of 100 forms each, because the cache was made with Grok. Don't
  run it to fix a few lemmas. Use `data/es/forms.overrides.tsv` instead (see
  below). Run a full re-map only if the person wants that, and tell them the
  size first.
- `src/definitions.py generate` never regenerates an entry with
  `checked: true`, and all 3,000 committed entries are checked. With the agent
  provider it therefore only writes definitions for new headwords, in requests
  of 10 words, 50 words per saved chunk, plus up to 2 repair rounds.

So a run with the agent provider also prints one line saying the other
2,997 checked entries "were made from other inputs" and are left alone. That
is expected: they were written by another model and stay as they were
reviewed.

An entry the loop writes comes out `checked: false`. It is in the book, but it
is not done until it is reviewed; see [Definitions](#definitions).

Never set `SMALLSCREEN_LLM_MODEL` to another model's name to reuse its cache.
That records answers you wrote as another model's, and provenance is a rule
here.

## Change the content

After any change, run the tests and lint before committing:

```sh
python3 -m unittest discover -s tests -t tests
uv run ruff format --check . && uv run ruff check .   # uv creates a gitignored .venv on first use
python3 src/definitions.py check --strict    # CI's stage 2 gate: every entry accepted
```

Review sheets go in `data/es/review/`, named for what they hold and the date,
such as `definitions-regenerated-2026-10-02.tsv`. Pick a new name rather than
overwriting a sheet that already exists; the sheets are the record of every
review.

### Fix a lemma, or drop a form

Add a line to `data/es/forms.overrides.tsv` (`form<TAB>lemma<TAB>pos`, or
`form<TAB>-` to drop the form). Then:

```sh
python3 src/headwords.py build
python3 src/headwords.py check        # needs data/es/raw/wiktionary-lemmas.tsv (see src/wiktionary.py)
python3 src/definitions.py sync       # words.jsonl follows the headwords; a dropped word goes to words.retired.jsonl
```

A test fails until `check` has stamped `headwords.source.json` for the new
list. The Wiktionary extract is a 1 GB download that stays local; it is
CC BY-SA and never committed. If you can't run `check`, say so; don't edit the
stamp by hand.

A headword that enters the list needs a definition and examples. Continue with
the next two sections.

### Definitions

```sh
SMALLSCREEN_LLM=agent python3 src/definitions.py generate    # agent loop; new and unchecked entries only
python3 src/definitions.py check                             # -> build/definitions-review.tsv
```

A definition must pass `validate.accept_definition`: at most 90 characters,
only words the book defines, and never the headword or one of its forms. That
rule is the owner's; never loosen it to make a run pass. The book's small
vocabulary also limits how exact a definition can be (`limpio` can't say
"dirt" if the book has no word for it). Tell the person when a definition had
to give ground.

**A definition that went missing** (lost from `words.jsonl`): look for its
approved text in the sheets under `data/es/review/` first. If you find it,
restore it through a sheet and `apply`, so it keeps its review. Otherwise
regenerate it with `generate`. Either way, the entry keeps its examples.

To review new definitions, or fix one that is rejected or wrong, write a
review sheet under `data/es/review/` with the columns
`ok lemma pos rank current suggested note`. `definitions.write_sheet` writes
one:

- `suggested` holds the text to approve. It is the same as `current` when the
  definition stands as written.
- `note` holds a short reason, such as `agent ok` or what changed.

The person marks `ok` as `y` on the rows they approve, then:

```sh
python3 src/definitions.py apply data/es/review/<sheet>.tsv                    # approved by a person
python3 src/definitions.py apply data/es/review/<sheet>.tsv --reviewer agent   # only when the person asked for an agent review
```

Don't mark `ok` yourself unless the person asks for an agent review. The
`reviewed_by` field records who approved each entry, and it has to stay true.
If their Spanish isn't strong enough to review, offer an agent review and say
it will be recorded as `agent`. Don't reword an entry marked
`reviewed_by: human` without asking.

**An agent review should come from a different agent than the writer.**
Start a fresh subagent. Give it only the sheet, the definition rule above and
the book's word list (`data/es/headwords.jsonl`). Ask it to mark `ok`, and to
write a better `suggested` text where one is needed. A writer approving its
own definitions is not a review. If you can't start a subagent, tell the
person, and let them decide whether a self-check will do. `reviewed_by: agent`
can't tell those two cases apart, so say which one happened.

### Examples

Examples are real sentences, never written by an LLM. Tatoeba comes first,
and the Leipzig news corpus is the fallback:

```sh
mkdir -p data/es/raw
curl -o data/es/raw/spa_sentences_detailed.tsv.bz2 https://downloads.tatoeba.org/exports/per_language/spa/spa_sentences_detailed.tsv.bz2
bunzip2 data/es/raw/spa_sentences_detailed.tsv.bz2
python3 src/examples.py pick          # fills entries short of two examples; reviewed entries are never refilled
python3 src/examples.py report        # -> build/examples-report.tsv
```

`pick` can match a form that carries another word's sense (`vino` from
*venir* under the noun). A reviewer chooses by sentence id in a sheet
`lemma<TAB>ids<TAB>note`, with ids like `896493` or `leipzig:584594`, and
applies it with:

```sh
python3 src/examples.py choose <sheet> --reviewer agent|human
```

To see the candidates for a lemma, call `examples.candidates()` from Python;
there is no command for it. An entry with no fitting sentence stays short and
shows in the report. Don't pad it.

`pick` and `choose` also rewrite `data/es/examples.source.json`, which holds
the Tatoeba export's digest and the contributors credited on the sources page.
Tatoeba publishes a new export every week, so a fresh download changes the
digest. Commit that file together with `words.jsonl`.

### A newer corpus or more words

Download the Leipzig corpus into `data/es/raw/`:

```sh
curl -O https://downloads.wortschatz-leipzig.de/corpora/spa_news_2011_1M.tar.gz
tar xzf spa_news_2011_1M.tar.gz -C data/es/raw/
```

Then run `python3 src/frequency.py`, followed by the steps
above in order: headwords, definitions, examples, render.

`data/es/frequency.txt` is only ever produced by `frequency.py`, together with
its `.excluded.txt` and `.source.json`; never hand-edit it. A new
`frequency.txt` brings new forms, and `headwords.py map` then sends only those
forms, unless the provider changed (see the agent loop above).

## Another kind of book

The generator is Spanish-only today. The following are hard-coded for Spanish:

- `render.py` sets `lang="es"`
- the prompts in `headwords.py` and `definitions.py` are written for Spanish
- `validate.py` folds Spanish accents and sorts `ñ` after `n`
- `examples.py` reads the `spa` Tatoeba export
- `frequency.py` reads a Spanish Leipzig corpus

French and German are planned to reuse stages 1 to 4 with new data
(`docs/plan.md`, "Later"). Poetry is planned to go through pandoc, and memory
cards through a second template.

So another language is a code change, not a build. Plan it with the person
before touching `src/`:

- which corpus and licence
- whether `--data data/<lang>` and a language parameter should thread through
  every stage
- who will review definitions in that language

Keep the constraints that make the book work on the device:

- **CSS:** use only the subset in `docs/device-constraints.md`. The reader
  silently ignores the rest.
- **Pages:** one XHTML file per page, because the engine ignores
  `page-break-*`.
- **Plain markup:** every entry must still read correctly with CSS off.
- **Licences:** no share-alike input, because it would turn the book's
  CC BY 4.0 into CC BY-SA. Any new source also needs a `source` block on the
  sources page.

## Finish

Tell the person:

- the path of the EPUB, and the `check_epub.py` result
- what changed in `data/`: counts of entries, definitions and examples, from
  the commands' own summary lines
- who reviewed the changes: the person, or an agent
- anything left open: open requests, rejected definitions, short entries

Commit with a lowercase subject in plain words, labelled by stage when it is
stage work (for example "stage 2: define the new headwords"). Commit the data
files and review sheets. Don't commit `build/`, which includes
`build/llm-exchange/`.
