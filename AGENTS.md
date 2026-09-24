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
mise run headwords # map new forms to lemmas via the LLM, rebuild headwords.jsonl
mise run headwords-check  # compare with Wiktionary -> build/headwords-review.tsv
mise run definitions      # write missing or stale definitions via the LLM -> data/es/words.jsonl
mise run definitions-check  # re-validate, no LLM -> build/definitions-review.tsv
uv run python tools/pilot_definitions.py  # measure a prompt change on 50 headwords first
uv run python tools/check_epub.py build/es-wordbook.epub   # structural EPUB check
```

Without mise: `python3 -m unittest discover -s tests -t tests`. Run one test
with `python3 -m unittest discover -s tests -t tests -p test_render.py`.

`mise run fit` and `mise run fit-entry` build the C++ tools in `tools/fit/`.
Both need `CROSSPOINT_ROOT` set to a crosspoint-reader checkout.

## Layout

```
src/frequency.py   corpus -> data/es/frequency.txt, 8,000 ranked forms (+ siblings)
src/headwords.py   forms -> lemmas (LLM) -> data/es/headwords.jsonl, the 3,000 entries
src/llm.py         the only way to call an LLM: xAI broker, Anthropic API or agent files
src/wiktionary.py  Wiktionary lemma pairs, for checking only -> data/es/raw/ (local)
src/definitions.py headwords -> definitions (LLM), repaired and cached -> words.jsonl
src/render.py      entries -> EPUB, one XHTML file per word
src/validate.py    accept_definition: the rule a definition must pass
tools/check_epub.py  structural EPUB checks (no JVM here, so no epubcheck)
tools/pilot_definitions.py  a prompt change measured on 50 headwords, before 3,000
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

**`forms.jsonl` is the LLM cache, and `headwords.jsonl` is derived from it.**
Each mapping carries the hash of its form, model and prompt, so `mise run
headwords` only pays for what changed. Never hand-edit either file: a wrong
lemma is fixed in `data/es/forms.overrides.tsv`, and a test fails if
`headwords.jsonl` is not exactly what its inputs build. After any change to
the headwords, run `mise run headwords-check`: it stamps
`headwords.source.json` with the hash of the list it checked, and a test fails
until the stamp matches.

**Wiktionary data never enters the repository.** It is CC BY-SA, and
share-alike would decide the book's licence. `wiktionary.py` writes it to the
gitignored `data/**/raw/`, and the review report goes to `build/`. Only a
reviewed decision, written as an override, is committed.

**`validate.accept_definition` is Andy's rule.** It is strict on purpose, and
`checked: true` is the only way past it (`docs/plan.md`, "The definition
rule"). Do not loosen it to make a run pass; a definition it rejects goes to
review.

**`words.jsonl` is the definition cache, and a reviewer's file.** Each entry
carries the hash of what produced it, so `mise run definitions` only pays for
what changed. The only hand edits are a reviewer's: correct `definition`, and
set `checked` to `true`. Suggestions for a reviewer go in a sheet under
`data/es/review/` (`definitions.write_sheet`); the reviewer marks `ok` with `y`
on the rows they approve, and `definitions.py apply <sheet>` applies only
those. Never mark `ok` yourself. A checked entry is never regenerated. Change the
prompt in `src/definitions.py` only with a pilot run to show it helps
(`tools/pilot_definitions.py` sends the same prompt), because every changed
character regenerates all 3,000 unchecked definitions.

**Record provenance for every piece of content.** Each entry's `source` field
names where its definition and examples came from, and that attribution goes
into the built book. `render.py` turns the `source` block of each
`*.source.json` into the "Fuentes" page, and `check_epub.py` fails a book
without it; a new licensed input needs its own `source` block there. Do not add data from a share-alike source (such as
OpenSubtitles) without asking, because it would decide the book's licence.

**Spanish sorting is not ASCII sorting.** `ñ` is its own letter, filed after
`n`. Accents do not change a word's alphabetical position. Use
`render.sort_key` and `render.initial`, not an ad-hoc sort.

## Choosing the LLM

`src/llm.py` has three providers. `SMALLSCREEN_LLM` picks one, and the
`--provider` flag of `headwords.py` and `tools/pilot_definitions.py` overrides
it. `SMALLSCREEN_LLM_MODEL` overrides the provider's default model.

| Provider | Default model | Needs |
|---|---|---|
| `xai` (default) | `grok-4.20-0309-non-reasoning` | the broker socket |
| `anthropic` | `claude-opus-5` | `ANTHROPIC_API_KEY` in the shell |
| `agent` | `agent` (a label) | someone to answer the request files |

The model is part of every cache hash (`generation.input_hash`, and each
mapping's hash in `forms.jsonl`). Switching provider or model therefore
regenerates everything that command touches: `mise run headwords` with a new
model re-maps all 8,000 forms. Pick one per stage and keep it.

### xai: the broker

There is no xAI key on the devbox, and there must never be one in this repo,
in a `.env` file, or in the environment. The devbox runs a broker that holds
the key and proxies `api.x.ai`. Send requests to the unix socket
`/run/xai-broker/xai.sock` with the normal `/v1/...` path and any placeholder
`Authorization` header; the broker replaces the header and journals the call.
`GET /healthz` answers without calling upstream.

The socket path comes from `XAI_BROKER_SOCKET`, defaulting to the path above,
so a Mac can use an ssh-forwarded socket. The broker allows 60 requests a
minute, which is one more reason generation is cached and versioned
(`docs/plan.md`). Do not work around the limit by adding a second key.

### anthropic: the Claude API

`llm.py` calls `https://api.anthropic.com/v1/messages` over the standard
library, with the key read from `ANTHROPIC_API_KEY`. Export it in your shell
only. It never goes in this repo, a `.env` file, or `mise.toml`. A refusal or a
truncated answer fails the call instead of falling back to another model,
because the cache records which model wrote each entry.

### agent: a coding agent plays the model

No network and no key. Each call writes `build/llm-exchange/requests/<key>.json`
(the user message, the path of the system prompt under `systems/`, and the
answer path) and raises `llm.PendingAnswer`. Whoever plays the model, such as
Claude Code in a cloud session, writes the JSON answer to
`build/llm-exchange/answers/<key>.json`, and the same command resumes. The
answer file is the reply exactly as a model would give it: one JSON object.
Answer the request as written, without running the validator on your own
answer first, or the pilot measures the validator instead of the writer.

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
