# What CrossPoint Reader renders

Read from the firmware source at commit `6c83edd`, 2026-09-14. The engine is
hand-written C++ in `lib/Epub/`. It is not a browser. Re-check this file when
the firmware moves, because every constraint here is a property of that code.

Device: Xteink X4 Pro, 480x800 pixels, 4.3 inch.

## CSS properties it honours

This is the complete set, from `lib/Epub/Epub/css/CssStyle.h`:

| Property | Accepted values |
|---|---|
| `text-align` | `justify` `left` `center` `right` |
| `font-style` | `normal` `italic` |
| `font-weight` | `normal` `bold` |
| `text-decoration` | `underline` `line-through` `none` |
| `text-indent` | length |
| `margin-top/bottom/left/right` | length |
| `padding-top/bottom/left/right` | length |
| `width` `height` | images only |
| `display` | `block` `none` |
| `direction` | `ltr` `rtl` |
| `vertical-align` | `baseline` `super` `sub` |
| `list-style-type` | `disc` `none` |

Lengths take `px`, `em`, `rem`, `pt` or `%`.

The engine ignores everything else. It has no `font-size`, no `color`, no
`background`, no `border`, no `line-height`, no `page-break-*`, no `@font-face`,
no `@import` and no media queries.

## Selectors it honours

`CssParser.cpp:690` rejects any selector containing one of `+ > [ : # ~ *` or a
space:

```cpp
constexpr std::string_view kUnsupportedSelectorChars = "+>[:#~* ";
```

So the grammar is `tag`, `.class`, `tag.class`, and comma-separated groups of
those. Descendant selectors and pseudo-classes do not reach the renderer.

## HTML tags it recognises

`a b blockquote body br div em h1 h2 h3 h4 h5 h6 hr i img li ol p ruby rt s
span strong sub sup table td th tr u ul`

## Two settings that override the book

- **The reader can switch your CSS off.** `embeddedStyle` is a user toggle
  (`src/CrossPointSettings.h:286`). Every template must stay readable without
  its stylesheet.
- **Font size belongs to the reader, not the book** (`src/ReaderFontSizes.h`).
  An entry that fills one screen at one size spills at the next size up. "Fits"
  is only ever true for a stated size.

## How a page break happens

There is no `page-break-after` in this engine.

One spine item is one `Section`, and a `Section` owns its own pages
(`lib/Epub/Epub/Section.h`, cached as `sections/*.bin`). A new XHTML file
therefore always starts on a new page.

**One XHTML file per word.** That is the whole mechanism.

### Large spine counts

`BookMetadataCache.h:80` sets `LARGE_SPINE_THRESHOLD = 400`. Above it the
engine switches to an indexed href lookup and batched size reads, so a
3,000-entry spine runs on the optimised path.

`spineCount` is a `uint16_t`, capping a book at 65,535 entries.

Nobody has measured 3,000 sections on this device yet. Expect 3,000 cache files
under `/.crosspoint/epub_<hash>/sections/` and measure the first open.

**A book to measure it with now exists**, before any content does. `mise run
book` builds `build/es-wordbook.epub`: 3,000 real headwords, one XHTML file
each, every definition a placeholder. CI builds the same file on every change
and attaches it as the `es-wordbook-epub` artifact, so the version under test
is always current.

To settle it (the one step that cannot be automated from here):

1. Download the `es-wordbook-epub` artifact, or run `mise run book`.
2. Upload it to the device over the reader's web upload page, WebDAV, OPDS or
   Calibre wireless.
3. Time the **first** open, which is when the 3,000 section caches are built,
   and a later open, which should read them back.
4. Check `/.crosspoint/epub_<hash>/sections/` holds roughly 3,000 files and
   what they cost in storage.
5. Page through a letter boundary and use the table of contents, which has one
   entry per letter rather than per word.

If first open is unusable at this spine count, one-XHTML-per-word is not
viable, and that invalidates the design -- which is exactly why this is worth
knowing before stage 2 generates 3,000 definitions.

### Keep the table of contents small

Give the TOC one entry per letter, not one per word. `docs/file-formats.md` in
the firmware shows `book.bin` stores an inherited `tocIndex` for spine entries
that carry no TOC entry of their own, so each word still reports the right
chapter without a 3,000-item navigation list.

## Measuring fit without the device

The firmware's host test suite builds with CMake (`test/README`), and
`test/chapter_html_slim_parser/` links the real **layout** classes on the host:
`ChapterHtmlSlimParser`, `ParsedText`, `Page`, `TextBlock` and `CssParser`.

