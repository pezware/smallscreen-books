// Measures how many lines a piece of Spanish prose takes on the device.
//
// The character budget in src/validate.py (MAX_DEFINITION_CHARS) is currently
// a guess, and stage 2 of docs/plan.md generates 3,000 cached LLM definitions
// against it. This turns the guess into a measurement, using the firmware's
// own line breaker, its own fonts and its own Spanish hyphenation patterns.
//
// "Fits" is only ever true for a stated font size, because the reader owns
// font size, not the book (docs/device-constraints.md). So the size is an
// argument, never a default assumption.

#include <Epub/ParsedText.h>
#include <GfxRenderer.h>
#include <builtinFonts/notoserif_12_regular.h>
#include <builtinFonts/notoserif_14_regular.h>
#include <builtinFonts/notoserif_16_regular.h>
#include <builtinFonts/notoserif_18_regular.h>

#include <cstring>
#include <iostream>
#include <memory>
#include <sstream>
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

std::vector<std::string> splitWords(const std::string& text) {
  std::vector<std::string> words;
  std::istringstream stream(text);
  std::string word;
  while (stream >> word) words.push_back(word);
  return words;
}

}  // namespace

int main(int argc, char** argv) {
  int size = 16;
  int viewportWidth = 480;
  bool hyphenate = true;

  for (int i = 1; i < argc; ++i) {
    if (std::strcmp(argv[i], "--size") == 0 && i + 1 < argc) {
      size = std::atoi(argv[++i]);
    } else if (std::strcmp(argv[i], "--width") == 0 && i + 1 < argc) {
      viewportWidth = std::atoi(argv[++i]);
    } else if (std::strcmp(argv[i], "--no-hyphenation") == 0) {
      hyphenate = false;
    } else {
      std::cerr << "usage: fit [--size 12|14|16|18] [--width px] [--no-hyphenation]\n"
                << "reads the text to measure on stdin, one passage per line\n";
      return 2;
    }
  }

  const EpdFontData* data = fontDataForSize(size);
  if (data == nullptr) {
    std::cerr << "no built-in NotoSerif at size " << size << "\n";
    return 2;
  }

  const EpdFont regular(data);
  const EpdFontFamily family(&regular);
  const GfxRenderer renderer(&family, viewportWidth, 800);

  // State the measurement's frame. "Fits" is meaningless without it, and a
  // reader who changes font size changes the answer.
  const int lineHeight = renderer.getLineHeight(0);
  const int linesPerScreen = lineHeight > 0 ? renderer.getScreenHeight() / lineHeight : 0;
  std::cerr << "# NotoSerif " << size << "  viewport " << viewportWidth << "x"
            << renderer.getScreenHeight() << "  line height " << lineHeight
            << "px  -> " << linesPerScreen << " lines per screen"
            << (hyphenate ? "  (hyphenation on)" : "  (hyphenation OFF)") << "\n";
  std::cout << "lines\twidth_px\ttext\n";
  std::string line;
  while (std::getline(std::cin, line)) {
    if (line.empty()) continue;

    ParsedText text(false, hyphenate);
    for (const std::string& word : splitWords(line)) {
      text.addWord(word, EpdFontFamily::REGULAR);
    }

    size_t lines = 0;
    // includeLastLine must be true. It defaults to true precisely because a
    // caller that omits it wants every line; passing false leaves the final
    // partial line unflushed and undercounts every passage by exactly one,
    // which reads as a suspiciously good fit rather than as an error.
    text.layoutAndExtractLines(
        renderer, 0, static_cast<uint16_t>(viewportWidth),
        [&](std::unique_ptr<TextBlock>, auto) { ++lines; }, true);

    int width = 0;
    int height = 0;
    family.getTextDimensions(line.c_str(), &width, &height, EpdFontFamily::REGULAR);
    std::cout << lines << "\t" << width << "\t" << line << "\n";
  }
  return 0;
}
