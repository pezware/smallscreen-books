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

I have not built either tool, so I cannot report what they cost.

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
