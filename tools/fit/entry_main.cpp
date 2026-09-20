// Measures how many pages a whole entry takes, through the device's parser.
//
// tools/fit measures a bare paragraph. A real entry is an XHTML file with a
// heading, several blocks, CSS margins, paragraph spacing and text-indent, and
// none of that is visible to a paragraph measurement. This drives the real
// ChapterHtmlSlimParser over a real file and counts the pages it emits, which
// is what the device will do when the reader opens that word.
//
// Pagination is the parser's own: it completes a page when the next line would
// cross viewportHeight (ChapterHtmlSlimParser.cpp:2157). The viewport is the
// text area, not the panel -- the reader subtracts its safe area, screenMargin
// on every side and a status lane before any of this runs.

#include <Epub/Page.h>
#include <Epub/css/CssParser.h>
#include <Epub/hyphenation/Hyphenator.h>
#include <Epub/hyphenation/LanguageRegistry.h>
#include <Epub/parsers/ChapterHtmlSlimParser.h>
#include <GfxRenderer.h>
#include <builtinFonts/notoserif_12_regular.h>
#include <builtinFonts/notoserif_14_regular.h>
#include <builtinFonts/notoserif_16_regular.h>
#include <builtinFonts/notoserif_18_regular.h>

#include <cstring>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

namespace {

const EpdFontData* fontDataForSize(const int size) {
  switch (size) {
    case 12: return &notoserif_12_regular;
    case 14: return &notoserif_14_regular;
    case 16: return &notoserif_16_regular;
    case 18: return &notoserif_18_regular;
    default: return nullptr;
  }
}

}  // namespace

int main(int argc, char** argv) {
  int size = 16;
  int screenMargin = 5;
  int statusBarHeight = 19;
  float lineCompression = 1.0f;
  bool hyphenate = false;              // CrossPointSettings.h: hyphenationEnabled = 0
  bool extraParagraphSpacing = true;   // CrossPointSettings.h: extraParagraphSpacing = 1
  bool embeddedStyle = true;
  std::string language = "es";
  std::vector<std::string> paths;

  for (int i = 1; i < argc; ++i) {
    if (std::strcmp(argv[i], "--size") == 0 && i + 1 < argc) {
      size = std::atoi(argv[++i]);
    } else if (std::strcmp(argv[i], "--margin") == 0 && i + 1 < argc) {
      screenMargin = std::atoi(argv[++i]);
    } else if (std::strcmp(argv[i], "--status-bar") == 0 && i + 1 < argc) {
      statusBarHeight = std::atoi(argv[++i]);
    } else if (std::strcmp(argv[i], "--line-compression") == 0 && i + 1 < argc) {
      lineCompression = static_cast<float>(std::atof(argv[++i]));
    } else if (std::strcmp(argv[i], "--hyphenate") == 0 && i + 1 < argc) {
      hyphenate = true;
      language = argv[++i];
    } else if (std::strcmp(argv[i], "--no-paragraph-spacing") == 0) {
      extraParagraphSpacing = false;
    } else if (std::strcmp(argv[i], "--no-stylesheet") == 0) {
      // The reader can switch embedded CSS off, and then the book must still
      // work. Measuring both is the only way to know it does.
      embeddedStyle = false;
    } else if (argv[i][0] != '-') {
      paths.emplace_back(argv[i]);
    } else {
      std::cerr << "usage: fit-entry [--size N] [--margin px] [--status-bar px]\n"
                   "                 [--line-compression f] [--hyphenate LANG]\n"
                   "                 [--no-paragraph-spacing] [--no-stylesheet] FILE...\n";
      return 2;
    }
  }

  if (paths.empty()) {
    std::cerr << "no XHTML file given\n";
    return 2;
  }

  const EpdFontData* data = fontDataForSize(size);
  if (data == nullptr) {
    std::cerr << "no built-in NotoSerif at size " << size << "\n";
    return 2;
  }
  if (hyphenate) {
    if (getLanguageHyphenatorForPrimaryTag(language) == nullptr) {
      std::cerr << "unsupported hyphenation language: " << language << "\n";
      return 2;
    }
    Hyphenator::setPreferredLanguage(language);
  }

  const EpdFont regular(data);
  const EpdFontFamily family(&regular);
  const int viewportWidth = 480 - 2 * screenMargin;
  const int viewportHeight = 800 - screenMargin - statusBarHeight;
  GfxRenderer renderer(&family, viewportWidth, viewportHeight);

  CssParser cssParser{"."};
  size_t pages = 0;
  auto measure = [&](const std::string& path) -> size_t {
    pages = 0;
    ChapterHtmlSlimParser parser{nullptr,
                               path,
                               renderer,
                               0,
                               lineCompression,
                               extraParagraphSpacing,
                               0,
                               static_cast<uint16_t>(viewportWidth),
                               static_cast<uint16_t>(viewportHeight),
                               hyphenate,
                               false,
                               [&](std::unique_ptr<Page>, uint16_t, uint16_t, uint32_t) { ++pages; },
                               embeddedStyle,
                               "",
                               "",
                               0,
                               {},
                               nullptr,
                               &cssParser};
    return parser.parseAndBuildPages() ? pages : 0;
  };

  std::cerr << "# NotoSerif " << size << "  text viewport " << viewportWidth << "x" << viewportHeight
            << (hyphenate ? "  hyphenation " + language : std::string("  hyphenation off"))
            << (extraParagraphSpacing ? "  paragraph spacing on" : "  paragraph spacing off")
            << (embeddedStyle ? "  stylesheet on" : "  stylesheet OFF") << "\n";

  size_t measured = 0;
  size_t spilled = 0;
  size_t failed = 0;
  for (const std::string& path : paths) {
    // completePageFn fires when a page fills; finishParse completes the last
    // one, so a single-page entry reports 1 rather than 0. Verified, because
    // a page counter that silently loses the final page would report every
    // entry as fitting.
    const size_t count = measure(path);
    if (count == 0) {
      std::cerr << path << ": parse failed\n";
      ++failed;
      continue;
    }
    ++measured;
    if (count > 1) ++spilled;
    std::cout << count << "\t" << path << "\n";
  }

  // Stage 5 of docs/plan.md: the spill rate tunes the character budget, it
  // does not gate the build. Continuation pages are an accepted design
  // decision, so this reports and never fails.
  if (measured > 0) {
    std::cerr << "# " << measured << " entries, " << spilled << " need a continuation page ("
              << (100.0 * static_cast<double>(spilled) / static_cast<double>(measured)) << "%)";
    if (failed > 0) std::cerr << ", " << failed << " failed to parse";
    std::cerr << "\n";
  }
  return failed > 0 ? 1 : 0;
}
