# Host build of the firmware's line breaker, so fit can be measured off-device.
#
# The firmware is a dependency, not a copy: point CROSSPOINT_ROOT at a
# crosspoint-reader checkout. Nothing is vendored here, so there is no forked
# copy of theirs to drift out of date -- only this file to update if they move
# a source.
cmake_minimum_required(VERSION 3.20)
project(fit CXX C)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(CROSSPOINT_ROOT "" CACHE PATH "Path to a crosspoint-reader checkout")
if(NOT CROSSPOINT_ROOT OR NOT EXISTS "${CROSSPOINT_ROOT}/lib/Epub")
  message(FATAL_ERROR
    "CROSSPOINT_ROOT must point at a crosspoint-reader checkout.\n"
    "  cmake -S tools/fit -B build/fit -DCROSSPOINT_ROOT=/path/to/crosspoint-reader")
endif()

add_executable(fit
  main.cpp
  ${CROSSPOINT_ROOT}/lib/Epub/Epub/ParsedText.cpp
  ${CROSSPOINT_ROOT}/lib/Epub/Epub/blocks/TextBlock.cpp
  # The real hyphenator, not a stub. Spanish is one of its supported
  # languages, and hyphenation changes where lines break -- measuring with it
  # switched off would report a page count the device never produces.
  ${CROSSPOINT_ROOT}/lib/Epub/Epub/hyphenation/Hyphenator.cpp
  ${CROSSPOINT_ROOT}/lib/Epub/Epub/hyphenation/LanguageRegistry.cpp
  ${CROSSPOINT_ROOT}/lib/Epub/Epub/hyphenation/LiangHyphenation.cpp
  ${CROSSPOINT_ROOT}/lib/Epub/Epub/hyphenation/HyphenationCommon.cpp
  ${CROSSPOINT_ROOT}/lib/EpdFont/EpdFont.cpp
  ${CROSSPOINT_ROOT}/lib/EpdFont/EpdFontFamily.cpp
  ${CROSSPOINT_ROOT}/lib/Utf8/Utf8.cpp
  ${CROSSPOINT_ROOT}/lib/MiniBidi/BidiUtils.cpp
  ${CROSSPOINT_ROOT}/lib/MiniBidi/minibidi.c
)

# The firmware's libraries include each other by bare header name, so the
# transitive set is wide and chasing it one fatal error at a time is a waste.
# Take every lib directory and its src/, and let the two that matter come
# first.
file(GLOB CROSSPOINT_LIB_DIRS "${CROSSPOINT_ROOT}/lib/*")
set(CROSSPOINT_INCLUDES "")
foreach(dir ${CROSSPOINT_LIB_DIRS})
  if(IS_DIRECTORY "${dir}")
    list(APPEND CROSSPOINT_INCLUDES "${dir}")
    if(IS_DIRECTORY "${dir}/src")
      list(APPEND CROSSPOINT_INCLUDES "${dir}/src")
    endif()
  endif()
endforeach()

target_include_directories(fit PRIVATE
  # Ours first: this directory supplies the GfxRenderer the layout code
  # includes, and it must win over the firmware's fake-metrics test double
  # further down the path.
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CROSSPOINT_ROOT}/test/chapter_html_slim_parser/stubs
  ${CROSSPOINT_ROOT}/lib
  ${CROSSPOINT_ROOT}/lib/Epub
  ${CROSSPOINT_ROOT}/lib/Epub/Epub
  ${CROSSPOINT_INCLUDES}
)
