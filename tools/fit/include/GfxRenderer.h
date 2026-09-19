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
#include <Utf8.h>

#include <BidiUtils.h>

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

  // Mirrors GfxRenderer::getTextAdvanceX (lib/GfxRenderer/GfxRenderer.cpp),
  // deliberately line for line.
  //
  // The tempting one-liner here is EpdFontFamily::getTextDimensions, and it is
  // wrong for this purpose. That measures INK: its maxX is
  // `glyphBaseX + glyph->left + glyph->width`, so it stops at the last glyph's
  // painted edge and drops that glyph's right side bearing. The renderer
  // instead ends with `widthPx += fp4::toPixel(prevAdvanceFP)` -- the full
  // final advance. Measuring ink makes every word a little narrower than it
  // really is, fits one more word per line than the device would, and reports
  // a line count that is too low. Like the includeLastLine bug before it, the
  // error flatters.
  //
  // The differential rounding matters too: the renderer snaps
  // (previous advance + current kern) to a pixel together rather than
  // separately, so that measurement and drawText agree exactly. Rounding them
  // apart drifts by a pixel per glyph pair.
  int getTextAdvanceX(int, const char* text, EpdFontFamily::Style style) const {
    uint32_t cp = 0;
    uint32_t prevCp = 0;
    int widthPx = 0;
    int32_t prevAdvanceFP = 0;  // 12.4 fixed-point
    const bool isSupSub = (style & (EpdFontFamily::SUP | EpdFontFamily::SUB)) != 0;

    while ((cp = utf8NextCodepoint(reinterpret_cast<const uint8_t**>(&text)))) {
      if (BidiUtils::isTransparentMark(cp)) continue;
      if (utf8IsCombiningMark(cp)) continue;

      cp = family_->applyLigatures(cp, text, style);

      if (prevCp != 0) {
        const int32_t kernFP = family_->getKerning(prevCp, cp, style);
        widthPx += fp4::toPixel(prevAdvanceFP + kernFP);
      }

      const EpdGlyph* glyph = family_->getGlyph(cp, style);
      prevAdvanceFP = glyph ? glyph->advanceX : 0;
      if (isSupSub) prevAdvanceFP = (prevAdvanceFP + 1) / 2;
      prevCp = cp;
    }
    widthPx += fp4::toPixel(prevAdvanceFP);  // final glyph's advance
    return widthPx;
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
