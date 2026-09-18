#pragma once

// A GfxRenderer that measures with the firmware's real fonts.
//
// The layout code takes a GfxRenderer and asks it for metrics: how wide is
// this word, how tall is a line, how wide is a space. It never needs to draw
// anything to decide where a line breaks. So a host tool can supply the
// metrics and skip the display driver entirely.
//
// This matters more than it sounds. The firmware ships its own test double at
// test/chapter_html_slim_parser/stubs/GfxRenderer.h, and that one answers 8
// pixels for every character, 16 for every line and 4 for a space. It is
// perfectly good for testing that a parser emits the right structure, and it
// is useless for asking whether an entry fits a screen: every measurement it
// returns is invented. A page count taken through it would look like evidence
// and be fiction.
//
// Here the answers come from EpdFontFamily, the same font layer the device
// measures with, reading the same built-in Noto data.
//
// Known limits, and they are real:
//   * The firmware's own getTextAdvanceX also does bidi reordering, Arabic
//     shaping and a CJK font fallback before measuring. None of that changes
//     Spanish, and all of it would change Arabic or Japanese. Do not reuse
//     this shim for those scripts without porting that logic.
//   * SD-card fonts and their advance tables do not exist here. Built-in
//     fonts only.

#include <EpdFontFamily.h>

#include <cstdint>
#include <deque>
#include <string>

namespace BidiUtils {
enum class BidiBaseDir : signed char { AUTO = -1, LTR = 0, RTL = 1 };
}

class GfxRenderer {
 public:
  GfxRenderer(const EpdFontFamily* family, int screenWidth, int screenHeight)
      : family_(family), screenWidth_(screenWidth), screenHeight_(screenHeight) {}

  int getScreenWidth() const { return screenWidth_; }
  int getScreenHeight() const { return screenHeight_; }

  int getTextAdvanceX(int, const char* text, EpdFontFamily::Style style) const {
    int w = 0;
    int h = 0;
    family_->getTextDimensions(text, &w, &h, style);
    return w;
  }

  int getTextWidth(int fontId, const char* text, EpdFontFamily::Style style,
                   BidiUtils::BidiBaseDir = BidiUtils::BidiBaseDir::AUTO) const {
    return getTextAdvanceX(fontId, text, style);
  }

  int getSpaceWidth(int, EpdFontFamily::Style style) const {
    const EpdGlyph* space = family_->getGlyph(' ', style);
    return space ? fp4::toPixel(space->advanceX) : 0;
  }

  int getSpaceAdvance(int fontId, uint32_t, uint32_t, EpdFontFamily::Style style) const {
    return getSpaceWidth(fontId, style);
  }

  int getKerning(int, uint32_t leftCp, uint32_t rightCp, EpdFontFamily::Style style) const {
    return family_->getKerning(leftCp, rightCp, style);
  }

  int getLineHeight(int, float compression = 1.0f) const {
    const EpdFontData* data = family_->getData(EpdFontFamily::REGULAR);
    return data ? static_cast<int>(data->advanceY * compression + 0.5f) : 0;
  }

  int getFontAscenderSize(int) const {
    const EpdFontData* data = family_->getData(EpdFontFamily::REGULAR);
    return data ? data->ascender : 0;
  }

  // Drawing is never reached by layout; these exist only to satisfy the link.
  bool isFontCacheScanning() const { return false; }
  void drawLine(int, int, int, int, int, bool) const {}
  void drawText(int, int, int, const char*, bool, EpdFontFamily::Style,
                BidiUtils::BidiBaseDir = BidiUtils::BidiBaseDir::AUTO) const {}
  bool isSdCardFont(int) const { return false; }
  void ensureSdCardFontReady(int, const std::deque<std::string>&, bool, uint8_t) const {}

 private:
  const EpdFontFamily* family_;
  int screenWidth_;
  int screenHeight_;
};
