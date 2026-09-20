// Symbols the layout and parser code references but a text-only measurement
// never reaches.
//
// Deliberately narrow. The firmware's own ParserLinkStubs.cpp additionally
// stubs the hyphenator and returns nullptr from lookupHtmlEntity, which is
// right for testing parser structure and wrong here: both change where lines
// break, and a fit measurement taken with them stubbed describes a layout the
// device does not produce. Those two are linked for real.
//
// What remains is images. A wordbook has none, and decoding one needs the
// display pipeline this tool exists to avoid.

#include <Epub/blocks/ImageBlock.h>
#include <Epub/converters/ImageDecoderFactory.h>
#include <Epub/converters/ImageToFramebufferDecoder.h>
#include <GfxRenderer.h>

ImageBlock::ImageBlock(const std::string& imagePath, const std::string& srcPath, int16_t width, int16_t height)
    : imagePath(imagePath), srcPath(srcPath), width(width), height(height) {}

bool ImageDecoderFactory::isFormatSupported(const std::string&) { return false; }
ImageToFramebufferDecoder* ImageDecoderFactory::getDecoder(const std::string&) { return nullptr; }
bool ImageToFramebufferDecoder::validateAndStoreDimensions(int64_t, int64_t, ImageDimensions&, const char*) {
  return false;
}

void ImageBlock::render(GfxRenderer&, int, int) {}
void ImageBlock::renderPlaceholder(GfxRenderer&, int, int) const {}
bool ImageBlock::needsDecode() const { return false; }
bool ImageBlock::serialize(HalFile&) { return false; }
std::unique_ptr<ImageBlock> ImageBlock::deserialize(HalFile&) { return nullptr; }
