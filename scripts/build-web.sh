#!/usr/bin/env bash
# scripts/build-web.sh — build the Emscripten target into build/web.
set -euo pipefail

EMSDK_DIR="${EMSDK_DIR:-/c/emsdk}"
# shellcheck disable=SC1091
source "$EMSDK_DIR/emsdk_env.sh" >/dev/null 2>&1 || {
  echo "ERROR: could not source $EMSDK_DIR/emsdk_env.sh" >&2
  echo "Run: $EMSDK_DIR/emsdk.bat activate 4.0.9" >&2
  exit 1
}

# cmake is not on PATH in a fresh shell; resolve it the same way env-check.sh
# does, then put it on PATH so the emcmake wrapper can find it.
if command -v cmake >/dev/null 2>&1; then
  CMAKE_BIN=$(command -v cmake)
else
  CMAKE_BIN=$(ls "/c/Program Files/CMake/bin/cmake.exe" 2>/dev/null | head -1)
  [ -n "$CMAKE_BIN" ] || {
    echo "ERROR: cmake not found on PATH or in C:\\Program Files\\CMake\\bin" >&2
    exit 1
  }
  export PATH="$(dirname "$CMAKE_BIN"):$PATH"
fi

TARGET="${1:-smoke}"

case "$TARGET" in
  smoke)
    SRC="platform/web/smoke"
    BUILD="build/web"
    ;;
  *)
    echo "ERROR: unknown target '$TARGET' (known: smoke)" >&2
    exit 1
    ;;
esac

# An inherited CC shadows emcc and silently wins, producing confusing host
# errors (see docs/findings/m0-compile-matrix-harness.sh).
unset CC CXX

emcmake cmake -S "$SRC" -B "$BUILD" \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/cmake/toolchains/emscripten.cmake" \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo

cmake --build "$BUILD" --parallel

echo "built $TARGET into $BUILD"