A small host tool can therefore feed one entry's XHTML through the true engine
and report its page count. That turns fit into a measurement.

**Correction, read from the firmware at `6c83edd` on 2026-09-15.** An earlier
version of this file listed `GfxRenderer` and `EpdFont` among what that harness
links. Neither is true, and the difference decides whether a screenshot is
possible:

- **No host target compiles `GfxRenderer.cpp`.** The parser test includes
  `GfxRenderer.h` and stubs `ImageBlock::render` in `ParserLinkStubs.cpp`, which
  is enough to link a layout test and not enough to paint a pixel.
- **`crosspoint_test_common` carries no sources.** It is an INTERFACE library
  holding include directories and warning flags, so it pulls nothing in.
- **`EpdFont.cpp` does build on the host**, in `test/differential_rounding/` and
  `test/ligature_guard/`.

So page counting is a wiring job against an existing pattern, and a true
480x800 screenshot is new work: compiling `GfxRenderer` for the host and
writing its framebuffer out as an image. The font layer, which is the part that
looks hardest, is already proven to build.

**Measured, 2026-09-19.** The line measurer exists: `tools/fit`, built against
firmware `6c83edd`. It links the real `ParsedText` line breaker, the real
hyphenation patterns and the real NotoSerif metrics, and supplies its own
`GfxRenderer` answering from `EpdFontFamily` instead of the firmware's test
double, which invents 8 pixels per character.

The panel is 480x800. **The text viewport is not.** The reader subtracts the
hardware safe area, then `screenMargin` on every side, then a status lane at
the bottom (`EpubReaderActivity.cpp:1138`). At the firmware's own defaults --
`screenMargin` 5, status bar 19 -- that is 470x776, and `screenMargin` goes up
to 40, which takes it to 400x720.

| NotoSerif | line height | lines in 776px | lines at margin 40 |
|---|---|---|---|
| 12 | 34px | 22 | 21 |
| 14 | 40px | 19 | 18 |
| 16 | 45px | 17 | 16 |
| 18 | 51px | 15 | 14 |

Measured at the firmware's defaults, which are hyphenation **off**
(`hyphenationEnabled = 0`) and paragraph spacing **on**
(`extraParagraphSpacing = 1`), a 90-character definition takes 3 lines at size
12, 4 at 14 and 16, and 5 at 18. Reproduce with `python3 tools/fit/probe.py |
./build/fit/fit --size N`.

**What this does and does not settle about `MAX_DEFINITION_CHARS`.**

An earlier version of this file claimed the first screen "does not spill at 90
characters at any built-in size". That claim was wrong twice over, and both
errors flattered the result: it measured against the full 480x800 panel rather
than the text viewport, and it ran with hyphenation on and paragraph spacing
off, which is the opposite of the device's defaults on both counts.

Corrected, the arithmetic is close rather than comfortable. An entry is four
blocks -- headword, definition, two examples -- and `extraParagraphSpacing`
adds roughly half a line after each. At size 16 that is about 13 line
equivalents against 17: it fits. At size 18 it is about 16 against 15: **it
spills**, and raising the margin makes every size worse.

So 90 characters is not obviously wrong as a budget, and the original comment
may well be right at the largest size. What it is not is *measured*, and a
bare-paragraph measurement plus arithmetic cannot settle it either: the real
entry carries CSS margins, heading weight and `text-indent` that none of this
counts, and measuring one 90-character passage cannot falsify a claim about
definitions *longer* than 90. Settling it needs the whole entry driven through
`ChapterHtmlSlimParser`.

The screenshot is still unbuilt. It needs `GfxRenderer.cpp` compiled for the
host and its framebuffer written out; `FontDecompressor` becomes necessary
there, and it wants Arduino's `millis`/`micros`, which the metrics path does
not.

## Related device features worth using

- **StarDict lookup.** The reader looks words up from `/dictionaries/`
  (`docs/dictionary.md`). The same source data can build a dictionary, so every
  Spanish book gets these glosses. Note its stemming step handles English forms
  only; Spanish inflections need a generated `.syn` file.
- **XTC.** The native format stores pre-rendered bitmaps at 480x800
  (`lib/Xtc/Xtc/XtcTypes.h`). It gives pixel control and loses reflowable text,
  font-size choice and dictionary lookup. Consider it only for memory cards.
- **Delivery.** The device accepts books over a web upload page, WebDAV, OPDS
  and Calibre wireless.
